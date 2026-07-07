"""Packaging configuration smoke tests."""

from pathlib import Path


def test_pyinstaller_collects_dynamic_gui_plugins() -> None:
    spec = (Path(__file__).parents[1] / "ko2_daw.spec").read_text(
        encoding="utf-8"
    )

    assert 'collect_submodules("ko2_daw")' in spec


def test_frozen_runtime_forwards_command_line_arguments() -> None:
    runtime = (Path(__file__).parents[1] / "ko2_daw_runtime.py").read_text(
        encoding="utf-8"
    )

    assert "main([])" not in runtime
    assert "main()" in runtime
