"""Autenticação: somente bcrypt, com bloqueio temporário após falhas seguidas."""
from __future__ import annotations

import logging
import threading
import time

import bcrypt
from psycopg2.extras import RealDictCursor

from pdv import config
from pdv.constantes import PERFIS_SUPERVISOR
from pdv.db.pool import SemConexao, conexao

log = logging.getLogger(__name__)

_falhas: dict[str, tuple[int, float]] = {}  # matricula -> (nº de falhas, bloqueado_ate)
_trava = threading.Lock()


def _segundos_bloqueado(matricula: str) -> int:
    with _trava:
        _, ate = _falhas.get(matricula, (0, 0.0))
    restante = int(ate - time.monotonic())
    return restante if restante > 0 else 0


def _registrar_falha(matricula: str) -> None:
    with _trava:
        n, _ = _falhas.get(matricula, (0, 0.0))
        n += 1
        if n >= config.MAX_FALHAS_LOGIN:
            _falhas[matricula] = (0, time.monotonic() + config.BLOQUEIO_LOGIN_S)
            log.warning("Matrícula %s bloqueada por %ss após %s falhas.", matricula, config.BLOQUEIO_LOGIN_S, n)
        else:
            _falhas[matricula] = (n, 0.0)


def _limpar_falhas(matricula: str) -> None:
    with _trava:
        _falhas.pop(matricula, None)


def autenticar(matricula: str, senha: str) -> tuple[dict | None, str]:
    """Devolve (usuario, mensagem_de_erro). Usuário nunca inclui o hash."""
    matricula = (matricula or "").strip()
    if not matricula or not senha:
        return None, "Informe a matrícula e a senha!"

    espera = _segundos_bloqueado(matricula)
    if espera:
        return None, f"Muitas tentativas. Aguarde {espera}s para tentar de novo."

    try:
        with conexao() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """SELECT id, matricula, nome, senha_hash, perfil FROM public.usuarios
                   WHERE TRIM(matricula) = %s AND ativo = TRUE""",
                (matricula,),
            )
            usuario = cur.fetchone()
    except SemConexao:
        return None, "Sem conexão com o banco de dados."
    except Exception:
        log.exception("Erro na autenticação")
        return None, "Erro ao consultar usuários."

    valido = False
    if usuario:
        try:
            valido = bcrypt.checkpw(senha.encode("utf-8"), str(usuario["senha_hash"]).encode("utf-8"))
        except ValueError:
            valido = False

    if not valido:
        _registrar_falha(matricula)
        return None, "Matrícula ou senha inválidos!"

    _limpar_falhas(matricula)
    usuario = dict(usuario)
    del usuario["senha_hash"]
    return usuario, ""


def eh_supervisor(usuario: dict | None) -> bool:
    return bool(usuario) and str(usuario.get("perfil", "")).upper() in PERFIS_SUPERVISOR


def autorizar_supervisor(matricula: str, senha: str) -> tuple[dict | None, str]:
    usuario, erro = autenticar(matricula, senha)
    if not usuario:
        return None, erro or "Credenciais do responsável inválidas!"
    if not eh_supervisor(usuario):
        return None, "Apenas Gerentes ou Administradores podem autorizar esta operação!"
    return usuario, ""
