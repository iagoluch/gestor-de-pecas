"""Gera o pack de imagens da proposta de gestão a partir do protótipo estático.

Uso: python gerar_pack.py   (precisa de playwright + chromium instalados)
Saída: ../imagens/<conta>/NN_<tela>.png  — dados ilustrativos, nada vem do banco.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

AQUI = Path(__file__).resolve().parent
SAIDA = AQUI.parent / "imagens"

COMUM = [
    "home-overview", "home-ai", "home-calls", "panels-andon", "panels-map", "panels-pauses",
    "ops-overview", "ops-resources", "ops-orders", "prod-orders", "prod-exec", "prod-done",
    "prod-plan", "an-hours", "audit", "reports", "trace-op", "trace-nest",
]
# Cada conta: telas exclusivas dela. As telas comuns saem uma vez (pasta 01_comum, vistas pelo gestor);
# cada conta ganha a tela inicial com o próprio menu, para mostrar o que ela enxerga.
CONTAS = {
    "gestor": [],
    "gerente": [],
    "lider": ["area-serra"],
    "manufatura": [],
    "qualidade": ["q-cotas", "q-spc", "q-rnc"],
    "diretoria": ["director"],
    "melhoria": ["improve"],
    "manutencao": ["maint"],
    "admin": ["dev-badges", "dev-users", "dev-calls", "dev-shifts", "dev-sector", "dev-changes", "dev-protheus", "dev-system"],
}


def main() -> None:
    url = (AQUI / "index.html").as_uri()
    with sync_playwright() as p:
        nav = p.chromium.launch()
        pg = nav.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=1)

        def foto(conta: str, tela: str, destino: Path) -> None:
            destino.parent.mkdir(parents=True, exist_ok=True)
            pg.goto(f"{url}?conta={conta}&tela={tela}")
            pg.wait_for_load_state("networkidle")
            # Viewport do tamanho da página: menu lateral e marca d'água acompanham telas longas.
            pg.set_viewport_size({"width": 1600, "height": 1000})
            alt = max(1000, pg.evaluate("document.documentElement.scrollHeight"))
            pg.set_viewport_size({"width": 1600, "height": alt})
            pg.screenshot(path=str(destino))

        foto("gestor", "capa", SAIDA / "00_LEIA_PRIMEIRO_principios.png")
        for i, tela in enumerate(COMUM, 1):
            foto("gestor", tela, SAIDA / "01_comum_todas_as_contas" / f"{i:02d}_{tela}.png")
        for n, (conta, telas) in enumerate(CONTAS.items(), 2):
            pasta = SAIDA / f"{n:02d}_conta_{conta}"
            inicio = telas[0] if conta == "manutencao" else "home-overview"
            foto(conta, inicio, pasta / f"00_menu_e_tela_inicial.png")
            for i, tela in enumerate(telas, 1):
                if conta == "manutencao":
                    break
                foto(conta, tela, pasta / f"{i:02d}_{tela}.png")
        nav.close()
    print("pack gerado em", SAIDA)


if __name__ == "__main__":
    main()
