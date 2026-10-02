"""E2E humanizado do portão Setup/Qualidade da Dobra (1303): Finalizar só depois do Setup.

Não é coletado pelo pytest. O estado do preview é em memória: reinicie o servidor antes.
    GESTOR_VISUAL_AUTOLOGIN=operador uvicorn tests.web_preview_api:app --port 8010 &
    python tests/e2e_quality_gate_flow.py
Gera vídeo, trace.zip e um PNG por passo em docs/auditoria_2026-10-01/e2e/qualidade/.
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

import e2e_operator_flow as flow  # mesmo helper `check`

flow.OUT = Path(__file__).resolve().parents[1] / "docs" / "auditoria_2026-10-01" / "e2e" / "qualidade"


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
        dialog = page.get_by_role("dialog")
        finalizar = page.get_by_role("button", name="Finalizar", exact=True)
        page.goto(flow.BASE + "/operador", wait_until="networkidle")
        page.get_by_text("1303", exact=True).click()
        page.get_by_placeholder(re.compile("OP", re.I)).first.fill("OP-VISUAL-101")
        page.get_by_role("button", name="Carregar roteiro").click()
        page.get_by_role("button", name="Iniciar", exact=True).click()

        flow.check("1 após iniciar, a tela explica que o lote só é liberado com o Setup",
                   lambda: expect(body).to_contain_text("Aponte o Setup"), page)
        flow.check("2 Finalizar fica bloqueado até a primeira peça ser aprovada",
                   lambda: expect(finalizar).to_be_disabled(), page)
        page.get_by_role("button", name="Setup", exact=True).click()
        flow.check("3 Setup abre confirmação com OP, operação e recurso",
                   lambda: expect(dialog).to_contain_text(re.compile(r"OP-VISUAL-101.*1303", re.S)), page)
        dialog.get_by_role("button", name="Cancelar").click()
        flow.check("4 cancelar fecha o diálogo e Finalizar continua bloqueado",
                   lambda: (expect(dialog).to_have_count(0), expect(finalizar).to_be_disabled()), page)
        page.get_by_role("button", name="Setup", exact=True).click()
        dialog.get_by_role("button", name="Confirmar", exact=True).click()
        page.wait_for_timeout(1500)
        salvar = dialog.get_by_role("button", name="Salvar cotas do produto")
        flow.check("5 produto sem cotas: o Setup abre o cadastro das cotas, com Salvar bloqueado",
                   lambda: (expect(dialog).to_contain_text("Cadastro das cotas do produto"),
                            expect(salvar).to_be_disabled()), page)
        dialog.get_by_placeholder(re.compile("125")).fill("12,0")
        dialog.get_by_placeholder(re.compile("0,5")).fill("0,2")
        flow.check("6 preenchendo padrão e tolerância, Salvar libera; tela sem texto cru",
                   lambda: (expect(salvar).to_be_enabled(),
                            expect(body).not_to_contain_text(re.compile(r"undefined|\[object|NaN"))), page)
        dialog.get_by_role("button", name="Cancelar").click()
        flow.check("7 cancelar o cadastro fecha o diálogo e Finalizar segue bloqueado",
                   lambda: (expect(dialog).to_have_count(0), expect(finalizar).to_be_disabled()), page)
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
