"""``GET /api/v1/management/explicacao``: acesso, erros e igualdade com a Visão Geral.

Sem banco: o repositório em memória de ``tests/test_oee_consistency`` alimenta o
serviço real, e o total da árvore é comparado com ``/management/overview``.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.core.permissions import USER_LEVELS, can_access_management_web
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import create_app
from backend.api.routers.explanation import redact_operator_names
from backend.api.schemas.auth import SessionUser
from tests.test_oee_consistency import _ThreeDayOeeRepo
from tests.test_standard_time import _settings

URL = "/api/v1/management/explicacao"
OVERVIEW = "/api/v1/management/overview"
PERIOD = {"inicio": "2026-08-18T00:00:00", "fim": "2026-08-21T00:00:00"}


class _Repo(_ThreeDayOeeRepo):
    """Três dias de produção na DOBRA1 mais uma hora de recurso sem demanda."""

    def listar_estados_recurso_periodo(self, inicio, fim, **kwargs):
        rows = super().listar_estados_recurso_periodo(inicio, fim, **kwargs)
        start = datetime(2026, 8, 19, 9, 0)
        finish = start + timedelta(hours=1)
        if self._overlaps(start, finish, inicio, fim):
            rows.append({
                "id": 90,
                "recurso": "DOBRA1",
                "tipo_setor": "Dobra",
                "categoria": "fila",
                "op": None,
                "operador": "Maria",
                "data_inicio": start,
                "data_fim": finish,
            })
        return rows


def _user(role, *, management):
    return SessionUser(
        id=5, name=f"Conta {role}", role=role, management_access=management,
        andon_access=True, operator_access=not management,
    )


class _ApiCase(unittest.TestCase):
    def setUp(self):
        db = _Repo()
        self.app = create_app(settings=_settings(), database_factory=lambda: db)
        self.app.dependency_overrides[get_database] = lambda: db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def _as(self, role, *, management=True):
        self.app.dependency_overrides[get_current_user] = lambda: _user(
            role, management=management
        )

    def _get(self, metric="tempo.producao", **extra):
        return self.client.get(URL, params={"metric": metric, **PERIOD, **extra})


class ExplanationEndpointTests(_ApiCase):
    def test_requires_management_level(self):
        self._as("operador_dobra", management=False)
        response = self._get()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "management_access_denied")
        self.assertNotIn("children", response.json())
        self.assertNotIn("total_seconds", response.json())

    def test_without_session_401(self):
        self.assertEqual(self._get().status_code, 401)

    def test_returns_tree_for_management_user(self):
        self._as("gestor")
        response = self._get()
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["metric"], "tempo.producao")
        self.assertTrue(body["children"])
        self.assertEqual(body["children"][0]["kind"], "sector")
        self.assertIn("notes", body)
        self.assertIn("truncated", body["children"][0])
        self.assertTrue(body["reconciliation"]["ok"])

    def test_unknown_metric_422(self):
        self._as("gestor")
        response = self._get("tempo.inexistente")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "unknown_metric")

    def test_missing_or_empty_metric_422(self):
        self._as("gestor")
        self.assertEqual(self.client.get(URL, params=PERIOD).status_code, 422)
        self.assertEqual(self._get("").status_code, 422)
        self.assertEqual(self._get("   ").status_code, 422)

    def test_invalid_period_rejected_like_overview(self):
        self._as("gestor")
        reversed_period = {"inicio": "2026-08-21T00:00:00", "fim": "2026-08-18T00:00:00"}
        response = self._get(**reversed_period)
        overview = self.client.get(OVERVIEW, params=reversed_period)
        self.assertEqual(response.status_code, overview.status_code)
        self.assertEqual(response.json()["code"], overview.json()["code"])

    def test_same_filters_same_total_as_inicio(self):
        self._as("gestor")
        hours = self.client.get(OVERVIEW, params=PERIOD).json()["hours"]
        for metric, key in (
            ("tempo.producao", "production_seconds"),
            ("tempo.sem_demanda", "no_demand_seconds"),
        ):
            body = self._get(metric).json()
            self.assertGreater(hours[key], 0, key)
            self.assertEqual(body["total_seconds"], hours[key], metric)

    def test_filters_are_applied_like_overview(self):
        self._as("gestor")
        one_day = {"inicio": "2026-08-19T00:00:00", "fim": "2026-08-20T00:00:00"}
        hours = self.client.get(OVERVIEW, params=one_day).json()["hours"]
        body = self.client.get(URL, params={"metric": "tempo.producao", **one_day}).json()
        self.assertEqual(body["total_seconds"], hours["production_seconds"])
        self.assertEqual(body["day_count"], 1)

    def test_management_levels_see_operator_name(self):
        self._as("gestor")
        body = self._get("tempo.sem_demanda").json()
        stretch = body["children"][0]["children"][0]["children"][0]
        self.assertEqual(stretch["detail"]["who"], "Maria")


class RedactOperatorNamesTests(unittest.TestCase):
    @staticmethod
    def _tree():
        stretch = {"kind": "stretch", "label": "08:00", "seconds": 1.0, "children": [],
                   "detail": {"who": "Maria", "origin": "estado_recurso"}}
        merged = {"kind": "stretch", "label": "09:00", "seconds": 1.0, "children": [],
                  "detail": None}
        resource = {"kind": "resource", "label": "DOBRA1", "seconds": 2.0,
                    "children": [stretch, merged], "detail": None}
        sector = {"kind": "sector", "label": "Dobra", "seconds": 2.0,
                  "children": [resource], "detail": None}
        return {"children": [sector]}

    @staticmethod
    def _first_detail(tree):
        return tree["children"][0]["children"][0]["children"][0]["detail"]

    def test_who_is_omitted_for_non_management_level(self):
        level = next(item for item in USER_LEVELS if not can_access_management_web(item))
        tree = redact_operator_names(self._tree(), level)
        self.assertIsNone(self._first_detail(tree)["who"])
        self.assertEqual(self._first_detail(tree)["origin"], "estado_recurso")

    def test_who_is_kept_for_management_level(self):
        tree = redact_operator_names(self._tree(), "gestor")
        self.assertEqual(self._first_detail(tree)["who"], "Maria")

    def test_unknown_level_is_treated_as_non_management(self):
        tree = redact_operator_names(self._tree(), "nivel_inventado")
        self.assertIsNone(self._first_detail(tree)["who"])


if __name__ == "__main__":
    unittest.main()
