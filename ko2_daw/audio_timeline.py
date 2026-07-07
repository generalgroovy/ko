"""Non-destructive multitrack audio timeline and PCM WAV mix engine."""

from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass, field
import copy
import json
import math
from pathlib import Path
import struct
import tempfile
import uuid
import wave

from ko2_daw.io_utils import atomic_write_text


DEFAULT_SAMPLE_RATE = 46875
RENDER_BLOCK_FRAMES = 4096


@dataclass
class AudioTrack:
    track_id: str
    name: str
    color: str = "#d7f58a"
    gain_db: float = 0.0
    pan: float = 0.0
    muted: bool = False
    solo: bool = False
    armed: bool = False

    def validate(self) -> None:
        if not self.track_id:
            raise ValueError("Audio track id cannot be empty.")
        if not -96 <= self.gain_db <= 24:
            raise ValueError("Audio track gain must be between -96 and +24 dB.")
        if not -1 <= self.pan <= 1:
            raise ValueError("Audio track pan must be between -1 and +1.")


@dataclass
class AudioClip:
    clip_id: str
    track_id: str
    path: str
    name: str
    start_sec: float
    source_in_sec: float
    source_out_sec: float
    stretch: float = 1.0
    gain_db: float = 0.0
    pan: float = 0.0
    fade_in_sec: float = 0.0
    fade_out_sec: float = 0.0
    reverse: bool = False
    muted: bool = False

    @property
    def source_duration_sec(self) -> float:
        return max(0.0, self.source_out_sec - self.source_in_sec)

    @property
    def duration_sec(self) -> float:
        return self.source_duration_sec * self.stretch

    @property
    def end_sec(self) -> float:
        return self.start_sec + self.duration_sec

    def validate(self, track_ids: set[str] | None = None) -> None:
        if not self.clip_id:
            raise ValueError("Audio clip id cannot be empty.")
        if track_ids is not None and self.track_id not in track_ids:
            raise ValueError(f"Audio clip references unknown track {self.track_id!r}.")
        if not self.path:
            raise ValueError("Audio clip path cannot be empty.")
        if self.start_sec < 0 or self.source_in_sec < 0:
            raise ValueError("Audio clip positions cannot be negative.")
        if self.source_out_sec <= self.source_in_sec:
            raise ValueError("Audio clip source-out must be after source-in.")
        if not 0.125 <= self.stretch <= 8:
            raise ValueError("Audio clip stretch must be between 0.125x and 8x.")
        if not -96 <= self.gain_db <= 24:
            raise ValueError("Audio clip gain must be between -96 and +24 dB.")
        if not -1 <= self.pan <= 1:
            raise ValueError("Audio clip pan must be between -1 and +1.")
        if self.fade_in_sec < 0 or self.fade_out_sec < 0:
            raise ValueError("Audio clip fades cannot be negative.")
        if self.fade_in_sec + self.fade_out_sec > self.duration_sec + 1e-9:
            raise ValueError("Audio clip fades cannot overlap beyond the clip duration.")


@dataclass
class AudioProject:
    name: str = "KO II Audio Project"
    bpm: float = 120.0
    sample_rate: int = DEFAULT_SAMPLE_RATE
    master_gain_db: float = 0.0
    tracks: list[AudioTrack] = field(default_factory=list)
    clips: list[AudioClip] = field(default_factory=list)

    def validate(self) -> None:
        if not 20 <= self.bpm <= 300:
            raise ValueError("Audio project BPM must be between 20 and 300.")
        if not 8000 <= self.sample_rate <= 192000:
            raise ValueError("Audio project sample rate must be between 8 kHz and 192 kHz.")
        if not -96 <= self.master_gain_db <= 24:
            raise ValueError("Master gain must be between -96 and +24 dB.")
        track_ids = {track.track_id for track in self.tracks}
        if len(track_ids) != len(self.tracks):
            raise ValueError("Audio track ids must be unique.")
        for track in self.tracks:
            track.validate()
        clip_ids = {clip.clip_id for clip in self.clips}
        if len(clip_ids) != len(self.clips):
            raise ValueError("Audio clip ids must be unique.")
        for clip in self.clips:
            clip.validate(track_ids)

    @property
    def duration_sec(self) -> float:
        return max((clip.end_sec for clip in self.clips), default=0.0)

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema": "ko2-daw.audio-project.v1",
            "name": self.name,
            "bpm": self.bpm,
            "sample_rate": self.sample_rate,
            "master_gain_db": self.master_gain_db,
            "tracks": [asdict(track) for track in self.tracks],
            "clips": [asdict(clip) for clip in self.clips],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AudioProject":
        tracks = data.get("tracks")
        clips = data.get("clips")
        if not isinstance(tracks, list) or not isinstance(clips, list):
            raise ValueError("Audio project tracks and clips must be arrays.")
        project = cls(
            name=str(data.get("name", "KO II Audio Project")),
            bpm=float(data.get("bpm", 120.0)),
            sample_rate=int(data.get("sample_rate", DEFAULT_SAMPLE_RATE)),
            master_gain_db=float(data.get("master_gain_db", 0.0)),
            tracks=[AudioTrack(**item) for item in tracks if isinstance(item, dict)],
            clips=[AudioClip(**item) for item in clips if isinstance(item, dict)],
        )
        project.validate()
        return project


def default_audio_project(track_count: int = 6) -> AudioProject:
    if not 1 <= track_count <= 64:
        raise ValueError("Audio track count must be between 1 and 64.")
    colors = ("#f2c230", "#e36a45", "#65a6a6", "#8fac56", "#d7f58a", "#b8a0cf")
    project = AudioProject(
        tracks=[
            AudioTrack(
                track_id=f"T{index + 1:02d}",
                name=f"Audio {index + 1}",
                color=colors[index % len(colors)],
                armed=index == 0,
            )
            for index in range(track_count)
        ]
    )
    project.validate()
    return project


class AudioSession:
    """Mutable non-destructive audio editor with project-wide history."""

    def __init__(self, project: AudioProject | None = None, *, history_limit: int = 64):
        self.project = project or default_audio_project()
        self.history_limit = max(1, int(history_limit))
        self.selected_track_id = self.project.tracks[0].track_id
        self.selected_clip_id: str | None = None
        self._undo: list[dict[str, object]] = []
        self._redo: list[dict[str, object]] = []

    @property
    def selected_track(self) -> AudioTrack:
        return self.track(self.selected_track_id)

    @property
    def selected_clip(self) -> AudioClip | None:
        if self.selected_clip_id is None:
            return None
        try:
            return self.clip(self.selected_clip_id)
        except KeyError:
            return None

    def track(self, track_id: str) -> AudioTrack:
        for track in self.project.tracks:
            if track.track_id == track_id:
                return track
        raise KeyError(f"Unknown audio track {track_id}.")

    def clip(self, clip_id: str) -> AudioClip:
        for clip in self.project.clips:
            if clip.clip_id == clip_id:
                return clip
        raise KeyError(f"Unknown audio clip {clip_id}.")

    def checkpoint(self) -> None:
        self._undo.append(self.project.to_dict())
        self._undo = self._undo[-self.history_limit :]
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.project.to_dict())
        self.project = AudioProject.from_dict(self._undo.pop())
        self._repair_selection()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.project.to_dict())
        self.project = AudioProject.from_dict(self._redo.pop())
        self._repair_selection()
        return True

    def add_track(self, name: str | None = None) -> AudioTrack:
        self.checkpoint()
        used = {track.track_id for track in self.project.tracks}
        index = 1
        while f"T{index:02d}" in used:
            index += 1
        track = AudioTrack(
            track_id=f"T{index:02d}",
            name=(name or f"Audio {index}").strip() or f"Audio {index}",
        )
        self.project.tracks.append(track)
        self.selected_track_id = track.track_id
        return track

    def remove_track(self, track_id: str) -> None:
        if len(self.project.tracks) <= 1:
            raise ValueError("An audio project must keep at least one track.")
        self.track(track_id)
        self.checkpoint()
        self.project.tracks = [
            track for track in self.project.tracks if track.track_id != track_id
        ]
        removed_clip_ids = {
            clip.clip_id for clip in self.project.clips if clip.track_id == track_id
        }
        self.project.clips = [
            clip for clip in self.project.clips if clip.track_id != track_id
        ]
        if self.selected_clip_id in removed_clip_ids:
            self.selected_clip_id = None
        self.selected_track_id = self.project.tracks[0].track_id

    def import_wav(
        self,
        path: str | Path,
        *,
        track_id: str | None = None,
        start_sec: float = 0.0,
    ) -> AudioClip:
        source = read_wave_source(path)
        target_track = track_id or self.selected_track_id
        self.track(target_track)
        if start_sec < 0:
            raise ValueError("Audio clip start cannot be negative.")
        self.checkpoint()
        clip = AudioClip(
            clip_id=f"C-{uuid.uuid4().hex[:12]}",
            track_id=target_track,
            path=str(source.path),
            name=source.path.stem,
            start_sec=float(start_sec),
            source_in_sec=0.0,
            source_out_sec=source.duration_sec,
        )
        clip.validate({track.track_id for track in self.project.tracks})
        self.project.clips.append(clip)
        self.selected_track_id = target_track
        self.selected_clip_id = clip.clip_id
        return clip

    def select(self, *, track_id: str | None = None, clip_id: str | None = None) -> None:
        if track_id is not None:
            self.track(track_id)
            self.selected_track_id = track_id
        if clip_id is not None:
            clip = self.clip(clip_id)
            self.selected_clip_id = clip_id
            self.selected_track_id = clip.track_id

    def set_track(
        self,
        track_id: str,
        *,
        name: str | None = None,
        gain_db: float | None = None,
        pan: float | None = None,
        muted: bool | None = None,
        solo: bool | None = None,
        armed: bool | None = None,
    ) -> None:
        track = self.track(track_id)
        candidate = copy.deepcopy(track)
        if name is not None:
            candidate.name = name.strip() or candidate.name
        if gain_db is not None:
            candidate.gain_db = float(gain_db)
        if pan is not None:
            candidate.pan = float(pan)
        if muted is not None:
            candidate.muted = bool(muted)
        if solo is not None:
            candidate.solo = bool(solo)
        if armed is not None:
            candidate.armed = bool(armed)
        candidate.validate()
        self.checkpoint()
        track.name = candidate.name
        track.gain_db = candidate.gain_db
        track.pan = candidate.pan
        track.muted = candidate.muted
        track.solo = candidate.solo
        track.armed = candidate.armed

    def set_clip(
        self,
        clip_id: str,
        *,
        track_id: str | None = None,
        start_sec: float | None = None,
        source_in_sec: float | None = None,
        source_out_sec: float | None = None,
        stretch: float | None = None,
        gain_db: float | None = None,
        pan: float | None = None,
        fade_in_sec: float | None = None,
        fade_out_sec: float | None = None,
        reverse: bool | None = None,
        muted: bool | None = None,
    ) -> None:
        clip = self.clip(clip_id)
        candidate = copy.deepcopy(clip)
        if track_id is not None:
            self.track(track_id)
            candidate.track_id = track_id
        if start_sec is not None:
            candidate.start_sec = float(start_sec)
        if source_in_sec is not None:
            candidate.source_in_sec = float(source_in_sec)
        if source_out_sec is not None:
            candidate.source_out_sec = float(source_out_sec)
        if stretch is not None:
            candidate.stretch = float(stretch)
        if gain_db is not None:
            candidate.gain_db = float(gain_db)
        if pan is not None:
            candidate.pan = float(pan)
        if fade_in_sec is not None:
            candidate.fade_in_sec = float(fade_in_sec)
        if fade_out_sec is not None:
            candidate.fade_out_sec = float(fade_out_sec)
        if reverse is not None:
            candidate.reverse = bool(reverse)
        if muted is not None:
            candidate.muted = bool(muted)
        candidate.validate({track.track_id for track in self.project.tracks})
        self.checkpoint()
        for field_name in (
            "track_id",
            "start_sec",
            "source_in_sec",
            "source_out_sec",
            "stretch",
            "gain_db",
            "pan",
            "fade_in_sec",
            "fade_out_sec",
            "reverse",
            "muted",
        ):
            setattr(clip, field_name, getattr(candidate, field_name))
        self.selected_track_id = candidate.track_id

    def split_clip(self, clip_id: str, timeline_sec: float) -> tuple[AudioClip, AudioClip]:
        clip = self.clip(clip_id)
        if not clip.start_sec < timeline_sec < clip.end_sec:
            raise ValueError("Split point must fall inside the audio clip.")
        self.checkpoint()
        left = copy.deepcopy(clip)
        right = copy.deepcopy(clip)
        left.clip_id = f"C-{uuid.uuid4().hex[:12]}"
        right.clip_id = f"C-{uuid.uuid4().hex[:12]}"
        output_left = timeline_sec - clip.start_sec
        source_delta = output_left / clip.stretch
        if clip.reverse:
            left.source_in_sec = clip.source_out_sec - source_delta
            right.source_out_sec = clip.source_out_sec - source_delta
        else:
            left.source_out_sec = clip.source_in_sec + source_delta
            right.source_in_sec = clip.source_in_sec + source_delta
        right.start_sec = float(timeline_sec)
        left.fade_out_sec = min(left.fade_out_sec, left.duration_sec)
        right.fade_in_sec = min(right.fade_in_sec, right.duration_sec)
        self.project.clips = [
            item for item in self.project.clips if item.clip_id != clip_id
        ]
        self.project.clips.extend([left, right])
        self.selected_clip_id = right.clip_id
        return left, right

    def duplicate_clip(self, clip_id: str, *, start_sec: float | None = None) -> AudioClip:
        source = self.clip(clip_id)
        duplicate = copy.deepcopy(source)
        duplicate.clip_id = f"C-{uuid.uuid4().hex[:12]}"
        duplicate.name = f"{source.name} copy"
        duplicate.start_sec = source.end_sec if start_sec is None else float(start_sec)
        duplicate.validate({track.track_id for track in self.project.tracks})
        self.checkpoint()
        self.project.clips.append(duplicate)
        self.selected_clip_id = duplicate.clip_id
        return duplicate

    def delete_clip(self, clip_id: str) -> None:
        self.clip(clip_id)
        self.checkpoint()
        self.project.clips = [
            clip for clip in self.project.clips if clip.clip_id != clip_id
        ]
        if self.selected_clip_id == clip_id:
            self.selected_clip_id = None

    def save(self, path: str | Path) -> Path:
        return atomic_write_text(
            path,
            json.dumps(self.project.to_dict(), indent=2, sort_keys=True) + "\n",
        )

    @classmethod
    def load(cls, path: str | Path) -> "AudioSession":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Audio project must be a JSON object.")
        return cls(AudioProject.from_dict(raw))

    def _repair_selection(self) -> None:
        track_ids = {track.track_id for track in self.project.tracks}
        if self.selected_track_id not in track_ids:
            self.selected_track_id = self.project.tracks[0].track_id
        clip_ids = {clip.clip_id for clip in self.project.clips}
        if self.selected_clip_id not in clip_ids:
            self.selected_clip_id = None


@dataclass(frozen=True)
class WaveSource:
    path: Path
    sample_rate: int
    channels: int
    sample_width: int
    frame_count: int
    samples: array = field(repr=False)

    @property
    def duration_sec(self) -> float:
        return self.frame_count / self.sample_rate if self.sample_rate else 0.0

    def stereo_at(self, frame_position: float) -> tuple[float, float]:
        if self.frame_count <= 0:
            return 0.0, 0.0
        position = max(0.0, min(self.frame_count - 1.0, frame_position))
        before = int(position)
        after = min(self.frame_count - 1, before + 1)
        fraction = position - before
        left_before, right_before = self._stereo_frame(before)
        left_after, right_after = self._stereo_frame(after)
        return (
            left_before + (left_after - left_before) * fraction,
            right_before + (right_after - right_before) * fraction,
        )

    def _stereo_frame(self, index: int) -> tuple[float, float]:
        offset = index * self.channels
        if self.channels == 1:
            value = float(self.samples[offset])
            return value, value
        if self.channels == 2:
            return float(self.samples[offset]), float(self.samples[offset + 1])
        left_values = self.samples[offset : offset + self.channels : 2]
        right_values = self.samples[offset + 1 : offset + self.channels : 2]
        left = sum(left_values) / max(1, len(left_values))
        right = sum(right_values) / max(1, len(right_values))
        return float(left), float(right)


@dataclass(frozen=True)
class AudioRenderResult:
    path: Path
    sample_rate: int
    frames: int
    duration_sec: float
    peak: float
    clipped_samples: int
    normalized_gain_db: float = 0.0


def read_wave_source(path: str | Path) -> WaveSource:
    source = Path(path).resolve()
    if source.suffix.casefold() != ".wav":
        raise ValueError("Audio timeline supports PCM WAV files.")
    try:
        with wave.open(str(source), "rb") as handle:
            if handle.getcomptype() != "NONE":
                raise ValueError("Compressed WAV files are not supported.")
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            sample_rate = handle.getframerate()
            frame_count = handle.getnframes()
            payload = handle.readframes(frame_count)
    except (wave.Error, OSError) as exc:
        raise ValueError(f"Could not read WAV file {source}: {exc}") from exc
    if not 1 <= channels <= 8:
        raise ValueError("WAV channel count must be between 1 and 8.")
    if sample_width not in {1, 2, 3, 4}:
        raise ValueError("WAV sample width must be 8, 16, 24, or 32 bits.")
    if not 8000 <= sample_rate <= 384000:
        raise ValueError("WAV sample rate is outside the supported range.")
    samples = _decode_pcm(payload, sample_width)
    expected = frame_count * channels
    if len(samples) != expected:
        raise ValueError(
            f"WAV payload decoded to {len(samples)} samples; expected {expected}."
        )
    return WaveSource(
        path=source,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
        frame_count=frame_count,
        samples=samples,
    )


def render_audio_project(
    project: AudioProject,
    path: str | Path,
    *,
    normalize: bool = False,
    tail_sec: float = 0.0,
    max_duration_sec: float = 60 * 60,
) -> AudioRenderResult:
    """Render a stereo 16-bit PCM WAV using block-based summing."""

    project.validate()
    if tail_sec < 0:
        raise ValueError("Render tail cannot be negative.")
    duration = project.duration_sec + tail_sec
    if duration > max_duration_sec:
        raise ValueError(
            f"Project duration {duration:.1f}s exceeds render limit "
            f"{max_duration_sec:.1f}s."
        )
    total_frames = max(1, math.ceil(duration * project.sample_rate))
    sources = {
        clip.path: read_wave_source(clip.path)
        for clip in project.clips
        if not clip.muted
    }
    gain_scale = 1.0
    normalized_gain_db = 0.0
    if normalize and project.clips:
        peak = _project_peak(project, sources, total_frames)
        if peak > 0:
            gain_scale = min(32.0, (10 ** (-0.2 / 20.0)) / peak)
            normalized_gain_db = 20.0 * math.log10(gain_scale)

    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    peak = 0.0
    clipped = 0
    with tempfile.NamedTemporaryFile(
        "wb",
        delete=False,
        dir=target.parent,
        suffix=".wav",
    ) as temporary:
        temp_path = Path(temporary.name)
    try:
        with wave.open(str(temp_path), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(project.sample_rate)
            for start in range(0, total_frames, RENDER_BLOCK_FRAMES):
                count = min(RENDER_BLOCK_FRAMES, total_frames - start)
                mixed = _mix_block(project, sources, start, count)
                pcm = bytearray(count * 4)
                for index, value in enumerate(mixed):
                    scaled = value * gain_scale
                    peak = max(peak, abs(scaled))
                    if scaled > 1 or scaled < -1:
                        clipped += 1
                    integer = round(max(-1.0, min(1.0, scaled)) * 32767)
                    struct.pack_into("<h", pcm, index * 2, integer)
                output.writeframesraw(pcm)
        temp_path.replace(target)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return AudioRenderResult(
        path=target,
        sample_rate=project.sample_rate,
        frames=total_frames,
        duration_sec=total_frames / project.sample_rate,
        peak=peak,
        clipped_samples=clipped,
        normalized_gain_db=normalized_gain_db,
    )


def waveform_peaks(
    clip: AudioClip,
    *,
    points: int = 512,
) -> list[tuple[float, float]]:
    if points < 1:
        raise ValueError("Waveform point count must be positive.")
    source = read_wave_source(clip.path)
    start = max(0, round(clip.source_in_sec * source.sample_rate))
    end = min(source.frame_count, round(clip.source_out_sec * source.sample_rate))
    if end <= start:
        return []
    frames_per_bucket = max(1, math.ceil((end - start) / points))
    peaks: list[tuple[float, float]] = []
    for bucket_start in range(start, end, frames_per_bucket):
        minimum = 1.0
        maximum = -1.0
        for frame in range(bucket_start, min(end, bucket_start + frames_per_bucket)):
            left, right = source._stereo_frame(frame)
            minimum = min(minimum, left, right)
            maximum = max(maximum, left, right)
        peaks.append((minimum, maximum))
    if clip.reverse:
        peaks.reverse()
    return peaks[:points]


def _project_peak(
    project: AudioProject,
    sources: dict[str, WaveSource],
    total_frames: int,
) -> float:
    peak = 0.0
    for start in range(0, total_frames, RENDER_BLOCK_FRAMES):
        count = min(RENDER_BLOCK_FRAMES, total_frames - start)
        block = _mix_block(project, sources, start, count)
        peak = max(peak, max((abs(value) for value in block), default=0.0))
    return peak


def _mix_block(
    project: AudioProject,
    sources: dict[str, WaveSource],
    start_frame: int,
    frame_count: int,
) -> list[float]:
    output = [0.0] * (frame_count * 2)
    tracks = {track.track_id: track for track in project.tracks}
    soloed = {track.track_id for track in project.tracks if track.solo}
    master_gain = _db_gain(project.master_gain_db)
    block_start_sec = start_frame / project.sample_rate
    block_end_sec = (start_frame + frame_count) / project.sample_rate
    for clip in project.clips:
        track = tracks[clip.track_id]
        if clip.muted or track.muted or (soloed and track.track_id not in soloed):
            continue
        if clip.end_sec <= block_start_sec or clip.start_sec >= block_end_sec:
            continue
        source = sources[clip.path]
        clip_gain = _db_gain(clip.gain_db + track.gain_db) * master_gain
        pan = max(-1.0, min(1.0, clip.pan + track.pan))
        left_pan, right_pan = _pan_gains(pan)
        first = max(0, math.floor((clip.start_sec - block_start_sec) * project.sample_rate))
        last = min(
            frame_count,
            math.ceil((clip.end_sec - block_start_sec) * project.sample_rate),
        )
        for local_index in range(first, last):
            timeline_sec = (start_frame + local_index) / project.sample_rate
            clip_time = timeline_sec - clip.start_sec
            source_time = clip_time / clip.stretch
            if clip.reverse:
                source_time = clip.source_out_sec - source_time
            else:
                source_time = clip.source_in_sec + source_time
            source_frame = source_time * source.sample_rate
            left, right = source.stereo_at(source_frame)
            envelope = _fade_envelope(clip, clip_time)
            target = local_index * 2
            output[target] += left * clip_gain * left_pan * envelope
            output[target + 1] += right * clip_gain * right_pan * envelope
    return output


def _fade_envelope(clip: AudioClip, clip_time: float) -> float:
    gain = 1.0
    if clip.fade_in_sec > 0 and clip_time < clip.fade_in_sec:
        gain *= max(0.0, clip_time / clip.fade_in_sec)
    remaining = clip.duration_sec - clip_time
    if clip.fade_out_sec > 0 and remaining < clip.fade_out_sec:
        gain *= max(0.0, remaining / clip.fade_out_sec)
    return gain


def _pan_gains(pan: float) -> tuple[float, float]:
    angle = (pan + 1.0) * math.pi / 4.0
    return math.cos(angle), math.sin(angle)


def _db_gain(value: float) -> float:
    return 0.0 if value <= -96 else 10 ** (value / 20.0)


def _decode_pcm(payload: bytes, sample_width: int) -> array:
    samples = array("f")
    if sample_width == 1:
        samples.extend((value - 128) / 128.0 for value in payload)
        return samples
    if sample_width == 2:
        values = struct.unpack(f"<{len(payload) // 2}h", payload)
        samples.extend(value / 32768.0 for value in values)
        return samples
    if sample_width == 3:
        for offset in range(0, len(payload), 3):
            raw = int.from_bytes(payload[offset : offset + 3], "little", signed=False)
            value = raw - (1 << 24) if raw & (1 << 23) else raw
            samples.append(value / 8388608.0)
        return samples
    values = struct.unpack(f"<{len(payload) // 4}i", payload)
    samples.extend(value / 2147483648.0 for value in values)
    return samples
