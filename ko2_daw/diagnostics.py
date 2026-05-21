"""Device readiness diagnostics for the KO II companion app."""

from __future__ import annotations

from ko2_daw.routing import resolve_ko2_route


def readiness_report(midi_report: dict[str, object]) -> dict[str, object]:
    ko2_usb = bool(midi_report.get("ko2_usb_connected"))
    ko2_midi = bool(midi_report.get("ko2_midi_ready"))
    live_backend = midi_report.get("live_backend")
    status = "ready" if ko2_usb and ko2_midi else "usb-only" if ko2_usb else "not-detected"
    actions = []
    if not ko2_usb:
        actions.append("Connect EP-133 over USB and rerun --list.")
    if ko2_usb and not ko2_midi:
        actions.append("Windows sees EP-133 as USB Audio only; expose a MIDI endpoint or connect DIN MIDI through a visible interface.")
    if live_backend:
        actions.append(f"Native live MIDI backend available: {live_backend}.")
    if not midi_report.get("input_ports"):
        actions.append("No MIDI input port is visible for state monitoring.")
    if not midi_report.get("output_ports"):
        actions.append("No MIDI output port is visible for remote control.")
    route = resolve_ko2_route(midi_report)
    return {
        "status": status,
        "ko2_usb_connected": ko2_usb,
        "ko2_midi_ready": ko2_midi,
        "input_ports": midi_report.get("input_ports") or [],
        "output_ports": midi_report.get("output_ports") or [],
        "route": {
            "status": route.status,
            "input_port": route.input_port,
            "output_port": route.output_port,
            "message": route.message,
            "requires_user_action": route.requires_user_action,
        },
        "actions": actions,
    }
