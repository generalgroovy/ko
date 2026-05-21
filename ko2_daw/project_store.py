"""Atomic project/session file storage for DAW experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
import tempfile


@dataclass
class ProjectSnapshot:
    """Serializable project state captured by the DAW app."""

    name: str
    bpm: float
    midi_channel: int
    notes: list[dict[str, int | float | str]] = field(default_factory=list)
    controller_log: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


class SafeProjectStore:
    """Write project snapshots atomically and keep backups of prior versions."""

    def __init__(self, root: str | Path, backup_dir: str | Path | None = None):
        self.root = Path(root).resolve()
        self.backup_dir = Path(backup_dir).resolve() if backup_dir else self.root / "backups"
        self.root.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def save(self, relative_path: str | Path, snapshot: ProjectSnapshot) -> Path:
        target = self._safe_target(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            backup = self.backup_dir / f"{target.stem}-{stamp}{target.suffix}.bak"
            backup.write_bytes(target.read_bytes())

        payload = json.dumps(asdict(snapshot), indent=2, sort_keys=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=target.parent) as handle:
            handle.write(payload)
            handle.write("\n")
            temp_name = handle.name
        Path(temp_name).replace(target)
        return target

    def load(self, relative_path: str | Path) -> ProjectSnapshot:
        target = self._safe_target(relative_path)
        data = json.loads(target.read_text(encoding="utf-8"))
        return ProjectSnapshot(**data)

    def _safe_target(self, relative_path: str | Path) -> Path:
        path = Path(relative_path)
        if path.is_absolute():
            raise ValueError("Project paths must be relative to the project store root.")
        target = (self.root / path).resolve()
        if self.root not in (target, *target.parents):
            raise ValueError("Project path escapes the project store root.")
        return target
