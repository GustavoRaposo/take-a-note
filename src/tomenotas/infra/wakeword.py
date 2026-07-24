"""Wake-word detection: always-on listening that triggers recording.

When enabled, the daemon captures the mic continuously (16 kHz mono) and
feeds 80 ms frames to an ONNX wake-word model (openWakeWord). When the
score crosses the threshold, `on_detected` fires — the glue routes it to
the same handler as Super+R. 100% offline: audio never leaves the
machine.

WakeWordGate (the firing logic) is pure and tested. WakeWordDetector
takes an injected `predict(frame_bytes) -> float` (the real one wraps the
ONNX model — numpy/onnxruntime live there, not here) and an injectable
capture, so it is testable without those deps.
"""

import logging
import subprocess
import threading

log = logging.getLogger("tomenotas.wakeword")

# openWakeWord expects 16 kHz mono int16 frames of 1280 samples (80 ms)
FRAME_SAMPLES = 1280
FRAME_BYTES = FRAME_SAMPLES * 2
# a real detection stays high for several frames; a ~1.2 s cooldown means
# one utterance = one trigger (1200 ms / 80 ms ≈ 15 frames)
DEFAULT_COOLDOWN = 15

CAPTURE_CMD = [
    "arecord", "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw",
]


class WakeWordGate:
    """Turns a stream of per-frame scores into fire decisions: fires when
    the score crosses the threshold, then stays quiet for `cooldown`
    frames so one utterance triggers only once."""

    def __init__(self, threshold: float = 0.5, cooldown: int = DEFAULT_COOLDOWN):
        self._threshold = threshold
        self._cooldown = cooldown
        self._quiet = 0  # frames remaining in cooldown

    def feed(self, score: float) -> bool:
        if self._quiet > 0:
            self._quiet -= 1
            return False
        if score >= self._threshold:
            self._quiet = self._cooldown
            return True
        return False


# in debug mode, log any score at/above this so you can watch it react
# and tune the threshold ("quase disparou: 0.45") without log spam
DEBUG_SCORE_FLOOR = 0.3


class WakeWordDetector:
    def __init__(self, predict, threshold: float = 0.5,
                 cooldown: int = DEFAULT_COOLDOWN,
                 popen=subprocess.Popen, capture_cmd=None,
                 debug: bool = False):
        self._predict = predict  # (frame_bytes) -> float
        self._threshold = threshold
        self._gate = WakeWordGate(threshold, cooldown)
        self._popen = popen
        self._capture_cmd = capture_cmd or CAPTURE_CMD
        self._debug = debug
        self._proc = None
        self._thread = None

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, on_detected) -> None:
        """Starts capturing and detecting. on_detected() fires from the
        reader thread — the glue hops to the main loop."""
        log.info("wake word: listening (threshold=%.2f%s)", self._threshold,
                 ", debug" if self._debug else "")
        self._proc = self._popen(
            self._capture_cmd, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._thread = threading.Thread(
            target=self._pump, args=(self._proc.stdout, on_detected),
            daemon=True,
        )
        self._thread.start()

    def _pump(self, stdout, on_detected) -> None:
        while True:
            frame = _read_exact(stdout, FRAME_BYTES)
            if frame is None:
                break
            try:
                score = self._predict(frame)
            except Exception as error:  # a bad frame must not kill listening
                log.warning("wake-word predict failed: %s", error)
                continue
            if self._debug and score >= DEBUG_SCORE_FLOOR:
                log.info("wake score: %.2f", score)
            if self._gate.feed(score):
                log.info("wake word DETECTED (score=%.2f)", score)
                on_detected()

    def stop(self, timeout: float = 3) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=timeout)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None


def _read_exact(stdout, n: int):
    """Reads exactly n bytes (a whole frame), or None at EOF."""
    buf = b""
    while len(buf) < n:
        chunk = stdout.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf
