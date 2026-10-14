"""Integração com PostgreSQL real. Rode com PDV_TEST_PG=1 e DB_HOST/DB_PORT/DB_USER/DB_PASS/DB_NAME definidos
apontando para um banco DESCARTÁVEL (as tabelas são recriadas)."""
import os
import threading
from decimal import Decimal

import pytest

pytestmark = pytest.mark.skipif(os.getenv("PDV_TEST_PG") != "1", reason="defina PDV_TEST_PG=1")

from pdv import config
from pdv.db import (
    caixa,
    local,
    migrations,
    pool,
    produtos,
    usuarios,
    vendas,
)
from pdv.db.modelos import DadosVenda
from pdv.money import D

BASE = """
DROP SCHEMA public CASCADE; CREATE SCHEMA public;
CREATE TABLE produtos (id SERIAL PRIMARY KEY, codigo_barras VARCHAR(50), nome VARCHAR(150),
    preco NUMERIC(10,2), quantidade_estoque NUMERIC(10,3));
CREATE TABLE clientes (id SERIAL PRIMARY KEY, nome VARCHAR(100), cpf VARCHAR(14) UNIQUE, pontos NUMERIC(10,2) DEFAULT 0);
CREATE TABLE caixas (id SERIAL PRIMARY KEY, operador VARCHAR(100), saldo_abertura NUMERIC(10,2),
    data_abertura TIMESTAMP DEFAULT CURRENT_TIMESTAMP, status VARCHAR(20));
CREATE TABLE vendas (id SERIAL PRIMARY KEY, total NUMERIC(10,2), forma_pagamento VARCHAR(30),
    valor_recebido NUMERIC(10,2), troco NUMERIC(10,2), caixa_id INT REFERENCES caixas(id),
    cliente_id INT REFERENCES clientes(id), cpf_nota VARCHAR(14), data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE itens_venda (id SERIAL PRIMARY KEY, venda_id INT REFERENCES vendas(id), produto_id INT REFERENCES produtos(id),
    quantidade NUMERIC(10,3), preco_unitario NUMERIC(10,2), subtotal NUMERIC(10,2));
"""


def _q(sql, params=None, um=True):
    with pool.conexao() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        r = None if cur.description is None else (cur.fetchone() if um else cur.fetchall())
        conn.commit()
        return r


@pytest.fixture(scope="module", autouse=True)
def banco(tmp_path_factory):
    config.LOCAL_DB = str(tmp_path_factory.mktemp("sq") / "t.db")
    config.MODO_DEV = True
    local.inicializar()
    assert pool.iniciar_pool()
    with pool.conexao() as conn, conn.cursor() as cur:
        cur.execute(BASE)
        conn.commit()
    assert migrations.migrar_banco()
    with pool.conexao() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO produtos (codigo_barras, nome, preco, quantidade_estoque) VALUES ('111','Arroz',5.25,10),('222','Feijao',8.00,1)")
        cur.execute("INSERT INTO clientes (nome, cpf) VALUES ('Ana','529.982.247-25')")
        conn.commit()
    yield
    pool.fechar_pool()


def _venda(caixa_id, qtd="2", produto_id=1, cliente_id=None):
    sub = D("5.25") * D(qtd)
    return DadosVenda(
        itens=[{"id": produto_id, "nome": "Arroz", "quantidade": D(qtd), "preco_unit": D("5.25"), "subtotal": sub}],
        total=sub, forma="Dinheiro", recebido=sub, troco=D("0"), caixa_id=caixa_id, cliente_id=cliente_id,
    )


@pytest.fixture()
def cx():
    cid, _ = caixa.abrir_caixa(1, "Op", D("100"), 1)
    return cid


def test_migracao_idempotente_e_so_dev_cria_usuarios():
    assert migrations.migrar_banco()
    assert _q("SELECT COUNT(*) FROM public.usuarios")[0] == 3


def test_senha_em_texto_puro_vira_bcrypt_e_hash_nao_serve_como_senha():
    _q("INSERT INTO public.usuarios (matricula, nome, senha_hash, perfil) VALUES ('5000','Legado','segredo','OPERADOR')")
    migrations.migrar_banco()
    assert _q("SELECT senha_hash FROM public.usuarios WHERE matricula='5000'")[0].startswith("$2")
    assert usuarios.autenticar("5000", "segredo")[0]["nome"] == "Legado"
    hash_ = _q("SELECT senha_hash FROM public.usuarios WHERE matricula='1001'")[0]
    assert usuarios.autenticar("1001", hash_)[0] is None  # o hash em si não loga mais


def test_login_bloqueia_apos_falhas():
    for _ in range(config.MAX_FALHAS_LOGIN):
        assert usuarios.autenticar("2001", "errada")[0] is None
    user, erro = usuarios.autenticar("2001", "4321")  # senha certa, mas bloqueado
    assert user is None and "Aguarde" in erro
    usuarios._falhas.clear()
    assert usuarios.autenticar("2001", "4321")[0]["perfil"] == "GERENTE"


def test_supervisor_precisa_do_perfil():
    usuarios._falhas.clear()
    assert usuarios.autorizar_supervisor("1001", "1234")[0] is None
    assert usuarios.autorizar_supervisor("2001", "4321")[0]["nome"] == "Gerente Teste"


def test_venda_online_baixa_estoque_pontos_e_e_idempotente(cx):
    est0 = _q("SELECT quantidade_estoque FROM produtos WHERE id=1")[0]
    v = _venda(cx, "2", cliente_id=1)
    r1 = vendas.finalizar_venda(v)
    r2 = vendas.finalizar_venda(v)  # mesmo UUID: reenvio
    assert r1.ok and not r1.offline and r2.ok and r1.ref == r2.ref
    assert _q("SELECT COUNT(*) FROM vendas WHERE uuid_venda=%s", (v.uuid_venda,))[0] == 1
    assert _q("SELECT quantidade_estoque FROM produtos WHERE id=1")[0] == est0 - 2  # baixou só uma vez
    assert _q("SELECT pontos FROM clientes WHERE id=1")[0] == Decimal("1.05")


def test_estoque_negativo_fica_registrado(cx):
    v = _venda(cx, "3", produto_id=2)
    assert vendas.finalizar_venda(v).ok
    assert _q("SELECT saldo_apos FROM divergencias_estoque ORDER BY id DESC LIMIT 1")[0] == Decimal("-2.000")


def test_produto_inexistente_nao_grava_nada(cx):
    antes = _q("SELECT COUNT(*) FROM vendas")[0]
    r = vendas.finalizar_venda(_venda(cx, "1", produto_id=9999))
    assert not r.ok
    assert _q("SELECT COUNT(*) FROM vendas")[0] == antes


def test_offline_sync_nao_duplica_mesmo_se_cair_antes_de_limpar_a_fila(cx):
    v = _venda(cx, "1", cliente_id=1)
    # simula: servidor já gravou (commit ok) mas o PDV caiu antes de apagar da fila local
    vendas.finalizar_venda(v)
    local.salvar_venda_offline(v)
    est = _q("SELECT quantidade_estoque FROM produtos WHERE id=1")[0]
    pontos = _q("SELECT pontos FROM clientes WHERE id=1")[0]
    assert vendas.sincronizar_pendentes() == 1
    assert _q("SELECT COUNT(*) FROM vendas WHERE uuid_venda=%s", (v.uuid_venda,))[0] == 1
    assert _q("SELECT quantidade_estoque FROM produtos WHERE id=1")[0] == est
    assert _q("SELECT pontos FROM clientes WHERE id=1")[0] == pontos
    assert local.contar_vendas_offline() == 0


def test_venda_offline_entra_com_pontos_e_defeituosa_nao_trava_a_fila(cx):
    boa = _venda(cx, "1", cliente_id=1)
    ruim = _venda(cx, "1", produto_id=9999)
    local.salvar_venda_offline(ruim)  # primeiro da fila e defeituosa
    local.salvar_venda_offline(boa)
    pontos0 = _q("SELECT pontos FROM clientes WHERE id=1")[0]
    assert vendas.sincronizar_pendentes() == 1
    assert _q("SELECT pontos FROM clientes WHERE id=1")[0] > pontos0  # pontos da venda offline contam
    restantes = local.listar_vendas_offline(99)
    assert len(restantes) == 1 and restantes[0][3] == 1  # só a ruim, com 1 tentativa
    local.remover_venda_offline(restantes[0][0])


def test_sincronizacao_concorrente_nao_duplica(cx):
    v = _venda(cx, "1")
    local.salvar_venda_offline(v)
    ts = [threading.Thread(target=vendas.sincronizar_pendentes) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert _q("SELECT COUNT(*) FROM vendas WHERE uuid_venda=%s", (v.uuid_venda,))[0] == 1


def test_caixa_por_pdv_e_fechamento_com_decimal(cx):
    assert caixa.obter_caixa_aberto(1)["id"] is not None
    caixa.registrar_sangria(cx, D("20.00"), "cofre", 2)
    vendas.finalizar_venda(_venda(cx, "1"))
    d = caixa.dados_fechamento_turno(cx, D("90.25"))
    assert d["dinheiro_sistema"] == D("100") + D("5.25") - D("20.00")
    assert d["diferenca"] == D("5.00") and d["houve_quebra"]
    assert caixa.dados_fechamento_dia()["qtd_vendas"] >= 1
    assert caixa.fechar_caixa(cx, D("90.25"))[0]
    assert not caixa.fechar_caixa(cx, D("0"))[0]


def test_cache_sincroniza_e_atende_offline(cx):
    assert produtos.sincronizar_cache()
    assert local.buscar_produto_cache("111")["preco"] == D("5.25")


def test_banco_fora_do_ar_cai_no_offline_e_volta():
    pool.fechar_pool()
    antigo = config.db_config

    def porta_errada():
        c = antigo(); c["port"] = 1; return c
    config.db_config = porta_errada
    pool._ultima_tentativa = 0
    try:
        r = vendas.finalizar_venda(_venda(1, "1"))
        assert r.ok and r.offline and r.ref.startswith("OFF-")
        assert produtos.buscar_produto("111")["nome"] == "Arroz"  # veio do cache
    finally:
        config.db_config = antigo
    pool._ultima_tentativa = 0
    assert pool.iniciar_pool()  # voltou sozinho
    assert vendas.sincronizar_pendentes() >= 0
