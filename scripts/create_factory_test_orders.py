"""Projeta OPs de ensaio no banco TESTE usando a ingestão TOTVS canônica.

O XML-base é uma ProductionOrder já recebida no banco de teste. A cópia usa o
mesmo produto e roteiro real; nenhuma tabela operacional é escrita diretamente
e nenhum transporte para o TOTVS é acionado.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
from pathlib import Path
import sys

import psycopg
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.database import Database
from mes.integrations.totvs.mapper import TotvsProductionOrderMapper
from mes.integrations.totvs.parser import TotvsMessageParser
from mes.integrations.totvs.resource_mapping import TotvsResourceResolver
from mes.integrations.totvs.service import TotvsProductionOrderIngestionService


TARGET_DATABASE = "gestor_pecas_test"
SOURCE_OP = "PCMD8201001"
BRANCH = "010004"
COMPANY = "01"


def dsn_from_env() -> str:
    env = dotenv_values(ROOT / ".env")
    dsn = str(env.get("TEST_DATABASE_URL") or "")
    if not dsn:
        raise RuntimeError("TEST_DATABASE_URL ausente.")
    return dsn


def clone_xml(raw: str, source_op: str, new_op: str, activity_seed: int) -> str:
    xml = raw.replace(source_op, new_op)
    stamp = datetime.now().replace(microsecond=0)
    xml = re.sub(r"<GeneratedOn>[^<]*</GeneratedOn>", f"<GeneratedOn>{stamp.isoformat()}</GeneratedOn>", xml)
    xml = re.sub(r"<StartOrderDateTime>[^<]*</StartOrderDateTime>", f"<StartOrderDateTime>{stamp.isoformat()}</StartOrderDateTime>", xml)
    xml = re.sub(r"<EndOrderDateTime>[^<]*</EndOrderDateTime>", f"<EndOrderDateTime>{stamp.isoformat()}</EndOrderDateTime>", xml)
    xml = re.sub(r"<StartPlanDateTime>[^<]*</StartPlanDateTime>", f"<StartPlanDateTime>{stamp.isoformat()}</StartPlanDateTime>", xml)
    xml = re.sub(r"<EndPlanDateTime>[^<]*</EndPlanDateTime>", f"<EndPlanDateTime>{stamp.isoformat()}</EndPlanDateTime>", xml)
    xml = re.sub(r"<MaterialDate>[^<]*</MaterialDate>", stamp.strftime("<MaterialDate>%Y%m%d</MaterialDate>"), xml)
    for index, old in enumerate(re.findall(r"<ActivityID>([^<]*)</ActivityID>", xml)):
        xml = xml.replace(f"<ActivityID>{old}</ActivityID>", f"<ActivityID>{activity_seed + index}</ActivityID>", 1)
    for tag in ("Quantity", "ProductionQuantity", "ActivityQuantity"):
        xml = re.sub(fr"<{tag}>2</{tag}>", f"<{tag}>1</{tag}>", xml)
    return xml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--source-op", default=SOURCE_OP)
    parser.add_argument("--prefix", default=None)
    parser.add_argument("--start-sequence", type=int, default=None)
    args = parser.parse_args()
    if not 1 <= args.count <= 12:
        raise SystemExit("--count deve ficar entre 1 e 12")

    dsn = dsn_from_env()
    source_op = str(args.source_op).strip()
    prefix = str(args.prefix or source_op[:-3]).strip()
    if not source_op or len(source_op) < 4 or not prefix:
        raise SystemExit("--source-op inválida")
    start_sequence = args.start_sequence
    with psycopg.connect(dsn, autocommit=True) as connection:
        actual = connection.execute("SELECT current_database()").fetchone()[0]
        if actual != TARGET_DATABASE:
            raise RuntimeError(f"Banco recusado: {actual!r}")
        source = connection.execute(
            "SELECT payload_raw FROM totvs_integration_messages WHERE external_id = %s ORDER BY id DESC LIMIT 1",
            (f"{COMPANY}|{BRANCH}|{source_op}",),
        ).fetchone()
        if not source:
            raise RuntimeError(f"XML-base não encontrado para {source_op}.")
        existing = {
            row[0]
            for row in connection.execute(
                "SELECT codigo_op FROM catalogo_pcp_ops WHERE codigo_op LIKE %s",
                (f"{prefix}%",),
            )
        }

    db = Database(dsn=dsn, auto_migrate=False)
    try:
        resolver = TotvsResourceResolver(
            known_resource_codes=tuple(db.listar_codigos_recursos_totvs()),
            known_resource_sectors=tuple(db.listar_setores_recursos_totvs()),
        )
        service = TotvsProductionOrderIngestionService(
            db,
            enabled=True,
            parser=TotvsMessageParser(),
            mapper=TotvsProductionOrderMapper(resolver),
        )
        rows = []
        sequence = start_sequence if start_sequence is not None else 2
        activity_seed = 980_000 + (abs(hash(source_op)) % 10_000)
        while len(rows) < args.count:
            op = f"{prefix}{sequence:03d}"
            sequence += 1
            if op in existing:
                continue
            outcome = service.handle_message(clone_xml(source[0], source_op, op, activity_seed))
            activity_seed += 10
            rows.append({
                "op": op,
                "action": outcome.ingestion.action if outcome.ingestion else None,
                "activities_projected": outcome.ingestion.activities_projected if outcome.ingestion else 0,
                "warnings": list(outcome.ingestion.warnings if outcome.ingestion else ()),
            })
            existing.add(op)
        print(json.dumps({"database": TARGET_DATABASE, "source_op": source_op, "created": rows}, ensure_ascii=False, indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
