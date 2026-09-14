"""Integração ProductionOrder somente em schema isolado de TEST_DATABASE_URL."""

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4
from xml.etree import ElementTree as ET

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database.config import load_postgres_config
from app.database.database import Database
from app.database.schema import SCHEMA_VERSION
from mes.integrations.totvs.errors import TotvsIntegrationError, TotvsTemporalConflictError
from mes.integrations.totvs.mapper import TotvsProductionOrderMapper
from mes.integrations.totvs.models import TotvsActivityClassification
from mes.integrations.totvs.parser import TotvsMessageParser
from mes.integrations.totvs.resource_mapping import TotvsResourceResolver
from mes.integrations.totvs.service import TotvsProductionOrderIngestionService


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "totvs"
PEND = FIXTURES / "pend_productionorder_20260818165346_10796502001.xml"
OK = FIXTURES / "ok_productionorder_20260821103018_1079689c001 1.xml"
WHOIS = FIXTURES / "whois_20260827102117_pcpa109.xml"
REAL_OP = FIXTURES / "ok_productionorder_20260827120232_a9716901001.xml"


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class TotvsPostgresIntegrationTests(unittest.TestCase):
    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "gestor_totvs_test_" + uuid4().hex
        self.admin_dsn = base.dsn
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        isolated_dsn = make_conninfo(base.dsn, options=f"-c search_path={self.schema}")
        self.db = Database(isolated_dsn)
        self.service = TotvsProductionOrderIngestionService(
            self.db,
            enabled=True,
            parser=TotvsMessageParser(),
            mapper=TotvsProductionOrderMapper(
                TotvsResourceResolver(resource_aliases={"LASER": "LASER1"})
            ),
        )

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _rows(self, query, params=()):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def _scalar(self, query, params=()):
        rows = self._rows(query, params)
        return next(iter(rows[0].values()))

    @staticmethod
    def _unique_payload(base_payload: str, source: str, prefix: str) -> str:
        return base_payload.replace(source, f"{prefix}-{uuid4().hex[:10].upper()}")

    def test_migration_16_cria_inbox_metadados_e_data_emissao_sem_falsa_semantica(self):
        self.assertEqual(self.db.obter_schema_version(), SCHEMA_VERSION)
        # A migration 16 é a base do inbox TOTVS; o schema segue evoluindo de
        # forma aditiva (17 acrescentou procedência SigmaNEST ao Corte).
        self.assertGreaterEqual(SCHEMA_VERSION, 16)
        tables = {
            row["table_name"]
            for row in self._rows(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
            )
        }
        self.assertIn("totvs_integration_messages", tables)
        columns = {
            row["column_name"]: row
            for row in self._rows(
                """
                SELECT column_name, is_nullable
                FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = 'catalogo_pcp_ops'
                """
            )
        }
        self.assertEqual(columns["data_emissao"]["is_nullable"], "YES")
        self.assertIn("totvs_unique_id", columns)
        operation_columns = {
            row["column_name"]
            for row in self._rows(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema() AND table_name = 'catalogo_operacoes_op'
                """
            )
        }
        self.assertIn("totvs_activity_id", operation_columns)
        self.assertEqual(self.db.listar_codigos_recursos_totvs(), ())
        self.assertEqual(self.db.listar_setores_recursos_totvs(), ())

    def test_whois_real_registra_diagnostico_sem_tocar_planejamento_ou_execucao(self):
        payload = WHOIS.read_text(encoding="utf-8")
        watched_tables = (
            "catalogo_pcp_ops",
            "catalogo_operacoes_op",
            "apontamentos_operacionais",
            "eventos_apontamento_operador",
            "eventos_estado_recurso",
            "eventos_quantidade_producao",
            "sessoes_recurso",
        )
        before = {
            table: self._scalar(f"SELECT COUNT(*) AS total FROM {table}")
            for table in watched_tables
        }

        outcome = self.service.handle_message(payload)
        self.assertEqual(outcome.transaction, "WhoIs")
        self.assertIsNone(outcome.ingestion)
        root = ET.fromstring(outcome.soap_result)
        self.assertEqual(root.findtext("MessageInformation/Type"), "Response")
        self.assertEqual(root.findtext("MessageInformation/Transaction"), "WHOIS")
        self.assertEqual(
            root.findtext("ResponseMessage/ProcessingInformation/Status"), "OK"
        )

        inbox = self._rows(
            """
            SELECT transaction, entity, event, external_id, status, result_action,
                   company_id, branch_id, source_application,
                   activities_parsed, activities_projected, processed_at
            FROM totvs_integration_messages
            """
        )
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["transaction"], "WhoIs")
        self.assertEqual(inbox[0]["status"], "ignored")
        self.assertEqual(inbox[0]["result_action"], "diagnostic")
        self.assertIsNone(inbox[0]["entity"])
        self.assertIsNone(inbox[0]["event"])
        self.assertIsNone(inbox[0]["external_id"])
        self.assertEqual(inbox[0]["company_id"], "01")
        self.assertEqual(inbox[0]["branch_id"], "010004")
        self.assertEqual(inbox[0]["activities_parsed"], 0)
        self.assertEqual(inbox[0]["activities_projected"], 0)
        self.assertIsNotNone(inbox[0]["processed_at"])

        repeated = self.service.handle_message(payload)
        self.assertEqual(
            ET.fromstring(repeated.soap_result).findtext(
                "ResponseMessage/ProcessingInformation/Status"
            ),
            "OK",
        )
        self.assertTrue(repeated.diagnostic.idempotent)
        self.assertEqual(
            self._scalar("SELECT COUNT(*) AS total FROM totvs_integration_messages"), 1
        )
        after = {
            table: self._scalar(f"SELECT COUNT(*) AS total FROM {table}")
            for table in watched_tables
        }
        self.assertEqual(after, before)

        # O ProductionOrder continua aplicando normalmente depois do WhoIs.
        applied = self.service.handle_message(OK.read_text(encoding="utf-8"))
        self.assertEqual(applied.ingestion.action, "inserted")
        self.assertEqual(
            ET.fromstring(applied.soap_result).findtext(
                "ResponseMessage/ProcessingInformation/Status"
            ),
            "OK",
        )
        self.assertEqual(
            self._scalar("SELECT COUNT(*) AS total FROM catalogo_pcp_ops"),
            before["catalogo_pcp_ops"] + 1,
        )

    def test_op_real_a9716901001_persiste_antes_de_responder_status_ok(self):
        payload = REAL_OP.read_text(encoding="utf-8")
        execution_tables = (
            "apontamentos_operacionais",
            "eventos_apontamento_operador",
            "eventos_estado_recurso",
            "eventos_quantidade_producao",
            "sessoes_recurso",
        )
        before_execution = {
            table: self._scalar(f"SELECT COUNT(*) AS total FROM {table}")
            for table in execution_tables
        }

        outcome = self.service.handle_message(payload)
        self.assertEqual(outcome.transaction, "ProductionOrder")
        self.assertEqual(outcome.ingestion.action, "inserted")
        self.assertEqual(outcome.ingestion.activities_parsed, 5)
        root = ET.fromstring(outcome.soap_result)
        self.assertEqual(root.findtext("MessageInformation/Transaction"), "PRODUCTIONORDER")
        self.assertEqual(
            root.findtext("ResponseMessage/ProcessingInformation/Status"), "OK"
        )
        # O commit da OP acontece antes da resposta: a OP já está consultável.
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM catalogo_pcp_ops WHERE codigo_op = %s",
                ("A9716901001",),
            ),
            1,
        )
        self.assertEqual(
            self._scalar(
                "SELECT status FROM totvs_integration_messages WHERE external_id = %s",
                ("01|010004|A9716901001",),
            ),
            "processed",
        )
        operations = self._rows(
            """
            SELECT numero_operacao, descricao_operacao, codigo_recurso, tipo_setor,
                   totvs_activity_id
            FROM catalogo_operacoes_op
            WHERE codigo_op = %s AND ativo
            ORDER BY ordem, id
            """,
            ("A9716901001",),
        )
        self.assertEqual(
            operations,
            [
                {
                    "numero_operacao": "10",
                    "descricao_operacao": "CORTE",
                    "codigo_recurso": "PLASMA",
                    "tipo_setor": "Corte",
                    "totvs_activity_id": "108761",
                },
                {
                    "numero_operacao": "20",
                    "descricao_operacao": "USINAGEM",
                    "codigo_recurso": "CNC-01",
                    "tipo_setor": "Usinagem",
                    "totvs_activity_id": "160893",
                },
            ],
        )
        self.assertTrue(
            self._scalar(
                "SELECT ativo FROM catalogo_pcp_ops WHERE codigo_op = %s",
                ("A9716901001",),
            )
        )
        self.assertFalse(
            any(
                operation["numero_operacao"] in {"01", "30", "99"}
                for operation in operations
            )
        )
        inbox = self._rows(
            """
            SELECT payload_raw, warnings, activities_parsed, activities_projected
            FROM totvs_integration_messages
            WHERE external_id = %s
            """,
            ("01|010004|A9716901001",),
        )[0]
        self.assertEqual((inbox["activities_parsed"], inbox["activities_projected"]), (5, 2))
        self.assertIn("<ActivityID>108760</ActivityID>", inbox["payload_raw"])
        self.assertIn("<MachineCode>INSPEC</MachineCode>", inbox["payload_raw"])
        self.assertIn("<MachineCode>ALMOX4</MachineCode>", inbox["payload_raw"])
        self.assertEqual(len(inbox["warnings"]), 3)
        self.assertTrue(
            any(
                TotvsActivityClassification.AUTOMATIC_SATISFIED.value in warning
                and "cria apontamento fictício" in warning
                for warning in inbox["warnings"]
            )
        )
        self.assertTrue(
            any(
                TotvsActivityClassification.QUALITY_INSPECTION.value in warning
                and "aba Qualidade" in warning
                for warning in inbox["warnings"]
            )
        )
        # A inspeção existe no catálogo, inativa e sem setor: ela alimenta a aba
        # Qualidade e o outbound canônico, nunca a Tela do Operador.
        self.assertEqual(
            self._rows(
                """
                SELECT numero_operacao, codigo_recurso, tipo_setor, ativo
                FROM catalogo_operacoes_op
                WHERE codigo_op = %s AND inspecao_qualidade IS TRUE
                """,
                ("A9716901001",),
            ),
            [
                {
                    "numero_operacao": "30",
                    "codigo_recurso": "INSPEC",
                    "tipo_setor": None,
                    "ativo": False,
                }
            ],
        )
        self.assertTrue(
            any(
                TotvsActivityClassification.TERMINAL_CONFIRMED.value in warning
                and "não finaliza" in warning
                for warning in inbox["warnings"]
            )
        )

        # Reenvio da mesma mensagem: idempotente, sem duplicar OP nem roteiro.
        operacoes = self._scalar(
            "SELECT COUNT(*) AS total FROM catalogo_operacoes_op WHERE codigo_op = %s AND ativo",
            ("A9716901001",),
        )
        resend = self.service.handle_message(payload)
        self.assertTrue(resend.ingestion.idempotent)
        self.assertEqual(
            ET.fromstring(resend.soap_result).findtext(
                "ResponseMessage/ProcessingInformation/Status"
            ),
            "OK",
        )
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM catalogo_pcp_ops WHERE codigo_op = %s",
                ("A9716901001",),
            ),
            1,
        )
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM catalogo_operacoes_op WHERE codigo_op = %s AND ativo",
                ("A9716901001",),
            ),
            operacoes,
        )
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM totvs_integration_messages WHERE external_id = %s",
                ("01|010004|A9716901001",),
            ),
            1,
        )
        after_execution = {
            table: self._scalar(f"SELECT COUNT(*) AS total FROM {table}")
            for table in execution_tables
        }
        self.assertEqual(after_execution, before_execution)

    def test_regra_exata_libera_jato_em_pintura_sem_promover_montagem(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO catalogo_recursos_pcfactory (
                    codigo, nome, tipo_setor, habilitado, fonte, sincronizado_em
                ) VALUES (%s, %s, %s, TRUE, 'fixture determinística', CURRENT_TIMESTAMP)
                """,
                (
                    ("PINT.L", "Pintura", "Pintura"),
                    ("INSPE2", "Inspeção Pintura", "Pintura"),
                    ("JATO", "Jateamento", None),
                    ("SOLD-CANON", "Solda canônica", "Solda"),
                    ("MONT-01", "Montagem", None),
                ),
            )

        resolver = TotvsResourceResolver(
            known_resource_codes=self.db.listar_codigos_recursos_totvs(),
            known_resource_sectors=self.db.listar_setores_recursos_totvs(),
        )
        result = TotvsProductionOrderMapper(resolver).map(
            TotvsMessageParser().parse(PEND.read_bytes())
        )
        self.assertEqual(
            [
                (
                    operation.numero_operacao,
                    operation.tipo_setor,
                    operation.codigo_recurso,
                )
                for operation in result.operations
                if not operation.marco_terminal
                and not operation.inspecao_qualidade
            ],
            [
                ("10", "Corte", "LASER1"),
                ("20", "Dobra", "DOBRA1"),
                ("40", "Pintura", "PINT.L"),
                ("50", "Pintura", "JATO"),
                ("60", "Pintura", "PINT.L"),
                ("70", "Pintura", "INSPE2"),
            ],
        )
        jateamento = next(
            item for item in result.activity_treatments if item.activity_code == "50"
        )
        self.assertEqual(
            jateamento.classification,
            TotvsActivityClassification.POINTABLE_CONFIRMED,
        )
        self.assertEqual((jateamento.sector, jateamento.resource_code), ("Pintura", "JATO"))
        # A decisão funcional explícita prevalece sobre o tipo_setor ainda
        # nulo no cadastro de TESTE; não há inferência pelo nome JATEAMENTO.
        self.assertNotIn(
            ("JATO", "Pintura"),
            self.db.listar_setores_recursos_totvs(),
        )
        self.assertNotIn(
            ("MONT-01", "Montagem"),
            self.db.listar_setores_recursos_totvs(),
        )

    def test_fixtures_idempotencia_upsert_stale_conflito_e_isolamento_por_op(self):
        pending_payload = PEND.read_text(encoding="utf-8")
        ok_payload = OK.read_text(encoding="utf-8")
        execution_tables = (
            "apontamentos_operacionais",
            "eventos_apontamento_operador",
            "eventos_estado_recurso",
            "eventos_quantidade_producao",
            "sessoes_recurso",
        )
        before_execution = {
            table: self._scalar(f"SELECT COUNT(*) AS total FROM {table}")
            for table in execution_tables
        }

        first = self.service.ingest(pending_payload)
        second = self.service.ingest(ok_payload)
        # O roteiro real repete o posto PINT.L (operações 40 e 60): duas etapas
        # de sequência diferentes, não uma duplicata — 5 operações apontáveis,
        # não 4 (decisão de negócio confirmada em 2026-09-14, ver
        # test_totvs_integration.py::test_mapper_nao_inventa_setor_e_aplica_alias_laser_oficial_exato).
        self.assertEqual((first.action, first.activities_parsed, first.activities_projected), ("inserted", 9, 5))
        self.assertEqual((second.action, second.activities_parsed, second.activities_projected), ("inserted", 4, 1))
        headers = self._rows(
            """
            SELECT codigo_op, quantidade, ativo, data_emissao, totvs_unique_id
            FROM catalogo_pcp_ops ORDER BY codigo_op
            """
        )
        self.assertEqual(len(headers), 2)
        self.assertTrue(all(row["ativo"] for row in headers))
        self.assertTrue(all(row["data_emissao"] is None for row in headers))
        self.assertEqual(
            self._scalar("SELECT COUNT(*) AS total FROM catalogo_operacoes_op WHERE codigo_op = %s AND ativo", ("10796502001",)),
            5,
        )
        self.assertEqual(
            self._scalar("SELECT COUNT(*) AS total FROM catalogo_operacoes_op WHERE codigo_op = %s AND ativo", ("1079689C001",)),
            1,
        )

        duplicate = self.service.ingest(pending_payload)
        self.assertTrue(duplicate.idempotent)
        self.assertEqual(
            self._scalar("SELECT COUNT(*) AS total FROM totvs_integration_messages"),
            2,
        )

        newer = pending_payload.replace(
            "<GeneratedOn>2026-08-18T16:53:46</GeneratedOn>",
            "<GeneratedOn>2026-08-22T16:53:46</GeneratedOn>",
            1,
        ).replace("<Quantity>22</Quantity>", "<Quantity>23</Quantity>", 1)
        updated = self.service.ingest(newer)
        self.assertEqual(updated.action, "updated")
        self.assertEqual(
            self._scalar("SELECT quantidade FROM catalogo_pcp_ops WHERE codigo_op = %s", ("10796502001",)),
            23,
        )

        stale_payload = pending_payload.replace(
            "ABRACADEIRA BRACOS DISCOS",
            "ABRACADEIRA BRACOS DISCOS STALE",
            1,
        )
        stale = self.service.ingest(stale_payload)
        self.assertEqual((stale.status, stale.action), ("ignored", "ignored_stale"))
        self.assertEqual(
            self._scalar("SELECT quantidade FROM catalogo_pcp_ops WHERE codigo_op = %s", ("10796502001",)),
            23,
        )

        conflicting = newer.replace(
            "ABRACADEIRA BRACOS DISCOS",
            "ABRACADEIRA BRACOS DISCOS CONFLITO",
            1,
        )
        with self.assertRaises(TotvsTemporalConflictError):
            self.service.ingest(conflicting)
        self.assertEqual(
            self._scalar(
                "SELECT status FROM totvs_integration_messages WHERE payload_raw = %s",
                (conflicting,),
            ),
            "error",
        )
        # A atualização da OP A não desativou cabeçalho ou roteiro da OP B.
        self.assertTrue(
            self._scalar("SELECT ativo FROM catalogo_pcp_ops WHERE codigo_op = %s", ("1079689C001",))
        )
        self.assertEqual(
            self._scalar("SELECT COUNT(*) AS total FROM catalogo_operacoes_op WHERE codigo_op = %s AND ativo", ("1079689C001",)),
            1,
        )
        after_execution = {
            table: self._scalar(f"SELECT COUNT(*) AS total FROM {table}")
            for table in execution_tables
        }
        self.assertEqual(after_execution, before_execution)

    def test_falha_no_roteiro_faz_rollback_do_cabecalho_e_audita_error(self):
        payload = self._unique_payload(
            OK.read_text(encoding="utf-8"),
            "1079689C001",
            "TEST-ROLLBACK",
        )
        parsed = TotvsMessageParser().parse(payload)
        with patch.object(
            self.db,
            "_replace_totvs_operations_cursor",
            side_effect=RuntimeError("falha injetada depois do cabeçalho"),
        ):
            with self.assertRaises(TotvsIntegrationError):
                self.service.ingest(payload)
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM catalogo_pcp_ops WHERE totvs_unique_id = %s",
                (parsed.external_id,),
            ),
            0,
        )
        audit = self._rows(
            "SELECT status, error_code FROM totvs_integration_messages WHERE external_id = %s",
            (parsed.external_id,),
        )[0]
        self.assertEqual((audit["status"], audit["error_code"]), ("error", "processing_error"))

    def test_concorrencia_da_mesma_mensagem_gera_uma_op_e_um_roteiro(self):
        payload = self._unique_payload(
            OK.read_text(encoding="utf-8"),
            "1079689C001",
            "TEST-CONCURRENT",
        )
        external_id = TotvsMessageParser().parse(payload).external_id
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _item: self.service.ingest(payload), range(2)))
        self.assertEqual(sum(result.idempotent for result in results), 1)
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM catalogo_pcp_ops WHERE totvs_unique_id = %s",
                (external_id,),
            ),
            1,
        )
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM catalogo_operacoes_op WHERE codigo_op = (SELECT codigo_op FROM catalogo_pcp_ops WHERE totvs_unique_id = %s) AND ativo",
                (external_id,),
            ),
            1,
        )
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM totvs_integration_messages WHERE external_id = %s",
                (external_id,),
            ),
            1,
        )


if __name__ == "__main__":
    unittest.main()
