# Know what is saved in the sample library

Baseline: `c081cf47ac42c5ad88397d148ebd7cb1ef87dc0d`. Candidate: `codex/ux-flow-2026-10-07`. The ten pre-existing untracked pytest directories are preserved.

The Samples panel previously showed the selected file and generic backup advice but did not distinguish newly imported rows from a saved table. It now uses the same small status area for **Unsaved library changes** or the last successfully saved/opened manifest name. A snapshot of the actual immutable sample rows detects changes, rather than only comparing counts. Imports, web-library merges and saved sample copies pass through the same refresh path.

A successful save confirms its filename inline and its full path in Log. The blocking success dialog is removed. The next Save Library dialog starts at that destination, keeping the operating system's normal file choice and overwrite confirmation. A cancelled or failed save does not change the saved snapshot or destination. Opening a validated library updates the baseline only after replacement is accepted. Nothing is saved automatically; JSON still references separate WAV files.

Evidence and independent review are recorded after the candidate checks. This change does not exercise live MIDI, audible output or physical hardware.
