"""Janela GTK de notas: listar, buscar (FTS), filtrar por tags/favoritos/
período, tocar, favoritar, taguear e apagar.

Camada de cola como daemon.py: só widgets e delegação para SqliteNoteStore /
Player (testados). Fica fora da métrica de cobertura (pyproject.toml) e é
validada manualmente. Não deixe lógica crescer aqui — ponha nos módulos
do núcleo.
"""

import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from .notes import NoteStore  # noqa: E402
from .notes_db import periodo_desde  # noqa: E402
from .player import PlayerError  # noqa: E402

PERIODOS = [
    ("", "Qualquer data"),
    ("hoje", "Hoje"),
    ("7dias", "Últimos 7 dias"),
    ("30dias", "Últimos 30 dias"),
]


class NotesWindow(Gtk.Window):
    def __init__(self, store, player, notifier):
        super().__init__(title="Tomenotas")
        self._store = store
        self._player = player
        self._notifier = notifier
        self._playing_button = None  # botão da nota tocando agora
        self._tags_ativas = set()
        self._so_favoritos = False
        self._periodo = ""

        self.set_default_size(680, 560)

        header = Gtk.HeaderBar(title="Tomenotas", subtitle="Suas notas de voz")
        header.set_show_close_button(True)
        self.set_titlebar(header)

        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                        margin=12)
        self.add(caixa)

        self._busca = Gtk.SearchEntry(
            placeholder_text="Buscar nas notas (busca por prefixo)..."
        )
        self._busca.connect("search-changed",
                            lambda *_: self._recarrega_lista())
        caixa.pack_start(self._busca, False, False, 0)

        # ---- linha de filtros: favoritos + período ----
        filtros = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        caixa.pack_start(filtros, False, False, 0)

        self._botao_favoritos = Gtk.ToggleButton(label="★ Favoritos")
        self._botao_favoritos.set_tooltip_text("Mostrar só as favoritas")
        self._botao_favoritos.connect("toggled", self._on_favoritos_toggle)
        filtros.pack_start(self._botao_favoritos, False, False, 0)

        self._combo_periodo = Gtk.ComboBoxText()
        for id_periodo, rotulo in PERIODOS:
            self._combo_periodo.append(id_periodo, rotulo)
        self._combo_periodo.set_active_id("")
        self._combo_periodo.connect("changed", self._on_periodo_mudou)
        filtros.pack_start(self._combo_periodo, False, False, 0)

        # ---- chips de tags (interseção quando várias ativas) ----
        self._chips = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,
                                  max_children_per_line=8)
        caixa.pack_start(self._chips, False, False, 0)

        rolagem = Gtk.ScrolledWindow()
        rolagem.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        caixa.pack_start(rolagem, True, True, 0)

        self._lista = Gtk.ListBox()
        self._lista.set_selection_mode(Gtk.SelectionMode.NONE)
        rolagem.add(self._lista)

        # Fechar a janela só esconde — o daemon continua na bandeja
        self.connect("delete-event", self._on_fechar)

    # ---------------- Recarga (filtros → consulta ao banco) ----------------

    def refresh(self):
        """Reconstrói chips e lista (usado ao abrir e após mudanças)."""
        self._reconstroi_chips()
        self._recarrega_lista()

    def _reconstroi_chips(self):
        for filho in self._chips.get_children():
            self._chips.remove(filho)
        nomes = self._store.tags()
        self._tags_ativas &= set(nomes)  # descarta tags que sumiram
        for nome in nomes:
            chip = Gtk.ToggleButton(label=nome)
            chip.set_active(nome in self._tags_ativas)  # antes do connect
            chip.connect("toggled", self._on_chip_toggle, nome)
            self._chips.add(chip)
        self._chips.set_visible(bool(nomes))
        self._chips.show_all() if nomes else self._chips.hide()

    def _recarrega_lista(self):
        self._parar_reproducao()
        for filho in self._lista.get_children():
            self._lista.remove(filho)

        notas = self._store.search(
            texto=self._busca.get_text(),
            tags=sorted(self._tags_ativas),
            favoritos=self._so_favoritos,
            desde=periodo_desde(self._periodo),
        )
        if not notas:
            linha = Gtk.ListBoxRow(selectable=False)
            linha.add(self._rotulo_vazio())
            self._lista.add(linha)
        for nota in notas:
            self._lista.add(self._monta_linha(nota))
        self._lista.show_all()

    def _tem_filtros(self):
        return bool(self._busca.get_text().strip() or self._tags_ativas
                    or self._so_favoritos or self._periodo)

    def _rotulo_vazio(self):
        if self._tem_filtros():
            texto = "Nenhuma nota encontrada com esses filtros."
        else:
            texto = ("Nenhuma nota ainda.\n"
                     "Aperte Super+R para gravar a primeira.")
        rotulo = Gtk.Label(label=texto)
        rotulo.set_justify(Gtk.Justification.CENTER)
        return rotulo

    def _on_chip_toggle(self, chip, nome):
        if chip.get_active():
            self._tags_ativas.add(nome)
        else:
            self._tags_ativas.discard(nome)
        self._recarrega_lista()

    def _on_favoritos_toggle(self, botao):
        self._so_favoritos = botao.get_active()
        self._recarrega_lista()

    def _on_periodo_mudou(self, combo):
        self._periodo = combo.get_active_id() or ""
        self._recarrega_lista()

    # ---------------- Linhas ----------------

    def _monta_linha(self, nota):
        linha = Gtk.ListBoxRow(selectable=False)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                       margin=6)
        linha.add(hbox)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        cabecalho = nota.title
        if nota.tags:
            cabecalho += "   🏷 " + ", ".join(nota.tags)
        titulo = Gtk.Label(label=cabecalho, xalign=0)
        titulo.get_style_context().add_class("dim-label")
        previa = Gtk.Label(label=NoteStore.preview(nota.text), xalign=0)
        previa.set_ellipsize(Pango.EllipsizeMode.END)
        vbox.pack_start(titulo, False, False, 0)
        vbox.pack_start(previa, False, False, 0)
        hbox.pack_start(vbox, True, True, 0)

        estrela = Gtk.ToggleButton()
        estrela.set_active(nota.favorite)  # antes do connect
        self._pinta_estrela(estrela, nota.favorite)
        estrela.connect("toggled", self._on_favoritar, nota)
        hbox.pack_start(estrela, False, False, 0)

        botao_tags = Gtk.MenuButton(label="🏷")
        botao_tags.set_tooltip_text("Tags desta nota")
        botao_tags.set_popover(self._monta_popover_tags(nota, botao_tags))
        hbox.pack_start(botao_tags, False, False, 0)

        botao_tocar = Gtk.Button.new_from_icon_name(
            "media-playback-start-symbolic", Gtk.IconSize.BUTTON
        )
        botao_tocar.set_tooltip_text("Tocar esta nota")
        botao_tocar.connect("clicked", self._on_tocar, nota)
        hbox.pack_start(botao_tocar, False, False, 0)

        botao_apagar = Gtk.Button.new_from_icon_name(
            "user-trash-symbolic", Gtk.IconSize.BUTTON
        )
        botao_apagar.set_tooltip_text("Apagar esta nota")
        botao_apagar.connect("clicked", self._on_apagar, nota)
        hbox.pack_start(botao_apagar, False, False, 0)

        return linha

    # ---------------- Favoritos ----------------

    def _pinta_estrela(self, botao, favorita):
        nome = "starred-symbolic" if favorita else "non-starred-symbolic"
        botao.set_image(Gtk.Image.new_from_icon_name(nome,
                                                     Gtk.IconSize.BUTTON))
        botao.set_tooltip_text(
            "Desmarcar favorita" if favorita else "Marcar como favorita"
        )

    def _on_favoritar(self, botao, nota):
        ativo = botao.get_active()
        self._store.set_favorite(nota.id, ativo)
        self._pinta_estrela(botao, ativo)
        if self._so_favoritos:
            # a nota pode ter saído do filtro atual — recarrega fora do
            # handler (o botão em uso será destruído na recarga)
            GLib.idle_add(self._recarrega_lista)

    # ---------------- Tags por nota (popover) ----------------

    def _monta_popover_tags(self, nota, botao):
        popover = Gtk.Popover()
        popover.set_relative_to(botao)
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                        margin=8)
        popover.add(caixa)

        for nome in self._store.tags():
            marca = Gtk.CheckButton(label=nome)
            marca.set_active(nome in nota.tags)  # antes do connect
            marca.connect("toggled", self._on_tag_da_nota, nota, nome)
            caixa.pack_start(marca, False, False, 0)

        nova = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        entrada = Gtk.Entry(placeholder_text="nova tag")
        adicionar = Gtk.Button(label="Adicionar")
        adicionar.connect("clicked", self._on_nova_tag, nota, entrada)
        entrada.connect("activate",
                        lambda e: self._on_nova_tag(adicionar, nota, e))
        nova.pack_start(entrada, True, True, 0)
        nova.pack_start(adicionar, False, False, 0)
        caixa.pack_start(nova, False, False, 4)

        caixa.show_all()
        return popover

    def _on_tag_da_nota(self, marca, nota, nome):
        if marca.get_active():
            self._store.add_tag(nota.id, nome)
        else:
            self._store.remove_tag(nota.id, nome)
        GLib.idle_add(self.refresh)  # atualiza chips e o 🏷 da linha

    def _on_nova_tag(self, _botao, nota, entrada):
        nome = entrada.get_text().strip()
        if not nome:
            return
        self._store.add_tag(nota.id, nome)
        entrada.set_text("")
        GLib.idle_add(self.refresh)

    # ---------------- Tocar / parar ----------------

    def _on_tocar(self, botao, nota):
        if botao is self._playing_button:
            self._parar_reproducao()
            return
        self._parar_reproducao()
        botao.set_sensitive(False)  # até a síntese terminar
        # A síntese do Piper bloqueia — roda numa thread, como a transcrição
        threading.Thread(
            target=self._tocar_worker, args=(botao, nota), daemon=True
        ).start()

    def _tocar_worker(self, botao, nota):
        try:
            self._player.play(nota.text)
        except PlayerError as erro:
            GLib.idle_add(self._on_erro_reproducao, botao, str(erro))
        else:
            GLib.idle_add(self._on_reproducao_iniciada, botao)

    def _on_erro_reproducao(self, botao, mensagem):
        botao.set_sensitive(True)
        self._notifier.send("Erro", mensagem)
        return False

    def _on_reproducao_iniciada(self, botao):
        botao.set_sensitive(True)
        self._marca_tocando(botao)
        # indicador de "tocando agora": volta a play quando o áudio acabar
        GLib.timeout_add(300, self._verifica_fim)
        return False

    def _verifica_fim(self):
        if self._player.is_playing:
            return True  # continua verificando
        self._desmarca_tocando()
        return False

    def _marca_tocando(self, botao):
        self._playing_button = botao
        imagem = Gtk.Image.new_from_icon_name(
            "media-playback-pause-symbolic", Gtk.IconSize.BUTTON
        )
        botao.set_image(imagem)
        botao.set_tooltip_text("Parar a reprodução")

    def _desmarca_tocando(self):
        if self._playing_button is not None:
            imagem = Gtk.Image.new_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.BUTTON
            )
            self._playing_button.set_image(imagem)
            self._playing_button.set_tooltip_text("Tocar esta nota")
            self._playing_button = None

    def _parar_reproducao(self):
        self._player.stop()
        self._desmarca_tocando()

    # ---------------- Apagar ----------------

    def _on_apagar(self, _botao, nota):
        dialogo = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Apagar a nota {nota.title}?",
        )
        dialogo.format_secondary_text(NoteStore.preview(nota.text))
        resposta = dialogo.run()
        dialogo.destroy()
        if resposta == Gtk.ResponseType.YES:
            self._store.delete(nota)
            self.refresh()

    # ---------------- Fechar ----------------

    def _on_fechar(self, *_args):
        self._parar_reproducao()
        self.hide()
        return True  # não destrói: reabrir pela bandeja é instantâneo
