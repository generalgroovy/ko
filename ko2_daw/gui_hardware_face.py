"""Unified hardware-style KO II face for the Tkinter GUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ko2_daw.midi import MidiMessage

GROUP_PROGRAMS = {"A": 0, "B": 1, "C": 2, "D": 3}
LANES = ("A", "B", "C", "D")
STEPS = 64


@dataclass(frozen=True)
class FaceAction:
    key: str
    label: str
    cc: int | None = None


ACTIONS = {
    "sound": FaceAction("sound", "SOUND", 20),
    "main": FaceAction("main", "MAIN", 21),
    "sample": FaceAction("sample", "SAMPLE", 22),
    "keys": FaceAction("keys", "KEYS", 23),
    "timing": FaceAction("timing", "TIMING", 24),
    "fx": FaceAction("fx", "FX", 25),
    "fader": FaceAction("fader", "FADER", 26),
    "shift": FaceAction("shift", "SHIFT", 27),
    "minus": FaceAction("minus", "-", 85),
    "plus": FaceAction("plus", "+", 86),
    "metro": FaceAction("metro", "METRO", 87),
}


class C:
    shell = "#11120f"
    panel = "#1b1c18"
    soft = "#272820"
    pad = "#f5f0e4"
    text = "#f3f1de"
    dim = "#aaa99a"
    accent = "#d7f58a"
    amber = "#f2c230"
    red = "#dc493a"


def apply_hardware_face_patch(gui_module: Any) -> None:
    """Replace duplicated control areas with one KO II-style hardware face."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_hardware_face_patch_installed", False):
        return

    tk = gui_module.tk
    original_send_midi = app_class._send_midi
    original_queue_midi_input = app_class._queue_midi_input

    def _build_mode_strip(self, parent) -> None:
        self._hardware_face_has_no_separate_mode_strip = True

    def _build_main_controls(self, parent) -> None:
        self._face_mode = "main"
        self._face_shift = False
        self._face_metro = False
        self._face_current_step = 0
        self._face_lanes = {lane: [False] * STEPS for lane in LANES}
        self._face_buttons = {}
        self._face_group_buttons = {}
        self._face_pad_buttons = {}

        face = tk.Frame(parent, bg=C.shell, padx=12, pady=12)
        face.grid(row=2, column=0, columnspan=2, sticky="nsew")
        for column, weight in enumerate((2, 4, 2)):
            face.columnconfigure(column, weight=weight)
        face.rowconfigure(1, weight=1)

        self._build_face_screen(face)
        self._build_face_left(face)
        self._build_face_center(face)
        self._build_face_right(face)
        self._build_face_timeline(face)
        self._refresh_hardware_face()
        self.root.after(120, self._refresh_hardware_face_loop)

    def _build_face_screen(self, parent) -> None:
        screen = tk.Frame(parent, bg=C.panel, padx=10, pady=8)
        screen.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        screen.columnconfigure(0, weight=1)
        screen.columnconfigure(1, weight=1)
        self.face_selection = tk.Label(
            screen,
            bg=C.panel,
            fg=C.accent,
            font=("Consolas", 12, "bold"),
            anchor="w",
        )
        self.face_selection.grid(row=0, column=0, sticky="ew")
        self.face_safety = tk.Label(
            screen,
            bg=C.panel,
            fg=C.dim,
            font=("Consolas", 10),
            anchor="e",
        )
        self.face_safety.grid(row=0, column=1, sticky="ew")

    def _build_face_left(self, parent) -> None:
        left = tk.Frame(parent, bg=C.panel, padx=10, pady=10)
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        for col in range(2):
            left.columnconfigure(col, weight=1)
        layout = (
            ("sound", 0, 0),
            ("main", 0, 1),
            ("sample", 1, 0),
            ("keys", 1, 1),
            ("timing", 2, 0),
            ("fx", 2, 1),
            ("fader", 3, 0),
            ("shift", 3, 1),
            ("minus", 4, 0),
            ("plus", 4, 1),
            ("metro", 5, 0),
        )
        for key, row, col in layout:
            button = _button(tk, left, ACTIONS[key].label, lambda value=key: self._face_action(value))
            button.grid(row=row, column=col, sticky="ew", padx=3, pady=3)
            self._face_buttons[key] = button

        utility = tk.Frame(left, bg=C.panel)
        utility.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        utility.columnconfigure(0, weight=1)
        utility.columnconfigure(1, weight=1)
        for index, (label, command) in enumerate(
            (
                ("CONNECT", self._connect_live),
                ("DISCONNECT", self._disconnect_live),
                ("REFRESH", self._refresh_report),
                ("DOCTOR", self._show_doctor),
                ("SYSEX", self._show_sysex_lab),
            )
        ):
            button = _button(tk, utility, label, command, small=True)
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=3, pady=3)

    def _build_face_center(self, parent) -> None:
        center = tk.Frame(parent, bg=C.panel, padx=10, pady=10)
        center.grid(row=1, column=1, sticky="nsew", padx=4)
        center.columnconfigure(0, weight=1)
        center.rowconfigure(1, weight=1)

        groups = tk.Frame(center, bg=C.panel)
        groups.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for index, group in enumerate(LANES):
            groups.columnconfigure(index, weight=1)
            button = _button(tk, groups, f"GROUP {group}", lambda value=group: self._face_group(value))
            button.grid(row=0, column=index, sticky="ew", padx=3)
            self._face_group_buttons[group] = button

        pads = tk.Frame(center, bg=C.soft, padx=8, pady=8)
        pads.grid(row=1, column=0, sticky="nsew")
        for row in range(3):
            pads.rowconfigure(row, weight=1, uniform="padrow")
        for col in range(4):
            pads.columnconfigure(col, weight=1, uniform="padcol")
        for index, label in enumerate(gui_module.PAD_LABELS):
            row, col = divmod(index, 4)
            button = tk.Button(
                pads,
                text=label,
                bg=C.pad,
                fg="#11120f",
                activebackground=C.amber,
                relief=tk.FLAT,
                bd=0,
                font=("Segoe UI", 18, "bold"),
                command=lambda pad=index: self._face_pad(pad),
            )
            button.grid(row=row, column=col, sticky="nsew", padx=5, pady=5)
            self._face_pad_buttons[index] = button

        transport = tk.Frame(center, bg=C.panel)
        transport.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        specs = (
            ("record", "REC", self._record, C.red),
            ("play", "PLAY", self._start, C.accent),
            ("continue", "CONT", self._continue, C.soft),
            ("stop", "STOP", self._stop, C.soft),
        )
        for index, (key, label, command, color) in enumerate(specs):
            transport.columnconfigure(index, weight=1)
            button = _button(tk, transport, label, command, bg=color)
            button.grid(row=0, column=index, sticky="ew", padx=3)
            self._face_buttons[key] = button

    def _build_face_right(self, parent) -> None:
        right = tk.Frame(parent, bg=C.panel, padx=10, pady=10)
        right.grid(row=1, column=2, sticky="nsew", padx=(8, 0))
        right.columnconfigure(0, weight=1)
        right.columnconfigure(1, weight=1)
        self.face_x = _slider(tk, right, "KNOB X", 0, 127, lambda v: self._face_cc(16, v, "knob x"))
        self.face_x.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.face_y = _slider(tk, right, "KNOB Y", 0, 127, lambda v: self._face_cc(17, v, "knob y"))
        self.face_y.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self.face_bpm = _slider(tk, right, "BPM", 40, 240, self._face_bpm)
        self.face_bpm.set(int(float(self.bpm.get())))
        self.face_bpm.grid(row=1, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        self.face_volume = _slider(tk, right, "VOLUME", 0, 127, lambda v: self._face_cc(7, v, "volume"))
        self.face_volume.set(96)
        self.face_volume.grid(row=2, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        self.face_fader = tk.Scale(
            right,
            label="FADER",
            from_=127,
            to=0,
            orient=tk.VERTICAL,
            length=180,
            bg=C.panel,
            fg=C.text,
            troughcolor=C.soft,
            highlightthickness=0,
            command=lambda v: self._send_mod_wheel(int(float(v))),
        )
        self.face_fader.set(96)
        self.face_fader.grid(row=3, column=0, columnspan=2, pady=(8, 0))

    def _build_face_timeline(self, parent) -> None:
        frame = tk.Frame(parent, bg=C.panel, padx=10, pady=8)
        frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        frame.columnconfigure(1, weight=1)
        for index, lane in enumerate(LANES):
            label = tk.Label(
                frame,
                text=lane,
                bg=C.panel,
                fg=C.accent,
                width=3,
                font=("Consolas", 10, "bold"),
            )
            label.grid(row=index, column=0, sticky="ns")
        self.face_timeline = tk.Canvas(frame, height=112, bg="#050604", highlightthickness=0)
        self.face_timeline.grid(row=0, column=1, rowspan=4, sticky="ew")

    def _face_action(self, key: str) -> None:
        action = ACTIONS[key]
        if key == "shift":
            self._face_shift = not self._face_shift
        elif key == "metro":
            self._face_metro = not self._face_metro
        else:
            self._face_mode = key
        value = 127
        if key == "shift":
            value = 127 if self._face_shift else 0
        if key == "metro":
            value = 127 if self._face_metro else 0
        if action.cc is not None:
            self._send_midi(MidiMessage.control_change(action.cc, value, channel=self.config.midi_channel))
        self._set_action(f"device {action.label.lower()}")
        self._refresh_hardware_face()

    def _face_group(self, group: str) -> None:
        self.group.set(group)
        self.session.selected_group = group
        self._send_midi(MidiMessage.program_change(GROUP_PROGRAMS[group], channel=self.config.midi_channel))
        self._set_action(f"group {group}")
        self._refresh_hardware_face()

    def _face_pad(self, pad_index: int) -> None:
        self._mark_face_step(self.group.get())
        self._trigger_pad(pad_index)
        self._refresh_hardware_face()

    def _face_cc(self, control: int, value, label: str) -> None:
        midi_value = int(float(value))
        self._send_midi(MidiMessage.control_change(control, midi_value, channel=self.config.midi_channel))
        self._set_action(f"{label} {midi_value}")
        self._refresh_hardware_face()

    def _face_bpm(self, value) -> None:
        self._set_bpm(float(value))
        self._face_mode = "tempo"
        self._refresh_hardware_face()

    def _send_midi(self, message: MidiMessage) -> bool:
        result = original_send_midi(self, message)
        if result:
            self._observe_face_message(message)
        return result

    def _queue_midi_input(self, message: MidiMessage) -> None:
        self._observe_face_message(message)
        original_queue_midi_input(self, message)

    def _observe_face_message(self, message: MidiMessage) -> None:
        if message.kind == "clock":
            self._face_current_step = self.runtime_state.clock_ticks % STEPS
        elif message.kind == "note_on" and message.note is not None and message.velocity:
            lane = _lane_for_note(message.note)
            if lane:
                self.group.set(lane)
                self._mark_face_step(lane)
        elif message.kind == "program_change" and message.program is not None:
            group = _group_for_program(message.program)
            if group:
                self.group.set(group)
        elif message.kind == "control_change" and message.control is not None:
            self._observe_face_cc(int(message.control), int(message.value or 0))
        if hasattr(self, "_refresh_hardware_face"):
            self._refresh_hardware_face()

    def _observe_face_cc(self, control: int, value: int) -> None:
        mapping = {20: "sound", 21: "main", 22: "sample", 23: "keys", 24: "timing", 25: "fx", 26: "fader"}
        if control in mapping and value:
            self._face_mode = mapping[control]
        elif control == 27:
            self._face_shift = bool(value)
        elif control == 87:
            self._face_metro = bool(value)

    def _mark_face_step(self, lane: str) -> None:
        if lane not in self._face_lanes:
            return
        step = int(self.runtime_state.clock_ticks % STEPS)
        self._face_current_step = step
        self._face_lanes[lane][step] = True

    def _refresh_hardware_face_loop(self) -> None:
        if hasattr(self, "face_timeline"):
            self._refresh_hardware_face()
        self.root.after(120, self._refresh_hardware_face_loop)

    def _refresh_hardware_face(self) -> None:
        if not hasattr(self, "face_selection"):
            return
        group = self.group.get()
        self.face_selection.configure(
            text=(
                f"MODE {self._face_mode.upper()}  GROUP {group}  "
                f"SHIFT {'ON' if self._face_shift else 'OFF'}  "
                f"METRO {'ON' if self._face_metro else 'OFF'}"
            )
        )
        live = "LIVE" if self.live_output_port else "DRY"
        self.face_safety.configure(text=f"{live} / {self.app_settings.access_mode} / CC mirror safe")
        for key, button in self._face_buttons.items():
            active = key == self._face_mode or (key == "shift" and self._face_shift) or (key == "metro" and self._face_metro)
            _set_active(button, active)
        for lane, button in self._face_group_buttons.items():
            _set_active(button, lane == group)
        self._draw_face_timeline()

    def _draw_face_timeline(self) -> None:
        canvas = self.face_timeline
        canvas.delete("all")
        width = max(canvas.winfo_width(), 640)
        lane_height = 24
        label_width = 0
        step_gap = 2
        step_width = max(4, int((width - label_width - step_gap * (STEPS + 1)) / STEPS))
        current = int(self.runtime_state.clock_ticks % STEPS)
        for lane_index, lane in enumerate(LANES):
            y0 = lane_index * lane_height + 4
            y1 = y0 + 16
            for step in range(STEPS):
                x0 = step_gap + step * (step_width + step_gap)
                x1 = x0 + step_width
                fill = C.soft
                if self._face_lanes[lane][step]:
                    fill = C.amber if lane == self.group.get() else "#5f6840"
                if step == current:
                    fill = C.accent
                canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline="")
        canvas.create_text(6, 100, anchor="nw", fill=C.dim, font=("Consolas", 8), text="A/B/C/D composition mirror from app/device MIDI events")

    app_class._build_mode_strip = _build_mode_strip
    app_class._build_main_controls = _build_main_controls
    app_class._build_face_screen = _build_face_screen
    app_class._build_face_left = _build_face_left
    app_class._build_face_center = _build_face_center
    app_class._build_face_right = _build_face_right
    app_class._build_face_timeline = _build_face_timeline
    app_class._face_action = _face_action
    app_class._face_group = _face_group
    app_class._face_pad = _face_pad
    app_class._face_cc = _face_cc
    app_class._face_bpm = _face_bpm
    app_class._send_midi = _send_midi
    app_class._queue_midi_input = _queue_midi_input
    app_class._observe_face_message = _observe_face_message
    app_class._observe_face_cc = _observe_face_cc
    app_class._mark_face_step = _mark_face_step
    app_class._refresh_hardware_face_loop = _refresh_hardware_face_loop
    app_class._refresh_hardware_face = _refresh_hardware_face
    app_class._draw_face_timeline = _draw_face_timeline
    app_class._hardware_face_patch_installed = True


def _button(tk, parent, label: str, command, *, bg: str | None = None, width: int = 8, small: bool = False):
    return tk.Button(
        parent,
        text=label,
        command=command,
        bg=bg or C.soft,
        fg=C.text,
        activebackground=C.accent,
        activeforeground="#11120f",
        relief=tk.FLAT,
        bd=0,
        width=width,
        padx=6,
        pady=4 if small else 8,
        font=("Segoe UI", 8 if small else 10, "bold"),
    )


def _slider(tk, parent, label: str, low: int, high: int, command):
    return tk.Scale(
        parent,
        label=label,
        from_=low,
        to=high,
        orient=tk.HORIZONTAL,
        showvalue=True,
        bg=C.panel,
        fg=C.text,
        troughcolor=C.soft,
        highlightthickness=0,
        command=command,
    )


def _set_active(button, active: bool) -> None:
    if active:
        button.configure(bg=C.accent, fg="#11120f", relief="sunken")
    else:
        button.configure(bg=C.soft, fg=C.text, relief="flat")


def _lane_for_note(note: int) -> str | None:
    if 36 <= note <= 47:
        return "A"
    if 48 <= note <= 59:
        return "B"
    if 60 <= note <= 71:
        return "C"
    if 72 <= note <= 83:
        return "D"
    return None


def _group_for_program(program: int) -> str | None:
    reverse = {value: key for key, value in GROUP_PROGRAMS.items()}
    return reverse.get(program)
