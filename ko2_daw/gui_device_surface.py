"""Modern KO II device-surface extension for the Tkinter GUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ko2_daw.midi import MidiMessage


@dataclass(frozen=True)
class DeviceAction:
    """GUI action that can optionally send a MIDI CC mirror command."""

    key: str
    label: str
    cc: int | None = None
    value: int = 127
    mode: str | None = None


DEVICE_ACTIONS = {
    "sound": DeviceAction("sound", "SOUND", cc=20, mode="sound"),
    "main": DeviceAction("main", "MAIN", cc=21, mode="main"),
    "sample": DeviceAction("sample", "SAMPLE", cc=22, mode="sample"),
    "keys": DeviceAction("keys", "KEYS", cc=23, mode="keys"),
    "timing": DeviceAction("timing", "TIMING", cc=24, mode="timing"),
    "tempo": DeviceAction("tempo", "TEMPO", cc=25, mode="tempo"),
    "fx": DeviceAction("fx", "FX", cc=26, mode="fx"),
    "shift": DeviceAction("shift", "SHIFT", cc=27, mode="shift"),
    "metronome": DeviceAction("metronome", "METRO", cc=28, mode="metronome"),
    "erase": DeviceAction("erase", "ERASE", cc=29, mode="erase"),
    "copy": DeviceAction("copy", "COPY", cc=30, mode="copy"),
    "scene": DeviceAction("scene", "SCENE", cc=31, mode="scene"),
    "pattern": DeviceAction("pattern", "PATTERN", cc=33, mode="pattern"),
}

GROUP_PROGRAMS = {"A": 0, "B": 1, "C": 2, "D": 3}


class ModernPalette:
    bg = "#11120f"
    panel = "#1c1d19"
    panel_soft = "#272820"
    text = "#f3f1de"
    dim = "#a9aa9a"
    accent = "#d7f58a"
    amber = "#f2c230"
    red = "#dc493a"


def apply_device_surface_patch(gui_module: Any) -> None:
    """Patch KO2DawApp with modern controls, timeline, and mirrored device state."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_device_surface_patch_installed", False):
        return

    tk = gui_module.tk

    original_init = app_class.__init__
    original_set_action = app_class._set_action
    original_queue_midi_input = app_class._queue_midi_input
    original_send_mod_wheel = app_class._send_mod_wheel
    original_set_bpm = app_class._set_bpm

    def __init__(self, root):
        self._device_surface_ready = False
        self._device_action_buttons = {}
        self._device_group_buttons = {}
        self._device_mode = "main"
        self._device_track = "unknown"
        self._device_effect = "none"
        self._device_volume = 96
        self._device_metronome = False
        original_init(self, root)
        self._install_device_surface()

    def _install_device_surface(self) -> None:
        if self._device_surface_ready:
            return
        self._device_surface_ready = True
        self.device_surface = tk.Frame(self.root, bg=ModernPalette.bg, padx=10, pady=8)
        self.device_surface.pack(side=tk.BOTTOM, fill=tk.X)

        top = tk.Frame(self.device_surface, bg=ModernPalette.bg)
        top.pack(fill=tk.X)

        self.device_selection_label = tk.Label(
            top,
            bg=ModernPalette.panel,
            fg=ModernPalette.accent,
            font=("Consolas", 11, "bold"),
            padx=10,
            pady=6,
            anchor="w",
        )
        self.device_selection_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.device_clock_label = tk.Label(
            top,
            bg=ModernPalette.panel,
            fg=ModernPalette.text,
            font=("Consolas", 11),
            padx=10,
            pady=6,
            width=28,
        )
        self.device_clock_label.pack(side=tk.RIGHT)

        controls = tk.Frame(self.device_surface, bg=ModernPalette.bg)
        controls.pack(fill=tk.X, pady=(8, 0))

        left = tk.Frame(controls, bg=ModernPalette.bg)
        left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        for action_key in (
            "sound",
            "main",
            "sample",
            "keys",
            "timing",
            "tempo",
            "fx",
            "shift",
            "metronome",
            "erase",
            "copy",
            "scene",
            "pattern",
        ):
            action = DEVICE_ACTIONS[action_key]
            button = _surface_button(
                tk,
                left,
                action.label,
                lambda key=action_key: self._trigger_device_surface_action(key),
            )
            button.pack(side=tk.LEFT, padx=2, pady=2)
            self._device_action_buttons[action_key] = button

        groups = tk.Frame(controls, bg=ModernPalette.bg)
        groups.pack(side=tk.LEFT, padx=(8, 0))
        for group in "ABCD":
            button = _surface_button(
                tk,
                groups,
                f"G{group}",
                lambda value=group: self._select_device_group(value),
                width=4,
            )
            button.pack(side=tk.LEFT, padx=2, pady=2)
            self._device_group_buttons[group] = button

        transport = tk.Frame(controls, bg=ModernPalette.bg)
        transport.pack(side=tk.LEFT, padx=(8, 0))
        transport_specs: tuple[tuple[str, Callable[[], None], str], ...] = (
            ("REC", self._record, ModernPalette.red),
            ("PLAY", self._start, ModernPalette.accent),
            ("CONT", self._continue, ModernPalette.amber),
            ("STOP", self._stop, ModernPalette.panel_soft),
        )
        for label, command, color in transport_specs:
            button = _surface_button(tk, transport, label, command, bg=color)
            button.pack(side=tk.LEFT, padx=2, pady=2)

        sliders = tk.Frame(self.device_surface, bg=ModernPalette.bg)
        sliders.pack(fill=tk.X, pady=(8, 0))
        self.device_timeline = tk.Canvas(
            sliders,
            height=46,
            bg="#050604",
            highlightthickness=0,
        )
        self.device_timeline.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self.device_volume_frame, self.device_volume_scale = _surface_scale(
            tk,
            sliders,
            "VOL",
            0,
            127,
            self._send_device_volume,
        )
        self.device_volume_scale.set(self._device_volume)
        self.device_volume_frame.pack(side=tk.LEFT, padx=4)

        self.device_bpm_frame, self.device_bpm_scale = _surface_scale(
            tk,
            sliders,
            "BPM",
            40,
            240,
            self._set_bpm,
        )
        self.device_bpm_scale.set(int(float(self.bpm.get())))
        self.device_bpm_frame.pack(side=tk.LEFT, padx=4)

        self._update_device_surface()
        self.root.after(100, self._tick_device_timeline)

    def _trigger_device_surface_action(self, action_key: str) -> None:
        action = DEVICE_ACTIONS[action_key]
        if action.mode:
            self._device_mode = action.mode
        if action_key == "metronome":
            self._device_metronome = not self._device_metronome
            value = 127 if self._device_metronome else 0
        else:
            value = action.value
        if action.cc is not None:
            self._send_midi(MidiMessage.control_change(action.cc, value, channel=self.config.midi_channel))
        original_set_action(self, f"device {action.label.lower()}")
        self._update_device_surface()

    def _select_device_group(self, group: str) -> None:
        self.group.set(group)
        self.session.selected_group = group
        self._device_track = f"group {group}"
        self._send_midi(MidiMessage.program_change(GROUP_PROGRAMS[group], channel=self.config.midi_channel))
        original_set_action(self, f"group {group}")
        self._update_device_surface()

    def _send_device_volume(self, value) -> None:
        volume = int(float(value))
        self._device_volume = volume
        self._send_midi(MidiMessage.control_change(7, volume, channel=self.config.midi_channel))
        original_set_action(self, f"volume {volume}")
        self._update_device_surface()

    def _send_mod_wheel(self, value: int) -> None:
        self._device_effect = f"fader {int(value)}"
        original_send_mod_wheel(self, value)
        self._update_device_surface()

    def _set_bpm(self, value: float) -> None:
        original_set_bpm(self, value)
        self._device_mode = "tempo"
        self._update_device_surface()

    def _set_action(self, text: str) -> None:
        normalized = str(text).strip().lower()
        if normalized in DEVICE_ACTIONS:
            self._trigger_device_surface_action(normalized)
            return
        if normalized.startswith("group ") and normalized[-1:].upper() in GROUP_PROGRAMS:
            self._select_device_group(normalized[-1:].upper())
            return
        original_set_action(self, text)
        if hasattr(self, "_update_device_surface"):
            self._update_device_surface()

    def _queue_midi_input(self, message: MidiMessage) -> None:
        if message.kind == "note_on" and message.note is not None and message.velocity:
            self._device_track = _group_for_note(message.note)
        elif message.kind == "program_change" and message.program is not None:
            self._device_track = f"program {message.program}"
        elif message.kind == "control_change" and message.control is not None:
            if message.control == 1:
                self._device_effect = f"fader {message.value}"
            elif message.control == 7:
                self._device_volume = int(message.value or 0)
            elif message.control in {20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 33}:
                self._device_mode = _mode_for_cc(message.control)
        original_queue_midi_input(self, message)
        if hasattr(self, "_update_device_surface"):
            self._update_device_surface()

    def _update_device_surface(self) -> None:
        if not getattr(self, "_device_surface_ready", False):
            return
        group = self.group.get()
        active_notes = len(getattr(self.runtime_state, "active_notes", {}))
        self.device_selection_label.configure(
            text=(
                f"MODE {self._device_mode.upper()}   GROUP {group}   "
                f"TRACK {self._device_track}   FX {self._device_effect}   "
                f"VOL {self._device_volume}"
            )
        )
        self.device_clock_label.configure(
            text=(
                f"{self.runtime_state.transport.upper()}  "
                f"CLK {self.runtime_state.clock_ticks:06d}  "
                f"NOTES {active_notes}"
            )
        )
        for key, button in self._device_action_buttons.items():
            is_active = key == self._device_mode or (key == "metronome" and self._device_metronome)
            _set_button_active(button, is_active)
        for group_name, button in self._device_group_buttons.items():
            _set_button_active(button, group_name == group)
        self._draw_timeline()

    def _tick_device_timeline(self) -> None:
        if getattr(self, "_device_surface_ready", False):
            self._update_device_surface()
        self.root.after(100, self._tick_device_timeline)

    def _draw_timeline(self) -> None:
        canvas = self.device_timeline
        canvas.delete("all")
        width = max(canvas.winfo_width(), 480)
        height = max(canvas.winfo_height(), 46)
        steps = 64
        gap = 2
        step_width = max(4, int((width - gap * (steps + 1)) / steps))
        active_step = self.runtime_state.clock_ticks % steps
        active_notes = bool(self.runtime_state.active_notes)
        for index in range(steps):
            x0 = gap + index * (step_width + gap)
            x1 = x0 + step_width
            y0 = 10
            y1 = height - 10
            fill = ModernPalette.panel_soft
            if index == active_step:
                fill = ModernPalette.accent
            elif index % 16 == 0:
                fill = ModernPalette.amber
            elif active_notes and index % 4 == 0:
                fill = "#5b6e41"
            canvas.create_rectangle(x0, y0, x1, y1, fill=fill, outline="")
        canvas.create_text(
            8,
            4,
            anchor="nw",
            fill=ModernPalette.dim,
            font=("Consolas", 8),
            text="LIVE TIMELINE / 64 STEP MIRROR",
        )

    app_class.__init__ = __init__
    app_class._install_device_surface = _install_device_surface
    app_class._trigger_device_surface_action = _trigger_device_surface_action
    app_class._select_device_group = _select_device_group
    app_class._send_device_volume = _send_device_volume
    app_class._set_action = _set_action
    app_class._queue_midi_input = _queue_midi_input
    app_class._send_mod_wheel = _send_mod_wheel
    app_class._set_bpm = _set_bpm
    app_class._update_device_surface = _update_device_surface
    app_class._tick_device_timeline = _tick_device_timeline
    app_class._draw_timeline = _draw_timeline
    app_class._device_surface_patch_installed = True


def _surface_button(tk, parent, label: str, command, *, bg: str | None = None, width: int = 7):
    return tk.Button(
        parent,
        text=label,
        command=command,
        bg=bg or ModernPalette.panel_soft,
        fg=ModernPalette.text,
        activebackground=ModernPalette.accent,
        activeforeground="#11120f",
        relief=tk.FLAT,
        bd=0,
        padx=8,
        pady=6,
        width=width,
        font=("Segoe UI", 9, "bold"),
    )


def _surface_scale(tk, parent, label: str, low: int, high: int, command):
    frame = tk.LabelFrame(
        parent,
        text=label,
        bg=ModernPalette.bg,
        fg=ModernPalette.dim,
        bd=0,
        labelanchor="n",
        font=("Segoe UI", 8, "bold"),
    )
    scale = tk.Scale(
        frame,
        from_=low,
        to=high,
        orient=tk.HORIZONTAL,
        length=130,
        showvalue=True,
        command=command,
        bg=ModernPalette.bg,
        fg=ModernPalette.text,
        troughcolor=ModernPalette.panel_soft,
        highlightthickness=0,
    )
    scale.pack(fill=tk.X)
    return frame, scale


def _set_button_active(button, active: bool) -> None:
    if active:
        button.configure(bg=ModernPalette.accent, fg="#11120f", relief="sunken")
    else:
        button.configure(bg=ModernPalette.panel_soft, fg=ModernPalette.text, relief="flat")


def _group_for_note(note: int) -> str:
    if 36 <= note <= 47:
        return "group A"
    if 48 <= note <= 59:
        return "group B"
    if 60 <= note <= 71:
        return "group C"
    if 72 <= note <= 83:
        return "group D"
    return f"note {note}"


def _mode_for_cc(control: int) -> str:
    for action in DEVICE_ACTIONS.values():
        if action.cc == control:
            return action.mode or action.key
    return f"cc {control}"
