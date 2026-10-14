"""Testes que não precisam de PostgreSQL."""
from decimal import Decimal

import pytest

from pdv import config
from pdv.db import local
from pdv.db.clientes import val_cpf
from pdv.db.modelos import DadosVenda, Promocao
from pdv.money import D, fmt_brl, fmt_qtd, mascara_moeda, parse_moeda
from pdv.services.promocoes import calcular

# --- dinheiro ---------------------------------------------------------------------

def test_float_acumula_erro_mas_decimal_nao():
    assert sum([0.1] * 3) != 0.3
    assert sum([D("0.1")] * 3) == D("0.3")


def test_formatacao_e_mascara():
    assert fmt_brl(1234.5) == "R$ 1.234,50"
    assert parse_moeda("1.234,56") == Decimal("1234.56")
    assert mascara_moeda("5") == "0,05"
    assert mascara_moeda("") == "0,00"
    assert fmt_qtd(Decimal("3")) == "3"
    assert fmt_qtd(Decimal("1.500")) == "1,5"


# --- CPF -----------------------------------------------------------------------------

def test_cpf_valido_e_invalido():
    assert val_cpf("529.982.247-25") == (True, "529.982.247-25")
    assert val_cpf("52998224725")[0] is True
    assert val_cpf("11111111111")[0] is False
    assert val_cpf("52998224726")[0] is False


def test_cpf_com_segundo_digito_zero_por_resto_10():
    # 100.000.000-00 não existe, mas este tem dígito verificador 0 vindo de resto 10 (bug antigo)
    assert val_cpf("00000000191")[0] is True


# --- promoções --------------------------------------------------------------------------

def _p(tipo, valor="0", nec=1, pag=1):
    return Promocao(tipo, D(valor), nec, pag, "teste")


def test_sem_promocao():
    assert calcular(None, 3, D("2.50")) == (D("2.50"), D("7.50"))


def test_percentual_e_valor_fixo_e_preco_final():
    assert calcular(_p("PERCENTUAL", "10"), 2, D("10.00")) == (D("9.00"), D("18.00"))
    assert calcular(_p("VALOR_FIXO", "1.50"), 2, D("10.00")) == (D("8.50"), D("17.00"))
    assert calcular(_p("PRECO_FINAL", "7.99"), 3, D("10.00")) == (D("7.99"), D("23.97"))


def test_leve_3_pague_2():
    promo = _p("LEVE_X_PAGUE_Y", nec=3, pag=2)
    assert calcular(promo, 3, D("6.00"))[1] == D("12.00")
    assert calcular(promo, 4, D("6.00"))[1] == D("18.00")
    assert calcular(promo, 6, D("6.00"))[1] == D("24.00")


def test_lote_preco_fixo():
    promo = _p("LOTE_PRECO_FIXO", valor="10.00", nec=3)
    assert calcular(promo, 4, D("4.00"))[1] == D("14.00")


# --- serialização da venda -------------------------------------------------------------

def _venda():
    return DadosVenda(
        itens=[{"id": 1, "nome": "Arroz", "quantidade": D("2"), "preco_unit": D("5.25"), "subtotal": D("10.50")}],
        total=D("10.50"), forma="Dinheiro", recebido=D("20.00"), troco=D("9.50"), caixa_id=7, cliente_id=3,
    )


def test_roundtrip_json_preserva_decimais_e_uuid():
    v = _venda()
    volta = DadosVenda.from_json(v.to_json())
    assert volta.uuid_venda == v.uuid_venda
    assert volta.itens[0]["subtotal"] == D("10.50")
    assert volta.troco == D("9.50")


def test_json_legado_com_floats_continua_valido():
    legado = '{"itens":[{"id":1,"nome":"X","quantidade":1,"preco_unit":2.5,"subtotal":2.5}],"total":2.5,' \
             '"forma":"PIX","recebido":2.5,"troco":0.0,"caixa_id":1,"cliente_id":null,"cpf_nota":null}'
    v = DadosVenda.from_json(legado, uuid_venda="abc")
    assert v.total == D("2.5") and v.uuid_venda == "abc"


# --- SQLite local ------------------------------------------------------------------------

@pytest.fixture()
def sqlite_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_DB", str(tmp_path / "t.db"))
    local.inicializar()


def test_fila_offline_e_estado(sqlite_tmp):
    v = _venda()
    reg = local.salvar_venda_offline(v)
    assert local.contar_vendas_offline() == 1
    (rid, uuid_, js, tent), = local.listar_vendas_offline(10)
    assert rid == reg and uuid_ == v.uuid_venda and tent == 0
    local.registrar_falha_offline(reg, "erro x")
    assert local.listar_vendas_offline(1) == []  # estourou o limite de tentativas
    local.remover_venda_offline(reg)
    assert local.contar_vendas_offline() == 0

    local.salvar_estado("caixa", {"id": 5})
    assert local.ler_estado("caixa") == {"id": 5}
    local.salvar_estado("caixa", None)
    assert local.ler_estado("caixa") is None


def test_cache_troca_atomica_e_busca(sqlite_tmp):
    local.substituir_cache([(1, "789", "Leite", "4.50", "10")], [])
    assert local.buscar_produto_cache("789")["preco"] == D("4.50")
    with pytest.raises(Exception):
        local.substituir_cache([(2, "1", "A", "1", "1"), (2, "2", "B", "1", "1")], [])  # PK duplicada
    assert local.buscar_produto_cache("789") is not None  # cache antigo preservado


def test_migracao_de_fila_antiga_sem_uuid(tmp_path, monkeypatch):
    import sqlite3
    caminho = str(tmp_path / "antigo.db")
    monkeypatch.setattr(config, "LOCAL_DB", caminho)
    c = sqlite3.connect(caminho)
    c.execute("CREATE TABLE vendas_offline (id INTEGER PRIMARY KEY AUTOINCREMENT, dados_venda TEXT, data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    c.execute("INSERT INTO vendas_offline (dados_venda) VALUES ('{}')")
    c.commit(); c.close()
    local.inicializar()
    (_, uuid_, _, _), = local.listar_vendas_offline(10)
    assert uuid_  # ganhou identificador
