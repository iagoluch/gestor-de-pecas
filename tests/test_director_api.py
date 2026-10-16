"""Rotas ``/api/v1/diretoria`` (16/10/2026): acesso, erros e vazamento de R$.

Sem banco: o serviço real roda sobre o repositório em memória de
``tests/test_director_summary.py``. O vazamento varre as rotas reais de gestão
sobre o ``ApiFakeDatabase`` de ``tests/test_web_api.py``.
"""

from __future__ import annotations

import unittest
from decimal import Decimal
from unittest import mock

from fastapi.testclient import TestClient

from app.core.permissions import USER_LEVELS
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import create_app
from backend.api.routers import director as director_router
from tests.test_director_summary import NOW, _Repo, _with_rates
from tests.test_standard_time import _settings, _user
from tests.test_web_api import ApiFakeDatabase

BASE = "/api/v1/diretoria"
READ_ROUTES = (
    f"{BASE}/painel?periodo=hoje",
    f"{BASE}/ficha?periodo=hoje",
    f"{BASE}/custos",
)
PUT_ROUTES = (
    f"{BASE}/custos/recurso/LASER1",
    f"{BASE}/custos/pessoa/1",
)
MONEY_KEYS = {"valor_hora", "custo", "custo_parada"}


def _money_keys(payload, path="$"):
    """Caminhos de toda chave de R$ no JSON, em qualquer profundidade."""
    found = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in MONEY_KEYS:
                found.append(f"{path}.{key}")
            found.extend(_money_keys(value, f"{path}.{key}"))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(_money_keys(value, f"{path}[{index}]"))
    return found


class _ApiCase(unittest.TestCase):
    def _build(self, db):
        self.db = db
        self.app = create_app(settings=_settings(), database_factory=lambda: db)
        self.app.dependency_overrides[get_database] = lambda: db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.client = TestClient(self.app)
        clock = mock.patch.object(director_router, "request_now_func", return_value=lambda: NOW)
        clock.start()
        self.addCleanup(clock.stop)
        self.addCleanup(self.client.close)

    def _as(self, role, uid=5):
        self.app.dependency_overrides[get_current_user] = lambda: _user(role, uid)


class DirectorAccessTests(_ApiCase):
    def setUp(self):
        self._build(_with_rates(_Repo()))

    def test_diretoria_e_admin_recebem_r_em_painel_ficha_e_custos(self):
        for role in ("diretoria", "admin"):
            self._as(role)
            panel = self.client.get(f"{BASE}/painel", params={"periodo": "hoje"})
            self.assertEqual(panel.status_code, 200, (role, panel.text))
            body = panel.json()
            self.assertEqual(body["periodo"]["nome"], "hoje")
            self.assertIsInstance(body["cards"]["custo_parada"], float)
            self.assertIn("onde_perdemos", body)
            self.assertIn("pior_setor", body)

            sheet = self.client.get(f"{BASE}/ficha", params={"periodo": "hoje", "recurso": "LASER1"})
            self.assertEqual(sheet.status_code, 200, (role, sheet.text))
            sheet_body = sheet.json()
            for key in ("texto", "custo_trabalho", "custo_parada", "pessoas", "custos_faltando_parada"):
                self.assertIn(key, sheet_body)
            self.assertTrue(sheet_body["texto"].startswith("O LASER1"), sheet_body["texto"])

            costs = self.client.get(f"{BASE}/custos")
            self.assertEqual(costs.status_code, 200, (role, costs.text))
            laser = next(r for r in costs.json()["recursos"] if r["recurso"] == "LASER1")
            self.assertEqual(laser["valor_hora"], 150.0)
            ana = next(p for p in costs.json()["pessoas"] if p["operador_id"] == 1)
            self.assertEqual(ana["valor_hora"], 100.0)

    def test_painel_bate_com_o_servico(self):
        self._as("diretoria")
        expected = director_router.DirectorSummaryService(self.db).panel("semana", NOW)
        body = self.client.get(f"{BASE}/painel", params={"periodo": "semana"}).json()
        self.assertEqual(body["cards"]["custo_parada"], expected["cards"]["custo_parada"])
        self.assertEqual(body["custos_faltando"], expected["custos_faltando"])
        self.assertEqual(len(body["onde_perdemos"]), len(expected["onde_perdemos"]))

    def test_diretoria_e_admin_gravam_valor_por_hora_com_autoria(self):
        for role, value in (("diretoria", 180.5), ("admin", 190)):
            self._as(role, uid=9)
            saved = self.client.put(f"{BASE}/custos/recurso/dobra1", json={"valor_hora": value})
            self.assertEqual(saved.status_code, 200, (role, saved.text))
            self.assertEqual(self.db.resource_rates["DOBRA1"], Decimal(str(value)).quantize(Decimal("0.01")))
            person = self.client.put(f"{BASE}/custos/pessoa/2", json={"valor_hora": value})
            self.assertEqual(person.status_code, 200, (role, person.text))
            self.assertEqual(self.db.operator_rates[2], Decimal(str(value)).quantize(Decimal("0.01")))

    def test_todo_outro_nivel_recebe_403_nas_cinco_rotas(self):
        others = [level for level in USER_LEVELS if level not in ("admin", "diretoria")]
        self.assertGreater(len(others), 10)
        before = (dict(self.db.resource_rates), dict(self.db.operator_rates))
        for level in others:
            self._as(level)
            for url in READ_ROUTES:
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403, (level, url, response.text))
                self.assertEqual(response.json()["code"], "director_access_denied")
                self.assertEqual(_money_keys(response.json()), [], (level, url))
            for url in PUT_ROUTES:
                response = self.client.put(url, json={"valor_hora": 99})
                self.assertEqual(response.status_code, 403, (level, url, response.text))
                self.assertEqual(response.json()["code"], "director_access_denied")
        self.assertEqual((self.db.resource_rates, self.db.operator_rates), before)

    def test_nivel_desconhecido_ou_vazio_tambem_e_negado(self):
        for level in ("", "DIRETORIA_X", "gestor "):
            self._as(level)
            self.assertEqual(self.client.get(f"{BASE}/custos").status_code, 403, repr(level))

    def test_sem_sessao_401(self):
        self.app.dependency_overrides.pop(get_current_user, None)
        for url in READ_ROUTES:
            self.assertEqual(self.client.get(url).status_code, 401, url)
        for url in PUT_ROUTES:
            self.assertEqual(self.client.put(url, json={"valor_hora": 10}).status_code, 401, url)

    def test_put_sem_csrf_falha_e_nao_grava(self):
        self.app.dependency_overrides.pop(require_csrf, None)
        self._as("diretoria")
        before = (dict(self.db.resource_rates), dict(self.db.operator_rates))
        for url in PUT_ROUTES:
            response = self.client.put(url, json={"valor_hora": 10})
            self.assertIn(response.status_code, (401, 403), (url, response.text))
        self.assertEqual((self.db.resource_rates, self.db.operator_rates), before)

    def test_valor_invalido_e_422_estruturado(self):
        self._as("diretoria")
        before = (dict(self.db.resource_rates), dict(self.db.operator_rates))
        for url in PUT_ROUTES:
            for value, code in ((0, "COST_RATE_INVALID"), (-5, "COST_RATE_INVALID"),
                                (1e10, "COST_RATE_INVALID"), ("abc", "validation_error"),
                                (None, "validation_error"), (True, "validation_error"),
                                (False, "validation_error"), ("NaN", "validation_error"),
                                ("12", "validation_error")):
                response = self.client.put(url, json={"valor_hora": value})
                self.assertEqual(response.status_code, 422, (url, value, response.text))
                self.assertEqual(response.json()["code"], code, (url, value))
            missing = self.client.put(url, json={})
            self.assertEqual(missing.status_code, 422)
            extra = self.client.put(url, json={"valor_hora": 10, "usuario": "x"})
            self.assertEqual(extra.status_code, 422)
        self.assertEqual((self.db.resource_rates, self.db.operator_rates), before)
        # Inteiro JSON continua aceito.
        for url in PUT_ROUTES:
            response = self.client.put(url, json={"valor_hora": 25})
            self.assertEqual(response.status_code, 200, (url, response.text))
        self.assertEqual(self.db.resource_rates["LASER1"], Decimal("25.00"))
        self.assertEqual(self.db.operator_rates[1], Decimal("25.00"))

    def test_operador_inexistente_404_estruturado(self):
        self._as("diretoria")
        response = self.client.put(f"{BASE}/custos/pessoa/999", json={"valor_hora": 10})
        self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(response.json()["code"], "OPERATOR_NOT_FOUND")
        self.assertEqual(self.client.put(f"{BASE}/custos/pessoa/abc", json={"valor_hora": 10}).status_code, 422)

    def test_periodo_invalido_e_422_estruturado_nao_500(self):
        self._as("diretoria")
        for url in (f"{BASE}/painel", f"{BASE}/ficha"):
            response = self.client.get(url, params={"periodo": "ano"})
            self.assertEqual(response.status_code, 422, (url, response.text))
            body = response.json()
            self.assertEqual(body["code"], "INVALID_PERIOD")
            self.assertTrue(body["message"])


# Rotas de gestão que já existiam antes da aba Diretoria.
LEAK_ROUTES = (
    "/api/v1/management/overview",
    "/api/v1/management/overview/trend",
    "/api/v1/management/sectors",
    "/api/v1/management/badges",
    "/api/v1/management/users",
    "/api/v1/management/standard-times",
    "/api/v1/analytics",
    "/api/v1/analytics/hours-utilization",
    "/api/v1/analytics/downtimes",
    "/api/v1/analytics/capacity",
    "/api/v1/reports/recursos",
    "/api/v1/reports/setores",
    "/api/v1/reports/completo",
    "/api/v1/reports/gerencial",
)


class _LeakDatabase(ApiFakeDatabase):
    """Banco falso com valores por hora cadastrados: se alguma rota de gestão
    passasse a ler as taxas, as chaves de R$ apareceriam na resposta."""

    def listar_custos_hora_recurso(self):
        return [{"recurso": "LASER1", "valor_hora": Decimal("150")}]

    def listar_custos_hora_operador(self):
        return [{"operador_id": 1, "valor_hora": Decimal("100")}]


class DirectorLeakTests(_ApiCase):
    def setUp(self):
        self._build(_LeakDatabase())

    def test_rotas_de_gestao_nao_expoem_r_para_diretoria_nem_gestor(self):
        answered = 0
        for role in ("diretoria", "gestor"):
            self._as(role)
            for url in LEAK_ROUTES:
                response = self.client.get(url)
                self.assertLess(response.status_code, 500, (role, url, response.text[:300]))
                if response.status_code == 200:
                    answered += 1
                self.assertEqual(_money_keys(response.json()), [], (role, url))
        # A varredura só prova algo se a maioria das rotas respondeu de verdade.
        self.assertGreaterEqual(answered, len(LEAK_ROUTES))

    def test_varredura_acha_chave_aninhada(self):
        self.assertEqual(_money_keys({"a": [{"b": {"custo": 1}}]}), ["$.a[0].b.custo"])


if __name__ == "__main__":
    unittest.main()
