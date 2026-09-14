"""Etapa 6.1 — sincronização de OP sob demanda.

Duas famílias:

* domínio puro (decisão de pedir ou não, timeout, indisponibilidade, cache
  negativo, entrega inline pelo pipeline canônico), com dublês determinísticos;
* arquitetura real em PostgreSQL, em schema isolado por teste, provando
  concorrência, idempotência, marco terminal e ausência de dado parcial.

Nenhum teste toca o TOTVS: o gateway é sempre um dublê.
"""

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import threading
import unittest
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database.config import load_postgres_config
from app.database.database import Database
from mes.integrations.totvs.errors import TotvsIntegrationError
from mes.integrations.totvs.mapper import TotvsProductionOrderMapper
from mes.integrations.totvs.on_demand import (
    DELIVERY_INLINE,
    DELIVERY_PUSH,
    STATUS_INDISPONIVEL,
    STATUS_LOCAL,
    STATUS_NAO_ENCONTRADA,
    STATUS_SEM_ROTEIRO,
    STATUS_SINCRONIZADA,
    STATUS_TIMEOUT,
    ProductionOrderOnDemandSyncService,
    ProductionOrderRequestResult,
    operator_message,
)
from mes.integrations.totvs.on_demand_gateway import (
    OnDemandGatewayConfig,
    ProtheusOnDemandRequestGateway,
)
from mes.integrations.totvs.parser import TotvsMessageParser
from mes.integrations.totvs.resource_mapping import TotvsResourceResolver
from mes.integrations.totvs.service import TotvsProductionOrderIngestionService
from mes.services.order_provisioning import (
    OrderProvisioningService,
    STATUS_INDISPONIVEL as PROVISIONING_INDISPONIVEL,
)


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "totvs"
REAL_OP = FIXTURES / "ok_productionorder_20260827120232_a9716901001.xml"
REAL_OP_NUMBER = "A9716901001"
REAL_OP_UNIQUE_ID = "01|010004|A9716901001"


class FakeClock:
    """Relógio determinístico: o timeout é medido, não esperado de verdade."""

    def __init__(self, start: datetime | None = None):
        self.now = start or datetime(2026, 9, 2, 8, 0, 0)

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now = self.now + timedelta(seconds=seconds)


class FakeRepository:
    """Repositório em memória com a mesma arbitragem lógica do PostgreSQL."""

    def __init__(self, orders=None):
        self.orders = dict(orders or {})
        self.requests = {}
        self._next_id = 1
        self.lookups = 0

    def buscar_op_local_totvs(self, codigo_op):
        self.lookups += 1
        return self.orders.get(codigo_op)

    def abrir_solicitacao_sync_op(
        self, *, codigo_op, agora, negative_ttl_seconds, stale_after_seconds
    ):
        current = self.requests.get(codigo_op)
        if current is None:
            row = {
                "id": self._next_id,
                "codigo_op": codigo_op,
                "status": "PENDING",
                "finished_at": None,
                "updated_at": agora,
                "error_code": None,
            }
            self._next_id += 1
            self.requests[codigo_op] = row
            return {"role": "leader", **row}
        if current["status"] == "PENDING" and current["updated_at"] > agora - timedelta(
            seconds=stale_after_seconds
        ):
            return {"role": "follower", **current}
        if (
            current["status"] == "NOT_FOUND"
            and negative_ttl_seconds > 0
            and current["finished_at"] is not None
            and current["finished_at"] > agora - timedelta(seconds=negative_ttl_seconds)
        ):
            return {"role": "negative_cache", **current}
        current.update(status="PENDING", finished_at=None, updated_at=agora, error_code=None)
        return {"role": "leader", **current}

    def finalizar_solicitacao_sync_op(
        self, *, solicitacao_id, status, agora, error_code=None, error_message=None
    ):
        for row in self.requests.values():
            if row["id"] == solicitacao_id:
                row.update(
                    status=status,
                    finished_at=agora,
                    updated_at=agora,
                    error_code=error_code,
                    error_message=error_message,
                )

    def consultar_solicitacao_sync_op(self, codigo_op):
        return self.requests.get(codigo_op)


class RecordingGateway:
    def __init__(self, result: ProductionOrderRequestResult, *, on_call=None):
        self.result = result
        self.calls = []
        self._on_call = on_call

    def request_production_order(self, *, company_id, branch_id, number):
        self.calls.append({"company_id": company_id, "branch_id": branch_id, "number": number})
        if self._on_call is not None:
            self._on_call(number)
        return self.result


class RecordingIngestion:
    def __init__(self, repository=None, codigo=None, order=None):
        self.messages = []
        self._repository = repository
        self._codigo = codigo
        self._order = order

    def handle_message(self, payload):
        self.messages.append(payload)
        if self._repository is not None:
            self._repository.orders[self._codigo] = self._order
        return type("Outcome", (), {"ingestion": None, "soap_result": None})()


class HeaderOnlyRepository(FakeRepository):
    def __init__(self):
        super().__init__()
        self.headers = {}

    def buscar_cabecalho_op_local_totvs(self, codigo_op):
        return self.headers.get(codigo_op)


class HeaderOnlyIngestion:
    def __init__(self, repository, codigo):
        self.repository = repository
        self.codigo = codigo

    def handle_message(self, _payload):
        self.repository.headers[self.codigo] = {
            "codigo_op": self.codigo,
            "operacoes_ativas": 0,
        }
        ingestion = type("Ingestion", (), {"warnings": ("roteiro ausente",)})()
        return type("Outcome", (), {"ingestion": ingestion, "soap_result": None})()


class LeaderInFlightRepository(HeaderOnlyRepository):
    """A janela real entre o cabeçalho e o roteiro do líder.

    A ingestão grava a OP antes das operações do roteiro. Enquanto isso o
    seguidor enxerga "cabeçalho sem roteiro" — que não é a mesma coisa que
    "o TOTVS não tem roteiro para esta OP".
    """

    def __init__(self, codigo, *, leituras_ate_o_roteiro=3):
        super().__init__()
        self.codigo = codigo
        self.leituras_ate_o_roteiro = leituras_ate_o_roteiro
        self.headers[codigo] = {"codigo_op": codigo, "operacoes_ativas": 0}

    def buscar_op_local_totvs(self, codigo_op):
        self.lookups += 1
        if codigo_op == self.codigo and self.lookups > self.leituras_ate_o_roteiro:
            # O líder terminou: o roteiro utilizável passa a existir.
            self.orders[codigo_op] = {"codigo_op": codigo_op, "operacoes_ativas": 4}
            self.headers.pop(codigo_op, None)
            self.requests[codigo_op].update(status="DONE")
        return self.orders.get(codigo_op)


def _service(repository, gateway=None, ingestion=None, clock=None, **kwargs):
    clock = clock or FakeClock()
    return ProductionOrderOnDemandSyncService(
        repository,
        ingestion_service=ingestion if ingestion is not None else RecordingIngestion(),
        gateway=gateway,
        company_id="01",
        branch_id="010004",
        now_func=clock,
        sleep_func=clock.sleep,
        **kwargs,
    )


# ----------------------------------------------------------------------
# Domínio puro
# ----------------------------------------------------------------------
class OnDemandDomainTests(unittest.TestCase):
    def test_op_local_nao_chama_totvs(self):
        """§8: OP existente é lookup local; o ERP não é acionado."""

        repo = FakeRepository({REAL_OP_NUMBER: {"codigo_op": REAL_OP_NUMBER}})
        gateway = RecordingGateway(ProductionOrderRequestResult(accepted=True))
        outcome = _service(repo, gateway).sync_production_order_on_demand(REAL_OP_NUMBER)
        self.assertEqual(outcome.status, STATUS_LOCAL)
        self.assertEqual(gateway.calls, [])
        self.assertFalse(outcome.requested)
        self.assertEqual(repo.requests, {})

    def test_op_ausente_solicita_totvs(self):
        repo = FakeRepository()
        order = {"codigo_op": REAL_OP_NUMBER}
        ingestion = RecordingIngestion(repo, REAL_OP_NUMBER, order)
        gateway = RecordingGateway(
            ProductionOrderRequestResult(
                accepted=True, delivery=DELIVERY_INLINE, message_xml="<TOTVSMessage/>"
            )
        )
        outcome = _service(repo, gateway, ingestion).sync_production_order_on_demand(
            REAL_OP_NUMBER
        )
        self.assertEqual(outcome.status, STATUS_SINCRONIZADA)
        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(gateway.calls[0]["number"], REAL_OP_NUMBER)

    def test_resposta_passa_pelo_pipeline_canonico(self):
        """A OP nasce pelo mesmo serviço de ingestão do push; não há segundo caminho."""

        repo = FakeRepository()
        ingestion = RecordingIngestion(repo, REAL_OP_NUMBER, {"codigo_op": REAL_OP_NUMBER})
        xml = REAL_OP.read_text(encoding="utf-8")
        gateway = RecordingGateway(
            ProductionOrderRequestResult(
                accepted=True, delivery=DELIVERY_INLINE, message_xml=xml
            )
        )
        _service(repo, gateway, ingestion).sync_production_order_on_demand(REAL_OP_NUMBER)
        self.assertEqual(ingestion.messages, [xml])

    def test_op_alfanumerica_preserva_identidade(self):
        """§10: alfanumérico, sem remover zero e sem converter para inteiro."""

        repo = FakeRepository()
        gateway = RecordingGateway(ProductionOrderRequestResult(not_found=True))
        service = _service(repo, gateway)
        service.sync_production_order_on_demand("  a9716901001 \n")
        self.assertEqual(gateway.calls[0]["number"], "A9716901001")
        self.assertEqual(
            ProductionOrderOnDemandSyncService.normalize("0079689C001"), "0079689C001"
        )

    def test_unique_id_do_ambiente_acompanha_a_solicitacao(self):
        repo = FakeRepository()
        gateway = RecordingGateway(ProductionOrderRequestResult(not_found=True))
        _service(repo, gateway).sync_production_order_on_demand(REAL_OP_NUMBER)
        call = gateway.calls[0]
        unique_id = "|".join([call["company_id"], call["branch_id"], call["number"]])
        self.assertEqual(unique_id, REAL_OP_UNIQUE_ID)

    def test_op_inexistente_nao_cria_nada(self):
        repo = FakeRepository()
        ingestion = RecordingIngestion()
        gateway = RecordingGateway(ProductionOrderRequestResult(not_found=True))
        outcome = _service(repo, gateway, ingestion).sync_production_order_on_demand("ZZ999")
        self.assertEqual(outcome.status, STATUS_NAO_ENCONTRADA)
        self.assertEqual(repo.orders, {})
        self.assertEqual(ingestion.messages, [])
        self.assertEqual(operator_message(outcome.status), "OP não encontrada no TOTVS.")

    def test_timeout_nao_vira_op_inexistente(self):
        """Aceito e sem chegada no prazo é indisponibilidade, não inexistência."""

        repo = FakeRepository()
        clock = FakeClock()
        gateway = RecordingGateway(
            ProductionOrderRequestResult(accepted=True, delivery=DELIVERY_PUSH)
        )
        outcome = _service(repo, gateway, clock=clock, timeout_seconds=5).sync_production_order_on_demand(
            REAL_OP_NUMBER
        )
        self.assertEqual(outcome.status, STATUS_TIMEOUT)
        self.assertEqual(repo.orders, {})
        self.assertEqual(repo.requests[REAL_OP_NUMBER]["status"], "TIMEOUT")
        self.assertGreaterEqual(outcome.elapsed_seconds, 5)

    def test_inline_com_cabecalho_sem_roteiro_nao_vira_timeout(self):
        repo = HeaderOnlyRepository()
        gateway = RecordingGateway(
            ProductionOrderRequestResult(
                accepted=True, delivery=DELIVERY_INLINE, message_xml="<TOTVSMessage/>"
            )
        )
        service = _service(
            repo,
            gateway,
            HeaderOnlyIngestion(repo, REAL_OP_NUMBER),
            timeout_seconds=5,
        )

        first = service.sync_production_order_on_demand(REAL_OP_NUMBER)
        second = service.sync_production_order_on_demand(REAL_OP_NUMBER)

        self.assertEqual(first.status, STATUS_SEM_ROTEIRO)
        self.assertFalse(first.found)
        self.assertTrue(first.requested)
        self.assertEqual(first.warnings, ("roteiro ausente",))
        self.assertEqual(repo.requests[REAL_OP_NUMBER]["status"], "DONE")
        self.assertEqual(second.status, STATUS_SEM_ROTEIRO)
        self.assertFalse(second.requested)
        self.assertEqual(len(gateway.calls), 1)
        self.assertEqual(
            operator_message(first.status),
            "OP existente no TOTVS, porém sem roteiro operacional utilizável.",
        )

    def test_seguidor_nao_responde_sem_roteiro_enquanto_o_lider_grava(self):
        """Corrida real observada na suíte completa (08/09/2026).

        A ingestão do líder grava o cabeçalho da OP antes das operações do
        roteiro. O seguidor que consultava exatamente nessa janela lia
        "cabeçalho sem roteiro" e devolvia ``sem_roteiro`` — uma resposta
        terminal errada sobre uma OP que estava prestes a ficar pronta. O
        seguidor precisa esperar enquanto a solicitação do líder está
        ``PENDING``.
        """

        repo = LeaderInFlightRepository(REAL_OP_NUMBER)
        clock = FakeClock()
        # O líder já reservou a OP e ainda está processando a resposta.
        repo.requests[REAL_OP_NUMBER] = {
            "id": 1,
            "codigo_op": REAL_OP_NUMBER,
            "status": "PENDING",
            "finished_at": None,
            "updated_at": clock.now,
            "error_code": None,
        }
        gateway = RecordingGateway(ProductionOrderRequestResult(accepted=True))
        service = _service(repo, gateway, clock=clock, timeout_seconds=5)

        outcome = service.sync_production_order_on_demand(REAL_OP_NUMBER)

        self.assertEqual(outcome.status, STATUS_SINCRONIZADA)
        self.assertTrue(outcome.idempotent)
        # O seguidor não abre uma segunda sincronização no TOTVS.
        self.assertEqual(gateway.calls, [])

    def test_seguidor_ainda_responde_sem_roteiro_quando_o_lider_terminou(self):
        """A espera não pode esconder a OP que realmente não tem roteiro."""

        repo = HeaderOnlyRepository()
        clock = FakeClock()
        repo.headers[REAL_OP_NUMBER] = {
            "codigo_op": REAL_OP_NUMBER,
            "operacoes_ativas": 0,
        }
        repo.requests[REAL_OP_NUMBER] = {
            "id": 1,
            "codigo_op": REAL_OP_NUMBER,
            "status": "PENDING",
            "finished_at": None,
            "updated_at": clock.now,
            "error_code": None,
        }
        gateway = RecordingGateway(ProductionOrderRequestResult(accepted=True))
        service = _service(repo, gateway, clock=clock, timeout_seconds=2)

        outcome = service.sync_production_order_on_demand(REAL_OP_NUMBER)

        # Esgotado o prazo do seguidor, a resposta parcial volta a valer.
        self.assertEqual(outcome.status, STATUS_SEM_ROTEIRO)
        self.assertEqual(gateway.calls, [])

    def test_totvs_offline_nao_deixa_dado_parcial(self):
        repo = FakeRepository()
        ingestion = RecordingIngestion()
        gateway = RecordingGateway(
            ProductionOrderRequestResult(unavailable_reason="conexao_recusada")
        )
        outcome = _service(repo, gateway, ingestion).sync_production_order_on_demand(
            REAL_OP_NUMBER
        )
        self.assertEqual(outcome.status, STATUS_INDISPONIVEL)
        self.assertEqual(repo.orders, {})
        self.assertEqual(ingestion.messages, [])
        self.assertEqual(repo.requests[REAL_OP_NUMBER]["status"], "UNAVAILABLE")
        self.assertEqual(
            operator_message(outcome.status),
            "Não foi possível consultar o TOTVS no momento.",
        )

    def test_offline_nao_alimenta_cache_negativo(self):
        """Indisponibilidade não pode virar 'OP não encontrada' na próxima busca."""

        repo = FakeRepository()
        gateway = RecordingGateway(
            ProductionOrderRequestResult(unavailable_reason="timeout")
        )
        service = _service(repo, gateway)
        service.sync_production_order_on_demand(REAL_OP_NUMBER)
        service.sync_production_order_on_demand(REAL_OP_NUMBER)
        self.assertEqual(len(gateway.calls), 2)

    def test_cache_negativo_curto_nao_martela_o_erp(self):
        repo = FakeRepository()
        clock = FakeClock()
        gateway = RecordingGateway(ProductionOrderRequestResult(not_found=True))
        service = _service(repo, gateway, clock=clock, negative_ttl_seconds=60)
        first = service.sync_production_order_on_demand("ZZ999")
        second = service.sync_production_order_on_demand("ZZ999")
        self.assertEqual(first.status, STATUS_NAO_ENCONTRADA)
        self.assertEqual(second.status, STATUS_NAO_ENCONTRADA)
        self.assertTrue(second.idempotent)
        self.assertEqual(len(gateway.calls), 1)

    def test_cache_negativo_expira_porque_a_op_pode_ser_criada_depois(self):
        repo = FakeRepository()
        clock = FakeClock()
        gateway = RecordingGateway(ProductionOrderRequestResult(not_found=True))
        service = _service(repo, gateway, clock=clock, negative_ttl_seconds=60)
        service.sync_production_order_on_demand("ZZ999")
        clock.now = clock.now + timedelta(seconds=120)
        service.sync_production_order_on_demand("ZZ999")
        self.assertEqual(len(gateway.calls), 2)

    def test_segunda_busca_ocorre_localmente(self):
        repo = FakeRepository()
        order = {"codigo_op": REAL_OP_NUMBER}
        ingestion = RecordingIngestion(repo, REAL_OP_NUMBER, order)
        gateway = RecordingGateway(
            ProductionOrderRequestResult(
                accepted=True, delivery=DELIVERY_INLINE, message_xml="<TOTVSMessage/>"
            )
        )
        service = _service(repo, gateway, ingestion)
        service.sync_production_order_on_demand(REAL_OP_NUMBER)
        second = service.sync_production_order_on_demand(REAL_OP_NUMBER)
        self.assertEqual(second.status, STATUS_LOCAL)
        self.assertEqual(len(gateway.calls), 1)

    def test_erro_do_pipeline_nao_reporta_sucesso(self):
        class FailingIngestion:
            def handle_message(self, payload):
                raise TotvsIntegrationError("XML inválido", code="invalid_totvs_message")

        repo = FakeRepository()
        gateway = RecordingGateway(
            ProductionOrderRequestResult(
                accepted=True, delivery=DELIVERY_INLINE, message_xml="<x/>"
            )
        )
        outcome = _service(repo, gateway, FailingIngestion()).sync_production_order_on_demand(
            REAL_OP_NUMBER
        )
        self.assertEqual(outcome.status, STATUS_INDISPONIVEL)
        self.assertEqual(repo.orders, {})

    def test_sem_mecanismo_configurado_nao_inventa_op(self):
        repo = FakeRepository()
        service = ProductionOrderOnDemandSyncService(repo, ingestion_service=None, gateway=None)
        outcome = service.sync_production_order_on_demand(REAL_OP_NUMBER)
        self.assertEqual(outcome.status, STATUS_INDISPONIVEL)
        self.assertEqual(repo.orders, {})
        self.assertEqual(repo.requests, {})

    def test_codigo_vazio_e_recusado(self):
        with self.assertRaises(TotvsIntegrationError):
            _service(FakeRepository()).sync_production_order_on_demand("   ")

    def test_mensagens_de_operador_nao_expoem_detalhe_tecnico(self):
        for status in (STATUS_INDISPONIVEL, STATUS_TIMEOUT, STATUS_NAO_ENCONTRADA):
            texto = operator_message(status)
            self.assertNotIn("SOAP", texto)
            self.assertNotIn("http", texto.casefold())
            self.assertNotIn("Traceback", texto)


class OnDemandGatewayTests(unittest.TestCase):
    """O transporte só classifica; a decisão continua no caso de uso."""

    def _gateway(self, handler, *, delivery=DELIVERY_PUSH):
        return ProtheusOnDemandRequestGateway(
            OnDemandGatewayConfig(endpoint="https://protheus.invalid/op", delivery=delivery),
            transport=httpx.MockTransport(handler),
        )

    def test_xml_de_retorno_vira_entrega_inline(self):
        xml = '<?xml version="1.0"?><TOTVSMessage/>'
        gateway = self._gateway(
            lambda request: httpx.Response(200, text=xml, headers={"content-type": "text/xml"})
        )
        result = gateway.request_production_order(
            company_id="01", branch_id="010004", number=REAL_OP_NUMBER
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.delivery, DELIVERY_INLINE)
        self.assertEqual(result.message_xml, xml)

    def test_404_e_inexistencia_e_nao_indisponibilidade(self):
        gateway = self._gateway(lambda request: httpx.Response(404, json={"status": "notFound"}))
        result = gateway.request_production_order(
            company_id="01", branch_id="010004", number="ZZ999"
        )
        self.assertTrue(result.not_found)
        self.assertIsNone(result.unavailable_reason)

    def test_falha_de_rede_e_indisponibilidade(self):
        def handler(request):
            raise httpx.ConnectError("recusada", request=request)

        gateway = self._gateway(handler)
        result = gateway.request_production_order(
            company_id="01", branch_id="010004", number=REAL_OP_NUMBER
        )
        self.assertFalse(result.accepted)
        self.assertFalse(result.not_found)
        self.assertEqual(result.unavailable_reason, "conexao_recusada")

    def test_http_500_e_indisponibilidade(self):
        gateway = self._gateway(lambda request: httpx.Response(500, text="erro"))
        result = gateway.request_production_order(
            company_id="01", branch_id="010004", number=REAL_OP_NUMBER
        )
        self.assertEqual(result.unavailable_reason, "http_500")

    def test_numero_alfanumerico_vai_intacto_no_payload(self):
        capturado = {}

        def handler(request):
            capturado["body"] = request.content.decode("utf-8")
            return httpx.Response(200, json={"status": "accepted"})

        self._gateway(handler).request_production_order(
            company_id="01", branch_id="010004", number="0079689C001"
        )
        self.assertIn('"0079689C001"', capturado["body"])

    def test_sem_endpoint_nao_existe_gateway(self):
        self.assertIsNone(ProtheusOnDemandRequestGateway.from_env({}))


# ----------------------------------------------------------------------
# Arquitetura real em PostgreSQL
# ----------------------------------------------------------------------
@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class OnDemandPostgresBase(unittest.TestCase):
    """Schema isolado por teste, com a OP real ainda ausente do catálogo."""

    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "gestor_ondemand_test_" + uuid4().hex
        self.admin_dsn = base.dsn
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.dsn = make_conninfo(base.dsn, options=f"-c search_path={self.schema}")
        self.db = Database(self.dsn)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO catalogo_recursos_pcfactory (
                    codigo, nome, tipo_setor, habilitado, fonte, sincronizado_em
                ) VALUES (%s, %s, %s, TRUE, 'fixture determinística', CURRENT_TIMESTAMP)
                """,
                (("PLASMA", "Plasma", "Corte"), ("CNC-01", "Centro CNC", "Usinagem")),
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
        self.xml = REAL_OP.read_text(encoding="utf-8")

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _rows(self, query, params=()):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def _build(self, gateway, **kwargs):
        return ProductionOrderOnDemandSyncService(
            self.db,
            ingestion_service=self.ingestion,
            gateway=gateway,
            company_id="01",
            branch_id="010004",
            timeout_seconds=kwargs.pop("timeout_seconds", 5),
            poll_interval_seconds=0.05,
            **kwargs,
        )


class OnDemandPostgresTests(OnDemandPostgresBase):
    def test_op_ausente_entra_pelo_pipeline_e_fica_disponivel(self):
        gateway = RecordingGateway(
            ProductionOrderRequestResult(
                accepted=True, delivery=DELIVERY_INLINE, message_xml=self.xml
            )
        )
        service = self._build(gateway)
        self.assertIsNone(service.lookup_local(REAL_OP_NUMBER))

        outcome = service.sync_production_order_on_demand(REAL_OP_NUMBER)
        self.assertEqual(outcome.status, STATUS_SINCRONIZADA)

        header = self._rows(
            "SELECT * FROM catalogo_pcp_ops WHERE codigo_op = %s", (REAL_OP_NUMBER,)
        )
        self.assertEqual(len(header), 1)
        self.assertEqual(header[0]["totvs_unique_id"], REAL_OP_UNIQUE_ID)

        # Segunda busca é local e não gera nova comunicação.
        second = service.sync_production_order_on_demand(REAL_OP_NUMBER)
        self.assertEqual(second.status, STATUS_LOCAL)
        self.assertEqual(len(gateway.calls), 1)

    def test_marco_terminal_preservado_e_invisivel_ao_operador(self):
        """§12: o terminal continua marco, inativo e fora da fila do operador."""

        gateway = RecordingGateway(
            ProductionOrderRequestResult(
                accepted=True, delivery=DELIVERY_INLINE, message_xml=self.xml
            )
        )
        self._build(gateway).sync_production_order_on_demand(REAL_OP_NUMBER)
        terminal = self._rows(
            """
            SELECT numero_operacao, marco_terminal, ativo, codigo_recurso
              FROM catalogo_operacoes_op
             WHERE codigo_op = %s AND marco_terminal = TRUE
            """,
            (REAL_OP_NUMBER,),
        )
        self.assertTrue(terminal, "o marco terminal precisa existir após a busca sob demanda")
        for row in terminal:
            self.assertTrue(row["marco_terminal"])
            self.assertFalse(row["ativo"])
        visiveis = self._rows(
            """
            SELECT numero_operacao FROM catalogo_operacoes_op
             WHERE codigo_op = %s AND ativo = TRUE AND marco_terminal = TRUE
            """,
            (REAL_OP_NUMBER,),
        )
        self.assertEqual(visiveis, [])

    def test_ingestao_sob_demanda_nao_gera_outbound(self):
        gateway = RecordingGateway(
            ProductionOrderRequestResult(
                accepted=True, delivery=DELIVERY_INLINE, message_xml=self.xml
            )
        )
        self._build(gateway).sync_production_order_on_demand(REAL_OP_NUMBER)
        self.assertEqual(self._rows("SELECT id FROM totvs_outbox"), [])

    def test_production_order_duplicado_nao_duplica_operacoes(self):
        gateway = RecordingGateway(
            ProductionOrderRequestResult(
                accepted=True, delivery=DELIVERY_INLINE, message_xml=self.xml
            )
        )
        service = self._build(gateway)
        service.sync_production_order_on_demand(REAL_OP_NUMBER)
        antes = self._rows(
            "SELECT id FROM catalogo_operacoes_op WHERE codigo_op = %s", (REAL_OP_NUMBER,)
        )
        # Reentrega da MESMA mensagem pelo inbound canônico.
        self.ingestion.handle_message(self.xml)
        depois = self._rows(
            "SELECT id FROM catalogo_operacoes_op WHERE codigo_op = %s", (REAL_OP_NUMBER,)
        )
        self.assertEqual(len(antes), len(depois))
        self.assertEqual(
            len(self._rows("SELECT codigo_op FROM catalogo_pcp_ops WHERE codigo_op = %s", (REAL_OP_NUMBER,))),
            1,
        )

    def test_duas_solicitacoes_simultaneas_geram_uma_sincronizacao(self):
        """§7/§19: o lock é do PostgreSQL, não do frontend."""

        barrier = threading.Barrier(2)
        chamadas = []
        lock = threading.Lock()

        def on_call(number):
            with lock:
                chamadas.append(number)

        gateway = RecordingGateway(
            ProductionOrderRequestResult(
                accepted=True, delivery=DELIVERY_INLINE, message_xml=self.xml
            ),
            on_call=on_call,
        )
        resultados = []

        def worker():
            database = Database(self.dsn)
            try:
                resolver = TotvsResourceResolver(
                    known_resource_codes=database.listar_codigos_recursos_totvs(),
                    known_resource_sectors=database.listar_setores_recursos_totvs(),
                )
                service = ProductionOrderOnDemandSyncService(
                    database,
                    ingestion_service=TotvsProductionOrderIngestionService(
                        database,
                        enabled=True,
                        parser=TotvsMessageParser(),
                        mapper=TotvsProductionOrderMapper(resolver),
                    ),
                    gateway=gateway,
                    company_id="01",
                    branch_id="010004",
                    timeout_seconds=8,
                    poll_interval_seconds=0.05,
                )
                barrier.wait(timeout=10)
                resultados.append(service.sync_production_order_on_demand(REAL_OP_NUMBER))
            finally:
                database.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(len(resultados), 2)
        for outcome in resultados:
            self.assertEqual(outcome.status, STATUS_SINCRONIZADA)
        self.assertEqual(len(chamadas), 1, "apenas uma sincronização lógica é permitida")
        self.assertEqual(
            len(self._rows("SELECT codigo_op FROM catalogo_pcp_ops WHERE codigo_op = %s", (REAL_OP_NUMBER,))),
            1,
        )
        self.assertEqual(
            len(self._rows("SELECT id FROM totvs_op_sync_requests WHERE codigo_op = %s", (REAL_OP_NUMBER,))),
            1,
        )
        terminais = self._rows(
            "SELECT id FROM catalogo_operacoes_op WHERE codigo_op = %s AND marco_terminal = TRUE",
            (REAL_OP_NUMBER,),
        )
        self.assertEqual(len(terminais), 1)

    def test_erro_remoto_nao_cria_dados_parciais(self):
        gateway = RecordingGateway(
            ProductionOrderRequestResult(unavailable_reason="conexao_recusada")
        )
        outcome = self._build(gateway).sync_production_order_on_demand(REAL_OP_NUMBER)
        self.assertEqual(outcome.status, STATUS_INDISPONIVEL)
        self.assertEqual(
            self._rows("SELECT codigo_op FROM catalogo_pcp_ops WHERE codigo_op = %s", (REAL_OP_NUMBER,)),
            [],
        )
        self.assertEqual(
            self._rows("SELECT id FROM catalogo_operacoes_op WHERE codigo_op = %s", (REAL_OP_NUMBER,)),
            [],
        )
        # Restaurado o mecanismo, a mesma OP sincroniza normalmente.
        gateway.result = ProductionOrderRequestResult(
            accepted=True, delivery=DELIVERY_INLINE, message_xml=self.xml
        )
        retomada = self._build(gateway).sync_production_order_on_demand(REAL_OP_NUMBER)
        self.assertEqual(retomada.status, STATUS_SINCRONIZADA)

    def test_sigmanest_permanece_somente_leitura(self):
        """A busca sob demanda não escreve no SigmaNEST nem depende dele."""

        gateway = RecordingGateway(
            ProductionOrderRequestResult(
                accepted=True, delivery=DELIVERY_INLINE, message_xml=self.xml
            )
        )
        outcome = self._build(gateway).sync_production_order_on_demand(REAL_OP_NUMBER)
        self.assertEqual(outcome.status, STATUS_SINCRONIZADA)
        # Nenhuma correlação SigmaNEST é inventada pela ingestão.
        self.assertEqual(self._rows("SELECT linha_hash FROM catalogo_sigmanest_ops"), [])


class ProtheusEndpointContractTests(OnDemandPostgresBase):
    """Etapa 6.2 — contrato do endpoint Protheus, do HTTP até o catálogo.

    Aqui o gateway HTTP real é exercitado (não um dublê de resultado): o
    transporte, a detecção de entrega inline, o pipeline canônico e a projeção
    são atravessados com a mensagem `ProductionOrder` **real** do PCPA111.
    Isso protege o contrato acordado com a TI antes de a rotina ser publicada.
    """

    def _gateway(self, handler, *, delivery=DELIVERY_INLINE):
        return ProtheusOnDemandRequestGateway(
            OnDemandGatewayConfig(
                endpoint="https://protheus.invalid/rest/gestorpecas/v1/production-order",
                delivery=delivery,
            ),
            transport=httpx.MockTransport(handler),
        )

    def _responder(self, capturado):
        def handler(request):
            capturado["body"] = request.content.decode("utf-8")
            return httpx.Response(
                200,
                text=self.xml,
                headers={"content-type": "text/xml; charset=utf-8"},
            )

        return handler

    def test_xml_do_endpoint_percorre_o_pipeline_ate_o_operador(self):
        capturado = {}
        service = self._build(self._gateway(self._responder(capturado)))
        outcome = service.sync_production_order_on_demand(REAL_OP_NUMBER)

        self.assertEqual(outcome.status, STATUS_SINCRONIZADA)
        # O contrato de entrada acordado com a TI.
        enviado = json.loads(capturado["body"])
        self.assertEqual(
            enviado,
            {"companyId": "01", "branchId": "010004", "number": REAL_OP_NUMBER},
        )

        header = self._rows(
            "SELECT * FROM catalogo_pcp_ops WHERE codigo_op = %s", (REAL_OP_NUMBER,)
        )
        self.assertEqual(len(header), 1)
        self.assertEqual(header[0]["totvs_unique_id"], REAL_OP_UNIQUE_ID)

        terminal = self._rows(
            """
            SELECT marco_terminal, ativo, tipo_setor FROM catalogo_operacoes_op
             WHERE codigo_op = %s AND marco_terminal = TRUE
            """,
            (REAL_OP_NUMBER,),
        )
        self.assertTrue(terminal)
        for row in terminal:
            self.assertFalse(row["ativo"])
            self.assertIsNone(row["tipo_setor"])
        self.assertEqual(self._rows("SELECT id FROM totvs_outbox"), [])

        # Segunda busca é local e não chama o endpoint de novo.
        capturado.clear()
        self.assertEqual(
            service.sync_production_order_on_demand(REAL_OP_NUMBER).status, STATUS_LOCAL
        )
        self.assertEqual(capturado, {})

    def test_404_notfound_do_endpoint_nao_cria_nada(self):
        gateway = self._gateway(
            lambda request: httpx.Response(404, json={"status": "notFound"})
        )
        outcome = self._build(gateway).sync_production_order_on_demand("ZZ00000ZZ99")
        self.assertEqual(outcome.status, STATUS_NAO_ENCONTRADA)
        self.assertEqual(
            self._rows(
                "SELECT codigo_op FROM catalogo_pcp_ops WHERE codigo_op = %s",
                ("ZZ00000ZZ99",),
            ),
            [],
        )

    def test_status_de_infraestrutura_viram_indisponibilidade(self):
        for status in (401, 403, 500, 503):
            with self.subTest(status=status):
                gateway = self._gateway(
                    lambda request, status=status: httpx.Response(
                        status, json={"status": "error"}
                    )
                )
                outcome = self._build(gateway).sync_production_order_on_demand(
                    REAL_OP_NUMBER
                )
                self.assertEqual(outcome.status, STATUS_INDISPONIVEL)
                self.assertEqual(outcome.detail, f"http_{status}")
                self.assertEqual(
                    self._rows(
                        "SELECT codigo_op FROM catalogo_pcp_ops WHERE codigo_op = %s",
                        (REAL_OP_NUMBER,),
                    ),
                    [],
                )

    def test_timeout_do_endpoint_nao_vira_op_inexistente(self):
        def handler(request):
            raise httpx.ReadTimeout("timeout", request=request)

        outcome = self._build(self._gateway(handler)).sync_production_order_on_demand(
            REAL_OP_NUMBER
        )
        self.assertEqual(outcome.status, STATUS_INDISPONIVEL)
        self.assertEqual(outcome.detail, "timeout")


class OrderProvisioningBoundaryTests(unittest.TestCase):
    """A execução pede uma OP; não pode aprender de onde ela vem."""

    def test_router_do_operador_nao_menciona_a_origem(self):
        source = (
            Path(__file__).resolve().parents[1] / "backend" / "api" / "routers" / "operator.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("totvs", source.casefold())

    def test_sem_provedor_a_execucao_recebe_indisponibilidade(self):
        service = OrderProvisioningService()
        self.assertFalse(service.available)
        result = service.provision(REAL_OP_NUMBER)
        self.assertEqual(result.status, PROVISIONING_INDISPONIVEL)
        self.assertFalse(result.found)
        self.assertTrue(result.message)

    def test_traduz_o_resultado_do_provedor_sem_vazar_detalhe_tecnico(self):
        repo = FakeRepository()
        gateway = RecordingGateway(
            ProductionOrderRequestResult(unavailable_reason="conexao_recusada")
        )
        service = OrderProvisioningService(
            _service(repo, gateway),
            message_for=operator_message,
            unavailable_message=operator_message(STATUS_INDISPONIVEL),
        )
        result = service.provision(REAL_OP_NUMBER)
        self.assertEqual(result.status, STATUS_INDISPONIVEL)
        self.assertEqual(result.message, "Não foi possível consultar o TOTVS no momento.")
        self.assertNotIn("conexao_recusada", result.message)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
