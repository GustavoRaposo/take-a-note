"""Testes de tomenotas.shortcuts — atalhos do GNOME via gsettings."""

from pathlib import Path
from types import SimpleNamespace

from tomenotas.infra.shortcuts import BASE_PATH, ShortcutManager


class GsettingsFalso:
    """Simula o CLI gsettings: get/set/list-recursively."""

    def __init__(self, lista="@as []", entradas=None, recursivo=None):
        self.lista = lista            # valor da chave custom-keybindings
        self.entradas = entradas or {}  # path -> {chave: valor impresso}
        self.recursivo = recursivo or {}  # schema -> saída de list-recursively
        self.sets = []

    def __call__(self, cmd, **kwargs):
        assert cmd[0] == "gsettings"
        op = cmd[1]
        if op == "get":
            alvo, chave = cmd[2], cmd[3]
            if ":" in alvo:
                path = alvo.split(":", 1)[1]
                saida = self.entradas.get(path, {}).get(chave, "''")
            elif chave == "custom-keybindings":
                saida = self.lista
            else:
                saida = "''"
        elif op == "set":
            alvo, chave, valor = cmd[2], cmd[3], cmd[4]
            self.sets.append((alvo, chave, valor))
            if ":" in alvo:
                path = alvo.split(":", 1)[1]
                self.entradas.setdefault(path, {})[chave] = f"'{valor}'"
            elif chave == "custom-keybindings":
                self.lista = valor
            saida = ""
        else:  # list-recursively
            saida = self.recursivo.get(cmd[2], "")
        return SimpleNamespace(stdout=saida + "\n", returncode=0)


BIN = Path("/home/x/bin")
PATH_GRAVAR = f"{BASE_PATH}/tomenotas-gravar/"
PATH_LISTAR = f"{BASE_PATH}/tomenotas-listar/"


def test_acoes_apontam_para_os_comandos_certos():
    manager = ShortcutManager(BIN, run=GsettingsFalso())
    acoes = manager.acoes
    assert acoes["gravar"].comando == "/home/x/bin/tomenotas-hotkey-record"
    assert acoes["listar"].comando == "/home/x/bin/tomenotas-hotkey-window"
    assert acoes["ler"].comando == "/home/x/bin/ler.sh"
    assert acoes["gravar"].padrao == "<Super>r"
    assert acoes["listar"].padrao == "<Super>l"
    assert acoes["ler"].padrao == "<Super>t"


def test_get_binding_remove_aspas():
    gs = GsettingsFalso(entradas={PATH_GRAVAR: {"binding": "'<Super>r'"}})
    manager = ShortcutManager(BIN, run=gs)
    assert manager.get_binding("gravar") == "<Super>r"


def test_get_binding_sem_valor_retorna_vazio():
    manager = ShortcutManager(BIN, run=GsettingsFalso())
    assert manager.get_binding("gravar") == ""


def test_set_binding_registra_na_lista_vazia_e_grava_tudo():
    gs = GsettingsFalso(lista="@as []")
    manager = ShortcutManager(BIN, run=gs)
    manager.set_binding("gravar", "<Super>F9")

    assert gs.lista == f"['{PATH_GRAVAR}']"
    schema_path = [s for s in gs.sets if ":" in s[0]]
    chaves = {(chave, valor) for _, chave, valor in schema_path}
    assert ("name", "Tomenotas - Gravar") in chaves
    assert ("command", "/home/x/bin/tomenotas-hotkey-record") in chaves
    assert ("binding", "<Super>F9") in chaves


def test_set_binding_preserva_lista_existente_sem_duplicar():
    gs = GsettingsFalso(lista=f"['/outro/app/', '{PATH_GRAVAR}']")
    manager = ShortcutManager(BIN, run=gs)
    manager.set_binding("gravar", "<Super>F9")
    # já estava na lista: não mexe nela
    assert gs.lista == f"['/outro/app/', '{PATH_GRAVAR}']"

    manager.set_binding("listar", "<Super>F10")
    assert gs.lista == f"['/outro/app/', '{PATH_GRAVAR}', '{PATH_LISTAR}']"


def test_conflito_com_atalho_do_sistema():
    gs = GsettingsFalso(recursivo={
        "org.gnome.desktop.wm.keybindings":
            "org.gnome.desktop.wm.keybindings close ['<Alt>F4', '<Super>r']\n"
            "org.gnome.desktop.wm.keybindings minimize ['<Super>h']",
    })
    manager = ShortcutManager(BIN, run=gs)
    conflitos = manager.list_conflicts("<Super>r")
    assert conflitos == ["close (org.gnome.desktop.wm.keybindings)"]


def test_conflito_ignora_prefixo_parecido():
    # '<Super>Right' não pode ser tratado como conflito de '<Super>r'
    gs = GsettingsFalso(recursivo={
        "org.gnome.desktop.wm.keybindings":
            "org.gnome.desktop.wm.keybindings move-right ['<Super>Right']",
    })
    manager = ShortcutManager(BIN, run=gs)
    assert manager.list_conflicts("<Super>r") == []


def test_conflito_sem_diferenciar_caixa():
    gs = GsettingsFalso(recursivo={
        "org.gnome.shell.keybindings":
            "org.gnome.shell.keybindings toggle-overview ['<super>R']",
    })
    manager = ShortcutManager(BIN, run=gs)
    assert manager.list_conflicts("<Super>r") == [
        "toggle-overview (org.gnome.shell.keybindings)"
    ]


def test_conflito_com_outro_atalho_personalizado_pelo_nome():
    gs = GsettingsFalso(
        lista=f"['{PATH_GRAVAR}', '{PATH_LISTAR}']",
        entradas={
            PATH_GRAVAR: {"binding": "'<Super>r'", "name": "'Tomenotas - Gravar'"},
            PATH_LISTAR: {"binding": "'<Super>l'", "name": "'Tomenotas - Listar'"},
        },
    )
    manager = ShortcutManager(BIN, run=gs)
    # quero usar <Super>l no "gravar": conflita com o "listar", pelo nome
    assert manager.list_conflicts("<Super>l", ignorar_acao="gravar") == [
        "Tomenotas - Listar"
    ]
    # o próprio atalho da ação editada não é conflito
    assert manager.list_conflicts("<Super>r", ignorar_acao="gravar") == []


def test_sem_conflitos_retorna_lista_vazia():
    manager = ShortcutManager(BIN, run=GsettingsFalso())
    assert manager.list_conflicts("<Super>F12") == []


def test_varredura_tolera_formatos_diversos_do_gsettings():
    gs = GsettingsFalso(recursivo={
        # valor string (não lista), linha curta e a própria lista de paths
        # de custom-keybindings devem ser tratados sem falso positivo
        "org.gnome.settings-daemon.plugins.media-keys":
            "org.gnome.settings-daemon.plugins.media-keys screensaver '<Super>s'\n"
            "linha-curta\n"
            "org.gnome.settings-daemon.plugins.media-keys custom-keybindings "
            "['/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/tomenotas-gravar/']",
    })
    manager = ShortcutManager(BIN, run=gs)
    assert manager.list_conflicts("<Super>s") == [
        "screensaver (org.gnome.settings-daemon.plugins.media-keys)"
    ]
    assert manager.list_conflicts("<Super>x") == []
