"""Native Windows PCM capture through the WinMM waveIn API."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Callable
import wave


WAVE_FORMAT_PCM = 1
CALLBACK_NULL = 0
WHDR_DONE = 0x00000001
MMSYSERR_NOERROR = 0
WAVERR_STILLPLAYING = 33


class WAVEFORMATEX(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


class WAVEHDR(ctypes.Structure):
    pass


WAVEHDR._fields_ = [
    ("lpData", ctypes.c_void_p),
    ("dwBufferLength", wintypes.DWORD),
    ("dwBytesRecorded", wintypes.DWORD),
    ("dwUser", ctypes.c_size_t),
    ("dwFlags", wintypes.DWORD),
    ("dwLoops", wintypes.DWORD),
    ("lpNext", ctypes.POINTER(WAVEHDR)),
    ("reserved", ctypes.c_size_t),
]


class WAVEINCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.DWORD),
        ("szPname", wintypes.WCHAR * 32),
        ("dwFormats", wintypes.DWORD),
        ("wChannels", wintypes.WORD),
        ("wReserved1", wintypes.WORD),
    ]


@dataclass(frozen=True)
class WaveInputDevice:
    device_id: int
    name: str
    channels: int
    format_mask: int


@dataclass(frozen=True)
class AudioCaptureResult:
    path: Path
    device: WaveInputDevice
    sample_rate: int
    channels: int
    bits_per_sample: int
    frames: int
    duration_sec: float
    bytes_recorded: int


def list_wave_input_devices() -> list[WaveInputDevice]:
    if sys.platform != "win32":
        return []
    winmm = ctypes.WinDLL("winmm")
    count = int(winmm.waveInGetNumDevs())
    devices: list[WaveInputDevice] = []
    for device_id in range(count):
        caps = WAVEINCAPSW()
        result = winmm.waveInGetDevCapsW(
            device_id,
            ctypes.byref(caps),
            ctypes.sizeof(caps),
        )
        if result == MMSYSERR_NOERROR:
            devices.append(
                WaveInputDevice(
                    device_id=device_id,
                    name=str(caps.szPname),
                    channels=int(caps.wChannels),
                    format_mask=int(caps.dwFormats),
                )
            )
    return devices


def record_wave_input(
    path: str | Path,
    *,
    device_name: str | None = None,
    device_id: int | None = None,
    duration_sec: float = 10.0,
    sample_rate: int = 48000,
    channels: int = 2,
    bits_per_sample: int = 16,
    buffer_ms: int = 100,
    buffer_count: int = 6,
    stop_event: threading.Event | None = None,
    progress: Callable[[float, float], None] | None = None,
) -> AudioCaptureResult:
    """Record a bounded PCM WAV from a visible Windows wave input."""

    if sys.platform != "win32":
        raise RuntimeError("Native wave input capture is available only on Windows.")
    if not 0.05 <= duration_sec <= 60 * 60:
        raise ValueError("Capture duration must be between 0.05 seconds and one hour.")
    if sample_rate not in {8000, 11025, 16000, 22050, 32000, 44100, 46875, 48000, 88200, 96000}:
        raise ValueError("Unsupported capture sample rate.")
    if channels not in {1, 2}:
        raise ValueError("Capture channels must be mono or stereo.")
    if bits_per_sample not in {8, 16, 24, 32}:
        raise ValueError("Capture bit depth must be 8, 16, 24, or 32.")
    if not 20 <= buffer_ms <= 1000 or not 2 <= buffer_count <= 32:
        raise ValueError("Capture buffer configuration is outside safe limits.")

    devices = list_wave_input_devices()
    device = _resolve_wave_input(devices, device_name=device_name, device_id=device_id)
    if channels > device.channels:
        raise ValueError(
            f"Input {device.name!r} exposes {device.channels} channels, not {channels}."
        )

    block_align = channels * (bits_per_sample // 8)
    average_bytes = sample_rate * block_align
    target_bytes = round(duration_sec * average_bytes)
    target_bytes -= target_bytes % block_align
    buffer_bytes = max(block_align, round(average_bytes * buffer_ms / 1000))
    buffer_bytes -= buffer_bytes % block_align
    wave_format = WAVEFORMATEX(
        WAVE_FORMAT_PCM,
        channels,
        sample_rate,
        average_bytes,
        block_align,
        bits_per_sample,
        0,
    )

    winmm = ctypes.WinDLL("winmm")
    handle = ctypes.c_void_p()
    result = winmm.waveInOpen(
        ctypes.byref(handle),
        device.device_id,
        ctypes.byref(wave_format),
        0,
        0,
        CALLBACK_NULL,
    )
    if result != MMSYSERR_NOERROR:
        raise RuntimeError(
            f"WinMM waveInOpen failed for {device.name!r} with code {result}."
        )

    buffers: list[ctypes.Array] = []
    headers: list[WAVEHDR] = []
    chunks: list[bytes] = []
    recorded = 0
    try:
        for _index in range(buffer_count):
            buffer = ctypes.create_string_buffer(buffer_bytes)
            header = WAVEHDR(
                ctypes.cast(buffer, ctypes.c_void_p),
                buffer_bytes,
                0,
                0,
                0,
                0,
                None,
                0,
            )
            _check_mm(
                winmm.waveInPrepareHeader(
                    handle,
                    ctypes.byref(header),
                    ctypes.sizeof(header),
                ),
                "waveInPrepareHeader",
            )
            _check_mm(
                winmm.waveInAddBuffer(
                    handle,
                    ctypes.byref(header),
                    ctypes.sizeof(header),
                ),
                "waveInAddBuffer",
            )
            buffers.append(buffer)
            headers.append(header)
        _check_mm(winmm.waveInStart(handle), "waveInStart")
        deadline = time.monotonic() + duration_sec + max(2.0, buffer_ms / 1000 * 4)
        while recorded < target_bytes:
            progressed = False
            for buffer, header in zip(buffers, headers):
                if not (header.dwFlags & WHDR_DONE):
                    continue
                count = min(int(header.dwBytesRecorded), target_bytes - recorded)
                count -= count % block_align
                if count:
                    chunks.append(bytes(buffer.raw[:count]))
                    recorded += count
                    progressed = True
                header.dwBytesRecorded = 0
                if recorded < target_bytes:
                    _check_mm(
                        winmm.waveInAddBuffer(
                            handle,
                            ctypes.byref(header),
                            ctypes.sizeof(header),
                        ),
                        "waveInAddBuffer",
                    )
            if recorded >= target_bytes:
                break
            if stop_event is not None and stop_event.is_set() and recorded > 0:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Audio capture stopped after {recorded} of {target_bytes} bytes."
                )
            if not progressed:
                time.sleep(0.004)
            if progress is not None:
                try:
                    progress(recorded / average_bytes, duration_sec)
                except Exception:
                    pass
        winmm.waveInStop(handle)
        winmm.waveInReset(handle)
    finally:
        if handle:
            winmm.waveInStop(handle)
            winmm.waveInReset(handle)
            for header in headers:
                for _attempt in range(50):
                    result = winmm.waveInUnprepareHeader(
                        handle,
                        ctypes.byref(header),
                        ctypes.sizeof(header),
                    )
                    if result == MMSYSERR_NOERROR:
                        break
                    if result != WAVERR_STILLPLAYING:
                        break
                    time.sleep(0.01)
            winmm.waveInClose(handle)

    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "wb",
        delete=False,
        dir=target.parent,
        suffix=".wav",
    ) as temporary:
        temp_path = Path(temporary.name)
    try:
        with wave.open(str(temp_path), "wb") as output:
            output.setnchannels(channels)
            output.setsampwidth(bits_per_sample // 8)
            output.setframerate(sample_rate)
            for chunk in chunks:
                output.writeframesraw(chunk)
        temp_path.replace(target)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    frames = recorded // block_align
    return AudioCaptureResult(
        path=target,
        device=device,
        sample_rate=sample_rate,
        channels=channels,
        bits_per_sample=bits_per_sample,
        frames=frames,
        duration_sec=frames / sample_rate,
        bytes_recorded=recorded,
    )


def _resolve_wave_input(
    devices: list[WaveInputDevice],
    *,
    device_name: str | None,
    device_id: int | None,
) -> WaveInputDevice:
    if device_id is not None:
        for device in devices:
            if device.device_id == int(device_id):
                return device
        raise ValueError(f"Wave input device id {device_id} is not visible.")
    if device_name:
        exact = [device for device in devices if device.name.casefold() == device_name.casefold()]
        if len(exact) == 1:
            return exact[0]
        partial = [
            device
            for device in devices
            if device_name.casefold() in device.name.casefold()
        ]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            names = ", ".join(device.name for device in partial)
            raise ValueError(f"Wave input name {device_name!r} is ambiguous: {names}")
        raise ValueError(f"Wave input {device_name!r} is not visible.")
    if not devices:
        raise RuntimeError("No Windows wave input devices are visible.")
    return devices[0]


def _check_mm(result: int, operation: str) -> None:
    if result != MMSYSERR_NOERROR:
        raise RuntimeError(f"WinMM {operation} failed with code {result}.")
