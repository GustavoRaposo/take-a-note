"""Página de Configurações (atalhos de teclado), embutida na sidebar da
janela principal.

Camada de cola: captura de teclas com GTK e delegação para o
ShortcutManager (testado), que grava nos gsettings com efeito imediato.
Fora da métrica de cobertura — não deixe lógica crescer aqui.

Nota (Wayland/GNOME): a combinação atualmente registrada como atalho
global é capturada pelo shell antes de chegar à janela — para trocá-la,
pressione uma combinação diferente.
"""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402


class SettingsPage(Gtk.Box):
    """A janela principal delega key-press-event para handle_key() quando
    esta página está visível."""

    def __init__(self, manager, notifier, janela):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                         margin=16)
        self._manager = manager
        self._notifier = notifier
        self._janela = janela  # pai dos diálogos de conflito
        self._capturando = None  # (acao_id, botao) durante a captura

        grade = Gtk.Grid(row_spacing=8, column_spacing=12)
        self.pack_start(grade, False, False, 0)

        self._botoes = {}
        for i, acao in enumerate(self._manager.acoes.values()):
            rotulo = Gtk.Label(label=acao.titulo, xalign=0)
            botao = Gtk.Button(label=self._rotulo(acao.id))
            botao.set_hexpand(True)
            botao.connect("clicked", self._on_definir, acao.id)
            grade.attach(rotulo, 0, i, 1, 1)
            grade.attach(botao, 1, i, 1, 1)
            self._botoes[acao.id] = botao

        dica = Gtk.Label(label="Clique num atalho e pressione a nova "
                               "combinação de teclas (Esc cancela).")
        dica.get_style_context().add_class("dim-label")
        dica.set_line_wrap(True)
        self.pack_start(dica, False, False, 0)

    # ---------------- Estado dos botões ----------------

    def _rotulo(self, acao_id):
        return (self._manager.get_binding(acao_id)
                or self._manager.acoes[acao_id].padrao)

    def refresh(self):
        self._cancela_captura()
        for acao_id, botao in self._botoes.items():
            botao.set_label(self._rotulo(acao_id))

    # ---------------- Captura de tecla ----------------

    def _on_definir(self, botao, acao_id):
        self._cancela_captura()
        self._capturando = (acao_id, botao)
        botao.set_label("Pressione o novo atalho...")

    def handle_key(self, event) -> bool:
        """Chamado pela janela principal; True = evento consumido."""
        if self._capturando is None:
            return False
        acao_id, botao = self._capturando

        keyval = Gdk.keyval_to_lower(event.keyval)
        if keyval == Gdk.KEY_Escape:
            self._cancela_captura()
            return True

        mods = event.state & Gtk.accelerator_get_default_mod_mask()
        # Tecla modificadora sozinha (Super, Ctrl...): espera o resto
        if not Gtk.accelerator_valid(keyval, mods):
            return True

        binding = Gtk.accelerator_name(keyval, mods)
        conflitos = self._manager.list_conflicts(binding, ignorar_acao=acao_id)
        if conflitos and not self._confirma_conflito(binding, conflitos):
            return True  # segue capturando: o usuário tenta outra combinação

        self._manager.set_binding(acao_id, binding)
        self._capturando = None
        botao.set_label(binding)
        titulo = self._manager.acoes[acao_id].titulo
        self._notifier.send("Atalho atualizado", f"{titulo}: {binding}")
        return True

    def _confirma_conflito(self, binding, conflitos):
        dialogo = Gtk.MessageDialog(
            transient_for=self._janela,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"O atalho {binding} já está em uso.",
        )
        dialogo.format_secondary_text(
            "Em uso por: " + ", ".join(conflitos) + ".\nUsar mesmo assim?"
        )
        resposta = dialogo.run()
        dialogo.destroy()
        return resposta == Gtk.ResponseType.YES

    def _cancela_captura(self):
        if self._capturando is not None:
            acao_id, botao = self._capturando
            self._capturando = None
            botao.set_label(self._rotulo(acao_id))
