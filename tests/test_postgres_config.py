import unittest

from app.database.config import load_postgres_config
from app.database.database import Database
from app.database.errors import DatabaseConfigurationError


class PostgresConfigTests(unittest.TestCase):
    def test_producao_exige_url_ou_variaveis_pg(self):
        with self.assertRaises(DatabaseConfigurationError):
            load_postgres_config(environ={})

    def test_configura_por_variaveis_pg_sem_expor_senha(self):
        config = load_postgres_config(environ={
            "PGHOST": "db.internal",
            "PGPORT": "5433",
            "PGDATABASE": "gestor",
            "PGUSER": "app",
            "PGPASSWORD": "segredo",
            "PGSSLMODE": "require",
            "PGPOOL_MAX_SIZE": "3",
        })
        self.assertEqual(config.max_pool_size, 3)
        self.assertEqual(config.safe_target["host"], "db.internal")
        self.assertNotIn("password", config.safe_target)
        self.assertNotIn("segredo", str(config.safe_target))

    def test_integracao_nunca_herda_database_url(self):
        with self.assertRaises(DatabaseConfigurationError):
            load_postgres_config(testing=True, environ={"DATABASE_URL": "postgresql://app:pw@db/prod"})

    def test_integracao_rejeita_mesmo_banco_operacional(self):
        dsn = "postgresql://app:pw@db/gestor"
        with self.assertRaises(DatabaseConfigurationError):
            load_postgres_config(testing=True, environ={"DATABASE_URL": dsn, "TEST_DATABASE_URL": dsn})

    def test_integracao_aceita_banco_isolado(self):
        config = load_postgres_config(testing=True, environ={
            "DATABASE_URL": "postgresql://app:pw@db/prod",
            "TEST_DATABASE_URL": "postgresql://app:pw@db/test",
            "GESTOR_EXPECTED_DATABASE": "test",
        })
        self.assertEqual(config.safe_target["dbname"], "test")

    def test_integracao_exige_identidade_explicita_do_banco(self):
        with self.assertRaises(DatabaseConfigurationError):
            load_postgres_config(testing=True, environ={
                "TEST_DATABASE_URL": "postgresql://app:pw@db/gestor_pecas",
            })

    def test_facade_padrao_recusa_dsn_operacional_explicita(self):
        with self.assertRaises(DatabaseConfigurationError):
            Database(
                dsn="postgresql://app:pw@db/gestor_pecas",
                auto_migrate=False,
            )

    def test_execucao_isolada_recusa_banco_diferente_do_esperado(self):
        with self.assertRaises(DatabaseConfigurationError):
            load_postgres_config(environ={
                "DATABASE_URL": "postgresql://app:pw@db/gestor_pecas",
                "GESTOR_EXPECTED_DATABASE": "gestor_pecas_test",
            })

    def test_execucao_isolada_aceita_exatamente_o_banco_esperado(self):
        config = load_postgres_config(environ={
            "DATABASE_URL": "postgresql://app:pw@db/gestor_pecas_test",
            "GESTOR_EXPECTED_DATABASE": "gestor_pecas_test",
        })
        self.assertEqual(config.safe_target["dbname"], "gestor_pecas_test")


if __name__ == "__main__":
    unittest.main()
