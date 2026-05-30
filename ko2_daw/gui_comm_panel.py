"""Compact communication settings panel for the KO II GUI."""

from __future__ import annotations

from typing import Any

from ko2_daw.config import APP_ACCESS_MODES, save_app_settings


def apply_comm_panel_patch(gui_module: Any) -> None:
    """Add a compact in-app communication settings panel."""

    app_class = gui_module.KO2DawApp
    if getattr(app_class, "_comm_panel_patch_installed", False):
        return

    tk = gui_module.tk
    ttk = gui_module.ttk
    messagebox = gui_module.messagebox
    original_build_menu = app_class._build_menu
    original_apply_settings = app_class._apply_settings
    original_send_file_playback = app_class._send_device_file_playback

    def _build_menu(self) -> None:
        original_build_menu(self)
        menu = self.root.nametowidget(self.root.cget("menu"))
        comm_menu = tk.Menu(menu, tearoff=False)
        comm_menu.add_command(label="Communication Panel", command=self._show_comm_panel)
        comm_menu.add_command(label="Communication Summary", command=self._show_comm_summary)
        menu.add_cascade(label="Communication", menu=comm_menu)

    def _show_comm_panel(self) -> None:
        if getattr(self, "comm_window", None) and self.comm_window.winfo_exists():
            self.comm_window.lift()
            return

        win = tk.Toplevel(self.root)
        win.title("KO II Communication")
        win.geometry("620x520")
        win.configure(bg="#11120f")
        self.comm_window = win

        self.comm_mode = tk.StringVar(value=self.app_settings.access_mode)
        self.comm_auto_connect = tk.BooleanVar(value=self.app_settings.auto_connect_on_start)
        self.comm_protocol = tk.BooleanVar(value=self.app_settings.sysex_enabled)
        self.comm_auto_scan = tk.BooleanVar(value=self.app_settings.auto_scan_on_connect)
        self.comm_file_preview = tk.BooleanVar(value=self.app_settings.allow_file_playback)
        self.comm_timeout = tk.StringVar(value=str(self.app_settings.sysex_timeout_sec))
        self.comm_limit = tk.StringVar(value=str(self.app_settings.max_sysex_bytes))
        self.comm_pages = tk.StringVar(value=str(self.app_settings.scan_pages_per_dir))
        self.comm_depth = tk.StringVar(value=str(self.app_settings.scan_max_depth))
        self.comm_dirs = tk.StringVar(value=str(self.app_settings.scan_max_dirs))
        self.comm_phrase = tk.StringVar(value=self.app_settings.write_arm_phrase)

        title = tk.Label(
            win,
            text="COMMUNICATION",
            bg="#11120f",
            fg="#d7f58a",
            font=("Consolas", 18, "bold"),
            pady=8,
        )
        title.pack(fill=tk.X)

        body = tk.Frame(win, bg="#d8d4c8", padx=10, pady=10)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        body.columnconfigure(1, weight=1)

        tk.Label(body, text="Profile", bg="#d8d4c8").grid(row=0, column=0, sticky="w")
        profile = ttk.Combobox(
            body,
            textvariable=self.comm_mode,
            values=list(APP_ACCESS_MODES),
            state="readonly",
        )
        profile.grid(row=0, column=1, sticky="ew", pady=3)

        options = (
            ("Connect on launch", self.comm_auto_connect),
            ("Enable device file channel", self.comm_protocol),
            ("Scan files after connect", self.comm_auto_scan),
            ("Allow file preview", self.comm_file_preview),
        )
        for row, (label, variable) in enumerate(options, start=1):
            check = tk.Checkbutton(
                body,
                text=label,
                variable=variable,
                bg="#d8d4c8",
                anchor="w",
            )
            check.grid(row=row, column=0, columnspan=2, sticky="ew", pady=2)

        fields = (
            ("Timeout seconds", self.comm_timeout, ""),
            ("Message size limit", self.comm_limit, ""),
            ("Pages per folder", self.comm_pages, ""),
            ("Folder depth", self.comm_depth, ""),
            ("Folder count", self.comm_dirs, ""),
            ("Lab phrase", self.comm_phrase, "*"),
        )
        for offset, (label, variable, mask) in enumerate(fields, start=5):
            tk.Label(body, text=label, bg="#d8d4c8").grid(
                row=offset,
                column=0,
                sticky="w",
                pady=3,
            )
            entry = tk.Entry(body, textvariable=variable, show=mask)
            entry.grid(row=offset, column=1, sticky="ew", pady=3)

        summary = tk.Text(body, height=8, bg="#f7f3e7", wrap=tk.WORD)
        summary.grid(row=11, column=0, columnspan=2, sticky="nsew", pady=(8, 8))
        body.rowconfigure(11, weight=1)
        summary.insert(tk.END, self._comm_summary_text())
        summary.configure(state=tk.DISABLED)

        actions = tk.Frame(body, bg="#d8d4c8")
        actions.grid(row=12, column=0, columnspan=2, sticky="ew")
        tk.Button(actions, text="APPLY", command=self._apply_comm_panel).pack(side=tk.LEFT, padx=3)
        tk.Button(actions, text="SAVE", command=self._save_comm_panel).pack(side=tk.LEFT, padx=3)
        tk.Button(actions, text="PROTOCOL", command=self._show_protocol_window).pack(
            side=tk.LEFT,
            padx=3,
        )
        tk.Button(actions, text="CLOSE", command=win.destroy).pack(side=tk.RIGHT, padx=3)

    def _apply_comm_panel(self) -> bool:
        self.access_mode_setting.set(self.comm_mode.get())
        self.auto_connect_setting.set(bool(self.comm_auto_connect.get()))
        self.sysex_enabled_setting.set(bool(self.comm_protocol.get()))
        self.auto_scan_setting.set(bool(self.comm_auto_scan.get()))
        self.file_playback_setting.set(bool(self.comm_file_preview.get()))
        self.sysex_timeout_setting.set(self.comm_timeout.get())
        self.max_sysex_bytes_setting.set(self.comm_limit.get())
        self.scan_pages_setting.set(self.comm_pages.get())
        self.scan_depth_setting.set(self.comm_depth.get())
        self.scan_dirs_setting.set(self.comm_dirs.get())
        self.write_arm_setting.set(self.comm_phrase.get())
        applied = self._apply_settings(show_message=True)
        if applied:
            self._record_comm_event("applied")
        return applied

    def _save_comm_panel(self) -> None:
        if getattr(self, "comm_window", None) and self.comm_window.winfo_exists():
            if not self._apply_comm_panel():
                return
        path = save_app_settings(self.settings_path, self.app_settings)
        self._record_comm_event("saved")
        self._set_action(f"communication settings saved: {path.name}")
        messagebox.showinfo("KO II Communication", f"Saved settings:\n{path}")

    def _apply_settings(self, *, show_message: bool = True) -> bool:
        result = original_apply_settings(self, show_message=show_message)
        if result:
            self._record_comm_event("settings")
        return result

    def _show_comm_summary(self) -> None:
        messagebox.showinfo("KO II Communication", self._comm_summary_text())

    def _comm_summary_text(self) -> str:
        settings = self.app_settings
        scan = (
            f"Scan: {settings.scan_pages_per_dir} pages, "
            f"depth {settings.scan_max_depth}, dirs {settings.scan_max_dirs}"
        )
        return "\n".join(
            [
                f"Profile: {settings.access_mode}",
                f"Device file channel: {'on' if settings.sysex_enabled else 'off'}",
                f"File preview: {'on' if settings.playback_enabled else 'off'}",
                f"Lab controls: {'on' if settings.write_enabled else 'off'}",
                f"Timeout: {settings.sysex_timeout_sec}s",
                f"Message limit: {settings.max_sysex_bytes} bytes",
                scan,
                "",
                "Use Protocol Monitor for full app/device message visibility.",
            ]
        )

    def _record_comm_event(self, label: str) -> None:
        detail = self._comm_summary_text()
        self._log(f"communication {label}: {self.app_settings.access_mode}")
        if hasattr(self, "_record_protocol"):
            self._record_protocol(
                "app",
                f"communication-{label}",
                self.app_settings.access_mode,
                detail,
            )

    def _send_device_file_playback(self, action: int) -> None:
        if not self.app_settings.playback_enabled:
            self._record_comm_event("preview-blocked")
            messagebox.showwarning(
                "KO II Communication",
                "File preview is disabled by the current communication profile.",
            )
            return
        original_send_file_playback(self, action)

    app_class._build_menu = _build_menu
    app_class._show_comm_panel = _show_comm_panel
    app_class._apply_comm_panel = _apply_comm_panel
    app_class._save_comm_panel = _save_comm_panel
    app_class._apply_settings = _apply_settings
    app_class._show_comm_summary = _show_comm_summary
    app_class._comm_summary_text = _comm_summary_text
    app_class._record_comm_event = _record_comm_event
    app_class._send_device_file_playback = _send_device_file_playback
    app_class._comm_panel_patch_installed = True
