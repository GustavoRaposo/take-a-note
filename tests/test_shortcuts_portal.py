"""Tests for tomenotas.infra.shortcuts_portal — pure helpers for the
GlobalShortcuts portal backend (data + backend selection, no D-Bus)."""

from tomenotas.domain.shortcuts import SHORTCUTS
from tomenotas.infra.shortcuts_portal import (
    choose_backend,
    portal_definitions,
    trigger_to_portal,
)


# ---------------- trigger translation ----------------

def test_trigger_translation_to_portal_syntax():
    assert trigger_to_portal("<Super>r") == "SUPER+r"
    assert trigger_to_portal("<Super>bracketleft") == "SUPER+bracketleft"
    assert trigger_to_portal("<Ctrl><Shift>a") == "CTRL+SHIFT+a"


# ---------------- BindShortcuts payload ----------------

def test_portal_definitions_match_the_catalog():
    defs = portal_definitions()
    assert [d[0] for d in defs] == [s.id for s in SHORTCUTS]
    first_id, meta = defs[0]
    assert first_id == "gravar"
    assert meta["description"] == "Gravar/parar"
    assert meta["preferred_trigger"] == "SUPER+r"


# ---------------- backend selection ----------------

def test_explicit_backend_always_wins():
    assert choose_backend("gsettings", "KDE", portal_available=True) == "gsettings"
    assert choose_backend("portal", "GNOME", portal_available=False) == "portal"


def test_auto_on_gnome_prefers_gsettings():
    # GNOME keeps the in-app key-capture UX (gsettings), even with a portal
    assert choose_backend("auto", "ubuntu:GNOME", portal_available=True) == "gsettings"


def test_auto_off_gnome_uses_portal_when_available():
    assert choose_backend("auto", "KDE", portal_available=True) == "portal"


def test_auto_falls_back_to_gsettings_without_a_portal():
    assert choose_backend("auto", "KDE", portal_available=False) == "gsettings"


def test_unknown_configured_value_is_treated_as_auto():
    assert choose_backend("banana", "KDE", portal_available=True) == "portal"
