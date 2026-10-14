"""Comprovante de sangria."""
from __future__ import annotations

from datetime import datetime

from reportlab.platypus import Paragraph

from pdv.money import fmt_brl
from pdv.relatorios import base


def gerar_comprovante_sangria_pdf(
    sangria_id: int, caixa_id: int, operador: str, gerente: str, valor, motivo: str, caminho_saida: str
) -> None:
    est = base.estilos()
    doc = base.documento(caminho_saida, 145, margem_h_mm=4, margem_v_mm=5)
    util = base.largura_util(4)

    elementos = base.cabecalho(
        est,
        [f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", f"Turno Caixa: #{caixa_id} | Registro: #{sangria_id:05d}"],
    )
    elementos.insert(2, Paragraph("COMPROVANTE DE SANGRIA", est["titulo"]))
    elementos.append(base.espaco(3))

    dados = [
        ["Operador:", operador[:30]],
        ["Autorizado por:", gerente[:30]],
        ["Valor Retirado:", fmt_brl(valor)],
        ["Motivo:", motivo[:28]],
    ]
    elementos.append(
        base.tabela(dados, [0.42, 0.58], util, fonte=8, padding=2, linha_abaixo=(-1,), extra=[("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold")])
    )
    elementos.append(base.espaco(10))
    elementos += base.assinatura(est, f"Operador: {operador}")
    elementos.append(base.espaco(8))
    elementos += base.assinatura(est, f"Gerência: {gerente}")
    elementos += [base.espaco(4), Paragraph("Via de controle interno de tesouraria", est["sub"])]
    doc.build(elementos)
