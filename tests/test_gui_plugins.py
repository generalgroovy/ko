"""Tests for declarative GUI plugin ordering."""

from ko2_daw.gui_plugins import GUI_PLUGINS, ordered_plugins


def test_gui_plugin_names_are_unique() -> None:
    names = [plugin.name for plugin in GUI_PLUGINS]
    assert len(names) == len(set(names))


def test_gui_plugins_are_ordered_deterministically() -> None:
    ordered = ordered_plugins()
    assert [plugin.order for plugin in ordered] == sorted(plugin.order for plugin in ordered)
    assert ordered[0].name == "protocol"
    assert ordered[-1].name == "visual-stability"


def test_photo_layout_is_activated_by_visual_stability() -> None:
    stability = ordered_plugins()[-1]
    assert stability.module == "ko2_daw.gui_visual_stability"
    assert stability.order >= 1000
