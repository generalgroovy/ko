"""GUI patch for robust EP-133 MIDI detection and diagnostics."""

from __future__ import annotations

from typing import Any

from ko2_daw.port_match import enrich_midi_report


def apply_midi_detection_patch(gui_module: Any) -> None:
    """Keep GUI reports and user messages aligned with robust port matching."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_midi_detection_patch_installed", False):
        return

    messagebox = gui_module.messagebox
    original_init = app_class.__init__
    original_refresh_report = app_class._refresh_report
    original_connect_live = app_class._connect_live

    def __init__(self, root):
        original_init(self, root)
        self.report = enrich_midi_report(self.report)
        self._refresh_ports()

    def _refresh_report(self) -> None:
        original_refresh_report(self)
        self.report = enrich_midi_report(self.report)
        self._refresh_ports()
        self._log(self._midi_detection_summary())
        if hasattr(self, "_record_protocol"):
            self._record_protocol("app", "midi-detection", "refreshed", self._midi_detection_summary())

    def _connect_live(self, route=None, *, auto_detected: bool = False) -> None:
        if route is None:
            self.report = enrich_midi_report(self.report)
        original_connect_live(self, route=route, auto_detected=auto_detected)

    def _midi_detection_summary(self) -> str:
        inputs = list(self.report.get("input_ports") or [])
        outputs = list(self.report.get("output_ports") or [])
        candidates = list(self.report.get("ko2_midi_ports") or [])
        lines = [
            f"input ports: {len(inputs)}",
            f"output ports: {len(outputs)}",
            f"EP-133/KO II candidates: {', '.join(candidates) or 'none'}",
            f"USB device present: {'yes' if self.report.get('ko2_usb_connected') else 'no'}",
            f"MIDI ready: {'yes' if self.report.get('ko2_midi_ready') else 'no'}",
        ]
        hints = list(self.report.get("hints") or [])
        if hints:
            lines.append("hints:")
            lines.extend(f"- {hint}" for hint in hints)
        return "\n".join(lines)

    def _show_midi_detection_summary(self) -> None:
        self._refresh_report()
        messagebox.showinfo("EP-133 MIDI Detection", self._midi_detection_summary())

    app_class.__init__ = __init__
    app_class._refresh_report = _refresh_report
    app_class._connect_live = _connect_live
    app_class._midi_detection_summary = _midi_detection_summary
    app_class._show_midi_detection_summary = _show_midi_detection_summary
    app_class._midi_detection_patch_installed = True
