"""Routing decisions for controlling a connected KO II."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KO2Route:
    status: str
    input_port: str | None
    output_port: str | None
    allow_output: str | None
    message: str
    requires_user_action: str | None = None

    @property
    def can_send_midi(self) -> bool:
        return self.output_port is not None


def resolve_ko2_route(midi_report: dict[str, object], preferred: str = "auto") -> KO2Route:
    """Resolve the best available route for KO II control.

    `usb-midi` means a KO II/EP-133 MIDI endpoint is directly visible.
    `quad-capture` means using a Roland QUAD-CAPTURE MIDI port, which requires
    physical DIN MIDI cabling between the interface and the KO II.
    """
    input_ports = list(midi_report.get("input_ports") or [])
    output_ports = list(midi_report.get("output_ports") or [])
    ko2_ports = list(midi_report.get("ko2_midi_ports") or [])
    ko2_usb_connected = bool(midi_report.get("ko2_usb_connected"))

    if preferred not in {"auto", "usb-midi", "quad-capture"}:
        raise ValueError("preferred route must be auto, usb-midi, or quad-capture.")

    ko2_output = next((port for port in ko2_ports if port in output_ports), None)
    ko2_input = next((port for port in ko2_ports if port in input_ports), None)
    if preferred in {"auto", "usb-midi"} and ko2_output:
        return KO2Route(
            status="usb-midi-ready",
            input_port=ko2_input,
            output_port=ko2_output,
            allow_output=ko2_output,
            message=f"Using visible KO II MIDI output: {ko2_output}",
        )
    if preferred == "usb-midi":
        return KO2Route(
            status="usb-midi-missing",
            input_port=None,
            output_port=None,
            allow_output=None,
            message="EP-133 USB is detected, but no EP-133/KO II MIDI endpoint is visible.",
            requires_user_action="Expose the EP-133 as a MIDI device in Windows, then rerun --list.",
        )

    quad_output = next((port for port in output_ports if "quad-capture" in port.lower()), None)
    quad_input = next((port for port in input_ports if "quad-capture" in port.lower()), None)
    if preferred in {"auto", "quad-capture"} and quad_output:
        return KO2Route(
            status="din-interface-ready" if ko2_usb_connected else "interface-ready",
            input_port=quad_input,
            output_port=quad_output,
            allow_output=quad_output,
            message=f"Using QUAD-CAPTURE MIDI output: {quad_output}",
            requires_user_action="Connect QUAD-CAPTURE MIDI OUT to KO II MIDI IN for remote control.",
        )
    if preferred == "quad-capture":
        return KO2Route(
            status="quad-capture-missing",
            input_port=None,
            output_port=None,
            allow_output=None,
            message="QUAD-CAPTURE MIDI output is not visible.",
            requires_user_action="Connect or enable QUAD-CAPTURE, then rerun --list.",
        )

    if ko2_usb_connected:
        return KO2Route(
            status="usb-audio-only",
            input_port=None,
            output_port=None,
            allow_output=None,
            message="EP-133 is USB-connected, but Windows exposes it as USB Audio only.",
            requires_user_action="Expose EP-133 as MIDI or route DIN MIDI through a visible MIDI interface.",
        )
    return KO2Route(
        status="not-detected",
        input_port=None,
        output_port=None,
        allow_output=None,
        message="No KO II USB or MIDI route is visible.",
        requires_user_action="Connect EP-133 over USB or through a MIDI interface, then rerun --list.",
    )
