"""Etapa 7A — homologação E2E com ProductionOrder controlado na borda HTTP.

Somente a fronteira temporariamente bloqueada no Protheus é substituída:

    POST GESTORPECASPO -> XML ProductionOrder real capturado

Depois dela o roteiro usa, sem atalhos, ``OrderProvisioningService``,
``ProductionOrderOnDemandSyncService``, a ingestão canônica, o fluxo normal de
apontamento, a outbox transacional e ``TotvsOutboxWorker``.

O script cria um schema efêmero dentro de ``gestor_pecas_test`` e nunca limpa o
schema público. O envio ao WSPCP nasce desligado. Para transmitir os quatro
eventos de negócio gerados (parada fechada, parcial, finalização e terminal),
é obrigatório confirmar literalmente o TESTE e a OP usada.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlparse
from uuid import uuid4
from xml.etree import ElementTree


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env", override=False)

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.conninfo import make_conninfo  # noqa: E402

from app.database.config import PostgresConfig, load_postgres_config  # noqa: E402
from app.database.database import Database  # noqa: E402
from backend.integrations.totvs_wspcp import (  # noqa: E402
    TotvsWspcpClient,
    WSPCP_SOAP_ACTION,
    WSPCP_SERVICE_NAMESPACE,
    WspcpClientConfig,
)
from mes.integrations.totvs.mapper import TotvsProductionOrderMapper  # noqa: E402
from mes.integrations.totvs.on_demand import (  # noqa: E402
    DELIVERY_INLINE,
    ProductionOrderOnDemandSyncService,
    operator_message,
)
from mes.integrations.totvs.on_demand_gateway import (  # noqa: E402
    OnDemandGatewayConfig,
    ProtheusOnDemandRequestGateway,
)
from mes.integrations.totvs.outbound_enqueue import OutboundEnqueueConfig  # noqa: E402
from mes.integrations.totvs.parser import TotvsMessageParser  # noqa: E402
from mes.integrations.totvs.resource_mapping import TotvsResourceResolver  # noqa: E402
from mes.integrations.totvs.service import TotvsProductionOrderIngestionService  # noqa: E402
from mes.services.operator_flow import OperatorFlowService  # noqa: E402
from mes.services.order_provisioning import OrderProvisioningService  # noqa: E402
from mes.services.totvs_outbox_worker import TotvsOutboxWorker  # noqa: E402


EXPECTED_DATABASE = "gestor_pecas_test"
TEST_CONFIRMATION = "TOTVS_TESTE"
OP = "1079689C001"
COMPANY_ID = "01"
BRANCH_ID = "010004"
EXPECTED_TEST_ENDPOINT = (
    "https://gtsdo143182.protheus.cloudtotvs.com.br:1465/ws/WSPCP.apw"
)
CONTROLLED_ROUTE = "/rest/GESTORPECASPO/gestorpecas/v1/production-order"
OFFLINE_ENDPOINT = "https://127.0.0.1:9/ws/WSPCP.apw"
FIXTURE = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "totvs"
    / "ok_productionorder_20260821103018_1079689c001 1.xml"
)
OPERATOR_BADGE = "9701"
STOP_STATUS_CODE = "0201"
STOP_REASON_CODE = "0010"
SCRAP_REASON = "REFUGO HOMOLOGACAO 7A"
WASTE_CODE = "RP"


class Etapa7AHomologationError(RuntimeError):
    """Falha objetiva de uma invariável da homologação."""


class _AdvancingClock:
    """Relógio local determinístico para preservar a ordem dos eventos."""

    def __init__(self):
        self.current = datetime.now().replace(microsecond=0) - timedelta(hours=1)

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(minutes=5)
        return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Etapa7AHomologationError(message)


class ControlledProductionOrderResponder:
    """HTTP real que replica a fixture; não interpreta nem reconstrói o XML."""

    def __init__(self, payload_xml: str, *, response_delay_seconds: float = 0.2):
        self.payload_xml = payload_xml
        self.response_delay_seconds = max(0.0, float(response_delay_seconds))
        self.calls: list[dict] = []
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def endpoint(self) -> str:
        _require(self._server is not None, "Responder HTTP não iniciado.")
        return f"http://127.0.0.1:{self._server.server_address[1]}{CONTROLLED_ROUTE}"

    def __enter__(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - assinatura da stdlib
                length = int(self.headers.get("content-length") or 0)
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw or b"{}")
                except (TypeError, ValueError):
                    self._reply(400, {"status": "invalidJson"})
                    return
                call = {
                    "path": self.path,
                    "companyId": str(body.get("companyId") or ""),
                    "branchId": str(body.get("branchId") or ""),
                    "number": str(body.get("number") or ""),
                }
                with owner._lock:
                    owner.calls.append(call)
                if self.path != CONTROLLED_ROUTE:
                    self._reply(404, {"status": "notFound"})
                    return
                if call != {
                    "path": CONTROLLED_ROUTE,
                    "companyId": COMPANY_ID,
                    "branchId": BRANCH_ID,
                    "number": OP,
                }:
                    self._reply(404, {"status": "notFound"})
                    return
                if owner.response_delay_seconds:
                    time.sleep(owner.response_delay_seconds)
                data = owner.payload_xml.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/xml; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _reply(self, status: int, payload: dict) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="etapa7a-production-order-responder",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *_exc):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


def _rows(db: Database, query: str, params=()) -> list[dict]:
    with db.connection() as connection, connection.cursor() as cursor:
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def _scalar(db: Database, query: str, params=()):
    rows = _rows(db, query, params)
    _require(bool(rows), f"Consulta sem resultado: {query[:80]}")
    return next(iter(rows[0].values()))


def _seed_reference_catalogs(db: Database) -> None:
    """Somente cadastro de apoio; nenhum fato produtivo é inserido por SQL."""

    with db.connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO catalogo_recursos_pcfactory (
                codigo, nome, tipo_setor, habilitado, fonte, sincronizado_em
            ) VALUES ('LASER1', 'Laser Ensis 3015', 'Corte', TRUE,
                      'homologacao etapa 7A', CURRENT_TIMESTAMP)
            """
        )
        cursor.execute(
            """
            INSERT INTO catalogo_status_recursos (
                codigo, nome, grupo_codigo, grupo_nome, habilitado,
                setup, retrabalho, oculto, requer_comentario, sincronizado_em
            ) VALUES (%s, 'FALTA DE MATERIAL', '0002', 'PARADAS', TRUE,
                      FALSE, FALSE, FALSE, FALSE, CURRENT_TIMESTAMP)
            """,
            (STOP_STATUS_CODE,),
        )
        # O crachá também autoriza refugo: desde a Wave 5 descartar peça exige o
        # crachá de um responsável (``autorizador_retrabalho``). Esta homologação
        # roda com um único operador e o refugo parcial é evidência intencional
        # do roteiro, então o mesmo crachá acumula os dois papéis.
        cursor.execute(
            """
            INSERT INTO operadores_apontamento (
                cracha, nome, ativo, fonte, autorizador_retrabalho
            )
            VALUES (%s, 'OPERADOR HOMOLOGACAO 7A', TRUE, 'homologacao etapa 7A', TRUE)
            """,
            (OPERATOR_BADGE,),
        )


def _build_provisioning(
    db: Database, endpoint: str, *, timeout_seconds: float = 10.0
) -> OrderProvisioningService:
    resolver = TotvsResourceResolver(
        known_resource_codes=db.listar_codigos_recursos_totvs(),
        known_resource_sectors=db.listar_setores_recursos_totvs(),
    )
    ingestion = TotvsProductionOrderIngestionService(
        db,
        enabled=True,
        parser=TotvsMessageParser(),
        mapper=TotvsProductionOrderMapper(resolver),
    )
    gateway = ProtheusOnDemandRequestGateway(
        OnDemandGatewayConfig(
            endpoint=endpoint,
            delivery=DELIVERY_INLINE,
            timeout_seconds=timeout_seconds,
        )
    )
    provider = ProductionOrderOnDemandSyncService(
        db,
        ingestion_service=ingestion,
        gateway=gateway,
        company_id=COMPANY_ID,
        branch_ids=(BRANCH_ID,),
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=0.05,
        negative_ttl_seconds=30,
    )
    return OrderProvisioningService(provider, message_for=operator_message)


def _provision_concurrently(
    dsn: str,
    endpoint: str,
    outbox_config: OutboundEnqueueConfig,
) -> list[dict]:
    barrier = threading.Barrier(2)
    outcomes: list[dict] = []
    errors: list[str] = []
    lock = threading.Lock()

    def worker() -> None:
        local_db = Database(
            dsn,
            auto_migrate=False,
            totvs_outbox_config=outbox_config,
        )
        try:
            service = _build_provisioning(local_db, endpoint)
            barrier.wait(timeout=10)
            result = service.provision(OP)
            with lock:
                outcomes.append(asdict(result))
        except Exception as exc:  # evidência estruturada para o processo principal
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            local_db.close()

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    _require(not any(thread.is_alive() for thread in threads), "Concorrência não terminou.")
    _require(not errors, f"Falha no provisionamento concorrente: {errors}")
    _require(len(outcomes) == 2, "As duas solicitações precisam obter resultado.")
    return outcomes


def _outbound_fields(payload_xml: str | None) -> dict:
    if not payload_xml:
        return {}
    root = ElementTree.fromstring(payload_xml)

    def text_of(name: str) -> str | None:
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == name:
                value = str(element.text or "").strip()
                return value or None
        return None

    return {
        "activity_code": text_of("ActivityCode"),
        "machine_code": text_of("MachineCode"),
        "approved_quantity": text_of("ApprovedQuantity"),
        "scrap_quantity": text_of("ScrapQuantity"),
        "rework_quantity": text_of("ReworkQuantity"),
        "close_operation": text_of("CloseOperation"),
    }


def _outbox_summary(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        payload = row.get("payload_xml")
        result.append(
            {
                "id": int(row["id"]),
                "event_type": row["event_type"],
                "status": row["status"],
                "attempts": int(row.get("attempts") or 0),
                "idempotency_key": row["idempotency_key"],
                "payload_sha256": (
                    hashlib.sha256(payload.encode("utf-8")).hexdigest() if payload else None
                ),
                "payload_fields": _outbound_fields(payload),
                "last_http_status": row.get("last_http_status"),
                "last_ack_status": row.get("last_ack_status"),
                "last_delivery_class": row.get("last_delivery_class"),
                "last_error_code": row.get("last_error_code"),
                "internal_id": row.get("internal_id"),
            }
        )
    return result


def _make_due(db: Database) -> None:
    with db.connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE totvs_outbox
               SET next_attempt_at = %s
             WHERE status IN ('PENDING', 'RETRY')
            """,
            (db._now(),),
        )


def _offline_gateway() -> TotvsWspcpClient:
    return TotvsWspcpClient(
        WspcpClientConfig(
            endpoint=OFFLINE_ENDPOINT,
            service_namespace=WSPCP_SERVICE_NAMESPACE,
            timeout_seconds=1.0,
            verify_tls=False,
        )
    )


def _validate_real_delivery(
    *,
    base: PostgresConfig,
    endpoint: str,
    expected_host: str,
    confirmation: str | None,
    confirmed_op: str | None,
) -> None:
    database = str(base.safe_target.get("dbname") or "")
    _require(database == EXPECTED_DATABASE, f"Banco efetivo recusado: {database!r}.")
    _require(
        confirmation == TEST_CONFIRMATION,
        f"Envio recusado: use --confirm-test-environment {TEST_CONFIRMATION}.",
    )
    _require(confirmed_op == OP, f"Envio recusado: confirme a OP com --confirm-business-op {OP}.")
    resolved = str(endpoint or "").strip().rstrip("/")
    _require(
        resolved.casefold() == EXPECTED_TEST_ENDPOINT.casefold(),
        "Envio recusado: o endpoint não é a publicação WSPCP TESTE aprovada.",
    )
    host = str(urlparse(resolved).hostname or "").casefold()
    _require(bool(expected_host) and host == str(expected_host).casefold(), "Host TESTE divergente.")


def _real_gateway(endpoint: str) -> TotvsWspcpClient:
    return TotvsWspcpClient(
        WspcpClientConfig(
            endpoint=endpoint,
            service_namespace=str(
                os.environ.get("GESTOR_TOTVS_OUTBOUND_SERVICE_NAMESPACE")
                or WSPCP_SERVICE_NAMESPACE
            ),
            timeout_seconds=float(
                os.environ.get("GESTOR_TOTVS_OUTBOUND_TIMEOUT_SECONDS") or 30
            ),
            username=os.environ.get("GESTOR_TOTVS_OUTBOUND_USERNAME") or None,
            password=os.environ.get("GESTOR_TOTVS_OUTBOUND_PASSWORD") or None,
            authentication_mode=os.environ.get("GESTOR_TOTVS_OUTBOUND_AUTH_MODE") or None,
            soap_action=os.environ.get("GESTOR_TOTVS_OUTBOUND_SOAP_ACTION")
            or WSPCP_SOAP_ACTION,
            verify_tls=str(
                os.environ.get("GESTOR_TOTVS_OUTBOUND_VERIFY_TLS") or "true"
            ).strip().casefold()
            not in {"0", "false", "nao", "não", "no", "off"},
        )
    )


def run_homologation(
    base: PostgresConfig,
    *,
    delivery_gateway=None,
    delivery_kind: str = "nao_executado",
    failure_gateway=None,
    keep_schema: bool = False,
) -> dict:
    """Executa a prova e devolve evidência sem payload/segredo em claro.

    ``delivery_gateway`` é ``None`` no dry-run. Testes automatizados podem
    injetar um ACK determinístico; a CLI só fornece o WSPCP real após as
    confirmações explícitas de ``main``.
    """

    database_name = str(base.safe_target.get("dbname") or "")
    _require(database_name == EXPECTED_DATABASE, f"Banco efetivo recusado: {database_name!r}.")
    fixture_xml = FIXTURE.read_text(encoding="utf-8")
    fixture_sha = hashlib.sha256(fixture_xml.encode("utf-8")).hexdigest()
    parsed = TotvsMessageParser().parse(fixture_xml)
    _require(parsed.production_order.number == OP, "A fixture real não corresponde à OP esperada.")

    schema = "etapa7a_" + uuid4().hex[:12]
    with psycopg.connect(base.dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base.dsn, options=f"-c search_path={schema}")
    outbox_config = OutboundEnqueueConfig(
        enabled=True,
        waste_codes={SCRAP_REASON: WASTE_CODE},
        stop_reason_codes={STOP_STATUS_CODE: STOP_REASON_CODE},
        emit_terminal_milestone=True,
    )
    evidence = {
        "etapa": "7A",
        "database": database_name,
        "schema_isolado": schema,
        "production_order": OP,
        "fixture": {
            "arquivo": str(FIXTURE.relative_to(PROJECT_ROOT)),
            "sha256": fixture_sha,
            "source_application": parsed.metadata.source_application,
            "product": parsed.metadata.product_name,
            "product_version": parsed.metadata.product_version,
        },
        "delivery_kind": delivery_kind,
    }
    db = Database(dsn, totvs_outbox_config=outbox_config)
    try:
        _seed_reference_catalogs(db)
        with ControlledProductionOrderResponder(fixture_xml) as responder:
            preflight = _build_provisioning(db, responder.endpoint)
            _require(
                preflight.provider.lookup_local(OP) is None,
                "A OP precisa estar ausente no início do schema isolado.",
            )
            concurrent = _provision_concurrently(dsn, responder.endpoint, outbox_config)
            _require(all(item["found"] for item in concurrent), "Provisionamento não encontrou a OP.")
            _require(
                all(item["status"] == "sincronizada" for item in concurrent),
                "Líder e seguidor precisam concluir a mesma sincronização.",
            )
            _require(len(responder.calls) == 1, "Concorrência abriu mais de uma chamada HTTP.")
            calls_before_local = len(responder.calls)
            local = _build_provisioning(db, responder.endpoint).provision(OP)
            _require(local.status == "local", "A segunda consulta deveria ser somente local.")
            _require(
                len(responder.calls) == calls_before_local,
                "A consulta local repetida não pode tocar a fronteira HTTP.",
            )
            evidence["provisionamento"] = {
                "lookup_inicial": "miss",
                "resultados_concorrentes": concurrent,
                "http_calls": len(responder.calls),
                "http_request": responder.calls[0],
                "segunda_consulta": asdict(local),
                "inbox_count": int(
                    _scalar(
                        db,
                        "SELECT COUNT(*) AS total FROM totvs_integration_messages",
                    )
                ),
            }

        raw_route = [
            {
                "order": index,
                "activity_code": activity.activity_code,
                "activity_description": activity.activity_description,
                "work_center_code": activity.work_center_code,
                "machine_code": activity.machine_code,
            }
            for index, activity in enumerate(parsed.production_order.activities, start=1)
        ]
        projected = _rows(
            db,
            """
            SELECT numero_operacao, descricao_operacao, totvs_work_center_code,
                   totvs_machine_code, codigo_recurso, tipo_setor, ordem,
                   marco_terminal, inspecao_qualidade, ativo, totvs_activity_id
              FROM catalogo_operacoes_op
             WHERE codigo_op = %s
             ORDER BY ordem, id
            """,
            (OP,),
        )
        pointable = [
            row for row in projected
            if not row["marco_terminal"] and not row["inspecao_qualidade"]
        ]
        terminals = [row for row in projected if row["marco_terminal"]]
        inspections = [row for row in projected if row["inspecao_qualidade"]]
        _require(
            len(projected) == len(pointable) + len(terminals) + len(inspections),
            "Uma linha do roteiro foi classificada em mais de uma categoria.",
        )
        _require(len(pointable) == 1 and pointable[0]["numero_operacao"] == "10", "Corte não projetado.")
        _require(pointable[0]["codigo_recurso"] == "LASER1", "Alias oficial LASER -> LASER1 regrediu.")
        _require(len(terminals) == 1, "O marco terminal foi duplicado ou perdido.")
        # A operação de inspeção, quando existir no roteiro, permanece inativa:
        # ela pertence à aba Qualidade e nunca ao posto do operador.
        for inspection in inspections:
            _require(
                not inspection["ativo"] and inspection["tipo_setor"] is None,
                "A operação de inspeção não pode virar etapa de bancada.",
            )
        terminal = terminals[0]
        _require(
            terminal["numero_operacao"] == "99"
            and terminal["descricao_operacao"] == "FINALIZADA"
            and terminal["totvs_machine_code"] == "ALMOX4"
            and terminal["marco_terminal"]
            and not terminal["ativo"],
            "O marco 99/FINALIZADA/ALMOX4 perdeu seu contrato.",
        )
        visible = db.listar_operacoes_para_op(OP)
        _require(len(visible) == 1 and visible[0]["numero_operacao"] == "10", "Terminal ficou visível.")
        _require(
            int(_scalar(db, "SELECT COUNT(*) AS total FROM totvs_outbox")) == 0,
            "A ingestão de planejamento não pode gerar outbound.",
        )
        evidence["roteiro"] = {
            "activities_received": raw_route,
            "catalog": projected,
            "operator_visible_operations": [row["numero_operacao"] for row in visible],
            "outbox_after_ingestion": 0,
        }

        # A auditoria live do SigmaNEST para esta OP não encontrou cadeia; o
        # schema isolado também não recebe qualquer publicação artificial.
        sigmanest_rows = int(
            _scalar(
                db,
                """
                SELECT COUNT(*) AS total
                  FROM catalogo_sigmanest_ops
                 WHERE UPPER(codigo_op) = UPPER(%s)
                """,
                (OP,),
            )
        )
        _require(sigmanest_rows == 0, "A homologação não pode fabricar correlação SigmaNEST.")
        evidence["sigmanest"] = {
            "status": "nao_aplicavel",
            "reason": "a OP não possui cadeia correlacionada no SigmaNEST consultado",
            "rows_created_by_homologation": sigmanest_rows,
            "read_only": True,
        }

        operation = visible[0]
        context = {
            "op": OP,
            "setor": "Corte",
            "recurso": "Laser Ensis 3015",
            "operacao": operation,
        }
        flow = OperatorFlowService(
            db,
            "HOMOLOGACAO ETAPA 7A",
            now_func=_AdvancingClock(),
        )
        # A OP real do Protheus tem ProductionQuantity = 2 e a quantidade
        # planejada é teto de boas + refugo. Para manter as duas evidências que
        # esta homologação existe para produzir — um apontamento parcial com
        # refugo e um fechamento — o refugo entra na parcial e a peça boa
        # fecha a operação. Nenhum número da fixture corporativa é alterado.
        actions = []
        for action, extra in (
            ("Início", {}),
            ("Parada", {"motivo_codigo": STOP_STATUS_CODE}),
            ("Retomar", {}),
            (
                "Finalizado",
                {
                    "pecas_boas": 0,
                    "refugo": 1,
                    "motivo_refugo": SCRAP_REASON,
                    "operadores_cracha": [OPERATOR_BADGE],
                },
            ),
            # A parcial devolve a OP à fila; o posto reabre para encerrar.
            ("Início", {}),
            (
                "Finalizado",
                {"pecas_boas": 1, "operadores_cracha": [OPERATOR_BADGE]},
            ),
        ):
            result = flow.executar(action, **context, **extra)
            _require(result.ok, f"Ação canônica {action!r} falhou: {result.code} {result.message}")
            actions.append({"action": action, "code": result.code, "message": result.message})

        facts = {
            "appointments": int(
                _scalar(
                    db,
                    "SELECT COUNT(*) AS total FROM apontamentos_operacionais WHERE op = %s",
                    (OP,),
                )
            ),
            "operator_events": int(
                _scalar(
                    db,
                    """
                    SELECT COUNT(*) AS total
                      FROM eventos_apontamento_operador e
                      JOIN apontamentos_operacionais a ON a.id = e.apontamento_id
                     WHERE a.op = %s
                    """,
                    (OP,),
                )
            ),
            "resource_events": int(
                _scalar(
                    db,
                    "SELECT COUNT(*) AS total FROM eventos_estado_recurso WHERE referencia_origem LIKE %s",
                    ("evento_apontamento:%",),
                )
            ),
            "history": int(
                _scalar(db, "SELECT COUNT(*) AS total FROM historico WHERE op = %s", (OP,))
            ),
            "good_quantity": int(
                _scalar(
                    db,
                    "SELECT COALESCE(SUM(quantidade), 0) AS total FROM eventos_quantidade_producao WHERE op = %s AND tipo = 'boa'",
                    (OP,),
                )
            ),
            "scrap_quantity": int(
                _scalar(
                    db,
                    "SELECT COALESCE(SUM(quantidade), 0) AS total FROM eventos_quantidade_producao WHERE op = %s AND tipo = 'refugo'",
                    (OP,),
                )
            ),
            "rework_quantity": int(
                _scalar(
                    db,
                    "SELECT COALESCE(SUM(quantidade), 0) AS total FROM eventos_quantidade_producao WHERE op = %s AND tipo = 'retrabalho'",
                    (OP,),
                )
            ),
        }
        _require(facts["appointments"] == 1, "O fluxo criou apontamento paralelo.")
        _require(facts["good_quantity"] == 1, "Quantidade boa não reconciliou.")
        _require(facts["scrap_quantity"] == 1, "Refugo não ficou separado.")
        _require(facts["rework_quantity"] == 0, "Retrabalho foi inferido.")
        evidence["execucao_canonica"] = {"actions": actions, "facts": facts}

        outbox = db.listar_itens_outbound_totvs(production_order=OP, limit=20)
        _require(len(outbox) == 4, "A execução deveria gerar quatro obrigações outbound.")
        event_types = [row["event_type"] for row in outbox]
        _require(event_types.count("production_appointment_terminal") == 1, "Terminal duplicado.")
        terminal_item = next(
            row for row in outbox if row["event_type"] == "production_appointment_terminal"
        )
        terminal_fields = _outbound_fields(terminal_item["payload_xml"])
        _require(terminal_fields["approved_quantity"] == "1", "Terminal não usou as boas reais.")
        _require(terminal_fields["scrap_quantity"] in {None, "0"}, "Terminal contou refugo.")
        _require(terminal_fields["activity_code"] == "99", "Terminal perdeu ActivityCode 99.")
        _require(terminal_fields["machine_code"] == "ALMOX4", "Terminal perdeu ALMOX4.")
        blocked = [
            {
                "event_type": row["event_type"],
                "error_code": row.get("last_error_code"),
                "error_message": row.get("last_error_message"),
            }
            for row in outbox
            if not row.get("payload_xml")
        ]
        _require(not blocked, f"Obrigação outbound ficou sem payload: {blocked}")
        initial_keys = {row["idempotency_key"] for row in outbox}
        initial_hashes = {
            row["idempotency_key"]: hashlib.sha256(row["payload_xml"].encode("utf-8")).hexdigest()
            for row in outbox
        }
        _require(len(initial_keys) == len(outbox), "Obrigações distintas compartilharam identidade.")
        duplicate_terminal = flow.executar(
            "Finalizado",
            **context,
            pecas_boas=1,
            operadores_cracha=[OPERATOR_BADGE],
        )
        _require(not duplicate_terminal.ok, "Operação concluída foi reaberta.")
        _require(
            len(db.listar_itens_outbound_totvs(production_order=OP, limit=20)) == 4,
            "A tentativa repetida criou outra obrigação/terminal.",
        )
        evidence["outbox_initial"] = _outbox_summary(outbox)
        evidence["idempotency"] = {
            "unique_keys": len(initial_keys),
            "duplicate_terminal_attempt": duplicate_terminal.code,
            "outbox_count_after_duplicate": 4,
        }

        offline_worker = TotvsOutboxWorker(
            db,
            gateway=failure_gateway or _offline_gateway(),
            worker_name="etapa7a-offline",
            batch_size=20,
            lease_seconds=30,
        )
        offline_cycle = offline_worker.run_once()
        after_failure = db.listar_itens_outbound_totvs(production_order=OP, limit=20)
        # Ordem causal por OP (F19): só a obrigação mais antiga da OP é
        # tentada; enquanto ela não chegar a SENT, as posteriores esperam em
        # PENDING — nenhuma é perdida, enviada fora de ordem ou vira ERROR.
        statuses = sorted(row["status"] for row in after_failure)
        _require(
            statuses == ["PENDING"] * (len(after_failure) - 1) + ["RETRY"],
            f"Falha não virou RETRY preservando a ordem causal: {statuses}",
        )
        _require(
            {row["idempotency_key"] for row in after_failure} == initial_keys,
            "Retry alterou a identidade lógica.",
        )
        evidence["retry"] = {
            "cycle": offline_cycle.as_dict(),
            "items": _outbox_summary(after_failure),
        }

        _make_due(db)
        abandoned = db.reservar_lote_outbound_totvs(
            worker="etapa7a-worker-abandonado",
            batch_size=1,
            lease_seconds=30,
            now=db._now(),
        )
        _require(len(abandoned) == 1 and abandoned[0]["status"] == "SENDING", "Lease não reservou.")
        abandoned_id = int(abandoned[0]["id"])
        before_restart = {
            row["idempotency_key"]: hashlib.sha256(row["payload_xml"].encode("utf-8")).hexdigest()
            for row in db.listar_itens_outbound_totvs(production_order=OP, limit=20)
        }
        db.close()
        db = Database(
            dsn,
            auto_migrate=False,
            totvs_outbox_config=outbox_config,
        )
        after_restart = {
            row["idempotency_key"]: hashlib.sha256(row["payload_xml"].encode("utf-8")).hexdigest()
            for row in db.listar_itens_outbound_totvs(production_order=OP, limit=20)
        }
        _require(before_restart == after_restart == initial_hashes, "Restart alterou obrigação/payload.")
        recovered = db.recuperar_envios_abandonados_totvs(
            now=db._now() + timedelta(minutes=2)
        )
        _require(any(int(row["id"]) == abandoned_id for row in recovered), "Lease não recuperou SENDING.")
        recovered_item = db.buscar_item_outbound_totvs(abandoned_id)
        _require(recovered_item["status"] == "RETRY", "Item abandonado não voltou para RETRY.")
        evidence["restart_and_lease"] = {
            "payloads_preserved": before_restart == after_restart,
            "abandoned_item_id": abandoned_id,
            "recovered": len(recovered),
            "item": _outbox_summary([recovered_item])[0],
        }

        if delivery_gateway is not None:
            _make_due(db)
            online_worker = TotvsOutboxWorker(
                db,
                gateway=delivery_gateway,
                worker_name="etapa7a-online",
                batch_size=20,
                lease_seconds=30,
            )
            # Um item por OP por ciclo (F19): um ciclo por obrigação pendente.
            online_cycles = []
            for _ in range(len(initial_keys)):
                online_cycles.append(online_worker.run_once())
                _make_due(db)
            final_rows = db.listar_itens_outbound_totvs(production_order=OP, limit=20)
            _require(all(row["status"] == "SENT" for row in final_rows), "Nem toda obrigação chegou a SENT.")
            _require(
                {row["idempotency_key"] for row in final_rows} == initial_keys,
                "Entrega criou nova identidade.",
            )
            duplicate_cycle = online_worker.run_once()
            _require(duplicate_cycle.reserved == 0, "Item SENT foi processado de novo.")
            evidence["delivery"] = {
                "executed": True,
                "kind": delivery_kind,
                "cycles": [cycle.as_dict() for cycle in online_cycles],
                "items": _outbox_summary(final_rows),
                "duplicate_cycle_reserved": duplicate_cycle.reserved,
            }
        else:
            evidence["delivery"] = {
                "executed": False,
                "kind": "nao_executado",
                "reason": (
                    "WSPCP de negócio não autorizado nesta execução; use --send com "
                    "as confirmações literais após validar uma OP descartável."
                ),
                "items": _outbox_summary(
                    db.listar_itens_outbound_totvs(production_order=OP, limit=20)
                ),
            }

        evidence["final_metrics"] = json.loads(
            json.dumps(db.metricas_outbound_totvs(), ensure_ascii=False, default=str)
        )
        evidence["status"] = "confirmado" if delivery_gateway is not None else "parcial"
        return evidence
    finally:
        db.close()
        if not keep_schema:
            with psycopg.connect(base.dsn, autocommit=True) as connection:
                connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--send",
        action="store_true",
        help=(
            "Envia quatro eventos de negócio ao WSPCP TESTE e pode alterar a OP no "
            "Protheus; sem esta opção termina em RETRY."
        ),
    )
    parser.add_argument(
        "--endpoint", default=os.environ.get("GESTOR_TOTVS_OUTBOUND_ENDPOINT", "")
    )
    parser.add_argument(
        "--expected-host",
        default=os.environ.get("GESTOR_TOTVS_OUTBOUND_EXPECTED_HOST", ""),
    )
    parser.add_argument("--confirm-test-environment")
    parser.add_argument("--confirm-business-op")
    parser.add_argument(
        "--keep-schema",
        action="store_true",
        help="Preserva o schema isolado para inspeção manual posterior.",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    try:
        base = load_postgres_config(testing=True)
        gateway = None
        delivery_kind = "nao_executado"
        if args.send:
            _validate_real_delivery(
                base=base,
                endpoint=args.endpoint,
                expected_host=args.expected_host,
                confirmation=args.confirm_test_environment,
                confirmed_op=args.confirm_business_op,
            )
            gateway = _real_gateway(args.endpoint)
            delivery_kind = "wspcp_teste_real"
        evidence = run_homologation(
            base,
            delivery_gateway=gateway,
            delivery_kind=delivery_kind,
            keep_schema=args.keep_schema,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(evidence, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
