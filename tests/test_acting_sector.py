"""Etapa 3: admin/desenvolvedor apontando "como" um setor (06/11/2026)."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.api.config import WebSettings
from backend.api.main import create_app
from tests.fakes import FakeDatabase

H = "X-Acting-Sector"
SENHA = "senha-forte-123"


def _client(db):
    settings = WebSettings(
        environment="test",
        session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
        allowed_hosts=("testserver",),
        allowed_origins=("http://testserver",),
    )
    return TestClient(create_app(settings=settings, database_factory=lambda: db))


class ModoAgindoComoSetorTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.db.criar_usuario("gabriel", SENHA, "admin")
        self.db.criar_usuario("iago", SENHA, "desenvolvedor")
        self.db.criar_usuario("lider1", SENHA, "lider")
        self.db.criar_usuario("op", SENHA, "operador_dobra")

    def _entrar(self, client, nome):
        r = client.post("/api/v1/auth/login", json={"username": nome, "password": SENHA})
        self.assertEqual(r.status_code, 200, r.text)

    def test_admin_e_dev_viram_o_operador_do_setor_no_nome_marcado(self):
        for nome in ("gabriel", "iago"):
            with _client(self.db) as c:
                self._entrar(c, nome)
                normal = c.get("/api/v1/auth/session").json()
                self.assertTrue(normal["management_access"])
                self.assertIsNone(normal["acting_sector"])
                r = c.get("/api/v1/auth/session", headers={H: "operador_dobra"})
                self.assertEqual(r.status_code, 200, r.text)
                s = r.json()
                self.assertEqual(s["acting_sector"], "Dobra")
                self.assertEqual(s["operator_sector"], "Dobra")
                self.assertTrue(s["operator_access"])
                self.assertFalse(s["management_access"])
                self.assertEqual(s["id"], normal["id"])
                self.assertTrue(s["name"].endswith(" (gestão)"))
                self.assertTrue(s["name"].startswith(normal["name"]))

    def test_sem_cabecalho_a_sessao_nao_muda(self):
        with _client(self.db) as c:
            self._entrar(c, "gabriel")
            self.assertIsNone(c.get("/api/v1/auth/session").json()["acting_sector"])

    def test_nivel_que_nao_e_admin_e_recusado_nao_ignorado(self):
        for nome in ("lider1", "op"):
            with _client(self.db) as c:
                self._entrar(c, nome)
                r = c.get("/api/v1/auth/session", headers={H: "operador_dobra"})
                self.assertEqual(r.status_code, 403, nome)

    def test_setor_invalido_da_422_e_nivel_de_gestao_nao_vale_como_setor(self):
        with _client(self.db) as c:
            self._entrar(c, "gabriel")
            for valor in ("admin", "desenvolvedor", "naoexiste"):
                self.assertEqual(c.get("/api/v1/auth/session", headers={H: valor}).status_code, 422, valor)

    def test_no_modo_setor_a_conta_perde_a_gestao(self):
        with _client(self.db) as c:
            self._entrar(c, "gabriel")
            self.assertEqual(c.get("/api/v1/management/audit", headers={H: "operador_dobra"}).status_code, 403)

    def test_lista_de_setores_so_para_admin(self):
        with _client(self.db) as c:
            self._entrar(c, "gabriel")
            r = c.get("/api/v1/management/operator-sectors")
            self.assertEqual(r.status_code, 200)
            niveis = {i["level"] for i in r.json()["items"]}
            self.assertIn("operador_dobra", niveis)
            self.assertNotIn("admin", niveis)
        with _client(self.db) as c:
            self._entrar(c, "lider1")
            self.assertEqual(c.get("/api/v1/management/operator-sectors").status_code, 403)


if __name__ == "__main__":
    unittest.main()
