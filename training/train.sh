#!/bin/bash
# training/train.sh — gera amostras, aumenta, treina e exporta o modelo
# "Tomenotas". Usa a GPU. Roda depois de setup.sh + download_data.sh.
# Ao final, instala o .onnx onde o Tomenotas espera.
# Uso:  ./train.sh [WORKDIR]
set -e

WORKDIR="${1:-$HOME/tomenotas-wakeword-training}"
cd "$WORKDIR"
if [ ! -f venv/bin/activate ]; then
  echo "ERRO: venv não encontrada em $WORKDIR. Rode ./setup.sh primeiro." >&2
  exit 1
fi
# shellcheck disable=SC1091
source venv/bin/activate
if ! python3 -c "import torch, openwakeword" 2>/dev/null; then
  echo "ERRO: a venv está incompleta (torch/openwakeword ausentes)." >&2
  echo "Rode ./setup.sh de novo." >&2
  exit 1
fi

# PyTorch 2.6 mudou o default de torch.load para weights_only=True, o que
# rejeita os checkpoints de modelo completo que essas ferramentas carregam
# (piper-sample-generator, deep-phonemizer, speechbrain). Um patch global
# restaura o comportamento antigo para todo o processo — confiamos nas
# fontes dos modelos. Aplicado via sitecustomize no PYTHONPATH.
mkdir -p .torchpatch
cat > .torchpatch/sitecustomize.py <<'PY'
try:
    import functools, torch
    if not getattr(torch.load, "_ww_patched", False):
        _orig = torch.load
        @functools.wraps(_orig)
        def _load(*args, **kwargs):
            kwargs.setdefault("weights_only", False)
            return _orig(*args, **kwargs)
        _load._ww_patched = True
        torch.load = _load
except Exception:
    pass
PY
export PYTHONPATH="$PWD/.torchpatch:$PYTHONPATH"

TRAIN="python3 openwakeword/openwakeword/train.py --training_config tomenotas.yml"

echo "==> 1/3 Gerando amostras positivas com o Piper (GPU)... (demorado)"
$TRAIN --generate_clips

echo "==> 2/3 Augmentation + cálculo de features..."
# O --augment_clips só recomputa se positive_features_train.npy NÃO existe
# (checa só esse 1 dos 4 arquivos). Se um run anterior morreu no meio, ele
# pode ter gravado só esse e, no re-run, pular tudo — deixando o treino sem
# os _test.npy/negativos. Se o conjunto de 4 estiver incompleto, apagamos os
# parciais para forçar uma recomputação limpa.
FEAT_DIR="tomenotas_model/tomenotas"
missing=0
for f in positive_features_train positive_features_test \
         negative_features_train negative_features_test; do
  [ -f "$FEAT_DIR/$f.npy" ] || missing=1
done
if [ "$missing" = 1 ]; then
  rm -f "$FEAT_DIR"/positive_features_*.npy "$FEAT_DIR"/negative_features_*.npy
fi
$TRAIN --augment_clips

echo "==> 3/3 Treinando o classificador e exportando ONNX/TFLite..."
$TRAIN --train_model

# localiza o .onnx gerado (output_dir: ./tomenotas_model)
ONNX="$(find tomenotas_model -name "tomenotas.onnx" | head -1)"
if [ -z "$ONNX" ]; then
  echo "ERRO: não encontrei tomenotas.onnx em tomenotas_model/" >&2
  exit 1
fi

DEST="$HOME/.local/share/tomenotas/models/tomenotas-ww.onnx"
mkdir -p "$(dirname "$DEST")"
cp "$ONNX" "$DEST"

echo ""
echo "==================================================="
echo " Modelo treinado e instalado em:"
echo "   $DEST"
echo " Reinicie o Tomenotas e ative o wake word em Configurações."
echo "==================================================="
