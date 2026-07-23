"""Shared keyboard-shortcut catalog — the single source of truth.

Pure data with no I/O and no platform specifics, so every backend uses
the same ids, titles and default triggers: the gsettings backend
(GNOME, today) and the GlobalShortcuts portal backend (KDE/others,
planned). Backend-specific details (the gsettings "name" and the client
script, the portal description) live in the adapters.

The `id`s are persisted in users' systems (gsettings paths
`tomenotas-<id>/`, and the portal shortcut ids) — never rename them.
The default triggers use the GNOME accelerator syntax ("<Super>r"); a
portal backend translates them to its own trigger format.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ShortcutSpec:
    id: str       # stable identifier — never rename (persisted)
    title: str    # shown in the UI (and reused as the portal description)
    default: str  # default trigger, GNOME accelerator syntax


# Order matters: ensure_defaults and the settings UI iterate in this order.
SHORTCUTS = [
    ShortcutSpec("gravar", "Gravar/parar", "<Super>r"),
    ShortcutSpec("listar", "Listar notas", "<Super>y"),
    ShortcutSpec("ler", "Ler nota atual", "<Super>t"),
    ShortcutSpec("critica", "Gravar nota crítica", "<Super>i"),
    ShortcutSpec("ler-critica", "Ler crítica mais recente", "<Super>k"),
    ShortcutSpec("reuniao", "Gravar reunião (mic + PC)", "<Super>bracketleft"),
]

SHORTCUTS_BY_ID = {spec.id: spec for spec in SHORTCUTS}
