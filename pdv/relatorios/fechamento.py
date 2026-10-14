"""Relatório de fechamento de turno / Leitura X."""
from __future__ import annotations

from datetime import datetime

from reportlab.platypus import Paragraph

from pdv.constantes import FORMA_CREDITO, FORMA_DEBITO, FORMA_DINHEIRO, FORMA_PIX
from pdv.money import ZERO, fmt_numero
from pdv.relatorios import base


def _total_forma(dados: dict, chave: str):
    return dados["formas"].get(chave, {"total": ZERO})["total"]


def _com_sinal(valor) -> str:
    return ("+" if valor > 0 else "") + fmt_numero(valor)


def gerar_relatorio_fechamento_pdf(dados: dict, caminho_saida: str) -> None:
    est = base.estilos()
    doc = base.documento(caminho_saida, 245, margem_h_mm=3, margem_v_mm=4)
    util = base.largura_util(3)

    elementos = base.cabecalho(est, [f"EMISSÃO: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"])
    elementos += [Paragraph(f"<b>*** {base.texto(dados['tipo_relatorio'])} ***</b>", est["titulo"]), base.espaco(2)]

    abertura = dados["data_abertura"]
    cabecalho = [
        ["Identificação:", dados["identificador"]],
        ["Operador:", dados["operador"][:22]],
        ["Abertura:", abertura.strftime("%d/%m/%Y %H:%M") if isinstance(abertura, datetime) else str(abertura)],
        ["Fechamento:", dados["data_fechamento"].strftime("%d/%m/%Y %H:%M")],
    ]
    elementos += [base.tabela(cabecalho, [0.35, 0.65], util, direita_de=None, linha_abaixo=(-1,)), base.espaco(2)]

    v_din = _total_forma(dados, FORMA_DINHEIRO)
    v_cre = _total_forma(dados, FORMA_CREDITO)
    v_deb = _total_forma(dados, FORMA_DEBITO)
    v_car = v_cre + v_deb
    v_pix = _total_forma(dados, FORMA_PIX)
    total = dados["total_vendas"]
    status = _com_sinal(dados["diferenca"]) if dados.get("houve_quebra") else "0,00"

    pagamentos = [
        ["Tipo pagamento", "Disponível", "Contagem", "Consolid."],
        ["- Dinheiro:", fmt_numero(v_din), fmt_numero(dados.get("dinheiro_contado", v_din)), status],
        ["- Cartão:", fmt_numero(v_car), fmt_numero(v_car), "0,00"],
        ["  - Crédito:", fmt_numero(v_cre), fmt_numero(v_cre), "0,00"],
        ["  - Débito:", fmt_numero(v_deb), fmt_numero(v_deb), "0,00"],
        ["- Pix:", fmt_numero(v_pix), fmt_numero(v_pix), "0,00"],
        ["Total:", fmt_numero(total), fmt_numero(total), status],
    ]
    elementos += [
        base.tabela(pagamentos, [0.37, 0.21, 0.21, 0.21], util, negrito_linhas=(0, -1), linha_abaixo=(0,), linha_acima=(-1,), padding=1),
        base.espaco(2),
    ]

    computado = [
        ["COMPUTADO (FT+VND+ENT+RCBT)", ""],
        ["Total:", fmt_numero(total + dados["fundo_inicial"])],
        ["- Dinheiro:", fmt_numero(v_din + dados["fundo_inicial"])],
        ["- Cartão:", fmt_numero(v_car)],
        ["  - Crédito:", fmt_numero(v_cre)],
        ["  - Débito:", fmt_numero(v_deb)],
        ["- Pix:", fmt_numero(v_pix)],
    ]
    elementos += [base.tabela(computado, [0.60, 0.40], util, negrito_linhas=(0, 1), linha_abaixo=(0,)), base.espaco(2)]

    gaveta = [
        ["DETALHAMENTO DO NUMERÁRIO / GAVETA", ""],
        ["(+) Fundo de Troco Inicial:", f"R$ {fmt_numero(dados['fundo_inicial'])}"],
        ["(+) Entradas em Dinheiro (Vendas):", f"R$ {fmt_numero(v_din)}"],
        ["(-) Detalhamento de Retirada (Sangrias):", f"- R$ {fmt_numero(dados['total_sangrias'])}"],
        ["(=) Saldo Apurado no Sistema:", f"R$ {fmt_numero(dados['dinheiro_sistema'])}"],
        ["Conferência Física Declarada:", f"R$ {fmt_numero(dados['dinheiro_contado'])}"],
        ["Estado da Conferência:", "QUEBRA / DIVERGÊNCIA" if dados.get("houve_quebra") else "CONFORME"],
    ]
    elementos += [
        base.tabela(gaveta, [0.65, 0.35], util, negrito_linhas=(0, 4, 5, 6), linha_abaixo=(0, -1)),
        base.espaco(2),
    ]

    atendimentos = dados["qtd_vendas"]
    ticket = (total / atendimentos) if atendimentos > 0 else ZERO
    resumo = [
        ["RESUMO DE CAIXA", ""],
        ["Total bruto:", fmt_numero(total)],
        ["Atendimentos:", str(atendimentos)],
        ["Ticket médio:", fmt_numero(ticket)],
    ]
    elementos += [base.tabela(resumo, [0.65, 0.35], util, negrito_linhas=(0,), linha_abaixo=(0, -1)), base.espaco(6)]

    elementos += base.assinatura(est, f"Responsável: {dados['operador']}")
    elementos.append(base.espaco(5))
    elementos += base.assinatura(est, "Fiscal de Caixa / Tesouraria")
    elementos += [base.espaco(2), Paragraph("Via de Auditoria Interna", est["sub"])]
    doc.build(elementos)
