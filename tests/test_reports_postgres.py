"""Integração dos artifacts, agendamentos e entregas somente em schema isolado."""

import os
import unittest
from datetime import datetime, time, timedelta
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.errors import CheckViolation, ForeignKeyViolation

from app.database.config import load_postgres_config
from app.database.database import Database
from app.database.migrations import SCHEMA_VERSION


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class ReportsPostgresTests(unittest.TestCase):
    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "gestor_reports_test_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.admin_dsn = base.dsn
        isolated_dsn = make_conninfo(base.dsn, options=f"-c search_path={self.schema}")
        self.db = Database(isolated_dsn)

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def test_migration_repositorios_constraints_idor_e_utf8(self):
        self.assertEqual(self.db.obter_schema_version(), SCHEMA_VERSION)
        owner = self.db.criar_usuario("Gestor Relatórios", "senha", "gestor")
        other = self.db.criar_usuario("Outro Gestor", "senha", "gestor")
        now = datetime(2026, 8, 26, 10, 0)
        report_id = str(uuid4())
        record = self.db.registrar_relatorio_gerado(
            report_id=report_id,
            created_by=owner,
            report_type="completo",
            period_start=now - timedelta(days=1),
            period_end=now,
            filters={"setor": "Usinagem", "texto": "Produção"},
            filename="gestor_completo.xlsx",
            storage_path="C:/artifacts/server-owned.xlsx",
            status="pronto",
            source="automatico",
            size_bytes=4096,
            worksheet_count=12,
            row_count=81,
            generation_ms=250,
            created_at=now,
            expires_at=now + timedelta(days=7),
            idempotency_key="schedule:1:2026-08-25:2026-08-26",
            generation_metadata={"calculation_policy": "backend_only"},
        )
        self.assertEqual(record["filters"]["texto"], "Produção")
        self.assertIsNone(self.db.obter_relatorio_gerado(report_id, other))
        self.assertEqual(
            self.db.obter_relatorio_por_idempotencia(
                owner, "schedule:1:2026-08-25:2026-08-26"
            )["id"],
            record["id"],
        )

        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO messaging_destinations
                    (user_id, provider, label, destination_ref)
                VALUES (%s, 'telegram', 'Diretoria', '-1000000000000')
                RETURNING id
                """,
                (owner,),
            )
            destination_id = cursor.fetchone()["id"]
        schedule = self.db.criar_agendamento_relatorio(
            created_by=owner,
            name="Fechamento diário",
            report_type="completo",
            frequency="diario",
            filters={"setor": "Usinagem"},
            run_time=time(6, 30),
            timezone="America/Sao_Paulo",
            enabled=True,
            destination_id=destination_id,
            created_at=now,
        )
        self.assertEqual(schedule["name"], "Fechamento diário")
        self.assertEqual(len(self.db.listar_agendamentos_relatorio(owner)), 1)
        delivery = self.db.registrar_entrega_relatorio(
            report_id=report_id,
            requested_by=owner,
            destination_id=destination_id,
            status="enviado",
            attempt=1,
            error_code=None,
            requested_at=now,
            completed_at=now,
            idempotency_key="delivery:unique",
        )
        self.assertEqual(delivery["status"], "enviado")
        self.assertEqual(
            self.db.obter_entrega_relatorio_por_idempotencia("delivery:unique")["id"],
            delivery["id"],
        )

        with self.assertRaises(CheckViolation):
            with self.db.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO generated_reports
                        (id, created_by, report_type, period_start, period_end,
                         filename, storage_path, status, source)
                    VALUES (%s, %s, 'ops', %s, %s, '../escape.xlsx', 'x', 'pronto', 'manual')
                    """,
                    (str(uuid4()), owner, now - timedelta(days=1), now),
                )
        with self.assertRaises(ForeignKeyViolation):
            with self.db.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO report_deliveries
                        (report_id, requested_by, destination_id, status, idempotency_key)
                    VALUES (%s, %s, %s, 'enviado', 'invalid-owner')
                    """,
                    (report_id, 999999999, destination_id),
                )

        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
            indexes = {row["indexname"] for row in cursor.fetchall()}
        self.assertIn("idx_generated_reports_owner_created", indexes)
        self.assertIn("idx_report_schedules_due", indexes)
        self.assertIn("idx_report_deliveries_report", indexes)


if __name__ == "__main__":
    unittest.main()
