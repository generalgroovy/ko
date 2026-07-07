"""GUI command for read-only EP-133 integrity snapshots."""

from __future__ import annotations

import queue
import threading
from typing import Any

from ko2_daw.device_snapshot import SnapshotLimits, capture_device_snapshot, save_device_snapshot
from ko2_daw.routing import KO2Route


def apply_device_snapshot_patch(gui_module: Any) -> None:
    """Add background device snapshot capture to the stable GUI."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_device_snapshot_patch_installed", False):
        return

    tk = gui_module.tk
    messagebox = gui_module.messagebox
    original_init = app_class.__init__
    original_build_menu = app_class._build_menu

    def __init__(self, root) -> None:
        self.device_snapshot_results: queue.Queue[tuple[str, object]] = queue.Queue()
        original_init(self, root)
        self.root.after(120, self._poll_device_snapshot_results)

    def _build_menu(self) -> None:
        original_build_menu(self)
        menu = self.root.nametowidget(self.root.cget("menu"))
        device_menu = tk.Menu(menu, tearoff=False)
        device_menu.add_command(label="Capture Integrity Snapshot", command=self._capture_integrity_snapshot)
        device_menu.add_command(label="Open Device Files", command=getattr(self, "_show_file_explorer_window", lambda: None))
        device_menu.add_command(label="MIDI Detection", command=getattr(self, "_show_midi_detection", lambda: None))
        menu.add_cascade(label="Device", menu=device_menu)

    def _capture_integrity_snapshot(self) -> None:
        if not self.live_input_port or not self.live_output_port:
            messagebox.showinfo("EP-133 Snapshot", "Connect EP-133 live before capturing a device snapshot.")
            return
        if not self.app_settings.sysex_enabled:
            messagebox.showinfo("EP-133 Snapshot", "SysEx is disabled in Communication settings.")
            return
        if self._hardware_scan_lock.locked():
            messagebox.showinfo("EP-133 Snapshot", "A device file scan is already running.")
            return
        if not self._hardware_scan_lock.acquire(blocking=False):
            return

        route = KO2Route(
            status="live-gui",
            input_port=self.live_input_port,
            output_port=self.live_output_port,
            allow_output=self.live_output_port,
            message="Using current GUI MIDI session.",
        )
        limits = SnapshotLimits(
            pages_per_directory=self.app_settings.scan_pages_per_dir,
            max_depth=self.app_settings.scan_max_depth,
            max_directories=self.app_settings.scan_max_dirs,
            timeout_sec=self.app_settings.sysex_timeout_sec,
        )
        self.hardware_status.set("integrity snapshot: running")
        self._set_action("capturing EP-133 integrity snapshot")

        def exchange(frame: bytes, timeout_sec: float):
            return self._send_sysex_and_decode("integrity-snapshot", frame, timeout_sec)

        def worker() -> None:
            try:
                snapshot = capture_device_snapshot(
                    limits=limits,
                    midi_report=self.report,
                    route=route,
                    exchange=exchange,
                )
                path = save_device_snapshot(snapshot, self.project_root / "ep133_device_snapshot.json")
                self.device_snapshot_results.put(("ok", (snapshot, path)))
            except Exception as exc:
                self.device_snapshot_results.put(("error", exc))
            finally:
                self._hardware_scan_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    def _poll_device_snapshot_results(self) -> None:
        while True:
            try:
                kind, payload = self.device_snapshot_results.get_nowait()
            except queue.Empty:
                break
            if kind == "error":
                self.hardware_status.set("integrity snapshot: failed")
                self._log(f"integrity snapshot failed: {payload}")
                messagebox.showerror("EP-133 Snapshot", str(payload))
                continue
            snapshot, path = payload
            short_hash = snapshot.integrity_sha256[:12]
            self.hardware_status.set(
                f"snapshot: {len(snapshot.records)} records / {short_hash}"
            )
            self._log(
                f"integrity snapshot saved: {path} | records={len(snapshot.records)} "
                f"files={len(snapshot.files)} sha256={snapshot.integrity_sha256}"
            )
            messagebox.showinfo(
                "EP-133 Snapshot",
                "\n".join(
                    [
                        f"Saved: {path}",
                        f"Identity: {snapshot.identity_sku or 'unknown'}",
                        f"Files: {len(snapshot.files)}",
                        f"Directories: {len(snapshot.directories)}",
                        f"Total bytes: {snapshot.total_file_bytes}",
                        f"Integrity SHA-256: {snapshot.integrity_sha256}",
                    ]
                ),
            )
        try:
            if self.root.winfo_exists():
                self.root.after(120, self._poll_device_snapshot_results)
        except tk.TclError:
            return

    app_class.__init__ = __init__
    app_class._build_menu = _build_menu
    app_class._capture_integrity_snapshot = _capture_integrity_snapshot
    app_class._poll_device_snapshot_results = _poll_device_snapshot_results
    app_class._device_snapshot_patch_installed = True
