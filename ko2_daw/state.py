"""Runtime state inferred from MIDI traffic.

The EP-133 MIDI implementation exposes notes, clock/transport, bank select, mod
wheel, and common controller messages. It does not expose a general "dump current
project/effects state" query in the public MIDI chart, so this module tracks
what the app sends and what it receives.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from ko2_daw.midi import MidiMessage


@dataclass
class MidiEventRecord:
    timestamp: str
    direction: str
    message: str


@dataclass
class KO2RuntimeState:
    """Best-effort state mirror based on observable MIDI traffic."""

    transport: str = "unknown"
    active_notes: dict[str, int] = field(default_factory=dict)
    clock_ticks: int = 0
    last_program: int | None = None
    last_bank_msb: int | None = None
    last_bank_lsb: int | None = None
    mod_wheel: int | None = None
    controllers: dict[str, int] = field(default_factory=dict)
    recent_events: list[MidiEventRecord] = field(default_factory=list)
    limitations: list[str] = field(
        default_factory=lambda: [
            "Effects, selected project, sample names, pattern contents, and most front-panel state are not queryable through the public MIDI implementation.",
            "Playing state is inferred from MIDI start/stop/clock and observed note traffic.",
            "Effect movement can only be mirrored when the device sends MIDI CC or the app sends a mapped controller.",
        ]
    )

    def observe(self, message: MidiMessage, direction: str = "in") -> None:
        now = datetime.now(UTC).isoformat(timespec="milliseconds")
        if message.kind == "start":
            self.transport = "playing"
        elif message.kind == "stop":
            self.transport = "stopped"
            self.active_notes.clear()
        elif message.kind == "clock":
            self.clock_ticks += 1
            if self.transport == "unknown":
                self.transport = "clock seen"
        elif message.kind == "note_on" and message.note is not None:
            if message.velocity:
                self.active_notes[str(message.note)] = int(message.velocity)
            else:
                self.active_notes.pop(str(message.note), None)
        elif message.kind == "note_off" and message.note is not None:
            self.active_notes.pop(str(message.note), None)
        elif message.kind == "control_change" and message.control is not None:
            value = int(message.value or 0)
            self.controllers[str(message.control)] = value
            if message.control == 0:
                self.last_bank_msb = value
            elif message.control == 32:
                self.last_bank_lsb = value
            elif message.control == 1:
                self.mod_wheel = value
        elif message.kind == "program_change" and message.program is not None:
            self.last_program = int(message.program)

        self.recent_events.append(MidiEventRecord(now, direction, message.display()))
        self.recent_events = self.recent_events[-128:]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
