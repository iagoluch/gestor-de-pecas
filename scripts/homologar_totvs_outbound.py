"""Monta e, opcionalmente, envia um fato canônico ao WSPCP do TOTVS TESTE.

Dry-run é o padrão. Não existe varredura automática, worker, retry ou outbox.
O envio exige confirmações independentes do banco e do host TESTE.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env", override=False)

from app.database import Database  # noqa: E402
from backend.integrations.totvs_wspcp import (  # noqa: E402
    TotvsWspcpClient,
    WSPCP_SOAP_ACTION,
    WspcpClientConfig,
)
from mes.integrations.totvs.errors import TotvsIntegrationError  # noqa: E402
from mes.integrations.totvs.outbound_service import TotvsOutboundService  # noqa: E402


EXPECTED_DATABASE = "gestor_pecas_test"
TEST_CONFIRMATION = "TOTVS_TESTE"
EXPECTED_TEST_ENDPOINT = (
    "https://gtsdo143182.protheus.cloudtotvs.com.br:1465/ws/WSPCP.apw"
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run/envio controlado ProductionAppointment ou StopReport."
    )
    parser.add_argument("--event-id", type=int)
    parser.add_argument(
        "--terminal-op",
        help="Emite o marco terminal do roteiro TOTVS da OP informada.",
    )
    parser.add_argument(
        "--contract",
        choices=("productionappointment", "stopreport"),
        required=True,
    )
    parser.add_argument("--waste-code", help="Código de refugo TOTVS comprovado.")
    parser.add_argument("--stop-reason-code", help="Código SX5/44 comprovado no TOTVS TESTE.")
    parser.add_argument(
        "--allow-zero-quantity",
        action="store_true",
        help="Permite tentativa controlada de início com quantidade zero.",
    )
    parser.add_argument("--send", action="store_true", help="Transmite ao WSPCP; sem esta opção é dry-run.")
    parser.add_argument(
        "--endpoint",
        default=os.environ.get("GESTOR_TOTVS_OUTBOUND_ENDPOINT", ""),
        help="URL TESTE terminada em /WSPCP.apw.",
    )
    parser.add_argument(
        "--expected-host",
        default=os.environ.get("GESTOR_TOTVS_OUTBOUND_EXPECTED_HOST", ""),
        help="Hostname exato previamente aprovado como TOTVS TESTE.",
    )
    parser.add_argument(
        "--confirm-test-environment",
        help=f"No envio, informar literalmente {TEST_CONFIRMATION}.",
    )
    parser.add_argument(
        "--insecure-test-tls",
        action="store_true",
        help="Somente TESTE: desativa validação TLS quando a infraestrutura usar certificado interno.",
    )
    return parser.parse_args()


def _message(database: Database, args: argparse.Namespace):
    service = TotvsOutboundService(database)
    if args.terminal_op:
        if args.contract != "productionappointment":
            raise TotvsIntegrationError(
                "O marco terminal é um ProductionAppointment."
            )
        milestone, message = service.build_terminal_production_appointment(
            args.terminal_op
        )
        if (
            milestone.execution_finished_at is not None
            and milestone.execution_finished_at
            > datetime.now().replace(microsecond=0) + timedelta(minutes=5)
        ):
            raise TotvsIntegrationError(
                "Conclusão possui timestamp futuro e não pode ser usada em homologação real."
            )
        return milestone, message
    if args.event_id is None:
        raise TotvsIntegrationError("Informe --event-id ou --terminal-op.")
    if args.contract == "productionappointment":
        event, message = service.build_production_appointment(
            args.event_id,
            waste_code=args.waste_code,
            allow_zero_quantity=args.allow_zero_quantity,
        )
    else:
        event, message = service.build_stop_report(
            args.event_id, stop_reason_code=args.stop_reason_code or ""
        )
    if event.event_time > datetime.now().replace(microsecond=0) + timedelta(minutes=5):
        raise TotvsIntegrationError(
            "Evento possui timestamp futuro e não pode ser usado em homologação real."
        )
    return event, message


def _validate_send_target(database: Database, args: argparse.Namespace) -> str:
    database_name = str((database.safe_target or {}).get("dbname") or "").strip()
    if database_name != EXPECTED_DATABASE:
        raise TotvsIntegrationError(
            f"Envio recusado: banco efetivo {database_name!r}, esperado {EXPECTED_DATABASE!r}."
        )
    if args.confirm_test_environment != TEST_CONFIRMATION:
        raise TotvsIntegrationError(
            f"Envio recusado: use --confirm-test-environment {TEST_CONFIRMATION}."
        )
    endpoint = str(args.endpoint or "").strip()
    parsed = urlparse(endpoint)
    expected_host = str(args.expected_host or "").strip().casefold()
    if endpoint.rstrip("/").casefold() != EXPECTED_TEST_ENDPOINT.casefold():
        raise TotvsIntegrationError(
            "Envio recusado: use exatamente a publicação externa WSPCP do TOTVS TESTE na porta 1465."
        )
    if not expected_host or parsed.hostname.casefold() != expected_host:
        raise TotvsIntegrationError(
            "Envio recusado: o hostname não coincide exatamente com o host TESTE aprovado."
        )
    if not str(os.environ.get("GESTOR_TOTVS_OUTBOUND_SERVICE_NAMESPACE") or "").strip():
        raise TotvsIntegrationError(
            "Envio recusado: configure o namespace exatamente como publicado no WSDL TESTE."
        )
    return endpoint


def main() -> int:
    args = _arguments()
    os.environ["GESTOR_EXPECTED_DATABASE"] = EXPECTED_DATABASE
    database = Database(auto_migrate=False)
    try:
        event, message = _message(database, args)
        if args.terminal_op:
            fato = {
                "kind": "marco_terminal",
                "production_order": event.production_order,
                "terminal_operation": event.terminal_operation,
                "terminal_resource": event.terminal_resource_code,
                "terminal_activity_id": event.terminal_activity_id,
                "last_operation": event.last_operation,
                "good_quantity": str(event.last_operation_good_quantity),
                "scrap_quantity": str(event.last_operation_scrap_quantity),
                "rework_quantity": str(event.last_operation_rework_quantity),
                "planned_quantity": str(event.planned_quantity),
                "pointable_operations": event.pointable_operations,
                "concluded_operations": event.concluded_operations,
                "timestamp": (
                    event.execution_finished_at.isoformat()
                    if event.execution_finished_at
                    else None
                ),
            }
        else:
            fato = {
                "id": event.event_id,
                "type": event.state,
                "production_order": event.production_order,
                "operation": event.operation,
                "resource": event.resource_code,
                "good_quantity": str(event.good_quantity),
                "scrap_quantity": str(event.scrap_quantity),
                "rework_quantity": str(event.rework_quantity),
                "timestamp": event.event_time.isoformat(),
            }
        evidence = {
            "mode": "send" if args.send else "dry-run",
            "database": str((database.safe_target or {}).get("dbname") or ""),
            "contract": args.contract,
            "event": fato,
            "idempotency_key": message.idempotency_key,
            "transaction": message.transaction,
            "payload": message.xml,
        }
        if not args.send:
            print(json.dumps(evidence, ensure_ascii=False, indent=2))
            return 0

        endpoint = _validate_send_target(database, args)
        client = TotvsWspcpClient(
            WspcpClientConfig(
                endpoint=endpoint,
                timeout_seconds=float(os.environ.get("GESTOR_TOTVS_OUTBOUND_TIMEOUT_SECONDS", "30")),
                username=os.environ.get("GESTOR_TOTVS_OUTBOUND_USERNAME") or None,
                password=os.environ.get("GESTOR_TOTVS_OUTBOUND_PASSWORD") or None,
                authentication_mode=os.environ.get("GESTOR_TOTVS_OUTBOUND_AUTH_MODE") or None,
                soap_action=os.environ.get("GESTOR_TOTVS_OUTBOUND_SOAP_ACTION")
                or WSPCP_SOAP_ACTION,
                service_namespace=os.environ["GESTOR_TOTVS_OUTBOUND_SERVICE_NAMESPACE"],
                verify_tls=not args.insecure_test_tls,
            )
        )
        ack = client.send(message)
        evidence["endpoint_host"] = urlparse(endpoint).hostname
        evidence["ack"] = {
            "status": ack.status,
            "accepted": ack.accepted,
            "already_processed": ack.already_processed,
            "transaction": ack.transaction,
            "messages": list(ack.messages),
            "internal_ids": list(ack.internal_ids),
            "raw_xml": ack.raw_xml,
            "http_status": ack.http_status,
            "raw_soap": ack.raw_soap,
        }
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        return 0 if ack.accepted else 1
    except (TotvsIntegrationError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_code": getattr(exc, "code", "homologation_error"),
                    "message": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
