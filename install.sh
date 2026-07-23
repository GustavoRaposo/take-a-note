#!/bin/bash
# Garante bash mesmo se invocado como "sh install.sh" (dash não tem [[ )
if [ -z "$BASH_VERSION" ]; then exec bash "$0" "$@"; fi
# install.sh
# Instala o sistema de notas de voz: dependências, whisper.cpp, Piper,
# copia os scripts para ~/tomenotas e configura os 3 atalhos de teclado no GNOME.
#
# Uso:
#   ./install.sh                     -> instala tudo com valores padrão
#   ./install.sh --skip-whisper      -> não baixa/compila o whisper.cpp
#   ./install.sh --skip-piper        -> não baixa o Piper
#   ./install.sh --skip-shortcuts    -> não mexe nos atalhos do GNOME
#   ./install.sh --skip-apt          -> não roda apt (dependências já instaladas)
#
# Os modelos de STT (whisper) e TTS (voz do Piper) NÃO são baixados aqui:
# o app oferece o download no primeiro uso, em Configurações (Fase A do
# plano .deb no ROADMAP).

set -e

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
        *) ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/tomenotas"
DATA_DIR="$HOME/.local/share/tomenotas"
NOTES_DIR="$DATA_DIR/notes"
WHISPER_DIR="$HOME/whisper.cpp"
PIPER_DIR="$HOME/piper"

if [ "$SKIP_APT" -eq 0 ]; then
    echo "==> Instalando dependências do sistema (apt)..."
    sudo apt update
    sudo apt install -y alsa-utils libnotify-bin git cmake build-essential wget unzip curl pulseaudio-utils \
        python3-venv python3-pip python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-ayatanaappindicator3-0.1
else
    echo "==> Pulando apt (--skip-apt). Certifique-se de que as dependências já estão instaladas."
fi

echo "==> Criando diretórios..."
mkdir -p "$BIN_DIR" "$NOTES_DIR"

echo "==> Copiando scripts para $BIN_DIR..."
cp "$SCRIPT_DIR/tomenotas-hotkey-record" "$BIN_DIR/tomenotas-hotkey-record"
cp "$SCRIPT_DIR/tomenotas-hotkey-window" "$BIN_DIR/tomenotas-hotkey-window"
cp "$SCRIPT_DIR/tomenotas-hotkey-read" "$BIN_DIR/tomenotas-hotkey-read"
cp "$SCRIPT_DIR/tomenotas-open" "$BIN_DIR/tomenotas-open"
chmod +x "$BIN_DIR/tomenotas-hotkey-record" \
    "$BIN_DIR/tomenotas-hotkey-window" "$BIN_DIR/tomenotas-hotkey-read" \
    "$BIN_DIR/tomenotas-open"
# limpa scripts legados de instalações anteriores (aposentados)
rm -f "$BIN_DIR/gravar.sh" "$BIN_DIR/listar.sh" "$BIN_DIR/ler.sh"
# migração: instalações antigas colocavam tudo em ~/bin
rm -f "$HOME/bin/gravar.sh" "$HOME/bin/listar.sh" "$HOME/bin/ler.sh" \
    "$HOME/bin/tomenotas-daemon" "$HOME/bin/tomenotas-hotkey-record" \
    "$HOME/bin/tomenotas-hotkey-window" "$HOME/bin/tomenotas-hotkey-read" \
    "$HOME/bin/tomenotas-open"

echo "==> Instalando o daemon (pacote Python em venv)..."
VENV_DIR="$DATA_DIR/venv"
# --system-site-packages: o PyGObject (gi) vem do apt, não do pip
python3 -m venv --system-site-packages "$VENV_DIR"
"$VENV_DIR/bin/pip" install -q --upgrade pip
"$VENV_DIR/bin/pip" install -q "$SCRIPT_DIR"
ln -sf "$VENV_DIR/bin/tomenotas-daemon" "$BIN_DIR/tomenotas-daemon"

echo "==> Instalando ícones da bandeja..."
mkdir -p "$DATA_DIR/icons"
cp "$SCRIPT_DIR/assets/icons/"*.svg "$DATA_DIR/icons/"

echo "==> Criando lançador no menu de aplicativos..."
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/tomenotas.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Tomenotas
Comment=Assistente de notas de voz (STT/TTS offline)
Exec=$BIN_DIR/tomenotas-open
Icon=$DATA_DIR/icons/tomenotas-idle.svg
Terminal=false
Categories=Utility;Audio;
Keywords=notas;voz;gravar;transcrever;tomenotas;
EOF

echo "==> Configurando início automático no login..."
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/tomenotas.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Tomenotas
Comment=Assistente de notas de voz (STT/TTS offline)
Exec=$BIN_DIR/tomenotas-daemon
Icon=audio-input-microphone
X-GNOME-Autostart-enabled=true
EOF

# Caminhos padrão (as seções abaixo refinam quando instalam de verdade);
# no fim, tudo vai para ~/.config/tomenotas/config.json, lido pelo daemon.
WHISPER_BIN_PATH="$WHISPER_DIR/build/bin/whisper-cli"
PIPER_BIN_PATH="$PIPER_DIR/piper"

if [ "$SKIP_WHISPER" -eq 0 ]; then
    if [ -d "$WHISPER_DIR" ]; then
        echo "==> whisper.cpp já existe em $WHISPER_DIR, pulando clone/build."
    else
        echo "==> Clonando e compilando whisper.cpp..."
        git clone https://github.com/ggerganov/whisper.cpp "$WHISPER_DIR"
        cmake -B "$WHISPER_DIR/build" -S "$WHISPER_DIR"
        cmake --build "$WHISPER_DIR/build" --config Release -j
    fi

    # Fase A do plano .deb: o modelo NÃO é mais baixado aqui — o app
    # oferece o download (com barra de progresso) no primeiro uso, em
    # Configurações. Modelos de instalações antigas continuam valendo.

    # Detecta o nome do binário (varia entre versões do whisper.cpp)
    if [ -f "$WHISPER_DIR/build/bin/whisper-cli" ]; then
        WHISPER_BIN_PATH="$WHISPER_DIR/build/bin/whisper-cli"
    elif [ -f "$WHISPER_DIR/build/bin/main" ]; then
        WHISPER_BIN_PATH="$WHISPER_DIR/build/bin/main"
    else
        WHISPER_BIN_PATH="$WHISPER_DIR/build/bin/whisper-cli"
        echo "AVISO: não encontrei o binário compilado automaticamente. Verifique $WHISPER_DIR/build/bin/"
    fi

else
    echo "==> Pulando instalação do whisper.cpp (--skip-whisper). Ajuste os caminhos em ~/.config/tomenotas/config.json"
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

    # Fase A do plano .deb: a voz NÃO é mais baixada aqui — o app oferece
    # o download da voz padrão no primeiro uso, em Configurações.

else
    echo "==> Pulando instalação do Piper (--skip-piper). Ajuste os caminhos em ~/.config/tomenotas/config.json"
fi

# O daemon lê os caminhos de ~/.config/tomenotas/config.json (nada de sed).
# Modelos só entram no json se já existirem (instalação antiga); sem eles,
# o daemon usa os padrões (~/.local/share/tomenotas/models/) e oferece o
# download no primeiro uso.
echo "==> Gravando caminhos em ~/.config/tomenotas/config.json..."
CONFIG_DIR="$HOME/.config/tomenotas"
mkdir -p "$CONFIG_DIR"
python3 - "$CONFIG_DIR/config.json" <<EOF
import glob, json, sys

cfg = {
    "whisper_bin": "$WHISPER_BIN_PATH",
    "piper_bin": "$PIPER_BIN_PATH",
    "bin_dir": "$BIN_DIR",
}
models = sorted(glob.glob("$WHISPER_DIR/models/ggml-*.bin"))
voices = sorted(glob.glob("$PIPER_DIR/*.onnx"))
if models:
    cfg["whisper_model"] = models[0]
if voices:
    cfg["piper_model"] = voices[0]
with open(sys.argv[1], "w", encoding="utf-8") as out:
    out.write(json.dumps(cfg, indent=4) + "\n")
EOF

if [ "$SKIP_SHORTCUTS" -eq 0 ]; then
    echo "==> Configurando atalhos de teclado no GNOME..."
    echo "    Gravar/parar : Super+R"
    echo "    Listar notas : Super+Y"
    echo "    Ler nota     : Super+T"

    BASE_PATH="/org/gnome/settings-daemon/plugins/media-keys"
    KEY_GRAVAR="$BASE_PATH/custom-keybindings/tomenotas-gravar/"
    KEY_LISTAR="$BASE_PATH/custom-keybindings/tomenotas-listar/"
    KEY_LER="$BASE_PATH/custom-keybindings/tomenotas-ler/"

    EXISTING=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings)
    if [ "$EXISTING" = "@as []" ] || [ "$EXISTING" = "[]" ]; then
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

    # O atalho de listar abre a janela de notas do daemon via D-Bus — como o
    # de gravar, só funciona enquanto o tomenotas-daemon estiver rodando.
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY_LISTAR" name 'Tomenotas - Listar'
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY_LISTAR" command "$BIN_DIR/tomenotas-hotkey-window"
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY_LISTAR" binding '<Super>y'

    # O atalho de ler chama o daemon via D-Bus — como os demais, só
    # funciona enquanto o tomenotas-daemon estiver rodando.
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY_LER" name 'Tomenotas - Ler'
    gsettings set org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:"$KEY_LER" command "$BIN_DIR/tomenotas-hotkey-read"
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
echo " Atalhos:    Super+R (gravar), Super+Y (listar), Super+T (ler)"
echo ""
echo " Inicie o daemon com: $BIN_DIR/tomenotas-daemon &"
echo " No primeiro uso, o app abre as Configurações para baixar o"
echo " modelo de transcrição e a voz (não são baixados na instalação)."
echo " O atalho Super+R só funciona enquanto o daemon estiver rodando"
echo " (feche pelo menu da bandeja para desativá-lo)."
echo "==================================================="
