"""GNOME shortcut backend: global shortcuts via gsettings
custom-keybindings.

Registers the actions from the shared catalog (domain/shortcuts.py) and
lets the settings UI change them, in-app. Uses the gsettings CLI through
an injectable subprocess (same pattern as the other modules), which keeps
the logic — including conflict detection — 100% testable. This is one of
the (future) shortcut backends; a GlobalShortcuts portal backend for
KDE/others is planned.

Note: the action ids ("gravar"/"listar"/"ler"/...) are part of the
gsettings paths persisted on users' systems (tomenotas-<id>/) — do not
rename them.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..domain.shortcuts import SHORTCUTS

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA = SCHEMA + ".custom-keybinding"
BASE_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"

# Where to look for conflicts with system shortcuts ("when detectable")
CONFLICT_SCHEMAS = [
    "org.gnome.desktop.wm.keybindings",
    "org.gnome.shell.keybindings",
    "org.gnome.mutter.keybindings",
    SCHEMA,
]

# gsettings-specific per action: the client script it invokes and the
# "name" shown in GNOME's shortcut settings. The portable bits (id,
# title, default trigger) come from domain/shortcuts.py.
_CLIENTS = {
    "gravar": "tomenotas-hotkey-record",
    "listar": "tomenotas-hotkey-window",
    "ler": "tomenotas-hotkey-read",
    "critica": "tomenotas-hotkey-critical",
    "ler-critica": "tomenotas-hotkey-critical-read",
    "reuniao": "tomenotas-hotkey-meeting",
}
_LABELS = {
    "gravar": "Tomenotas - Gravar",
    "listar": "Tomenotas - Listar",
    "ler": "Tomenotas - Ler",
    "critica": "Tomenotas - Critica",
    "ler-critica": "Tomenotas - Ler Critica",
    "reuniao": "Tomenotas - Reuniao",
}


@dataclass(frozen=True)
class Action:
    id: str       # gsettings path suffix (tomenotas-<id>)
    label: str    # "name" in gsettings
    title: str    # label shown in the UI
    command: str  # executable invoked by the shortcut
    default: str  # default binding (same as install.sh)


def _parse_list(value: str) -> list[str]:
    """'@as []' / \"['/a/', '/b/']\" → list of paths."""
    value = value.strip()
    if not value or value in ("@as []", "[]"):
        return []
    return [
        item.strip().strip("'\"")
        for item in value.strip("[]").split(",")
        if item.strip()
    ]


def _bindings_from(value: str) -> list[str]:
    """Extracts the bindings from a gsettings value, which can be a string
    (\"'<Super>r'\") or a list (\"['<Alt>F4', '<Super>r']\")."""
    value = value.strip()
    if value.startswith("["):
        return _parse_list(value)
    return [value.strip("'\"")] if value.strip("'\"") else []


class ShortcutManager:
    def __init__(self, bin_dir: Path, run=subprocess.run):
        self._run = run
        # built from the shared catalog + the gsettings-specific mappings
        self.actions = {
            spec.id: Action(
                spec.id, _LABELS[spec.id], spec.title,
                str(bin_dir / _CLIENTS[spec.id]), spec.default,
            )
            for spec in SHORTCUTS
        }

    def _out(self, *args: str) -> str:
        result = self._run(
            ["gsettings", *args],
            capture_output=True, text=True, check=False,
        )
        return (result.stdout or "").strip()

    def _path(self, action_id: str) -> str:
        return f"{BASE_PATH}/tomenotas-{action_id}/"

    def get_binding(self, action_id: str) -> str:
        raw = self._out("get", f"{CUSTOM_SCHEMA}:{self._path(action_id)}",
                        "binding")
        return raw.strip("'\"")

    def set_binding(self, action_id: str, binding: str) -> None:
        """Writes the shortcut to GNOME — immediate keyboard effect. Also
        (re)writes name/command, which makes the operation self-repairing."""
        action = self.actions[action_id]
        target = f"{CUSTOM_SCHEMA}:{self._path(action_id)}"
        self._register(self._path(action_id))
        self._out("set", target, "name", action.label)
        self._out("set", target, "command", action.command)
        self._out("set", target, "binding", binding)

    def ensure_defaults(self) -> list[str]:
        """First-run (Fase B): makes sure every action is registered and
        has a binding. Missing binding → register the default; binding
        set but path absent from the custom-keybindings list (dconf
        leftover after an uninstall) → re-list it keeping the user's
        value. Never changes an active binding. The .deb cannot do this
        at install time — postinst runs as root and gsettings is
        per-user — so the daemon calls this on startup; it is a no-op
        afterwards. Returns the ids of the actions (re)registered."""
        listed = _parse_list(self._out("get", SCHEMA, "custom-keybindings"))
        registered = []
        for action_id, action in self.actions.items():
            binding = self.get_binding(action_id)
            if binding and self._path(action_id) in listed:
                continue  # active and listed: leave it alone
            self.set_binding(action_id, binding or action.default)
            registered.append(action_id)
        return registered

    def _register(self, path: str) -> None:
        current = self._out("get", SCHEMA, "custom-keybindings")
        paths = _parse_list(current)
        if path in paths:
            return
        paths.append(path)
        new = "[" + ", ".join(f"'{p}'" for p in paths) + "]"
        self._out("set", SCHEMA, "custom-keybindings", new)

    def list_conflicts(self, binding: str,
                       ignore_action: str | None = None) -> list[str]:
        """Human-readable descriptions of whoever already uses this
        shortcut (empty list if nobody). Compares exact bindings,
        case-insensitively."""
        target = binding.lower()
        conflicts = []

        for schema in CONFLICT_SCHEMAS:
            for line in self._out("list-recursively", schema).splitlines():
                parts = line.split(None, 2)
                if len(parts) < 3:
                    continue
                _, key, value = parts
                if key == "custom-keybindings":
                    continue  # it's the path list, not a binding
                if target in (b.lower() for b in _bindings_from(value)):
                    conflicts.append(f"{key} ({schema})")

        own = self._path(ignore_action) if ignore_action else None
        listing = self._out("get", SCHEMA, "custom-keybindings")
        for path in _parse_list(listing):
            if path == own:
                continue
            entry = f"{CUSTOM_SCHEMA}:{path}"
            b = self._out("get", entry, "binding").strip("'\"")
            if b and b.lower() == target:
                name = self._out("get", entry, "name").strip("'\"")
                conflicts.append(name or path)

        return conflicts
