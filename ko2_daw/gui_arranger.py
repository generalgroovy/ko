"""Stable KO II-style scene arranger GUI."""

from __future__ import annotations

import queue
from typing import Any

from ko2_daw.arranger import (
    GROUP_BASE_NOTES,
    GROUPS,
    ArrangerCapture,
    ArrangerClockFollower,
    ArrangerProject,
    ArrangerSession,
    RealtimeArrangerEngine,
    default_arranger_project,
)
from ko2_daw.midi import MidiMessage


GROUP_COLORS = {
    "A": "#f2c230",
    "B": "#e36a45",
    "C": "#65a6a6",
    "D": "#8fac56",
}


def apply_arranger_patch(gui_module: Any) -> None:
    """Install the multitrack scene arranger into the stable desktop app."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_arranger_patch_installed", False):
        return

    tk = gui_module.tk
    ttk = gui_module.ttk
    filedialog = gui_module.filedialog
    messagebox = gui_module.messagebox
    original_init = app_class.__init__
    original_build_menu = app_class._build_menu
    original_send_midi = app_class._send_midi
    original_queue_midi_input = app_class._queue_midi_input
    original_stop = app_class._stop
    original_close = app_class._close

    def __init__(self, root) -> None:
        self.arranger_session = ArrangerSession(default_arranger_project())
        self.arranger_capture = ArrangerCapture(self.arranger_session)
        self.arranger_window = None
        self.arranger_queue: queue.Queue[tuple[object, ...]] = queue.Queue()
        self.arranger_follower = None
        self.arranger_follow_active_notes: set[tuple[int, int]] = set()
        self.arranger_scene_buttons = {}
        self.arranger_track_vars = {}
        self.arranger_engine = None
        original_init(self, root)
        self.arranger_status = tk.StringVar(value="arranger ready")
        self.arranger_engine = RealtimeArrangerEngine(
            self._arranger_send_engine,
            on_position=lambda beat, length, cycle: self.arranger_queue.put(
                ("position", beat, length, cycle)
            ),
            on_error=lambda exc: self.arranger_queue.put(("error", exc)),
            on_complete=lambda: self.arranger_queue.put(("complete",)),
        )
        self.root.after(40, self._poll_arranger_queue)

    def _build_menu(self) -> None:
        original_build_menu(self)
        menu = self.root.nametowidget(self.root.cget("menu"))
        daw_menu = _find_menu(menu, "DAW")
        if daw_menu is None:
            daw_menu = tk.Menu(menu, tearoff=False)
            menu.add_cascade(label="DAW", menu=daw_menu)
        daw_menu.insert_command(
            0,
            label="Scene Arranger",
            command=self._show_arranger_window,
        )
        daw_menu.insert_command(
            1,
            label="Play Arrangement",
            command=self._arranger_play,
        )
        daw_menu.insert_command(
            2,
            label="Stop Arrangement",
            command=self._arranger_stop,
        )
        daw_menu.insert_separator(3)
        help_menu = _find_menu(menu, "Help")
        if help_menu is not None:
            help_menu.add_command(label="Scene Arranger Guide", command=self._show_arranger_help)

    def _send_midi(self, message: MidiMessage) -> bool:
        sent = original_send_midi(self, message)
        if sent:
            self.arranger_capture.record(message)
        return sent

    def _queue_midi_input(self, message: MidiMessage) -> None:
        self.arranger_capture.record(message)
        follower = self.arranger_follower
        if follower is not None:
            try:
                for outgoing in follower.observe(message):
                    self._arranger_send_engine(outgoing)
                    _track_note(self.arranger_follow_active_notes, outgoing)
                if message.kind == "stop":
                    self._arranger_release_follow_notes()
                    self.arranger_queue.put(("follow-stopped",))
            except Exception as exc:
                self.arranger_queue.put(("error", exc))
        original_queue_midi_input(self, message)

    def _stop(self) -> None:
        self._arranger_stop()
        original_stop(self)

    def _show_arranger_window(self) -> None:
        if self.arranger_window and self.arranger_window.winfo_exists():
            self.arranger_window.lift()
            self._refresh_arranger()
            return

        win = tk.Toplevel(self.root)
        win.title("KO II Scene Arranger")
        win.geometry("1380x790")
        win.minsize(1120, 680)
        win.configure(bg="#d8d4c8")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(2, weight=1)
        self.arranger_window = win

        self.arranger_project_name = tk.StringVar(value=self.arranger_session.project.name)
        self.arranger_mode = tk.StringVar(value="scene")
        self.arranger_sync = tk.StringVar(value="master")
        self.arranger_loop = tk.BooleanVar(value=True)
        self.arranger_steps = tk.IntVar(value=16)
        self.arranger_step_velocity = tk.IntVar(value=96)
        self.arranger_probability = tk.IntVar(value=100)
        self.arranger_duration = tk.DoubleVar(value=0.9)
        self.arranger_swing = tk.DoubleVar(value=self.arranger_session.project.swing_percent)
        self.arranger_song_repeats = tk.IntVar(value=1)
        self.arranger_cc_step = tk.IntVar(value=1)
        self.arranger_cc_number = tk.IntVar(value=1)
        self.arranger_cc_value = tk.IntVar(value=64)

        header = tk.Frame(win, bg="#171915", padx=10, pady=8)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        title = tk.Label(
            header,
            text="KO II  /  SCENE ARRANGER",
            bg="#171915",
            fg="#ff4b0b",
            font=("Consolas", 18, "bold"),
        )
        title.grid(row=0, column=0, sticky="w")
        name = tk.Entry(
            header,
            textvariable=self.arranger_project_name,
            bg="#252820",
            fg="#f3f1de",
            insertbackground="#f3f1de",
            relief=tk.FLAT,
            font=("Consolas", 11),
        )
        name.grid(row=0, column=1, sticky="ew", padx=14)
        status = tk.Label(
            header,
            textvariable=self.arranger_status,
            bg="#ff4b0b",
            fg="#171915",
            padx=10,
            pady=3,
            font=("Consolas", 10, "bold"),
        )
        status.grid(row=0, column=2, sticky="e")
        self._tip(title, "Four-group MIDI arranger mapped directly to KO II pad notes A 36-47, B 48-59, C 60-71, and D 72-83.")
        self._tip(name, "Arrangement name stored in the non-destructive JSON project.")
        self._tip(status, "Playback, recording, synchronization, and edit status.")

        toolbar = tk.Frame(win, bg="#bdb7aa", padx=8, pady=6)
        toolbar.grid(row=1, column=0, sticky="ew")
        _label(toolbar, "BPM", tk).pack(side=tk.LEFT)
        bpm_entry = tk.Spinbox(toolbar, textvariable=self.bpm, from_=20, to=300, width=6)
        bpm_entry.pack(side=tk.LEFT, padx=(3, 10))
        _label(toolbar, "SWING", tk).pack(side=tk.LEFT)
        swing = tk.Spinbox(
            toolbar,
            textvariable=self.arranger_swing,
            from_=50,
            to=75,
            increment=0.5,
            width=6,
        )
        swing.pack(side=tk.LEFT, padx=(3, 10))
        for text, value in (("SCENE", "scene"), ("SONG", "song")):
            button = tk.Radiobutton(
                toolbar,
                text=text,
                value=value,
                variable=self.arranger_mode,
                indicatoron=False,
                width=7,
                bg="#efeadf",
                selectcolor="#ff4b0b",
            )
            button.pack(side=tk.LEFT, padx=1)
            self._tip(button, f"Play the selected {text.lower()} structure.")
        sync = ttk.Combobox(
            toolbar,
            textvariable=self.arranger_sync,
            values=("master", "follow device", "internal no clock"),
            state="readonly",
            width=18,
        )
        sync.pack(side=tk.LEFT, padx=10)
        loop = tk.Checkbutton(
            toolbar,
            text="LOOP",
            variable=self.arranger_loop,
            bg="#bdb7aa",
        )
        loop.pack(side=tk.LEFT)
        self._tip(bpm_entry, "Arrangement tempo. Master mode schedules MIDI and sends 24 PPQN clock at this BPM.")
        self._tip(swing, "Delay alternate sixteenth notes from straight 50% toward 75% swing.")
        self._tip(sync, "Master sends clock and transport; follow device advances from incoming KO II clock; internal no clock sends notes and transport only.")
        self._tip(loop, "Repeat the compiled scene or song until stopped.")

        action_specs = (
            ("REC", self._arranger_record, "#dc493a"),
            ("PLAY", self._arranger_play, "#88b04b"),
            ("STOP", self._arranger_stop, "#efeadf"),
            ("UNDO", self._arranger_undo, "#efeadf"),
            ("REDO", self._arranger_redo, "#efeadf"),
            ("SAVE", self._arranger_save, "#efeadf"),
            ("LOAD", self._arranger_load, "#efeadf"),
            ("MIDI", self._arranger_export_midi, "#efeadf"),
            ("IMPORT TAKE", self._arranger_import_performance, "#efeadf"),
            ("HELP", self._show_arranger_help, "#efeadf"),
        )
        for text, command, color in action_specs:
            button = tk.Button(toolbar, text=text, command=command, bg=color, padx=7)
            button.pack(side=tk.RIGHT, padx=2)
            self._tip(button, _action_tip(text))

        body = tk.PanedWindow(
            win,
            orient=tk.HORIZONTAL,
            sashwidth=5,
            bg="#171915",
            bd=0,
        )
        body.grid(row=2, column=0, sticky="nsew")
        left = tk.Frame(body, bg="#d8d4c8", padx=7, pady=7, width=360)
        center = tk.Frame(body, bg="#d8d4c8", padx=7, pady=7)
        right = tk.Frame(body, bg="#d8d4c8", padx=7, pady=7, width=310)
        body.add(left, minsize=310)
        body.add(center, minsize=520, stretch="always")
        body.add(right, minsize=270)

        self._build_arranger_scene_panel(left)
        self._build_arranger_editor(center)
        self._build_arranger_song_panel(right)
        self._refresh_arranger()

    def _build_arranger_scene_panel(self, parent) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(4, weight=1)
        tk.Label(
            parent,
            text="GROUPS / SCENES",
            bg="#d8d4c8",
            fg="#171915",
            font=("Consolas", 12, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        matrix = tk.Frame(parent, bg="#171915", padx=5, pady=5)
        matrix.grid(row=1, column=0, sticky="ew", pady=(5, 8))
        for column in range(9):
            matrix.columnconfigure(column, weight=1, uniform="scene")
        for index in range(8):
            tk.Label(
                matrix,
                text=str(index + 1),
                bg="#171915",
                fg="#f3f1de",
                font=("Consolas", 9, "bold"),
            ).grid(row=0, column=index + 1, sticky="ew")
        for row, group in enumerate(GROUPS, start=1):
            tk.Label(
                matrix,
                text=group,
                bg=GROUP_COLORS[group],
                fg="#171915",
                width=2,
                font=("Consolas", 11, "bold"),
            ).grid(row=row, column=0, sticky="nsew", padx=(0, 3), pady=2)
            for index, scene in enumerate(self.arranger_session.project.scenes[:8]):
                button = tk.Button(
                    matrix,
                    text="",
                    width=2,
                    height=1,
                    command=lambda sid=scene.scene_id, grp=group: self._arranger_select(sid, grp),
                    bg="#595b53",
                    activebackground=GROUP_COLORS[group],
                    relief=tk.FLAT,
                )
                button.grid(row=row, column=index + 1, sticky="nsew", padx=2, pady=2)
                self.arranger_scene_buttons[(scene.scene_id, group)] = button
                self._tip(button, f"Select Group {group}, {scene.name}. The editor below maps its 12 pads across the clip steps.")

        tk.Label(
            parent,
            text="TRACK MIX",
            bg="#d8d4c8",
            fg="#171915",
            font=("Consolas", 12, "bold"),
            anchor="w",
        ).grid(row=2, column=0, sticky="ew")
        tracks = tk.Frame(parent, bg="#bdb7aa", padx=5, pady=4)
        tracks.grid(row=3, column=0, sticky="ew", pady=(5, 0))
        for column, weight in enumerate((0, 0, 0, 0, 1, 1)):
            tracks.columnconfigure(column, weight=weight)
        for row, group in enumerate(GROUPS):
            muted = tk.BooleanVar()
            solo = tk.BooleanVar()
            armed = tk.BooleanVar()
            velocity = tk.StringVar()
            transpose = tk.StringVar()
            self.arranger_track_vars[group] = {
                "muted": muted,
                "solo": solo,
                "armed": armed,
                "velocity": velocity,
                "transpose": transpose,
            }
            tk.Label(
                tracks,
                text=group,
                bg=GROUP_COLORS[group],
                width=2,
                font=("Consolas", 10, "bold"),
            ).grid(row=row, column=0, padx=(0, 4), pady=3)
            for column, (text, variable, field) in enumerate(
                (("M", muted, "muted"), ("S", solo, "solo"), ("R", armed, "armed")),
                start=1,
            ):
                check = tk.Checkbutton(
                    tracks,
                    text=text,
                    variable=variable,
                    indicatoron=False,
                    width=2,
                    command=lambda grp=group: self._arranger_track_changed(grp),
                    bg="#efeadf",
                    selectcolor="#ff4b0b",
                )
                check.grid(row=row, column=column, padx=1)
                self._tip(check, {"muted": "Mute track.", "solo": "Solo track.", "armed": "Arm this group for incoming or app-generated MIDI recording."}[field])
            vel = tk.Spinbox(tracks, textvariable=velocity, from_=0, to=200, width=5)
            vel.grid(row=row, column=4, sticky="ew", padx=4)
            trans = tk.Spinbox(tracks, textvariable=transpose, from_=-48, to=48, width=5)
            trans.grid(row=row, column=5, sticky="ew", padx=4)
            for widget in (vel, trans):
                widget.configure(command=lambda grp=group: self._arranger_track_changed(grp))
                widget.bind("<Return>", lambda _event, grp=group: self._arranger_track_changed(grp))
                widget.bind("<FocusOut>", lambda _event, grp=group: self._arranger_track_changed(grp))
            self._tip(vel, "Track velocity scale in percent; 100 preserves recorded velocity.")
            self._tip(trans, "Track transpose in semitones, applied during playback and MIDI export.")

        automation = tk.Frame(parent, bg="#d8d4c8")
        automation.grid(row=4, column=0, sticky="nsew", pady=(10, 0))
        automation.columnconfigure(0, weight=1)
        automation.rowconfigure(2, weight=1)
        tk.Label(
            automation,
            text="CLIP CC AUTOMATION",
            bg="#d8d4c8",
            fg="#171915",
            font=("Consolas", 12, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        cc_controls = tk.Frame(automation, bg="#bdb7aa", padx=4, pady=4)
        cc_controls.grid(row=1, column=0, sticky="ew", pady=(5, 4))
        for text, variable, start, end, tip in (
            ("STEP", self.arranger_cc_step, 1, 128, "Sequencer step where the CC value is emitted."),
            ("CC", self.arranger_cc_number, 0, 127, "Standard MIDI controller number."),
            ("VALUE", self.arranger_cc_value, 0, 127, "Controller value emitted at this step."),
        ):
            _label(cc_controls, text, tk).pack(side=tk.LEFT)
            entry = tk.Spinbox(
                cc_controls,
                textvariable=variable,
                from_=start,
                to=end,
                width=4,
            )
            entry.pack(side=tk.LEFT, padx=(2, 5))
            self._tip(entry, tip)
        write = tk.Button(
            cc_controls,
            text="WRITE",
            command=self._arranger_write_cc,
            bg="#efeadf",
        )
        write.pack(side=tk.RIGHT)
        self._tip(write, "Insert or replace this CC point in the selected clip.")
        tree = ttk.Treeview(
            automation,
            columns=("step", "cc", "value"),
            show="headings",
            height=6,
        )
        for column, width in (("step", 55), ("cc", 55), ("value", 70)):
            tree.heading(column, text=column.upper())
            tree.column(column, width=width, anchor="center")
        tree.grid(row=2, column=0, sticky="nsew")
        self.arranger_cc_tree = tree
        self._tip(tree, "Automation points compiled alongside notes and exported to MIDI.")
        delete = tk.Button(
            automation,
            text="DELETE SELECTED CC",
            command=self._arranger_delete_cc,
            bg="#efeadf",
        )
        delete.grid(row=3, column=0, sticky="ew", pady=(4, 0))
        self._tip(delete, "Remove the selected automation point with undo support.")

    def _build_arranger_editor(self, parent) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)
        self.arranger_clip_title = tk.StringVar(value="")
        tk.Label(
            parent,
            textvariable=self.arranger_clip_title,
            bg="#171915",
            fg="#ff4b0b",
            font=("Consolas", 12, "bold"),
            padx=8,
            pady=5,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        controls = tk.Frame(parent, bg="#bdb7aa", padx=5, pady=5)
        controls.grid(row=1, column=0, sticky="ew", pady=5)
        for label, variable, values, width, tip in (
            ("STEPS", self.arranger_steps, (4, 8, 16, 32, 64, 128), 6, "Clip length at four steps per beat. Different groups may use different lengths for polymeter."),
            ("VEL", self.arranger_step_velocity, tuple(range(1, 128)), 5, "Velocity assigned to newly inserted steps."),
            ("PROB %", self.arranger_probability, tuple(range(0, 101)), 5, "Deterministic playback probability assigned to newly inserted steps."),
            ("GATE", self.arranger_duration, (0.25, 0.5, 0.75, 0.9, 1, 2, 4, 8), 5, "New note duration measured in sequencer steps."),
        ):
            _label(controls, label, tk).pack(side=tk.LEFT)
            combo = ttk.Combobox(
                controls,
                textvariable=variable,
                values=values,
                state="readonly",
                width=width,
            )
            combo.pack(side=tk.LEFT, padx=(3, 8))
            self._tip(combo, tip)
            if label == "STEPS":
                combo.bind("<<ComboboxSelected>>", lambda _event: self._arranger_set_steps())
        clear = tk.Button(controls, text="CLEAR", command=self._arranger_clear_clip, bg="#efeadf")
        quantize = tk.Button(controls, text="QUANTIZE", command=self._arranger_quantize, bg="#efeadf")
        clear.pack(side=tk.RIGHT, padx=2)
        quantize.pack(side=tk.RIGHT, padx=2)
        self._tip(clear, "Clear notes and automation from the selected clip after confirmation.")
        self._tip(quantize, "Move selected clip notes fully to the nearest sixteenth-note grid.")

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
        canvas.bind("<Button-1>", self._arranger_canvas_click)
        canvas.bind("<Button-3>", self._arranger_canvas_audition)
        canvas.bind("<Configure>", lambda _event: self._draw_arranger_grid())
        self.arranger_canvas = canvas
        self._tip(canvas, "Left-click a pad/step cell to toggle a note. Right-click a row to audition that KO II pad. Strong vertical lines mark beats.")

    def _build_arranger_song_panel(self, parent) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        tk.Label(
            parent,
            text="SONG CHAIN",
            bg="#d8d4c8",
            fg="#171915",
            font=("Consolas", 12, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        tree = ttk.Treeview(
            parent,
            columns=("scene", "repeats", "beats"),
            show="headings",
            height=14,
        )
        for column, width in (("scene", 100), ("repeats", 65), ("beats", 65)):
            tree.heading(column, text=column.title())
            tree.column(column, width=width, anchor="center")
        tree.grid(row=1, column=0, sticky="nsew", pady=5)
        self.arranger_song_tree = tree
        self._tip(tree, "Ordered scene chain. Scene duration is the longest group clip, so shorter clips repeat polymetrically.")
        controls = tk.Frame(parent, bg="#bdb7aa", padx=5, pady=5)
        controls.grid(row=2, column=0, sticky="ew")
        repeat = tk.Spinbox(
            controls,
            textvariable=self.arranger_song_repeats,
            from_=1,
            to=999,
            width=5,
        )
        repeat.pack(side=tk.LEFT)
        self._tip(repeat, "Number of times to repeat the selected scene when adding it to the song.")
        for text, command, tip in (
            ("ADD", self._arranger_song_add, "Append the currently selected scene."),
            ("DEL", self._arranger_song_remove, "Remove the selected song section."),
            ("UP", lambda: self._arranger_song_move(-1), "Move the selected section earlier."),
            ("DOWN", lambda: self._arranger_song_move(1), "Move the selected section later."),
        ):
            button = tk.Button(controls, text=text, command=command, bg="#efeadf")
            button.pack(side=tk.LEFT, padx=2)
            self._tip(button, tip)

        info = tk.Label(
            parent,
            text=(
                "Pad notes\n"
                "A 36-47   B 48-59\n"
                "C 60-71   D 72-83\n\n"
                "Recording captures paired note\n"
                "events and CC automation into\n"
                "armed group clips."
            ),
            bg="#171915",
            fg="#f3f1de",
            justify=tk.LEFT,
            anchor="nw",
            padx=8,
            pady=8,
            font=("Consolas", 9),
        )
        info.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self._tip(info, "The arranger uses the KO II's documented MIDI pad ranges and standard transport/clock messages.")

    def _arranger_select(self, scene_id: str, group: str) -> None:
        self.arranger_session.select(scene_id, group)
        self.group.set(group)
        self._refresh_arranger()

    def _arranger_set_steps(self) -> None:
        try:
            self.arranger_session.set_clip_steps(int(self.arranger_steps.get()))
        except ValueError as exc:
            messagebox.showerror("KO II Arranger", str(exc))
        self._refresh_arranger()

    def _arranger_canvas_click(self, event) -> None:
        canvas = self.arranger_canvas
        x = canvas.canvasx(event.x)
        y = canvas.canvasy(event.y)
        step = int((x - 58) // self.arranger_cell_width)
        pad = int((y - 25) // self.arranger_row_height)
        steps = int(self.arranger_steps.get())
        if not 0 <= step < steps or not 0 <= pad < 12:
            return
        try:
            enabled = self.arranger_session.toggle_step(
                step,
                pad,
                steps=steps,
                velocity=int(self.arranger_step_velocity.get()),
                duration_steps=float(self.arranger_duration.get()),
                probability=float(self.arranger_probability.get()) / 100.0,
            )
        except ValueError as exc:
            messagebox.showerror("KO II Arranger", str(exc))
            return
        self.arranger_status.set(
            f"{'set' if enabled else 'cleared'} pad {pad + 1} / step {step + 1}"
        )
        self._draw_arranger_grid()

    def _arranger_canvas_audition(self, event) -> None:
        y = self.arranger_canvas.canvasy(event.y)
        pad = int((y - 25) // self.arranger_row_height)
        if not 0 <= pad < 12:
            return
        note = GROUP_BASE_NOTES[self.arranger_session.selected_group] + pad
        channel = self.arranger_session.project.tracks[self.arranger_session.selected_group].channel
        if self._send_midi(
            MidiMessage.note_on(note, int(self.arranger_step_velocity.get()), channel)
        ):
            self.root.after(
                120,
                lambda: self._send_midi(MidiMessage.note_off(note, channel=channel)),
            )

    def _arranger_track_changed(self, group: str) -> None:
        values = self.arranger_track_vars[group]
        try:
            self.arranger_session.set_track(
                group,
                muted=values["muted"].get(),
                solo=values["solo"].get(),
                armed=values["armed"].get(),
                velocity_scale=float(values["velocity"].get()) / 100.0,
                transpose=int(values["transpose"].get()),
            )
        except ValueError as exc:
            messagebox.showerror("KO II Arranger", str(exc))
        self._refresh_arranger_tracks()

    def _arranger_write_cc(self) -> None:
        try:
            step = int(self.arranger_cc_step.get())
            steps = round(self.arranger_session.selected_clip.length_beats * 4)
            if not 1 <= step <= steps:
                raise ValueError(f"CC step must be between 1 and {steps}.")
            self.arranger_session.add_control(
                (step - 1) / 4.0,
                int(self.arranger_cc_number.get()),
                int(self.arranger_cc_value.get()),
            )
        except ValueError as exc:
            messagebox.showerror("KO II Arranger", str(exc))
            return
        self.arranger_status.set(
            f"CC {self.arranger_cc_number.get()}={self.arranger_cc_value.get()} at step {step}"
        )
        self._refresh_arranger_cc()

    def _arranger_delete_cc(self) -> None:
        selected = self.arranger_cc_tree.selection()
        if not selected:
            messagebox.showinfo("KO II Arranger", "Select a CC automation point first.")
            return
        self.arranger_session.remove_control(int(selected[0]))
        self.arranger_status.set("CC automation point removed")
        self._refresh_arranger_cc()

    def _arranger_record(self) -> None:
        self._show_arranger_window()
        self._arranger_stop(playback_only=True)
        if not any(track.armed for track in self.arranger_session.project.tracks.values()):
            messagebox.showinfo("KO II Arranger", "Arm at least one group track first.")
            return
        self._arranger_apply_fields()
        self.arranger_capture.start()
        self.arranger_status.set("recording armed tracks")
        self._set_action("arranger recording")

    def _arranger_play(self) -> None:
        self._show_arranger_window()
        if not self._arranger_apply_fields():
            return
        if self.arranger_capture.recording:
            self.arranger_capture.stop()
        if hasattr(self, "_performance_stop_playback"):
            self._performance_stop_playback()
        self._arranger_stop(playback_only=True)
        mode = self.arranger_mode.get()
        sync = self.arranger_sync.get()
        snapshot = ArrangerProject.from_dict(self.arranger_session.project.to_dict())
        if sync == "follow device":
            self.arranger_follower = ArrangerClockFollower(
                snapshot,
                mode=mode,
                scene_id=self.arranger_session.selected_scene_id,
            )
            self.arranger_status.set("armed: waiting for incoming MIDI Start + Clock")
            self._set_action("arranger follows device clock")
            return
        try:
            self.arranger_engine.start(
                snapshot,
                mode=mode,
                scene_id=self.arranger_session.selected_scene_id,
                loop=self.arranger_loop.get(),
                send_clock=sync == "master",
                send_transport=True,
            )
        except (RuntimeError, ValueError) as exc:
            messagebox.showerror("KO II Arranger", str(exc))
            return
        self.arranger_status.set(f"playing {mode} / {sync}")
        self._set_action(f"arranger playback {mode}")

    def _arranger_stop(self, playback_only: bool = False) -> None:
        if self.arranger_engine is not None:
            self.arranger_engine.stop(wait=True)
        self.arranger_follower = None
        self._arranger_release_follow_notes()
        if not playback_only and self.arranger_capture.recording:
            count = self.arranger_capture.stop()
            self.arranger_status.set(f"recording stopped / {count} events")
            self._refresh_arranger()
        elif self.arranger_window and self.arranger_window.winfo_exists():
            self.arranger_status.set("stopped")

    def _arranger_release_follow_notes(self) -> None:
        for channel, note in sorted(self.arranger_follow_active_notes):
            try:
                self._arranger_send_engine(MidiMessage.note_off(note, channel=channel))
            except Exception:
                pass
        self.arranger_follow_active_notes.clear()

    def _arranger_send_engine(self, message: MidiMessage) -> None:
        self.controller.send(message)
        self.arranger_queue.put(("sent", message))

    def _poll_arranger_queue(self) -> None:
        refresh_state = False
        while True:
            try:
                event = self.arranger_queue.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "sent":
                message = event[1]
                self.runtime_state.observe(message, "out")
                refresh_state = True
                if message.kind != "clock":
                    self._log(f"arranger out {message.display()}")
            elif kind == "position":
                _, beat, length, cycle = event
                self.arranger_status.set(
                    f"playing {float(beat):.2f} / {float(length):.2f} beats  loop {int(cycle) + 1}"
                )
                self._draw_arranger_playhead(float(beat), float(length))
            elif kind == "complete":
                self.arranger_status.set("playback complete")
                self._draw_arranger_playhead(0, 1)
            elif kind == "follow-stopped":
                self.arranger_status.set("external transport stopped")
            elif kind == "error":
                self.arranger_status.set(f"error: {event[1]}")
                self._log(f"arranger error: {event[1]}")
                messagebox.showerror("KO II Arranger", str(event[1]))
        if refresh_state:
            self._refresh_state_label()
        if self.root.winfo_exists():
            self.root.after(40, self._poll_arranger_queue)

    def _arranger_apply_fields(self) -> bool:
        try:
            project = self.arranger_session.project
            project.name = self.arranger_project_name.get().strip() or "EP-133 Arrangement"
            project.bpm = float(self.bpm.get())
            project.swing_percent = float(self.arranger_swing.get())
            project.validate()
        except (TypeError, ValueError) as exc:
            messagebox.showerror("KO II Arranger", str(exc))
            return False
        return True

    def _arranger_undo(self) -> None:
        if self.arranger_session.undo():
            self.arranger_status.set("undo")
            self._refresh_arranger()

    def _arranger_redo(self) -> None:
        if self.arranger_session.redo():
            self.arranger_status.set("redo")
            self._refresh_arranger()

    def _arranger_clear_clip(self) -> None:
        if not messagebox.askyesno(
            "KO II Arranger",
            "Clear all notes and CC automation from the selected in-memory clip?",
        ):
            return
        self.arranger_session.clear_clip()
        self.arranger_status.set("clip cleared")
        self._refresh_arranger()

    def _arranger_quantize(self) -> None:
        self.arranger_session.quantize_clip(16, 1.0)
        self.arranger_status.set("clip quantized to 1/16")
        self._refresh_arranger()

    def _arranger_save(self) -> None:
        if not self._arranger_apply_fields():
            return
        path = filedialog.asksaveasfilename(
            title="Save KO II arrangement",
            initialdir=str(self.project_root),
            defaultextension=".json",
            filetypes=(("KO II arrangement", "*.json"),),
        )
        if not path:
            return
        try:
            saved = self.arranger_session.save(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("KO II Arranger", str(exc))
            return
        self.arranger_status.set(f"saved {saved.name}")

    def _arranger_load(self) -> None:
        path = filedialog.askopenfilename(
            title="Load KO II arrangement",
            initialdir=str(self.project_root),
            filetypes=(("KO II arrangement", "*.json"), ("All files", "*.*")),
        )
        if not path:
            return
        self._arranger_stop()
        try:
            session = ArrangerSession.load(path)
        except (OSError, ValueError) as exc:
            messagebox.showerror("KO II Arranger", str(exc))
            return
        self.arranger_session = session
        self.arranger_capture = ArrangerCapture(session)
        self.arranger_project_name.set(session.project.name)
        self.bpm.set(session.project.bpm)
        self.arranger_swing.set(session.project.swing_percent)
        self.arranger_status.set(f"loaded {len(session.project.scenes)} scenes")
        self._refresh_arranger()

    def _arranger_export_midi(self) -> None:
        if not self._arranger_apply_fields():
            return
        path = filedialog.asksaveasfilename(
            title="Export arrangement MIDI",
            initialdir=str(self.project_root),
            defaultextension=".mid",
            filetypes=(("Standard MIDI File", "*.mid"),),
        )
        if not path:
            return
        try:
            exported = self.arranger_session.export_midi(
                path,
                mode=self.arranger_mode.get(),
                scene_id=self.arranger_session.selected_scene_id,
            )
        except (OSError, ValueError) as exc:
            messagebox.showerror("KO II Arranger", str(exc))
            return
        self.arranger_status.set(f"exported {exported.name}")

    def _arranger_import_performance(self) -> None:
        recorder = getattr(self, "performance_recorder", None)
        if recorder is None or not recorder.clip.events:
            messagebox.showinfo(
                "KO II Arranger",
                "Record or load a take in Performance Recorder first.",
            )
            return
        count = self.arranger_session.import_performance(recorder.clip)
        self.arranger_status.set(f"imported {count} MIDI events into selected scene")
        self._refresh_arranger()

    def _arranger_song_add(self) -> None:
        try:
            self.arranger_session.append_song_section(
                self.arranger_session.selected_scene_id,
                int(self.arranger_song_repeats.get()),
            )
        except ValueError as exc:
            messagebox.showerror("KO II Arranger", str(exc))
            return
        self._refresh_arranger_song()

    def _arranger_song_remove(self) -> None:
        index = self._arranger_song_index()
        if index is None:
            return
        self.arranger_session.remove_song_section(index)
        self._refresh_arranger_song()

    def _arranger_song_move(self, offset: int) -> None:
        index = self._arranger_song_index()
        if index is None:
            return
        target = self.arranger_session.move_song_section(index, offset)
        self._refresh_arranger_song()
        if self.arranger_song_tree.exists(str(target)):
            self.arranger_song_tree.selection_set(str(target))

    def _arranger_song_index(self) -> int | None:
        selected = self.arranger_song_tree.selection()
        if not selected:
            messagebox.showinfo("KO II Arranger", "Select a song section first.")
            return None
        return int(selected[0])

    def _refresh_arranger(self) -> None:
        if not self.arranger_window or not self.arranger_window.winfo_exists():
            return
        project = self.arranger_session.project
        clip = self.arranger_session.selected_clip
        self.arranger_project_name.set(project.name)
        self.arranger_swing.set(project.swing_percent)
        self.arranger_steps.set(round(clip.length_beats * 4))
        scene = project.scene(self.arranger_session.selected_scene_id)
        self.arranger_clip_title.set(
            f"{scene.name.upper()}  /  GROUP {clip.group}  /  {len(clip.notes)} NOTES"
        )
        for (scene_id, group), button in self.arranger_scene_buttons.items():
            selected = (
                scene_id == self.arranger_session.selected_scene_id
                and group == self.arranger_session.selected_group
            )
            clip_id = project.scene(scene_id).clip_ids[group]
            populated = bool(project.clips[clip_id].notes or project.clips[clip_id].controls)
            button.configure(
                bg=GROUP_COLORS[group] if selected else ("#8d907f" if populated else "#595b53"),
                relief=tk.SUNKEN if selected else tk.FLAT,
            )
        self._refresh_arranger_tracks()
        self._refresh_arranger_cc()
        self._refresh_arranger_song()
        self._draw_arranger_grid()

    def _refresh_arranger_tracks(self) -> None:
        for group, variables in self.arranger_track_vars.items():
            track = self.arranger_session.project.tracks[group]
            variables["muted"].set(track.muted)
            variables["solo"].set(track.solo)
            variables["armed"].set(track.armed)
            variables["velocity"].set(str(round(track.velocity_scale * 100)))
            variables["transpose"].set(str(track.transpose))

    def _refresh_arranger_cc(self) -> None:
        tree = getattr(self, "arranger_cc_tree", None)
        if tree is None:
            return
        for item in tree.get_children():
            tree.delete(item)
        for index, control in enumerate(self.arranger_session.selected_clip.controls):
            tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(round(control.beat * 4) + 1, control.control, control.value),
            )

    def _refresh_arranger_song(self) -> None:
        tree = getattr(self, "arranger_song_tree", None)
        if tree is None:
            return
        for item in tree.get_children():
            tree.delete(item)
        for index, section in enumerate(self.arranger_session.project.song):
            scene = self.arranger_session.project.scene(section.scene_id)
            beats = self.arranger_session.project.scene_length(section.scene_id)
            tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(scene.name, section.repeats, f"{beats * section.repeats:g}"),
            )

    def _draw_arranger_grid(self) -> None:
        canvas = getattr(self, "arranger_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        clip = self.arranger_session.selected_clip
        steps = max(4, round(clip.length_beats * 4))
        visible_width = max(570, canvas.winfo_width())
        visible_height = max(385, canvas.winfo_height())
        self.arranger_cell_width = max(32.0, (visible_width - 58) / min(steps, 16))
        self.arranger_row_height = max(30.0, (visible_height - 25) / 12)
        width = 58 + steps * self.arranger_cell_width
        height = 25 + 12 * self.arranger_row_height
        canvas.configure(scrollregion=(0, 0, width, height))
        group = clip.group
        note_steps = {
            (item.note - GROUP_BASE_NOTES[group], round(item.beat * 4)): item
            for item in clip.notes
            if GROUP_BASE_NOTES[group] <= item.note < GROUP_BASE_NOTES[group] + 12
        }
        for step in range(steps):
            x0 = 58 + step * self.arranger_cell_width
            canvas.create_text(
                x0 + self.arranger_cell_width / 2,
                13,
                text=str(step + 1),
                fill="#f3f1de" if step % 4 == 0 else "#8d907f",
                font=("Consolas", 8, "bold" if step % 4 == 0 else "normal"),
            )
        for pad in range(12):
            y0 = 25 + pad * self.arranger_row_height
            note = GROUP_BASE_NOTES[group] + pad
            canvas.create_rectangle(
                0,
                y0,
                57,
                y0 + self.arranger_row_height - 1,
                fill=GROUP_COLORS[group],
                outline="#11120f",
            )
            canvas.create_text(
                28,
                y0 + self.arranger_row_height / 2,
                text=f"P{pad + 1:02d} {note}",
                fill="#171915",
                font=("Consolas", 9, "bold"),
            )
            for step in range(steps):
                x0 = 58 + step * self.arranger_cell_width
                item = note_steps.get((pad, step))
                fill = "#ff4b0b" if item else ("#2d3029" if step % 4 else "#3b3f35")
                canvas.create_rectangle(
                    x0 + 1,
                    y0 + 1,
                    x0 + self.arranger_cell_width - 1,
                    y0 + self.arranger_row_height - 1,
                    fill=fill,
                    outline="#11120f",
                )
                if item and item.probability < 1:
                    canvas.create_text(
                        x0 + self.arranger_cell_width / 2,
                        y0 + self.arranger_row_height / 2,
                        text=str(round(item.probability * 100)),
                        fill="#171915",
                        font=("Consolas", 7, "bold"),
                    )
        self.arranger_playhead_item = canvas.create_line(
            58,
            25,
            58,
            height,
            fill="#dc493a",
            width=2,
            state=tk.HIDDEN,
        )

    def _draw_arranger_playhead(self, beat: float, length: float) -> None:
        canvas = getattr(self, "arranger_canvas", None)
        item = getattr(self, "arranger_playhead_item", None)
        if canvas is None or item is None:
            return
        clip_length = self.arranger_session.selected_clip.length_beats
        position = 0 if length <= 0 else beat % clip_length
        x = 58 + position * 4 * self.arranger_cell_width
        canvas.coords(item, x, 25, x, 25 + 12 * self.arranger_row_height)
        canvas.itemconfigure(item, state=tk.NORMAL)

    def _show_arranger_help(self) -> None:
        messagebox.showinfo(
            "KO II Scene Arranger Guide",
            "\n".join(
                [
                    "GROUPS / SCENES selects one of four KO II MIDI groups and eight clip scenes.",
                    "Left-click the 12 x step grid to sequence pads; right-click a row to audition it.",
                    "M, S, and R mean mute, solo, and record-arm. Velocity and transpose are per group.",
                    "SCENE loops the selected scene. SONG follows the ordered chain at right.",
                    "Master sends Start, Stop, 24 PPQN clock, notes, and CC to the connected KO II.",
                    "Follow device waits for incoming Start/Clock and plays the arrangement in KO II time.",
                    "Internal no clock plays notes and transport without becoming clock master.",
                    "REC captures incoming hardware MIDI and app pad actions into every armed group.",
                    "IMPORT TAKE converts the Performance Recorder take into four scene clips.",
                    "SAVE writes non-destructive JSON. MIDI exports a type-1 Standard MIDI File.",
                    "",
                    "Project edits do not write EP-133 storage. Device project downloads remain read-only,",
                    "content-addressed, and automatically analyzed for pad-to-sound assignments.",
                ]
            ),
        )

    def _close(self) -> None:
        if self.arranger_engine is not None:
            self.arranger_engine.stop(wait=True)
        self.arranger_follower = None
        self._arranger_release_follow_notes()
        original_close(self)

    app_class.__init__ = __init__
    app_class._build_menu = _build_menu
    app_class._send_midi = _send_midi
    app_class._queue_midi_input = _queue_midi_input
    app_class._stop = _stop
    app_class._show_arranger_window = _show_arranger_window
    app_class._build_arranger_scene_panel = _build_arranger_scene_panel
    app_class._build_arranger_editor = _build_arranger_editor
    app_class._build_arranger_song_panel = _build_arranger_song_panel
    app_class._arranger_select = _arranger_select
    app_class._arranger_set_steps = _arranger_set_steps
    app_class._arranger_canvas_click = _arranger_canvas_click
    app_class._arranger_canvas_audition = _arranger_canvas_audition
    app_class._arranger_track_changed = _arranger_track_changed
    app_class._arranger_write_cc = _arranger_write_cc
    app_class._arranger_delete_cc = _arranger_delete_cc
    app_class._arranger_record = _arranger_record
    app_class._arranger_play = _arranger_play
    app_class._arranger_stop = _arranger_stop
    app_class._arranger_release_follow_notes = _arranger_release_follow_notes
    app_class._arranger_send_engine = _arranger_send_engine
    app_class._poll_arranger_queue = _poll_arranger_queue
    app_class._arranger_apply_fields = _arranger_apply_fields
    app_class._arranger_undo = _arranger_undo
    app_class._arranger_redo = _arranger_redo
    app_class._arranger_clear_clip = _arranger_clear_clip
    app_class._arranger_quantize = _arranger_quantize
    app_class._arranger_save = _arranger_save
    app_class._arranger_load = _arranger_load
    app_class._arranger_export_midi = _arranger_export_midi
    app_class._arranger_import_performance = _arranger_import_performance
    app_class._arranger_song_add = _arranger_song_add
    app_class._arranger_song_remove = _arranger_song_remove
    app_class._arranger_song_move = _arranger_song_move
    app_class._arranger_song_index = _arranger_song_index
    app_class._refresh_arranger = _refresh_arranger
    app_class._refresh_arranger_tracks = _refresh_arranger_tracks
    app_class._refresh_arranger_cc = _refresh_arranger_cc
    app_class._refresh_arranger_song = _refresh_arranger_song
    app_class._draw_arranger_grid = _draw_arranger_grid
    app_class._draw_arranger_playhead = _draw_arranger_playhead
    app_class._show_arranger_help = _show_arranger_help
    app_class._close = _close
    app_class._arranger_patch_installed = True


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


def _action_tip(text: str) -> str:
    return {
        "REC": "Record incoming KO II MIDI and app pad actions into armed group clips.",
        "PLAY": "Compile and play the selected scene or song using the selected synchronization mode.",
        "STOP": "Stop playback or recording and release every tracked active note.",
        "UNDO": "Undo the most recent arranger edit.",
        "REDO": "Redo the most recently undone arranger edit.",
        "SAVE": "Save the complete arrangement as atomic, non-destructive JSON.",
        "LOAD": "Load and validate an arrangement JSON file.",
        "MIDI": "Export the selected scene or song as a type-1 Standard MIDI File.",
        "IMPORT TAKE": "Split the Performance Recorder take across KO II groups by pad note range.",
        "HELP": "Show all arranger interactions and synchronization behavior.",
    }[text]


def _track_note(active_notes: set[tuple[int, int]], message: MidiMessage) -> None:
    if message.note is None:
        return
    key = (int(message.channel or 0), int(message.note))
    if message.kind == "note_on" and int(message.velocity or 0) > 0:
        active_notes.add(key)
    elif message.kind in {"note_off", "note_on"}:
        active_notes.discard(key)
