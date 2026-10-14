"""Logging com arquivo rotativo. Num PDV, o log é a evidência quando algo dá errado no balcão."""
from __future__ import annotations

import logging
import logging.handlers


def configurar_logs() -> None:
    from pdv import config

    raiz = logging.getLogger("pdv")
    if raiz.handlers:
        return
    raiz.setLevel(logging.INFO)
    formato = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    try:
        config.PASTA_LOGS.mkdir(parents=True, exist_ok=True)
        arquivo = logging.handlers.RotatingFileHandler(
            config.PASTA_LOGS / "pdv.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        arquivo.setFormatter(formato)
        raiz.addHandler(arquivo)
    except OSError:
        pass

    console = logging.StreamHandler()
    console.setFormatter(formato)
    raiz.addHandler(console)


def obter_logger(nome: str) -> logging.Logger:
    return logging.getLogger(nome)
