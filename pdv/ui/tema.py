import flet as ft

TEMAS_COMERCIAIS = {
    "Supermercado (Esmeralda)": ft.Colors.GREEN_400,
    "Atacarejo (Laranja Swift)": ft.Colors.ORANGE_400,
    "Corporativo (Azul Pro)": ft.Colors.BLUE_400,
    "Moderno (Roxo Elegance)": ft.Colors.PURPLE_400,
}
TEMA_PADRAO = "Supermercado (Esmeralda)"


def cor_do_tema(nome: str):
    return TEMAS_COMERCIAIS.get(nome, TEMAS_COMERCIAIS[TEMA_PADRAO])
