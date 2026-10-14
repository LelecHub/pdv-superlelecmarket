"""Aplicação Flet do PDV: estado da venda e ações. Telas em telas.py, modais em modais.py, teclas em teclado.py."""
from __future__ import annotations

import logging
from decimal import Decimal

import flet as ft

from pdv import config
from pdv.db import caixa as caixa_db
from pdv.db import carrinho as carrinho_db
from pdv.db import local, produtos, usuarios, vendas
from pdv.db.modelos import DadosVenda, ResultadoVenda
from pdv.db.pool import SemConexao
from pdv.money import ZERO, D, fmt_brl, fmt_qtd
from pdv.relatorios.base import abrir_pdf_async, caminho_pdf
from pdv.relatorios.cupom import gerar_cupom_pdf
from pdv.services import promocoes as svc_promo
from pdv.ui import modais, teclado, telas, tema
from pdv.ui.compat import focar, mostrar_aviso
from pdv.ui.estado import ClienteVenda

log = logging.getLogger(__name__)

_SEM_PRODUTO_TXT = "Passe o primeiro item pelo leitor"


class PDVApp:
    def __init__(self, page: ft.Page) -> None:
        self.page = page
        page.title = "PDV - Ponto de Venda"
        page.padding = 0
        page.window.full_screen = True

        prefs = config.carregar_configuracoes_locais()
        page.theme_mode = ft.ThemeMode.DARK if prefs.get("tema") == "Escuro" else ft.ThemeMode.LIGHT
        self.tema_comercial: str = prefs.get("cor", tema.TEMA_PADRAO)
        self.cor = tema.cor_do_tema(self.tema_comercial)
        self.numero_pdv: int = int(prefs.get("numero_caixa", 1))
        self.nome_loja = config.NOME_LOJA

        self.caixa: dict | None = None
        self.carrinho: list[dict] = []
        self.cliente = ClienteVenda()
        self.tela = "descanso"
        self.venda_concluida: dict = {}
        self._finalizando = False
        self.modais: list[modais.ModalBase] = []

        self._criar_controles()
        self._criar_modais()
        page.on_keyboard_event = teclado.criar_handler(self)

    # ------------------------------------------------------------------ construção

    def _criar_controles(self) -> None:
        self.txt_info_caixa = ft.Text(f"PDV #{self.numero_pdv:02d} : Fechado", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_400)
        self.txt_status = ft.Text("Aguardando...", color=ft.Colors.GREY_400, size=13)
        self.txt_ultimo_nome = ft.Text("CAIXA LIVRE", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE, text_align=ft.TextAlign.CENTER)
        self.txt_ultimo_qtd_preco = ft.Text(_SEM_PRODUTO_TXT, size=16, color=ft.Colors.GREY_400, text_align=ft.TextAlign.CENTER)
        self.txt_ultimo_subtotal = ft.Text("R$ 0,00", size=38, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_400, text_align=ft.TextAlign.CENTER)
        self.txt_total = ft.Text("R$ 0,00", size=56, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400, text_align=ft.TextAlign.CENTER)
        self.lista_produtos = ft.ListView(expand=True, spacing=6, auto_scroll=True)

        self.campo_codigo = ft.TextField(
            label="Código de Barras / SKU (Somente Números)",
            hint_text="Bipe o produto. Com campo vazio: ENTER ou F4 finaliza a compra.",
            input_filter=ft.NumbersOnlyInputFilter(), keyboard_type=ft.KeyboardType.NUMBER,
            autofocus=True, on_submit=self.bipar_produto, expand=True, text_size=18, height=54,
            disabled=True,
        )
        self.botao_finalizar = ft.FilledButton(
            "Finalizar Venda (F4 / ENTER)", icon=ft.Icons.CHECK_CIRCLE, height=54, disabled=True,
            style=ft.ButtonStyle(
                bgcolor=self.cor, color=ft.Colors.WHITE,
                padding=ft.Padding(24, 14, 24, 14), shape=ft.RoundedRectangleBorder(radius=8),
            ),
            on_click=lambda e: self.m_pagamento.abrir(),
        )
        self.img_fundo = ft.Image(src=telas.fundo_por_horario(), fit="cover", width=float("inf"), height=float("inf"))

    def _criar_modais(self) -> None:
        self.m_abertura = modais.AberturaModal(self)
        self.m_autorizacao = modais.AutorizacaoModal(self)
        self.m_sangria = modais.SangriaModal(self)
        self.m_canc_item = modais.CancelarItemModal(self)
        self.m_canc_cupom = modais.CancelarCupomModal(self)
        self.m_preco = modais.VerificarPrecoModal(self)
        self.m_estoque = modais.EstoqueModal(self)
        self.m_pagamento = modais.PagamentoModal(self)
        self.m_sucesso = modais.SucessoVendaModal(self)
        self.m_fechamento = modais.FechamentoModal(self)  # cria também o modal de relatório gerencial
        self.m_config = modais.ConfiguracoesModal(self)

    # ------------------------------------------------------------------ inicialização

    def iniciar(self) -> None:
        self._restaurar_turno()
        self.alternar_tela("descanso")

    def _restaurar_turno(self) -> None:
        dados = None
        try:
            dados = caixa_db.obter_caixa_aberto(self.numero_pdv)
            self._guardar_turno_local(dados)
        except SemConexao:
            salvo = local.ler_estado("caixa")
            if salvo:
                salvo["saldo_inicial"] = D(salvo.get("saldo_inicial"))
                dados = salvo
                log.warning("Banco indisponível: turno #%s restaurado do estado local (modo offline).", salvo.get("id"))
        except Exception:
            log.exception("Erro ao restaurar o turno")

        if not dados:
            self._aplicar_estado_caixa()
            self.status("Aguardando...", ft.Colors.GREY_400)
            return

        self.caixa = dados
        self._aplicar_estado_caixa()

        itens = carrinho_db.carregar_carrinho(dados["id"])
        for item in itens:
            self._recalcular(item)
        self.carrinho.extend(itens)
        if self.carrinho:
            self._atualizar_ultimo(self.carrinho[-1])
            self.renderizar_carrinho()
            self.status(f"Venda restaurada: {len(self.carrinho)} itens recuperados.", ft.Colors.AMBER_400)
        else:
            self.status("Aguardando bipagem...", self.cor)

    @staticmethod
    def _guardar_turno_local(dados: dict | None) -> None:
        if dados is None:
            local.salvar_estado("caixa", None)
        else:
            local.salvar_estado("caixa", {**dados, "saldo_inicial": str(dados["saldo_inicial"])})

    # ------------------------------------------------------------------ utilidades de UI

    @property
    def nome_tema_claro_escuro(self) -> str:
        return "Escuro" if self.page.theme_mode == ft.ThemeMode.DARK else "Claro"

    def status(self, msg: str, cor=None) -> None:
        self.txt_status.value = msg
        self.txt_status.color = cor or self.cor
        self.page.update()

    def _atualizar_info_caixa(self) -> None:
        if self.caixa:
            self.txt_info_caixa.value = f"PDV #{self.numero_pdv:02d} | Op: {self.caixa['operador']}"
            self.txt_info_caixa.color = self.cor
        else:
            self.txt_info_caixa.value = f"PDV #{self.numero_pdv:02d} : Fechado"
            self.txt_info_caixa.color = ft.Colors.AMBER_400

    def _aplicar_estado_caixa(self) -> None:
        aberto = self.caixa is not None
        self.campo_codigo.disabled = not aberto
        self.botao_finalizar.disabled = not aberto
        self._atualizar_info_caixa()

    def alternar_tela(self, nome: str) -> None:
        self.tela = nome
        self.page.controls.clear()
        construtores = {
            "descanso": telas.descanso,
            "identificacao_cliente_pergunta": telas.pergunta_cpf,
            "identificacao_cliente_digitar": telas.digitar_cpf,
            "identificacao_preferencias": telas.preferencias,
        }
        self.page.controls.append(construtores.get(nome, telas.venda)(self))
        self.page.update()
        if nome not in construtores:
            focar(self.page, self.campo_codigo)

    def iniciar_fluxo_pos_descanso(self) -> None:
        self.alternar_tela("identificacao_cliente_pergunta")

    def escolher_preferencia_cliente(self, tecla: str) -> None:
        c = self.cliente
        c.preferencia, c.cpf, c.id = tecla, c.cpf_tmp, c.id_tmp
        self.status(f"Cliente vinculado com sucesso! Preferência [{tecla}] aplicada.")
        self.alternar_tela("venda")

    def digitar_no_campo_codigo(self, digito: str) -> None:
        self.campo_codigo.value = (self.campo_codigo.value or "") + digito
        focar(self.page, self.campo_codigo)
        self.page.update()

    # ------------------------------------------------------------------ turno

    def abrir_turno(self, caixa_id: int, usuario: dict, saldo: Decimal, msg: str) -> None:
        self.caixa = {
            "id": caixa_id,
            "usuario_id": usuario["id"],
            "operador": usuario["nome"],
            "saldo_inicial": saldo,
            "perfil": usuario.get("perfil", "OPERADOR"),
        }
        try:
            self._guardar_turno_local(self.caixa)
        except Exception:
            log.exception("Não foi possível guardar o turno localmente")
        self._aplicar_estado_caixa()

        campanhas = svc_promo.campanhas_ativas()
        extra = f" | Promoções ativas: {', '.join(c[0] for c in campanhas)}" if campanhas else ""
        self.status(f"{msg}{extra} Pronto para operar.")
        self.iniciar_fluxo_pos_descanso()

    def encerrar_turno(self, msg: str) -> None:
        self.caixa = None
        self.limpar_venda("CAIXA FECHADO", "Abra o turno para iniciar vendas")
        try:
            self._guardar_turno_local(None)
        except Exception:
            log.exception("Não foi possível limpar o turno local")
        self._aplicar_estado_caixa()
        self.status(f"{msg} Fechamento impresso.", ft.Colors.GREEN_400)
        self.alternar_tela("descanso")

    # ------------------------------------------------------------------ carrinho

    def total(self) -> Decimal:
        return sum((i["subtotal"] for i in self.carrinho), ZERO)

    def _recalcular(self, item: dict) -> None:
        unit, subtotal, campanha = svc_promo.aplicar(item["codigo_barras"], item["quantidade"], item["preco_tabela"])
        item["preco_unit"], item["subtotal"], item["promo"] = unit, subtotal, campanha

    def _atualizar_ultimo(self, item: dict) -> None:
        self.txt_ultimo_nome.value = item["nome"].upper()
        self.txt_ultimo_qtd_preco.value = (
            f"QTD: {fmt_qtd(item['quantidade'])}  x  {fmt_brl(item['preco_unit'])}" + (" [PROMO]" if item["promo"] else "")
        )
        self.txt_ultimo_subtotal.value = fmt_brl(item["subtotal"])

    def limpar_venda(self, titulo: str = "CAIXA LIVRE", subtitulo: str = _SEM_PRODUTO_TXT) -> None:
        self.carrinho.clear()
        self.cliente.resetar()
        self.txt_ultimo_nome.value = titulo
        self.txt_ultimo_qtd_preco.value = subtitulo
        self.txt_ultimo_subtotal.value = "R$ 0,00"
        self.renderizar_carrinho()

    def renderizar_carrinho(self) -> None:
        self.lista_produtos.controls.clear()
        for idx, item in enumerate(self.carrinho, start=1):
            sem_estoque = item["quantidade"] > item["estoque"]
            nome = [ft.Text(item["nome"], size=15, weight=ft.FontWeight.W_500)]
            if item["promo"]:
                nome.append(ft.Text(f"PROMO: {item['promo']}", size=11, color=ft.Colors.AMBER_400))
            self.lista_produtos.controls.append(
                ft.Container(
                    padding=12, bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST, border_radius=6,
                    border=ft.Border.all(1, ft.Colors.ORANGE_700) if sem_estoque else None,
                    content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_BETWEEN, controls=[
                        ft.Row([
                            ft.Text(f"{idx:02d}.", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.GREY_400),
                            ft.Column(nome, spacing=0, tight=True),
                            ft.Container(
                                visible=sem_estoque, bgcolor=ft.Colors.ORANGE_800,
                                padding=ft.Padding(6, 2, 6, 2), border_radius=4,
                                content=ft.Text("SEM ESTOQUE", size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                            ),
                        ], spacing=8),
                        ft.Row([
                            ft.Text(f"{fmt_qtd(item['quantidade'])} x {fmt_brl(item['preco_unit'])}", size=13, color=ft.Colors.GREY_400),
                            ft.Container(width=10),
                            ft.Text(fmt_brl(item["subtotal"]), size=15, weight=ft.FontWeight.BOLD),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_400, icon_size=18,
                                tooltip=f"Cancelar item {idx} ({item['nome']})",
                                on_click=lambda e, pos=idx - 1: self.solicitar_cancelamento_item(pos),
                            ),
                        ], spacing=4),
                    ]),
                )
            )
        self.txt_total.value = fmt_brl(self.total())
        self.page.update()

    def _persistir_carrinho(self) -> None:
        carrinho_db.salvar_carrinho(self.caixa["id"] if self.caixa else None, self.carrinho)

    def bipar_produto(self, e=None) -> None:
        codigo = (self.campo_codigo.value or "").strip()
        if not codigo:
            if self.carrinho:
                self.m_pagamento.abrir()
            return
        produto = produtos.buscar_produto(codigo)
        if produto:
            self.adicionar_produto(produto)
        else:
            mostrar_aviso(self.page, f"ATENÇÃO: código '{codigo}' não encontrado!")
        self.campo_codigo.value = ""
        focar(self.page, self.campo_codigo)
        self.page.update()

    def adicionar_produto(self, produto: dict) -> None:
        item = next((i for i in self.carrinho if i["id"] == produto["id"]), None)
        if item:
            item["quantidade"] += 1
        else:
            item = {
                "id": produto["id"], "nome": produto["nome"], "codigo_barras": produto["codigo_barras"] or "",
                "preco_tabela": produto["preco"], "estoque": produto["estoque"], "quantidade": Decimal(1),
                "preco_unit": produto["preco"], "subtotal": produto["preco"], "promo": "",
            }
            self.carrinho.append(item)
        self._recalcular(item)
        self._atualizar_ultimo(item)
        self._persistir_carrinho()

        saldo = item["estoque"] - item["quantidade"]
        if saldo < 0:
            if item["estoque"] <= 0:
                self.status(f"[ALERTA ESTOQUE] {item['nome']} | Estoque cadastrado ZERADO.", ft.Colors.ORANGE_400)
            else:
                self.status(
                    f"[ALERTA ESTOQUE] {item['nome']} (x{fmt_qtd(item['quantidade'])}) | Saldo insuficiente: {fmt_qtd(saldo)} un",
                    ft.Colors.ORANGE_400,
                )
        else:
            extra = f" - Promo: {item['promo']}" if item["promo"] else ""
            self.status(f"Adicionado: {item['nome']} (x{fmt_qtd(item['quantidade'])}){extra}")
        self.renderizar_carrinho()

    # ------------------------------------------------------------------ cancelamentos

    def _valor_do_cancelamento(self, indice: int) -> Decimal:
        item = self.carrinho[indice]
        if item["quantidade"] > 1:
            _, novo_subtotal, _ = svc_promo.aplicar(item["codigo_barras"], item["quantidade"] - 1, item["preco_tabela"])
            return item["subtotal"] - novo_subtotal
        return item["subtotal"]

    def solicitar_cancelamento_item(self, indice: int) -> None:
        """Item de valor alto só é cancelado com senha de supervisor (a menos que o operador logado seja um)."""
        if not self.caixa or indice < 0 or indice >= len(self.carrinho):
            self.status("Item inválido!", ft.Colors.ORANGE_400)
            return
        valor = self._valor_do_cancelamento(indice)
        if valor > config.LIMITE_CANCELAMENTO_ITEM and not usuarios.eh_supervisor({"perfil": self.caixa.get("perfil")}):
            item = self.carrinho[indice]
            self.m_autorizacao.pedir(
                f"Cancelar o item {indice + 1} ({item['nome']}), no valor de {fmt_brl(valor)}, exige autorização de supervisor.",
                lambda sup: self._cancelar_item(indice, sup["id"]),
            )
            return
        self._cancelar_item(indice, self.caixa["usuario_id"])

    def _cancelar_item(self, indice: int, autorizado_por: int | None) -> None:
        if indice < 0 or indice >= len(self.carrinho):
            self.status("Item inválido!", ft.Colors.ORANGE_400)
            return
        item = self.carrinho[indice]
        nome = item["nome"]
        valor = self._valor_do_cancelamento(indice)

        if item["quantidade"] > 1:
            item["quantidade"] -= 1
            self._recalcular(item)
        else:
            self.carrinho.pop(indice)

        self._persistir_carrinho()
        caixa_db.registrar_auditoria_cancelamento(
            self.caixa["id"], "ITEM", f"Item cancelado: {nome} (Posição {indice + 1})", valor, autorizado_por
        )
        if self.carrinho:
            self._atualizar_ultimo(self.carrinho[-1])
        else:
            self.txt_ultimo_nome.value = "CAIXA LIVRE"
            self.txt_ultimo_qtd_preco.value = _SEM_PRODUTO_TXT
            self.txt_ultimo_subtotal.value = "R$ 0,00"
        self.renderizar_carrinho()
        self.status(f"Item '{nome}' cancelado com sucesso.", ft.Colors.AMBER_400)

    def cancelar_cupom(self, motivo: str, supervisor: dict) -> None:
        total = self.total()
        caixa_db.registrar_auditoria_cancelamento(
            self.caixa["id"], "CUPOM", f"Cancelamento de cupom ({len(self.carrinho)} itens). Motivo: {motivo}",
            total, supervisor["id"],
        )
        carrinho_db.limpar_carrinho(self.caixa["id"])
        self.limpar_venda("CUPOM CANCELADO", f"Autorizado por: {supervisor['nome']}")
        self.status(f"Cupom cancelado com sucesso por {supervisor['nome']}.", ft.Colors.RED_400)

    # ------------------------------------------------------------------ finalização

    def concluir_venda(self, forma: str, valor_recebido: Decimal) -> ResultadoVenda | None:
        if self._finalizando or not self.carrinho or not self.caixa:
            return None
        self._finalizando = True  # evita venda duplicada por Enter repetido
        try:
            total = self.total()
            itens = [dict(i) for i in self.carrinho]
            dv = DadosVenda(
                itens=itens, total=total, forma=forma, recebido=valor_recebido,
                troco=max(ZERO, valor_recebido - total), caixa_id=self.caixa["id"],
                cliente_id=self.cliente.id_fidelidade, cpf_nota=self.cliente.cpf_na_nota,
            )
            resultado = vendas.finalizar_venda(dv)
            if not resultado.ok:
                self.status(resultado.msg, ft.Colors.RED_400)
                return resultado

            self.venda_concluida = {
                "ref": resultado.ref, "total": total, "forma": forma,
                "recebido": valor_recebido, "troco": dv.troco, "itens": itens,
            }
            try:
                caminho = caminho_pdf(f"comprovante_venda_{resultado.ref}.pdf")
                gerar_cupom_pdf(resultado.ref, itens, total, forma, valor_recebido, dv.troco, caminho)
                abrir_pdf_async(caminho)
            except Exception:
                log.exception("Venda gravada, mas o cupom não pôde ser gerado")

            self.limpar_venda()
            troco = f" Troco: {fmt_brl(dv.troco)}" if dv.troco > 0 else ""
            self.status(f"{resultado.msg}{troco}", ft.Colors.AMBER_400 if resultado.offline else self.cor)
            self.m_sucesso.abrir()
            return resultado
        finally:
            self._finalizando = False

    def reimprimir_ultimo_cupom(self, e=None) -> None:
        if not self.caixa:
            return
        # Venda desta sessão (inclui as offline, que ainda não existem no servidor)
        v = self.venda_concluida
        if v:
            ref, itens, total, forma, recebido, troco = v["ref"], v["itens"], v["total"], v["forma"], v["recebido"], v["troco"]
        else:
            venda_id = vendas.ultima_venda_id(self.caixa["id"])
            venda, itens = vendas.obter_dados_venda(venda_id) if venda_id else (None, [])
            if not venda or not itens:
                self.status("Nenhuma venda registrada para reimprimir!", ft.Colors.ORANGE_400)
                return
            ref, total, forma, recebido, troco = f"{venda_id:05d}", venda["total"], venda["forma"], venda["recebido"], venda["troco"]
        try:
            caminho = caminho_pdf(f"reimpressao_cupom_{ref}.pdf")
            gerar_cupom_pdf(ref, itens, total, forma, recebido, troco, caminho)
            abrir_pdf_async(caminho)
            self.status(f"Reimpressão do Cupom #{ref} gerada com sucesso!", ft.Colors.GREEN_400)
        except Exception:
            log.exception("Falha na reimpressão")
            self.status("Erro ao gerar a reimpressão.", ft.Colors.RED_400)

    # ------------------------------------------------------------------ configurações

    def _salvar_preferencias(self) -> None:
        config.salvar_configuracoes_locais(
            {"numero_caixa": self.numero_pdv, "tema": self.nome_tema_claro_escuro, "cor": self.tema_comercial}
        )

    def definir_tema_claro_escuro(self, valor: str) -> None:
        self.page.theme_mode = ft.ThemeMode.DARK if valor == "Escuro" else ft.ThemeMode.LIGHT
        self._salvar_preferencias()
        self.alternar_tela(self.tela)

    def definir_tema_comercial(self, valor: str) -> None:
        self.tema_comercial = valor
        self.cor = tema.cor_do_tema(valor)
        self.botao_finalizar.style = ft.ButtonStyle(
            bgcolor=self.cor, color=ft.Colors.WHITE,
            padding=ft.Padding(24, 14, 24, 14), shape=ft.RoundedRectangleBorder(radius=8),
        )
        self._salvar_preferencias()
        self._atualizar_info_caixa()
        self.alternar_tela(self.tela)

    def definir_numero_pdv(self, texto: str) -> None:
        try:
            valor = int(texto)
        except (TypeError, ValueError):
            return
        if valor > 0 and valor != self.numero_pdv:
            self.numero_pdv = valor
            self._atualizar_info_caixa()
            self._salvar_preferencias()
            self.page.update()


def main(page: ft.Page) -> None:
    app = PDVApp(page)
    app.iniciar()
