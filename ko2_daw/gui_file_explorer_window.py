"""Compact standalone EP-133 file explorer window."""

from __future__ import annotations

from typing import Any

from ko2_daw.te_sysex import TEFileCommand


def apply_file_explorer_window_patch(gui_module: Any) -> None:
    """Patch KO2DawApp with a compact standalone hardware-file explorer."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_file_explorer_window_patch_installed", False):
        return

    tk = gui_module.tk
    ttk = gui_module.ttk
    original_build_menu = app_class._build_menu
    original_add_hardware_entry = app_class._add_hardware_entry
    original_clear_hardware_cache = app_class._clear_hardware_cache

    def _build_menu(self) -> None:
        original_build_menu(self)
        menu = self.root.nametowidget(self.root.cget("menu"))
        files = tk.Menu(menu, tearoff=False)
        files.add_command(label="Open Compact Device Explorer", command=self._show_device_file_explorer)
        files.add_command(
            label="Scan Device Files",
            command=lambda: self._scan_complete_device_tree(auto=False),
        )
        menu.add_cascade(label="Device Files", menu=files)

    def _show_device_file_explorer(self) -> None:
        if getattr(self, "file_explorer_window", None) and self.file_explorer_window.winfo_exists():
            self.file_explorer_window.lift()
            return
        win = tk.Toplevel(self.root)
        win.title("EP-133 Device Explorer")
        win.geometry("520x620")
        win.configure(bg="#11120f")
        self.file_explorer_window = win

        toolbar = tk.Frame(win, bg="#11120f", padx=6, pady=5)
        toolbar.pack(fill=tk.X)
        for label, command in (
            ("SCAN", lambda: self._scan_complete_device_tree(auto=False)),
            ("ROOT", self._probe_root_list),
            ("LIST", self._probe_selected_node),
            ("PLAY", self._play_selected_device_file),
            ("STOP", self._stop_selected_device_file),
        ):
            tk.Button(toolbar, text=label, command=command, padx=8, pady=3).pack(
                side=tk.LEFT,
                padx=2,
            )
        tk.Label(toolbar, textvariable=self.hardware_status, bg="#11120f", fg="#d7f58a").pack(
            side=tk.RIGHT,
        )

        shell = tk.Frame(win, bg="#11120f", padx=6, pady=6)
        shell.pack(fill=tk.BOTH, expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)
        columns = ("kind", "node", "size")
        self.file_explorer_tree = ttk.Treeview(shell, columns=columns, show="tree headings", height=28)
        self.file_explorer_tree.heading("#0", text="Name")
        self.file_explorer_tree.column("#0", width=270, anchor="w", stretch=True)
        for column, width in (("kind", 55), ("node", 65), ("size", 75)):
            self.file_explorer_tree.heading(column, text=column.title())
            self.file_explorer_tree.column(column, width=width, anchor="w")
        y_scroll = ttk.Scrollbar(shell, orient="vertical", command=self.file_explorer_tree.yview)
        x_scroll = ttk.Scrollbar(shell, orient="horizontal", command=self.file_explorer_tree.xview)
        self.file_explorer_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.file_explorer_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.file_explorer_tree.bind("<Double-1>", lambda _event: self._file_explorer_double_click())
        self._rebuild_file_explorer_from_hardware_tree()

    def _file_explorer_double_click(self) -> None:
        if not getattr(self, "file_explorer_tree", None):
            return
        selected = self.file_explorer_tree.selection()
        if not selected:
            return
        item = selected[0]
        values = self.file_explorer_tree.item(item, "values")
        kind = values[0] if values else ""
        if kind == "dir":
            self.file_explorer_tree.item(item, open=not bool(self.file_explorer_tree.item(item, "open")))
            self._select_matching_hardware_item(item)
            self._probe_selected_node()
            return
        if kind == "file":
            self._select_matching_hardware_item(item)
            self._send_device_file_playback(TEFileCommand.PLAYBACK_START)

    def _select_matching_hardware_item(self, item_id: str) -> None:
        if hasattr(self, "hardware_tree") and self.hardware_tree.exists(item_id):
            self.hardware_tree.selection_set(item_id)
            self.hardware_tree.see(item_id)

    def _rebuild_file_explorer_from_hardware_tree(self) -> None:
        if not getattr(self, "file_explorer_tree", None):
            return
        tree = self.file_explorer_tree
        for item in tree.get_children(""):
            tree.delete(item)
        if not hasattr(self, "hardware_tree"):
            return

        def copy_node(source_item: str, target_parent: str) -> None:
            text = self.hardware_tree.item(source_item, "text") or source_item
            values = self.hardware_tree.item(source_item, "values")
            kind = values[1] if len(values) > 1 else ""
            node = values[0] if len(values) > 0 else ""
            size = values[2] if len(values) > 2 else ""
            tree.insert(
                target_parent,
                tk.END,
                iid=source_item,
                text=text,
                values=(kind, node, size),
                open=True,
            )
            for child in self.hardware_tree.get_children(source_item):
                copy_node(child, source_item)

        for source_root in self.hardware_tree.get_children(""):
            copy_node(source_root, "")

    def _add_hardware_entry(self, kind: str, node: str, name: str, size: str, status: str) -> None:
        original_add_hardware_entry(self, kind, node, name, size, status)
        if getattr(self, "file_explorer_tree", None):
            self._rebuild_file_explorer_from_hardware_tree()

    def _clear_hardware_cache(self, silent: bool = False) -> None:
        original_clear_hardware_cache(self, silent=silent)
        if getattr(self, "file_explorer_tree", None):
            self._rebuild_file_explorer_from_hardware_tree()

    app_class._build_menu = _build_menu
    app_class._show_device_file_explorer = _show_device_file_explorer
    app_class._file_explorer_double_click = _file_explorer_double_click
    app_class._select_matching_hardware_item = _select_matching_hardware_item
    app_class._rebuild_file_explorer_from_hardware_tree = _rebuild_file_explorer_from_hardware_tree
    app_class._add_hardware_entry = _add_hardware_entry
    app_class._clear_hardware_cache = _clear_hardware_cache
    app_class._file_explorer_window_patch_installed = True
