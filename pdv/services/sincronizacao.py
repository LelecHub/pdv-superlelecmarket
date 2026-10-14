"""Serviço em segundo plano: envia vendas offline e mantém o cache local atualizado.

Não inicia nada ao ser importado; main.py chama `servico.start()` uma vez.
"""
from __future__ import annotations

import logging
import threading
import time

from pdv import config
from pdv.db import produtos, vendas

log = logging.getLogger(__name__)


class ServicoSincronizacao(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="pdv-sincronizacao")
        self._parar = threading.Event()

    def parar(self) -> None:
        self._parar.set()

    def run(self) -> None:
        proximo_cache = 0.0
        while not self._parar.is_set():
            try:
                # Primeiro as vendas (o estoque no servidor fica correto), depois o cache
                vendas.sincronizar_pendentes()
                if time.monotonic() >= proximo_cache:
                    ok = produtos.sincronizar_cache()
                    proximo_cache = time.monotonic() + (config.INTERVALO_SYNC_CACHE_S if ok else 30)
            except Exception:
                log.exception("Erro inesperado no serviço de sincronização")
            self._parar.wait(config.INTERVALO_SYNC_VENDAS_S)


servico = ServicoSincronizacao()
