from types import SimpleNamespace
from unittest.mock import Mock

from ko2_daw.gui import KO2DawApp
from ko2_daw.samples import SampleLibrary


def test_partial_wav_import_reports_skips_and_keeps_successes(monkeypatch):
    library = Mock()
    library.add_wav.side_effect = [object(), ValueError("Not a WAV file")]
    view = SimpleNamespace(
        sample_library=library, _log=Mock(), _refresh_sample_tree=Mock(), _set_action=Mock()
    )
    warning = Mock()
    monkeypatch.setattr(
        "ko2_daw.gui.filedialog.askopenfilenames", lambda **kw: ["good.wav", "broken.wav"]
    )
    monkeypatch.setattr("ko2_daw.gui.messagebox.showwarning", warning)
    KO2DawApp._import_wav(view)
    assert library.add_wav.call_count == 2
    assert "1 skipped" in view._set_action.call_args.args[0]
    assert "broken.wav" in warning.call_args.args[1]
    view._refresh_sample_tree.assert_called_once()


def test_sample_refresh_preserves_selection_and_disables_empty_actions():
    view = KO2DawApp.__new__(KO2DawApp)
    view.sample_tree = Mock()
    view.sample_status = Mock()
    view.sample_selection_buttons = [Mock(), Mock()]
    view.sample_library = SampleLibrary()
    view.sample_tree.get_children.return_value = ("2", "5")
    view.sample_tree.selection.return_value = ("5",)
    view._refresh_sample_tree()
    view.sample_tree.selection_set.assert_called_once_with("5")
    for button in view.sample_selection_buttons:
        button.configure.assert_called_with(state="normal")
    view.sample_tree.reset_mock()
    view.sample_tree.selection.return_value = ()
    view._refresh_sample_tree()
    view.sample_tree.selection_set.assert_called_once_with("2")
    view.sample_tree.get_children.return_value = ()
    view.sample_tree.reset_mock()
    view._refresh_sample_tree()
    view.sample_tree.selection_set.assert_not_called()
    for button in view.sample_selection_buttons:
        button.configure.assert_called_with(state="disabled")
