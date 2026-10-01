"""E2E humanizado do Destaque: selecionar tarefa, Parada disponível, desselecionar recolhe.

Cobre os pontos 4 e 5 da auditoria no navegador (o unitário está em operator.test.tsx).
    GESTOR_VISUAL_AUTOLOGIN=destaque uvicorn tests.web_preview_api:app --port 8010 &
    python tests/e2e_destaque_flow.py
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

import e2e_operator_flow as flow  # mesmo helper `check`; roda com `python tests/e2e_destaque_flow.py`

flow.OUT = Path(__file__).resolve().parents[1] / "docs" / "auditoria_2026-10-01" / "e2e" / "destaque"


def main() -> int:
    flow.OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                  record_video_dir=str(flow.OUT / "video"),
                                  record_video_size={"width": 1280, "height": 800})
        ctx.tracing.start(screenshots=True, snapshots=True)
        page = ctx.new_page()
        page.set_default_timeout(6000)
        body = page.locator("body")
        parada = page.get_by_role("button", name="Parada", exact=True)
        page.goto(flow.BASE + "/operador", wait_until="networkidle")
        selecionada = re.compile("tarefa selecionada", re.I)  # o CSS põe em caixa alta; o DOM não
        card = page.get_by_role("button").filter(has_text="T-CORTE-310").first

        flow.check("1 fila do Destaque lista a tarefa liberada pelo Corte",
                   lambda: expect(card).to_be_visible(), page)
        card.click()
        flow.check("2 selecionar mostra a tarefa e a escolha de plano",
                   lambda: expect(body).to_contain_text(selecionada), page)
        flow.check("3 Parada segue disponível com a tarefa selecionada",
                   lambda: expect(parada).to_be_enabled(), page)
        card.click()
        flow.check("4 clicar de novo desseleciona e recolhe o detalhe",
                   lambda: expect(body).not_to_contain_text(selecionada), page)
        flow.check("5 após desselecionar a Parada continua disponível",
                   lambda: expect(parada).to_be_enabled(), page)
        ctx.tracing.stop(path=str(flow.OUT / "trace.zip"))
        ctx.close()
        browser.close()
    for name, status in flow.steps:
        print(status, name)
    for f in flow.failures:
        print("DETALHE", f)
    return 1 if flow.failures else 0


if __name__ == "__main__":
    sys.exit(main())
