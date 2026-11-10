"""Persistência opcional do login sem ampliar a validade da sessão."""

from dataclasses import replace
import base64
import hashlib
import hmac
import json
from http.cookies import SimpleCookie
import unittest

from fastapi.testclient import TestClient

from backend.api.errors import AppError
from backend.api.main import create_app
from tests.test_web_api import ApiFakeDatabase, _settings


class RememberMeTests(unittest.TestCase):
    def setUp(self):
        self.db = ApiFakeDatabase()
        self.db.criar_usuario("Admin Login", "123456", "admin")
        self.settings = replace(_settings(), cookie_secure=True)
        self.app = create_app(settings=self.settings, database_factory=lambda: self.db)
        self.client = TestClient(self.app, base_url="https://testserver")
        self.addCleanup(self.client.close)

    def login(self, remember_me=None):
        payload = {"username": "Admin Login", "password": "123456"}
        if remember_me is not None:
            payload["remember_me"] = remember_me
        response = self.client.post("/api/v1/auth/login", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def cookies(self, response):
        cookies = SimpleCookie()
        for header in response.headers.get_list("set-cookie"):
            cookies.load(header)
        return cookies

    def assert_persistence(self, response, remembered):
        cookies = self.cookies(response)
        for name in (self.settings.session_cookie_name, self.settings.csrf_cookie_name):
            cookie = cookies[name]
            self.assertEqual(cookie["max-age"], str(self.settings.session_ttl_seconds) if remembered else "")
            self.assertEqual(cookie["expires"], "")
            self.assertEqual(cookie["samesite"], "strict")
            self.assertEqual(cookie["path"], "/")
            self.assertTrue(cookie["secure"])
        self.assertTrue(cookies[self.settings.session_cookie_name]["httponly"])
        self.assertFalse(cookies[self.settings.csrf_cookie_name]["httponly"])
        claims = self.app.state.session_signer.decode(self.client.cookies.get(self.settings.session_cookie_name))
        self.assertEqual(claims.remember_me, remembered)
        self.assertEqual(claims.expires_at - claims.issued_at, self.settings.session_ttl_seconds)
        return claims

    def test_login_sem_opcao_e_cookie_de_sessao(self):
        response = self.login()
        self.assert_persistence(response, False)
        self.assertNotIn("123456", response.text)
        self.assertNotIn("csrf", response.json())
        self.assertEqual(self.client.get("/api/v1/auth/session").status_code, 200)

    def test_login_marcado_e_desmarcado_respeita_prazo_e_protecoes(self):
        for remembered in (True, False):
            with self.subTest(remembered=remembered):
                self.assert_persistence(self.login(remembered), remembered)

    def test_troca_obrigatoria_de_senha_preserva_escolha(self):
        for remembered in (False, True):
            with self.subTest(remembered=remembered):
                # Uma conta nova por caso para manter a troca obrigatória real.
                self.client.cookies.clear()
                name = f"Admin Troca {remembered}"
                self.db.criar_usuario(name, "123456", "admin")
                response = self.client.post("/api/v1/auth/login", json={
                    "username": name, "password": "123456", "remember_me": remembered,
                })
                self.assertEqual(response.status_code, 200, response.text)
                old_token = self.client.cookies.get(self.settings.session_cookie_name)
                self.assertTrue(response.json()["password_change_required"])
                changed = self.client.post("/api/v1/auth/password", json={"new_password": "senha-nova-forte"}, headers={
                    "X-CSRF-Token": self.client.cookies.get(self.settings.csrf_cookie_name),
                })
                self.assertEqual(changed.status_code, 200, changed.text)
                self.assertFalse(changed.json()["password_change_required"])
                self.assert_persistence(changed, remembered)
                self.client.cookies.clear()
                self.client.cookies.set(self.settings.session_cookie_name, old_token, domain="testserver.local", path="/")
                revoked = self.client.get("/api/v1/auth/session")
                self.assertEqual((revoked.status_code, revoked.json()["code"]), (401, "session_revoked"))

    def test_logout_continua_exigindo_csrf_e_revoga_ambas_modalidades(self):
        for remembered in (False, True):
            with self.subTest(remembered=remembered):
                self.client.cookies.clear()
                self.login(remembered)
                old_token = self.client.cookies.get(self.settings.session_cookie_name)
                self.assertEqual(self.client.post("/api/v1/auth/logout").status_code, 403)
                response = self.client.post("/api/v1/auth/logout", headers={
                    "X-CSRF-Token": self.client.cookies.get(self.settings.csrf_cookie_name),
                })
                self.assertEqual(response.status_code, 204)
                for cookie in self.cookies(response).values():
                    self.assertEqual(cookie["max-age"], "0")
                self.client.cookies.clear()
                self.client.cookies.set(self.settings.session_cookie_name, old_token, domain="testserver.local", path="/")
                revoked = self.client.get("/api/v1/auth/session")
                self.assertEqual((revoked.status_code, revoked.json()["code"]), (401, "session_revoked"))

    def test_persistencia_nao_remove_expiracao_do_servidor(self):
        for remembered in (False, True):
            with self.subTest(remembered=remembered):
                claims = self.assert_persistence(self.login(remembered), remembered)
                token = self.client.cookies.get(self.settings.session_cookie_name)
                with self.assertRaises(AppError) as error:
                    self.app.state.session_signer.decode(token, now=claims.expires_at)
                self.assertEqual(error.exception.code, "expired_session")

    def test_cookie_anterior_sem_opcao_permanece_valido_e_persistente_na_troca(self):
        self.login()
        token = self.client.cookies.get(self.settings.session_cookie_name)
        encoded, _ = token.split(".")
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        payload.pop("remember_me")
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        signature = hmac.new(self.settings.session_secret.encode("utf-8"), raw, hashlib.sha256).digest()
        b64 = lambda value: base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
        legacy_token = f"{b64(raw)}.{b64(signature)}"
        self.client.cookies.clear()
        self.client.cookies.set(self.settings.session_cookie_name, legacy_token, domain="testserver.local", path="/")
        self.client.cookies.set(self.settings.csrf_cookie_name, payload["csrf"], domain="testserver.local", path="/")
        self.assertEqual(self.client.get("/api/v1/auth/session").status_code, 200)
        changed = self.client.post("/api/v1/auth/password", json={"new_password": "senha-nova-forte"}, headers={
            "X-CSRF-Token": payload["csrf"],
        })
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assert_persistence(changed, True)

