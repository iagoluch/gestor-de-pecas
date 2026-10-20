"""Rota /traceability/nestings (totals) e acesso a /management/explicacao?metric=cut.*."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.main import create_app
from backend.api.schemas.auth import SessionUser
from tests.test_standard_time import _settings

ITEMS = [
    {"tarefa": "T1", "programa": "P1", "nesting": 1, "maquina": "LASER1", "previsto_segundos": 3600, "real_segundos": 4200, "real_periodo_segundos": 4200},
    {"tarefa": "T2", "programa": "P2", "nesting": 2, "maquina": "LASER1", "previsto_segundos": None, "real_segundos": 600, "real_periodo_segundos": None},
    {"tarefa": "T3", "programa": "P3", "nesting": 3, "maquina": "LASER2", "previsto_segundos": 1800, "real_segundos": 1500, "real_periodo_segundos": 300},
]


class _Facade:
    def nestings(self, filters):
        return {"items": [dict(i) for i in ITEMS]}


def _user(role, management):
    return SessionUser(id=5, name="Conta", role=role, management_access=management,
                       andon_access=True, operator_access=not management)


class NestingTotalsTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(settings=_settings(), database_factory=lambda: None)
        self.app.dependency_overrides[get_frontend_facade] = lambda: _Facade()
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.app.dependency_overrides[get_current_user] = lambda: _user("gestor", True)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_totals_sum_all_items_even_when_paged_and_tolerate_none(self):
        body = self.client.get("/api/v1/traceability/nestings", params={"page": 1, "page_size": 1}).json()
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["count"], 3)
        self.assertEqual(body["totals"], {"previsto_segundos": 5400.0, "real_segundos": 6300.0, "real_periodo_segundos": 4500.0})

    def test_totals_follow_search(self):
        body = self.client.get("/api/v1/traceability/nestings", params={"search": "laser2"}).json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["totals"]["previsto_segundos"], 1800.0)

    def test_totals_denied_for_non_management(self):
        self.app.dependency_overrides[get_current_user] = lambda: _user("operador_dobra", False)
        response = self.client.get("/api/v1/traceability/nestings")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("totals", response.json())

    def test_cut_explanation_denied_for_non_management(self):
        self.app.dependency_overrides[get_current_user] = lambda: _user("operador_dobra", False)
        response = self.client.get("/api/v1/management/explicacao", params={"metric": "cut.nestings"})
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("children", response.json())


if __name__ == "__main__":
    unittest.main()
