"""Professional session and device-profile models for the KO II companion app."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PadAssignment:
    group: str
    label: str
    note: int
    name: str = ""
    color: str = "#f5f0e4"


@dataclass(frozen=True)
class DeviceProfile:
    name: str
    model: str
    usb_vendor_id: str
    usb_product_id: str
    midi_channel: int
    pads: list[PadAssignment]
    supported_controls: dict[str, str] = field(default_factory=dict)
    unsupported_state_queries: list[str] = field(default_factory=list)


@dataclass
class RoutingConfig:
    input_port: str | None = None
    output_port: str | None = None
    midi_backend: str = "auto"
    live_enabled: bool = False
    allow_output: str = "KO II"


@dataclass
class CompanionSession:
    name: str
    profile: DeviceProfile
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    bpm: float = 120.0
    selected_group: str = "A"
    notes: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, object]:
        self.updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        return asdict(self)


def default_ko2_profile() -> DeviceProfile:
    labels = [".", "0", "ENTER", "1", "2", "3", "4", "5", "6", "7", "8", "9"]
    pads: list[PadAssignment] = []
    for group_index, group in enumerate(("A", "B", "C", "D")):
        base = 36 + group_index * 12
        for offset, label in enumerate(labels):
            pads.append(PadAssignment(group=group, label=label, note=base + offset, name=f"{group}{label}"))
    return DeviceProfile(
        name="EP-133 K.O. II default MIDI profile",
        model="EP-133",
        usb_vendor_id="VID_2367",
        usb_product_id="PID_0020",
        midi_channel=0,
        pads=pads,
        supported_controls={
            "transport": "MIDI start/continue/stop/clock",
            "pads": "Note on/off, groups A-D mapped to notes 36-83",
            "bank_select": "CC 0 and CC 32",
            "mod_wheel": "CC 1",
            "program_change": "Program change",
            "identity": "Universal MIDI identity request",
            "read_only_files": "TE SysEx file init/list/info/metadata probes for sounds and projects",
            "panic": "All notes off and all sound off",
        },
        unsupported_state_queries=[
            "current playing track or scene",
            "selected effect",
            "complete project contents through public MIDI",
            "pattern contents through public MIDI",
            "front-panel edit mode",
        ],
    )


def default_session(name: str = "KO II Session") -> CompanionSession:
    return CompanionSession(name=name, profile=default_ko2_profile())


class CompanionSessionStore:
    """Atomic JSON storage for companion sessions."""

    def __init__(self, root: str | Path = "daw_projects"):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, relative_path: str | Path, session: CompanionSession) -> Path:
        target = self._target(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(session.to_dict(), indent=2, sort_keys=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=target.parent) as handle:
            handle.write(payload)
            handle.write("\n")
            temp_name = handle.name
        Path(temp_name).replace(target)
        return target

    def load(self, relative_path: str | Path) -> CompanionSession:
        data = json.loads(self._target(relative_path).read_text(encoding="utf-8"))
        profile_data = data["profile"]
        pads = [PadAssignment(**pad) for pad in profile_data["pads"]]
        profile = DeviceProfile(
            name=profile_data["name"],
            model=profile_data["model"],
            usb_vendor_id=profile_data["usb_vendor_id"],
            usb_product_id=profile_data["usb_product_id"],
            midi_channel=profile_data["midi_channel"],
            pads=pads,
            supported_controls=profile_data.get("supported_controls", {}),
            unsupported_state_queries=profile_data.get("unsupported_state_queries", []),
        )
        routing = RoutingConfig(**data.get("routing", {}))
        return CompanionSession(
            name=data["name"],
            profile=profile,
            routing=routing,
            bpm=data.get("bpm", 120.0),
            selected_group=data.get("selected_group", "A"),
            notes=data.get("notes", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )

    def _target(self, relative_path: str | Path) -> Path:
        path = Path(relative_path)
        if path.is_absolute():
            raise ValueError("Session paths must be relative to the session root.")
        target = (self.root / path).resolve()
        if self.root not in (target, *target.parents):
            raise ValueError("Session path escapes the session root.")
        return target
