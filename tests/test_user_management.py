"""Cadastro de usuários — tela exclusiva da conta admin (14/09/2026)."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.core.permissions import USER_LEVELS
from backend.api.config import WebSettings
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_admin_user, require_csrf
from backend.api.main import create_app
from backend.api.schemas.auth import SessionUser
from tests.fakes import FakeDatabase


def _settings():
    return WebSettings(
        environment="test",
        session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
        allowed_hosts=("testserver",),
        allowed_origins=("http://testserver",),
    )


def _management_user():
    return SessionUser(
        id=2, name="Gestor Y", role="supervisor",
        management_access=True, andon_access=True, operator_access=False,
    )


def _admin_user():
    return SessionUser(
        id=1, name="Admin Z", role="admin",
        management_access=True, andon_access=True, operator_access=False,
    )


class UserManagementApiTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.app = create_app(settings=_settings(), database_factory=lambda: self.db)
        self.app.dependency_overrides[get_database] = lambda: self.db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.client = TestClient(self.app)

    def _as(self, user):
        self.app.dependency_overrides[get_current_user] = lambda: user
        self.app.dependency_overrides[require_admin_user] = (
            lambda: user if user.role == "admin" else self._forbid()
        )

    @staticmethod
    def _forbid():
        from backend.api.errors import AppError

        raise AppError("admin_access_denied", "sem acesso", status_code=403)

    def test_gestao_comum_nao_acessa_o_cadastro_de_usuarios(self):
        self._as(_management_user())
        resposta = self.client.get("/api/v1/management/users")
        self.assertEqual(resposta.status_code, 403)

    def test_crachas_agora_e_exclusivo_do_admin(self):
        # Reorganização 15/09/2026: Crachás saiu de "qualquer gestão" para a
        # seção DEV, junto do Cadastro de usuários.
        self._as(_management_user())
        resposta = self.client.get("/api/v1/management/badges")
        self.assertEqual(resposta.status_code, 403)

        self._as(_admin_user())
        resposta = self.client.get("/api/v1/management/badges")
        self.assertEqual(resposta.status_code, 200)

    def test_admin_lista_niveis_disponiveis(self):
        self._as(_admin_user())
        resposta = self.client.get("/api/v1/management/users")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["levels"], list(USER_LEVELS))

    def test_admin_cria_usuario_com_senha_obrigatoria(self):
        self._as(_admin_user())
        sem_senha = self.client.post(
            "/api/v1/management/users",
            json={"nome": "Novo Supervisor", "nivel": "supervisor", "ativo": True},
        )
        self.assertEqual(sem_senha.status_code, 422)

        criado = self.client.post(
            "/api/v1/management/users",
            json={
                "nome": "Novo Supervisor", "nivel": "supervisor", "ativo": True,
                "senha": "senha-forte-123",
            },
        )
        self.assertEqual(criado.status_code, 200)
        item = criado.json()["item"]
        self.assertEqual(item["nome"], "Novo Supervisor")
        self.assertEqual(item["nivel"], "supervisor")
        self.assertTrue(item["ativo"])

    def test_nivel_invalido_e_recusado(self):
        self._as(_admin_user())
        resposta = self.client.post(
            "/api/v1/management/users",
            json={"nome": "X", "nivel": "nivel-que-nao-existe", "senha": "senha-forte-123"},
        )
        self.assertEqual(resposta.status_code, 422)

    def test_nome_duplicado_e_recusado(self):
        self._as(_admin_user())
        self.db.criar_usuario("Duplicado", "senha-123456", "gestor")
        resposta = self.client.post(
            "/api/v1/management/users",
            json={"nome": "Duplicado", "nivel": "gestor", "senha": "senha-forte-123"},
        )
        self.assertEqual(resposta.status_code, 409)

    def test_admin_edita_nivel_situacao_e_senha_sem_exigir_senha_de_novo(self):
        self._as(_admin_user())
        usuario_id = self.db.criar_usuario("Editar Depois", "senha-antiga", "gestor")

        editado = self.client.post(
            "/api/v1/management/users",
            json={"id": usuario_id, "nome": "Editar Depois", "nivel": "admin", "ativo": False},
        )
        self.assertEqual(editado.status_code, 200)
        item = editado.json()["item"]
        self.assertEqual(item["nivel"], "admin")
        self.assertFalse(item["ativo"])

        atualizado = next(u for u in self.db.users if u["id"] == usuario_id)
        self.assertEqual(atualizado["senha"], "senha-antiga")

    def test_admin_pode_criar_outra_conta_admin(self):
        self._as(_admin_user())
        resposta = self.client.post(
            "/api/v1/management/users",
            json={"nome": "Segundo Admin", "nivel": "admin", "senha": "senha-forte-123"},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["item"]["nivel"], "admin")


if __name__ == "__main__":
    unittest.main()
