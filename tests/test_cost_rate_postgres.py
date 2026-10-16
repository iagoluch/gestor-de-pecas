"""Custo por hora de recurso e operador contra o Postgres real (migration 63).

Schema isolado em ``TEST_DATABASE_URL`` (nunca o REAL), criado e descartado por
teste. Cobre o que dublês não executam: upsert por ``UPPER(recurso)``, FK do
operador e o CHECK ``valor_hora > 0``.
"""

from decimal import Decimal
import os
import unittest
from uuid import uuid4

import psycopg
from psycopg import errors, sql
from psycopg.conninfo import make_conninfo

from app.database.config import load_postgres_config
from app.database.database import Database
from app.database.schema import SCHEMA_VERSION


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class CostRatePostgresTests(unittest.TestCase):
    def setUp(self):
        base = load_postgres_config(testing=True)
        self.admin_dsn = base.dsn
        self.schema = "custo_hora_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self._drop_schema)
        self.db = Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}"))

    def _drop_schema(self):
        db = getattr(self, "db", None)
        if db is not None:
            db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _scalar(self, query, params=()):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return list(cursor.fetchone().values())[0]

    def _novo_operador(self, cracha="C001"):
        return self._scalar(
            "INSERT INTO operadores_apontamento (cracha, nome) VALUES (%s, %s) RETURNING id",
            (cracha, "Operador Teste"),
        )

    def test_migration_cria_as_duas_tabelas(self):
        self.assertGreaterEqual(SCHEMA_VERSION, 63)
        for tabela in ("custo_hora_recurso", "custo_hora_operador"):
            self.assertEqual(
                self._scalar(
                    "SELECT COUNT(*) FROM information_schema.tables"
                    " WHERE table_schema = current_schema() AND table_name = %s",
                    (tabela,),
                ),
                1,
                tabela,
            )
        self.assertEqual(
            self._scalar("SELECT COUNT(*) FROM schema_migrations WHERE version = 63"), 1
        )

    def test_recurso_e_upsert_por_nome_sem_caixa(self):
        self.db.salvar_custo_hora_recurso("laser1", Decimal("250"), "ana")
        self.db.salvar_custo_hora_recurso("LASER1", Decimal("300"), "bia")
        linhas = self.db.listar_custos_hora_recurso()
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["recurso"], "LASER1")
        self.assertEqual(linhas[0]["valor_hora"], Decimal("300.00"))
        self.assertEqual(linhas[0]["atualizado_por"], "bia")
        self.assertIsNotNone(linhas[0]["atualizado_em"])

    def test_operador_salva_e_atualiza(self):
        operador = self._novo_operador()
        self.db.salvar_custo_hora_operador(operador, Decimal("40"), "ana")
        self.db.salvar_custo_hora_operador(operador, Decimal("45.5"), "bia")
        linhas = self.db.listar_custos_hora_operador()
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["operador_id"], operador)
        self.assertEqual(linhas[0]["valor_hora"], Decimal("45.50"))
        self.assertEqual(linhas[0]["atualizado_por"], "bia")

    def test_operador_inexistente_levanta_erro_de_fk(self):
        with self.assertRaises(errors.ForeignKeyViolation):
            self.db.salvar_custo_hora_operador(999_999, Decimal("40"), "ana")

    def test_apagar_operador_remove_o_custo_dele(self):
        operador = self._novo_operador()
        self.db.salvar_custo_hora_operador(operador, Decimal("40"), "ana")
        self._scalar("DELETE FROM operadores_apontamento WHERE id = %s RETURNING id", (operador,))
        self.assertEqual(self.db.listar_custos_hora_operador(), [])

    def test_check_rejeita_zero_e_negativo(self):
        operador = self._novo_operador()
        for valor in (Decimal("0"), Decimal("-1")):
            with self.subTest(valor=valor):
                with self.assertRaises(errors.CheckViolation):
                    self.db.salvar_custo_hora_recurso("LASER1", valor, "ana")
                with self.assertRaises(errors.CheckViolation):
                    self.db.salvar_custo_hora_operador(operador, valor, "ana")
        self.assertEqual(self.db.listar_custos_hora_recurso(), [])
        self.assertEqual(self.db.listar_custos_hora_operador(), [])


if __name__ == "__main__":
    unittest.main()
