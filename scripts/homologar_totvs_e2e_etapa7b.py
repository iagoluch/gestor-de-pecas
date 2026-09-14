"""Etapa 7B — homologação E2E real da OP sob demanda no TOTVS TESTE.

O instrumento fecha somente a lacuna deixada pela 7A:

    MISS local -> OrderProvisioningService -> GPOPSYNC/MATI650 real
    -> TotvsProductionOrderIngestionService -> PostgreSQL -> consulta operacional

Não executa apontamento, não envia outbound, não apaga a OP para fabricar MISS
e não contém fixture/replay do ProductionOrder. A credencial é lida do ambiente
e nunca é impressa. O alvo aceito é exclusivamente ``gestor_pecas_test``.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

import httpx
import psycopg


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env", override=False)

from app.database.database import Database  # noqa: E402
from backend.api.config import WebSettings  # noqa: E402
from mes.integrations.totvs.on_demand_gateway import (  # noqa: E402
    ProtheusOnDemandRequestGateway,
    build_order_provisioning_service,
)
from mes.integrations.totvs.parser import TotvsMessageParser  # noqa: E402
from mes.services.operator_flow import OperatorFlowService  # noqa: E402


EXPECTED_DATABASE = "gestor_pecas_test"
EXPECTED_ENDPOINT = (
    "https://gtsdo143182.protheus.cloudtotvs.com.br:1467/"
    "rest/GESTORPECASPO/gestorpecas/v1/production-order"
)
COMPANY_ID = "01"
BRANCH_ID = "010004"
OP = "00615903001"
MATRIX_BRANCH_ID = "010001"
MATRIX_OP = "10795102002"


class Etapa7BHomologationError(RuntimeError):
    """Falha objetiva de um critério de aceite da homologação."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Etapa7BHomologationError(message)


class RecordingTransport(httpx.BaseTransport):
    """Registra metadados seguros e delega o tráfego ao transporte HTTP real."""

    def __init__(self, *, verify_tls: bool):
        self._inner = httpx.HTTPTransport(verify=verify_tls)
        self.calls: list[dict] = []
        self._closed = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8"))
        response = self._inner.handle_request(request)
        self.calls.append(
            {
                "method": request.method,
                "url": str(request.url),
                "host": request.url.host,
                "path": request.url.path,
                "json": payload,
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type"),
            }
        )
        return response

    def close(self) -> None:
        # Cada chamada do gateway cria um ``httpx.Client`` curto, que chama
        # ``close`` ao sair. O mesmo gravador precisa sobreviver para observar
        # a consulta matriz posterior.
        return

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._inner.close()


def _rows(db: Database, query: str, params=()) -> list[dict]:
    with db.connection() as connection, connection.cursor() as cursor:
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def _scalar(db: Database, query: str, params=()):
    rows = _rows(db, query, params)
    _require(bool(rows), f"Consulta sem resultado: {query[:80]}")
    return next(iter(rows[0].values()))


def _database_name(dsn: str) -> str:
    return str(psycopg.conninfo.conninfo_to_dict(dsn).get("dbname") or "")


def _json_safe(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Tipo não serializável: {type(value).__name__}")


def _counts(db: Database, op: str, *, company: str, branch: str) -> dict:
    external_id = f"{company}|{branch}|{op}"
    return {
        "catalogo_pcp_ops": int(
            _scalar(db, "SELECT COUNT(*) AS total FROM catalogo_pcp_ops WHERE codigo_op=%s", (op,))
        ),
        "catalogo_operacoes_op": int(
            _scalar(
                db,
                "SELECT COUNT(*) AS total FROM catalogo_operacoes_op WHERE codigo_op=%s",
                (op,),
            )
        ),
        "totvs_integration_messages": int(
            _scalar(
                db,
                "SELECT COUNT(*) AS total FROM totvs_integration_messages WHERE external_id=%s",
                (external_id,),
            )
        ),
        "totvs_op_sync_requests": int(
            _scalar(
                db,
                "SELECT COUNT(*) AS total FROM totvs_op_sync_requests WHERE codigo_op=%s",
                (op,),
            )
        ),
        "totvs_outbox": int(
            _scalar(
                db,
                "SELECT COUNT(*) AS total FROM totvs_outbox WHERE production_order=%s",
                (op,),
            )
        ),
        "apontamentos_operacionais": int(
            _scalar(
                db,
                "SELECT COUNT(*) AS total FROM apontamentos_operacionais WHERE op=%s",
                (op,),
            )
        ),
        "eventos_apontamento_operador": int(
            _scalar(
                db,
                """
                SELECT COUNT(*) AS total
                  FROM eventos_apontamento_operador evento
                  JOIN apontamentos_operacionais apontamento
                    ON apontamento.id = evento.apontamento_id
                 WHERE apontamento.op = %s
                """,
                (op,),
            )
        ),
        "eventos_quantidade_producao": int(
            _scalar(
                db,
                "SELECT COUNT(*) AS total FROM eventos_quantidade_producao WHERE op=%s",
                (op,),
            )
        ),
        "historico": int(
            _scalar(db, "SELECT COUNT(*) AS total FROM historico WHERE op=%s", (op,))
        ),
    }


def _inbox(db: Database, external_id: str) -> dict:
    rows = _rows(
        db,
        """
        SELECT payload_hash, transaction, entity, event, external_id, company_id,
               branch_id, source_application, generated_on, received_at,
               processed_at, status, result_action, warnings,
               activities_parsed, activities_projected, payload_raw
          FROM totvs_integration_messages
         WHERE external_id = %s
         ORDER BY id DESC
         LIMIT 1
        """,
        (external_id,),
    )
    _require(len(rows) == 1, "ProductionOrder não chegou à inbox canônica.")
    return rows[0]


def _projected_operations(db: Database, op: str) -> list[dict]:
    return _rows(
        db,
        """
        SELECT numero_operacao, descricao_operacao, codigo_recurso, tipo_setor,
               ordem, ativo, marco_terminal, totvs_activity_id,
               totvs_work_center_code, totvs_machine_code
          FROM catalogo_operacoes_op
         WHERE codigo_op = %s
         ORDER BY ordem, id
        """,
        (op,),
    )


def _header(db: Database, op: str) -> dict:
    rows = _rows(
        db,
        """
        SELECT codigo_op, produto_codigo, produto_descricao, quantidade, unidade,
               status_pcp, filial, local_estoque, roteiro, ativo,
               totvs_unique_id, totvs_company_id, totvs_branch_id,
               totvs_generated_on, totvs_source_application, sincronizado_em
          FROM catalogo_pcp_ops
         WHERE codigo_op = %s
        """,
        (op,),
    )
    _require(len(rows) == 1, "Cabeçalho canônico da OP não foi projetado uma única vez.")
    return rows[0]


def _raw_route(parsed) -> list[dict]:
    return [
        {
            "activity_code": activity.activity_code,
            "activity_description": activity.activity_description,
            "work_center_code": activity.work_center_code,
            "machine_code": activity.machine_code,
            "is_activity_end": activity.is_activity_end,
        }
        for activity in parsed.production_order.activities
    ]


def _validate_configuration(settings: WebSettings, gateway) -> dict:
    config = gateway.config
    endpoint = str(config.endpoint or "").strip().rstrip("/")
    expected = EXPECTED_ENDPOINT.rstrip("/")
    _require(endpoint == expected, "GESTOR_TOTVS_OP_PULL_ENDPOINT diverge do endpoint aprovado.")
    _require(config.delivery == "inline", "O GPOPSYNC precisa operar em modo inline.")
    _require(bool(config.username) and bool(config.password), "Credencial de pull não configurada.")
    _require(settings.totvs_enabled, "A ingestão canônica TOTVS está desabilitada.")
    _require(settings.totvs_op_pull_company_id == COMPANY_ID, "CompanyId configurado diverge.")
    _require(settings.totvs_op_pull_branch_id == BRANCH_ID, "BranchId configurado diverge.")
    parsed_url = urlsplit(endpoint)
    return {
        "endpoint": endpoint,
        "host": parsed_url.hostname,
        "port": parsed_url.port,
        "delivery": config.delivery,
        "company_id": settings.totvs_op_pull_company_id,
        "branch_id": settings.totvs_op_pull_branch_id,
        "credentials_configured": True,
        "tls_verification": bool(config.verify_tls),
    }


def run_main_case(db: Database, settings: WebSettings, gateway, recorder) -> dict:
    provisioning = build_order_provisioning_service(db, settings, gateway=gateway)
    before = _counts(db, OP, company=COMPANY_ID, branch=BRANCH_ID)
    _require(provisioning.provider.lookup_local(OP) is None, "A OP principal já existe localmente.")
    _require(
        all(before[key] == 0 for key in before),
        f"O cenário principal não começou limpo por OP: {before}",
    )
    outbox_total_before = int(_scalar(db, "SELECT COUNT(*) AS total FROM totvs_outbox"))

    result = provisioning.provision(OP)
    _require(result.found and result.status == "sincronizada", f"Provisionamento falhou: {result}")
    _require(result.requested, "O MISS não foi marcado como solicitação remota.")
    _require(len(recorder.calls) == 1, "O MISS principal deve produzir exatamente uma chamada HTTP.")
    call = recorder.calls[0]
    _require(call["method"] == "POST", "O gateway não realizou POST.")
    _require(call["url"].rstrip("/") == EXPECTED_ENDPOINT.rstrip("/"), "URL HTTP divergente.")
    _require(
        call["json"] == {"companyId": COMPANY_ID, "branchId": BRANCH_ID, "number": OP},
        "Corpo JSON enviado ao GPOPSYNC diverge do contrato.",
    )
    _require(call["status_code"] == 200, "GPOPSYNC não respondeu HTTP 200.")
    _require("xml" in str(call["content_type"] or "").casefold(), "Resposta real não foi XML.")

    external_id = f"{COMPANY_ID}|{BRANCH_ID}|{OP}"
    inbox = _inbox(db, external_id)
    parsed = TotvsMessageParser().parse(inbox["payload_raw"])
    order = parsed.production_order
    _require(parsed.metadata.transaction == "ProductionOrder", "Transaction divergente.")
    _require(parsed.metadata.message_version == "2.004", "MessageVersion divergente.")
    _require(parsed.metadata.source_application == "SIGAPCP", "SourceApplication divergente.")
    _require(parsed.metadata.product_name == "MATA650", "Product divergente.")
    _require(parsed.metadata.product_version == "12.1.2510", "ProductVersion divergente.")
    _require(order.production_order_unique_id == external_id, "UniqueID divergente.")
    _require(order.item_code == "IPCX04014041P", "ItemCode divergente.")
    _require(
        order.item_description == "CHAPA FECHAMENTO PALHA 8 (PINTURA COR PRETO GTS)",
        "ItemDescription divergente.",
    )
    _require(order.quantity == Decimal("15"), "Quantity divergente.")
    _require(order.report_quantity == Decimal("0"), "ReportQuantity divergente.")
    _require(order.status_order_type == "1", "StatusOrderType divergente.")

    route = _raw_route(parsed)
    expected_route = [
        ("01", "IMPRESSAO OP", "PCP", "PCP"),
        ("10", "CORTE", "CORTE", "LASER"),
        ("20", "INSPECAO", "CALDER", "INSPEC"),
        ("99", "FINALIZADA", "ALMOX4", "ALMOX4"),
    ]
    actual_route = [
        (
            row["activity_code"],
            row["activity_description"],
            row["work_center_code"],
            row["machine_code"],
        )
        for row in route
    ]
    _require(actual_route == expected_route, f"Roteiro MATI650 divergente: {actual_route}")
    _require(route[-1]["is_activity_end"] is True, "Atividade 99 perdeu IsActivityEnd=true.")

    header = _header(db, OP)
    projected = _projected_operations(db, OP)
    _require(len(projected) == 2, "A regra atual deve projetar LASER e o marco terminal.")
    laser = next((row for row in projected if row["numero_operacao"] == "10"), None)
    terminal = next((row for row in projected if row["numero_operacao"] == "99"), None)
    _require(
        laser is not None
        and laser["codigo_recurso"] == "LASER1"
        and laser["tipo_setor"] == "Corte"
        and laser["ativo"]
        and not laser["marco_terminal"],
        "Alias/mapeamento canônico LASER -> LASER1 regrediu.",
    )
    _require(
        terminal is not None
        and terminal["descricao_operacao"] == "FINALIZADA"
        and terminal["codigo_recurso"] == "ALMOX4"
        and terminal["totvs_machine_code"] == "ALMOX4"
        and terminal["tipo_setor"] is None
        and terminal["marco_terminal"]
        and not terminal["ativo"],
        "O contrato terminal 99/FINALIZADA/ALMOX4 regrediu.",
    )

    visible = OperatorFlowService(db, "HOMOLOGAÇÃO ETAPA 7B").listar_operacoes(OP, "Corte")
    _require(
        len(visible) == 1
        and visible[0]["numero_operacao"] == "10"
        and visible[0]["codigo_recurso"] == "LASER1",
        "Consulta operacional não expôs exclusivamente a operação LASER apontável.",
    )

    after = _counts(db, OP, company=COMPANY_ID, branch=BRANCH_ID)
    _require(after["catalogo_pcp_ops"] == 1, "Cabeçalho não foi projetado uma vez.")
    _require(after["catalogo_operacoes_op"] == 2, "Roteiro projetado divergente.")
    _require(after["totvs_integration_messages"] == 1, "Inbox não recebeu uma mensagem.")
    _require(after["totvs_op_sync_requests"] == 1, "Solicitação de sync não foi auditada.")
    for key in (
        "totvs_outbox",
        "apontamentos_operacionais",
        "eventos_apontamento_operador",
        "eventos_quantidade_producao",
        "historico",
    ):
        _require(after[key] == 0, f"Ingestão criou efeito operacional proibido: {key}={after[key]}")
    outbox_total_after = int(_scalar(db, "SELECT COUNT(*) AS total FROM totvs_outbox"))
    _require(outbox_total_after == outbox_total_before, "A ingestão alterou a outbox global.")

    calls_before_second = len(recorder.calls)
    second = provisioning.provision(OP)
    _require(second.found and second.status == "local", "A segunda consulta não resolveu localmente.")
    _require(len(recorder.calls) == calls_before_second, "A segunda consulta tocou o ERP.")

    return {
        "lookup_inicial": "miss",
        "sync": asdict(result),
        "http_call": call,
        "http_calls_main_case": len(recorder.calls),
        "xml": {
            "payload_sha256": hashlib.sha256(inbox["payload_raw"].encode("utf-8")).hexdigest(),
            "transaction": parsed.metadata.transaction,
            "standard_version": parsed.metadata.standard_version,
            "message_version": parsed.metadata.message_version,
            "source_application": parsed.metadata.source_application,
            "product": parsed.metadata.product_name,
            "product_version": parsed.metadata.product_version,
            "unique_id": order.production_order_unique_id,
            "item_code": order.item_code,
            "item_description": order.item_description,
            "quantity": order.quantity,
            "report_quantity": order.report_quantity,
            "status_order_type": order.status_order_type,
            "route": route,
        },
        "inbox": {key: value for key, value in inbox.items() if key != "payload_raw"},
        "header": header,
        "projected_operations": projected,
        "operator_visible_operations": [
            {
                "numero_operacao": row["numero_operacao"],
                "codigo_recurso": row["codigo_recurso"],
                "tipo_setor": row["tipo_setor"],
                "visual_status": row["visual_status"],
            }
            for row in visible
        ],
        "counts_before": before,
        "counts_after": after,
        "outbox_total_before": outbox_total_before,
        "outbox_total_after": outbox_total_after,
        "second_lookup": asdict(second),
        "http_calls_after_second_lookup": len(recorder.calls),
    }


def inspect_existing_main_case(db: Database, settings: WebSettings, gateway, recorder) -> dict:
    """Reconcilia o resultado da chamada única sem repetir o transporte real."""

    external_id = f"{COMPANY_ID}|{BRANCH_ID}|{OP}"
    counts = _counts(db, OP, company=COMPANY_ID, branch=BRANCH_ID)
    inbox = _inbox(db, external_id)
    parsed = TotvsMessageParser().parse(inbox["payload_raw"])
    header = _header(db, OP)
    projected = _projected_operations(db, OP)
    sync_rows = _rows(
        db,
        """
        SELECT codigo_op, status, attempts, requested_at, finished_at,
               updated_at, error_code
          FROM totvs_op_sync_requests
         WHERE codigo_op = %s
        """,
        (OP,),
    )
    _require(len(sync_rows) == 1, "Auditoria da solicitação principal ausente.")
    sync = sync_rows[0]
    _require(sync["status"] == "DONE" and int(sync["attempts"]) == 1, "Sync principal não ficou DONE/1.")
    elapsed = (sync["finished_at"] - sync["requested_at"]).total_seconds()
    _require(parsed.metadata.transaction == "ProductionOrder", "Transaction divergente.")
    _require(parsed.metadata.message_version == "2.004", "MessageVersion divergente.")
    _require(parsed.metadata.source_application == "SIGAPCP", "SourceApplication divergente.")
    _require(parsed.metadata.product_name == "MATA650", "Product divergente.")
    _require(parsed.metadata.product_version == "12.1.2510", "ProductVersion divergente.")
    _require(parsed.production_order.production_order_unique_id == external_id, "UniqueID divergente.")
    _require(parsed.production_order.item_code == "IPCX04014041P", "ItemCode divergente.")
    _require(parsed.production_order.quantity == Decimal("15"), "Quantity divergente.")
    _require(parsed.production_order.report_quantity == Decimal("0"), "ReportQuantity divergente.")
    _require(len(parsed.production_order.activities) == 4, "Roteiro real não contém quatro atividades.")
    _require(len(projected) == 2, "Projeção principal não contém LASER e terminal.")
    laser = next((row for row in projected if row["numero_operacao"] == "10"), None)
    terminal = next((row for row in projected if row["numero_operacao"] == "99"), None)
    _require(laser and laser["codigo_recurso"] == "LASER1" and laser["ativo"], "LASER regrediu.")
    _require(
        terminal
        and terminal["codigo_recurso"] == "ALMOX4"
        and terminal["tipo_setor"] is None
        and terminal["marco_terminal"]
        and not terminal["ativo"],
        "Terminal 99 regrediu.",
    )
    for key in (
        "totvs_outbox",
        "apontamentos_operacionais",
        "eventos_apontamento_operador",
        "eventos_quantidade_producao",
        "historico",
    ):
        _require(counts[key] == 0, f"Auditoria encontrou efeito operacional: {key}={counts[key]}")
    provisioning = build_order_provisioning_service(db, settings, gateway=gateway)
    calls_before = len(recorder.calls)
    local = provisioning.provision(OP)
    _require(local.status == "local" and local.found, "Consulta repetida não resolveu localmente.")
    _require(len(recorder.calls) == calls_before, "Consulta repetida tocou o ERP.")
    visible = OperatorFlowService(db, "HOMOLOGAÇÃO ETAPA 7B").listar_operacoes(OP, "Corte")
    _require(len(visible) == 1 and visible[0]["numero_operacao"] == "10", "Consulta operacional divergiu.")
    return {
        "evidence_mode": "post_call_reconciliation_without_repeating_http",
        "sync_request": {**sync, "elapsed_seconds": elapsed},
        "inbox": {key: value for key, value in inbox.items() if key != "payload_raw"},
        "xml": {
            "payload_sha256": hashlib.sha256(inbox["payload_raw"].encode("utf-8")).hexdigest(),
            "transaction": parsed.metadata.transaction,
            "message_version": parsed.metadata.message_version,
            "source_application": parsed.metadata.source_application,
            "product": parsed.metadata.product_name,
            "product_version": parsed.metadata.product_version,
            "unique_id": parsed.production_order.production_order_unique_id,
            "item_code": parsed.production_order.item_code,
            "item_description": parsed.production_order.item_description,
            "quantity": parsed.production_order.quantity,
            "report_quantity": parsed.production_order.report_quantity,
            "status_order_type": parsed.production_order.status_order_type,
            "route": _raw_route(parsed),
        },
        "header": header,
        "projected_operations": projected,
        "operator_visible_operations": [
            {
                "numero_operacao": row["numero_operacao"],
                "codigo_recurso": row["codigo_recurso"],
                "tipo_setor": row["tipo_setor"],
                "visual_status": row["visual_status"],
            }
            for row in visible
        ],
        "counts": counts,
        "local_lookup": asdict(local),
        "erp_calls_during_reconciliation": len(recorder.calls) - calls_before,
    }


def run_matrix_case(db: Database, settings: WebSettings, gateway, recorder) -> dict:
    """Observa o caso sem roteiro; não inventa operação nem converte em notFound."""

    matrix_settings = replace(
        settings,
        totvs_op_pull_branch_id=MATRIX_BRANCH_ID,
        # O inline já terminou quando o cabeçalho foi persistido. Reduzir só a
        # espera local torna observável o estado atual sem aguardar 40 s.
        totvs_op_pull_timeout_seconds=2,
        totvs_op_pull_poll_interval_ms=100,
    )
    provisioning = build_order_provisioning_service(db, matrix_settings, gateway=gateway)
    before = _counts(db, MATRIX_OP, company=COMPANY_ID, branch=MATRIX_BRANCH_ID)
    calls_before = len(recorder.calls)
    result = provisioning.provision(MATRIX_OP)
    if before["catalogo_pcp_ops"] == 1:
        _require(result.status == "sem_roteiro", "Cabeçalho sem roteiro não recebeu estado explícito.")
        _require(not result.found and not result.requested, "Caso matriz local não pode ser apontável/remoto.")
        _require(len(recorder.calls) == calls_before, "Caso matriz conhecido voltou a tocar o ERP.")
        external_id = f"{COMPANY_ID}|{MATRIX_BRANCH_ID}|{MATRIX_OP}"
        inbox = _inbox(db, external_id)
        parsed = TotvsMessageParser().parse(inbox["payload_raw"])
        after = _counts(db, MATRIX_OP, company=COMPANY_ID, branch=MATRIX_BRANCH_ID)
        sync = _rows(
            db,
            "SELECT status, attempts, error_code FROM totvs_op_sync_requests WHERE codigo_op=%s",
            (MATRIX_OP,),
        )
        _require(sync and sync[0]["status"] == "DONE", "Solicitação matriz não foi reconciliada para DONE.")
        return {
            "evidence_mode": "post_fix_local_reconciliation_without_repeating_http",
            "sync": asdict(result),
            "xml": {
                "unique_id": parsed.production_order.production_order_unique_id,
                "quantity": parsed.production_order.quantity,
                "report_quantity": parsed.production_order.report_quantity,
                "activities": len(parsed.production_order.activities),
            },
            "header": _header(db, MATRIX_OP),
            "projected_operations": _projected_operations(db, MATRIX_OP),
            "counts_before": before,
            "counts_after": after,
            "sync_request": sync[0],
            "erp_calls_during_reconciliation": len(recorder.calls) - calls_before,
            "current_representation": (
                "OP existente no TOTVS, porém sem roteiro operacional utilizável; "
                "found=false; nenhuma operação inventada"
            ),
        }
    _require(before["catalogo_pcp_ops"] == 0, "Estado inicial inesperado no caso matriz.")
    _require(len(recorder.calls) == calls_before + 1, "Caso matriz não realizou uma chamada real.")
    call = recorder.calls[-1]
    _require(call["status_code"] == 200, "Caso matriz não retornou HTTP 200.")
    _require(call["json"]["branchId"] == MATRIX_BRANCH_ID, "Filial matriz divergente.")
    external_id = f"{COMPANY_ID}|{MATRIX_BRANCH_ID}|{MATRIX_OP}"
    inbox = _inbox(db, external_id)
    parsed = TotvsMessageParser().parse(inbox["payload_raw"])
    after = _counts(db, MATRIX_OP, company=COMPANY_ID, branch=MATRIX_BRANCH_ID)
    _require(parsed.production_order.number == MATRIX_OP, "OP matriz divergente.")
    _require(parsed.production_order.quantity == Decimal("14"), "Quantity da OP matriz divergente.")
    _require(len(parsed.production_order.activities) == 0, "MATI650 deveria devolver roteiro vazio.")
    _require(after["catalogo_pcp_ops"] == 1, "Cabeçalho matriz não foi preservado.")
    _require(after["catalogo_operacoes_op"] == 0, "Gestor inventou roteiro para a OP matriz.")
    _require(after["totvs_outbox"] == 0 and after["apontamentos_operacionais"] == 0, "Caso matriz criou execução.")
    _require(result.status != "nao_encontrada", "OP existente sem roteiro foi confundida com inexistente.")
    return {
        "sync": asdict(result),
        "http_call": call,
        "xml": {
            "unique_id": parsed.production_order.production_order_unique_id,
            "quantity": parsed.production_order.quantity,
            "report_quantity": parsed.production_order.report_quantity,
            "activities": len(parsed.production_order.activities),
        },
        "header": _header(db, MATRIX_OP),
        "projected_operations": _projected_operations(db, MATRIX_OP),
        "counts_before": before,
        "counts_after": after,
        "current_representation": (
            "cabecalho_persistido_sem_roteiro; lookup operacional permanece miss; "
            f"status do provisionamento={result.status}"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verify-matrix",
        action="store_true",
        help="Após o caso principal, observa a OP 10795102002 sem roteiro.",
    )
    parser.add_argument(
        "--inspect-existing-main",
        action="store_true",
        help="Reconcilia a OP principal já importada sem repetir o HTTP real.",
    )
    args = parser.parse_args()

    dsn = str(os.environ.get("TEST_DATABASE_URL") or "").strip()
    _require(bool(dsn), "TEST_DATABASE_URL não configurada.")
    database_name = _database_name(dsn)
    _require(database_name == EXPECTED_DATABASE, f"Banco recusado: {database_name!r}.")

    settings = WebSettings.from_env(os.environ)
    gateway_probe = ProtheusOnDemandRequestGateway.from_env(os.environ)
    _require(gateway_probe is not None, "Gateway de OP sob demanda não configurado.")
    config_evidence = _validate_configuration(settings, gateway_probe)

    recorder = RecordingTransport(verify_tls=gateway_probe.config.verify_tls)
    gateway = ProtheusOnDemandRequestGateway.from_env(os.environ, transport=recorder)
    _require(gateway is not None, "Gateway de OP sob demanda não configurado.")

    db = Database(dsn)
    evidence = {
        "etapa": "7B",
        "database": database_name,
        "configuration": config_evidence,
    }
    try:
        if args.inspect_existing_main:
            evidence["main_case"] = inspect_existing_main_case(
                db, settings, gateway, recorder
            )
        else:
            evidence["main_case"] = run_main_case(db, settings, gateway, recorder)
        if args.verify_matrix:
            evidence["matrix_case"] = run_matrix_case(db, settings, gateway, recorder)
        evidence["erp_calls_total"] = len(recorder.calls)
        evidence["result"] = "APROVADA"
        print(json.dumps(evidence, ensure_ascii=False, indent=2, default=_json_safe))
        return 0
    finally:
        recorder.shutdown()
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
