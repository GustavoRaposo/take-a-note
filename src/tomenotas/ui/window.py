"""Tomenotas main window, with a sidebar of sections:

- Notas: list with FTS search, tag dropdown, favorites, period, play,
  favorite, tag and delete.
- Tags: tag CRUD (create, list with counts, rename, delete).
- Configurações: keyboard shortcuts and Piper voice (SettingsPage).

Glue layer like daemon.py: only widgets and delegation to the (tested)
SqliteNoteStore / Player / ShortcutManager. Stays outside the coverage
metric (pyproject.toml) and is validated manually. Do not let logic grow
here — put it in the core modules.
"""

import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from ..domain.errors import PlayerError  # noqa: E402
from ..domain.note import preview  # noqa: E402
from ..domain.period import period_since  # noqa: E402
from .settings_page import SettingsPage  # noqa: E402

PERIODS = [
    ("", "Qualquer data"),
    ("today", "Hoje"),
    ("7days", "Últimos 7 dias"),
    ("30days", "Últimos 30 dias"),
]


class NotesWindow(Gtk.Window):
    def __init__(self, store, player, notifier, shortcuts, voices, models,
                 config, alarm, sound, backend="gsettings"):
        super().__init__(title="Tomenotas")
        self._store = store
        self._player = player
        self._notifier = notifier
        self._alarm = alarm
        self._playing_button = None  # button of the note playing now
        self._active_tag = ""  # tag selected in the dropdown ("" = all)
        self._favorites_only = False
        self._period = ""
        self._reloading_tags = False  # suppress "changed" during rebuild

        self.set_default_size(840, 560)

        # window icon → shown in the taskbar/dock (X11) and as the title
        # icon; on Wayland the app_id (set via prgname) does the matching
        icon_file = config.icons_dir / "tomenotas-idle.svg"
        if icon_file.exists():
            self.set_icon_from_file(str(icon_file))

        header = Gtk.HeaderBar(title="Tomenotas", subtitle="Suas notas de voz")
        header.set_show_close_button(True)
        self.set_titlebar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.add(root)

        self._stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE
        )
        sidebar = Gtk.StackSidebar()
        sidebar.set_stack(self._stack)
        root.pack_start(sidebar, False, False, 0)
        root.pack_start(
            Gtk.Separator(orientation=Gtk.Orientation.VERTICAL),
            False, False, 0,
        )
        root.pack_start(self._stack, True, True, 0)

        self._stack.add_titled(self._build_notes_page(), "notas", "Notas")
        self._stack.add_titled(self._build_tags_page(), "tags", "Tags")
        self._settings = SettingsPage(shortcuts, voices, models, store,
                                      config, alarm, sound, notifier,
                                      self, backend=backend)
        # Configurações grew several sections: scroll instead of clipping
        settings_scroller = Gtk.ScrolledWindow()
        settings_scroller.set_policy(Gtk.PolicyType.NEVER,
                                     Gtk.PolicyType.AUTOMATIC)
        settings_scroller.add(self._settings)
        self._stack.add_titled(settings_scroller, "config", "Configurações")
        self._stack.connect("notify::visible-child", self._on_page_switch)

        # The Settings page's shortcut capture needs the window's
        # keyboard events
        self.connect("key-press-event", self._on_key)
        # Closing the window only hides it — the daemon stays in the tray
        self.connect("delete-event", self._on_close)

    # ---------------- Public entry point (daemon) ----------------

    def show_page(self, page=None):
        self.refresh()
        self.show_all()
        if page:
            self._stack.set_visible_child_name(page)
        self.present()

    def refresh(self):
        self._rebuild_tag_dropdown()
        self._reload_list()
        self._reload_tags()
        self._settings.refresh()
        self._alarm.refresh()  # deletes/edits may change the criticals

    def _on_page_switch(self, *_args):
        name = self._stack.get_visible_child_name()
        if name == "notas":
            self._rebuild_tag_dropdown()
            self._reload_list()
        elif name == "tags":
            self._reload_tags()
        elif name == "config":
            self._settings.refresh()

    def _on_key(self, _widget, event):
        # the visible child is the ScrolledWindow wrapping the page
        if self._stack.get_visible_child_name() == "config":
            return self._settings.handle_key(event)
        return False

    # ================= Page: Notas =================

    def _build_notes_page(self):
        """Inner stack: 'list' (search + filters + notes) ⇄ 'detail'
        (full content, editable). The sidebar does not see the detail."""
        self._notes_stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT
        )
        self._notes_stack.add_named(self._build_notes_list(), "list")
        self._notes_stack.add_named(self._build_detail(), "detail")
        return self._notes_stack

    def _build_notes_list(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      margin=12)

        self._search = Gtk.SearchEntry(
            placeholder_text="Buscar nas notas (busca por prefixo)..."
        )
        self._search.connect("search-changed",
                             lambda *_: self._reload_list())
        box.pack_start(self._search, False, False, 0)

        # ---- filter row: favorites + tag (dropdown) + period ----
        filters = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.pack_start(filters, False, False, 0)

        self._favorites_button = Gtk.ToggleButton(label="★ Favoritos")
        self._favorites_button.set_tooltip_text("Mostrar só as favoritas")
        self._favorites_button.connect("toggled", self._on_favorites_toggle)
        filters.pack_start(self._favorites_button, False, False, 0)

        self._tag_combo = Gtk.ComboBoxText()
        self._tag_combo.set_tooltip_text("Filtrar por tag")
        self._tag_combo.connect("changed", self._on_tag_changed)
        filters.pack_start(self._tag_combo, False, False, 0)

        self._period_combo = Gtk.ComboBoxText()
        for period_id, label in PERIODS:
            self._period_combo.append(period_id, label)
        self._period_combo.set_active_id("")
        self._period_combo.connect("changed", self._on_period_changed)
        filters.pack_start(self._period_combo, False, False, 0)

        reload_button = Gtk.Button.new_from_icon_name(
            "view-refresh-symbolic", Gtk.IconSize.BUTTON
        )
        reload_button.set_tooltip_text("Recarregar a lista de notas")
        reload_button.connect("clicked", self._on_reload)
        filters.pack_end(reload_button, False, False, 0)

        new_button = Gtk.Button.new_from_icon_name(
            "list-add-symbolic", Gtk.IconSize.BUTTON
        )
        new_button.set_tooltip_text("Nova nota escrita")
        new_button.connect("clicked", self._on_new_note)
        filters.pack_end(new_button, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box.pack_start(scroller, True, True, 0)

        self._list = Gtk.ListBox()
        self._list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._list.connect("row-activated", self._on_note_activated)
        scroller.add(self._list)

        return box

    # ---------------- Detail (view/edit one note) ----------------

    def _build_detail(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      margin=12)
        self._current_note = None
        self._pending_tags = set()  # tags chosen while creating a note

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.pack_start(bar, False, False, 0)

        back = Gtk.Button.new_from_icon_name(
            "go-previous-symbolic", Gtk.IconSize.BUTTON
        )
        back.set_tooltip_text("Voltar sem salvar")
        back.connect("clicked", lambda *_: self._leave_detail())
        bar.pack_start(back, False, False, 0)

        self._detail_title = Gtk.Label(xalign=0)
        self._detail_title.get_style_context().add_class("dim-label")
        bar.pack_start(self._detail_title, True, True, 0)

        self._detail_star = Gtk.ToggleButton()
        self._star_handler_id = self._detail_star.connect(
            "toggled", self._on_detail_favorite
        )
        bar.pack_start(self._detail_star, False, False, 0)

        self._detail_critical = Gtk.ToggleButton()
        self._critical_handler_id = self._detail_critical.connect(
            "toggled", self._on_detail_critical
        )
        bar.pack_start(self._detail_critical, False, False, 0)

        self._detail_tags = Gtk.MenuButton(label="🏷")
        self._detail_tags.set_tooltip_text("Tags desta nota")
        bar.pack_start(self._detail_tags, False, False, 0)

        play = Gtk.Button.new_from_icon_name(
            "media-playback-start-symbolic", Gtk.IconSize.BUTTON
        )
        play.set_tooltip_text("Tocar o texto exibido")
        play.connect("clicked", self._on_detail_play)
        bar.pack_start(play, False, False, 0)

        self._detail_delete = Gtk.Button.new_from_icon_name(
            "user-trash-symbolic", Gtk.IconSize.BUTTON
        )
        self._detail_delete.set_tooltip_text("Apagar esta nota")
        self._detail_delete.connect("clicked", self._on_detail_delete)
        bar.pack_start(self._detail_delete, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box.pack_start(scroller, True, True, 0)

        self._editor = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self._editor.set_top_margin(8)
        self._editor.set_left_margin(8)
        self._editor.set_right_margin(8)
        scroller.add(self._editor)

        save = Gtk.Button(label="Salvar")
        save.get_style_context().add_class("suggested-action")
        save.connect("clicked", self._on_detail_save)
        box.pack_start(save, False, False, 0)

        return box

    def _on_note_activated(self, _list, row):
        note = getattr(row, "note", None)
        if note is not None:
            self._open_detail(note)

    def _open_detail(self, note):
        self._stop_playback()
        self._current_note = note
        self._detail_title.set_text(note.title)
        self._editor.get_buffer().set_text(note.text)
        # set_active without firing the toggle handler
        self._detail_star.handler_block(self._star_handler_id)
        self._detail_star.set_active(note.favorite)
        self._detail_star.handler_unblock(self._star_handler_id)
        self._paint_star(self._detail_star, note.favorite)
        self._detail_critical.handler_block(self._critical_handler_id)
        self._detail_critical.set_active(note.critical)
        self._detail_critical.handler_unblock(self._critical_handler_id)
        self._paint_critical(self._detail_critical, note.critical)
        self._detail_star.set_sensitive(True)
        self._detail_critical.set_sensitive(True)
        self._detail_tags.set_sensitive(True)
        self._detail_delete.set_sensitive(True)
        self._detail_tags.set_popover(
            self._build_tags_popover(note, self._detail_tags)
        )
        self._notes_stack.set_visible_child_name("detail")

    def _open_new_note(self):
        """Same detail view, empty, in create mode (_current_note is
        None): Salvar creates the note via store.save."""
        self._stop_playback()
        self._current_note = None
        self._detail_title.set_text("Nova nota")
        self._editor.get_buffer().set_text("")
        self._detail_star.handler_block(self._star_handler_id)
        self._detail_star.set_active(False)
        self._detail_star.handler_unblock(self._star_handler_id)
        self._paint_star(self._detail_star, False)
        self._detail_critical.handler_block(self._critical_handler_id)
        self._detail_critical.set_active(False)
        self._detail_critical.handler_unblock(self._critical_handler_id)
        self._paint_critical(self._detail_critical, False)
        # favorite/critical/delete only make sense after the note exists;
        # tags can be picked now and are applied right after Salvar
        self._detail_star.set_sensitive(False)
        self._detail_critical.set_sensitive(False)
        self._detail_delete.set_sensitive(False)
        self._pending_tags = set()
        self._detail_tags.set_sensitive(True)
        self._detail_tags.set_popover(
            self._build_pending_tags_popover(self._detail_tags)
        )
        self._notes_stack.set_visible_child_name("detail")
        self._editor.grab_focus()

    def _editor_text(self):
        buffer = self._editor.get_buffer()
        start, end = buffer.get_bounds()
        return buffer.get_text(start, end, True)

    def _on_detail_save(self, _button):
        text = self._editor_text()
        if self._current_note is None:  # create mode (_open_new_note)
            if not text.strip():
                self._notifier.send("Erro", "A nota está vazia.")
                return
            note = self._store.save(text)
            for name in sorted(self._pending_tags):
                self._store.add_tag(note.id, name)
            self._notifier.send("Nota criada", preview(note.text))
            self._leave_detail()
            return
        try:
            self._store.update_text(self._current_note.id, text)
        except ValueError as error:
            self._notifier.send("Erro", str(error))
            return
        self._leave_detail()

    def _leave_detail(self):
        self._stop_playback()
        self._current_note = None
        self._notes_stack.set_visible_child_name("list")
        self.refresh()

    def _on_detail_favorite(self, button):
        if self._current_note is None:
            return
        self._store.set_favorite(self._current_note.id, button.get_active())
        self._paint_star(button, button.get_active())

    def _on_detail_critical(self, button):
        if self._current_note is None:
            return
        self._store.set_critical(self._current_note.id, button.get_active())
        self._paint_critical(button, button.get_active())
        self._alarm.refresh()

    def _on_detail_play(self, button):
        self._stop_playback()
        button.set_sensitive(False)
        threading.Thread(
            target=self._play_worker,
            args=(button, self._editor_text()),
            daemon=True,
        ).start()

    def _on_detail_delete(self, _button):
        note = self._current_note
        if note is None:
            return
        if self._confirm(f"Apagar a nota {note.title}?",
                         preview(note.text)):
            self._store.delete(note)
            self._leave_detail()

    def _rebuild_tag_dropdown(self):
        """Repopulates the dropdown with the database tags, preserving
        the selection (falls back to "Todas" if the selected tag was
        deleted/renamed)."""
        names = self._store.tags()
        if self._active_tag not in names:
            self._active_tag = ""
        self._reloading_tags = True  # rebuild is not a user choice
        try:
            self._tag_combo.remove_all()
            self._tag_combo.append("", "Todas as tags")
            for name in names:
                self._tag_combo.append(name, f"🏷 {name}")
            self._tag_combo.set_active_id(self._active_tag)
        finally:
            self._reloading_tags = False

    def _reload_list(self):
        self._stop_playback()
        for child in self._list.get_children():
            self._list.remove(child)

        notes = self._store.search(
            text=self._search.get_text(),
            tags=[self._active_tag] if self._active_tag else [],
            favorites=self._favorites_only,
            since=period_since(self._period),
        )
        if not notes:
            row = Gtk.ListBoxRow(selectable=False)
            row.add(self._empty_label())
            self._list.add(row)
        for note in notes:
            self._list.add(self._build_row(note))
        self._list.show_all()

    def _has_filters(self):
        return bool(self._search.get_text().strip() or self._active_tag
                    or self._favorites_only or self._period)

    def _empty_label(self):
        if self._has_filters():
            text = "Nenhuma nota encontrada com esses filtros."
        else:
            text = ("Nenhuma nota ainda.\n"
                    "Aperte Super+R para gravar a primeira.")
        label = Gtk.Label(label=text)
        label.set_justify(Gtk.Justification.CENTER)
        return label

    def _on_reload(self, _button):
        # same as switching back to the page: new notes may bring new tags
        self._rebuild_tag_dropdown()
        self._reload_list()

    def _on_new_note(self, _button):
        self._open_new_note()

    def _on_tag_changed(self, combo):
        if self._reloading_tags:
            return
        self._active_tag = combo.get_active_id() or ""
        self._reload_list()

    def _on_favorites_toggle(self, button):
        self._favorites_only = button.get_active()
        self._reload_list()

    def _on_period_changed(self, combo):
        self._period = combo.get_active_id() or ""
        self._reload_list()

    def _build_row(self, note):
        row = Gtk.ListBoxRow(selectable=False)
        row.note = note  # read by _on_note_activated (opens the detail)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                       margin=6)
        row.add(hbox)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        heading = note.title
        if note.tags:
            heading += "   🏷 " + ", ".join(note.tags)
        title = Gtk.Label(label=heading, xalign=0)
        title.get_style_context().add_class("dim-label")
        excerpt = Gtk.Label(label=preview(note.text), xalign=0)
        excerpt.set_ellipsize(Pango.EllipsizeMode.END)
        vbox.pack_start(title, False, False, 0)
        vbox.pack_start(excerpt, False, False, 0)
        hbox.pack_start(vbox, True, True, 0)

        star = Gtk.ToggleButton()
        star.set_active(note.favorite)  # before connect
        self._paint_star(star, note.favorite)
        star.connect("toggled", self._on_favorite, note)
        hbox.pack_start(star, False, False, 0)

        critical = Gtk.ToggleButton()
        critical.set_active(note.critical)  # before connect
        self._paint_critical(critical, note.critical)
        critical.connect("toggled", self._on_critical, note)
        hbox.pack_start(critical, False, False, 0)

        tags_button = Gtk.MenuButton(label="🏷")
        tags_button.set_tooltip_text("Tags desta nota")
        tags_button.set_popover(self._build_tags_popover(note, tags_button))
        hbox.pack_start(tags_button, False, False, 0)

        play_button = Gtk.Button.new_from_icon_name(
            "media-playback-start-symbolic", Gtk.IconSize.BUTTON
        )
        play_button.set_tooltip_text("Tocar esta nota")
        play_button.connect("clicked", self._on_play, note)
        hbox.pack_start(play_button, False, False, 0)

        delete_button = Gtk.Button.new_from_icon_name(
            "user-trash-symbolic", Gtk.IconSize.BUTTON
        )
        delete_button.set_tooltip_text("Apagar esta nota")
        delete_button.connect("clicked", self._on_delete, note)
        hbox.pack_start(delete_button, False, False, 0)

        return row

    # ---------------- Favorites ----------------

    def _paint_star(self, button, favorite):
        name = "starred-symbolic" if favorite else "non-starred-symbolic"
        button.set_image(Gtk.Image.new_from_icon_name(name,
                                                      Gtk.IconSize.BUTTON))
        button.set_tooltip_text(
            "Desmarcar favorita" if favorite else "Marcar como favorita"
        )

    def _on_favorite(self, button, note):
        active = button.get_active()
        self._store.set_favorite(note.id, active)
        self._paint_star(button, active)
        if self._favorites_only:
            # the note may have left the current filter — reload outside
            # the handler (the clicked button is destroyed by the reload)
            GLib.idle_add(self._reload_list)

    # ---------------- Critical notes (alarm) ----------------

    def _paint_critical(self, button, critical):
        name = "alarm-symbolic" if critical else "appointment-new-symbolic"
        button.set_image(Gtk.Image.new_from_icon_name(name,
                                                      Gtk.IconSize.BUTTON))
        button.set_tooltip_text(
            "Crítica com alarme ativo — clique para tornar normal"
            if critical else "Tornar crítica (alarme periódico)"
        )

    def _on_critical(self, button, note):
        active = button.get_active()
        self._store.set_critical(note.id, active)
        self._paint_critical(button, active)
        self._alarm.refresh()  # arms/disarms right away

    # ---------------- Per-note tags (popover) ----------------

    @staticmethod
    def _popover_scroller(popover, box):
        """Wraps the popover content: with many tags it scrolls instead
        of growing past the screen."""
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_height(True)
        scroller.set_max_content_height(320)
        scroller.add(box)
        popover.add(scroller)
        return scroller

    def _build_tags_popover(self, note, button):
        popover = Gtk.Popover()
        popover.set_relative_to(button)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                      margin=8)
        scroller = self._popover_scroller(popover, box)

        for name in self._store.tags():
            check = Gtk.CheckButton(label=name)
            check.set_active(name in note.tags)  # before connect
            check.connect("toggled", self._on_note_tag, note, name)
            box.pack_start(check, False, False, 0)

        new_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        entry = Gtk.Entry(placeholder_text="nova tag")
        add = Gtk.Button(label="Adicionar")
        add.connect("clicked", self._on_new_note_tag, note, entry)
        entry.connect(
            "activate",
            lambda e: self._on_new_note_tag(add, note, e),
        )
        new_row.pack_start(entry, True, True, 0)
        new_row.pack_start(add, False, False, 0)
        box.pack_start(new_row, False, False, 4)

        scroller.show_all()
        return popover

    def _build_pending_tags_popover(self, button):
        """Create-mode variant of the tags popover: checks toggle the
        _pending_tags set, applied to the store right after Salvar."""
        popover = Gtk.Popover()
        popover.set_relative_to(button)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                      margin=8)
        scroller = self._popover_scroller(popover, box)

        # existing tags plus the pending ones not yet in the store
        names = {name.lower(): name for name in self._store.tags()}
        for name in self._pending_tags:
            names.setdefault(name.lower(), name)
        pending = {name.lower() for name in self._pending_tags}
        for name in sorted(names.values(), key=str.lower):
            check = Gtk.CheckButton(label=name)
            # tag names are case-insensitive in the store (NOCASE)
            check.set_active(name.lower() in pending)  # before connect
            check.connect("toggled", self._on_pending_tag, name)
            box.pack_start(check, False, False, 0)

        new_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        entry = Gtk.Entry(placeholder_text="nova tag")
        add = Gtk.Button(label="Adicionar")
        add.connect("clicked", self._on_new_pending_tag, entry)
        entry.connect(
            "activate",
            lambda e: self._on_new_pending_tag(add, e),
        )
        new_row.pack_start(entry, True, True, 0)
        new_row.pack_start(add, False, False, 0)
        box.pack_start(new_row, False, False, 4)

        scroller.show_all()
        return popover

    def _on_pending_tag(self, check, name):
        if check.get_active():
            self._pending_tags.add(name)
        else:  # drop any case variant (tag names are NOCASE)
            self._pending_tags = {
                t for t in self._pending_tags if t.lower() != name.lower()
            }

    def _on_new_pending_tag(self, _button, entry):
        name = entry.get_text().strip()
        if not name:
            return
        self._pending_tags.add(name)
        entry.set_text("")
        # rebuild so the new tag shows up checked in the list
        self._detail_tags.set_popover(
            self._build_pending_tags_popover(self._detail_tags)
        )

    def _on_note_tag(self, check, note, name):
        if check.get_active():
            self._store.add_tag(note.id, name)
        else:
            self._store.remove_tag(note.id, name)
        GLib.idle_add(self.refresh)  # updates the dropdown and the row 🏷

    def _on_new_note_tag(self, _button, note, entry):
        name = entry.get_text().strip()
        if not name:
            return
        self._store.add_tag(note.id, name)
        entry.set_text("")
        GLib.idle_add(self.refresh)

    # ================= Page: Tags (CRUD) =================

    def _build_tags_page(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      margin=12)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._tag_entry = Gtk.Entry(placeholder_text="nova tag")
        create_button = Gtk.Button(label="Criar")
        create_button.connect("clicked", self._on_create_tag)
        self._tag_entry.connect("activate",
                                lambda *_: self._on_create_tag(create_button))
        top.pack_start(self._tag_entry, True, True, 0)
        top.pack_start(create_button, False, False, 0)
        box.pack_start(top, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box.pack_start(scroller, True, True, 0)

        self._tags_list = Gtk.ListBox()
        self._tags_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller.add(self._tags_list)

        return box

    def _reload_tags(self):
        for child in self._tags_list.get_children():
            self._tags_list.remove(child)

        counts = self._store.tags_with_counts()
        if not counts:
            row = Gtk.ListBoxRow(selectable=False)
            label = Gtk.Label(
                label="Nenhuma tag ainda.\nCrie uma acima ou pelo 🏷 de uma nota."
            )
            label.set_justify(Gtk.Justification.CENTER)
            row.add(label)
            self._tags_list.add(row)
        for name, count in counts:
            self._tags_list.add(self._build_tag_row(name, count))
        self._tags_list.show_all()

    def _build_tag_row(self, name, count):
        row = Gtk.ListBoxRow(selectable=False)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6,
                       margin=6)
        row.add(hbox)

        label = Gtk.Label(label=f"🏷 {name}", xalign=0)
        count_label = Gtk.Label(label=f"{count} nota(s)", xalign=0)
        count_label.get_style_context().add_class("dim-label")
        hbox.pack_start(label, True, True, 0)
        hbox.pack_start(count_label, False, False, 6)

        rename = Gtk.Button.new_from_icon_name(
            "document-edit-symbolic", Gtk.IconSize.BUTTON
        )
        rename.set_tooltip_text("Renomear esta tag")
        rename.connect("clicked", self._on_rename_tag, name)
        hbox.pack_start(rename, False, False, 0)

        delete = Gtk.Button.new_from_icon_name(
            "user-trash-symbolic", Gtk.IconSize.BUTTON
        )
        delete.set_tooltip_text("Apagar esta tag")
        delete.connect("clicked", self._on_delete_tag, name, count)
        hbox.pack_start(delete, False, False, 0)

        return row

    def _on_create_tag(self, _button):
        name = self._tag_entry.get_text().strip()
        if not name:
            return
        try:
            created = self._store.create_tag(name)
        except ValueError as error:
            self._notifier.send("Erro", str(error))
            return
        if not created:
            self._notifier.send("Tags", f"A tag \"{name}\" já existe.")
        self._tag_entry.set_text("")
        self.refresh()

    def _on_rename_tag(self, _button, name):
        dialog = Gtk.Dialog(title=f"Renomear tag \"{name}\"",
                            transient_for=self, modal=True)
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL,
                           "Renomear", Gtk.ResponseType.OK)
        entry = Gtk.Entry(text=name, activates_default=True, margin=8)
        dialog.get_content_area().add(entry)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.show_all()
        response = dialog.run()
        new = entry.get_text().strip()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not new or new == name:
            return
        # Renaming into an existing tag merges them — warn first
        existing = {t.lower() for t in self._store.tags()}
        if new.lower() in existing and new.lower() != name.lower():
            if not self._confirm(
                f"Já existe a tag \"{new}\".",
                f"As notas de \"{name}\" serão unidas a \"{new}\". Continuar?",
            ):
                return
        try:
            self._store.rename_tag(name, new)
        except ValueError as error:
            self._notifier.send("Erro", str(error))
            return
        self.refresh()

    def _on_delete_tag(self, _button, name, count):
        if not self._confirm(
            f"Apagar a tag \"{name}\"?",
            f"As {count} nota(s) associadas não serão apagadas — "
            "só deixam de ter essa tag.",
        ):
            return
        self._store.delete_tag(name)
        self.refresh()

    def _confirm(self, text, detail):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=text,
        )
        dialog.format_secondary_text(detail)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES

    # ---------------- Play / stop ----------------

    def _on_play(self, button, note):
        if button is self._playing_button:
            self._stop_playback()
            return
        self._stop_playback()
        button.set_sensitive(False)  # until the synthesis finishes
        # Piper synthesis blocks — run in a thread, like transcription
        threading.Thread(
            target=self._play_worker, args=(button, note.text), daemon=True
        ).start()

    def _play_worker(self, button, text):
        try:
            self._player.play(text)
        except PlayerError as error:
            GLib.idle_add(self._on_playback_error, button, str(error))
        else:
            GLib.idle_add(self._on_playback_started, button)

    def _on_playback_error(self, button, message):
        button.set_sensitive(True)
        self._notifier.send("Erro", message)
        return False

    def _on_playback_started(self, button):
        button.set_sensitive(True)
        self._mark_playing(button)
        # "playing now" indicator: back to play when the audio ends
        GLib.timeout_add(300, self._check_finished)
        return False

    def _check_finished(self):
        if self._player.is_playing:
            return True  # keep checking
        self._unmark_playing()
        return False

    def _mark_playing(self, button):
        self._playing_button = button
        image = Gtk.Image.new_from_icon_name(
            "media-playback-pause-symbolic", Gtk.IconSize.BUTTON
        )
        button.set_image(image)
        button.set_tooltip_text("Parar a reprodução")

    def _unmark_playing(self):
        if self._playing_button is not None:
            image = Gtk.Image.new_from_icon_name(
                "media-playback-start-symbolic", Gtk.IconSize.BUTTON
            )
            self._playing_button.set_image(image)
            self._playing_button.set_tooltip_text("Tocar esta nota")
            self._playing_button = None

    def _stop_playback(self):
        self._player.stop()
        self._unmark_playing()

    # ---------------- Delete note ----------------

    def _on_delete(self, _button, note):
        if self._confirm(f"Apagar a nota {note.title}?",
                         preview(note.text)):
            self._store.delete(note)
            self.refresh()

    # ---------------- Close ----------------

    def _on_close(self, *_args):
        self._stop_playback()
        self.hide()
        return True  # don't destroy: reopening from the tray is instant
