"""Stable multitrack audio studio GUI for the KO II companion DAW."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import queue
import threading
import time
from typing import Any

from ko2_daw.audio_timeline import (
    AudioProject,
    AudioSession,
    default_audio_project,
    read_wave_source,
    render_audio_project,
    waveform_peaks,
)
from ko2_daw.native_audio import list_wave_input_devices, record_wave_input
from ko2_daw.samples import play_wav, stop_wav


def apply_audio_studio_patch(gui_module: Any) -> None:
    """Install the non-destructive audio timeline into the stable GUI."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_audio_studio_patch_installed", False):
        return

    tk = gui_module.tk
    ttk = gui_module.ttk
    filedialog = gui_module.filedialog
    messagebox = gui_module.messagebox
    original_init = app_class.__init__
    original_build_menu = app_class._build_menu
    original_close = app_class._close

    def __init__(self, root) -> None:
        self.audio_session = AudioSession(default_audio_project())
        self.audio_window = None
        self.audio_queue: queue.Queue[tuple[object, ...]] = queue.Queue()
        self.audio_record_stop = threading.Event()
        self.audio_recording = False
        self.audio_busy = False
        self.audio_wave_cache: dict[tuple[object, ...], list[tuple[float, float]]] = {}
        self.audio_clip_items: dict[int, str] = {}
        self.audio_drag = None
        self.audio_cursor_sec = 0.0
        original_init(self, root)
        self.audio_status = tk.StringVar(value="audio studio ready")
        self.root.after(80, self._poll_audio_queue)

    def _build_menu(self) -> None:
        original_build_menu(self)
        menu = self.root.nametowidget(self.root.cget("menu"))
        daw_menu = _find_menu(menu, "DAW")
        if daw_menu is None:
            daw_menu = tk.Menu(menu, tearoff=False)
            menu.add_cascade(label="DAW", menu=daw_menu)
        daw_menu.insert_command(
            0,
            label="Audio Studio",
            command=self._show_audio_studio,
        )
        daw_menu.insert_command(
            1,
            label="Render Audio Mix",
            command=self._audio_render_dialog,
        )
        daw_menu.insert_separator(2)
        help_menu = _find_menu(menu, "Help")
        if help_menu is not None:
            help_menu.add_command(label="Audio Studio Guide", command=self._show_audio_help)

    def _show_audio_studio(self) -> None:
        if self.audio_window and self.audio_window.winfo_exists():
            self.audio_window.lift()
            self._refresh_audio_studio()
            return
        win = tk.Toplevel(self.root)
        win.title("KO II Audio Studio")
        win.geometry("1440x840")
        win.minsize(1180, 800)
        win.configure(bg="#d8d4c8")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(2, weight=1)
        self.audio_window = win

        project = self.audio_session.project
        self.audio_project_name = tk.StringVar(value=project.name)
        self.audio_sample_rate = tk.IntVar(value=project.sample_rate)
        self.audio_master_gain = tk.DoubleVar(value=project.master_gain_db)
        self.audio_zoom = tk.DoubleVar(value=90.0)
        self.audio_snap = tk.BooleanVar(value=True)
        self.audio_cursor_var = tk.StringVar(value="0.000")
        self.audio_track_name = tk.StringVar()
        self.audio_track_gain = tk.DoubleVar()
        self.audio_track_pan = tk.DoubleVar()
        self.audio_track_mute = tk.BooleanVar()
        self.audio_track_solo = tk.BooleanVar()
        self.audio_track_arm = tk.BooleanVar()
        self.audio_clip_start = tk.DoubleVar()
        self.audio_clip_in = tk.DoubleVar()
        self.audio_clip_out = tk.DoubleVar()
        self.audio_clip_stretch = tk.DoubleVar(value=1.0)
        self.audio_clip_gain = tk.DoubleVar()
        self.audio_clip_pan = tk.DoubleVar()
        self.audio_clip_fade_in = tk.DoubleVar()
        self.audio_clip_fade_out = tk.DoubleVar()
        self.audio_clip_reverse = tk.BooleanVar()
        self.audio_clip_mute = tk.BooleanVar()
        devices = list_wave_input_devices()
        preferred = next(
            (device.name for device in devices if "MAIN" in device.name.upper()),
            devices[0].name if devices else "",
        )
        self.audio_input_device = tk.StringVar(value=preferred)
        self.audio_record_duration = tk.DoubleVar(value=30.0)
        self.audio_record_rate = tk.IntVar(value=48000)
        self.audio_source_info = tk.StringVar(value="No clip selected")
        self.audio_summary = tk.StringVar(value="")

        header = tk.Frame(win, bg="#171915", padx=10, pady=8)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        title = tk.Label(
            header,
            text="KO II  /  AUDIO STUDIO",
            bg="#171915",
            fg="#d7f58a",
            font=("Consolas", 18, "bold"),
        )
        title.grid(row=0, column=0, sticky="w")
        name = tk.Entry(
            header,
            textvariable=self.audio_project_name,
            bg="#252820",
            fg="#f3f1de",
            insertbackground="#f3f1de",
            relief=tk.FLAT,
            font=("Consolas", 11),
        )
        name.grid(row=0, column=1, sticky="ew", padx=14)
        status = tk.Label(
            header,
            textvariable=self.audio_status,
            bg="#d7f58a",
            fg="#171915",
            padx=10,
            pady=3,
            font=("Consolas", 10, "bold"),
        )
        status.grid(row=0, column=2, sticky="e")
        self._tip(title, "Non-destructive stereo audio timeline for KO II samples, resampling, capture, editing, mixing, and WAV export.")
        self._tip(name, "Audio project name stored in the editable JSON session.")
        self._tip(status, "Current import, recording, rendering, or preview state.")

        toolbar = tk.Frame(win, bg="#bdb7aa", padx=7, pady=6)
        toolbar.grid(row=1, column=0, sticky="ew")
        toolbar.columnconfigure(0, weight=1)
        config_bar = tk.Frame(toolbar, bg="#bdb7aa")
        config_bar.grid(row=0, column=0, sticky="ew")
        action_bar = tk.Frame(toolbar, bg="#bdb7aa")
        action_bar.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        _label(config_bar, "BPM", tk).pack(side=tk.LEFT)
        bpm = tk.Spinbox(config_bar, textvariable=self.bpm, from_=20, to=300, width=6)
        bpm.pack(side=tk.LEFT, padx=(3, 8))
        _label(config_bar, "RATE", tk).pack(side=tk.LEFT)
        rate = ttk.Combobox(
            config_bar,
            textvariable=self.audio_sample_rate,
            values=(44100, 46875, 48000, 88200, 96000),
            state="readonly",
            width=7,
        )
        rate.pack(side=tk.LEFT, padx=(3, 8))
        _label(config_bar, "MASTER dB", tk).pack(side=tk.LEFT)
        master = tk.Spinbox(
            config_bar,
            textvariable=self.audio_master_gain,
            from_=-96,
            to=24,
            increment=0.5,
            width=6,
        )
        master.pack(side=tk.LEFT, padx=(3, 8))
        tk.Label(
            config_bar,
            textvariable=self.audio_summary,
            bg="#bdb7aa",
            fg="#55584f",
            font=("Consolas", 9, "bold"),
        ).pack(side=tk.RIGHT)
        self._tip(bpm, "Project tempo used for beat grid and snap.")
        self._tip(rate, "Mixdown sample rate. 46,875 Hz matches downloaded EP-133 sample metadata.")
        self._tip(master, "Master gain applied after clip and track gain.")

        actions = (
            ("IMPORT", self._audio_import, "#efeadf", "Import a PCM WAV onto the selected audio track at the edit cursor."),
            ("DEVICE WAV", self._audio_import_device_wav, "#efeadf", "Import a previously downloaded EP-133 WAV from the immutable device library."),
            ("REC", self._audio_record, "#dc493a", "Record the selected Windows audio input into the first armed track."),
            ("KO II BOUNCE", self._audio_bounce_ko2, "#f2c230", "Run the MIDI arranger against the connected EP-133 while capturing its analog output to an armed audio track."),
            ("STOP REC", self._audio_stop_record, "#efeadf", "Request a clean stop after the current WinMM capture buffer."),
            ("PLAY MIX", self._audio_preview_mix, "#88b04b", "Render a temporary current mix and play it through Windows audio."),
            ("STOP", stop_wav, "#efeadf", "Stop local WAV playback."),
            ("RENDER", self._audio_render_dialog, "#efeadf", "Render a stereo 16-bit PCM WAV with optional peak normalization."),
            ("SAVE", self._audio_save, "#efeadf", "Save the non-destructive audio project as atomic JSON."),
            ("LOAD", self._audio_load, "#efeadf", "Load and validate an audio project JSON file."),
            ("UNDO", self._audio_undo, "#efeadf", "Undo the latest timeline or mixer edit."),
            ("REDO", self._audio_redo, "#efeadf", "Redo the latest undone audio edit."),
            ("HELP", self._show_audio_help, "#efeadf", "Show all Audio Studio interactions."),
        )
        for column, (text, command, color, tip) in enumerate(actions):
            action_bar.columnconfigure(column, weight=1, uniform="audio-actions")
            button = tk.Button(action_bar, text=text, command=command, bg=color, padx=4)
            button.grid(row=0, column=column, sticky="ew", padx=2)
            self._tip(button, tip)

        body = tk.PanedWindow(
            win,
            orient=tk.HORIZONTAL,
            sashwidth=5,
            bg="#171915",
            bd=0,
        )
        body.grid(row=2, column=0, sticky="nsew")
        left = tk.Frame(body, bg="#d8d4c8", padx=7, pady=7, width=300)
        center = tk.Frame(body, bg="#d8d4c8", padx=7, pady=7)
        right = tk.Frame(body, bg="#d8d4c8", padx=7, pady=7, width=330)
        body.add(left, minsize=270)
        body.add(center, minsize=570, stretch="always")
        body.add(right, minsize=300)
        self._build_audio_tracks(left)
        self._build_audio_timeline(center)
        self._build_audio_inspector(right, devices)
        self._refresh_audio_studio()

    def _build_audio_tracks(self, parent) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        tk.Label(
            parent,
            text="TRACK MIXER",
            bg="#d8d4c8",
            fg="#171915",
            font=("Consolas", 12, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        tree = ttk.Treeview(
            parent,
            columns=("m", "s", "r", "gain", "pan"),
            show="tree headings",
            height=14,
        )
        tree.heading("#0", text="Track")
        tree.column("#0", width=105, anchor="w")
        for column, width in (("m", 28), ("s", 28), ("r", 28), ("gain", 48), ("pan", 45)):
            tree.heading(column, text=column.upper())
            tree.column(column, width=width, anchor="center")
        tree.grid(row=1, column=0, sticky="nsew", pady=(5, 4))
        tree.bind("<<TreeviewSelect>>", lambda _event: self._audio_track_selected())
        self.audio_track_tree = tree
        self._tip(tree, "Select a track. M, S, R indicate mute, solo, and record arm; gain and pan are non-destructive.")
        row = tk.Frame(parent, bg="#bdb7aa", padx=4, pady=4)
        row.grid(row=2, column=0, sticky="ew")
        for text, command, tip in (
            ("+", self._audio_add_track, "Add a new audio track."),
            ("-", self._audio_remove_track, "Delete the selected track and its clips after confirmation."),
        ):
            button = tk.Button(row, text=text, command=command, bg="#efeadf", width=3)
            button.pack(side=tk.LEFT, padx=2)
            self._tip(button, tip)

        editor = tk.Frame(parent, bg="#bdb7aa", padx=6, pady=6)
        editor.grid(row=3, column=0, sticky="ew", pady=(5, 0))
        editor.columnconfigure(1, weight=1)
        fields = (
            ("NAME", self.audio_track_name, None),
            ("GAIN dB", self.audio_track_gain, (-96, 24, 0.5)),
            ("PAN", self.audio_track_pan, (-1, 1, 0.05)),
        )
        for row_index, (text, variable, bounds) in enumerate(fields):
            _label(editor, text, tk).grid(row=row_index, column=0, sticky="w", pady=2)
            if bounds is None:
                widget = tk.Entry(editor, textvariable=variable)
            else:
                widget = tk.Spinbox(
                    editor,
                    textvariable=variable,
                    from_=bounds[0],
                    to=bounds[1],
                    increment=bounds[2],
                )
            widget.grid(row=row_index, column=1, sticky="ew", padx=(5, 0), pady=2)
        toggles = tk.Frame(editor, bg="#bdb7aa")
        toggles.grid(row=3, column=0, columnspan=2, sticky="ew", pady=4)
        for text, variable, tip in (
            ("MUTE", self.audio_track_mute, "Mute this track."),
            ("SOLO", self.audio_track_solo, "Solo this track; other non-solo tracks are excluded."),
            ("ARM", self.audio_track_arm, "Arm this track for native audio recording."),
        ):
            check = tk.Checkbutton(
                toggles,
                text=text,
                variable=variable,
                indicatoron=False,
                bg="#efeadf",
                selectcolor="#d7f58a",
            )
            check.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
            self._tip(check, tip)
        apply_button = tk.Button(
            editor,
            text="APPLY TRACK",
            command=self._audio_apply_track,
            bg="#efeadf",
        )
        apply_button.grid(row=4, column=0, columnspan=2, sticky="ew")
        self._tip(apply_button, "Commit track name, gain, pan, mute, solo, and arm as one undoable edit.")

    def _build_audio_timeline(self, parent) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        tk.Label(
            parent,
            text="AUDIO TIMELINE",
            bg="#171915",
            fg="#d7f58a",
            font=("Consolas", 12, "bold"),
            padx=8,
            pady=5,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        controls = tk.Frame(parent, bg="#bdb7aa", padx=5, pady=5)
        controls.grid(row=1, column=0, sticky="ew", pady=5)
        _label(controls, "CURSOR", tk).pack(side=tk.LEFT)
        cursor = tk.Entry(controls, textvariable=self.audio_cursor_var, width=8)
        cursor.pack(side=tk.LEFT, padx=(3, 8))
        cursor.bind("<Return>", lambda _event: self._audio_cursor_from_field())
        _label(controls, "ZOOM", tk).pack(side=tk.LEFT)
        zoom = tk.Scale(
            controls,
            variable=self.audio_zoom,
            from_=30,
            to=300,
            resolution=10,
            orient=tk.HORIZONTAL,
            showvalue=False,
            length=130,
            command=lambda _value: self._draw_audio_timeline(),
            bg="#bdb7aa",
        )
        zoom.pack(side=tk.LEFT, padx=(3, 8))
        snap = tk.Checkbutton(
            controls,
            text="SNAP 1/16",
            variable=self.audio_snap,
            bg="#bdb7aa",
        )
        snap.pack(side=tk.LEFT)
        self._tip(cursor, "Edit cursor in seconds. Empty timeline clicks move it; split and import use it.")
        self._tip(zoom, "Horizontal pixels per second.")
        self._tip(snap, "Snap cursor and dragged clips to the nearest sixteenth note at project BPM.")

        shell = tk.Frame(parent, bg="#171915")
        shell.grid(row=2, column=0, sticky="nsew")
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)
        canvas = tk.Canvas(shell, bg="#11120f", highlightthickness=0)
        x_scroll = ttk.Scrollbar(shell, orient=tk.HORIZONTAL, command=canvas.xview)
        y_scroll = ttk.Scrollbar(shell, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        canvas.bind("<Configure>", lambda _event: self._draw_audio_timeline())
        canvas.bind("<ButtonPress-1>", self._audio_timeline_press)
        canvas.bind("<B1-Motion>", self._audio_timeline_drag)
        canvas.bind("<ButtonRelease-1>", self._audio_timeline_release)
        canvas.bind("<Double-1>", lambda _event: self._audio_audition_clip())
        self.audio_timeline_canvas = canvas
        self._tip(canvas, "Click to set cursor or select a clip. Drag clips horizontally or between tracks. Double-click previews the selected source WAV.")

    def _build_audio_inspector(self, parent, devices) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(6, weight=1)
        tk.Label(
            parent,
            text="CLIP INSPECTOR",
            bg="#d8d4c8",
            fg="#171915",
            font=("Consolas", 12, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        editor = tk.Frame(parent, bg="#bdb7aa", padx=6, pady=6)
        editor.grid(row=1, column=0, sticky="ew", pady=(5, 8))
        editor.columnconfigure(1, weight=1)
        specs = (
            ("START", self.audio_clip_start, 0, 36000, 0.01),
            ("SOURCE IN", self.audio_clip_in, 0, 36000, 0.01),
            ("SOURCE OUT", self.audio_clip_out, 0, 36000, 0.01),
            ("STRETCH", self.audio_clip_stretch, 0.125, 8, 0.025),
            ("GAIN dB", self.audio_clip_gain, -96, 24, 0.5),
            ("PAN", self.audio_clip_pan, -1, 1, 0.05),
            ("FADE IN", self.audio_clip_fade_in, 0, 3600, 0.01),
            ("FADE OUT", self.audio_clip_fade_out, 0, 3600, 0.01),
        )
        for row, (text, variable, minimum, maximum, increment) in enumerate(specs):
            _label(editor, text, tk).grid(row=row, column=0, sticky="w", pady=2)
            field = tk.Spinbox(
                editor,
                textvariable=variable,
                from_=minimum,
                to=maximum,
                increment=increment,
            )
            field.grid(row=row, column=1, sticky="ew", padx=(5, 0), pady=2)
            self._tip(field, _clip_field_tip(text))
        toggles = tk.Frame(editor, bg="#bdb7aa")
        toggles.grid(row=8, column=0, columnspan=2, sticky="ew", pady=4)
        for text, variable, tip in (
            ("REVERSE", self.audio_clip_reverse, "Play source frames backwards without changing the source file."),
            ("MUTE", self.audio_clip_mute, "Exclude this clip from preview and render."),
        ):
            check = tk.Checkbutton(
                toggles,
                text=text,
                variable=variable,
                indicatoron=False,
                bg="#efeadf",
                selectcolor="#d7f58a",
            )
            check.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
            self._tip(check, tip)
        apply_button = tk.Button(
            editor,
            text="APPLY CLIP",
            command=self._audio_apply_clip,
            bg="#efeadf",
        )
        apply_button.grid(row=9, column=0, columnspan=2, sticky="ew")
        self._tip(apply_button, "Commit all clip edits as one undoable operation.")
        actions = tk.Frame(parent, bg="#d8d4c8")
        actions.grid(row=2, column=0, sticky="ew")
        for text, command, tip in (
            ("SPLIT", self._audio_split_clip, "Split the selected clip at the edit cursor."),
            ("DUP", self._audio_duplicate_clip, "Duplicate the selected clip immediately after itself."),
            ("DELETE", self._audio_delete_clip, "Delete the selected clip without touching its source WAV."),
            ("AUDITION", self._audio_audition_clip, "Play the selected source WAV locally."),
        ):
            button = tk.Button(actions, text=text, command=command, bg="#efeadf")
            button.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=1)
            self._tip(button, tip)

        tk.Label(
            parent,
            text="NATIVE INPUT CAPTURE",
            bg="#d8d4c8",
            fg="#171915",
            font=("Consolas", 12, "bold"),
            anchor="w",
        ).grid(row=3, column=0, sticky="ew", pady=(12, 0))
        capture = tk.Frame(parent, bg="#171915", padx=7, pady=7)
        capture.grid(row=4, column=0, sticky="ew", pady=(5, 0))
        capture.columnconfigure(1, weight=1)
        _dark_label(capture, "INPUT", tk).grid(row=0, column=0, sticky="w")
        input_combo = ttk.Combobox(
            capture,
            textvariable=self.audio_input_device,
            values=tuple(device.name for device in devices),
            state="readonly",
        )
        input_combo.grid(row=0, column=1, sticky="ew", padx=(5, 0), pady=2)
        _dark_label(capture, "MAX SEC", tk).grid(row=1, column=0, sticky="w")
        duration = tk.Spinbox(
            capture,
            textvariable=self.audio_record_duration,
            from_=0.1,
            to=3600,
            increment=1,
        )
        duration.grid(row=1, column=1, sticky="ew", padx=(5, 0), pady=2)
        _dark_label(capture, "RATE", tk).grid(row=2, column=0, sticky="w")
        record_rate = ttk.Combobox(
            capture,
            textvariable=self.audio_record_rate,
            values=(44100, 48000, 96000),
            state="readonly",
        )
        record_rate.grid(row=2, column=1, sticky="ew", padx=(5, 0), pady=2)
        self._tip(input_combo, "Windows WinMM audio input. QUAD-CAPTURE MAIN/1-2 can record the KO II analog output.")
        self._tip(duration, "Safety-bounded maximum capture duration. STOP REC can finish earlier.")
        self._tip(record_rate, "Native capture sample rate; the timeline resamples during mixdown.")
        note = tk.Label(
            capture,
            text="LOCAL CAPTURE  /  DEVICE STORAGE LOCKED",
            bg="#171915",
            fg="#f3f1de",
            justify=tk.LEFT,
            anchor="w",
            font=("Consolas", 9),
        )
        note.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(7, 0))
        self._tip(note, "Audio capture is PC-side and preserves device configuration integrity.")

        tk.Label(
            parent,
            text="SELECTED SOURCE",
            bg="#d8d4c8",
            fg="#171915",
            font=("Consolas", 12, "bold"),
            anchor="w",
        ).grid(row=5, column=0, sticky="ew", pady=(12, 0))
        detail = tk.Frame(parent, bg="#171915", padx=6, pady=6)
        detail.grid(row=6, column=0, sticky="nsew", pady=(5, 0))
        detail.columnconfigure(0, weight=1)
        detail.rowconfigure(0, weight=1)
        canvas = tk.Canvas(detail, bg="#11120f", highlightthickness=0, height=100)
        canvas.grid(row=0, column=0, sticky="nsew")
        canvas.bind("<Configure>", lambda _event: self._draw_audio_source_detail())
        self.audio_source_canvas = canvas
        self._tip(canvas, "Waveform for the selected trimmed source range; fades are shown as diagonal guides.")
        info = tk.Label(
            detail,
            textvariable=self.audio_source_info,
            bg="#171915",
            fg="#f3f1de",
            justify=tk.LEFT,
            anchor="w",
            font=("Consolas", 8),
        )
        info.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        self._tip(info, "Source format, trim range, timeline duration, and file path.")

    def _audio_import(self, path: str | None = None) -> None:
        if path is None:
            path = filedialog.askopenfilename(
                title="Import PCM WAV",
                initialdir=str(self.project_root),
                filetypes=(("WAV audio", "*.wav"),),
            )
        if not path:
            return
        try:
            clip = self.audio_session.import_wav(
                path,
                start_sec=self.audio_cursor_sec,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("KO II Audio Studio", str(exc))
            return
        self.audio_status.set(f"imported {clip.name}")
        self._refresh_audio_studio()

    def _audio_import_device_wav(self) -> None:
        path = filedialog.askopenfilename(
            title="Import downloaded EP-133 WAV",
            initialdir=str(self.project_root / "device_library"),
            filetypes=(("WAV audio", "*.wav"),),
        )
        if path:
            self._audio_import(path)

    def _audio_record(self) -> None:
        if self.audio_recording or self.audio_busy:
            messagebox.showinfo("KO II Audio Studio", "Wait for the current audio operation.")
            return
        armed = [track for track in self.audio_session.project.tracks if track.armed]
        if not armed:
            messagebox.showinfo("KO II Audio Studio", "Arm at least one audio track first.")
            return
        try:
            duration = float(self.audio_record_duration.get())
            sample_rate = int(self.audio_record_rate.get())
            device = self.audio_input_device.get()
        except (TypeError, ValueError) as exc:
            messagebox.showerror("KO II Audio Studio", str(exc))
            return
        capture_dir = self.project_root / "audio_captures"
        path = capture_dir / f"capture-{datetime.now().strftime('%Y%m%d-%H%M%S')}.wav"
        track_id = armed[0].track_id
        start_sec = self.audio_cursor_sec
        self.audio_record_stop.clear()
        self.audio_recording = True
        self.audio_status.set(f"recording {device} -> {armed[0].name}")

        def worker() -> None:
            try:
                result = record_wave_input(
                    path,
                    device_name=device,
                    duration_sec=duration,
                    sample_rate=sample_rate,
                    channels=2,
                    bits_per_sample=16,
                    stop_event=self.audio_record_stop,
                    progress=lambda done, total: self.audio_queue.put(
                        ("capture-progress", done, total)
                    ),
                )
                self.audio_queue.put(("capture-complete", result, track_id, start_sec))
            except Exception as exc:
                self.audio_queue.put(("error", "capture", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _audio_stop_record(self) -> None:
        if self.audio_recording:
            self.audio_record_stop.set()
            self.audio_status.set("stopping after current capture buffer")

    def _audio_bounce_ko2(self) -> None:
        if self.audio_recording or self.audio_busy:
            messagebox.showinfo("KO II Audio Studio", "Wait for the current audio operation.")
            return
        if not getattr(self, "live_output_port", None):
            messagebox.showinfo(
                "KO II Audio Studio",
                "Connect EP-133 live before starting a synchronized bounce.",
            )
            return
        arranger_session = getattr(self, "arranger_session", None)
        if arranger_session is None:
            messagebox.showinfo("KO II Audio Studio", "Scene Arranger is not available.")
            return
        armed = [track for track in self.audio_session.project.tracks if track.armed]
        if not armed:
            messagebox.showinfo("KO II Audio Studio", "Arm an audio track first.")
            return
        if not messagebox.askyesno(
            "KO II Synchronized Bounce",
            "Send the current arranger project, MIDI clock, and transport to EP-133 "
            "while recording the selected audio input?",
        ):
            return
        try:
            from ko2_daw.arranger import (
                ArrangerProject,
                RealtimeArrangerEngine,
                compile_arrangement,
            )

            arranger_project = ArrangerProject.from_dict(
                arranger_session.project.to_dict()
            )
            mode = (
                self.arranger_mode.get()
                if hasattr(self, "arranger_mode")
                else "song"
            )
            scene_id = arranger_session.selected_scene_id
            _events, beats = compile_arrangement(
                arranger_project,
                mode=mode,
                scene_id=scene_id,
            )
            music_duration = beats * 60.0 / arranger_project.bpm
            if music_duration <= 0:
                raise ValueError("The arranger project has no playable duration.")
            device = self.audio_input_device.get()
            sample_rate = int(self.audio_record_rate.get())
        except (TypeError, ValueError) as exc:
            messagebox.showerror("KO II Audio Studio", str(exc))
            return
        if hasattr(self, "_arranger_stop"):
            self._arranger_stop(playback_only=True)
        if hasattr(self, "_performance_stop_playback"):
            self._performance_stop_playback()

        pre_roll = 0.15
        tail = 0.35
        capture_duration = music_duration + pre_roll + tail
        capture_dir = self.project_root / "audio_captures"
        path = capture_dir / f"ko2-bounce-{datetime.now().strftime('%Y%m%d-%H%M%S')}.wav"
        track_id = armed[0].track_id
        start_sec = self.audio_cursor_sec
        self.audio_record_stop.clear()
        self.audio_recording = True
        self.audio_status.set(
            f"KO II bounce / {music_duration:.2f}s / {device}"
        )

        def worker() -> None:
            result_box: list[object] = []
            capture_errors: list[Exception] = []

            def capture() -> None:
                try:
                    result_box.append(
                        record_wave_input(
                            path,
                            device_name=device,
                            duration_sec=capture_duration,
                            sample_rate=sample_rate,
                            channels=2,
                            bits_per_sample=16,
                            stop_event=self.audio_record_stop,
                            progress=lambda done, total: self.audio_queue.put(
                                ("bounce-progress", done, total)
                            ),
                        )
                    )
                except Exception as exc:
                    capture_errors.append(exc)

            capture_thread = threading.Thread(target=capture, daemon=True)
            capture_thread.start()
            time.sleep(pre_roll)
            completed = threading.Event()
            arranger_errors: list[Exception] = []
            send = getattr(self, "_arranger_send_engine", self.controller.send)
            engine = RealtimeArrangerEngine(
                send,
                on_error=lambda exc: (arranger_errors.append(exc), completed.set()),
                on_complete=completed.set,
            )
            try:
                engine.start(
                    arranger_project,
                    mode=mode,
                    scene_id=scene_id,
                    loop=False,
                    send_clock=True,
                    send_transport=True,
                )
                deadline = time.monotonic() + music_duration + 3.0
                while not completed.wait(0.02):
                    if self.audio_record_stop.is_set() or time.monotonic() >= deadline:
                        engine.stop()
                        break
                if not self.audio_record_stop.is_set():
                    time.sleep(tail)
                self.audio_record_stop.set()
                capture_thread.join(timeout=3.0)
                if capture_thread.is_alive():
                    raise TimeoutError("Synchronized audio capture did not stop.")
                if arranger_errors:
                    raise arranger_errors[0]
                if capture_errors:
                    raise capture_errors[0]
                if not result_box:
                    raise RuntimeError("Synchronized audio capture produced no result.")
                self.audio_queue.put(
                    (
                        "bounce-complete",
                        result_box[0],
                        track_id,
                        start_sec,
                        pre_roll,
                        music_duration,
                    )
                )
            except Exception as exc:
                self.audio_record_stop.set()
                engine.stop()
                capture_thread.join(timeout=2.0)
                self.audio_queue.put(("error", "KO II bounce", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _audio_preview_mix(self) -> None:
        if self.audio_busy or self.audio_recording:
            messagebox.showinfo("KO II Audio Studio", "Wait for the current audio operation.")
            return
        if not self._audio_apply_project_fields():
            return
        snapshot = AudioProject.from_dict(self.audio_session.project.to_dict())
        path = self.project_root / "audio_previews" / "current_mix.wav"
        self.audio_busy = True
        self.audio_status.set("rendering preview")

        def worker() -> None:
            try:
                result = render_audio_project(snapshot, path)
                self.audio_queue.put(("preview-complete", result))
            except Exception as exc:
                self.audio_queue.put(("error", "preview", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _audio_render_dialog(self) -> None:
        self._show_audio_studio()
        if self.audio_busy or self.audio_recording:
            messagebox.showinfo("KO II Audio Studio", "Wait for the current audio operation.")
            return
        if not self._audio_apply_project_fields():
            return
        path = filedialog.asksaveasfilename(
            title="Render stereo mix",
            initialdir=str(self.project_root),
            defaultextension=".wav",
            filetypes=(("WAV audio", "*.wav"),),
        )
        if not path:
            return
        normalize = messagebox.askyesno(
            "KO II Audio Studio",
            "Peak-normalize the rendered mix to -0.2 dBFS?",
        )
        snapshot = AudioProject.from_dict(self.audio_session.project.to_dict())
        self.audio_busy = True
        self.audio_status.set("rendering mix")

        def worker() -> None:
            try:
                result = render_audio_project(snapshot, path, normalize=normalize)
                self.audio_queue.put(("render-complete", result))
            except Exception as exc:
                self.audio_queue.put(("error", "render", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_audio_queue(self) -> None:
        while True:
            try:
                event = self.audio_queue.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "capture-progress":
                _, done, total = event
                self.audio_status.set(f"recording {float(done):.1f} / {float(total):.1f} sec")
            elif kind == "capture-complete":
                _, result, track_id, start_sec = event
                self.audio_recording = False
                self.audio_record_stop.clear()
                try:
                    clip = self.audio_session.import_wav(
                        result.path,
                        track_id=str(track_id),
                        start_sec=float(start_sec),
                    )
                except Exception as exc:
                    messagebox.showerror("KO II Audio Studio", str(exc))
                else:
                    self.audio_status.set(
                        f"captured {result.duration_sec:.2f}s -> {clip.name}"
                    )
                    self._refresh_audio_studio()
            elif kind == "bounce-progress":
                _, done, total = event
                self.audio_status.set(
                    f"KO II bounce {float(done):.1f} / {float(total):.1f} sec"
                )
            elif kind == "bounce-complete":
                _, result, track_id, start_sec, pre_roll, music_duration = event
                self.audio_recording = False
                self.audio_record_stop.clear()
                try:
                    clip = self.audio_session.import_wav(
                        result.path,
                        track_id=str(track_id),
                        start_sec=float(start_sec),
                    )
                    source_out = min(
                        result.duration_sec,
                        float(pre_roll) + float(music_duration) + 0.25,
                    )
                    self.audio_session.set_clip(
                        clip.clip_id,
                        source_in_sec=min(float(pre_roll), source_out - 0.001),
                        source_out_sec=source_out,
                    )
                except Exception as exc:
                    messagebox.showerror("KO II Audio Studio", str(exc))
                else:
                    self.audio_status.set(
                        f"KO II bounce captured {clip.duration_sec:.2f}s -> {clip.name}"
                    )
                    self._refresh_audio_studio()
            elif kind == "preview-complete":
                result = event[1]
                self.audio_busy = False
                try:
                    play_wav(result.path)
                    self.audio_status.set(
                        f"playing mix / peak {result.peak:.3f}"
                    )
                except Exception as exc:
                    messagebox.showerror("KO II Audio Studio", str(exc))
            elif kind == "render-complete":
                result = event[1]
                self.audio_busy = False
                self.audio_status.set(
                    f"rendered {result.path.name} / peak {result.peak:.3f} / "
                    f"clipped {result.clipped_samples}"
                )
                messagebox.showinfo(
                    "KO II Audio Studio",
                    f"Rendered:\n{result.path}\n\n"
                    f"Duration: {result.duration_sec:.3f} sec\n"
                    f"Peak: {result.peak:.4f}\n"
                    f"Clipped samples: {result.clipped_samples}",
                )
            elif kind == "error":
                _, operation, exc = event
                self.audio_busy = False
                self.audio_recording = False
                self.audio_record_stop.clear()
                self.audio_status.set(f"{operation} failed: {exc}")
                messagebox.showerror("KO II Audio Studio", str(exc))
        if self.root.winfo_exists():
            self.root.after(80, self._poll_audio_queue)

    def _audio_track_selected(self) -> None:
        selection = self.audio_track_tree.selection()
        if not selection:
            return
        try:
            self.audio_session.select(track_id=selection[0])
        except KeyError:
            return
        self._refresh_audio_track_fields()
        self._draw_audio_timeline()

    def _audio_add_track(self) -> None:
        self.audio_session.add_track()
        self._refresh_audio_studio()

    def _audio_remove_track(self) -> None:
        track = self.audio_session.selected_track
        if not messagebox.askyesno(
            "KO II Audio Studio",
            f"Delete {track.name!r} and every clip on it from this project?",
        ):
            return
        try:
            self.audio_session.remove_track(track.track_id)
        except ValueError as exc:
            messagebox.showerror("KO II Audio Studio", str(exc))
        self._refresh_audio_studio()

    def _audio_apply_track(self) -> None:
        try:
            self.audio_session.set_track(
                self.audio_session.selected_track_id,
                name=self.audio_track_name.get(),
                gain_db=float(self.audio_track_gain.get()),
                pan=float(self.audio_track_pan.get()),
                muted=self.audio_track_mute.get(),
                solo=self.audio_track_solo.get(),
                armed=self.audio_track_arm.get(),
            )
        except (TypeError, ValueError) as exc:
            messagebox.showerror("KO II Audio Studio", str(exc))
            return
        self.audio_status.set("track updated")
        self._refresh_audio_studio()

    def _audio_apply_clip(self) -> None:
        clip = self.audio_session.selected_clip
        if clip is None:
            messagebox.showinfo("KO II Audio Studio", "Select an audio clip first.")
            return
        try:
            self.audio_session.set_clip(
                clip.clip_id,
                start_sec=float(self.audio_clip_start.get()),
                source_in_sec=float(self.audio_clip_in.get()),
                source_out_sec=float(self.audio_clip_out.get()),
                stretch=float(self.audio_clip_stretch.get()),
                gain_db=float(self.audio_clip_gain.get()),
                pan=float(self.audio_clip_pan.get()),
                fade_in_sec=float(self.audio_clip_fade_in.get()),
                fade_out_sec=float(self.audio_clip_fade_out.get()),
                reverse=self.audio_clip_reverse.get(),
                muted=self.audio_clip_mute.get(),
            )
        except (TypeError, ValueError) as exc:
            messagebox.showerror("KO II Audio Studio", str(exc))
            return
        self.audio_wave_cache.clear()
        self.audio_status.set("clip updated")
        self._refresh_audio_studio()

    def _audio_split_clip(self) -> None:
        clip = self.audio_session.selected_clip
        if clip is None:
            messagebox.showinfo("KO II Audio Studio", "Select an audio clip first.")
            return
        try:
            self.audio_session.split_clip(clip.clip_id, self.audio_cursor_sec)
        except ValueError as exc:
            messagebox.showerror("KO II Audio Studio", str(exc))
            return
        self.audio_wave_cache.clear()
        self.audio_status.set(f"split at {self.audio_cursor_sec:.3f}s")
        self._refresh_audio_studio()

    def _audio_duplicate_clip(self) -> None:
        clip = self.audio_session.selected_clip
        if clip is None:
            messagebox.showinfo("KO II Audio Studio", "Select an audio clip first.")
            return
        self.audio_session.duplicate_clip(clip.clip_id)
        self.audio_status.set("clip duplicated")
        self._refresh_audio_studio()

    def _audio_delete_clip(self) -> None:
        clip = self.audio_session.selected_clip
        if clip is None:
            return
        self.audio_session.delete_clip(clip.clip_id)
        self.audio_status.set("clip removed; source file preserved")
        self._refresh_audio_studio()

    def _audio_audition_clip(self) -> None:
        clip = self.audio_session.selected_clip
        if clip is None:
            messagebox.showinfo("KO II Audio Studio", "Select an audio clip first.")
            return
        try:
            play_wav(clip.path)
            self.audio_status.set(f"auditioning {clip.name}")
        except Exception as exc:
            messagebox.showerror("KO II Audio Studio", str(exc))

    def _audio_save(self) -> None:
        if not self._audio_apply_project_fields():
            return
        path = filedialog.asksaveasfilename(
            title="Save audio project",
            initialdir=str(self.project_root),
            defaultextension=".json",
            filetypes=(("KO II audio project", "*.json"),),
        )
        if not path:
            return
        try:
            saved = self.audio_session.save(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("KO II Audio Studio", str(exc))
            return
        self.audio_status.set(f"saved {saved.name}")

    def _audio_load(self) -> None:
        path = filedialog.askopenfilename(
            title="Load audio project",
            initialdir=str(self.project_root),
            filetypes=(("KO II audio project", "*.json"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            session = AudioSession.load(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("KO II Audio Studio", str(exc))
            return
        self.audio_session = session
        self.audio_wave_cache.clear()
        self.audio_project_name.set(session.project.name)
        self.bpm.set(session.project.bpm)
        self.audio_sample_rate.set(session.project.sample_rate)
        self.audio_master_gain.set(session.project.master_gain_db)
        self.audio_status.set(f"loaded {len(session.project.clips)} clips")
        self._refresh_audio_studio()

    def _audio_undo(self) -> None:
        if self.audio_session.undo():
            self.audio_wave_cache.clear()
            self.audio_status.set("undo")
            self._refresh_audio_studio()

    def _audio_redo(self) -> None:
        if self.audio_session.redo():
            self.audio_wave_cache.clear()
            self.audio_status.set("redo")
            self._refresh_audio_studio()

    def _audio_apply_project_fields(self) -> bool:
        try:
            project = self.audio_session.project
            project.name = self.audio_project_name.get().strip() or "KO II Audio Project"
            project.bpm = float(self.bpm.get())
            project.sample_rate = int(self.audio_sample_rate.get())
            project.master_gain_db = float(self.audio_master_gain.get())
            project.validate()
        except (TypeError, ValueError) as exc:
            messagebox.showerror("KO II Audio Studio", str(exc))
            return False
        return True

    def _audio_cursor_from_field(self) -> None:
        try:
            value = max(0.0, float(self.audio_cursor_var.get()))
        except ValueError:
            return
        self._set_audio_cursor(value)

    def _set_audio_cursor(self, value: float) -> None:
        if self.audio_snap.get():
            grid = 60.0 / float(self.bpm.get()) / 4.0
            value = round(value / grid) * grid
        self.audio_cursor_sec = max(0.0, value)
        self.audio_cursor_var.set(f"{self.audio_cursor_sec:.3f}")
        self._draw_audio_timeline()

    def _audio_timeline_press(self, event) -> None:
        canvas = self.audio_timeline_canvas
        x = canvas.canvasx(event.x)
        y = canvas.canvasy(event.y)
        overlapping = canvas.find_overlapping(x, y, x, y)
        clip_id = None
        for item in reversed(overlapping):
            tags = canvas.gettags(item)
            tag = next((value for value in tags if value.startswith("clip:")), None)
            if tag:
                clip_id = tag.split(":", 1)[1]
                break
        if clip_id:
            clip = self.audio_session.clip(clip_id)
            self.audio_session.select(clip_id=clip_id)
            self.audio_drag = {
                "clip_id": clip_id,
                "offset": x - self._audio_time_x(clip.start_sec),
                "target_start": clip.start_sec,
                "target_track": clip.track_id,
            }
            self._refresh_audio_clip_fields()
            self._draw_audio_timeline()
            return
        self.audio_drag = None
        self._set_audio_cursor(self._audio_x_time(x))

    def _audio_timeline_drag(self, event) -> None:
        if not self.audio_drag:
            return
        canvas = self.audio_timeline_canvas
        x = canvas.canvasx(event.x) - float(self.audio_drag["offset"])
        y = canvas.canvasy(event.y)
        start = max(0.0, self._audio_x_time(x))
        if self.audio_snap.get():
            grid = 60.0 / float(self.bpm.get()) / 4.0
            start = round(start / grid) * grid
        track_index = max(0, min(len(self.audio_session.project.tracks) - 1, int((y - 34) // 86)))
        track_id = self.audio_session.project.tracks[track_index].track_id
        self.audio_drag["target_start"] = start
        self.audio_drag["target_track"] = track_id
        self.audio_status.set(f"move -> {start:.3f}s / {self.audio_session.track(track_id).name}")

    def _audio_timeline_release(self, _event) -> None:
        if not self.audio_drag:
            return
        try:
            self.audio_session.set_clip(
                str(self.audio_drag["clip_id"]),
                start_sec=float(self.audio_drag["target_start"]),
                track_id=str(self.audio_drag["target_track"]),
            )
        except ValueError as exc:
            messagebox.showerror("KO II Audio Studio", str(exc))
        self.audio_drag = None
        self.audio_status.set("clip moved")
        self._refresh_audio_studio()

    def _refresh_audio_studio(self) -> None:
        if not self.audio_window or not self.audio_window.winfo_exists():
            return
        tree = self.audio_track_tree
        selected = self.audio_session.selected_track_id
        for item in tree.get_children():
            tree.delete(item)
        for track in self.audio_session.project.tracks:
            tree.insert(
                "",
                tk.END,
                iid=track.track_id,
                text=track.name,
                values=(
                    "M" if track.muted else "",
                    "S" if track.solo else "",
                    "R" if track.armed else "",
                    f"{track.gain_db:g}",
                    f"{track.pan:+.2f}",
                ),
            )
        if tree.exists(selected):
            tree.selection_set(selected)
            tree.see(selected)
        self.audio_summary.set(
            f"{len(self.audio_session.project.tracks)} TRACKS  /  "
            f"{len(self.audio_session.project.clips)} CLIPS  /  "
            f"{self.audio_session.project.duration_sec:.2f} SEC"
        )
        self._refresh_audio_track_fields()
        self._refresh_audio_clip_fields()
        self._draw_audio_timeline()

    def _refresh_audio_track_fields(self) -> None:
        track = self.audio_session.selected_track
        self.audio_track_name.set(track.name)
        self.audio_track_gain.set(track.gain_db)
        self.audio_track_pan.set(track.pan)
        self.audio_track_mute.set(track.muted)
        self.audio_track_solo.set(track.solo)
        self.audio_track_arm.set(track.armed)

    def _refresh_audio_clip_fields(self) -> None:
        clip = self.audio_session.selected_clip
        if clip is None:
            self.audio_source_info.set("No clip selected")
            self._draw_audio_source_detail()
            return
        self.audio_clip_start.set(clip.start_sec)
        self.audio_clip_in.set(clip.source_in_sec)
        self.audio_clip_out.set(clip.source_out_sec)
        self.audio_clip_stretch.set(clip.stretch)
        self.audio_clip_gain.set(clip.gain_db)
        self.audio_clip_pan.set(clip.pan)
        self.audio_clip_fade_in.set(clip.fade_in_sec)
        self.audio_clip_fade_out.set(clip.fade_out_sec)
        self.audio_clip_reverse.set(clip.reverse)
        self.audio_clip_mute.set(clip.muted)
        try:
            source = read_wave_source(clip.path)
            self.audio_source_info.set(
                f"{source.sample_rate:,} Hz  /  {source.channels} ch  /  "
                f"{source.sample_width * 8}-bit\n"
                f"source {clip.source_in_sec:.3f}-{clip.source_out_sec:.3f}s  /  "
                f"timeline {clip.duration_sec:.3f}s\n{clip.path}"
            )
        except (OSError, ValueError) as exc:
            self.audio_source_info.set(str(exc))
        self._draw_audio_source_detail()

    def _draw_audio_source_detail(self) -> None:
        canvas = getattr(self, "audio_source_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        width = max(80, canvas.winfo_width())
        height = max(80, canvas.winfo_height())
        center = height / 2
        canvas.create_line(0, center, width, center, fill="#4b5044")
        clip = self.audio_session.selected_clip
        if clip is None:
            canvas.create_text(
                width / 2,
                center,
                text="SELECT A CLIP",
                fill="#d7f58a",
                font=("Consolas", 10, "bold"),
            )
            return
        key = (
            "detail",
            clip.path,
            clip.source_in_sec,
            clip.source_out_sec,
            clip.reverse,
            max(32, width // 2),
        )
        try:
            peaks = self.audio_wave_cache.get(key)
            if peaks is None:
                peaks = waveform_peaks(clip, points=max(32, width // 2))
                self.audio_wave_cache[key] = peaks
        except (OSError, ValueError):
            peaks = []
        if peaks:
            x_step = width / max(1, len(peaks) - 1)
            for index, (minimum, maximum) in enumerate(peaks):
                x = index * x_step
                canvas.create_line(
                    x,
                    center + minimum * height * 0.43,
                    x,
                    center + maximum * height * 0.43,
                    fill="#d7f58a",
                )
        if clip.fade_in_sec > 0 and clip.duration_sec > 0:
            x = width * clip.fade_in_sec / clip.duration_sec
            canvas.create_line(0, height, x, 0, fill="#dc493a", width=2)
        if clip.fade_out_sec > 0 and clip.duration_sec > 0:
            x = width * (1 - clip.fade_out_sec / clip.duration_sec)
            canvas.create_line(x, 0, width, height, fill="#dc493a", width=2)

    def _draw_audio_timeline(self) -> None:
        canvas = getattr(self, "audio_timeline_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        self.audio_clip_items.clear()
        label_width = 140
        ruler_height = 34
        track_height = 86
        pixels_per_sec = float(self.audio_zoom.get())
        visible_width = max(600, canvas.winfo_width())
        duration = max(30.0, self.audio_session.project.duration_sec + 5.0)
        width = max(visible_width, label_width + duration * pixels_per_sec)
        height = ruler_height + len(self.audio_session.project.tracks) * track_height
        canvas.configure(scrollregion=(0, 0, width, height))
        beat = 60.0 / float(self.bpm.get())
        grid = beat / 4.0
        grid_index = 0
        position = 0.0
        while position <= duration + 1e-9:
            x = label_width + position * pixels_per_sec
            strong = grid_index % 4 == 0
            canvas.create_line(
                x,
                ruler_height if strong else ruler_height + 8,
                x,
                height,
                fill="#4b5044" if strong else "#272a24",
            )
            if strong:
                canvas.create_text(
                    x + 3,
                    16,
                    text=f"{position:.1f}",
                    fill="#f3f1de",
                    anchor="w",
                    font=("Consolas", 8),
                )
            grid_index += 1
            position = grid_index * grid
        for index, track in enumerate(self.audio_session.project.tracks):
            y0 = ruler_height + index * track_height
            selected_track = track.track_id == self.audio_session.selected_track_id
            canvas.create_rectangle(
                0,
                y0,
                width,
                y0 + track_height - 1,
                fill="#1c1f1a" if index % 2 == 0 else "#22251f",
                outline="#11120f",
            )
            canvas.create_rectangle(
                0,
                y0,
                label_width - 1,
                y0 + track_height - 1,
                fill=track.color if selected_track else "#bdb7aa",
                outline="#11120f",
            )
            canvas.create_text(
                8,
                y0 + 20,
                text=track.name,
                fill="#171915",
                anchor="w",
                font=("Consolas", 10, "bold"),
            )
            canvas.create_text(
                8,
                y0 + 46,
                text=(
                    f"{'M ' if track.muted else ''}{'S ' if track.solo else ''}"
                    f"{'R ' if track.armed else ''}{track.gain_db:+g}dB  {track.pan:+.2f}"
                ),
                fill="#171915",
                anchor="w",
                font=("Consolas", 8),
            )
        for clip in self.audio_session.project.clips:
            track_index = next(
                index
                for index, track in enumerate(self.audio_session.project.tracks)
                if track.track_id == clip.track_id
            )
            y0 = ruler_height + track_index * track_height + 7
            y1 = y0 + track_height - 15
            x0 = label_width + clip.start_sec * pixels_per_sec
            x1 = label_width + clip.end_sec * pixels_per_sec
            selected = clip.clip_id == self.audio_session.selected_clip_id
            track = self.audio_session.track(clip.track_id)
            fill = "#5a5d52" if clip.muted else track.color
            tag = f"clip:{clip.clip_id}"
            rectangle = canvas.create_rectangle(
                x0,
                y0,
                max(x0 + 8, x1),
                y1,
                fill=fill,
                outline="#f3f1de" if selected else "#11120f",
                width=2 if selected else 1,
                tags=(tag,),
            )
            self.audio_clip_items[rectangle] = clip.clip_id
            points = max(8, min(500, round(max(8, x1 - x0) / 3)))
            key = (
                clip.path,
                clip.source_in_sec,
                clip.source_out_sec,
                clip.reverse,
                points,
            )
            try:
                peaks = self.audio_wave_cache.get(key)
                if peaks is None:
                    peaks = waveform_peaks(clip, points=points)
                    self.audio_wave_cache[key] = peaks
            except (OSError, ValueError):
                peaks = []
            center = (y0 + y1) / 2
            amplitude = (y1 - y0) * 0.38
            if peaks:
                x_step = max(1.0, (x1 - x0) / len(peaks))
                for peak_index, (minimum, maximum) in enumerate(peaks):
                    x = x0 + peak_index * x_step
                    canvas.create_line(
                        x,
                        center + minimum * amplitude,
                        x,
                        center + maximum * amplitude,
                        fill="#171915",
                        tags=(tag,),
                    )
            canvas.create_text(
                x0 + 5,
                y0 + 10,
                text=f"{clip.name}  {clip.duration_sec:.2f}s",
                fill="#171915",
                anchor="w",
                font=("Consolas", 8, "bold"),
                tags=(tag,),
            )
            if clip.fade_in_sec > 0:
                fade_x = x0 + clip.fade_in_sec * pixels_per_sec
                canvas.create_line(x0, y1, fade_x, y0, fill="#f3f1de", tags=(tag,))
            if clip.fade_out_sec > 0:
                fade_x = x1 - clip.fade_out_sec * pixels_per_sec
                canvas.create_line(fade_x, y0, x1, y1, fill="#f3f1de", tags=(tag,))
        cursor_x = label_width + self.audio_cursor_sec * pixels_per_sec
        canvas.create_line(
            cursor_x,
            0,
            cursor_x,
            height,
            fill="#dc493a",
            width=2,
            tags=("cursor",),
        )

    def _audio_time_x(self, seconds: float) -> float:
        return 140 + seconds * float(self.audio_zoom.get())

    def _audio_x_time(self, x: float) -> float:
        return max(0.0, (x - 140) / float(self.audio_zoom.get()))

    def _show_audio_help(self) -> None:
        messagebox.showinfo(
            "KO II Audio Studio Guide",
            "\n".join(
                [
                    "IMPORT places a PCM WAV on the selected track at the red edit cursor.",
                    "DEVICE WAV opens the immutable EP-133 download library for local audio use.",
                    "Click empty timeline space to set the cursor; drag clips in time or between tracks.",
                    "SPLIT cuts the selected clip at the cursor without altering its source file.",
                    "Clip edits include source trim, stretch, reverse, gain, pan, fades, and mute.",
                    "Track edits include gain, pan, mute, solo, and record arm.",
                    "REC captures a visible Windows input, normally QUAD-CAPTURE MAIN or 1-2.",
                    "STOP REC finishes after the current WinMM buffer and imports the local WAV.",
                    "PLAY MIX renders the current project to a temporary WAV before local playback.",
                    "RENDER creates a stereo 16-bit WAV and can peak-normalize to -0.2 dBFS.",
                    "SAVE stores only non-destructive project instructions and source paths.",
                    "",
                    "Audio capture and editing are PC-side. They never upload, delete, move, or",
                    "rewrite EP-133 files. Downloaded device assets remain content-addressed.",
                ]
            ),
        )

    def _close(self) -> None:
        self.audio_record_stop.set()
        stop_wav()
        original_close(self)

    app_class.__init__ = __init__
    app_class._build_menu = _build_menu
    app_class._show_audio_studio = _show_audio_studio
    app_class._build_audio_tracks = _build_audio_tracks
    app_class._build_audio_timeline = _build_audio_timeline
    app_class._build_audio_inspector = _build_audio_inspector
    app_class._audio_import = _audio_import
    app_class._audio_import_device_wav = _audio_import_device_wav
    app_class._audio_record = _audio_record
    app_class._audio_stop_record = _audio_stop_record
    app_class._audio_bounce_ko2 = _audio_bounce_ko2
    app_class._audio_preview_mix = _audio_preview_mix
    app_class._audio_render_dialog = _audio_render_dialog
    app_class._poll_audio_queue = _poll_audio_queue
    app_class._audio_track_selected = _audio_track_selected
    app_class._audio_add_track = _audio_add_track
    app_class._audio_remove_track = _audio_remove_track
    app_class._audio_apply_track = _audio_apply_track
    app_class._audio_apply_clip = _audio_apply_clip
    app_class._audio_split_clip = _audio_split_clip
    app_class._audio_duplicate_clip = _audio_duplicate_clip
    app_class._audio_delete_clip = _audio_delete_clip
    app_class._audio_audition_clip = _audio_audition_clip
    app_class._audio_save = _audio_save
    app_class._audio_load = _audio_load
    app_class._audio_undo = _audio_undo
    app_class._audio_redo = _audio_redo
    app_class._audio_apply_project_fields = _audio_apply_project_fields
    app_class._audio_cursor_from_field = _audio_cursor_from_field
    app_class._set_audio_cursor = _set_audio_cursor
    app_class._audio_timeline_press = _audio_timeline_press
    app_class._audio_timeline_drag = _audio_timeline_drag
    app_class._audio_timeline_release = _audio_timeline_release
    app_class._refresh_audio_studio = _refresh_audio_studio
    app_class._refresh_audio_track_fields = _refresh_audio_track_fields
    app_class._refresh_audio_clip_fields = _refresh_audio_clip_fields
    app_class._draw_audio_source_detail = _draw_audio_source_detail
    app_class._draw_audio_timeline = _draw_audio_timeline
    app_class._audio_time_x = _audio_time_x
    app_class._audio_x_time = _audio_x_time
    app_class._show_audio_help = _show_audio_help
    app_class._close = _close
    app_class._audio_studio_patch_installed = True


def _find_menu(menu, label: str):
    end = menu.index("end")
    if end is None:
        return None
    for index in range(end + 1):
        try:
            if menu.entrycget(index, "label") == label:
                child = menu.entrycget(index, "menu")
                return menu.nametowidget(child) if child else None
        except Exception:
            continue
    return None


def _label(parent, text: str, tk):
    return tk.Label(
        parent,
        text=text,
        bg=parent.cget("bg"),
        fg="#171915",
        font=("Consolas", 9, "bold"),
    )


def _dark_label(parent, text: str, tk):
    return tk.Label(
        parent,
        text=text,
        bg="#171915",
        fg="#d7f58a",
        font=("Consolas", 9, "bold"),
    )


def _clip_field_tip(name: str) -> str:
    return {
        "START": "Timeline position in seconds.",
        "SOURCE IN": "Non-destructive trim from the start of the source WAV.",
        "SOURCE OUT": "Non-destructive trim endpoint in the source WAV.",
        "STRETCH": "Playback duration multiplier from 0.125x to 8x with linear resampling.",
        "GAIN dB": "Clip gain before track and master gain.",
        "PAN": "Clip stereo position from -1 left to +1 right.",
        "FADE IN": "Linear fade-in duration in timeline seconds.",
        "FADE OUT": "Linear fade-out duration in timeline seconds.",
    }[name]
