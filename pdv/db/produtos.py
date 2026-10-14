"""Produtos: consulta online com fallback para o cache local, e sincronização do cache."""
from __future__ import annotations

import logging

from pdv.db import local
from pdv.db.pool import SemConexao, conexao
from pdv.money import D

log = logging.getLogger(__name__)

_SQL_PRODUTO = """SELECT id, codigo_barras, nome, preco, quantidade_estoque FROM produtos"""


def _para_dict(linha) -> dict:
    return {
        "id": linha[0],
        "codigo_barras": linha[1],
        "nome": linha[2],
        "preco": D(linha[3]),
        "estoque": D(linha[4]),
    }


def buscar_produto(codigo: str) -> dict | None:
    """Produto pelo código de barras. Só usa o cache se o banco estiver inacessível."""
    try:
        with conexao() as conn, conn.cursor() as cur:
            cur.execute(_SQL_PRODUTO + " WHERE codigo_barras = %s", (codigo,))
            linha = cur.fetchone()
        return _para_dict(linha) if linha else None
    except SemConexao:
        pass
    except Exception:
        log.exception("Erro ao buscar produto no PostgreSQL; usando cache local")

    try:
        return local.buscar_produto_cache(codigo)
    except Exception:
        log.exception("Falha no cache local de produtos")
        return None


def consultar_produtos(termo: str = "", limite: int = 50) -> list[dict]:
    try:
        with conexao() as conn, conn.cursor() as cur:
            cur.execute(
                _SQL_PRODUTO + " WHERE codigo_barras ILIKE %s OR nome ILIKE %s ORDER BY nome ASC LIMIT %s",
                (f"%{termo}%", f"%{termo}%", limite),
            )
            return [_para_dict(r) for r in cur.fetchall()]
    except SemConexao:
        pass
    except Exception:
        log.exception("Erro na consulta de estoque; usando cache local")

    try:
        return local.consultar_cache(termo, limite)
    except Exception:
        log.exception("Falha no cache local de produtos")
        return []


def sincronizar_cache() -> bool:
    """Copia produtos e promoções ativas para o SQLite. Não apaga o cache se vier vazio."""
    try:
        with conexao() as conn, conn.cursor() as cur:
            cur.execute(_SQL_PRODUTO)
            produtos = [(r[0], r[1], r[2], str(D(r[3])), str(D(r[4]))) for r in cur.fetchall()]
            cur.execute(
                """SELECT codigo_barras, descricao_campanha, tipo_desconto, valor_desconto,
                          COALESCE(qtd_necessaria, 1), COALESCE(qtd_pagante, 1), data_inicio, data_fim
                   FROM promocoes WHERE ativa = TRUE AND data_fim >= CURRENT_TIMESTAMP ORDER BY id"""
            )
            promocoes = [
                (
                    r[0], r[1], r[2], str(D(r[3])), int(r[4]), int(r[5]),
                    r[6].strftime("%Y-%m-%d %H:%M:%S"), r[7].strftime("%Y-%m-%d %H:%M:%S"),
                )
                for r in cur.fetchall()
            ]
    except SemConexao:
        log.info("Cache não sincronizado: PostgreSQL indisponível.")
        return False
    except Exception:
        log.exception("Erro ao ler dados para o cache")
        return False

    if not produtos:
        log.warning("Tabela de produtos veio vazia; mantendo o cache anterior.")
        return False
    try:
        local.substituir_cache(produtos, promocoes)
    except Exception:
        log.exception("Erro ao gravar o cache local")
        return False
    log.info("Cache local sincronizado: %s produtos, %s promoções.", len(produtos), len(promocoes))
    return True
