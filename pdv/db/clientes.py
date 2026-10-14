"""Clientes e validação de CPF."""
from __future__ import annotations

import logging

from psycopg2 import errors

from pdv.db.pool import SemConexao, conexao

log = logging.getLogger(__name__)


def val_cpf(texto: str) -> tuple[bool, str]:
    """Devolve (valido, cpf_formatado_ou_somente_digitos)."""
    n = "".join(filter(str.isdigit, texto or ""))
    if len(n) != 11 or n == n[0] * 11:
        return False, n
    s1 = sum(int(n[i]) * (10 - i) for i in range(9))
    d1 = (s1 * 10) % 11
    if d1 == 10:
        d1 = 0
    s2 = sum(int(n[i]) * (11 - i) for i in range(10))
    d2 = (s2 * 10) % 11
    if d2 == 10:
        d2 = 0
    if d1 == int(n[9]) and d2 == int(n[10]):
        return True, f"{n[:3]}.{n[3:6]}.{n[6:9]}-{n[9:]}"
    return False, n


def buscar_cliente(cpf: str):
    """(id, nome, cpf, pontos) ou None. Sem banco, devolve None (venda segue sem fidelidade)."""
    try:
        with conexao() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, nome, cpf, pontos FROM clientes WHERE cpf = %s", (cpf,))
            return cur.fetchone()
    except SemConexao:
        return None
    except Exception:
        log.exception("Erro ao buscar cliente")
        return None


def cadastrar_cliente(nome: str, cpf: str) -> tuple[int | None, str]:
    try:
        with conexao() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO clientes (nome, cpf, pontos) VALUES (%s, %s, 0) RETURNING id",
                    (nome, cpf),
                )
                novo_id = cur.fetchone()[0]
            conn.commit()
            return novo_id, "Ok"
    except SemConexao:
        return None, "Sem conexão com o banco: não é possível cadastrar agora."
    except errors.UniqueViolation:
        return None, "Este CPF já está cadastrado."
    except Exception as e:
        log.exception("Erro ao cadastrar cliente")
        return None, f"Erro ao cadastrar: {e}"
