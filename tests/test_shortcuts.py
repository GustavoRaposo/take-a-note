"""Tests for tomenotas.infra.shortcuts — GNOME shortcuts via gsettings."""

from pathlib import Path
from types import SimpleNamespace

from tomenotas.infra.shortcuts import BASE_PATH, ShortcutManager


class FakeGsettings:
    """Simulates the gsettings CLI: get/set/list-recursively."""

    def __init__(self, listing="@as []", entries=None, recursive=None):
        self.listing = listing          # value of the custom-keybindings key
        self.entries = entries or {}    # path -> {key: printed value}
        self.recursive = recursive or {}  # schema -> list-recursively output
        self.sets = []

    def __call__(self, cmd, **kwargs):
        assert cmd[0] == "gsettings"
        op = cmd[1]
        if op == "get":
            target, key = cmd[2], cmd[3]
            if ":" in target:
                path = target.split(":", 1)[1]
                out = self.entries.get(path, {}).get(key, "''")
            elif key == "custom-keybindings":
                out = self.listing
            else:
                out = "''"
        elif op == "set":
            target, key, value = cmd[2], cmd[3], cmd[4]
            self.sets.append((target, key, value))
            if ":" in target:
                path = target.split(":", 1)[1]
                self.entries.setdefault(path, {})[key] = f"'{value}'"
            elif key == "custom-keybindings":
                self.listing = value
            out = ""
        else:  # list-recursively
            out = self.recursive.get(cmd[2], "")
        return SimpleNamespace(stdout=out + "\n", returncode=0)


BIN = Path("/home/x/bin")
RECORD_PATH = f"{BASE_PATH}/tomenotas-gravar/"
LIST_PATH = f"{BASE_PATH}/tomenotas-listar/"


def test_actions_point_to_the_right_commands():
    manager = ShortcutManager(BIN, run=FakeGsettings())
    actions = manager.actions
    assert actions["gravar"].command == "/home/x/bin/tomenotas-hotkey-record"
    assert actions["listar"].command == "/home/x/bin/tomenotas-hotkey-window"
    assert actions["ler"].command == "/home/x/bin/tomenotas-hotkey-read"
    assert actions["gravar"].default == "<Super>r"
    assert actions["listar"].default == "<Super>y"
    assert actions["ler"].default == "<Super>t"


def test_get_binding_strips_quotes():
    gs = FakeGsettings(entries={RECORD_PATH: {"binding": "'<Super>r'"}})
    manager = ShortcutManager(BIN, run=gs)
    assert manager.get_binding("gravar") == "<Super>r"


def test_get_binding_without_value_returns_empty():
    manager = ShortcutManager(BIN, run=FakeGsettings())
    assert manager.get_binding("gravar") == ""


def test_set_binding_registers_on_empty_list_and_writes_everything():
    gs = FakeGsettings(listing="@as []")
    manager = ShortcutManager(BIN, run=gs)
    manager.set_binding("gravar", "<Super>F9")

    assert gs.listing == f"['{RECORD_PATH}']"
    schema_path = [s for s in gs.sets if ":" in s[0]]
    keys = {(key, value) for _, key, value in schema_path}
    assert ("name", "Tomenotas - Gravar") in keys
    assert ("command", "/home/x/bin/tomenotas-hotkey-record") in keys
    assert ("binding", "<Super>F9") in keys


def test_set_binding_preserves_existing_list_without_duplicating():
    gs = FakeGsettings(listing=f"['/outro/app/', '{RECORD_PATH}']")
    manager = ShortcutManager(BIN, run=gs)
    manager.set_binding("gravar", "<Super>F9")
    # already on the list: leave it untouched
    assert gs.listing == f"['/outro/app/', '{RECORD_PATH}']"

    manager.set_binding("listar", "<Super>F10")
    assert gs.listing == f"['/outro/app/', '{RECORD_PATH}', '{LIST_PATH}']"


def test_conflict_with_system_shortcut():
    gs = FakeGsettings(recursive={
        "org.gnome.desktop.wm.keybindings":
            "org.gnome.desktop.wm.keybindings close ['<Alt>F4', '<Super>r']\n"
            "org.gnome.desktop.wm.keybindings minimize ['<Super>h']",
    })
    manager = ShortcutManager(BIN, run=gs)
    conflicts = manager.list_conflicts("<Super>r")
    assert conflicts == ["close (org.gnome.desktop.wm.keybindings)"]


def test_conflict_ignores_similar_prefix():
    # '<Super>Right' must not be treated as a conflict of '<Super>r'
    gs = FakeGsettings(recursive={
        "org.gnome.desktop.wm.keybindings":
            "org.gnome.desktop.wm.keybindings move-right ['<Super>Right']",
    })
    manager = ShortcutManager(BIN, run=gs)
    assert manager.list_conflicts("<Super>r") == []


def test_conflict_is_case_insensitive():
    gs = FakeGsettings(recursive={
        "org.gnome.shell.keybindings":
            "org.gnome.shell.keybindings toggle-overview ['<super>R']",
    })
    manager = ShortcutManager(BIN, run=gs)
    assert manager.list_conflicts("<Super>r") == [
        "toggle-overview (org.gnome.shell.keybindings)"
    ]


def test_conflict_with_another_custom_shortcut_by_name():
    gs = FakeGsettings(
        listing=f"['{RECORD_PATH}', '{LIST_PATH}']",
        entries={
            RECORD_PATH: {"binding": "'<Super>r'", "name": "'Tomenotas - Gravar'"},
            LIST_PATH: {"binding": "'<Super>l'", "name": "'Tomenotas - Listar'"},
        },
    )
    manager = ShortcutManager(BIN, run=gs)
    # using <Super>l for "gravar": conflicts with "listar", by name
    assert manager.list_conflicts("<Super>l", ignore_action="gravar") == [
        "Tomenotas - Listar"
    ]
    # the edited action's own shortcut is not a conflict
    assert manager.list_conflicts("<Super>r", ignore_action="gravar") == []


def test_without_conflicts_returns_empty_list():
    manager = ShortcutManager(BIN, run=FakeGsettings())
    assert manager.list_conflicts("<Super>F12") == []


def test_ensure_defaults_registers_only_missing_bindings():
    # "gravar" already has a binding (user may have customized it):
    # ensure_defaults must not touch it, only register the missing two
    gs = FakeGsettings(
        listing=f"['{RECORD_PATH}']",
        entries={RECORD_PATH: {"binding": "'<Super>F9'"}},
    )
    manager = ShortcutManager(BIN, run=gs)
    registered = manager.ensure_defaults()

    assert registered == ["listar", "ler"]
    assert manager.get_binding("gravar") == "<Super>F9"  # untouched
    assert manager.get_binding("listar") == "<Super>y"
    assert manager.get_binding("ler") == "<Super>t"
    assert LIST_PATH in gs.listing


def test_ensure_defaults_on_fresh_system_registers_all():
    gs = FakeGsettings(listing="@as []")
    manager = ShortcutManager(BIN, run=gs)
    assert manager.ensure_defaults() == ["gravar", "listar", "ler"]
    assert manager.get_binding("gravar") == "<Super>r"


def test_ensure_defaults_is_idempotent():
    gs = FakeGsettings(listing="@as []")
    manager = ShortcutManager(BIN, run=gs)
    manager.ensure_defaults()
    assert manager.ensure_defaults() == []  # second run: nothing to do


def test_scan_tolerates_varied_gsettings_formats():
    gs = FakeGsettings(recursive={
        # a string value (not a list), a short line and the
        # custom-keybindings path list itself must all be handled
        # without false positives
        "org.gnome.settings-daemon.plugins.media-keys":
            "org.gnome.settings-daemon.plugins.media-keys screensaver '<Super>s'\n"
            "linha-curta\n"
            "org.gnome.settings-daemon.plugins.media-keys custom-keybindings "
            "['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/tomenotas-gravar/']",
    })
    manager = ShortcutManager(BIN, run=gs)
    assert manager.list_conflicts("<Super>s") == [
        "screensaver (org.gnome.settings-daemon.plugins.media-keys)"
    ]
    assert manager.list_conflicts("<Super>x") == []
