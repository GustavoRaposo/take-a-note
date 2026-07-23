"""Janela principal do Tomenotas, com sidebar de seções:

- Notas: lista com busca FTS, dropdown de tags, favoritos, período, tocar,
  favoritar, taguear e apagar.
- Tags: CRUD de tags (criar, listar com contagem, renomear, apagar).
- Configurações: atalhos de teclado (SettingsPage).

Camada de cola como daemon.py: só widgets e delegação para
SqliteNoteStore / Player / ShortcutManager (testados). Fica fora da
métrica de cobertura (pyproject.toml) e é validada manualmente. Não deixe
lógica crescer aqui — ponha nos módulos do núcleo.
"""

import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from ..domain.errors import PlayerError  # noqa: E402
from ..domain.note import preview  # noqa: E402
from ..domain.periodo import periodo_desde  # noqa: E402
from .settings_page import SettingsPage  # noqa: E402

PERIODOS = [
    ("", "Qualquer data"),
    ("hoje", "Hoje"),
    ("7dias", "Últimos 7 dias"),
    ("30dias", "Últimos 30 dias"),
]


class NotesWindow(Gtk.Window):
    def __init__(self, store, player, notifier, shortcuts):
        super().__init__(title="Tomenotas")
        self._store = store
        self._player = player
        self._notifier = notifier
        self._playing_button = None  # botão da nota tocando agora
        self._tag_ativa = ""  # tag selecionada no dropdown ("" = todas)
        self._so_favoritos = False
        self._periodo = ""
        self._recarregando_tags = False  # evita "changed" durante rebuild

        self.set_default_size(840, 560)

        header = Gtk.HeaderBar(title="Tomenotas", subtitle="Suas notas de voz")
        header.set_show_close_button(True)
        self.set_titlebar(header)

        raiz = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(raiz)

        self._stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE
        )
        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self._stack)
        raiz.pack_start(sidebar, False, False, 0)
        raiz.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.VERTICAL),
            False, False, 0,
        )
        raiz.pack_start(self._stack, True, True, 0)

        self._stack.add_titled(self._monta_pagina_notas(), "notas", "Notas")
        self._stack.add_titled(self._monta_pagina_tags(), "tags", "Tags")
        self._config = SettingsPage(shortcuts, notifier, self)
        self._stack.add_titled(self._config, "config", "Configurações")
        self._stack.connect("notify::visible-child", self._on_troca_pagina)

        # A captura de atalho da página de Configurações precisa dos
        # eventos de teclado da janela
        self.connect("key-press-event", self._on_tecla)
        # Fechar a janela só esconde — o daemon continua na bandeja
        self.connect("delete-event", self._on_fechar)

    # ---------------- Entrada pública (daemon) ----------------

    def mostrar(self, pagina=None):
        self.refresh()
        self.show_all()
        if pagina:
            self._stack.set_visible_child_name(pagina)
        self.present()

    def refresh(self):
        self._reconstroi_dropdown_tags()
        self._recarrega_lista()
        self._recarrega_tags()
        self._config.refresh()

    def _on_troca_pagina(self, *_args):
        nome = self._stack.get_visible_child_name()
        if nome == "notas":
            self._reconstroi_dropdown_tags()
            self._recarrega_lista()
        elif nome == "tags":
            self._recarrega_tags()
        elif nome == "config":
            self._config.refresh()

    def _on_tecla(self, _widget, event):
        if self._stack.get_visible_child() is self._config:
            return self._config.handle_key(event)
        return False

    # ================= Página: Notas =================

    def _monta_pagina_notas(self):
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                        margin=12)

        self._busca = Gtk.SearchEntry(
            placeholder_text="Buscar nas notas (busca por prefixo)..."
        )
        self._busca.connect("search-changed",
                            lambda *_: self._recarrega_lista())
        caixa.pack_start(self._busca, False, False, 0)

        # ---- linha de filtros: favoritos + tag (dropdown) + período ----
        filtros = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        caixa.pack_start(filtros, False, False, 0)

        self._botao_favoritos = Gtk.ToggleButton(label="★ Favoritos")
        self._botao_favoritos.set_tooltip_text("Mostrar só as favoritas")
        self._botao_favoritos.connect("toggled", self._on_favoritos_toggle)
        filtros.pack_start(self._botao_favoritos, False, False, 0)

        self._combo_tag = Gtk.ComboBoxText()
        self._combo_tag.set_tooltip_text("Filtrar por tag")
        self._combo_tag.connect("changed", self._on_tag_mudou)
        filtros.pack_start(self._combo_tag, False, False, 0)

        self._combo_periodo = Gtk.ComboBoxText()
        for id_periodo, rotulo in PERIODOS:
            self._combo_periodo.append(id_periodo, rotulo)
        self._combo_periodo.set_active_id("")
        self._combo_periodo.connect("changed", self._on_periodo_mudou)
        filtros.pack_start(self._combo_periodo, False, False, 0)

        rolagem = Gtk.ScrolledWindow()
        rolagem.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        caixa.pack_start(rolagem, True, True, 0)

        self._lista = Gtk.ListBox()
        self._lista.set_selection_mode(Gtk.SelectionMode.NONE)
        rolagem.add(self._lista)

        return caixa

    def _reconstroi_dropdown_tags(self):
        """Repovoa o dropdown com as tags do banco, preservando a seleção
        (volta para "Todas" se a tag selecionada foi apagada/renomeada)."""
        nomes = self._store.tags()
        if self._tag_ativa not in nomes:
            self._tag_ativa = ""
        self._recarregando_tags = True  # rebuild não é escolha do usuário
        try:
            self._combo_tag.remove_all()
            self._combo_tag.append("", "Todas as tags")
            for nome in nomes:
                self._combo_tag.append(nome, f"🏷 {nome}")
            self._combo_tag.set_active_id(self._tag_ativa)
        finally:
            self._recarregando_tags = False

    def _recarrega_lista(self):
        self._parar_reproducao()
        for filho in self._lista.get_children():
            self._lista.remove(filho)

        notas = self._store.search(
            texto=self._busca.get_text(),
            tags=[self._tag_ativa] if self._tag_ativa else [],
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
        return bool(self._busca.get_text().strip() or self._tag_ativa
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

    def _on_tag_mudou(self, combo):
        if self._recarregando_tags:
            return
        self._tag_ativa = combo.get_active_id() or ""
        self._recarrega_lista()

    def _on_favoritos_toggle(self, botao):
        self._so_favoritos = botao.get_active()
        self._recarrega_lista()

    def _on_periodo_mudou(self, combo):
        self._periodo = combo.get_active_id() or ""
        self._recarrega_lista()

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
        previa = Gtk.Label(label=preview(nota.text), xalign=0)
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
        adicionar.connect("clicked", self._on_nova_tag_da_nota, nota, entrada)
        entrada.connect(
            "activate",
            lambda e: self._on_nova_tag_da_nota(adicionar, nota, e),
        )
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
        GLib.idle_add(self.refresh)  # atualiza o dropdown e o 🏷 da linha

    def _on_nova_tag_da_nota(self, _botao, nota, entrada):
        nome = entrada.get_text().strip()
        if not nome:
            return
        self._store.add_tag(nota.id, nome)
        entrada.set_text("")
        GLib.idle_add(self.refresh)

    # ================= Página: Tags (CRUD) =================

    def _monta_pagina_tags(self):
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                        margin=12)

        topo = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._entrada_tag = Gtk.Entry(placeholder_text="nova tag")
        botao_criar = Gtk.Button(label="Criar")
        botao_criar.connect("clicked", self._on_criar_tag)
        self._entrada_tag.connect("activate",
                                  lambda *_: self._on_criar_tag(botao_criar))
        topo.pack_start(self._entrada_tag, True, True, 0)
        topo.pack_start(botao_criar, False, False, 0)
        caixa.pack_start(topo, False, False, 0)

        rolagem = Gtk.ScrolledWindow()
        rolagem.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        caixa.pack_start(rolagem, True, True, 0)

        self._lista_tags = Gtk.ListBox()
        self._lista_tags.set_selection_mode(Gtk.SelectionMode.NONE)
        rolagem.add(self._lista_tags)

        return caixa

    def _recarrega_tags(self):
        for filho in self._lista_tags.get_children():
            self._lista_tags.remove(filho)

        contagens = self._store.tags_com_contagem()
        if not contagens:
            linha = Gtk.ListBoxRow(selectable=False)
            rotulo = Gtk.Label(
                label="Nenhuma tag ainda.\nCrie uma acima ou pelo 🏷 de uma nota."
            )
            rotulo.set_justify(Gtk.Justification.CENTER)
            linha.add(rotulo)
            self._lista_tags.add(linha)
        for nome, quantidade in contagens:
            self._lista_tags.add(self._monta_linha_tag(nome, quantidade))
        self._lista_tags.show_all()

    def _monta_linha_tag(self, nome, quantidade):
        linha = Gtk.ListBoxRow(selectable=False)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                       margin=6)
        linha.add(hbox)

        rotulo = Gtk.Label(label=f"🏷 {nome}", xalign=0)
        contagem = Gtk.Label(label=f"{quantidade} nota(s)", xalign=0)
        contagem.get_style_context().add_class("dim-label")
        hbox.pack_start(rotulo, True, True, 0)
        hbox.pack_start(contagem, False, False, 6)

        renomear = Gtk.Button.new_from_icon_name(
            "document-edit-symbolic", Gtk.IconSize.BUTTON
        )
        renomear.set_tooltip_text("Renomear esta tag")
        renomear.connect("clicked", self._on_renomear_tag, nome)
        hbox.pack_start(renomear, False, False, 0)

        apagar = Gtk.Button.new_from_icon_name(
            "user-trash-symbolic", Gtk.IconSize.BUTTON
        )
        apagar.set_tooltip_text("Apagar esta tag")
        apagar.connect("clicked", self._on_apagar_tag, nome, quantidade)
        hbox.pack_start(apagar, False, False, 0)

        return linha

    def _on_criar_tag(self, _botao):
        nome = self._entrada_tag.get_text().strip()
        if not nome:
            return
        try:
            criada = self._store.create_tag(nome)
        except ValueError as erro:
            self._notifier.send("Erro", str(erro))
            return
        if not criada:
            self._notifier.send("Tags", f"A tag \"{nome}\" já existe.")
        self._entrada_tag.set_text("")
        self.refresh()

    def _on_renomear_tag(self, _botao, nome):
        dialogo = Gtk.Dialog(title=f"Renomear tag \"{nome}\"",
                             transient_for=self, modal=True)
        dialogo.add_buttons("Cancelar", Gtk.ResponseType.CANCEL,
                            "Renomear", Gtk.ResponseType.OK)
        entrada = Gtk.Entry(text=nome, activates_default=True, margin=8)
        dialogo.get_content_area().add(entrada)
        dialogo.set_default_response(Gtk.ResponseType.OK)
        dialogo.show_all()
        resposta = dialogo.run()
        novo = entrada.get_text().strip()
        dialogo.destroy()
        if resposta != Gtk.ResponseType.OK or not novo or novo == nome:
            return
        # Renomear para uma tag que já existe faz merge — avisa antes
        existentes = {t.lower() for t in self._store.tags()}
        if novo.lower() in existentes and novo.lower() != nome.lower():
            if not self._confirma(
                f"Já existe a tag \"{novo}\".",
                f"As notas de \"{nome}\" serão unidas a \"{novo}\". Continuar?",
            ):
                return
        try:
            self._store.rename_tag(nome, novo)
        except ValueError as erro:
            self._notifier.send("Erro", str(erro))
            return
        self.refresh()

    def _on_apagar_tag(self, _botao, nome, quantidade):
        if not self._confirma(
            f"Apagar a tag \"{nome}\"?",
            f"As {quantidade} nota(s) associadas não serão apagadas — "
            "só deixam de ter essa tag.",
        ):
            return
        self._store.delete_tag(nome)
        self.refresh()

    def _confirma(self, texto, detalhe):
        dialogo = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=texto,
        )
        dialogo.format_secondary_text(detalhe)
        resposta = dialogo.run()
        dialogo.destroy()
        return resposta == Gtk.ResponseType.YES

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

    # ---------------- Apagar nota ----------------

    def _on_apagar(self, _botao, nota):
        if self._confirma(f"Apagar a nota {nota.title}?",
                          preview(nota.text)):
            self._store.delete(nota)
            self.refresh()

    # ---------------- Fechar ----------------

    def _on_fechar(self, *_args):
        self._parar_reproducao()
        self.hide()
        return True  # não destrói: reabrir pela bandeja é instantâneo
