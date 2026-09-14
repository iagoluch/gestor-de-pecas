"""Homologação prática da Etapa 6 — outbox, retry e recuperação, no TOTVS TESTE.

Executa três cenários de falha controlada usando um schema PostgreSQL isolado
dentro de ``gestor_pecas_test``. O Gestor é real, o fluxo canônico do operador é
real e o WSPCP é o do TOTVS TESTE. Nada do banco TESTE existente é alterado: o
schema é criado no início e destruído no fim.

```text
A  operador executa -> COMMIT local -> outbox PENDING
   worker com endpoint inacessível -> RETRY (mesma idempotency_key)
   endpoint restaurado -> worker -> WSPCP -> ACK OK -> SENT
B  item reservado e worker "morto" -> SENDING abandonado
   novo processo -> lease expirado -> RETRY -> entrega posterior
C  ProductionAppointment em operação já totalizada -> ACK funcional ERROR
   -> ERROR sem retry infinito
```

Mensagens de negócio transmitidas ao Protheus: **duas**, o mínimo necessário —
um ``StopReport`` (registro de parada de recurso, que não altera quantidade,
`C2_QUJE`, `C2_DATRF` nem estoque) e um ``ProductionAppointment`` que o próprio
Protheus deve recusar por `A680OPTOT`.

Dry-run é o padrão. O envio exige banco, endpoint, host e confirmação literal.
"""

from __future__ import annotations

import argparse
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env", override=False)

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.conninfo import make_conninfo  # noqa: E402

from app.database.config import load_postgres_config  # noqa: E402
from app.database.database import Database  # noqa: E402
from backend.integrations.totvs_wspcp import (  # noqa: E402
    TotvsWspcpClient,
    WSPCP_SOAP_ACTION,
    WspcpClientConfig,
)
from mes.integrations.totvs.errors import TotvsIntegrationError  # noqa: E402
from mes.integrations.totvs.mapper import TotvsProductionOrderMapper  # noqa: E402
from mes.integrations.totvs.outbound_enqueue import OutboundEnqueueConfig  # noqa: E402
from mes.integrations.totvs.outbox import OutboxStatus  # noqa: E402
from mes.integrations.totvs.parser import TotvsMessageParser  # noqa: E402
from mes.integrations.totvs.resource_mapping import TotvsResourceResolver  # noqa: E402
from mes.integrations.totvs.service import (  # noqa: E402
    TotvsProductionOrderIngestionService,
)
from mes.services.totvs_outbox_worker import TotvsOutboxWorker  # noqa: E402


EXPECTED_DATABASE = "gestor_pecas_test"
TEST_CONFIRMATION = "TOTVS_TESTE"
EXPECTED_TEST_ENDPOINT = (
    "https://gtsdo143182.protheus.cloudtotvs.com.br:1465/ws/WSPCP.apw"
)
# Endpoint deliberadamente inacessível: porta descartada da IANA em loopback.
OFFLINE_ENDPOINT = "https://127.0.0.1:9/ws/WSPCP.apw"

FIXTURE = (
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "totvs"
    / "ok_productionorder_20260827120232_a9716901001.xml"
)
OP = "A9716901001"
# Código real do SX5 grupo 44 do TESTE, já homologado na Etapa 5.
STOP_REASON_CODE = "0010"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Etapa 6 — falha controlada no TESTE.")
    parser.add_argument(
        "--send",
        action="store_true",
        help="Transmite ao WSPCP TESTE; sem esta opção nada sai da máquina.",
    )
    parser.add_argument("--endpoint", default=os.environ.get("GESTOR_TOTVS_OUTBOUND_ENDPOINT", ""))
    parser.add_argument(
        "--expected-host", default=os.environ.get("GESTOR_TOTVS_OUTBOUND_EXPECTED_HOST", "")
    )
    parser.add_argument("--confirm-test-environment")
    parser.add_argument(
        "--keep-schema",
        action="store_true",
        help="Preserva o schema isolado para inspeção manual posterior.",
    )
    return parser.parse_args()


def _validate_target(args: argparse.Namespace, database_name: str) -> str:
    if database_name != EXPECTED_DATABASE:
        raise TotvsIntegrationError(
            f"Recusado: banco efetivo {database_name!r}, esperado {EXPECTED_DATABASE!r}."
        )
    if not args.send:
        return ""
    if args.confirm_test_environment != TEST_CONFIRMATION:
        raise TotvsIntegrationError(
            f"Envio recusado: use --confirm-test-environment {TEST_CONFIRMATION}."
        )
    endpoint = str(args.endpoint or "").strip()
    if endpoint.rstrip("/").casefold() != EXPECTED_TEST_ENDPOINT.casefold():
        raise TotvsIntegrationError(
            "Envio recusado: use exatamente a publicação externa WSPCP do TOTVS TESTE."
        )
    expected_host = str(args.expected_host or "").strip().casefold()
    if not expected_host or urlparse(endpoint).hostname.casefold() != expected_host:
        raise TotvsIntegrationError(
            "Envio recusado: hostname diferente do host TESTE aprovado."
        )
    return endpoint


def _client(endpoint: str, *, timeout: float = 30.0) -> TotvsWspcpClient:
    return TotvsWspcpClient(
        WspcpClientConfig(
            endpoint=endpoint,
            service_namespace=os.environ["GESTOR_TOTVS_OUTBOUND_SERVICE_NAMESPACE"],
            timeout_seconds=timeout,
            username=os.environ.get("GESTOR_TOTVS_OUTBOUND_USERNAME") or None,
            password=os.environ.get("GESTOR_TOTVS_OUTBOUND_PASSWORD") or None,
            authentication_mode=os.environ.get("GESTOR_TOTVS_OUTBOUND_AUTH_MODE") or None,
            soap_action=os.environ.get("GESTOR_TOTVS_OUTBOUND_SOAP_ACTION") or WSPCP_SOAP_ACTION,
        )
    )


def _item(row, *, with_payload=False) -> dict:
    if row is None:
        return {}
    data = dict(row)
    payload = data.pop("payload_xml", None)
    if with_payload:
        data["payload_xml"] = payload
    else:
        data["payload_bytes"] = len(payload) if payload else 0
    return json.loads(json.dumps(data, ensure_ascii=False, default=str))


def _seed(db: Database) -> None:
    with db.connection() as connection, connection.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO catalogo_recursos_pcfactory (
                codigo, nome, tipo_setor, habilitado, fonte, sincronizado_em
            ) VALUES (%s, %s, %s, TRUE, 'homologacao etapa 6', CURRENT_TIMESTAMP)
            """,
            (("PLASMA", "Plasma", "Corte"), ("CNC-01", "Centro CNC", "Usinagem")),
        )
    resolver = TotvsResourceResolver(
        known_resource_codes=db.listar_codigos_recursos_totvs(),
        known_resource_sectors=db.listar_setores_recursos_totvs(),
    )
    service = TotvsProductionOrderIngestionService(
        db,
        enabled=True,
        parser=TotvsMessageParser(),
        mapper=TotvsProductionOrderMapper(resolver),
    )
    service.ingest(FIXTURE.read_text(encoding="utf-8"))


def _queue(db: Database, numero: str):
    with db.connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM catalogo_operacoes_op WHERE codigo_op = %s AND numero_operacao = %s",
            (OP, numero),
        )
        operation = dict(cursor.fetchone())
    return db.enfileirar_apontamento_operacional(
        OP,
        "PNT002002003",
        None,
        operation["tipo_setor"],
        operation["codigo_recurso"],
        "HOMOLOGACAO",
        quantidade=10,
        operacao={
            "id": operation["id"],
            "numero_operacao": operation["numero_operacao"],
            "codigo_recurso": operation["codigo_recurso"],
            "produto_codigo": "PNT002002003",
            "produto_descricao": "BRACO ARTICULACAO",
        },
    )


def _ack(item: dict) -> dict:
    return {
        "status": item.get("status"),
        "attempts": item.get("attempts"),
        "idempotency_key": item.get("idempotency_key"),
        "last_http_status": item.get("last_http_status"),
        "last_ack_status": item.get("last_ack_status"),
        "last_delivery_class": item.get("last_delivery_class"),
        "last_error_code": item.get("last_error_code"),
        "last_error_message": item.get("last_error_message"),
        "internal_id": item.get("internal_id"),
        "next_attempt_at": str(item.get("next_attempt_at")),
        "sent_at": str(item.get("sent_at")),
    }


def main() -> int:  # noqa: C901 - roteiro linear de homologação
    args = _arguments()
    base = load_postgres_config(testing=True)
    database_name = str(base.safe_target.get("dbname") or "")
    endpoint = _validate_target(args, database_name)

    schema = "etapa6_" + uuid4().hex[:12]
    with psycopg.connect(base.dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base.dsn, options=f"-c search_path={schema}")

    evidence = {
        "modo": "send" if args.send else "dry-run",
        "banco": database_name,
        "schema_isolado": schema,
        "endpoint_teste": urlparse(endpoint).hostname if endpoint else None,
        "op": OP,
        "cenarios": {},
    }
    config = OutboundEnqueueConfig(
        enabled=True,
        stop_reason_codes={"MANUTENCAO PREVENTIVA": STOP_REASON_CODE},
    )
    db = Database(dsn, totvs_outbox_config=config)
    try:
        _seed(db)
        agora = db._now()

        # ------------------------------------------------------------------
        # Cenário A — TOTVS indisponível não bloqueia o operador
        # ------------------------------------------------------------------
        card = _queue(db, "10")
        inicio = agora - timedelta(hours=3)
        db.transicionar_apontamento_operador(
            card["id"], "producao", "HOMOLOG-ETAPA6", data_hora=inicio
        )
        db.transicionar_apontamento_operador(
            card["id"],
            "parada",
            "HOMOLOG-ETAPA6",
            motivo="Manutencao preventiva",
            data_hora=inicio + timedelta(minutes=20),
        )
        db.transicionar_apontamento_operador(
            card["id"],
            "producao",
            "HOMOLOG-ETAPA6",
            data_hora=inicio + timedelta(minutes=50),
        )
        stop_items = [
            item
            for item in db.listar_itens_outbound_totvs(limit=20)
            if item["event_type"] == "stop_report"
        ]
        if not stop_items:
            raise TotvsIntegrationError("O intervalo de parada não gerou item na outbox.")
        stop = stop_items[0]
        evidence["cenarios"]["A1_commit_local_sem_totvs"] = {
            "apontamento_status": db.buscar_apontamento_operacional(card["id"])["status"],
            "outbox": _item(stop),
            "observacao": (
                "O fluxo do operador terminou no COMMIT local; nenhuma chamada "
                "SOAP participou da transação."
            ),
        }

        # Worker apontado para um endpoint inacessível.
        offline = TotvsOutboxWorker(
            db, gateway=_client(OFFLINE_ENDPOINT, timeout=3.0), worker_name="worker-offline"
        )
        ciclo_offline = offline.run_once()
        depois_offline = db.buscar_item_outbound_totvs(stop["id"])
        evidence["cenarios"]["A2_totvs_offline_gera_retry"] = {
            "ciclo": ciclo_offline.as_dict(),
            "item": _ack(depois_offline),
            "chave_preservada": depois_offline["idempotency_key"] == stop["idempotency_key"],
            "payload_preservado": depois_offline["payload_xml"] == stop["payload_xml"],
        }

        # ------------------------------------------------------------------
        # Cenário B — worker morto no meio do envio
        # ------------------------------------------------------------------
        with db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE totvs_outbox SET next_attempt_at = %s WHERE id = %s",
                (db._now(), stop["id"]),
            )
        reservado = db.reservar_lote_outbound_totvs(
            worker="worker-que-morre", lease_seconds=30
        )
        db.close()

        db = Database(dsn, auto_migrate=False, totvs_outbox_config=config)
        futuro = db._now() + timedelta(minutes=5)
        recuperados = db.recuperar_envios_abandonados_totvs(now=futuro)
        recuperado = db.buscar_item_outbound_totvs(stop["id"])
        evidence["cenarios"]["B_sending_abandonado_recuperado"] = {
            "reservado_como": [_ack(item) for item in reservado],
            "recuperados": len(recuperados),
            "item": _ack(recuperado),
            "chave_preservada": recuperado["idempotency_key"] == stop["idempotency_key"],
        }

        # ------------------------------------------------------------------
        # Cenário A (parte 2) — endpoint restaurado entrega de verdade
        # ------------------------------------------------------------------
        if args.send:
            with db.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE totvs_outbox SET next_attempt_at = %s WHERE id = %s",
                    (db._now(), stop["id"]),
                )
            online = TotvsOutboxWorker(
                db, gateway=_client(endpoint), worker_name="worker-online"
            )
            ciclo_online = online.run_once()
            entregue = db.buscar_item_outbound_totvs(stop["id"])
            evidence["cenarios"]["A3_endpoint_restaurado_entrega"] = {
                "ciclo": ciclo_online.as_dict(),
                "item": _ack(entregue),
                "payload": entregue["payload_xml"],
                "chave_preservada": entregue["idempotency_key"] == stop["idempotency_key"],
            }
        else:
            evidence["cenarios"]["A3_endpoint_restaurado_entrega"] = {
                "executado": False,
                "motivo": "dry-run; use --send para transmitir ao TOTVS TESTE.",
                "payload": stop["payload_xml"],
            }

        # ------------------------------------------------------------------
        # Cenário C — rejeição funcional determinística do Protheus
        # ------------------------------------------------------------------
        # A operação 20 desta OP já foi totalizada no TESTE em 01/09/2026, e a
        # própria OP está encerrada. O Protheus deve recusar o apontamento com
        # A680OPTOT: é a rejeição funcional que precisamos provar sem produzir
        # nenhum movimento novo. A operação 10 continua em processo, de modo que
        # a execução da OP não fecha e nenhum marco terminal é emitido aqui.
        segundo = _queue(db, "20")
        db.transicionar_apontamento_operador(
            segundo["id"], "producao", "HOMOLOG-ETAPA6", data_hora=agora - timedelta(hours=1)
        )
        db.transicionar_apontamento_operador(
            segundo["id"],
            "finalizado",
            "HOMOLOG-ETAPA6",
            quantidade_boa=10,
            data_hora=agora - timedelta(minutes=30),
        )
        appointments = [
            item
            for item in db.listar_itens_outbound_totvs(limit=20)
            if item["event_type"] == "production_appointment"
        ]
        if not appointments:
            raise TotvsIntegrationError("A finalização não gerou ProductionAppointment.")
        appointment = appointments[0]
        if args.send:
            worker = TotvsOutboxWorker(
                db, gateway=_client(endpoint), worker_name="worker-cenario-c"
            )
            worker.run_once()
            recusado = db.buscar_item_outbound_totvs(appointment["id"])
            segundo_ciclo = TotvsOutboxWorker(
                db, gateway=_client(endpoint), worker_name="worker-cenario-c"
            ).run_once()
            evidence["cenarios"]["C_ack_funcional_error"] = {
                "item": _ack(recusado),
                "reservado_em_novo_ciclo": segundo_ciclo.reserved,
                "sem_retry_infinito": (
                    recusado["status"] == OutboxStatus.ERROR.value
                    and segundo_ciclo.reserved == 0
                ),
                "tentativas": db.listar_tentativas_outbound_totvs(appointment["id"]),
            }
        else:
            evidence["cenarios"]["C_ack_funcional_error"] = {
                "executado": False,
                "motivo": "dry-run; use --send para provocar o ACK real.",
                "payload": appointment["payload_xml"],
            }

        evidence["metricas_finais"] = json.loads(
            json.dumps(db.metricas_outbound_totvs(), ensure_ascii=False, default=str)
        )
        print(json.dumps(evidence, ensure_ascii=False, indent=2, default=str))
        return 0
    except TotvsIntegrationError as exc:
        print(
            json.dumps(
                {"status": "error", "code": getattr(exc, "code", "erro"), "message": str(exc)},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        db.close()
        if not args.keep_schema:
            with psycopg.connect(base.dsn, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )


if __name__ == "__main__":
    raise SystemExit(main())
