"""SQLite local: cache de produtos/promoções, fila de vendas offline e estado do turno."""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime

from pdv import config
from pdv.db.modelos import DadosVenda
from pdv.money import D

log = logging.getLogger(__name__)


@contextmanager
def sqlite_local():
    """Conexão SQLite que SEMPRE fecha; commit em sucesso, rollback em erro."""
    conn = sqlite3.connect(config.LOCAL_DB, timeout=10)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def inicializar() -> None:
    with sqlite_local() as conn:
        conn.execute("PRAGMA journal_mode=WAL")

        # Cache antigo guardava preço em REAL (float). O novo guarda texto Decimal.
        conn.execute("DROP TABLE IF EXISTS produtos_cache")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS cache_produtos (
                id INTEGER PRIMARY KEY, codigo_barras TEXT, nome TEXT,
                preco TEXT, quantidade_estoque TEXT)"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_cache_produtos_cod ON cache_produtos(codigo_barras)")

        conn.execute(
            """CREATE TABLE IF NOT EXISTS cache_promocoes (
                codigo_barras TEXT, descricao_campanha TEXT, tipo_desconto TEXT,
                valor_desconto TEXT, qtd_necessaria INTEGER, qtd_pagante INTEGER,
                data_inicio TEXT, data_fim TEXT)"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS ix_cache_promocoes_cod ON cache_promocoes(codigo_barras)")

        conn.execute(
            """CREATE TABLE IF NOT EXISTS vendas_offline (
                id INTEGER PRIMARY KEY AUTOINCREMENT, dados_venda TEXT,
                data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"""
        )
        colunas = {linha[1] for linha in conn.execute("PRAGMA table_info(vendas_offline)")}
        if "uuid_venda" not in colunas:
            conn.execute("ALTER TABLE vendas_offline ADD COLUMN uuid_venda TEXT")
        if "tentativas" not in colunas:
            conn.execute("ALTER TABLE vendas_offline ADD COLUMN tentativas INTEGER NOT NULL DEFAULT 0")
        if "ultimo_erro" not in colunas:
            conn.execute("ALTER TABLE vendas_offline ADD COLUMN ultimo_erro TEXT")
        # Vendas enfileiradas pela versão antiga não tinham identificador: ganham um agora
        for (reg_id,) in conn.execute("SELECT id FROM vendas_offline WHERE uuid_venda IS NULL").fetchall():
            conn.execute("UPDATE vendas_offline SET uuid_venda = ? WHERE id = ?", (str(uuid.uuid4()), reg_id))
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_vendas_offline_uuid ON vendas_offline(uuid_venda)")

        conn.execute("CREATE TABLE IF NOT EXISTS estado_local (chave TEXT PRIMARY KEY, valor TEXT)")


# --- Estado local (ex.: turno aberto, para o PDV funcionar offline após reiniciar) ---------

def salvar_estado(chave: str, valor: dict | None) -> None:
    with sqlite_local() as conn:
        if valor is None:
            conn.execute("DELETE FROM estado_local WHERE chave = ?", (chave,))
        else:
            conn.execute(
                "INSERT OR REPLACE INTO estado_local (chave, valor) VALUES (?, ?)",
                (chave, json.dumps(valor)),
            )


def ler_estado(chave: str) -> dict | None:
    with sqlite_local() as conn:
        linha = conn.execute("SELECT valor FROM estado_local WHERE chave = ?", (chave,)).fetchone()
    return json.loads(linha[0]) if linha else None


# --- Cache de produtos e promoções ---------------------------------------------------------

def substituir_cache(produtos: list[tuple], promocoes: list[tuple]) -> None:
    """Troca o cache inteiro numa única transação (se algo falhar, o cache antigo permanece)."""
    with sqlite_local() as conn:
        conn.execute("DELETE FROM cache_produtos")
        conn.executemany("INSERT INTO cache_produtos VALUES (?, ?, ?, ?, ?)", produtos)
        conn.execute("DELETE FROM cache_promocoes")
        conn.executemany("INSERT INTO cache_promocoes VALUES (?, ?, ?, ?, ?, ?, ?, ?)", promocoes)


def _produto(linha) -> dict:
    return {
        "id": linha[0],
        "codigo_barras": linha[1],
        "nome": linha[2],
        "preco": D(linha[3]),
        "estoque": D(linha[4]),
    }


def buscar_produto_cache(codigo: str) -> dict | None:
    with sqlite_local() as conn:
        linha = conn.execute(
            "SELECT id, codigo_barras, nome, preco, quantidade_estoque FROM cache_produtos WHERE codigo_barras = ?",
            (codigo,),
        ).fetchone()
    return _produto(linha) if linha else None


def consultar_cache(termo: str, limite: int) -> list[dict]:
    with sqlite_local() as conn:
        linhas = conn.execute(
            """SELECT id, codigo_barras, nome, preco, quantidade_estoque FROM cache_produtos
               WHERE codigo_barras LIKE ? OR nome LIKE ? ORDER BY nome ASC LIMIT ?""",
            (f"%{termo}%", f"%{termo}%", limite),
        ).fetchall()
    return [_produto(linha) for linha in linhas]


def promocao_cache(codigo: str) -> tuple | None:
    """Promoção vigente no cache: (descricao, tipo, valor, qtd_nec, qtd_pag)."""
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite_local() as conn:
        return conn.execute(
            """SELECT descricao_campanha, tipo_desconto, valor_desconto, qtd_necessaria, qtd_pagante
               FROM cache_promocoes
               WHERE codigo_barras = ? AND data_inicio <= ? AND data_fim >= ?
               ORDER BY rowid DESC LIMIT 1""",
            (codigo, agora, agora),
        ).fetchone()


def campanhas_cache() -> list[tuple]:
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with sqlite_local() as conn:
        return conn.execute(
            "SELECT descricao_campanha, codigo_barras FROM cache_promocoes WHERE data_inicio <= ? AND data_fim >= ?",
            (agora, agora),
        ).fetchall()


# --- Fila de vendas offline -----------------------------------------------------------------

def salvar_venda_offline(dv: DadosVenda) -> int:
    with sqlite_local() as conn:
        cur = conn.execute(
            "INSERT INTO vendas_offline (dados_venda, uuid_venda) VALUES (?, ?)",
            (dv.to_json(), dv.uuid_venda),
        )
        return int(cur.lastrowid)


def listar_vendas_offline(max_tentativas: int) -> list[tuple]:
    with sqlite_local() as conn:
        return conn.execute(
            """SELECT id, uuid_venda, dados_venda, tentativas FROM vendas_offline
               WHERE tentativas < ? ORDER BY id ASC""",
            (max_tentativas,),
        ).fetchall()


def remover_venda_offline(reg_id: int) -> None:
    with sqlite_local() as conn:
        conn.execute("DELETE FROM vendas_offline WHERE id = ?", (reg_id,))


def registrar_falha_offline(reg_id: int, erro: str) -> None:
    with sqlite_local() as conn:
        conn.execute(
            "UPDATE vendas_offline SET tentativas = tentativas + 1, ultimo_erro = ? WHERE id = ?",
            (erro[:500], reg_id),
        )


def contar_vendas_offline() -> int:
    try:
        with sqlite_local() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM vendas_offline").fetchone()[0])
    except Exception as e:
        log.error("Falha ao contar vendas offline: %s", e)
        return 0
