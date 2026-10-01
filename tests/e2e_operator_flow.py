"""Fluxo E2E humanizado do operador (Dobra 1303) contra o preview isolado.

Não é coletado pelo pytest. Estado do preview é em memória: reinicie o servidor
antes de cada execução.
    GESTOR_VISUAL_AUTOLOGIN=operador uvicorn tests.web_preview_api:app --port 8010 &
    python tests/e2e_operator_flow.py
Gera vídeo, trace.zip e um PNG por passo em docs/auditoria_2026-10-01/e2e/operador/.
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = "http://127.0.0.1:8010"
OUT = Path(__file__).resolve().parents[1] / "docs" / "auditoria_2026-10-01" / "e2e" / "operador"
steps, failures = [], []


def check(name, fn, page):
    """Executa um passo; registra PASS/FAIL com captura, sem interromper o fluxo."""
    try:
        fn()
        steps.append((name, "PASS"))
    except Exception as exc:  # noqa: BLE001 - relatório de QA, cada falha vira linha
        steps.append((name, "FAIL"))
        failures.append(f"{name}: {str(exc).splitlines()[0]}")
    page.screenshot(path=str(OUT / (f"{len(steps):02d}_" + re.sub(r"\W+", "_", name)[:40] + ".png")))
    page.wait_for_timeout(400)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1280, "height": 800},
                                  record_video_dir=str(OUT / "video"),
                                  record_video_size={"width": 1280, "height": 800})
        ctx.tracing.start(screenshots=True, snapshots=True)
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.set_default_timeout(6000)
        body = page.locator("body")

        page.goto(BASE + "/operador", wait_until="networkidle")
        check("1 portal lista os recursos da Dobra",
              lambda: expect(page.get_by_text("Selecione o recurso")).to_be_visible(), page)

        page.get_by_text("1303", exact=True).click()
        check("2 recurso abre com a máquina e sem apontamento",
              lambda: expect(page.get_by_text("SEM APONTAMENTO")).to_be_visible(), page)

        page.get_by_placeholder(re.compile("OP", re.I)).first.fill("OP-VISUAL-101")
        page.get_by_role("button", name="Carregar roteiro").click()
        check("3 roteiro da OP carrega com as etapas",
              lambda: expect(page.get_by_text("10 - DOBRAR SUPORTE").first).to_be_visible(), page)

        page.get_by_role("button", name="Iniciar", exact=True).click()
        check("4 iniciar libera a conferência da primeira peça (Setup)",
              lambda: expect(body).to_contain_text("Aponte o Setup"), page)
        check("5 múltiplas ordens: duas OPs em produção na mesma máquina",
              lambda: expect(body).to_contain_text(re.compile(r"Produção\s*2")), page)

        page.get_by_role("button", name="Parada", exact=True).click()
        check("6 parada abre motivos oficiais com código",
              lambda: expect(page.get_by_role("dialog")).to_contain_text("Pausa para café"), page)
        page.get_by_role("dialog").get_by_text("0009 - Pausa para café").click()
        page.get_by_role("button", name="Confirmar parada").click()
        page.wait_for_timeout(1200)
        check("7 parada confirmada fecha o diálogo",
              lambda: expect(page.get_by_role("dialog")).to_have_count(0), page)
        check("8 retorno: botão vira Retomar produção",
              lambda: expect(page.get_by_role("button", name="Retomar produção")).to_be_enabled(), page)
        page.get_by_role("button", name="Retomar produção").click()
        page.wait_for_timeout(1000)
        check("9 retomada ativa a Parada de novo e a tela segue sem texto cru",
              lambda: (expect(page.get_by_role("button", name="Parada", exact=True)).to_be_enabled(),
                       expect(body).not_to_contain_text(re.compile(r"undefined|\[object|NaN"))), page)

        ctx.tracing.stop(path=str(OUT / "trace.zip"))
        ctx.close()
        browser.close()
    if errors:
        failures.append(f"console/pageerror: {errors[:3]}")
    for name, status in steps:
        print(status, name)
    for f in failures:
        print("DETALHE", f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
