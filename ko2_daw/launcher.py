"""Application launcher for CLI and GUI startup."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Run the KO II application."""

    raw_argv = sys.argv[1:] if argv is None else argv
    if _needs_gui(raw_argv):
        _install_gui_extensions()

    from ko2_daw.app import main as app_main

    return app_main(raw_argv)


def _needs_gui(argv: list[str]) -> bool:
    """Return True when the requested command opens the desktop GUI."""

    return not argv or "--gui" in argv


def _install_gui_extensions() -> None:
    """Install GUI extensions before creating the Tkinter window."""

    from ko2_daw import gui
    from ko2_daw.gui_comm_panel import apply_comm_panel_patch
    from ko2_daw.gui_connection_guard import apply_connection_guard_patch
    from ko2_daw.gui_detection_menu import apply_detection_menu_patch
    from ko2_daw.gui_file_explorer_window import apply_file_explorer_window_patch
    from ko2_daw.gui_hardware_face import apply_hardware_face_patch
    from ko2_daw.gui_midi_detection import apply_midi_detection_patch
    from ko2_daw.gui_protocol_window import apply_protocol_window_patch
    from ko2_daw.gui_scrollbars import apply_hardware_scrollbar_patch
    from ko2_daw.hardware_explorer import apply_hardware_explorer_patch

    apply_protocol_window_patch(gui)
    apply_midi_detection_patch(gui)
    apply_detection_menu_patch(gui)
    apply_comm_panel_patch(gui)
    apply_hardware_face_patch(gui)
    apply_hardware_explorer_patch(gui)
    apply_hardware_scrollbar_patch(gui)
    apply_file_explorer_window_patch(gui)
    apply_connection_guard_patch(gui)


if __name__ == "__main__":
    raise SystemExit(main())
