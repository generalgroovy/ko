"""MIDI message models and backends.

The module works without external MIDI packages. If `mido` and a backend such as
`python-rtmidi` are installed, `MidoMidiBackend` can bridge to real hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
import ctypes
import importlib.util
import sys
import time
from collections.abc import Callable
from typing import Protocol


DATA_BYTE_MAX = 127
CHANNEL_MAX = 15
KO2_USB_VENDOR_ID = "VID_2367"
KO2_USB_PRODUCT_ID = "PID_0020"


@dataclass(frozen=True)
class MidiMessage:
    """Validated MIDI message description used by the DAW controller."""

    kind: str
    channel: int | None = None
    note: int | None = None
    velocity: int | None = None
    control: int | None = None
    value: int | None = None
    program: int | None = None
    data: bytes | None = None

    def __post_init__(self) -> None:
        channel_messages = {"note_on", "note_off", "control_change", "program_change"}
        if self.kind in channel_messages:
            _validate_range("channel", self.channel, 0, CHANNEL_MAX)
        if self.note is not None:
            _validate_range("note", self.note, 0, DATA_BYTE_MAX)
        if self.velocity is not None:
            _validate_range("velocity", self.velocity, 0, DATA_BYTE_MAX)
        if self.control is not None:
            _validate_range("control", self.control, 0, DATA_BYTE_MAX)
        if self.value is not None:
            _validate_range("value", self.value, 0, DATA_BYTE_MAX)
        if self.program is not None:
            _validate_range("program", self.program, 0, DATA_BYTE_MAX)

    @classmethod
    def note_on(cls, note: int, velocity: int = 96, channel: int = 0) -> "MidiMessage":
        return cls("note_on", channel=channel, note=note, velocity=velocity)

    @classmethod
    def note_off(cls, note: int, velocity: int = 0, channel: int = 0) -> "MidiMessage":
        return cls("note_off", channel=channel, note=note, velocity=velocity)

    @classmethod
    def control_change(cls, control: int, value: int, channel: int = 0) -> "MidiMessage":
        return cls("control_change", channel=channel, control=control, value=value)

    @classmethod
    def program_change(cls, program: int, channel: int = 0) -> "MidiMessage":
        return cls("program_change", channel=channel, program=program)

    @classmethod
    def clock(cls) -> "MidiMessage":
        return cls("clock")

    @classmethod
    def start(cls) -> "MidiMessage":
        return cls("start")

    @classmethod
    def stop(cls) -> "MidiMessage":
        return cls("stop")

    @classmethod
    def sysex(cls, data: bytes) -> "MidiMessage":
        return cls("sysex", data=bytes(data))

    @classmethod
    def continue_(cls) -> "MidiMessage":
        return cls("continue")

    def to_mido(self):
        """Convert to a `mido.Message` if mido is installed."""
        if importlib.util.find_spec("mido") is None:
            raise RuntimeError("mido is not installed.")
        import mido

        if self.kind == "note_on":
            return mido.Message("note_on", channel=self.channel, note=self.note, velocity=self.velocity)
        if self.kind == "note_off":
            return mido.Message("note_off", channel=self.channel, note=self.note, velocity=self.velocity)
        if self.kind == "control_change":
            return mido.Message("control_change", channel=self.channel, control=self.control, value=self.value)
        if self.kind == "program_change":
            return mido.Message("program_change", channel=self.channel, program=self.program)
        if self.kind in {"clock", "start", "stop", "continue"}:
            return mido.Message(self.kind)
        if self.kind == "sysex":
            return mido.Message("sysex", data=list(self.data or b""))
        raise ValueError(f"Unsupported MIDI message kind: {self.kind}")

    def display(self) -> str:
        fields = []
        for name in ("channel", "note", "velocity", "control", "value", "program"):
            value = getattr(self, name)
            if value is not None:
                fields.append(f"{name}={value}")
        if self.data:
            fields.append(f"data_len={len(self.data)}")
        suffix = " " + " ".join(fields) if fields else ""
        return f"{self.kind}{suffix}"


class MidiBackend(Protocol):
    """Backend interface for dry-run and hardware MIDI adapters."""

    def list_input_ports(self) -> list[str]:
        ...

    def list_output_ports(self) -> list[str]:
        ...

    def send(self, port_name: str | None, message: MidiMessage) -> None:
        ...


class DryRunMidiBackend:
    """In-memory backend used for tests and safe exploration."""

    def __init__(self, input_ports: list[str] | None = None, output_ports: list[str] | None = None):
        self.input_ports = input_ports or []
        self.output_ports = output_ports or []
        self.sent: list[tuple[str | None, MidiMessage]] = []

    def list_input_ports(self) -> list[str]:
        return list(self.input_ports)

    def list_output_ports(self) -> list[str]:
        return list(self.output_ports)

    def send(self, port_name: str | None, message: MidiMessage) -> None:
        self.sent.append((port_name, message))


class MidoMidiBackend:
    """Hardware MIDI backend using mido when available."""

    def __init__(self):
        missing = [
            package
            for package in ("mido", "rtmidi")
            if importlib.util.find_spec(package) is None
        ]
        if missing:
            raise RuntimeError(
                "Install mido and python-rtmidi to use the mido live MIDI backend "
                f"(missing: {', '.join(missing)})."
            )
        import mido

        self._mido = mido
        self._outputs = {}

    def list_input_ports(self) -> list[str]:
        return list(self._mido.get_input_names())

    def list_output_ports(self) -> list[str]:
        return list(self._mido.get_output_names())

    def send(self, port_name: str | None, message: MidiMessage) -> None:
        if not port_name:
            raise ValueError("A MIDI output port is required for live send.")
        output = self._outputs.get(port_name)
        if output is None:
            output = self._mido.open_output(port_name)
            self._outputs[port_name] = output
        output.send(message.to_mido())


class WinMMMidiBackend:
    """Native Windows MIDI backend using winmm, with no third-party packages."""

    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("WinMM MIDI is only available on Windows.")
        self._winmm = ctypes.WinDLL("winmm")
        self._outputs: dict[str, ctypes.c_void_p] = {}

    def list_input_ports(self) -> list[str]:
        inputs, _, _ = _winmm_port_names()
        return inputs

    def list_output_ports(self) -> list[str]:
        _, outputs, _ = _winmm_port_names()
        return outputs

    def send(self, port_name: str | None, message: MidiMessage) -> None:
        if not port_name:
            raise ValueError("A MIDI output port is required for live send.")
        output = self._outputs.get(port_name)
        if output is None:
            output = self._open_output(port_name)
            self._outputs[port_name] = output
        if message.kind == "sysex":
            _send_winmm_sysex(self._winmm, output, message.data or b"")
            return
        result = self._winmm.midiOutShortMsg(output, _to_winmm_short_message(message))
        if result != 0:
            raise RuntimeError(f"WinMM midiOutShortMsg failed with code {result}.")

    def close(self) -> None:
        for output in self._outputs.values():
            self._winmm.midiOutClose(output)
        self._outputs.clear()

    def _open_output(self, port_name: str) -> ctypes.c_void_p:
        outputs = self.list_output_ports()
        try:
            device_id = outputs.index(port_name)
        except ValueError as exc:
            raise ValueError(f"MIDI output port is not visible through WinMM: {port_name}") from exc
        handle = ctypes.c_void_p()
        result = self._winmm.midiOutOpen(ctypes.byref(handle), device_id, 0, 0, 0)
        if result != 0:
            raise RuntimeError(f"WinMM midiOutOpen failed with code {result}.")
        return handle


class WinMMInputMonitor:
    """Native Windows MIDI input monitor for short messages and optional SysEx."""

    def __init__(
        self,
        port_name: str,
        callback: Callable[[MidiMessage], None],
        *,
        include_sysex: bool = False,
        sysex_buffer_size: int = 4 * 1024 * 1024,
        sysex_buffer_count: int = 2,
    ):
        if sys.platform != "win32":
            raise RuntimeError("WinMM MIDI input is only available on Windows.")
        self.port_name = port_name
        self.callback = callback
        self.include_sysex = include_sysex
        self.sysex_buffer_size = sysex_buffer_size
        self.sysex_buffer_count = sysex_buffer_count
        self._winmm = ctypes.WinDLL("winmm")
        self._handle = ctypes.c_void_p()
        self._callback_type = ctypes.WINFUNCTYPE(
            None,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        self._callback_ref = self._callback_type(self._handle_message)
        self._started = False
        self._sysex_buffers: list[tuple[ctypes.Array, "_MidiHeader"]] = []

    def start(self) -> None:
        inputs, _, _ = _winmm_port_names()
        try:
            device_id = inputs.index(self.port_name)
        except ValueError as exc:
            raise ValueError(f"MIDI input port is not visible through WinMM: {self.port_name}") from exc
        result = self._winmm.midiInOpen(
            ctypes.byref(self._handle),
            device_id,
            self._callback_ref,
            0,
            0x00030000,
        )
        if result != 0:
            raise RuntimeError(f"WinMM midiInOpen failed with code {result}.")
        if self.include_sysex:
            self._prepare_sysex_buffers()
        result = self._winmm.midiInStart(self._handle)
        if result != 0:
            self._unprepare_sysex_buffers()
            self._winmm.midiInClose(self._handle)
            raise RuntimeError(f"WinMM midiInStart failed with code {result}.")
        self._started = True

    def stop(self) -> None:
        if not self._handle:
            return
        if self._started:
            self._started = False
            self._winmm.midiInStop(self._handle)
            self._winmm.midiInReset(self._handle)
        self._unprepare_sysex_buffers()
        self._winmm.midiInClose(self._handle)
        self._handle = ctypes.c_void_p()

    def _handle_message(
        self,
        _handle: ctypes.c_void_p,
        message_type: int,
        _instance: ctypes.c_void_p,
        param1: ctypes.c_void_p,
        _param2: ctypes.c_void_p,
    ) -> None:
        if message_type == 0x3C3:
            try:
                message = _from_winmm_short_message(int(param1))
            except ValueError:
                return
            self.callback(message)
            return
        if message_type == 0x3C4 and self.include_sysex:
            self._handle_sysex_buffer(param1)

    def _prepare_sysex_buffers(self) -> None:
        for _ in range(max(1, self.sysex_buffer_count)):
            buffer = ctypes.create_string_buffer(max(256, self.sysex_buffer_size))
            header = _MidiHeader()
            header.lpData = ctypes.addressof(buffer)
            header.dwBufferLength = len(buffer)
            result = self._winmm.midiInPrepareHeader(
                self._handle,
                ctypes.byref(header),
                ctypes.sizeof(header),
            )
            if result != 0:
                raise RuntimeError(f"WinMM midiInPrepareHeader failed with code {result}.")
            result = self._winmm.midiInAddBuffer(self._handle, ctypes.byref(header), ctypes.sizeof(header))
            if result != 0:
                raise RuntimeError(f"WinMM midiInAddBuffer failed with code {result}.")
            self._sysex_buffers.append((buffer, header))

    def _unprepare_sysex_buffers(self) -> None:
        for _buffer, header in self._sysex_buffers:
            self._winmm.midiInUnprepareHeader(self._handle, ctypes.byref(header), ctypes.sizeof(header))
        self._sysex_buffers.clear()

    def _handle_sysex_buffer(self, param1: ctypes.c_void_p) -> None:
        if not param1:
            return
        header_pointer = ctypes.cast(param1, ctypes.POINTER(_MidiHeader))
        header = header_pointer.contents
        if header.dwBytesRecorded:
            data = ctypes.string_at(header.lpData, header.dwBytesRecorded)
            self.callback(MidiMessage.sysex(data))
        if self._started:
            header.dwBytesRecorded = 0
            self._winmm.midiInAddBuffer(self._handle, header_pointer, ctypes.sizeof(_MidiHeader))


def midi_capability_report() -> dict[str, object]:
    """Return local MIDI package availability and visible ports when possible."""
    winmm_inputs, winmm_outputs, winmm_error = _winmm_port_names()
    usb_devices = _usb_device_report()
    ko2_usb_devices = [
        device
        for device in usb_devices
        if KO2_USB_VENDOR_ID in device["hardware_id"].upper()
        and KO2_USB_PRODUCT_ID in device["hardware_id"].upper()
    ]
    report: dict[str, object] = {
        "mido_installed": importlib.util.find_spec("mido") is not None,
        "rtmidi_installed": importlib.util.find_spec("rtmidi") is not None,
        "native_winmm_available": sys.platform == "win32" and winmm_error is None,
        "live_midi_available": sys.platform == "win32" and winmm_error is None and bool(winmm_outputs),
        "live_backend": "winmm" if sys.platform == "win32" and winmm_error is None and winmm_outputs else None,
        "input_ports": winmm_inputs,
        "output_ports": winmm_outputs,
        "port_source": "winmm",
        "usb_devices": usb_devices,
        "ko2_usb_connected": bool(ko2_usb_devices),
        "ko2_usb_devices": ko2_usb_devices,
        "ko2_midi_ports": [
            port
            for port in [*winmm_inputs, *winmm_outputs]
            if _looks_like_ko2_port(port)
        ],
        "ko2_midi_ready": False,
        "winmm_error": winmm_error,
        "error": None,
        "mido_error": None,
        "hints": [],
    }
    if not report["mido_installed"]:
        report["mido_error"] = "mido not installed."
        report["hints"] = [
            "Install mido and python-rtmidi only if you prefer the mido backend; native WinMM can send short MIDI messages on Windows.",
            "Use dry-run commands until the intended sampler appears as a MIDI output.",
        ]
    else:
        try:
            backend = MidoMidiBackend()
            report["input_ports"] = backend.list_input_ports()
            report["output_ports"] = backend.list_output_ports()
            report["port_source"] = "mido"
            report["live_midi_available"] = True
            report["live_backend"] = "mido"
        except Exception as exc:
            report["mido_error"] = str(exc)
    if report["ko2_usb_connected"] and not report["ko2_midi_ports"]:
        ko2_classes = sorted({device.get("usb_class") for device in ko2_usb_devices if device.get("usb_class")})
        report["hints"] = [
            *report["hints"],
            "EP-133 is connected over USB, but Windows exposes it as USB Audio rather than a MIDI input/output endpoint.",
            f"Detected EP-133 USB classes: {', '.join(ko2_classes) or 'unknown'}. USB MIDI streaming would normally appear as Class_01/SubClass_03.",
        ]
    report["ko2_midi_ready"] = bool(report["ko2_midi_ports"])
    if not any(_looks_like_ko2_port(port) for port in [*report["input_ports"], *report["output_ports"]]):
        report["hints"] = [
            *report["hints"],
            "No visible port name looks like KO II; check the cable, device USB mode, drivers, or MIDI interface routing.",
        ]
    if not report["live_midi_available"]:
        report["hints"] = [
            *report["hints"],
            "Live MIDI needs a visible MIDI output port. USB connection alone is not enough if Windows exposes only USB Audio.",
        ]
    return report


def _looks_like_ko2_port(port_name: str) -> bool:
    normalized = port_name.lower()
    return any(token in normalized for token in ("ko ii", "k.o", "ep-133", "ep133", "ko2"))


class _MidiHeader(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_void_p),
        ("dwBufferLength", ctypes.c_uint32),
        ("dwBytesRecorded", ctypes.c_uint32),
        ("dwUser", ctypes.c_size_t),
        ("dwFlags", ctypes.c_uint32),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_size_t),
        ("dwOffset", ctypes.c_uint32),
        ("dwReserved", ctypes.c_size_t * 8),
    ]


def _send_winmm_sysex(
    winmm,
    output: ctypes.c_void_p,
    data: bytes,
    timeout_sec: float = 2.0,
) -> None:
    if not data or data[0] != 0xF0 or data[-1] != 0xF7:
        raise ValueError("SysEx messages must include F0 start and F7 end bytes.")
    buffer = ctypes.create_string_buffer(data)
    header = _MidiHeader()
    header.lpData = ctypes.addressof(buffer)
    header.dwBufferLength = len(data)
    result = winmm.midiOutPrepareHeader(output, ctypes.byref(header), ctypes.sizeof(header))
    if result != 0:
        raise RuntimeError(f"WinMM midiOutPrepareHeader failed with code {result}.")
    try:
        result = winmm.midiOutLongMsg(output, ctypes.byref(header), ctypes.sizeof(header))
        if result != 0:
            raise RuntimeError(f"WinMM midiOutLongMsg failed with code {result}.")
        deadline = time.monotonic() + max(0.1, timeout_sec)
        while not header.dwFlags & 0x00000001:
            if time.monotonic() > deadline:
                raise TimeoutError("Timed out waiting for WinMM SysEx send to complete.")
            time.sleep(0.01)
    finally:
        winmm.midiOutUnprepareHeader(output, ctypes.byref(header), ctypes.sizeof(header))


def _to_winmm_short_message(message: MidiMessage) -> int:
    if message.kind == "note_on":
        return (0x90 | int(message.channel or 0)) | (int(message.note or 0) << 8) | (int(message.velocity or 0) << 16)
    if message.kind == "note_off":
        return (0x80 | int(message.channel or 0)) | (int(message.note or 0) << 8) | (int(message.velocity or 0) << 16)
    if message.kind == "control_change":
        return (0xB0 | int(message.channel or 0)) | (int(message.control or 0) << 8) | (int(message.value or 0) << 16)
    if message.kind == "program_change":
        return (0xC0 | int(message.channel or 0)) | (int(message.program or 0) << 8)
    if message.kind == "clock":
        return 0xF8
    if message.kind == "start":
        return 0xFA
    if message.kind == "continue":
        return 0xFB
    if message.kind == "stop":
        return 0xFC
    raise ValueError(f"Unsupported WinMM short MIDI message kind: {message.kind}")


def _from_winmm_short_message(packed: int) -> MidiMessage:
    status = packed & 0xFF
    data1 = (packed >> 8) & 0xFF
    data2 = (packed >> 16) & 0xFF
    high = status & 0xF0
    channel = status & 0x0F
    if high == 0x80:
        return MidiMessage.note_off(data1, velocity=data2, channel=channel)
    if high == 0x90:
        if data2 == 0:
            return MidiMessage.note_off(data1, velocity=0, channel=channel)
        return MidiMessage.note_on(data1, velocity=data2, channel=channel)
    if high == 0xB0:
        return MidiMessage.control_change(data1, data2, channel=channel)
    if high == 0xC0:
        return MidiMessage.program_change(data1, channel=channel)
    if status == 0xF8:
        return MidiMessage.clock()
    if status == 0xFA:
        return MidiMessage.start()
    if status == 0xFB:
        return MidiMessage.continue_()
    if status == 0xFC:
        return MidiMessage.stop()
    raise ValueError(f"Unsupported WinMM input message: 0x{packed:06x}")


def _validate_range(name: str, value: int | None, low: int, high: int) -> None:
    if value is None or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}.")


def _winmm_port_names() -> tuple[list[str], list[str], str | None]:
    """Enumerate Windows MIDI port names without external dependencies."""
    if sys.platform != "win32":
        return [], [], None
    try:
        import ctypes
        from ctypes import wintypes

        max_name = 32

        class MidiOutCaps(ctypes.Structure):
            _fields_ = [
                ("wMid", wintypes.WORD),
                ("wPid", wintypes.WORD),
                ("vDriverVersion", wintypes.UINT),
                ("szPname", wintypes.WCHAR * max_name),
                ("wTechnology", wintypes.WORD),
                ("wVoices", wintypes.WORD),
                ("wNotes", wintypes.WORD),
                ("wChannelMask", wintypes.WORD),
                ("dwSupport", wintypes.DWORD),
            ]

        class MidiInCaps(ctypes.Structure):
            _fields_ = [
                ("wMid", wintypes.WORD),
                ("wPid", wintypes.WORD),
                ("vDriverVersion", wintypes.UINT),
                ("szPname", wintypes.WCHAR * max_name),
                ("dwSupport", wintypes.DWORD),
            ]

        winmm = ctypes.WinDLL("winmm")
        outputs = []
        for index in range(winmm.midiOutGetNumDevs()):
            caps = MidiOutCaps()
            result = winmm.midiOutGetDevCapsW(index, ctypes.byref(caps), ctypes.sizeof(caps))
            if result == 0:
                outputs.append(caps.szPname)
        inputs = []
        for index in range(winmm.midiInGetNumDevs()):
            caps = MidiInCaps()
            result = winmm.midiInGetDevCapsW(index, ctypes.byref(caps), ctypes.sizeof(caps))
            if result == 0:
                inputs.append(caps.szPname)
        return inputs, outputs, None
    except Exception as exc:
        return [], [], str(exc)


def _usb_device_report() -> list[dict[str, str]]:
    """Read connected USB device metadata from the Windows registry."""
    if sys.platform != "win32":
        return []
    try:
        import winreg

        devices: list[dict[str, str]] = []
        root_path = r"SYSTEM\CurrentControlSet\Enum\USB"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root_path) as root:
            for vendor_index in range(winreg.QueryInfoKey(root)[0]):
                vendor_id = winreg.EnumKey(root, vendor_index)
                if not vendor_id.upper().startswith("VID_"):
                    continue
                with winreg.OpenKey(root, vendor_id) as vendor_key:
                    for instance_index in range(winreg.QueryInfoKey(vendor_key)[0]):
                        instance = winreg.EnumKey(vendor_key, instance_index)
                        with winreg.OpenKey(vendor_key, instance) as instance_key:
                            devices.append(
                                {
                                    "hardware_id": vendor_id,
                                    "instance": instance,
                                    "friendly_name": _registry_value(instance_key, "FriendlyName"),
                                    "device_description": _registry_value(instance_key, "DeviceDesc"),
                                    "manufacturer": _registry_value(instance_key, "Mfg"),
                                    "service": _registry_value(instance_key, "Service"),
                                    "usb_class": _usb_class_from_ids(_registry_values(instance_key, "CompatibleIDs")),
                                    "compatible_ids": "; ".join(_registry_values(instance_key, "CompatibleIDs")),
                                }
                            )
        return devices
    except Exception:
        return []


def _registry_value(key, name: str) -> str:
    try:
        value, _ = __import__("winreg").QueryValueEx(key, name)
    except OSError:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item) for item in value)
    return str(value)


def _registry_values(key, name: str) -> list[str]:
    try:
        value, _ = __import__("winreg").QueryValueEx(key, name)
    except OSError:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _usb_class_from_ids(compatible_ids: list[str]) -> str:
    normalized = [item.replace("Subclass_", "SubClass_") for item in compatible_ids]
    joined = " ".join(normalized)
    if _has_usb_class(normalized, "01", "03"):
        return "usb-midi-streaming"
    if _has_usb_class(normalized, "01", "01"):
        return "usb-audio-control"
    if _has_usb_class(normalized, "01"):
        return "usb-audio"
    if "USB\\COMPOSITE" in joined:
        return "usb-composite"
    return ""


def _has_usb_class(compatible_ids: list[str], class_id: str, subclass_id: str | None = None) -> bool:
    class_patterns = (f"USB\\Class_{class_id}", f"&Class_{class_id}")
    subclass_pattern = f"SubClass_{subclass_id}" if subclass_id is not None else None
    return any(
        any(pattern in item for pattern in class_patterns)
        and (subclass_pattern is None or subclass_pattern in item)
        for item in compatible_ids
    )
