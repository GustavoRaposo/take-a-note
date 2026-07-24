"""Settings page, embedded in the main window sidebar, split into
sections:

- Atalhos: keyboard shortcut capture, delegated to the (tested)
  ShortcutManager, which writes to gsettings with immediate effect.
- Voz: Piper voice picker (VoiceManager) + first-run download of the
  default pt_BR voice.
- Modelo de transcrição: whisper model download/switch (ModelManager,
  first-run flow of Fase A — models are no longer shipped by install.sh).

Glue layer, outside the coverage metric — do not let logic grow here.

Note (Wayland/GNOME): the combination currently registered as a global
shortcut is captured by the shell before it reaches the window — to
change it, press a different combination.
"""

import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from ..domain.errors import DownloadError  # noqa: E402
from ..infra.config import update_config_file  # noqa: E402
from ..infra.downloads import WHISPER_MODELS  # noqa: E402


class SettingsPage(Gtk.Box):
    """The main window forwards key-press-event to handle_key() while
    this page is visible."""

    def __init__(self, manager, voices, models, store, config, alarm,
                 sound, notifier, window, backend="gsettings", core=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                         margin=16)
        self._manager = manager
        self._voices = voices
        self._models = models
        self._store = store
        self._alarm = alarm
        self._sound = sound
        self._core = core  # live daemon core (to toggle streaming at runtime)
        self._notifier = notifier
        self._window = window  # parent of the conflict dialogs
        self._updating_stream_switch = False
        # "gsettings" → capture keys in-app; "portal" → the system owns
        # the key assignment, so we only show the shortcuts read-only
        self._backend = backend
        self._capturing = None  # (action_id, button) while capturing
        self._reloading_voices = False  # suppress "changed" during rebuild
        self._reloading_models = False

        # ---------------- Section: Atalhos ----------------

        self.pack_start(self._section_label("Atalhos"), False, False, 0)

        grid = Gtk.Grid(row_spacing=8, column_spacing=12)
        self.pack_start(grid, False, False, 0)

        self._buttons = {}
        for i, action in enumerate(self._manager.actions.values()):
            label = Gtk.Label(label=action.title, xalign=0)
            grid.attach(label, 0, i, 1, 1)
            if self._backend == "portal":
                # read-only: the system assigns the keys, not the app
                trigger = Gtk.Label(label=action.default, xalign=0)
                trigger.get_style_context().add_class("dim-label")
                grid.attach(trigger, 1, i, 1, 1)
            else:
                button = Gtk.Button(label=self._button_label(action.id))
                button.set_hexpand(True)
                button.connect("clicked", self._on_assign, action.id)
                grid.attach(button, 1, i, 1, 1)
                self._buttons[action.id] = button

        if self._backend == "portal":
            actions_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                                  spacing=6)
            open_btn = Gtk.Button(label="Configurar atalhos no sistema")
            open_btn.connect("clicked", self._on_open_system_shortcuts)
            actions_row.pack_start(open_btn, False, False, 0)
            help_btn = Gtk.Button(label="?")
            help_btn.set_tooltip_text("Como configurar os atalhos")
            help_btn.connect("clicked", self._on_shortcuts_help)
            actions_row.pack_start(help_btn, False, False, 0)
            self.pack_start(actions_row, False, False, 0)
            hint = Gtk.Label(
                label="Neste ambiente, os atalhos são gerenciados pelo "
                      "sistema. Use o botão acima para abrir as "
                      "Configurações de Atalhos e definir as teclas (os "
                      "valores acima são apenas os sugeridos)."
            )
        else:
            hint = Gtk.Label(label="Clique num atalho e pressione a nova "
                                   "combinação de teclas (Esc cancela).")
        hint.get_style_context().add_class("dim-label")
        hint.set_line_wrap(True)
        hint.set_xalign(0)
        self.pack_start(hint, False, False, 0)

        # ---------------- Section: Voz ----------------

        self.pack_start(self._section_label("Voz"), False, False, 8)

        voice_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                            spacing=12)
        voice_row.pack_start(Gtk.Label(label="Voz do Piper", xalign=0),
                             False, False, 0)
        self._voice_combo = Gtk.ComboBoxText()
        self._voice_combo.set_hexpand(True)
        self._voice_combo.connect("changed", self._on_voice_changed)
        voice_row.pack_start(self._voice_combo, True, True, 0)

        help_button = Gtk.Button(label="?")
        help_button.set_tooltip_text("Como baixar mais vozes")
        help_button.connect("clicked", self._on_voice_help)
        voice_row.pack_start(help_button, False, False, 0)
        self.pack_start(voice_row, False, False, 0)

        voice_hint = Gtk.Label(
            label="A troca vale já para a próxima leitura."
        )
        voice_hint.get_style_context().add_class("dim-label")
        voice_hint.set_line_wrap(True)
        voice_hint.set_xalign(0)
        self.pack_start(voice_hint, False, False, 0)

        # First-run: no voice installed yet — offer the default download
        self._voice_download = Gtk.Button(label="Baixar voz padrão (pt_BR)")
        self._voice_download.set_no_show_all(True)
        self._voice_download.connect("clicked", self._on_voice_download)
        self.pack_start(self._voice_download, False, False, 0)

        self._voice_progress = Gtk.ProgressBar(show_text=True)
        self._voice_progress.set_no_show_all(True)
        self.pack_start(self._voice_progress, False, False, 0)

        # ---------------- Section: Modelo de transcrição ----------------

        self.pack_start(self._section_label("Modelo de transcrição"),
                        False, False, 8)

        model_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                            spacing=12)
        model_row.pack_start(Gtk.Label(label="Modelo Whisper", xalign=0),
                             False, False, 0)
        self._model_combo = Gtk.ComboBoxText()
        self._model_combo.set_hexpand(True)
        self._model_combo.connect("changed", self._on_model_changed)
        model_row.pack_start(self._model_combo, True, True, 0)
        self._model_button = Gtk.Button(label="Baixar")
        self._model_button.connect("clicked", self._on_model_action)
        model_row.pack_start(self._model_button, False, False, 0)
        self.pack_start(model_row, False, False, 0)

        self._model_progress = Gtk.ProgressBar(show_text=True)
        self._model_progress.set_no_show_all(True)
        self.pack_start(self._model_progress, False, False, 0)

        model_hint = Gtk.Label(
            label="Modelos maiores transcrevem melhor, porém mais devagar "
                  "e ocupando mais espaço em disco."
        )
        model_hint.get_style_context().add_class("dim-label")
        model_hint.set_line_wrap(True)
        model_hint.set_xalign(0)
        self.pack_start(model_hint, False, False, 0)

        # ---------------- Section: Transcrição ao vivo ----------------

        self.pack_start(self._section_label("Transcrição ao vivo"),
                        False, False, 8)

        stream_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                             spacing=12)
        stream_row.pack_start(
            Gtk.Label(label="Prévia enquanto você fala", xalign=0),
            False, False, 0)
        self._stream_switch = Gtk.Switch(active=config.stream_enabled)
        self._stream_switch.set_valign(Gtk.Align.CENTER)
        self._stream_switch.connect("notify::active", self._on_stream_toggle)
        stream_row.pack_start(self._stream_switch, False, False, 0)
        self._stream_model_combo = Gtk.ComboBoxText()
        self._stream_model_combo.set_hexpand(True)
        for size, label in [("base", "base (recomendado)"),
                            ("tiny", "tiny (mais rápido)")]:
            self._stream_model_combo.append(size, label)
        self._stream_model_combo.set_active_id(config.stream_model)
        self._stream_model_combo.connect("changed",
                                         self._on_stream_model_changed)
        stream_row.pack_start(self._stream_model_combo, True, True, 0)
        self.pack_start(stream_row, False, False, 0)

        self._stream_progress = Gtk.ProgressBar(show_text=True)
        self._stream_progress.set_no_show_all(True)
        self.pack_start(self._stream_progress, False, False, 0)

        stream_hint = Gtk.Label(
            label="Abre uma janela com o texto sendo transcrito enquanto "
                  "você grava (Super+R / Super+I). Usa um modelo pequeno "
                  "só para a prévia — a nota final continua vindo do "
                  "modelo de transcrição. Não vale no modo reunião."
        )
        stream_hint.get_style_context().add_class("dim-label")
        stream_hint.set_line_wrap(True)
        stream_hint.set_xalign(0)
        self.pack_start(stream_hint, False, False, 0)

        # ---------------- Section: Wake word ----------------

        self.pack_start(self._section_label("Wake word"), False, False, 8)

        ww_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        ww_row.pack_start(
            Gtk.Label(label="Acionar por voz (\"Tomenotas\")", xalign=0),
            False, False, 0)
        self._wakeword_switch = Gtk.Switch(active=config.wakeword_enabled)
        self._wakeword_switch.set_valign(Gtk.Align.CENTER)
        self._wakeword_switch.connect("notify::active",
                                     self._on_wakeword_toggle)
        ww_row.pack_start(self._wakeword_switch, False, False, 0)
        self.pack_start(ww_row, False, False, 0)

        sens_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        sens_row.pack_start(Gtk.Label(label="Sensibilidade", xalign=0),
                            False, False, 0)
        # higher threshold = less sensitive; show it directly as the value
        self._wakeword_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.1, 0.9, 0.05)
        self._wakeword_scale.set_value(config.wakeword_threshold)
        self._wakeword_scale.set_hexpand(True)
        self._wakeword_scale.set_draw_value(True)
        self._wakeword_scale.connect("value-changed",
                                    self._on_wakeword_sensitivity)
        sens_row.pack_start(self._wakeword_scale, True, True, 0)
        self.pack_start(sens_row, False, False, 0)

        available = core is not None and getattr(core, "_wakeword", None)
        ww_hint = Gtk.Label(
            label=("O daemon escuta continuamente pela palavra e, ao ouvi-la, "
                   "inicia a gravação (como o Super+R). É 100% offline — o "
                   "áudio nunca sai da sua máquina. Limiar maior = menos "
                   "disparos falsos.")
            + ("" if available else
               "\n\nO modelo \"Tomenotas\" ainda não está instalado; ao "
               "instalá-lo, reinicie o app para ativar a escuta.")
        )
        ww_hint.get_style_context().add_class("dim-label")
        ww_hint.set_line_wrap(True)
        ww_hint.set_xalign(0)
        self.pack_start(ww_hint, False, False, 0)

        # ---------------- Section: Notas críticas ----------------

        self.pack_start(self._section_label("Notas críticas"),
                        False, False, 8)

        interval_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                               spacing=12)
        interval_row.pack_start(
            Gtk.Label(label="Notificar a cada", xalign=0), False, False, 0)
        self._interval_combo = Gtk.ComboBoxText()
        self._interval_combo.set_hexpand(True)
        for seconds, label in [("60", "1 minuto"), ("300", "5 minutos"),
                               ("900", "15 minutos"), ("1800", "30 minutos"),
                               ("3600", "1 hora")]:
            self._interval_combo.append(seconds, label)
        if not self._interval_combo.set_active_id(
                str(config.alarm_interval)):
            self._interval_combo.set_active_id("300")
        # connect AFTER set_active_id: the initial value is not a change
        self._interval_combo.connect("changed",
                                     self._on_alarm_interval_changed)
        interval_row.pack_start(self._interval_combo, True, True, 0)
        self.pack_start(interval_row, False, False, 0)

        sound_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                            spacing=12)
        sound_row.pack_start(
            Gtk.Label(label="Toque da notificação", xalign=0),
            False, False, 0)
        self._sound_button = Gtk.FileChooserButton(
            title="Toque da notificação",
            action=Gtk.FileChooserAction.OPEN,
        )
        audio_filter = Gtk.FileFilter()
        audio_filter.set_name("Áudio (.oga, .ogg, .wav)")
        for pattern in ("*.oga", "*.ogg", "*.wav"):
            audio_filter.add_pattern(pattern)
        self._sound_button.add_filter(audio_filter)
        self._sound_button.set_hexpand(True)
        self._sound_button.set_filename(str(config.alarm_sound))
        self._sound_button.connect("file-set", self._on_alarm_sound_set)
        sound_row.pack_start(self._sound_button, True, True, 0)

        preview = Gtk.Button.new_from_icon_name(
            "media-playback-start-symbolic", Gtk.IconSize.BUTTON
        )
        preview.set_tooltip_text("Ouvir o toque")
        preview.connect("clicked", lambda *_: self._sound.play())
        sound_row.pack_start(preview, False, False, 0)
        self.pack_start(sound_row, False, False, 0)

        alarm_hint = Gtk.Label(
            label="Notas marcadas como críticas (⏰) disparam uma "
                  "notificação com som nesse intervalo até serem "
                  "desativadas na tela de notas. Sem críticas ativas, "
                  "nenhum alarme roda."
        )
        alarm_hint.get_style_context().add_class("dim-label")
        alarm_hint.set_line_wrap(True)
        alarm_hint.set_xalign(0)
        self.pack_start(alarm_hint, False, False, 0)

        # ---------------- Section: Espelho .txt ----------------

        self.pack_start(self._section_label("Espelho .txt"), False, False, 8)

        mirror_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                             spacing=12)
        mirror_row.pack_start(
            Gtk.Label(label="Salvar espelho das notas em .txt", xalign=0),
            False, False, 0,
        )
        self._mirror_switch = Gtk.Switch(active=config.mirror_enabled)
        self._mirror_switch.set_valign(Gtk.Align.CENTER)
        self._mirror_switch.connect("notify::active",
                                    self._on_mirror_toggle)
        mirror_row.pack_start(self._mirror_switch, False, False, 0)

        self._mirror_dir_button = Gtk.FileChooserButton(
            title="Diretório do espelho",
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        self._mirror_dir_button.set_hexpand(True)
        self._mirror_dir_button.set_filename(str(config.mirror_dir))
        self._mirror_dir_button.set_sensitive(config.mirror_enabled)
        self._mirror_dir_button.connect("file-set", self._on_mirror_dir)
        mirror_row.pack_start(self._mirror_dir_button, True, True, 0)

        mirror_help = Gtk.Button(label="?")
        mirror_help.set_tooltip_text("O que é o espelho .txt")
        mirror_help.connect("clicked", self._on_mirror_help)
        mirror_row.pack_start(mirror_help, False, False, 0)
        self.pack_start(mirror_row, False, False, 0)

    @staticmethod
    def _section_label(text):
        label = Gtk.Label(xalign=0)
        label.set_markup(f"<b>{text}</b>")
        return label

    # ---------------- Button state ----------------

    def _button_label(self, action_id):
        return (self._manager.get_binding(action_id)
                or self._manager.actions[action_id].default)

    def refresh(self):
        self._cancel_capture()
        for action_id, button in self._buttons.items():
            button.set_label(self._button_label(action_id))
        self._reload_voices()
        self._reload_models()

    # ---------------- Voice picker ----------------

    def _reload_voices(self):
        self._reloading_voices = True  # rebuild is not a user choice
        try:
            self._voice_combo.remove_all()
            names = self._voices.list_voices()
            for name in names:
                self._voice_combo.append(name, name)
            self._voice_combo.set_active_id(self._voices.current_voice())
        finally:
            self._reloading_voices = False
        self._voice_download.set_visible(not names)

    def _on_voice_download(self, button):
        button.set_sensitive(False)
        self._voice_progress.show()
        threading.Thread(target=self._voice_download_worker,
                         daemon=True).start()

    def _voice_download_worker(self):
        try:
            name = self._voices.download_default(
                self._models.downloader,
                on_progress=self._progress_cb(self._voice_progress),
            )
        except (DownloadError, ValueError) as error:
            GLib.idle_add(self._on_download_done, self._voice_progress,
                          self._voice_download, "Erro", str(error))
        else:
            GLib.idle_add(self._on_download_done, self._voice_progress,
                          self._voice_download, "Voz baixada",
                          f"{name} pronta para uso.")

    # ---------------- Whisper model ----------------

    def _reload_models(self):
        self._reloading_models = True  # rebuild is not a user choice
        try:
            self._model_combo.remove_all()
            for size, info in WHISPER_MODELS.items():
                self._model_combo.append(size, info["label"])
            self._model_combo.set_active_id(self._models.current_size())
        finally:
            self._reloading_models = False
        self._update_model_button()

    def _on_model_changed(self, _combo):
        if self._reloading_models:
            return
        self._update_model_button()

    def _update_model_button(self):
        size = self._model_combo.get_active_id()
        if not size:
            self._model_button.set_label("Baixar")
            self._model_button.set_sensitive(False)
            return
        if not self._models.is_installed(size):
            self._model_button.set_label("Baixar")
            self._model_button.set_sensitive(True)
        elif size == self._models.current_size():
            self._model_button.set_label("Em uso ✓")
            self._model_button.set_sensitive(False)
        else:
            self._model_button.set_label("Usar")
            self._model_button.set_sensitive(True)

    def _on_model_action(self, button):
        size = self._model_combo.get_active_id()
        if not size:
            return
        if self._models.is_installed(size):  # "Usar": just switch
            try:
                self._models.use(size)
            except ValueError as error:
                self._notifier.send("Erro", str(error))
                return
            self._notifier.send("Modelo alterado", size)
            self._reload_models()
            return
        button.set_sensitive(False)
        self._model_progress.show()
        threading.Thread(target=self._model_download_worker, args=(size,),
                         daemon=True).start()

    def _model_download_worker(self, size):
        try:
            self._models.download(
                size, on_progress=self._progress_cb(self._model_progress)
            )
        except DownloadError as error:
            GLib.idle_add(self._on_download_done, self._model_progress,
                          self._model_button, "Erro", str(error))
        else:
            GLib.idle_add(self._on_download_done, self._model_progress,
                          self._model_button, "Modelo baixado",
                          f"Modelo {size} baixado e ativado.")

    # ---------------- Live transcription (streaming) ----------------

    def _on_stream_toggle(self, switch, _pspec):
        if self._updating_stream_switch:
            return
        enabled = switch.get_active()
        if enabled:
            size = self._stream_model_combo.get_active_id() or "base"
            if not self._models.is_installed(size):
                # need the small model first — download, then enable
                switch.set_sensitive(False)
                self._stream_progress.show()
                threading.Thread(target=self._stream_download_worker,
                                 args=(size,), daemon=True).start()
                return
        self._apply_stream_enabled(enabled)

    def _apply_stream_enabled(self, enabled):
        update_config_file("stream_enabled", enabled)
        if self._core is not None:
            self._core.stream_enabled = enabled
        self._notifier.send(
            "Transcrição ao vivo",
            "Ativada — o texto aparece numa janela ao gravar."
            if enabled else "Desativada.",
        )

    def _on_stream_model_changed(self, combo):
        size = combo.get_active_id()
        if not size:
            return
        update_config_file("stream_model", size)
        if self._core is not None and getattr(self._core, "_stream", None):
            # the model file changed — point the stream transcriber at it
            self._core._stream._model = self._models.model_path(size)

    def _stream_download_worker(self, size):
        try:
            self._models.download(
                size, on_progress=self._progress_cb(self._stream_progress),
                activate=False,  # must not replace the main model
            )
        except DownloadError as error:
            GLib.idle_add(self._on_stream_download_done, False, str(error))
        else:
            GLib.idle_add(self._on_stream_download_done, True, size)

    def _on_stream_download_done(self, ok, detail):
        self._stream_progress.hide()
        self._stream_progress.set_fraction(0)
        self._stream_switch.set_sensitive(True)
        if ok:
            self._apply_stream_enabled(True)
        else:
            # download failed → leave the switch off without notifying twice
            self._updating_stream_switch = True
            self._stream_switch.set_active(False)
            self._updating_stream_switch = False
            self._notifier.send("Erro", detail)
        return False

    # ---------------- Wake word ----------------

    def _on_wakeword_toggle(self, switch, _pspec):
        enabled = switch.get_active()
        update_config_file("wakeword_enabled", enabled)
        if self._core is not None:
            self._core.set_wakeword_enabled(enabled)
        listening = (enabled and self._core is not None
                     and getattr(self._core, "_wakeword", None) is not None)
        self._notifier.send(
            "Wake word",
            "Ativado — escutando por \"Tomenotas\"." if listening else
            ("Ativado, mas o modelo não está instalado." if enabled
             else "Desativado."),
        )

    def _on_wakeword_sensitivity(self, scale):
        threshold = round(scale.get_value(), 2)
        # persisted; applied to the detector on the next daemon start
        update_config_file("wakeword_threshold", threshold)

    # ---------------- Critical notes (alarm) ----------------

    def _on_alarm_interval_changed(self, combo):
        seconds = int(combo.get_active_id() or 300)
        self._alarm.set_interval(seconds)
        update_config_file("alarm_interval", seconds)
        self._notifier.send("Notas críticas",
                            f"Notificações a cada {combo.get_active_text()}.")

    def _on_alarm_sound_set(self, button):
        path = button.get_filename()
        if not path:
            return
        self._sound.set_sound(path)
        update_config_file("alarm_sound", path)
        self._sound.play()  # immediate feedback with the chosen ringtone

    # ---------------- .txt mirror ----------------

    def _on_mirror_toggle(self, switch, _pspec):
        enabled = switch.get_active()
        self._mirror_dir_button.set_sensitive(enabled)
        self._store.set_mirror(enabled, self._mirror_dir_button.get_filename())
        update_config_file("mirror_enabled", enabled)
        self._notifier.send(
            "Espelho .txt",
            "Espelho ativado: novas notas geram arquivos .txt."
            if enabled else "Espelho desativado.",
        )

    def _on_mirror_dir(self, button):
        path = button.get_filename()
        if not path:
            return
        self._store.set_mirror(self._mirror_switch.get_active(), path)
        update_config_file("mirror_dir", path)
        self._notifier.send("Espelho .txt", f"Diretório: {path}")

    def _on_mirror_help(self, _button):
        dialog = Gtk.MessageDialog(
            transient_for=self._window,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="O que é o espelho .txt",
        )
        dialog.format_secondary_text(
            "Com o espelho ativado, cada nota gravada ou criada passa a "
            "gerar também um arquivo .txt no diretório escolhido — um "
            "export em texto puro, legível sem o Tomenotas.\n\n"
            "Importante: o espelho apenas CRIA os arquivos. A edição de "
            "uma nota é feita pela interface do Tomenotas — alterar o "
            ".txt por fora não muda a nota.\n\n"
            "Arquivos .txt novos colocados no diretório são importados "
            "como notas na próxima abertura do app, e apagar uma nota "
            "apaga também o seu .txt."
        )
        dialog.run()
        dialog.destroy()

    # ---------------- Download plumbing ----------------

    def _progress_cb(self, bar):
        """Callback for the download thread: throttles to whole percent
        steps and posts the update to the main thread."""
        last = [-1]

        def on_progress(done, total):
            if not total:
                return
            pct = min(100, int(done * 100 / total))
            if pct != last[0]:
                last[0] = pct
                GLib.idle_add(self._set_progress, bar, pct)

        return on_progress

    def _set_progress(self, bar, pct):
        bar.set_fraction(pct / 100)
        bar.set_text(f"{pct}%")
        return False  # idle_add: do not repeat

    def _on_download_done(self, bar, button, title, message):
        bar.hide()
        bar.set_fraction(0)
        button.set_sensitive(True)
        self._notifier.send(title, message)
        self.refresh()
        return False

    def _on_voice_help(self, _button):
        dialog = Gtk.MessageDialog(
            transient_for=self._window,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Como baixar mais vozes",
        )
        # markup: links are clickable (GtkLabel opens them in the browser)
        voices_dir = GLib.markup_escape_text(str(self._voices.voices_dir))
        dialog.format_secondary_markup(
            "1. Abra o catálogo de vozes do Piper:\n"
            '   <a href="https://huggingface.co/rhasspy/piper-voices">'
            "huggingface.co/rhasspy/piper-voices</a>\n"
            "   (amostras de áudio em "
            '<a href="https://rhasspy.github.io/piper-samples/">'
            "rhasspy.github.io/piper-samples</a>)\n\n"
            "2. Baixe os DOIS arquivos da voz desejada:\n"
            "   &lt;voz&gt;.onnx e &lt;voz&gt;.onnx.json\n"
            "   (ex.: pt_BR-edresson-low.onnx e pt_BR-edresson-low.onnx.json)\n\n"
            "3. Coloque os dois arquivos em:\n"
            f"   {voices_dir}\n\n"
            "4. Volte a esta tela e escolha a voz nova no seletor —\n"
            "   a lista é atualizada ao reabrir a tela de Configurações."
        )
        dialog.run()
        dialog.destroy()

    def _on_voice_changed(self, combo):
        if self._reloading_voices:
            return
        name = combo.get_active_id()
        if not name or name == self._voices.current_voice():
            return
        try:
            self._voices.set_voice(name)
        except ValueError as error:
            self._notifier.send("Erro", str(error))
            self._reload_voices()  # back to the voice that actually works
            return
        self._notifier.send("Voz alterada", name)

    # ---------------- Key capture ----------------

    def _on_assign(self, button, action_id):
        self._cancel_capture()
        self._capturing = (action_id, button)
        button.set_label("Pressione o novo atalho...")

    def handle_key(self, event) -> bool:
        """Called by the main window; True = event consumed."""
        if self._capturing is None:
            return False
        action_id, button = self._capturing

        keyval = Gdk.keyval_to_lower(event.keyval)
        if keyval == Gdk.KEY_Escape:
            self._cancel_capture()
            return True

        mods = event.state & Gtk.accelerator_get_default_mod_mask()
        # A modifier key alone (Super, Ctrl...): wait for the rest
        if not Gtk.accelerator_valid(keyval, mods):
            return True

        binding = Gtk.accelerator_name(keyval, mods)
        conflicts = self._manager.list_conflicts(binding,
                                                 ignore_action=action_id)
        if conflicts and not self._confirm_conflict(binding, conflicts):
            return True  # keep capturing: the user tries another combination

        self._manager.set_binding(action_id, binding)
        self._capturing = None
        button.set_label(binding)
        title = self._manager.actions[action_id].title
        self._notifier.send("Atalho atualizado", f"{title}: {binding}")
        return True

    def _confirm_conflict(self, binding, conflicts):
        dialog = Gtk.MessageDialog(
            transient_for=self._window,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"O atalho {binding} já está em uso.",
        )
        dialog.format_secondary_text(
            "Em uso por: " + ", ".join(conflicts) + ".\nUsar mesmo assim?"
        )
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES

    def _cancel_capture(self):
        if self._capturing is not None:
            action_id, button = self._capturing
            self._capturing = None
            button.set_label(self._button_label(action_id))

    # ---------------- Portal mode: system shortcuts ----------------

    def _on_open_system_shortcuts(self, _button):
        """Opens the desktop's global-shortcuts settings (portal mode —
        the app cannot set keys itself). Best-effort across KDE versions;
        if nothing launches, the user still has the "?" instructions."""
        import shutil
        import subprocess

        candidates = [
            ["systemsettings", "kcm_keys"],       # Plasma 6
            ["systemsettings5", "kcm_keys"],      # Plasma 5
            ["kcmshell6", "kcm_keys"],
            ["kcmshell5", "keys"],
            ["systemsettings"],                   # fallback: just open it
        ]
        for cmd in candidates:
            if shutil.which(cmd[0]):
                try:
                    subprocess.Popen(cmd)
                    return
                except OSError:
                    continue
        self._notifier.send(
            "Atalhos",
            "Abra as Configurações do sistema → Atalhos para definir as "
            "teclas do Tomenotas.",
        )

    def _on_shortcuts_help(self, _button):
        dialog = Gtk.MessageDialog(
            transient_for=self._window,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Como configurar os atalhos",
        )
        dialog.format_secondary_text(
            "Neste desktop (ex.: KDE), por segurança, só o sistema pode "
            "definir atalhos globais — o Tomenotas apenas os registra e "
            "sugere as teclas.\n\n"
            "1. Clique em \"Configurar atalhos no sistema\" (ou abra as "
            "Configurações do Sistema → Atalhos).\n"
            "2. Encontre as ações do Tomenotas (Gravar, Listar, Ler, "
            "Nota crítica, Ler crítica, Reunião).\n"
            "3. Clique na ação e defina a combinação de teclas desejada.\n\n"
            "Os atalhos só funcionam enquanto o Tomenotas estiver aberto "
            "(fechar pela bandeja os desativa)."
        )
        dialog.run()
        dialog.destroy()
