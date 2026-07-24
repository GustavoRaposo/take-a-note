#!/bin/bash
# training/setup.sh — prepara o ambiente de treino do wake word "Tomenotas".
# Roda UMA vez. Requer: GPU NVIDIA + driver, git, wget, ~5GB (deps/repos).
#
# O ecossistema de treino (torch etc.) NÃO tem wheels para Python 3.13+/3.14.
# Este script usa o `uv` para obter um Python 3.11 standalone (sem sudo) se
# você não tiver um 3.10-3.12 instalado. Também pula TensorFlow/tflite e
# speexdsp-ns: eles só servem para a conversão .tflite e a supressão de
# ruído, que NÃO usamos (nosso runtime é só-ONNX).
#
# Uso:  ./setup.sh [WORKDIR]   (padrão: ~/tomenotas-wakeword-training)
set -e

WORKDIR="${1:-$HOME/tomenotas-wakeword-training}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$WORKDIR"
cd "$WORKDIR"
echo "==> Diretório de trabalho: $WORKDIR"

# ---------------- Python 3.11 ----------------
export PATH="$HOME/.local/bin:$PATH"
PY=""
for cand in python3.11 python3.12 python3.10; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$(command -v "$cand")"; break; fi
done
if [ -z "$PY" ]; then
  echo "==> Nenhum Python 3.10-3.12 no sistema; obtendo 3.11 via uv..."
  if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
  uv python install 3.11
  PY="$(uv python find 3.11)"
fi
echo "==> Python de treino: $("$PY" --version) ($PY)"

echo "==> Criando venv (limpa)..."
rm -rf venv          # evita reaproveitar uma venv de outro Python (mistura)
"$PY" -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install -q --upgrade pip

echo "==> Instalando PyTorch (CUDA) — pode baixar ~2.5GB..."
pip install -q torch torchaudio

echo "==> Deps de treino (sem TensorFlow/tflite/speex — não usados p/ ONNX)..."
pip install -q torchinfo torchmetrics speechbrain audiomentations \
    torch-audiomentations datasets scipy scikit-learn numpy pyyaml tqdm \
    mutagen acoustics onnx onnxruntime requests piper-phonemize webrtcvad

echo "==> Clonando o openWakeWord (sem deps — já instaladas; evita TF/speex)..."
[ -d openwakeword ] || git clone --depth 1 https://github.com/dscripka/openwakeword
pip install -q -e ./openwakeword --no-deps

echo "==> Clonando o piper-sample-generator + baixando o modelo gerador..."
[ -d piper-sample-generator ] || git clone --depth 1 https://github.com/rhasspy/piper-sample-generator
mkdir -p piper-sample-generator/models
[ -f piper-sample-generator/models/en_US-libritts_r-medium.pt ] || \
  wget -q -O piper-sample-generator/models/en_US-libritts_r-medium.pt \
    "https://github.com/rhasspy/piper-sample-generator/releases/download/v2.0.0/en_US-libritts_r-medium.pt"

echo "==> Baixando os modelos base do openWakeWord (melspec + embedding)..."
mkdir -p openwakeword/openwakeword/resources/models
for m in melspectrogram.onnx embedding_model.onnx; do
  dst="openwakeword/openwakeword/resources/models/$m"
  [ -f "$dst" ] || wget -q -O "$dst" \
    "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/$m"
done

echo "==> Copiando o config do treino..."
cp "$HERE/tomenotas.yml" "$WORKDIR/tomenotas.yml"

echo ""
echo "==================================================="
echo " Setup pronto em $WORKDIR"
echo " Próximo passo:  ./download_data.sh \"$WORKDIR\""
echo " (baixa RIRs, ruído de fundo e ~2000h de features negativas — vários GB)"
echo "==================================================="
