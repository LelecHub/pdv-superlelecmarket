"""Cupom não fiscal."""
from __future__ import annotations

from datetime import datetime

from reportlab.platypus import Paragraph

from pdv.money import fmt_brl, fmt_numero, fmt_qtd
from pdv.relatorios import base


def gerar_cupom_pdf(
    venda_ref: str, itens: list[dict], total, forma_pagamento: str, valor_recebido, troco, caminho_saida: str
) -> None:
    est = base.estilos()
    linhas_promo = sum(1 for i in itens if i.get("promo"))
    altura = 110 + len(itens) * 7 + linhas_promo * 4
    doc = base.documento(caminho_saida, altura, margem_h_mm=3, margem_v_mm=5)
    util = base.largura_util(3)

    elementos = base.cabecalho(est, [f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"])
    elementos += [
        Paragraph(f"<b>CUPOM NÃO FISCAL - VENDA #{base.texto(venda_ref)}</b>", est["titulo"]),
        base.espaco(4),
    ]

    dados = [["Item", "Qtd", "Un.", "Subtotal"]]
    extra = []
    for item in itens:
        dados.append([item["nome"][:18], fmt_qtd(item["quantidade"]), fmt_numero(item["preco_unit"]), fmt_numero(item["subtotal"])])
        if item.get("promo"):
            linha = len(dados)
            dados.append([f"  promo: {item['promo'][:28]}", "", "", ""])
            extra += [("SPAN", (0, linha), (-1, linha)), ("FONTSIZE", (0, linha), (-1, linha), 6), ("ALIGN", (0, linha), (0, linha), "LEFT")]
    elementos.append(
        base.tabela(dados, [0.44, 0.14, 0.20, 0.22], util, fonte=7, negrito_linhas=(0,), linha_abaixo=(0,), padding=2, extra=extra)
    )
    elementos.append(base.espaco(3))

    totais = [["TOTAL:", fmt_brl(total)], [f"Forma ({forma_pagamento}):", fmt_brl(valor_recebido)]]
    if forma_pagamento.upper() == "DINHEIRO":
        totais.append(["Troco:", fmt_brl(troco)])
    elementos.append(
        base.tabela(totais, [0.60, 0.40], util, fonte=8, negrito_linhas=tuple(range(len(totais))), linha_acima=(0,), padding=2)
    )
    elementos += [base.espaco(4), Paragraph("Agradecemos a preferência!", est["sub"])]
    doc.build(elementos)
