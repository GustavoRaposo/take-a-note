"""Tests for tomenotas.domain.shortcuts — the shared action catalog.

This catalog is the single source of truth for the keybindings, shared by
every backend (gsettings today, GlobalShortcuts portal next). It is pure
data — no I/O, no platform specifics.
"""

from tomenotas.domain.shortcuts import SHORTCUTS, SHORTCUTS_BY_ID, ShortcutSpec


def test_catalog_has_the_expected_actions_in_order():
    assert [s.id for s in SHORTCUTS] == [
        "gravar", "listar", "ler", "critica", "ler-critica", "reuniao",
    ]


def test_every_action_has_a_title_and_a_default_trigger():
    for spec in SHORTCUTS:
        assert isinstance(spec, ShortcutSpec)
        assert spec.title
        assert spec.default.startswith("<Super>")


def test_default_triggers_are_unique():
    defaults = [s.default for s in SHORTCUTS]
    assert len(defaults) == len(set(defaults))


def test_lookup_by_id():
    assert SHORTCUTS_BY_ID["gravar"].default == "<Super>r"
    assert SHORTCUTS_BY_ID["reuniao"].default == "<Super>bracketleft"
    assert set(SHORTCUTS_BY_ID) == {s.id for s in SHORTCUTS}
