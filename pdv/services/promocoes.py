"""Cálculo de promoções (puro, em Decimal) e atalhos que consultam o banco/cache."""
from __future__ import annotations

from decimal import Decimal

from pdv.db import promocoes as repo
from pdv.db.modelos import Promocao
from pdv.money import ZERO, D, arred


def calcular(promo: Promocao | None, quantidade, preco_tabela) -> tuple[Decimal, Decimal]:
    """Devolve (preço unitário efetivo, subtotal). O subtotal é a verdade; o unitário é para exibição."""
    qtd = D(quantidade)
    preco = D(preco_tabela)
    if promo is None or qtd <= 0:
        return preco, arred(qtd * preco)

    t, v = promo.tipo, promo.valor
    if t == "PERCENTUAL":
        unit = arred(preco * (1 - v / Decimal(100)))
        return unit, arred(qtd * unit)
    if t == "VALOR_FIXO":
        unit = arred(max(ZERO, preco - v))
        return unit, arred(qtd * unit)
    if t == "PRECO_FINAL":
        unit = arred(v)
        return unit, arred(qtd * unit)
    if t == "LEVE_X_PAGUE_Y" and promo.qtd_necessaria > 0 and promo.qtd_pagante > 0:
        grupos = qtd // promo.qtd_necessaria
        restantes = qtd - grupos * promo.qtd_necessaria
        subtotal = arred(grupos * promo.qtd_pagante * preco + restantes * preco)
        return arred(subtotal / qtd), subtotal
    if t == "LOTE_PRECO_FIXO" and promo.qtd_necessaria > 0:
        lotes = qtd // promo.qtd_necessaria
        restantes = qtd - lotes * promo.qtd_necessaria
        subtotal = arred(lotes * v + restantes * preco)
        return arred(subtotal / qtd), subtotal
    return preco, arred(qtd * preco)


def aplicar(codigo_barras: str, quantidade, preco_tabela) -> tuple[Decimal, Decimal, str]:
    """(preço unitário efetivo, subtotal, nome da campanha ou '')."""
    promo = repo.buscar_promocao(codigo_barras)
    unit, subtotal = calcular(promo, quantidade, preco_tabela)
    return unit, subtotal, (promo.campanha if promo else "")


def campanhas_ativas() -> list[tuple]:
    return repo.listar_campanhas_ativas()
