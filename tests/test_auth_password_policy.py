"""Auditoria 14/10/2026 — SEC-05: freio por IP e troca obrigatória da senha
padrão só para contas de gestão."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.api.routers import auth as auth_router
from tests.test_web_api import ApiFakeDatabase, _settings

LOGIN = "/api/v1/auth/login"


class _Base(unittest.TestCase):
    def setUp(self):
        self.db = ApiFakeDatabase()
        self.client = TestClient(create_app(settings=_settings(), database_factory=lambda: self.db))
        self.addCleanup(self.client.close)

    def _login(self, username, password):
        return self.client.post(LOGIN, json={"username": username, "password": password})

    def _csrf(self):
        return {"X-CSRF-Token": self.client.cookies.get("gestor_csrf")}


class SenhaPadraoDaGestaoTests(_Base):
    def setUp(self):
        super().setUp()
        self.db.criar_usuario("Admin Padrao", "123456", "admin")
        self.db.criar_usuario("Terminal Dobra", "123456", "operador_dobra")

    def test_gestao_com_senha_padrao_so_entra_depois_de_trocar(self):
        entrada = self._login("Admin Padrao", "123456")
        self.assertEqual(entrada.status_code, 200)
        self.assertTrue(entrada.json()["password_change_required"])
        self.assertTrue(self.client.get("/api/v1/auth/session").json()["password_change_required"])

        bloqueada = self.client.get("/api/v1/management/users")
        self.assertEqual(
            (bloqueada.status_code, bloqueada.json()["code"]), (403, "password_change_required")
        )

        for fraca in ("123456", "1234567"):
            recusa = self.client.post(
                "/api/v1/auth/password", json={"new_password": fraca}, headers=self._csrf()
            )
            self.assertEqual((recusa.status_code, recusa.json()["code"]), (422, "user_password_weak"))

        troca = self.client.post(
            "/api/v1/auth/password", json={"new_password": "senha-nova-forte"}, headers=self._csrf()
        )
        self.assertEqual(troca.status_code, 200, troca.text)
        self.assertFalse(troca.json()["password_change_required"])
        # A sessão nova, devolvida na troca, já abre as telas de gestão.
        self.assertEqual(self.client.get("/api/v1/management/users").status_code, 200)
        self.assertEqual(self._login("Admin Padrao", "123456").status_code, 401)
        self.assertFalse(self._login("Admin Padrao", "senha-nova-forte").json()["password_change_required"])

    def test_troca_exige_csrf(self):
        self._login("Admin Padrao", "123456")
        sem_csrf = self.client.post("/api/v1/auth/password", json={"new_password": "senha-nova-forte"})
        self.assertEqual(sem_csrf.status_code, 403)

    def test_gestao_pendente_ainda_consegue_sair(self):
        self._login("Admin Padrao", "123456")
        self.assertEqual(self.client.post("/api/v1/auth/logout", headers=self._csrf()).status_code, 204)

    def test_operador_com_senha_padrao_entra_normal(self):
        entrada = self._login("Terminal Dobra", "123456")
        self.assertEqual(entrada.status_code, 200)
        self.assertFalse(entrada.json()["password_change_required"])
        self.assertFalse(self.client.get("/api/v1/auth/session").json()["password_change_required"])
        nada_a_trocar = self.client.post(
            "/api/v1/auth/password", json={"new_password": "qualquer-coisa"}, headers=self._csrf()
        )
        self.assertEqual(nada_a_trocar.status_code, 409)


class SessaoAnteriorAoAvisoTests(_Base):
    """Cookie emitido antes do deploy não tem ``session_format`` nem o aviso."""

    def setUp(self):
        super().setUp()
        self.db.criar_usuario("Admin Padrao", "123456", "admin")
        self.db.criar_usuario("Terminal Dobra", "123456", "operador_dobra")

    def _cookie_antigo(self, username):
        settings = self.client.app.state.settings
        user_id = next(int(row["id"]) for row in self.db.users if row["nome"] == username)
        agora = int(time.time())
        claims = {
            "user_id": user_id, "username": username, "role": "x",
            "issued_at": agora, "expires_at": agora + 3600,
            "csrf": "csrf-antigo", "session_id": "sid-antigo", "session_version": 0,
        }
        payload = json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8")
        assinatura = hmac.new(
            settings.session_secret.encode("utf-8"), payload, hashlib.sha256
        ).digest()
        b64 = lambda raw: base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        self.client.cookies.set(settings.session_cookie_name, f"{b64(payload)}.{b64(assinatura)}")

    def test_cookie_antigo_de_gestao_e_recusado_e_novo_login_grava_o_aviso(self):
        self._cookie_antigo("Admin Padrao")
        recusa = self.client.get("/api/v1/auth/session")
        self.assertEqual((recusa.status_code, recusa.json()["code"]), (401, "session_outdated"))
        self.assertEqual(self.client.get("/api/v1/management/users").status_code, 401)
        self.client.cookies.clear()
        self.assertTrue(self._login("Admin Padrao", "123456").json()["password_change_required"])
        self.assertTrue(self.client.get("/api/v1/auth/session").json()["password_change_required"])

    def test_cookie_antigo_de_operador_continua_valido(self):
        self._cookie_antigo("Terminal Dobra")
        sessao = self.client.get("/api/v1/auth/session")
        self.assertEqual(sessao.status_code, 200, sessao.text)
        self.assertFalse(sessao.json()["password_change_required"])


class FreioPorIpTests(_Base):
    def setUp(self):
        super().setUp()
        self.db.criar_usuario("Terminal Dobra", "123456", "operador_dobra")
        for nome, valor in (("LOGIN_DELAY_BASE_SECONDS", 0.5), ("LOGIN_DELAY_MAX_SECONDS", 8.0)):
            patcher = patch.object(auth_router, nome, valor)
            patcher.start()
            self.addCleanup(patcher.stop)
        sleep = patch.object(auth_router.anyio, "sleep", new=AsyncMock())
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def test_varredura_de_nomes_e_atrasada_depois_do_limite(self):
        limite = auth_router.LOGIN_IP_FAILURE_LIMIT
        for indice in range(limite + 1):
            self.assertEqual(self._login(f"cracha-{indice}", "123456").status_code, 401)
        self.sleep.assert_not_awaited()
        self.assertEqual(self._login("cracha-novo", "123456").status_code, 401)
        self.sleep.assert_awaited_once_with(0.5)

    def test_acertos_nao_contam_e_operador_legitimo_entra_sem_esperar(self):
        for _ in range(50):
            self.assertEqual(self._login("Terminal Dobra", "123456").status_code, 200)
        # Vários operadores do mesmo terminal errando uma vez cada: abaixo do limite.
        for indice in range(auth_router.LOGIN_IP_FAILURE_LIMIT):
            self._login(f"operador-{indice}", "errou")
        self.assertEqual(self._login("Terminal Dobra", "123456").status_code, 200)
        self.sleep.assert_not_awaited()

    def test_acima_do_limite_so_atrasa_nunca_recusa(self):
        for indice in range(auth_router.LOGIN_IP_FAILURE_LIMIT + 10):
            self._login(f"cracha-{indice}", "123456")
        self.assertEqual(self._login("Terminal Dobra", "123456").status_code, 200)

    def test_ip_acima_do_limite_com_senha_certa_entra_sem_esperar(self):
        # Terminal atrás de um IP compartilhado já "sujo": o atraso do IP só
        # entra depois de uma falha, nunca antes de conferir a senha.
        for indice in range(auth_router.LOGIN_IP_FAILURE_LIMIT + 10):
            self._login(f"cracha-{indice}", "123456")
        self.assertTrue(self.sleep.await_count)
        self.sleep.reset_mock()
        self.assertEqual(self._login("Terminal Dobra", "123456").status_code, 200)
        self.sleep.assert_not_awaited()
        # E a próxima falha desse IP continua pagando o atraso antes do 401.
        self.assertEqual(self._login("cracha-outro", "errou").status_code, 401)
        self.sleep.assert_awaited_once()

    def test_linhas_antigas_sao_limpas_periodicamente(self):
        self.db.login_throttle["10.0.0.9:fantasma"] = (1, time.time() - 10_000)
        with patch.object(auth_router, "_last_throttle_cleanup", float("-inf")):
            self._login("Terminal Dobra", "123456")
        self.assertNotIn("10.0.0.9:fantasma", self.db.login_throttle)


if __name__ == "__main__":
    unittest.main()
