"""Shared file persistence helpers."""

from __future__ import annotations

from pathlib import Path
import tempfile


def atomic_write_text(path: str | Path, payload: str, *, encoding: str = "utf-8") -> Path:
    """Write text using a temporary file and atomic replace."""

    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding=encoding, delete=False, dir=target.parent) as handle:
        handle.write(payload)
        temp_name = handle.name
    Path(temp_name).replace(target)
    return target
