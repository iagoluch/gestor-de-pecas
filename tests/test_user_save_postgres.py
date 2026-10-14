"""SEC-04: a edição de usuário é uma única instrução no PostgreSQL real."""

import os
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database.config import load_postgres_config
from app.database.database import Database


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class SalvarUsuarioPostgresTests(unittest.TestCase):
    def setUp(self):
        base = load_postgres_config(testing=True)
        self.admin_dsn = base.dsn
        self.schema = "gestor_test_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.db = Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}"))
        self.usuario_id = self.db.criar_usuario("Terminal", "123456", "operador_dobra", unidade="3")

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _salvar(self, **mudancas):
        campos = {"nivel": "operador_dobra", "ativo": True, "unidade": "3", **mudancas}
        return self.db.salvar_usuario(self.usuario_id, **campos)

    def test_session_version_so_sobe_quando_nivel_situacao_ou_senha_mudam(self):
        self.assertTrue(self._salvar(unidade="4"))
        linha = self.db.obter_usuario_por_id(self.usuario_id)
        self.assertEqual((linha["unidade"], linha["session_version"]), ("4", 0))
        self._salvar(unidade="4", nivel="operador_corte")
        self._salvar(unidade="4", nivel="operador_corte", ativo=False)
        self._salvar(unidade="4", nivel="operador_corte", ativo=False, nova_senha="outra-senha")
        self.assertEqual(self.db.obter_usuario_por_id(self.usuario_id)["session_version"], 3)

    def test_falha_no_meio_nao_deixa_edicao_pela_metade(self):
        with self.assertRaises(psycopg.errors.NotNullViolation):
            self._salvar(unidade="9", ativo=False, nivel=None, nova_senha="outra-senha")
        linha = self.db.obter_usuario_por_id(self.usuario_id)
        self.assertEqual(
            (linha["unidade"], linha["ativo"], linha["nivel"], linha["session_version"]),
            ("3", True, "operador_dobra", 0),
        )
        self.assertIsNotNone(self.db.autenticar_usuario("Terminal", "123456"))


if __name__ == "__main__":
    unittest.main()
