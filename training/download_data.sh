#!/bin/bash
# training/download_data.sh — baixa os dados de treino (RIRs, ruído de
# fundo e features negativas pré-computadas). É a parte pesada: vários GB
# e pode demorar. Roda UMA vez, depois do setup.sh.
# Uso:  ./download_data.sh [WORKDIR]
set -e

WORKDIR="${1:-$HOME/tomenotas-wakeword-training}"
cd "$WORKDIR"
if [ ! -f venv/bin/activate ]; then
  echo "ERRO: venv não encontrada em $WORKDIR. Rode ./setup.sh primeiro." >&2
  exit 1
fi
# shellcheck disable=SC1091
source venv/bin/activate
if ! python3 -c "import numpy, datasets, scipy" 2>/dev/null; then
  echo "ERRO: a venv está incompleta (deps ausentes)." >&2
  echo "Rode ./setup.sh de novo (ele recria a venv limpa)." >&2
  exit 1
fi

echo "==> 1/4 RIRs (respostas de impulso — reverberação) do MIT..."
python3 - <<'PY'
import os, numpy as np, scipy.io.wavfile, datasets
from tqdm import tqdm
out = "./mit_rirs"; os.makedirs(out, exist_ok=True)
if not os.listdir(out):
    ds = datasets.load_dataset("davidscripka/MIT_environmental_impulse_responses",
                               split="train", streaming=True)
    for row in tqdm(ds):
        name = row['audio']['path'].split('/')[-1]
        scipy.io.wavfile.write(os.path.join(out, name), 16000,
                               (row['audio']['array']*32767).astype(np.int16))
PY

echo "==> 2/4 Ruído de fundo (uma parte do AudioSet, convertido p/ 16kHz)..."
mkdir -p audioset background_clips
if [ ! -f audioset/bal_train09.tar ]; then
  wget -q -O audioset/bal_train09.tar \
    "https://huggingface.co/datasets/agkphysics/AudioSet/resolve/main/data/bal_train09.tar"
fi
if [ -z "$(ls -A background_clips 2>/dev/null)" ]; then
  tar -xf audioset/bal_train09.tar -C audioset
  # converte os .flac/.wav extraídos para wav 16kHz mono em background_clips
  find audioset -name "*.flac" -o -name "*.wav" | head -2000 | while read -r f; do
    ffmpeg -nostdin -loglevel error -y -i "$f" -ar 16000 -ac 1 \
      "background_clips/$(basename "${f%.*}").wav" || true
  done
fi

echo "==> 3/4 Features negativas de treino (~2000h, ACAV100M) — arquivo grande..."
[ -f openwakeword_features_ACAV100M_2000_hrs_16bit.npy ] || \
  wget -q "https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/openwakeword_features_ACAV100M_2000_hrs_16bit.npy"

echo "==> 4/4 Features de validação (falsos positivos, ~11h)..."
[ -f validation_set_features.npy ] || \
  wget -q "https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/validation_set_features.npy"

echo ""
echo "==================================================="
echo " Dados prontos. Próximo passo:  ./train.sh \"$WORKDIR\""
echo "==================================================="
