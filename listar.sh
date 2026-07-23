#!/bin/bash
# listar.sh
# Bind 2: mostra a lista de notas (mais recente primeiro) e permite
# selecionar uma para virar a "nota atual" (usada pelo ler.sh).

BASE_DIR="$HOME/.local/share/tomenotas"
NOTES_DIR="$BASE_DIR/notes"
CURRENT_NOTE_FILE="$BASE_DIR/current_note"

mkdir -p "$NOTES_DIR"

mapfile -t files < <(ls -t "$NOTES_DIR"/*.txt 2>/dev/null)

if [ ${#files[@]} -eq 0 ]; then
    notify-send "Notas de voz" "Nenhuma nota encontrada ainda."
    exit 0
fi

declare -A preview_to_path
labels=()

for f in "${files[@]}"; do
    ts=$(basename "$f" .txt)
    preview=$(head -c 60 "$f" | tr '\n' ' ')
    line="$ts | $preview..."
    preview_to_path["$line"]="$f"
    labels+=("$line")
done

selected=$(zenity --list --title="Notas de voz" --width=800 --height=500 \
    --column="Selecione uma nota" "${labels[@]}" 2>/dev/null)

if [ -n "$selected" ] && [ -n "${preview_to_path[$selected]}" ]; then
    echo "${preview_to_path[$selected]}" > "$CURRENT_NOTE_FILE"
    notify-send "Nota selecionada" "$selected"
fi
