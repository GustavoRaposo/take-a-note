# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Tomenotas — a personal voice-notes assistant for Ubuntu/GNOME, implemented as a
Python package (`src/tomenotas/`: daemon with tray icon, D-Bus, recording,
notes UI) plus thin bash D-Bus clients for the hotkeys, and an
installer/uninstaller. The Python side is a proper package (pyproject.toml,
pytest, 90% coverage gate on the core). **Language convention:** the `.py`
code is developed in English — identifiers, docstrings, comments, test names
and log messages. User-visible strings stay in Portuguese: `notify-send`
titles/bodies, window labels and dialogs, and error messages shown to the
user (the `domain/errors.py` exception messages are displayed as-is, so
they are Portuguese too). Keep new code consistent with that. Exception:
the action ids `gravar`/`listar`/`ler` and their `tomenotas-<id>` gsettings
paths are persisted on users' systems — never rename them.

There is no cloud/API/LLM involved anywhere in this project by design (see README):
speech-to-text and text-to-speech both run fully offline via local binaries. Don't
introduce network calls to AI services when extending this project.

## Architecture

Everything goes through the daemon — the keybindings are thin D-Bus
clients that die silently when it isn't running:

- **`src/tomenotas/`** — the daemon package, organized in lightweight
  clean-architecture layers. **Dependency rule (enforced by
  `tests/test_architecture.py` — the suite fails on violations):**
  `domain` imports nothing internal; `app` may import only `domain`;
  `infra` may import only `domain`; `ui` may import everything; `gi`
  (GTK) is only allowed inside `ui/`. New code goes in the innermost
  layer that can hold it.
  - **`domain/`** — pure types and rules, zero I/O: `note.py` (`DbNote`,
    `preview`), `state.py` (`State`, `ToggleAction`, tray icon/tooltip
    mapping + `Pulser` — AppIndicator can't animate, so pulse alternates
    strong/dim variants), `period.py` (`period_since` for the UI period
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
    `voices.py` (`VoiceManager` — lists installed Piper `.onnx` voices and
    switches the active one: applies to the Player and persists
    `piper_model` in config.json; `download_default` fetches the pt_BR
    voice pair on first run),
    `downloads.py` (`Downloader` — streaming download with progress
    callback and atomic `.part`→rename; `ModelManager` — whisper model
    catalog (tiny…large-v3), download/switch applied to the Transcriber
    and persisted in config.json. **Models are downloaded by the app on
    first run, not by install.sh** — the daemon opens Configurações and
    `DaemonCore.toggle()` refuses to record while
    `transcriber.is_ready()` is False),
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
    keeps a `.txt` mirror in `notes/` (plain-text export), and foreign
    `.txt` files are imported at startup. A `MigrationError` at startup
    aborts the daemon with a notification, leaving the db untouched.
  - **`ui/`** — the glue layer (`daemon.py`, `window.py`,
    `settings_page.py`): GTK main loop, `AyatanaAppIndicator3` tray with
    "Abrir"/"Configurações"/"Sair", D-Bus name `com.tomenotas.Daemon` at
    `/com/tomenotas/Daemon` with
    `ToggleRecording()`/`ReadCurrentNote()`/`ShowWindow()`/`ShowSettings()`/`Ping()`,
    threading for slow work (transcription, TTS synthesis), and the
    single main window with a `Gtk.StackSidebar` of three pages: Notas
    (FTS search re-querying the db, tag dropdown, favorite star, tag
    popover, period combo, play/pause, delete; activating a row slides
    to an internal detail view — editable TextView backed by
    `store.update_text`, star/tags/play/delete actions, Salvar returns
    to the list), Tags (CRUD with merge warning) and Configurações
    (`SettingsPage`, embedded — the window forwards key-press-event to
    its `handle_key`; sections: Atalhos, Voz (Piper voice dropdown backed
    by `VoiceManager` + first-run default-voice download) and Modelo de
    transcrição (whisper size download/switch backed by `ModelManager`,
    with progress bars). Window close hides —
    the daemon stays in the tray. Deliberately thin and dumb: only builds
    widgets and delegates to the tested core. The whole layer is
    **excluded from coverage** (pyproject omit) — keep new behavior out
    of it. Recording state lives in-process — no `recording.pid`.
  Entry point: `tomenotas-daemon = tomenotas.ui.daemon:main` (console
  script; `install.sh` installs the package into a
  `--system-site-packages` venv at `~/.local/share/tomenotas/venv` and
  symlinks `~/tomenotas/tomenotas-daemon`).
- **`tomenotas-hotkey-record`** (Super+R) / **`tomenotas-hotkey-window`**
  (Super+Y) / **`tomenotas-hotkey-read`** (Super+T) — thin bash D-Bus
  clients, the targets of the keybindings. They just call
  `ToggleRecording()` / `ShowWindow()` / `ReadCurrentNote()` via `gdbus`;
  if the daemon isn't running the call fails silently, so the shortcuts
  are dead unless the app is open (this is the intended behavior — don't
  "fix" it with local fallbacks).
- **`tomenotas-open`** — target of the applications-menu launcher
  (`~/.local/share/applications/tomenotas.desktop`, written by
  `install.sh`). Unlike the hotkey clients, it *does* start the daemon if
  it isn't running (waits for the D-Bus name, up to ~5s) before calling
  `ShowWindow()` — opening the app is an explicit user request.
- **`install.sh`** — installs apt dependencies (including `python3-gi` and
  `gir1.2-ayatanaappindicator3-0.1` for the daemon), clones/builds whisper.cpp and
  downloads the Piper binary (**models/voices are NOT downloaded here** —
  the app offers them on first run; old installs' models keep working via
  config.json), copies the D-Bus clients to `~/tomenotas` (deleting retired legacy scripts —
  `gravar.sh`/`listar.sh`/`ler.sh` — from old installs), installs the
  daemon venv, and registers the three keybindings via `gsettings`.
- **`uninstall.sh`** — reverses `install.sh`; by default keeps notes and the
  whisper.cpp/Piper installs (large downloads), removable via `--purge-notes` /
  `--purge-deps`.
- **`packaging/build-deb.sh`** — builds `dist/tomenotas_<ver>_amd64.deb`
  with plain `dpkg-deb` (no debhelper needed): vendors a **static**
  `whisper-cli` build and the Piper release tarball into
  `/usr/lib/tomenotas/`, copies the pure-Python package into
  `dist-packages` (no venv), clients into `/usr/bin/`, icons into
  `/usr/share/tomenotas/icons/`, desktop launcher + `/etc/xdg/autostart`.
  Per-user setup the package cannot do happens on daemon startup:
  `ShortcutManager.ensure_defaults()` registers missing keybindings
  (never overriding existing ones) and models come from the Fase A
  first-run flow. `Config` prefers the system paths
  (`SYSTEM_LIB_DIR`/`SYSTEM_BIN_DIR`/`SYSTEM_SHARE_DIR`) when they
  exist; explicit config.json/env always wins. Don't mix the two install
  routes — run `uninstall.sh` before installing the .deb.

All legacy bash flows are retired — nothing is sed-patched anymore. All
runtime paths come from `~/.config/tomenotas/config.json` (written by
`install.sh`) / `TOMENOTAS_*` env vars via `infra/config.py`. The `.txt`
mirror in `notes/` is kept as a plain-text export of the db (and foreign
`.txt` files are still imported at startup).

State/data layout (see README "Onde ficam os arquivos" for the authoritative list):
```
~/tomenotas/tomenotas-daemon          # symlink into the venv below
~/tomenotas/tomenotas-hotkey-record   # D-Bus client bound to Super+R
~/tomenotas/tomenotas-hotkey-window   # D-Bus client bound to Super+Y
~/tomenotas/tomenotas-hotkey-read     # D-Bus client bound to Super+T
~/tomenotas/tomenotas-open            # app-menu launcher (starts daemon if needed)
~/.config/tomenotas/config.json # whisper paths, read by the daemon
~/.local/share/tomenotas/
├── venv/              # daemon package install (system-site-packages)
├── notes.db           # SQLite source of truth (+ notes.db.bak-* backups)
└── notes/*.txt        # read-only .txt mirror (plain-text export)
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
dependency rule is enforced by `tests/test_architecture.py`.

**Bash scripts + the glue layer:** no automated harness. To validate, install
and exercise the real keyboard-driven flow:
```bash
./install.sh --skip-whisper --skip-piper   # if whisper.cpp/Piper already installed
```
Then start the daemon (`~/tomenotas/tomenotas-daemon &`), manually trigger Super+R
(record/stop), Super+Y (list), Super+T (read), and check
`~/.local/share/tomenotas/notes/` and `notify-send` output. Also verify the Fase 1
invariant: quit the daemon via the tray menu and confirm Super+R does nothing.
When editing a single script without reinstalling, run it directly from `~/tomenotas/`
(the installed, path-patched copy), not from this repo checkout, since the checkout
copies have placeholder paths.

## Roadmap context

See `ROADMAP.md` for the v2 plan. All fases (0–5) are done: bash scripts;
daemon skeleton with tray + D-Bus; GTK notes window; settings window for
hotkeys; state-reflecting tray icons with pulse; autostart + structured
logging + specific error messages. Remaining ideas (SQLite storage, note
export/editing, multiple voices, `.deb` packaging, GlobalShortcuts portal)
live in the ROADMAP backlog — none of those exist yet.
