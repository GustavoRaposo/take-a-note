"""Live-transcription preview window.

When streaming is on, this window opens while recording and shows the
text growing as the user speaks (fed by DaemonCore.on_stream_text via the
glue). Preview only — the saved note comes from the normal transcription
on stop; closing this window does not stop the recording.

Glue (GTK) — outside the coverage metric; kept thin (only widgets).
"""

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Pango  # noqa: E402


class LiveWindow(Gtk.Window):
    def __init__(self, config=None):
        super().__init__(title="Transcrição ao vivo")
        self.set_default_size(520, 320)
        if config is not None:
            icon_file = config.icons_dir / "tomenotas-idle.svg"
            if icon_file.exists():
                self.set_icon_from_file(str(icon_file))

        header = Gtk.HeaderBar(title="Transcrição ao vivo",
                              subtitle="prévia enquanto você fala")
        header.set_show_close_button(True)
        self.set_titlebar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                      margin=12)
        self.add(box)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        box.pack_start(scroller, True, True, 0)

        self._view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                  editable=False, cursor_visible=False)
        self._view.set_top_margin(8)
        self._view.set_left_margin(8)
        self._view.set_right_margin(8)
        self._scroller = scroller
        scroller.add(self._view)

        hint = Gtk.Label(
            label="Prévia rápida (modelo pequeno). A nota final é gerada "
                  "com o modelo de transcrição ao parar a gravação."
        )
        hint.get_style_context().add_class("dim-label")
        hint.set_line_wrap(True)
        hint.set_xalign(0)
        box.pack_start(hint, False, False, 0)

        # closing hides (the recording keeps going); reused next time
        self.connect("delete-event", self._on_close)

    def begin(self):
        """Opens the window fresh for a new recording."""
        self._view.get_buffer().set_text("")
        self.show_all()
        self.present()

    def update(self, text):
        """Sets the current preview text and keeps the view scrolled down."""
        buffer = self._view.get_buffer()
        buffer.set_text(text)
        end = buffer.get_end_iter()
        self._view.scroll_to_iter(end, 0.0, False, 0, 0)

    def finish(self):
        """Recording stopped — hide the preview."""
        self.hide()

    def _on_close(self, *_args):
        self.hide()
        return True  # don't destroy: reused on the next recording
