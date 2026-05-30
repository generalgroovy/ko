"""Song and track timeline model for EP-133 style sequencing."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

SONG_NUMBERS = tuple(range(1, 10))
TRACKS = ("A", "B", "C", "D")
DEFAULT_STEPS = 64
MAX_STEPS = 256


@dataclass
class TrackTimeline:
    """Best-known timeline for one A/B/C/D track."""

    name: str
    length_steps: int = DEFAULT_STEPS
    hits: set[int] = field(default_factory=set)
    components: list[str] = field(default_factory=list)
    evidence: str = "default"

    def mark(self, step: int, component: str, *, evidence: str) -> None:
        self.length_steps = max(self.length_steps, min(MAX_STEPS, step + 1))
        self.hits.add(step % max(1, self.length_steps))
        if component and component not in self.components:
            self.components.append(component)
        self.evidence = evidence

    def set_length(self, steps: int, *, evidence: str) -> None:
        self.length_steps = max(1, min(MAX_STEPS, int(steps)))
        self.evidence = evidence

    @property
    def component_label(self) -> str:
        if not self.components:
            return "observed notes only" if self.hits else "empty/unknown"
        return ", ".join(self.components[:6]) + (" …" if len(self.components) > 6 else "")


@dataclass
class SongTimeline:
    """Best-known setup for one song slot."""

    number: int
    tracks: dict[str, TrackTimeline] = field(default_factory=dict)
    evidence: str = "default"

    def __post_init__(self) -> None:
        for track in TRACKS:
            self.tracks.setdefault(track, TrackTimeline(track))


@dataclass
class SongTimelineSet:
    """Timeline state for song slots 1-9."""

    songs: dict[int, SongTimeline] = field(default_factory=dict)
    selected_song: int = 1
    selected_track: str = "A"

    def __post_init__(self) -> None:
        for number in SONG_NUMBERS:
            self.songs.setdefault(number, SongTimeline(number))

    @property
    def current_song(self) -> SongTimeline:
        return self.songs[self.selected_song]

    @property
    def current_track(self) -> TrackTimeline:
        return self.current_song.tracks[self.selected_track]

    def select_song(self, number: int) -> None:
        if number not in SONG_NUMBERS:
            raise ValueError("song number must be 1-9")
        self.selected_song = number

    def select_track(self, track: str) -> None:
        normalized = str(track).upper()
        if normalized not in TRACKS:
            raise ValueError("track must be A, B, C, or D")
        self.selected_track = normalized

    def mark_step(self, track: str, step: int, component: str, *, evidence: str) -> None:
        self.select_track(track)
        self.current_song.tracks[self.selected_track].mark(step, component, evidence=evidence)

    def infer_from_file_entry(self, path: str, kind: str, node: str, name: str, size: str = "") -> None:
        """Infer song/track setup hints from a hardware file-tree entry."""

        text = " ".join(str(part or "") for part in (path, kind, node, name, size)).casefold()
        song = _extract_song_number(text)
        track = _extract_track(text)
        if song is None or track is None:
            return
        self.select_song(song)
        self.select_track(track)
        track_model = self.current_song.tracks[track]
        length = _extract_length_steps(text)
        if length:
            track_model.set_length(length, evidence="device file tree")
        label = str(name or path or node).strip()[:64]
        if label and label not in track_model.components:
            track_model.components.append(label)
        track_model.evidence = "device file tree"
        self.current_song.evidence = "device file tree"


def _extract_song_number(text: str) -> int | None:
    patterns = (
        r"(?:song|project|pattern|scene)[ _\-/]*(\d)",
        r"\bs(\d)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            number = int(match.group(1))
            if number in SONG_NUMBERS:
                return number
    return None


def _extract_track(text: str) -> str | None:
    match = re.search(r"(?:track|group|lane)[ _\-/]*([abcd])\b", text)
    if match:
        return match.group(1).upper()
    match = re.search(r"\b([abcd])\b", text)
    if match:
        return match.group(1).upper()
    return None


def _extract_length_steps(text: str) -> int | None:
    match = re.search(r"(?:len|length|steps?)[ _\-/:]*(\d{1,3})", text)
    if not match:
        match = re.search(r"(16|32|48|64|96|128|256)[ _\-]*(?:step|st|bar|seq)", text)
    if not match:
        return None
    steps = int(match.group(1))
    return steps if 1 <= steps <= MAX_STEPS else None
