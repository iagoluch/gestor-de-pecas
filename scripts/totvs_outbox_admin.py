"""Administração e operação manual da outbox outbound TOTVS (Etapa 6).

Nenhuma UI nova foi criada nesta etapa. Este comando cobre a observabilidade
mínima e o reprocessamento controlado exigidos:

```powershell
python scripts\\totvs_outbox_admin.py metricas
python scripts\\totvs_outbox_admin.py listar --status ERROR
python scripts\\totvs_outbox_admin.py tentativas --id 12
python scripts\\totvs_outbox_admin.py reprocessar --id 12
python scripts\\totvs_outbox_admin.py worker --once
```

O worker aqui é o MESMO ``TotvsOutboxWorker`` que roda dentro do backend; o
script apenas o executa fora do processo Web. Nenhum nome de banco é embutido
na lógica: o alvo vem do ``.env`` do ambiente.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import sys
import time


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env", override=False)

from app.database import Database  # noqa: E402
from backend.integrations.totvs_wspcp import TotvsWspcpClient  # noqa: E402
from mes.integrations.totvs.outbox import OutboxStatus  # noqa: E402
from mes.services.totvs_outbox_admin import TotvsOutboxAdminService  # noqa: E402
from mes.services.totvs_outbox_worker import TotvsOutboxWorker  # noqa: E402


# O payload completo não é despejado no terminal por padrão: ele é evidência do
# banco, não saída de console.
_HIDDEN_COLUMNS = ("payload_xml",)


def _plain(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _item(row, *, with_payload=False):
    if row is None:
        return None
    data = {
        key: _plain(value)
        for key, value in dict(row).items()
        if with_payload or key not in _HIDDEN_COLUMNS
    }
    if not with_payload and dict(row).get("payload_xml") is not None:
        data["payload_bytes"] = len(str(dict(row)["payload_xml"]))
    return data


def _print(payload) -> None:
    print(json.dumps(_plain(payload), ensure_ascii=False, indent=2, default=str))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Outbox outbound TOTVS.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("metricas", help="Contagens, item mais antigo e últimas falhas.")

    listar = sub.add_parser("listar", help="Lista itens da fila.")
    listar.add_argument("--status", choices=[item.value for item in OutboxStatus])
    listar.add_argument("--op", help="Filtra por ordem de produção.")
    listar.add_argument("--limit", type=int, default=25)
    listar.add_argument("--com-payload", action="store_true")

    tentativas = sub.add_parser("tentativas", help="Histórico de tentativas de um item.")
    tentativas.add_argument("--id", type=int, required=True)

    reprocessar = sub.add_parser(
        "reprocessar", help="Devolve um item ERROR à fila mantendo a mesma mensagem."
    )
    reprocessar.add_argument("--id", type=int, required=True)
    reprocessar.add_argument("--operador", default="ADMIN")

    worker = sub.add_parser("worker", help="Executa a entrega fora do backend Web.")
    worker.add_argument("--once", action="store_true", help="Um único ciclo.")
    worker.add_argument("--interval", type=float, default=15.0)
    worker.add_argument("--batch-size", type=int, default=10)
    worker.add_argument("--lease-seconds", type=int, default=120)
    worker.add_argument(
        "--dry-run",
        action="store_true",
        help="Reserva e classifica sem gateway configurado; não transmite nada.",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    database = Database(auto_migrate=False)
    try:
        service = TotvsOutboxAdminService(database)
        if args.command == "metricas":
            metrics = service.metrics()
            for key in ("item_pendente_mais_antigo", "ultima_falha", "ultima_entrega_ok"):
                metrics[key] = _item(metrics.get(key))
            _print({"banco": database.safe_target, "metricas": metrics})
            return 0

        if args.command == "listar":
            rows = service.list_items(
                status=args.status, production_order=args.op, limit=args.limit
            )
            _print([_item(row, with_payload=args.com_payload) for row in rows])
            return 0

        if args.command == "tentativas":
            _print(
                {
                    "item": _item(database.buscar_item_outbound_totvs(args.id)),
                    "tentativas": service.attempts(args.id),
                }
            )
            return 0

        if args.command == "reprocessar":
            result = service.reprocess(args.id, operador=args.operador)
            result["item"] = _item(result.get("item"))
            _print(result)
            return 0 if result.get("ok") else 1

        gateway = None if args.dry_run else TotvsWspcpClient.from_env()
        if gateway is None and not args.dry_run:
            _print(
                {
                    "ok": False,
                    "code": "endpoint_nao_configurado",
                    "message": "Configure GESTOR_TOTVS_OUTBOUND_ENDPOINT para transmitir.",
                }
            )
            return 2
        worker = TotvsOutboxWorker(
            database,
            gateway=gateway,
            batch_size=args.batch_size,
            lease_seconds=args.lease_seconds,
        )
        while True:
            cycle = worker.run_once()
            _print({"ciclo": cycle.as_dict(), "worker": worker.worker_name})
            if args.once:
                return 0
            time.sleep(max(1.0, float(args.interval)))
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
