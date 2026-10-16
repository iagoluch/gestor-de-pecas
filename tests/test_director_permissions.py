"""Permissão da aba Diretoria (16/10/2026): só ``admin`` e ``diretoria``."""

from __future__ import annotations

from types import SimpleNamespace
import unittest

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.permissions import DIRECTOR_LEVELS, USER_LEVELS, can_view_director_tab
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_diretoria_user
from backend.api.errors import register_error_handlers
from backend.api.schemas.auth import SessionUser


def _user(role):
    return SessionUser(
        id=7, name=f"Conta {role}", role=role, management_access=True,
        andon_access=True, operator_access=False,
    )


class DirectorPermissionTests(unittest.TestCase):
    def test_niveis_da_aba_sao_exatamente_admin_e_diretoria(self):
        self.assertEqual(DIRECTOR_LEVELS, ("admin", "diretoria"))

    def test_so_admin_e_diretoria_veem_a_aba(self):
        for level in USER_LEVELS:
            self.assertEqual(
                can_view_director_tab(level), level in ("admin", "diretoria"), level
            )

    def test_nivel_desconhecido_ou_vazio_nao_ve(self):
        for level in (None, "", "   ", "root", "inexistente"):
            self.assertFalse(can_view_director_tab(level), repr(level))

    def test_normaliza_caixa_e_espacos(self):
        self.assertTrue(can_view_director_tab(" Diretoria "))
        self.assertTrue(can_view_director_tab("ADMIN"))


class RequireDiretoriaUserTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.state.settings = SimpleNamespace(session_cookie_name="gestor_session")
        register_error_handlers(self.app)
        self.app.dependency_overrides[get_database] = lambda: object()

        @self.app.get("/ping")
        def ping(user: SessionUser = Depends(require_diretoria_user)):
            return {"role": user.role}

        self.client = TestClient(self.app)

    def _as(self, role):
        self.app.dependency_overrides[get_current_user] = lambda: _user(role)

    def test_admin_e_diretoria_passam(self):
        for role in ("admin", "diretoria"):
            self._as(role)
            response = self.client.get("/ping")
            self.assertEqual(response.status_code, 200, role)
            self.assertEqual(response.json(), {"role": role})

    def test_demais_niveis_recebem_403_com_codigo_estavel(self):
        for role in USER_LEVELS:
            if role in DIRECTOR_LEVELS:
                continue
            self._as(role)
            response = self.client.get("/ping")
            self.assertEqual(response.status_code, 403, role)
            self.assertEqual(response.json()["code"], "director_access_denied", role)

    def test_sem_sessao_recebe_401(self):
        response = self.client.get("/ping")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "authentication_required")


if __name__ == "__main__":
    unittest.main()
