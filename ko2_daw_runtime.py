"""PyInstaller runtime entry point for KO II DAW."""

from __future__ import annotations

import os

from ko2_daw.launcher import main


if __name__ == "__main__":
    os.environ.setdefault("KO2_DAW_GUI_MODE", "stable")
    raise SystemExit(main([]))
