"""Testes de tomenotas.migrations — versionamento do esquema sem perda."""

import sqlite3
from datetime import datetime

import pytest

from tomenotas.domain.errors import MigrationError
from tomenotas.infra.migrations import (
    MIGRATIONS,
    SCHEMA_VERSION,
    Migration,
    apply_migrations,
)

RELOGIO = lambda: datetime(2026, 7, 23, 1, 2, 3)  # noqa: E731


def versao(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def test_banco_novo_aplica_todas_e_registra_versao():
    conn = sqlite3.connect(":memory:")
    aplicadas = apply_migrations(conn)
    assert aplicadas == [m.version for m in MIGRATIONS]
    assert versao(conn) == SCHEMA_VERSION
    # o esquema final existe de verdade
    conn.execute(
        "INSERT INTO notes (created_at, text, favorite, filename) "
        "VALUES ('2026-07-23T00:00:00', 'olá', 0, 'a.txt')"
    )
    conn.close()


def test_reaplicar_e_idempotente():
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)
    assert apply_migrations(conn) == []
    assert versao(conn) == SCHEMA_VERSION
    conn.close()


def test_banco_antigo_migra_preservando_dados():
    conn = sqlite3.connect(":memory:")
    # instala só a v1 (esquema inicial, sem a coluna filename) e popula
    apply_migrations(conn, migrations=MIGRATIONS[:1])
    assert versao(conn) == 1
    conn.execute(
        "INSERT INTO notes (created_at, text, favorite) "
        "VALUES ('2026-07-22T10:00:00', 'nota antiga', 1)"
    )
    conn.commit()

    aplicadas = apply_migrations(conn)  # atualização do programa

    assert aplicadas == [m.version for m in MIGRATIONS[1:]]
    assert versao(conn) == SCHEMA_VERSION
    linha = conn.execute(
        "SELECT text, favorite, filename FROM notes"
    ).fetchone()
    assert linha == ("nota antiga", 1, None)  # nada se perdeu
    conn.close()


def test_migration_que_falha_faz_rollback():
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn)

    def quebra(c):
        c.execute("INSERT INTO tags (name) VALUES ('antes-da-falha')")
        c.execute("ISSO NAO E SQL")

    ruins = MIGRATIONS + [Migration(99, "quebra no meio", quebra)]
    with pytest.raises(MigrationError, match="99"):
        apply_migrations(conn, migrations=ruins)

    assert versao(conn) == SCHEMA_VERSION  # versão não avançou
    assert conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 0
    conn.close()


def test_atualizacao_faz_backup_do_arquivo(tmp_path):
    db = tmp_path / "notes.db"
    conn = sqlite3.connect(db)
    apply_migrations(conn, db_path=db, migrations=MIGRATIONS[:1], now=RELOGIO)
    conn.close()

    conn = sqlite3.connect(db)
    apply_migrations(conn, db_path=db, now=RELOGIO)

    backups = list(tmp_path.glob("notes.db.bak-*"))
    assert len(backups) == 1
    assert "bak-v1-" in backups[0].name  # versão de onde partiu
    conn.close()


def test_banco_novo_nao_gera_backup(tmp_path):
    db = tmp_path / "notes.db"
    conn = sqlite3.connect(db)
    apply_migrations(conn, db_path=db, now=RELOGIO)
    assert list(tmp_path.glob("notes.db.bak-*")) == []
    conn.close()


def test_backups_antigos_sao_podados(tmp_path):
    db = tmp_path / "notes.db"
    for sufixo in ["v1-20260101-000000", "v1-20260102-000000",
                   "v1-20260103-000000"]:
        (tmp_path / f"notes.db.bak-{sufixo}").write_bytes(b"velho")

    conn = sqlite3.connect(db)
    apply_migrations(conn, db_path=db, migrations=MIGRATIONS[:1], now=RELOGIO)
    conn.close()
    conn = sqlite3.connect(db)
    apply_migrations(conn, db_path=db, now=RELOGIO)  # gera o 4º backup

    conn.close()
    backups = sorted(p.name for p in tmp_path.glob("notes.db.bak-*"))
    assert len(backups) == 3  # mantém só os 3 mais recentes
    assert "notes.db.bak-v1-20260101-000000" not in backups
