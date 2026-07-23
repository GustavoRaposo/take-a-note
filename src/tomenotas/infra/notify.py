"""Desktop notifications via notify-send (same mechanism the old bash
scripts used).

Fase 5: notifications show up as "Tomenotas" (--app-name) and, when an
`on_activate` observer is registered, gain a default action — clicking
the notification fires the callback (the glue uses this to open the
notes window).
"""

import subprocess
import sys
import threading


class Notifier:
    def __init__(self, spawn=subprocess.Popen, icon=None):
        self._spawn = spawn
        self._icon = str(icon) if icon else None  # shown by the notification
        # Called when the user clicks the notification. May fire from a
        # thread — the glue wraps it with GLib.idle_add.
        self.on_activate = None

    def send(self, title: str, body: str) -> None:
        cmd = ["notify-send", "--app-name=Tomenotas"]
        if self._icon:
            cmd.append(f"--icon={self._icon}")
        if self.on_activate is not None:
            cmd.append("--action=default=Abrir")
        cmd += [title, body]

        try:
            if self.on_activate is None:
                self._spawn(cmd)
                return
            # --action makes notify-send wait and print the clicked action
            proc = self._spawn(cmd, stdout=subprocess.PIPE, text=True)
        except FileNotFoundError:
            # libnotify-bin not installed: degrade to stderr instead of
            # crashing the daemon over a notification.
            print(f"tomenotas: {title}: {body}", file=sys.stderr)
            return

        threading.Thread(
            target=self._wait_click, args=(proc,), daemon=True
        ).start()

    def _wait_click(self, proc) -> None:
        out, _ = proc.communicate()
        if (out or "").strip() == "default" and self.on_activate is not None:
            self.on_activate()
