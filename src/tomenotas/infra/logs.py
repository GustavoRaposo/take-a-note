"""Logging estruturado do daemon (Fase 5).

Todos os módulos usam logging.getLogger("tomenotas.<módulo>"); esta função
liga o logger raiz "tomenotas" a um arquivo rotativo em
~/.local/share/tomenotas/daemon.log para facilitar debug.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

FORMATO = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("tomenotas")
    logger.setLevel(logging.INFO)
    # Idempotente por arquivo: repetir para o mesmo destino não duplica o
    # handler; um destino novo substitui o anterior.
    for existente in list(logger.handlers):
        if (isinstance(existente, RotatingFileHandler)
                and Path(existente.baseFilename) == log_file):
            return logger
        logger.removeHandler(existente)
        existente.close()
    handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(FORMATO))
    logger.addHandler(handler)
    return logger
