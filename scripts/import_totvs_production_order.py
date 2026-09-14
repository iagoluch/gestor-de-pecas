"""Importa XML ProductionOrder usando o pipeline real e somente PostgreSQL TESTE."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import Database  # noqa: E402
from backend.api.config import WebSettings  # noqa: E402
from mes.integrations.totvs.errors import TotvsIntegrationError  # noqa: E402
from mes.integrations.totvs.service import build_totvs_ingestion_service  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Importa um ou mais TOTVSMessage/ProductionOrder no banco TESTE."
    )
    parser.add_argument("xml", nargs="+", type=Path, help="Caminho do XML UTF-8")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    settings = WebSettings.from_env()
    if not settings.totvs_enabled:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_code": "totvs_integration_disabled",
                    "message": "Defina GESTOR_TOTVS_ENABLED=true para a importação controlada.",
                },
                ensure_ascii=False,
            )
        )
        return 2

    database = Database()
    try:
        database_name = str((database.safe_target or {}).get("dbname") or "")
        if "test" not in database_name.casefold():
            raise RuntimeError("Importação recusada: o banco ativo não é explicitamente de teste.")
        service = build_totvs_ingestion_service(database, settings)
        exit_code = 0
        for path in args.xml:
            try:
                payload = path.resolve(strict=True).read_bytes()
                result = service.ingest(payload)
                print(
                    json.dumps(
                        {
                            "transaction": result.transaction,
                            "external_id": result.external_id,
                            "status": result.status,
                            "action": result.action,
                            "activities_parsed": result.activities_parsed,
                            "activities_projected": result.activities_projected,
                            "warnings": list(result.warnings),
                            "idempotent": result.idempotent,
                        },
                        ensure_ascii=False,
                    )
                )
            except (OSError, TotvsIntegrationError, RuntimeError) as exc:
                print(
                    json.dumps(
                        {
                            "file": path.name,
                            "status": "error",
                            "error_code": getattr(exc, "code", "import_error"),
                            "message": str(exc),
                        },
                        ensure_ascii=False,
                    )
                )
                exit_code = 1
        return exit_code
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())

