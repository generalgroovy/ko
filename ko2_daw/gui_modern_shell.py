"""Modern EP-133-inspired application shell for the stable GUI."""

from __future__ import annotations

import tkinter.font as tkfont
from typing import Any, Callable


BG = "#d8d7d4"
CARD = "#e9e7e3"
CARD_ALT = "#c8c7c4"
INK = "#252525"
MUTED = "#6f706f"
DISPLAY = "#151515"
DISPLAY_TEXT = "#e8e8e5"
ACCENT = "#e34a18"
ACCENT_DARK = "#a92f12"
LINE = "#aaa9a6"
GROUP = "#aaa9a7"
CHASSIS = "#bcbab6"
KEY_DARK = "#252525"
KEY_DARK_ACTIVE = "#343332"
KEY_LIGHT = "#d7d5d1"
KEY_LIGHT_ACTIVE = "#e5e3df"
KEY_EDGE = "#777673"
LEGEND_DARK = "#d2d1ce"
DEVICE_KEY_LAYOUT = (
    (("7", 6), ("8", 7), ("9", 8)),
    (("4", 3), ("5", 4), ("6", 5)),
    (("1", 0), ("2", 1), ("3", 2)),
    ((".", 9), ("0", 10), ("ENTER", 11)),
)
DEVICE_GROUP_ORDER = ("A", "B", "C", "D")


def apply_modern_shell_patch(gui_module: Any) -> None:
    """Replace menu-heavy chrome with a direct, card-led workspace."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_modern_shell_patch_installed", False):
        return

    tk = gui_module.tk
    ttk = gui_module.ttk
    messagebox = gui_module.messagebox
    original_init = app_class.__init__

    def __init__(self, root) -> None:
        root.option_add("*tearOff", False)
        original_init(self, root)
        self.root.after_idle(self._modern_apply_widget_theme)
        self.root.after(80, self._modern_enter_fullscreen)

    def _build_menu(self) -> None:
        menu = tk.Menu(
            self.root,
            bg=CARD,
            fg=INK,
            activebackground=ACCENT,
            activeforeground="#ffffff",
            borderwidth=0,
        )
        app_menu = tk.Menu(menu)
        app_menu.add_command(label="Connect EP-133", command=self._connect_live)
        app_menu.add_command(label="Disconnect", command=self._disconnect_live)
        app_menu.add_separator()
        app_menu.add_command(label="Save Project", command=self._save_project)
        app_menu.add_command(label="Save Session", command=self._save_session)
        app_menu.add_separator()
        app_menu.add_command(label="Quit", command=self._close)
        menu.add_cascade(label="Application", menu=app_menu)

        help_menu = tk.Menu(menu)
        help_menu.add_command(
            label="Interaction Guide",
            command=self._show_interaction_guide,
        )
        help_menu.add_command(label="MIDI And Safety", command=self._show_midi_safety)
        help_menu.add_command(label="Current Device Status", command=self._show_doctor)
        help_menu.add_separator()
        for label, method_name in (
            ("Performance Guide", "_show_performance_help"),
            ("Scene Arranger Guide", "_show_arranger_help"),
            ("Audio Studio Guide", "_show_audio_help"),
            ("Project Manager Guide", "_show_project_catalog_help"),
            ("Device Library Guide", "_show_device_library_help"),
        ):
            command = getattr(self, method_name, None)
            if callable(command):
                help_menu.add_command(label=label, command=command)
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menu)

    def _build(self) -> None:
        self._modern_configure_styles()
        self._build_menu()
        outer = tk.Frame(self.root, bg=BG, padx=12, pady=12)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.columnconfigure(0, weight=5, uniform="main-area")
        outer.columnconfigure(1, weight=4, uniform="main-area")
        outer.rowconfigure(3, weight=1)

        self._build_top_panel(outer)
        self._build_mode_strip(outer)
        self._modern_build_tool_cards(outer)

        controls = tk.Frame(outer, bg=BG)
        controls.grid(row=3, column=0, sticky="nsew", pady=(8, 0), padx=(0, 4))
        controls.columnconfigure(0, weight=1)
        controls.rowconfigure(0, weight=1)
        self._build_main_controls(controls)

        workspace = tk.Frame(outer, bg=BG)
        workspace.grid(row=3, column=1, sticky="nsew", pady=(8, 0), padx=(4, 0))
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(3, weight=1)
        self._build_workspace(workspace)

    def _build_top_panel(self, parent) -> None:
        display = tk.Frame(
            parent,
            bg=DISPLAY,
            highlightbackground=INK,
            highlightthickness=1,
            padx=16,
            pady=11,
        )
        display.grid(row=0, column=0, sticky="ew")
        display.grid_configure(columnspan=2)
        display.columnconfigure(1, weight=1)

        brand = tk.Frame(display, bg=DISPLAY)
        brand.grid(row=0, column=0, rowspan=3, sticky="nsw", padx=(0, 20))
        tk.Label(
            brand,
            text="K.O. II",
            bg=DISPLAY,
            fg=DISPLAY_TEXT,
            font=("Segoe UI", 23),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            brand,
            text="SAMPLER  /  COMPOSER  /  DAW",
            bg=DISPLAY,
            fg=ACCENT,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(1, 0))

        action = tk.Label(
            display,
            textvariable=self.last_action,
            bg=DISPLAY,
            fg=DISPLAY_TEXT,
            font=("Consolas", 16, "bold"),
            anchor="w",
        )
        action.grid(row=0, column=1, sticky="ew")
        self._tip(action, "Most recent app or device action.")

        self.port_label = tk.Label(
            display,
            bg=DISPLAY,
            fg="#bfc4c1",
            font=("Consolas", 9),
            anchor="w",
            justify=tk.LEFT,
        )
        self.port_label.grid(row=1, column=1, sticky="ew", pady=(5, 0))
        self._tip(
            self.port_label,
            "Detected EP-133 USB/MIDI route and available ports.",
        )

        self.state_label = tk.Label(
            display,
            bg=DISPLAY,
            fg="#bfc4c1",
            font=("Consolas", 9),
            anchor="w",
            justify=tk.LEFT,
        )
        self.state_label.grid(row=2, column=1, sticky="ew", pady=(3, 0))
        self._tip(
            self.state_label,
            "Runtime state inferred from MIDI traffic and app-originated commands.",
        )
        self._refresh_state_label()

        status_shell = tk.Frame(display, bg=DISPLAY)
        status_shell.grid(row=0, column=2, rowspan=3, sticky="nse", padx=(18, 0))
        state = tk.Label(
            status_shell,
            textvariable=self.status,
            bg=ACCENT,
            fg="#ffffff",
            font=("Consolas", 11, "bold"),
            padx=12,
            pady=7,
        )
        state.pack(fill=tk.X)
        live = tk.Label(
            status_shell,
            textvariable=self.live_state,
            bg=DISPLAY,
            fg=DISPLAY_TEXT,
            font=("Consolas", 9),
            anchor="e",
        )
        live.pack(fill=tk.X, pady=(7, 0))
        self._tip(state, "DRY RUN sends nothing; LIVE EP-133 routes controls to hardware.")
        self._tip(live, "Resolved connection state.")

    def _modern_build_tool_cards(self, parent) -> None:
        rail = tk.Frame(parent, bg=BG)
        rail.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        tools: tuple[tuple[str, str, str, str], ...] = (
            ("PERFORM", "Capture and overdub MIDI", "_show_performance_window", "performance"),
            (
                "SEQUENCE",
                "Scenes, clips and song",
                "_show_arranger_window",
                "arranger",
            ),
            ("AUDIO", "Record, edit and mix", "_show_audio_studio", "audio"),
            ("PROJECTS", "Backup, inspect and diff", "_show_project_catalog", "projects"),
            (
                "FILES",
                "Browse device storage",
                "_show_device_file_explorer",
                "files",
            ),
            ("LIBRARY", "Samples, waveforms, preview", "_show_device_library", "library"),
            (
                "MIDI",
                "Detect and configure route",
                "_show_midi_detection_summary",
                "midi",
            ),
            ("PROTOCOL", "Inspect read-only SysEx", "_show_protocol_window", "protocol"),
            ("COMM", "Connection and safety", "_show_comm_panel", "communication"),
            ("SETTINGS", "App and scan policy", "_modern_show_settings", "settings"),
        )
        for index, (title, subtitle, method_name, key) in enumerate(tools):
            column = index % 5
            row = index // 5
            rail.columnconfigure(column, weight=1, uniform="tool-card")
            card = tk.Frame(
                rail,
                bg=CARD,
                highlightbackground=LINE,
                highlightthickness=1,
                padx=10,
                pady=8,
                cursor="hand2",
            )
            card.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=(0 if column == 0 else 4, 0),
                pady=(0 if row == 0 else 4, 0),
            )
            marker = tk.Frame(card, bg=ACCENT if index < 4 else INK, width=4)
            marker.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 9))
            text = tk.Frame(card, bg=CARD)
            text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            title_widget = tk.Label(
                text,
                text=title,
                bg=CARD,
                fg=INK,
                font=("Segoe UI", 9, "bold"),
                anchor="w",
            )
            title_widget.pack(fill=tk.X)
            subtitle_widget = tk.Label(
                text,
                text=subtitle,
                bg=CARD,
                fg=MUTED,
                font=("Segoe UI", 8),
                anchor="w",
            )
            subtitle_widget.pack(fill=tk.X, pady=(2, 0))
            command = getattr(self, method_name, None)
            if not callable(command):
                command = lambda name=title: self._set_action(
                    f"{name.lower()} unavailable"
                )
            for widget in (card, marker, text, title_widget, subtitle_widget):
                widget.bind(
                    "<Button-1>",
                    lambda _event, cmd=command: self._modern_invoke_tool(cmd),
                )
            card.bind(
                "<Enter>",
                lambda _event, target=card: target.configure(
                    highlightbackground=ACCENT
                ),
            )
            card.bind(
                "<Leave>",
                lambda _event, target=card: target.configure(
                    highlightbackground=LINE
                ),
            )
            self._tip(card, f"{title}: {subtitle}.")
            setattr(self, f"modern_tool_{key}", card)

    def _build_mode_strip(self, parent) -> None:
        strip = tk.Frame(parent, bg=BG)
        strip.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        modes = (
            ("SOUND", "sound"),
            ("MAIN", "main"),
            ("TEMPO", "tempo"),
            ("FX", "fx"),
            ("SHIFT", "shift"),
            ("FADER", "fader"),
        )
        for column, (label, action) in enumerate(modes):
            strip.columnconfigure(column, weight=1, uniform="device-mode")
            button = tk.Button(
                strip,
                text=label,
                command=lambda value=action: self._set_action(value),
                bg=CARD,
                fg=INK,
                activebackground=ACCENT,
                activeforeground="#ffffff",
                relief=tk.FLAT,
                borderwidth=1,
            )
            button.grid(
                row=0,
                column=column,
                sticky="ew",
                padx=(0 if column == 0 else 3, 0),
                ipady=5,
            )
            self._tip(button, f"EP-133 {label} mode control.")

    def _build_main_controls(self, parent) -> None:
        deck = tk.Frame(
            parent,
            bg=CHASSIS,
            highlightbackground="#8f8e8a",
            highlightthickness=1,
            padx=15,
            pady=15,
        )
        deck.grid(row=0, column=0, sticky="nsew")
        for column, weight in enumerate((2, 2, 3, 3, 3, 2, 2)):
            deck.columnconfigure(column, weight=weight, uniform="device-column")
        for row in range(6):
            deck.rowconfigure(row, weight=1, uniform="device-row")

        self._modern_build_left_controls(deck)
        self._modern_build_group_column(deck)
        self._modern_build_keypad(deck)
        self._modern_build_function_columns(deck)

    def _modern_build_left_controls(self, deck) -> None:
        volume = tk.Scale(
            deck,
            from_=0,
            to=127,
            orient=tk.HORIZONTAL,
            showvalue=False,
            bg=CHASSIS,
            troughcolor=DISPLAY,
            activebackground="#ffffff",
            highlightthickness=0,
            borderwidth=0,
            sliderlength=22,
        )
        volume.set(96)
        volume.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        self._tip(volume, "Visual monitor-level control; device volume is not exposed by MIDI.")

        utilities = (
            ("KEYS", lambda: self._set_action("keys")),
            ("FADER", lambda: self._set_action("fader")),
            ("SHIFT", lambda: self._set_action("shift")),
        )
        for row, (label, command) in zip((1, 2, 5), utilities):
            button = _device_button(
                tk,
                deck,
                label,
                command,
                dark=True,
                font_size=9,
            )
            button.grid(row=row, column=0, sticky="nsew", padx=9, pady=9)
            self._tip(button, f"EP-133 {label} control.")

        self.modern_fader_value = tk.IntVar(value=96)
        fader = tk.Scale(
            deck,
            from_=127,
            to=0,
            orient=tk.VERTICAL,
            variable=self.modern_fader_value,
            showvalue=False,
            bg=CHASSIS,
            troughcolor=DISPLAY,
            activebackground=ACCENT,
            highlightthickness=0,
            borderwidth=0,
            sliderlength=22,
            command=lambda value: self._send_mod_wheel(int(float(value))),
        )
        fader.grid(row=3, column=0, rowspan=2, sticky="ns", padx=6, pady=3)
        self._tip(fader, "Physical-style fader mapped to MIDI CC 1.")

    def _modern_build_group_column(self, deck) -> None:
        group_actions = {
            "A": "sound",
            "B": "back",
            "C": "up",
            "D": "down",
        }
        for row, group in enumerate(DEVICE_GROUP_ORDER, start=2):
            button = tk.Radiobutton(
                deck,
                text=group,
                value=group,
                variable=self.group,
                indicatoron=False,
                command=lambda value=group: self._set_action(f"group {value}"),
                bg=KEY_LIGHT,
                fg=INK,
                selectcolor="#c5c2bd",
                activebackground=KEY_LIGHT_ACTIVE,
                font=("Segoe UI", 17),
                relief=tk.RAISED,
                borderwidth=1,
                highlightbackground=KEY_EDGE,
                highlightthickness=1,
            )
            button.grid(row=row, column=1, sticky="nsew", padx=9, pady=9)
            self._tip(
                button,
                f"Select Group {group}; notes {gui_module.PAD_NOTES[group][0]}-"
                f"{gui_module.PAD_NOTES[group][-1]}. Secondary device legend: "
                f"{group_actions[group]}.",
            )

    def _modern_build_keypad(self, deck) -> None:
        for row, keys in enumerate(DEVICE_KEY_LAYOUT, start=2):
            for offset, (label, pad_index) in enumerate(keys, start=2):
                button = _device_button(
                    tk,
                    deck,
                    label,
                    lambda index=pad_index: self._trigger_pad(index),
                    dark=True,
                    font_size=16 if label != "ENTER" else 10,
                )
                button.grid(
                    row=row,
                    column=offset,
                    sticky="nsew",
                    padx=9,
                    pady=9,
                )
                self._tip(
                    button,
                    f"Trigger physical keypad position {label} in Group "
                    f"{self.group.get()}; app pad index {pad_index + 1}.",
                )

    def _modern_build_function_columns(self, deck) -> None:
        left_functions = (
            ("SOUND\nEDIT", lambda: self._set_action("sound edit")),
            ("MAIN\nCOMMIT", lambda: self._set_action("main commit")),
            ("TEMPO\nLOOP", lambda: self._set_action("tempo loop")),
            ("FX\nOUTPUT", lambda: self._set_action("fx output")),
        )
        right_functions = (
            ("SAMPLE\nCHOP", lambda: self._set_action("sample chop")),
            ("TIMING\nCORRECT", lambda: self._set_action("timing correct")),
            ("ERASE\nSYSTEM", lambda: self._set_action("erase system")),
        )
        for row, (label, command) in enumerate(left_functions):
            button = _split_device_button(tk, deck, label, command)
            button.grid(row=row, column=5, sticky="nsew", padx=9, pady=9)
            self._tip(button, f"EP-133 {label.replace(chr(10), ' / ')} control.")
        for row, (label, command) in enumerate(right_functions):
            button = _split_device_button(
                tk,
                deck,
                label,
                command,
                accent=row == 0,
            )
            button.grid(row=row, column=6, sticky="nsew", padx=9, pady=9)
            self._tip(button, f"EP-133 {label.replace(chr(10), ' / ')} control.")

        minus = _device_button(
            tk,
            deck,
            "−",
            lambda: self._modern_nudge(-1),
            dark=False,
            font_size=20,
        )
        plus = _device_button(
            tk,
            deck,
            "+",
            lambda: self._modern_nudge(1),
            dark=False,
            font_size=20,
        )
        minus.grid(row=3, column=5, sticky="nsew", padx=9, pady=9)
        plus.grid(row=3, column=6, sticky="nsew", padx=9, pady=9)
        self._tip(minus, "Decrease the focused numeric parameter.")
        self._tip(plus, "Increase the focused numeric parameter.")

        record = _device_button(
            tk,
            deck,
            "RECORD",
            self._record,
            dark=False,
            accent=True,
            font_size=10,
        )
        play = _device_button(
            tk,
            deck,
            "PLAY",
            self._start,
            dark=True,
            font_size=10,
        )
        record.grid(row=4, column=5, rowspan=2, sticky="nsew", padx=9, pady=9)
        play.grid(row=4, column=6, rowspan=2, sticky="nsew", padx=9, pady=9)
        self._tip(record, "Record-arm action, matching the physical RECORD key.")
        self._tip(play, "Send MIDI Start, matching the physical PLAY key.")

    def _modern_nudge(self, direction: int) -> None:
        value = max(60.0, min(180.0, float(self.bpm.get()) + direction))
        self.bpm.set(value)
        self._set_bpm(value)

    def _modern_invoke_tool(self, command: Callable[[], object]) -> None:
        command()
        self.root.after_idle(self._modern_theme_open_windows)

    def _modern_theme_open_windows(self) -> None:
        old_light = {"#d8d4c8", "#bdb7aa", "#c9c4b8", "#efeadf", "#f5f0e4"}

        def configure_color(widget, option: str, value: str) -> None:
            try:
                widget.configure(**{option: value})
            except tk.TclError:
                return

        def walk(widget) -> None:
            if isinstance(widget, tk.Toplevel):
                configure_color(widget, "bg", BG)
            if isinstance(widget, (tk.Frame, tk.LabelFrame)):
                try:
                    current = str(widget.cget("bg")).lower()
                except tk.TclError:
                    current = ""
                if current in old_light:
                    configure_color(
                        widget,
                        "bg",
                        CARD if isinstance(widget, tk.LabelFrame) else BG,
                    )
            elif isinstance(widget, tk.Label):
                try:
                    current = str(widget.cget("bg")).lower()
                except tk.TclError:
                    current = ""
                if current in old_light:
                    configure_color(widget, "bg", BG)
                    configure_color(widget, "fg", INK)
            elif isinstance(widget, tk.Button):
                try:
                    current = str(widget.cget("bg")).lower()
                except tk.TclError:
                    current = ""
                if current not in {"#dc493a", "#88b04b", ACCENT.lower(), DISPLAY}:
                    widget.configure(
                        bg=CARD,
                        fg=INK,
                        activebackground="#ffffff",
                        activeforeground=INK,
                        relief=tk.FLAT,
                        borderwidth=1,
                        highlightbackground=LINE,
                        highlightthickness=1,
                        cursor="hand2",
                    )
            elif isinstance(widget, tk.Checkbutton):
                try:
                    current = str(widget.cget("bg")).lower()
                except tk.TclError:
                    current = ""
                if current in old_light:
                    widget.configure(
                        bg=BG,
                        activebackground=BG,
                        selectcolor=ACCENT,
                    )
            elif isinstance(widget, tk.PanedWindow):
                configure_color(widget, "bg", LINE)
            for child in widget.winfo_children():
                walk(child)

        for child in self.root.winfo_children():
            if isinstance(child, tk.Toplevel):
                walk(child)

    def _build_encoders(self, parent) -> None:
        panel = tk.Frame(
            parent,
            bg=CARD_ALT,
            highlightbackground=LINE,
            highlightthickness=1,
            padx=10,
            pady=9,
            width=250,
        )
        panel.pack(fill=tk.BOTH, expand=True)
        panel.columnconfigure(0, weight=1)

        tk.Label(
            panel,
            text="DEVICE PARAMETERS",
            bg=CARD_ALT,
            fg=INK,
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        session = tk.Label(
            panel,
            textvariable=self.session_status,
            bg=CARD_ALT,
            fg=MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        )
        session.grid(row=1, column=0, sticky="ew", pady=(1, 5))
        self._tip(session, "Current companion session.")

        specs = (
            ("BPM / X", self.bpm, 60, 180, self._set_bpm, "Session tempo."),
            (
                "VELOCITY / Y",
                self.velocity,
                1,
                127,
                self._set_velocity,
                "Pad trigger velocity.",
            ),
        )
        for row, (label, variable, low, high, command, tip) in enumerate(
            specs,
            start=2,
        ):
            shell = tk.Frame(panel, bg=CARD_ALT)
            shell.grid(row=row, column=0, sticky="ew", pady=2)
            shell.columnconfigure(1, weight=1)
            title = tk.Label(
                shell,
                text=label,
                bg=CARD_ALT,
                fg=INK,
                width=12,
                anchor="w",
                font=("Segoe UI", 8, "bold"),
            )
            title.grid(row=0, column=0, sticky="w")
            scale = tk.Scale(
                shell,
                from_=low,
                to=high,
                orient=tk.HORIZONTAL,
                variable=variable,
                showvalue=True,
                resolution=1,
                bg=CARD_ALT,
                fg=INK,
                troughcolor=DISPLAY,
                activebackground=ACCENT,
                highlightthickness=0,
                borderwidth=0,
                sliderlength=16,
                command=lambda value, callback=command: callback(float(value)),
            )
            scale.grid(row=0, column=1, sticky="ew")
            self._tip(title, tip)
            self._tip(scale, tip)

        fader_shell = tk.Frame(panel, bg=CARD_ALT)
        fader_shell.grid(row=4, column=0, sticky="ew", pady=2)
        fader_shell.columnconfigure(1, weight=1)
        fader_title = tk.Label(
            fader_shell,
            text="FADER / CC1",
            bg=CARD_ALT,
            fg=INK,
            width=12,
            anchor="w",
            font=("Segoe UI", 8, "bold"),
        )
        fader_title.grid(row=0, column=0, sticky="w")
        self.modern_fader_value = tk.IntVar(value=96)
        fader = tk.Scale(
            fader_shell,
            from_=0,
            to=127,
            orient=tk.HORIZONTAL,
            variable=self.modern_fader_value,
            showvalue=True,
            bg=CARD_ALT,
            fg=INK,
            troughcolor=DISPLAY,
            activebackground=ACCENT,
            highlightthickness=0,
            borderwidth=0,
            sliderlength=16,
            command=lambda value: self._send_mod_wheel(int(float(value))),
        )
        fader.grid(row=0, column=1, sticky="ew")
        self._tip(
            fader,
            "KO II fader mapped to MIDI CC 1 / mod wheel.",
        )

        connection = tk.Frame(panel, bg=CARD_ALT)
        connection.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        connection.columnconfigure(0, weight=1)
        connection.columnconfigure(1, weight=1)
        connect = tk.Button(
            connection,
            text="CONNECT",
            command=self._connect_live,
            bg=ACCENT,
            fg="#ffffff",
            activebackground=ACCENT_DARK,
            activeforeground="#ffffff",
        )
        connect.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        disconnect = tk.Button(
            connection,
            text="DISCONNECT",
            command=self._disconnect_live,
            bg=CARD,
        )
        disconnect.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        self._tip(connect, "Connect the configured EP-133 MIDI route.")
        self._tip(disconnect, "Close the active device route.")

    def _modern_show_settings(self) -> None:
        tabs = getattr(self, "workspace_tabs", None)
        if tabs is None:
            return
        for tab_id in tabs.tabs():
            if tabs.tab(tab_id, "text") == "Settings":
                tabs.select(tab_id)
                self._set_action("settings")
                return

    def _modern_configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "TNotebook",
            background=BG,
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            "TNotebook.Tab",
            background=CARD_ALT,
            foreground=INK,
            padding=(14, 7),
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", CARD), ("active", "#ececea")],
            foreground=[("selected", ACCENT_DARK)],
        )
        style.configure(
            "Treeview",
            background=CARD,
            fieldbackground=CARD,
            foreground=INK,
            rowheight=25,
            borderwidth=0,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background=CARD_ALT,
            foreground=INK,
            relief="flat",
            font=("Segoe UI", 9, "bold"),
            padding=(6, 5),
        )
        style.map(
            "Treeview",
            background=[("selected", ACCENT)],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "TCombobox",
            fieldbackground=CARD,
            background=CARD,
            foreground=INK,
            padding=5,
        )
        style.configure(
            "Horizontal.TProgressbar",
            background=ACCENT,
            troughcolor=CARD_ALT,
            borderwidth=0,
        )

    def _modern_apply_widget_theme(self) -> None:
        self.root.title("KO II Studio")
        self.root.minsize(1180, 760)
        self.root.configure(bg=BG)
        default_font = tkfont.nametofont("TkDefaultFont")
        default_font.configure(family="Segoe UI", size=9)
        text_font = tkfont.nametofont("TkTextFont")
        text_font.configure(family="Segoe UI", size=9)
        fixed_font = tkfont.nametofont("TkFixedFont")
        fixed_font.configure(family="Consolas", size=9)

        def walk(widget) -> None:
            for child in widget.winfo_children():
                if isinstance(child, tk.Button):
                    current_bg = str(child.cget("bg")).lower()
                    if current_bg not in {
                        ACCENT.lower(),
                        ACCENT_DARK.lower(),
                        DISPLAY.lower(),
                        "#dc493a",
                        "#88b04b",
                        "#171915",
                    }:
                        child.configure(
                            bg=CARD,
                            fg=INK,
                            activebackground="#ffffff",
                            activeforeground=INK,
                            relief=tk.FLAT,
                            borderwidth=1,
                            highlightbackground=LINE,
                            highlightthickness=1,
                            padx=8,
                            pady=4,
                            cursor="hand2",
                        )
                elif isinstance(child, tk.Radiobutton):
                    child.configure(
                        bg=GROUP,
                        fg=INK,
                        activebackground="#b8bdc0",
                        selectcolor=ACCENT,
                        relief=tk.FLAT,
                        borderwidth=0,
                        cursor="hand2",
                    )
                elif isinstance(child, tk.LabelFrame):
                    child.configure(
                        bg=CARD,
                        fg=INK,
                        highlightbackground=LINE,
                        highlightthickness=1,
                        borderwidth=0,
                    )
                walk(child)

        walk(self.root)

    def _modern_enter_fullscreen(self) -> None:
        try:
            self.root.state("zoomed")
        except tk.TclError:
            width = self.root.winfo_screenwidth()
            height = self.root.winfo_screenheight()
            self.root.geometry(f"{width}x{height}+0+0")

    app_class.__init__ = __init__
    app_class._build = _build
    app_class._build_menu = _build_menu
    app_class._build_top_panel = _build_top_panel
    app_class._build_mode_strip = _build_mode_strip
    app_class._build_main_controls = _build_main_controls
    app_class._modern_build_left_controls = _modern_build_left_controls
    app_class._modern_build_group_column = _modern_build_group_column
    app_class._modern_build_keypad = _modern_build_keypad
    app_class._modern_build_function_columns = _modern_build_function_columns
    app_class._modern_nudge = _modern_nudge
    app_class._modern_build_tool_cards = _modern_build_tool_cards
    app_class._modern_invoke_tool = _modern_invoke_tool
    app_class._modern_theme_open_windows = _modern_theme_open_windows
    app_class._modern_show_settings = _modern_show_settings
    app_class._modern_configure_styles = _modern_configure_styles
    app_class._modern_apply_widget_theme = _modern_apply_widget_theme
    app_class._modern_enter_fullscreen = _modern_enter_fullscreen
    app_class._modern_shell_patch_installed = True


def _device_button(
    tk,
    parent,
    text: str,
    command: Callable[[], object],
    *,
    dark: bool,
    accent: bool = False,
    font_size: int = 11,
):
    bg = ACCENT_DARK if accent else (KEY_DARK if dark else KEY_LIGHT)
    fg = "#d8b4a8" if accent else (LEGEND_DARK if dark else INK)
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=(
            ACCENT if accent else (KEY_DARK_ACTIVE if dark else KEY_LIGHT_ACTIVE)
        ),
        activeforeground="#ffffff" if accent else fg,
        font=("Segoe UI", font_size, "bold"),
        relief=tk.RAISED,
        borderwidth=1,
        highlightbackground=KEY_EDGE,
        highlightthickness=1,
        padx=6,
        pady=6,
    )


def _split_device_button(
    tk,
    parent,
    text: str,
    command: Callable[[], object],
    *,
    accent: bool = False,
):
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=ACCENT if accent else KEY_LIGHT,
        fg="#f1d0c5" if accent else INK,
        activebackground=ACCENT_DARK if accent else KEY_LIGHT_ACTIVE,
        activeforeground="#ffffff" if accent else INK,
        font=("Segoe UI", 9, "bold"),
        relief=tk.RAISED,
        borderwidth=1,
        highlightbackground=KEY_EDGE,
        highlightthickness=1,
        padx=5,
        pady=5,
    )
