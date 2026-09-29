"""BK-22: o throttle dos dois logins roda contra a tabela `login_throttle` real."""

import os
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database.config import load_postgres_config
from app.database.database import Database
from backend.api.config import WebSettings
from backend.api.main import create_app
from backend.api.routers import dev_observatory as dev_observatory_router


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class LoginThrottlePostgresTests(unittest.TestCase):
    def setUp(self):
        base = load_postgres_config(testing=True)
        self.admin_dsn = base.dsn
        self.schema = "gestor_test_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.db = Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}"))
        self.db.criar_usuario("Operador Throttle", "senha-certa", "operador_dobra")
        settings = WebSettings(
            environment="test",
            session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
            allowed_hosts=("testserver",),
            allowed_origins=("http://testserver",),
            session_ttl_seconds=3600,
            dev_observatory_enabled=True,
            dev_observatory_login_username="devobs",
            dev_observatory_login_password="senha-do-observatorio",
        )
        self.client = TestClient(create_app(settings=settings, database_factory=lambda: self.db))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _contadores(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT throttle_key, failures FROM login_throttle ORDER BY throttle_key")
            return {row["throttle_key"]: row["failures"] for row in cursor.fetchall()}

    def test_login_principal_conta_no_banco_e_sucesso_zera(self):
        for _ in range(2):
            recusa = self.client.post(
                "/api/v1/auth/login", json={"username": "Operador Throttle", "password": "errada"}
            )
            self.assertEqual(recusa.status_code, 401, recusa.text)
        # O contador está na tabela, visível a qualquer worker que leia o banco.
        self.assertEqual(list(self._contadores().values()), [2])

        sucesso = self.client.post(
            "/api/v1/auth/login", json={"username": "Operador Throttle", "password": "senha-certa"}
        )
        self.assertEqual(sucesso.status_code, 200, sucesso.text)
        self.assertEqual(self._contadores(), {})

    def test_dev_observatory_trava_pelo_contador_do_banco(self):
        for tentativa in range(dev_observatory_router.LOGIN_MAX_FAILURES):
            recusa = self.client.post(
                "/api/v1/dev-observatory/login",
                json={"username": "devobs", "password": f"errada-{tentativa}"},
            )
            self.assertEqual(recusa.status_code, 401, recusa.text)
        self.assertEqual(
            list(self._contadores().values()), [dev_observatory_router.LOGIN_MAX_FAILURES]
        )
        travado = self.client.post(
            "/api/v1/dev-observatory/login",
            json={"username": "devobs", "password": "senha-do-observatorio"},
        )
        self.assertEqual(travado.status_code, 429, travado.text)


if __name__ == "__main__":
    unittest.main()
