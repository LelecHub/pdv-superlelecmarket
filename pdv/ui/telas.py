"""Telas do PDV: funções que recebem o `app` e devolvem a árvore de controles."""
from __future__ import annotations

from datetime import datetime

import flet as ft

from pdv.db import clientes
from pdv.ui.compat import focar


def fundo_por_horario() -> str:
    hora = datetime.now().hour
    if 6 <= hora < 12:
        return "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?auto=format&fit=crop&w=1920&q=80"
    if 12 <= hora < 18:
        return "https://images.unsplash.com/photo-1510414842594-a61c69b5ae57?auto=format&fit=crop&w=1920&q=80"
    return "https://images.unsplash.com/photo-1509773896068-7fd415d91e2e?auto=format&fit=crop&w=1920&q=80"


def _sobre_fundo(app, conteudo) -> ft.Stack:
    """Imagem + desfoque + conteúdo centralizado. Fundo preto garante tela legível se a imagem não carregar (offline)."""
    return ft.Stack(
        expand=True,
        controls=[
            ft.Container(expand=True, bgcolor=ft.Colors.BLACK),
            app.img_fundo,
            ft.Container(expand=True, blur=ft.Blur(sigma_x=6, sigma_y=6), bgcolor=ft.Colors.with_opacity(0.5, ft.Colors.BLACK)),
            ft.Container(expand=True, alignment=ft.Alignment(0, 0), padding=30, content=conteudo),
        ],
    )


def _coluna(controles, spacing=16) -> ft.Column:
    return ft.Column(
        alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=spacing,
        controls=controles,
    )


def descanso(app) -> ft.Control:
    cor = app.cor
    return _sobre_fundo(app, _coluna([
        ft.Icon(ft.Icons.POINT_OF_SALE, size=180, color=cor),
        ft.Text(app.nome_loja, size=36, weight=ft.FontWeight.W_300, color=ft.Colors.ORANGE_ACCENT_400),
        ft.Text(f"PDV #{app.numero_pdv:02d} - CAIXA LIVRE", size=50, weight=ft.FontWeight.BOLD, color=cor),
        ft.Container(height=10),
        ft.Container(
            padding=ft.Padding(24, 12, 24, 12), border_radius=30,
            bgcolor=ft.Colors.with_opacity(0.5, ft.Colors.BLACK), border=ft.Border.all(1, cor),
            content=ft.Text("Pressione [ENTER] ou [ESPAÇO] para iniciar", size=18, weight=ft.FontWeight.W_500, color=cor),
        ),
        ft.Text(app.txt_info_caixa.value, size=32, color=ft.Colors.WHITE),
    ]))


def pergunta_cpf(app) -> ft.Control:
    return _sobre_fundo(app, _coluna([
        ft.Icon(ft.Icons.HELP_OUTLINE, size=80, color=app.cor),
        ft.Text("DESEJA INSERIR O CPF DO CLIENTE?", size=28, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
        ft.Container(height=10),
        ft.Container(
            padding=20, border_radius=10, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, border=ft.Border.all(1, app.cor),
            content=ft.Column(spacing=14, controls=[
                ft.Text("[1] SIM - Inserir CPF do Cliente", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
                ft.Text("[2] NÃO - Continuar sem CPF", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.RED_400),
            ]),
        ),
        ft.Text("Pressione [ESC] para voltar ao Descanso | Tecla [1] ou [2] para escolher", size=14, color=ft.Colors.GREY_400, italic=True),
    ], spacing=20))


def digitar_cpf(app) -> ft.Control:
    cpf = ft.TextField(
        label="Digite o CPF do Cliente (11 Dígitos)", hint_text="Apenas números...",
        input_filter=ft.NumbersOnlyInputFilter(), keyboard_type=ft.KeyboardType.NUMBER,
        autofocus=True, max_length=11, text_align=ft.TextAlign.CENTER, text_size=20, width=350,
    )
    nome = ft.TextField(label="Nome do Cliente (Novo Cadastro)", hint_text="Nome completo...", dense=True, visible=False, width=350)
    erro = ft.Text("", size=13, color=ft.Colors.RED_400)

    def falha(msg: str, limpar_cpf: bool = True, destino=None):
        erro.value = msg
        erro.color = ft.Colors.RED_400
        if limpar_cpf:
            cpf.value = ""
        focar(app.page, destino or cpf)
        app.page.update()

    def processar(e=None):
        digitos = "".join(filter(str.isdigit, cpf.value or ""))
        if len(digitos) != 11:
            return falha("Digite exatamente 11 dígitos!")
        valido, formatado = clientes.val_cpf(digitos)
        if not valido:
            return falha("CPF inválido (dígitos verificadores incorretos)!")

        cliente = clientes.buscar_cliente(formatado)
        if cliente:
            app.cliente.cpf_tmp, app.cliente.id_tmp = formatado, cliente[0]
            return app.alternar_tela("identificacao_preferencias")

        if not nome.visible:
            nome.visible = True
            erro.value = "Cliente não cadastrado. Informe o nome:"
            erro.color = ft.Colors.AMBER_400
            focar(app.page, nome)
            return app.page.update()

        nome_cli = (nome.value or "").strip()
        if not nome_cli:
            return falha("Informe o nome do cliente!", limpar_cpf=False, destino=nome)
        novo_id, msg = clientes.cadastrar_cliente(nome_cli, formatado)
        if novo_id:
            app.cliente.cpf_tmp, app.cliente.id_tmp = formatado, novo_id
            return app.alternar_tela("identificacao_preferencias")
        falha(msg, limpar_cpf=False)

    cpf.on_submit = processar
    nome.on_submit = processar
    return _sobre_fundo(app, _coluna([
        ft.Icon(ft.Icons.PERSON_SEARCH, size=70, color=app.cor),
        ft.Text("IDENTIFICAÇÃO DE CLIENTE", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
        ft.Container(height=10),
        cpf, nome, erro,
        ft.FilledButton("Avançar (ENTER)", icon=ft.Icons.CHECK, on_click=processar),
        ft.Text("Pressione [ESC] para voltar", size=13, color=ft.Colors.GREY_400, italic=True),
    ]))


def preferencias(app) -> ft.Control:
    return _sobre_fundo(app, _coluna([
        ft.Icon(ft.Icons.RECEIPT_LONG, size=70, color=app.cor),
        ft.Text("PREFERÊNCIAS DO CLIENTE", size=26, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
        ft.Text(f"CPF Vinculado: {app.cliente.cpf_tmp or ''}", size=16, color=ft.Colors.GREEN_400, weight=ft.FontWeight.BOLD),
        ft.Divider(height=10),
        ft.Container(
            padding=20, border_radius=10, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            content=ft.Column(spacing=12, controls=[
                ft.Text("[1] CPF na Nota e Fidelidade (Loja)", size=18, weight=ft.FontWeight.BOLD),
                ft.Text("[2] Somente Fidelidade (Sem CPF na Nota)", size=18, weight=ft.FontWeight.BOLD),
                ft.Text("[3] Somente CPF na Nota (Sem Fidelidade)", size=18, weight=ft.FontWeight.BOLD),
            ]),
        ),
        ft.Text("Pressione [ESC] para voltar | Teclas [1], [2] ou [3] para selecionar", size=13, color=ft.Colors.GREY_400, italic=True),
    ], spacing=20))


def venda(app) -> ft.Control:
    cor = app.cor
    m = app  # atalho

    barra_superior = ft.Container(
        padding=ft.Padding(16, 8, 16, 8), bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, border_radius=8,
        content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
            ft.Row([
                ft.Icon(ft.Icons.STOREFRONT, color=cor, size=24),
                ft.Text(f"{app.nome_loja} - PDV #{app.numero_pdv:02d}", size=18, weight=ft.FontWeight.BOLD),
                ft.Container(width=8),
                app.txt_info_caixa,
            ], spacing=8),
            ft.Row([
                ft.IconButton(icon=ft.Icons.SETTINGS, icon_color=ft.Colors.BLUE_400, tooltip="Configurações do PDV", on_click=m.m_config.abrir),
                ft.TextButton("Item [I]", icon=ft.Icons.DELETE_SWEEP, icon_color=ft.Colors.AMBER_400, on_click=m.m_canc_item.abrir),
                ft.TextButton("Cupom [C]", icon=ft.Icons.CANCEL, icon_color=ft.Colors.RED_400, on_click=m.m_canc_cupom.abrir),
                ft.TextButton("Estoque [M]", icon=ft.Icons.INVENTORY_2, icon_color=ft.Colors.BLUE_400, on_click=m.m_estoque.abrir),
                ft.TextButton("Preço [P]", icon=ft.Icons.PRICE_CHECK, icon_color=ft.Colors.GREEN_400, on_click=m.m_preco.abrir),
                ft.TextButton("Reimprimir [R]", icon=ft.Icons.RECEIPT, icon_color=ft.Colors.CYAN_400, on_click=lambda e: m.reimprimir_ultimo_cupom()),
                ft.TextButton("Sangria [S]", icon=ft.Icons.MONEY_OFF, icon_color=ft.Colors.AMBER_400, on_click=m.m_sangria.abrir),
                ft.TextButton("Fechar [F]", icon=ft.Icons.LOGOUT, icon_color=ft.Colors.RED_400, on_click=m.m_fechamento.abrir),
            ], spacing=2),
        ]),
    )

    cupom = ft.Container(
        expand=6, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=8, padding=12,
        content=ft.Column(expand=True, spacing=8, controls=[
            ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                ft.Row([ft.Icon(ft.Icons.RECEIPT_LONG, size=18, color=ft.Colors.GREY_400),
                        ft.Text("CUPOM DA COMPRA", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_300)]),
                ft.Text("ITENS REGISTRADOS", size=11, color=ft.Colors.GREY_500),
            ]),
            ft.Divider(height=1, color=ft.Colors.GREY_800),
            app.lista_produtos,
        ]),
    )

    ultimo = ft.Container(
        expand=5, width=float("inf"), padding=20, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGH, border_radius=8,
        alignment=ft.Alignment(0, 0),
        content=ft.Column(expand=True, alignment=ft.MainAxisAlignment.SPACE_EVENLY, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            ft.Text("ÚLTIMO PRODUTO BIPADO", size=13, weight=ft.FontWeight.BOLD, color=cor),
            ft.Icon(ft.Icons.SHOPPING_BAG_OUTLINED, size=60, color=cor),
            app.txt_ultimo_nome, app.txt_ultimo_qtd_preco,
            ft.Divider(height=1, color=ft.Colors.GREY_800),
            app.txt_ultimo_subtotal,
        ]),
    )

    total = ft.Container(
        expand=5, width=float("inf"), padding=24, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, border_radius=8,
        border=ft.Border.all(2, cor), alignment=ft.Alignment(0, 0),
        content=ft.Column(expand=True, alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12, controls=[
            ft.Text("SUBTOTAL / TOTAL A PAGAR", size=16, weight=ft.FontWeight.BOLD, color=cor),
            app.txt_total,
            ft.Container(
                padding=ft.Padding(12, 6, 12, 6), bgcolor=ft.Colors.BLACK_38, border_radius=6,
                content=ft.Text("Pressione F4 ou ENTER (com campo vazio) para finalizar", size=12, color=ft.Colors.GREY_400),
            ),
        ]),
    )

    # A linha de status existia no código, mas nunca era colocada na tela: as mensagens ficavam invisíveis.
    rodape = ft.Container(
        padding=12, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, border_radius=8,
        content=ft.Column(spacing=8, controls=[
            app.txt_status,
            ft.Row(controls=[app.campo_codigo, app.botao_finalizar], spacing=12),
        ]),
    )

    return ft.Container(
        expand=True, padding=14,
        content=ft.Column(expand=True, spacing=12, controls=[
            barra_superior,
            ft.Row(expand=True, spacing=12, controls=[
                cupom,
                ft.Container(expand=4, content=ft.Column(expand=True, spacing=12, controls=[ultimo, total])),
            ]),
            rodape,
        ]),
    )
