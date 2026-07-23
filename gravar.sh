#!/bin/bash
# gravar.sh
# Bind 1: aperta uma vez para começar a gravar, aperta de novo para parar,
# transcrever e salvar como uma nova nota.

# ---- CONFIGURAÇÃO (ajuste os caminhos abaixo) ----
BASE_DIR="$HOME/.local/share/tomenotas"
NOTES_DIR="$BASE_DIR/notes"
PID_FILE="$BASE_DIR/recording.pid"
AUDIO_TMP="$BASE_DIR/tmp_recording.wav"

WHISPER_BIN="$HOME/whisper.cpp/build/bin/whisper-cli"   # ou .../main, depende da versão
WHISPER_MODEL="$HOME/whisper.cpp/models/ggml-medium.bin"
# ---------------------------------------------------

mkdir -p "$NOTES_DIR"

if [ -f "$PID_FILE" ]; then
    # Já está gravando -> parar gravação
    PID=$(cat "$PID_FILE")
    kill -SIGINT "$PID" 2>/dev/null
    rm -f "$PID_FILE"

    # dá um tempo para o arecord fechar o arquivo wav corretamente
    sleep 1

    notify-send "Gravação" "Transcrevendo..."

    TS=$(date +%Y-%m-%d_%H-%M-%S)
    NOTE_FILE="$NOTES_DIR/$TS.txt"
    TMP_OUT="$BASE_DIR/tmp_transcricao"

    "$WHISPER_BIN" -m "$WHISPER_MODEL" -l pt -f "$AUDIO_TMP" -nt -otxt -of "$TMP_OUT" > /dev/null 2>&1

    if [ -f "$TMP_OUT.txt" ]; then
        cp "$TMP_OUT.txt" "$NOTE_FILE"
        rm -f "$TMP_OUT.txt"
        PREVIEW=$(head -c 60 "$NOTE_FILE")
        notify-send "Nota criada" "$PREVIEW"
    else
        notify-send "Erro" "Falha ao transcrever o áudio."
    fi

    rm -f "$AUDIO_TMP"
else
    # Não está gravando -> começar
    arecord -f cd -t wav "$AUDIO_TMP" &
    echo $! > "$PID_FILE"
    notify-send "Gravação" "Gravando... aperte o atalho de novo para parar."
fi
