#!/bin/bash
# uninstall.sh
# Remove os scripts e atalhos instalados pelo install.sh.
# Por padrão, NÃO apaga suas notas nem o whisper.cpp/Piper (evita perda de dados
# e retrabalho de download). Use as flags abaixo se quiser remover tudo.
#
# Uso:
#   ./uninstall.sh                  -> remove scripts e atalhos, mantém notas e dependências
#   ./uninstall.sh --purge-notes    -> também apaga suas notas gravadas
#   ./uninstall.sh --purge-deps     -> também remove whisper.cpp e Piper (pastas grandes)
#   ./uninstall.sh --purge-notes --purge-deps   -> remove absolutamente tudo

PURGE_NOTES=0
PURGE_DEPS=0

for arg in "$@"; do
    case "$arg" in
        --purge-notes) PURGE_NOTES=1 ;;
        --purge-deps) PURGE_DEPS=1 ;;
        *) ;;
    esac
done

BIN_DIR="$HOME/bin"
DATA_DIR="$HOME/.local/share/tomenotas"
WHISPER_DIR="$HOME/whisper.cpp"
PIPER_DIR="$HOME/piper"

echo "==> Removendo atalhos de teclado do GNOME..."
BASE_PATH="/org/gnome/settings-daemon/plugins/media-keys"
KEY_GRAVAR="$BASE_PATH/custom-keybindings/tomenotas-gravar/"
KEY_LISTAR="$BASE_PATH/custom-keybindings/tomenotas-listar/"
KEY_LER="$BASE_PATH/custom-keybindings/tomenotas-ler/"

EXISTING=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null)

if [ -n "$EXISTING" ]; then
    NEW_LIST=$(python3 -c "
existing = $EXISTING
to_remove = ['$KEY_GRAVAR', '$KEY_LISTAR', '$KEY_LER']
result = [x for x in existing if x not in to_remove]
print(result)
" 2>/dev/null)

    if [ -n "$NEW_LIST" ]; then
        gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$NEW_LIST"
    fi
fi

echo "==> Removendo scripts de $BIN_DIR..."
rm -f "$BIN_DIR/gravar.sh" "$BIN_DIR/listar.sh" "$BIN_DIR/ler.sh"

# remove processo de gravação pendente, se houver
if [ -f "$DATA_DIR/recording.pid" ]; then
    kill -SIGINT "$(cat "$DATA_DIR/recording.pid")" 2>/dev/null
    rm -f "$DATA_DIR/recording.pid"
fi

if [ "$PURGE_NOTES" -eq 1 ]; then
    echo "==> Apagando notas e diretório de dados ($DATA_DIR)..."
    rm -rf "$DATA_DIR"
else
    echo "==> Mantendo suas notas em $DATA_DIR (use --purge-notes para apagar)."
fi

if [ "$PURGE_DEPS" -eq 1 ]; then
    echo "==> Removendo whisper.cpp e Piper..."
    rm -rf "$WHISPER_DIR" "$PIPER_DIR"
else
    echo "==> Mantendo whisper.cpp e Piper instalados (use --purge-deps para remover)."
fi

echo ""
echo "==================================================="
echo " Desinstalação concluída."
echo "==================================================="
