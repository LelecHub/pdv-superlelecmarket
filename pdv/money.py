"""Dinheiro e quantidades com Decimal (float acumula erro; num PDV isso vira diferença de caixa)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal("0")
CENTAVO = Decimal("0.01")


def D(valor) -> Decimal:
    """Converte qualquer coisa (str, int, float, Decimal, None) em Decimal sem herdar ruído de float."""
    if valor is None:
        return ZERO
    if isinstance(valor, Decimal):
        return valor
    return Decimal(str(valor))


def arred(valor) -> Decimal:
    """Arredonda para centavos (meio para cima)."""
    return D(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def fmt_numero(valor) -> str:
    """1234.5 -> '1.234,50'"""
    return f"{arred(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_brl(valor) -> str:
    return f"R$ {fmt_numero(valor)}"


def fmt_qtd(valor) -> str:
    """3 -> '3'; 1.500 -> '1,5'"""
    q = D(valor)
    if q == q.to_integral_value():
        return str(int(q))
    return f"{q.normalize():f}".replace(".", ",")


def parse_moeda(texto: str | None) -> Decimal:
    """Campo com máscara de centavos: '1.234,56' -> Decimal('1234.56')."""
    digitos = "".join(c for c in (texto or "") if c.isdigit())
    return Decimal(int(digitos)) / 100 if digitos else ZERO


def mascara_moeda(texto: str | None) -> str:
    return fmt_numero(parse_moeda(texto))
