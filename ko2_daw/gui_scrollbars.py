"""Scrollbar extension for the hardware explorer tree."""

from __future__ import annotations

from typing import Any


def apply_hardware_scrollbar_patch(gui_module: Any) -> None:
    """Add vertical and horizontal scrollbars to the hardware tree after build."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_hardware_scrollbar_patch_installed", False):
        return

    ttk = gui_module.ttk
    original_build_hardware_files = app_class._build_hardware_files

    def _build_hardware_files(self, parent):
        original_build_hardware_files(self, parent)
        if not hasattr(self, "hardware_tree"):
            return
        tree = self.hardware_tree
        y_scroll = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        x_scroll = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=1, column=0, sticky="nsew")
        y_scroll.grid(row=1, column=1, sticky="ns")
        x_scroll.grid(row=2, column=0, sticky="ew")
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=0)
        parent.rowconfigure(1, weight=1)
        parent.rowconfigure(2, weight=0)
        self._tip(y_scroll, "Scroll the EP-133 device explorer vertically.")
        self._tip(x_scroll, "Scroll wide device paths and status values horizontally.")

    app_class._build_hardware_files = _build_hardware_files
    app_class._hardware_scrollbar_patch_installed = True
