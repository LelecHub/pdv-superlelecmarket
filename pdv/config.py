"""Configuração central do PDV.

Nenhum segredo fica no código: tudo vem de variáveis de ambiente ou do arquivo .env
(que NÃO deve ser versionado).
"""
from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _carregar_dotenv(caminho: Path) -> None:
    """Leitor mínimo de .env (sem depender de python-dotenv)."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


_carregar_dotenv(BASE_DIR / ".env")


def _env_int(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, str(padrao)))
    except ValueError:
        return padrao


# --- Identidade da loja -----------------------------------------------------
NOME_LOJA = os.getenv("PDV_NOME_LOJA", "SUPERLELECMARKET")
CNPJ_LOJA = os.getenv("PDV_CNPJ", "00.000.000/0001-00")

# --- Modo desenvolvimento: só nele os usuários de teste são criados ----------
MODO_DEV = os.getenv("PDV_DEV", "0") == "1"

# --- Arquivos locais -----------------------------------------------------------
LOCAL_DB = os.getenv("PDV_LOCAL_DB", str(BASE_DIR / "pdv_offline.db"))
CONFIG_FILE = os.getenv("PDV_CONFIG_FILE", str(BASE_DIR / "pdv_config.json"))
PASTA_PDFS = Path(os.getenv("PDV_PASTA_PDFS", str(BASE_DIR / "saida_pdfs")))
PASTA_LOGS = Path(os.getenv("PDV_PASTA_LOGS", str(BASE_DIR / "logs")))

# --- Banco / pool --------------------------------------------------------------
POOL_MIN = 1
POOL_MAX = _env_int("DB_POOL_MAX", 10)
REINICIO_POOL_S = _env_int("DB_REINICIO_POOL_S", 10)

# --- Sincronização offline -----------------------------------------------------
INTERVALO_SYNC_VENDAS_S = _env_int("PDV_SYNC_VENDAS_S", 30)
INTERVALO_SYNC_CACHE_S = _env_int("PDV_SYNC_CACHE_S", 600)
MAX_TENTATIVAS_SYNC = _env_int("PDV_MAX_TENTATIVAS_SYNC", 10)

# --- Segurança -------------------------------------------------------------------
MAX_FALHAS_LOGIN = _env_int("PDV_MAX_FALHAS_LOGIN", 5)
BLOQUEIO_LOGIN_S = _env_int("PDV_BLOQUEIO_LOGIN_S", 300)
# Cancelar item acima deste valor exige senha de supervisor
LIMITE_CANCELAMENTO_ITEM = Decimal(os.getenv("PDV_LIMITE_CANCEL_ITEM", "50.00"))


def validar() -> None:
    """Falha cedo e com mensagem clara se faltar algo essencial."""
    if not os.getenv("DB_PASS"):
        raise RuntimeError(
            "Variável de ambiente DB_PASS não definida.\n"
            "Copie .env.example para .env e preencha as credenciais do banco."
        )


def db_config() -> dict:
    validar()
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "database": os.getenv("DB_NAME", "postgres"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.environ["DB_PASS"],
        "port": _env_int("DB_PORT", 5432),
        # Sem timeout, um servidor fora do ar trava o bip por minutos antes de cair no offline
        "connect_timeout": _env_int("DB_TIMEOUT", 3),
    }


# --- Preferências de interface (arquivo JSON local) ------------------------------
PREFERENCIAS_PADRAO = {"numero_caixa": 1, "tema": "Escuro", "cor": "Supermercado (Esmeralda)"}


def carregar_configuracoes_locais() -> dict:
    prefs = dict(PREFERENCIAS_PADRAO)
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            prefs.update(json.load(f))
    except FileNotFoundError:
        pass
    except Exception:
        # arquivo corrompido: segue com o padrão
        pass
    return prefs


def salvar_configuracoes_locais(config: dict) -> None:
    from pdv.logger import obter_logger

    destino = Path(CONFIG_FILE)
    temporario = destino.with_suffix(".tmp")
    try:
        temporario.write_text(json.dumps(config, indent=4, ensure_ascii=False), encoding="utf-8")
        os.replace(temporario, destino)  # escrita atômica
    except Exception as e:
        obter_logger(__name__).error("Falha ao salvar configurações: %s", e)
