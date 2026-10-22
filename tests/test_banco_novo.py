"""Banco vazio: as migrações criam tudo e o modo demo semeia uma única vez.
Mesmas condições de test_postgres.py: PDV_TEST_PG=1 e um banco DESCARTÁVEL."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("PDV_TEST_PG") != "1", reason="defina PDV_TEST_PG=1")

from pdv import config, demo
from pdv.db import local, migrations, pool


def _contar(tabela):
    with pool.conexao() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {tabela}")
        return cur.fetchone()[0]


@pytest.fixture(scope="module", autouse=True)
def banco_vazio(tmp_path_factory):
    config.LOCAL_DB = str(tmp_path_factory.mktemp("sq") / "t.db")
    config.MODO_DEV = True
    local.inicializar()
    assert pool.iniciar_pool()
    with pool.conexao() as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        conn.commit()
    yield
    pool.fechar_pool()


def test_migracao_cria_schema_completo_em_banco_vazio():
    assert migrations.migrar_banco()
    for tabela in ("produtos", "clientes", "caixas", "vendas", "itens_venda", "usuarios", "promocoes"):
        assert _contar(tabela) >= 0
    assert _contar("usuarios") == 3  # usuários de teste do modo DEV


def test_semear_insere_uma_vez():
    assert demo.semear()
    assert not demo.semear()
    assert _contar("produtos") == len(demo.PRODUTOS)
    assert _contar("promocoes") == len(demo.PROMOCOES)
    assert _contar("clientes") == 1
