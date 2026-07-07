"""Protocol JSONL recording and replay helpers.

This module is hardware-free by design. It serializes visible MIDI/SysEx-like
message objects and can replay them into any observer callable for GUI/state
regression tests.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Iterable

from ko2_daw.io_utils import atomic_write_text
from ko2_daw.midi import MidiMessage


@dataclass(frozen=True)
class ProtocolEvent:
    """One recorded protocol event."""

    elapsed_sec: float
    direction: str
    kind: str
    message: dict[str, object]
    raw: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "elapsed_sec": self.elapsed_sec,
            "direction": self.direction,
            "kind": self.kind,
            "message": self.message,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ProtocolEvent":
        message = data.get("message")
        if not isinstance(message, dict):
            raise ValueError("protocol event message must be an object")
        return cls(
            elapsed_sec=float(data.get("elapsed_sec", 0.0)),
            direction=str(data.get("direction", "unknown")),
            kind=str(data.get("kind", message.get("kind", "unknown"))),
            message=dict(message),
            raw=str(data.get("raw", "")),
        )


class ProtocolRecorder:
    """In-memory recorder that can flush JSONL atomically."""

    def __init__(self) -> None:
        self.started_at = monotonic()
        self.events: list[ProtocolEvent] = []

    def record(self, direction: str, message: MidiMessage | dict[str, object], raw: str = "") -> None:
        payload = midi_message_to_dict(message) if isinstance(message, MidiMessage) else dict(message)
        self.events.append(
            ProtocolEvent(
                elapsed_sec=round(monotonic() - self.started_at, 6),
                direction=direction,
                kind=str(payload.get("kind", "unknown")),
                message=payload,
                raw=raw,
            )
        )

    def to_jsonl(self) -> str:
        return "\n".join(json.dumps(event.to_dict(), sort_keys=True) for event in self.events) + "\n"

    def save(self, path: str | Path) -> Path:
        return atomic_write_text(path, self.to_jsonl())


class ProtocolReplay:
    """Replay recorded protocol events into an observer callable."""

    def __init__(self, events: Iterable[ProtocolEvent]) -> None:
        self.events = list(events)

    @classmethod
    def load(cls, path: str | Path) -> "ProtocolReplay":
        return cls(load_protocol_jsonl(path))

    def replay(self, observer: Callable[[ProtocolEvent, MidiMessage | None], None]) -> int:
        count = 0
        for event in self.events:
            observer(event, midi_message_from_dict(event.message))
            count += 1
        return count


def midi_message_to_dict(message: MidiMessage) -> dict[str, object]:
    return {
        "kind": message.kind,
        "note": message.note,
        "velocity": message.velocity,
        "control": message.control,
        "value": message.value,
        "program": message.program,
        "channel": message.channel,
        "data": list(message.data or []),
    }


def midi_message_from_dict(data: dict[str, object]) -> MidiMessage | None:
    kind = str(data.get("kind", ""))
    channel = int(data.get("channel") or 0)
    if kind == "note_on":
        return MidiMessage.note_on(int(data.get("note") or 0), int(data.get("velocity") or 0), channel=channel)
    if kind == "note_off":
        return MidiMessage.note_off(
            int(data.get("note") or 0),
            velocity=int(data.get("velocity") or 0),
            channel=channel,
        )
    if kind == "control_change":
        return MidiMessage.control_change(int(data.get("control") or 0), int(data.get("value") or 0), channel=channel)
    if kind == "program_change":
        return MidiMessage.program_change(int(data.get("program") or 0), channel=channel)
    if kind == "start":
        return MidiMessage.start()
    if kind == "continue":
        return MidiMessage.continue_()
    if kind == "stop":
        return MidiMessage.stop()
    if kind == "clock":
        return MidiMessage.clock()
    if kind == "sysex":
        raw_data = data.get("data") or []
        if isinstance(raw_data, list):
            return MidiMessage.sysex(bytes(int(value) & 0xFF for value in raw_data))
    return None


def load_protocol_jsonl(path: str | Path) -> list[ProtocolEvent]:
    events: list[ProtocolEvent] = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {line_number}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"invalid JSONL at line {line_number}: expected object")
        events.append(ProtocolEvent.from_dict(raw))
    return events
