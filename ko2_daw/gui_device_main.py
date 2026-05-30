"""Primary EP-133-style device layout for the main GUI window."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ko2_daw.midi import MidiMessage


@dataclass(frozen=True)
class DeviceControl:
    key: str
    label: str
    kind: str
    row: int
    column: int
    command: str | None = None
    midi_cc: int | None = None


GROUP_PROGRAMS = {"A": 0, "B": 1, "C": 2, "D": 3}
LANES = ("A", "B", "C", "D")
STEPS = 64

MODE_CONTROLS = {
    "sound": DeviceControl("sound", "SOUND", "mode", 0, 0, "sound", 20),
    "edit": DeviceControl("edit", "EDIT", "mode", 1, 0, "edit", 21),
    "main": DeviceControl("main", "MAIN", "mode", 0, 1, "main", 22),
    "commit": DeviceControl("commit", "COMMIT", "mode", 1, 1, "commit", 23),
    "tempo": DeviceControl("tempo", "TEMPO", "mode", 0, 2, "tempo", 24),
    "loop": DeviceControl("loop", "LOOP", "mode", 1, 2, "loop", 25),
    "sample": DeviceControl("sample", "SAMPLE", "mode", 0, 3, "sample", 26),
    "chop": DeviceControl("chop", "CHOP", "mode", 1, 3, "chop", 27),
    "timing": DeviceControl("timing", "TIMING", "mode", 0, 4, "timing", 28),
    "correct": DeviceControl("correct", "CORRECT", "mode", 1, 4, "correct", 29),
    "keys": DeviceControl("keys", "KEYS", "mode", 0, 5, "keys", 30),
    "shift": DeviceControl("shift", "SHIFT", "modifier", 1, 5, "shift", 31),
    "fx": DeviceControl("fx", "FX", "mode", 2, 4, "fx", 32),
    "output": DeviceControl("output", "OUTPUT", "mode", 3, 4, "output", 33),
    "erase": DeviceControl("erase", "ERASE", "mode", 2, 5, "erase", 34),
    "system": DeviceControl("system", "SYSTEM", "mode", 3, 5, "system", 35),
}

KEYPAD_LAYOUT = [
    ["A", "B", "C", "D"],
    ["7", "8", "9", "ENTER"],
    ["4", "5", "6", "."],
    ["1", "2", "3", "0"],
]

PAD_INDEX_BY_LABEL = {
    ".": 0,
    "0": 1,
    "ENTER": 2,
    "1": 3,
    "2": 4,
    "3": 5,
    "4": 6,
    "5": 7,
    "6": 8,
    "7": 9,
    "8": 10,
    "9": 11,
}


class Palette:
    body = "#d8d4c8"
    panel = "#bdb7aa"
    dark = "#171915"
    soft = "#efeadf"
    key = "#1f211d"
    key_text = "#f5f0e4"
    pale_key = "#f5f0e4"
    pale_text = "#11120f"
    orange = "#f36f21"
    green = "#d7f58a"
    amber = "#f2c230"
    red = "#dc493a"


def apply_device_main_patch(gui_module: Any) -> None:
    """Make the main window a device view plus settings and timeline."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_device_main_patch_installed", False):
        return

    tk = gui_module.tk
    ttk = gui_module.ttk
    original_init = app_class.__init__
    original_send_midi = app_class._send_midi
    original_queue_midi_input = app_class._queue_midi_input

    def __init__(self, root):
        self.device_controls: dict[str, dict[str, object]] = {}
        self.device_buttons: dict[str, Any] = {}
        self.device_steps = {lane: [False] * STEPS for lane in LANES}
        self.device_mode = "main"
        self.device_shift = False
        self.device_last_control = "none"
        self.device_last_source = "app"
        self.device_current_step = 0
        original_init(self, root)

    def _build_mode_strip(self, parent) -> None:
        self.device_mode_strip_removed = True

    def _build_main_controls(self, parent) -> None:
        shell = tk.Frame(parent, bg=Palette.body)
        shell.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        shell.columnconfigure(0, weight=1)
        shell.columnconfigure(1, weight=3)
        shell.columnconfigure(2, weight=1)
        shell.rowconfigure(0, weight=1)

        self._build_left_hardware_area(shell)
        self._build_center_hardware_area(shell)
        self._build_right_hardware_area(shell)
        self._refresh_device_view()
        self.root.after(120, self._device_tick)

    def _build_left_hardware_area(self, parent) -> None:
        left = tk.Frame(parent, bg=Palette.panel, padx=10, pady=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        for column in range(2):
            left.columnconfigure(column, weight=1)

        volume = self._make_slider(
            left,
            "VOLUME",
            0,
            127,
            lambda value: self._device_cc("volume", 7, value),
        )
        volume.set(96)
        volume.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self._register_control("volume", "VOLUME", "continuous")

        fader = tk.Scale(
            left,
            label="FADER",
            from_=127,
            to=0,
            orient=tk.VERTICAL,
            length=210,
            bg=Palette.panel,
            fg=Palette.pale_text,
            troughcolor=Palette.dark,
            highlightthickness=0,
            command=lambda value: self._device_fader(value),
        )
        fader.set(96)
        fader.grid(row=1, column=0, rowspan=4, sticky="ns", padx=(0, 8))
        self._register_control("fader", "FADER", "continuous")

        for index, key in enumerate(("shift", "keys", "sound", "edit")):
            row = 1 + index
            button = self._make_button(
                left,
                MODE_CONTROLS[key].label,
                lambda name=key: self._device_mode_button(name),
            )
            button.grid(row=row, column=1, sticky="ew", pady=3)
            self.device_buttons[key] = button
            self._register_control(key, MODE_CONTROLS[key].label, MODE_CONTROLS[key].kind)

    def _build_center_hardware_area(self, parent) -> None:
        center = tk.Frame(parent, bg=Palette.panel, padx=10, pady=10)
        center.grid(row=0, column=1, sticky="nsew")
        for column in range(4):
            center.columnconfigure(column, weight=1, uniform="center")
        for row in range(7):
            center.rowconfigure(row, weight=1)

        top_modes = (
            ("main", "commit"),
            ("tempo", "loop"),
            ("sample", "chop"),
            ("timing", "correct"),
        )
        for column, pair in enumerate(top_modes):
            stack = tk.Frame(center, bg=Palette.panel)
            stack.grid(row=0, column=column, sticky="nsew", padx=4, pady=(0, 8))
            for _row, key in enumerate(pair):
                control = MODE_CONTROLS[key]
                button = self._make_button(
                    stack,
                    control.label,
                    lambda name=key: self._device_mode_button(name),
                    orange=key in {"commit", "sample"},
                )
                button.pack(fill=tk.BOTH, expand=True, pady=2)
                self.device_buttons[key] = button
                self._register_control(key, control.label, control.kind)

        for row, labels in enumerate(KEYPAD_LAYOUT, start=1):
            for column, label in enumerate(labels):
                key = f"group_{label.lower()}" if label in GROUP_PROGRAMS else f"pad_{label}"
                command = self._device_group if label in GROUP_PROGRAMS else self._device_pad
                button = self._make_button(
                    center,
                    label,
                    lambda value=label, callback=command: callback(value),
                    pale=label in GROUP_PROGRAMS,
                )
                button.grid(row=row, column=column, sticky="nsew", padx=5, pady=5)
                self.device_buttons[key] = button
                kind = "group" if label in GROUP_PROGRAMS else "pad"
                self._register_control(key, label, kind)

        transport = tk.Frame(center, bg=Palette.panel)
        transport.grid(row=5, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        for column in range(4):
            transport.columnconfigure(column, weight=1)
        transport_specs = (
            ("record", "RECORD", self._record, Palette.orange),
            ("play", "PLAY", self._start, Palette.green),
            ("stop", "STOP", self._stop, Palette.soft),
            ("panic", "PANIC", self._panic, Palette.dark),
        )
        for column, (key, label, command, color) in enumerate(transport_specs):
            button = self._make_button(
                transport,
                label,
                lambda name=key, cmd=command: self._device_transport(name, cmd),
                bg=color,
            )
            button.grid(row=0, column=column, sticky="ew", padx=4)
            self.device_buttons[key] = button
            self._register_control(key, label, "transport")

        self.device_status = tk.Label(
            center,
            bg=Palette.dark,
            fg=Palette.green,
            font=("Consolas", 11, "bold"),
            anchor="w",
            padx=8,
            pady=6,
        )
        self.device_status.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(8, 0))

    def _build_right_hardware_area(self, parent) -> None:
        right = tk.Frame(parent, bg=Palette.panel, padx=10, pady=10)
        right.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        right.columnconfigure(0, weight=1)
        right.columnconfigure(1, weight=1)

        x_knob = self._make_slider(
            right,
            "X / GAIN",
            0,
            127,
            lambda value: self._device_cc("x", 16, value),
        )
        x_knob.grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 8))
        self._register_control("x", "X", "knob")

        y_knob = self._make_slider(
            right,
            "Y / SWING",
            0,
            127,
            lambda value: self._device_cc("y", 17, value),
        )
        y_knob.grid(row=0, column=1, sticky="ew", padx=4, pady=(0, 8))
        self._register_control("y", "Y", "knob")

        bpm = self._make_slider(right, "BPM", 40, 240, lambda value: self._device_bpm(value))
        bpm.set(int(float(self.bpm.get())))
        bpm.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self._register_control("bpm", "BPM", "knob")

        for index, key in enumerate(("fx", "output", "erase", "system"), start=2):
            control = MODE_CONTROLS[key]
            button = self._make_button(
                right,
                control.label,
                lambda name=key: self._device_mode_button(name),
            )
            button.grid(row=index, column=0, columnspan=2, sticky="ew", pady=3)
            self.device_buttons[key] = button
            self._register_control(key, control.label, control.kind)

        open_files = self._make_button(right, "DEVICE FILES", self._show_device_file_explorer, pale=True)
        open_files.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(12, 3))
        self.device_buttons["device_files"] = open_files
        self._register_control("device_files", "DEVICE FILES", "window")

        protocol = self._make_button(right, "PROTOCOL", self._show_protocol_window, pale=True)
        protocol.grid(row=7, column=0, columnspan=2, sticky="ew", pady=3)
        self.device_buttons["protocol"] = protocol
        self._register_control("protocol", "PROTOCOL", "window")

        connect = self._make_button(right, "CONNECT", self._connect_live, pale=True)
        connect.grid(row=8, column=0, sticky="ew", padx=(0, 3), pady=(12, 3))
        disconnect = self._make_button(right, "DISCONNECT", self._disconnect_live, pale=True)
        disconnect.grid(row=8, column=1, sticky="ew", padx=(3, 0), pady=(12, 3))
        self.device_buttons["connect"] = connect
        self.device_buttons["disconnect"] = disconnect
        self._register_control("connect", "CONNECT", "window")
        self._register_control("disconnect", "DISCONNECT", "window")

    def _build_workspace(self, parent) -> None:
        tabs = ttk.Notebook(parent)
        tabs.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        self._tip(
            tabs,
            "Main workspace: timeline, settings, and activity. Device files open only in their own window.",
        )

        timeline = tk.Frame(tabs, bg=Palette.body, padx=8, pady=8)
        settings = tk.Frame(tabs, bg=Palette.body, padx=6, pady=6)
        log_tab = tk.Frame(tabs, bg=Palette.body, padx=6, pady=6)
        tabs.add(timeline, text="Timeline")
        tabs.add(settings, text="Settings")
        tabs.add(log_tab, text="Log")

        self._build_device_timeline(timeline)
        self._build_settings(settings)
        self._build_log(log_tab)

        self._hidden_file_root = tk.Frame(parent)
        self._build_hardware_files(self._hidden_file_root)

    def _build_device_timeline(self, parent) -> None:
        parent.columnconfigure(1, weight=1)
        for row in range(4):
            parent.rowconfigure(row, weight=1)
        self.timeline_canvas = tk.Canvas(parent, height=150, bg="#050604", highlightthickness=0)
        self.timeline_canvas.grid(row=0, column=1, rowspan=4, sticky="nsew")
        for index, lane in enumerate(LANES):
            label = tk.Label(
                parent,
                text=lane,
                bg=Palette.body,
                fg=Palette.dark,
                font=("Consolas", 12, "bold"),
            )
            label.grid(row=index, column=0, sticky="ns", padx=(0, 6))
        self.timeline_info = tk.Label(parent, bg=Palette.body, fg=Palette.dark, anchor="w")
        self.timeline_info.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._draw_device_timeline()

    def _register_control(self, key: str, label: str, kind: str) -> None:
        self.device_controls[key] = {
            "label": label,
            "kind": kind,
            "state": "idle",
            "source": "none",
        }

    def _mark_control(self, key: str, source: str, state: str = "active") -> None:
        if key not in self.device_controls:
            self._register_control(key, key.upper(), "external")
        record = self.device_controls[key]
        record["state"] = state
        record["source"] = source
        self.device_last_control = str(record["label"])
        self.device_last_source = source
        self._refresh_device_view()

    def _device_mode_button(self, key: str) -> None:
        control = MODE_CONTROLS[key]
        if key == "shift":
            self.device_shift = not self.device_shift
        else:
            self.device_mode = key
        value = 127 if key != "shift" or self.device_shift else 0
        if control.midi_cc is not None:
            self._send_midi(
                MidiMessage.control_change(control.midi_cc, value, channel=self.config.midi_channel)
            )
        self._mark_control(key, "app")
        self._set_action(f"device button {control.label}")

    def _device_group(self, group: str) -> None:
        self.group.set(group)
        self.session.selected_group = group
        self._send_midi(MidiMessage.program_change(GROUP_PROGRAMS[group], channel=self.config.midi_channel))
        self._mark_control(f"group_{group.lower()}", "app")
        self._set_action(f"group {group}")

    def _device_pad(self, label: str) -> None:
        pad_index = PAD_INDEX_BY_LABEL[label]
        self._trigger_pad(pad_index)
        self._mark_current_step(self.group.get())
        self._mark_control(f"pad_{label}", "app")

    def _device_transport(self, key: str, command: Callable[[], None]) -> None:
        command()
        self._mark_control(key, "app")

    def _device_cc(self, key: str, control: int, value) -> None:
        midi_value = int(float(value))
        self._send_midi(MidiMessage.control_change(control, midi_value, channel=self.config.midi_channel))
        self._mark_control(key, "app", str(midi_value))
        self._set_action(f"{key} {midi_value}")

    def _device_fader(self, value) -> None:
        midi_value = int(float(value))
        self._send_mod_wheel(midi_value)
        self._mark_control("fader", "app", str(midi_value))

    def _device_bpm(self, value) -> None:
        bpm = float(value)
        self._set_bpm(bpm)
        self.device_mode = "tempo"
        self._mark_control("bpm", "app", str(int(round(bpm))))

    def _send_midi(self, message: MidiMessage) -> bool:
        result = original_send_midi(self, message)
        if result:
            self._observe_device_message(message, "app")
        return result

    def _queue_midi_input(self, message: MidiMessage) -> None:
        self._observe_device_message(message, "device")
        original_queue_midi_input(self, message)

    def _observe_device_message(self, message: MidiMessage, source: str) -> None:
        if message.kind == "note_on" and message.note is not None and message.velocity:
            lane, pad = self._lane_pad_from_note(message.note)
            if lane and pad:
                self.group.set(lane)
                self._mark_current_step(lane)
                self._mark_control(f"pad_{pad}", source)
        elif message.kind == "program_change" and message.program is not None:
            group = self._group_from_program(message.program)
            if group:
                self.group.set(group)
                self._mark_control(f"group_{group.lower()}", source)
        elif message.kind == "control_change" and message.control is not None:
            self._observe_device_cc(int(message.control), int(message.value or 0), source)
        elif message.kind in {"start", "continue", "stop", "clock"}:
            if message.kind == "clock":
                self.device_current_step = int(self.runtime_state.clock_ticks % STEPS)
            self._mark_control(message.kind, source)

    def _observe_device_cc(self, control: int, value: int, source: str) -> None:
        cc_to_key = {
            control_spec.midi_cc: key
            for key, control_spec in MODE_CONTROLS.items()
            if control_spec.midi_cc is not None
        }
        if control in cc_to_key:
            key = cc_to_key[control]
            if key == "shift":
                self.device_shift = bool(value)
            else:
                self.device_mode = key
            self._mark_control(key, source, str(value))
            return
        if control == 1:
            self._mark_control("fader", source, str(value))
        elif control == 7:
            self._mark_control("volume", source, str(value))
        elif control == 16:
            self._mark_control("x", source, str(value))
        elif control == 17:
            self._mark_control("y", source, str(value))

    def _lane_pad_from_note(self, note: int) -> tuple[str | None, str | None]:
        for lane, notes in gui_module.PAD_NOTES.items():
            if note in notes:
                index = notes.index(note)
                return lane, gui_module.PAD_LABELS[index]
        return None, None

    def _group_from_program(self, program: int) -> str | None:
        reverse = {value: key for key, value in GROUP_PROGRAMS.items()}
        return reverse.get(program)

    def _mark_current_step(self, lane: str) -> None:
        if lane not in self.device_steps:
            return
        step = int(self.runtime_state.clock_ticks % STEPS)
        self.device_current_step = step
        self.device_steps[lane][step] = True
        self._draw_device_timeline()

    def _refresh_device_view(self) -> None:
        if hasattr(self, "device_status"):
            self.device_status.configure(
                text=(
                    f"MODE {self.device_mode.upper()}   GROUP {self.group.get()}   "
                    f"SHIFT {'ON' if self.device_shift else 'OFF'}   "
                    f"LAST {self.device_last_control} [{self.device_last_source}]"
                )
            )
        for key, button in getattr(self, "device_buttons", {}).items():
            active = False
            if key == self.device_mode:
                active = True
            if key == "shift" and self.device_shift:
                active = True
            if key.startswith("group_") and key[-1:].upper() == self.group.get():
                active = True
            record = self.device_controls.get(key)
            if record and record.get("source") == "device":
                active = True
            self._set_button_active(button, active)
        self._draw_device_timeline()

    def _device_tick(self) -> None:
        self.device_current_step = int(self.runtime_state.clock_ticks % STEPS)
        self._refresh_device_view()
        self.root.after(120, self._device_tick)

    def _draw_device_timeline(self) -> None:
        canvas = getattr(self, "timeline_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        width = max(canvas.winfo_width(), 720)
        lane_height = 30
        gap = 2
        step_width = max(4, int((width - gap * (STEPS + 1)) / STEPS))
        current = int(self.runtime_state.clock_ticks % STEPS)
        for lane_index, lane in enumerate(LANES):
            y0 = 8 + lane_index * lane_height
            y1 = y0 + 20
            for step in range(STEPS):
                x0 = gap + step * (step_width + gap)
                x1 = x0 + step_width
                fill = "#2a2d24"
                if self.device_steps[lane][step]:
                    fill = Palette.orange if lane == self.group.get() else "#69724b"
                if step == current:
                    fill = Palette.green
                canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline="")
        if hasattr(self, "timeline_info"):
            self.timeline_info.configure(
                text=(
                    f"A/B/C/D composition mirror | current step {current + 1}/{STEPS} | "
                    "source: app actions + observable incoming MIDI"
                )
            )

    def _make_button(
        self,
        parent,
        label: str,
        command,
        *,
        bg: str | None = None,
        orange: bool = False,
        pale: bool = False,
    ):
        background = bg or (Palette.orange if orange else Palette.pale_key if pale else Palette.key)
        foreground = (
            Palette.pale_text
            if background in {Palette.orange, Palette.pale_key, Palette.green, Palette.soft}
            else Palette.key_text
        )
        return tk.Button(
            parent,
            text=label,
            command=command,
            bg=background,
            fg=foreground,
            activebackground=Palette.amber,
            activeforeground=Palette.pale_text,
            relief=tk.FLAT,
            bd=0,
            padx=8,
            pady=8,
            font=("Segoe UI", 10, "bold"),
        )

    def _make_slider(self, parent, label: str, low: int, high: int, command):
        return tk.Scale(
            parent,
            label=label,
            from_=low,
            to=high,
            orient=tk.HORIZONTAL,
            bg=Palette.panel,
            fg=Palette.pale_text,
            troughcolor=Palette.dark,
            highlightthickness=0,
            command=command,
        )

    def _set_button_active(self, button, active: bool) -> None:
        if active:
            button.configure(bg=Palette.green, fg=Palette.pale_text, relief="sunken")
            return
        text = str(button.cget("text"))
        if text in {"A", "B", "C", "D", "DEVICE FILES", "PROTOCOL", "CONNECT", "DISCONNECT"}:
            button.configure(bg=Palette.pale_key, fg=Palette.pale_text, relief="flat")
        elif text in {"COMMIT", "SAMPLE", "RECORD"}:
            button.configure(bg=Palette.orange, fg=Palette.pale_text, relief="flat")
        else:
            button.configure(bg=Palette.key, fg=Palette.key_text, relief="flat")

    app_class.__init__ = __init__
    app_class._build_mode_strip = _build_mode_strip
    app_class._build_main_controls = _build_main_controls
    app_class._build_left_hardware_area = _build_left_hardware_area
    app_class._build_center_hardware_area = _build_center_hardware_area
    app_class._build_right_hardware_area = _build_right_hardware_area
    app_class._build_workspace = _build_workspace
    app_class._build_device_timeline = _build_device_timeline
    app_class._register_control = _register_control
    app_class._mark_control = _mark_control
    app_class._device_mode_button = _device_mode_button
    app_class._device_group = _device_group
    app_class._device_pad = _device_pad
    app_class._device_transport = _device_transport
    app_class._device_cc = _device_cc
    app_class._device_fader = _device_fader
    app_class._device_bpm = _device_bpm
    app_class._send_midi = _send_midi
    app_class._queue_midi_input = _queue_midi_input
    app_class._observe_device_message = _observe_device_message
    app_class._observe_device_cc = _observe_device_cc
    app_class._lane_pad_from_note = _lane_pad_from_note
    app_class._group_from_program = _group_from_program
    app_class._mark_current_step = _mark_current_step
    app_class._refresh_device_view = _refresh_device_view
    app_class._device_tick = _device_tick
    app_class._draw_device_timeline = _draw_device_timeline
    app_class._make_button = _make_button
    app_class._make_slider = _make_slider
    app_class._set_button_active = _set_button_active
    app_class._device_main_patch_installed = True
