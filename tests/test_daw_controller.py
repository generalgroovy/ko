import contextlib
import io
import tempfile
import unittest
from unittest.mock import patch
import wave
from pathlib import Path

from ko2_daw.app import build_sysex_probe_frame, choose_input_port, choose_output_port, main, save_json_report
from ko2_daw.capabilities import CapabilityFinding, DeviceProbeReport, ProbeObservation
from ko2_daw.config import AppSettings, DAWConfig, DeviceSafetyConfig, load_app_settings, save_app_settings
from ko2_daw.controller import DAWController
from ko2_daw.diagnostics import readiness_report
from ko2_daw.gui import PAD_NOTES
from ko2_daw.midi import DryRunMidiBackend, MidiMessage, MidoMidiBackend, _from_winmm_short_message, _to_winmm_short_message, _usb_class_from_ids
from ko2_daw.project_store import ProjectSnapshot, SafeProjectStore
from ko2_daw.routing import KO2Route, resolve_ko2_route
from ko2_daw.samples import SampleLibrary, read_wav_metadata
from ko2_daw.sequencer import StepEvent, StepSequencer
from ko2_daw.session import CompanionSessionStore, default_ko2_profile, default_session
from ko2_daw.state import KO2RuntimeState
from ko2_daw.sysex_exchange import decode_sysex_response
from ko2_daw.te_sysex import (
    TEFileCommand,
    TESysexCommand,
    build_file_init_payload,
    build_file_list_payload,
    build_file_playback_payload,
    build_te_frame,
    build_universal_identity_request,
    pack_to_7bit_payload,
    parse_file_init_response,
    parse_file_list_response,
    parse_te_frame,
    parse_universal_identity,
    self_test_packing,
    set_experimental_write_enabled,
    unpack_7bit_payload,
)


class DAWControllerTests(unittest.TestCase):
    @patch("ko2_daw.midi.importlib.util.find_spec")
    def test_mido_backend_requires_python_rtmidi(self, find_spec):
        find_spec.side_effect = lambda package: object() if package == "mido" else None

        with self.assertRaisesRegex(RuntimeError, "python-rtmidi"):
            MidoMidiBackend()

    def test_dry_run_note_and_clock_messages_are_recorded(self):
        backend = DryRunMidiBackend(output_ports=["KO II MIDI"])
        controller = DAWController(
            config=DAWConfig(clock_enabled=True),
            backend=backend,
            output_port="KO II MIDI",
        )

        controller.start_transport()
        controller.tick_clock()
        controller.play_note(60, velocity=90)
        controller.release_note(60)
        controller.stop_transport()

        self.assertEqual(
            [message.kind for _, message in backend.sent],
            ["start", "clock", "note_on", "note_off", "stop"],
        )
        self.assertEqual(controller.state.clock_ticks, 1)

    def test_live_output_requires_allow_list_match(self):
        backend = DryRunMidiBackend(output_ports=["Untrusted Port"])
        controller = DAWController(
            config=DAWConfig(safety=DeviceSafetyConfig(dry_run=False, allowed_output_ports=("KO II",))),
            backend=backend,
            output_port="Untrusted Port",
        )

        with self.assertRaises(PermissionError):
            controller.play_note(60)

    def test_continue_transport_is_supported(self):
        backend = DryRunMidiBackend(output_ports=["KO II MIDI"])
        controller = DAWController(backend=backend, output_port="KO II MIDI")

        controller.continue_transport()

        self.assertEqual(backend.sent[-1][1].kind, "continue")
        self.assertTrue(controller.state.running)

    def test_sysex_is_blocked_by_default(self):
        controller = DAWController()

        with self.assertRaises(PermissionError):
            controller.send(MidiMessage.sysex(b"\x01\x02"))

    def test_step_sequencer_sends_note_on_and_off(self):
        backend = DryRunMidiBackend()
        controller = DAWController(backend=backend)
        sequencer = StepSequencer(controller, [StepEvent(beat=0, note=36), StepEvent(beat=0.5, note=38)])

        sent = sequencer.render_once()

        self.assertEqual(sent, 4)
        self.assertEqual([message.kind for _, message in backend.sent], ["note_on", "note_off", "note_on", "note_off"])

    def test_winmm_short_message_packing(self):
        self.assertEqual(_to_winmm_short_message(MidiMessage.note_on(60, velocity=96, channel=0)), 0x603C90)
        self.assertEqual(_to_winmm_short_message(MidiMessage.note_off(60, velocity=0, channel=0)), 0x003C80)
        self.assertEqual(_to_winmm_short_message(MidiMessage.clock()), 0xF8)
        self.assertEqual(_to_winmm_short_message(MidiMessage.continue_()), 0xFB)

    def test_winmm_short_message_parsing(self):
        self.assertEqual(_from_winmm_short_message(0x603C90), MidiMessage.note_on(60, velocity=96, channel=0))
        self.assertEqual(_from_winmm_short_message(0x003C80), MidiMessage.note_off(60, velocity=0, channel=0))
        self.assertEqual(_from_winmm_short_message(0xF8), MidiMessage.clock())

    def test_usb_class_detection_distinguishes_audio_and_midi(self):
        self.assertEqual(_usb_class_from_ids(["USB\\Class_01&SubClass_01"]), "usb-audio-control")
        self.assertEqual(_usb_class_from_ids(["USB\\Class_01&SubClass_03"]), "usb-midi-streaming")
        self.assertEqual(_usb_class_from_ids(["USB\\Class_03&SubClass_01"]), "")

    def test_runtime_state_tracks_observed_midi(self):
        state = KO2RuntimeState()

        state.observe(MidiMessage.start())
        state.observe(MidiMessage.note_on(36, velocity=100))
        state.observe(MidiMessage.control_change(1, 64))
        state.observe(MidiMessage.note_off(36))

        self.assertEqual(state.transport, "playing")
        self.assertEqual(state.mod_wheel, 64)
        self.assertEqual(state.active_notes, {})


class AppSettingsTests(unittest.TestCase):
    def test_app_settings_save_load_and_write_arm(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "app_settings.json"
            settings = AppSettings(
                preferred_route="manual",
                preferred_input_port="EP-133",
                preferred_output_port="EP-133",
                access_mode="expert-write",
                auto_connect_on_start=False,
                write_arm_phrase="WRITE",
                scan_max_depth=4,
                scan_max_dirs=250,
            )

            saved = save_app_settings(path, settings)
            loaded = load_app_settings(saved)

            self.assertEqual(loaded.preferred_route, "manual")
            self.assertEqual(loaded.preferred_output_port, "EP-133")
            self.assertFalse(loaded.auto_connect_on_start)
            self.assertTrue(loaded.write_enabled)
            self.assertEqual(loaded.scan_max_depth, 4)
            self.assertEqual(loaded.scan_max_dirs, 250)

    def test_app_settings_reject_invalid_values(self):
        with self.assertRaises(ValueError):
            AppSettings(access_mode="read-write").validate()
        with self.assertRaises(ValueError):
            AppSettings(scan_pages_per_dir=0).validate()

    def test_experimental_write_policy_can_be_armed_and_reset(self):
        payload = bytes([TEFileCommand.DELETE, 0, 0])
        with self.assertRaises(PermissionError):
            build_te_frame(TEFileCommand.COMMAND, payload)
        try:
            set_experimental_write_enabled(True)
            self.assertIsInstance(build_te_frame(TEFileCommand.COMMAND, payload), bytes)
        finally:
            set_experimental_write_enabled(False)
        with self.assertRaises(PermissionError):
            build_te_frame(TEFileCommand.COMMAND, payload)


class SafeProjectStoreTests(unittest.TestCase):
    def test_project_store_writes_atomically_and_backups_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "projects"
            store = SafeProjectStore(root)
            snapshot = ProjectSnapshot(name="session", bpm=120, midi_channel=0)

            first = store.save("session.json", snapshot)
            second = store.save("session.json", snapshot)

            self.assertEqual(first, second)
            self.assertTrue(first.exists())
            self.assertEqual(store.load("session.json").name, "session")
            self.assertEqual(len(list((root / "backups").glob("session-*.json.bak"))), 1)

    def test_project_store_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SafeProjectStore(Path(tmpdir) / "projects")

            with self.assertRaises(ValueError):
                store.save("../escape.json", ProjectSnapshot(name="bad", bpm=120, midi_channel=0))

    def test_companion_session_store_round_trips_default_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CompanionSessionStore(tmpdir)
            session = default_session("studio")

            path = store.save("studio.json", session)
            loaded = store.load("studio.json")

            self.assertTrue(path.exists())
            self.assertEqual(loaded.name, "studio")
            self.assertEqual(loaded.profile.model, "EP-133")
            self.assertEqual(len(loaded.profile.pads), 48)

    def test_default_profile_documents_unsupported_state_queries(self):
        profile = default_ko2_profile()

        self.assertIn("mod_wheel", profile.supported_controls)
        self.assertIn("selected effect", profile.unsupported_state_queries)


class AppUsabilityTests(unittest.TestCase):
    def test_gui_pad_notes_follow_ep133_group_ranges(self):
        self.assertEqual(PAD_NOTES["A"], list(range(36, 48)))
        self.assertEqual(PAD_NOTES["B"], list(range(48, 60)))
        self.assertEqual(PAD_NOTES["C"], list(range(60, 72)))
        self.assertEqual(PAD_NOTES["D"], list(range(72, 84)))

    def test_choose_output_port_auto_selects_single_allow_list_match(self):
        backend = DryRunMidiBackend(output_ports=["Microsoft GS Wavetable Synth", "KO II MIDI"])

        selected = choose_output_port(backend, None, ("KO II",), live=True)

        self.assertEqual(selected, "KO II MIDI")

    def test_choose_output_port_rejects_ambiguous_matches(self):
        backend = DryRunMidiBackend(output_ports=["KO II MIDI 1", "KO II MIDI 2"])

        with self.assertRaises(ValueError):
            choose_output_port(backend, None, ("KO II",), live=True)

    def test_choose_input_port_prefers_ko2_then_single_input(self):
        self.assertEqual(choose_input_port(["EP-133", "Other"], ["EP-133"]), "EP-133")
        self.assertEqual(choose_input_port(["QUAD-CAPTURE"], []), "QUAD-CAPTURE")
        self.assertIsNone(choose_input_port(["A", "B"], []))

    def test_save_json_report_writes_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "reports" / "midi.json"

            saved = save_json_report(path, {"output_ports": ["KO II MIDI"]})

            self.assertEqual(saved, path.resolve())
            self.assertIn("KO II MIDI", path.read_text(encoding="utf-8"))

    def test_cli_validation_returns_error_without_traceback(self):
        with self.assertRaises(SystemExit) as raised:
            main(["--bpm", "10"])

        self.assertEqual(raised.exception.code, 2)

    def test_status_cli_prints_startup_status(self):
        stream = io.StringIO()

        with contextlib.redirect_stdout(stream):
            self.assertEqual(main(["--status"]), 0)

        output = stream.getvalue()
        self.assertIn("KO II Sampler DAW", output)
        self.assertIn("Mode: dry-run by default", output)
        self.assertIn("Starter commands", output)

    def test_cli_cc_and_program_dry_run(self):
        stream = io.StringIO()

        with contextlib.redirect_stdout(stream):
            self.assertEqual(main(["--cc", "1", "64", "--program", "2", "--bank-msb", "0", "--bank-lsb", "1"]), 0)

        output = stream.getvalue()
        self.assertIn("control_change channel=0 control=1 value=64", output)
        self.assertIn("program_change channel=0 program=2", output)

    def test_cli_transport_dry_run(self):
        stream = io.StringIO()

        with contextlib.redirect_stdout(stream):
            self.assertEqual(main(["--start", "--continue-transport", "--stop"]), 0)

        output = stream.getvalue()
        self.assertIn("message=start", output)
        self.assertIn("message=continue", output)
        self.assertIn("message=stop", output)

    def test_cli_ko2_route_dry_run_reports_route(self):
        stream = io.StringIO()

        with contextlib.redirect_stdout(stream):
            self.assertEqual(main(["--ko2-route", "quad-capture", "--note", "36"]), 0)

        output = stream.getvalue()
        self.assertIn("ko2_route_status=", output)
        self.assertIn("DRY RUN", output)

    def test_readiness_report_distinguishes_usb_only(self):
        report = readiness_report(
            {
                "ko2_usb_connected": True,
                "ko2_midi_ready": False,
                "input_ports": ["QUAD-CAPTURE"],
                "output_ports": ["QUAD-CAPTURE"],
                "live_backend": "winmm",
            }
        )

        self.assertEqual(report["status"], "usb-only")
        self.assertIn("USB Audio only", " ".join(report["actions"]))
        self.assertEqual(report["route"]["status"], "din-interface-ready")

    def test_resolve_ko2_route_prefers_direct_ko2_midi(self):
        route = resolve_ko2_route(
            {
                "ko2_usb_connected": True,
                "ko2_midi_ports": ["EP-133"],
                "input_ports": ["EP-133"],
                "output_ports": ["EP-133", "QUAD-CAPTURE"],
            }
        )

        self.assertEqual(route.status, "usb-midi-ready")
        self.assertEqual(route.output_port, "EP-133")

    def test_resolve_ko2_route_uses_quad_capture_when_usb_midi_missing(self):
        route = resolve_ko2_route(
            {
                "ko2_usb_connected": True,
                "ko2_midi_ports": [],
                "input_ports": ["QUAD-CAPTURE"],
                "output_ports": ["Microsoft GS Wavetable Synth", "QUAD-CAPTURE"],
            }
        )

        self.assertEqual(route.status, "din-interface-ready")
        self.assertEqual(route.output_port, "QUAD-CAPTURE")

    def test_sample_library_reads_wav_metadata_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "kick.wav"
            with wave.open(str(wav_path), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(8000)
                handle.writeframes(b"\x00\x00" * 8000)

            sample = read_wav_metadata(wav_path, slot=12)
            library = SampleLibrary([sample])
            manifest_path = library.save(Path(tmpdir) / "manifest.json")
            loaded = SampleLibrary.load(manifest_path)

            self.assertEqual(sample.name, "kick")
            self.assertAlmostEqual(sample.duration_sec, 1.0)
            self.assertEqual(loaded.ordered()[0].slot, 12)

    def test_capability_report_text_marks_pause_as_unavailable(self):
        report = DeviceProbeReport(
            timestamp="2026-05-21T12:00:00",
            route=KO2Route(
                status="usb-midi-ready",
                input_port="EP-133",
                output_port="EP-133",
                allow_output="EP-133",
                message="ok",
            ),
            midi_report={
                "ko2_usb_connected": True,
                "ko2_midi_ready": True,
                "input_ports": ["EP-133"],
                "output_ports": ["EP-133"],
            },
            observations=[ProbeObservation("identity", received=["TE identity TE032AS001"], result="ok")],
            findings=[
                CapabilityFinding(
                    "Transport",
                    "Start, Continue, Stop",
                    "confirmed",
                    "test",
                    "Expose Start/Continue/Stop, not play/pause.",
                )
            ],
        )

        text = report.to_text()

        self.assertIn("Start, Continue, and Stop", text)
        self.assertIn("Pause is not a distinct standard MIDI transport command", text)


class TESysexTests(unittest.TestCase):
    def test_7bit_pack_round_trips_high_bytes(self):
        payload = bytes([0, 1, 2, 3, 4, 5, 6, 7, 127, 128, 129, 255])

        self.assertEqual(unpack_7bit_payload(pack_to_7bit_payload(payload)), payload)
        self.assertTrue(self_test_packing())

    def test_build_and_parse_te_echo_frame(self):
        frame = build_te_frame(TESysexCommand.ECHO, b"hello", request_id=0x123, device_id=0x7F)
        parsed = parse_te_frame(frame)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.command, TESysexCommand.ECHO)
        self.assertEqual(parsed.request_id, 0x123)
        self.assertEqual(parsed.payload, b"hello")

    def test_universal_identity_parser(self):
        frame = build_universal_identity_request()
        self.assertEqual(frame, bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7]))

        reply = bytes([0xF0, 0x7E, 0x7F, 0x06, 0x02, 0x00, 0x20, 0x76, 32, 0, 1, 0, 0, 0, 0, 0, 0])
        identity = parse_universal_identity(reply)
        self.assertEqual(identity["sku"], "TE032AS001")

    def test_file_payload_helpers_and_write_block(self):
        self.assertEqual(build_file_init_payload()[:2], bytes([TEFileCommand.INIT, TEFileCommand.INIT_SUBSCRIBE]))
        self.assertEqual(build_file_list_payload(0, 0), bytes([TEFileCommand.LIST, 0, 0, 0, 0]))
        self.assertEqual(
            build_file_playback_payload(1, TEFileCommand.PLAYBACK_START),
            bytes([TEFileCommand.PLAYBACK, TEFileCommand.PLAYBACK_START, 0, 1]),
        )
        self.assertEqual(parse_file_init_response(bytes([0, 0, 0, 0x10, 0]))["chunk_size"], 4096)

        list_payload = bytes([0, 0, 0, 2, TEFileCommand.FILE_TYPE_DIR, 0, 0, 0, 0, *b"sounds", 0])
        entries = parse_file_list_response(list_payload)["entries"]
        self.assertEqual(entries[0].name, "sounds")
        self.assertTrue(entries[0].is_directory)

        with self.assertRaises(PermissionError):
            build_te_frame(TEFileCommand.COMMAND, bytes([TEFileCommand.DELETE, 0, 0]))
        self.assertIsInstance(
            build_te_frame(TEFileCommand.COMMAND, build_file_playback_payload(1, TEFileCommand.PLAYBACK_STOP)),
            bytes,
        )
        with self.assertRaises(PermissionError):
            build_te_frame(TEFileCommand.COMMAND, bytes([TEFileCommand.PLAYBACK, TEFileCommand.PLAYBACK_START]))
        with self.assertRaises(ValueError):
            build_file_playback_payload(1, 99)

    def test_sysex_probe_builder_and_response_decoder(self):
        class Args:
            sysex_probe = "identity"
            sysex_request_id = 1
            sysex_device_id = 0x7F

        probe, frame = build_sysex_probe_frame(Args())
        self.assertEqual(probe, "identity")
        self.assertEqual(frame, build_universal_identity_request())

        reply = bytes([0xF0, 0x7E, 0x7F, 0x06, 0x02, 0x00, 0x20, 0x76, 32, 0, 1, 0, 0, 0, 0, 0, 0])
        decoded = decode_sysex_response(reply)
        self.assertEqual(decoded.kind, "identity")
        self.assertIn("TE032AS001", decoded.summary)

    def test_sysex_file_list_response_decoder(self):
        raw = bytes.fromhex(
            "f0 00 20 76 33 40 20 01 05 00 08 00 00 03 68 0e 00 00 00 00 00 "
            "73 6f 75 6e 64 08 73 00 07 50 0e 00 00 00 00 00 70 72 6f 6a "
            "65 00 63 74 73 00 f7"
        )

        decoded = decode_sysex_response(raw)

        self.assertEqual(decoded.summary, "file list 2 entries")
        self.assertEqual(decoded.details["entries"][0]["name"], "sounds")


if __name__ == "__main__":
    unittest.main()
