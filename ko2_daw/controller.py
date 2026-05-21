"""High-level DAW controller with hardware safety gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic

from ko2_daw.config import DAWConfig
from ko2_daw.midi import DryRunMidiBackend, MidiBackend, MidiMessage


@dataclass
class ControllerState:
    """Mutable transport state."""

    running: bool = False
    clock_ticks: int = 0
    last_tick_time: float | None = None
    recorded: list[MidiMessage] = field(default_factory=list)


class DAWController:
    """Safe control surface for MIDI-capable samplers and DAW workflows."""

    def __init__(
        self,
        config: DAWConfig | None = None,
        backend: MidiBackend | None = None,
        output_port: str | None = None,
    ):
        self.config = config or DAWConfig()
        self.config.validate()
        self.backend = backend or DryRunMidiBackend()
        self.output_port = output_port
        self.state = ControllerState()

    def available_inputs(self) -> list[str]:
        return self.backend.list_input_ports()

    def available_outputs(self) -> list[str]:
        return self.backend.list_output_ports()

    def send(self, message: MidiMessage) -> None:
        self._assert_safe_to_send(message)
        self.backend.send(self.output_port, message)

    def start_transport(self) -> None:
        self.send(MidiMessage.start())
        self.state.running = True
        self.state.last_tick_time = monotonic()

    def stop_transport(self) -> None:
        self.send(MidiMessage.stop())
        self.state.running = False

    def continue_transport(self) -> None:
        self.send(MidiMessage.continue_())
        self.state.running = True
        self.state.last_tick_time = monotonic()

    def tick_clock(self) -> None:
        if not self.config.clock_enabled:
            raise RuntimeError("Clock output is disabled in configuration.")
        self.send(MidiMessage.clock())
        self.state.clock_ticks += 1
        self.state.last_tick_time = monotonic()

    def play_note(self, note: int, velocity: int = 96) -> None:
        self.send(MidiMessage.note_on(note, velocity=velocity, channel=self.config.midi_channel))

    def release_note(self, note: int) -> None:
        self.send(MidiMessage.note_off(note, channel=self.config.midi_channel))

    def control_change(self, control: int, value: int) -> None:
        self.send(MidiMessage.control_change(control, value, channel=self.config.midi_channel))

    def program_change(self, program: int) -> None:
        self.send(MidiMessage.program_change(program, channel=self.config.midi_channel))

    def record_incoming(self, message: MidiMessage) -> None:
        self.state.recorded.append(message)

    def panic(self) -> None:
        """Send all-notes-off and all-sound-off on every channel."""
        for channel in range(16):
            self.send(MidiMessage.control_change(123, 0, channel=channel))
            self.send(MidiMessage.control_change(120, 0, channel=channel))

    def _assert_safe_to_send(self, message: MidiMessage) -> None:
        safety = self.config.safety
        if not safety.output_port_allowed(self.output_port):
            raise PermissionError(
                "Live MIDI output requires an explicit output port allow-list match."
            )
        if message.kind == "sysex":
            if not safety.sysex_enabled:
                raise PermissionError("SysEx output is disabled.")
            if message.data is not None and len(message.data) > safety.max_sysex_bytes:
                raise PermissionError("SysEx payload exceeds configured byte limit.")
