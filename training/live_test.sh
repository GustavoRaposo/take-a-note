#!/bin/bash
# training/live_test.sh — teste ao vivo do wake word treinado.
# Usa a venv de treino (tem openwakeword+onnxruntime+numpy) e o CÓDIGO REAL
# do Tomenotas (WakeWordDetector), com debug ligado: fala "Tomenotas" e veja
# o score aparecer no terminal em tempo real. Ajuda a calibrar o threshold.
#
# Uso:  ./live_test.sh [WORKDIR]
set -e
WORKDIR="${1:-$HOME/tomenotas-wakeword-training}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
MODEL="$HOME/.local/share/tomenotas/models/tomenotas-ww.onnx"

if [ ! -f "$MODEL" ]; then
  echo "ERRO: modelo não encontrado em $MODEL — rode ./train.sh primeiro." >&2
  exit 1
fi
# shellcheck disable=SC1091
source "$WORKDIR/venv/bin/activate"

# o WakeWordDetector vive no pacote; o predict real vem de ui/wakeword_model.py
export PYTHONPATH="$REPO/src:$PYTHONPATH"

echo "=================================================================="
echo " Ouvindo do microfone. Fale 'Tomenotas' algumas vezes."
echo " Você verá 'wake score: X.XX' quando algo chegar perto, e"
echo " 'DETECTED' quando disparar. Ctrl+C para sair."
echo " (score no silêncio deve ficar ~0.00)"
echo "=================================================================="

python3 - "$MODEL" <<'PY'
import sys, time, logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
sys.path.insert(0, "src")
from tomenotas.ui.wakeword_model import load_predict
from tomenotas.infra.wakeword import WakeWordDetector

model_path = sys.argv[1]
predict = load_predict(model_path)
if predict is None:
    print("ERRO: não consegui carregar o modelo (deps ausentes?)."); sys.exit(1)

det = WakeWordDetector(predict=predict, threshold=0.5, debug=True)
det.start(lambda: print(">>> DISPAROU! (aqui o Tomenotas começaria a gravar)"))
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    det.stop()
    print("\nencerrado.")
PY
