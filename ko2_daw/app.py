"""Command-line entry point for safe KO II / MIDI DAW exploration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

from ko2_daw.config import DAWConfig, DeviceSafetyConfig
from ko2_daw.controller import DAWController
from ko2_daw.capabilities import run_device_capability_probe, save_capability_report
from ko2_daw.diagnostics import readiness_report
from ko2_daw.midi import DryRunMidiBackend, MidiBackend, MidoMidiBackend, WinMMInputMonitor, WinMMMidiBackend, midi_capability_report
from ko2_daw.project_store import ProjectSnapshot, SafeProjectStore
from ko2_daw.routing import resolve_ko2_route
from ko2_daw.sequencer import StepEvent, StepSequencer
from ko2_daw.session import CompanionSessionStore, default_session
from ko2_daw.state import KO2RuntimeState
from ko2_daw.sysex_exchange import send_read_only_sysex_probe
from ko2_daw.te_sysex import (
    TEFileCommand,
    TESysexCommand,
    build_file_info_payload,
    build_file_init_payload,
    build_file_list_payload,
    build_file_metadata_get_payload,
    build_te_frame,
    build_universal_identity_request,
    bytes_to_hex,
    self_test_packing,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe MIDI DAW controller for sampler experiments.")
    parser.add_argument("--gui", action="store_true", help="Open the KO II-style desktop control surface.")
    parser.add_argument("--status", action="store_true", help="Print startup status without opening the GUI.")
    parser.add_argument("--list", action="store_true", help="List visible MIDI capability and ports.")
    parser.add_argument("--doctor", action="store_true", help="Run device readiness diagnostics.")
    parser.add_argument("--usb-diagnose", action="store_true", help="Print detailed EP-133 USB class diagnostics.")
    parser.add_argument("--report-json", default=None, help="Save a read-only MIDI capability report as JSON.")
    parser.add_argument("--capability-scan", action="store_true", help="Probe EP-133 interaction capabilities and print a text report.")
    parser.add_argument(
        "--capability-scan-live-actions",
        action="store_true",
        help="Include state-changing note/transport/CC probes in --capability-scan.",
    )
    parser.add_argument(
        "--capability-report-txt",
        default=None,
        help="Save --capability-scan output to this text file.",
    )
    parser.add_argument("--init-session", default=None, help="Create a companion session JSON under --project-root.")
    parser.add_argument(
        "--sysex-probe",
        choices=("self-test", "identity", "te-echo", "file-init", "root-list", "root-info", "metadata-get"),
        default=None,
        help="Build a safe read-only SysEx probe frame. Does not send hardware writes.",
    )
    parser.add_argument("--sysex-node", type=int, default=0, help="Node id for read-only file SysEx probes.")
    parser.add_argument("--sysex-page", type=int, default=0, help="Page for read-only file SysEx probes.")
    parser.add_argument("--sysex-key", default="", help="Metadata key for read-only metadata probe.")
    parser.add_argument("--sysex-device-id", type=lambda value: int(value, 0), default=0x7F)
    parser.add_argument("--sysex-request-id", type=lambda value: int(value, 0), default=1)
    parser.add_argument("--send-sysex-probe", action="store_true", help="Send the selected read-only --sysex-probe live.")
    parser.add_argument("--sysex-timeout", type=float, default=2.0, help="Seconds to wait for a live SysEx response.")
    parser.add_argument("--live", action="store_true", help="Allow live MIDI when the port is allow-listed.")
    parser.add_argument(
        "--midi-backend",
        choices=("auto", "winmm", "mido"),
        default="auto",
        help="Live MIDI backend. auto prefers mido when usable, then native Windows WinMM.",
    )
    parser.add_argument("--allow-output", action="append", default=[], help="Substring of an allowed live output port.")
    parser.add_argument("--output-port", default=None, help="MIDI output port name.")
    parser.add_argument(
        "--ko2-route",
        choices=("auto", "usb-midi", "quad-capture"),
        default=None,
        help="Resolve KO II routing. auto uses KO II MIDI when visible, otherwise QUAD-CAPTURE when visible.",
    )
    parser.add_argument("--input-port", default=None, help="MIDI input port name for monitoring.")
    parser.add_argument("--monitor-input", action="store_true", help="Read incoming MIDI and infer KO II runtime state.")
    parser.add_argument("--monitor-seconds", type=float, default=10.0, help="How long --monitor-input listens.")
    parser.add_argument("--state-json", default=None, help="Save inferred runtime state as JSON.")
    parser.add_argument("--bpm", type=float, default=120.0)
    parser.add_argument("--channel", type=int, default=0, help="Zero-based MIDI channel.")
    parser.add_argument("--start", action="store_true", help="Send MIDI Start.")
    parser.add_argument("--continue-transport", action="store_true", help="Send MIDI Continue.")
    parser.add_argument("--stop", action="store_true", help="Send MIDI Stop.")
    parser.add_argument("--clock-ticks", type=int, default=0, help="Send this many MIDI clock ticks.")
    parser.add_argument("--note", type=int, default=None, help="Send a note-on/note-off dry-run or live test.")
    parser.add_argument("--velocity", type=int, default=96)
    parser.add_argument("--cc", nargs=2, type=int, metavar=("CONTROL", "VALUE"), help="Send a MIDI control change.")
    parser.add_argument("--program", type=int, default=None, help="Send a MIDI program change.")
    parser.add_argument("--bank-msb", type=int, default=None, help="Send bank select MSB using CC 0.")
    parser.add_argument("--bank-lsb", type=int, default=None, help="Send bank select LSB using CC 32.")
    parser.add_argument("--save-project", default=None, help="Relative JSON path under --project-root.")
    parser.add_argument("--project-root", default="daw_projects")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_argv = sys.argv[1:] if argv is None else argv
    args = parser.parse_args(raw_argv)

    report = None
    if not raw_argv:
        return launch_gui_or_status()

    if args.gui:
        return launch_gui_or_status()

    if args.status:
        report = midi_capability_report()
        print_startup_status(report)
        return 0

    if args.list:
        report = midi_capability_report()
        print_report(report)
    if args.doctor:
        report = report or midi_capability_report()
        print_readiness(readiness_report(report))
    if args.usb_diagnose:
        report = report or midi_capability_report()
        print_usb_diagnostics(report)
    if args.report_json:
        report = report or midi_capability_report()
        path = save_json_report(Path(args.report_json), report)
        print(f"saved_report={path}")
    if args.capability_scan:
        try:
            capability_report = run_device_capability_probe(
                include_state_changing=args.capability_scan_live_actions,
            )
        except (RuntimeError, ValueError, PermissionError, TimeoutError) as exc:
            parser.exit(2, f"error: {exc}\n")
        text = capability_report.to_text()
        print(text, end="")
        if args.capability_report_txt:
            path = save_capability_report(capability_report, args.capability_report_txt)
            print(f"saved_capability_report={path}")
        return 0
    if args.sysex_probe:
        print_sysex_probe(args)
        if args.send_sysex_probe:
            if not args.live:
                parser.exit(2, "error: --send-sysex-probe requires --live.\n")
            try:
                send_and_print_sysex_probe(args, report or midi_capability_report())
            except (RuntimeError, ValueError, PermissionError, TimeoutError) as exc:
                parser.exit(2, f"error: {exc}\n")
        return 0
    if args.init_session:
        session = default_session()
        session.routing.input_port = choose_input_port(
            list((report or midi_capability_report()).get("input_ports") or []),
            list((report or midi_capability_report()).get("ko2_midi_ports") or []),
        )
        outputs = list((report or midi_capability_report()).get("output_ports") or [])
        session.routing.output_port = outputs[0] if len(outputs) == 1 else None
        path = CompanionSessionStore(args.project_root).save(args.init_session, session)
        print(f"saved_session={path}")
    if args.monitor_input:
        try:
            state = monitor_input(args.input_port, args.monitor_seconds)
            print_state(state)
            if args.state_json:
                path = save_json_report(Path(args.state_json), state.to_dict())
                print(f"saved_state={path}")
        except (RuntimeError, ValueError) as exc:
            parser.exit(2, f"error: {exc}\n")
        return 0

    route = None
    output_port = args.output_port
    allow_outputs = list(args.allow_output)
    if args.ko2_route:
        route_report = report or midi_capability_report()
        route = resolve_ko2_route(route_report, args.ko2_route)
        print_route(route)
        if route.output_port:
            output_port = output_port or route.output_port
            if route.allow_output and route.allow_output not in allow_outputs:
                allow_outputs.append(route.allow_output)

    safety = DeviceSafetyConfig(
        dry_run=not args.live,
        allowed_output_ports=tuple(allow_outputs),
    )
    try:
        config = DAWConfig(
            bpm=args.bpm,
            midi_channel=args.channel,
            clock_enabled=args.clock_ticks > 0,
            safety=safety,
        )
        backend: MidiBackend = build_backend(args.live, args.midi_backend)
        output_port = choose_output_port(backend, output_port, tuple(allow_outputs), args.live)
        if args.live and output_port and args.output_port is None:
            print(f"selected_output_port={output_port!r}")
        controller = DAWController(config=config, backend=backend, output_port=output_port)

        log: list[str] = []
        if args.start:
            controller.start_transport()
            log.append("start")

        if args.continue_transport:
            controller.continue_transport()
            log.append("continue")

        if args.clock_ticks:
            controller.start_transport()
            log.append("start")
            for _ in range(args.clock_ticks):
                controller.tick_clock()
            controller.stop_transport()
            log.append(f"clock_ticks={args.clock_ticks}")

        if args.note is not None:
            sequencer = StepSequencer(controller, [StepEvent(beat=0, note=args.note, velocity=args.velocity)])
            sent = sequencer.render_once()
            log.append(f"note_test_sent_messages={sent}")

        if args.bank_msb is not None:
            controller.control_change(0, args.bank_msb)
            log.append(f"bank_msb={args.bank_msb}")

        if args.bank_lsb is not None:
            controller.control_change(32, args.bank_lsb)
            log.append(f"bank_lsb={args.bank_lsb}")

        if args.cc is not None:
            control, value = args.cc
            controller.control_change(control, value)
            log.append(f"cc={control}:{value}")

        if args.program is not None:
            controller.program_change(args.program)
            log.append(f"program={args.program}")

        if args.stop:
            controller.stop_transport()
            log.append("stop")

        if args.save_project:
            snapshot = ProjectSnapshot(
                name="ko2-daw-session",
                bpm=args.bpm,
                midi_channel=args.channel,
                notes=[] if args.note is None else [{"beat": 0, "note": args.note, "velocity": args.velocity}],
                controller_log=log,
            )
            store = SafeProjectStore(Path(args.project_root))
            path = store.save(args.save_project, snapshot)
            print(f"saved_project={path}")

        if isinstance(backend, DryRunMidiBackend) and backend.sent:
            print("DRY RUN: no MIDI was sent to hardware.")
            for port, message in backend.sent:
                print(f"dry_run_send port={port!r} message={message.display()}")
    except (PermissionError, RuntimeError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    return 0


def monitor_input(input_port: str | None, seconds: float) -> KO2RuntimeState:
    report = midi_capability_report()
    ports = list(report.get("input_ports") or [])
    port = input_port or choose_input_port(ports, list(report.get("ko2_midi_ports") or []))
    if not port:
        raise ValueError("No MIDI input port is visible. Run --list to inspect connected ports.")
    state = KO2RuntimeState()

    def observe(message):
        state.observe(message, "in")
        print(f"in {message.display()}")

    monitor = WinMMInputMonitor(port, observe)
    print(f"monitoring_input={port!r} seconds={seconds:g}")
    monitor.start()
    try:
        time.sleep(max(0, seconds))
    finally:
        monitor.stop()
    return state


def choose_input_port(input_ports: list[str], ko2_ports: list[str]) -> str | None:
    for port in ko2_ports:
        if port in input_ports:
            return port
    if len(input_ports) == 1:
        return input_ports[0]
    return None


def print_state(state: KO2RuntimeState) -> None:
    payload = state.to_dict()
    print("KO II inferred state")
    print(f"transport: {payload['transport']}")
    print(f"active_notes: {payload['active_notes']}")
    print(f"clock_ticks: {payload['clock_ticks']}")
    print(f"last_program: {payload['last_program']}")
    print(f"mod_wheel: {payload['mod_wheel']}")
    print(f"controllers: {payload['controllers']}")
    for limitation in payload["limitations"]:
        print(f"limit: {limitation}")


def print_readiness(report: dict[str, object]) -> None:
    print("KO II readiness")
    print(f"status: {report['status']}")
    print(f"ko2_usb_connected: {report['ko2_usb_connected']}")
    print(f"ko2_midi_ready: {report['ko2_midi_ready']}")
    print("input_ports:")
    for port in report["input_ports"]:
        print(f"  - {port}")
    print("output_ports:")
    for port in report["output_ports"]:
        print(f"  - {port}")
    route = report.get("route") or {}
    if route:
        print(f"route_status: {route.get('status')}")
        print(f"route_output: {route.get('output_port')}")
        print(f"route_input: {route.get('input_port')}")
        print(f"route_message: {route.get('message')}")
        if route.get("requires_user_action"):
            print(f"route_action: {route.get('requires_user_action')}")
    for action in report["actions"]:
        print(f"action: {action}")


def print_usb_diagnostics(report: dict[str, object]) -> None:
    print("EP-133 USB diagnostics")
    print(f"ko2_usb_connected: {report.get('ko2_usb_connected')}")
    print(f"ko2_midi_ready: {report.get('ko2_midi_ready')}")
    for device in report.get("ko2_usb_devices") or []:
        print(f"device: {device.get('friendly_name') or device.get('device_description') or device.get('hardware_id')}")
        print(f"  hardware_id: {device.get('hardware_id')}")
        print(f"  instance: {device.get('instance')}")
        print(f"  service: {device.get('service')}")
        print(f"  usb_class: {device.get('usb_class')}")
        if device.get("compatible_ids"):
            print(f"  compatible_ids: {device.get('compatible_ids')}")
    if report.get("ko2_usb_connected") and not report.get("ko2_midi_ready"):
        print("diagnosis: EP-133 is connected, but this USB interface is not exposing USB MIDI streaming.")
        print("expected_for_direct_usb_midi: USB Class_01 SubClass_03 or a visible EP-133 MIDI input/output port.")


def print_route(route) -> None:
    print(f"ko2_route_status={route.status}")
    print(f"ko2_route_output={route.output_port}")
    print(f"ko2_route_input={route.input_port}")
    print(f"ko2_route_message={route.message}")
    if route.requires_user_action:
        print(f"ko2_route_action={route.requires_user_action}")


def print_sysex_probe(args: argparse.Namespace) -> None:
    if args.sysex_probe == "self-test":
        print(f"te_sysex_packing_self_test={self_test_packing()}")
        print("write_commands_enabled=False")
        return
    probe, frame = build_sysex_probe_frame(args)
    if frame is None:
        return
    if probe in {"identity", "te-echo"}:
        print(f"probe={probe} frame={bytes_to_hex(frame)}")
    else:
        payload = build_sysex_probe_payload(args)
        print(f"probe={probe} payload={bytes_to_hex(payload)} frame={bytes_to_hex(frame)}")


def build_sysex_probe_frame(args: argparse.Namespace) -> tuple[str, bytes | None]:
    if args.sysex_probe == "self-test":
        return "self-test", None
    if args.sysex_probe == "identity":
        return "identity", build_universal_identity_request()
    if args.sysex_probe == "te-echo":
        payload = b"ko2-sampler-daw"
        return "te-echo", build_te_frame(TESysexCommand.ECHO, payload, args.sysex_request_id, args.sysex_device_id)
    payload = build_sysex_probe_payload(args)
    return args.sysex_probe, build_te_frame(
        TEFileCommand.COMMAND,
        payload,
        args.sysex_request_id,
        args.sysex_device_id,
    )


def build_sysex_probe_payload(args: argparse.Namespace) -> bytes:
    if args.sysex_probe == "file-init":
        return build_file_init_payload()
    if args.sysex_probe == "root-list":
        return build_file_list_payload(args.sysex_node, args.sysex_page)
    if args.sysex_probe == "root-info":
        return build_file_info_payload(args.sysex_node)
    if args.sysex_probe == "metadata-get":
        return build_file_metadata_get_payload(args.sysex_node, args.sysex_page, args.sysex_key)
    raise ValueError(f"Unsupported SysEx probe: {args.sysex_probe}")


def send_and_print_sysex_probe(args: argparse.Namespace, report: dict[str, object]) -> None:
    probe, frame = build_sysex_probe_frame(args)
    if frame is None:
        raise ValueError("self-test does not produce a SysEx frame to send.")
    route = resolve_ko2_route(report, args.ko2_route or "auto")
    print_route(route)
    if not route.input_port or not route.output_port:
        raise ValueError("Live SysEx probes require visible EP-133 MIDI input and output ports.")
    result = send_read_only_sysex_probe(
        route.input_port,
        route.output_port,
        frame,
        timeout_sec=args.sysex_timeout,
    )
    print(f"sysex_probe_sent={probe}")
    print(f"sysex_input={result.input_port!r}")
    print(f"sysex_output={result.output_port!r}")
    print(f"sysex_timed_out={result.timed_out}")
    for index, response in enumerate(result.responses, start=1):
        print(f"sysex_response_{index}_kind={response.kind}")
        print(f"sysex_response_{index}_summary={response.summary}")
        if response.details.get("chunk_size"):
            print(f"sysex_response_{index}_chunk_size={response.details['chunk_size']}")
        for entry in response.details.get("entries") or []:
            print(
                "sysex_entry "
                f"node={entry.get('node_id')} "
                f"kind={entry.get('kind')} "
                f"size={entry.get('size')} "
                f"name={entry.get('name')}"
            )
        print(f"sysex_response_{index}_raw={response.raw_hex}")


def build_backend(live: bool, backend_name: str = "auto") -> MidiBackend:
    if not live:
        return DryRunMidiBackend()
    if backend_name == "mido":
        return MidoMidiBackend()
    if backend_name == "winmm":
        return WinMMMidiBackend()
    try:
        return MidoMidiBackend()
    except Exception:
        return WinMMMidiBackend()


def launch_gui_or_status() -> int:
    try:
        from ko2_daw.gui import run_gui

        return run_gui()
    except Exception as exc:
        print(f"GUI unavailable: {exc}")
        print()
        print_startup_status(midi_capability_report())
        return 0


def choose_output_port(
    backend: MidiBackend,
    requested_port: str | None,
    allow_list: tuple[str, ...],
    live: bool,
) -> str | None:
    """Resolve a live output port without guessing when more than one port matches."""
    if not live or requested_port:
        return requested_port
    if not allow_list:
        raise ValueError("Live mode requires --output-port or at least one --allow-output substring.")

    ports = backend.list_output_ports()
    matches = [
        port
        for port in ports
        if any(allowed.lower() in port.lower() for allowed in allow_list)
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(
            "No MIDI output port matched --allow-output. Run --list to inspect visible port names."
        )
    raise ValueError(
        "Multiple MIDI output ports matched --allow-output; pass --output-port with the exact port name."
    )


def save_json_report(path: Path, report: dict[str, object]) -> Path:
    """Save a capability report atomically."""
    target = path.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=target.parent) as handle:
        handle.write(payload)
        handle.write("\n")
        temp_name = handle.name
    Path(temp_name).replace(target)
    return target


def print_startup_status(report: dict[str, object]) -> None:
    print("KO II Sampler DAW")
    print("==================")
    print("Mode: dry-run by default. No MIDI is sent unless you pass --live.")
    print("Run python run_ko2_daw.py to open the KO II-style desktop surface.")
    print()
    print_report(report)
    print()
    print("Starter commands")
    print("  python run_ko2_daw.py --list")
    print("  python run_ko2_daw.py --note 60 --clock-ticks 2")
    print("  python run_ko2_daw.py --cc 1 64")
    print("  python run_ko2_daw.py --doctor")
    print("  python run_ko2_daw.py --ko2-route auto --note 36")
    print("  python run_ko2_daw.py --live --ko2-route usb-midi --note 36")
    print("  python run_ko2_daw.py --live --ko2-route usb-midi --start")
    print("  python run_ko2_daw.py --live --ko2-route usb-midi --continue-transport")
    print("  python run_ko2_daw.py --live --ko2-route usb-midi --stop")
    print("  python run_ko2_daw.py --init-session ko2_session_companion.json")
    print("  python run_ko2_daw.py --sysex-probe self-test")
    print("  python run_ko2_daw.py --sysex-probe identity")
    print("  python run_ko2_daw.py --live --ko2-route usb-midi --sysex-probe identity --send-sysex-probe")
    print("  python run_ko2_daw.py --live --ko2-route usb-midi --sysex-probe root-list --send-sysex-probe")
    print("  python run_ko2_daw.py --capability-scan --capability-report-txt docs\\ko2_device_interaction_capabilities.txt")
    print("  python run_ko2_daw.py --monitor-input --monitor-seconds 10 --state-json daw_projects\\ko2_state.json")
    print("  python run_ko2_daw.py --note 60 --save-project ko2_session.json")
    print()
    print("Live MIDI requires a visible output port and an explicit allow-list:")
    print('  python run_ko2_daw.py --live --ko2-route usb-midi --note 60')


def print_report(report: dict[str, object]) -> None:
    print("MIDI capability report")
    print(f"live_midi_available: {report.get('live_midi_available')}")
    print(f"live_backend: {report.get('live_backend')}")
    print(f"mido_installed: {report.get('mido_installed')}")
    print(f"rtmidi_installed: {report.get('rtmidi_installed')}")
    print(f"native_winmm_available: {report.get('native_winmm_available')}")
    print(f"ko2_usb_connected: {report.get('ko2_usb_connected')}")
    print(f"ko2_midi_ready: {report.get('ko2_midi_ready')}")
    for device in report.get("ko2_usb_devices") or []:
        label = device.get("friendly_name") or device.get("device_description") or device.get("hardware_id")
        print(f"ko2_usb_device: {label} {device.get('hardware_id')} instance={device.get('instance')}")
    print("ko2_midi_ports:")
    for port in report.get("ko2_midi_ports") or []:
        print(f"  - {port}")
    print("input_ports:")
    for port in report.get("input_ports") or []:
        print(f"  - {port}")
    print("output_ports:")
    for port in report.get("output_ports") or []:
        print(f"  - {port}")
    if report.get("winmm_error"):
        print(f"winmm_error: {report.get('winmm_error')}")
    if report.get("error"):
        print(f"error: {report.get('error')}")
    for hint in report.get("hints") or []:
        print(f"hint: {hint}")


if __name__ == "__main__":
    raise SystemExit(main())
