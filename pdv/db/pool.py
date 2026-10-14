"""Pool de conexões PostgreSQL (thread-safe) com reconexão automática."""
from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager

from psycopg2 import InterfaceError, OperationalError, pool
from psycopg2.extensions import STATUS_READY

from pdv import config

log = logging.getLogger(__name__)


class SemConexao(Exception):
    """Banco indisponível agora. Quem chama decide se cai no modo offline."""


_pool: pool.ThreadedConnectionPool | None = None
_trava = threading.Lock()
_ultima_tentativa = 0.0


def _pool_ou_none(forcar: bool = False) -> pool.ThreadedConnectionPool | None:
    """Devolve o pool; se ele não existe, tenta criar de novo (com intervalo mínimo entre tentativas).

    Antes, uma falha no startup deixava o PDV offline para sempre, mesmo com a rede de volta.
    """
    global _pool, _ultima_tentativa
    if _pool is not None:
        return _pool
    with _trava:
        if _pool is not None:
            return _pool
        agora = time.monotonic()
        if not forcar and agora - _ultima_tentativa < config.REINICIO_POOL_S:
            return None
        _ultima_tentativa = agora
        try:
            _pool = pool.ThreadedConnectionPool(config.POOL_MIN, config.POOL_MAX, **config.db_config())
            log.info("Pool PostgreSQL inicializado.")
        except Exception as e:
            log.warning("PostgreSQL indisponível: %s", e)
            _pool = None
        return _pool


def iniciar_pool() -> bool:
    return _pool_ou_none(forcar=True) is not None


def fechar_pool() -> None:
    global _pool
    with _trava:
        if _pool is not None:
            _pool.closeall()
            _pool = None


@contextmanager
def conexao():
    """Empresta uma conexão do pool.

    - Levanta SemConexao se não houver banco.
    - Em erro, faz rollback; se a conexão quebrou, ela é descartada (não volta suja ao pool).
    - O commit é responsabilidade de quem usa.
    """
    p = _pool_ou_none()
    if p is None:
        raise SemConexao()
    try:
        conn = p.getconn()
    except Exception as e:
        raise SemConexao() from e

    descartar = False
    try:
        yield conn
    except (OperationalError, InterfaceError):
        descartar = True
        raise
    except BaseException:
        try:
            conn.rollback()
        except Exception:
            descartar = True
        raise
    finally:
        try:
            if not descartar and not conn.closed and conn.status != STATUS_READY:
                conn.rollback()
        except Exception:
            descartar = True
        try:
            p.putconn(conn, close=descartar or bool(conn.closed))
        except Exception as e:
            log.warning("Não foi possível devolver a conexão ao pool: %s", e)
