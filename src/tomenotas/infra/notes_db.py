"""Armazenamento de notas em SQLite: busca FTS5, tags, favoritos (v3).

O banco (~/.local/share/tomenotas/notes.db) é a fonte da verdade. Decisão
do ROADMAP implementada como espelho: cada nota mantém um .txt em notes/
para os scripts legados (ler.sh/listar.sh) continuarem funcionando, e .txt
criados por fora do daemon (ex.: gravar.sh legado) são importados na
abertura seguinte.

Mesmo contrato do NoteStore de arquivos (save/list/delete + Note.matches)
mais favoritos, tags e search() com filtros combináveis.
"""

import logging
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from ..domain.note import DbNote
from .migrations import apply_migrations

log = logging.getLogger("tomenotas.notes_db")

_STEM_TS = re.compile(r"^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})")


class SqliteNoteStore:
    def __init__(self, db_path, notes_dir: Path, now=datetime.now):
        self.notes_dir = Path(notes_dir)
        self._now = now
        # save() roda na thread de transcrição; o resto na thread principal
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.isolation_level = None  # autocommit fora das migrations
        self._conn.execute("PRAGMA foreign_keys = ON")

        caminho = Path(db_path) if str(db_path) != ":memory:" else None
        apply_migrations(self._conn, db_path=caminho)

        importadas = self._importa_txt()
        if importadas:
            log.info("%d nota(s) .txt importada(s) para o banco", importadas)

    def close(self) -> None:
        self._conn.close()

    def __del__(self):  # pragma: no cover - depende do momento do GC
        try:
            self._conn.close()
        except Exception:
            pass

    # ---------------- contrato básico (core/janela) ----------------

    def save(self, texto: str) -> DbNote:
        with self._lock:
            agora = self._now()
            self.notes_dir.mkdir(parents=True, exist_ok=True)
            base = agora.strftime("%Y-%m-%d_%H-%M-%S")
            nome, contador = f"{base}.txt", 2
            while (self.notes_dir / nome).exists():
                nome = f"{base}-{contador}.txt"
                contador += 1
            (self.notes_dir / nome).write_text(texto, encoding="utf-8")
            cursor = self._conn.execute(
                "INSERT INTO notes (created_at, text, favorite, filename) "
                "VALUES (?, ?, 0, ?)",
                (agora.isoformat(timespec="seconds"), texto, nome),
            )
            return self._nota(cursor.lastrowid)

    def list(self) -> list[DbNote]:
        return self.search()

    def delete(self, nota: DbNote) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM notes WHERE id = ?", (nota.id,))
            if nota.filename:
                (self.notes_dir / nota.filename).unlink(missing_ok=True)

    # ---------------- favoritos e tags ----------------

    def set_favorite(self, nota_id: int, valor: bool) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE notes SET favorite = ? WHERE id = ?",
                (int(bool(valor)), nota_id),
            )

    def add_tag(self, nota_id: int, nome: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO tags (name) VALUES (?)", (nome,)
            )
            # name é UNIQUE COLLATE NOCASE: "Compras" e "compras" são a mesma
            tag_id = self._conn.execute(
                "SELECT id FROM tags WHERE name = ?", (nome,)
            ).fetchone()[0]
            self._conn.execute(
                "INSERT OR IGNORE INTO note_tags (note_id, tag_id) "
                "VALUES (?, ?)",
                (nota_id, tag_id),
            )

    def remove_tag(self, nota_id: int, nome: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM note_tags WHERE note_id = ? AND tag_id = "
                "(SELECT id FROM tags WHERE name = ?)",
                (nota_id, nome),
            )

    def tags(self) -> list[str]:
        with self._lock:
            return [linha[0] for linha in self._conn.execute(
                "SELECT name FROM tags ORDER BY name COLLATE NOCASE"
            )]

    def tags_com_contagem(self) -> list[tuple[str, int]]:
        """[(nome, nº de notas)] — para a tela de gestão de tags."""
        with self._lock:
            return [tuple(linha) for linha in self._conn.execute(
                "SELECT t.name, COUNT(nt.note_id) FROM tags t "
                "LEFT JOIN note_tags nt ON nt.tag_id = t.id "
                "GROUP BY t.id ORDER BY t.name COLLATE NOCASE"
            )]

    def create_tag(self, nome: str) -> bool:
        """Cria uma tag avulsa (sem nota). Devolve False se já existia."""
        nome = nome.strip()
        if not nome:
            raise ValueError("o nome da tag não pode ser vazio")
        with self._lock:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO tags (name) VALUES (?)", (nome,)
            )
            return cursor.rowcount > 0

    def delete_tag(self, nome: str) -> None:
        """Apaga a tag; as notas ficam, só perdem a associação (cascade)."""
        with self._lock:
            self._conn.execute("DELETE FROM tags WHERE name = ?", (nome,))

    def rename_tag(self, antigo: str, novo: str) -> None:
        """Renomeia a tag preservando as associações. Se o novo nome já é
        outra tag, faz merge (as notas da antiga passam para a existente).
        Mudança só de caixa ("compras" → "Compras") é troca de rótulo."""
        novo = novo.strip()
        if not novo:
            raise ValueError("o nome da tag não pode ser vazio")
        with self._lock:
            origem = self._conn.execute(
                "SELECT id FROM tags WHERE name = ?", (antigo,)
            ).fetchone()
            if origem is None:
                return
            alvo = self._conn.execute(
                "SELECT id FROM tags WHERE name = ?", (novo,)
            ).fetchone()
            if alvo is None or alvo[0] == origem[0]:
                self._conn.execute(
                    "UPDATE tags SET name = ? WHERE id = ?",
                    (novo, origem[0]),
                )
            else:  # merge na tag existente
                self._conn.execute(
                    "INSERT OR IGNORE INTO note_tags (note_id, tag_id) "
                    "SELECT note_id, ? FROM note_tags WHERE tag_id = ?",
                    (alvo[0], origem[0]),
                )
                self._conn.execute(
                    "DELETE FROM tags WHERE id = ?", (origem[0],)
                )

    # ---------------- busca (filtros combináveis) ----------------

    def search(self, texto: str = "", tags=(), favoritos: bool = False,
               desde: str | None = None) -> list[DbNote]:
        with self._lock:
            sql = "SELECT n.id FROM notes n"
            condicoes, params = [], []

            consulta_fts = self._consulta_fts(texto)
            if consulta_fts:
                sql += " JOIN notes_fts ON notes_fts.rowid = n.id"
                condicoes.append("notes_fts MATCH ?")
                params.append(consulta_fts)
            if tags:
                marcadores = ", ".join("?" * len(tags))
                condicoes.append(
                    "n.id IN (SELECT nt.note_id FROM note_tags nt "
                    "JOIN tags t ON t.id = nt.tag_id "
                    f"WHERE t.name IN ({marcadores}) "
                    "GROUP BY nt.note_id HAVING COUNT(DISTINCT t.id) = ?)"
                )
                params.extend(tags)
                params.append(len(tags))
            if favoritos:
                condicoes.append("n.favorite = 1")
            if desde:
                condicoes.append("n.created_at >= ?")
                params.append(desde)

            if condicoes:
                sql += " WHERE " + " AND ".join(condicoes)
            # com texto: ranking de relevância; sem texto: mais recente antes
            sql += (" ORDER BY bm25(notes_fts)" if consulta_fts
                    else " ORDER BY n.created_at DESC, n.id DESC")

            ids = [linha[0] for linha in self._conn.execute(sql, params)]
            return [self._nota(nota_id) for nota_id in ids]

    @staticmethod
    def _consulta_fts(texto: str) -> str | None:
        """Sanitiza a busca do usuário para a sintaxe FTS5: cada palavra
        vira um termo com prefixo ("palavra"*), combinadas com AND."""
        tokens = re.findall(r"\w+", texto)
        if not tokens:
            return None
        return " ".join(f'"{token}"*' for token in tokens)

    # ---------------- internos ----------------

    def _nota(self, nota_id: int) -> DbNote:
        linha = self._conn.execute(
            "SELECT id, created_at, text, favorite, filename "
            "FROM notes WHERE id = ?", (nota_id,)
        ).fetchone()
        etiquetas = tuple(t[0] for t in self._conn.execute(
            "SELECT t.name FROM tags t "
            "JOIN note_tags nt ON nt.tag_id = t.id "
            "WHERE nt.note_id = ? ORDER BY t.name COLLATE NOCASE",
            (nota_id,),
        ))
        return DbNote(
            id=linha[0], created_at=linha[1], text=linha[2],
            favorite=bool(linha[3]), tags=etiquetas, filename=linha[4],
        )

    def _importa_txt(self) -> int:
        """Importa .txt de notes/ que ainda não estão no banco (notas da
        era pré-SQLite e as criadas pelo gravar.sh legado)."""
        if not self.notes_dir.is_dir():
            return 0
        conhecidos = {linha[0] for linha in self._conn.execute(
            "SELECT filename FROM notes WHERE filename IS NOT NULL"
        )}
        total = 0
        for txt in sorted(self.notes_dir.glob("*.txt")):
            if txt.name in conhecidos:
                continue
            self._conn.execute(
                "INSERT INTO notes (created_at, text, favorite, filename) "
                "VALUES (?, ?, 0, ?)",
                (
                    self._created_at_de(txt),
                    txt.read_text(encoding="utf-8", errors="replace"),
                    txt.name,
                ),
            )
            total += 1
        return total

    @staticmethod
    def _created_at_de(txt: Path) -> str:
        casamento = _STEM_TS.match(txt.stem)
        if casamento:
            return datetime.strptime(
                casamento.group(1), "%Y-%m-%d_%H-%M-%S"
            ).isoformat(timespec="seconds")
        # nome fora do padrão (arquivo criado na mão): usa o mtime
        return datetime.fromtimestamp(
            txt.stat().st_mtime
        ).isoformat(timespec="seconds")
