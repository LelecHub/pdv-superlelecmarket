"""Atalhos de teclado. Ações ficam em dicionários {tecla: função} em vez de cadeias de if/elif."""
from __future__ import annotations

import flet as ft

_TECLAS_DESPERTAR = ("Enter", "Numpad Enter", "Space", " ")


def criar_handler(app):
    # Atalhos de letra da tela de venda (só valem com o campo de código vazio)
    atalhos_venda = {
        "I": app.m_canc_item.abrir,
        "C": app.m_canc_cupom.abrir,
        "M": app.m_estoque.abrir,
        "P": app.m_preco.abrir,
        "R": app.reimprimir_ultimo_cupom,
        "S": app.m_sangria.abrir,
        "F": app.m_fechamento.abrir,
    }

    def escape() -> bool:
        # Fecha o primeiro modal aberto (a lista é única: app.modais)
        for modal in app.modais:
            if modal.aberto:
                modal.fechar()
                return True

        tela = app.tela
        if tela == "identificacao_cliente_pergunta":
            app.alternar_tela("descanso")
        elif tela == "identificacao_cliente_digitar":
            app.alternar_tela("identificacao_cliente_pergunta")
        elif tela == "identificacao_preferencias":
            app.alternar_tela("identificacao_cliente_digitar")
        elif tela == "venda":
            if not app.carrinho:
                app.alternar_tela("descanso")
            else:
                app.status("Finalize ou cancele a venda antes de voltar ao descanso!", ft.Colors.ORANGE_400)
        return True

    def descanso(tecla: str) -> None:
        if tecla not in _TECLAS_DESPERTAR:
            return
        if app.caixa is None:
            app.m_abertura.abrir()
        else:
            app.iniciar_fluxo_pos_descanso()

    def pergunta_cpf(tecla: str) -> None:
        if tecla == "1":
            app.alternar_tela("identificacao_cliente_digitar")
        elif tecla == "2":
            app.cliente.resetar()
            app.alternar_tela("venda")

    def preferencias(tecla: str) -> None:
        if tecla in ("1", "2", "3"):
            app.escolher_preferencia_cliente(tecla)

    def venda(tecla: str, tecla_bruta: str) -> None:
        if app.caixa is None:
            return
        # Dígito digitado fora do campo (ex.: leitor de código de barras sem foco)
        digito = tecla_bruta.replace("Numpad ", "") if tecla_bruta.startswith("Numpad ") else tecla_bruta
        if digito.isdigit() and len(digito) == 1:
            app.digitar_no_campo_codigo(digito)
            return
        if tecla == "F4":
            app.m_pagamento.abrir()
            return
        if (app.campo_codigo.value or "").strip() == "":
            acao = atalhos_venda.get(tecla)
            if acao:
                acao()

    por_tela = {
        "descanso": lambda t, b: descanso(b if b in _TECLAS_DESPERTAR else t),
        "identificacao_cliente_pergunta": lambda t, b: pergunta_cpf(t),
        "identificacao_preferencias": lambda t, b: preferencias(t),
        "venda": venda,
    }

    def on_keyboard(e: ft.KeyboardEvent) -> None:
        bruta = (e.key or "").strip() if e.key != " " else " "
        tecla = bruta.upper()

        if bruta == "Escape":
            escape()
            return
        if any(m.aberto for m in app.modais):
            return
        acao = por_tela.get(app.tela)
        if acao:
            acao(tecla, bruta)

    return on_keyboard
