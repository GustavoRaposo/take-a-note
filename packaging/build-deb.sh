#!/bin/bash
# Garante bash mesmo se invocado como "sh packaging/build-deb.sh"
if [ -z "$BASH_VERSION" ]; then exec bash "$0" "$@"; fi
# packaging/build-deb.sh — Fase B do plano .deb (ver ROADMAP)
#
# Constrói o pacote tomenotas_<versão>_amd64.deb usando dpkg-deb:
#   1. "vendoriza" os binários (compila o whisper-cli estático e baixa o
#      Piper) em packaging/vendor/ — acontece no BUILD do pacote, nunca
#      na máquina do usuário final;
#   2. monta a árvore de arquivos em packaging/staging/;
#   3. gera o .deb em dist/.
#
# O pacote resultante instala em /usr (código em dist-packages, binários
# em /usr/lib/tomenotas, clientes em /usr/bin, ícones em
# /usr/share/tomenotas) e declara só dependências de runtime — o usuário
# final não precisa de git/cmake/build-essential. Os modelos de STT/TTS
# continuam sendo baixados pelo app no primeiro uso (Fase A), e os
# atalhos de teclado são registrados pelo daemon na primeira execução
# (gsettings é por usuário; o postinst roda como root e não pode).
#
# Uso:
#   ./packaging/build-deb.sh              -> build completo
#   ./packaging/build-deb.sh --skip-vendor -> reusa packaging/vendor/

set -e

SKIP_VENDOR=0
for arg in "$@"; do
    case "$arg" in
        --skip-vendor) SKIP_VENDOR=1 ;;
        *) ;;
    esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$ROOT/packaging/vendor"
# Versões pinadas: builds reproduzíveis (nada de master/latest)
WHISPER_TAG="v1.9.1"
PIPER_VERSION="2023.11.14-2"
STAGING="$ROOT/packaging/staging"
DIST="$ROOT/dist"
VERSION=$(python3 -c "
import tomllib
with open('$ROOT/pyproject.toml', 'rb') as f:
    print(tomllib.load(f)['project']['version'])")
ARCH="amd64"
DEB="$DIST/tomenotas_${VERSION}_${ARCH}.deb"

# ---------------- 1. vendor: whisper-cli (estático) + piper ----------------

if [ "$SKIP_VENDOR" -eq 0 ] || [ ! -f "$VENDOR/whisper-cli" ]; then
    echo "==> Compilando whisper-cli estático ($WHISPER_TAG)..."
    WHISPER_SRC="$VENDOR/whisper.cpp-src"
    # re-clona se o checkout existente não é a tag pinada
    if [ -d "$WHISPER_SRC" ]; then
        ATUAL=$(git -C "$WHISPER_SRC" describe --tags --exact-match 2>/dev/null || echo "")
        if [ "$ATUAL" != "$WHISPER_TAG" ]; then
            rm -rf "$WHISPER_SRC"
        fi
    fi
    if [ ! -d "$WHISPER_SRC" ]; then
        git clone --depth 1 --branch "$WHISPER_TAG" \
            https://github.com/ggerganov/whisper.cpp "$WHISPER_SRC"
    fi
    # GGML_NATIVE=OFF: sem otimizações da CPU da máquina de build — o
    # binário precisa rodar em qualquer amd64, não só na nossa
    cmake -B "$WHISPER_SRC/build" -S "$WHISPER_SRC" \
        -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
        -DGGML_NATIVE=OFF > /dev/null
    cmake --build "$WHISPER_SRC/build" --config Release -j --target whisper-cli > /dev/null
    cp "$WHISPER_SRC/build/bin/whisper-cli" "$VENDOR/whisper-cli"
    # binário não pode depender de libs do build (precisa rodar de /usr/lib)
    if ldd "$VENDOR/whisper-cli" | grep -qE 'libwhisper|libggml'; then
        echo "ERRO: whisper-cli ficou dinâmico (depende de libwhisper/libggml)." >&2
        exit 1
    fi
fi

if [ "$SKIP_VENDOR" -eq 0 ] || [ ! -f "$VENDOR/piper/piper" ]; then
    echo "==> Baixando Piper ($PIPER_VERSION)..."
    mkdir -p "$VENDOR"
    wget -q -O "$VENDOR/piper.tar.gz" \
        "https://github.com/rhasspy/piper/releases/download/$PIPER_VERSION/piper_linux_x86_64.tar.gz"
    rm -rf "$VENDOR/piper"
    tar -xzf "$VENDOR/piper.tar.gz" -C "$VENDOR"   # extrai vendor/piper/
    rm -f "$VENDOR/piper.tar.gz"
fi

# ---------------- 2. staging ----------------

echo "==> Montando a árvore do pacote..."
rm -rf "$STAGING"
mkdir -p "$STAGING/DEBIAN" \
    "$STAGING/usr/bin" \
    "$STAGING/usr/lib/tomenotas" \
    "$STAGING/usr/lib/python3/dist-packages" \
    "$STAGING/usr/share/tomenotas/icons" \
    "$STAGING/usr/share/applications" \
    "$STAGING/etc/xdg/autostart"

# pacote Python (puro — basta copiar; nada de venv)
cp -r "$ROOT/src/tomenotas" "$STAGING/usr/lib/python3/dist-packages/"
find "$STAGING/usr/lib/python3/dist-packages" \
    -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# entry point do daemon (equivalente ao console script do pyproject)
cat > "$STAGING/usr/bin/tomenotas-daemon" <<'EOF'
#!/usr/bin/python3
from tomenotas.ui.daemon import main

if __name__ == "__main__":
    main()
EOF

# clientes D-Bus e lançador
cp "$ROOT/tomenotas-hotkey-record" "$ROOT/tomenotas-hotkey-window" \
   "$ROOT/tomenotas-hotkey-read" "$ROOT/tomenotas-open" "$STAGING/usr/bin/"
chmod 755 "$STAGING/usr/bin/"*

# binários vendorizados
cp "$VENDOR/whisper-cli" "$STAGING/usr/lib/tomenotas/whisper-cli"
cp -r "$VENDOR/piper" "$STAGING/usr/lib/tomenotas/piper"
chmod 755 "$STAGING/usr/lib/tomenotas/whisper-cli" \
          "$STAGING/usr/lib/tomenotas/piper/piper"

# ícones e lançadores de desktop
cp "$ROOT/assets/icons/"*.svg "$STAGING/usr/share/tomenotas/icons/"
cp "$ROOT/packaging/tomenotas.desktop" "$STAGING/usr/share/applications/"
cp "$ROOT/packaging/tomenotas-autostart.desktop" "$STAGING/etc/xdg/autostart/"

# ---------------- 3. metadados + build ----------------

INSTALLED_SIZE=$(du -sk "$STAGING" --exclude=DEBIAN | cut -f1)
cat > "$STAGING/DEBIAN/control" <<EOF
Package: tomenotas
Version: $VERSION
Section: sound
Priority: optional
Architecture: $ARCH
Installed-Size: $INSTALLED_SIZE
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, gir1.2-ayatanaappindicator3-0.1, alsa-utils, libnotify-bin, pulseaudio-utils, libgomp1, libstdc++6
Maintainer: Gustavo Raposo <gustavo_f.raposo@hotmail.com>
Description: Assistente pessoal de notas de voz (STT/TTS offline)
 Grave notas de voz com um atalho global (Super+R), transcritas
 localmente pelo whisper.cpp e lidas em voz alta pelo Piper — 100%
 offline, nada sai da sua máquina.
 .
 Os modelos de transcricao e voz sao baixados pelo proprio aplicativo
 no primeiro uso; os atalhos de teclado sao registrados pelo daemon na
 primeira execucao de cada usuario.
EOF

mkdir -p "$DIST"
dpkg-deb --build --root-owner-group "$STAGING" "$DEB" > /dev/null

echo ""
echo "==================================================="
echo " Pacote gerado: $DEB"
echo " Instalar com:  sudo apt install $DEB"
echo " (apt resolve as dependências declaradas)"
echo "==================================================="
