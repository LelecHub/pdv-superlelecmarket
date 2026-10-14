"""Cria (ou redefine a senha de) um usuário sem passar por senhas fixas no código.

Uso:  python -m pdv.criar_usuario 2001 "Maria Gerente" GERENTE
"""
from __future__ import annotations

import getpass
import sys

import bcrypt

from pdv.db.pool import conexao, iniciar_pool


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[2].upper() not in ("OPERADOR", "GERENTE", "ADMIN"):
        print('Uso: python -m pdv.criar_usuario <matricula> "<nome>" <OPERADOR|GERENTE|ADMIN>')
        return 2
    matricula, nome, perfil = argv[0], argv[1], argv[2].upper()
    senha = getpass.getpass("Senha: ")
    if len(senha) < 6 or senha != getpass.getpass("Repita a senha: "):
        print("Senha curta demais (mínimo 6) ou diferente da confirmação.")
        return 1
    if not iniciar_pool():
        print("Sem conexão com o PostgreSQL.")
        return 1
    hash_ = bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()
    with conexao() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO public.usuarios (matricula, nome, senha_hash, perfil, ativo)
                   VALUES (%s, %s, %s, %s, TRUE)
                   ON CONFLICT (matricula) DO UPDATE
                   SET nome = EXCLUDED.nome, senha_hash = EXCLUDED.senha_hash,
                       perfil = EXCLUDED.perfil, ativo = TRUE""",
                (matricula, nome, hash_, perfil),
            )
        conn.commit()
    print(f"Usuário {matricula} ({perfil}) salvo.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
