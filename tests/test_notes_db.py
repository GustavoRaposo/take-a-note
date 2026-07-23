"""Testes de tomenotas.notes_db — armazenamento SQLite (FTS5, tags, favoritos)."""

from datetime import datetime
from pathlib import Path

from tomenotas.infra.notes_db import SqliteNoteStore

RELOGIO = lambda: datetime(2026, 7, 23, 15, 0, 38)  # noqa: E731


def monta(tmp_path, now=RELOGIO):
    return SqliteNoteStore(tmp_path / "notes.db", tmp_path / "notes", now=now)


# ---------------- save / list / delete ----------------

def test_save_grava_no_banco_e_no_espelho_txt(tmp_path):
    store = monta(tmp_path)
    nota = store.save("minha nota")
    assert nota.text == "minha nota"
    assert nota.created_at == "2026-07-23T15:00:38"
    assert nota.title == "2026-07-23_15-00-38"
    assert not nota.favorite
    assert nota.tags == ()
    espelho = tmp_path / "notes" / "2026-07-23_15-00-38.txt"
    assert espelho.read_text(encoding="utf-8") == "minha nota"


def test_save_no_mesmo_segundo_nao_sobrescreve(tmp_path):
    store = monta(tmp_path)
    store.save("primeira")
    segunda = store.save("segunda")
    assert segunda.title == "2026-07-23_15-00-38-2"
    assert (tmp_path / "notes" / "2026-07-23_15-00-38-2.txt").exists()


def test_list_ordena_mais_recente_primeiro(tmp_path):
    momentos = iter([
        datetime(2026, 7, 21, 10, 0, 0),
        datetime(2026, 7, 23, 9, 0, 0),
        datetime(2026, 7, 22, 12, 0, 0),
    ])
    store = monta(tmp_path, now=lambda: next(momentos))
    store.save("antiga")
    store.save("recente")
    store.save("do meio")
    assert [n.text for n in store.list()] == ["recente", "do meio", "antiga"]


def test_delete_remove_banco_e_espelho(tmp_path):
    store = monta(tmp_path)
    nota = store.save("descartável")
    store.delete(nota)
    assert store.list() == []
    assert not (tmp_path / "notes" / f"{nota.title}.txt").exists()


def test_close_fecha_a_conexao(tmp_path):
    import sqlite3

    import pytest

    store = monta(tmp_path)
    store.save("x")
    store.close()
    with pytest.raises(sqlite3.ProgrammingError):
        store.list()


def test_title_sem_filename_usa_created_at_e_str_e_o_title(tmp_path):
    store = monta(tmp_path)
    nota = store.save("x")
    sem_arquivo = type(nota)(id=1, created_at="2026-07-23T10:00:00",
                             text="x", favorite=False, tags=(),
                             filename=None)
    assert sem_arquivo.title == "2026-07-23 10:00:00"
    assert str(nota) == nota.title


def test_matches_compatibilidade_com_o_filtro_da_janela(tmp_path):
    store = monta(tmp_path)
    store.save("Comprar PÃO na padaria")
    (nota,) = store.list()
    assert nota.matches("pão")
    assert nota.matches("2026-07-23")  # busca também no título
    assert nota.matches("")
    assert not nota.matches("leite")


# ---------------- importação dos .txt ----------------

def test_importa_txt_preexistentes_na_primeira_abertura(tmp_path):
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir(parents=True)
    (notes_dir / "2026-07-20_08-30-00.txt").write_text("do bash", encoding="utf-8")

    store = monta(tmp_path)
    (nota,) = store.list()
    assert nota.text == "do bash"
    assert nota.created_at == "2026-07-20T08:30:00"


def test_reabrir_nao_duplica_importacao(tmp_path):
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir(parents=True)
    (notes_dir / "2026-07-20_08-30-00.txt").write_text("única", encoding="utf-8")
    monta(tmp_path)
    store = monta(tmp_path)  # segunda abertura (ex.: reinício do daemon)
    assert len(store.list()) == 1


def test_txt_criado_depois_e_importado_na_proxima_abertura(tmp_path):
    store = monta(tmp_path)
    store.save("pela UI")
    # gravar.sh legado cria um txt por fora do daemon
    (tmp_path / "notes" / "2026-07-23_20-00-00.txt").write_text(
        "pelo script legado", encoding="utf-8"
    )
    store2 = monta(tmp_path)
    assert {n.text for n in store2.list()} == {"pela UI", "pelo script legado"}


def test_txt_com_nome_fora_do_padrao_usa_mtime(tmp_path):
    notes_dir = tmp_path / "notes"
    notes_dir.mkdir(parents=True)
    (notes_dir / "avulso.txt").write_text("sem timestamp", encoding="utf-8")
    store = monta(tmp_path)
    (nota,) = store.list()
    assert nota.text == "sem timestamp"
    assert nota.created_at  # derivado do mtime, mas presente


# ---------------- favoritos ----------------

def test_favoritar_e_desfavoritar(tmp_path):
    store = monta(tmp_path)
    nota = store.save("importante")
    store.set_favorite(nota.id, True)
    assert store.list()[0].favorite
    store.set_favorite(nota.id, False)
    assert not store.list()[0].favorite


# ---------------- tags ----------------

def test_add_e_remove_tag(tmp_path):
    store = monta(tmp_path)
    nota = store.save("mercado")
    store.add_tag(nota.id, "compras")
    store.add_tag(nota.id, "casa")
    assert store.list()[0].tags == ("casa", "compras")  # ordem alfabética
    store.remove_tag(nota.id, "casa")
    assert store.list()[0].tags == ("compras",)
    assert store.tags() == ["casa", "compras"]  # a tag em si continua


def test_tags_nao_diferenciam_caixa(tmp_path):
    store = monta(tmp_path)
    nota = store.save("x")
    store.add_tag(nota.id, "Compras")
    store.add_tag(nota.id, "compras")  # mesma tag
    assert store.list()[0].tags == ("Compras",)
    assert store.tags() == ["Compras"]


def test_create_tag_cria_avulsa_sem_nota(tmp_path):
    store = monta(tmp_path)
    assert store.create_tag("projetos") is True
    assert store.create_tag("PROJETOS") is False  # já existe (sem caixa)
    assert store.tags() == ["projetos"]
    assert store.tags_com_contagem() == [("projetos", 0)]


def test_create_tag_vazia_levanta_erro(tmp_path):
    import pytest

    store = monta(tmp_path)
    with pytest.raises(ValueError):
        store.create_tag("   ")


def test_delete_tag_remove_associacoes_mas_nao_as_notas(tmp_path):
    store = monta(tmp_path)
    nota = store.save("nota que fica")
    store.add_tag(nota.id, "temporaria")
    store.delete_tag("temporaria")
    assert store.tags() == []
    (sobrou,) = store.list()
    assert sobrou.text == "nota que fica"
    assert sobrou.tags == ()


def test_rename_tag_simples_preserva_associacoes(tmp_path):
    store = monta(tmp_path)
    nota = store.save("x")
    store.add_tag(nota.id, "mercado")
    store.rename_tag("mercado", "compras")
    assert store.tags() == ["compras"]
    assert store.list()[0].tags == ("compras",)


def test_rename_tag_para_nome_existente_faz_merge(tmp_path):
    store = monta(tmp_path)
    a = store.save("a")
    b = store.save("b")
    store.add_tag(a.id, "mercado")
    store.add_tag(b.id, "compras")
    store.add_tag(b.id, "mercado")  # b tem as duas
    store.rename_tag("mercado", "compras")
    assert store.tags() == ["compras"]
    assert {n.text: n.tags for n in store.list()} == {
        "a": ("compras",), "b": ("compras",),
    }


def test_rename_tag_so_de_caixa_atualiza_o_rotulo(tmp_path):
    store = monta(tmp_path)
    nota = store.save("x")
    store.add_tag(nota.id, "compras")
    store.rename_tag("compras", "Compras")
    assert store.tags() == ["Compras"]
    assert store.list()[0].tags == ("Compras",)


def test_rename_tag_inexistente_e_ignorado(tmp_path):
    store = monta(tmp_path)
    store.rename_tag("fantasma", "novo")  # não deve levantar
    assert store.tags() == []


def test_rename_tag_para_vazio_levanta_erro(tmp_path):
    import pytest

    store = monta(tmp_path)
    nota = store.save("x")
    store.add_tag(nota.id, "compras")
    with pytest.raises(ValueError):
        store.rename_tag("compras", "  ")


def test_tags_com_contagem(tmp_path):
    store = monta(tmp_path)
    a = store.save("a")
    b = store.save("b")
    store.add_tag(a.id, "compras")
    store.add_tag(b.id, "compras")
    store.add_tag(a.id, "casa")
    store.create_tag("vazia")
    assert store.tags_com_contagem() == [
        ("casa", 1), ("compras", 2), ("vazia", 0),
    ]


def test_apagar_nota_limpa_associacoes_de_tags(tmp_path):
    store = monta(tmp_path)
    nota = store.save("x")
    store.add_tag(nota.id, "solta")
    store.delete(nota)
    assert store.tags() == ["solta"]  # tag sobrevive, associação não
    outra = store.save("y")
    assert outra.tags == ()


# ---------------- busca (FTS5 + filtros combináveis) ----------------

def povoa(store):
    momentos = iter([
        datetime(2026, 7, 20, 10, 0, 0),
        datetime(2026, 7, 22, 10, 0, 0),
        datetime(2026, 7, 23, 10, 0, 0),
    ])
    store._now = lambda: next(momentos)
    a = store.save("comprar pão e leite no mercado")
    b = store.save("reunião sobre o projeto do mercado municipal")
    c = store.save("ideia de presente de aniversário")
    return a, b, c


def test_busca_texto_com_prefixo(tmp_path):
    store = monta(tmp_path)
    povoa(store)
    textos = [n.text for n in store.search(texto="merc")]
    assert len(textos) == 2
    assert all("mercado" in t for t in textos)


def test_busca_texto_sem_resultado(tmp_path):
    store = monta(tmp_path)
    povoa(store)
    assert store.search(texto="inexistente") == []


def test_busca_com_caracteres_especiais_nao_explode(tmp_path):
    store = monta(tmp_path)
    povoa(store)
    assert store.search(texto='pão " * () -') != []  # sanitizado


def test_busca_multiplas_palavras_exige_todas(tmp_path):
    store = monta(tmp_path)
    povoa(store)
    (nota,) = store.search(texto="mercado municipal")
    assert "municipal" in nota.text


def test_busca_por_tag_e_intersecao(tmp_path):
    store = monta(tmp_path)
    a, b, _ = povoa(store)
    store.add_tag(a.id, "compras")
    store.add_tag(b.id, "trabalho")
    store.add_tag(b.id, "compras")
    assert {n.id for n in store.search(tags=["compras"])} == {a.id, b.id}
    assert [n.id for n in store.search(tags=["compras", "trabalho"])] == [b.id]


def test_busca_so_favoritos(tmp_path):
    store = monta(tmp_path)
    a, _, _ = povoa(store)
    store.set_favorite(a.id, True)
    assert [n.id for n in store.search(favoritos=True)] == [a.id]


def test_busca_por_periodo(tmp_path):
    store = monta(tmp_path)
    povoa(store)
    recentes = store.search(desde="2026-07-22T00:00:00")
    assert len(recentes) == 2


def test_filtros_combinados(tmp_path):
    store = monta(tmp_path)
    a, b, _ = povoa(store)
    store.add_tag(a.id, "compras")
    store.add_tag(b.id, "compras")
    store.set_favorite(b.id, True)
    resultado = store.search(texto="mercado", tags=["compras"],
                             favoritos=True)
    assert [n.id for n in resultado] == [b.id]
