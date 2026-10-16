"""Auditoria de segurança 16/10/2026: freio na busca de OP, diagnóstico do Corte só admin,
reconstrução do frontend só em ambiente de desenvolvimento/teste."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api.config import WebSettings
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import create_app
from backend.api.schemas.auth import SessionUser


def _app(environment="test"):
    settings = WebSettings(
        environment=environment,
        session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
        allowed_hosts=("testserver",),
        allowed_origins=("http://testserver",),
    )
    app = create_app(settings=settings, database_factory=lambda: object())
    app.dependency_overrides[get_database] = lambda: object()
    app.dependency_overrides[require_csrf] = lambda: None
    return app


def _user(role, **flags):
    base = dict(management_access=False, andon_access=False, operator_access=False)
    base.update(flags)
    return SessionUser(id=7, name=role, role=role, **base)


class BuscaDeOpFrequenciaTests(unittest.TestCase):
    def test_busca_de_op_estoura_o_freio_com_429(self):
        app = _app()
        app.dependency_overrides[get_current_user] = lambda: _user("operador_serra", operator_access=True)
        client = TestClient(app)

        def falha(_op):
            raise RuntimeError("Protheus fora")

        stub = SimpleNamespace(provision=falha, unavailable_message="indisponível")
        with patch("backend.api.routers.operator._provisioning", return_value=stub):
            codigos = [client.post(f"/api/v1/operator/operations/OP{i}/sync").status_code for i in range(11)]

        self.assertEqual(codigos[:10], [503] * 10)
        self.assertEqual(codigos[10], 429)


class DiagnosticoCorteTests(unittest.TestCase):
    def test_gestao_comum_nao_ve_o_diagnostico_e_admin_ve(self):
        app = _app()
        client = TestClient(app)
        app.dependency_overrides[get_current_user] = lambda: _user(
            "supervisor", management_access=True, andon_access=True
        )
        self.assertEqual(client.get("/api/v1/cutting/sync/diagnostico").status_code, 403)
        app.dependency_overrides[get_current_user] = lambda: _user(
            "admin", management_access=True, andon_access=True
        )
        self.assertEqual(client.get("/api/v1/cutting/sync/diagnostico").status_code, 200)


class ReconstruirFrontendTests(unittest.TestCase):
    def _post(self, environment):
        app = _app(environment)
        app.dependency_overrides[get_current_user] = lambda: _user(
            "admin", management_access=True, andon_access=True
        )
        return TestClient(app).post("/api/v1/system/rebuild-frontend")

    def test_fora_de_dev_e_teste_a_rota_responde_404_sem_rodar_npm(self):
        with patch("backend.api.routers.system.subprocess.run") as run:
            resposta = self._post("production")
        self.assertEqual(resposta.status_code, 404)
        run.assert_not_called()

    def test_em_teste_continua_disponivel(self):
        with patch("backend.api.routers.system.subprocess.run") as run:
            run.return_value = SimpleNamespace(returncode=0, stdout="ok", stderr="")
            resposta = self._post("test")
        self.assertEqual(resposta.status_code, 200)


if __name__ == "__main__":
    unittest.main()
