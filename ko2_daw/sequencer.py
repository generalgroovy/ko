"""Small deterministic MIDI sequencer primitives."""

from __future__ import annotations

from dataclasses import dataclass

from ko2_daw.controller import DAWController


@dataclass(frozen=True)
class StepEvent:
    """One scheduled note event in beats."""

    beat: float
    note: int
    velocity: int = 96
    length_beats: float = 0.25


class StepSequencer:
    """Render beat-based note events through a DAWController."""

    def __init__(self, controller: DAWController, events: list[StepEvent] | None = None):
        self.controller = controller
        self.events = sorted(events or [], key=lambda event: event.beat)

    def add(self, event: StepEvent) -> None:
        self.events.append(event)
        self.events.sort(key=lambda item: item.beat)

    def render_once(self) -> int:
        """Send each note-on and note-off in deterministic order."""
        count = 0
        off_events = [
            StepEvent(
                beat=event.beat + event.length_beats,
                note=event.note,
                velocity=0,
                length_beats=0,
            )
            for event in self.events
        ]
        timeline = [(event.beat, "on", event) for event in self.events]
        timeline.extend((event.beat, "off", event) for event in off_events)
        for _, kind, event in sorted(timeline, key=lambda item: (item[0], item[1])):
            if kind == "on":
                self.controller.play_note(event.note, event.velocity)
            else:
                self.controller.release_note(event.note)
            count += 1
        return count
