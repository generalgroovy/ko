"""Tests for EP-133 / KO II MIDI port matching."""

from ko2_daw.port_match import (
    collect_ko2_ports,
    enrich_midi_report,
    looks_like_ko2_port,
    select_ko2_input,
    select_ko2_output,
)


def test_ep133_name_variants_are_detected() -> None:
    variants = [
        "EP-133 MIDI",
        "EP133",
        "K.O. II",
        "KO II",
        "KO2",
        "Teenage Engineering EP-133",
        "teenage eng ko ii port 1",
    ]
    assert all(looks_like_ko2_port(name) for name in variants)


def test_collect_selects_visible_input_and_output() -> None:
    inputs = ["Microsoft GS Wavetable Synth", "EP-133 MIDI In"]
    outputs = ["LoopMIDI", "EP-133 MIDI Out"]
    candidates = collect_ko2_ports(inputs, outputs)
    assert "EP-133 MIDI In" in candidates
    assert "EP-133 MIDI Out" in candidates
    assert select_ko2_input(inputs, candidates) == "EP-133 MIDI In"
    assert select_ko2_output(outputs, candidates) == "EP-133 MIDI Out"


def test_enrich_report_recomputes_ready_state() -> None:
    report = {
        "input_ports": ["KO II input"],
        "output_ports": ["KO II output"],
        "ko2_midi_ports": [],
        "ko2_midi_ready": False,
        "hints": ["No visible port name looks like KO II; check the cable."],
    }
    enriched = enrich_midi_report(report)
    assert enriched["ko2_midi_ready"] is True
    assert enriched["ko2_midi_ports"] == ["KO II input", "KO II output"]
    assert not enriched["hints"]
