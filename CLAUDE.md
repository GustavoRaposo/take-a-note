# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Tomenotas — a personal voice-notes assistant for Ubuntu/GNOME, implemented as a
Python package (`src/tomenotas/`, the daemon: tray icon + D-Bus + recording)
plus bash scripts for listing/reading notes, and an installer/uninstaller.
The Python side is a proper package (pyproject.toml, pytest, 90% coverage gate
on the core); the bash side remains glue code around system tools. All
comments, `notify-send` messages, and user-facing strings are in Portuguese —
keep new code consistent with that.

There is no cloud/API/LLM involved anywhere in this project by design (see README):
speech-to-text and text-to-speech both run fully offline via local binaries. Don't
introduce network calls to AI services when extending this project.

## Architecture

Recording goes through the daemon (Fase 1 of ROADMAP.md); listing/reading are
still standalone scripts communicating through shared files under
`~/.local/share/tomenotas/`:

- **`src/tomenotas/`** — the daemon package, organized in lightweight
  clean-architecture layers. **Dependency rule (enforced by
  `tests/test_arquitetura.py` — the suite fails on violations):**
  `domain` imports nothing internal; `app` may import only `domain`;
  `infra` may import only `domain`; `ui` may import everything; `gi`
  (GTK) is only allowed inside `ui/`. New code goes in the innermost
  layer that can hold it.
  - **`domain/`** — pure types and rules, zero I/O: `note.py` (`DbNote`,
    `preview`), `state.py` (`State`, `ToggleAction`, tray icon/tooltip
    mapping + `Pulsador` — AppIndicator can't animate, so pulse alternates
    strong/dim variants), `periodo.py` (`periodo_desde` for the UI period
    filter) and `errors.py` (user-facing exceptions:
    `TranscriptionError`, `PlayerError`, `RecorderError`,
    `MigrationError`).
  - **`app/core.py`** — the use case: `DaemonCore` state machine (idle →
    recording → transcribing), fully synchronous, no GTK/D-Bus/threads;
    I/O ports (recorder/transcriber/notes/notifier) are injected.
    `toggle()` returns a `ToggleAction` telling the glue what to do next;
    `on_state_change` is the observer hook for the tray icon (may fire
    from the transcription worker thread — the glue wraps it in
    `GLib.idle_add`).
  - **`infra/`** — injectable I/O adapters: `recorder.py` (arecord),
    `transcriber.py` (whisper.cpp), `player.py` (Piper + paplay),
    `notify.py` (notify-send, `--app-name=Tomenotas`, click action),
    `shortcuts.py` (gsettings keybindings + conflict detection),
    `config.py` (`~/.config/tomenotas/config.json` + `TOMENOTAS_*` env),
    `logs.py` (rotating `daemon.log`), and `notes_db.py` +
    `migrations.py` — SQLite storage, the source of truth
    (`~/.local/share/tomenotas/notes.db`): FTS5 search with combinable
    filters and bm25 ranking, tags (CRUD incl. rename-merge), favorites.
    **Every schema change MUST be a new immutable `Migration` appended to
    `MIGRATIONS`** (never edit a published one) plus a test that migrates
    a *populated* older-version db and proves nothing is lost; version in
    `PRAGMA user_version`, one transaction per migration, file backup
    (`notes.db.bak-v<n>-<ts>`, last 3 kept) before upgrading. Each note
    keeps a `.txt` mirror in `notes/` for the legacy scripts, and foreign
    `.txt` files are imported at startup. A `MigrationError` at startup
    aborts the daemon with a notification, leaving the db untouched.
  - **`ui/`** — the glue layer (`daemon.py`, `window.py`,
    `settings_page.py`): GTK main loop, `AyatanaAppIndicator3` tray with
    "Abrir"/"Configurações"/"Sair", D-Bus name `com.tomenotas.Daemon` at
    `/com/tomenotas/Daemon` with
    `ToggleRecording()`/`ShowWindow()`/`ShowSettings()`/`Ping()`,
    threading for slow work (transcription, TTS synthesis), and the
    single main window with a `Gtk.StackSidebar` of three pages: Notas
    (FTS search re-querying the db, tag dropdown, favorite star, tag
    popover, period combo, play/pause, delete), Tags (CRUD with merge
    warning) and Configurações (`SettingsPage`, embedded — the window
    forwards key-press-event to its `handle_key`). Window close hides —
    the daemon stays in the tray. Deliberately thin and dumb: only builds
    widgets and delegates to the tested core. The whole layer is
    **excluded from coverage** (pyproject omit) — keep new behavior out
    of it. Recording state lives in-process — no `recording.pid`.
  Entry point: `tomenotas-daemon = tomenotas.ui.daemon:main` (console
  script; `install.sh` installs the package into a
  `--system-site-packages` venv at `~/.local/share/tomenotas/venv` and
  symlinks `~/bin/tomenotas-daemon`).
- **`tomenotas-hotkey-record`** (Super+R) / **`tomenotas-hotkey-window`**
  (Super+L) — thin bash D-Bus clients, the targets of the record/list
  keybindings. They just call `ToggleRecording()` / `ShowWindow()` via
  `gdbus`; if the daemon isn't running the call fails silently, so the
  shortcuts are dead unless the app is open (this is the intended behavior —
  don't "fix" it by falling back to the legacy scripts).
- **`tomenotas-open`** — target of the applications-menu launcher
  (`~/.local/share/applications/tomenotas.desktop`, written by
  `install.sh`). Unlike the hotkey clients, it *does* start the daemon if
  it isn't running (waits for the D-Bus name, up to ~5s) before calling
  `ShowWindow()` — opening the app is an explicit user request.
- **`gravar.sh`** / **`listar.sh`** — legacy standalone flows (arecord +
  `recording.pid` + whisper.cpp; zenity list writing `current_note`). Still
  installed for manual use, but no longer bound to keys.
- **`ler.sh`** (Super+T) — reads `current_note` (falling back to the most recent note
  if none is selected or the pointer is stale) and pipes its text through Piper TTS,
  playing the resulting audio with `paplay`.
- **`install.sh`** — installs apt dependencies (including `python3-gi` and
  `gir1.2-ayatanaappindicator3-0.1` for the daemon), clones/builds whisper.cpp and
  downloads a model, downloads the Piper binary + `pt_BR-faber-medium` voice, copies
  the scripts + daemon + hotkey client to `~/bin`, rewrites the binary/model paths
  in the copies via `sed`, and registers the three keybindings via `gsettings`
  (record → `tomenotas-hotkey-record`, not `gravar.sh`).
- **`uninstall.sh`** — reverses `install.sh`; by default keeps notes and the
  whisper.cpp/Piper installs (large downloads), removable via `--purge-notes` /
  `--purge-deps`.

Key invariant: the **bash scripts** in this repo (`gravar.sh`, `listar.sh`,
`ler.sh`) are **templates**. `install.sh` copies them to `~/bin/` and then patches
the `WHISPER_BIN`/`WHISPER_MODEL`/`PIPER_BIN`/`PIPER_MODEL` variables in the
*copies* with `sed`. When editing these scripts, preserve the exact variable
assignment format the installer's `sed` patterns expect (e.g. `^WHISPER_BIN=.*`),
or update the corresponding `sed` line in `install.sh` to match. The Python
daemon is **not** sed-patched — it reads `~/.config/tomenotas/config.json`
(written by `install.sh`) / `TOMENOTAS_*` env vars via `config.py`.

State/data layout (see README "Onde ficam os arquivos" for the authoritative list):
```
~/bin/{gravar,listar,ler}.sh
~/bin/tomenotas-daemon          # symlink into the venv below
~/bin/tomenotas-hotkey-record   # D-Bus client bound to Super+R
~/bin/tomenotas-hotkey-window   # D-Bus client bound to Super+L
~/bin/tomenotas-open            # app-menu launcher (starts daemon if needed)
~/.config/tomenotas/config.json # whisper paths, read by the daemon
~/.local/share/tomenotas/
├── venv/              # daemon package install (system-site-packages)
├── notes.db           # SQLite source of truth (+ notes.db.bak-* backups)
├── notes/*.txt        # read-only .txt mirror of the db (legacy scripts)
├── current_note       # path to the note selected in listar.sh
└── recording.pid       # only written by the legacy gravar.sh, not the daemon
~/whisper.cpp/          # whisper.cpp build + model
~/piper/                 # Piper binary + voice model
```

## Testing changes

**Python (the daemon): TDD is the workflow.** Any change to `src/tomenotas/`
(except `ui/`) starts with a failing test in `tests/`. Run the suite with:
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```
The coverage gate (`--cov-fail-under=90`, configured in pyproject.toml) makes
`pytest` fail below 90% on the core; the `ui/` layer (GTK/D-Bus glue) is
omitted from the metric on purpose — do not "fix" coverage by adding
mock-heavy tests for it, and do not grow logic inside it: put logic in
`domain`/`app`/`infra` (tested) and keep the glue delegating. The layer
dependency rule is enforced by `tests/test_arquitetura.py`.

**Bash scripts + the glue layer:** no automated harness. To validate, install
and exercise the real keyboard-driven flow:
```bash
./install.sh --skip-whisper --skip-piper   # if whisper.cpp/Piper already installed
```
Then start the daemon (`~/bin/tomenotas-daemon &`), manually trigger Super+R
(record/stop), Super+L (list), Super+T (read), and check
`~/.local/share/tomenotas/notes/` and `notify-send` output. Also verify the Fase 1
invariant: quit the daemon via the tray menu and confirm Super+R does nothing.
When editing a single script without reinstalling, run it directly from `~/bin/`
(the installed, path-patched copy), not from this repo checkout, since the checkout
copies have placeholder paths.

## Roadmap context

See `ROADMAP.md` for the v2 plan. All fases (0–5) are done: bash scripts;
daemon skeleton with tray + D-Bus; GTK notes window; settings window for
hotkeys; state-reflecting tray icons with pulse; autostart + structured
logging + specific error messages. Remaining ideas (SQLite storage, note
export/editing, multiple voices, `.deb` packaging, GlobalShortcuts portal)
live in the ROADMAP backlog — none of those exist yet.
