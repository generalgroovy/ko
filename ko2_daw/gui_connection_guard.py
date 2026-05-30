"""Connection hardening for EP-133 file protocol workflows."""

from __future__ import annotations

from typing import Any


def apply_connection_guard_patch(gui_module: Any) -> None:
    """Patch live connection and SysEx/file operations with route health checks."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_connection_guard_patch_installed", False):
        return

    messagebox = gui_module.messagebox
    original_connect_live = app_class._connect_live
    original_run_sysex_probe = app_class._run_sysex_probe
    original_scan_complete_device_tree = app_class._scan_complete_device_tree
    original_send_device_file_playback = app_class._send_device_file_playback

    def _connect_live(self, route=None, *, auto_detected: bool = False) -> None:
        original_connect_live(self, route=route, auto_detected=auto_detected)
        self._verify_file_protocol_route(show_window=False)

    def _verify_file_protocol_route(self, *, show_window: bool = True) -> bool:
        if not self.live_output_port:
            if show_window:
                messagebox.showinfo("KO II Connection", "Connect EP-133 before using device files.")
            return False
        if not self.app_settings.sysex_enabled:
            if show_window:
                messagebox.showinfo("KO II Connection", "SysEx is disabled in Settings.")
            return False
        if self.live_input_port and self.input_monitor:
            return True

        self._refresh_report()
        route = self._resolve_configured_route()
        if route.input_port and route.output_port == self.live_output_port:
            try:
                if self.input_monitor:
                    self.input_monitor.stop()
                self.input_monitor = gui_module.WinMMInputMonitor(
                    route.input_port,
                    self._queue_midi_input,
                    include_sysex=True,
                )
                self.input_monitor.start()
                self.live_input_port = route.input_port
                self.live_state.set(f"live: {self.live_input_port} -> {self.live_output_port}")
                self._log(f"file protocol input recovered: {self.live_input_port}")
                if hasattr(self, "_record_protocol"):
                    self._record_protocol("app", "route", f"input recovered: {self.live_input_port}")
                return True
            except Exception as exc:
                self._log(f"file protocol input recovery failed: {exc}")
                if hasattr(self, "_record_protocol"):
                    self._record_protocol("app", "error", f"input recovery failed: {exc}")

        message = (
            "Live MIDI output is open, but no SysEx input is available. "
            "Device file browsing/playback needs the EP-133 input endpoint. "
            "Use direct USB-C EP-133 route, close other MIDI tools, then reconnect."
        )
        self.hardware_status.set("file protocol blocked: missing input")
        self._log(message)
        if hasattr(self, "_record_protocol"):
            self._record_protocol("app", "route-warning", message)
        if show_window:
            messagebox.showwarning("KO II File Protocol", message)
        return False

    def _run_sysex_probe(self, name: str, frame: bytes) -> None:
        if not self._verify_file_protocol_route(show_window=True):
            return
        original_run_sysex_probe(self, name, frame)

    def _scan_complete_device_tree(self, auto: bool = False) -> None:
        if not self._verify_file_protocol_route(show_window=not auto):
            return
        original_scan_complete_device_tree(self, auto=auto)

    def _send_device_file_playback(self, action: int) -> None:
        if not self._verify_file_protocol_route(show_window=True):
            return
        original_send_device_file_playback(self, action)

    app_class._connect_live = _connect_live
    app_class._verify_file_protocol_route = _verify_file_protocol_route
    app_class._run_sysex_probe = _run_sysex_probe
    app_class._scan_complete_device_tree = _scan_complete_device_tree
    app_class._send_device_file_playback = _send_device_file_playback
    app_class._connection_guard_patch_installed = True
