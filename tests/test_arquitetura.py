"""Gate da regra de dependência entre camadas (Clean Architecture leve).

Falha se: gi for importado fora de ui/; domain/ importar qualquer camada
interna; app/ importar infra/ ou ui/; infra/ importar app/ ou ui/.
Ver a seção "Plano — camadas físicas" no ROADMAP.
"""

import ast
from pathlib import Path

PACOTE = Path(__file__).parent.parent / "src" / "tomenotas"

# camada -> camadas internas que ela PODE importar (além da própria)
PERMITIDAS = {
    "domain": set(),
    "app": {"domain"},
    "infra": {"domain"},
    "ui": {"domain", "app", "infra"},
}


def _arquivos_por_camada():
    for camada in PERMITIDAS:
        for arquivo in sorted((PACOTE / camada).glob("*.py")):
            yield camada, arquivo


def _imports_absolutos(camada, arquivo):
    """Todos os imports do arquivo como nomes absolutos de módulo."""
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
    pacote_atual = ["tomenotas", camada]  # pacote que contém o módulo
    for no in ast.walk(arvore):
        if isinstance(no, ast.Import):
            for alias in no.names:
                yield alias.name
        elif isinstance(no, ast.ImportFrom):
            if no.level == 0:
                yield no.module or ""
            else:
                base = pacote_atual[:len(pacote_atual) - (no.level - 1)]
                modulo = no.module.split(".") if no.module else []
                yield ".".join(base + modulo)


def _camada_de(modulo):
    partes = modulo.split(".")
    if partes[0] != "tomenotas" or len(partes) < 2:
        return None  # externo (stdlib etc.) ou a raiz do pacote
    return partes[1] if partes[1] in PERMITIDAS else None


def test_gi_so_pode_ser_importado_na_ui():
    violacoes = []
    for camada, arquivo in _arquivos_por_camada():
        if camada == "ui":
            continue
        for modulo in _imports_absolutos(camada, arquivo):
            if modulo == "gi" or modulo.startswith("gi."):
                violacoes.append(f"{camada}/{arquivo.name} importa {modulo}")
    assert violacoes == []


def test_regra_de_dependencia_entre_camadas():
    violacoes = []
    for camada, arquivo in _arquivos_por_camada():
        autorizadas = PERMITIDAS[camada] | {camada}
        for modulo in _imports_absolutos(camada, arquivo):
            alvo = _camada_de(modulo)
            if alvo is not None and alvo not in autorizadas:
                violacoes.append(
                    f"{camada}/{arquivo.name} importa {modulo} "
                    f"(camada {alvo} é proibida para {camada})"
                )
    assert violacoes == []


def test_todas_as_camadas_existem_e_tem_modulos():
    for camada in PERMITIDAS:
        modulos = list((PACOTE / camada).glob("*.py"))
        assert modulos, f"camada {camada}/ vazia ou ausente"
