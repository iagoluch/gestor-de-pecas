"""Integração da migration 14 somente no TEST_DATABASE_URL isolado."""

import os
import unittest
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database.config import load_postgres_config
from app.database.database import Database
from app.database.migrations import (
    AI_ASSISTANT_STATEMENTS,
    INTELLIGENCE_REPORTS_STATEMENTS,
    SCHEMA_VERSION,
)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class AIPostgresTests(unittest.TestCase):
    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "gestor_ai_test_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.admin_dsn = base.dsn
        isolated_dsn = make_conninfo(base.dsn, options=f"-c search_path={self.schema}")
        self.db = Database(isolated_dsn)

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def test_migration_14_cria_fks_constraints_indices_utf8_e_isolamento(self):
        self.assertEqual(self.db.obter_schema_version(), SCHEMA_VERSION)
        first_user = self.db.criar_usuario("Gestor Peças", "senha", "gestor")
        second_user = self.db.criar_usuario("Outro Gestor", "senha", "gestor")
        conversation = self.db.criar_conversa_ia(first_user, "Produção e qualidade")
        self.db.adicionar_mensagem_ia(
            conversation["id"],
            first_user,
            "user",
            "Como estão as peças boas, o refugo e o retrabalho?",
        )
        self.db.adicionar_mensagem_ia(
            conversation["id"],
            first_user,
            "assistant",
            "Dados insuficientes para confirmar a Produção.",
            model="openai/gpt-oss-120b",
            metadata={"availability": "dados_insuficientes"},
        )
        loaded = self.db.obter_conversa_ia(conversation["id"], first_user)
        self.assertIn("peças boas", loaded["messages"][0]["content"])
        self.assertIsNone(self.db.obter_conversa_ia(conversation["id"], second_user))

        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ai_knowledge (tipo, conteudo, origem, status_validacao)
                VALUES
                    ('regra', 'Quantidade Produzida é somente peça boa.', 'Manufatura', 'validado'),
                    ('rascunho', 'Não usar ainda.', 'teste', 'rascunho')
                """
            )
            cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
            indexes = {row["indexname"] for row in cursor.fetchall()}
            cursor.execute(
                """
                SELECT conname, pg_get_constraintdef(oid) AS definition
                FROM pg_constraint
                WHERE connamespace = current_schema()::regnamespace
                  AND conrelid IN ('ai_conversations'::regclass, 'ai_messages'::regclass, 'ai_knowledge'::regclass)
                """
            )
            constraints = {row["conname"]: row["definition"] for row in cursor.fetchall()}

        knowledge = self.db.listar_conhecimento_ia_validado()
        self.assertEqual(len(knowledge), 1)
        self.assertIn("peça boa", knowledge[0]["conteudo"])
        self.assertIn("idx_ai_conversations_user_updated", indexes)
        self.assertIn("idx_ai_messages_conversation_created", indexes)
        self.assertIn("idx_ai_knowledge_validation", indexes)
        serialized_constraints = " ".join(constraints.values())
        self.assertIn("FOREIGN KEY (user_id) REFERENCES usuarios", serialized_constraints)
        self.assertIn("FOREIGN KEY (conversation_id) REFERENCES ai_conversations", serialized_constraints)
        self.assertIn("role", serialized_constraints)
        self.assertIn("validado", serialized_constraints)

        self.assertTrue(self.db.excluir_conversa_ia(conversation["id"], first_user))
        self.assertIsNone(self.db.obter_conversa_ia(conversation["id"], first_user))
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS total FROM ai_messages WHERE conversation_id = %s",
                (conversation["id"],),
            )
            self.assertEqual(cursor.fetchone()["total"], 0)

    def test_migration_15_ausente_eh_reaplicada_sem_backfill_produtivo(self):
        user_id = self.db.criar_usuario("Usuário preservado", "senha", "gestor")
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("DROP TABLE report_deliveries")
            cursor.execute("DROP TABLE report_schedules")
            cursor.execute("DROP TABLE messaging_destinations")
            cursor.execute("DROP TABLE generated_reports")
            cursor.execute("DELETE FROM schema_migrations WHERE version = 15")
        # A migration 16 pode já estar registrada. O migrador deve reparar a
        # lacuna 15 sem confundir MAX(version) com o conjunto efetivamente
        # aplicado e sem reexecutar a versão posterior.
        self.assertEqual(self.db.obter_schema_version(), SCHEMA_VERSION)
        self.assertEqual(self.db.create_tables(), SCHEMA_VERSION)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM schema_migrations WHERE version = 15")
            self.assertEqual(cursor.fetchone()["total"], 1)
        self.assertIsNotNone(self.db.obter_usuario_por_id(user_id))
        self.assertEqual(self.db.listar_conversas_ia(user_id), [])
        self.assertTrue(
            all(
                not statement.lstrip().upper().startswith(("UPDATE ", "INSERT ", "DELETE "))
                for statement in AI_ASSISTANT_STATEMENTS
            )
        )
        self.assertTrue(
            all(
                not statement.lstrip().upper().startswith(("UPDATE ", "INSERT ", "DELETE "))
                for statement in INTELLIGENCE_REPORTS_STATEMENTS
            )
        )


if __name__ == "__main__":
    unittest.main()
