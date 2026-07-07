"""Scene/clip arranger and synchronized MIDI playback for the EP-133."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import threading
from time import monotonic, perf_counter
from typing import Callable

from ko2_daw.io_utils import atomic_write_bytes, atomic_write_text
from ko2_daw.midi import MidiMessage
from ko2_daw.performance import PerformanceClip
from ko2_daw.protocol_recorder import midi_message_from_dict


GROUPS = ("A", "B", "C", "D")
GROUP_BASE_NOTES = {"A": 36, "B": 48, "C": 60, "D": 72}
DEFAULT_SCENES = 8
STEPS_PER_BEAT = 4


@dataclass(frozen=True)
class ClipNote:
    beat: float
    duration: float
    note: int
    velocity: int = 96
    probability: float = 1.0

    def validate(self, length_beats: float) -> None:
        if not 0 <= self.beat < length_beats:
            raise ValueError("Clip note beat must fall inside the clip.")
        if not 0.01 <= self.duration <= 1024:
            raise ValueError("Clip note duration must be between 0.01 and 1024 beats.")
        if not 0 <= self.note <= 127:
            raise ValueError("Clip note must be between 0 and 127.")
        if not 1 <= self.velocity <= 127:
            raise ValueError("Clip note velocity must be between 1 and 127.")
        if not 0 <= self.probability <= 1:
            raise ValueError("Clip note probability must be between 0 and 1.")


@dataclass(frozen=True)
class ClipControl:
    beat: float
    control: int
    value: int

    def validate(self, length_beats: float) -> None:
        if not 0 <= self.beat < length_beats:
            raise ValueError("Clip control beat must fall inside the clip.")
        if not 0 <= self.control <= 127 or not 0 <= self.value <= 127:
            raise ValueError("Clip control and value must be between 0 and 127.")


@dataclass
class MidiClip:
    clip_id: str
    name: str
    group: str
    length_beats: float = 4.0
    notes: list[ClipNote] = field(default_factory=list)
    controls: list[ClipControl] = field(default_factory=list)

    def validate(self) -> None:
        if self.group not in GROUPS:
            raise ValueError("Clip group must be A, B, C, or D.")
        if not 0.25 <= self.length_beats <= 1024:
            raise ValueError("Clip length must be between 0.25 and 1024 beats.")
        for note in self.notes:
            note.validate(self.length_beats)
        for control in self.controls:
            control.validate(self.length_beats)

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "clip_id": self.clip_id,
            "name": self.name,
            "group": self.group,
            "length_beats": self.length_beats,
            "notes": [asdict(note) for note in sorted(self.notes, key=lambda item: item.beat)],
            "controls": [
                asdict(control) for control in sorted(self.controls, key=lambda item: item.beat)
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "MidiClip":
        clip = cls(
            clip_id=str(data.get("clip_id", "")),
            name=str(data.get("name", "Clip")),
            group=str(data.get("group", "A")),
            length_beats=float(data.get("length_beats", 4.0)),
            notes=[
                ClipNote(**item)
                for item in data.get("notes", [])
                if isinstance(item, dict)
            ],
            controls=[
                ClipControl(**item)
                for item in data.get("controls", [])
                if isinstance(item, dict)
            ],
        )
        clip.validate()
        return clip


@dataclass
class ArrangerTrack:
    group: str
    name: str
    channel: int = 0
    muted: bool = False
    solo: bool = False
    armed: bool = False
    velocity_scale: float = 1.0
    transpose: int = 0

    def validate(self) -> None:
        if self.group not in GROUPS:
            raise ValueError("Track group must be A, B, C, or D.")
        if not 0 <= self.channel <= 15:
            raise ValueError("Track channel must be between 0 and 15.")
        if not 0 <= self.velocity_scale <= 2:
            raise ValueError("Track velocity scale must be between 0 and 2.")
        if not -48 <= self.transpose <= 48:
            raise ValueError("Track transpose must be between -48 and 48 semitones.")


@dataclass
class ArrangerScene:
    scene_id: str
    name: str
    clip_ids: dict[str, str] = field(default_factory=dict)


@dataclass
class SongSection:
    scene_id: str
    repeats: int = 1

    def validate(self) -> None:
        if not 1 <= self.repeats <= 999:
            raise ValueError("Song section repeats must be between 1 and 999.")


@dataclass(frozen=True)
class ScheduledMidiEvent:
    beat: float
    priority: int
    track: str
    clip_id: str
    message: MidiMessage


@dataclass
class ArrangerProject:
    name: str = "EP-133 Arrangement"
    bpm: float = 120.0
    beats_per_bar: int = 4
    swing_percent: float = 50.0
    seed: int = 133
    tracks: dict[str, ArrangerTrack] = field(default_factory=dict)
    clips: dict[str, MidiClip] = field(default_factory=dict)
    scenes: list[ArrangerScene] = field(default_factory=list)
    song: list[SongSection] = field(default_factory=list)

    def validate(self) -> None:
        if not 20 <= self.bpm <= 300:
            raise ValueError("Arranger BPM must be between 20 and 300.")
        if not 1 <= self.beats_per_bar <= 16:
            raise ValueError("Beats per bar must be between 1 and 16.")
        if not 50 <= self.swing_percent <= 75:
            raise ValueError("Swing must be between 50 and 75 percent.")
        for group in GROUPS:
            if group not in self.tracks:
                raise ValueError(f"Arranger project is missing track {group}.")
            self.tracks[group].validate()
        for clip in self.clips.values():
            clip.validate()
        scene_ids = {scene.scene_id for scene in self.scenes}
        for scene in self.scenes:
            for group, clip_id in scene.clip_ids.items():
                if group not in GROUPS or clip_id not in self.clips:
                    raise ValueError(f"Scene {scene.scene_id} references an invalid clip.")
        for section in self.song:
            section.validate()
            if section.scene_id not in scene_ids:
                raise ValueError(f"Song references unknown scene {section.scene_id}.")

    def scene(self, scene_id: str) -> ArrangerScene:
        for scene in self.scenes:
            if scene.scene_id == scene_id:
                return scene
        raise KeyError(f"Unknown scene {scene_id}.")

    def scene_length(self, scene_id: str) -> float:
        scene = self.scene(scene_id)
        lengths = [
            self.clips[clip_id].length_beats
            for clip_id in scene.clip_ids.values()
            if clip_id in self.clips
        ]
        return max(lengths, default=float(self.beats_per_bar))

    def total_song_beats(self) -> float:
        return sum(self.scene_length(item.scene_id) * item.repeats for item in self.song)

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema": "ko2-daw.arranger.v1",
            "name": self.name,
            "bpm": self.bpm,
            "beats_per_bar": self.beats_per_bar,
            "swing_percent": self.swing_percent,
            "seed": self.seed,
            "tracks": {group: asdict(track) for group, track in self.tracks.items()},
            "clips": {clip_id: clip.to_dict() for clip_id, clip in self.clips.items()},
            "scenes": [asdict(scene) for scene in self.scenes],
            "song": [asdict(section) for section in self.song],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArrangerProject":
        tracks_data = data.get("tracks") or {}
        clips_data = data.get("clips") or {}
        project = cls(
            name=str(data.get("name", "EP-133 Arrangement")),
            bpm=float(data.get("bpm", 120.0)),
            beats_per_bar=int(data.get("beats_per_bar", 4)),
            swing_percent=float(data.get("swing_percent", 50.0)),
            seed=int(data.get("seed", 133)),
            tracks={
                str(group): ArrangerTrack(**track)
                for group, track in tracks_data.items()
                if isinstance(track, dict)
            },
            clips={
                str(clip_id): MidiClip.from_dict(clip)
                for clip_id, clip in clips_data.items()
                if isinstance(clip, dict)
            },
            scenes=[
                ArrangerScene(
                    scene_id=str(scene.get("scene_id", "")),
                    name=str(scene.get("name", "Scene")),
                    clip_ids={
                        str(group): str(clip_id)
                        for group, clip_id in (scene.get("clip_ids") or {}).items()
                    },
                )
                for scene in data.get("scenes", [])
                if isinstance(scene, dict)
            ],
            song=[
                SongSection(
                    scene_id=str(section.get("scene_id", "")),
                    repeats=int(section.get("repeats", 1)),
                )
                for section in data.get("song", [])
                if isinstance(section, dict)
            ],
        )
        project.validate()
        return project


def default_arranger_project(scene_count: int = DEFAULT_SCENES) -> ArrangerProject:
    if not 1 <= scene_count <= 64:
        raise ValueError("scene_count must be between 1 and 64.")
    tracks = {
        group: ArrangerTrack(group=group, name=f"Group {group}", armed=group == "A")
        for group in GROUPS
    }
    clips: dict[str, MidiClip] = {}
    scenes: list[ArrangerScene] = []
    for index in range(1, scene_count + 1):
        clip_ids: dict[str, str] = {}
        for group in GROUPS:
            clip_id = f"S{index:02d}-{group}"
            clips[clip_id] = MidiClip(
                clip_id=clip_id,
                name=f"Scene {index} / {group}",
                group=group,
            )
            clip_ids[group] = clip_id
        scenes.append(ArrangerScene(f"S{index:02d}", f"Scene {index}", clip_ids))
    project = ArrangerProject(
        tracks=tracks,
        clips=clips,
        scenes=scenes,
        song=[SongSection(scenes[0].scene_id)],
    )
    project.validate()
    return project


class ArrangerSession:
    """Mutable arranger editor with project-wide undo and redo."""

    def __init__(self, project: ArrangerProject | None = None, *, history_limit: int = 64):
        self.project = project or default_arranger_project()
        self.history_limit = max(1, int(history_limit))
        self.selected_scene_id = self.project.scenes[0].scene_id
        self.selected_group = "A"
        self._undo: list[dict[str, object]] = []
        self._redo: list[dict[str, object]] = []

    @property
    def selected_clip(self) -> MidiClip:
        scene = self.project.scene(self.selected_scene_id)
        return self.project.clips[scene.clip_ids[self.selected_group]]

    def checkpoint(self) -> None:
        self._undo.append(self.project.to_dict())
        self._undo = self._undo[-self.history_limit :]
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.project.to_dict())
        self.project = ArrangerProject.from_dict(self._undo.pop())
        self._repair_selection()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.project.to_dict())
        self.project = ArrangerProject.from_dict(self._redo.pop())
        self._repair_selection()
        return True

    def select(self, scene_id: str, group: str) -> None:
        self.project.scene(scene_id)
        if group not in GROUPS:
            raise ValueError("Group must be A, B, C, or D.")
        self.selected_scene_id = scene_id
        self.selected_group = group

    def toggle_step(
        self,
        step: int,
        pad: int,
        *,
        steps: int = 16,
        velocity: int = 96,
        duration_steps: float = 0.9,
        probability: float = 1.0,
    ) -> bool:
        if steps not in {4, 8, 16, 32, 64, 128}:
            raise ValueError("Steps must be 4, 8, 16, 32, 64, or 128.")
        if not 0 <= step < steps:
            raise ValueError("Step falls outside the clip.")
        if not 0 <= pad < 12:
            raise ValueError("Pad must be between 0 and 11.")
        if not 0 < duration_steps <= 16:
            raise ValueError("Duration steps must be greater than 0 and at most 16.")
        clip = self.selected_clip
        self.checkpoint()
        clip.length_beats = steps / STEPS_PER_BEAT
        beat = step / STEPS_PER_BEAT
        note = GROUP_BASE_NOTES[clip.group] + pad
        for index, existing in enumerate(clip.notes):
            if existing.note == note and abs(existing.beat - beat) < 1e-6:
                clip.notes.pop(index)
                return False
        new_note = ClipNote(
            beat=beat,
            duration=duration_steps / STEPS_PER_BEAT,
            note=note,
            velocity=int(velocity),
            probability=float(probability),
        )
        new_note.validate(clip.length_beats)
        clip.notes.append(new_note)
        clip.notes.sort(key=lambda item: (item.beat, item.note))
        return True

    def clear_clip(self) -> None:
        self.checkpoint()
        self.selected_clip.notes.clear()
        self.selected_clip.controls.clear()

    def set_clip_steps(self, steps: int) -> None:
        if steps not in {4, 8, 16, 32, 64, 128}:
            raise ValueError("Steps must be 4, 8, 16, 32, 64, or 128.")
        self.checkpoint()
        length = steps / STEPS_PER_BEAT
        clip = self.selected_clip
        clip.length_beats = length
        clip.notes = [
            ClipNote(
                beat=note.beat % length,
                duration=min(note.duration, length),
                note=note.note,
                velocity=note.velocity,
                probability=note.probability,
            )
            for note in clip.notes
        ]
        clip.controls = [
            ClipControl(control.beat % length, control.control, control.value)
            for control in clip.controls
        ]

    def quantize_clip(self, division: int = 16, strength: float = 1.0) -> None:
        if division not in {4, 8, 16, 32, 64}:
            raise ValueError("Quantize division must be 4, 8, 16, 32, or 64.")
        if not 0 <= strength <= 1:
            raise ValueError("Quantize strength must be between 0 and 1.")
        self.checkpoint()
        grid = 4.0 / division
        clip = self.selected_clip
        clip.notes = [
            ClipNote(
                beat=(note.beat + (round(note.beat / grid) * grid - note.beat) * strength)
                % clip.length_beats,
                duration=note.duration,
                note=note.note,
                velocity=note.velocity,
                probability=note.probability,
            )
            for note in clip.notes
        ]
        clip.notes.sort(key=lambda item: (item.beat, item.note))

    def add_control(self, beat: float, control: int, value: int) -> None:
        clip = self.selected_clip
        point = ClipControl(float(beat) % clip.length_beats, int(control), int(value))
        point.validate(clip.length_beats)
        self.checkpoint()
        clip.controls = [
            item
            for item in clip.controls
            if not (item.control == point.control and abs(item.beat - point.beat) < 1e-6)
        ]
        clip.controls.append(point)
        clip.controls.sort(key=lambda item: (item.beat, item.control))

    def remove_control(self, index: int) -> None:
        clip = self.selected_clip
        if not 0 <= index < len(clip.controls):
            raise IndexError("Clip control index is out of range.")
        self.checkpoint()
        clip.controls.pop(index)

    def set_track(
        self,
        group: str,
        *,
        muted: bool | None = None,
        solo: bool | None = None,
        armed: bool | None = None,
        velocity_scale: float | None = None,
        transpose: int | None = None,
    ) -> None:
        track = self.project.tracks[group]
        self.checkpoint()
        if muted is not None:
            track.muted = bool(muted)
        if solo is not None:
            track.solo = bool(solo)
        if armed is not None:
            track.armed = bool(armed)
        if velocity_scale is not None:
            track.velocity_scale = float(velocity_scale)
        if transpose is not None:
            track.transpose = int(transpose)
        track.validate()

    def append_song_section(self, scene_id: str, repeats: int = 1) -> None:
        self.project.scene(scene_id)
        section = SongSection(scene_id, int(repeats))
        section.validate()
        self.checkpoint()
        self.project.song.append(section)

    def remove_song_section(self, index: int) -> None:
        if not 0 <= index < len(self.project.song):
            raise IndexError("Song section index is out of range.")
        self.checkpoint()
        self.project.song.pop(index)

    def move_song_section(self, index: int, offset: int) -> int:
        target = index + offset
        if not 0 <= index < len(self.project.song) or not 0 <= target < len(self.project.song):
            return index
        self.checkpoint()
        item = self.project.song.pop(index)
        self.project.song.insert(target, item)
        return target

    def import_performance(self, performance: PerformanceClip, scene_id: str | None = None) -> int:
        target_scene = scene_id or self.selected_scene_id
        self.project.scene(target_scene)
        self.checkpoint()
        pending: dict[tuple[int, int], list[tuple[float, int]]] = {}
        imported = 0
        max_beat = max((event.beat for event in performance.events), default=0.0)
        for group in GROUPS:
            clip_id = self.project.scene(target_scene).clip_ids[group]
            clip = self.project.clips[clip_id]
            clip.length_beats = max(0.25, performance.loop_beats)
            clip.notes.clear()
            clip.controls.clear()
        for event in sorted(performance.events, key=lambda item: item.beat):
            message = midi_message_from_dict(event.message)
            if message is None:
                continue
            channel = int(message.channel or 0)
            if message.kind == "note_on" and message.note is not None and message.velocity:
                pending.setdefault((channel, message.note), []).append(
                    (event.beat, int(message.velocity))
                )
            elif message.kind in {"note_off", "note_on"} and message.note is not None:
                starts = pending.get((channel, message.note))
                if not starts:
                    continue
                start, velocity = starts.pop(0)
                imported += self._append_imported_note(
                    target_scene,
                    message.note,
                    start,
                    max(0.01, event.beat - start),
                    velocity,
                )
            elif message.kind == "control_change" and message.control is not None:
                clip = self.project.clips[
                    self.project.scene(target_scene).clip_ids[self.selected_group]
                ]
                clip.controls.append(
                    ClipControl(
                        event.beat % clip.length_beats,
                        int(message.control),
                        int(message.value or 0),
                    )
                )
                imported += 1
        for (_channel, note), starts in pending.items():
            for start, velocity in starts:
                imported += self._append_imported_note(
                    target_scene,
                    note,
                    start,
                    max(0.05, min(performance.loop_beats, max_beat + 0.25) - start),
                    velocity,
                )
        return imported

    def save(self, path: str | Path) -> Path:
        payload = json.dumps(self.project.to_dict(), indent=2, sort_keys=True) + "\n"
        return atomic_write_text(path, payload)

    @classmethod
    def load(cls, path: str | Path) -> "ArrangerSession":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Arranger project must be a JSON object.")
        return cls(ArrangerProject.from_dict(raw))

    def export_midi(
        self,
        path: str | Path,
        *,
        mode: str = "song",
        scene_id: str | None = None,
        ticks_per_beat: int = 480,
    ) -> Path:
        if not 24 <= ticks_per_beat <= 9600:
            raise ValueError("ticks_per_beat must be between 24 and 9600.")
        events, _length = compile_arrangement(
            self.project,
            mode=mode,
            scene_id=scene_id or self.selected_scene_id,
        )
        tracks: list[bytes] = []
        conductor = bytearray()
        tempo = round(60_000_000 / self.project.bpm)
        conductor.extend(b"\x00\xff\x51\x03")
        conductor.extend(int(tempo).to_bytes(3, "big"))
        conductor.extend(b"\x00\xff\x58\x04")
        conductor.extend(bytes([self.project.beats_per_bar, 2, 24, 8]))
        conductor.extend(b"\x00\xff\x2f\x00")
        tracks.append(bytes(conductor))
        for group in GROUPS:
            track = bytearray()
            name = f"EP-133 Group {group}".encode("ascii")
            track.extend(b"\x00\xff\x03")
            track.extend(_variable_length(len(name)))
            track.extend(name)
            last_tick = 0
            for event in (item for item in events if item.track == group):
                encoded = _encode_midi_message(event.message)
                if not encoded:
                    continue
                tick = max(last_tick, round(event.beat * ticks_per_beat))
                track.extend(_variable_length(tick - last_tick))
                track.extend(encoded)
                last_tick = tick
            track.extend(b"\x00\xff\x2f\x00")
            tracks.append(bytes(track))
        header = (
            b"MThd"
            + (6).to_bytes(4, "big")
            + (1).to_bytes(2, "big")
            + len(tracks).to_bytes(2, "big")
            + int(ticks_per_beat).to_bytes(2, "big")
        )
        payload = bytearray(header)
        for track in tracks:
            payload.extend(b"MTrk")
            payload.extend(len(track).to_bytes(4, "big"))
            payload.extend(track)
        return atomic_write_bytes(path, bytes(payload))

    def _append_imported_note(
        self,
        scene_id: str,
        note: int,
        beat: float,
        duration: float,
        velocity: int,
    ) -> int:
        group = group_for_note(note)
        if group is None:
            return 0
        clip = self.project.clips[self.project.scene(scene_id).clip_ids[group]]
        clip.notes.append(
            ClipNote(
                beat=beat % clip.length_beats,
                duration=min(duration, clip.length_beats),
                note=note,
                velocity=velocity,
            )
        )
        clip.notes.sort(key=lambda item: (item.beat, item.note))
        return 1

    def _repair_selection(self) -> None:
        scene_ids = {scene.scene_id for scene in self.project.scenes}
        if self.selected_scene_id not in scene_ids:
            self.selected_scene_id = self.project.scenes[0].scene_id
        if self.selected_group not in GROUPS:
            self.selected_group = "A"


def compile_arrangement(
    project: ArrangerProject,
    *,
    mode: str = "song",
    scene_id: str | None = None,
    probability_cycle: int = 0,
) -> tuple[list[ScheduledMidiEvent], float]:
    """Compile a scene or song chain into deterministic MIDI events."""

    project.validate()
    if mode not in {"song", "scene"}:
        raise ValueError("Arranger mode must be song or scene.")
    if mode == "scene":
        target = scene_id or project.scenes[0].scene_id
        sections = [SongSection(target)]
    else:
        sections = project.song or [SongSection(project.scenes[0].scene_id)]

    audible = _audible_groups(project)
    events: list[ScheduledMidiEvent] = []
    cursor = 0.0
    iteration_number = 0
    for section in sections:
        for _repeat in range(section.repeats):
            scene = project.scene(section.scene_id)
            scene_length = project.scene_length(scene.scene_id)
            for group in GROUPS:
                if group not in audible:
                    continue
                clip_id = scene.clip_ids.get(group)
                if not clip_id:
                    continue
                clip = project.clips[clip_id]
                track = project.tracks[group]
                clip_iteration = 0
                while clip_iteration * clip.length_beats < scene_length - 1e-9:
                    base = cursor + clip_iteration * clip.length_beats
                    available = min(clip.length_beats, scene_length - clip_iteration * clip.length_beats)
                    for note_index, note in enumerate(clip.notes):
                        if note.beat >= available:
                            continue
                        if not _probability_passes(
                            project.seed,
                            probability_cycle,
                            iteration_number,
                            clip.clip_id,
                            note_index,
                            note.probability,
                        ):
                            continue
                        start = base + _apply_swing(note.beat, project.swing_percent)
                        end = min(base + available, start + note.duration)
                        transposed = max(0, min(127, note.note + track.transpose))
                        velocity = max(
                            1,
                            min(127, round(note.velocity * track.velocity_scale)),
                        )
                        events.append(
                            ScheduledMidiEvent(
                                start,
                                2,
                                group,
                                clip.clip_id,
                                MidiMessage.note_on(
                                    transposed,
                                    velocity,
                                    channel=track.channel,
                                ),
                            )
                        )
                        events.append(
                            ScheduledMidiEvent(
                                end,
                                0,
                                group,
                                clip.clip_id,
                                MidiMessage.note_off(
                                    transposed,
                                    channel=track.channel,
                                ),
                            )
                        )
                    for control in clip.controls:
                        if control.beat >= available:
                            continue
                        events.append(
                            ScheduledMidiEvent(
                                base + _apply_swing(control.beat, project.swing_percent),
                                1,
                                group,
                                clip.clip_id,
                                MidiMessage.control_change(
                                    control.control,
                                    control.value,
                                    channel=track.channel,
                                ),
                            )
                        )
                    clip_iteration += 1
                    iteration_number += 1
            cursor += scene_length
    events.sort(key=lambda item: (item.beat, item.priority, item.track, item.clip_id))
    return events, cursor


class ArrangerCapture:
    """Record paired MIDI notes and controls into armed scene clips."""

    def __init__(self, session: ArrangerSession):
        self.session = session
        self.recording = False
        self.started_at = 0.0
        self.pending: dict[tuple[int, int], tuple[float, int, str]] = {}
        self.events_recorded = 0

    def start(self, *, now: float | None = None) -> None:
        if self.recording:
            return
        self.session.checkpoint()
        self.started_at = monotonic() if now is None else float(now)
        self.pending.clear()
        self.events_recorded = 0
        self.recording = True

    def record(self, message: MidiMessage, *, now: float | None = None) -> None:
        if not self.recording:
            return
        current = monotonic() if now is None else float(now)
        beat = max(0.0, current - self.started_at) * self.session.project.bpm / 60.0
        channel = int(message.channel or 0)
        if message.kind == "note_on" and message.note is not None and message.velocity:
            group = group_for_note(message.note)
            if group and self.session.project.tracks[group].armed:
                self.pending[(channel, message.note)] = (
                    beat,
                    int(message.velocity),
                    group,
                )
        elif message.kind in {"note_off", "note_on"} and message.note is not None:
            pending = self.pending.pop((channel, message.note), None)
            if pending:
                start, velocity, group = pending
                self._append_note(group, message.note, start, max(0.01, beat - start), velocity)
        elif message.kind == "control_change" and message.control is not None:
            for group, track in self.session.project.tracks.items():
                if not track.armed:
                    continue
                clip = self.session.project.clips[
                    self.session.project.scene(self.session.selected_scene_id).clip_ids[group]
                ]
                clip.controls.append(
                    ClipControl(
                        beat % clip.length_beats,
                        int(message.control),
                        int(message.value or 0),
                    )
                )
                self.events_recorded += 1

    def stop(self, *, now: float | None = None) -> int:
        if not self.recording:
            return self.events_recorded
        current = monotonic() if now is None else float(now)
        beat = max(0.0, current - self.started_at) * self.session.project.bpm / 60.0
        for (_channel, note), (start, velocity, group) in list(self.pending.items()):
            self._append_note(group, note, start, max(0.01, beat - start), velocity)
        self.pending.clear()
        self.recording = False
        return self.events_recorded

    def _append_note(
        self,
        group: str,
        note: int,
        start: float,
        duration: float,
        velocity: int,
    ) -> None:
        clip = self.session.project.clips[
            self.session.project.scene(self.session.selected_scene_id).clip_ids[group]
        ]
        clip.notes.append(
            ClipNote(
                start % clip.length_beats,
                min(duration, clip.length_beats),
                note,
                velocity,
            )
        )
        clip.notes.sort(key=lambda item: (item.beat, item.note))
        self.events_recorded += 1


class RealtimeArrangerEngine:
    """High-resolution internal-clock scheduler for compiled arrangements."""

    def __init__(
        self,
        send: Callable[[MidiMessage], None],
        *,
        on_position: Callable[[float, float, int], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        on_complete: Callable[[], None] | None = None,
    ):
        self.send = send
        self.on_position = on_position
        self.on_error = on_error
        self.on_complete = on_complete
        self.running = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_notes: set[tuple[int, int]] = set()

    def start(
        self,
        project: ArrangerProject,
        *,
        mode: str = "song",
        scene_id: str | None = None,
        loop: bool = False,
        send_clock: bool = True,
        send_transport: bool = True,
    ) -> None:
        if self.running:
            raise RuntimeError("Arranger playback is already running.")
        project.validate()
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(
            target=self._run,
            args=(project, mode, scene_id, loop, send_clock, send_transport),
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, wait: bool = True) -> None:
        self._stop.set()
        if wait and self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)

    def _run(
        self,
        project: ArrangerProject,
        mode: str,
        scene_id: str | None,
        loop: bool,
        send_clock: bool,
        send_transport: bool,
    ) -> None:
        try:
            if send_transport:
                self.send(MidiMessage.start())
            cycle = 0
            while not self._stop.is_set():
                events, length = compile_arrangement(
                    project,
                    mode=mode,
                    scene_id=scene_id,
                    probability_cycle=cycle,
                )
                if length <= 0:
                    break
                timeline: list[tuple[float, int, MidiMessage]] = [
                    (event.beat, event.priority + 2, event.message) for event in events
                ]
                if send_clock:
                    tick_count = max(1, round(length * 24))
                    timeline.extend(
                        (tick / 24.0, 1, MidiMessage.clock())
                        for tick in range(tick_count)
                    )
                timeline.sort(key=lambda item: (item[0], item[1]))
                started = perf_counter()
                seconds_per_beat = 60.0 / project.bpm
                for beat, _priority, message in timeline:
                    if self._stop.is_set():
                        break
                    due = started + beat * seconds_per_beat
                    self._wait_until(due)
                    if self._stop.is_set():
                        break
                    self.send(message)
                    self._track_note(message)
                    if self.on_position and message.kind == "clock":
                        self.on_position(beat, length, cycle)
                if self._stop.is_set() or not loop:
                    break
                cycle += 1
            self._cleanup(send_transport)
            if self.on_complete:
                self.on_complete()
        except Exception as exc:
            self._cleanup(send_transport)
            if self.on_error:
                self.on_error(exc)
        finally:
            self.running = False

    def _wait_until(self, due: float) -> None:
        while not self._stop.is_set():
            remaining = due - perf_counter()
            if remaining <= 0:
                return
            self._stop.wait(min(remaining, 0.002 if remaining < 0.02 else 0.01))

    def _track_note(self, message: MidiMessage) -> None:
        if message.note is None:
            return
        key = (int(message.channel or 0), int(message.note))
        if message.kind == "note_on" and int(message.velocity or 0) > 0:
            self._active_notes.add(key)
        elif message.kind in {"note_off", "note_on"}:
            self._active_notes.discard(key)

    def _cleanup(self, send_transport: bool) -> None:
        for channel, note in sorted(self._active_notes):
            try:
                self.send(MidiMessage.note_off(note, channel=channel))
            except Exception:
                pass
        self._active_notes.clear()
        if send_transport:
            try:
                self.send(MidiMessage.stop())
            except Exception:
                pass


class ArrangerClockFollower:
    """Advance an arrangement from incoming MIDI Start/Continue/Stop/Clock."""

    def __init__(self, project: ArrangerProject, *, mode: str = "song", scene_id: str | None = None):
        self.project = project
        self.mode = mode
        self.scene_id = scene_id
        self.running = False
        self.tick = 0
        self.cycle = 0
        self.index = 0
        self.events, self.length = compile_arrangement(
            project,
            mode=mode,
            scene_id=scene_id,
        )

    @property
    def beat(self) -> float:
        return self.tick / 24.0

    def observe(self, message: MidiMessage) -> list[MidiMessage]:
        if message.kind == "start":
            self.running = True
            self.tick = 0
            self.cycle = 0
            self.index = 0
            return self._due()
        if message.kind == "continue":
            self.running = True
            return []
        if message.kind == "stop":
            self.running = False
            return []
        if message.kind != "clock" or not self.running:
            return []
        self.tick += 1
        if self.length > 0 and self.beat >= self.length:
            self.tick = 0
            self.cycle += 1
            self.index = 0
            self.events, self.length = compile_arrangement(
                self.project,
                mode=self.mode,
                scene_id=self.scene_id,
                probability_cycle=self.cycle,
            )
        return self._due()

    def _due(self) -> list[MidiMessage]:
        due: list[MidiMessage] = []
        while self.index < len(self.events) and self.events[self.index].beat <= self.beat + 1e-9:
            due.append(self.events[self.index].message)
            self.index += 1
        return due


def group_for_note(note: int) -> str | None:
    value = int(note)
    for group, base in GROUP_BASE_NOTES.items():
        if base <= value < base + 12:
            return group
    return None


def _audible_groups(project: ArrangerProject) -> set[str]:
    soloed = {group for group, track in project.tracks.items() if track.solo}
    if soloed:
        return {group for group in soloed if not project.tracks[group].muted}
    return {group for group, track in project.tracks.items() if not track.muted}


def _apply_swing(beat: float, swing_percent: float) -> float:
    if swing_percent <= 50:
        return beat
    sixteenth = round(beat * 4)
    if abs(beat * 4 - sixteenth) > 1e-6 or sixteenth % 2 == 0:
        return beat
    delay = ((swing_percent - 50.0) / 25.0) * 0.125
    return beat + delay


def _probability_passes(
    seed: int,
    cycle: int,
    iteration: int,
    clip_id: str,
    note_index: int,
    probability: float,
) -> bool:
    if probability >= 1:
        return True
    if probability <= 0:
        return False
    payload = f"{seed}:{cycle}:{iteration}:{clip_id}:{note_index}".encode("utf-8")
    value = int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") / float(1 << 64)
    return value < probability


def _encode_midi_message(message: MidiMessage) -> bytes:
    channel = int(message.channel or 0) & 0x0F
    if message.kind == "note_on":
        return bytes(
            [
                0x90 | channel,
                int(message.note or 0) & 0x7F,
                int(message.velocity or 0) & 0x7F,
            ]
        )
    if message.kind == "note_off":
        return bytes(
            [
                0x80 | channel,
                int(message.note or 0) & 0x7F,
                int(message.velocity or 0) & 0x7F,
            ]
        )
    if message.kind == "control_change":
        return bytes(
            [
                0xB0 | channel,
                int(message.control or 0) & 0x7F,
                int(message.value or 0) & 0x7F,
            ]
        )
    if message.kind == "program_change":
        return bytes([0xC0 | channel, int(message.program or 0) & 0x7F])
    return b""


def _variable_length(value: int) -> bytes:
    number = max(0, int(value))
    data = [number & 0x7F]
    while number >> 7:
        number >>= 7
        data.append((number & 0x7F) | 0x80)
    return bytes(reversed(data))
