"""Live transcription via whisper-stream (the whisper.cpp streaming
example) — a preview shown while the user speaks.

Preview only: the saved note still comes from the normal high-quality
transcription on stop; this just feeds a live window with a small model
(tiny/base) that keeps up in real time. whisper-stream captures the mic
itself (SDL2), in parallel with arecord (which records the audio for the
final note).

The parser turns whisper-stream's stdout into growing text: it finalizes
a line on "\\n" and overwrites the current line on "\\r"/ANSI clear
(whisper-stream reprints the current window). Isolated and tested; the
subprocess is injectable. The real binary needs SDL2 + a mic — validated
manually.
"""

import logging
import re
import subprocess
import threading
from pathlib import Path

log = logging.getLogger("tomenotas.stream")

# clear-line codes (\033[2K, \033[K) reset the current line → treat as \r;
# any other escape sequence is just stripped
_CLEAR = re.compile(r"\033\[[0-9;]*K")
_ANSI = re.compile(r"\033\[[0-9;]*[A-Za-z]")
# a "### Transcription N START ..." marker: whisper-stream re-decodes the
# WHOLE current window each block, so a new block replaces the preview
# (accumulating across blocks would duplicate the text)
_BLOCK_START = re.compile(r"^\s*###.*START")
# lines that are not note content: any ### marker, "[Start speaking]"
_NOISE = re.compile(r"^\s*(###|\[Start speaking\])")
# leading "[00:00:00.000 --> 00:00:02.000]" timestamp on each content line
_TS = re.compile(
    r"^\s*\[\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}\]\s*"
)

# whisper-stream flags: "--step 0" = VAD sliding-window mode; "--length"
# is the max window it re-decodes each utterance — kept modest so the
# preview stays responsive (it shows the recent speech; the saved note is
# the full high-quality transcription on stop). Validated against the real
# binary: no "-nt", and the language must be explicit (default is English).
STREAM_ARGS = ["--step", "0", "--length", "10000", "-vth", "0.6"]


class StreamOutputParser:
    """Turns whisper-stream stdout into preview text. Each "###
    Transcription N START" block is a full re-decode of the current
    window, so a new block replaces the shown text; timestamp prefixes
    and status markers are stripped. "\\n" commits a line, "\\r"/ANSI-clear
    overwrites the current one."""

    def __init__(self):
        self._committed = []  # content lines of the current block
        self._current = ""

    def feed(self, chunk: str) -> str:
        chunk = _ANSI.sub("", _CLEAR.sub("\r", chunk))
        for ch in chunk:
            if ch == "\n":
                self._commit(self._current)
                self._current = ""
            elif ch == "\r":
                self._current = ""
            else:
                self._current += ch
        return self.text

    def _commit(self, line: str) -> None:
        if _BLOCK_START.match(line):
            self._committed = []  # new full-window decode → start fresh
            return
        content = self._content(line)
        if content:
            self._committed.append(content)

    @staticmethod
    def _content(line: str) -> str:
        if _NOISE.match(line):
            return ""
        return _TS.sub("", line).strip()

    @property
    def text(self) -> str:
        lines = list(self._committed)
        current = self._content(self._current)
        if current:
            lines.append(current)
        return "\n".join(lines)


class StreamTranscriber:
    def __init__(self, stream_bin, model_path, language: str = "pt",
                 popen=subprocess.Popen, threads: int = 4):
        self._bin = Path(stream_bin)
        self._model = Path(model_path)
        self._language = language
        self._popen = popen
        self._threads = threads
        self._proc = None
        self._thread = None

    def is_ready(self) -> bool:
        """False until both the binary and the small model exist."""
        return self._bin.exists() and self._model.exists()

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, on_text) -> None:
        """Launches whisper-stream and pumps its output to on_text(text)
        (called from a reader thread — the glue hops to the main loop)."""
        cmd = [str(self._bin), "-m", str(self._model),
               "-l", self._language, "-t", str(self._threads),
               *STREAM_ARGS]
        self._proc = self._popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True,
        )
        self._thread = threading.Thread(
            target=self._pump, args=(self._proc.stdout, on_text), daemon=True
        )
        self._thread.start()

    def _pump(self, stdout, on_text) -> None:
        parser = StreamOutputParser()
        while True:
            chunk = stdout.read(64)
            if not chunk:
                break
            on_text(parser.feed(chunk))

    def stop(self, timeout: float = 3) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()  # closes stdout → the pump loop ends
                proc.wait(timeout=timeout)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
