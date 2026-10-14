"""Tudo que depende de diferenças entre versões do Flet fica AQUI, em um único lugar.

Antes, `hasattr(page, "open")` estava espalhado por todos os modais.
"""
from __future__ import annotations

import inspect
import logging

import flet as ft

from pdv.money import mascara_moeda

log = logging.getLogger(__name__)


async def _focar(controle) -> None:
    try:
        resultado = controle.focus()
        if inspect.isawaitable(resultado):  # Flet novo: focus() é assíncrono
            await resultado
    except Exception:
        pass


def focar(page: ft.Page, controle) -> None:
    try:
        page.run_task(_focar, controle)
    except Exception:
        log.debug("Não foi possível focar o controle", exc_info=True)


def mostrar_aviso(page: ft.Page, mensagem: str, cor=ft.Colors.RED_700) -> None:
    snack = ft.SnackBar(
        content=ft.Text(mensagem, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
        bgcolor=cor,
        duration=2500,
    )
    for nome in ("show_dialog", "open"):  # Flet recente / intermediário
        funcao = getattr(page, nome, None)
        if callable(funcao):
            try:
                funcao(snack)
                return
            except Exception:
                continue
    page.snack_bar = snack  # Flet antigo
    snack.open = True
    page.update()


def campo_moeda(label: str, valor: str = "0,00", ao_mudar=None, **kwargs) -> ft.TextField:
    """TextField com máscara de centavos (digita 1234 -> 12,34)."""
    campo = ft.TextField(
        label=label, hint_text="0,00", value=valor,
        keyboard_type=ft.KeyboardType.NUMBER, dense=True, **kwargs,
    )

    def ao_digitar(e):
        campo.value = mascara_moeda(campo.value)
        if ao_mudar:
            ao_mudar(e)
        campo.page.update()

    campo.on_change = ao_digitar
    return campo
