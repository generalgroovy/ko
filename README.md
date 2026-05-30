# KO II Sampler DAW

Safe Python MIDI controller experiments for a KO II-style sampler.

## Easiest Run On Windows

Double-click:

```powershell
KO2-DAW.bat
```

That launcher creates a local `.venv`, installs the project in editable mode, and opens the desktop GUI. It is the recommended source-tree launcher when you have Python installed.

## Build A Windows Executable

Double-click or run:

```powershell
build_exe.bat
```

The built app appears at:

```text
dist\KO2-DAW\KO2-DAW.exe
```

You can copy the whole `dist\KO2-DAW` folder to another Windows machine. Keep the folder together; the `.exe` depends on the files beside it.

GitHub Actions also builds a downloadable Windows artifact named `KO2-DAW-windows` from `.github/workflows/build-windows-exe.yml`. Open the latest workflow run and download the artifact when the build completes.

## Run From Python

From this folder:

```powershell
python run_ko2_daw.py
```

or:

```powershell
python -m ko2_daw
```

or, after install:

```powershell
ko2-daw
```

The default launch opens a KO II-style desktop control surface. It starts in dry-run mode. Use **CONNECT EP-133** in the GUI to switch the pads, transport, CC fader, and read-only hardware probes to the direct USB-C `EP-133` MIDI route.

For text-only startup status:

```powershell
python run_ko2_daw.py --status
```

Useful commands:

```powershell
python run_ko2_daw.py --list
python run_ko2_daw.py --doctor
python run_ko2_daw.py --usb-diagnose
python run_ko2_daw.py --ko2-route auto --note 36
python run_ko2_daw.py --init-session companion_session.json
python run_ko2_daw.py --note 60 --clock-ticks 2
python run_ko2_daw.py --cc 1 64
python run_ko2_daw.py --bank-msb 0 --bank-lsb 1 --program 2
python run_ko2_daw.py --monitor-input --monitor-seconds 10 --state-json daw_projects\ko2_state.json
python run_ko2_daw.py --sysex-probe self-test
python run_ko2_daw.py --sysex-probe identity
python run_ko2_daw.py --sysex-probe file-init
python run_ko2_daw.py --live --ko2-route usb-midi --sysex-probe identity --send-sysex-probe
python run_ko2_daw.py --live --ko2-route usb-midi --sysex-probe root-list --send-sysex-probe
python run_ko2_daw.py --live --ko2-route usb-midi --sysex-probe root-list --sysex-node 1000 --send-sysex-probe
python run_ko2_daw.py --capability-scan --capability-report-txt docs\ko2_device_interaction_capabilities.txt
python run_ko2_daw.py --capability-scan --capability-scan-live-actions --capability-report-txt docs\ko2_device_interaction_capabilities.txt
python run_ko2_daw.py --note 60 --save-project ko2_session.json
```

Live MIDI is intentionally opt-in:

```powershell
python run_ko2_daw.py --live --midi-backend winmm --ko2-route auto --note 36
```

Live mode requires both a visible output port and an allow-list match. On Windows, the app can use native WinMM for short MIDI messages and read-only SysEx without `python-rtmidi`. Write-capable SysEx operations remain blocked unless explicitly armed through the GUI communication profile.

Current USB/MIDI distinction:

- If `ko2_usb_connected` is `True`, Windows can see the EP-133 over USB.
- If `ko2_midi_ready` is `False`, Windows has not exposed the EP-133 as a MIDI input/output port, so this MIDI app cannot send directly to it yet.
- `--usb-diagnose` prints the exact USB classes. Direct USB MIDI normally requires a MIDI streaming interface, not only USB Audio Control.
- `--ko2-route auto` resolves the best available route. With a direct USB-C MIDI connection it selects `EP-133`.
- Run `python run_ko2_daw.py --list` after changing cable, USB mode, firmware, or drivers.

State monitoring:

- The app can infer transport, clock, active notes, program changes, bank select, mod wheel, and observed controllers from incoming MIDI.
- The public EP-133 MIDI implementation does not provide a full query/dump for current project, sample names, selected effect, or complete front-panel state. Those fields are shown as unknown unless MIDI traffic exposes them.

Companion sessions:

- `--init-session companion_session.json` creates a professional session file with the EP-133 profile, 48 pad assignments, routing placeholders, supported MIDI controls, and unsupported state-query notes.
- The GUI `SAVE SESSION` button writes `daw_projects\companion_session.json`.
- The GUI `DOCTOR` button reports whether the connected EP-133 is USB-only or MIDI-ready.

## Windows Shortcuts

Double-click or run:

```powershell
KO2-DAW.bat
ko2-daw.cmd
launch_ko2_daw.cmd
test_ko2_daw.cmd
```

The visual layout mirrors the physical workflow at a practical level: LCD-style status display, group buttons A-D, 12 sample pads using the EP-133 note ranges, mode keys, transport controls, mod-wheel fader, X/Y controls, MIDI status, inferred state, diagnostics, session save, and a scrolling activity log.

The main window is now primarily a device view plus Settings, Timeline, and Log. Device files open in their own compact explorer window. The all-groups matrix shows A-D simultaneously and lights active incoming notes as visible button presses.

Usability aids:

- Hover over controls for tooltips explaining what each interaction does.
- Use **Protocol Monitor** for app/device traffic.
- Use **Communication Panel** for connection/profile/access settings.
- Use **MIDI Detect** for EP-133 port diagnostics.
- Use **Configuration > Save Settings** to persist app-level connection and access policy choices.

The current probe summary is saved in `docs\ko2_device_interaction_capabilities.txt`.

On launch, the GUI checks the configured route automatically. If it finds a usable EP-133/KO II MIDI route, it asks for confirmation before opening live MIDI. If no route is usable, it stays in dry-run mode and logs the route status.

## SysEx Lab

This project ports the safe protocol primitives from `generalgroovy/ko2` branch `codex/ko2-sysex-lab`:

- TE manufacturer SysEx frame build/parse.
- 7-bit payload pack/unpack.
- Universal identity request/parser.
- Read-only file protocol payloads for init, list, info, and metadata get.
- Explicit file playback start/stop payload for selected hardware rows.
- File list and JSON metadata response parsers.
- Write-capable file operations blocked by default; expert-write/full-lab profiles can arm low-level frame construction only after typing `WRITE`, and destructive write buttons are still not exposed.

The app can generate, send, receive, and parse identity/file probes over the direct USB-C `EP-133` MIDI route. Hardware browsing remains read-only unless the app is configured for selected-file playback preview. It does not expose upload, delete, move, restore, or metadata-write buttons.

## Optional Install

The app has no required third-party dependency for dry-run use or native Windows WinMM short MIDI output. For the optional mido backend:

```powershell
python -m pip install mido python-rtmidi
```

## Test

```powershell
python -m pytest
```
