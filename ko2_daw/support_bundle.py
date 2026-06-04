"""Support bundle export for debugging connected KO II sessions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
import platform
import zipfile

from ko2_daw.config import load_app_settings
from ko2_daw.diagnostics import readiness_report
from ko2_daw.midi import midi_capability_report
from ko2_daw.routing import resolve_ko2_route


def create_support_bundle(
    output_dir: str | Path = "daw_projects",
    *,
    settings_path: str | Path = "ko2_app_settings.json",
    project_root: str | Path = "daw_projects",
) -> Path:
    """Create a timestamped ZIP with non-destructive diagnostics and local state."""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bundle_path = out_dir / f"support_bundle_{timestamp}.zip"

    report = midi_capability_report()
    settings = load_app_settings(settings_path)
    try:
        route = resolve_ko2_route(report, settings.preferred_route if settings.preferred_route != "manual" else "auto")
        route_payload = route.__dict__
    except Exception as exc:  # defensive: support bundle should not fail on route errors
        route_payload = {"error": str(exc)}

    payloads: dict[str, object] = {
        "manifest.json": {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "app": "ko2-daw",
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "midi_report.json": report,
        "readiness_report.json": readiness_report(report),
        "route.json": route_payload,
        "settings.json": settings.to_dict(),
    }

    project_path = Path(project_root)
    optional_files = [
        project_path / "hardware_file_cache.json",
        project_path / "ko2_state.json",
        project_path / "companion_session.json",
        Path("docs") / "ko2_device_interaction_capabilities.txt",
    ]

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in payloads.items():
            archive.writestr(name, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        for path in optional_files:
            if path.exists() and path.is_file():
                archive.write(path, f"files/{path.as_posix()}")

    return bundle_path.resolve()
