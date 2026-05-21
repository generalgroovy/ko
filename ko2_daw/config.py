"""Configuration models for safe external-device interaction."""

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class DeviceSafetyConfig:
    """Safety controls for hardware-facing MIDI operations."""

    dry_run: bool = True
    allowed_output_ports: tuple[str, ...] = ()
    sysex_enabled: bool = False
    max_sysex_bytes: int = 0
    backup_dir: Path = Path("daw_backups")

    def output_port_allowed(self, port_name: str | None) -> bool:
        if self.dry_run:
            return True
        if not port_name:
            return False
        return any(allowed.lower() in port_name.lower() for allowed in self.allowed_output_ports)


@dataclass(frozen=True)
class DAWConfig:
    """Runtime DAW control configuration."""

    bpm: float = 120.0
    midi_channel: int = 0
    clock_enabled: bool = False
    safety: DeviceSafetyConfig = field(default_factory=DeviceSafetyConfig)

    def validate(self) -> None:
        if not 20 <= self.bpm <= 300:
            raise ValueError("BPM must be between 20 and 300.")
        if not 0 <= self.midi_channel <= 15:
            raise ValueError("MIDI channel must be zero-based and between 0 and 15.")

    @property
    def clock_interval_sec(self) -> float:
        """Return MIDI clock pulse interval for 24 PPQN."""
        return 60.0 / (self.bpm * 24.0)


APP_ACCESS_MODES = ("read-only", "read-playback", "expert-write")


@dataclass
class AppSettings:
    """Persistent GUI settings for routing, device access, and scan behavior."""

    preferred_route: str = "auto"
    preferred_input_port: str = ""
    preferred_output_port: str = ""
    access_mode: str = "read-playback"
    auto_connect_on_start: bool = True
    sysex_enabled: bool = True
    auto_scan_on_connect: bool = True
    allow_file_playback: bool = True
    require_playback_confirmation: bool = True
    sysex_timeout_sec: float = 2.0
    max_sysex_bytes: int = 4 * 1024 * 1024
    scan_pages_per_dir: int = 32
    scan_max_depth: int = 6
    scan_max_dirs: int = 500
    write_arm_phrase: str = ""

    def validate(self) -> None:
        if self.preferred_route not in {"auto", "usb-midi", "quad-capture", "manual"}:
            raise ValueError("preferred_route must be auto, usb-midi, quad-capture, or manual.")
        if self.access_mode not in APP_ACCESS_MODES:
            raise ValueError(f"access_mode must be one of {', '.join(APP_ACCESS_MODES)}.")
        if not 0.2 <= float(self.sysex_timeout_sec) <= 30.0:
            raise ValueError("sysex_timeout_sec must be between 0.2 and 30.")
        if not 1024 <= int(self.max_sysex_bytes) <= 16 * 1024 * 1024:
            raise ValueError("max_sysex_bytes must be between 1024 and 16777216.")
        if not 1 <= int(self.scan_pages_per_dir) <= 128:
            raise ValueError("scan_pages_per_dir must be between 1 and 128.")
        if not 0 <= int(self.scan_max_depth) <= 16:
            raise ValueError("scan_max_depth must be between 0 and 16.")
        if not 1 <= int(self.scan_max_dirs) <= 5000:
            raise ValueError("scan_max_dirs must be between 1 and 5000.")

    @property
    def playback_enabled(self) -> bool:
        return self.sysex_enabled and self.allow_file_playback and self.access_mode in {"read-playback", "expert-write"}

    @property
    def write_enabled(self) -> bool:
        return self.access_mode == "expert-write" and self.write_arm_phrase.strip().upper() == "WRITE"

    def to_dict(self) -> dict[str, object]:
        return {
            "preferred_route": self.preferred_route,
            "preferred_input_port": self.preferred_input_port,
            "preferred_output_port": self.preferred_output_port,
            "access_mode": self.access_mode,
            "auto_connect_on_start": self.auto_connect_on_start,
            "sysex_enabled": self.sysex_enabled,
            "auto_scan_on_connect": self.auto_scan_on_connect,
            "allow_file_playback": self.allow_file_playback,
            "require_playback_confirmation": self.require_playback_confirmation,
            "sysex_timeout_sec": self.sysex_timeout_sec,
            "max_sysex_bytes": self.max_sysex_bytes,
            "scan_pages_per_dir": self.scan_pages_per_dir,
            "scan_max_depth": self.scan_max_depth,
            "scan_max_dirs": self.scan_max_dirs,
            "write_arm_phrase": self.write_arm_phrase,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AppSettings":
        defaults = cls()
        settings = cls(
            preferred_route=str(data.get("preferred_route", defaults.preferred_route)),
            preferred_input_port=str(data.get("preferred_input_port", defaults.preferred_input_port)),
            preferred_output_port=str(data.get("preferred_output_port", defaults.preferred_output_port)),
            access_mode=str(data.get("access_mode", defaults.access_mode)),
            auto_connect_on_start=bool(data.get("auto_connect_on_start", defaults.auto_connect_on_start)),
            sysex_enabled=bool(data.get("sysex_enabled", defaults.sysex_enabled)),
            auto_scan_on_connect=bool(data.get("auto_scan_on_connect", defaults.auto_scan_on_connect)),
            allow_file_playback=bool(data.get("allow_file_playback", defaults.allow_file_playback)),
            require_playback_confirmation=bool(
                data.get("require_playback_confirmation", defaults.require_playback_confirmation)
            ),
            sysex_timeout_sec=float(data.get("sysex_timeout_sec", defaults.sysex_timeout_sec)),
            max_sysex_bytes=int(data.get("max_sysex_bytes", defaults.max_sysex_bytes)),
            scan_pages_per_dir=int(data.get("scan_pages_per_dir", defaults.scan_pages_per_dir)),
            scan_max_depth=int(data.get("scan_max_depth", defaults.scan_max_depth)),
            scan_max_dirs=int(data.get("scan_max_dirs", defaults.scan_max_dirs)),
            write_arm_phrase=str(data.get("write_arm_phrase", defaults.write_arm_phrase)),
        )
        settings.validate()
        return settings


def load_app_settings(path: str | Path) -> AppSettings:
    settings_path = Path(path)
    if not settings_path.exists():
        return AppSettings()
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()
    if not isinstance(raw, dict):
        return AppSettings()
    try:
        return AppSettings.from_dict(raw)
    except (TypeError, ValueError):
        return AppSettings()


def save_app_settings(path: str | Path, settings: AppSettings) -> Path:
    settings.validate()
    settings_path = Path(path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return settings_path
