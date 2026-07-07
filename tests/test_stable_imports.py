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
        "ko2_daw.gui_performance",
        "ko2_daw.gui_audio_studio",
        "ko2_daw.gui_arranger",
        "ko2_daw.gui_device_snapshot",
        "ko2_daw.gui_device_library",
        "ko2_daw.gui_project_catalog",
        "ko2_daw.gui_modern_shell",
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
        "ko2_daw.performance",
        "ko2_daw.audio_timeline",
        "ko2_daw.native_audio",
        "ko2_daw.arranger",
        "ko2_daw.project_archive",
        "ko2_daw.project_catalog",
        "ko2_daw.device_snapshot",
        "ko2_daw.device_transfer",
    ]
    for module_name in modules:
        assert importlib.import_module(module_name)
