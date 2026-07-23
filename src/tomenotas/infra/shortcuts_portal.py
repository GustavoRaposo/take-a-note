"""Pure helpers for the GlobalShortcuts portal backend.

Data and decisions only — no D-Bus, no gi — so this stays testable. The
actual portal session/signal wiring lives in ui/portal_backend.py (needs
Gio). Shared with the gsettings backend through the domain catalog.
"""

import re

from ..domain.shortcuts import SHORTCUTS

VALID_BACKENDS = ("auto", "gsettings", "portal")


def trigger_to_portal(accel: str) -> str:
    """GNOME accelerator → the portal's `preferred_trigger` hint:
    "<Super>r" → "SUPER+r", "<Ctrl><Shift>a" → "CTRL+SHIFT+a".

    Best-effort: the portal treats this only as a suggestion — the user
    confirms/assigns the real key in the system dialog, so backends may
    ignore it."""
    mods = [m.upper() for m in re.findall(r"<([^>]+)>", accel)]
    key = re.sub(r"<[^>]+>", "", accel)
    return "+".join([*mods, key]) if key else "+".join(mods)


def portal_definitions(specs=SHORTCUTS):
    """The shared catalog as the portal BindShortcuts `shortcuts`
    argument: [(id, {"description", "preferred_trigger"}), ...]."""
    return [
        (spec.id, {
            "description": spec.title,
            "preferred_trigger": trigger_to_portal(spec.default),
        })
        for spec in specs
    ]


def choose_backend(configured: str, desktop: str,
                   portal_available: bool) -> str:
    """Picks the shortcut backend: returns "gsettings" or "portal".

    `configured` is the config.json value ("auto"/"gsettings"/"portal");
    an explicit value always wins. In "auto", GNOME keeps the gsettings
    backend (its in-app key capture is the better UX there); off GNOME we
    use the portal when it is available, otherwise fall back to
    gsettings."""
    if configured in ("gsettings", "portal"):
        return configured
    if "gnome" in (desktop or "").lower():
        return "gsettings"
    return "portal" if portal_available else "gsettings"
