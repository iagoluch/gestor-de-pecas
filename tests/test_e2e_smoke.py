"""Smoke test E2E via Playwright, adotado (não é mais POC) — ver
docs/CLAUDE_CODE_SETUP.md. Roda sob demanda via
`.github/workflows/e2e.yml` (workflow_dispatch), não no CI principal.

Setup local:
    pip install -r requirements.txt -r requirements-e2e.txt
    python -m playwright install chromium

Rodar com o preview em http://127.0.0.1:8010 já no ar
(`uvicorn tests.web_preview_api:app --port 8010`):
    python -m pytest tests/poc_playwright_smoke.py -v
"""


def test_pagina_inicial_carrega(page):
    page.goto("http://127.0.0.1:8010/")
    assert "Gestor de Peças" in page.title()
