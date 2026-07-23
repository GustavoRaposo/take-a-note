#!/bin/bash
# install.sh
# Instala o sistema de notas de voz: dependências, whisper.cpp, Piper,
# copia os scripts para ~/bin e configura os 3 atalhos de teclado no GNOME.
#
# Uso:
#   ./install.sh                     -> instala tudo com valores padrão
#   ./install.sh --skip-whisper      -> não baixa/compila o whisper.cpp
#   ./install.sh --skip-piper        -> não baixa o Piper
#   ./install.sh --skip-shortcuts    -> não mexe nos atalhos do GNOME
#   ./install.sh --skip-apt          -> não roda apt (dependências já instaladas)
#   ./install.sh --model-size small  -> escolhe o tamanho do modelo whisper
#                                        (tiny, base, small, medium, large)

set -e

MODEL_SIZE="medium"
SKIP_WHISPER=0
SKIP_PIPER=0
SKIP_SHORTCUTS=0
SKIP_APT=0

for arg in "$@"; do
    case "$arg" in
        --skip-whisper) SKIP_WHISPER=1 ;;
        --skip-piper) SKIP_PIPER=1 ;;
        --skip-shortcuts) SKIP_SHORTCUTS=1 ;;
        --skip-apt) SKIP_APT=1 ;;
        --model-size=*) MODEL_SIZE="${arg#*=}" ;;
        --model-size) shift ;;
        *) ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/bin"
DATA_DIR="$HOME/.local/share/tomenotas"
NOTES_DIR="$DATA_DIR/notes"
WHISPER_DIR="$HOME/whisper.cpp"
PIPER_DIR="$HOME/piper"

if [ "$SKIP_APT" -eq 0 ]; then
    echo "==> Instalando dependências do sistema (apt)..."
    sudo apt update
    sudo apt install -y zenity alsa-utils libnotify-bin git cmake build-essential wget unzip curl pulseaudio-utils \
        python3-venv python3-pip python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
else
    echo "==> Pulando apt (--skip-apt). Certifique-se de que as dependências já estão instaladas."
fi

echo "==> Criando diretórios..."
mkdir -p "$BIN_DIR" "$NOTES_DIR"

echo "==> Copiando scripts para $BIN_DIR..."
cp "$SCRIPT_DIR/gravar.sh" "$BIN_DIR/gravar.sh"
cp "$SCRIPT_DIR/listar.sh" "$BIN_DIR/listar.sh"
cp "$SCRIPT_DIR/ler.sh" "$BIN_DIR/ler.sh"
cp "$SCRIPT_DIR/tomenotas-hotkey-record" "$BIN_DIR/tomenotas-hotkey-record"
chmod +x "$BIN_DIR/gravar.sh" "$BIN_DIR/listar.sh" "$BIN_DIR/ler.sh" \
    "$BIN_DIR/tomenotas-hotkey-record"

echo "==> Instalando o daemon (pacote Python em venv)..."
VENV_DIR="$DATA_DIR/venv"
# --system-site-packages: o PyGObject (gi) vem do apt, não do pip
python3 -m venv --system-site-packages "$VENV_DIR"
"$VENV_DIR/bin/pip" install -q --upgrade pip
"$VENV_DIR/bin/pip" install -q "$SCRIPT_DIR"
ln -sf "$VENV_DIR/bin/tomenotas-daemon" "$BIN_DIR/tomenotas-daemon"

if [ "$SKIP_WHISPER" -eq 0 ]; then
    if [ -d "$WHISPER_DIR" ]; then
        echo "==> whisper.cpp já existe em $WHISPER_DIR, pulando clone/build."
    else
        echo "==> Clonando e compilando whisper.cpp..."
        git clone https://github.com/ggerganov/whisper.cpp "$WHISPER_DIR"
        cmake -B "$WHISPER_DIR/build" -S "$WHISPER_DIR"
        cmake --build "$WHISPER_DIR/build" --config Release -j
    fi

    MODEL_FILE="$WHISPER_DIR/models/ggml-$MODEL_SIZE.bin"
    if [ -f "$MODEL_FILE" ]; then
        echo "==> Modelo $MODEL_SIZE já baixado."
    else
        echo "==> Baixando modelo whisper ($MODEL_SIZE)..."
        bash "$WHISPER_DIR/models/download-ggml-model.sh" "$MODEL_SIZE"
    fi

    # Detecta o nome do binário (varia entre versões do whisper.cpp)
    if [ -f "$WHISPER_DIR/build/bin/whisper-cli" ]; then
        WHISPER_BIN_PATH="$WHISPER_DIR/build/bin/whisper-cli"
    elif [ -f "$WHISPER_DIR/build/bin/main" ]; then
        WHISPER_BIN_PATH="$WHISPER_DIR/build/bin/main"
    else
        WHISPER_BIN_PATH="$WHISPER_DIR/build/bin/whisper-cli"
        echo "AVISO: não encontrei o binário compilado automaticamente. Verifique $WHISPER_DIR/build/bin/"
    fi

    echo "==> Ajustando caminhos do whisper.cpp em gravar.sh..."
    sed -i "s|^WHISPER_BIN=.*|WHISPER_BIN=\"$WHISPER_BIN_PATH\"|" "$BIN_DIR/gravar.sh"
    sed -i "s|^WHISPER_MODEL=.*|WHISPER_MODEL=\"$MODEL_FILE\"|" "$BIN_DIR/gravar.sh"

    # O daemon lê os caminhos de ~/.config/tomenotas/config.json (nada de sed)
    echo "==> Gravando caminhos do whisper.cpp em ~/.config/tomenotas/config.json..."
    CONFIG_DIR="$HOME/.config/tomenotas"
    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG_DIR/config.json" <<EOF
{
    "whisper_bin": "$WHISPER_BIN_PATH",
    "whisper_model": "$MODEL_FILE"
}
EOF
else
    echo "==> Pulando instalação do whisper.cpp (--skip-whisper). Ajuste WHISPER_BIN em $BIN_DIR/gravar.sh e os caminhos em ~/.config/tomenotas/config.json"
fi

if [ "$SKIP_PIPER" -eq 0 ]; then
    if [ -d "$PIPER_DIR" ] && [ -f "$PIPER_DIR/piper" ]; then
        echo "==> Piper já instalado em $PIPER_DIR."
    else
        echo "==> Baixando Piper (TTS)..."
        mkdir -p "$PIPER_DIR"
        cd "$PIPER_DIR"
        wget -q -O piper.tar.gz "https://github.com/rhasspy/piper/releases/latest/download/piper_linux_x86_64.tar.gz"
        tar -xzf piper.tar.gz --strip-components=1
        rm -f piper.tar.gz
        chmod +x "$PIPER_DIR/piper"
    fi

    VOICE_MODEL="$PIPER_DIR/pt_BR-faber-medium.onnx"
    if [ -f "$VOICE_MODEL" ]; then
        echo "==> Voz pt_BR já baixada."
    else
        echo "==> Baixando voz em português (pt_BR-faber-medium)..."
        BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/faber/medium"
        wget -q -O "$VOICE_MODEL" "$BASE_URL/pt_BR-faber-medium.onnx"
        wget -q -O "$VOICE_MODEL.json" "$BASE_URL/pt_BR-faber-medium.onnx.json"
    fi

    echo "==> Ajustando caminhos do Piper em ler.sh..."
    sed -i "s|^PIPER_BIN=.*|PIPER_BIN=\"$PIPER_DIR/piper\"|" "$BIN_DIR/ler.sh"
    sed -i "s|^PIPER_MODEL=.*|PIPER_MODEL=\"$VOICE_MODEL\"|" "$BIN_DIR/ler.sh"
else
    echo "==> Pulando instalação do Piper (--skip-piper). Ajuste PIPER_BIN e PIPER_MODEL manualmente em $BIN_DIR/ler.sh"
fi

if [ "$SKIP_SHORTCUTS" -eq 0 ]; then
    echo "==> Configurando atalhos de teclado no GNOME..."
    echo "    Gravar/parar : Super+R"
    echo "    Listar notas : Super+L"
    echo "    Ler nota     : Super+T"

    BASE_PATH="/org/gnome/settings-daemon/plugins/media-keys"
    KEY_GRAVAR="$BASE_PATH/custom-keybindings/tomenotas-gravar/"
    KEY_LISTAR="$BASE_PATH/custom-keybindings/tomenotas-listar/"
    KEY_LER="$BASE_PATH/custom-keybindings/tomenotas-ler/"

    EXISTING=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)
    if [[ "$EXISTING" == "@as []" ]]; then
        NEW_LIST="['$KEY_GRAVAR', '$KEY_LISTAR', '$KEY_LER']"
    else
        # remove colchetes e adiciona os novos, evitando duplicar se já existirem
        TRIMMED="${EXISTING%]}"
        TRIMMED="${TRIMMED#[}"
        NEW_LIST="[$TRIMMED, '$KEY_GRAVAR', '$KEY_LISTAR', '$KEY_LER']"
    fi
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$NEW_LIST"

    # O atalho de gravar chama o cliente D-Bus leve, não o gravar.sh: assim
    # ele só funciona enquanto o tomenotas-daemon estiver rodando (Fase 1).
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY_GRAVAR" name 'Tomenotas - Gravar'
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY_GRAVAR" command "$BIN_DIR/tomenotas-hotkey-record"
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY_GRAVAR" binding '<Super>r'

    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY_LISTAR" name 'Tomenotas - Listar'
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY_LISTAR" command "$BIN_DIR/listar.sh"
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY_LISTAR" binding '<Super>l'

    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY_LER" name 'Tomenotas - Ler'
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY_LER" command "$BIN_DIR/ler.sh"
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY_LER" binding '<Super>t'

    echo "==> Atalhos configurados. Se algum já estiver em uso por outro app, mude em:"
    echo "    Configurações > Teclado > Atalhos personalizados"
else
    echo "==> Pulando configuração de atalhos (--skip-shortcuts). Configure manualmente em Configurações > Teclado."
fi

echo ""
echo "==================================================="
echo " Instalação concluída!"
echo " Scripts em: $BIN_DIR"
echo " Notas em:   $NOTES_DIR"
echo " Atalhos:    Super+R (gravar), Super+L (listar), Super+T (ler)"
echo ""
echo " Inicie o daemon com: $BIN_DIR/tomenotas-daemon &"
echo " O atalho Super+R só funciona enquanto o daemon estiver rodando"
echo " (feche pelo menu da bandeja para desativá-lo)."
echo "==================================================="
