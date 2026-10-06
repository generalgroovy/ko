"""Real Tk interactions on a Windows CI desktop; no playback or MIDI activation."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import tkinter as tk
import wave
from pathlib import Path
from tkinter import ttk
from unittest.mock import patch

from PIL import ImageGrab

from ko2_daw.sample_edit import slice_copies
from ko2_daw.sample_editor import SampleEditor
from ko2_daw.samples import SampleLibrary


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def main():
    output = Path("docs/evidence/sample-editor-2026-10-06")
    output.mkdir(parents=True, exist_ok=True)
    root = tk.Tk()
    root.withdraw()
    errors = []
    root.report_callback_exception = lambda *args: errors.append(str(args))

    def wait_for(predicate):
        deadline = time.monotonic() + 15
        while not predicate():
            root.update()
            assert time.monotonic() < deadline, "Tk operation timed out"
            time.sleep(0.01)
        root.update()

    with tempfile.TemporaryDirectory(prefix="ko-sample-ui-") as directory:
        work = Path(directory)
        source = work / "rhythm.wav"
        raw = bytes(index % 256 for index in range(120001 * 4))
        with wave.open(str(source), "wb") as writer:
            writer.setparams((2, 2, 48000, 120001, "NONE", "not compressed"))
            writer.writeframes(raw)
        original = source.read_bytes()
        library = SampleLibrary()
        completed = []

        def saved(paths):
            library.add_wavs(paths)
            completed.extend(paths)

        editor = SampleEditor(root, str(source), saved)
        wait_for(lambda: not editor.reading)
        assert editor.frames == 120001 and editor.rate == 48000
        assert editor.save_button["state"] == "normal"
        editor.canvas.focus_force()
        root.update()
        editor.canvas.event_generate("<Right>")
        root.update()
        assert editor._region()[0] == 1
        editor.canvas.event_generate("<Shift-Right>")
        root.update()
        assert editor._region()[0] == 481
        editor.canvas.event_generate("<Home>")
        root.update()
        assert editor._region()[0] == 0
        end_radio = next(
            w
            for w in descendants(editor)
            if isinstance(w, ttk.Radiobutton) and str(w["text"]) == "End (s)"
        )
        end_radio.invoke()
        editor.canvas.event_generate("<Home>")
        root.update()
        assert editor._region() == (0, 1)
        editor.reset_button.invoke()
        root.update()
        start_entry = next(
            w
            for w in descendants(editor)
            if isinstance(w, ttk.Entry) and str(w["textvariable"]) == str(editor.start)
        )
        start_entry.delete(0, "end")
        start_entry.insert(0, "oops")
        root.update()
        assert editor.save_button["state"] == "disabled"
        start_entry.delete(0, "end")
        start_entry.insert(0, "0.25")
        editor.count_box.set("4 slices")
        root.update()
        assert len(editor.canvas.find_all()) > len(editor.peaks)
        assert "108,001 frames" in editor.selection.get()

        for width in (680, 460):
            editor.geometry(f"{width}x390+20+20")
            root.update()
            for widget in descendants(editor):
                if widget.winfo_ismapped() and isinstance(
                    widget, (ttk.Button, ttk.Entry, ttk.Combobox, ttk.Radiobutton)
                ):
                    assert widget.winfo_rootx() >= editor.winfo_rootx()
                    assert (
                        widget.winfo_rootx() + widget.winfo_width()
                        <= editor.winfo_rootx() + editor.winfo_width()
                    )
                    assert (
                        widget.winfo_rooty() + widget.winfo_height()
                        <= editor.winfo_rooty() + editor.winfo_height()
                    )
            ImageGrab.grab(
                bbox=(
                    editor.winfo_rootx(),
                    editor.winfo_rooty(),
                    editor.winfo_rootx() + editor.winfo_width(),
                    editor.winfo_rooty() + editor.winfo_height(),
                )
            ).save(output / f"sample-editor-{width}.png")

        with patch("ko2_daw.sample_editor.filedialog.askdirectory", return_value=str(work)):
            editor.save_button.invoke()
        assert editor.saving
        editor._close()
        assert editor.winfo_exists() and "Cancel" in editor.status.get()
        wait_for(lambda: not editor.saving)
        assert len(completed) == 4 and len(library.samples) == 4
        selected = b""
        for path in completed:
            with wave.open(str(path), "rb") as reader:
                selected += reader.readframes(reader.getnframes())
        assert selected == raw[12000 * 4 :]
        with patch("ko2_daw.sample_editor.filedialog.askdirectory", return_value=str(work)):
            editor.save_button.invoke()
        wait_for(lambda: not editor.saving)
        assert len(completed) == 4
        assert editor.save_button["state"] == "normal"
        assert source.read_bytes() == original

        destination = work / "cancelled"
        destination.mkdir()
        gate = threading.Event()

        def gated_export(*args, **kwargs):
            assert gate.wait(5)
            return slice_copies(*args, **kwargs)

        with (
            patch("ko2_daw.sample_editor.filedialog.askdirectory", return_value=str(destination)),
            patch("ko2_daw.sample_editor.slice_copies", side_effect=gated_export),
        ):
            editor.save_button.invoke()
            editor.cancel_button.invoke()
            editor._close()
            assert editor.winfo_exists()
            gate.set()
            wait_for(lambda: not editor.saving)
        assert "Cancelled" in editor.status.get()
        assert not list(destination.iterdir()) and len(completed) == 4
        assert editor.save_button["state"] == "normal"
        assert not errors, errors
        editor._close()
    root.destroy()
    (output / "results.json").write_text(
        json.dumps(
            {
                "result": "PASS",
                "platform": "Windows CI",
                "tk": tk.TkVersion,
                "viewports": [680, 460],
                "checks": [
                    "background waveform ready",
                    "keyboard frame and 10 ms steps",
                    "edge radio and boundary keys",
                    "invalid seconds disable export",
                    "odd-frame 4-slice partition",
                    "all controls within minimum window",
                    "native save action creates exact PCM and adds library batch",
                    "close waits during write",
                    "existing folder preserved and controls recover",
                    "Cancel signals real worker and cleans output",
                    "original bytes unchanged",
                    "no Tk callback errors",
                ],
                "not_run": ["audible output", "MIDI hardware", "installer execution"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
