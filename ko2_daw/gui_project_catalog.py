"""Stable EP-133 project catalog, backup, and structural comparison window."""

from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import threading
from typing import Any

from ko2_daw.device_transfer import DeviceDownloadLimits, DeviceFileClient, find_latest_device_artifact
from ko2_daw.project_archive import compare_project_archives
from ko2_daw.project_catalog import (
    ProjectBackupEvent,
    backup_project_archives,
    build_project_catalog,
    save_project_catalog,
)


def apply_project_catalog_patch(gui_module: Any) -> None:
    """Add a read-only, integrity-checked project manager to the stable GUI."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_project_catalog_patch_installed", False):
        return

    tk = gui_module.tk
    ttk = gui_module.ttk
    messagebox = gui_module.messagebox
    original_init = app_class.__init__
    original_build_menu = app_class._build_menu

    def __init__(self, root) -> None:
        self.project_catalog_window = None
        self.project_catalog_tree = None
        self.project_catalog_text = None
        self.project_catalog_entries: dict[str, object] = {}
        self.project_catalog_queue: queue.Queue[tuple[object, ...]] = queue.Queue()
        self.project_catalog_status = tk.StringVar(value="project catalog ready")
        self.project_catalog_progress = tk.DoubleVar(value=0)
        original_init(self, root)
        self.root.after(120, self._poll_project_catalog_queue)

    def _build_menu(self) -> None:
        original_build_menu(self)
        menu = self.root.nametowidget(self.root.cget("menu"))
        projects = tk.Menu(menu, tearoff=False)
        projects.add_command(
            label="Open Project Manager",
            command=self._show_project_catalog,
        )
        projects.add_command(
            label="Backup Missing Projects",
            command=lambda: self._backup_project_catalog(False),
        )
        projects.add_command(
            label="Refresh All Project Backups",
            command=lambda: self._backup_project_catalog(True),
        )
        projects.add_separator()
        projects.add_command(
            label="Project Manager Guide",
            command=self._show_project_catalog_help,
        )
        menu.add_cascade(label="Projects", menu=projects)

    def _show_project_catalog(self) -> None:
        if (
            self.project_catalog_window
            and self.project_catalog_window.winfo_exists()
        ):
            self.project_catalog_window.lift()
            self._refresh_project_catalog()
            return

        win = tk.Toplevel(self.root)
        win.title("EP-133 Project Manager")
        win.geometry("1180x720")
        win.minsize(940, 580)
        win.configure(bg="#d8d4c8")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        self.project_catalog_window = win

        toolbar = tk.Frame(win, bg="#171915", padx=8, pady=7)
        toolbar.grid(row=0, column=0, sticky="ew")
        actions = (
            (
                "REFRESH LOCAL",
                self._refresh_project_catalog,
                "Verify all latest local project bundles and rebuild project_catalog.json.",
            ),
            (
                "BACKUP MISSING",
                lambda: self._backup_project_catalog(False),
                "Download only missing or invalid project slots through read-only SysEx.",
            ),
            (
                "REFRESH ALL",
                lambda: self._backup_project_catalog(True),
                "Download all nine project archives again and retain versions by SHA-256.",
            ),
            (
                "COMPARE TWO",
                self._compare_selected_projects,
                "Select exactly two project rows to compare pads and opaque binary byte ranges.",
            ),
            (
                "PAD MAP",
                self._inspect_selected_project,
                "Open the decoded pad-to-sound map for the selected project.",
            ),
            (
                "OPEN FOLDER",
                self._open_selected_project_folder,
                "Open the selected immutable SHA-256 bundle in Windows Explorer.",
            ),
            (
                "HELP",
                self._show_project_catalog_help,
                "Explain project backup, integrity, comparison, and safety behavior.",
            ),
        )
        for column, (label, command, tip) in enumerate(actions):
            toolbar.columnconfigure(column, weight=1, uniform="project-actions")
            button = tk.Button(
                toolbar,
                text=label,
                command=command,
                bg="#efeadf",
                padx=6,
            )
            button.grid(row=0, column=column, sticky="ew", padx=3)
            self._tip(button, tip)

        paned = tk.PanedWindow(
            win,
            orient=tk.HORIZONTAL,
            sashwidth=6,
            bg="#807b70",
            bd=0,
        )
        paned.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)

        table_shell = tk.Frame(paned, bg="#d8d4c8")
        table_shell.columnconfigure(0, weight=1)
        table_shell.rowconfigure(0, weight=1)
        columns = (
            "node",
            "bytes",
            "pads",
            "patterns",
            "records",
            "status",
            "hash",
        )
        tree = ttk.Treeview(
            table_shell,
            columns=columns,
            show="tree headings",
            selectmode="extended",
        )
        tree.heading("#0", text="Project")
        tree.column("#0", width=90, anchor="w", stretch=False)
        widths = {
            "node": 72,
            "bytes": 88,
            "pads": 58,
            "patterns": 70,
            "records": 72,
            "status": 80,
            "hash": 116,
        }
        for column in columns:
            tree.heading(column, text=column.title())
            tree.column(column, width=widths[column], anchor="center")
        scroll = ttk.Scrollbar(
            table_shell,
            orient=tk.VERTICAL,
            command=tree.yview,
        )
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        tree.bind(
            "<<TreeviewSelect>>",
            lambda _event: self._project_catalog_selection_changed(),
        )
        self._tip(
            tree,
            "Nine EP-133 project slots. Ctrl-click selects two rows for structural comparison.",
        )
        self.project_catalog_tree = tree

        detail_shell = tk.Frame(paned, bg="#bdb7aa", padx=8, pady=8)
        detail_shell.columnconfigure(0, weight=1)
        detail_shell.rowconfigure(1, weight=1)
        detail_header = tk.Label(
            detail_shell,
            text="PROJECT STRUCTURE / INTEGRITY",
            bg="#171915",
            fg="#d7f58a",
            font=("Consolas", 12, "bold"),
            anchor="w",
            padx=8,
            pady=6,
        )
        detail_header.grid(row=0, column=0, sticky="ew")
        detail = tk.Text(
            detail_shell,
            bg="#171915",
            fg="#f3f1de",
            insertbackground="#f3f1de",
            wrap=tk.WORD,
            padx=8,
            pady=8,
        )
        detail_scroll = ttk.Scrollbar(
            detail_shell,
            orient=tk.VERTICAL,
            command=detail.yview,
        )
        detail.configure(yscrollcommand=detail_scroll.set, state=tk.DISABLED)
        detail.grid(row=1, column=0, sticky="nsew")
        detail_scroll.grid(row=1, column=1, sticky="ns")
        self._tip(
            detail,
            "Verified manifest data and opaque record sizes. Unknown bytes are never labeled as controls without evidence.",
        )
        self.project_catalog_text = detail

        paned.add(table_shell, minsize=550, width=650)
        paned.add(detail_shell, minsize=330)

        footer = tk.Frame(win, bg="#d8d4c8", padx=8)
        footer.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        footer.columnconfigure(0, weight=1)
        progress = ttk.Progressbar(
            footer,
            variable=self.project_catalog_progress,
            maximum=100,
        )
        progress.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        status = tk.Label(
            footer,
            textvariable=self.project_catalog_status,
            bg="#d8d4c8",
            font=("Segoe UI", 10, "bold"),
        )
        status.grid(row=0, column=1, sticky="e")
        self._tip(
            progress,
            "Composite progress across all nine complete project transfers.",
        )
        self._tip(status, "Current catalog verification or device backup state.")
        self._refresh_project_catalog()

    def _refresh_project_catalog(self) -> None:
        try:
            catalog = build_project_catalog(
                self.project_root / "device_library",
            )
            path = save_project_catalog(catalog)
        except Exception as exc:
            self.project_catalog_status.set(f"catalog failed: {exc}")
            self._log(f"project catalog failed: {exc}")
            return
        tree = self.project_catalog_tree
        if tree is None or not tree.winfo_exists():
            return
        selected_slots = {
            int(str(iid).split("-", 1)[1])
            for iid in tree.selection()
            if str(iid).startswith("slot-")
        }
        for iid in tree.get_children(""):
            tree.delete(iid)
        self.project_catalog_entries.clear()
        for entry in catalog.entries:
            iid = f"slot-{entry.slot}"
            self.project_catalog_entries[iid] = entry
            tree.insert(
                "",
                tk.END,
                iid=iid,
                text=f"{entry.slot:02d}",
                values=(
                    entry.node_id,
                    _format_bytes(entry.byte_count),
                    entry.assigned_pad_count,
                    entry.pattern_count,
                    entry.file_count,
                    entry.status.upper(),
                    entry.sha256[:12] if entry.sha256 else "-",
                ),
            )
            if entry.slot in selected_slots:
                tree.selection_add(iid)
        self.project_catalog_status.set(
            f"{catalog.verified_count}/9 verified / {catalog.integrity_sha256[:12]}"
        )
        self._set_action(f"project catalog verified: {catalog.verified_count}/9")
        self._log(
            f"project catalog: {path} | verified={catalog.verified_count} "
            f"sha256={catalog.integrity_sha256}"
        )
        if tree.selection():
            self._project_catalog_selection_changed()
        elif catalog.entries:
            tree.selection_set("slot-1")
            self._project_catalog_selection_changed()

    def _selected_project_entries(self) -> list[object]:
        tree = self.project_catalog_tree
        if tree is None:
            return []
        return [
            self.project_catalog_entries[iid]
            for iid in tree.selection()
            if iid in self.project_catalog_entries
        ]

    def _project_catalog_selection_changed(self) -> None:
        entries = self._selected_project_entries()
        if not entries:
            return
        if len(entries) == 2:
            text = (
                f"Projects {entries[0].slot:02d} and {entries[1].slot:02d} selected.\n\n"
                "Use COMPARE TWO to calculate exact pad changes and changed byte ranges "
                "for opaque project records."
            )
        else:
            entry = entries[0]
            text = "\n".join(
                [
                    f"PROJECT {entry.slot:02d}",
                    f"Status: {entry.status}",
                    f"Node: {entry.node_id}",
                    f"Archive bytes: {entry.byte_count:,}",
                    f"Transfer pages: {entry.pages}",
                    f"SHA-256: {entry.sha256 or '-'}",
                    f"Captured: {entry.captured_at or '-'}",
                    "",
                    f"Archive files: {entry.file_count}",
                    f"Archive directories: {entry.directory_count}",
                    f"Assigned pads: {entry.assigned_pad_count} / 48",
                    f"Pattern records: {entry.pattern_count}",
                    f"fx_settings bytes: {entry.fx_settings_bytes}",
                    f"scenes bytes: {entry.scenes_bytes}",
                    f"settings bytes: {entry.settings_bytes}",
                    "",
                    f"Raw: {entry.raw_path or '-'}",
                    f"Bundle: {entry.bundle_dir or '-'}",
                    "",
                    (
                        f"Validation error: {entry.error}"
                        if entry.error
                        else "Integrity: raw SHA-256, bundle path, manifest, and safe TAR parse verified."
                    ),
                ]
            )
        _set_text(self.project_catalog_text, text, tk)

    def _backup_project_catalog(self, force: bool) -> None:
        if not self.live_input_port or not self.live_output_port:
            messagebox.showinfo(
                "EP-133 Project Manager",
                "Connect EP-133 live before backing up projects.",
            )
            return
        if not self.app_settings.sysex_enabled:
            messagebox.showinfo(
                "EP-133 Project Manager",
                "SysEx is disabled in Communication settings.",
            )
            return
        if self._hardware_scan_lock.locked():
            messagebox.showinfo(
                "EP-133 Project Manager",
                "Wait for the active device scan or project backup to finish.",
            )
            return
        if self._device_library_transfer_lock.locked():
            messagebox.showinfo(
                "EP-133 Project Manager",
                "Wait for the active device transfer to finish.",
            )
            return
        if force and not messagebox.askyesno(
            "Refresh All Project Backups",
            "Read all nine project archives again?\n\n"
            "This is read-only. Existing versions remain preserved by SHA-256.",
        ):
            return
        self.project_catalog_progress.set(0)
        self.project_catalog_status.set(
            "preparing all projects" if force else "checking missing projects"
        )

        def worker() -> None:
            transfer_acquired = self._device_library_transfer_lock.acquire(
                blocking=False
            )
            scan_acquired = False
            if not transfer_acquired:
                self.project_catalog_queue.put(
                    ("error", RuntimeError("Another device transfer started first."))
                )
                return
            try:
                scan_acquired = self._hardware_scan_lock.acquire(blocking=False)
                if not scan_acquired:
                    raise RuntimeError("Another device scan started first.")

                def exchange(frame: bytes, timeout: float) -> list[bytes]:
                    responses = self._send_sysex_and_decode(
                        "project-backup",
                        frame,
                        timeout,
                    )
                    return [
                        bytes.fromhex(response.raw_hex) for response in responses
                    ]

                def progress(event: ProjectBackupEvent) -> None:
                    self.project_catalog_queue.put(("progress", event))

                client = DeviceFileClient(
                    exchange,
                    limits=DeviceDownloadLimits(
                        timeout_sec=self.app_settings.sysex_timeout_sec,
                        max_file_bytes=128 * 1024 * 1024,
                    ),
                )
                result = backup_project_archives(
                    client,
                    self.project_root / "device_library",
                    force=force,
                    progress=progress,
                )
                self.project_catalog_queue.put(("complete", result))
            except Exception as exc:
                self.project_catalog_queue.put(("error", exc))
            finally:
                if scan_acquired:
                    self._hardware_scan_lock.release()
                self._device_library_transfer_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    def _poll_project_catalog_queue(self) -> None:
        while True:
            try:
                event = self.project_catalog_queue.get_nowait()
            except queue.Empty:
                break
            if event[0] == "progress":
                progress_event = event[1]
                fraction = 0.0
                if progress_event.bytes_total:
                    fraction = min(
                        1.0,
                        progress_event.bytes_done / progress_event.bytes_total,
                    )
                elif progress_event.stage in {"saved", "skipped-verified"}:
                    fraction = 1.0
                percent = (
                    progress_event.project_index - 1 + fraction
                ) / progress_event.project_total * 100.0
                self.project_catalog_progress.set(percent)
                self.project_catalog_status.set(
                    f"project {progress_event.slot:02d}: "
                    f"{progress_event.stage.replace('-', ' ')} "
                    f"{_format_bytes(progress_event.bytes_done)} / "
                    f"{_format_bytes(progress_event.bytes_total)}"
                )
            elif event[0] == "complete":
                result = event[1]
                self.project_catalog_progress.set(100)
                self.project_catalog_status.set(
                    f"{result.catalog.verified_count}/9 verified / "
                    f"{len(result.downloaded_nodes)} downloaded"
                )
                self._set_action(
                    f"project backup complete: {len(result.downloaded_nodes)} downloaded"
                )
                self._log(
                    f"project backup complete: {result.catalog_path} | "
                    f"downloaded={result.downloaded_nodes} "
                    f"skipped={result.skipped_nodes}"
                )
                self._refresh_project_catalog()
            elif event[0] == "error":
                self.project_catalog_progress.set(0)
                self.project_catalog_status.set(f"project backup failed: {event[1]}")
                self._log(f"project backup failed: {event[1]}")
                messagebox.showerror("EP-133 Project Manager", str(event[1]))
                self._refresh_project_catalog()
        try:
            if self.root.winfo_exists():
                self.root.after(120, self._poll_project_catalog_queue)
        except tk.TclError:
            return

    def _compare_selected_projects(self) -> None:
        entries = self._selected_project_entries()
        if len(entries) != 2:
            messagebox.showinfo(
                "EP-133 Project Comparison",
                "Select exactly two verified project rows. Use Ctrl-click for the second row.",
            )
            return
        before, after = entries
        if not before.verified or not after.verified:
            messagebox.showinfo(
                "EP-133 Project Comparison",
                "Both selected projects must have verified local bundles.",
            )
            return
        try:
            comparison = compare_project_archives(
                Path(before.raw_path).read_bytes(),
                Path(after.raw_path).read_bytes(),
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("EP-133 Project Comparison", str(exc))
            return
        _show_comparison_window(self, before, after, comparison, tk, ttk)

    def _inspect_selected_project(self) -> None:
        entries = self._selected_project_entries()
        if len(entries) != 1:
            messagebox.showinfo(
                "EP-133 Project Manager",
                "Select one project to open its pad map.",
            )
            return
        artifact = find_latest_device_artifact(
            self.project_root / "device_library",
            entries[0].node_id,
        )
        self._show_project_archive_analysis(artifact)

    def _open_selected_project_folder(self) -> None:
        entries = self._selected_project_entries()
        if len(entries) != 1 or not entries[0].bundle_dir:
            messagebox.showinfo(
                "EP-133 Project Manager",
                "Select one verified project bundle.",
            )
            return
        os.startfile(entries[0].bundle_dir)

    def _show_project_catalog_help(self) -> None:
        messagebox.showinfo(
            "EP-133 Project Manager Guide",
            "\n".join(
                [
                    "REFRESH LOCAL verifies manifests, raw SHA-256 hashes, bundle paths, and TAR safety.",
                    "BACKUP MISSING reads only missing or invalid slots and resumes from verified bundles.",
                    "REFRESH ALL reads all nine slots and preserves each distinct version by SHA-256.",
                    "COMPARE TWO reports pad sound-id changes and exact changed ranges in opaque records.",
                    "PAD MAP opens all 48 group/pad sound assignments for one project.",
                    "",
                    "A transfer cannot be canceled mid-project. Disconnect, reconnect, scans, and app close "
                    "remain blocked until the declared archive bytes are consumed.",
                    "The manager sends file INIT/GET only. It does not upload, restore, rename, delete, "
                    "or assign meanings to unverified binary fields.",
                ]
            ),
        )

    app_class.__init__ = __init__
    app_class._build_menu = _build_menu
    app_class._show_project_catalog = _show_project_catalog
    app_class._refresh_project_catalog = _refresh_project_catalog
    app_class._selected_project_entries = _selected_project_entries
    app_class._project_catalog_selection_changed = _project_catalog_selection_changed
    app_class._backup_project_catalog = _backup_project_catalog
    app_class._poll_project_catalog_queue = _poll_project_catalog_queue
    app_class._compare_selected_projects = _compare_selected_projects
    app_class._inspect_selected_project = _inspect_selected_project
    app_class._open_selected_project_folder = _open_selected_project_folder
    app_class._show_project_catalog_help = _show_project_catalog_help
    app_class._project_catalog_patch_installed = True


def _show_comparison_window(app, before, after, comparison, tk, ttk) -> None:
    win = tk.Toplevel(app.root)
    win.title(f"EP-133 Project Comparison {before.slot:02d} -> {after.slot:02d}")
    win.geometry("980x700")
    win.minsize(760, 520)
    win.configure(bg="#d8d4c8")
    win.columnconfigure(0, weight=1)
    win.rowconfigure(1, weight=1)

    header = tk.Label(
        win,
        text=(
            f"PROJECT {before.slot:02d} -> {after.slot:02d}  /  "
            f"{len(comparison.pad_changes)} PAD CHANGES  /  "
            f"{len(comparison.binary_changes)} RECORD CHANGES"
        ),
        bg="#171915",
        fg="#d7f58a",
        font=("Consolas", 12, "bold"),
        anchor="w",
        padx=10,
        pady=7,
    )
    header.grid(row=0, column=0, sticky="ew")
    app._tip(
        header,
        "Structural comparison only. Opaque byte changes are reported without guessed meanings.",
    )

    notebook = ttk.Notebook(win)
    notebook.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
    pads = tk.Frame(notebook, bg="#d8d4c8")
    records = tk.Frame(notebook, bg="#d8d4c8")
    notebook.add(pads, text=f"Pad Changes ({len(comparison.pad_changes)})")
    notebook.add(
        records,
        text=f"Binary Records ({len(comparison.binary_changes)})",
    )

    pad_tree = ttk.Treeview(
        pads,
        columns=("group", "pad", "before", "after"),
        show="headings",
    )
    for column, width in (
        ("group", 90),
        ("pad", 90),
        ("before", 160),
        ("after", 160),
    ):
        pad_tree.heading(column, text=column.title())
        pad_tree.column(column, width=width, anchor="center")
    pad_tree.pack(fill=tk.BOTH, expand=True)
    for index, change in enumerate(comparison.pad_changes):
        pad_tree.insert(
            "",
            tk.END,
            iid=str(index),
            values=(
                change.group,
                f"{change.pad:02d}",
                _sound_label(change.before_sound_id),
                _sound_label(change.after_sound_id),
            ),
        )

    records.columnconfigure(0, weight=1)
    records.rowconfigure(0, weight=1)
    record_tree = ttk.Treeview(
        records,
        columns=("path", "status", "before", "after", "changed", "ranges"),
        show="headings",
    )
    widths = {
        "path": 220,
        "status": 80,
        "before": 80,
        "after": 80,
        "changed": 90,
        "ranges": 330,
    }
    for column, width in widths.items():
        record_tree.heading(column, text=column.title())
        record_tree.column(
            column,
            width=width,
            anchor="w" if column in {"path", "ranges"} else "center",
        )
    scroll = ttk.Scrollbar(records, orient=tk.VERTICAL, command=record_tree.yview)
    record_tree.configure(yscrollcommand=scroll.set)
    record_tree.grid(row=0, column=0, sticky="nsew")
    scroll.grid(row=0, column=1, sticky="ns")
    for index, change in enumerate(comparison.binary_changes):
        ranges = ", ".join(
            f"{item.start_offset}:{item.end_offset}"
            for item in change.changed_ranges
        )
        if change.ranges_truncated:
            ranges = f"{ranges}, ..." if ranges else "..."
        record_tree.insert(
            "",
            tk.END,
            iid=str(index),
            values=(
                change.path,
                change.status,
                change.before_byte_count,
                change.after_byte_count,
                change.changed_byte_count,
                ranges or "-",
            ),
        )
    app._tip(
        record_tree,
        "Changed ranges use half-open offsets start:end. Added and removed bytes count as changes.",
    )

    footer = tk.Label(
        win,
        text=(
            f"Before {comparison.before_sha256}\n"
            f"After  {comparison.after_sha256}"
        ),
        bg="#171915",
        fg="#f3f1de",
        font=("Consolas", 9),
        justify=tk.LEFT,
        anchor="w",
        padx=10,
        pady=7,
    )
    footer.grid(row=2, column=0, sticky="ew")


def _set_text(widget, value: str, tk) -> None:
    if widget is None:
        return
    widget.configure(state=tk.NORMAL)
    widget.delete("1.0", tk.END)
    widget.insert("1.0", value)
    widget.configure(state=tk.DISABLED)


def _sound_label(value: int | None) -> str:
    if value is None:
        return "missing"
    return "unassigned" if value == 0 else str(value)


def _format_bytes(value: int) -> str:
    if not value:
        return "-"
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MB"
    if value >= 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value} B"
