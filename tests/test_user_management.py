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
        id=900, name="Admin Z", role="admin",
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
            json={"nome": "Novo Operador", "nivel": "operador_corte", "ativo": True},
        )
        self.assertEqual(sem_senha.status_code, 422)

        criado = self.client.post(
            "/api/v1/management/users",
            json={
                "nome": "Novo Operador", "nivel": "operador_corte", "ativo": True,
                "senha": "senha-forte-123",
            },
        )
        self.assertEqual(criado.status_code, 200)
        item = criado.json()["item"]
        self.assertEqual(item["nome"], "Novo Operador")
        self.assertEqual(item["nivel"], "operador_corte")
        self.assertTrue(item["ativo"])

    def test_admin_cria_usuario_ja_inativo_sem_passar_por_ativo(self):
        self._as(_admin_user())
        criado = self.client.post(
            "/api/v1/management/users",
            json={"nome": "Desligado", "nivel": "operador_corte", "ativo": False, "senha": "senha-forte-123"},
        )
        self.assertEqual(criado.status_code, 200)
        self.assertFalse(criado.json()["item"]["ativo"])
        self.assertIsNone(self.db.autenticar_usuario("Desligado", "senha-forte-123"))

    def test_nivel_invalido_e_recusado(self):
        self._as(_admin_user())
        resposta = self.client.post(
            "/api/v1/management/users",
            json={"nome": "X", "nivel": "nivel-que-nao-existe", "senha": "senha-forte-123"},
        )
        self.assertEqual(resposta.status_code, 422)

    def test_nome_duplicado_e_recusado(self):
        self._as(_admin_user())
        self.db.criar_usuario("Duplicado", "senha-123456", "operador_corte")
        resposta = self.client.post(
            "/api/v1/management/users",
            json={"nome": "Duplicado", "nivel": "operador_corte", "senha": "senha-forte-123"},
        )
        self.assertEqual(resposta.status_code, 409)

    def test_niveis_crus_nao_sao_mais_atribuidos(self):
        self._as(_admin_user())
        for cru in ("lider", "supervisor", "gestor"):
            nova = self.client.post(
                "/api/v1/management/users",
                json={"nome": f"Cru {cru}", "nivel": cru, "senha": "senha-forte-123"},
            )
            self.assertEqual((nova.status_code, nova.json()["code"]), (422, "level_not_assignable"))
        antigo = self.db.criar_usuario("Conta Antiga", "senha-antiga", "gestor")
        corpo = {"id": antigo, "nome": "Conta Antiga", "ativo": True}
        # Conta que já está num nível cru pode ser salva sem trocar; para outra conta crua, não.
        self.assertEqual(self.client.post("/api/v1/management/users", json={**corpo, "nivel": "gestor"}).status_code, 200)
        self.assertEqual(self.client.post("/api/v1/management/users", json={**corpo, "nivel": "lider"}).status_code, 422)
        self.assertEqual(self.client.post("/api/v1/management/users", json={**corpo, "nivel": "operador_corte"}).status_code, 200)
        self.assertEqual(self.client.post("/api/v1/management/users", json={**corpo, "nivel": "gestor"}).status_code, 422)

    def test_lista_diz_em_qual_tela_cada_conta_entra(self):
        self._as(_admin_user())
        for nome, nivel in (("Op Corte", "operador_corte"), ("Sala Andon", "andon"), ("Gerente", "gestor")):
            self.db.criar_usuario(nome, "senha-antiga", nivel)
        telas = {u["nome"]: u["tela"] for u in self.client.get("/api/v1/management/users").json()["items"]}
        self.assertEqual(telas["Op Corte"], "apontamento")
        self.assertEqual(telas["Sala Andon"], "outro")
        self.assertEqual(telas["Gerente"], "gestao")

    def test_unidade_da_conta_e_gravada_aparada_e_listada(self):
        self._as(_admin_user())
        usuario_id = self.db.criar_usuario("Com Unidade", "senha-antiga", "gestor")
        corpo = {"id": usuario_id, "nome": "Com Unidade", "nivel": "gestor", "ativo": True}

        salvo = self.client.post("/api/v1/management/users", json={**corpo, "unidade": " 4 "})
        self.assertEqual(salvo.json()["item"]["unidade"], "4")
        listado = next(u for u in self.client.get("/api/v1/management/users").json()["items"] if u["id"] == usuario_id)
        self.assertEqual(listado["unidade"], "4")

        limpo = self.client.post("/api/v1/management/users", json={**corpo, "unidade": "  "})
        self.assertIsNone(limpo.json()["item"]["unidade"])

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

    def test_admin_nao_desativa_nem_rebaixa_a_propria_conta(self):
        admin = _admin_user()
        admin_id = self.db.criar_usuario("Admin Z", "senha-forte-123", "admin")
        admin.id = admin_id
        self._as(admin)

        for mudanca in ({"ativo": False, "nivel": "admin"}, {"ativo": True, "nivel": "operador_corte"}):
            resposta = self.client.post(
                "/api/v1/management/users",
                json={"id": admin_id, "nome": "Admin Z", **mudanca},
            )
            self.assertEqual(resposta.status_code, 409)
            self.assertEqual(resposta.json()["code"], "user_self_lockout")
        proprio = next(u for u in self.db.users if u["id"] == admin_id)
        self.assertTrue(proprio["ativo"])
        self.assertEqual(proprio["nivel"], "admin")

    def test_admin_exclui_outra_conta_mas_nao_a_propria(self):
        admin = _admin_user()
        admin.id = self.db.criar_usuario("Admin Z", "senha-forte-123", "admin")
        alvo = self.db.criar_usuario("Fulano", "senha-forte-123", "operador")
        self._as(admin)

        resposta = self.client.delete(f"/api/v1/management/users/{alvo}")
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(any(u["id"] == alvo for u in self.db.users))

        resposta = self.client.delete(f"/api/v1/management/users/{alvo}")
        self.assertEqual(resposta.status_code, 404)
        self.assertEqual(resposta.json()["code"], "user_not_found")

        resposta = self.client.delete(f"/api/v1/management/users/{admin.id}")
        self.assertEqual(resposta.status_code, 409)
        self.assertEqual(resposta.json()["code"], "user_self_delete")
        self.assertTrue(any(u["id"] == admin.id for u in self.db.users))

    def test_gestao_comum_nao_exclui_usuario(self):
        alvo = self.db.criar_usuario("Fulano", "senha-forte-123", "operador")
        self._as(_management_user())
        resposta = self.client.delete(f"/api/v1/management/users/{alvo}")
        self.assertEqual(resposta.status_code, 403)
        self.assertTrue(any(u["id"] == alvo for u in self.db.users))

    def test_nivel_personalizado_herda_permissoes_do_nivel_base(self):
        self._as(_admin_user())
        r = self.client.post("/api/v1/management/levels", json={"rotulo": "Planejador PCP", "nivel_base": "gestor"})
        self.assertEqual(r.status_code, 200)
        nome = r.json()["item"]["nome"]
        self.assertEqual(nome, "planejador_pcp")

        self.assertEqual(
            self.client.post("/api/v1/management/levels", json={"rotulo": "planejador pcp", "nivel_base": "gestor"}).status_code, 409
        )
        self.assertEqual(
            self.client.post("/api/v1/management/levels", json={"rotulo": "Gestor", "nivel_base": "gestor"}).status_code, 409
        )
        self.assertEqual(
            self.client.post("/api/v1/management/levels", json={"rotulo": "X", "nivel_base": "inexistente"}).status_code, 422
        )

        r = self.client.post(
            "/api/v1/management/users",
            json={"nome": "Ana", "nivel": nome, "senha": "senha-forte-123"},
        )
        self.assertEqual(r.status_code, 200)
        lista = self.client.get("/api/v1/management/users").json()
        self.assertIn(nome, lista["levels"])
        ana = next(i for i in lista["items"] if i["nome"] == "Ana")
        self.assertEqual((ana["nivel"], ana["nivel_atribuido"], ana["nivel_rotulo"]), ("gestor", nome, "Planejador PCP"))
        self.assertEqual(self.db.autenticar_usuario("Ana", "senha-forte-123")["nivel"], "gestor")

        r = self.client.delete(f"/api/v1/management/levels/{nome}")
        self.assertEqual((r.status_code, r.json()["code"]), (409, "level_in_use"))
        self.client.delete(f"/api/v1/management/users/{ana['id']}")
        self.assertEqual(self.client.delete(f"/api/v1/management/levels/{nome}").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/v1/management/levels/{nome}").status_code, 404)

    def test_gestao_comum_nao_cria_nivel(self):
        self._as(_management_user())
        r = self.client.post("/api/v1/management/levels", json={"rotulo": "Novo", "nivel_base": "gestor"})
        self.assertEqual(r.status_code, 403)

    def test_admin_pode_criar_outra_conta_admin(self):
        self._as(_admin_user())
        resposta = self.client.post(
            "/api/v1/management/users",
            json={"nome": "Segundo Admin", "nivel": "admin", "senha": "senha-forte-123"},
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.json()["item"]["nivel"], "admin")


    def test_admin_gera_codigo_de_vinculo_do_telegram(self):
        # Regressão: a rota usava user.username (inexistente em SessionUser) e dava 500.
        chamadas = []

        def gerar(operador_id, criado_por=None):
            chamadas.append((operador_id, criado_por))
            return {"status": "ok", "codigo": "ABC123", "expira_em": "2026-10-07T20:00:00", "operador": "Ana"}

        self.db.gerar_codigo_vinculo_telegram = gerar
        self._as(_admin_user())
        resposta = self.client.post("/api/v1/management/badges/7/telegram-link-code")
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json()["code"], "ABC123")
        self.assertEqual(chamadas, [(7, "Admin Z")])


if __name__ == "__main__":
    unittest.main()
