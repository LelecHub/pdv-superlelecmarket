"""Ponto de entrada do PDV.   Uso:  python main.py"""
import sys


def iniciar(web: bool = False, apos_migrar=None) -> None:
    from pdv import config
    from pdv.logger import configurar_logs

    configurar_logs()
    try:
        config.validar()
    except RuntimeError as erro:
        print(f"[CONFIGURAÇÃO] {erro}")
        sys.exit(1)

    # Nada disso roda mais ao importar um módulo: a ordem de inicialização é explícita
    from pdv.db import local, migrations, pool

    local.inicializar()
    pool.iniciar_pool()
    migrations.migrar_banco()
    if apos_migrar:
        apos_migrar()

    from pdv.services.sincronizacao import servico

    servico.start()

    import flet as ft

    from pdv.ui.app import main

    view = ft.AppView.WEB_BROWSER if web else ft.AppView.FLET_APP
    # Flet 1.0 trocou ft.app(target=...) por ft.run(...)
    if hasattr(ft, "run"):
        ft.run(main, view=view)
    else:  # Flet 0.x
        ft.app(target=main, view=view)


if __name__ == "__main__":
    iniciar(web="--web" in sys.argv)
