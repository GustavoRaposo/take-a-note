"""Atalhos globais do GNOME via gsettings custom-keybindings.

Equivalente programático ao que o install.sh faz na instalação: registra
os três atalhos (gravar/listar/ler) e permite trocá-los pela UI da Fase 3.
Usa o CLI gsettings via subprocess injetável (mesmo padrão dos outros
módulos), o que mantém a lógica — inclusive a detecção de conflitos —
100% testável.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
CUSTOM_SCHEMA = SCHEMA + ".custom-keybinding"
BASE_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings"

# Onde procurar conflitos com atalhos do sistema ("quando possível detectar")
SCHEMAS_DE_CONFLITO = [
    "org.gnome.desktop.wm.keybindings",
    "org.gnome.shell.keybindings",
    "org.gnome.mutter.keybindings",
    SCHEMA,
]


@dataclass(frozen=True)
class Action:
    id: str       # sufixo do path gsettings (tomenotas-<id>)
    label: str    # "name" no gsettings
    titulo: str   # rótulo exibido na UI
    comando: str  # executável chamado pelo atalho
    padrao: str   # binding padrão (o mesmo do install.sh)


def _parse_lista(valor: str) -> list[str]:
    """'@as []' / \"['/a/', '/b/']\" → lista de paths."""
    valor = valor.strip()
    if not valor or valor in ("@as []", "[]"):
        return []
    return [
        item.strip().strip("'\"")
        for item in valor.strip("[]").split(",")
        if item.strip()
    ]


def _bindings_de(valor: str) -> list[str]:
    """Extrai os bindings de um valor gsettings, que pode ser uma string
    (\"'<Super>r'\") ou uma lista (\"['<Alt>F4', '<Super>r']\")."""
    valor = valor.strip()
    if valor.startswith("["):
        return _parse_lista(valor)
    return [valor.strip("'\"")] if valor.strip("'\"") else []


class ShortcutManager:
    def __init__(self, bin_dir: Path, run=subprocess.run):
        self._run = run
        self.acoes = {
            "gravar": Action(
                "gravar", "Tomenotas - Gravar", "Gravar/parar",
                str(bin_dir / "tomenotas-hotkey-record"), "<Super>r",
            ),
            "listar": Action(
                "listar", "Tomenotas - Listar", "Listar notas",
                str(bin_dir / "tomenotas-hotkey-window"), "<Super>l",
            ),
            "ler": Action(
                "ler", "Tomenotas - Ler", "Ler nota atual",
                str(bin_dir / "ler.sh"), "<Super>t",
            ),
        }

    def _out(self, *args: str) -> str:
        resultado = self._run(
            ["gsettings", *args],
            capture_output=True, text=True, check=False,
        )
        return (resultado.stdout or "").strip()

    def _path(self, acao_id: str) -> str:
        return f"{BASE_PATH}/tomenotas-{acao_id}/"

    def get_binding(self, acao_id: str) -> str:
        bruto = self._out("get", f"{CUSTOM_SCHEMA}:{self._path(acao_id)}",
                          "binding")
        return bruto.strip("'\"")

    def set_binding(self, acao_id: str, binding: str) -> None:
        """Grava o atalho no GNOME — efeito imediato no teclado. Também
        (re)grava name/command, o que torna a operação auto-reparadora."""
        acao = self.acoes[acao_id]
        alvo = f"{CUSTOM_SCHEMA}:{self._path(acao_id)}"
        self._registra(self._path(acao_id))
        self._out("set", alvo, "name", acao.label)
        self._out("set", alvo, "command", acao.comando)
        self._out("set", alvo, "binding", binding)

    def _registra(self, path: str) -> None:
        atual = self._out("get", SCHEMA, "custom-keybindings")
        caminhos = _parse_lista(atual)
        if path in caminhos:
            return
        caminhos.append(path)
        novo = "[" + ", ".join(f"'{c}'" for c in caminhos) + "]"
        self._out("set", SCHEMA, "custom-keybindings", novo)

    def list_conflicts(self, binding: str,
                       ignorar_acao: str | None = None) -> list[str]:
        """Descrições legíveis de quem já usa esse atalho (lista vazia se
        ninguém). Compara bindings exatos, sem diferenciar caixa."""
        alvo = binding.lower()
        conflitos = []

        for schema in SCHEMAS_DE_CONFLITO:
            for linha in self._out("list-recursively", schema).splitlines():
                partes = linha.split(None, 2)
                if len(partes) < 3:
                    continue
                _, chave, valor = partes
                if chave == "custom-keybindings":
                    continue  # é a lista de paths, não um binding
                if alvo in (b.lower() for b in _bindings_de(valor)):
                    conflitos.append(f"{chave} ({schema})")

        proprio = self._path(ignorar_acao) if ignorar_acao else None
        lista = self._out("get", SCHEMA, "custom-keybindings")
        for caminho in _parse_lista(lista):
            if caminho == proprio:
                continue
            entrada = f"{CUSTOM_SCHEMA}:{caminho}"
            b = self._out("get", entrada, "binding").strip("'\"")
            if b and b.lower() == alvo:
                nome = self._out("get", entrada, "name").strip("'\"")
                conflitos.append(nome or caminho)

        return conflitos
