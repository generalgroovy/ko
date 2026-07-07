"""Stable EP-133 sample download, waveform, and local preview window."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import threading
from typing import Any

from ko2_daw.device_transfer import (
    DeviceDownloadArtifact,
    DeviceDownloadLimits,
    DeviceFileClient,
    find_latest_device_artifact,
    save_device_download,
    wav_peak_envelope,
)
from ko2_daw.samples import play_wav, stop_wav


def apply_device_library_patch(gui_module: Any) -> None:
    """Add an integrity-checked device audio library to the stable GUI."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_device_library_patch_installed", False):
        return

    tk = gui_module.tk
    ttk = gui_module.ttk
    messagebox = gui_module.messagebox
    original_init = app_class.__init__
    original_build_menu = app_class._build_menu
    original_build_sample_library = app_class._build_sample_library
    original_connect_live = app_class._connect_live
    original_disconnect_live = app_class._disconnect_live
    original_close = app_class._close

    def __init__(self, root):
        self.device_library_window = None
        self.device_library_tree = None
        self.device_library_entries: dict[str, dict[str, object]] = {}
        self.device_library_queue: queue.Queue[tuple[object, ...]] = queue.Queue()
        self._device_library_transfer_lock = threading.Lock()
        self.device_library_status = tk.StringVar(value="device library ready")
        self.device_library_progress = tk.DoubleVar(value=0)
        original_init(self, root)
        self.root.after(100, self._poll_device_library_queue)

    def _build_menu(self) -> None:
        original_build_menu(self)
        menu = self.root.nametowidget(self.root.cget("menu"))
        library = tk.Menu(menu, tearoff=False)
        library.add_command(label="Open Device Sample Library", command=self._show_device_library)
        library.add_command(
            label="Download Selected Hardware Node",
            command=self._download_selected_hardware_node,
        )
        library.add_command(
            label="Inspect Downloaded Project",
            command=self._show_project_archive_analysis,
        )
        library.add_separator()
        library.add_command(label="Device Library Guide", command=self._show_device_library_help)
        library.add_command(label="Stop Local Audio", command=stop_wav)
        menu.add_cascade(label="Device Library", menu=library)

    def _build_sample_library(self, parent) -> None:
        original_build_sample_library(self, parent)
        toolbars = parent.grid_slaves(row=0, column=0)
        if not toolbars:
            return
        button = tk.Button(
            toolbars[0],
            text="DEVICE LIBRARY",
            command=self._show_device_library,
            bg="#efeadf",
        )
        button.pack(side=tk.LEFT, padx=4)
        self._tip(
            button,
            "Open the read-only EP-133 sound downloader, metadata viewer, waveform, and local preview.",
        )

    def _connect_live(self, *args, **kwargs) -> None:
        if self._device_library_transfer_lock.locked():
            messagebox.showinfo(
                "EP-133 Device Library",
                "Wait for the active device download to finish before reconnecting.",
            )
            return
        original_connect_live(self, *args, **kwargs)

    def _disconnect_live(self, *args, **kwargs) -> None:
        if self._device_library_transfer_lock.locked():
            if not kwargs.get("silent", False):
                messagebox.showinfo(
                    "EP-133 Device Library",
                    "Wait for the active device download to finish before disconnecting.",
                )
            return
        original_disconnect_live(self, *args, **kwargs)

    def _close(self) -> None:
        if self._device_library_transfer_lock.locked():
            messagebox.showinfo(
                "EP-133 Device Library",
                "A device file is still downloading. Keep the app open until the "
                "transfer finishes so the EP-133 read transaction is not abandoned.",
            )
            return
        original_close(self)

    def _show_device_library(self) -> None:
        if self.device_library_window and self.device_library_window.winfo_exists():
            self.device_library_window.lift()
            self._refresh_device_library_rows()
            return

        win = tk.Toplevel(self.root)
        win.title("EP-133 Device Sample Library")
        win.geometry("1040x690")
        win.minsize(860, 560)
        win.configure(bg="#d8d4c8")
        win.columnconfigure(0, weight=3)
        win.columnconfigure(1, weight=2)
        win.rowconfigure(1, weight=1)
        self.device_library_window = win

        toolbar = tk.Frame(win, bg="#171915", padx=8, pady=7)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        for column in range(5):
            toolbar.columnconfigure(column, weight=1, uniform="device-library-actions")
        actions = (
            (
                "REFRESH",
                self._refresh_device_library_rows,
                "Reload sound rows from the live device tree or latest integrity snapshot.",
            ),
            (
                "SCAN",
                lambda: self._scan_complete_device_tree(auto=False),
                "Run a complete read-only device file scan.",
            ),
            (
                "FETCH + WAV",
                lambda: self._download_selected_device_sound(True),
                "Download the selected PCM, verify CRC/SHA-256, and export a local WAV.",
            ),
            (
                "FETCH RAW",
                lambda: self._download_selected_device_sound(False),
                "Download and integrity-check the selected device file without WAV conversion.",
            ),
            (
                "PLAY LOCAL",
                self._play_selected_device_artifact,
                "Preview the downloaded WAV through Windows audio.",
            ),
            ("STOP LOCAL", stop_wav, "Stop local WAV playback."),
            (
                "PLAY DEVICE",
                self._play_selected_device_library_sound,
                "Ask the EP-133 to audition the selected device sound.",
            ),
            (
                "STOP DEVICE",
                self._stop_selected_device_library_sound,
                "Stop EP-133 file audition.",
            ),
            (
                "OPEN FOLDER",
                self._open_selected_device_artifact,
                "Open the immutable content-addressed download folder.",
            ),
        )
        for index, (label, command, tip) in enumerate(actions):
            button = tk.Button(toolbar, text=label, command=command, bg="#efeadf", padx=7)
            button.grid(
                row=index // 5,
                column=index % 5,
                sticky="ew",
                padx=3,
                pady=3,
            )
            self._tip(button, tip)

        table_shell = tk.Frame(win, bg="#d8d4c8", padx=8, pady=8)
        table_shell.grid(row=1, column=0, sticky="nsew")
        table_shell.columnconfigure(0, weight=1)
        table_shell.rowconfigure(0, weight=1)
        columns = ("slot", "node", "bytes", "local", "integrity")
        tree = ttk.Treeview(table_shell, columns=columns, show="tree headings")
        tree.heading("#0", text="Device Sound")
        tree.column("#0", width=190, anchor="w", stretch=True)
        widths = {"slot": 55, "node": 70, "bytes": 90, "local": 80, "integrity": 105}
        for column in columns:
            tree.heading(column, text=column.title())
            tree.column(column, width=widths[column], anchor="w")
        y_scroll = ttk.Scrollbar(table_shell, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=y_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        tree.bind("<<TreeviewSelect>>", lambda _event: self._device_library_selection_changed())
        tree.bind("<Double-1>", lambda _event: self._play_selected_device_artifact())
        self._tip(
            tree,
            "All visible /sounds/*.pcm files. Downloaded rows point to immutable "
            "SHA-256 bundles and locally playable WAV files.",
        )
        self.device_library_tree = tree

        detail = tk.Frame(win, bg="#bdb7aa", padx=10, pady=10)
        detail.grid(row=1, column=1, sticky="nsew", padx=(0, 8), pady=8)
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(0, weight=2)
        detail.rowconfigure(1, weight=3)
        canvas = tk.Canvas(detail, bg="#11120f", highlightthickness=0, height=220)
        canvas.grid(row=0, column=0, sticky="nsew")
        self.device_library_waveform = canvas
        self._tip(
            canvas,
            "Peak waveform generated from the downloaded local WAV; no device write is involved.",
        )

        metadata = tk.Text(
            detail,
            bg="#171915",
            fg="#f3f1de",
            insertbackground="#f3f1de",
            wrap=tk.WORD,
            height=16,
        )
        metadata.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        metadata.configure(state=tk.DISABLED)
        self.device_library_metadata_text = metadata
        self._tip(
            metadata,
            "Verified device metadata, hashes, PCM format, and local artifact paths.",
        )

        footer = tk.Frame(win, bg="#d8d4c8", padx=8, pady=0)
        footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        footer.columnconfigure(0, weight=1)
        progress = ttk.Progressbar(
            footer,
            variable=self.device_library_progress,
            maximum=100,
        )
        progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        status = tk.Label(
            footer,
            textvariable=self.device_library_status,
            bg="#d8d4c8",
            font=("Segoe UI", 10, "bold"),
        )
        status.grid(row=0, column=1, sticky="e")
        self._tip(progress, "Progress for the current read-only file transfer.")
        self._tip(status, "Current device library operation and integrity result.")
        self._refresh_device_library_rows()

    def _show_device_library_help(self) -> None:
        messagebox.showinfo(
            "EP-133 Device Library Guide",
            "\n".join(
                [
                    "REFRESH loads sounds from the live tree or latest integrity snapshot.",
                    "SCAN refreshes the complete read-only device tree.",
                    "FETCH + WAV downloads raw PCM, metadata, verifies hashes, and creates WAV.",
                    "FETCH RAW preserves the exact device bytes without WAV conversion.",
                    "PLAY LOCAL previews a downloaded WAV on this computer.",
                    "PLAY DEVICE and STOP DEVICE control EP-133 file audition.",
                    "OPEN FOLDER opens the immutable SHA-256 bundle.",
                    "",
                    "Downloads are read-only and cannot be canceled mid-file. The app "
                    "blocks disconnect, reconnect, and close until every declared page "
                    "is consumed.",
                    "Project directories can be downloaded from Hardware Files using "
                    "Download Selected Hardware Node. Restore and other writes remain "
                    "blocked.",
                ]
            ),
        )

    def _refresh_device_library_rows(self) -> None:
        tree = self.device_library_tree
        if tree is None or not tree.winfo_exists():
            return
        selected_node = None
        selection = tree.selection()
        if selection:
            selected_node = self.device_library_entries.get(selection[0], {}).get("node")

        entries = self._collect_device_sound_entries()
        self.device_library_entries.clear()
        for item in tree.get_children(""):
            tree.delete(item)
        for entry in entries:
            node = int(entry["node"])
            iid = f"node-{node}"
            artifact = find_latest_device_artifact(
                self.project_root / "device_library",
                node,
            )
            local = "WAV" if artifact and artifact.wav_path else ("RAW" if artifact else "-")
            integrity = "-"
            if artifact:
                manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
                match = manifest.get("crc_matches_metadata")
                integrity = "CRC OK" if match is True else ("SHA-256" if match is None else "CRC FAIL")
            self.device_library_entries[iid] = {**entry, "artifact": artifact}
            tree.insert(
                "",
                tk.END,
                iid=iid,
                text=str(entry["name"]),
                values=(
                    entry.get("slot", ""),
                    node,
                    _format_bytes(int(entry.get("size") or 0)),
                    local,
                    integrity,
                ),
            )
            if selected_node == node:
                tree.selection_set(iid)
                tree.see(iid)
        self.device_library_status.set(f"{len(entries)} device sounds / read-only")
        if tree.selection():
            self._device_library_selection_changed()

    def _collect_device_sound_entries(self) -> list[dict[str, object]]:
        entries: dict[int, dict[str, object]] = {}
        tree = getattr(self, "hardware_tree", None)
        if tree is not None:

            def walk(item: str) -> None:
                values = tree.item(item, "values")
                path = str(item)
                if len(values) >= 3:
                    try:
                        node = int(values[0])
                    except (TypeError, ValueError):
                        node = -1
                    kind = str(values[1])
                    size = _parse_int(values[2])
                    if node >= 0 and kind == "file" and path.casefold().startswith("/sounds/"):
                        name = str(tree.item(item, "text") or Path(path).name)
                        entries[node] = _sound_entry(node, name, path, size)
                for child in tree.get_children(item):
                    walk(child)

            for root_item in tree.get_children(""):
                walk(root_item)

        if not entries:
            snapshot = self.project_root / "ep133_device_snapshot.json"
            for entry in load_snapshot_sound_entries(snapshot):
                entries[int(entry["node"])] = entry
        return sorted(
            entries.values(),
            key=lambda item: (int(item.get("slot") or 10000), int(item["node"])),
        )

    def _selected_device_library_entry(self, *, quiet: bool = False) -> dict[str, object] | None:
        tree = self.device_library_tree
        if tree is None:
            return None
        selected = tree.selection()
        if not selected:
            if not quiet:
                messagebox.showinfo("EP-133 Device Library", "Select a device sound first.")
            return None
        return self.device_library_entries.get(selected[0])

    def _download_selected_device_sound(self, export_wav: bool) -> None:
        entry = self._selected_device_library_entry()
        if entry is None:
            return
        self._start_device_download(entry, export_wav=export_wav, include_metadata=True)

    def _download_selected_hardware_node(self) -> None:
        row = self._selected_hardware_row()
        if not row:
            return
        entry = {
            "node": int(row["node"]),
            "name": str(row["name"]),
            "path": str(row.get("path") or row["name"]),
            "size": _parse_int(row.get("size")),
            "kind": str(row["kind"]),
        }
        is_sound = str(entry["path"]).casefold().startswith("/sounds/")
        self._start_device_download(
            entry,
            export_wav=is_sound,
            include_metadata=is_sound,
        )

    def _start_device_download(
        self,
        entry: dict[str, object],
        *,
        export_wav: bool,
        include_metadata: bool,
    ) -> None:
        if not self.live_input_port or not self.live_output_port:
            messagebox.showinfo("EP-133 Device Library", "Connect EP-133 live before downloading.")
            return
        if not self.app_settings.sysex_enabled:
            messagebox.showinfo("EP-133 Device Library", "SysEx is disabled in Settings.")
            return
        if self._hardware_scan_lock.locked():
            messagebox.showinfo(
                "EP-133 Device Library",
                "Wait for the device scan to finish before starting a download.",
            )
            return
        if self._device_library_transfer_lock.locked():
            messagebox.showinfo("EP-133 Device Library", "A device download is already running.")
            return

        node = int(entry["node"])
        name = str(entry["name"])
        self.device_library_progress.set(0)
        self.device_library_status.set(f"preparing {name}")

        def worker() -> None:
            if not self._device_library_transfer_lock.acquire(blocking=False):
                return
            try:

                def exchange(frame: bytes, timeout: float) -> list[bytes]:
                    responses = self._send_sysex_and_decode("device-download", frame, timeout)
                    return [bytes.fromhex(response.raw_hex) for response in responses]

                def progress(done: int, total: int, stage: str) -> None:
                    self.device_library_queue.put(
                        ("progress", node, name, done, total, stage)
                    )

                client = DeviceFileClient(
                    exchange,
                    limits=DeviceDownloadLimits(
                        timeout_sec=self.app_settings.sysex_timeout_sec,
                        max_file_bytes=128 * 1024 * 1024,
                    ),
                )
                download = client.download(
                    node,
                    include_metadata=include_metadata,
                    progress=progress,
                )
                artifact = save_device_download(
                    download,
                    self.project_root / "device_library",
                    export_wav=export_wav,
                )
                self.device_library_queue.put(("complete", entry, download, artifact))
            except Exception as exc:
                self.device_library_queue.put(("error", exc))
            finally:
                self._device_library_transfer_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    def _poll_device_library_queue(self) -> None:
        while True:
            try:
                event = self.device_library_queue.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "progress":
                _, _node, name, done, total, stage = event
                percent = 100.0 if not total else (float(done) / float(total)) * 100.0
                self.device_library_progress.set(percent)
                self.device_library_status.set(
                    f"{name}: {stage} {_format_bytes(int(done))} / "
                    f"{_format_bytes(int(total))}"
                )
            elif kind == "complete":
                _, entry, download, artifact = event
                self.device_library_progress.set(100)
                integrity = (
                    "CRC verified"
                    if download.crc_matches_metadata is True
                    else "SHA-256 captured"
                )
                self.device_library_status.set(
                    f"{download.file_name}: {integrity}, {download.pages} pages"
                )
                self._set_action(
                    f"downloaded device node {download.node_id}: {integrity}"
                )
                if artifact.wav_path:
                    slot = _parse_slot(download.file_name)
                    try:
                        self.sample_library.add_wav(
                            artifact.wav_path,
                            slot=slot if slot is not None else None,
                        )
                        self._refresh_sample_tree()
                    except Exception as exc:
                        self._log(f"local sample registration failed: {exc}")
                if artifact.project_analysis_path:
                    self._show_project_archive_analysis(artifact)
                self._refresh_device_library_rows()
                iid = f"node-{int(entry['node'])}"
                if self.device_library_tree and self.device_library_tree.exists(iid):
                    self.device_library_tree.selection_set(iid)
                    self.device_library_tree.see(iid)
                    self._device_library_selection_changed()
            elif kind == "error":
                self.device_library_progress.set(0)
                self.device_library_status.set(f"download failed: {event[1]}")
                self._log(f"device download failed: {event[1]}")
                messagebox.showerror("EP-133 Device Library", str(event[1]))
        if self.root.winfo_exists():
            self.root.after(100, self._poll_device_library_queue)

    def _device_library_selection_changed(self) -> None:
        entry = self._selected_device_library_entry(quiet=True)
        if entry is None:
            return
        artifact = find_latest_device_artifact(
            self.project_root / "device_library",
            int(entry["node"]),
        )
        entry["artifact"] = artifact
        self._draw_device_library_waveform(artifact)
        lines = [
            f"Device path: {entry['path']}",
            f"Node: {entry['node']}",
            f"Declared size: {int(entry.get('size') or 0):,} bytes",
        ]
        if artifact:
            manifest = json.loads(artifact.manifest_path.read_text(encoding="utf-8"))
            metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
            lines.extend(
                [
                    "",
                    f"SHA-256: {manifest['sha256']}",
                    f"CRC32: {manifest['crc32']}",
                    f"Metadata CRC: {manifest.get('metadata_crc32')}",
                    f"CRC match: {manifest.get('crc_matches_metadata')}",
                    f"Pages: {manifest['pages']}",
                    f"Raw: {artifact.raw_path}",
                    f"WAV: {artifact.wav_path or '-'}",
                    "",
                    "Device metadata:",
                    json.dumps(metadata, indent=2, sort_keys=True),
                ]
            )
        else:
            lines.extend(["", "Not downloaded locally."])
        text = self.device_library_metadata_text
        text.configure(state=tk.NORMAL)
        text.delete("1.0", tk.END)
        text.insert("1.0", "\n".join(lines))
        text.configure(state=tk.DISABLED)

    def _draw_device_library_waveform(
        self,
        artifact: DeviceDownloadArtifact | None,
    ) -> None:
        canvas = getattr(self, "device_library_waveform", None)
        if canvas is None:
            return
        canvas.delete("all")
        canvas.update_idletasks()
        width = max(40, canvas.winfo_width())
        height = max(40, canvas.winfo_height())
        center = height / 2
        canvas.create_line(0, center, width, center, fill="#56604c")
        if not artifact or not artifact.wav_path or not artifact.wav_path.exists():
            canvas.create_text(
                width / 2,
                center,
                text="FETCH + WAV TO BUILD WAVEFORM",
                fill="#d7f58a",
                font=("Consolas", 11, "bold"),
            )
            return
        peaks = wav_peak_envelope(artifact.wav_path, points=max(32, width // 2))
        if not peaks:
            return
        x_scale = width / max(1, len(peaks) - 1)
        for index, (minimum, maximum) in enumerate(peaks):
            x = index * x_scale
            canvas.create_line(
                x,
                center + minimum * (height * 0.44),
                x,
                center + maximum * (height * 0.44),
                fill="#d7f58a",
            )

    def _play_selected_device_artifact(self) -> None:
        entry = self._selected_device_library_entry()
        if entry is None:
            return
        artifact = find_latest_device_artifact(
            self.project_root / "device_library",
            int(entry["node"]),
        )
        if not artifact or not artifact.wav_path:
            messagebox.showinfo(
                "EP-133 Device Library",
                "Download this sound with FETCH + WAV before local preview.",
            )
            return
        try:
            play_wav(artifact.wav_path)
            self.device_library_status.set(f"playing local {artifact.wav_path.name}")
        except Exception as exc:
            messagebox.showerror("EP-133 Device Library", str(exc))

    def _play_selected_device_library_sound(self) -> None:
        if self._select_device_library_hardware_row():
            self._play_selected_device_file()

    def _stop_selected_device_library_sound(self) -> None:
        if self._select_device_library_hardware_row():
            self._stop_selected_device_file()

    def _select_device_library_hardware_row(self) -> bool:
        entry = self._selected_device_library_entry()
        if entry is None:
            return False
        path = str(entry["path"])
        if not self.hardware_tree.exists(path):
            messagebox.showinfo(
                "EP-133 Device Library",
                "Run SCAN so the selected sound exists in the live hardware tree.",
            )
            return False
        self.hardware_tree.selection_set(path)
        self.hardware_tree.see(path)
        return True

    def _open_selected_device_artifact(self) -> None:
        entry = self._selected_device_library_entry()
        if entry is None:
            return
        artifact = find_latest_device_artifact(
            self.project_root / "device_library",
            int(entry["node"]),
        )
        if not artifact:
            messagebox.showinfo("EP-133 Device Library", "This sound has no local bundle yet.")
            return
        os.startfile(artifact.bundle_dir)

    def _show_project_archive_analysis(
        self,
        artifact: DeviceDownloadArtifact | None = None,
    ) -> None:
        if artifact is None:
            row = self._selected_hardware_row()
            if not row:
                return
            artifact = find_latest_device_artifact(
                self.project_root / "device_library",
                int(row["node"]),
            )
        if not artifact or not artifact.project_analysis_path:
            messagebox.showinfo(
                "EP-133 Project Inspector",
                "The selected node has no decoded local project archive. "
                "Download the project directory node first.",
            )
            return
        try:
            analysis = json.loads(
                artifact.project_analysis_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("EP-133 Project Inspector", str(exc))
            return

        win = tk.Toplevel(self.root)
        win.title("EP-133 Project Inspector")
        win.geometry("1040x690")
        win.minsize(820, 520)
        win.configure(bg="#d8d4c8")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        header = tk.Label(
            win,
            text=(
                f"PROJECT ARCHIVE  /  {analysis.get('assigned_pad_count', 0)} "
                f"ASSIGNED PADS  /  {analysis.get('file_count', 0)} FILES"
            ),
            bg="#171915",
            fg="#d7f58a",
            font=("Consolas", 13, "bold"),
            anchor="w",
            padx=10,
            pady=7,
        )
        header.grid(row=0, column=0, sticky="ew")
        self._tip(
            header,
            "Read-only interpretation of pads/{group}/p{number}; the sound id is decoded as signed little-endian int16 at byte offset 1.",
        )
        notebook = ttk.Notebook(win)
        notebook.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)

        shell = tk.Frame(notebook, bg="#d8d4c8")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)
        notebook.add(
            shell,
            text=f"Pad Map ({len(analysis.get('assignments') or [])})",
        )
        tree = ttk.Treeview(
            shell,
            columns=("group", "pad", "sound", "assigned", "bytes", "path"),
            show="headings",
        )
        widths = {
            "group": 60,
            "pad": 60,
            "sound": 80,
            "assigned": 80,
            "bytes": 70,
            "path": 260,
        }
        for column, width in widths.items():
            tree.heading(column, text=column.title())
            tree.column(column, width=width, anchor="center" if column != "path" else "w")
        scroll = ttk.Scrollbar(shell, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        for index, item in enumerate(analysis.get("assignments") or []):
            if not isinstance(item, dict):
                continue
            tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    item.get("group"),
                    item.get("pad"),
                    item.get("sound_id"),
                    "yes" if item.get("assigned") else "no",
                    item.get("byte_count"),
                    item.get("path"),
                ),
            )

        selected_pad_status = tk.StringVar(
            value="Select one pad assignment to map it to the physical device."
        )

        def pad_selection_changed(_event=None) -> None:
            selected = tree.selection()
            if not selected:
                selected_pad_status.set(
                    "Select one pad assignment to map it to the physical device."
                )
                return
            values = tree.item(selected[0], "values")
            if len(values) < 4:
                return
            group = str(values[0])
            pad = int(values[1])
            note = gui_module.PAD_NOTES[group][pad - 1]
            sound = values[2]
            assigned = str(values[3]).casefold() == "yes"
            selected_pad_status.set(
                f"{group}{pad:02d} -> MIDI note {note} / "
                f"archive sound {sound if assigned else 'unassigned'}"
            )

        def trigger_selected_device_pad() -> None:
            selected = tree.selection()
            if not selected:
                messagebox.showinfo(
                    "EP-133 Project Inspector",
                    "Select one pad assignment first.",
                )
                return
            values = tree.item(selected[0], "values")
            group = str(values[0])
            pad = int(values[1])
            self.group.set(group)
            self._trigger_pad(pad - 1)
            selected_pad_status.set(
                f"Triggered current device pad {group}{pad:02d}; "
                "the downloaded archive may not be the project currently loaded."
            )

        tree.bind("<<TreeviewSelect>>", pad_selection_changed)
        self._tip(
            tree,
            "Pad-to-sound assignments decoded in memory. No archive member is extracted and no device write is sent.",
        )

        records_shell = tk.Frame(notebook, bg="#d8d4c8")
        records_shell.columnconfigure(0, weight=1)
        records_shell.rowconfigure(0, weight=1)
        records = analysis.get("binary_records") or []
        notebook.add(records_shell, text=f"Binary Records ({len(records)})")
        record_columns = (
            "path",
            "kind",
            "group",
            "index",
            "bytes",
            "nonzero",
            "crc32",
            "sha256",
            "preview",
        )
        record_tree = ttk.Treeview(
            records_shell,
            columns=record_columns,
            show="headings",
        )
        record_widths = {
            "path": 180,
            "kind": 90,
            "group": 55,
            "index": 55,
            "bytes": 65,
            "nonzero": 70,
            "crc32": 95,
            "sha256": 110,
            "preview": 280,
        }
        for column in record_columns:
            record_tree.heading(column, text=column.title())
            record_tree.column(
                column,
                width=record_widths[column],
                anchor="w" if column in {"path", "preview"} else "center",
                stretch=column in {"path", "preview"},
            )
        record_y = ttk.Scrollbar(
            records_shell,
            orient=tk.VERTICAL,
            command=record_tree.yview,
        )
        record_x = ttk.Scrollbar(
            records_shell,
            orient=tk.HORIZONTAL,
            command=record_tree.xview,
        )
        record_tree.configure(
            yscrollcommand=record_y.set,
            xscrollcommand=record_x.set,
        )
        record_tree.grid(row=0, column=0, sticky="nsew")
        record_y.grid(row=0, column=1, sticky="ns")
        record_x.grid(row=1, column=0, sticky="ew")
        for index, item in enumerate(records):
            if not isinstance(item, dict):
                continue
            record_tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    item.get("path"),
                    item.get("kind"),
                    item.get("group") or "-",
                    item.get("index") if item.get("index") is not None else "-",
                    item.get("byte_count"),
                    item.get("nonzero_byte_count"),
                    item.get("crc32"),
                    str(item.get("sha256") or "")[:12],
                    item.get("preview_hex"),
                ),
            )
        self._tip(
            record_tree,
            "Opaque project members. Hashes and previews are evidence for controlled comparisons; field meanings are intentionally not guessed.",
        )

        actions = tk.Frame(win, bg="#d8d4c8", padx=8)
        actions.grid(row=2, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        selected_label = tk.Label(
            actions,
            textvariable=selected_pad_status,
            bg="#d8d4c8",
            anchor="w",
        )
        selected_label.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        trigger = tk.Button(
            actions,
            text="TRIGGER CURRENT DEVICE PAD",
            command=trigger_selected_device_pad,
            bg="#efeadf",
        )
        trigger.grid(row=0, column=1, sticky="e")
        self._tip(
            selected_label,
            "Maps the archived group/pad location to the verified EP-133 note range A36-47, B48-59, C60-71, or D72-83.",
        )
        self._tip(
            trigger,
            "Send note on/off for the selected physical pad location. This auditions the project currently active on EP-133, which may differ from this archive.",
        )
        footer = tk.Label(
            win,
            text=(
                f"SHA-256 {analysis.get('sha256', '-')}\n"
                f"Archive {analysis.get('byte_count', 0):,} bytes  |  "
                f"Other files {len(analysis.get('other_files') or [])}  |  "
                f"{artifact.project_analysis_path}"
            ),
            bg="#171915",
            fg="#f3f1de",
            justify=tk.LEFT,
            anchor="w",
            padx=10,
            pady=7,
            wraplength=1000,
        )
        footer.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self._tip(footer, "Integrity hash, archive summary, and local analysis path.")

    app_class.__init__ = __init__
    app_class._build_menu = _build_menu
    app_class._build_sample_library = _build_sample_library
    app_class._connect_live = _connect_live
    app_class._disconnect_live = _disconnect_live
    app_class._close = _close
    app_class._show_device_library = _show_device_library
    app_class._show_device_library_help = _show_device_library_help
    app_class._refresh_device_library_rows = _refresh_device_library_rows
    app_class._collect_device_sound_entries = _collect_device_sound_entries
    app_class._selected_device_library_entry = _selected_device_library_entry
    app_class._download_selected_device_sound = _download_selected_device_sound
    app_class._download_selected_hardware_node = _download_selected_hardware_node
    app_class._start_device_download = _start_device_download
    app_class._poll_device_library_queue = _poll_device_library_queue
    app_class._device_library_selection_changed = _device_library_selection_changed
    app_class._draw_device_library_waveform = _draw_device_library_waveform
    app_class._play_selected_device_artifact = _play_selected_device_artifact
    app_class._play_selected_device_library_sound = _play_selected_device_library_sound
    app_class._stop_selected_device_library_sound = _stop_selected_device_library_sound
    app_class._select_device_library_hardware_row = _select_device_library_hardware_row
    app_class._open_selected_device_artifact = _open_selected_device_artifact
    app_class._show_project_archive_analysis = _show_project_archive_analysis
    app_class._device_library_patch_installed = True


def load_snapshot_sound_entries(path: str | Path) -> list[dict[str, object]]:
    snapshot_path = Path(path)
    if not snapshot_path.exists():
        return []
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    records = payload.get("records") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        return []
    entries: list[dict[str, object]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        path_value = str(record.get("path") or "")
        if record.get("kind") != "file" or not path_value.casefold().startswith("/sounds/"):
            continue
        try:
            node = int(record.get("node_id"))
        except (TypeError, ValueError):
            continue
        entries.append(
            _sound_entry(
                node,
                str(record.get("name") or Path(path_value).name),
                path_value,
                _parse_int(record.get("size")),
            )
        )
    return sorted(
        entries,
        key=lambda entry: (int(entry.get("slot") or 10000), int(entry["node"])),
    )


def _sound_entry(node: int, name: str, path: str, size: int) -> dict[str, object]:
    return {
        "node": node,
        "name": name,
        "path": path,
        "size": size,
        "kind": "file",
        "slot": _parse_slot(name),
    }


def _parse_slot(name: str) -> int | None:
    stem = Path(str(name)).stem
    try:
        value = int(stem)
    except ValueError:
        return None
    return value if 0 <= value <= 999 else None


def _parse_int(value: object) -> int:
    try:
        return int(str(value).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0


def _format_bytes(value: int) -> str:
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value} B"
