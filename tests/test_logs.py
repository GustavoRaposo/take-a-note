"""Testes de tomenotas.logs — logging estruturado em arquivo."""

import logging

from tomenotas.infra.logs import setup_logging


def test_escreve_linha_formatada_no_arquivo(tmp_path):
    arquivo = tmp_path / "sub" / "daemon.log"
    setup_logging(arquivo)
    logging.getLogger("tomenotas.core").info("nota salva: %s", "x.txt")

    conteudo = arquivo.read_text(encoding="utf-8")
    assert "INFO tomenotas.core: nota salva: x.txt" in conteudo


def test_setup_repetido_nao_duplica_linhas(tmp_path):
    arquivo = tmp_path / "daemon.log"
    setup_logging(arquivo)
    setup_logging(arquivo)  # idempotente: um handler só
    logging.getLogger("tomenotas.player").warning("uma vez")

    linhas = [l for l in arquivo.read_text(encoding="utf-8").splitlines()
              if "uma vez" in l]
    assert len(linhas) == 1
