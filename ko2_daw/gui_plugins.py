"""Declarative GUI plugin registry.

The default GUI mode is intentionally conservative. Earlier experimental
surface patches are still available through KO2_DAW_GUI_MODE=experimental,
but the normal launcher installs only the stable extensions required for a
reliable desktop app.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import os
from typing import Any


@dataclass(frozen=True)
class GuiPlugin:
    """One GUI extension patch with an explicit install order."""

    name: str
    module: str
    function: str
    order: int
    experimental: bool = False

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
    GuiPlugin("state-poll", "ko2_daw.gui_state_poll", "apply_state_poll_patch", 90),
    GuiPlugin("device-main", "ko2_daw.gui_device_main", "apply_device_main_patch", 200, True),
    GuiPlugin("song-timeline", "ko2_daw.gui_song_timeline", "apply_song_timeline_patch", 210, True),
    GuiPlugin("segment-grid", "ko2_daw.gui_segment_grid", "apply_segment_grid_patch", 220, True),
    GuiPlugin("all-groups-matrix", "ko2_daw.gui_all_groups_matrix", "apply_all_groups_matrix_patch", 230, True),
    GuiPlugin("visual-stability", "ko2_daw.gui_visual_stability", "apply_visual_stability_patch", 1000, True),
)


def gui_mode() -> str:
    """Return the requested GUI mode.

    Supported values:
    - stable: protocol, MIDI detection, communication panel, explorer, state polling.
    - experimental: stable plus photo/device/timeline/matrix patches.
    """

    value = os.environ.get("KO2_DAW_GUI_MODE", "stable").strip().lower()
    return value if value in {"stable", "experimental"} else "stable"


def ordered_plugins(*, include_experimental: bool | None = None) -> tuple[GuiPlugin, ...]:
    """Return plugins in deterministic installation order."""

    if include_experimental is None:
        include_experimental = gui_mode() == "experimental"
    plugins = [
        plugin
        for plugin in GUI_PLUGINS
        if include_experimental or not plugin.experimental
    ]
    return tuple(sorted(plugins, key=lambda plugin: (plugin.order, plugin.name)))


def install_gui_plugins(gui_module: Any) -> None:
    """Install all GUI extension patches into the supplied gui module."""

    for plugin in ordered_plugins():
        plugin.install(gui_module)
