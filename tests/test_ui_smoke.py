"""UI smoke test: builds the real (GTK) window and exercises the flow of
opening a note's detail view — the path unit tests don't cover because
ui/ stays outside the metric.

Only runs when a display is available (local); skipped in environments
without GTK/display. This test exists because a refactor once removed
the `.note` attribute from the rows and clicking started failing
silently.
"""

import os
from pathlib import Path

import pytest

has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
gtk_ok = True
try:  # pragma: no cover - depends on the environment
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk  # noqa: F401
except Exception:  # pragma: no cover
    gtk_ok = False

pytestmark = pytest.mark.skipif(
    not (has_display and gtk_ok), reason="requires GTK and a display"
)


@pytest.fixture
def window(tmp_path):
    from tomenotas.app.alarm import CriticalAlarm
    from tomenotas.infra.config import Config
    from tomenotas.infra.downloads import Downloader, ModelManager
    from tomenotas.infra.notes_db import SqliteNoteStore
    from tomenotas.infra.notify import Notifier
    from tomenotas.infra.player import Player
    from tomenotas.infra.shortcuts import ShortcutManager
    from tomenotas.infra.transcriber import Transcriber
    from tomenotas.infra.voices import VoiceManager
    from tomenotas.ui.window import NotesWindow

    from tomenotas.infra.sound import AlarmSound

    window = _make_window(tmp_path)
    window.refresh()
    # makes the stack children "visible" without mapping the window
    # (Gtk.Stack won't switch to a child with visible=False)
    window._notes_stack.show_all()
    yield window
    window.destroy()


def _make_window(tmp_path, backend="gsettings"):
    from tomenotas.app.alarm import CriticalAlarm
    from tomenotas.infra.config import Config
    from tomenotas.infra.downloads import Downloader, ModelManager
    from tomenotas.infra.notes_db import SqliteNoteStore
    from tomenotas.infra.notify import Notifier
    from tomenotas.infra.player import Player
    from tomenotas.infra.shortcuts import ShortcutManager
    from tomenotas.infra.sound import AlarmSound
    from tomenotas.infra.transcriber import Transcriber
    from tomenotas.infra.voices import VoiceManager
    from tomenotas.ui.window import NotesWindow

    store = SqliteNoteStore(tmp_path / "notes.db", tmp_path / "notes")
    store.save("nota de teste para o detalhe")
    player = Player(Path("/x/piper"), Path("/x/voz.onnx"), tmp_path / "t.wav")
    transcriber = Transcriber(Path("/x/whisper"), Path("/x/ggml-medium.bin"))
    notifier = Notifier(spawn=lambda cmd, **kw: None)  # no real notifications
    sound = AlarmSound(Path("/x/toque.oga"), spawn=lambda cmd: None)
    alarm = CriticalAlarm(store, notifier, sound,
                          schedule=lambda s, cb: 1, cancel=lambda h: None,
                          interval=300)
    return NotesWindow(
        store,
        player,
        notifier,
        ShortcutManager(Path.home() / "tomenotas"),
        VoiceManager(player, Path("/x/voz.onnx"),
                     config_path=tmp_path / "config.json"),
        ModelManager(transcriber, Path("/x/ggml-medium.bin"),
                     tmp_path / "models", Downloader(),
                     config_path=tmp_path / "config.json"),
        Config(base_dir=tmp_path / "dados"),
        alarm,
        sound,
        backend=backend,
    )


def test_settings_capture_keys_in_gsettings_mode(tmp_path):
    window = _make_window(tmp_path, backend="gsettings")
    try:
        window.refresh()
        settings = window._settings
        assert len(settings._buttons) == 6  # one capture button per action
    finally:
        window.destroy()


def test_settings_are_read_only_in_portal_mode(tmp_path):
    window = _make_window(tmp_path, backend="portal")
    try:
        window.refresh()  # must be safe with no capture buttons
        settings = window._settings
        assert settings._buttons == {}  # no in-app capture
        # a stray key must not be captured (nothing is being assigned)
        assert settings.handle_key(object()) is False
    finally:
        window.destroy()


def test_streaming_and_wakeword_sections_default_off(tmp_path):
    window = _make_window(tmp_path)
    try:
        window.refresh()
        settings = window._settings
        assert settings._stream_switch.get_active() is False
        assert settings._wakeword_switch.get_active() is False  # opt-in
        assert 0.1 <= settings._wakeword_scale.get_value() <= 0.9
    finally:
        window.destroy()


def test_rows_carry_the_note_and_activating_opens_the_detail(window):
    (row,) = window._list.get_children()
    assert getattr(row, "note", None) is not None
    assert row.get_activatable()

    window._on_note_activated(window._list, row)

    assert window._notes_stack.get_visible_child_name() == "detail"
    assert window._editor_text() == "nota de teste para o detalhe"


def test_saving_an_edit_persists_and_returns_to_the_list(window):
    (row,) = window._list.get_children()
    window._on_note_activated(window._list, row)
    window._editor.get_buffer().set_text("texto editado no teste")

    window._on_detail_save(None)

    assert window._notes_stack.get_visible_child_name() == "list"
    (note,) = window._store.list()
    assert note.text == "texto editado no teste"
