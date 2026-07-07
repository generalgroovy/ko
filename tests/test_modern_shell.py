"""Tests for the physical EP-133 control layout."""

from ko2_daw.gui_modern_shell import DEVICE_GROUP_ORDER, DEVICE_KEY_LAYOUT


def test_device_keypad_matches_physical_ep133_geometry() -> None:
    assert [[label for label, _index in row] for row in DEVICE_KEY_LAYOUT] == [
        ["7", "8", "9"],
        ["4", "5", "6"],
        ["1", "2", "3"],
        [".", "0", "ENTER"],
    ]
    assert sorted(index for row in DEVICE_KEY_LAYOUT for _label, index in row) == list(
        range(12)
    )


def test_device_group_column_matches_physical_order() -> None:
    assert DEVICE_GROUP_ORDER == ("A", "B", "C", "D")
