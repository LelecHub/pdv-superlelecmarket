"""Gravação de vendas (online e offline) e sincronização da fila offline.

Ponto central da integridade financeira: toda venda carrega um UUID e é gravada com
`INSERT ... ON CONFLICT (uuid_venda) DO NOTHING`. Reenviar a mesma venda (queda entre o
commit e a limpeza da fila, timeout no commit, etc.) nunca duplica nada.
"""
from __future__ import annotations

import logging

from psycopg2 import InterfaceError, OperationalError

from pdv import config
from pdv.db import local
from pdv.db.modelos import DadosVenda, ResultadoVenda
from pdv.db.pool import SemConexao, conexao
from pdv.money import D, arred

log = logging.getLogger(__name__)


class ProdutoNaoEncontrado(Exception):
    pass


def _gravar_venda(cur, dv: DadosVenda) -> tuple[int, bool]:
    """Grava venda, itens, baixa de estoque e pontos. Devolve (venda_id, é_nova).

    Se o UUID já existe, não mexe em estoque nem pontos (já foram aplicados antes).
    """
    cur.execute(
        """INSERT INTO vendas (uuid_venda, total, forma_pagamento, valor_recebido, troco,
                               caixa_id, cliente_id, cpf_nota)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (uuid_venda) DO NOTHING
           RETURNING id""",
        (dv.uuid_venda, dv.total, dv.forma, dv.recebido, dv.troco, dv.caixa_id, dv.cliente_id, dv.cpf_nota),
    )
    linha = cur.fetchone()
    if linha is None:
        cur.execute("SELECT id FROM vendas WHERE uuid_venda = %s", (dv.uuid_venda,))
        return cur.fetchone()[0], False
    venda_id = linha[0]

    for item in dv.itens:
        cur.execute(
            """INSERT INTO itens_venda (venda_id, produto_id, quantidade, preco_unitario, subtotal)
               VALUES (%s, %s, %s, %s, %s)""",
            (venda_id, item["id"], item["quantidade"], item["preco_unit"], item["subtotal"]),
        )
        cur.execute(
            """UPDATE produtos SET quantidade_estoque = COALESCE(quantidade_estoque, 0) - %s
               WHERE id = %s RETURNING quantidade_estoque""",
            (item["quantidade"], item["id"]),
        )
        baixa = cur.fetchone()
        if baixa is None:
            raise ProdutoNaoEncontrado(f"Produto não localizado: {item.get('nome') or item['id']}")
        if D(baixa[0]) < 0:
            # Vender com estoque insuficiente é permitido, mas deixa rastro para o inventário
            cur.execute(
                """INSERT INTO divergencias_estoque (venda_id, produto_id, quantidade_vendida, saldo_apos)
                   VALUES (%s, %s, %s, %s)""",
                (venda_id, item["id"], item["quantidade"], baixa[0]),
            )

    if dv.cliente_id:
        pontos = arred(D(dv.total) / 10)
        cur.execute("UPDATE clientes SET pontos = pontos + %s WHERE id = %s", (pontos, dv.cliente_id))
    return venda_id, True


def _salvar_offline(dv: DadosVenda) -> ResultadoVenda:
    try:
        local_id = local.salvar_venda_offline(dv)
    except Exception as e:
        log.exception("Falha CRÍTICA ao gravar venda offline")
        return ResultadoVenda(False, f"Erro crítico offline: {e}")
    return ResultadoVenda(
        True,
        "[MODO OFFLINE] Venda salva no cache local para sincronização posterior!",
        ref=f"OFF-{local_id:05d}",
        offline=True,
    )


def finalizar_venda(dv: DadosVenda) -> ResultadoVenda:
    try:
        with conexao() as conn:
            with conn.cursor() as cur:
                venda_id, _ = _gravar_venda(cur, dv)
                cur.execute("DELETE FROM vendas_pendentes WHERE caixa_id = %s", (dv.caixa_id,))
            conn.commit()
        return ResultadoVenda(True, f"Venda #{venda_id} finalizada com sucesso!", ref=f"{venda_id:05d}")
    except SemConexao:
        return _salvar_offline(dv)
    except (OperationalError, InterfaceError) as e:
        # A conexão caiu no meio: não sabemos se o commit chegou. Como a venda tem UUID,
        # enfileirar offline é seguro (se já foi gravada, a sincronização reconhece e descarta).
        log.warning("Conexão perdida ao finalizar venda (%s); enfileirando offline.", e)
        return _salvar_offline(dv)
    except ProdutoNaoEncontrado as e:
        return ResultadoVenda(False, str(e))
    except Exception as e:
        log.exception("Erro ao finalizar venda")
        return ResultadoVenda(False, f"Erro no banco: {e}")


def sincronizar_pendentes() -> int:
    """Envia a fila offline. Cada venda é independente: uma defeituosa não trava as outras."""
    pendentes = local.listar_vendas_offline(config.MAX_TENTATIVAS_SYNC)
    if not pendentes:
        return 0

    enviadas = 0
    try:
        with conexao() as conn:
            for reg_id, uuid_venda, json_str, _tentativas in pendentes:
                try:
                    dv = DadosVenda.from_json(json_str, uuid_venda)
                    with conn.cursor() as cur:
                        venda_id, nova = _gravar_venda(cur, dv)
                    conn.commit()
                except (OperationalError, InterfaceError):
                    raise
                except Exception as e:
                    conn.rollback()
                    local.registrar_falha_offline(reg_id, str(e))
                    log.error("Venda offline #%s falhou na sincronização: %s", reg_id, e)
                    continue

                local.remover_venda_offline(reg_id)
                enviadas += 1
                if nova:
                    log.info("Venda offline #%s sincronizada como venda #%s.", reg_id, venda_id)
                else:
                    log.info("Venda offline #%s já existia no servidor (venda #%s); descartada da fila.", reg_id, venda_id)
    except SemConexao:
        pass
    except (OperationalError, InterfaceError) as e:
        log.warning("Conexão perdida durante a sincronização: %s", e)
    return enviadas


# --- Consultas para reimpressão ---------------------------------------------------------

def ultima_venda_id(caixa_id: int) -> int | None:
    """Última venda DESTE caixa (antes era a última do sistema inteiro)."""
    try:
        with conexao() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM vendas WHERE caixa_id = %s ORDER BY id DESC LIMIT 1", (caixa_id,))
            linha = cur.fetchone()
            return linha[0] if linha else None
    except SemConexao:
        return None
    except Exception:
        log.exception("Erro ao obter última venda")
        return None


def obter_dados_venda(venda_id: int) -> tuple[dict | None, list[dict]]:
    try:
        with conexao() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT total, forma_pagamento, valor_recebido, troco FROM vendas WHERE id = %s", (venda_id,)
            )
            v = cur.fetchone()
            if not v:
                return None, []
            cur.execute(
                """SELECT p.nome, iv.quantidade, iv.preco_unitario, iv.subtotal
                   FROM itens_venda iv JOIN produtos p ON p.id = iv.produto_id
                   WHERE iv.venda_id = %s ORDER BY iv.id""",
                (venda_id,),
            )
            itens = [
                {"nome": r[0], "quantidade": D(r[1]), "preco_unit": D(r[2]), "subtotal": D(r[3]), "promo": ""}
                for r in cur.fetchall()
            ]
        return {"total": D(v[0]), "forma": v[1], "recebido": D(v[2]), "troco": D(v[3])}, itens
    except SemConexao:
        return None, []
    except Exception:
        log.exception("Erro ao obter dados da venda")
        return None, []
