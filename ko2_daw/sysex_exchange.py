"""Read-only SysEx probe exchange helpers for the EP-133 / KO II."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading

from ko2_daw.config import DAWConfig, DeviceSafetyConfig
from ko2_daw.controller import DAWController
from ko2_daw.midi import MidiMessage, WinMMInputMonitor, WinMMMidiBackend
from ko2_daw.te_sysex import (
    TEFileCommand,
    bytes_to_hex,
    parse_file_init_response,
    parse_file_list_response,
    parse_json_metadata_payload,
    parse_te_frame,
    parse_universal_identity,
)


@dataclass(frozen=True)
class SysexDecodedResponse:
    kind: str
    summary: str
    raw_hex: str
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class SysexProbeResult:
    input_port: str
    output_port: str
    request_hex: str
    responses: list[SysexDecodedResponse]
    timed_out: bool


def send_read_only_sysex_probe(
    input_port: str,
    output_port: str,
    frame: bytes,
    *,
    timeout_sec: float = 2.0,
) -> SysexProbeResult:
    """Send a read-only SysEx frame and collect responses from the selected input."""
    responses: list[bytes] = []
    received = threading.Event()

    def observe(message: MidiMessage) -> None:
        if message.kind == "sysex" and message.data:
            responses.append(message.data)
            received.set()

    monitor = WinMMInputMonitor(input_port, observe, include_sysex=True)
    backend = WinMMMidiBackend()
    safety = DeviceSafetyConfig(
        dry_run=False,
        allowed_output_ports=(output_port,),
        sysex_enabled=True,
        max_sysex_bytes=max(1024, len(frame) + 16),
    )
    controller = DAWController(config=DAWConfig(safety=safety), backend=backend, output_port=output_port)
    monitor.start()
    try:
        controller.send(MidiMessage.sysex(frame))
        timed_out = not received.wait(max(0.1, timeout_sec))
    finally:
        monitor.stop()
        backend.close()
    return SysexProbeResult(
        input_port=input_port,
        output_port=output_port,
        request_hex=bytes_to_hex(frame),
        responses=[decode_sysex_response(data) for data in responses],
        timed_out=timed_out,
    )


def decode_sysex_response(data: bytes) -> SysexDecodedResponse:
    identity = parse_universal_identity(data)
    if identity:
        return SysexDecodedResponse(
            kind="identity",
            summary=f"TE identity {identity.get('sku')}",
            raw_hex=bytes_to_hex(data),
            details=identity,
        )

    frame = parse_te_frame(data)
    if frame is None:
        return SysexDecodedResponse("unknown", "unmatched SysEx response", bytes_to_hex(data), {})

    details: dict[str, object] = {
        "device_id": frame.device_id,
        "request_id": frame.request_id,
        "command": frame.command,
        "status": frame.status_text,
        "payload_len": len(frame.payload),
    }
    summary = f"TE command {frame.command} status {frame.status_text}"
    if frame.command == TEFileCommand.COMMAND and frame.payload:
        parsed_init = parse_file_init_response(frame.payload) if len(frame.payload) == 5 else None
        if parsed_init:
            details.update(parsed_init)
            summary = f"file init chunk {parsed_init['chunk_size']} bytes"
        else:
            parsed_list = parse_file_list_response(frame.payload)
            entries = parsed_list["entries"]
            if entries:
                details["page"] = parsed_list["page"]
                details["entries"] = [
                    {
                        "node_id": entry.node_id,
                        "name": entry.name,
                        "size": entry.size,
                        "kind": "dir" if entry.is_directory else "file",
                    }
                    for entry in entries
                ]
                summary = f"file list {len(entries)} entries"
            elif frame.payload[:1] == bytes([TEFileCommand.METADATA]):
                metadata = parse_json_metadata_payload(frame.payload[1:])
                details.update(metadata)
                summary = "metadata response"
    return SysexDecodedResponse("te", summary, bytes_to_hex(data), details)
