"""Tests for protocol JSONL recorder and replay helpers."""

from ko2_daw.midi import MidiMessage
from ko2_daw.protocol_recorder import (
    ProtocolRecorder,
    ProtocolReplay,
    load_protocol_jsonl,
    midi_message_from_dict,
    midi_message_to_dict,
)


def test_midi_message_round_trip_note() -> None:
    message = MidiMessage.note_on(60, 96, channel=2)
    payload = midi_message_to_dict(message)
    restored = midi_message_from_dict(payload)
    assert restored is not None
    assert restored.kind == "note_on"
    assert restored.note == 60
    assert restored.velocity == 96
    assert restored.channel == 2


def test_recorder_saves_and_loads_jsonl(tmp_path) -> None:
    recorder = ProtocolRecorder()
    recorder.record("app -> device", MidiMessage.program_change(2))
    recorder.record("device -> app", MidiMessage.control_change(7, 100))
    path = recorder.save(tmp_path / "session.jsonl")
    events = load_protocol_jsonl(path)
    assert len(events) == 2
    assert events[0].direction == "app -> device"
    assert events[0].message["kind"] == "program_change"
    assert events[1].message["control"] == 7


def test_replay_invokes_observer(tmp_path) -> None:
    recorder = ProtocolRecorder()
    recorder.record("device -> app", MidiMessage.start())
    recorder.record("device -> app", MidiMessage.stop())
    path = recorder.save(tmp_path / "transport.jsonl")
    replay = ProtocolReplay.load(path)
    seen = []
    count = replay.replay(lambda event, message: seen.append((event.kind, message.kind if message else None)))
    assert count == 2
    assert seen == [("start", "start"), ("stop", "stop")]
