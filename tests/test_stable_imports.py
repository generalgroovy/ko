"""Stable-mode import smoke tests."""

import importlib


def test_stable_gui_modules_import() -> None:
    modules = [
        "ko2_daw.launcher",
        "ko2_daw.gui_plugins",
        "ko2_daw.gui_protocol_window",
        "ko2_daw.gui_midi_detection",
        "ko2_daw.gui_comm_panel",
        "ko2_daw.hardware_explorer",
        "ko2_daw.gui_connection_guard",
        "ko2_daw.gui_state_poll",
    ]
    for module_name in modules:
        assert importlib.import_module(module_name)


def test_core_command_modules_import() -> None:
    modules = [
        "ko2_daw.app",
        "ko2_daw.midi",
        "ko2_daw.routing",
        "ko2_daw.config",
        "ko2_daw.support_bundle",
        "ko2_daw.protocol_recorder",
    ]
    for module_name in modules:
        assert importlib.import_module(module_name)
