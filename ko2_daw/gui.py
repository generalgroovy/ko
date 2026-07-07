"""Tkinter control-surface UI inspired by the KO II hardware layout."""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ko2_daw.config import APP_ACCESS_MODES, AppSettings, DAWConfig, DeviceSafetyConfig, load_app_settings, save_app_settings
from ko2_daw.controller import DAWController
from ko2_daw.diagnostics import readiness_report
from ko2_daw.midi import DryRunMidiBackend, MidiMessage, WinMMInputMonitor, WinMMMidiBackend, midi_capability_report
from ko2_daw.project_store import ProjectSnapshot, SafeProjectStore
from ko2_daw.routing import KO2Route, resolve_ko2_route
from ko2_daw.samples import MAX_SAMPLE_SLOTS, SampleLibrary, play_wav, stop_wav
from ko2_daw.session import CompanionSessionStore, default_session
from ko2_daw.state import KO2RuntimeState
from ko2_daw.sysex_exchange import (
    SysexDecodedResponse,
    decode_sysex_response,
    matching_sysex_responses,
)
from ko2_daw.te_sysex import (
    TEFileCommand,
    build_file_init_payload,
    build_file_list_payload,
    build_file_playback_payload,
    build_te_frame,
    build_universal_identity_request,
    bytes_to_hex,
    self_test_packing,
    set_experimental_write_enabled,
)


PAD_NOTES = {
    "A": list(range(36, 48)),
    "B": list(range(48, 60)),
    "C": list(range(60, 72)),
    "D": list(range(72, 84)),
}
PAD_LABELS = [".", "0", "ENTER", "1", "2", "3", "4", "5", "6", "7", "8", "9"]


class ToolTip:
    """Small hover tooltip for explaining hardware-style controls."""

    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self.tip: tk.Toplevel | None = None
        self.after_id: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self.after_id = self.widget.after(450, self._show)

    def _show(self) -> None:
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 10
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.tip,
            text=self.text,
            justify=tk.LEFT,
            bg="#171915",
            fg="#f3f1de",
            relief=tk.SOLID,
            borderwidth=1,
            padx=8,
            pady=6,
            wraplength=320,
        )
        label.pack()

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None

    def _cancel(self) -> None:
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None


class KO2DawApp:
    """Small desktop app that keeps hardware-facing controls explicit."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("KO II Sampler DAW")
        self.root.geometry("1180x760")
        self.root.minsize(1040, 680)
        self.root.configure(bg="#d8d4c8")

        self.report = midi_capability_report()
        self.backend = DryRunMidiBackend(
            input_ports=list(self.report.get("input_ports") or []),
            output_ports=list(self.report.get("output_ports") or []),
        )
        self.config = DAWConfig(clock_enabled=True)
        self.controller = DAWController(config=self.config, backend=self.backend)
        self.runtime_state = KO2RuntimeState()
        self.session = default_session()
        self.sample_library = SampleLibrary()
        self.project_root = Path("daw_projects")
        self.settings_path = self.project_root / "app_settings.json"
        self.app_settings = load_app_settings(self.settings_path)
        set_experimental_write_enabled(self.app_settings.write_enabled)
        self.live_backend: WinMMMidiBackend | None = None
        self.input_monitor: WinMMInputMonitor | None = None
        self.input_queue: queue.Queue[object] = queue.Queue()
        self.live_input_port: str | None = None
        self.live_output_port: str | None = None
        self._sysex_lock = threading.Lock()
        self._sysex_transaction_lock = threading.Lock()
        self._sysex_event = threading.Event()
        self._sysex_responses: list[bytes] = []
        self._hardware_scan_lock = threading.Lock()
        self.hardware_rows_seen: set[tuple[str, str]] = set()
        self.tooltips: list[ToolTip] = []

        self.group = tk.StringVar(value="A")
        self.bpm = tk.DoubleVar(value=self.config.bpm)
        self.velocity = tk.IntVar(value=96)
        self.status = tk.StringVar(value="DRY RUN")
        self.last_action = tk.StringVar(value="ready")
        self.live_state = tk.StringVar(value="live off")
        self.session_status = tk.StringVar(value=f"session: {self.session.name}")
        self.settings_status = tk.StringVar(value=f"settings: {self.app_settings.access_mode}")
        self.route_setting = tk.StringVar(value=self.app_settings.preferred_route)
        self.input_port_setting = tk.StringVar(value=self.app_settings.preferred_input_port)
        self.output_port_setting = tk.StringVar(value=self.app_settings.preferred_output_port)
        self.access_mode_setting = tk.StringVar(value=self.app_settings.access_mode)
        self.auto_connect_setting = tk.BooleanVar(value=self.app_settings.auto_connect_on_start)
        self.sysex_enabled_setting = tk.BooleanVar(value=self.app_settings.sysex_enabled)
        self.auto_scan_setting = tk.BooleanVar(value=self.app_settings.auto_scan_on_connect)
        self.file_playback_setting = tk.BooleanVar(value=self.app_settings.allow_file_playback)
        self.playback_confirm_setting = tk.BooleanVar(value=self.app_settings.require_playback_confirmation)
        self.sysex_timeout_setting = tk.StringVar(value=str(self.app_settings.sysex_timeout_sec))
        self.max_sysex_bytes_setting = tk.StringVar(value=str(self.app_settings.max_sysex_bytes))
        self.scan_pages_setting = tk.StringVar(value=str(self.app_settings.scan_pages_per_dir))
        self.scan_depth_setting = tk.StringVar(value=str(self.app_settings.scan_max_depth))
        self.scan_dirs_setting = tk.StringVar(value=str(self.app_settings.scan_max_dirs))
        self.write_arm_setting = tk.StringVar(value=self.app_settings.write_arm_phrase)

        self._build()
        self._refresh_ports()
        self.root.after(100, self._drain_input_queue)
        self.root.after(650, self._auto_connect_on_start)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self) -> None:
        self._build_menu()
        outer = tk.Frame(self.root, bg="#d8d4c8", padx=8, pady=8)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=5)
        outer.columnconfigure(1, weight=0)
        outer.rowconfigure(2, weight=4)
        outer.rowconfigure(3, weight=2)

        self._build_top_panel(outer)
        self._build_mode_strip(outer)
        self._build_main_controls(outer)
        self._build_workspace(outer)

    def _build_menu(self) -> None:
        menu = tk.Menu(self.root)
        config_menu = tk.Menu(menu, tearoff=False)
        config_menu.add_command(label="Apply Settings", command=self._apply_settings)
        config_menu.add_command(label="Save Settings", command=self._save_app_settings)
        config_menu.add_command(label="Reset Settings Form", command=self._reset_settings_form)
        menu.add_cascade(label="Configuration", menu=config_menu)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Interaction Guide", command=self._show_interaction_guide)
        help_menu.add_command(label="MIDI And Safety", command=self._show_midi_safety)
        help_menu.add_command(label="Current Device Status", command=self._show_doctor)
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menu)

    def _tip(self, widget: tk.Widget, text: str) -> None:
        self.tooltips.append(ToolTip(widget, text))

    def _build_top_panel(self, parent: tk.Frame) -> None:
        display = tk.Frame(parent, bg="#171915", bd=4, relief=tk.RIDGE, padx=12, pady=8)
        display.grid(row=0, column=0, columnspan=2, sticky="ew")
        display.columnconfigure(0, weight=1)
        display.columnconfigure(1, weight=1)

        title = tk.Label(
            display,
            text="KO II SAMPLER DAW",
            fg="#d7f58a",
            bg="#171915",
            font=("Consolas", 22, "bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="ew")
        self._tip(title, "Main status display. This area mirrors the KO II-style screen: route, last action, and inferred state.")

        state = tk.Label(
            display,
            textvariable=self.status,
            fg="#171915",
            bg="#d7f58a",
            font=("Consolas", 18, "bold"),
            padx=12,
            pady=4,
        )
        state.grid(row=0, column=1, sticky="e")
        self._tip(state, "Current output mode. DRY RUN means no hardware MIDI is sent; LIVE EP-133 means controls are routed to the connected KO II.")

        self.port_label = tk.Label(
            display,
            fg="#d7f58a",
            bg="#171915",
            font=("Consolas", 10),
            anchor="w",
            justify=tk.LEFT,
        )
        self.port_label.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._tip(self.port_label, "Detected MIDI inputs, outputs, USB status, and whether the EP-133 appears as a MIDI endpoint.")

        action = tk.Label(
            display,
            textvariable=self.last_action,
            fg="#f3f1de",
            bg="#171915",
            font=("Consolas", 12),
            anchor="w",
        )
        action.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self._tip(action, "Most recent command or UI action.")

        self.state_label = tk.Label(
            display,
            fg="#f3f1de",
            bg="#171915",
            font=("Consolas", 11),
            anchor="w",
            justify=tk.LEFT,
        )
        self.state_label.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._tip(self.state_label, "Best-effort runtime mirror inferred from MIDI traffic: transport, active notes, clock ticks, and mod wheel.")
        self._refresh_state_label()

    def _build_mode_strip(self, parent: tk.Frame) -> None:
        strip = tk.Frame(parent, bg="#d8d4c8", pady=6)
        strip.grid(row=1, column=0, columnspan=2, sticky="ew")
        help_text = {
            "SOUND": "Select or inspect sound-focused work. Currently logs the mode and keeps the hardware-style workflow visible.",
            "MAIN": "Return attention to the primary pad and transport surface.",
            "TEMPO": "Tempo work area. Use knob X to change the session BPM.",
            "FX": "Effect work area. Public MIDI does not expose full KO II effect state, so changes are mirrored only when sent or observed as MIDI.",
            "SHIFT": "Modifier-style mode marker for future expanded KO II operations.",
            "FADER": "Fader work area. The vertical fader sends MIDI CC 1 / mod wheel.",
        }
        for index, label in enumerate(("SOUND", "MAIN", "TEMPO", "FX", "SHIFT", "FADER")):
            strip.columnconfigure(index, weight=1)
            button = tk.Button(
                strip,
                text=label,
                height=1,
                bg="#efeadf",
                activebackground="#fff6d6",
                relief=tk.RAISED,
                command=lambda value=label: self._set_action(value.lower()),
            )
            button.grid(row=0, column=index, sticky="ew", padx=3)
            self._tip(button, help_text[label])

    def _build_main_controls(self, parent: tk.Frame) -> None:
        left = tk.Frame(parent, bg="#d8d4c8")
        left.grid(row=2, column=0, sticky="nsew")
        right = tk.Frame(parent, bg="#d8d4c8")
        right.grid(row=2, column=1, sticky="nsew", padx=(8, 0))

        self._build_groups(left)
        self._build_pads(left)
        self._build_transport(left)
        self._build_encoders(right)

    def _build_groups(self, parent: tk.Frame) -> None:
        groups = tk.Frame(parent, bg="#d8d4c8")
        groups.pack(fill=tk.X, pady=(0, 10))
        for group in ("A", "B", "C", "D"):
            button = tk.Radiobutton(
                groups,
                text=f"GROUP {group}",
                value=group,
                variable=self.group,
                indicatoron=False,
                width=12,
                height=2,
                bg="#c9c4b8",
                selectcolor="#f2c230",
                command=lambda value=group: self._set_action(f"group {value}"),
            )
            button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=3)
            self._tip(button, f"Select KO II group {group}. Pads in this group map to MIDI notes {PAD_NOTES[group][0]}-{PAD_NOTES[group][-1]}.")

    def _build_pads(self, parent: tk.Frame) -> None:
        pad_frame = tk.Frame(parent, bg="#bdb7aa", padx=10, pady=10)
        pad_frame.pack(fill=tk.BOTH, expand=True)
        for col in range(4):
            pad_frame.columnconfigure(col, weight=1, uniform="pad")
        for row in range(3):
            pad_frame.rowconfigure(row, weight=1, uniform="pad")

        for index in range(12):
            row, col = divmod(index, 4)
            label = PAD_LABELS[index]
            button = tk.Button(
                pad_frame,
                text=label,
                font=("Segoe UI", 18, "bold"),
                bg="#f5f0e4",
                activebackground="#f2c230",
                relief=tk.RAISED,
                command=lambda pad=index: self._trigger_pad(pad),
            )
            button.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
            self._tip(
                button,
                f"Trigger pad {index + 1} in the selected group. In dry-run it logs note on/off; when live it sends the mapped note to EP-133.",
            )

    def _build_transport(self, parent: tk.Frame) -> None:
        transport = tk.Frame(parent, bg="#d8d4c8", pady=12)
        transport.pack(fill=tk.X)
        buttons = (
            ("REC", "#dc493a", self._record),
            ("PLAY", "#88b04b", self._start),
            ("CONT", "#9fb86a", self._continue),
            ("STOP", "#efeadf", self._stop),
            ("PANIC", "#171915", self._panic),
        )
        for text, color, command in buttons:
            fg = "#f7f3e7" if color == "#171915" else "#171915"
            button = tk.Button(
                transport,
                text=text,
                height=2,
                bg=color,
                fg=fg,
                activebackground="#f2c230",
                command=command,
            )
            button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
            transport_tips = {
                "REC": "Marks record-arm intent in the log. Audio sampling/upload is not sent to hardware from this button.",
                "PLAY": "Send MIDI Start to the selected route and mark transport as playing.",
                "CONT": "Send MIDI Continue. This resumes transport from the device's current song/pattern position when supported.",
                "STOP": "Send MIDI Stop, clear active notes, and stop the inferred transport.",
                "PANIC": "Send all-notes-off and all-sound-off on every MIDI channel.",
            }
            self._tip(button, transport_tips[text])

    def _build_encoders(self, parent: tk.Frame) -> None:
        panel = tk.Frame(parent, bg="#c9c4b8", padx=10, pady=10, width=240)
        panel.pack(fill=tk.BOTH, expand=True)
        panel.pack_propagate(False)

        header = tk.Label(panel, text="PARAMETERS", bg="#c9c4b8", font=("Segoe UI", 11, "bold"))
        header.pack(fill=tk.X)
        self._tip(header, "Session parameters and connection controls.")
        session_label = tk.Label(panel, textvariable=self.session_status, bg="#c9c4b8", wraplength=210, justify=tk.LEFT)
        session_label.pack(
            fill=tk.X,
            pady=(0, 8),
        )
        self._tip(session_label, "Current companion session file state.")
        self._dial(panel, "X", self.bpm, 60, 180, self._set_bpm)
        self._dial(panel, "Y", self.velocity, 1, 127, self._set_velocity)

        fader_label = tk.Label(panel, text="FADER", bg="#c9c4b8", font=("Segoe UI", 11, "bold"))
        fader_label.pack(fill=tk.X, pady=(10, 0))
        self._tip(fader_label, "Vertical KO II-style fader mapped to MIDI CC 1 / mod wheel.")
        fader = tk.Scale(
            panel,
            from_=127,
            to=0,
            orient=tk.VERTICAL,
            length=150,
            showvalue=True,
            bg="#c9c4b8",
            troughcolor="#171915",
            command=lambda value: self._send_mod_wheel(int(float(value))),
        )
        fader.set(96)
        fader.pack(pady=4)
        self._tip(fader, "Send or preview mod wheel values. Live mode sends CC 1 to EP-133; dry-run records it locally.")

        button_specs = (
            ("SAVE", self._save_project, "#efeadf", "Save the current GUI activity/session snapshot under daw_projects."),
            ("SAVE SESSION", self._save_session, "#efeadf", "Save companion profile, routing, selected group, and BPM."),
            ("CONNECT EP-133", self._connect_live, "#d7f58a", "Open the detected EP-133 MIDI input/output and enable live pad, transport, CC, and read-only SysEx controls."),
            ("DISCONNECT", self._disconnect_live, "#efeadf", "Close live MIDI handles and return to dry-run mode."),
            ("REFRESH MIDI", self._refresh_report, "#efeadf", "Rescan WinMM MIDI ports and EP-133 USB status."),
            ("DOCTOR", self._show_doctor, "#efeadf", "Show route diagnostics and suggested setup actions."),
            ("SYSEX LAB", self._show_sysex_lab, "#efeadf", "Show read-only SysEx frames and protocol safety status."),
        )
        for index, (text, command, color, tip) in enumerate(button_specs):
            button = tk.Button(panel, text=text, command=command, bg=color, height=1)
            button.pack(fill=tk.X, pady=(8 if index == 0 else 3, 0))
            self._tip(button, tip)

        live_label = tk.Label(panel, textvariable=self.live_state, bg="#c9c4b8", fg="#7a1f16", font=("Segoe UI", 10, "bold"))
        live_label.pack(
            fill=tk.X,
            pady=(10, 0),
        )
        self._tip(live_label, "Resolved live route. Ready means a route is available; live means the route is currently open.")

    def _dial(
        self,
        parent: tk.Frame,
        label: str,
        variable: tk.Variable,
        low: int,
        high: int,
        command,
    ) -> None:
        frame = tk.Frame(parent, bg="#c9c4b8", pady=6)
        frame.pack(fill=tk.X)
        label_widget = tk.Label(frame, text=f"KNOB {label}", bg="#c9c4b8")
        label_widget.pack(anchor="w")
        scale = tk.Scale(
            frame,
            from_=low,
            to=high,
            orient=tk.HORIZONTAL,
            variable=variable,
            bg="#c9c4b8",
            troughcolor="#171915",
            command=lambda value: command(float(value)),
        )
        scale.pack(fill=tk.X)
        if label == "X":
            tip = "Set session BPM. Transport clock commands use this value when clocking is enabled."
        else:
            tip = "Set pad trigger velocity for note-on messages."
        self._tip(label_widget, tip)
        self._tip(scale, tip)

    def _build_workspace(self, parent: tk.Frame) -> None:
        tabs = ttk.Notebook(parent)
        self.workspace_tabs = tabs
        tabs.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        self._tip(tabs, "Lower workspace. Use Samples for local audio, Hardware Files for EP-133 browsing/playback, Settings for access policy, and Log for activity.")

        samples = tk.Frame(tabs, bg="#d8d4c8", padx=6, pady=6)
        hardware = tk.Frame(tabs, bg="#d8d4c8", padx=6, pady=6)
        settings = tk.Frame(tabs, bg="#d8d4c8", padx=6, pady=6)
        log_tab = tk.Frame(tabs, bg="#d8d4c8", padx=6, pady=6)
        tabs.add(samples, text="Samples")
        tabs.add(hardware, text="Hardware Files")
        tabs.add(settings, text="Settings")
        tabs.add(log_tab, text="Log")

        self._build_sample_library(samples)
        self._build_hardware_files(hardware)
        self._build_settings(settings)
        self._build_log(log_tab)

    def _build_sample_library(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        toolbar = tk.Frame(parent, bg="#d8d4c8")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        sample_buttons = (
            ("IMPORT WAV", self._import_wav, "Add WAV files to the local 999-slot sample library. This does not upload to the KO II."),
            ("PLAY LOCAL", self._play_selected_sample, "Preview the selected WAV through Windows audio."),
            ("STOP AUDIO", self._stop_audio, "Stop local WAV preview playback."),
            ("TRIGGER MIDI", self._trigger_selected_sample, "Trigger the pad note corresponding to the selected sample slot."),
            ("SAVE MANIFEST", self._save_sample_manifest, "Save the local sample table to daw_projects/sample_manifest.json."),
        )
        for index, (text, command, tip) in enumerate(sample_buttons):
            button = tk.Button(toolbar, text=text, command=command, bg="#efeadf")
            button.pack(side=tk.LEFT, padx=(0 if index == 0 else 4, 4))
            self._tip(button, tip)
        self.sample_status = tk.StringVar(value=f"0 / {MAX_SAMPLE_SLOTS} slots")
        sample_status = tk.Label(toolbar, textvariable=self.sample_status, bg="#d8d4c8", font=("Segoe UI", 10, "bold"))
        sample_status.pack(
            side=tk.RIGHT
        )
        self._tip(sample_status, "Number of populated local sample slots out of the KO II-style 999-slot table.")

        columns = ("slot", "name", "duration", "rate", "channels", "bits", "size", "path")
        self.sample_tree = ttk.Treeview(parent, columns=columns, show="headings", height=7)
        headings = {
            "slot": "Slot",
            "name": "Name",
            "duration": "Duration",
            "rate": "Rate",
            "channels": "Ch",
            "bits": "Bits",
            "size": "Size",
            "path": "Path",
        }
        widths = {"slot": 60, "name": 160, "duration": 90, "rate": 80, "channels": 50, "bits": 50, "size": 90, "path": 430}
        for column in columns:
            self.sample_tree.heading(column, text=headings[column])
            self.sample_tree.column(column, width=widths[column], anchor="w")
        self.sample_tree.grid(row=1, column=0, sticky="nsew")
        self._tip(self.sample_tree, "Local sample table. Select a row to preview audio or trigger the matching MIDI pad slot.")

    def _build_hardware_files(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        toolbar = tk.Frame(parent, bg="#d8d4c8")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        hardware_buttons = (
            ("READ IDENTITY", self._probe_identity, "Ask the EP-133 for its universal MIDI identity. Read-only."),
            ("FILE INIT", self._probe_file_init, "Initialize the Teenage Engineering read-only file protocol and learn chunk size."),
            ("LIST ROOT", self._probe_root_list, "List the root folders exposed by the device, usually sounds and projects."),
            ("LIST SELECTED", self._probe_selected_node, "List the selected hardware node, such as sounds or projects."),
            ("PLAY FILE", self._play_selected_device_file, "Start playback preview for the selected device file. This talks to the EP-133 and may make sound."),
            ("STOP FILE", self._stop_selected_device_file, "Stop playback preview for the selected device file."),
            ("SCAN DEVICE", self._scan_complete_device_tree, "Run the full read-only scan immediately used at connection: identity, file init, root, and every discovered directory."),
            ("EXPORT CACHE", self._export_hardware_cache, "Save visible hardware file rows to daw_projects/hardware_file_cache.json."),
            ("CLEAR", self._clear_hardware_cache, "Clear the displayed hardware file rows."),
        )
        for index, (text, command, tip) in enumerate(hardware_buttons):
            button = tk.Button(toolbar, text=text, command=command, bg="#efeadf")
            button.pack(side=tk.LEFT, padx=(0 if index == 0 else 4, 4))
            self._tip(button, tip)
        self.hardware_status = tk.StringVar(value="connect live, then run read-only probes")
        hardware_status = tk.Label(toolbar, textvariable=self.hardware_status, bg="#d8d4c8", font=("Segoe UI", 10, "bold"))
        hardware_status.pack(
            side=tk.RIGHT
        )
        self._tip(hardware_status, "Status of the most recent hardware probe.")

        columns = ("kind", "node", "name", "size", "status")
        self.hardware_tree = ttk.Treeview(parent, columns=columns, show="headings", height=7)
        widths = {"kind": 80, "node": 80, "name": 260, "size": 100, "status": 460}
        for column in columns:
            self.hardware_tree.heading(column, text=column.title())
            self.hardware_tree.column(column, width=widths[column], anchor="w")
        self.hardware_tree.grid(row=1, column=0, sticky="nsew")
        self._tip(self.hardware_tree, "Hardware file rows loaded automatically after connecting. Select a directory and use LIST SELECTED to refresh it, or select a file and use PLAY FILE for device preview.")

    def _build_settings(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=1)
        parent.columnconfigure(2, weight=1)
        parent.rowconfigure(1, weight=1)

        header = tk.Frame(parent, bg="#d8d4c8")
        header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        title = tk.Label(header, text="APP CONFIGURATION", bg="#d8d4c8", font=("Segoe UI", 11, "bold"))
        title.pack(side=tk.LEFT)
        self._tip(title, "Persistent app settings. Apply changes before connecting; Save writes daw_projects/app_settings.json.")
        status = tk.Label(header, textvariable=self.settings_status, bg="#d8d4c8", fg="#7a1f16", font=("Segoe UI", 10, "bold"))
        status.pack(side=tk.RIGHT)
        self._tip(status, "Current configuration mode and whether expert write frame construction is armed.")

        route_box = tk.LabelFrame(parent, text="Route", bg="#d8d4c8", padx=8, pady=8)
        route_box.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        route_box.columnconfigure(1, weight=1)
        tk.Label(route_box, text="Mode", bg="#d8d4c8").grid(row=0, column=0, sticky="w", pady=3)
        route_combo = ttk.Combobox(
            route_box,
            textvariable=self.route_setting,
            values=("auto", "usb-midi", "quad-capture", "manual"),
            state="readonly",
        )
        route_combo.grid(row=0, column=1, sticky="ew", pady=3)
        self._tip(route_combo, "auto prefers direct EP-133 USB MIDI, then QUAD-CAPTURE. manual uses the chosen ports below.")

        tk.Label(route_box, text="Input", bg="#d8d4c8").grid(row=1, column=0, sticky="w", pady=3)
        self.input_combo = ttk.Combobox(route_box, textvariable=self.input_port_setting)
        self.input_combo.grid(row=1, column=1, sticky="ew", pady=3)
        self._tip(self.input_combo, "MIDI input used for SysEx responses and live monitoring. Leave blank for output-only control.")

        tk.Label(route_box, text="Output", bg="#d8d4c8").grid(row=2, column=0, sticky="w", pady=3)
        self.output_combo = ttk.Combobox(route_box, textvariable=self.output_port_setting)
        self.output_combo.grid(row=2, column=1, sticky="ew", pady=3)
        self._tip(self.output_combo, "MIDI output used in manual route mode. EP-133 is preferred for direct USB-C control.")

        refresh = tk.Button(route_box, text="REFRESH PORTS", command=self._refresh_report, bg="#efeadf")
        refresh.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self._tip(refresh, "Rescan visible MIDI input/output ports and update the route choices.")

        access_box = tk.LabelFrame(parent, text="Access Policy", bg="#d8d4c8", padx=8, pady=8)
        access_box.grid(row=1, column=1, sticky="nsew", padx=6)
        access_box.columnconfigure(1, weight=1)
        tk.Label(access_box, text="Mode", bg="#d8d4c8").grid(row=0, column=0, sticky="w", pady=3)
        access_combo = ttk.Combobox(access_box, textvariable=self.access_mode_setting, values=APP_ACCESS_MODES, state="readonly")
        access_combo.grid(row=0, column=1, sticky="ew", pady=3)
        self._tip(access_combo, "read-only blocks playback and writes. read-playback allows selected-file preview. expert-write arms write frame construction only after typing WRITE.")

        checks = (
            ("Auto-connect on launch", self.auto_connect_setting, "Check for the configured KO II route on startup and prompt to connect when found."),
            ("SysEx enabled", self.sysex_enabled_setting, "Allow SysEx identity, file browsing, and selected-file playback commands."),
            ("Auto-scan on connect", self.auto_scan_setting, "Load the complete hardware file tree immediately after connecting."),
            ("Allow file playback", self.file_playback_setting, "Allow PLAY FILE / STOP FILE in read-playback or expert-write mode."),
            ("Confirm playback", self.playback_confirm_setting, "Ask before PLAY FILE sends an audible device preview command."),
        )
        for index, (text, variable, tip) in enumerate(checks, start=1):
            check = tk.Checkbutton(access_box, text=text, variable=variable, bg="#d8d4c8", anchor="w")
            check.grid(row=index, column=0, columnspan=2, sticky="ew", pady=2)
            self._tip(check, tip)

        tk.Label(access_box, text="Write arm", bg="#d8d4c8").grid(row=6, column=0, sticky="w", pady=(8, 3))
        write_entry = tk.Entry(access_box, textvariable=self.write_arm_setting, show="*")
        write_entry.grid(row=6, column=1, sticky="ew", pady=(8, 3))
        self._tip(write_entry, "Expert write mode only becomes armed when this field is exactly WRITE. No upload/delete/move buttons are exposed yet.")

        scan_box = tk.LabelFrame(parent, text="SysEx And Scan", bg="#d8d4c8", padx=8, pady=8)
        scan_box.grid(row=1, column=2, sticky="nsew", padx=(6, 0))
        scan_box.columnconfigure(1, weight=1)
        fields = (
            ("Timeout sec", self.sysex_timeout_setting, "How long to wait for each SysEx response."),
            ("Max SysEx bytes", self.max_sysex_bytes_setting, "Maximum outbound SysEx frame size allowed by the live controller."),
            ("Pages per dir", self.scan_pages_setting, "Maximum file-list pages to request for each hardware directory."),
            ("Max depth", self.scan_depth_setting, "Maximum recursive directory depth for device scanning."),
            ("Max dirs", self.scan_dirs_setting, "Maximum directories to visit during a full device scan."),
        )
        for row, (label, variable, tip) in enumerate(fields):
            tk.Label(scan_box, text=label, bg="#d8d4c8").grid(row=row, column=0, sticky="w", pady=3)
            entry = tk.Entry(scan_box, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            self._tip(entry, tip)

        actions = tk.Frame(parent, bg="#d8d4c8")
        actions.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        buttons = (
            ("APPLY", self._apply_settings, "Apply settings to the current GUI session."),
            ("SAVE", self._save_app_settings, "Apply and write settings to daw_projects/app_settings.json."),
            ("LOAD DEFAULTS", self._load_default_settings, "Replace the form with conservative defaults; press APPLY or SAVE afterward."),
        )
        for index, (text, command, tip) in enumerate(buttons):
            button = tk.Button(actions, text=text, command=command, bg="#efeadf", width=18)
            button.pack(side=tk.LEFT, padx=(0 if index == 0 else 5, 0))
            self._tip(button, tip)

        self._refresh_settings_port_choices()

    def _build_log(self, parent: tk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.log = tk.Text(parent, height=6, bg="#171915", fg="#f3f1de", insertbackground="#f3f1de")
        self.log.grid(row=0, column=0, sticky="nsew")
        self._tip(self.log, "Chronological activity log for GUI actions, MIDI sends, MIDI input, and SysEx probe results.")
        self._log("ready: dry-run mode")

    def _refresh_settings_port_choices(self) -> None:
        if not hasattr(self, "input_combo") or not hasattr(self, "output_combo"):
            return
        inputs = ["", *list(self.report.get("input_ports") or [])]
        outputs = ["", *list(self.report.get("output_ports") or [])]
        self.input_combo.configure(values=inputs)
        self.output_combo.configure(values=outputs)

    def _settings_from_widgets(self) -> AppSettings:
        settings = AppSettings(
            preferred_route=self.route_setting.get().strip() or "auto",
            preferred_input_port=self.input_port_setting.get().strip(),
            preferred_output_port=self.output_port_setting.get().strip(),
            access_mode=self.access_mode_setting.get().strip() or "read-playback",
            auto_connect_on_start=bool(self.auto_connect_setting.get()),
            sysex_enabled=bool(self.sysex_enabled_setting.get()),
            auto_scan_on_connect=bool(self.auto_scan_setting.get()),
            allow_file_playback=bool(self.file_playback_setting.get()),
            require_playback_confirmation=bool(self.playback_confirm_setting.get()),
            sysex_timeout_sec=float(self.sysex_timeout_setting.get()),
            max_sysex_bytes=int(self.max_sysex_bytes_setting.get()),
            scan_pages_per_dir=int(self.scan_pages_setting.get()),
            scan_max_depth=int(self.scan_depth_setting.get()),
            scan_max_dirs=int(self.scan_dirs_setting.get()),
            write_arm_phrase=self.write_arm_setting.get(),
        )
        settings.validate()
        return settings

    def _write_settings_to_widgets(self, settings: AppSettings) -> None:
        self.route_setting.set(settings.preferred_route)
        self.input_port_setting.set(settings.preferred_input_port)
        self.output_port_setting.set(settings.preferred_output_port)
        self.access_mode_setting.set(settings.access_mode)
        self.auto_connect_setting.set(settings.auto_connect_on_start)
        self.sysex_enabled_setting.set(settings.sysex_enabled)
        self.auto_scan_setting.set(settings.auto_scan_on_connect)
        self.file_playback_setting.set(settings.allow_file_playback)
        self.playback_confirm_setting.set(settings.require_playback_confirmation)
        self.sysex_timeout_setting.set(str(settings.sysex_timeout_sec))
        self.max_sysex_bytes_setting.set(str(settings.max_sysex_bytes))
        self.scan_pages_setting.set(str(settings.scan_pages_per_dir))
        self.scan_depth_setting.set(str(settings.scan_max_depth))
        self.scan_dirs_setting.set(str(settings.scan_max_dirs))
        self.write_arm_setting.set(settings.write_arm_phrase)

    def _apply_settings(self, *, show_message: bool = True) -> bool:
        try:
            settings = self._settings_from_widgets()
        except (TypeError, ValueError) as exc:
            if show_message:
                messagebox.showerror("KO II Configuration", str(exc))
            return False
        self.app_settings = settings
        set_experimental_write_enabled(settings.write_enabled)
        write_state = "write armed" if settings.write_enabled else "write blocked"
        self.settings_status.set(f"settings: {settings.access_mode} / {write_state}")
        if show_message:
            self._set_action(f"settings applied: {settings.access_mode}, {write_state}")
        self._refresh_ports()
        return True

    def _save_app_settings(self) -> None:
        if not self._apply_settings(show_message=False):
            return
        path = save_app_settings(self.settings_path, self.app_settings)
        self._set_action(f"settings saved: {path.name}")
        messagebox.showinfo("KO II Configuration", f"Saved app settings:\n{path}")

    def _reset_settings_form(self) -> None:
        self._write_settings_to_widgets(self.app_settings)
        self.settings_status.set(f"settings: {self.app_settings.access_mode}")
        self._set_action("settings form reset")

    def _load_default_settings(self) -> None:
        self._write_settings_to_widgets(AppSettings())
        self.settings_status.set("settings: defaults loaded")
        self._set_action("settings defaults loaded")

    def _refresh_report(self) -> None:
        self.report = midi_capability_report()
        self._refresh_settings_port_choices()
        self._refresh_ports()
        self._log("midi ports refreshed")

    def _resolve_configured_route(self) -> KO2Route:
        preferred = self.app_settings.preferred_route
        if preferred == "manual":
            inputs = list(self.report.get("input_ports") or [])
            outputs = list(self.report.get("output_ports") or [])
            output_port = self.app_settings.preferred_output_port.strip()
            input_port = self.app_settings.preferred_input_port.strip()
            if not output_port:
                return KO2Route(
                    status="manual-output-missing",
                    input_port=None,
                    output_port=None,
                    allow_output=None,
                    message="Manual route needs an output port in Settings.",
                    requires_user_action="Choose a MIDI output in Settings, then apply.",
                )
            if output_port not in outputs:
                return KO2Route(
                    status="manual-output-unavailable",
                    input_port=None,
                    output_port=None,
                    allow_output=None,
                    message=f"Manual output is not visible: {output_port}",
                    requires_user_action="Refresh MIDI or choose a visible output in Settings.",
                )
            selected_input = input_port if input_port in inputs else None
            return KO2Route(
                status="manual-ready",
                input_port=selected_input,
                output_port=output_port,
                allow_output=output_port,
                message=f"Using manual MIDI output: {output_port}",
                requires_user_action=None if selected_input or not input_port else "Selected input is not visible; SysEx responses will not be monitored.",
            )
        return resolve_ko2_route(self.report, preferred)

    def _auto_connect_on_start(self) -> None:
        if not self.app_settings.auto_connect_on_start or self.live_output_port:
            return
        if not self._apply_settings(show_message=False):
            return
        self._refresh_report()
        route = self._resolve_configured_route()
        if not route.output_port:
            self._log(f"auto-connect check: {route.status}")
            return
        self._log(f"auto-connect found: {route.output_port}")
        self._connect_live(route=route, auto_detected=True)

    def _refresh_ports(self) -> None:
        inputs = ", ".join(self.report.get("input_ports") or ["none"])
        outputs = ", ".join(self.report.get("output_ports") or ["none"])
        live = "yes" if self.report.get("live_midi_available") else "no"
        ko2_usb = "yes" if self.report.get("ko2_usb_connected") else "no"
        ko2_midi = "yes" if self.report.get("ko2_midi_ready") else "no"
        self.port_label.configure(
            text=(
                f"inputs: {inputs}\n"
                f"outputs: {outputs}\n"
                f"live midi available: {live}    ep-133 usb: {ko2_usb}    ep-133 midi: {ko2_midi}\n"
                f"route: {self.app_settings.preferred_route}    access: {self.app_settings.access_mode}    sysex: {'yes' if self.app_settings.sysex_enabled else 'no'}"
            )
        )
        route = self._resolve_configured_route()
        if self.live_output_port:
            self.live_state.set(f"live: {self.live_input_port or '-'} -> {self.live_output_port}")
        elif route.output_port:
            self.live_state.set(f"ready: {route.status} / {route.output_port}")
        elif self.report.get("ko2_usb_connected") and not self.report.get("ko2_midi_ready"):
            self.live_state.set("EP-133 USB seen / MIDI endpoint missing")
        else:
            self.live_state.set("live off / dry-run protected")

    def _connect_live(self, route: KO2Route | None = None, *, auto_detected: bool = False) -> None:
        if not self._apply_settings(show_message=False):
            return
        if route is None:
            self._refresh_report()
            route = self._resolve_configured_route()
        if not route.output_port:
            messagebox.showwarning("KO II Connection", route.message)
            self._log(f"connect blocked: {route.message}")
            return
        title = "EP-133 Found" if auto_detected else "Connect EP-133"
        prefix = "Detected a usable KO II MIDI route.\n\n" if auto_detected else ""
        if not messagebox.askyesno(
            title,
            f"{prefix}Use live MIDI output {route.output_port!r} and input {route.input_port or 'none'!r}?\n\n"
            f"Access mode: {self.app_settings.access_mode}\n"
            f"SysEx enabled: {'yes' if self.app_settings.sysex_enabled else 'no'}\n\n"
            "Pad, transport, CC, and enabled SysEx controls will talk to the device.",
        ):
            if auto_detected:
                self._log("auto-connect declined")
            return

        self._disconnect_live(silent=True)
        backend = WinMMMidiBackend()
        safety = DeviceSafetyConfig(
            dry_run=False,
            allowed_output_ports=(route.allow_output or route.output_port,),
            sysex_enabled=self.app_settings.sysex_enabled,
            max_sysex_bytes=self.app_settings.max_sysex_bytes,
        )
        self.config = DAWConfig(
            bpm=float(self.bpm.get()),
            midi_channel=self.session.profile.midi_channel,
            clock_enabled=True,
            safety=safety,
        )
        self.controller = DAWController(config=self.config, backend=backend, output_port=route.output_port)
        self.backend = backend
        self.live_backend = backend
        self.live_input_port = route.input_port
        self.live_output_port = route.output_port
        if route.input_port:
            self.input_monitor = WinMMInputMonitor(route.input_port, self._queue_midi_input, include_sysex=True)
            try:
                self.input_monitor.start()
            except Exception as exc:
                backend.close()
                self._reset_dry_controller()
                messagebox.showerror("KO II Connection", f"Could not open MIDI input {route.input_port!r}:\n{exc}")
                return
        self.status.set("LIVE EP-133")
        self.live_state.set(f"live: {self.live_input_port or '-'} -> {self.live_output_port}")
        self.hardware_status.set("live connection ready")
        self._log(f"live connected: {self.live_input_port or '-'} -> {self.live_output_port}")
        if self.app_settings.sysex_enabled and self.app_settings.auto_scan_on_connect:
            self.hardware_status.set("live connection ready / loading files")
            self._scan_complete_device_tree(auto=True)

    def _disconnect_live(self, *, silent: bool = False) -> None:
        if self.input_monitor:
            try:
                self.input_monitor.stop()
            except Exception as exc:
                self._log(f"monitor close error: {exc}")
        if self.live_backend:
            try:
                self.live_backend.close()
            except Exception as exc:
                self._log(f"midi close error: {exc}")
        self._reset_dry_controller()
        self.status.set("DRY RUN")
        self.hardware_status.set("connect live, then run read-only probes")
        if not silent:
            self._log("live disconnected")
            self._refresh_ports()

    def _reset_dry_controller(self) -> None:
        self.input_monitor = None
        self.live_backend = None
        self.live_input_port = None
        self.live_output_port = None
        self.backend = DryRunMidiBackend(
            input_ports=list(self.report.get("input_ports") or []),
            output_ports=list(self.report.get("output_ports") or []),
        )
        self.config = DAWConfig(clock_enabled=True)
        self.controller = DAWController(config=self.config, backend=self.backend)

    def _queue_midi_input(self, message: MidiMessage) -> None:
        if message.kind == "sysex" and message.data:
            with self._sysex_lock:
                self._sysex_responses.append(message.data)
            self._sysex_event.set()
        self.input_queue.put(message)

    def _drain_input_queue(self) -> None:
        while True:
            try:
                item = self.input_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, MidiMessage):
                self.runtime_state.observe(item, "in")
                if item.kind == "sysex" and item.data:
                    decoded = decode_sysex_response(item.data)
                    self._log(f"in sysex: {decoded.summary}")
                else:
                    self._log(f"in {item.display()}")
                self._refresh_state_label()
            elif isinstance(item, tuple) and item and item[0] == "sysex_probe_result":
                _, name, responses, timed_out = item
                self._handle_sysex_probe_result(str(name), list(responses), bool(timed_out))
            elif isinstance(item, tuple) and item and item[0] == "hardware_clear":
                self._clear_hardware_cache(silent=True)
            elif isinstance(item, tuple) and item and item[0] == "hardware_entry":
                _, kind, node, path, size, status = item
                self._add_hardware_entry(str(kind), str(node), str(path), str(size), str(status))
            elif isinstance(item, tuple) and item and item[0] == "hardware_scan_status":
                self.hardware_status.set(str(item[1]))
                self._log(str(item[1]))
            elif isinstance(item, tuple) and item and item[0] == "error":
                self._log(f"error: {item[1]}")
                messagebox.showerror("KO II Sampler DAW", str(item[1]))
        self.root.after(100, self._drain_input_queue)

    def _send_midi(self, message: MidiMessage) -> bool:
        try:
            self.controller.send(message)
        except Exception as exc:
            self._log(f"send failed: {exc}")
            messagebox.showerror("KO II MIDI", str(exc))
            return False
        self.runtime_state.observe(message, "out")
        self._refresh_state_label()
        return True

    def _set_action(self, text: str) -> None:
        self.last_action.set(text)
        self._log(text)

    def _set_bpm(self, value: float) -> None:
        self.bpm.set(round(value))
        self.session.bpm = float(round(value))
        self._set_action(f"tempo {int(round(value))} bpm")

    def _set_velocity(self, value: float) -> None:
        self.velocity.set(int(round(value)))
        self._set_action(f"velocity {self.velocity.get()}")

    def _send_mod_wheel(self, value: int) -> None:
        if self._send_midi(MidiMessage.control_change(1, value, channel=self.config.midi_channel)):
            self._set_action(f"mod wheel {value}")

    def _trigger_pad(self, pad_index: int) -> None:
        group = self.group.get()
        self.session.selected_group = group
        note = PAD_NOTES[group][pad_index]
        if not self._send_midi(MidiMessage.note_on(note, velocity=self.velocity.get(), channel=self.config.midi_channel)):
            return
        self._send_midi(MidiMessage.note_off(note, channel=self.config.midi_channel))
        self._set_action(f"group {group} pad {pad_index + 1} note {note}")

    def _record(self) -> None:
        self._set_action("record armed (dry-run)")

    def _start(self) -> None:
        if self._send_midi(MidiMessage.start()):
            self.controller.state.running = True
            self._set_action("transport start")

    def _continue(self) -> None:
        if self._send_midi(MidiMessage.continue_()):
            self.controller.state.running = True
            self._set_action("transport continue")

    def _stop(self) -> None:
        if self._send_midi(MidiMessage.stop()):
            self.controller.state.running = False
            self._set_action("transport stop")

    def _panic(self) -> None:
        for channel in range(16):
            self._send_midi(MidiMessage.control_change(123, 0, channel=channel))
            self._send_midi(MidiMessage.control_change(120, 0, channel=channel))
        self._set_action("panic: all notes off")

    def _save_project(self) -> None:
        snapshot = ProjectSnapshot(
            name="ko2-daw-gui-session",
            bpm=self.bpm.get(),
            midi_channel=0,
            controller_log=[event.message for event in self.runtime_state.recent_events[-64:]],
        )
        path = SafeProjectStore(self.project_root).save("gui_session.json", snapshot)
        self._set_action(f"saved {path.name}")
        messagebox.showinfo("KO II Sampler DAW", f"Saved session:\n{path}")

    def _save_session(self) -> None:
        self.session.routing.input_port = (self.report.get("input_ports") or [None])[0]
        outputs = list(self.report.get("output_ports") or [])
        self.session.routing.output_port = outputs[0] if len(outputs) == 1 else self.session.routing.output_port
        self.session.routing.input_port = self.live_input_port or self.session.routing.input_port
        self.session.routing.output_port = self.live_output_port or self.session.routing.output_port
        self.session.routing.live_enabled = self.live_output_port is not None
        path = CompanionSessionStore(self.project_root).save("companion_session.json", self.session)
        self.session_status.set(f"session saved: {path.name}")
        self._set_action(f"saved {path.name}")
        messagebox.showinfo("KO II Companion", f"Saved companion session:\n{path}")

    def _import_wav(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Import WAV samples",
            filetypes=(("WAV audio", "*.wav"), ("All files", "*.*")),
        )
        if not paths:
            return
        imported = 0
        for path in paths:
            try:
                self.sample_library.add_wav(path)
                imported += 1
            except Exception as exc:
                self._log(f"sample import failed: {Path(path).name}: {exc}")
        self._refresh_sample_tree()
        self._set_action(f"imported {imported} wav sample(s)")

    def _refresh_sample_tree(self) -> None:
        for item in self.sample_tree.get_children():
            self.sample_tree.delete(item)
        for sample in self.sample_library.ordered():
            self.sample_tree.insert(
                "",
                tk.END,
                iid=str(sample.slot),
                values=(
                    sample.slot,
                    sample.name,
                    f"{sample.duration_sec:.2f}s",
                    sample.sample_rate,
                    sample.channels,
                    sample.sample_width_bits,
                    f"{sample.size_bytes // 1024} KB",
                    sample.path,
                ),
            )
        self.sample_status.set(f"{len(self.sample_library.samples)} / {MAX_SAMPLE_SLOTS} slots")

    def _selected_sample(self):
        selected = self.sample_tree.selection()
        if not selected:
            messagebox.showinfo("KO II Samples", "Select a sample first.")
            return None
        return self.sample_library.samples.get(int(selected[0]))

    def _play_selected_sample(self) -> None:
        sample = self._selected_sample()
        if not sample:
            return
        try:
            play_wav(sample.path)
        except Exception as exc:
            messagebox.showerror("KO II Samples", str(exc))
            return
        self._set_action(f"local play slot {sample.slot}: {sample.name}")

    def _stop_audio(self) -> None:
        stop_wav()
        self._set_action("local audio stop")

    def _trigger_selected_sample(self) -> None:
        sample = self._selected_sample()
        if not sample:
            return
        slot = sample.slot % 48
        group = ("A", "B", "C", "D")[slot // 12]
        pad = slot % 12
        self.group.set(group)
        self._trigger_pad(pad)

    def _save_sample_manifest(self) -> None:
        path = self.sample_library.save(self.project_root / "sample_manifest.json")
        self._set_action(f"saved {path.name}")
        messagebox.showinfo("KO II Samples", f"Saved sample manifest:\n{path}")

    def _probe_identity(self) -> None:
        self._run_sysex_probe("identity", build_universal_identity_request())

    def _probe_file_init(self) -> None:
        self._run_sysex_probe(
            "file-init",
            build_te_frame(TEFileCommand.COMMAND, build_file_init_payload(), request_id=1),
        )

    def _probe_root_list(self) -> None:
        self._run_sysex_probe(
            "root-list",
            build_te_frame(TEFileCommand.COMMAND, build_file_list_payload(0, 0), request_id=2),
        )

    def _probe_selected_node(self) -> None:
        row = self._selected_hardware_row()
        if not row:
            return
        self._run_sysex_probe(
            f"list-{row['name']}",
            build_te_frame(TEFileCommand.COMMAND, build_file_list_payload(int(row["node"]), 0), request_id=3),
        )

    def _selected_hardware_row(self) -> dict[str, object] | None:
        selected = self.hardware_tree.selection()
        if not selected:
            messagebox.showinfo("KO II Hardware Files", "Select a hardware folder or file row first.")
            return None
        values = self.hardware_tree.item(selected[0], "values")
        if len(values) < 2:
            return None
        try:
            node_id = int(values[1])
        except (TypeError, ValueError):
            messagebox.showinfo("KO II Hardware Files", "The selected row does not have a numeric node id.")
            return None
        return {
            "kind": str(values[0]) if len(values) > 0 else "",
            "node": node_id,
            "name": str(values[2]) if len(values) > 2 else str(node_id),
            "size": str(values[3]) if len(values) > 3 else "",
            "status": str(values[4]) if len(values) > 4 else "",
        }

    def _play_selected_device_file(self) -> None:
        self._send_device_file_playback(TEFileCommand.PLAYBACK_START)

    def _stop_selected_device_file(self) -> None:
        self._send_device_file_playback(TEFileCommand.PLAYBACK_STOP)

    def _send_device_file_playback(self, action: int) -> None:
        if not self.app_settings.playback_enabled:
            messagebox.showinfo(
                "KO II Hardware Files",
                "Device file playback is disabled in Settings. Use read-playback or expert-write mode with file playback enabled.",
            )
            return
        row = self._selected_hardware_row()
        if not row:
            return
        if row["kind"] != "file":
            messagebox.showinfo(
                "KO II Hardware Files",
                "Select a file row to preview. Directory/project rows can be browsed with LIST SELECTED; transport PLAY/CONT/STOP controls device playback state.",
            )
            return
        node_id = int(row["node"])
        label = str(row["name"])
        verb = "play" if action == TEFileCommand.PLAYBACK_START else "stop"
        if action == TEFileCommand.PLAYBACK_START and self.app_settings.require_playback_confirmation and not messagebox.askyesno(
            "Play Device File",
            f"Send EP-133 device playback start for:\n\n{label}\n\nThis may play audio on the sampler.",
        ):
            return
        frame = build_te_frame(
            TEFileCommand.COMMAND,
            build_file_playback_payload(node_id, action),
            request_id=5 if action == TEFileCommand.PLAYBACK_START else 6,
        )
        self._run_sysex_probe(f"{verb}-{label}", frame)

    def _run_sysex_probe(self, name: str, frame: bytes) -> None:
        if not self.live_output_port:
            messagebox.showinfo("KO II Hardware Files", "Connect EP-133 live before running hardware probes.")
            return
        if not self.app_settings.sysex_enabled:
            messagebox.showinfo("KO II Hardware Files", "SysEx is disabled in Settings.")
            return
        self.hardware_status.set(f"{name}: waiting for response")
        self._set_action(f"sysex {name}")
        with self._sysex_lock:
            self._sysex_responses.clear()
        self._sysex_event.clear()

        def worker() -> None:
            try:
                responses = self._send_sysex_and_decode(
                    name,
                    frame,
                    self.app_settings.sysex_timeout_sec,
                )
                timed_out = not responses
                self.input_queue.put(("sysex_probe_result", name, responses, timed_out))
            except Exception as exc:
                self.input_queue.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_complete_device_tree(self, auto: bool = False) -> None:
        if not self.live_output_port:
            if not auto:
                messagebox.showinfo("KO II Hardware Files", "Connect EP-133 live before scanning device files.")
            return
        if not self.app_settings.sysex_enabled:
            if not auto:
                messagebox.showinfo("KO II Hardware Files", "SysEx is disabled in Settings.")
            return
        if self._hardware_scan_lock.locked():
            if not auto:
                messagebox.showinfo("KO II Hardware Files", "A device file scan is already running.")
            return

        def worker() -> None:
            if not self._hardware_scan_lock.acquire(blocking=False):
                return
            try:
                self.input_queue.put(("hardware_clear",))
                self.input_queue.put(("hardware_scan_status", "device scan: identity"))
                identity = self._send_sysex_and_decode(
                    "identity",
                    build_universal_identity_request(),
                    self.app_settings.sysex_timeout_sec,
                )
                self.input_queue.put(("sysex_probe_result", "identity", identity, not identity))

                self.input_queue.put(("hardware_scan_status", "device scan: file init"))
                init = self._send_sysex_and_decode(
                    "file-init",
                    build_te_frame(TEFileCommand.COMMAND, build_file_init_payload(), request_id=1),
                    self.app_settings.sysex_timeout_sec,
                )
                self.input_queue.put(("sysex_probe_result", "file-init", init, not init))

                scanned_nodes = 0
                request_id = 2
                queue_nodes: list[tuple[int, str, int]] = [(0, "", 0)]
                seen_nodes: set[int] = set()
                while queue_nodes and scanned_nodes < self.app_settings.scan_max_dirs:
                    node_id, parent_path, depth = queue_nodes.pop(0)
                    if node_id in seen_nodes or depth > self.app_settings.scan_max_depth:
                        continue
                    seen_nodes.add(node_id)
                    scanned_nodes += 1
                    entries_seen_for_node: set[tuple[tuple[object, ...], ...]] = set()
                    for page in range(self.app_settings.scan_pages_per_dir):
                        self.input_queue.put(("hardware_scan_status", f"device scan: node {node_id} page {page}"))
                        request_id = (request_id + 1) & 0x3FFF
                        frame = build_te_frame(
                            TEFileCommand.COMMAND,
                            build_file_list_payload(node_id, page),
                            request_id=request_id or 1,
                        )
                        responses = self._send_sysex_and_decode(
                            f"list-{node_id}-{page}",
                            frame,
                            self.app_settings.sysex_timeout_sec,
                        )
                        entries = self._entries_from_responses(responses)
                        if not entries:
                            break
                        signature = tuple(
                            (entry.get("node_id"), entry.get("kind"), entry.get("name"), entry.get("size"))
                            for entry in entries
                        )
                        if signature in entries_seen_for_node:
                            break
                        entries_seen_for_node.add(signature)
                        for entry in entries:
                            child_node = int(entry.get("node_id") or 0)
                            name = str(entry.get("name") or child_node)
                            kind = str(entry.get("kind") or "file")
                            size = int(entry.get("size") or 0)
                            full_path = self._device_child_path(parent_path, name)
                            self.input_queue.put(("hardware_entry", kind, child_node, full_path, size, f"node {node_id} page {page}"))
                            if kind == "dir" and child_node not in seen_nodes:
                                queue_nodes.append((child_node, full_path, depth + 1))
                self.input_queue.put(("hardware_scan_status", f"device scan complete: {scanned_nodes} directories checked"))
            except Exception as exc:
                self.input_queue.put(("error", exc))
            finally:
                self._hardware_scan_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    def _run_sysex_probe_sequence(self, frames: list[tuple[str, bytes]]) -> None:
        if not self.live_output_port:
            messagebox.showinfo("KO II Hardware Files", "Connect EP-133 live before running hardware probes.")
            return
        if not self.app_settings.sysex_enabled:
            messagebox.showinfo("KO II Hardware Files", "SysEx is disabled in Settings.")
            return
        self.hardware_status.set("device scan: running")
        self._set_action("device scan")

        def worker() -> None:
            try:
                for name, frame in frames:
                    responses = self._send_sysex_and_decode(
                        name,
                        frame,
                        self.app_settings.sysex_timeout_sec,
                    )
                    timed_out = not responses
                    self.input_queue.put(("sysex_probe_result", name, responses, timed_out))
                    time.sleep(0.08)
            except Exception as exc:
                self.input_queue.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _send_sysex_and_decode(self, name: str, frame: bytes, timeout_sec: float) -> list[SysexDecodedResponse]:
        del name
        with self._sysex_transaction_lock:
            with self._sysex_lock:
                self._sysex_responses.clear()
            self._sysex_event.clear()
            self.controller.send(MidiMessage.sysex(frame))
            deadline = time.monotonic() + max(0.1, timeout_sec)
            cursor = 0
            while time.monotonic() < deadline:
                with self._sysex_lock:
                    raw_responses = list(self._sysex_responses[cursor:])
                    cursor = len(self._sysex_responses)
                matched = matching_sysex_responses(frame, raw_responses)
                if matched:
                    return [decode_sysex_response(data) for data in matched]
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._sysex_event.wait(min(remaining, 0.05))
                self._sysex_event.clear()
        return []

    def _entries_from_responses(self, responses: list[SysexDecodedResponse]) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for response in responses:
            response_entries = response.details.get("entries")
            if isinstance(response_entries, list):
                entries.extend(entry for entry in response_entries if isinstance(entry, dict))
        return entries

    def _device_child_path(self, parent_path: str, name: str) -> str:
        cleaned = str(name).strip("/")
        if not parent_path:
            return f"/{cleaned}"
        return f"{parent_path.rstrip('/')}/{cleaned}"

    def _handle_sysex_probe_result(
        self,
        name: str,
        responses: list[SysexDecodedResponse],
        timed_out: bool,
    ) -> None:
        if timed_out and not responses:
            self.hardware_status.set(f"{name}: no response")
            self._log(f"{name}: no SysEx response")
            return
        self.hardware_status.set(f"{name}: {len(responses)} response(s)")
        for response in responses:
            self._add_hardware_response(name, response)
            self._log(f"{name}: {response.summary}")

    def _add_hardware_response(self, probe_name: str, response: SysexDecodedResponse) -> None:
        details = response.details
        entries = details.get("entries")
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                self._add_hardware_entry(
                    str(entry.get("kind", "file")),
                    str(entry.get("node_id", "")),
                    str(entry.get("name", "")),
                    str(entry.get("size", "")),
                    response.summary,
                )
            return
        self._add_hardware_entry(
            response.kind,
            str(details.get("request_id", details.get("device_id", ""))),
            probe_name,
            str(details.get("payload_len", "")),
            response.summary,
        )

    def _add_hardware_entry(self, kind: str, node: str, name: str, size: str, status: str) -> None:
        key = (str(node), str(name))
        if key in self.hardware_rows_seen:
            return
        self.hardware_rows_seen.add(key)
        self.hardware_tree.insert(
            "",
            tk.END,
            values=(kind, node, name, size, status),
        )

    def _export_hardware_cache(self) -> None:
        rows = []
        for item in self.hardware_tree.get_children():
            values = self.hardware_tree.item(item, "values")
            rows.append(
                {
                    "kind": values[0] if len(values) > 0 else "",
                    "node": values[1] if len(values) > 1 else "",
                    "name": values[2] if len(values) > 2 else "",
                    "size": values[3] if len(values) > 3 else "",
                    "status": values[4] if len(values) > 4 else "",
                }
            )
        import json

        path = self.project_root / "hardware_file_cache.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"rows": rows}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._set_action(f"exported {path.name}")
        messagebox.showinfo("KO II Hardware Files", f"Exported hardware cache:\n{path}")

    def _clear_hardware_cache(self, silent: bool = False) -> None:
        for item in self.hardware_tree.get_children():
            self.hardware_tree.delete(item)
        self.hardware_rows_seen.clear()
        self.hardware_status.set("hardware cache cleared")
        if not silent:
            self._set_action("hardware cache cleared")

    def _show_doctor(self) -> None:
        report = readiness_report(self.report)
        route = report.get("route") or {}
        lines = [
            f"status: {report['status']}",
            f"ep-133 usb: {report['ko2_usb_connected']}",
            f"ep-133 midi: {report['ko2_midi_ready']}",
            f"route: {route.get('status')}",
            f"output: {route.get('output_port')}",
            f"input: {route.get('input_port')}",
            "",
            route.get("message") or "",
            route.get("requires_user_action") or "",
            "",
            *[f"- {action}" for action in report["actions"]],
        ]
        self._set_action("doctor report")
        messagebox.showinfo("KO II Doctor", "\n".join(lines))

    def _show_sysex_lab(self) -> None:
        identity = bytes_to_hex(build_universal_identity_request())
        file_init = bytes_to_hex(build_te_frame(TEFileCommand.COMMAND, build_file_init_payload(), request_id=1))
        lines = [
            f"7-bit packing self-test: {self_test_packing()}",
            f"access mode: {self.app_settings.access_mode}",
            f"sysex enabled: {self.app_settings.sysex_enabled}",
            f"write frame construction: {'armed' if self.app_settings.write_enabled else 'blocked'}",
            f"device file playback: {'enabled' if self.app_settings.playback_enabled else 'disabled'}",
            f"timeout: {self.app_settings.sysex_timeout_sec}s",
            "",
            f"identity: {identity}",
            f"file init: {file_init}",
        ]
        self._set_action("sysex lab")
        messagebox.showinfo("KO II SysEx Lab", "\n".join(lines))

    def _show_interaction_guide(self) -> None:
        lines = [
            "KO II Sampler DAW Interaction Guide",
            "",
            "Top display",
            "- Shows dry/live mode, MIDI ports, last action, and inferred state.",
            "- Inferred state is based on MIDI traffic observed or sent by the app.",
            "",
            "Mode keys",
            "- SOUND, MAIN, TEMPO, FX, SHIFT, and FADER mark the active hardware-style work area.",
            "- Current implementation logs these mode choices and keeps controls grouped like the physical unit.",
            "",
            "Groups and pads",
            "- GROUP A-D selects the active pad bank.",
            "- The 12 pads send note on/off for the selected group.",
            "- Dry-run logs the messages; live mode sends them to EP-133.",
            "",
            "Transport",
            "- REC records intent in the log only.",
            "- PLAY sends MIDI Start.",
            "- CONT sends MIDI Continue.",
            "- STOP sends MIDI Stop.",
            "- The KO II exposes Start, Continue, and Stop; it does not expose a separate DAW-style Pause command through the tested MIDI surface.",
            "- PANIC sends all-notes-off and all-sound-off on all channels.",
            "",
            "Parameters",
            "- Knob X sets session BPM.",
            "- Knob Y sets pad velocity.",
            "- FADER sends CC 1 / mod wheel.",
            "- SAVE writes a GUI session snapshot.",
            "- SAVE SESSION writes the companion profile and routing state.",
            "- CONNECT EP-133 opens the detected EP-133 MIDI input/output.",
            "- DISCONNECT closes live MIDI and returns to dry-run.",
            "- REFRESH MIDI rescans ports.",
            "- DOCTOR shows routing diagnostics.",
            "- SYSEX LAB shows safe read-only probe frames.",
            "",
            "Samples tab",
            "- IMPORT WAV adds local WAV files to the 999-slot library.",
            "- PLAY LOCAL previews the selected WAV on the computer.",
            "- STOP AUDIO stops local preview.",
            "- TRIGGER MIDI triggers the pad note mapped from the selected slot.",
            "- SAVE MANIFEST writes the local sample table to JSON.",
            "",
            "Hardware Files tab",
            "- READ IDENTITY asks the device for MIDI identity.",
            "- FILE INIT opens the read-only file protocol.",
            "- LIST ROOT lists device root folders.",
            "- LIST SELECTED browses the selected device node.",
            "- PLAY FILE starts EP-133 playback preview for the selected file row.",
            "- STOP FILE stops EP-133 playback preview for the selected file row.",
            "- SCAN DEVICE runs the confirmed read-only scan: identity, file init, root, sounds, and projects.",
            "- EXPORT CACHE saves the visible rows.",
            "- CLEAR removes visible rows from the table.",
            "",
            "Settings tab",
            "- Route chooses auto, direct EP-133 USB MIDI, QUAD-CAPTURE, or manual ports.",
            "- Access Policy chooses read-only, read-playback, or expert-write.",
            "- Auto-connect on launch checks for the configured route after startup and prompts when a usable KO II route is found.",
            "- read-only disables selected-file playback and write frame construction.",
            "- read-playback allows Hardware Files playback preview while keeping upload/delete/move/metadata writes blocked.",
            "- expert-write only arms write-capable frame construction when the Write arm field is exactly WRITE; destructive write buttons are still not exposed.",
            "- SysEx And Scan controls timeout, maximum frame size, scan pages, depth, and directory count.",
            "- SAVE writes these settings to daw_projects/app_settings.json.",
            "",
            "Log tab",
            "- Shows actions, MIDI traffic, and SysEx probe results.",
        ]
        self._set_action("interaction guide")
        messagebox.showinfo("KO II Help", "\n".join(lines))

    def _show_midi_safety(self) -> None:
        lines = [
            "MIDI And Safety",
            "",
            "- The app starts in DRY RUN. No MIDI is sent until CONNECT EP-133 is confirmed.",
            "- If auto-connect is enabled, startup scans for the configured route and asks before opening live MIDI.",
            "- Live mode uses the detected EP-133 route and an allow-list safety gate.",
            "- Settings controls route choice, SysEx enablement, playback preview, scan limits, and write policy.",
            "- Pads, transport, and CC fader can change what the connected sampler is doing.",
            "- Hardware file browsing uses read-only SysEx probes; PLAY FILE and STOP FILE send explicit device playback start/stop only.",
            "- Upload, delete, move, restore, and metadata write operations are not exposed in this GUI; expert write mode only changes the low-level frame-construction policy.",
            "- If another app holds the EP-133 MIDI port, disconnect there and use REFRESH MIDI.",
        ]
        self._set_action("midi safety")
        messagebox.showinfo("KO II MIDI Safety", "\n".join(lines))

    def _log(self, text: str) -> None:
        self.log.insert(tk.END, f"{text}\n")
        self.log.see(tk.END)

    def _refresh_state_label(self) -> None:
        active = ", ".join(self.runtime_state.active_notes.keys()) or "none"
        self.state_label.configure(
            text=(
                f"transport: {self.runtime_state.transport}    "
                f"active notes: {active}    "
                f"clock: {self.runtime_state.clock_ticks}    "
                f"mod: {self.runtime_state.mod_wheel if self.runtime_state.mod_wheel is not None else 'unknown'}"
            )
        )

    def _close(self) -> None:
        self._disconnect_live(silent=True)
        stop_wav()
        self.root.destroy()


def run_gui() -> int:
    root = tk.Tk()
    ttk.Style(root)
    KO2DawApp(root)
    root.mainloop()
    return 0
