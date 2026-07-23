"""Daemon glue layer: tray (AyatanaAppIndicator3), D-Bus service
(com.tomenotas.Daemon) and the GTK main loop.

Kept deliberately thin and dumb: it only builds the components and
delegates to the (tested) DaemonCore. Stays outside the coverage metric
(see pyproject.toml) and is validated manually — see "Testing changes"
in CLAUDE.md.
"""

import os
import signal
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import Gio, GLib, Gtk  # noqa: E402
from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402

from .. import __version__  # noqa: E402
from ..app.core import DaemonCore  # noqa: E402
from ..domain import state as status  # noqa: E402
from ..domain.errors import MigrationError  # noqa: E402
from ..domain.state import State, ToggleAction  # noqa: E402
from ..infra.config import Config  # noqa: E402
from ..infra.logs import setup_logging  # noqa: E402
from ..infra.notes_db import SqliteNoteStore  # noqa: E402
from ..infra.notify import Notifier  # noqa: E402
from ..infra.player import Player  # noqa: E402
from ..infra.recorder import Recorder  # noqa: E402
from ..infra.shortcuts import ShortcutManager  # noqa: E402
from ..infra.downloads import Downloader, ModelManager  # noqa: E402
from ..infra.transcriber import Transcriber  # noqa: E402
from ..infra.voices import VoiceManager  # noqa: E402
from .window import NotesWindow  # noqa: E402

BUS_NAME = "com.tomenotas.Daemon"
OBJECT_PATH = "/com/tomenotas/Daemon"

# Fallback when the project SVGs are not installed (no pulse)
FALLBACK_ICONS = {
    State.IDLE: "audio-input-microphone-symbolic",
    State.RECORDING: "media-record-symbolic",
    State.TRANSCRIBING: "system-run-symbolic",
}

INTROSPECTION_XML = """
<node>
  <interface name="com.tomenotas.Daemon">
    <method name="ToggleRecording"/>
    <method name="ReadCurrentNote"/>
    <method name="ShowWindow"/>
    <method name="ShowSettings"/>
    <method name="Ping">
      <arg type="s" name="reply" direction="out"/>
    </method>
  </interface>
</node>
"""


class TrayDaemon:
    def __init__(self, core: DaemonCore, config: Config,
                 store: SqliteNoteStore, player: Player, notifier: Notifier,
                 shortcuts: ShortcutManager, voices: VoiceManager,
                 models: ModelManager):
        self._core = core
        self._config = config
        self._store = store
        self._player = player
        self._notifier = notifier
        self._shortcuts = shortcuts
        self._voices = voices
        self._models = models
        self._window = None  # created on demand at the first "Abrir"
        self._pulser = status.Pulser()
        self._pulsing = False
        self._setup_indicator()
        self._setup_dbus()
        # Fase 4: the icon mirrors the state machine. finish_recording
        # runs in a thread, so the update is posted to the main thread.
        core.on_state_change = (
            lambda state: GLib.idle_add(self._on_state, state)
        )
        # Fase 5: clicking a notification opens the notes window
        notifier.on_activate = (
            lambda: GLib.idle_add(self.show_window)
        )

    # ---------------- Tray (AppIndicator) ----------------

    def _setup_indicator(self):
        icons_dir = self._config.icons_dir
        self._has_icons = icons_dir.is_dir()
        if self._has_icons:
            self.indicator = AppIndicator.Indicator.new_with_path(
                "tomenotas",
                status.icon(self._core.state),
                AppIndicator.IndicatorCategory.APPLICATION_STATUS,
                str(icons_dir),
            )
        else:
            self.indicator = AppIndicator.Indicator.new(
                "tomenotas",
                FALLBACK_ICONS[self._core.state],
                AppIndicator.IndicatorCategory.APPLICATION_STATUS,
            )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title(
            f"Tomenotas — {status.tooltip(self._core.state)}"
        )

        menu = Gtk.Menu()

        open_item = Gtk.MenuItem(label="Abrir")
        open_item.connect("activate", self.on_open)
        menu.append(open_item)

        settings_item = Gtk.MenuItem(label="Configurações")
        settings_item.connect("activate", self.on_settings)
        menu.append(settings_item)

        quit_item = Gtk.MenuItem(label="Sair")
        quit_item.connect("activate", self.on_quit)
        menu.append(quit_item)

        menu.show_all()
        self.indicator.set_menu(menu)

    def _on_state(self, state):
        """Applies the state to the icon/tooltip (main thread)."""
        hint = status.tooltip(state)
        self.indicator.set_title(f"Tomenotas — {hint}")
        if not self._has_icons:
            self.indicator.set_icon_full(FALLBACK_ICONS[state], hint)
            return False
        self.indicator.set_icon_full(status.icon(state), hint)
        if status.pulses(state) and not self._pulsing:
            self._pulsing = True
            GLib.timeout_add(600, self._pulse_tick)
        return False  # idle_add: do not repeat

    def _pulse_tick(self):
        state = self._core.state
        if not status.pulses(state):
            # _on_state already set the idle icon; just stop the timer
            self._pulsing = False
            return False
        self.indicator.set_icon_full(
            self._pulser.next_icon(state), status.tooltip(state)
        )
        return True

    def on_open(self, _item):
        self.show_window()

    def show_window(self, page=None):
        if self._window is None:
            self._window = NotesWindow(self._store, self._player,
                                       self._notifier, self._shortcuts,
                                       self._voices, self._models)
        self._window.show_page(page)

    def on_settings(self, _item):
        self.show_window("config")

    def on_quit(self, _item):
        self.quit()

    def quit(self):
        self._core.shutdown()
        self._player.stop()
        Gtk.main_quit()

    # ---------------- D-Bus (com.tomenotas.Daemon) ----------------

    def _setup_dbus(self):
        self._node_info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)
        self._owner_id = Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.NONE,
            self._on_bus_acquired,
            None,
            self._on_name_lost,
        )

    def _on_bus_acquired(self, connection, _name):
        connection.register_object(
            OBJECT_PATH,
            self._node_info.interfaces[0],
            self._on_method_call,
            None,
            None,
        )

    def _on_name_lost(self, _connection, _name):
        # Another instance already owns the name (or we lost the
        # connection): no point in running duplicated.
        print(f"tomenotas-daemon: nome {BUS_NAME} indisponível "
              "(já existe outra instância rodando?)", file=sys.stderr)
        Gtk.main_quit()

    def _on_method_call(self, _conn, _sender, _path, _iface, method,
                        _params, invocation):
        if method == "ToggleRecording":
            self._handle_toggle()
            invocation.return_value(None)
        elif method == "ReadCurrentNote":
            # TTS synthesis is slow — thread, like the transcription
            threading.Thread(
                target=self._core.read_current_note, daemon=True
            ).start()
            invocation.return_value(None)
        elif method == "ShowWindow":
            self.show_window()
            invocation.return_value(None)
        elif method == "ShowSettings":
            self.show_window("config")
            invocation.return_value(None)
        elif method == "Ping":
            invocation.return_value(GLib.Variant("(s)", ("pong",)))

    def _handle_toggle(self):
        action = self._core.toggle()
        if action is ToggleAction.STOP_REQUESTED:
            # Transcription is slow — run it in a thread so the main loop
            # stays responsive (tray and D-Bus keep answering).
            threading.Thread(
                target=self._core.finish_recording, daemon=True
            ).start()


def main():
    config = Config.load()
    log = setup_logging(config.base_dir / "daemon.log")
    # The daemon can be launched from any directory (terminal, autostart,
    # launcher) — including one that may cease to exist. Anchor the cwd
    # at base_dir so subprocesses (whisper/piper/arecord) never inherit
    # an invalid cwd (whisper-cli aborts if getcwd() fails).
    os.chdir(config.base_dir)
    log.info("daemon starting (tomenotas %s)", __version__)
    notifier = Notifier()
    try:
        store = SqliteNoteStore(config.db_path, config.notes_dir)
    except MigrationError as error:
        # Database intact at the previous version (rollback + backup) —
        # warn and refuse to start rather than run with an incompatible
        # schema.
        log.error("%s", error)
        notifier.send("Erro no banco de notas", str(error))
        sys.exit(1)
    player = Player(config.piper_bin, config.piper_model, config.tts_tmp)
    transcriber = Transcriber(
        config.whisper_bin, config.whisper_model, config.language
    )
    core = DaemonCore(
        recorder=Recorder(config.audio_tmp),
        transcriber=transcriber,
        notes=store,
        notifier=notifier,
        player=player,
    )
    shortcuts = ShortcutManager(config.bin_dir)
    # First run from the .deb (no install.sh): register the default
    # keybindings; no-op when they already exist (never overrides).
    try:
        registered = shortcuts.ensure_defaults()
        if registered:
            log.info("default keybindings registered: %s", registered)
    except Exception as error:  # gsettings absent/broken must not kill us
        log.warning("could not register default keybindings: %s", error)
    voices = VoiceManager(player, config.piper_model)
    models = ModelManager(transcriber, config.whisper_model,
                          config.models_dir, Downloader())
    app = TrayDaemon(core, config, store, player, notifier, shortcuts,
                     voices, models)
    # First run (Fase A): models are downloaded by the app, not by
    # install.sh — open Configurações so the user can fetch them.
    if not transcriber.is_ready() or not voices.list_voices():
        log.info("first run: models missing, opening Configurações")
        notifier.send(
            "Tomenotas",
            "Primeiro uso: baixe o modelo de transcrição e a voz em "
            "Configurações.",
        )
        GLib.idle_add(app.show_window, "config")
    # Ctrl+C in the terminal exits cleanly (useful when run by hand)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    Gtk.main()
    log.info("daemon stopped")


if __name__ == "__main__":
    main()
