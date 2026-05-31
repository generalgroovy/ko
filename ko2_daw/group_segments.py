"""A1-D99 segment occupancy model for EP-133 style projects."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable

GROUPS = ("A", "B", "C", "D")
SEGMENT_NUMBERS = tuple(range(1, 100))
DEFAULT_SEGMENT_LENGTH_STEPS = 64


@dataclass
class SegmentSlot:
    """Best-known state for one segment such as A1 or D99."""

    group: str
    number: int
    occupied: bool | None = None
    label: str = ""
    node: str = ""
    size: str = ""
    evidence: str = "unscanned"
    components: set[str] = field(default_factory=set)
    hits: set[int] = field(default_factory=set)
    length_steps: int = DEFAULT_SEGMENT_LENGTH_STEPS

    @property
    def segment_id(self) -> str:
        return f"{self.group}{self.number}"

    @property
    def status_text(self) -> str:
        if self.occupied is True:
            what = self.label or ", ".join(sorted(self.components)) or "occupied"
            return what[:80]
        if self.occupied is False:
            return "empty"
        return "unknown"

    def mark_occupied(
        self,
        *,
        label: str = "",
        component: str = "",
        node: str = "",
        size: str = "",
        evidence: str,
    ) -> None:
        self.occupied = True
        if label:
            self.label = label
        if component:
            self.components.add(component)
        if node:
            self.node = str(node)
        if size:
            self.size = str(size)
        self.evidence = evidence

    def mark_empty(self, *, evidence: str) -> None:
        if self.occupied is not True:
            self.occupied = False
            self.evidence = evidence

    def mark_hit(self, step: int, component: str, *, evidence: str) -> None:
        self.occupied = True
        self.hits.add(int(step) % max(1, self.length_steps))
        if component:
            self.components.add(component)
        self.evidence = evidence


@dataclass
class SegmentBank:
    """A-D groups with 99 segment slots each."""

    slots: dict[str, dict[int, SegmentSlot]] = field(default_factory=dict)
    selected_group: str = "A"
    selected_segment: int = 1
    current_song: int = 1
    current_step: int = 0
    scan_complete: bool = False
    last_poll: str = "not polled"

    def __post_init__(self) -> None:
        for group in GROUPS:
            self.slots.setdefault(
                group,
                {number: SegmentSlot(group, number) for number in SEGMENT_NUMBERS},
            )

    @property
    def selected_slot(self) -> SegmentSlot:
        return self.slots[self.selected_group][self.selected_segment]

    def select(self, group: str | None = None, segment: int | None = None) -> None:
        if group is not None:
            normalized = str(group).upper()
            if normalized not in GROUPS:
                raise ValueError("group must be A-D")
            self.selected_group = normalized
        if segment is not None:
            number = int(segment)
            if number not in SEGMENT_NUMBERS:
                raise ValueError("segment must be 1-99")
            self.selected_segment = number

    def mark_scan_complete(self) -> None:
        self.scan_complete = True
        for slot in self.iter_slots():
            slot.mark_empty(evidence="device scan")

    def iter_slots(self) -> Iterable[SegmentSlot]:
        for group in GROUPS:
            for number in SEGMENT_NUMBERS:
                yield self.slots[group][number]

    def ingest_file_entry(self, *, path: str, kind: str, node: str, name: str, size: str, status: str) -> SegmentSlot | None:
        text = " ".join(str(part or "") for part in (path, kind, node, name, size, status))
        found = extract_segment_id(text)
        if not found:
            return None
        group, number = found
        slot = self.slots[group][number]
        label = str(name or path or node or slot.segment_id)
        slot.mark_occupied(
            label=label,
            component=label,
            node=str(node or ""),
            size=str(size or ""),
            evidence="device file tree",
        )
        return slot

    def mark_midi_note(self, note: int, step: int, component: str, *, evidence: str) -> SegmentSlot | None:
        mapped = note_to_group_segment(note)
        if not mapped:
            return None
        group, segment = mapped
        self.select(group, segment)
        slot = self.slots[group][segment]
        slot.mark_hit(step, component, evidence=evidence)
        return slot


def extract_segment_id(text: str) -> tuple[str, int] | None:
    """Extract segment IDs like A1, A01, B3, C44, or group D segment 99."""

    normalized = str(text or "")
    patterns = (
        r"\b([ABCDabcd])\s*[-_ ]?\s*(\d{1,2})\b",
        r"\b(?:group|track|lane)\s*([ABCDabcd])\s*(?:segment|slot|pattern|part)?\s*(\d{1,2})\b",
        r"\b(?:segment|slot|pattern|part)\s*([ABCDabcd])\s*(\d{1,2})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue
        group = match.group(1).upper()
        number = int(match.group(2))
        if group in GROUPS and number in SEGMENT_NUMBERS:
            return group, number
    return None


def note_to_group_segment(note: int) -> tuple[str, int] | None:
    """Map the visible pad note ranges to group segment numbers 1-12.

    MIDI does not expose all 99 segment slots as notes in the current app model.
    The first twelve are observable through the pad note ranges; higher slots are
    populated through file-tree/metadata evidence when available.
    """

    value = int(note)
    if 36 <= value <= 47:
        return "A", value - 35
    if 48 <= value <= 59:
        return "B", value - 47
    if 60 <= value <= 71:
        return "C", value - 59
    if 72 <= value <= 83:
        return "D", value - 71
    return None


def program_to_group(program: int) -> str | None:
    mapping = {0: "A", 1: "B", 2: "C", 3: "D"}
    return mapping.get(int(program))
