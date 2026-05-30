"""Menu entry for EP-133 MIDI detection diagnostics."""

from __future__ import annotations

from typing import Any


def apply_detection_menu_patch(gui_module: Any) -> None:
    """Add an EP-133 MIDI detection item to the GUI menu."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_detection_menu_patch_installed", False):
        return

    tk = gui_module.tk
    original_build_menu = app_class._build_menu

    def _build_menu(self) -> None:
        original_build_menu(self)
        menu = self.root.nametowidget(self.root.cget("menu"))
        detect_menu = tk.Menu(menu, tearoff=False)
        detect_menu.add_command(label="Refresh MIDI", command=self._refresh_report)
        detect_menu.add_command(label="EP-133 Detection Summary", command=self._show_midi_detection_summary)
        menu.add_cascade(label="MIDI Detect", menu=detect_menu)

    app_class._build_menu = _build_menu
    app_class._detection_menu_patch_installed = True
