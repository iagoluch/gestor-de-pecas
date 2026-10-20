"""Explicação ``cut.*``: tempos dos nestings do Corte (fonte: ``get_nesting_times``)."""

from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace

from backend.api.errors import AppError
from backend.api.routers.explanation import explain_for_user
from backend.api.schemas.auth import SessionUser
from mes.contracts import AnalyticsFilter
from mes.services.cut_explanation import CutExplanationService
from mes.services.metric_explanation import UnknownMetricError

AGORA = datetime(2026, 10, 20, 14, 0)
FILTERS = AnalyticsFilter(datetime(2026, 10, 1), datetime(2026, 10, 20))


def _row(n, *, maquina="LASER1", tarefa="T1", programa="P1", previsto=3600, real=4200, periodo=None, inicio=None):
    return {
        "nesting": n,
        "maquina": maquina,
        "tarefa": tarefa,
        "programa": programa,
        "plano_hash": f"h-{programa}",
        "previsto_segundos": previsto,
        "real_segundos": real,
        "real_periodo_segundos": periodo if periodo is not None else real,
        "material": "Aço",
        "espessura": 3,
        "status": "Concluído",
        "operador_inicio": "Ana",
        "inicio": inicio or datetime(2026, 10, 2, 8, n),
        "fim": datetime(2026, 10, 2, 9, n),
    }


class _Management:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_nesting_times(self, filters):
        self.calls.append(filters)
        return self.rows


def _explain(rows, metric, filters=FILTERS, **kwargs):
    service = CutExplanationService(_Management(rows), now_func=lambda: AGORA)
    return service.explain(metric, filters, **kwargs).to_dict()


def _leaves(node):
    return [node] if not node["children"] else [leaf for child in node["children"] for leaf in _leaves(child)]


ROWS = [
    _row(1),
    _row(2, previsto=1800, real=1500),
    _row(3, maquina="LASER2", tarefa="T2", programa="P2", previsto=0, real=600),
]


class CutExplanationTests(unittest.TestCase):
    def test_nestings_count_matches_rows_and_reconciles(self):
        body = _explain(ROWS, "cut.nestings")
        self.assertEqual(body["value"], 3)
        self.assertEqual(body["unit"], "count")
        self.assertTrue(body["reconciliation"]["ok"])
        self.assertEqual([n["label"] for n in body["children"]], ["LASER1", "LASER2"])

    def test_previsto_and_realizado_are_hours_and_reconcile(self):
        previsto = _explain(ROWS, "cut.previsto")
        real = _explain(ROWS, "cut.realizado")
        self.assertAlmostEqual(previsto["value"], 5400 / 3600)
        self.assertAlmostEqual(real["value"], 6300 / 3600)
        for body in (previsto, real):
            self.assertEqual(body["unit"], "hours")
            self.assertTrue(body["reconciliation"]["ok"])

    def test_tree_is_machine_task_plan_nesting_with_detail(self):
        body = _explain(ROWS, "cut.realizado")
        laser1 = body["children"][0]
        self.assertEqual(laser1["kind"], "resource")
        task = laser1["children"][0]
        self.assertEqual(task["label"], "Tarefa T1")
        self.assertEqual(task["children"][0]["label"], "Plano P1")
        leaf = _leaves(laser1)[0]
        self.assertTrue(leaf["label"].startswith("Nesting "))
        self.assertEqual(leaf["detail"]["material"], "Aço")
        self.assertIn("realizado_total", leaf["detail"])

    def test_previsto_lists_nestings_without_previsto_as_excluded(self):
        body = _explain(ROWS, "cut.previsto")
        # texto: a tela formata números na unidade da métrica (horas), então a contagem vai como texto
        self.assertEqual(body["excluded"][0]["value"], "1")

    def test_realizado_notes_total_time_and_period_part_in_detail(self):
        rows = [_row(1, real=7200, periodo=3600)]
        body = _explain(rows, "cut.realizado")
        self.assertTrue(any("TOTAL" in note for note in body["notes"]))
        self.assertEqual(_leaves(body["children"][0])[0]["detail"]["realizado_no_periodo"], "1h 00m")

    def test_desvio_recomputes_from_inputs(self):
        body = _explain(ROWS, "cut.desvio")
        self.assertAlmostEqual(body["value"], (6300 - 5400) / 5400 * 100)
        self.assertEqual([c["kind"] for c in body["children"]], ["input", "input"])
        self.assertTrue(body["reconciliation"]["ok"])

    def test_desvio_without_previsto_has_no_value(self):
        body = _explain([_row(1, previsto=0)], "cut.desvio")
        self.assertIsNone(body["value"])
        self.assertEqual(body["children"], [])

    def test_empty_list_gives_zero_and_ok(self):
        for metric in ("cut.nestings", "cut.previsto", "cut.realizado"):
            body = _explain([], metric)
            self.assertEqual(body["value"], 0)
            self.assertTrue(body["reconciliation"]["ok"])

    def test_truncation_keeps_total_and_flags_it(self):
        rows = [_row(n % 50, programa="P1", real=3600) for n in range(1, 11)]
        body = _explain(rows, "cut.realizado", max_leaves=3)
        self.assertTrue(body["truncated"])
        self.assertAlmostEqual(body["value"], 10.0)
        self.assertTrue(body["reconciliation"]["ok"])

    def test_unsupported_filter_adds_note(self):
        body = _explain(ROWS, "cut.nestings", filters=AnalyticsFilter(FILTERS.inicio, FILTERS.fim, op="123"))
        self.assertTrue(any("não se aplica a nestings" in note for note in body["notes"]))
        self.assertTrue(any("tempo padrão" in note for note in body["notes"]))

    def test_unknown_metric_raises(self):
        with self.assertRaises(UnknownMetricError):
            _explain(ROWS, "cut.xyz")


class CutDispatchTests(unittest.TestCase):
    def _facade(self):
        return SimpleNamespace(management=_Management(ROWS), db=None)

    def test_explain_for_user_routes_cut_prefix(self):
        user = SessionUser(id=1, name="G", role="gestor", management_access=True, andon_access=True, operator_access=False)
        body = explain_for_user(self._facade(), "cut.nestings", FILTERS, user)
        self.assertEqual(body["value"], 3)

    def test_unknown_cut_id_is_422(self):
        user = SessionUser(id=1, name="G", role="gestor", management_access=True, andon_access=True, operator_access=False)
        with self.assertRaises(AppError) as ctx:
            explain_for_user(self._facade(), "cut.xyz", FILTERS, user)
        self.assertEqual(ctx.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
