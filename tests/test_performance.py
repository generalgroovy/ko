"""Tests for non-destructive MIDI performance recording."""

from __future__ import annotations

from ko2_daw.midi import MidiMessage
from ko2_daw.performance import PerformanceClip, PerformanceRecorder


def test_record_quantize_undo_and_redo() -> None:
    recorder = PerformanceRecorder(PerformanceClip(bpm=120, loop_beats=4))
    recorder.start(now=10.0)
    recorder.record(MidiMessage.note_on(36, 100), "device", now=10.13)
    recorder.record(MidiMessage.note_off(36), "device", now=10.39)
    recorder.stop()

    assert [round(event.beat, 2) for event in recorder.clip.events] == [0.26, 0.78]
    recorder.quantize(16)
    assert [event.beat for event in recorder.clip.events] == [0.25, 0.75]
    assert recorder.undo()
    assert [round(event.beat, 2) for event in recorder.clip.events] == [0.26, 0.78]
    assert recorder.redo()
    assert [event.beat for event in recorder.clip.events] == [0.25, 0.75]


def test_overdub_keeps_existing_events_and_wraps_loop() -> None:
    recorder = PerformanceRecorder(PerformanceClip(bpm=60, loop_beats=2))
    recorder.start(now=0.0)
    recorder.record(MidiMessage.note_on(36), "app", now=0.5)
    recorder.stop()
    recorder.start(overdub=True, now=10.0)
    recorder.record(MidiMessage.note_on(38), "device", now=12.5)
    recorder.stop()

    assert len(recorder.clip.events) == 2
    assert [event.beat for event in recorder.clip.events] == [0.5, 0.5]


def test_performance_json_and_midi_export(tmp_path) -> None:
    recorder = PerformanceRecorder(PerformanceClip(name="beat", bpm=100, loop_beats=4))
    recorder.start(now=0.0)
    recorder.record(MidiMessage.note_on(40, 90), "app", now=0.0)
    recorder.record(MidiMessage.note_off(40), "app", now=0.2)
    recorder.record(MidiMessage.control_change(1, 64), "device", now=0.3)
    recorder.stop()

    json_path = recorder.save(tmp_path / "beat.json")
    loaded = PerformanceRecorder.load(json_path)
    midi_path = loaded.export_midi(tmp_path / "beat.mid")

    assert loaded.clip.name == "beat"
    assert len(loaded.clip.events) == 3
    assert midi_path.read_bytes().startswith(b"MThd")
    assert b"MTrk" in midi_path.read_bytes()
    assert len(loaded.playback_events()) == 3


def test_new_recording_replaces_previous_clip() -> None:
    recorder = PerformanceRecorder()
    recorder.start(now=0)
    recorder.record(MidiMessage.note_on(36), "app", now=0)
    recorder.stop()
    recorder.start(now=5)
    recorder.record(MidiMessage.note_on(48), "app", now=5)
    recorder.stop()

    assert len(recorder.clip.events) == 1
    assert recorder.clip.events[0].message["note"] == 48
