"""Todos os modais do PDV.

Cada modal é uma classe com `abrir()` / `fechar()`. A classe base registra o diálogo no overlay
e na lista `app.modais`, o que permite ao teclado (ESC) e à checagem "algum modal aberto?"
usar uma lista única, em vez de repetir os nomes dos modais em vários lugares.
"""
from __future__ import annotations

import logging

import flet as ft

from pdv import config
from pdv.constantes import (
    FORMA_CREDITO,
    FORMA_DEBITO,
    FORMA_DINHEIRO,
    FORMA_PIX,
    FORMAS_PAGAMENTO,
)
from pdv.db import caixa as caixa_db
from pdv.db import local, produtos, usuarios
from pdv.money import ZERO, fmt_brl, fmt_numero, fmt_qtd, parse_moeda
from pdv.relatorios.base import abrir_pdf_async, caminho_pdf
from pdv.relatorios.cupom import gerar_cupom_pdf
from pdv.relatorios.fechamento import gerar_relatorio_fechamento_pdf
from pdv.relatorios.sangria import gerar_comprovante_sangria_pdf
from pdv.services import promocoes as svc_promo
from pdv.ui.compat import campo_moeda, focar

log = logging.getLogger(__name__)


# --- blocos de construção --------------------------------------------------------------------

def _dialogo(icone, cor_icone, titulo, controles, largura, acoes, altura=None, modal=True, spacing=12):
    return ft.AlertDialog(
        modal=modal,
        title=ft.Row([ft.Icon(icone, color=cor_icone), ft.Text(titulo)]),
        content=ft.Container(
            width=largura,
            height=altura,
            content=ft.Column(tight=True, spacing=spacing, controls=controles),
        ),
        actions=acoes,
        actions_alignment=ft.MainAxisAlignment.END,
    )


def _texto_erro() -> ft.Text:
    return ft.Text("", color=ft.Colors.RED_400, size=12)


def _botao_primario(texto, icone, cor_fundo, ao_clicar):
    return ft.FilledButton(
        texto, icon=icone, on_click=ao_clicar,
        style=ft.ButtonStyle(bgcolor=cor_fundo, color=ft.Colors.WHITE),
    )


# --- base ---------------------------------------------------------------------------------------

class ModalBase:
    foco: str | None = None  # nome do atributo (campo) que recebe o foco ao abrir

    def __init__(self, app) -> None:
        self.app = app
        self.page = app.page
        self.dialog = self.construir()
        self.page.overlay.append(self.dialog)
        app.modais.append(self)

    @property
    def aberto(self) -> bool:
        return bool(self.dialog.open)

    def construir(self) -> ft.AlertDialog:
        raise NotImplementedError

    def preparar(self):
        """Roda antes de abrir. Devolver False cancela a abertura."""

    def abrir(self, e=None) -> None:
        if self.preparar() is False:
            return
        self.dialog.open = True
        self.page.update()
        alvo = getattr(self, self.foco, None) if self.foco else None
        if alvo is not None:
            focar(self.page, alvo)

    def fechar(self, e=None) -> None:
        self.dialog.open = False
        self.page.update()
        focar(self.page, self.app.campo_codigo)


# --- abertura de turno ---------------------------------------------------------------------------

class AberturaModal(ModalBase):
    foco = "matricula"

    def construir(self):
        self.matricula = ft.TextField(label="Matrícula do Operador", hint_text="Digite a matrícula...", dense=True)
        self.senha = ft.TextField(label="Senha", hint_text="Digite a senha...", password=True, can_reveal_password=True, dense=True)
        self.fundo = campo_moeda("Fundo de Troco / Saldo Inicial (R$)")
        self.erro = _texto_erro()
        self.matricula.on_submit = lambda e: focar(self.page, self.senha)
        self.senha.on_submit = lambda e: focar(self.page, self.fundo)
        self.fundo.on_submit = self.confirmar
        return _dialogo(
            ft.Icons.LOCK_OPEN, ft.Colors.GREEN_400, "Abertura de Turno de Caixa",
            [self.matricula, self.senha, self.fundo, self.erro], 420,
            [
                ft.TextButton("Cancelar (ESC)", on_click=self.fechar),
                _botao_primario("Abrir Caixa", ft.Icons.CHECK, ft.Colors.GREEN_700, self.confirmar),
            ],
        )

    def preparar(self):
        self.matricula.value = ""
        self.senha.value = ""
        self.fundo.value = "0,00"
        self.erro.value = ""

    def confirmar(self, e=None):
        usuario, erro = usuarios.autenticar(self.matricula.value or "", self.senha.value or "")
        if not usuario:
            self.erro.value = erro
            self.page.update()
            return
        saldo = parse_moeda(self.fundo.value)
        caixa_id, msg = caixa_db.abrir_caixa(usuario["id"], usuario["nome"], saldo, self.app.numero_pdv)
        if not caixa_id:
            self.erro.value = msg
            self.page.update()
            return
        self.senha.value = ""
        self.dialog.open = False
        self.app.abrir_turno(caixa_id, usuario, saldo, msg)


# --- autorização de supervisor (reutilizável) -------------------------------------------------------

class AutorizacaoModal(ModalBase):
    foco = "matricula"

    def construir(self):
        self._ao_autorizar = None
        self.mensagem = ft.Text("", size=13, color=ft.Colors.GREY_300)
        self.matricula = ft.TextField(label="Matrícula do Supervisor/Gerente", dense=True)
        self.senha = ft.TextField(label="Senha de Autorização", password=True, can_reveal_password=True, dense=True)
        self.erro = _texto_erro()
        self.matricula.on_submit = lambda e: focar(self.page, self.senha)
        self.senha.on_submit = self.confirmar
        self.titulo = ft.Text("Autorização Gerencial")
        d = _dialogo(
            ft.Icons.ADMIN_PANEL_SETTINGS, ft.Colors.AMBER_400, "Autorização Gerencial",
            [
                self.mensagem,
                ft.Text("Autorização da Supervisão Obrigatória", weight=ft.FontWeight.BOLD, size=13, color=ft.Colors.AMBER_300),
                self.matricula, self.senha, self.erro,
            ], 420,
            [
                ft.TextButton("Voltar (ESC)", on_click=self.fechar),
                _botao_primario("Autorizar", ft.Icons.CHECK, ft.Colors.AMBER_800, self.confirmar),
            ],
        )
        return d

    def pedir(self, mensagem: str, ao_autorizar) -> None:
        self._ao_autorizar = ao_autorizar
        self.mensagem.value = mensagem
        self.matricula.value = ""
        self.senha.value = ""
        self.erro.value = ""
        self.abrir()

    def confirmar(self, e=None):
        supervisor, erro = usuarios.autorizar_supervisor(self.matricula.value or "", self.senha.value or "")
        if not supervisor:
            self.erro.value = erro
            self.page.update()
            return
        self.senha.value = ""
        callback, self._ao_autorizar = self._ao_autorizar, None
        self.fechar()
        if callback:
            callback(supervisor)


# --- sangria --------------------------------------------------------------------------------------------

class SangriaModal(ModalBase):
    foco = "valor"

    def construir(self):
        self.valor = campo_moeda("Valor da Retirada (R$)", autofocus=True)
        self.motivo = ft.TextField(label="Motivo da Sangria", hint_text="Ex: Recolha para cofre...", value="Recolha para cofre", dense=True)
        self.matricula = ft.TextField(label="Matrícula do Gerente / Responsável", dense=True)
        self.senha = ft.TextField(label="Senha de Autorização", password=True, can_reveal_password=True, dense=True)
        self.erro = _texto_erro()
        return _dialogo(
            ft.Icons.MONEY_OFF, ft.Colors.AMBER_400, "Registrar Sangria [S]",
            [
                self.valor, self.motivo, ft.Divider(),
                ft.Text("Autorização Gerencial Obrigatória", weight=ft.FontWeight.BOLD, size=13, color=ft.Colors.AMBER_300),
                self.matricula, self.senha, self.erro,
            ], 420,
            [
                ft.TextButton("Cancelar (ESC)", on_click=self.fechar),
                _botao_primario("Confirmar e Imprimir", ft.Icons.PRINT, ft.Colors.AMBER_800, self.confirmar),
            ],
        )

    def preparar(self):
        if not self.app.caixa:
            self.app.status("Abra o caixa antes de efetuar sangrias!", ft.Colors.ORANGE_400)
            return False
        self.valor.value = "0,00"
        self.matricula.value = ""
        self.senha.value = ""
        self.erro.value = ""

    def confirmar(self, e=None):
        app = self.app
        if not app.caixa:
            return
        valor = parse_moeda(self.valor.value)
        if valor <= 0:
            self.erro.value = "Informe um valor de sangria válido!"
            self.page.update()
            return
        gerente, erro = usuarios.autorizar_supervisor(self.matricula.value or "", self.senha.value or "")
        if not gerente:
            self.erro.value = erro
            self.page.update()
            return

        motivo = (self.motivo.value or "").strip() or "Recolha de numerário"
        sangria_id, msg = caixa_db.registrar_sangria(app.caixa["id"], valor, motivo, gerente["id"])
        if not sangria_id:
            self.erro.value = msg
            self.page.update()
            return

        self.senha.value = ""
        try:
            caminho = caminho_pdf(f"sangria_{sangria_id}.pdf")
            gerar_comprovante_sangria_pdf(sangria_id, app.caixa["id"], app.caixa["operador"], gerente["nome"], valor, motivo, caminho)
            abrir_pdf_async(caminho)
            app.status(f"{msg} Recibo emitido para assinatura.", ft.Colors.AMBER_400)
        except Exception:
            log.exception("Falha ao gerar o comprovante de sangria")
            app.status(f"{msg} ATENÇÃO: não foi possível gerar o comprovante.", ft.Colors.ORANGE_400)
        self.fechar()


# --- cancelamento de item ----------------------------------------------------------------------------------

class CancelarItemModal(ModalBase):
    foco = "numero"

    def construir(self):
        self.numero = ft.TextField(
            label="Número do Item na Bobina", hint_text="Ex: 1, 2, 3... (Vazio cancela o último)",
            keyboard_type=ft.KeyboardType.NUMBER, dense=True, autofocus=True,
        )
        self.numero.on_submit = self.confirmar
        self.erro = _texto_erro()
        return _dialogo(
            ft.Icons.DELETE_SWEEP, ft.Colors.AMBER_400, "Cancelar Item [I]",
            [
                ft.Text("Informe o número do item que deseja cancelar (ou tecle ENTER para cancelar o último):", size=13, color=ft.Colors.GREY_300),
                self.numero, self.erro,
            ], 380,
            [
                ft.TextButton("Cancelar (ESC)", on_click=self.fechar),
                _botao_primario("Confirmar (ENTER)", ft.Icons.CHECK, ft.Colors.AMBER_800, self.confirmar),
            ],
            spacing=10,
        )

    def preparar(self):
        if not self.app.carrinho:
            self.app.status("Nenhum item para cancelar no carrinho!", ft.Colors.ORANGE_400)
            return False
        self.numero.value = str(len(self.app.carrinho))
        self.erro.value = ""

    def confirmar(self, e=None):
        texto = (self.numero.value or "").strip()
        try:
            indice = (int(texto) - 1) if texto else len(self.app.carrinho) - 1
        except ValueError:
            self.erro.value = "Digite apenas o número do item!"
            self.page.update()
            return
        if indice < 0 or indice >= len(self.app.carrinho):
            self.erro.value = f"Item {texto} não encontrado no cupom!"
            self.page.update()
            return
        self.fechar()
        self.app.solicitar_cancelamento_item(indice)


# --- cancelamento de cupom ------------------------------------------------------------------------------------

class CancelarCupomModal(ModalBase):
    foco = "matricula"

    def construir(self):
        self.motivo = ft.TextField(label="Motivo do Cancelamento", value="Desistência do cliente", dense=True)
        self.matricula = ft.TextField(label="Matrícula do Supervisor/Gerente", dense=True)
        self.senha = ft.TextField(label="Senha de Autorização", password=True, can_reveal_password=True, dense=True)
        self.erro = _texto_erro()
        return _dialogo(
            ft.Icons.DELETE_FOREVER, ft.Colors.RED_400, "Cancelamento de Cupom [C]",
            [
                ft.Text("Atenção: Todos os itens registrados serão cancelados.", size=13, color=ft.Colors.GREY_300),
                self.motivo, ft.Divider(),
                ft.Text("Autorização da Supervisão Obrigatória", weight=ft.FontWeight.BOLD, size=13, color=ft.Colors.RED_300),
                self.matricula, self.senha, self.erro,
            ], 430,
            [
                ft.TextButton("Voltar (ESC)", on_click=self.fechar),
                _botao_primario("Confirmar Cancelamento", ft.Icons.CHECK, ft.Colors.RED_800, self.confirmar),
            ],
        )

    def preparar(self):
        if not self.app.carrinho:
            self.app.status("Não há cupom aberto para cancelar!", ft.Colors.ORANGE_400)
            return False
        self.matricula.value = ""
        self.senha.value = ""
        self.erro.value = ""

    def confirmar(self, e=None):
        supervisor, erro = usuarios.autorizar_supervisor(self.matricula.value or "", self.senha.value or "")
        if not supervisor:
            self.erro.value = erro
            self.page.update()
            return
        self.senha.value = ""
        self.fechar()
        self.app.cancelar_cupom((self.motivo.value or "").strip() or "Desistência", supervisor)


# --- verificar preço ------------------------------------------------------------------------------------------------

class VerificarPrecoModal(ModalBase):
    foco = "codigo"

    def construir(self):
        self.codigo = ft.TextField(
            label="Código de Barras / SKU", hint_text="Digite o código para consultar...",
            keyboard_type=ft.KeyboardType.NUMBER, dense=True, autofocus=True,
        )
        self.codigo.on_submit = self.consultar
        self.resultado = ft.Text("Informe um código para verificar", size=14, color=ft.Colors.GREY_300)
        return _dialogo(
            ft.Icons.PRICE_CHECK, ft.Colors.BLUE_400, "Verificar Preço [P]",
            [self.codigo, self.resultado], 380,
            [
                ft.TextButton("Fechar (ESC)", on_click=self.fechar),
                ft.FilledButton("Consultar (ENTER)", on_click=self.consultar),
            ],
            altura=180,
        )

    def preparar(self):
        self.codigo.value = ""
        self.resultado.value = "Informe um código para verificar"
        self.resultado.color = ft.Colors.GREY_300

    def consultar(self, e=None):
        cod = (self.codigo.value or "").strip()
        if not cod:
            self.resultado.value = "Digite um código de barras válido."
            self.page.update()
            return
        produto = produtos.buscar_produto(cod)
        if produto:
            unit, _, campanha = svc_promo.aplicar(cod, 1, produto["preco"])
            promo = f"\nPROMOÇÃO: {campanha} ({fmt_brl(unit)})" if campanha else ""
            self.resultado.value = (
                f"PRODUTO: {produto['nome']}\nPREÇO TABELA: {fmt_brl(produto['preco'])}{promo}\n"
                f"ESTOQUE: {fmt_qtd(produto['estoque'])} un"
            )
            self.resultado.color = ft.Colors.GREEN_400
        else:
            self.resultado.value = f"Produto com código '{cod}' não encontrado!"
            self.resultado.color = ft.Colors.RED_400
        self.page.update()


# --- consulta de estoque ----------------------------------------------------------------------------------------------

class EstoqueModal(ModalBase):
    foco = "busca"

    def construir(self):
        self.busca = ft.TextField(hint_text="Digite o nome ou código de barras...", prefix_icon=ft.Icons.SEARCH, autofocus=True, dense=True)
        self.busca.on_change = lambda e: self.atualizar((self.busca.value or "").strip())
        self.linhas = ft.ListView(expand=True, spacing=4, padding=0)
        cabecalho = ft.Container(
            padding=8, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, border_radius=4,
            content=ft.Row(controls=[
                ft.Text("Código", weight=ft.FontWeight.BOLD, expand=3),
                ft.Text("Produto", weight=ft.FontWeight.BOLD, expand=5),
                ft.Text("Preço", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.RIGHT, expand=2),
                ft.Text("Estoque", weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.RIGHT, expand=2),
                ft.Container(width=48, alignment=ft.Alignment(0, 0), content=ft.Text("Ação", weight=ft.FontWeight.BOLD)),
            ]),
        )
        return ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.INVENTORY_2, color=ft.Colors.BLUE_400), ft.Text("Consulta de Estoque [M]")]),
            content=ft.Container(
                width=820, height=460,
                content=ft.Column(alignment=ft.MainAxisAlignment.START, spacing=8, controls=[self.busca, cabecalho, self.linhas]),
            ),
            actions=[ft.TextButton("Fechar (ESC)", on_click=self.fechar)],
        )

    def preparar(self):
        self.busca.value = ""
        self.atualizar("")

    def _adicionar(self, produto: dict) -> None:
        self.app.adicionar_produto(produto)
        self.fechar()

    def atualizar(self, termo: str) -> None:
        self.linhas.controls.clear()
        lista = produtos.consultar_produtos(termo, limite=50)
        if not lista:
            self.linhas.controls.append(
                ft.Container(padding=20, alignment=ft.Alignment(0, 0), content=ft.Text("Nenhum produto encontrado.", color=ft.Colors.GREY_400))
            )
        for p in lista:
            est = p["estoque"]
            cor = ft.Colors.RED_400 if est <= 0 else (ft.Colors.ORANGE_400 if est < 10 else ft.Colors.GREEN_400)
            self.linhas.controls.append(
                ft.Container(
                    padding=6, border_radius=4, ink=True,
                    content=ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
                        ft.Text(str(p["codigo_barras"]), expand=3, size=13),
                        ft.Text(p["nome"], expand=5, size=13, no_wrap=True, tooltip=p["nome"]),
                        ft.Text(fmt_brl(p["preco"]), expand=2, size=13, text_align=ft.TextAlign.RIGHT),
                        ft.Text(fmt_qtd(est), expand=2, size=13, text_align=ft.TextAlign.RIGHT, color=cor, weight=ft.FontWeight.BOLD),
                        ft.Container(width=48, alignment=ft.Alignment(0, 0), content=ft.IconButton(
                            icon=ft.Icons.ADD_SHOPPING_CART, icon_size=18, icon_color=ft.Colors.BLUE_400,
                            tooltip="Adicionar ao Carrinho",
                            on_click=lambda e, prod=p: self._adicionar(prod),
                        )),
                    ]),
                )
            )
        self.page.update()


# --- pagamento -------------------------------------------------------------------------------------------------------------------

class PagamentoModal(ModalBase):
    foco = "pago"

    def construir(self):
        self.txt_total = ft.Text(size=20, weight=ft.FontWeight.BOLD)
        self.txt_troco = ft.Text("Troco: R$ 0,00", size=16, color=ft.Colors.GREEN_400)
        self.forma = ft.Dropdown(
            label="Forma de Pagamento",
            options=[ft.dropdown.Option(f) for f in FORMAS_PAGAMENTO],
            value="Dinheiro",
        )
        self.forma.on_select = self._forma_mudou
        self.pago = campo_moeda("Valor Recebido (R$)", ao_mudar=self.calcular_troco)
        self.pago.on_submit = self.confirmar
        return ft.AlertDialog(
            modal=True,
            title=ft.Text("Pagamento e Fechamento (Enter para Concluir)"),
            content=ft.Column(tight=True, controls=[self.txt_total, self.forma, self.pago, self.txt_troco]),
            actions=[
                ft.TextButton("Cancelar (ESC)", on_click=self.fechar),
                _botao_primario("Concluir Venda (Enter)", None, ft.Colors.GREEN_700, self.confirmar),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def preparar(self):
        if not self.app.carrinho:
            self.app.status("Carrinho vazio! Adicione itens antes de finalizar.", ft.Colors.ORANGE_400)
            return False
        total = self.app.total()
        self.txt_total.value = f"Total a pagar: {fmt_brl(total)}"
        self.forma.value = "Dinheiro"
        self.pago.disabled = False
        self.pago.value = fmt_numero(total)
        self.txt_troco.value = "Troco: R$ 0,00"
        self.txt_troco.color = ft.Colors.GREEN_400

    def _forma_mudou(self, e=None):
        self.pago.disabled = (self.forma.value or "Dinheiro") != "Dinheiro"
        self.page.update()

    def calcular_troco(self, e=None):
        diferenca = parse_moeda(self.pago.value) - self.app.total()
        if diferenca >= 0:
            self.txt_troco.value = f"Troco: {fmt_brl(diferenca)}"
            self.txt_troco.color = ft.Colors.GREEN_400
        else:
            self.txt_troco.value = f"Faltam {fmt_brl(abs(diferenca))}"
            self.txt_troco.color = ft.Colors.RED_400
        self.page.update()

    def confirmar(self, e=None):
        total = self.app.total()
        forma = self.forma.value or "Dinheiro"
        if forma == "Dinheiro":
            recebido = parse_moeda(self.pago.value)
            if recebido < total:
                self.app.status("Valor pago é insuficiente!", ft.Colors.RED_400)
                return
        else:
            recebido = total
        self.fechar()
        self.app.concluir_venda(forma, recebido)


class SucessoVendaModal(ModalBase):
    def construir(self):
        return ft.AlertDialog(
            modal=True,
            title=ft.Row([
                ft.Icon(ft.Icons.CHECK_CIRCLE, color=ft.Colors.GREEN_400, size=30),
                ft.Text("COMPRA CONCLUÍDA COM SUCESSO", size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400),
            ]),
            content=ft.Container(
                width=380, height=140, alignment=ft.Alignment(0, 0),
                content=ft.Column(
                    alignment=ft.MainAxisAlignment.CENTER, horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8,
                    controls=[
                        ft.Text("O cupom não fiscal foi gerado.", size=14, color=ft.Colors.GREY_300),
                        ft.Text("Escolha a opção de impressão abaixo:", size=12, color=ft.Colors.GREY_400),
                    ],
                ),
            ),
            actions=[
                ft.OutlinedButton("Imprimir Cupom", icon=ft.Icons.PRINT, on_click=self.imprimir),
                _botao_primario("Novo Atendimento (OK)", ft.Icons.CHECK, ft.Colors.GREEN_700, self.fechar),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )

    def imprimir(self, e=None):
        v = self.app.venda_concluida
        if not v:
            return
        try:
            caminho = caminho_pdf(f"comprovante_venda_{v['ref']}.pdf")
            gerar_cupom_pdf(v["ref"], v["itens"], v["total"], v["forma"], v["recebido"], v["troco"], caminho)
            abrir_pdf_async(caminho)
        except Exception:
            log.exception("Falha ao imprimir o cupom")
            self.app.status("Não foi possível gerar o cupom.", ft.Colors.RED_400)

    def fechar(self, e=None):
        self.dialog.open = False
        self.app.iniciar_fluxo_pos_descanso()
        self.page.update()


# --- fechamento de turno / relatórios -----------------------------------------------------------------------------------------------------

class RelatorioGerencialModal(ModalBase):
    def construir(self):
        self.conteudo = ft.Text("", size=13, font_family="Consolas", color=ft.Colors.GREEN_300)
        return ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(ft.Icons.BAR_CHART, color=ft.Colors.BLUE_400), ft.Text("Relatório Gerencial de Caixa (Detalhado)")]),
            content=ft.Container(
                width=500, height=350, padding=10, bgcolor=ft.Colors.BLACK_54, border_radius=8,
                content=ft.ListView(expand=True, controls=[self.conteudo]),
            ),
            actions=[ft.TextButton("Fechar", on_click=self.fechar)],
        )

    def fechar(self, e=None):
        self.dialog.open = False
        self.page.update()

    def mostrar(self, dados: dict) -> None:
        f = dados["formas"]
        total = lambda chave: fmt_brl(f.get(chave, {"total": ZERO})["total"])
        atend = dados["qtd_vendas"]
        ticket = (dados["total_vendas"] / atend) if atend else ZERO
        self.conteudo.value = (
            f"=== {config.NOME_LOJA} - GERENCIAL ===\n"
            f"Identificação: {dados['identificador']}\n"
            f"Operador: {dados['operador']}\n"
            f"Abertura: {dados['data_abertura']}\n"
            f"----------------------------------------\n"
            f"(+) Fundo Inicial: {fmt_brl(dados['fundo_inicial'])}\n"
            f"(+) Vendas Brutas: {fmt_brl(dados['total_vendas'])}\n"
            f"    - Dinheiro: {total(FORMA_DINHEIRO)}\n"
            f"    - Crédito:  {total(FORMA_CREDITO)}\n"
            f"    - Débito:   {total(FORMA_DEBITO)}\n"
            f"    - PIX:      {total(FORMA_PIX)}\n"
            f"(-) Sangrias:   {fmt_brl(dados['total_sangrias'])}\n"
            f"----------------------------------------\n"
            f"(=) Dinheiro Esperado: {fmt_brl(dados['dinheiro_sistema'])}\n"
            f"Atendimentos Totais: {atend}\n"
            f"Ticket Médio: {fmt_brl(ticket)}\n"
            f"========================================"
        )
        self.abrir()


class FechamentoModal(ModalBase):
    foco = "contagem"

    def construir(self):
        self.info = ft.Text("", size=13, color=ft.Colors.WHITE_70)
        self.contagem = campo_moeda("Contagem Física do Dinheiro (R$)")
        self.erro = _texto_erro()
        self.relatorio = RelatorioGerencialModal(self.app)
        return _dialogo(
            ft.Icons.ASSESSMENT, ft.Colors.RED_400, "Fechamento de Caixa / Leitura X [F]",
            [self.info, self.contagem, self.erro], 480,
            [
                ft.TextButton("Cancelar (ESC)", on_click=self.fechar),
                ft.OutlinedButton("Relatório Detalhado", icon=ft.Icons.ANALYTICS, on_click=self.ver_detalhado),
                ft.OutlinedButton("Leitura X (Total Dia)", icon=ft.Icons.PRINT, on_click=self.leitura_x),
                _botao_primario("Encerrar Turno Operador", ft.Icons.CHECK, ft.Colors.RED_700, self.encerrar),
            ],
        )

    def preparar(self):
        app = self.app
        if not app.caixa:
            app.status("Nenhum turno de caixa aberto no momento!", ft.Colors.ORANGE_400)
            return False
        if app.carrinho:
            app.status("Conclua ou cancele a venda atual antes de fechar o turno!", ft.Colors.ORANGE_400)
            return False
        dados = caixa_db.dados_fechamento_turno(app.caixa["id"])
        if not dados:
            app.status("Não foi possível carregar os dados do turno (sem conexão?).", ft.Colors.ORANGE_400)
            return False

        f = dados["formas"]
        din = f.get(FORMA_DINHEIRO, {"total": ZERO})["total"]
        cre = f.get(FORMA_CREDITO, {"total": ZERO})["total"]
        deb = f.get(FORMA_DEBITO, {"total": ZERO})["total"]
        pix = f.get(FORMA_PIX, {"total": ZERO})["total"]
        atend = dados["qtd_vendas"]
        ticket = (dados["total_vendas"] / atend) if atend else ZERO
        texto = (
            f"Operador: {app.caixa['operador']}\n"
            f"Fundo de Troco: {fmt_brl(app.caixa['saldo_inicial'])}\n"
            f"Total Vendas: {fmt_brl(dados['total_vendas'])}\n"
            f"  - Dinheiro: {fmt_brl(din)}\n"
            f"  - Cartão: {fmt_brl(cre + deb)} (Créd: {fmt_brl(cre)} | Déb: {fmt_brl(deb)})\n"
            f"  - Pix: {fmt_brl(pix)}\n"
            f"Retiradas / Sangrias: {fmt_brl(dados['total_sangrias'])}\n"
            f"Atendimentos: {atend} | Ticket Médio: {fmt_brl(ticket)}"
        )
        pendentes = local.contar_vendas_offline()
        if pendentes:
            texto += f"\n\nATENÇÃO: {pendentes} venda(s) offline ainda não sincronizadas. Os totais acima estão incompletos."
        self.info.value = texto
        self.contagem.value = "0,00"
        self.erro.value = ""

    def ver_detalhado(self, e=None):
        dados = caixa_db.dados_fechamento_turno(self.app.caixa["id"]) if self.app.caixa else None
        if not dados:
            self.erro.value = "Não foi possível carregar os dados do turno!"
            self.page.update()
            return
        self.relatorio.mostrar(dados)

    def leitura_x(self, e=None):
        dados = caixa_db.dados_fechamento_dia()
        if not dados or (dados["qtd_vendas"] == 0 and dados["fundo_inicial"] == 0):
            self.erro.value = "Sem movimentações registradas no dia para Leitura X!"
            self.page.update()
            return
        caminho = caminho_pdf(f"leitura_x_geral_{self._agora()}.pdf")
        gerar_relatorio_fechamento_pdf(dados, caminho)
        abrir_pdf_async(caminho)
        self.app.status("Leitura X impressa com sucesso!", ft.Colors.GREEN_400)
        self.fechar()

    @staticmethod
    def _agora() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def encerrar(self, e=None):
        app = self.app
        if not app.caixa:
            return
        contado = parse_moeda(self.contagem.value)
        dados = caixa_db.dados_fechamento_turno(app.caixa["id"], dinheiro_contado=contado)
        ok, msg = caixa_db.fechar_caixa(app.caixa["id"], contado)
        if not ok:
            self.erro.value = msg
            self.page.update()
            return
        if dados:
            try:
                caminho = caminho_pdf(f"fechamento_turno_{app.caixa['id']}.pdf")
                gerar_relatorio_fechamento_pdf(dados, caminho)
                abrir_pdf_async(caminho)
            except Exception:
                log.exception("Falha ao gerar o relatório de fechamento")
        self.dialog.open = False
        app.encerrar_turno(msg)


# --- configurações (criado uma vez só) --------------------------------------------------------------------------------------------------------

class ConfiguracoesModal(ModalBase):
    def construir(self):
        from pdv.ui.tema import TEMAS_COMERCIAIS

        app = self.app
        self.num_pdv = ft.TextField(
            label="Número Fixo deste PDV", value=str(app.numero_pdv),
            keyboard_type=ft.KeyboardType.NUMBER, dense=True,
            on_change=lambda e: app.definir_numero_pdv(e.control.value),
        )
        self.tema = ft.Dropdown(
            options=[ft.dropdown.Option("Escuro"), ft.dropdown.Option("Claro")],
            value=app.nome_tema_claro_escuro, dense=True,
            on_select=lambda e: app.definir_tema_claro_escuro(e.control.value),
        )
        self.identidade = ft.Dropdown(
            options=[ft.dropdown.Option(n) for n in TEMAS_COMERCIAIS],
            value=app.tema_comercial, dense=True,
            on_select=lambda e: app.definir_tema_comercial(e.control.value),
        )
        return _dialogo(
            ft.Icons.PALETTE, ft.Colors.BLUE_400, "Configurações do PDV",
            [
                self.num_pdv,
                ft.Text("Tema de Cores da UI:", weight=ft.FontWeight.BOLD, size=12), self.tema,
                ft.Text("Identidade Visual / Setor:", weight=ft.FontWeight.BOLD, size=12), self.identidade,
            ], 340,
            [ft.TextButton("Salvar e Fechar", on_click=self.fechar)],
            altura=260, modal=False, spacing=10,
        )

    def preparar(self):
        self.num_pdv.value = str(self.app.numero_pdv)
        self.tema.value = self.app.nome_tema_claro_escuro
        self.identidade.value = self.app.tema_comercial
