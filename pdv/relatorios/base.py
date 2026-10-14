"""Peças comuns dos PDFs de bobina 80 mm (antes cada gerador repetia tudo isso)."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import webbrowser
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from pdv import config

log = logging.getLogger(__name__)

LARGURA = 80 * mm
PRETO = HexColor("#000000")


def caminho_pdf(nome: str) -> str:
    config.PASTA_PDFS.mkdir(parents=True, exist_ok=True)
    return str(config.PASTA_PDFS / nome)


def estilos() -> dict[str, ParagraphStyle]:
    return {
        "titulo": ParagraphStyle("Titulo", fontName="Helvetica-Bold", fontSize=9.5, leading=11, alignment=1),
        "sub": ParagraphStyle("Sub", fontName="Helvetica", fontSize=6.5, leading=8.5, alignment=1, textColor=HexColor("#333333")),
        "assinatura": ParagraphStyle("Assinatura", fontName="Helvetica", fontSize=6.5, leading=8, alignment=1),
    }


def documento(caminho: str, altura_mm: float, margem_h_mm: float = 3, margem_v_mm: float = 4) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        caminho,
        pagesize=(LARGURA, altura_mm * mm),
        leftMargin=margem_h_mm * mm,
        rightMargin=margem_h_mm * mm,
        topMargin=margem_v_mm * mm,
        bottomMargin=margem_v_mm * mm,
    )


def largura_util(margem_h_mm: float = 3) -> float:
    return LARGURA - 2 * margem_h_mm * mm


def texto(valor) -> str:
    """Escapa texto vindo do banco/usuário antes de colocar num Paragraph (evita quebrar com '&' ou '<')."""
    return escape(str(valor))


def cabecalho(est: dict, linhas: list[str]) -> list:
    itens = [Paragraph(texto(config.NOME_LOJA), est["titulo"]), Paragraph(f"CNPJ: {texto(config.CNPJ_LOJA)}", est["sub"])]
    itens += [Paragraph(l, est["sub"]) for l in linhas]
    return itens


def assinatura(est: dict, rotulo: str) -> list:
    return [Paragraph("_" * 42, est["assinatura"]), Paragraph(texto(rotulo), est["assinatura"])]


def tabela(
    dados: list[list[str]],
    fracoes: list[float],
    util: float,
    *,
    fonte: float = 6.5,
    negrito_linhas: tuple[int, ...] = (),
    direita_de: int | None = 1,
    linha_abaixo: tuple[int, ...] = (),
    linha_acima: tuple[int, ...] = (),
    padding: float = 0.8,
    extra: list | None = None,
) -> Table:
    """Tabela monoespaçada de bobina. Índices negativos valem (-1 = última linha)."""
    t = Table(dados, colWidths=[util * f for f in fracoes])
    cmds = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), fonte),
        ("BOTTOMPADDING", (0, 0), (-1, -1), padding),
        ("TOPPADDING", (0, 0), (-1, -1), padding),
    ]
    if direita_de is not None:
        cmds.append(("ALIGN", (direita_de, 0), (-1, -1), "RIGHT"))
    cmds += [("FONTNAME", (0, i), (-1, i), "Helvetica-Bold") for i in negrito_linhas]
    cmds += [("LINEBELOW", (0, i), (-1, i), 0.5, PRETO) for i in linha_abaixo]
    cmds += [("LINEABOVE", (0, i), (-1, i), 0.5, PRETO) for i in linha_acima]
    if extra:
        cmds += extra
    t.setStyle(TableStyle(cmds))
    return t


def espaco(mm_: float = 2) -> Spacer:
    return Spacer(1, mm_ * mm)


# --- Abertura do PDF no sistema ---------------------------------------------------------

def _abrir(caminho: str) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(caminho)  # type: ignore[attr-defined]
        elif sys.platform.startswith("darwin"):
            subprocess.run(["open", caminho], check=True)
        else:
            subprocess.run(["xdg-open", caminho], check=True)
    except Exception:
        try:
            webbrowser.open_new_tab(f"file://{caminho}")
        except Exception:
            log.exception("Não foi possível abrir o PDF %s", caminho)


def abrir_pdf_async(caminho: str) -> None:
    threading.Thread(target=_abrir, args=(os.path.abspath(caminho),), daemon=True).start()
