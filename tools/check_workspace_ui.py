"""Exercise the composed stable Tk workspace using synthetic files and no devices."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import tkinter as tk
import tkinter.font as tkfont
import wave
from pathlib import Path
from unittest.mock import patch

from PIL import ImageGrab

from ko2_daw import gui
from ko2_daw.gui_plugins import install_gui_plugins


def check_hardware_labels(widget):
    for child in widget.winfo_children():
        if getattr(child, "studio_device_button", False):
            font = tkfont.Font(font=child["font"])
            border = child.winfo_pixels(child["borderwidth"]) + child.winfo_pixels(
                child["highlightthickness"]
            )
            needed = max(font.measure(line) for line in str(child["text"]).splitlines())
            needed += 2 * (border + child.winfo_pixels(child["padx"]))
            assert needed <= child.winfo_width(), (str(child["text"]), needed, child.winfo_width())
        check_hardware_labels(child)


def main():
    output = Path("docs/evidence/ux-2026-10-07").resolve()
    output.mkdir(parents=True, exist_ok=True)
    original_cwd = Path.cwd()
    install_gui_plugins(gui)
    errors = []
    with tempfile.TemporaryDirectory(prefix="ko-workspace-ui-") as directory:
        work = Path(directory)
        try:
            os.chdir(work)
            with (
                patch(
                    "ko2_daw.gui.midi_capability_report",
                    return_value={"input_ports": [], "output_ports": []},
                ),
                patch.object(gui.KO2DawApp, "_auto_connect_on_start"),
                patch.object(gui.KO2DawApp, "_modern_enter_fullscreen"),
                patch(
                    "ko2_daw.gui.WinMMMidiBackend", side_effect=AssertionError("Hardware forbidden")
                ) as backend,
                patch(
                    "ko2_daw.gui.WinMMInputMonitor",
                    side_effect=AssertionError("Hardware forbidden"),
                ) as monitor,
                patch("ko2_daw.gui.play_wav", side_effect=AssertionError("Playback forbidden")),
            ):
                root = tk.Tk()
                root.report_callback_exception = lambda *args: errors.append(str(args))
                app = gui.KO2DawApp(root)
                root.geometry("1180x760+10+10")
                root.update()
                check_hardware_labels(root)
                assert app.status.get() == "DRY RUN" and not app.live_output_port
                assert "Import WAV" in app.sample_status.get()
                assert all(
                    str(button["state"]) == "disabled" for button in app.sample_selection_buttons
                )

                # Home cards are real keyboard controls. Samples returns from Settings.
                app.modern_tool_buttons["SETTINGS"].invoke()
                assert app.workspace_tabs.tab(app.workspace_tabs.select(), "text") == "Settings"
                button = app.modern_tool_buttons["SAMPLES"]
                button.focus_force()
                root.update()
                button.event_generate("<Return>")
                root.update()
                assert app.workspace_tabs.tab(app.workspace_tabs.select(), "text") == "Samples"
                assert root.focus_get() == app.sample_import_button
                assert all(
                    str(control["takefocus"]) == "1" for control in app.modern_tool_buttons.values()
                )
                menu = root.nametowidget(root["menu"])
                tools_index = next(
                    i
                    for i in range(menu.index("end") + 1)
                    if menu.type(i) == "cascade" and menu.entrycget(i, "label") == "Tools"
                )
                tools = root.nametowidget(menu.entrycget(tools_index, "menu"))
                assert [tools.entrycget(i, "label") for i in range(tools.index("end") + 1)] == [
                    "MIDI route and detection",
                    "Protocol inspector",
                    "Communication and safety",
                ]

                for state in ("empty", "selected", "saved"):
                    if state == "selected":
                        source = work / "warm-chord.wav"
                        with wave.open(str(source), "wb") as writer:
                            writer.setparams((1, 2, 48000, 48000, "NONE", "not compressed"))
                            writer.writeframes(b"\0\0" * 48000)
                        with patch(
                            "ko2_daw.gui.filedialog.askopenfilenames", return_value=[str(source)]
                        ):
                            app._import_wav()
                        root.update()
                        assert "warm-chord" in app.sample_status.get()
                        assert "Unsaved library changes" in app.sample_save_status.get()
                        app.modern_tool_buttons["SAMPLES"].invoke()
                        root.update()
                        assert root.focus_get() == app.sample_tree
                        assert all(
                            str(control["state"]) == "normal"
                            for control in app.sample_selection_buttons
                        )
                        assert tuple(app.sample_tree["displaycolumns"]) == (
                            "slot",
                            "name",
                            "duration",
                            "path",
                        )
                    if state == "saved":
                        manifest = work / "library.json"
                        with (
                            patch(
                                "ko2_daw.gui.filedialog.asksaveasfilename",
                                return_value=str(manifest),
                            ),
                            patch("ko2_daw.gui.messagebox.showinfo") as notice,
                        ):
                            app._save_sample_manifest()
                        assert manifest.exists()
                        notice.assert_not_called()
                        assert "Saved: library.json" in app.sample_save_status.get()
                        assert "WAVs stay separate" in app.sample_save_status.get()
                    root.update()
                    for control in (
                        *app.modern_tool_buttons.values(),
                        *app.sample_selection_buttons,
                        app.sample_tree,
                    ):
                        assert control.winfo_ismapped()
                        assert root.winfo_rootx() <= control.winfo_rootx()
                        assert (
                            control.winfo_rootx() + control.winfo_width()
                            <= root.winfo_rootx() + root.winfo_width()
                        )
                        assert (
                            control.winfo_rooty() + control.winfo_height()
                            <= root.winfo_rooty() + root.winfo_height()
                        )
                    # A Windows runner can exercise a larger window than its desktop,
                    # but cannot capture clipped regions. Only save complete screenshots;
                    # the Linux/Xvfb job provides the complementary full layout evidence.
                    if (
                        root.winfo_rootx() + root.winfo_width() <= root.winfo_screenwidth()
                        and root.winfo_rooty() + root.winfo_height() <= root.winfo_screenheight()
                    ):
                        ImageGrab.grab(
                            bbox=(
                                root.winfo_rootx(),
                                root.winfo_rooty(),
                                root.winfo_rootx() + root.winfo_width(),
                                root.winfo_rooty() + root.winfo_height(),
                            )
                        ).save(output / f"workspace-{state}.png")
                    elif sys.platform != "win32":
                        raise AssertionError("The layout CI desktop must fit the studio window")
                backend.assert_not_called()
                monitor.assert_not_called()
                assert not errors, errors
                root.destroy()
        finally:
            os.chdir(original_cwd)
    (output / "workspace-results.json").write_text(
        json.dumps(
            {
                "result": "PASS",
                "platform": sys.platform,
                "capture": "complete screenshots only; Windows small-desktop runs exercise widgets without full-window visual acceptance",
                "viewport": [1180, 760],
                "checks": [
                    "composed stable GUI with all plugins",
                    "local first-use and selected-file status",
                    "keyboard home navigation and focus",
                    "diagnostics remain in Tools menu",
                    "local import without device activation",
                    "manifest save explains referenced audio",
                    "import marks library unsaved and successful save clears it inline",
                    "home actions and sample controls within minimum window",
                    "no MIDI or audio activation",
                    "no Tk callback errors",
                    "all hardware legends fit their buttons at minimum studio width",
                ],
                "not_run": ["physical hardware", "audible output", "human usability study"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
