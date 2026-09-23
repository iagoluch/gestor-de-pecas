"""Etapa 6 — outbox transacional, retry e confiabilidade do outbound TOTVS.

Duas famílias de teste:

* domínio puro (backoff, classificação de erro, planejamento do enqueue), sem
  banco e sem rede;
* arquitetura real em PostgreSQL, em schema isolado criado por teste, provando
  atomicidade, concorrência, recuperação e reprocessamento.

Nenhum teste toca o TOTVS: o gateway é sempre um dublê determinístico.
"""

from datetime import datetime, timedelta
from decimal import Decimal
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database.config import load_postgres_config
from app.database.database import Database
from app.database.errors import DatabaseIntegrityError
from app.database.schema import SCHEMA_VERSION
from backend.integrations.totvs_wspcp import (
    TotvsWspcpClient,
    WspcpClientConfig,
    WspcpSendResult,
)
from mes.integrations.totvs.mapper import TotvsProductionOrderMapper
from mes.integrations.totvs.outbound_enqueue import (
    EVENT_PRODUCTION_APPOINTMENT,
    EVENT_PRODUCTION_APPOINTMENT_TERMINAL,
    EVENT_PRODUCTION_APPOINTMENT_ZERO,
    EVENT_STOP_REPORT,
    OutboundEnqueueConfig,
    load_outbound_enqueue_config,
    plan_execution_event,
    plan_terminal_milestone,
)
from mes.integrations.totvs.outbox import (
    BACKOFF_SECONDS,
    DeliveryAttempt,
    DeliveryClass,
    OutboxStatus,
    backoff_delay_seconds,
    classify_attempt,
    next_attempt_at,
)
from mes.integrations.totvs.parser import TotvsMessageParser
from mes.integrations.totvs.resource_mapping import TotvsResourceResolver
from mes.integrations.totvs.service import TotvsProductionOrderIngestionService
from mes.services.totvs_outbox_admin import TotvsOutboxAdminService
from mes.services.totvs_outbox_worker import TotvsOutboxWorker
from tests.test_totvs_outbound import canonical_event, terminal_milestone


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "totvs"
REAL_OP = FIXTURES / "ok_productionorder_20260827120232_a9716901001.xml"
WHOIS = FIXTURES / "whois_20260827102117_pcpa109.xml"

ACK_OK = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
    "<SOAP-ENV:Body><RECEIVEMESSAGERESPONSE><RECEIVEMESSAGERESULT>"
    "&lt;TOTVSMessage&gt;&lt;ResponseMessage&gt;&lt;ProcessingInformation&gt;"
    "&lt;Status&gt;OK&lt;/Status&gt;&lt;/ProcessingInformation&gt;"
    "&lt;ReturnContent&gt;&lt;ListOfInternalId&gt;&lt;InternalId&gt;"
    "&lt;Name&gt;ID&lt;/Name&gt;&lt;Destination&gt;783199&lt;/Destination&gt;"
    "&lt;/InternalId&gt;&lt;/ListOfInternalId&gt;&lt;/ReturnContent&gt;"
    "&lt;/ResponseMessage&gt;&lt;/TOTVSMessage&gt;"
    "</RECEIVEMESSAGERESULT></RECEIVEMESSAGERESPONSE></SOAP-ENV:Body></SOAP-ENV:Envelope>"
)

ACK_FUNCTIONAL_ERROR = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
    "<SOAP-ENV:Body><RECEIVEMESSAGERESPONSE><RECEIVEMESSAGERESULT>"
    "&lt;TOTVSMessage&gt;&lt;ResponseMessage&gt;&lt;ProcessingInformation&gt;"
    "&lt;Status&gt;ERROR&lt;/Status&gt;&lt;/ProcessingInformation&gt;"
    '&lt;Message type="ERROR" code="1"&gt;A680OPTOT Operacao ja totalizada'
    "&lt;/Message&gt;&lt;/ResponseMessage&gt;&lt;/TOTVSMessage&gt;"
    "</RECEIVEMESSAGERESULT></RECEIVEMESSAGERESPONSE></SOAP-ENV:Body></SOAP-ENV:Envelope>"
)


def _client(handler) -> TotvsWspcpClient:
    return TotvsWspcpClient(
        WspcpClientConfig(endpoint="https://teste-outbox/WSPCP.apw"),
        transport=httpx.MockTransport(handler),
    )


class _RecordingGateway:
    """Dublê que registra os XML transmitidos, sem rede."""

    def __init__(self, results):
        self._results = list(results)
        self.sent = []

    def send_result(self, message):
        self.sent.append(message)
        result = self._results[min(len(self.sent) - 1, len(self._results) - 1)]
        if isinstance(result, Exception):
            raise result
        return result


OK_RESULT = WspcpSendResult(
    ack=_client(lambda request: httpx.Response(200, text=ACK_OK)),
)


# ----------------------------------------------------------------------
# Domínio puro
# ----------------------------------------------------------------------
class OutboxBackoffTests(unittest.TestCase):
    def test_backoff_cresce_e_satura_no_ultimo_degrau(self):
        self.assertEqual(
            [backoff_delay_seconds(n) for n in range(1, 8)],
            [60, 120, 300, 600, 1800, 3600, 3600],
        )
        self.assertEqual(BACKOFF_SECONDS[0], 60)

    def test_next_attempt_at_e_deterministico_e_sem_microssegundos(self):
        agora = datetime(2026, 9, 1, 10, 0, 0, 123456)
        self.assertEqual(
            next_attempt_at(agora, 3), datetime(2026, 9, 1, 10, 5, 0)
        )


class OutboxClassificationTests(unittest.TestCase):
    def test_ack_ok_e_sucesso(self):
        decision = classify_attempt(DeliveryAttempt(succeeded=True), attempts=1)
        self.assertIs(decision.status, OutboxStatus.SENT)
        self.assertIs(decision.delivery_class, DeliveryClass.SUCCESS)

    def test_timeout_e_transitorio_com_retry(self):
        decision = classify_attempt(
            DeliveryAttempt(transport_failure="timeout"), attempts=1
        )
        self.assertIs(decision.status, OutboxStatus.RETRY)
        self.assertIs(decision.delivery_class, DeliveryClass.TRANSIENT)
        self.assertTrue(decision.retryable)

    def test_503_e_transitorio_e_502_504_tambem(self):
        for status in (502, 503, 504):
            decision = classify_attempt(
                DeliveryAttempt(http_status=status), attempts=1
            )
            self.assertIs(decision.status, OutboxStatus.RETRY, status)
            self.assertIs(decision.delivery_class, DeliveryClass.TRANSIENT, status)

    def test_transitorio_para_ao_esgotar_tentativas(self):
        decision = classify_attempt(
            DeliveryAttempt(http_status=503), attempts=12, max_attempts=12
        )
        self.assertIs(decision.status, OutboxStatus.ERROR)
        self.assertFalse(decision.retryable)

    def test_ack_funcional_error_nao_entra_em_retry_infinito(self):
        decision = classify_attempt(
            DeliveryAttempt(http_status=200, ack_status="ERROR", error_message="A680OPTOT"),
            attempts=1,
        )
        self.assertIs(decision.status, OutboxStatus.ERROR)
        self.assertIs(decision.delivery_class, DeliveryClass.FUNCTIONAL)
        self.assertFalse(decision.retryable)

    def test_colisao_de_id_interno_do_totvs_e_transitoria_nao_funcional(self):
        # Achado real em 16/09/2026 (teste em lote de 10 OPs): o WSPCP recusa
        # com ACK Status=ERROR uma colisão de chave única na própria tabela
        # interna dele (SMO010/MO_IDAPON), sem relação com o dado enviado.
        # Reenviar tende a gerar um ID novo e ter sucesso — não é rejeição de
        # negócio como "sem saldo" ou "OP já totalizada".
        mensagem = (
            "1 - SMO010: DB error (Insert): -37 File: SMO010 - Error : 2601 "
            "(23000) (RC=-1) - [Microsoft][ODBC Driver 13 for SQL Server]"
            "[SQL Server]Cannot insert duplicate key row in object "
            "'dbo.SMO010' with unique index 'SMO010_UNQ'."
        )
        decision = classify_attempt(
            DeliveryAttempt(http_status=200, ack_status="ERROR", error_message=mensagem),
            attempts=1,
        )
        self.assertIs(decision.status, OutboxStatus.RETRY)
        self.assertIs(decision.delivery_class, DeliveryClass.TRANSIENT)
        self.assertTrue(decision.retryable)

    def test_colisao_de_id_interno_para_ao_esgotar_tentativas(self):
        decision = classify_attempt(
            DeliveryAttempt(
                http_status=200,
                ack_status="ERROR",
                error_message="SMO010: duplicate key row",
            ),
            attempts=12,
            max_attempts=12,
        )
        self.assertIs(decision.status, OutboxStatus.ERROR)
        self.assertFalse(decision.retryable)

    def test_401_e_403_tem_politica_limitada_e_identificada(self):
        for status in (401, 403):
            primeira = classify_attempt(
                DeliveryAttempt(http_status=status), attempts=1
            )
            self.assertIs(primeira.status, OutboxStatus.RETRY, status)
            self.assertIs(primeira.delivery_class, DeliveryClass.AUTHENTICATION, status)
            ultima = classify_attempt(
                DeliveryAttempt(http_status=status), attempts=3
            )
            self.assertIs(ultima.status, OutboxStatus.ERROR, status)

    def test_fault_de_autenticacao_em_http_500_nao_vira_indisponibilidade(self):
        # O WSPCP TESTE responde credencial inválida com HTTP 500 + Fault
        # AUTHENTICATION. Sem essa leitura, senha errada entraria em retry longo.
        decision = classify_attempt(
            DeliveryAttempt(
                http_status=500,
                soap_fault="WSPCP retornou SOAP Fault: AUTHENTICATION: USER NOT AUTHORIZED",
            ),
            attempts=1,
        )
        self.assertIs(decision.delivery_class, DeliveryClass.AUTHENTICATION)

    def test_http_200_sem_ack_legivel_nao_gera_nova_identidade(self):
        decision = classify_attempt(
            DeliveryAttempt(http_status=200, error_code="invalid_totvs_contract"),
            attempts=1,
        )
        self.assertIs(decision.delivery_class, DeliveryClass.PROTOCOL)
        self.assertIs(decision.status, OutboxStatus.RETRY)


class OutboxPlannerTests(unittest.TestCase):
    CONFIG = OutboundEnqueueConfig(enabled=True)

    def test_parcial_gera_production_appointment(self):
        requests = plan_execution_event(canonical_event(), config=self.CONFIG)
        self.assertEqual([item.event_type for item in requests], [EVENT_PRODUCTION_APPOINTMENT])
        self.assertIn("<ApprovedQuantity>2</ApprovedQuantity>", requests[0].payload_xml)
        self.assertFalse(requests[0].blocked)

    def test_outbox_desabilitada_nao_planeja_nada(self):
        self.assertEqual(plan_execution_event(canonical_event(), config=OutboundEnqueueConfig()), [])

    def test_op_sem_identidade_totvs_nao_entra_na_fila(self):
        evento = canonical_event(company_id="", branch_id="")
        self.assertEqual(plan_execution_event(evento, config=self.CONFIG), [])

    def test_op_sintetica_soak_nao_entra_mesmo_com_identidade_totvs(self):
        evento = canonical_event(
            production_order="SOAK1538010001",
            company_id="01",
            branch_id="010004",
        )
        self.assertEqual(plan_execution_event(evento, config=self.CONFIG), [])

    def test_prefixo_sintetico_adicional_e_configuravel_sem_bloquear_op_real(self):
        config = load_outbound_enqueue_config(
            {
                "GESTOR_TOTVS_OUTBOX_ENABLED": "true",
                "GESTOR_TOTVS_OUTBOX_SYNTHETIC_OP_PREFIXES": " SIMREAL, teste- ",
            }
        )
        self.assertEqual(
            plan_execution_event(
                canonical_event(production_order="simreal0001"), config=config
            ),
            [],
        )
        self.assertEqual(
            plan_execution_event(
                canonical_event(production_order="TESTE-0001"), config=config
            ),
            [],
        )
        real = plan_execution_event(
            canonical_event(production_order="A9717101001"), config=config
        )
        self.assertEqual(
            [item.event_type for item in real], [EVENT_PRODUCTION_APPOINTMENT]
        )

    def test_parada_aberta_nao_entra_na_fila(self):
        parada = canonical_event(
            state="parada",
            good_quantity=Decimal("0"),
            previous_state="producao",
        )
        self.assertEqual(plan_execution_event(parada, config=self.CONFIG), [])

    def test_retomada_apos_parada_gera_stop_report_fechado(self):
        config = OutboundEnqueueConfig(
            enabled=True, stop_reason_codes={"MANUTENCAO PREVENTIVA": "0010"}
        )
        retomada = canonical_event(
            state="producao",
            good_quantity=Decimal("0"),
            previous_state="parada",
            previous_reason="Manutencao preventiva",
            previous_event_time=canonical_event().event_time - timedelta(minutes=30),
        )
        requests = plan_execution_event(retomada, config=config)
        self.assertEqual([item.event_type for item in requests], [EVENT_STOP_REPORT])
        self.assertIn("<StopReasonCode>0010</StopReasonCode>", requests[0].payload_xml)
        self.assertIn("<StartDateTime>", requests[0].payload_xml)
        self.assertIn("<EndDateTime>", requests[0].payload_xml)

    def test_parada_sem_codigo_totvs_fica_visivel_como_erro_bloqueado(self):
        retomada = canonical_event(
            state="producao",
            good_quantity=Decimal("0"),
            previous_state="parada",
            previous_reason="Motivo sem cadastro",
            previous_event_time=canonical_event().event_time - timedelta(minutes=30),
        )
        request = plan_execution_event(retomada, config=self.CONFIG)[0]
        self.assertTrue(request.blocked)
        self.assertIs(request.status, OutboxStatus.ERROR)
        self.assertEqual(request.error_code, "stop_reason_code_nao_configurado")

    def test_retrabalho_continua_bloqueado_e_nao_vira_mensagem(self):
        evento = canonical_event(
            state="parcial",
            good_quantity=Decimal("0"),
            rework_quantity=Decimal("3"),
        )
        self.assertEqual(plan_execution_event(evento, config=self.CONFIG), [])

    def test_refugo_exige_codigo_totvs_e_nao_vira_peca_boa(self):
        evento = canonical_event(
            state="parcial",
            good_quantity=Decimal("4"),
            scrap_quantity=Decimal("1"),
            event_reason="RESSECAMENTO",
        )
        bloqueado = plan_execution_event(evento, config=self.CONFIG)[0]
        self.assertTrue(bloqueado.blocked)
        config = OutboundEnqueueConfig(enabled=True, waste_codes={"RESSECAMENTO": "RP"})
        request = plan_execution_event(evento, config=config)[0]
        self.assertIn("<ApprovedQuantity>4</ApprovedQuantity>", request.payload_xml)
        self.assertIn("<ScrapQuantity>1</ScrapQuantity>", request.payload_xml)
        self.assertIn("<ReportQuantity>5</ReportQuantity>", request.payload_xml)
        self.assertIn("<WasteCode>RP</WasteCode>", request.payload_xml)

    def test_refugo_da_primeira_peca_entra_na_mesma_outbox_canonica(self):
        event = canonical_event(
            state="primeira_peca_refugo",
            good_quantity=Decimal("0"),
            scrap_quantity=Decimal("1"),
            event_reason="REFUGO DA PRIMEIRA PEÇA",
        )
        config = OutboundEnqueueConfig(
            enabled=True, waste_codes={"REFUGO DA PRIMEIRA PEÇA": "RP"}
        )
        requests = plan_execution_event(event, config=config)

        self.assertEqual([item.event_type for item in requests], [EVENT_PRODUCTION_APPOINTMENT])
        self.assertIn("<ApprovedQuantity>0</ApprovedQuantity>", requests[0].payload_xml)
        self.assertIn("<ScrapQuantity>1</ScrapQuantity>", requests[0].payload_xml)

    def test_inicio_com_quantidade_zero_e_opt_in(self):
        inicio = canonical_event(
            state="producao",
            good_quantity=Decimal("0"),
            previous_state="fila",
        )
        self.assertEqual(plan_execution_event(inicio, config=self.CONFIG), [])
        config = OutboundEnqueueConfig(enabled=True, emit_zero_quantity_start=True)
        request = plan_execution_event(inicio, config=config)[0]
        self.assertEqual(request.event_type, EVENT_PRODUCTION_APPOINTMENT_ZERO)
        self.assertIn("<ReportQuantity>0</ReportQuantity>", request.payload_xml)

    def test_marco_terminal_so_entra_com_execucao_concluida(self):
        aberto = terminal_milestone(concluded_operations=1, open_operations=("20",))
        self.assertEqual(plan_terminal_milestone(aberto, config=self.CONFIG), [])
        pronto = terminal_milestone()
        request = plan_terminal_milestone(pronto, config=self.CONFIG)[0]
        self.assertEqual(request.event_type, EVENT_PRODUCTION_APPOINTMENT_TERMINAL)
        self.assertIn("<ActivityCode>99</ActivityCode>", request.payload_xml)
        self.assertIn("<CloseOperation>true</CloseOperation>", request.payload_xml)

    def test_marco_terminal_sintetico_soak_nao_entra_na_fila(self):
        pronto = terminal_milestone(production_order="SOAK1538010001")
        self.assertEqual(plan_terminal_milestone(pronto, config=self.CONFIG), [])

    def test_configuracao_vem_do_ambiente_sem_nome_de_banco(self):
        config = load_outbound_enqueue_config(
            {
                "GESTOR_TOTVS_OUTBOX_ENABLED": "true",
                "GESTOR_TOTVS_OUTBOUND_WASTE_CODE_MAP_JSON": '{"quebra": "RP"}',
                "GESTOR_TOTVS_OUTBOUND_DEFAULT_STOP_REASON_CODE": "0018",
            }
        )
        self.assertTrue(config.enabled)
        self.assertEqual(config.waste_codes, {"QUEBRA": "RP"})
        self.assertEqual(config.default_stop_reason_code, "0018")
        self.assertEqual(config.additional_synthetic_order_prefixes, ())
        self.assertFalse(load_outbound_enqueue_config({}).enabled)


# ----------------------------------------------------------------------
# Arquitetura real em PostgreSQL
# ----------------------------------------------------------------------
@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class TotvsOutboxPostgresTests(unittest.TestCase):
    """Cada teste roda em um schema próprio, criado e destruído no setUp/tearDown."""

    CONFIG = OutboundEnqueueConfig(
        enabled=True,
        stop_reason_codes={"MANUTENCAO PREVENTIVA": "0010"},
        waste_codes={"RISCO NA PECA": "RP"},
    )

    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "gestor_outbox_test_" + uuid4().hex
        self.admin_dsn = base.dsn
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.dsn = make_conninfo(base.dsn, options=f"-c search_path={self.schema}")
        self.db = Database(self.dsn, totvs_outbox_config=self.CONFIG)
        self._seed_production_order()

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    # -- fixtures ------------------------------------------------------
    def _seed_production_order(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO catalogo_recursos_pcfactory (
                    codigo, nome, tipo_setor, habilitado, fonte, sincronizado_em
                ) VALUES (%s, %s, %s, TRUE, 'fixture determinística', CURRENT_TIMESTAMP)
                """,
                (
                    ("PLASMA", "Plasma", "Corte"),
                    ("CNC-01", "Centro CNC", "Usinagem"),
                ),
            )
        resolver = TotvsResourceResolver(
            known_resource_codes=self.db.listar_codigos_recursos_totvs(),
            known_resource_sectors=self.db.listar_setores_recursos_totvs(),
        )
        self.ingestion = TotvsProductionOrderIngestionService(
            self.db,
            enabled=True,
            parser=TotvsMessageParser(),
            mapper=TotvsProductionOrderMapper(resolver),
        )
        self.ingestion.ingest(REAL_OP.read_text(encoding="utf-8"))
        self.op = "A9716901001"

    def _rows(self, query, params=()):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def _scalar(self, query, params=()):
        return next(iter(self._rows(query, params)[0].values()))

    def _operation(self, numero):
        return self._rows(
            "SELECT * FROM catalogo_operacoes_op WHERE codigo_op = %s AND numero_operacao = %s",
            (self.op, numero),
        )[0]

    def _queue(self, numero, *, quantidade=10):
        operation = self._operation(numero)
        return self.db.enfileirar_apontamento_operacional(
            self.op,
            "PNT002002003",
            None,
            operation["tipo_setor"],
            operation["codigo_recurso"],
            "PLANEJAMENTO",
            quantidade=quantidade,
            operacao={
                "id": operation["id"],
                "numero_operacao": operation["numero_operacao"],
                "codigo_recurso": operation["codigo_recurso"],
                "produto_codigo": "PNT002002003",
                "produto_descricao": "BRACO ARTICULACAO",
            },
        )

    def _transition(self, apontamento_id, estado, **kwargs):
        return self.db.transicionar_apontamento_operador(
            apontamento_id, estado, "OPERADOR-TESTE", **kwargs
        )

    def _outbox(self, **filters):
        return self.db.listar_itens_outbound_totvs(limit=100, **filters)

    def _make_due(self, item_id=None):
        """Antecipa o backoff sem depender do relógio do servidor PostgreSQL."""

        query = "UPDATE totvs_outbox SET next_attempt_at = %s"
        params = [self.db._now()]
        if item_id is not None:
            query += " WHERE id = %s"
            params.append(item_id)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)

    def _produce_and_finish(self, numero, *, boas, quantidade=None, refugo=0):
        card = self._queue(numero, quantidade=quantidade or boas)
        self._transition(card["id"], "producao")
        return self._transition(
            card["id"],
            "finalizado",
            quantidade_boa=boas,
            quantidade_refugo=refugo,
        )

    # -- 1/2: garantia transacional -----------------------------------
    def test_migration_19_cria_outbox_com_chave_unica_e_historico(self):
        self.assertEqual(self.db.obter_schema_version(), SCHEMA_VERSION)
        self.assertGreaterEqual(SCHEMA_VERSION, 19)
        tables = {
            row["table_name"]
            for row in self._rows(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
            )
        }
        self.assertIn("totvs_outbox", tables)
        self.assertIn("totvs_outbox_attempts", tables)
        constraints = {
            row["constraint_name"]
            for row in self._rows(
                """
                SELECT constraint_name FROM information_schema.table_constraints
                WHERE table_schema = current_schema() AND table_name = 'totvs_outbox'
                """
            )
        }
        # A proteção contra duplicata é do banco, não apenas de Python.
        self.assertIn("uq_totvs_outbox_idempotency_key", constraints)

    def test_evento_e_outbox_nascem_no_mesmo_commit(self):
        self._produce_and_finish("10", boas=10)
        eventos = self._rows(
            """
            SELECT e.id, e.estado FROM eventos_apontamento_operador e
            JOIN apontamentos_operacionais a ON a.id = e.apontamento_id
            WHERE a.op = %s AND e.estado = 'finalizado'
            """,
            (self.op,),
        )
        self.assertEqual(len(eventos), 1)
        itens = self._outbox()
        self.assertTrue(itens)
        appointment = next(
            item for item in itens if item["event_type"] == EVENT_PRODUCTION_APPOINTMENT
        )
        self.assertEqual(appointment["canonical_event_id"], eventos[0]["id"])
        self.assertEqual(appointment["status"], OutboxStatus.PENDING.value)
        # O item já nasce commitado com o fato: nenhuma segunda transação.
        self.assertIsNotNone(appointment["payload_xml"])

    def test_rollback_do_evento_tambem_remove_o_item_da_outbox(self):
        card = self._queue("10")
        self._transition(card["id"], "producao")
        before = self._scalar("SELECT COUNT(*) AS total FROM totvs_outbox")

        def explode(_self, connection, action, row):
            if action == "finalizado":
                raise RuntimeError("falha forçada depois do fato canônico")

        with patch.object(Database, "_after_appointment_transition", explode):
            with self.assertRaises(RuntimeError):
                self._transition(card["id"], "finalizado", quantidade_boa=10)
        self.assertEqual(
            self._scalar("SELECT COUNT(*) AS total FROM totvs_outbox"), before
        )
        self.assertEqual(
            self._scalar(
                """
                SELECT COUNT(*) AS total FROM eventos_apontamento_operador e
                JOIN apontamentos_operacionais a ON a.id = e.apontamento_id
                WHERE a.op = %s AND e.estado = 'finalizado'
                """,
                (self.op,),
            ),
            0,
        )

    def _appointment(self):
        return self._rows(
            "SELECT * FROM apontamentos_operacionais WHERE op = %s AND numero_operacao = '10'",
            (self.op,),
        )[0]

    def _facts_snapshot(self):
        """Retrato das tabelas canônicas envolvidas em uma transição."""

        return {
            table: self._scalar(f"SELECT COUNT(*) AS total FROM {table}")
            for table in (
                "apontamentos_operacionais",
                "eventos_apontamento_operador",
                "eventos_quantidade_producao",
                "eventos_estado_recurso",
                "historico",
                "totvs_outbox",
                "totvs_outbox_attempts",
            )
        }

    def test_falha_ao_persistir_a_outbox_derruba_a_transacao_inteira(self):
        """A obrigação de integração é parte do fato, não um efeito colateral.

        O ``INSERT`` na ``totvs_outbox`` é quebrado no nível do PostgreSQL — a
        tabela deixa de existir para a transação. Não é um mock do código do
        Gestor: é a própria persistência falhando, que é o cenário que não pode
        terminar em "apontamento commitado + outbox inexistente".
        """

        card = self._queue("10")
        self._transition(card["id"], "producao")
        antes = self._facts_snapshot()
        estado_antes = self._appointment()

        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("ALTER TABLE totvs_outbox RENAME TO totvs_outbox_indisponivel")
        try:
            with self.assertRaises(Exception) as capturado:
                self._transition(card["id"], "finalizado", quantidade_boa=10)
            self.assertNotIsInstance(capturado.exception, AssertionError)
        finally:
            with self.db.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE totvs_outbox_indisponivel RENAME TO totvs_outbox"
                )

        # Nada do fato canônico sobreviveu: nem apontamento, nem evento, nem
        # quantidade, nem estado, nem histórico, nem outbox parcial.
        self.assertEqual(self._facts_snapshot(), antes)
        depois = self._appointment()
        self.assertEqual(depois["status"], estado_antes["status"])
        self.assertEqual(depois["quantidade_boa"], estado_antes["quantidade_boa"])
        self.assertEqual(depois["data_fim"], estado_antes["data_fim"])
        self.assertEqual(
            self._scalar(
                """
                SELECT COUNT(*) AS total FROM eventos_apontamento_operador e
                JOIN apontamentos_operacionais a ON a.id = e.apontamento_id
                WHERE a.op = %s AND e.estado IN ('finalizado', 'parcial')
                """,
                (self.op,),
            ),
            0,
        )

    def test_conflito_sem_obrigacao_registrada_tambem_derruba_a_transacao(self):
        """``ON CONFLICT DO NOTHING`` nunca pode virar "obrigação ausente".

        Se o INSERT não gravou e a chave também não existe, o Gestor não tem
        como afirmar que a obrigação está registrada — e reverte tudo em vez de
        commitar um apontamento órfão.
        """

        card = self._queue("10")
        self._transition(card["id"], "producao")
        antes = self._facts_snapshot()

        with patch.object(
            Database, "enfileirar_outbound_totvs_tx", lambda *args, **kwargs: None
        ):
            with self.assertRaises(DatabaseIntegrityError):
                self._transition(card["id"], "finalizado", quantidade_boa=10)
        self.assertEqual(self._facts_snapshot(), antes)

    def test_sem_outbox_habilitada_a_transicao_segue_sem_obrigacao(self):
        """Outbox desligada não cria obrigação, então não há o que perder."""

        desligada = Database(
            self.dsn, auto_migrate=False, totvs_outbox_config=OutboundEnqueueConfig()
        )
        self.db.close()
        self.db = desligada
        card = self._queue("10")
        self._transition(card["id"], "producao")
        row = self._transition(card["id"], "finalizado", quantidade_boa=10)
        self.assertEqual(row["status"], "Finalizado")
        self.assertEqual(self._outbox(), [])

    # -- 3/4: operador nunca depende do TOTVS -------------------------
    def test_fluxo_do_operador_nao_abre_conexao_http_com_o_wspcp(self):
        def proibido(*args, **kwargs):
            raise AssertionError("O caminho do operador não pode falar com o WSPCP.")

        with patch.object(httpx, "Client", proibido):
            row = self._produce_and_finish("10", boas=10)
        self.assertEqual(row["status"], "Finalizado")
        self.assertTrue(self._outbox(status=OutboxStatus.PENDING))

    def test_totvs_offline_nao_impede_commit_local_e_deixa_retry(self):
        self._produce_and_finish("10", boas=10)
        gateway = _RecordingGateway(
            [
                WspcpSendResult(
                    transport_failure="conexao_recusada",
                    error_code="conexao_recusada",
                    error_message="Falha de comunicação com WSPCP: connection refused",
                )
            ]
        )
        worker = TotvsOutboxWorker(self.db, gateway=gateway, worker_name="w-offline")
        cycle = worker.run_once()
        self.assertGreaterEqual(cycle.reserved, 1)
        self.assertEqual(cycle.sent, 0)
        self.assertEqual(cycle.retried, cycle.reserved)
        # O apontamento local continua íntegro.
        self.assertEqual(
            self._scalar(
                "SELECT status FROM apontamentos_operacionais WHERE op = %s AND numero_operacao = '10'",
                (self.op,),
            ),
            "Finalizado",
        )
        item = self._outbox(status=OutboxStatus.RETRY)[0]
        self.assertEqual(item["last_delivery_class"], DeliveryClass.TRANSIENT.value)
        self.assertEqual(item["last_error_code"], "conexao_recusada")

    # -- 5/9: ciclo feliz ---------------------------------------------
    def test_pending_vira_sending_e_depois_sent_com_internal_id(self):
        self._produce_and_finish("10", boas=10)
        pendente = self._outbox(status=OutboxStatus.PENDING)[0]
        gateway = _RecordingGateway([_client(lambda r: httpx.Response(200, text=ACK_OK))])

        reservados = self.db.reservar_lote_outbound_totvs(worker="w1")
        self.assertEqual([item["status"] for item in reservados], [OutboxStatus.SENDING.value])
        self.assertEqual(reservados[0]["attempts"], 1)
        self.assertIsNotNone(reservados[0]["lease_expires_at"])

        worker = TotvsOutboxWorker(
            self.db,
            gateway=_client(lambda r: httpx.Response(200, text=ACK_OK)),
            worker_name="w1",
        )
        final = worker.deliver(reservados[0])
        self.assertEqual(final["status"], OutboxStatus.SENT.value)
        self.assertEqual(final["internal_id"], "783199")
        self.assertEqual(final["last_ack_status"], "OK")
        self.assertIsNotNone(final["sent_at"])
        self.assertIsNone(final["lease_expires_at"])
        self.assertEqual(final["idempotency_key"], pendente["idempotency_key"])
        historico = self.db.listar_tentativas_outbound_totvs(final["id"])
        self.assertEqual([item["attempt_number"] for item in historico], [1])
        self.assertEqual(historico[0]["internal_id"], "783199")
        del gateway

    def test_payload_transmitido_e_exatamente_o_persistido_no_enqueue(self):
        self._produce_and_finish("10", boas=10)
        item = self._outbox(status=OutboxStatus.PENDING)[0]
        enviados = []

        def handler(request):
            enviados.append(request.content.decode("utf-8"))
            return httpx.Response(200, text=ACK_OK)

        TotvsOutboxWorker(self.db, gateway=_client(handler), worker_name="w1").run_once()
        self.assertIn(item["payload_xml"], enviados[0])

    # -- 6/7/8/10: falhas e idempotência ------------------------------
    def _run_worker_with(self, handler, *, worker_name="w1"):
        worker = TotvsOutboxWorker(self.db, gateway=_client(handler), worker_name=worker_name)
        return worker.run_once()

    def test_timeout_volta_para_retry_com_a_mesma_chave(self):
        self._produce_and_finish("10", boas=10)
        antes = self._outbox(status=OutboxStatus.PENDING)[0]

        def timeout(request):
            raise httpx.ReadTimeout("tempo esgotado", request=request)

        self._run_worker_with(timeout)
        depois = self.db.buscar_item_outbound_totvs(antes["id"])
        self.assertEqual(depois["status"], OutboxStatus.RETRY.value)
        self.assertEqual(depois["idempotency_key"], antes["idempotency_key"])
        self.assertEqual(depois["payload_xml"], antes["payload_xml"])
        self.assertEqual(depois["last_error_code"], "timeout")
        self.assertEqual(depois["attempts"], 1)
        self.assertGreater(depois["next_attempt_at"], depois["last_attempt_at"])

    def test_503_volta_para_retry_e_agenda_backoff_crescente(self):
        self._produce_and_finish("10", boas=10)
        item_id = self._outbox()[0]["id"]
        for esperado, atraso in enumerate(BACKOFF_SECONDS[:3], start=1):
            self._make_due(item_id)
            self._run_worker_with(lambda r: httpx.Response(503, text="indisponivel"))
            item = self.db.buscar_item_outbound_totvs(item_id)
            self.assertEqual(item["status"], OutboxStatus.RETRY.value)
            self.assertEqual(item["attempts"], esperado)
            self.assertEqual(
                item["next_attempt_at"] - item["last_attempt_at"],
                timedelta(seconds=atraso),
            )
        historico = self.db.listar_tentativas_outbound_totvs(item_id)
        self.assertEqual([row["attempt_number"] for row in historico], [1, 2, 3])
        self.assertTrue(all(row["http_status"] == 503 for row in historico))

    def test_ack_funcional_error_vira_error_sem_retry_infinito(self):
        self._produce_and_finish("10", boas=10)
        item_id = self._outbox()[0]["id"]
        self._run_worker_with(lambda r: httpx.Response(200, text=ACK_FUNCTIONAL_ERROR))
        item = self.db.buscar_item_outbound_totvs(item_id)
        self.assertEqual(item["status"], OutboxStatus.ERROR.value)
        self.assertEqual(item["last_ack_status"], "ERROR")
        self.assertEqual(item["last_delivery_class"], DeliveryClass.FUNCTIONAL.value)
        self.assertIn("A680OPTOT", item["last_error_message"])
        # Um novo ciclo não reserva o item recusado.
        self.assertEqual(self._run_worker_with(lambda r: httpx.Response(200)).reserved, 0)

    # -- 11: concorrência ---------------------------------------------
    def test_dois_workers_simultaneos_nao_reservam_a_mesma_linha(self):
        self._produce_and_finish("10", boas=10)
        self.assertEqual(len(self._outbox(status=OutboxStatus.PENDING)), 1)
        resultados = []
        barreira = threading.Barrier(2)

        def reservar(nome):
            outra = Database(self.dsn, auto_migrate=False, totvs_outbox_config=self.CONFIG)
            try:
                barreira.wait(timeout=10)
                resultados.append(
                    [item["id"] for item in outra.reservar_lote_outbound_totvs(worker=nome)]
                )
            finally:
                outra.close()

        threads = [threading.Thread(target=reservar, args=(f"w{n}",)) for n in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        reservados = [item for lote in resultados for item in lote]
        self.assertEqual(len(reservados), 1)
        self.assertEqual(len(set(reservados)), 1)

    # -- 12/14: recuperação -------------------------------------------
    def test_sending_abandonado_volta_para_retry_com_a_mesma_chave(self):
        self._produce_and_finish("10", boas=10)
        reservado = self.db.reservar_lote_outbound_totvs(worker="w-morto", lease_seconds=10)[0]
        # Nenhum ciclo consegue tocar o item enquanto o lease vale.
        self.assertEqual(self.db.recuperar_envios_abandonados_totvs(), [])
        futuro = self.db._now() + timedelta(seconds=60)
        recuperados = self.db.recuperar_envios_abandonados_totvs(now=futuro)
        self.assertEqual(len(recuperados), 1)
        item = recuperados[0]
        self.assertEqual(item["status"], OutboxStatus.RETRY.value)
        self.assertEqual(item["idempotency_key"], reservado["idempotency_key"])
        self.assertEqual(item["last_error_code"], "lease_expirado")
        self.assertIsNone(item["lease_expires_at"])
        historico = self.db.listar_tentativas_outbound_totvs(item["id"])
        self.assertEqual([row["outcome"] for row in historico], ["abandonado"])

    def test_worker_com_lease_perdido_nao_sobrescreve_o_novo_dono(self):
        self._produce_and_finish("10", boas=10)
        lento = self.db.reservar_lote_outbound_totvs(worker="w-lento", lease_seconds=10)[0]
        futuro = self.db._now() + timedelta(minutes=10)
        self.assertEqual(len(self.db.recuperar_envios_abandonados_totvs(now=futuro)), 1)
        novo = self.db.reservar_lote_outbound_totvs(
            worker="w-novo", now=futuro + timedelta(minutes=5)
        )[0]
        self.assertEqual(novo["id"], lento["id"])

        # O worker lento termina o POST depois de perder o lease: nada é gravado.
        atrasado = TotvsOutboxWorker(
            self.db,
            gateway=_client(lambda r: httpx.Response(503, text="indisponivel")),
            worker_name="w-lento",
        ).deliver(lento)
        self.assertIsNone(atrasado)
        item = self.db.buscar_item_outbound_totvs(lento["id"])
        self.assertEqual(item["status"], OutboxStatus.SENDING.value)
        self.assertEqual(item["lease_owner"], "w-novo")
        self.assertEqual(item["attempts"], 2)
        self.assertEqual(
            [row["outcome"] for row in self.db.listar_tentativas_outbound_totvs(lento["id"])],
            ["abandonado"],
        )

        # O dono atual conclui normalmente.
        final = TotvsOutboxWorker(
            self.db,
            gateway=_client(lambda r: httpx.Response(200, text=ACK_OK)),
            worker_name="w-novo",
        ).deliver(novo)
        self.assertEqual(final["status"], OutboxStatus.SENT.value)
        self.assertIsNone(final["lease_owner"])

    def test_reinicio_processa_pending_antigo_sem_perder_mensagem(self):
        # Item A: abandonado em SENDING quando o processo anterior morreu.
        self._produce_and_finish("10", boas=10)
        abandonado = self.db.reservar_lote_outbound_totvs(
            worker="processo-antigo", lease_seconds=10
        )[0]
        # Item B: nunca reservado, apenas PENDING no banco.
        self._produce_and_finish("20", boas=8, quantidade=8)
        pendentes = [
            item["id"] for item in self._outbox(status=OutboxStatus.PENDING)
        ]
        self.assertTrue(pendentes)
        self.db.close()

        reiniciado = Database(self.dsn, auto_migrate=False, totvs_outbox_config=self.CONFIG)
        self.db = reiniciado
        futuro = reiniciado._now() + timedelta(minutes=10)
        gateway = _client(lambda r: httpx.Response(200, text=ACK_OK))

        primeiro = TotvsOutboxWorker(
            reiniciado,
            gateway=gateway,
            worker_name="processo-novo",
            now_func=lambda: futuro,
        ).run_once()
        # O PENDING antigo sai no primeiro ciclo, sem intervenção manual.
        self.assertEqual(primeiro.recovered, 1)
        self.assertEqual(primeiro.sent, len(pendentes))

        # O abandonado voltou para RETRY e sai quando o backoff vence.
        recuperado = reiniciado.buscar_item_outbound_totvs(abandonado["id"])
        self.assertEqual(recuperado["status"], OutboxStatus.RETRY.value)
        self.assertEqual(
            recuperado["idempotency_key"], abandonado["idempotency_key"]
        )
        segundo = TotvsOutboxWorker(
            reiniciado,
            gateway=gateway,
            worker_name="processo-novo",
            now_func=lambda: futuro + timedelta(minutes=5),
        ).run_once()
        self.assertEqual(segundo.sent, 1)
        entregue = reiniciado.buscar_item_outbound_totvs(abandonado["id"])
        self.assertEqual(entregue["status"], OutboxStatus.SENT.value)
        self.assertEqual(entregue["internal_id"], "783199")
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM totvs_outbox WHERE status <> 'SENT'"
            ),
            0,
        )

    # -- 15: reprocessamento manual -----------------------------------
    def test_reprocessar_error_nao_cria_nova_identidade(self):
        self._produce_and_finish("10", boas=10)
        item_id = self._outbox()[0]["id"]
        self._run_worker_with(lambda r: httpx.Response(200, text=ACK_FUNCTIONAL_ERROR))
        antes = self.db.buscar_item_outbound_totvs(item_id)
        total_antes = self._scalar("SELECT COUNT(*) AS total FROM totvs_outbox")

        service = TotvsOutboxAdminService(self.db, config=self.CONFIG)
        result = service.reprocess(item_id, operador="IAGO")
        self.assertTrue(result["ok"])
        depois = self.db.buscar_item_outbound_totvs(item_id)
        self.assertEqual(depois["status"], OutboxStatus.PENDING.value)
        self.assertEqual(depois["idempotency_key"], antes["idempotency_key"])
        self.assertEqual(depois["payload_xml"], antes["payload_xml"])
        self.assertEqual(depois["attempts"], antes["attempts"])
        self.assertEqual(
            self._scalar("SELECT COUNT(*) AS total FROM totvs_outbox"), total_antes
        )
        # O histórico anterior continua disponível para diagnóstico.
        self.assertEqual(len(self.db.listar_tentativas_outbound_totvs(item_id)), 1)

    def test_item_bloqueado_e_remontado_do_mesmo_fato_canonico(self):
        db_sem_codigo = Database(
            self.dsn,
            auto_migrate=False,
            totvs_outbox_config=OutboundEnqueueConfig(enabled=True),
        )
        self.db.close()
        self.db = db_sem_codigo
        card = self._queue("10")
        inicio = self.db._now()
        self._transition(card["id"], "producao", data_hora=inicio)
        self._transition(
            card["id"],
            "parada",
            motivo="Manutencao preventiva",
            data_hora=inicio + timedelta(minutes=5),
        )
        self._transition(
            card["id"], "producao", data_hora=inicio + timedelta(minutes=35)
        )
        bloqueado = self._outbox(status=OutboxStatus.ERROR)[0]
        self.assertEqual(bloqueado["event_type"], EVENT_STOP_REPORT)
        self.assertIsNone(bloqueado["payload_xml"])

        service = TotvsOutboxAdminService(self.db, config=self.CONFIG)
        result = service.reprocess(bloqueado["id"], operador="IAGO")
        self.assertTrue(result["ok"], result)
        item = self.db.buscar_item_outbound_totvs(bloqueado["id"])
        self.assertEqual(item["status"], OutboxStatus.PENDING.value)
        self.assertIn("<StopReasonCode>0010</StopReasonCode>", item["payload_xml"])
        self.assertNotIn("blocked", item["idempotency_key"])

    def test_refugo_e_parada_sem_codigo_totvs_ficam_registrados_para_lancar_depois(self):
        """Falta de cadastro não descarta o fato: ela o deixa pendente e legível.

        Sem ``WasteCode``/``StopReasonCode`` configurados, o Gestor não inventa
        código nem some com o refugo e a parada. Ele commita o apontamento e
        deixa a obrigação registrada com **os valores**, para que a Manufatura
        possa mapeá-los e lançá-los no Protheus depois.
        """

        db_sem_codigo = Database(
            self.dsn,
            auto_migrate=False,
            totvs_outbox_config=OutboundEnqueueConfig(enabled=True),
        )
        self.db.close()
        self.db = db_sem_codigo

        # Wave 4: boas + refugo atendem o planejado. Com 10 previstas, 7 boas
        # e 3 refugos fecham a operação — que é o cenário exercitado aqui.
        card = self._queue("10", quantidade=10)
        inicio = self.db._now()
        self._transition(card["id"], "producao", data_hora=inicio)
        self._transition(
            card["id"],
            "parada",
            motivo="Manutencao preventiva",
            data_hora=inicio + timedelta(minutes=12),
        )
        self._transition(
            card["id"], "producao", data_hora=inicio + timedelta(minutes=47)
        )
        finalizado = self._transition(
            card["id"],
            "finalizado",
            quantidade_boa=7,
            quantidade_refugo=3,
            motivo_refugo="Risco na peca",
            data_hora=inicio + timedelta(minutes=90),
        )
        # O operador foi liberado normalmente.
        self.assertEqual(finalizado["status"], "Finalizado")

        bloqueados = {
            item["event_type"]: item for item in self._outbox(status=OutboxStatus.ERROR)
        }
        self.assertEqual(
            set(bloqueados), {EVENT_STOP_REPORT, EVENT_PRODUCTION_APPOINTMENT}
        )

        parada = bloqueados[EVENT_STOP_REPORT]["payload_context"]
        self.assertTrue(parada["bloqueado"])
        self.assertEqual(
            bloqueados[EVENT_STOP_REPORT]["last_error_code"],
            "stop_reason_code_nao_configurado",
        )
        # Intervalo fechado e motivo do Gestor preservados para o lançamento futuro.
        self.assertEqual(
            parada["stop_started_at"], (inicio + timedelta(minutes=12)).isoformat()
        )
        self.assertEqual(
            parada["stop_ended_at"], (inicio + timedelta(minutes=47)).isoformat()
        )
        self.assertEqual(parada["stop_reason_gestor"], "Manutencao preventiva")
        self.assertIsNone(parada["stop_reason_code"])
        self.assertEqual(parada["resource_code"], "PLASMA")
        self.assertEqual(parada["company_id"], "01")
        self.assertEqual(parada["branch_id"], "010004")

        refugo = bloqueados[EVENT_PRODUCTION_APPOINTMENT]["payload_context"]
        self.assertTrue(refugo["bloqueado"])
        self.assertEqual(refugo["scrap_quantity"], "3")
        self.assertEqual(refugo["good_quantity"], "7")
        self.assertEqual(refugo["scrap_reason"], "Risco na peca")
        self.assertIsNone(refugo["waste_code"])
        self.assertTrue(refugo["close_operation"])
        self.assertEqual(refugo["operation"], "10")
        self.assertEqual(refugo["item_code"], "PNT002002003")

        # As quantidades canônicas continuam separadas e intactas no Gestor.
        quantidades = {
            row["tipo"]: row["quantidade"]
            for row in self._rows(
                """
                SELECT tipo, SUM(quantidade) AS quantidade
                FROM eventos_quantidade_producao WHERE op = %s GROUP BY tipo
                """,
                (self.op,),
            )
        }
        self.assertEqual(quantidades, {"boa": 7, "refugo": 3})

        # Configurados os cadastros, as MESMAS obrigações viram mensagem real.
        service = TotvsOutboxAdminService(self.db, config=self.CONFIG)
        for item in bloqueados.values():
            resultado = service.reprocess(item["id"], operador="PCP")
            self.assertTrue(resultado["ok"], resultado)
        entregaveis = self._outbox(status=OutboxStatus.PENDING)
        self.assertEqual(len(entregaveis), 2)
        payloads = "".join(item["payload_xml"] for item in entregaveis)
        self.assertIn("<StopReasonCode>0010</StopReasonCode>", payloads)
        self.assertIn("<WasteCode>RP</WasteCode>", payloads)
        self.assertIn("<ScrapQuantity>3</ScrapQuantity>", payloads)
        self.assertIn("<ApprovedQuantity>7</ApprovedQuantity>", payloads)

    # -- 16/17: StopReport --------------------------------------------
    def test_parada_aberta_nao_entra_na_fila_e_retomada_fecha_o_intervalo(self):
        card = self._queue("10")
        inicio = self.db._now()
        self._transition(card["id"], "producao", data_hora=inicio)
        self._transition(
            card["id"],
            "parada",
            motivo="Manutencao preventiva",
            data_hora=inicio + timedelta(minutes=5),
        )
        self.assertEqual(self._outbox(), [])

        self._transition(
            card["id"], "producao", data_hora=inicio + timedelta(minutes=35)
        )
        itens = self._outbox()
        self.assertEqual([item["event_type"] for item in itens], [EVENT_STOP_REPORT])
        payload = itens[0]["payload_xml"]
        self.assertIn("<StopReasonCode>0010</StopReasonCode>", payload)
        self.assertIn("<StartDateTime>", payload)
        self.assertIn("<EndDateTime>", payload)
        self.assertIn("<MachineCode>PLASMA</MachineCode>", payload)

    # -- 18/19/20/21: marco terminal ----------------------------------
    def test_ingestao_de_production_order_nao_cria_outbound_terminal(self):
        # Reingerir o mesmo planejamento não pode gerar mensagem de saída.
        self.ingestion.ingest(REAL_OP.read_text(encoding="utf-8"))
        self.assertEqual(self._outbox(), [])
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM catalogo_operacoes_op WHERE codigo_op = %s AND marco_terminal IS TRUE",
                (self.op,),
            ),
            1,
        )

    def test_terminal_entra_apenas_quando_toda_a_execucao_termina(self):
        self._produce_and_finish("10", boas=10)
        self.assertEqual(
            [
                item
                for item in self._outbox()
                if item["event_type"] == EVENT_PRODUCTION_APPOINTMENT_TERMINAL
            ],
            [],
        )
        self._produce_and_finish("20", boas=8, quantidade=8)
        terminais = [
            item
            for item in self._outbox()
            if item["event_type"] == EVENT_PRODUCTION_APPOINTMENT_TERMINAL
        ]
        self.assertEqual(len(terminais), 1)
        payload = terminais[0]["payload_xml"]
        self.assertIn("<ActivityCode>99</ActivityCode>", payload)
        self.assertIn("<MachineCode>ALMOX4</MachineCode>", payload)
        self.assertIn("<CloseOperation>true</CloseOperation>", payload)
        # Regra canônica preservada: boas da última operação produtiva (8),
        # nunca a soma das etapas (18) nem o planejado (10).
        self.assertIn("<ApprovedQuantity>8</ApprovedQuantity>", payload)
        self.assertNotIn("<ApprovedQuantity>18</ApprovedQuantity>", payload)
        self.assertEqual(terminais[0]["operation_code"], "99")

    def test_terminal_nao_duplica_nem_por_chave_nem_por_reexecucao(self):
        self._produce_and_finish("10", boas=10)
        self._produce_and_finish("20", boas=8, quantidade=8)
        terminal = [
            item
            for item in self._outbox()
            if item["event_type"] == EVENT_PRODUCTION_APPOINTMENT_TERMINAL
        ][0]
        # Uma segunda tentativa de enfileirar a mesma mensagem lógica é
        # recusada pela constraint do banco, não por verificação em Python.
        marco = self.db.buscar_marco_terminal_outbound_totvs(self.op)
        pedido = plan_terminal_milestone(marco, config=self.CONFIG)[0]
        self.assertEqual(pedido.idempotency_key, terminal["idempotency_key"])
        with self.db.connection() as connection, connection.cursor() as cursor:
            duplicado = self.db.enfileirar_outbound_totvs_tx(cursor, pedido)
        self.assertIsNone(duplicado)
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM totvs_outbox WHERE event_type = %s",
                (EVENT_PRODUCTION_APPOINTMENT_TERMINAL,),
            ),
            1,
        )

        # E pelo caminho real: uma nova execução da mesma OP volta a satisfazer
        # a condição do terminal. O conflito de chave é reconhecido como
        # "obrigação já registrada" e a transação do operador segue normal —
        # não vira erro de integridade nem segundo apontamento terminal.
        row = self._produce_and_finish("20", boas=2, quantidade=2)
        self.assertEqual(row["status"], "Finalizado")
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM totvs_outbox WHERE event_type = %s",
                (EVENT_PRODUCTION_APPOINTMENT_TERMINAL,),
            ),
            1,
        )

    # -- 22/23/24: regras industriais preservadas ---------------------
    def test_refugo_continua_separado_da_peca_boa(self):
        card = self._queue("10")
        self._transition(card["id"], "producao")
        self._transition(
            card["id"],
            "finalizado",
            quantidade_boa=7,
            quantidade_refugo=2,
            motivo_refugo="Risco na peca",
        )
        quantidades = {
            row["tipo"]: row["quantidade"]
            for row in self._rows(
                "SELECT tipo, SUM(quantidade) AS quantidade FROM eventos_quantidade_producao WHERE op = %s GROUP BY tipo",
                (self.op,),
            )
        }
        self.assertEqual(quantidades, {"boa": 7, "refugo": 2})
        item = next(
            item
            for item in self._outbox()
            if item["event_type"] == EVENT_PRODUCTION_APPOINTMENT
        )
        self.assertIn("<ApprovedQuantity>7</ApprovedQuantity>", item["payload_xml"])
        self.assertIn("<ScrapQuantity>2</ScrapQuantity>", item["payload_xml"])
        self.assertIn("<ReportQuantity>9</ReportQuantity>", item["payload_xml"])
        self.assertIn("<WasteCode>RP</WasteCode>", item["payload_xml"])

    def test_retrabalho_nao_gera_outbound(self):
        card = self._queue("10")
        self._transition(card["id"], "producao")
        self._transition(card["id"], "retrabalho", quantidade_retrabalho=3)
        self.assertEqual(self._outbox(), [])
        self.assertEqual(
            self._scalar(
                "SELECT COALESCE(SUM(quantidade), 0) AS total FROM eventos_quantidade_producao WHERE op = %s AND tipo = 'retrabalho'",
                (self.op,),
            ),
            3,
        )

    def test_production_appointment_normal_mantem_identidade_do_planejamento(self):
        self._produce_and_finish("10", boas=10)
        item = next(
            item
            for item in self._outbox()
            if item["event_type"] == EVENT_PRODUCTION_APPOINTMENT
        )
        payload = item["payload_xml"]
        self.assertIn("<ProductionOrderNumber>A9716901001</ProductionOrderNumber>", payload)
        self.assertIn("<ActivityCode>10</ActivityCode>", payload)
        self.assertIn("<ActivityID>108761</ActivityID>", payload)
        self.assertIn("<MachineCode>PLASMA</MachineCode>", payload)
        self.assertIn("<ItemCode>PNT002002003</ItemCode>", payload)
        self.assertIn("<CloseOperation>true</CloseOperation>", payload)
        self.assertIn("<ReworkQuantity>0</ReworkQuantity>", payload)
        self.assertEqual(item["transaction"], "productionappointment")

    # -- 25: inbound intacto ------------------------------------------
    def test_whois_e_production_order_inbound_continuam_intactos(self):
        antes = self._scalar("SELECT COUNT(*) AS total FROM totvs_outbox")
        outcome = self.ingestion.handle_message(WHOIS.read_text(encoding="utf-8"))
        self.assertEqual(outcome.transaction, "WhoIs")
        self.assertIsNone(outcome.ingestion)
        resultado = self.ingestion.ingest(REAL_OP.read_text(encoding="utf-8"))
        self.assertEqual(resultado.action, "duplicate")
        self.assertEqual(
            self._scalar("SELECT COUNT(*) AS total FROM totvs_outbox"), antes
        )
        self.assertEqual(
            self._scalar(
                "SELECT COUNT(*) AS total FROM catalogo_operacoes_op WHERE codigo_op = %s AND ativo IS TRUE",
                (self.op,),
            ),
            2,
        )

    # -- 16: observabilidade ------------------------------------------
    def test_metricas_expõem_fila_ultima_falha_e_ultima_entrega(self):
        self._produce_and_finish("10", boas=10)
        metricas = self.db.metricas_outbound_totvs()
        self.assertEqual(metricas["pending"], 1)
        self.assertIsNotNone(metricas["item_pendente_mais_antigo"])
        self._run_worker_with(lambda r: httpx.Response(503, text="fora"))
        metricas = self.db.metricas_outbound_totvs()
        self.assertEqual(metricas["retry"], 1)
        self.assertEqual(metricas["ultima_falha"]["last_error_code"], "http_503")
        self._make_due()
        self._run_worker_with(lambda r: httpx.Response(200, text=ACK_OK))
        metricas = self.db.metricas_outbound_totvs()
        self.assertEqual(metricas["sent"], 1)
        self.assertEqual(metricas["ultima_entrega_ok"]["internal_id"], "783199")
        self.assertEqual(metricas["tentativas_registradas"], 2)


if __name__ == "__main__":
    unittest.main()
