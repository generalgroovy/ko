"""Non-destructive MIDI performance recording, editing, looping, and export."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from time import monotonic

from ko2_daw.io_utils import atomic_write_bytes, atomic_write_text
from ko2_daw.midi import MidiMessage
from ko2_daw.protocol_recorder import midi_message_from_dict, midi_message_to_dict


PLAYABLE_KINDS = {"note_on", "note_off", "control_change", "program_change"}


@dataclass(frozen=True)
class PerformanceEvent:
    beat: float
    source: str
    message: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "beat": round(self.beat, 6),
            "source": self.source,
            "message": dict(self.message),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PerformanceEvent":
        message = data.get("message")
        if not isinstance(message, dict):
            raise ValueError("performance event message must be an object")
        return cls(
            beat=float(data.get("beat", 0.0)),
            source=str(data.get("source", "app")),
            message=dict(message),
        )


@dataclass
class PerformanceClip:
    name: str = "EP-133 Performance"
    bpm: float = 120.0
    loop_beats: float = 4.0
    events: list[PerformanceEvent] = field(default_factory=list)

    def validate(self) -> None:
        if not 20 <= self.bpm <= 300:
            raise ValueError("Clip BPM must be between 20 and 300.")
        if not 0.25 <= self.loop_beats <= 1024:
            raise ValueError("Loop length must be between 0.25 and 1024 beats.")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema_version": 1,
            "name": self.name,
            "bpm": self.bpm,
            "loop_beats": self.loop_beats,
            "events": [event.to_dict() for event in sorted(self.events, key=lambda item: item.beat)],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PerformanceClip":
        raw_events = data.get("events") or []
        if not isinstance(raw_events, list):
            raise ValueError("performance clip events must be an array")
        clip = cls(
            name=str(data.get("name", "EP-133 Performance")),
            bpm=float(data.get("bpm", 120.0)),
            loop_beats=float(data.get("loop_beats", 4.0)),
            events=[PerformanceEvent.from_dict(event) for event in raw_events if isinstance(event, dict)],
        )
        clip.validate()
        clip.events.sort(key=lambda item: item.beat)
        return clip


class PerformanceRecorder:
    """Beat-based recorder with quantize and bounded undo/redo history."""

    def __init__(self, clip: PerformanceClip | None = None, *, history_limit: int = 32):
        self.clip = clip or PerformanceClip()
        self.history_limit = max(1, int(history_limit))
        self.recording = False
        self.overdub = False
        self._started_at = 0.0
        self._undo: list[list[PerformanceEvent]] = []
        self._redo: list[list[PerformanceEvent]] = []

    def start(self, *, bpm: float | None = None, overdub: bool = False, now: float | None = None) -> None:
        if bpm is not None:
            self.clip.bpm = float(bpm)
        self.clip.validate()
        self._push_undo()
        if not overdub:
            self.clip.events.clear()
        self.overdub = bool(overdub)
        self.recording = True
        self._started_at = monotonic() if now is None else float(now)

    def stop(self) -> None:
        self.recording = False
        self.overdub = False
        self.clip.events.sort(key=lambda item: item.beat)

    def record(
        self,
        message: MidiMessage,
        source: str,
        *,
        now: float | None = None,
    ) -> PerformanceEvent | None:
        if not self.recording or message.kind not in PLAYABLE_KINDS:
            return None
        current = monotonic() if now is None else float(now)
        elapsed = max(0.0, current - self._started_at)
        beat = elapsed * self.clip.bpm / 60.0
        if self.clip.loop_beats > 0:
            beat %= self.clip.loop_beats
        event = PerformanceEvent(
            beat=round(beat, 6),
            source=str(source),
            message=midi_message_to_dict(message),
        )
        self.clip.events.append(event)
        return event

    def clear(self) -> None:
        self._push_undo()
        self.clip.events.clear()

    def quantize(self, division: int = 16, *, strength: float = 1.0) -> None:
        if division not in {1, 2, 4, 8, 16, 32, 64}:
            raise ValueError("Quantize division must be 1, 2, 4, 8, 16, 32, or 64.")
        if not 0 <= strength <= 1:
            raise ValueError("Quantize strength must be between 0 and 1.")
        self._push_undo()
        grid_beats = 4.0 / division
        quantized: list[PerformanceEvent] = []
        for event in self.clip.events:
            target = round(event.beat / grid_beats) * grid_beats
            beat = event.beat + ((target - event.beat) * strength)
            if self.clip.loop_beats > 0:
                beat %= self.clip.loop_beats
            quantized.append(
                PerformanceEvent(
                    beat=round(beat, 6),
                    source=event.source,
                    message=dict(event.message),
                )
            )
        self.clip.events = sorted(quantized, key=lambda item: item.beat)

    def set_loop_beats(self, beats: float) -> None:
        value = float(beats)
        if not 0.25 <= value <= 1024:
            raise ValueError("Loop length must be between 0.25 and 1024 beats.")
        self._push_undo()
        self.clip.loop_beats = value
        self.clip.events = [
            PerformanceEvent(event.beat % value, event.source, dict(event.message))
            for event in self.clip.events
        ]
        self.clip.events.sort(key=lambda item: item.beat)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._clone_events(self.clip.events))
        self.clip.events = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._clone_events(self.clip.events))
        self.clip.events = self._redo.pop()
        return True

    def playback_events(self) -> list[tuple[float, MidiMessage]]:
        seconds_per_beat = 60.0 / self.clip.bpm
        playable: list[tuple[float, MidiMessage]] = []
        for event in sorted(self.clip.events, key=lambda item: item.beat):
            message = midi_message_from_dict(event.message)
            if message is not None and message.kind in PLAYABLE_KINDS:
                playable.append((event.beat * seconds_per_beat, message))
        return playable

    def save(self, path: str | Path) -> Path:
        payload = json.dumps(self.clip.to_dict(), indent=2, sort_keys=True) + "\n"
        return atomic_write_text(path, payload)

    @classmethod
    def load(cls, path: str | Path) -> "PerformanceRecorder":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("performance clip must be a JSON object")
        return cls(PerformanceClip.from_dict(raw))

    def export_midi(self, path: str | Path, *, ticks_per_beat: int = 480) -> Path:
        if not 24 <= ticks_per_beat <= 9600:
            raise ValueError("ticks_per_beat must be between 24 and 9600.")
        track = bytearray()
        tempo = round(60_000_000 / self.clip.bpm)
        track.extend(b"\x00\xff\x51\x03")
        track.extend(int(tempo).to_bytes(3, "big"))
        last_tick = 0
        for event in sorted(self.clip.events, key=lambda item: item.beat):
            message = midi_message_from_dict(event.message)
            encoded = _encode_channel_message(message)
            if not encoded:
                continue
            tick = max(last_tick, round(event.beat * ticks_per_beat))
            track.extend(_variable_length(tick - last_tick))
            track.extend(encoded)
            last_tick = tick
        track.extend(b"\x00\xff\x2f\x00")
        header = b"MThd" + (6).to_bytes(4, "big") + (0).to_bytes(2, "big") + (1).to_bytes(2, "big")
        header += int(ticks_per_beat).to_bytes(2, "big")
        midi = header + b"MTrk" + len(track).to_bytes(4, "big") + bytes(track)
        return atomic_write_bytes(path, midi)

    def _push_undo(self) -> None:
        self._undo.append(self._clone_events(self.clip.events))
        self._undo = self._undo[-self.history_limit :]
        self._redo.clear()

    @staticmethod
    def _clone_events(events: list[PerformanceEvent]) -> list[PerformanceEvent]:
        return [
            PerformanceEvent(event.beat, event.source, dict(event.message))
            for event in events
        ]


def _encode_channel_message(message: MidiMessage | None) -> bytes:
    if message is None:
        return b""
    channel = int(message.channel or 0) & 0x0F
    if message.kind == "note_on":
        return bytes([0x90 | channel, int(message.note or 0) & 0x7F, int(message.velocity or 0) & 0x7F])
    if message.kind == "note_off":
        return bytes([0x80 | channel, int(message.note or 0) & 0x7F, int(message.velocity or 0) & 0x7F])
    if message.kind == "control_change":
        return bytes([0xB0 | channel, int(message.control or 0) & 0x7F, int(message.value or 0) & 0x7F])
    if message.kind == "program_change":
        return bytes([0xC0 | channel, int(message.program or 0) & 0x7F])
    return b""


def _variable_length(value: int) -> bytes:
    number = max(0, int(value))
    buffer = [number & 0x7F]
    while number >> 7:
        number >>= 7
        buffer.append((number & 0x7F) | 0x80)
    return bytes(reversed(buffer))
