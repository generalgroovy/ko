"""Tests for declarative GUI plugin ordering."""

from ko2_daw.gui_plugins import GUI_PLUGINS, ordered_plugins


def test_gui_plugin_names_are_unique() -> None:
    names = [plugin.name for plugin in GUI_PLUGINS]
    assert len(names) == len(set(names))


def test_stable_gui_plugins_are_ordered_and_conservative() -> None:
    ordered = ordered_plugins(include_experimental=False)
    names = [plugin.name for plugin in ordered]
    assert [plugin.order for plugin in ordered] == sorted(plugin.order for plugin in ordered)
    assert names[0] == "protocol"
    assert "communication" in names
    assert "state-poll" in names
    assert "visual-stability" not in names
    assert "device-main" not in names
    assert "all-groups-matrix" not in names


def test_experimental_gui_plugins_keep_final_stability_layer() -> None:
    ordered = ordered_plugins(include_experimental=True)
    names = [plugin.name for plugin in ordered]
    assert names[0] == "protocol"
    assert names[-1] == "visual-stability"
    assert "device-main" in names
    assert "segment-grid" in names
    assert "all-groups-matrix" in names
