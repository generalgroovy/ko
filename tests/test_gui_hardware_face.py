"""Tests for GUI hardware-face mapping helpers."""

from ko2_daw.gui_hardware_face import GROUP_PROGRAMS, _group_for_program, _lane_for_note


def test_lane_for_note_maps_ep133_pad_ranges() -> None:
    assert _lane_for_note(36) == "A"
    assert _lane_for_note(47) == "A"
    assert _lane_for_note(48) == "B"
    assert _lane_for_note(59) == "B"
    assert _lane_for_note(60) == "C"
    assert _lane_for_note(71) == "C"
    assert _lane_for_note(72) == "D"
    assert _lane_for_note(83) == "D"
    assert _lane_for_note(35) is None
    assert _lane_for_note(84) is None


def test_group_program_mirror_mapping_is_reversible() -> None:
    assert GROUP_PROGRAMS == {"A": 0, "B": 1, "C": 2, "D": 3}
    assert _group_for_program(0) == "A"
    assert _group_for_program(1) == "B"
    assert _group_for_program(2) == "C"
    assert _group_for_program(3) == "D"
    assert _group_for_program(4) is None
