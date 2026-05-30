"""Tests for all-groups matrix MIDI mapping."""

from ko2_daw.gui_all_groups_matrix import (
    GROUPS,
    NOTES_BY_GROUP,
    PAD_LABELS,
    _label_to_pad_index,
    _note_to_group_pad,
)


def test_note_to_group_pad_maps_all_visible_pads() -> None:
    for group in GROUPS:
        for index, note in enumerate(NOTES_BY_GROUP[group]):
            assert _note_to_group_pad(note) == (group, index)


def test_note_to_group_pad_rejects_outside_notes() -> None:
    assert _note_to_group_pad(35) == (None, None)
    assert _note_to_group_pad(84) == (None, None)


def test_label_to_pad_index_matches_button_order() -> None:
    for index, label in enumerate(PAD_LABELS):
        assert _label_to_pad_index(label) == index


def test_pad_order_is_stable_for_device_layout() -> None:
    assert PAD_LABELS == (".", "0", "ENTER", "1", "2", "3", "4", "5", "6", "7", "8", "9")
    assert NOTES_BY_GROUP["A"] == tuple(range(36, 48))
    assert NOTES_BY_GROUP["B"] == tuple(range(48, 60))
    assert NOTES_BY_GROUP["C"] == tuple(range(60, 72))
    assert NOTES_BY_GROUP["D"] == tuple(range(72, 84))
