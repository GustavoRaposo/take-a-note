#!/bin/bash
# tools/wakeword-daemon-test.sh — valida o wake word ponta-a-ponta no app.
#
# Roda o daemon DO REPO (código mais novo, com o wake word) sob o python de
# runtime real (/usr/bin/python3, o mesmo do .deb) usando o runtime de wake
# word vendorizado em packaging/vendor/pydeps — ou seja, exatamente o
# ambiente que o .deb terá. Liga o wake word no config, com o threshold que
# calibramos (0.55), e transmite os scores do daemon.log ao vivo.
#
# Fale "Tomenotas": o daemon deve começar a gravar (o ícone da bandeja muda
# e sai uma notificação). Ctrl+C encerra o daemon e o teste.
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYDEPS="$ROOT/packaging/vendor/pydeps"
LOG="$HOME/.local/share/tomenotas/daemon.log"

if [ ! -d "$PYDEPS/openwakeword" ]; then
  echo "ERRO: runtime vendorizado ausente em $PYDEPS." >&2
  echo "Gere-o rodando: ./packaging/build-deb.sh --skip-vendor" >&2
  exit 1
fi

# Não pode haver outro Tomenotas dono do nome D-Bus (ex.: o do .deb via
# autostart) — os dois brigariam pelo mesmo nome.
if gdbus call --session --dest com.tomenotas.Daemon \
     --object-path /com/tomenotas/Daemon \
     --method com.tomenotas.Daemon.Ping >/dev/null 2>&1; then
  echo "Já há um Tomenotas rodando (provavelmente o do .deb, via autostart)." >&2
  echo "Feche-o pela bandeja (ícone → Sair) e rode este script de novo." >&2
  exit 1
fi

# Liga o wake word no config do usuário, com o threshold calibrado.
/usr/bin/python3 - <<'PY'
import json, pathlib
p = pathlib.Path("~/.config/tomenotas/config.json").expanduser()
data = {}
if p.is_file():
    try:
        data = json.loads(p.read_text())
    except Exception:
        data = {}
if not isinstance(data, dict):
    data = {}
data["wakeword_enabled"] = True
data["wakeword_threshold"] = 0.55
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(data, indent=2) + "\n")
print("config: wake word LIGADO, threshold=0.55")
PY

echo "-----------------------------------------------------------------"
echo " Iniciando o daemon (python de runtime + pydeps vendorizado)."
echo " Fale 'Tomenotas' — deve começar a gravar."
echo " Os scores aparecem abaixo ao vivo. Ctrl+C encerra."
echo "-----------------------------------------------------------------"

PYTHONPATH="$PYDEPS:$ROOT/src" TOMENOTAS_WAKEWORD_DEBUG=1 \
  /usr/bin/python3 -c "from tomenotas.ui.daemon import main; main()" &
DAEMON=$!
trap 'kill $DAEMON 2>/dev/null; echo; echo "encerrado."' INT TERM EXIT

# transmite só as novas linhas do log (scores + DETECTED aparecem aqui)
sleep 1
tail -n 0 -f "$LOG"
