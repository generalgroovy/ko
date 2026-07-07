"""Stable GUI integration for MIDI performance recording and looping."""

from __future__ import annotations

from time import monotonic
from typing import Any

from ko2_daw.midi import MidiMessage
from ko2_daw.performance import PerformanceClip, PerformanceRecorder


def apply_performance_patch(gui_module: Any) -> None:
    """Add a non-destructive performance recorder to the stable GUI."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_performance_patch_installed", False):
        return

    tk = gui_module.tk
    ttk = gui_module.ttk
    filedialog = gui_module.filedialog
    messagebox = gui_module.messagebox
    original_init = app_class.__init__
    original_build_menu = app_class._build_menu
    original_send_midi = app_class._send_midi
    original_queue_midi_input = app_class._queue_midi_input
    original_record = app_class._record
    original_stop = app_class._stop
    original_close = app_class._close

    def __init__(self, root) -> None:
        self.performance_recorder = PerformanceRecorder(PerformanceClip())
        self.performance_playing = False
        self.performance_play_index = 0
        self.performance_play_started = 0.0
        self.performance_active_notes: set[tuple[int, int]] = set()
        self.performance_window = None
        original_init(self, root)
        self.performance_status = tk.StringVar(value="ready")

    def _build_menu(self) -> None:
        original_build_menu(self)
        menu = self.root.nametowidget(self.root.cget("menu"))
        daw_menu = tk.Menu(menu, tearoff=False)
        daw_menu.add_command(label="Performance Recorder", command=self._show_performance_window)
        daw_menu.add_command(label="Record New Clip", command=lambda: self._performance_start(False))
        daw_menu.add_command(label="Overdub Clip", command=lambda: self._performance_start(True))
        daw_menu.add_command(label="Stop Recording / Playback", command=self._performance_stop)
        menu.add_cascade(label="DAW", menu=daw_menu)

    def _send_midi(self, message: MidiMessage) -> bool:
        sent = original_send_midi(self, message)
        if sent:
            self.performance_recorder.record(message, "app")
            self._refresh_performance_view()
        return sent

    def _queue_midi_input(self, message: MidiMessage) -> None:
        self.performance_recorder.record(message, "device")
        original_queue_midi_input(self, message)
        self.root.after(0, self._refresh_performance_view)

    def _record(self) -> None:
        self._show_performance_window()
        self._performance_start(False)

    def _stop(self) -> None:
        original_stop(self)
        self._performance_stop()

    def _show_performance_window(self) -> None:
        if self.performance_window and self.performance_window.winfo_exists():
            self.performance_window.lift()
            return

        win = tk.Toplevel(self.root)
        win.title("KO II Performance Recorder")
        win.geometry("920x620")
        win.minsize(780, 500)
        win.configure(bg="#171915")
        self.performance_window = win
        self.performance_name = tk.StringVar(value=self.performance_recorder.clip.name)
        self.performance_loop_beats = tk.StringVar(value=str(self.performance_recorder.clip.loop_beats))
        self.performance_grid = tk.StringVar(value="1/16")
        self.performance_strength = tk.DoubleVar(value=100)
        self.performance_loop = tk.BooleanVar(value=True)

        header = tk.Frame(win, bg="#171915", padx=10, pady=8)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="PERFORMANCE RECORDER",
            bg="#171915",
            fg="#d7f58a",
            font=("Consolas", 18, "bold"),
        ).pack(side=tk.LEFT)
        tk.Label(
            header,
            textvariable=self.performance_status,
            bg="#171915",
            fg="#f3f1de",
            font=("Consolas", 11),
        ).pack(side=tk.RIGHT)

        controls = tk.Frame(win, bg="#d8d4c8", padx=8, pady=8)
        controls.pack(fill=tk.X, padx=10)
        tk.Label(controls, text="Clip", bg="#d8d4c8").grid(row=0, column=0, sticky="w")
        tk.Entry(controls, textvariable=self.performance_name, width=24).grid(row=0, column=1, sticky="ew", padx=(4, 10))
        tk.Label(controls, text="Loop beats", bg="#d8d4c8").grid(row=0, column=2, sticky="w")
        tk.Entry(controls, textvariable=self.performance_loop_beats, width=8).grid(row=0, column=3, padx=(4, 10))
        tk.Label(controls, text="Grid", bg="#d8d4c8").grid(row=0, column=4, sticky="w")
        ttk.Combobox(
            controls,
            textvariable=self.performance_grid,
            values=("1/4", "1/8", "1/16", "1/32", "1/64"),
            state="readonly",
            width=7,
        ).grid(row=0, column=5, padx=(4, 10))
        tk.Checkbutton(controls, text="Loop playback", variable=self.performance_loop, bg="#d8d4c8").grid(
            row=0, column=6, sticky="w"
        )
        controls.columnconfigure(1, weight=1)

        tk.Label(controls, text="Quantize strength", bg="#d8d4c8").grid(row=1, column=0, sticky="w", pady=(6, 0))
        tk.Scale(
            controls,
            variable=self.performance_strength,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            bg="#d8d4c8",
            length=220,
        ).grid(row=1, column=1, columnspan=2, sticky="w", pady=(6, 0))

        actions = tk.Frame(win, bg="#d8d4c8", padx=8, pady=8)
        actions.pack(fill=tk.X, padx=10, pady=(6, 0))
        action_specs = (
            ("RECORD", lambda: self._performance_start(False), "#dc493a"),
            ("OVERDUB", lambda: self._performance_start(True), "#f2c230"),
            ("STOP", self._performance_stop, "#efeadf"),
            ("PLAY", self._performance_play, "#88b04b"),
            ("QUANTIZE", self._performance_quantize, "#efeadf"),
            ("UNDO", self._performance_undo, "#efeadf"),
            ("REDO", self._performance_redo, "#efeadf"),
            ("SAVE", self._performance_save, "#efeadf"),
            ("LOAD", self._performance_load, "#efeadf"),
            ("EXPORT MIDI", self._performance_export_midi, "#efeadf"),
            ("CLEAR", self._performance_clear, "#efeadf"),
        )
        for text, command, color in action_specs:
            tk.Button(actions, text=text, command=command, bg=color).pack(side=tk.LEFT, padx=2)

        table = tk.Frame(win, bg="#171915", padx=10, pady=10)
        table.pack(fill=tk.BOTH, expand=True)
        columns = ("beat", "source", "kind", "details")
        self.performance_tree = ttk.Treeview(table, columns=columns, show="headings")
        widths = {"beat": 90, "source": 90, "kind": 140, "details": 520}
        for column in columns:
            self.performance_tree.heading(column, text=column.title())
            self.performance_tree.column(column, width=widths[column], anchor="w")
        scrollbar = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self.performance_tree.yview)
        self.performance_tree.configure(yscrollcommand=scrollbar.set)
        self.performance_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._refresh_performance_view()

    def _performance_apply_fields(self) -> bool:
        try:
            self.performance_recorder.clip.name = self.performance_name.get().strip() or "EP-133 Performance"
            self.performance_recorder.clip.bpm = float(self.bpm.get())
            self.performance_recorder.set_loop_beats(float(self.performance_loop_beats.get()))
            return True
        except (TypeError, ValueError) as exc:
            messagebox.showerror("KO II Performance", str(exc))
            return False

    def _performance_start(self, overdub: bool) -> None:
        self._show_performance_window()
        if not self._performance_apply_fields():
            return
        self._performance_stop_playback()
        self.performance_recorder.start(bpm=float(self.bpm.get()), overdub=overdub)
        mode = "overdub" if overdub else "record"
        self.performance_status.set(f"{mode} armed at {self.performance_recorder.clip.bpm:g} BPM")
        self._set_action(f"performance {mode}")
        self._refresh_performance_view()

    def _performance_stop(self) -> None:
        was_recording = self.performance_recorder.recording
        self.performance_recorder.stop()
        self._performance_stop_playback()
        self.performance_status.set(
            f"stopped | {len(self.performance_recorder.clip.events)} events"
        )
        if was_recording:
            self._set_action("performance recording stopped")
        self._refresh_performance_view()

    def _performance_play(self) -> None:
        self._show_performance_window()
        if not self._performance_apply_fields():
            return
        events = self.performance_recorder.playback_events()
        if not events:
            messagebox.showinfo("KO II Performance", "Record or load a performance first.")
            return
        self.performance_recorder.stop()
        self._performance_stop_playback()
        self.performance_playing = True
        self.performance_play_index = 0
        self.performance_play_started = monotonic()
        self.performance_status.set("playing")
        self._set_action("performance playback")
        self.root.after(1, self._performance_tick)

    def _performance_tick(self) -> None:
        if not self.performance_playing:
            return
        events = self.performance_recorder.playback_events()
        elapsed = monotonic() - self.performance_play_started
        while self.performance_play_index < len(events) and events[self.performance_play_index][0] <= elapsed:
            _, message = events[self.performance_play_index]
            self._send_midi(message)
            _track_active_note(self.performance_active_notes, message)
            self.performance_play_index += 1
        if self.performance_play_index >= len(events):
            loop_seconds = self.performance_recorder.clip.loop_beats * 60.0 / self.performance_recorder.clip.bpm
            if self.performance_loop.get() and loop_seconds > 0:
                if elapsed >= loop_seconds:
                    self.performance_play_index = 0
                    self.performance_play_started += loop_seconds
            else:
                self._performance_stop_playback()
                self.performance_status.set("playback complete")
                return
        self.root.after(5, self._performance_tick)

    def _performance_stop_playback(self) -> None:
        self.performance_playing = False
        for channel, note in list(self.performance_active_notes):
            original_send_midi(self, MidiMessage.note_off(note, channel=channel))
        self.performance_active_notes.clear()

    def _performance_quantize(self) -> None:
        division = int(self.performance_grid.get().split("/")[-1])
        try:
            self.performance_recorder.quantize(
                division,
                strength=float(self.performance_strength.get()) / 100.0,
            )
        except ValueError as exc:
            messagebox.showerror("KO II Performance", str(exc))
            return
        self.performance_status.set(f"quantized {self.performance_grid.get()}")
        self._refresh_performance_view()

    def _performance_undo(self) -> None:
        if self.performance_recorder.undo():
            self.performance_status.set("undo")
            self._refresh_performance_view()

    def _performance_redo(self) -> None:
        if self.performance_recorder.redo():
            self.performance_status.set("redo")
            self._refresh_performance_view()

    def _performance_clear(self) -> None:
        if not messagebox.askyesno("KO II Performance", "Clear the current in-memory performance clip?"):
            return
        self.performance_recorder.clear()
        self.performance_status.set("clip cleared")
        self._refresh_performance_view()

    def _performance_save(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Save performance clip",
            defaultextension=".json",
            filetypes=(("KO II performance", "*.json"),),
            initialdir=str(self.project_root),
        )
        if not path:
            return
        if not self._performance_apply_fields():
            return
        saved = self.performance_recorder.save(path)
        self.performance_status.set(f"saved {saved.name}")

    def _performance_load(self) -> None:
        path = filedialog.askopenfilename(
            title="Load performance clip",
            filetypes=(("KO II performance", "*.json"), ("All files", "*.*")),
            initialdir=str(self.project_root),
        )
        if not path:
            return
        try:
            self.performance_recorder = PerformanceRecorder.load(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("KO II Performance", str(exc))
            return
        self.performance_name.set(self.performance_recorder.clip.name)
        self.performance_loop_beats.set(str(self.performance_recorder.clip.loop_beats))
        self.bpm.set(self.performance_recorder.clip.bpm)
        self.performance_status.set(f"loaded {len(self.performance_recorder.clip.events)} events")
        self._refresh_performance_view()

    def _performance_export_midi(self) -> None:
        path = filedialog.asksaveasfilename(
            title="Export Standard MIDI File",
            defaultextension=".mid",
            filetypes=(("MIDI file", "*.mid"),),
            initialdir=str(self.project_root),
        )
        if not path:
            return
        try:
            exported = self.performance_recorder.export_midi(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("KO II Performance", str(exc))
            return
        self.performance_status.set(f"exported {exported.name}")

    def _refresh_performance_view(self) -> None:
        tree = getattr(self, "performance_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        for item in tree.get_children():
            tree.delete(item)
        for index, event in enumerate(sorted(self.performance_recorder.clip.events, key=lambda item: item.beat)):
            message = event.message
            details = " ".join(
                f"{key}={value}"
                for key, value in message.items()
                if key not in {"kind", "data"} and value is not None
            )
            tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(f"{event.beat:.3f}", event.source, message.get("kind", ""), details),
            )
        if self.performance_recorder.recording:
            mode = "overdub" if self.performance_recorder.overdub else "recording"
            self.performance_status.set(f"{mode} | {len(self.performance_recorder.clip.events)} events")

    def _close(self) -> None:
        self._performance_stop_playback()
        original_close(self)

    app_class.__init__ = __init__
    app_class._build_menu = _build_menu
    app_class._send_midi = _send_midi
    app_class._queue_midi_input = _queue_midi_input
    app_class._record = _record
    app_class._stop = _stop
    app_class._show_performance_window = _show_performance_window
    app_class._performance_apply_fields = _performance_apply_fields
    app_class._performance_start = _performance_start
    app_class._performance_stop = _performance_stop
    app_class._performance_play = _performance_play
    app_class._performance_tick = _performance_tick
    app_class._performance_stop_playback = _performance_stop_playback
    app_class._performance_quantize = _performance_quantize
    app_class._performance_undo = _performance_undo
    app_class._performance_redo = _performance_redo
    app_class._performance_clear = _performance_clear
    app_class._performance_save = _performance_save
    app_class._performance_load = _performance_load
    app_class._performance_export_midi = _performance_export_midi
    app_class._refresh_performance_view = _refresh_performance_view
    app_class._close = _close
    app_class._performance_patch_installed = True


def _track_active_note(active_notes: set[tuple[int, int]], message: MidiMessage) -> None:
    if message.note is None:
        return
    key = (int(message.channel or 0), int(message.note))
    if message.kind == "note_on" and int(message.velocity or 0) > 0:
        active_notes.add(key)
    elif message.kind in {"note_off", "note_on"}:
        active_notes.discard(key)
