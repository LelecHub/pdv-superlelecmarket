"""Turnos de caixa, sangrias, auditoria de cancelamentos e dados de fechamento."""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal

from pdv.constantes import FORMA_DINHEIRO
from pdv.db.pool import SemConexao, conexao
from pdv.money import ZERO, D, fmt_brl

log = logging.getLogger(__name__)

_SEM_BANCO = "Sem conexão com a base de dados"


def obter_caixa_aberto(numero_pdv: int) -> dict | None:
    """Caixa aberto DESTE PDV. Levanta SemConexao se o banco estiver fora (quem chama usa o estado local).

    Antes pegava o último caixa aberto de qualquer PDV, então um segundo PDV assumia o turno do primeiro.
    Caixas antigos sem numero_pdv continuam sendo reconhecidos.
    """
    with conexao() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT c.id, c.operador, c.saldo_abertura, c.data_abertura, c.usuario_id, u.perfil
               FROM caixas c LEFT JOIN public.usuarios u ON u.id = c.usuario_id
               WHERE c.status = 'ABERTO' AND (c.numero_pdv = %s OR c.numero_pdv IS NULL)
               ORDER BY c.id DESC LIMIT 1""",
            (numero_pdv,),
        )
        r = cur.fetchone()
    if not r:
        return None
    return {
        "id": r[0],
        "operador": r[1],
        "saldo_inicial": D(r[2]),
        "usuario_id": r[4],
        "perfil": (r[5] or "OPERADOR"),
    }


def abrir_caixa(usuario_id: int, nome_operador: str, saldo_inicial: Decimal, numero_pdv: int):
    try:
        with conexao() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO caixas (operador, saldo_abertura, status, usuario_id, numero_pdv)
                       VALUES (%s, %s, 'ABERTO', %s, %s) RETURNING id""",
                    (nome_operador, saldo_inicial, usuario_id, numero_pdv),
                )
                caixa_id = cur.fetchone()[0]
            conn.commit()
        return caixa_id, f"Caixa #{caixa_id} aberto com sucesso!"
    except SemConexao:
        return None, _SEM_BANCO
    except Exception as e:
        log.exception("Erro ao abrir caixa")
        return None, f"Erro ao abrir caixa: {e}"


def fechar_caixa(caixa_id: int, saldo_fechamento: Decimal):
    try:
        with conexao() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE caixas SET status = 'FECHADO', saldo_fechamento = %s,
                              data_fechamento = CURRENT_TIMESTAMP
                       WHERE id = %s AND status = 'ABERTO' RETURNING id""",
                    (saldo_fechamento, caixa_id),
                )
                if not cur.fetchone():
                    conn.rollback()
                    return False, "Caixa não encontrado, ou já encerrado."
                cur.execute("DELETE FROM vendas_pendentes WHERE caixa_id = %s", (caixa_id,))
            conn.commit()
        return True, f"Fechamento do Turno #{caixa_id} concluído com sucesso!"
    except SemConexao:
        return False, _SEM_BANCO
    except Exception as e:
        log.exception("Erro ao fechar caixa")
        return False, f"Erro ao fechar caixa: {e}"


def registrar_sangria(caixa_id: int, valor: Decimal, motivo: str, autorizado_por: int):
    try:
        with conexao() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO movimentacoes_caixa (caixa_id, tipo, valor, motivo, autorizado_por)
                       VALUES (%s, 'SANGRIA', %s, %s, %s) RETURNING id""",
                    (caixa_id, valor, motivo, autorizado_por),
                )
                sangria_id = cur.fetchone()[0]
            conn.commit()
        return sangria_id, f"Sangria de {fmt_brl(valor)} registrada com sucesso!"
    except SemConexao:
        return None, _SEM_BANCO
    except Exception as e:
        log.exception("Erro ao registrar sangria")
        return None, f"Erro ao registrar sangria: {e}"


def registrar_auditoria_cancelamento(
    caixa_id: int, tipo: str, descricao: str, valor: Decimal, autorizado_por_id: int | None
) -> bool:
    try:
        with conexao() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO cancelamentos_pdv (caixa_id, tipo, descricao, valor, autorizado_por)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (caixa_id, tipo, descricao[:255], valor, autorizado_por_id),
                )
            conn.commit()
        return True
    except SemConexao:
        log.warning("Auditoria de cancelamento NÃO registrada (sem conexão): %s %s", tipo, descricao)
        return False
    except Exception:
        log.exception("Falha ao registrar auditoria de cancelamento")
        return False


# --- Fechamento -------------------------------------------------------------------

def _agregar(cur, condicao: str, params: tuple):
    """Totais de vendas, por forma de pagamento, e de sangrias.
    `condicao` é sempre texto fixo do código (nunca vem do usuário)."""
    cur.execute(
        f"""SELECT COALESCE(SUM(v.total), 0), COUNT(v.id)
            FROM vendas v JOIN caixas c ON c.id = v.caixa_id WHERE {condicao}""",
        params,
    )
    total_vendas, qtd_vendas = cur.fetchone()

    cur.execute(
        f"""SELECT UPPER(TRIM(v.forma_pagamento)), COALESCE(SUM(v.total), 0), COUNT(v.id)
            FROM vendas v JOIN caixas c ON c.id = v.caixa_id WHERE {condicao}
            GROUP BY UPPER(TRIM(v.forma_pagamento))""",
        params,
    )
    formas = {l[0]: {"total": D(l[1]), "qtd": int(l[2])} for l in cur.fetchall()}

    cur.execute(
        f"""SELECT COALESCE(SUM(m.valor), 0)
            FROM movimentacoes_caixa m JOIN caixas c ON c.id = m.caixa_id
            WHERE m.tipo = 'SANGRIA' AND {condicao}""",
        params,
    )
    sangrias = D(cur.fetchone()[0])
    return D(total_vendas), int(qtd_vendas), formas, sangrias


def dados_fechamento_turno(caixa_id: int, dinheiro_contado: Decimal | None = None) -> dict | None:
    try:
        with conexao() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, operador, saldo_abertura, data_abertura FROM caixas WHERE id = %s", (caixa_id,)
            )
            c = cur.fetchone()
            if not c:
                return None
            total, qtd, formas, sangrias = _agregar(cur, "c.id = %s", (caixa_id,))
    except SemConexao:
        return None
    except Exception:
        log.exception("Erro no fechamento do turno")
        return None

    fundo = D(c[2])
    vendas_dinheiro = formas.get(FORMA_DINHEIRO, {"total": ZERO})["total"]
    dinheiro_sistema = fundo + vendas_dinheiro - sangrias
    contado = dinheiro_contado if dinheiro_contado is not None else dinheiro_sistema
    diferenca = contado - dinheiro_sistema
    return {
        "tipo_relatorio": "FECHAMENTO DE CAIXA",
        "identificador": f"Turno #{c[0]}",
        "operador": c[1],
        "data_abertura": c[3],
        "data_fechamento": datetime.now(),
        "fundo_inicial": fundo,
        "total_vendas": total,
        "qtd_vendas": qtd,
        "formas": formas,
        "total_sangrias": sangrias,
        "dinheiro_sistema": dinheiro_sistema,
        "dinheiro_contado": contado,
        "diferenca": diferenca,
        "houve_quebra": abs(diferenca) >= Decimal("0.01"),
    }


def dados_fechamento_dia() -> dict | None:
    hoje = datetime.now().date()
    try:
        with conexao() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT COALESCE(SUM(saldo_abertura), 0), MIN(data_abertura), COUNT(id)
                   FROM caixas c WHERE DATE(c.data_abertura) = %s""",
                (hoje,),
            )
            fundo, inicio, turnos = cur.fetchone()
            total, qtd, formas, sangrias = _agregar(cur, "DATE(c.data_abertura) = %s", (hoje,))
    except SemConexao:
        return None
    except Exception:
        log.exception("Erro no fechamento do dia")
        return None

    fundo = D(fundo)
    vendas_dinheiro = formas.get(FORMA_DINHEIRO, {"total": ZERO})["total"]
    dinheiro_sistema = fundo + vendas_dinheiro - sangrias
    return {
        "tipo_relatorio": "TOTAL DO CAIXA - LEITURA X",
        "identificador": f"Data: {hoje.strftime('%d/%m/%Y')} (Turnos: {int(turnos)})",
        "operador": "TODOS OS OPERADORES",
        "data_abertura": inicio or datetime.now(),
        "data_fechamento": datetime.now(),
        "fundo_inicial": fundo,
        "total_vendas": total,
        "qtd_vendas": qtd,
        "formas": formas,
        "total_sangrias": sangrias,
        "dinheiro_sistema": dinheiro_sistema,
        "dinheiro_contado": dinheiro_sistema,
        "diferenca": ZERO,
        "houve_quebra": False,
    }
