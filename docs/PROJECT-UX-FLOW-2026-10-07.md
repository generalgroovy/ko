# Know what is saved in the sample library

Baseline: `c081cf47ac42c5ad88397d148ebd7cb1ef87dc0d`. Candidate: `codex/ux-flow-2026-10-07`. The ten pre-existing untracked pytest directories are preserved.

The Samples panel previously showed the selected file and generic backup advice but did not distinguish newly imported rows from a saved table. It now uses the same small status area for **Unsaved library changes** or the last successfully saved/opened manifest name. A snapshot of the actual immutable sample rows detects changes, rather than only comparing counts. Imports, web-library merges and saved sample copies pass through the same refresh path.

A successful save confirms its filename inline and its full path in Log. The blocking success dialog is removed. The next Save Library dialog starts at that destination, keeping the operating system's normal file choice and overwrite confirmation. A cancelled or failed save does not change the saved snapshot or destination. Opening a validated library updates the baseline only after replacement is accepted. Nothing is saved automatically; JSON still references separate WAV files.

Final runtime: `85fcf9beb4ce55921dcaa39de65b5eab69218659`.

- Local Python: **220 passed, 1 existing Windows symlink-permission skip**. Ruff, Black (all 87 Python files), compilation and whitespace checks passed.
- Independent flow_a reviewed the implementation, ran 91 relevant tests (one existing skip), then accepted the small final confirmation-text change with its five targeted tests.
- [Candidate CI](https://github.com/generalgroovy/ko/actions/runs/37612069359) passed Windows Python 3.11 with **220 passed, 1 skipped**, both real Tk harnesses, lint, formatting and compilation. Linux/Xvfb exercised and captured the complete 1180×760 studio with no hardware or playback activation.
- Root inspected the [unsaved table](evidence/ux-flow-2026-10-07/workspace-selected.png) and [saved table](evidence/ux-flow-2026-10-07/workspace-saved.png). The first candidate showed a clipped full path in the header; the accepted runtime keeps the filename there and stores the full location in Log. The status fits the existing area without an extra panel. [Composed-workspace results](evidence/ux-flow-2026-10-07/workspace-results.json).

The normal main fast-forward is authorized after these checks. Native source publication and an installed build are separate: no installer replacement or desktop installation was performed. The established full-studio minimum remains 1180×760 plus window borders. This pass does not establish smaller-screen support, audible output, physical MIDI/device acceptance or human usability-study outcomes.
