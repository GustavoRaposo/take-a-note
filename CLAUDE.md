# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Tomenotas — a personal voice-notes assistant for Ubuntu/GNOME, implemented as a
Python daemon (tray icon + D-Bus, handles recording) plus bash scripts for
listing/reading notes, and an installer/uninstaller. There is no build system,
package manager, or test suite: this is glue code around system tools and GNOME
keyboard shortcuts. All comments, `notify-send` messages, and user-facing
strings are in Portuguese — keep new code consistent with that.

There is no cloud/API/LLM involved anywhere in this project by design (see README):
speech-to-text and text-to-speech both run fully offline via local binaries. Don't
introduce network calls to AI services when extending this project.

## Architecture

Recording goes through the daemon (Fase 1 of ROADMAP.md); listing/reading are
still standalone scripts communicating through shared files under
`~/.local/share/tomenotas/`:

- **`tomenotas-daemon`** — long-running Python process (PyGObject/GTK3 main
  loop). Shows a tray icon via `AyatanaAppIndicator3` (menu: "Abrir" opens the
  notes folder — placeholder until the Fase 2 GTK window — and "Sair" quits),
  and owns the D-Bus name `com.tomenotas.Daemon` (object
  `/com/tomenotas/Daemon`) with methods `ToggleRecording()` and `Ping()`.
  Recording state (idle/recording/transcribing) lives in-process — no
  `recording.pid`. `ToggleRecording()` starts/stops `arecord` and transcribes
  with whisper.cpp in a worker thread (results marshalled back via
  `GLib.idle_add`).
- **`tomenotas-hotkey-record`** (Super+R) — thin bash D-Bus client, the target
  of the record keybinding. Just calls `ToggleRecording()` via `gdbus`; if the
  daemon isn't running the call fails silently, so the shortcut is dead unless
  the app is open (this is the intended behavior — don't "fix" it by falling
  back to `gravar.sh`).
- **`gravar.sh`** — legacy standalone recorder (arecord + `recording.pid` +
  whisper.cpp). Still installed for manual use, but no longer bound to a key.
- **`listar.sh`** (Super+L) — lists all notes (newest first) via `zenity --list` and
  writes the chosen note's path into `current_note`, the pointer file `ler.sh` reads.
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

Key invariant: the scripts in this repo (`gravar.sh`, `listar.sh`, `ler.sh`,
`tomenotas-daemon`) are **templates**. `install.sh` copies them to `~/bin/` and then
patches the `WHISPER_BIN`/`WHISPER_MODEL`/`PIPER_BIN`/`PIPER_MODEL` variables in the
*copies* with `sed`. When editing these scripts, preserve the exact variable
assignment format the installer's `sed` patterns expect (bash: `^WHISPER_BIN=.*`;
the Python daemon: `^WHISPER_BIN = .*`, with spaces around `=`), or update the
corresponding `sed` line in `install.sh` to match.

State/data layout (see README "Onde ficam os arquivos" for the authoritative list):
```
~/bin/{gravar,listar,ler}.sh
~/bin/tomenotas-daemon          # daemon (tray + D-Bus + recording)
~/bin/tomenotas-hotkey-record   # D-Bus client bound to Super+R
~/.local/share/tomenotas/
├── notes/*.txt        # transcribed notes, one file per recording
├── current_note       # path to the note selected in listar.sh
└── recording.pid       # only written by the legacy gravar.sh, not the daemon
~/whisper.cpp/          # whisper.cpp build + model
~/piper/                 # Piper binary + voice model
```

## Testing changes

There's no test harness. To validate changes, install and exercise the real
keyboard-driven flow:
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

See `ROADMAP.md` for the v2 plan. Fase 0 (bash scripts) and Fase 1 (daemon
skeleton: tray icon, D-Bus service, recording migrated into the daemon) are done.
Next up is Fase 2 (GTK window for listing/playing notes) — the notes UI, hotkey
configuration UI (Fase 3), and state-reflecting tray icons (Fase 4) don't exist
yet.
