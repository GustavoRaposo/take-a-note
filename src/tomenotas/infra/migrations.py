"""Migrations do banco de notas (estratégia detalhada no ROADMAP).

Regras:
- Toda alteração de estrutura do banco entra como uma NOVA migration no
  fim de MIGRATIONS; migrations publicadas são imutáveis.
- A versão aplicada fica no próprio banco (PRAGMA user_version).
- apply_migrations aplica só as pendentes, cada uma numa transação: ou
  aplica inteira, ou faz rollback e nada muda. Antes de atualizar um banco
  existente, o arquivo ganha um backup (mantidos os últimos N).
"""

import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..domain.errors import MigrationError

log = logging.getLogger("tomenotas.migrations")

BACKUPS_MANTIDOS = 3


@dataclass(frozen=True)
class Migration:
    version: int
    descricao: str
    apply: Callable[[sqlite3.Connection], None]


def _v1_esquema_inicial(conn: sqlite3.Connection) -> None:
    # Sem executescript: ele daria COMMIT implícito e quebraria a transação
    comandos = [
        """CREATE TABLE notes (
               id         INTEGER PRIMARY KEY,
               created_at TEXT    NOT NULL,
               text       TEXT    NOT NULL,
               favorite   INTEGER NOT NULL DEFAULT 0
           )""",
        "CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE)",
        """CREATE TABLE note_tags (
               note_id INTEGER REFERENCES notes(id) ON DELETE CASCADE,
               tag_id  INTEGER REFERENCES tags(id)  ON DELETE CASCADE,
               PRIMARY KEY (note_id, tag_id)
           )""",
        """CREATE VIRTUAL TABLE notes_fts USING fts5(
               text, content='notes', content_rowid='id'
           )""",
        """CREATE TRIGGER notes_fts_ai AFTER INSERT ON notes BEGIN
               INSERT INTO notes_fts(rowid, text) VALUES (new.id, new.text);
           END""",
        """CREATE TRIGGER notes_fts_ad AFTER DELETE ON notes BEGIN
               INSERT INTO notes_fts(notes_fts, rowid, text)
               VALUES ('delete', old.id, old.text);
           END""",
        """CREATE TRIGGER notes_fts_au AFTER UPDATE OF text ON notes BEGIN
               INSERT INTO notes_fts(notes_fts, rowid, text)
               VALUES ('delete', old.id, old.text);
               INSERT INTO notes_fts(rowid, text) VALUES (new.id, new.text);
           END""",
    ]
    for comando in comandos:
        conn.execute(comando)


def _v2_coluna_filename(conn: sqlite3.Connection) -> None:
    # Espelho .txt: mapeia cada nota ao arquivo em notes/ (scripts legados)
    conn.execute("ALTER TABLE notes ADD COLUMN filename TEXT")


MIGRATIONS = [
    Migration(1, "esquema inicial (notes, tags, note_tags, FTS5)",
              _v1_esquema_inicial),
    Migration(2, "coluna filename para o espelho .txt", _v2_coluna_filename),
]

SCHEMA_VERSION = MIGRATIONS[-1].version


def apply_migrations(conn: sqlite3.Connection, db_path: Path | None = None,
                     migrations=None, now=datetime.now) -> list[int]:
    """Aplica as migrations pendentes; devolve as versões aplicadas."""
    migrations = MIGRATIONS if migrations is None else migrations
    atual = conn.execute("PRAGMA user_version").fetchone()[0]
    pendentes = [m for m in migrations if m.version > atual]
    if not pendentes:
        return []

    # Backup antes de atualizar um banco que já existia (versão > 0)
    if db_path is not None and atual > 0 and Path(db_path).exists():
        _backup(Path(db_path), atual, now())

    aplicadas = []
    isolation_anterior = conn.isolation_level
    conn.isolation_level = None  # transações controladas manualmente
    try:
        for migration in pendentes:
            try:
                conn.execute("BEGIN")
                migration.apply(conn)
                conn.execute(f"PRAGMA user_version = {int(migration.version)}")
                conn.execute("COMMIT")
            except Exception as erro:
                conn.execute("ROLLBACK")
                raise MigrationError(
                    f"Falha ao migrar o banco de notas para a versão "
                    f"{migration.version} ({migration.descricao}): {erro}. "
                    f"Nenhum dado foi alterado."
                ) from erro
            log.info("migration %d aplicada: %s",
                     migration.version, migration.descricao)
            aplicadas.append(migration.version)
    finally:
        conn.isolation_level = isolation_anterior
    return aplicadas


def _backup(db_path: Path, versao: int, agora: datetime) -> None:
    nome = f"{db_path.name}.bak-v{versao}-{agora.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(db_path, db_path.with_name(nome))
    log.info("backup do banco criado: %s", nome)
    backups = sorted(db_path.parent.glob(db_path.name + ".bak-*"))
    for velho in backups[:-BACKUPS_MANTIDOS]:
        velho.unlink()
        log.info("backup antigo removido: %s", velho.name)
