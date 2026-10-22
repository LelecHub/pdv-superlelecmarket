"""Modo demonstração: banco PostgreSQL separado, com produtos, promoções e cliente fictícios.

Uso:  python -m pdv.demo            (abre o PDV)
      python -m pdv.demo --web      (abre no navegador)
      python -m pdv.demo --reset    (apaga e recria o banco de demonstração)

Usa as credenciais do .env, mas NUNCA o banco de produção: o banco é PDV_DEMO_DB (padrão "pdv_demo")
e os arquivos locais (fila offline, PDFs, logs) ficam na pasta demo/.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PASTA_DEMO = Path(__file__).resolve().parent.parent / "demo"

PRODUTOS = [
    ("7891000100103", "Arroz Branco Tipo 1 5kg", "27.90", 120),
    ("7891000200201", "Feijão Carioca 1kg", "8.49", 85),
    ("7891000300309", "Óleo de Soja 900ml", "7.29", 60),
    ("7891000400406", "Café Torrado e Moído 500g", "18.90", 40),
    ("7891000500503", "Leite Integral 1L", "5.49", 200),
    ("7891000600600", "Açúcar Refinado 1kg", "4.99", 90),
    ("7891000700707", "Macarrão Espaguete 500g", "4.29", 75),
    ("7891000800804", "Refrigerante Cola 2L", "9.99", 50),
    ("7891000900901", "Sabão em Pó 1,6kg", "21.90", 30),
    ("7891001000108", "Papel Higiênico 12 rolos", "19.90", 45),
]
# (código, campanha, tipo, valor, qtd_necessaria, qtd_pagante)
PROMOCOES = [
    ("7891000500503", "Leve 3 Pague 2 - Leite", "LEVE_X_PAGUE_Y", "0", 3, 2),
    ("7891000400406", "Café 10% OFF", "PERCENTUAL", "10", 1, 1),
]
# CPF válido de exemplo (não pertence a ninguém)
CLIENTE = ("Cliente Demonstração", "529.982.247-25", 150)


def _configurar_ambiente() -> str:
    """Precisa rodar ANTES de importar pdv.config, que lê o ambiente na importação."""
    banco = os.getenv("PDV_DEMO_DB", "pdv_demo")
    os.environ.update({
        "DB_NAME": banco,
        "PDV_DEV": "1",  # cria os usuários de teste 1001/1234, 2001/4321 e 9999/admin
        "PDV_LOCAL_DB": str(PASTA_DEMO / "pdv_offline.db"),
        "PDV_CONFIG_FILE": str(PASTA_DEMO / "pdv_config.json"),
        "PDV_PASTA_PDFS": str(PASTA_DEMO / "pdfs"),
        "PDV_PASTA_LOGS": str(PASTA_DEMO / "logs"),
    })
    return banco


def criar_banco(nome: str, recriar: bool = False) -> None:
    """Cria o banco de demonstração conectando no banco de manutenção "postgres"."""
    import psycopg2
    from psycopg2 import sql

    from pdv import config

    conn = psycopg2.connect(**{**config.db_config(), "database": "postgres"})
    conn.autocommit = True  # CREATE/DROP DATABASE não rodam dentro de transação
    try:
        with conn.cursor() as cur:
            if recriar:
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(nome)))
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (nome,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nome)))
    finally:
        conn.close()


def semear() -> bool:
    """Insere os dados fictícios. Só age em banco sem produtos, então pode rodar a cada abertura."""
    from pdv.db.pool import SemConexao, conexao

    try:
        with conexao() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM produtos")
            if cur.fetchone()[0]:
                return False
            cur.executemany(
                "INSERT INTO produtos (codigo_barras, nome, preco, quantidade_estoque) VALUES (%s, %s, %s, %s)",
                PRODUTOS,
            )
            cur.execute(
                "INSERT INTO clientes (nome, cpf, pontos) VALUES (%s, %s, %s) ON CONFLICT (cpf) DO NOTHING",
                CLIENTE,
            )
            cur.executemany(
                """INSERT INTO promocoes (codigo_barras, descricao_campanha, tipo_desconto, valor_desconto,
                       qtd_necessaria, qtd_pagante, data_inicio, data_fim)
                   VALUES (%s, %s, %s, %s, %s, %s, now() - interval '1 day', now() + interval '10 years')""",
                PROMOCOES,
            )
            conn.commit()
        return True
    except SemConexao:
        return False


def main(argv: list[str]) -> None:
    banco = _configurar_ambiente()
    recriar = "--reset" in argv
    if recriar:
        shutil.rmtree(PASTA_DEMO, ignore_errors=True)
    PASTA_DEMO.mkdir(exist_ok=True)

    try:
        criar_banco(banco, recriar=recriar)
    except Exception as erro:
        print(f"[DEMO] Não foi possível preparar o banco '{banco}': {erro}")
        print("[DEMO] Confira as credenciais DB_* no .env (o usuário precisa poder criar bancos).")
        sys.exit(1)

    print(f"[DEMO] Banco '{banco}' com dados fictícios. Usuários: 1001/1234 (operador), 2001/4321 (gerente).")
    sys.path.insert(0, str(PASTA_DEMO.parent))  # main.py fica na raiz do projeto
    from main import iniciar

    iniciar(web="--web" in argv, apos_migrar=semear)


if __name__ == "__main__":
    main(sys.argv[1:])
