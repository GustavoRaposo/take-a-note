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

# dep de sistema: o gerador de amostras usa espeak-phonemizer (libespeak-ng)
if ! ldconfig -p 2>/dev/null | grep -q libespeak-ng; then
  echo "AVISO: 'espeak-ng' não parece instalado (necessário para gerar as" >&2
  echo "amostras). Instale com:  sudo apt install espeak-ng" >&2
  echo "Continuando o setup — mas o train.sh vai falhar sem ele." >&2
fi

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
# datasets<3: as versões novas (4.x) exigem torchcodec para ler áudio; o
# pipeline usa a decodificação antiga via soundfile. datasets só é usado
# no nosso download de dados (o train.py não o importa), então é seguro.
pip install -q torchinfo torchmetrics speechbrain audiomentations \
    torch-audiomentations "datasets<3" soundfile scipy scikit-learn numpy \
    pyyaml tqdm mutagen acoustics onnx onnxruntime requests \
    pronouncing espeak-phonemizer webrtcvad

echo "==> Clonando o openWakeWord (sem deps — já instaladas; evita TF/speex)..."
[ -d openwakeword ] || git clone --depth 1 https://github.com/dscripka/openwakeword
pip install -q -e ./openwakeword --no-deps

echo "==> Clonando o piper-sample-generator (fork dscripka, o que o treino usa)..."
# O train.py faz `from generate_samples import generate_samples` — arquivo
# que só existe no fork do dscripka (o do rhasspy tem outra interface).
if [ -d piper-sample-generator ] && \
   ! grep -q "def generate_samples" piper-sample-generator/generate_samples.py 2>/dev/null; then
  echo "   (removendo clone antigo do fork errado)"; rm -rf piper-sample-generator
fi
[ -d piper-sample-generator ] || \
  git clone --depth 1 https://github.com/dscripka/piper-sample-generator
# o .json de config já vem no fork; falta baixar o modelo .pt (255MB)
[ -f piper-sample-generator/models/en-us-libritts-high.pt ] || \
  wget -q -O piper-sample-generator/models/en-us-libritts-high.pt \
    "https://github.com/rhasspy/piper-sample-generator/releases/download/v1.0.0/en-us-libritts-high.pt"

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
