"""Loads the openWakeWord ONNX model and returns a predict callable.

Kept in the glue layer (ui/) because it imports onnxruntime + numpy and
loads an ML model — not unit-testable like the rest of infra. The tested
WakeWordDetector (infra/wakeword.py) takes the callable this returns.
Degrades gracefully: if the deps or the model are missing, returns None
and the daemon simply never starts listening.

Runtime deps are only numpy + onnxruntime (openWakeWord's inference path
needs nothing more); packaged separately (see the .deb build).
"""

import logging
from pathlib import Path

log = logging.getLogger("tomenotas.wakeword")


def load_predict(model_path: Path):
    """Returns predict(frame_bytes: bytes) -> float, or None when the
    wake word can't run (deps or model absent, or load failure)."""
    try:
        import numpy as np
        from openwakeword.model import Model
    except ImportError:
        log.info("wake word: onnxruntime/openwakeword not available")
        return None

    model_path = Path(model_path)
    if not model_path.is_file():
        log.info("wake word: model not found at %s", model_path)
        return None

    try:
        # onnx-only runtime: the base melspec/embedding models must also be
        # ONNX (the default, "tflite", would need a TF Lite runtime we ship
        # nothing for).
        model = Model(wakeword_models=[str(model_path)],
                      inference_framework="onnx")
    except Exception as error:  # bad/incompatible model file
        log.warning("wake word: failed to load model %s: %s",
                    model_path, error)
        return None

    def predict(frame_bytes: bytes) -> float:
        frame = np.frombuffer(frame_bytes, dtype=np.int16)
        scores = model.predict(frame)  # {model_name: score}
        return float(max(scores.values())) if scores else 0.0

    log.info("wake word: model loaded (%s)", model_path.stem)
    return predict
