"""Read-only SysEx probe exchange helpers for the EP-133 / KO II."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import time

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


def sysex_response_matches(request: bytes, response: bytes) -> bool:
    """Return whether a SysEx response belongs to the supplied request."""

    if request[:5] == bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01]):
        return parse_universal_identity(response) is not None

    request_frame = parse_te_frame(request)
    response_frame = parse_te_frame(response)
    if request_frame is None or response_frame is None:
        return False
    if request_frame.frame_type != "request" or response_frame.frame_type != "response":
        return False
    return (
        response_frame.command == request_frame.command
        and response_frame.request_id == request_frame.request_id
    )


def matching_sysex_responses(request: bytes, responses: list[bytes]) -> list[bytes]:
    return [response for response in responses if sysex_response_matches(request, response)]


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
        deadline = time.monotonic() + max(0.1, timeout_sec)
        cursor = 0
        matched: list[bytes] = []
        while time.monotonic() < deadline:
            current = list(responses[cursor:])
            cursor = len(responses)
            matched.extend(matching_sysex_responses(frame, current))
            if matched:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            received.wait(min(remaining, 0.05))
            received.clear()
        timed_out = not matched
    finally:
        monitor.stop()
        backend.close()
    return SysexProbeResult(
        input_port=input_port,
        output_port=output_port,
        request_hex=bytes_to_hex(frame),
        responses=[decode_sysex_response(data) for data in matched],
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
