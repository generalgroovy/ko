"""Tests for A-D x 99 segment occupancy model."""

from ko2_daw.group_segments import SegmentBank, extract_segment_id, note_to_group_segment, program_to_group


def test_extract_segment_id_variants() -> None:
    assert extract_segment_id("A1") == ("A", 1)
    assert extract_segment_id("A01") == ("A", 1)
    assert extract_segment_id("B-3 kick") == ("B", 3)
    assert extract_segment_id("group C segment 44") == ("C", 44)
    assert extract_segment_id("lane d slot 99") == ("D", 99)
    assert extract_segment_id("E1") is None
    assert extract_segment_id("A100") is None


def test_note_to_group_segment_visible_pad_range() -> None:
    assert note_to_group_segment(36) == ("A", 1)
    assert note_to_group_segment(47) == ("A", 12)
    assert note_to_group_segment(48) == ("B", 1)
    assert note_to_group_segment(59) == ("B", 12)
    assert note_to_group_segment(60) == ("C", 1)
    assert note_to_group_segment(71) == ("C", 12)
    assert note_to_group_segment(72) == ("D", 1)
    assert note_to_group_segment(83) == ("D", 12)
    assert note_to_group_segment(35) is None
    assert note_to_group_segment(84) is None


def test_program_to_group_mapping() -> None:
    assert program_to_group(0) == "A"
    assert program_to_group(1) == "B"
    assert program_to_group(2) == "C"
    assert program_to_group(3) == "D"
    assert program_to_group(4) is None


def test_segment_bank_ingests_file_entries() -> None:
    bank = SegmentBank()
    slot = bank.ingest_file_entry(
        path="/projects/song1/group C/C44 bass.wav",
        kind="file",
        node="1234",
        name="C44 bass.wav",
        size="2048",
        status="ok",
    )
    assert slot is not None
    assert slot.segment_id == "C44"
    assert slot.occupied is True
    assert slot.node == "1234"
    assert slot.size == "2048"
    assert "C44 bass.wav" in slot.components


def test_segment_bank_mark_scan_complete_sets_unknowns_empty() -> None:
    bank = SegmentBank()
    bank.ingest_file_entry(
        path="/A1.wav",
        kind="file",
        node="1",
        name="A1.wav",
        size="1",
        status="ok",
    )
    bank.mark_scan_complete()
    assert bank.slots["A"][1].occupied is True
    assert bank.slots["A"][2].occupied is False
    assert bank.slots["D"][99].occupied is False
