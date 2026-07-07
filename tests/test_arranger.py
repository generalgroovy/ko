"""Tests for the EP-133 scene/clip arranger."""

from __future__ import annotations

from ko2_daw.arranger import (
    ArrangerCapture,
    ArrangerClockFollower,
    ArrangerSession,
    SongSection,
    compile_arrangement,
    default_arranger_project,
)
from ko2_daw.midi import MidiMessage
from ko2_daw.performance import PerformanceClip, PerformanceEvent
from ko2_daw.protocol_recorder import midi_message_to_dict


def test_default_project_has_four_groups_and_eight_scene_slots() -> None:
    project = default_arranger_project()

    assert set(project.tracks) == {"A", "B", "C", "D"}
    assert len(project.scenes) == 8
    assert len(project.clips) == 32
    assert all(set(scene.clip_ids) == {"A", "B", "C", "D"} for scene in project.scenes)


def test_clip_control_automation_can_be_added_replaced_and_removed() -> None:
    session = ArrangerSession(default_arranger_project())

    session.add_control(0.5, 1, 64)
    session.add_control(0.5, 1, 96)

    assert [(item.beat, item.control, item.value) for item in session.selected_clip.controls] == [
        (0.5, 1, 96)
    ]
    session.remove_control(0)
    assert session.selected_clip.controls == []


def test_step_toggle_compile_mute_solo_velocity_and_transpose() -> None:
    session = ArrangerSession()
    session.select("S01", "A")
    assert session.toggle_step(0, 0, steps=16, velocity=100)
    assert session.toggle_step(4, 1, steps=16, velocity=80)
    session.set_track("A", velocity_scale=0.5, transpose=12)

    events, length = compile_arrangement(session.project, mode="scene", scene_id="S01")

    note_ons = [event for event in events if event.message.kind == "note_on"]
    assert length == 4
    assert [(event.message.note, event.message.velocity) for event in note_ons] == [
        (48, 50),
        (49, 40),
    ]

    session.set_track("A", muted=True)
    events, _ = compile_arrangement(session.project, mode="scene", scene_id="S01")
    assert not [event for event in events if event.track == "A"]

    session.set_track("A", muted=False)
    session.set_track("B", solo=True)
    events, _ = compile_arrangement(session.project, mode="scene", scene_id="S01")
    assert not [event for event in events if event.track == "A"]


def test_polymetric_scene_and_song_chain_repeat() -> None:
    session = ArrangerSession()
    session.select("S01", "A")
    session.toggle_step(0, 0, steps=16)
    session.select("S01", "B")
    session.toggle_step(0, 0, steps=32)
    session.project.song = [SongSection("S01", repeats=2)]

    events, length = compile_arrangement(session.project, mode="song")

    assert length == 16
    a_notes = [
        event.beat
        for event in events
        if event.track == "A" and event.message.kind == "note_on"
    ]
    b_notes = [
        event.beat
        for event in events
        if event.track == "B" and event.message.kind == "note_on"
    ]
    assert a_notes == [0.0, 4.0, 8.0, 12.0]
    assert b_notes == [0.0, 8.0]


def test_probability_is_deterministic_per_cycle() -> None:
    session = ArrangerSession()
    session.select("S01", "A")
    session.toggle_step(0, 0, probability=0.5)

    first, _ = compile_arrangement(
        session.project,
        mode="scene",
        scene_id="S01",
        probability_cycle=3,
    )
    second, _ = compile_arrangement(
        session.project,
        mode="scene",
        scene_id="S01",
        probability_cycle=3,
    )

    assert [(event.beat, event.message) for event in first] == [
        (event.beat, event.message) for event in second
    ]


def test_undo_redo_save_load_and_midi_export(tmp_path) -> None:
    session = ArrangerSession()
    session.toggle_step(0, 0)
    assert len(session.selected_clip.notes) == 1
    assert session.undo()
    assert not session.selected_clip.notes
    assert session.redo()
    assert len(session.selected_clip.notes) == 1

    project_path = session.save(tmp_path / "song.json")
    loaded = ArrangerSession.load(project_path)
    midi_path = loaded.export_midi(tmp_path / "song.mid")

    assert len(loaded.selected_clip.notes) == 1
    raw = midi_path.read_bytes()
    assert raw.startswith(b"MThd")
    assert raw.count(b"MTrk") == 5


def test_import_performance_routes_notes_to_ep133_groups() -> None:
    performance = PerformanceClip(
        bpm=120,
        loop_beats=4,
        events=[
            PerformanceEvent(0, "app", midi_message_to_dict(MidiMessage.note_on(36, 100))),
            PerformanceEvent(0.5, "app", midi_message_to_dict(MidiMessage.note_off(36))),
            PerformanceEvent(1, "device", midi_message_to_dict(MidiMessage.note_on(50, 80))),
            PerformanceEvent(1.25, "device", midi_message_to_dict(MidiMessage.note_off(50))),
        ],
    )
    session = ArrangerSession()

    imported = session.import_performance(performance)

    assert imported == 2
    scene = session.project.scene("S01")
    assert len(session.project.clips[scene.clip_ids["A"]].notes) == 1
    assert len(session.project.clips[scene.clip_ids["B"]].notes) == 1


def test_capture_records_only_armed_groups_and_closes_notes() -> None:
    session = ArrangerSession()
    session.set_track("A", armed=True)
    session.set_track("B", armed=False)
    capture = ArrangerCapture(session)
    capture.start(now=10)
    capture.record(MidiMessage.note_on(36, 90), now=10)
    capture.record(MidiMessage.note_on(48, 90), now=10)
    capture.record(MidiMessage.note_off(36), now=10.5)
    count = capture.stop(now=11)

    assert count == 1
    assert session.selected_clip.notes[0].duration == 1.0


def test_external_clock_follower_emits_events_on_due_ticks() -> None:
    session = ArrangerSession()
    session.toggle_step(1, 0, steps=16)
    follower = ArrangerClockFollower(session.project, mode="scene", scene_id="S01")

    assert follower.observe(MidiMessage.start()) == []
    emitted = []
    for _ in range(6):
        emitted.extend(follower.observe(MidiMessage.clock()))

    assert [message.kind for message in emitted] == ["note_on"]
