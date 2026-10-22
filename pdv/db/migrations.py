"""Migrações do PostgreSQL. Idempotentes: podem rodar a cada inicialização."""
from __future__ import annotations

import logging

import bcrypt

from pdv import config
from pdv.db.pool import SemConexao, conexao

log = logging.getLogger(__name__)

_PREFIXOS_BCRYPT = ("$2a$", "$2b$", "$2y$")

_USUARIOS_DEV = [
    ("1001", "Operador Teste", "1234", "OPERADOR"),
    ("2001", "Gerente Teste", "4321", "GERENTE"),
    ("9999", "Admin Sistema", "admin", "ADMIN"),
]

_DDL = [
    # Tabelas base: num banco vazio o PDV sobe sozinho; num banco existente nada muda
    """CREATE TABLE IF NOT EXISTS produtos (
        id SERIAL PRIMARY KEY,
        codigo_barras VARCHAR(50),
        nome VARCHAR(150),
        preco NUMERIC(10, 2),
        quantidade_estoque NUMERIC(10, 3)
    )""",
    """CREATE TABLE IF NOT EXISTS clientes (
        id SERIAL PRIMARY KEY,
        nome VARCHAR(100),
        cpf VARCHAR(14) UNIQUE,
        pontos NUMERIC(10, 2) DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS caixas (
        id SERIAL PRIMARY KEY,
        operador VARCHAR(100),
        saldo_abertura NUMERIC(10, 2),
        data_abertura TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status VARCHAR(20)
    )""",
    """CREATE TABLE IF NOT EXISTS vendas (
        id SERIAL PRIMARY KEY,
        total NUMERIC(10, 2),
        forma_pagamento VARCHAR(30),
        valor_recebido NUMERIC(10, 2),
        troco NUMERIC(10, 2),
        caixa_id INT REFERENCES caixas(id),
        cliente_id INT REFERENCES clientes(id),
        cpf_nota VARCHAR(14),
        data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS itens_venda (
        id SERIAL PRIMARY KEY,
        venda_id INT REFERENCES vendas(id),
        produto_id INT REFERENCES produtos(id),
        quantidade NUMERIC(10, 3),
        preco_unitario NUMERIC(10, 2),
        subtotal NUMERIC(10, 2)
    )""",
    """CREATE TABLE IF NOT EXISTS public.usuarios (
        id SERIAL PRIMARY KEY,
        matricula VARCHAR(20) UNIQUE NOT NULL,
        nome VARCHAR(100) NOT NULL,
        senha_hash VARCHAR(255) NOT NULL,
        perfil VARCHAR(20) NOT NULL DEFAULT 'OPERADOR',
        ativo BOOLEAN NOT NULL DEFAULT TRUE,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """ALTER TABLE caixas
        ADD COLUMN IF NOT EXISTS usuario_id INT REFERENCES public.usuarios(id),
        ADD COLUMN IF NOT EXISTS saldo_fechamento NUMERIC(10, 2),
        ADD COLUMN IF NOT EXISTS data_fechamento TIMESTAMP,
        ADD COLUMN IF NOT EXISTS numero_pdv INT""",
    """CREATE TABLE IF NOT EXISTS movimentacoes_caixa (
        id SERIAL PRIMARY KEY,
        caixa_id INT REFERENCES caixas(id),
        tipo VARCHAR(20) NOT NULL,
        valor NUMERIC(10, 2) NOT NULL,
        motivo VARCHAR(255),
        autorizado_por INT REFERENCES public.usuarios(id),
        data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS vendas_pendentes (
        id SERIAL PRIMARY KEY,
        caixa_id INT UNIQUE REFERENCES caixas(id) ON DELETE CASCADE,
        data_inicio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS itens_venda_pendente (
        id SERIAL PRIMARY KEY,
        venda_pendente_id INT REFERENCES vendas_pendentes(id) ON DELETE CASCADE,
        produto_id INT REFERENCES produtos(id),
        quantidade NUMERIC(10, 3) NOT NULL,
        preco_unitario NUMERIC(10, 2) NOT NULL,
        subtotal NUMERIC(10, 2) NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS cancelamentos_pdv (
        id SERIAL PRIMARY KEY,
        caixa_id INT REFERENCES caixas(id),
        tipo VARCHAR(20) NOT NULL,
        descricao VARCHAR(255) NOT NULL,
        valor NUMERIC(10, 2) NOT NULL,
        autorizado_por INT REFERENCES public.usuarios(id),
        data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS public.promocoes (
        id SERIAL PRIMARY KEY,
        codigo_barras VARCHAR(50) NOT NULL,
        descricao_campanha VARCHAR(150) NOT NULL,
        tipo_desconto VARCHAR(20) NOT NULL,
        valor_desconto NUMERIC(10, 2) NOT NULL,
        qtd_necessaria INT DEFAULT 1,
        qtd_pagante INT DEFAULT 1,
        data_inicio TIMESTAMP NOT NULL,
        data_fim TIMESTAMP NOT NULL,
        ativa BOOLEAN NOT NULL DEFAULT TRUE
    )""",
    "ALTER TABLE promocoes ADD COLUMN IF NOT EXISTS qtd_necessaria INT DEFAULT 1",
    "ALTER TABLE promocoes ADD COLUMN IF NOT EXISTS qtd_pagante INT DEFAULT 1",
    # Idempotência: a mesma venda enviada duas vezes vira uma só
    "ALTER TABLE vendas ADD COLUMN IF NOT EXISTS uuid_venda UUID",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_vendas_uuid_venda ON vendas (uuid_venda)",
    # Estoque negativo é permitido (decisão de negócio), mas fica registrado
    """CREATE TABLE IF NOT EXISTS divergencias_estoque (
        id SERIAL PRIMARY KEY,
        venda_id INT REFERENCES vendas(id),
        produto_id INT REFERENCES produtos(id),
        quantidade_vendida NUMERIC(10, 3) NOT NULL,
        saldo_apos NUMERIC(10, 3) NOT NULL,
        data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""",
]


def _hash(senha: str) -> str:
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def migrar_banco() -> bool:
    try:
        with conexao() as conn:
            with conn.cursor() as cur:
                for comando in _DDL:
                    cur.execute(comando)

                # Senhas antigas em texto puro (a versão anterior aceitava isso) viram bcrypt UMA vez,
                # para ninguém ficar sem acesso quando o login passar a aceitar só hash.
                cur.execute("SELECT id, senha_hash FROM public.usuarios")
                for uid, atual in cur.fetchall():
                    if not (atual or "").startswith(_PREFIXOS_BCRYPT):
                        cur.execute(
                            "UPDATE public.usuarios SET senha_hash = %s WHERE id = %s",
                            (_hash(atual or ""), uid),
                        )
                        log.warning("Usuário id=%s tinha senha sem hash; convertida para bcrypt.", uid)

                # Usuários de teste: só em desenvolvimento e NUNCA sobrescrevem usuário existente
                if config.MODO_DEV:
                    log.warning("PDV_DEV=1: garantindo usuários de teste. NÃO use em produção.")
                    for mat, nome, senha, perfil in _USUARIOS_DEV:
                        cur.execute(
                            """INSERT INTO public.usuarios (matricula, nome, senha_hash, perfil, ativo)
                               VALUES (%s, %s, %s, %s, TRUE) ON CONFLICT (matricula) DO NOTHING""",
                            (mat, nome, _hash(senha), perfil),
                        )
            conn.commit()
        return True
    except SemConexao:
        log.warning("Migração ignorada: sem conexão com o PostgreSQL.")
        return False
    except Exception:
        log.exception("Falha na migração do banco")
        return False
