"""Explorer-style hardware file browser for the KO II GUI.

This module patches the existing Tkinter GUI at import time so device file
responses are shown as a hierarchical explorer instead of a flat table.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def apply_hardware_explorer_patch(gui_module: Any) -> None:
    """Patch KO2DawApp hardware file methods with explorer-style behavior."""

    app_class = gui_module.KO2DawApp
    tk = gui_module.tk
    ttk = gui_module.ttk
    messagebox = gui_module.messagebox

    def _build_hardware_files(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        toolbar = tk.Frame(parent, bg="#d8d4c8")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        hardware_buttons = (
            ("READ IDENTITY", self._probe_identity, "Ask the EP-133 for its universal MIDI identity. Read-only."),
            ("FILE INIT", self._probe_file_init, "Initialize the Teenage Engineering read-only file protocol and learn chunk size."),
            ("LIST ROOT", self._probe_root_list, "List the root folders exposed by the device, usually sounds and projects."),
            ("LIST SELECTED", self._probe_selected_node, "List the selected hardware folder node."),
            ("PLAY FILE", self._play_selected_device_file, "Start playback preview for the selected device file."),
            ("STOP FILE", self._stop_selected_device_file, "Stop playback preview for the selected device file."),
            ("SCAN DEVICE", self._scan_complete_device_tree, "Scan the complete read-only hardware file tree."),
            ("EXPORT CACHE", self._export_hardware_cache, "Save the visible explorer tree to daw_projects/hardware_file_cache.json."),
            ("CLEAR", self._clear_hardware_cache, "Clear the displayed hardware file tree."),
        )
        for index, (text, command, tip) in enumerate(hardware_buttons):
            button = tk.Button(toolbar, text=text, command=command, bg="#efeadf")
            button.pack(side=tk.LEFT, padx=(0 if index == 0 else 4, 4))
            self._tip(button, tip)
        self.hardware_status = tk.StringVar(value="connect live, then run read-only probes")
        hardware_status = tk.Label(
            toolbar,
            textvariable=self.hardware_status,
            bg="#d8d4c8",
            font=("Segoe UI", 10, "bold"),
        )
        hardware_status.pack(side=tk.RIGHT)
        self._tip(hardware_status, "Status of the most recent hardware probe.")

        columns = ("node", "kind", "size", "status")
        self.hardware_tree = ttk.Treeview(parent, columns=columns, show="tree headings", height=7)
        self.hardware_tree.heading("#0", text="Device Explorer")
        self.hardware_tree.column("#0", width=360, anchor="w", stretch=True)
        widths = {"node": 90, "kind": 80, "size": 90, "status": 390}
        for column in columns:
            self.hardware_tree.heading(column, text=column.title())
            self.hardware_tree.column(column, width=widths[column], anchor="w")
        self.hardware_tree.grid(row=1, column=0, sticky="nsew")
        self._tip(
            self.hardware_tree,
            "Explorer view of the hardware file tree. Select folders for LIST SELECTED, or files for PLAY FILE / STOP FILE.",
        )
        self._ensure_hardware_root()

    def _selected_hardware_row(self) -> dict[str, object] | None:
        selected = self.hardware_tree.selection()
        if not selected:
            messagebox.showinfo("KO II Hardware Files", "Select a hardware folder or file first.")
            return None
        item_id = selected[0]
        values = self.hardware_tree.item(item_id, "values")
        if len(values) < 2:
            return None
        try:
            node_id = int(values[0])
        except (TypeError, ValueError):
            messagebox.showinfo("KO II Hardware Files", "The selected item does not have a numeric node id.")
            return None
        return {
            "kind": str(values[1]) if len(values) > 1 else "",
            "node": node_id,
            "name": str(self.hardware_tree.item(item_id, "text") or item_id),
            "path": item_id,
            "size": str(values[2]) if len(values) > 2 else "",
            "status": str(values[3]) if len(values) > 3 else "",
        }

    def _ensure_hardware_root(self) -> None:
        if not self.hardware_tree.exists("/"):
            self.hardware_tree.insert(
                "",
                tk.END,
                iid="/",
                text="EP-133",
                values=("", "device", "", "root"),
                open=True,
            )

    def _normalize_hardware_path(self, kind: str, node: str, name: str) -> str:
        label = str(name or node or "unknown").strip()
        if not label:
            label = str(node or "unknown")
        if label.startswith("/"):
            return _clean_path(label)
        if kind in {"dir", "file"}:
            return _clean_path(f"/{label}")
        return _clean_path(f"/probes/{label}")

    def _ensure_hardware_parent(self, path: str) -> str:
        self._ensure_hardware_root()
        parent = _parent_path(path)
        if parent == "/":
            return parent
        parts = [part for part in parent.strip("/").split("/") if part]
        current = "/"
        for part in parts:
            next_path = _clean_path(f"{current.rstrip('/')}/{part}")
            if not self.hardware_tree.exists(next_path):
                self.hardware_tree.insert(
                    current,
                    tk.END,
                    iid=next_path,
                    text=part,
                    values=("", "dir", "", "inferred parent"),
                    open=True,
                )
            current = next_path
        return parent

    def _add_hardware_entry(self, kind: str, node: str, name: str, size: str, status: str) -> None:
        normalized_kind = str(kind or "file")
        path = self._normalize_hardware_path(normalized_kind, str(node), str(name))
        key = (str(node), path)
        if key in self.hardware_rows_seen:
            return
        self.hardware_rows_seen.add(key)
        parent = self._ensure_hardware_parent(path)
        label = _label_for_path(path)
        values = (str(node), normalized_kind, str(size), str(status))
        if self.hardware_tree.exists(path):
            self.hardware_tree.item(path, text=label, values=values)
            return
        self.hardware_tree.insert(
            parent,
            tk.END,
            iid=path,
            text=label,
            values=values,
            open=normalized_kind == "dir",
        )

    def _export_hardware_cache(self) -> None:
        rows: list[dict[str, object]] = []

        def collect(item_id: str) -> None:
            values = self.hardware_tree.item(item_id, "values")
            rows.append(
                {
                    "path": item_id,
                    "name": self.hardware_tree.item(item_id, "text"),
                    "node": values[0] if len(values) > 0 else "",
                    "kind": values[1] if len(values) > 1 else "",
                    "size": values[2] if len(values) > 2 else "",
                    "status": values[3] if len(values) > 3 else "",
                }
            )
            for child in self.hardware_tree.get_children(item_id):
                collect(child)

        for item in self.hardware_tree.get_children(""):
            collect(item)
        path = self.project_root / "hardware_file_cache.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"rows": rows}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._set_action(f"exported {path.name}")
        messagebox.showinfo("KO II Hardware Files", f"Exported hardware cache:\n{path}")

    def _clear_hardware_cache(self, silent: bool = False) -> None:
        for item in self.hardware_tree.get_children(""):
            self.hardware_tree.delete(item)
        self.hardware_rows_seen.clear()
        self._ensure_hardware_root()
        self.hardware_status.set("hardware cache cleared")
        if not silent:
            self._set_action("hardware cache cleared")

    app_class._build_hardware_files = _build_hardware_files
    app_class._selected_hardware_row = _selected_hardware_row
    app_class._ensure_hardware_root = _ensure_hardware_root
    app_class._normalize_hardware_path = _normalize_hardware_path
    app_class._ensure_hardware_parent = _ensure_hardware_parent
    app_class._add_hardware_entry = _add_hardware_entry
    app_class._export_hardware_cache = _export_hardware_cache
    app_class._clear_hardware_cache = _clear_hardware_cache


def _clean_path(path: str) -> str:
    parts = [part for part in str(path).replace("\\", "/").split("/") if part]
    return "/" + "/".join(parts) if parts else "/"


def _parent_path(path: str) -> str:
    clean = _clean_path(path)
    if clean == "/":
        return "/"
    parent = Path(clean).parent.as_posix()
    return parent if parent.startswith("/") else f"/{parent}"


def _label_for_path(path: str) -> str:
    clean = _clean_path(path)
    if clean == "/":
        return "EP-133"
    return clean.rstrip("/").split("/")[-1]
