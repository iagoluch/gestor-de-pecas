"""Cartão "A esclarecer" da planilha de perdas (decisão de 19/10/2026)."""
from __future__ import annotations

import unittest
from datetime import datetime

from openpyxl import Workbook

from backend.api.report_workbook.executive import build_perdas


def _textos(conflicting_state_seconds) -> list[str]:
    workbook = Workbook()
    payload = {"losses": {"conflicting_state_seconds": conflicting_state_seconds}}
    build_perdas(workbook, payload, {}, datetime(2026, 10, 19, 8, 0))
    return [
        cell.value
        for sheet in workbook.worksheets
        for row in sheet.iter_rows()
        for cell in row
        if isinstance(cell.value, str)
    ]


def _tem_cartao(conflicting_state_seconds) -> bool:
    # O painel grava os rótulos dos cartões em maiúsculas.
    return "A ESCLARECER" in {t.upper() for t in _textos(conflicting_state_seconds)}


class AEsclarecerCardTests(unittest.TestCase):
    def test_aparece_quando_ha_estado_em_conflito(self):
        self.assertTrue(_tem_cartao(7200))

    def test_some_quando_zero_ou_ausente(self):
        self.assertFalse(_tem_cartao(0))
        self.assertFalse(_tem_cartao(None))


if __name__ == "__main__":
    unittest.main()
