"""Acesso a promoções (PostgreSQL e cache local). O cálculo fica em services/promocoes.py."""
from __future__ import annotations

import logging

from pdv.db import local
from pdv.db.modelos import Promocao
from pdv.db.pool import SemConexao, conexao
from pdv.money import D

log = logging.getLogger(__name__)


def _de_linha(descricao, tipo, valor, qtd_nec, qtd_pag) -> Promocao:
    return Promocao(
        tipo=tipo,
        valor=D(valor),
        qtd_necessaria=int(qtd_nec or 1),
        qtd_pagante=int(qtd_pag or 1),
        campanha=descricao,
    )


def buscar_promocao(codigo_barras: str) -> Promocao | None:
    """Promoção vigente do produto. Banco fora do ar -> usa o cache (antes a venda saía sem promoção)."""
    if not codigo_barras:
        return None
    try:
        with conexao() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT descricao_campanha, tipo_desconto, valor_desconto, qtd_necessaria, qtd_pagante
                   FROM promocoes
                   WHERE codigo_barras = %s AND ativa = TRUE
                     AND CURRENT_TIMESTAMP BETWEEN data_inicio AND data_fim
                   ORDER BY id DESC LIMIT 1""",
                (codigo_barras,),
            )
            linha = cur.fetchone()
        return _de_linha(*linha) if linha else None
    except SemConexao:
        pass
    except Exception:
        log.exception("Erro ao buscar promoção; usando cache local")

    try:
        linha = local.promocao_cache(codigo_barras)
        return _de_linha(*linha) if linha else None
    except Exception:
        log.exception("Falha no cache local de promoções")
        return None


def listar_campanhas_ativas() -> list[tuple]:
    try:
        with conexao() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT descricao_campanha, codigo_barras FROM promocoes
                   WHERE ativa = TRUE AND CURRENT_TIMESTAMP BETWEEN data_inicio AND data_fim"""
            )
            return cur.fetchall()
    except SemConexao:
        pass
    except Exception:
        log.exception("Erro ao listar campanhas")
    try:
        return local.campanhas_cache()
    except Exception:
        return []
