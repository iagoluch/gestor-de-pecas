"""POC isolada (não faz parte da suíte principal ainda): valida que
pytest-playwright funciona neste ambiente contra o preview visual do
projeto. Ver docs/CLAUDE_CODE_SETUP.md para a decisão de adoção.

Rodar manualmente com o preview em http://127.0.0.1:8010 já no ar:
    python -m pytest tests/poc_playwright_smoke.py -v
"""

import pytest


@pytest.mark.skip(reason="POC manual - requer o preview visual rodando em 127.0.0.1:8010")
def test_pagina_inicial_carrega(page):
    page.goto("http://127.0.0.1:8010/")
    assert "Gestor de Peças" in page.title()
