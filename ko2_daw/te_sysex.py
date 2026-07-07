"""Teenage Engineering EP / KO II SysEx helpers.

Based on protocol notes from generalgroovy/ko2 codex/ko2-sysex-lab.
Write-capable file operations are blocked by default.
"""

from __future__ import annotations

from dataclasses import dataclass
import json


EXPERIMENTAL_WRITE_ENABLED = False
SYSEX_START = 0xF0
SYSEX_END = 0xF7
TE_ID = (0x00, 0x20, 0x76)
TE_MARKER = 0x40
BIT_IS_REQUEST = 0x40
BIT_REQUEST_ID_AVAILABLE = 0x20


class TESysexCommand:
    GREET = 1
    ECHO = 2
    DFU = 3
    PRODUCT_SPECIFIC = 127
    STATUS_OK = 0
    STATUS_ERROR = 1
    STATUS_COMMAND_NOT_FOUND = 2
    STATUS_BAD_REQUEST = 3
    STATUS_SPECIFIC_ERROR_START = 16
    STATUS_SPECIFIC_SUCCESS_START = 64


class TEFileCommand:
    COMMAND = 5
    INIT = 1
    INIT_SUBSCRIBE = 1
    PUT = 2
    GET = 3
    LIST = 4
    PLAYBACK = 5
    PLAYBACK_START = 1
    PLAYBACK_STOP = 2
    DELETE = 6
    METADATA = 7
    METADATA_SET = 1
    METADATA_GET = 2
    METADATA_SET_PAGED = 4
    FILE_TYPE_FILE = 1
    FILE_TYPE_DIR = 2
    CAPABILITY_READ = 4
    CAPABILITY_WRITE = 8
    CAPABILITY_DELETE = 16
    CAPABILITY_MOVE = 32
    CAPABILITY_PLAYBACK = 64
    INFO = 11
    MOVED = 12
    GET_TYPE_INIT = 0
    GET_TYPE_DATA = 1


WRITE_FILE_SUBCOMMANDS = {
    TEFileCommand.PUT,
    TEFileCommand.DELETE,
    TEFileCommand.MOVED,
}

PLAYBACK_ACTIONS = {
    TEFileCommand.PLAYBACK_START,
    TEFileCommand.PLAYBACK_STOP,
}


def set_experimental_write_enabled(enabled: bool) -> None:
    global EXPERIMENTAL_WRITE_ENABLED
    EXPERIMENTAL_WRITE_ENABLED = bool(enabled)


@dataclass(frozen=True)
class TEFrame:
    frame_type: str
    device_id: int
    request_id: int | None
    command: int
    status: int
    payload: bytes
    raw: bytes

    @property
    def status_text(self) -> str:
        return status_to_string(self.status)


@dataclass(frozen=True)
class TEFileEntry:
    node_id: int
    flags: int
    size: int
    name: str

    @property
    def is_directory(self) -> bool:
        return bool(self.flags & TEFileCommand.FILE_TYPE_DIR)

    @property
    def is_file(self) -> bool:
        return bool(self.flags & TEFileCommand.FILE_TYPE_FILE)


@dataclass(frozen=True)
class TEFileDownloadInfo:
    node_id: int
    flags: int
    size: int
    name: str


@dataclass(frozen=True)
class TEFileDataPage:
    page: int
    data: bytes


def bytes_to_hex(data: bytes | bytearray | list[int]) -> str:
    return " ".join(f"{byte:02x}" for byte in data)


def string_to_bytes(value: str) -> bytes:
    return value.encode("utf-8")


def bytes_to_string(value: bytes | bytearray) -> str:
    return bytes(value).decode("utf-8", errors="replace")


def pack_to_7bit_payload(data: bytes | bytearray | list[int]) -> bytes:
    source = bytes(data)
    packed = bytearray(len(source) + ((len(source) + 6) // 7))
    data_index = 1
    header_index = 0
    for index, byte in enumerate(source):
        group_offset = index % 7
        packed[header_index] |= (byte >> 7) << group_offset
        packed[data_index] = byte & 0x7F
        data_index += 1
        if group_offset == 6 and index < len(source) - 1:
            header_index += 8
            data_index += 1
    return bytes(packed)


def unpack_7bit_payload(data: bytes | bytearray | list[int]) -> bytes:
    source = bytes(data)
    output = bytearray()
    header_index = 0
    read_index = 1
    header_bit = 0
    header = source[header_index] if source else 0
    while read_index < len(source):
        high_bit = 0x80 if header & (1 << header_bit) else 0
        output.append(high_bit | (source[read_index] & 0x7F))
        read_index += 1
        header_bit += 1
        if header_bit > 6:
            header_index += 8
            read_index += 1
            header_bit = 0
            header = source[header_index] if header_index < len(source) else 0
    return bytes(output)


def build_te_frame(command: int, payload: bytes = b"", request_id: int = 1, device_id: int = 0x7F) -> bytes:
    assert_command_allowed(command, payload)
    safe_payload = pack_to_7bit_payload(payload)
    flags = BIT_IS_REQUEST | BIT_REQUEST_ID_AVAILABLE | ((request_id >> 7) & 0x1F)
    return bytes(
        [
            SYSEX_START,
            *TE_ID,
            device_id & 0x7F,
            TE_MARKER,
            flags,
            request_id & 0x7F,
            command & 0x7F,
            *safe_payload,
            SYSEX_END,
        ]
    )


def parse_te_frame(data: bytes | bytearray | list[int]) -> TEFrame | None:
    raw = bytes(data)
    if (
        len(raw) < 9
        or raw[0] != SYSEX_START
        or tuple(raw[1:4]) != TE_ID
        or raw[5] != TE_MARKER
        or raw[-1] != SYSEX_END
    ):
        return None
    has_request_id = bool(raw[6] & BIT_REQUEST_ID_AVAILABLE)
    frame_type = "request" if raw[6] & BIT_IS_REQUEST else "response"
    request_id = ((raw[6] & 0x1F) << 7) | (raw[7] & 0x7F) if has_request_id else None
    command = raw[8]
    offset = 9
    status = -1
    if frame_type == "response":
        status = raw[offset]
        offset += 1
    payload = unpack_7bit_payload(raw[offset:-1])
    return TEFrame(frame_type, raw[4], request_id, command, status, payload, raw)


def build_universal_identity_request() -> bytes:
    return bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])


def parse_universal_identity(data: bytes | bytearray | list[int]) -> dict[str, object] | None:
    raw = bytes(data)
    if len(raw) != 17:
        return None
    if raw[0] != 0xF0 or raw[1] != 0x7E or raw[3] != 0x06 or raw[4] != 0x02:
        return None
    if tuple(raw[5:8]) != TE_ID:
        return None
    product = raw[8] ^ (raw[9] << 7)
    variant = raw[10] ^ (raw[11] << 7)
    return {
        "device_id": raw[2],
        "sku": f"TE{product:03d}AS{variant:03d}",
        "raw": raw,
    }


def build_file_init_payload(max_response_length: int = 4 * 1024 * 1024, subscribe: bool = True) -> bytes:
    return bytes(
        [
            TEFileCommand.INIT,
            TEFileCommand.INIT_SUBSCRIBE if subscribe else 0,
            (max_response_length >> 24) & 0xFF,
            (max_response_length >> 16) & 0xFF,
            (max_response_length >> 8) & 0xFF,
            max_response_length & 0xFF,
        ]
    )


def parse_file_init_response(payload: bytes | bytearray | list[int]) -> dict[str, int] | None:
    raw = bytes(payload)
    if len(raw) < 5:
        return None
    return {"chunk_size": (raw[1] << 24) | (raw[2] << 16) | (raw[3] << 8) | raw[4]}


def build_file_list_payload(node_id: int = 0, page: int = 0) -> bytes:
    return bytes([TEFileCommand.LIST, (page >> 8) & 0xFF, page & 0xFF, (node_id >> 8) & 0xFF, node_id & 0xFF])


def build_file_info_payload(node_id: int = 0) -> bytes:
    return bytes([TEFileCommand.INFO, (node_id >> 8) & 0xFF, node_id & 0xFF])


def build_file_get_init_payload(
    node_id: int,
    *,
    offset: int = 0,
    extra_args: bytes | bytearray | None = None,
) -> bytes:
    node_id = _unsigned_value(node_id, 16, "node_id")
    offset = _unsigned_value(offset, 32, "offset")
    payload = bytearray(
        [
            TEFileCommand.GET,
            TEFileCommand.GET_TYPE_INIT,
            (node_id >> 8) & 0xFF,
            node_id & 0xFF,
            (offset >> 24) & 0xFF,
            (offset >> 16) & 0xFF,
            (offset >> 8) & 0xFF,
            offset & 0xFF,
        ]
    )
    if extra_args is not None:
        payload.extend(b"\x00" * 8)
        payload.extend(bytes(extra_args))
    return bytes(payload)


def build_file_get_data_payload(page: int) -> bytes:
    page = _unsigned_value(page, 16, "page")
    return bytes(
        [
            TEFileCommand.GET,
            TEFileCommand.GET_TYPE_DATA,
            (page >> 8) & 0xFF,
            page & 0xFF,
        ]
    )


def build_file_metadata_get_payload(node_id: int = 0, page: int = 0, key: str = "") -> bytes:
    key_bytes = string_to_bytes(key) if key else b""
    payload = bytearray([TEFileCommand.METADATA, TEFileCommand.METADATA_GET, (node_id >> 8) & 0xFF, node_id & 0xFF, (page >> 8) & 0xFF, page & 0xFF])
    if key_bytes:
        payload.extend(key_bytes)
        payload.append(0)
    return bytes(payload)


def build_file_playback_payload(node_id: int, action: int = TEFileCommand.PLAYBACK_START) -> bytes:
    if action not in PLAYBACK_ACTIONS:
        raise ValueError("Playback action must be PLAYBACK_START or PLAYBACK_STOP.")
    node_id = int(node_id)
    if not 0 <= node_id <= 0xFFFF:
        raise ValueError("node_id must fit in an unsigned 16-bit value.")
    return bytes([TEFileCommand.PLAYBACK, action, (node_id >> 8) & 0xFF, node_id & 0xFF])


def parse_file_list_response(payload: bytes | bytearray | list[int]) -> dict[str, object]:
    raw = bytes(payload)
    if len(raw) <= 2:
        return {"page": 0, "entries": []}
    page = (raw[0] << 8) | raw[1]
    entries: list[TEFileEntry] = []
    offset = 2
    while offset + 7 <= len(raw):
        node_id = (raw[offset] << 8) | raw[offset + 1]
        flags = raw[offset + 2]
        size = (raw[offset + 3] << 24) | (raw[offset + 4] << 16) | (raw[offset + 5] << 8) | raw[offset + 6]
        name_end = offset + 7
        while name_end < len(raw) and raw[name_end] != 0:
            name_end += 1
        name = bytes_to_string(raw[offset + 7 : name_end])
        entries.append(TEFileEntry(node_id, flags, size, name))
        offset = name_end + 1
    return {"page": page, "entries": entries}


def parse_file_get_init_response(
    payload: bytes | bytearray | list[int],
) -> TEFileDownloadInfo:
    raw = bytes(payload)
    if len(raw) < 8:
        raise ValueError("File GET init response is shorter than 8 bytes.")
    node_id = int.from_bytes(raw[0:2], "big")
    flags = raw[2]
    size = int.from_bytes(raw[3:7], "big")
    name = bytes_to_string(raw[7:].split(b"\x00", 1)[0])
    if not name:
        raise ValueError("File GET init response did not include a filename.")
    return TEFileDownloadInfo(node_id=node_id, flags=flags, size=size, name=name)


def parse_file_get_data_response(
    payload: bytes | bytearray | list[int],
) -> TEFileDataPage:
    raw = bytes(payload)
    if len(raw) < 2:
        raise ValueError("File GET data response is shorter than 2 bytes.")
    return TEFileDataPage(page=int.from_bytes(raw[0:2], "big"), data=raw[2:])


def parse_json_metadata_payload(payload: bytes | bytearray | list[int]) -> dict[str, object]:
    raw = bytes(payload)
    if len(raw) <= 2:
        return {"page": 0, "done": True, "metadata": {}}
    page = (raw[0] << 8) | raw[1]
    text_bytes = raw[2:]
    nul_index = text_bytes.find(b"\x00")
    done = nul_index >= 0
    if done:
        text_bytes = text_bytes[:nul_index]
    text = bytes_to_string(text_bytes)
    try:
        metadata = json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        metadata = {"parse_error": str(exc), "raw": text}
    return {"page": page, "done": done, "metadata": metadata, "raw": text}


def parse_te_metadata_string(value: str) -> dict[str, str]:
    keys = ("chip_id", "mode", "os_version", "product", "serial", "sku", "sw_version", "base_sku")
    metadata = {key: "" for key in keys}
    for part in str(value or "").split(";"):
        key, _, val = part.partition(":")
        if key in metadata:
            metadata[key] = val
    return metadata


def status_to_string(status: int) -> str:
    if status == TESysexCommand.STATUS_OK:
        return "ok"
    if status >= TESysexCommand.STATUS_SPECIFIC_SUCCESS_START:
        return "command-specific-success"
    if status == TESysexCommand.STATUS_ERROR:
        return "error"
    if status == TESysexCommand.STATUS_COMMAND_NOT_FOUND:
        return "not-found"
    if status == TESysexCommand.STATUS_BAD_REQUEST:
        return "bad-request"
    if TESysexCommand.STATUS_SPECIFIC_ERROR_START <= status < TESysexCommand.STATUS_SPECIFIC_SUCCESS_START:
        return "command-specific-error"
    return "unknown"


def assert_command_allowed(command: int, payload: bytes | bytearray | list[int]) -> None:
    if command != TEFileCommand.COMMAND:
        return
    raw = bytes(payload)
    if not raw:
        return
    subcommand = raw[0]
    metadata_type = raw[1] if len(raw) > 1 else None
    if not EXPERIMENTAL_WRITE_ENABLED and subcommand == TEFileCommand.METADATA and metadata_type != TEFileCommand.METADATA_GET:
        raise PermissionError("Blocked write-capable TE metadata subcommand; EXPERIMENTAL_WRITE_ENABLED is false.")
    if subcommand == TEFileCommand.PLAYBACK:
        action = raw[1] if len(raw) > 1 else None
        if len(raw) != 4 or action not in PLAYBACK_ACTIONS:
            raise PermissionError("Blocked unsupported TE playback action.")
        return
    if not EXPERIMENTAL_WRITE_ENABLED and subcommand in WRITE_FILE_SUBCOMMANDS:
        raise PermissionError(f"Blocked write-capable TE file subcommand {subcommand}; EXPERIMENTAL_WRITE_ENABLED is false.")


def self_test_packing() -> bool:
    sample = bytes([0, 1, 2, 3, 4, 5, 6, 7, 127, 128, 129, 255])
    return unpack_7bit_payload(pack_to_7bit_payload(sample)) == sample


def _unsigned_value(value: int, bits: int, name: str) -> int:
    parsed = int(value)
    maximum = (1 << bits) - 1
    if not 0 <= parsed <= maximum:
        raise ValueError(f"{name} must fit in an unsigned {bits}-bit value.")
    return parsed
