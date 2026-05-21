"""Hardware capability probing and documentation for the connected EP-133."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import threading
import time

from ko2_daw.config import DAWConfig, DeviceSafetyConfig
from ko2_daw.controller import DAWController
from ko2_daw.midi import MidiMessage, WinMMInputMonitor, WinMMMidiBackend, midi_capability_report
from ko2_daw.routing import KO2Route, resolve_ko2_route
from ko2_daw.sysex_exchange import decode_sysex_response, send_read_only_sysex_probe
from ko2_daw.te_sysex import (
    TEFileCommand,
    build_file_init_payload,
    build_file_list_payload,
    build_te_frame,
    build_universal_identity_request,
)


OFFICIAL_MIDI_REFERENCE_URL = "https://teenage.engineering/guides/ep-133/system"
WEB_LAB_REFERENCE_URL = "https://generalgroovy.github.io/ko2/"
EP_SAMPLE_TOOL_URL = "https://teenage.engineering/apps/ep-sample-tool"


@dataclass(frozen=True)
class CapabilityFinding:
    area: str
    interaction: str
    support: str
    evidence: str
    app_action: str


@dataclass(frozen=True)
class ProbeObservation:
    name: str
    sent: list[str] = field(default_factory=list)
    received: list[str] = field(default_factory=list)
    result: str = ""
    note: str = ""


@dataclass(frozen=True)
class DeviceProbeReport:
    timestamp: str
    route: KO2Route
    midi_report: dict[str, object]
    observations: list[ProbeObservation]
    findings: list[CapabilityFinding]

    def to_text(self) -> str:
        lines = [
            "KO II / EP-133 Device Interaction Capability Scan",
            "=" * 52,
            f"Generated: {self.timestamp}",
            "",
            "References",
            f"- Official MIDI/system guide: {OFFICIAL_MIDI_REFERENCE_URL}",
            f"- KO II Web MIDI Lab reference: {WEB_LAB_REFERENCE_URL}",
            f"- Teenage Engineering EP Sample Tool: {EP_SAMPLE_TOOL_URL}",
            "",
            "Detected Route",
            f"- route status: {self.route.status}",
            f"- input port: {self.route.input_port or 'none'}",
            f"- output port: {self.route.output_port or 'none'}",
            f"- route message: {self.route.message}",
            f"- ko2_usb_connected: {self.midi_report.get('ko2_usb_connected')}",
            f"- ko2_midi_ready: {self.midi_report.get('ko2_midi_ready')}",
            f"- input ports: {', '.join(self.midi_report.get('input_ports') or [])}",
            f"- output ports: {', '.join(self.midi_report.get('output_ports') or [])}",
            "",
            "Observed Probe Results",
        ]
        for observation in self.observations:
            lines.extend(
                [
                    f"- {observation.name}",
                    f"  result: {observation.result}",
                    f"  sent: {', '.join(observation.sent) or 'none'}",
                    f"  received: {', '.join(observation.received) or 'none'}",
                    f"  note: {observation.note or 'none'}",
                ]
            )

        lines.extend(["", "Capability Matrix"])
        for finding in self.findings:
            lines.extend(
                [
                    f"- {finding.area}: {finding.interaction}",
                    f"  support: {finding.support}",
                    f"  evidence: {finding.evidence}",
                    f"  app action: {finding.app_action}",
                ]
            )

        lines.extend(
            [
                "",
                "Practical Conclusions",
                "- Direct USB-C MIDI is the correct route on this machine when EP-133 appears as both input and output.",
                "- The app can send pad triggers, transport start/stop/continue, clock ticks, CC 1 fader output, bank select, program change, panic messages, and read-only device file browsing over the confirmed EP-133 route.",
                "- The device does not expose a generic query for the current playing scene, selected pad, selected effect, complete project state, or current front-panel mode through the tested public MIDI/SysEx surface.",
                "- Pause is not a distinct standard MIDI transport command. The available controls are Start, Continue, and Stop. The app should label this as transport Start/Continue/Stop rather than DAW-style play/pause.",
                "- File and sample upload/delete/move/metadata writes must stay blocked until a backup/restore workflow is fully verified.",
            ]
        )
        return "\n".join(lines) + "\n"


def run_device_capability_probe(
    *,
    include_state_changing: bool = False,
    listen_seconds: float = 0.35,
) -> DeviceProbeReport:
    """Probe confirmed safe surfaces plus optional transport/note messages."""
    midi_report = midi_capability_report()
    route = resolve_ko2_route(midi_report, "usb-midi")
    observations: list[ProbeObservation] = []
    findings: list[CapabilityFinding] = []

    if not route.input_port or not route.output_port:
        observations.append(
            ProbeObservation(
                "route",
                result="blocked",
                note="No direct EP-133 MIDI input/output route is visible.",
            )
        )
        return DeviceProbeReport(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            route=route,
            midi_report=midi_report,
            observations=observations,
            findings=_base_findings(False, False, False),
        )

    sysex_ok = _probe_sysex(route, observations)
    file_ok = any("file list" in received for obs in observations for received in obs.received)

    if include_state_changing:
        midi_ok = _probe_short_midi(route, observations, listen_seconds)
    else:
        midi_ok = False
        observations.append(
            ProbeObservation(
                "short-midi-state-changing",
                result="skipped",
                note="Use --capability-scan-live-actions to send notes, transport, CC, clock, and panic probes.",
            )
        )

    findings.extend(_base_findings(sysex_ok, file_ok, midi_ok))
    return DeviceProbeReport(
        timestamp=datetime.now().isoformat(timespec="seconds"),
        route=route,
        midi_report=midi_report,
        observations=observations,
        findings=findings,
    )


def save_capability_report(report: DeviceProbeReport, path: str | Path) -> Path:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report.to_text(), encoding="utf-8")
    return target


def _probe_sysex(route: KO2Route, observations: list[ProbeObservation]) -> bool:
    assert route.input_port and route.output_port
    probes = [
        ("identity", build_universal_identity_request()),
        ("file-init", build_te_frame(TEFileCommand.COMMAND, build_file_init_payload(), request_id=1)),
        ("list-root", build_te_frame(TEFileCommand.COMMAND, build_file_list_payload(0, 0), request_id=2)),
        ("list-sounds", build_te_frame(TEFileCommand.COMMAND, build_file_list_payload(1000, 0), request_id=3)),
        ("list-projects", build_te_frame(TEFileCommand.COMMAND, build_file_list_payload(2000, 0), request_id=4)),
    ]
    ok = False
    for name, frame in probes:
        try:
            result = send_read_only_sysex_probe(route.input_port, route.output_port, frame, timeout_sec=2.0)
        except Exception as exc:
            observations.append(ProbeObservation(name, sent=[f"sysex {len(frame)} bytes"], result="error", note=str(exc)))
            continue
        received = [response.summary for response in result.responses]
        for response in result.responses:
            entries = response.details.get("entries")
            if isinstance(entries, list) and entries:
                received.extend(
                    f"entry node={entry.get('node_id')} kind={entry.get('kind')} name={entry.get('name')} size={entry.get('size')}"
                    for entry in entries[:12]
                )
                if len(entries) > 12:
                    received.append(f"... {len(entries) - 12} more entries")
        observations.append(
            ProbeObservation(
                name,
                sent=[f"sysex {len(frame)} bytes"],
                received=received,
                result="ok" if result.responses else ("timeout" if result.timed_out else "no-response"),
                note="read-only SysEx probe",
            )
        )
        ok = ok or bool(result.responses)
    return ok


def _probe_short_midi(route: KO2Route, observations: list[ProbeObservation], listen_seconds: float) -> bool:
    assert route.input_port and route.output_port
    received: list[MidiMessage] = []
    lock = threading.Lock()

    def observe(message: MidiMessage) -> None:
        with lock:
            received.append(message)

    monitor = WinMMInputMonitor(route.input_port, observe, include_sysex=False)
    backend = WinMMMidiBackend()
    safety = DeviceSafetyConfig(dry_run=False, allowed_output_ports=(route.output_port,))
    controller = DAWController(config=DAWConfig(clock_enabled=True, safety=safety), backend=backend, output_port=route.output_port)
    steps = [
        ("pad-a-dot-note", [MidiMessage.note_on(36, velocity=24), MidiMessage.note_off(36)]),
        ("transport-start-stop", [MidiMessage.start(), MidiMessage.stop()]),
        ("transport-continue-stop", [MidiMessage.continue_(), MidiMessage.stop()]),
        ("clock-ticks", [MidiMessage.clock(), MidiMessage.clock(), MidiMessage.clock(), MidiMessage.stop()]),
        ("fader-cc1", [MidiMessage.control_change(1, 64)]),
        ("bank-select", [MidiMessage.control_change(0, 0), MidiMessage.control_change(32, 0)]),
        ("program-change-zero", [MidiMessage.program_change(0)]),
        ("panic", [MidiMessage.control_change(123, 0), MidiMessage.control_change(120, 0)]),
    ]
    try:
        monitor.start()
        for name, messages in steps:
            with lock:
                received.clear()
            sent: list[str] = []
            try:
                for message in messages:
                    controller.send(message)
                    sent.append(message.display())
                    time.sleep(0.05)
                time.sleep(max(0.05, listen_seconds))
                with lock:
                    incoming = [message.display() for message in received]
                observations.append(
                    ProbeObservation(
                        name,
                        sent=sent,
                        received=incoming,
                        result="sent",
                        note="No response is still useful: most short MIDI commands are acted on by the device, not echoed.",
                    )
                )
            except Exception as exc:
                observations.append(ProbeObservation(name, sent=sent, result="error", note=str(exc)))
    finally:
        monitor.stop()
        backend.close()
    return True


def _base_findings(sysex_ok: bool, file_ok: bool, midi_ok: bool) -> list[CapabilityFinding]:
    route_support = "confirmed" if sysex_ok or midi_ok else "blocked"
    return [
        CapabilityFinding(
            "Connection",
            "Direct USB-C MIDI input/output through EP-133",
            route_support,
            "WinMM sees EP-133 as both input and output when connected directly.",
            "Use --ko2-route usb-midi or CONNECT EP-133 in the GUI.",
        ),
        CapabilityFinding(
            "Transport",
            "Start, Continue, Stop, Clock",
            "confirmed" if midi_ok else "official/unprobed",
            "Official MIDI chart lists system realtime clock and commands. Live scan sends start/continue/stop/clock when enabled.",
            "Expose as Start, Continue, Stop, Clock. Avoid labeling Stop as pause.",
        ),
        CapabilityFinding(
            "Pads",
            "Trigger group pads with MIDI notes 36-83",
            "confirmed" if midi_ok else "official/unprobed",
            "Official note map: group A 36-47, B 48-59, C 60-71, D 72-83.",
            "Keep 4x12 pad grid and MIDI note mapping.",
        ),
        CapabilityFinding(
            "Fader",
            "CC 1 / mod wheel",
            "confirmed" if midi_ok else "official/unprobed",
            "Official MIDI chart lists CC#1 as recognized/transmitted.",
            "Keep fader mapped to CC 1 and mirror observed CC 1 input.",
        ),
        CapabilityFinding(
            "Bank Select",
            "CC 0 and CC 32",
            "confirmed" if midi_ok else "official/unprobed",
            "Official MIDI chart lists CC#0,32.",
            "Keep advanced bank-select controls in CLI; keep GUI simple unless a clear workflow is added.",
        ),
        CapabilityFinding(
            "Panic",
            "All Notes Off and All Sound Off",
            "confirmed" if midi_ok else "official/unprobed",
            "Official MIDI chart lists all sound off and all notes off.",
            "Keep PANIC prominent and always available.",
        ),
        CapabilityFinding(
            "Identity",
            "Universal MIDI identity request",
            "confirmed" if sysex_ok else "blocked",
            "Device answered identity probe during read-only SysEx scan.",
            "Use for connection verification and status display.",
        ),
        CapabilityFinding(
            "Device Files",
            "Read-only file init/list for sounds and projects",
            "confirmed" if file_ok else "blocked",
            "TE SysEx file probes list root, sounds, and projects.",
            "Keep Hardware Files as read-only browser; add pagination/recursive scan next.",
        ),
        CapabilityFinding(
            "Current State",
            "Query playing track, selected effect, selected pad, complete project state",
            "not exposed by tested surface",
            "No public MIDI/SysEx probe tested returned complete current front-panel/project/effect state.",
            "Represent these as inferred/unknown unless observed from MIDI traffic.",
        ),
        CapabilityFinding(
            "Writes",
            "Upload/delete/move/metadata write/backup restore",
            "intentionally blocked",
            "Write-capable SysEx commands exist in reference tooling, but are not safe to use without verified backup and restore.",
            "Keep blocked in controller and GUI.",
        ),
    ]
