"""Persistência do carrinho em andamento (recupera a venda se o PDV for reiniciado)."""
from __future__ import annotations

import logging

from pdv.db.pool import SemConexao, conexao
from pdv.money import D

log = logging.getLogger(__name__)


def salvar_carrinho(caixa_id: int | None, itens: list[dict]) -> None:
    """Melhor esforço: falha aqui nunca deve travar o atendimento."""
    if not caixa_id:
        return
    try:
        with conexao() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO vendas_pendentes (caixa_id) VALUES (%s)
                       ON CONFLICT (caixa_id) DO UPDATE SET data_inicio = vendas_pendentes.data_inicio
                       RETURNING id""",
                    (caixa_id,),
                )
                vp_id = cur.fetchone()[0]
                cur.execute("DELETE FROM itens_venda_pendente WHERE venda_pendente_id = %s", (vp_id,))
                cur.executemany(
                    """INSERT INTO itens_venda_pendente
                       (venda_pendente_id, produto_id, quantidade, preco_unitario, subtotal)
                       VALUES (%s, %s, %s, %s, %s)""",
                    [(vp_id, i["id"], i["quantidade"], i["preco_unit"], i["subtotal"]) for i in itens],
                )
            conn.commit()
    except SemConexao:
        log.info("Carrinho não persistido: sem conexão.")
    except Exception:
        log.exception("Falha ao persistir carrinho pendente")


def carregar_carrinho(caixa_id: int | None) -> list[dict]:
    """Itens da venda interrompida. Traz código de barras e preço de tabela para a UI
    poder recalcular promoções (antes isso se perdia ao restaurar)."""
    if not caixa_id:
        return []
    try:
        with conexao() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT p.id, p.nome, p.codigo_barras, p.preco, p.quantidade_estoque, ivp.quantidade
                   FROM vendas_pendentes vp
                   JOIN itens_venda_pendente ivp ON ivp.venda_pendente_id = vp.id
                   JOIN produtos p ON p.id = ivp.produto_id
                   WHERE vp.caixa_id = %s
                   ORDER BY ivp.id ASC""",
                (caixa_id,),
            )
            return [
                {
                    "id": r[0],
                    "nome": r[1],
                    "codigo_barras": r[2] or "",
                    "preco_tabela": D(r[3]),
                    "estoque": D(r[4]),
                    "quantidade": D(r[5]),
                }
                for r in cur.fetchall()
            ]
    except SemConexao:
        return []
    except Exception:
        log.exception("Erro ao carregar carrinho pendente")
        return []


def limpar_carrinho(caixa_id: int | None) -> None:
    if not caixa_id:
        return
    try:
        with conexao() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM vendas_pendentes WHERE caixa_id = %s", (caixa_id,))
            conn.commit()
    except SemConexao:
        pass
    except Exception:
        log.exception("Erro ao limpar carrinho pendente")
