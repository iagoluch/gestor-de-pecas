"""Gera um exemplo factual no banco explicitamente isolado da simulação histórica."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.config import PostgresConfig  # noqa: E402
from app.database.database import Database  # noqa: E402
from backend.api.report_workbook import build_report_workbook  # noqa: E402
from mes.contracts import ReportRequest  # noqa: E402
from mes.services.frontend_facade import FrontendBackendFacade  # noqa: E402
from mes.services.industrial_reports import IndustrialReportService  # noqa: E402
from tests.simulacao_historica_3_meses.seed_simulacao_historica import (  # noqa: E402
    SIMULATED_NOW,
    TARGET_DATABASE,
    _safe_dsns,
)


OUTPUT_DIR = ROOT / "outputs" / "evolucao_inteligencia_2026-08-26"


def main() -> None:
    _source, _common, target_dsn, _maintenance, safe = _safe_dsns()
    if safe["target"]["dbname"].casefold() != TARGET_DATABASE.casefold():
        raise RuntimeError("Geração recusada: banco de simulação inesperado.")
    database = Database(config=PostgresConfig(
        dsn=target_dsn,
        min_pool_size=1,
        max_pool_size=8,
        pool_timeout=15,
    ))
    try:
        with database.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id FROM usuarios
                WHERE ativo IS TRUE AND nivel IN ('gestor', 'admin', 'supervisor')
                ORDER BY id LIMIT 1
                """
            )
            row = cursor.fetchone()
        if not row:
            raise RuntimeError("A simulação não possui gestor autorizado para registrar o exemplo.")
        facade = FrontendBackendFacade(
            database,
            now_func=lambda: SIMULATED_NOW,
            simulation_mode=True,
        )
        service = IndustrialReportService(
            facade,
            database,
            artifact_dir=OUTPUT_DIR,
            workbook_builder=build_report_workbook,
            now_func=lambda: SIMULATED_NOW,
        )
        artifact = service.generate(
            ReportRequest(
                report_type="completo",
                inicio=datetime(2026, 8, 1),
                fim=SIMULATED_NOW,
            ),
            created_by=int(row["id"]),
            source="manual",
            idempotency_key="example:evolucao-inteligencia:2026-08",
        )
        record, path = service.get(artifact["id"], user_id=int(row["id"]))
        print(json.dumps({
            "id": artifact["id"],
            "database": safe["target"]["dbname"],
            "path": str(path),
            "size_bytes": artifact["size_bytes"],
            "worksheet_count": artifact["worksheet_count"],
            "row_count": artifact["row_count"],
            "generation_ms": record["generation_ms"],
            "source": artifact["source"],
        }, ensure_ascii=True, indent=2))
    finally:
        database.close()


if __name__ == "__main__":
    main()
