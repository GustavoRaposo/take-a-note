# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Voz Notas — a personal voice-notes assistant for Ubuntu/GNOME, currently implemented
as three standalone bash scripts plus an installer/uninstaller. There is no build
system, package manager, or test suite: this is glue code around system tools and
GNOME keyboard shortcuts. All comments, `notify-send` messages, and user-facing
strings are in Portuguese — keep new code consistent with that.

There is no cloud/API/LLM involved anywhere in this project by design (see README):
speech-to-text and text-to-speech both run fully offline via local binaries. Don't
introduce network calls to AI services when extending this project.

## Architecture

Three scripts, each bound to a GNOME custom keybinding, communicating only through
shared files under `~/.local/share/voz-notas/` — there is no daemon or shared process
(this is intentional for v1; see ROADMAP.md for the planned v2 daemon architecture):

- **`gravar.sh`** (Super+R) — toggles recording. First press: starts `arecord` in the
  background and writes its PID to `recording.pid`. Second press: the presence of
  `recording.pid` is what signals "currently recording"; it kills the recording
  process, transcribes the resulting `.wav` with whisper.cpp, saves the result as
  `notes/<timestamp>.txt`, and deletes the temporary `.wav`. Only the recording PID
  file and the audio tmp file constitute "state" — there is no daemon.
- **`listar.sh`** (Super+L) — lists all notes (newest first) via `zenity --list` and
  writes the chosen note's path into `current_note`, the pointer file `ler.sh` reads.
- **`ler.sh`** (Super+T) — reads `current_note` (falling back to the most recent note
  if none is selected or the pointer is stale) and pipes its text through Piper TTS,
  playing the resulting audio with `paplay`.
- **`install.sh`** — installs apt dependencies, clones/builds whisper.cpp and
  downloads a model, downloads the Piper binary + `pt_BR-faber-medium` voice, copies
  the three scripts to `~/bin`, rewrites the binary/model paths in the copies via
  `sed`, and registers the three keybindings via `gsettings`.
- **`uninstall.sh`** — reverses `install.sh`; by default keeps notes and the
  whisper.cpp/Piper installs (large downloads), removable via `--purge-notes` /
  `--purge-deps`.

Key invariant: the scripts in this repo (`gravar.sh`, `listar.sh`, `ler.sh`) are
**templates**. `install.sh` copies them to `~/bin/` and then patches the
`WHISPER_BIN`/`WHISPER_MODEL`/`PIPER_BIN`/`PIPER_MODEL` variables in the *copies*
with `sed`. When editing these scripts, preserve the exact variable assignment
format the installer's `sed` patterns expect (e.g. `^WHISPER_BIN=.*`), or update the
corresponding `sed` line in `install.sh` to match.

State/data layout (see README "Onde ficam os arquivos" for the authoritative list):
```
~/bin/{gravar,listar,ler}.sh
~/.local/share/voz-notas/
├── notes/*.txt        # transcribed notes, one file per recording
├── current_note       # path to the note selected in listar.sh
└── recording.pid       # present only while a recording is in progress
~/whisper.cpp/          # whisper.cpp build + model
~/piper/                 # Piper binary + voice model
```

## Testing changes

There's no test harness. To validate changes, install and exercise the real
keyboard-driven flow:
```bash
./install.sh --skip-whisper --skip-piper   # if whisper.cpp/Piper already installed
```
Then manually trigger Super+R (record/stop), Super+L (list), Super+T (read), and
check `~/.local/share/voz-notas/notes/` and `notify-send` output. When editing a
single script without reinstalling, run it directly from `~/bin/` (the installed,
path-patched copy), not from this repo checkout, since the checkout copies have
placeholder paths.

## Roadmap context

See `ROADMAP.md` for the planned v2 rewrite: a long-running Python daemon with a
GTK/AyatanaAppIndicator3 tray icon, D-Bus IPC (`com.voznotas.Daemon`) so keyboard
shortcuts only work while the app is running, and a GTK UI for managing notes. The
current bash scripts are Fase 0 (done) in that plan — don't assume the daemon/D-Bus
pieces exist yet.
