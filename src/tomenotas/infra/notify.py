"""Notificações de desktop via notify-send (mesmo mecanismo dos scripts bash).

Fase 5: as notificações aparecem como "Tomenotas" (--app-name) e, quando um
observador `on_activate` está registrado, ganham uma ação padrão — clicar na
notificação chama o callback (a cola usa isso para abrir a janela de notas).
"""

import subprocess
import sys
import threading


class Notifier:
    def __init__(self, spawn=subprocess.Popen):
        self._spawn = spawn
        # Chamado quando o usuário clica na notificação. Pode disparar de
        # uma thread — a cola embrulha com GLib.idle_add.
        self.on_activate = None

    def send(self, titulo: str, corpo: str) -> None:
        cmd = ["notify-send", "--app-name=Tomenotas"]
        if self.on_activate is not None:
            cmd.append("--action=default=Abrir")
        cmd += [titulo, corpo]

        try:
            if self.on_activate is None:
                self._spawn(cmd)
                return
            # --action faz o notify-send esperar e imprimir a ação clicada
            proc = self._spawn(cmd, stdout=subprocess.PIPE, text=True)
        except FileNotFoundError:
            # Sem libnotify-bin instalado: degrada para o stderr em vez de
            # derrubar o daemon por causa de uma notificação.
            print(f"tomenotas: {titulo}: {corpo}", file=sys.stderr)
            return

        threading.Thread(
            target=self._espera_clique, args=(proc,), daemon=True
        ).start()

    def _espera_clique(self, proc) -> None:
        saida, _ = proc.communicate()
        if (saida or "").strip() == "default" and self.on_activate is not None:
            self.on_activate()
