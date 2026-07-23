"""Camada de cola do daemon: bandeja (AyatanaAppIndicator3), serviço D-Bus
(com.tomenotas.Daemon) e main loop GTK.

Mantida deliberadamente fina e burra: só constrói os componentes e delega
para o DaemonCore (testado). Fica fora da métrica de cobertura (ver
pyproject.toml) e é validada manualmente — ver "Testing changes" no
CLAUDE.md.
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
from ..infra.transcriber import Transcriber  # noqa: E402
from .window import NotesWindow  # noqa: E402

BUS_NAME = "com.tomenotas.Daemon"
OBJECT_PATH = "/com/tomenotas/Daemon"

# Fallback quando os SVGs do projeto não estão instalados (sem pulso)
FALLBACK_ICONES = {
    State.IDLE: "audio-input-microphone-symbolic",
    State.RECORDING: "media-record-symbolic",
    State.TRANSCRIBING: "system-run-symbolic",
}

INTROSPECTION_XML = """
<node>
  <interface name="com.tomenotas.Daemon">
    <method name="ToggleRecording"/>
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
                 shortcuts: ShortcutManager):
        self._core = core
        self._config = config
        self._store = store
        self._player = player
        self._notifier = notifier
        self._shortcuts = shortcuts
        self._window = None  # criada sob demanda no primeiro "Abrir"
        self._pulsador = status.Pulsador()
        self._pulsando = False
        self._setup_indicator()
        self._setup_dbus()
        # Fase 4: o ícone reflete a máquina de estados. finish_recording
        # roda em thread, então o update vai para a thread principal.
        core.on_state_change = (
            lambda estado: GLib.idle_add(self._on_estado, estado)
        )
        # Fase 5: clicar numa notificação abre a janela de notas
        notifier.on_activate = (
            lambda: GLib.idle_add(self.show_window)
        )

    # ---------------- Bandeja (AppIndicator) ----------------

    def _setup_indicator(self):
        icons_dir = self._config.icons_dir
        self._tem_icones = icons_dir.is_dir()
        if self._tem_icones:
            self.indicator = AppIndicator.Indicator.new_with_path(
                "tomenotas",
                status.icone(self._core.state),
                AppIndicator.IndicatorCategory.APPLICATION_STATUS,
                str(icons_dir),
            )
        else:
            self.indicator = AppIndicator.Indicator.new(
                "tomenotas",
                FALLBACK_ICONES[self._core.state],
                AppIndicator.IndicatorCategory.APPLICATION_STATUS,
            )
        self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self.indicator.set_title(
            f"Tomenotas — {status.tooltip(self._core.state)}"
        )

        menu = Gtk.Menu()

        item_abrir = Gtk.MenuItem(label="Abrir")
        item_abrir.connect("activate", self.on_abrir)
        menu.append(item_abrir)

        item_config = Gtk.MenuItem(label="Configurações")
        item_config.connect("activate", self.on_configuracoes)
        menu.append(item_config)

        item_sair = Gtk.MenuItem(label="Sair")
        item_sair.connect("activate", self.on_sair)
        menu.append(item_sair)

        menu.show_all()
        self.indicator.set_menu(menu)

    def _on_estado(self, estado):
        """Aplica o estado no ícone/tooltip (thread principal)."""
        dica = status.tooltip(estado)
        self.indicator.set_title(f"Tomenotas — {dica}")
        if not self._tem_icones:
            self.indicator.set_icon_full(FALLBACK_ICONES[estado], dica)
            return False
        self.indicator.set_icon_full(status.icone(estado), dica)
        if status.pulsa(estado) and not self._pulsando:
            self._pulsando = True
            GLib.timeout_add(600, self._pulso_tick)
        return False  # idle_add: não repetir

    def _pulso_tick(self):
        estado = self._core.state
        if not status.pulsa(estado):
            # _on_estado já pôs o ícone de ocioso; só encerra o timer
            self._pulsando = False
            return False
        self.indicator.set_icon_full(
            self._pulsador.proximo(estado), status.tooltip(estado)
        )
        return True

    def on_abrir(self, _item):
        self.show_window()

    def show_window(self, pagina=None):
        if self._window is None:
            self._window = NotesWindow(self._store, self._player,
                                       self._notifier, self._shortcuts)
        self._window.mostrar(pagina)

    def on_configuracoes(self, _item):
        self.show_window("config")

    def on_sair(self, _item):
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
        # Outra instância já é dona do nome (ou perdemos a conexão): não faz
        # sentido continuar rodando duplicado.
        print(f"tomenotas-daemon: nome {BUS_NAME} indisponível "
              "(já existe outra instância rodando?)", file=sys.stderr)
        Gtk.main_quit()

    def _on_method_call(self, _conn, _sender, _path, _iface, method,
                        _params, invocation):
        if method == "ToggleRecording":
            self._handle_toggle()
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
        acao = self._core.toggle()
        if acao is ToggleAction.STOP_REQUESTED:
            # A transcrição é lenta — roda numa thread para não travar o
            # main loop (bandeja e D-Bus continuam respondendo).
            threading.Thread(
                target=self._core.finish_recording, daemon=True
            ).start()


def main():
    config = Config.load()
    log = setup_logging(config.base_dir / "daemon.log")
    # O daemon pode ser lançado de qualquer diretório (terminal, autostart,
    # lançador) — inclusive de um que deixe de existir depois. Ancora o cwd
    # no base_dir para que os subprocessos (whisper/piper/arecord) nunca
    # herdem um cwd inválido (o whisper-cli aborta se getcwd() falhar).
    os.chdir(config.base_dir)
    log.info("daemon iniciando (tomenotas %s)", __version__)
    notifier = Notifier()
    try:
        store = SqliteNoteStore(config.db_path, config.notes_dir)
    except MigrationError as erro:
        # Banco intacto na versão anterior (rollback + backup) — avisa e
        # não sobe, em vez de rodar com esquema incompatível.
        log.error("%s", erro)
        notifier.send("Erro no banco de notas", str(erro))
        sys.exit(1)
    player = Player(config.piper_bin, config.piper_model, config.tts_tmp)
    core = DaemonCore(
        recorder=Recorder(config.audio_tmp),
        transcriber=Transcriber(
            config.whisper_bin, config.whisper_model, config.language
        ),
        notes=store,
        notifier=notifier,
    )
    shortcuts = ShortcutManager(config.bin_dir)
    app = TrayDaemon(core, config, store, player, notifier, shortcuts)
    # Ctrl+C no terminal encerra limpo (útil ao rodar o daemon na mão)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    Gtk.main()
    log.info("daemon encerrado")


if __name__ == "__main__":
    main()
