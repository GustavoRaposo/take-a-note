"""GlobalShortcuts portal backend (KDE and other non-GNOME desktops).

Registers the shared shortcuts with org.freedesktop.portal.GlobalShortcuts
and routes the portal's `Activated` signal to the daemon's handlers,
in-process — no client scripts. Unlike the gsettings backend, the user
assigns/confirms the keys in the system dialog (the app only suggests
triggers); the portal session dies with the daemon, which matches the
"shortcuts only work while the app is open" invariant natively.

This is glue (Gio/D-Bus) — outside the coverage metric, and validated on
a real portal (KDE's xdg-desktop-portal-kde). On GNOME the default is the
gsettings backend, so this path runs only when forced via
`shortcut_backend=portal`. The pure parts (payload + backend selection)
live in infra/shortcuts_portal.py and are tested.
"""

import logging

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib  # noqa: E402

from ..infra.shortcuts_portal import portal_definitions  # noqa: E402

log = logging.getLogger("tomenotas.portal")

PORTAL_BUS = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
GS_IFACE = "org.freedesktop.portal.GlobalShortcuts"
REQUEST_IFACE = "org.freedesktop.portal.Request"


def portal_available(connection) -> bool:
    """True if the GlobalShortcuts portal answers on the session bus."""
    try:
        connection.call_sync(
            PORTAL_BUS, PORTAL_PATH, "org.freedesktop.DBus.Properties",
            "Get", GLib.Variant("(ss)", (GS_IFACE, "version")),
            GLib.VariantType.new("(v)"), Gio.DBusCallFlags.NONE, 800, None,
        )
        return True
    except GLib.Error:
        return False


class PortalBackend:
    def __init__(self, on_activated, connection=None):
        self._on_activated = on_activated  # callable(action_id)
        self._conn = connection or Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self._session_handle = None
        self._counter = 0

    def register(self) -> None:
        """Subscribes to Activated and starts the CreateSession →
        BindShortcuts handshake (async, driven by Response signals)."""
        self._conn.signal_subscribe(
            PORTAL_BUS, GS_IFACE, "Activated", PORTAL_PATH, None,
            Gio.DBusSignalFlags.NONE, self._on_activated_signal, None,
        )
        self._create_session()

    # ---------------- portal handshake ----------------

    def _token(self, prefix: str) -> str:
        self._counter += 1
        return f"tomenotas_{prefix}_{self._counter}"

    def _await_response(self, token: str, callback) -> None:
        """Fires callback(response, results) once for this Request."""
        sender = self._conn.get_unique_name().lstrip(":").replace(".", "_")
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"
        state = {}

        def handler(conn, _sender, _path, _iface, _signal, params, *_):
            self._conn.signal_unsubscribe(state["id"])
            response, results = params.unpack()
            callback(response, results)

        state["id"] = self._conn.signal_subscribe(
            PORTAL_BUS, REQUEST_IFACE, "Response", path, None,
            Gio.DBusSignalFlags.NONE, handler, None,
        )

    def _create_session(self) -> None:
        req_token = self._token("req")
        self._await_response(req_token, self._on_session_response)
        options = GLib.Variant("a{sv}", {
            "handle_token": GLib.Variant("s", req_token),
            "session_handle_token": GLib.Variant("s", self._token("session")),
        })
        self._conn.call(
            PORTAL_BUS, PORTAL_PATH, GS_IFACE, "CreateSession",
            GLib.Variant("(a{sv})", (options,)),
            GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE, -1, None,
            None, None,
        )

    def _on_session_response(self, response, results) -> None:
        if response != 0:
            log.warning("portal CreateSession denied (response=%s)", response)
            return
        self._session_handle = results["session_handle"]
        self._bind_shortcuts()

    def _bind_shortcuts(self) -> None:
        req_token = self._token("req")
        self._await_response(req_token, self._on_bind_response)
        shortcuts = [
            (sid, {k: GLib.Variant("s", v) for k, v in meta.items()})
            for sid, meta in portal_definitions()
        ]
        args = GLib.Variant(
            "(oa(sa{sv})sa{sv})",
            (self._session_handle, shortcuts, "",
             {"handle_token": GLib.Variant("s", req_token)}),
        )
        self._conn.call(
            PORTAL_BUS, PORTAL_PATH, GS_IFACE, "BindShortcuts", args,
            GLib.VariantType.new("(o)"), Gio.DBusCallFlags.NONE, -1, None,
            None, None,
        )

    def _on_bind_response(self, response, _results) -> None:
        if response != 0:
            log.warning("portal BindShortcuts denied (response=%s)", response)
        else:
            log.info("portal shortcuts bound")

    def _on_activated_signal(self, _conn, _sender, _path, _iface, _signal,
                             params, *_) -> None:
        session_handle, shortcut_id = params.unpack()[:2]
        if session_handle == self._session_handle:
            self._on_activated(shortcut_id)
