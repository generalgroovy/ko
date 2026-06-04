"""Declarative GUI plugin registry.

The GUI still uses patch-style extension functions for now, but their install
order is centralized and testable here instead of being hand-coded in the
launcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any


@dataclass(frozen=True)
class GuiPlugin:
    """One GUI extension patch with an explicit install order."""

    name: str
    module: str
    function: str
    order: int

    def install(self, gui_module: Any) -> None:
        module = import_module(self.module)
        installer = getattr(module, self.function)
        installer(gui_module)


GUI_PLUGINS: tuple[GuiPlugin, ...] = (
    GuiPlugin("protocol", "ko2_daw.gui_protocol_window", "apply_protocol_window_patch", 10),
    GuiPlugin("midi-detection", "ko2_daw.gui_midi_detection", "apply_midi_detection_patch", 20),
    GuiPlugin("detection-menu", "ko2_daw.gui_detection_menu", "apply_detection_menu_patch", 30),
    GuiPlugin("communication", "ko2_daw.gui_comm_panel", "apply_comm_panel_patch", 40),
    GuiPlugin("hardware-explorer", "ko2_daw.hardware_explorer", "apply_hardware_explorer_patch", 50),
    GuiPlugin("scrollbars", "ko2_daw.gui_scrollbars", "apply_hardware_scrollbar_patch", 60),
    GuiPlugin("file-explorer-window", "ko2_daw.gui_file_explorer_window", "apply_file_explorer_window_patch", 70),
    GuiPlugin("connection-guard", "ko2_daw.gui_connection_guard", "apply_connection_guard_patch", 80),
    GuiPlugin("device-main", "ko2_daw.gui_device_main", "apply_device_main_patch", 90),
    GuiPlugin("song-timeline", "ko2_daw.gui_song_timeline", "apply_song_timeline_patch", 100),
    GuiPlugin("segment-grid", "ko2_daw.gui_segment_grid", "apply_segment_grid_patch", 110),
    GuiPlugin("all-groups-matrix", "ko2_daw.gui_all_groups_matrix", "apply_all_groups_matrix_patch", 120),
    GuiPlugin("state-poll", "ko2_daw.gui_state_poll", "apply_state_poll_patch", 130),
    GuiPlugin("visual-stability", "ko2_daw.gui_visual_stability", "apply_visual_stability_patch", 1000),
)


def ordered_plugins() -> tuple[GuiPlugin, ...]:
    """Return plugins in deterministic installation order."""

    return tuple(sorted(GUI_PLUGINS, key=lambda plugin: (plugin.order, plugin.name)))


def install_gui_plugins(gui_module: Any) -> None:
    """Install all GUI extension patches into the supplied gui module."""

    for plugin in ordered_plugins():
        plugin.install(gui_module)
