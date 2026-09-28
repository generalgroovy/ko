# KO II Sampler DAW

A Windows desktop companion for the Teenage Engineering EP-133 / KO II: local samples, MIDI performance recording, a scene arranger, an audio timeline and read-only device exploration.

This is the main KO II project. The older [Web MIDI Lab](https://github.com/generalgroovy/ko2) is a reference; its exported sample libraries can be migrated here.

## Open the app

Install Python 3.11 or newer with Tcl/Tk. From this checkout, double-click **KO2-DAW-STABLE.bat**, or run:

```powershell
python -m ko2_daw
```

Stable mode is the default. Dry-run use and native Windows WinMM MIDI do not require third-party application packages. To install a console command, use `python -m pip install -e .`, then `ko2-daw`.

The app starts with dry-run routing. If a usable EP-133 route is detected, it asks before opening live MIDI. Use **CONNECT EP-133** when you intend to send MIDI. Opening the app or importing a local library does not upload samples to the device.

For startup diagnostics without the GUI:

```powershell
python -m ko2_daw --status
python -m ko2_daw --doctor
python -m ko2_daw --list
```

## Main workflows

| Tool | Use it for | Saved/exported data |
| --- | --- | --- |
| Samples | Import, reopen and preview local WAV samples | JSON manifest referencing the WAV files |
| Performance | Record MIDI input/app actions; quantize and loop | Editable JSON clip; format-0 MIDI export |
| Sequence / Scene Arranger | Four group tracks, steps, automation and song chains | Editable JSON project; type-1 MIDI export |
| Audio | Arrange WAV clips without changing their sources | JSON timeline; stereo WAV mixdown |
| Files / Library / Projects | Inspect and download supported hardware data | Inventory, immutable bundles, metadata and analysis |
| MIDI / Protocol / Communication | Diagnose routes and inspect messages | Reports, logs and communication settings |

Tool cards open the relevant windows. Stop playback before changing routing. Performance and arranger playback release held notes on Stop; edits in those tools have their own Undo/Redo.

## Save and reopen a local sample library

1. In **Samples**, use **IMPORT WAV** for desktop audio files.
2. Use **SAVE MANIFEST** and choose a JSON destination. The manifest saves slot/name/path information; it does not copy or embed audio.
3. Use **OPEN MANIFEST** to restore that desktop table after restarting. Replacing a nonempty table asks for confirmation. Invalid manifests, duplicate slots or unavailable WAVs leave the current table unchanged.

The table keeps its selected slot when refreshed and selects the first available sample otherwise. **PLAY LOCAL** and **TRIGGER MIDI** become available when a sample is selected. If a WAV batch is only partly valid, successful files remain imported and a warning identifies the skipped files.

Keep referenced WAV files with your backup. Saved paths are normally absolute; relative paths in a manifest resolve from the manifest's folder. On open, WAV format and duration are read from the actual files. If files moved, restore their paths or update the manifest's paths before reopening. The library is not automatically saved or reopened at startup.

For the older browser app, download every sample as WAV and export its JSON manifest. Keep the downloaded filenames together. In **Samples → IMPORT WEB LIBRARY**, choose the browser JSON and the WAV folder. This merges into free slots; it does not replace existing samples. A bad or incomplete batch changes nothing.

Command-line conversion creates a new desktop manifest and refuses to overwrite an existing output:

```powershell
python -m ko2_daw --import-web-manifest ko2-local-samples.json --sample-audio-dir exported-wavs --sample-manifest-output migrated-library.json
```

[Migration format, limits and capability comparison](docs/web-library-migration.md)

## Local data and recovery

The launchers use the checkout as their working directory. Local projects, settings, recordings and reports are normally written under `daw_projects/`; individual tools also let you choose files. Back up saved JSON **and its referenced audio/bundles**. JSON alone is not an audio backup.

Sample manifests and the recorder/arranger project formats use atomic file replacement when saving. This protects the previous file from an interrupted write; it is not version history. Keep a separate copy before overwriting a project. A failed manifest open leaves the in-memory sample table available to save elsewhere.

Use **Settings** or the communication panel to review stored connection choices. A support bundle captures diagnostics and optional local state:

```powershell
python -m ko2_daw.support_bundle
```

Review its contents before sharing; local settings, device inventory and paths may be included. [Result-analysis guide](docs/result_analysis_guide.md)

## Hardware boundaries

Live MIDI is opt-in and requires a visible output port with an allow-list match. The native WinMM route supports short MIDI messages and supported read-only SysEx. The optional mido backend requires `mido` and `python-rtmidi`.

The app exposes read-only inventory and supported downloads plus explicit non-persistent playback preview. It does **not** expose sample upload, delete, move, restore or metadata-write buttons. Expert communication profiles can arm low-level write-frame construction for protocol research; that is not a verified write/rollback workflow.

Incoming MIDI does not reveal every front-panel state. Unobserved project/pad/effect values remain unknown; inferred state is not a device snapshot. A USB data cable is required; connector shape alone does not establish MIDI availability.

Historical physical-device verification was recorded on **2026-06-11**, not during the current software audit. It covered an EP-133 WinMM route, inventory/download integrity and limited MIDI/arranger probes. Hardware behavior must be rechecked for another device/firmware. [Protocol evidence and transfer rules](docs/ep133_file_protocol.md) · [Recorded capability report](docs/ko2_device_interaction_capabilities.txt)

## Development and checks

```powershell
python -m pip install -e ".[dev]"
python -m compileall -q ko2_daw
python -m ruff check .
python -m black --check .
python -m pytest
```

The suite covers dry-run behavior, protocols, transfer integrity, project formats, GUI plugin wiring and library migration/recovery. Test outputs use `.pytest_tmp`; use a unique `--basetemp` if running separate suites concurrently. No test pass establishes physical MIDI/audio operation.

The dev extra pins the same Ruff and Black versions used by CI; formatting targets Python 3.11. General CI runs compilation, lint, formatting and tests on every push and pull request. Specific inline lint exceptions document intentional GUI/worker recovery boundaries, serialized-data exception contracts and existing timestamp formats; keep those behaviors when changing the surrounding code.

For a Windows package, run **build_exe.bat**. Keep the complete `dist\KO2-DAW` folder together. CI's Windows packaging artifact is named `KO2-DAW-windows`; check that workflow's result before treating a package as verified.

Experimental GUI mode remains opt-in through `KO2_DAW_GUI_MODE=experimental`. Use the stable surface for normal work; the experimental photo/timeline/matrix extensions have a separate acceptance boundary.

## Technical references

- [Detailed workflow reference and historical device evidence](docs/WORKFLOW-REFERENCE.md)
- [Application comparison](docs/functionality_overview_comparison.md)
- [Result artifacts and integrity review](docs/result_analysis_guide.md)
- [Protocol and transaction behavior](docs/ep133_file_protocol.md)
- [Future model proposals](docs/model_proposals.md)
- [Optional cluster jobs](slurm/README.md)
- [Core source](ko2_daw/) and [tests](tests/)
