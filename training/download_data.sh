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

echo "==> 2/4 Ruído de fundo (AudioSet 'balanced' via datasets → wav 16kHz)..."
# O AudioSet no HF hoje é parquet (não .tar): usa o datasets em streaming
# para extrair ~2000 clipes e reamostra 48kHz→16kHz mono.
python3 - <<'PY'
import os, numpy as np, soundfile as sf, datasets
from scipy.signal import resample_poly
from tqdm import tqdm
out = "background_clips"; os.makedirs(out, exist_ok=True)
TARGET = 2000
have = len([f for f in os.listdir(out) if f.endswith(".wav")])
if have >= TARGET:
    print(f"já há {have} clipes, pulando")
else:
    ds = datasets.load_dataset("agkphysics/AudioSet", "balanced",
                               split="train", streaming=True)
    n = have
    for row in tqdm(ds, total=TARGET - have):
        a = row["audio"]
        arr = np.asarray(a["array"], dtype=np.float32); sr = a["sampling_rate"]
        if sr != 16000:
            g = np.gcd(int(sr), 16000)
            arr = resample_poly(arr, 16000 // g, int(sr) // g)
        arr16 = np.clip(arr * 32767, -32768, 32767).astype(np.int16)
        sf.write(os.path.join(out, f"bg_{n}.wav"), arr16, 16000)
        n += 1
        if n >= TARGET:
            break
    print(f"{n} clipes de ruído prontos")
PY

echo "==> 3/4 Features negativas de treino (~2000h, ACAV100M) — arquivo GRANDE (vários GB)..."
[ -f openwakeword_features_ACAV100M_2000_hrs_16bit.npy ] || \
  wget --show-progress -q "https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/openwakeword_features_ACAV100M_2000_hrs_16bit.npy"

echo "==> 4/4 Features de validação (falsos positivos, ~11h)..."
[ -f validation_set_features.npy ] || \
  wget --show-progress -q "https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main/validation_set_features.npy"

echo ""
echo "==================================================="
echo " Dados prontos. Próximo passo:  ./train.sh \"$WORKDIR\""
echo "==================================================="
