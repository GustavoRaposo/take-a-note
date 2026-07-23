#!/bin/bash
# ler.sh
# Bind 3: lê em voz alta (TTS em português) a nota atualmente selecionada.
# Se nenhuma nota foi selecionada via listar.sh, lê a nota mais recente.

# ---- CONFIGURAÇÃO (ajuste os caminhos abaixo) ----
BASE_DIR="$HOME/.local/share/tomenotas"
NOTES_DIR="$BASE_DIR/notes"
CURRENT_NOTE_FILE="$BASE_DIR/current_note"

PIPER_BIN="$HOME/piper/piper"
PIPER_MODEL="$HOME/piper/pt_BR-faber-medium.onnx"   # ajuste para a voz que você baixou
TTS_TMP="$BASE_DIR/tmp_tts.wav"
# ---------------------------------------------------

if [ -f "$CURRENT_NOTE_FILE" ]; then
    note_path=$(cat "$CURRENT_NOTE_FILE")
fi

if [ -z "$note_path" ] || [ ! -f "$note_path" ]; then
    note_path=$(ls -t "$NOTES_DIR"/*.txt 2>/dev/null | head -n 1)
fi

if [ -z "$note_path" ] || [ ! -f "$note_path" ]; then
    notify-send "TTS" "Nenhuma nota disponível para ler."
    exit 1
fi

text=$(cat "$note_path")

if [ -z "$text" ]; then
    notify-send "TTS" "A nota está vazia."
    exit 1
fi

echo "$text" | "$PIPER_BIN" --model "$PIPER_MODEL" --output_file "$TTS_TMP"
paplay "$TTS_TMP"
rm -f "$TTS_TMP"
