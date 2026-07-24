"""Tests for tomenotas.infra.wakeword — the wake-word detector.

The firing logic (WakeWordGate: score stream → one fire per utterance,
with a threshold and a cooldown) is pure and tested directly. The
detector wires an injected audio capture and an injected `predict`
callable (the real one wraps the openWakeWord ONNX model) to the gate,
so it is tested without numpy/onnxruntime. Detection against the real
"Tomenotas" model is validated manually once the model is trained.
"""

from tomenotas.infra.wakeword import WakeWordDetector, WakeWordGate


# ---------------- gate (threshold + cooldown) ----------------

def test_fires_when_score_crosses_the_threshold():
    gate = WakeWordGate(threshold=0.5, cooldown=3)
    assert gate.feed(0.1) is False
    assert gate.feed(0.49) is False
    assert gate.feed(0.7) is True  # crossed


def test_one_utterance_fires_only_once_cooldown():
    # a real detection stays high for several frames — must fire once
    gate = WakeWordGate(threshold=0.5, cooldown=3)
    assert gate.feed(0.8) is True   # fire
    assert gate.feed(0.9) is False  # still high, but in cooldown
    assert gate.feed(0.9) is False
    assert gate.feed(0.9) is False
    # cooldown elapsed; a fresh rise fires again
    assert gate.feed(0.2) is False  # dropped below first
    assert gate.feed(0.8) is True


def test_cooldown_counts_frames_even_below_threshold():
    gate = WakeWordGate(threshold=0.5, cooldown=2)
    assert gate.feed(0.9) is True
    assert gate.feed(0.1) is False  # cooldown frame 1
    assert gate.feed(0.1) is False  # cooldown frame 2
    assert gate.feed(0.9) is True   # cooldown over → fires


# ---------------- detector (capture → predict → gate) ----------------

class FakeStdout:
    def __init__(self, frames):
        # each "frame" is raw bytes of one 1280-sample chunk
        self._chunks = list(frames)

    def read(self, _n):
        return self._chunks.pop(0) if self._chunks else b""


class FakeProc:
    def __init__(self, stdout):
        self.stdout = stdout
        self.terminated = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.terminated = True
        return 0

    def kill(self):
        self.terminated = True


FRAME = b"\x00\x00" * 1280  # 1280 int16 samples of silence


def test_detector_fires_on_detected_when_predict_crosses_threshold():
    # scripted scores per frame: high on frames 3-4 (one utterance)
    scores = iter([0.0, 0.2, 0.9, 0.9, 0.1])
    fired = []
    det = WakeWordDetector(predict=lambda _frame: next(scores),
                           threshold=0.5, cooldown=5)
    # drive the reader loop directly (no thread) for determinism
    det._pump(FakeStdout([FRAME] * 5), lambda: fired.append(True))
    # exactly one fire despite two consecutive high frames (cooldown)
    assert len(fired) == 1


def test_debug_logs_scores_above_the_floor(caplog):
    import logging
    scores = iter([0.05, 0.4, 0.9])
    det = WakeWordDetector(predict=lambda _f: next(scores), threshold=0.5,
                           debug=True)
    with caplog.at_level(logging.INFO, logger="tomenotas.wakeword"):
        det._pump(FakeStdout([FRAME, FRAME, FRAME]), lambda: None)
    logged = "\n".join(caplog.messages)
    assert "0.05" not in logged     # below the floor → not logged
    assert "wake score: 0.40" in logged
    assert "DETECTED" in logged     # the 0.9 fired


def test_no_score_logging_without_debug(caplog):
    import logging
    det = WakeWordDetector(predict=lambda _f: 0.4, threshold=0.5)  # debug off
    with caplog.at_level(logging.INFO, logger="tomenotas.wakeword"):
        det._pump(FakeStdout([FRAME, FRAME]), lambda: None)
    assert "wake score" not in "\n".join(caplog.messages)


def test_detector_skips_a_frame_whose_prediction_errors():
    scores = iter([0.0, 0.9])

    def flaky(_frame):
        v = next(scores)
        if v == 0.0:
            raise RuntimeError("frame ruim")
        return v

    fired = []
    det = WakeWordDetector(predict=flaky, threshold=0.5)
    det._pump(FakeStdout([FRAME, FRAME]), lambda: fired.append(True))
    assert fired == [True]  # the bad frame was skipped, the good one fired


def test_detector_start_uses_16k_mono_capture_and_stop_terminates(tmp_path):
    proc = FakeProc(FakeStdout([b""]))
    cmds = []
    det = WakeWordDetector(predict=lambda f: 0.0,
                           popen=lambda cmd, **kw: cmds.append(cmd) or proc)
    det.start(lambda: None)
    det.stop()

    (cmd,) = cmds
    assert "arecord" in cmd[0] or cmd[0].endswith("arecord")
    assert "16000" in cmd
    assert proc.terminated
    assert not det.is_running


def test_stop_without_start_does_nothing():
    det = WakeWordDetector(predict=lambda f: 0.0)
    det.stop()  # must not raise


def test_stop_kills_a_capture_that_wont_terminate():
    import subprocess as sp
    proc = FakeProc(FakeStdout([b""]))
    proc.killed = False

    def hang(timeout=None):
        raise sp.TimeoutExpired(cmd="arecord", timeout=timeout)

    def kill():
        proc.killed = True
        proc.terminated = True

    proc.wait = hang
    proc.kill = kill
    det = WakeWordDetector(predict=lambda f: 0.0,
                           popen=lambda cmd, **kw: proc)
    det.start(lambda: None)
    det.stop()
    assert proc.killed


def test_stop_kill_tolerates_capture_dying_first():
    import subprocess as sp
    proc = FakeProc(FakeStdout([b""]))

    def hang(timeout=None):
        raise sp.TimeoutExpired(cmd="arecord", timeout=timeout)

    def gone():
        raise ProcessLookupError

    proc.wait = hang   # → kill()
    proc.kill = gone   # kill races with the process exiting → swallowed
    det = WakeWordDetector(predict=lambda f: 0.0,
                           popen=lambda cmd, **kw: proc)
    det.start(lambda: None)
    det.stop()  # must not raise


def test_stop_tolerates_an_already_dead_capture():
    proc = FakeProc(FakeStdout([b""]))

    def gone():
        raise ProcessLookupError

    proc.terminate = gone
    det = WakeWordDetector(predict=lambda f: 0.0,
                           popen=lambda cmd, **kw: proc)
    det.start(lambda: None)
    det.stop()  # must not raise
