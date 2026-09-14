"""Teste de carga: 40+ operadores trabalhando ao mesmo tempo, com OPs reais.

Objetivo: reproduzir um turno cheio — cada operador carrega uma OP de
verdade, aperta Início, Parada, Retomar e tenta Finalizar — e registrar
**todo e qualquer erro** que aparecer (não só timeout/pool), para achar
travamentos de ação, exceptions não tratadas e gargalos de conexão antes da
virada para o TOTVS real.

Roda inteiramente contra ``TEST_DATABASE_URL`` (nunca ``DATABASE_URL``), num
schema Postgres isolado e descartável criado só para este teste — o mesmo
padrão de isolamento já usado em ``tests/test_totvs_on_demand.py``
(``OnDemandPostgresBase``). As OPs entram pelo MESMO pipeline de ingestão
TOTVS que a produção usa (``TotvsProductionOrderIngestionService``), não por
INSERT direto — para que o teste exercite o caminho real, erros incluídos.
Nada aqui toca o banco de teste "oficial" nem o real.

A carga é gerada em asyncio nativo, contra a app ASGI real (com o lifespan
rodando de verdade — inclusive os limites de threads configurados em
``backend/api/main.py``), sem passar por rede.

Uso:
    python -m tests.load_test.run_operator_load_test
    python -m tests.load_test.run_operator_load_test --operators 60 --seconds 45
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.operator_sectors import OPERATOR_SECTORS  # noqa: E402
from app.core.resource_mapping import station_resource_code  # noqa: E402
from app.database.config import load_postgres_config  # noqa: E402
from app.database.database import Database, agora_db  # noqa: E402
from backend.api.config import WebSettings  # noqa: E402
from backend.api.main import create_app  # noqa: E402
from mes.integrations.totvs.mapper import TotvsProductionOrderMapper  # noqa: E402
from mes.integrations.totvs.parser import TotvsMessageParser  # noqa: E402
from mes.integrations.totvs.resource_mapping import TotvsResourceResolver  # noqa: E402
from mes.integrations.totvs.service import TotvsProductionOrderIngestionService  # noqa: E402


REPORT_PATH = Path(__file__).with_name("last_run_report.json")
PASSWORD = "carga-2026"
STOP_REASON_CODE = "LOADTEST-STOP"

# Um único ActivityOrder por OP: cada operador recebe uma OP de verdade, já
# apontável no recurso dele, ingerida pelo MESMO parser/mapper do TOTVS real.
XML_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8" ?><TOTVSMessage '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xsi:noNamespaceSchemaLocation="xmlschema/general/events/ProductionOrder_2_004.xsd">'
    '<MessageInformation version="2.004"><UUID>1</UUID><Type>BusinessMessage</Type>'
    "<Transaction>ProductionOrder</Transaction><StandardVersion>1.0</StandardVersion>"
    "<SourceApplication>SIGAPCP</SourceApplication><CompanyId>01</CompanyId>"
    "<BranchId>010004</BranchId><UserId>001114</UserId>"
    '<Product name="MATA650" version="12.1.2510"/>'
    "<GeneratedOn>2026-08-27T12:02:32</GeneratedOn><ContextName>PROTHEUS</ContextName>"
    "<DeliveryType>Sync</DeliveryType></MessageInformation><BusinessMessage>"
    "<BusinessEvent><Entity>ProductionOrder</Entity><Event>upsert</Event>"
    '<Identification><key name="InternalID">01|010004|{op}</key></Identification>'
    "</BusinessEvent><BusinessContent><Number>{op}</Number><Origin />"
    "<ProductionOrderUniqueID>01|010004|{op}</ProductionOrderUniqueID><FatherNumber />"
    "<FatherProductionOrderUniqueID /><ItemCode>{item}</ItemCode><ListOfItemGrids />"
    "<ItemDescription>PECA TESTE DE CARGA</ItemDescription><Type>1</Type>"
    "<IsItemCoproduct /><Quantity>10</Quantity><MinimumQuantity /><MaximumQuantity />"
    "<ReportQuantity>0</ReportQuantity><ApprovedQuantity /><ReworkQuantity />"
    "<ScrapQuantity /><AuxiliarItemCode /><IsStatusOrder />"
    "<UnitOfMeasureCode>UN</UnitOfMeasureCode><RequestOrderCode></RequestOrderCode>"
    "<StatusType /><StatusOrderType>1</StatusOrderType><ProductionLineCode />"
    "<ProductionLineDescription /><PlannerUser /><ReferenceCode />"
    "<ReportOrderType>2</ReportOrderType><AllocationType /><SiteCode />"
    "<WarehouseCode>01</WarehouseCode><EndOrderCPDate /><StartOrderCPDate />"
    "<ReleaseOrderDate /><TimeReleaseQuantity />"
    "<StartOrderDateTime>2026-08-27T00:00:00</StartOrderDateTime><StartOrderQuantity />"
    "<EndOrderDateTime>2026-08-28T00:00:00</EndOrderDateTime><EndOrderQuantity />"
    "<StartEarlierDateTime /><EndLaterDateTime /><AbbreviationProviderName>"
    "</AbbreviationProviderName><CustomerGroupCode /><CustomerRequestCode />"
    "<LastPertNumber /><PertRequestNumber /><LotCode /><MaterialListCode />"
    "<ScriptCode>35</ScriptCode><MaterialCalculationType /><LaborType />"
    "<LaborCostType /><MaterialCostType /><OverheadCostType /><LaborCalculationType />"
    "<OverheadCalculationType /><OverheadType /><ScrapItemCode /><ScrapItemValue />"
    "<BusinessUnitCode /><StockGroupCode /><StockGroupDescription /><FamilyCode />"
    "<FamilyDescription /><NetWeight /><GrossWeight /><DeliveryNumber /><Priority />"
    "<ListOfActivityOrders><ActivityOrder><ProductionOrderNumber>{op}</ProductionOrderNumber>"
    "<ActivityID>{activity_id}</ActivityID><ActivityCode>10</ActivityCode>"
    "<ActivityDescription>{sector}</ActivityDescription><Split>000</Split>"
    "<ItemCode>{item}</ItemCode><ItemDescription>PECA TESTE DE CARGA</ItemDescription>"
    "<ListOfItemGrids /><ActivityType>1</ActivityType>"
    "<WorkCenterCode>{resource}</WorkCenterCode><WorkCenterDescription>{sector}</WorkCenterDescription>"
    "<UnitTimeType>1</UnitTimeType><TimeResource>0.05</TimeResource>"
    "<TimeMachine>0.5</TimeMachine><TimeSetup>0</TimeSetup><ScriptCode>35</ScriptCode>"
    "<EndLaterDateTime /><ResourceQuantity>0</ResourceQuantity><PercentageOverlapValue />"
    "<PercentageScrapValue /><PercentageValue /><LaborCode>MOD</LaborCode>"
    "<UnitItemNumber>1</UnitItemNumber><ProductionQuantity>10</ProductionQuantity>"
    "<ActivityQuantity>10</ActivityQuantity><AlternativeActivityCode />"
    "<UnitActivityCode>UN</UnitActivityCode><ReworkQuantity /><ScrapItemCode />"
    "<ScrapItemValue /><TimePostprocessing /><UsedCapacity /><LoadQuantity />"
    "<StatusType /><StartRealDateTime /><EndRealDateTime /><StartEarlierDateTime />"
    "<OrderReferenceNumber /><IsActivityStart /><IsActivityEnd>true</IsActivityEnd>"
    "<ApprovedQuantity /><ScrapQuantity /><ReportQuantity /><IsLastReport />"
    "<MaterialItemValue /><TreatmentTimeType /><StandardLotQuantity />"
    "<MultipleLotQuantity /><MinimumLotQuantity /><MachineCode>{resource}</MachineCode>"
    "<StartPlanDateTime>2026-08-27T00:00:00</StartPlanDateTime>"
    "<EndPlanDateTime>2026-08-28T00:00:00</EndPlanDateTime><IsSignificantTime />"
    "<ActivityControlCode /><ActivityItemValue /><TimeMOD>0</TimeMOD><TimeIndMES>3</TimeIndMES>"
    "<SecondUnitActivityCode /><SecondUnitActivityFactor /><ListOfActivityOrderTools />"
    "</ActivityOrder></ListOfActivityOrders><ListOfPertOrders /><ListOfMaterialOrders>"
    "</ListOfMaterialOrders><ListOfQuotaActivity /><ListOfRequestOrders /></BusinessContent>"
    "</BusinessMessage></TOTVSMessage>"
)


def _resource_pool() -> list[tuple[str, str, str, str]]:
    """(nivel, setor, recurso_exibido, codigo_canonico_totvs) por posto real.

    Corte fica de fora: usa fila automática, não o Workbench manual. Destaque
    e Montagem ficam de fora: não têm recurso fixo.
    """

    pairs = []
    for sector in OPERATOR_SECTORS:
        if sector.automatic_queue or not sector.resources:
            continue
        for resource in sector.resources:
            canonical = station_resource_code(sector.route, resource) or resource
            pairs.append((sector.level, sector.name, resource, canonical))
    return pairs


def _dedicated_schema(base_dsn: str) -> tuple[str, str]:
    schema = "gestor_loadtest_" + uuid4().hex[:12]
    with psycopg.connect(base_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base_dsn, options=f"-c search_path={schema}")
    return schema, dsn


def _drop_schema(base_dsn: str, schema: str) -> None:
    with psycopg.connect(base_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _seed(db: Database, operator_count: int) -> list[dict]:
    """Motivo de parada, catálogo de recursos, N usuários e N OPs reais (via TOTVS)."""

    with db.connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO catalogo_status_recursos (
                codigo, nome, grupo_codigo, grupo_nome, habilitado, classificacao,
                setup, retrabalho, retorno_automatico, parada_geral, oculto,
                requer_detalhe, requer_comentario, acao_padrao, fonte, sincronizado_em,
                categoria_gerencial, produtivo, planejado, afeta_disponibilidade,
                afeta_performance, afeta_qualidade, atividade_sem_op, requer_causa_raiz
            ) VALUES (
                %s, %s, 'LOADTEST', 'Teste de carga', TRUE, 1,
                FALSE, FALSE, FALSE, FALSE, FALSE, FALSE, FALSE, NULL, 'load_test', %s,
                'parada', FALSE, FALSE, TRUE, FALSE, FALSE, FALSE, FALSE
            )
            """,
            (STOP_REASON_CODE, "Parada — teste de carga", agora_db()),
        )

    pool = _resource_pool()
    assignments = [pool[index % len(pool)] for index in range(operator_count)]

    with db.connection() as connection, connection.cursor() as cursor:
        for _level, sector, _display, canonical in {(a[0], a[1], a[2], a[3]) for a in assignments}:
            cursor.execute(
                """
                INSERT INTO catalogo_recursos_pcfactory
                    (codigo, nome, tipo_setor, habilitado, fonte, sincronizado_em)
                VALUES (%s, %s, %s, TRUE, 'load_test', %s)
                ON CONFLICT (codigo) DO NOTHING
                """,
                (canonical, canonical, sector, agora_db()),
            )

    resolver = TotvsResourceResolver(
        known_resource_codes=db.listar_codigos_recursos_totvs(),
        known_resource_sectors=db.listar_setores_recursos_totvs(),
    )
    ingestion = TotvsProductionOrderIngestionService(
        db, enabled=True, parser=TotvsMessageParser(), mapper=TotvsProductionOrderMapper(resolver),
    )

    operators = []
    ingest_failures = []
    for index, (level, sector, resource, canonical) in enumerate(assignments):
        name = f"Carga {index + 1:03d} — {sector}"
        user_id = db.criar_usuario(name, PASSWORD, level)
        op_code = f"LOADOP{index + 1:04d}"
        xml = XML_TEMPLATE.format(
            op=op_code,
            item=f"ITEM-CARGA-{index + 1:04d}",
            activity_id=f"9{index + 1:06d}",
            sector=sector,
            resource=canonical,
        )
        result = ingestion.ingest(xml)
        if result.activities_projected < 1:
            ingest_failures.append({"op": op_code, "warnings": result.warnings})
        operators.append({
            "id": user_id,
            "username": name,
            "sector": sector,
            "resource": resource,
            "canonical_resource": canonical,
            "op": op_code,
        })
    return operators, ingest_failures


@dataclass
class Sample:
    endpoint: str
    status: int
    ms: float
    code: str | None = None
    transport_error: str | None = None


@dataclass
class Metrics:
    samples: list[Sample] = field(default_factory=list)

    def add(self, sample: Sample) -> None:
        self.samples.append(sample)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))
    return ordered[index]


REQUEST_TIMEOUT_SECONDS = 15.0


async def _timed(metrics: Metrics, endpoint: str, coro) -> httpx.Response | None:
    """Cronometra uma chamada com timeout duro — um travamento vira amostra, não trava o teste."""

    t0 = time.perf_counter()
    try:
        response = await asyncio.wait_for(coro, timeout=REQUEST_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        metrics.add(Sample(endpoint, 0, (time.perf_counter() - t0) * 1000, transport_error="timeout_do_cliente"))
        return None
    except httpx.HTTPError as exc:
        metrics.add(Sample(endpoint, 0, (time.perf_counter() - t0) * 1000, transport_error=str(exc)))
        return None
    ms = (time.perf_counter() - t0) * 1000
    code = None
    if response.status_code >= 400:
        try:
            code = response.json().get("code")
        except Exception:
            code = "<corpo_nao_json>"
    metrics.add(Sample(endpoint, response.status_code, ms, code=code))
    return response


async def _operator_loop(
    app,
    operator: dict,
    settings: WebSettings,
    metrics: Metrics,
    stop_at: float,
    pace_seconds: float,
) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await _timed(
            metrics, "login",
            client.post("/api/v1/auth/login", json={"username": operator["username"], "password": PASSWORD}),
        )
        if response is None or response.status_code != 200:
            return
        csrf = client.cookies.get(settings.csrf_cookie_name, "")
        headers = {"X-CSRF-Token": csrf}
        resource = operator["resource"]
        op = operator["op"]

        # Turno real: carregar o roteiro, Início, Parada, Retomar, tentar
        # Finalizar — nessa ordem, uma vez, como um operador faria.
        await _timed(
            metrics, "carregar_roteiro",
            client.get("/api/v1/operator/operations/" + op, params={"resource": resource}),
        )
        await _timed(
            metrics, "acao_inicio",
            client.post(
                "/api/v1/operator/actions",
                json={"action": "Início", "resource": resource, "op": op, "operation_number": "10"},
                headers=headers,
            ),
        )
        await _timed(metrics, "workbench", client.get("/api/v1/operator/workbench", params={"resource": resource}))
        await asyncio.sleep(pace_seconds)
        await _timed(
            metrics, "acao_parada",
            client.post(
                "/api/v1/operator/actions",
                json={
                    "action": "Parada", "resource": resource, "op": op, "operation_number": "10",
                    "stop_reason_code": STOP_REASON_CODE,
                },
                headers=headers,
            ),
        )
        await asyncio.sleep(pace_seconds)
        await _timed(
            metrics, "acao_retomar",
            client.post(
                "/api/v1/operator/actions",
                json={"action": "Retomar", "resource": resource, "op": op, "operation_number": "10"},
                headers=headers,
            ),
        )
        await asyncio.sleep(pace_seconds)
        await _timed(
            metrics, "acao_finalizar",
            client.post(
                "/api/v1/operator/actions",
                json={
                    "action": "Finalizado", "resource": resource, "op": op, "operation_number": "10",
                    "good": 10, "scrap": 0,
                },
                headers=headers,
            ),
        )

        # Resto do turno: o operador majoritariamente OLHA a tela (polling
        # real do frontend) — isso é o grosso da "coleta de dados" sob carga.
        while time.perf_counter() < stop_at:
            await _timed(metrics, "context", client.get("/api/v1/operator/context"))
            await _timed(metrics, "workbench", client.get("/api/v1/operator/workbench", params={"resource": resource}))
            await _timed(metrics, "history", client.get("/api/v1/operator/history", params={"resource": resource}))
            await asyncio.sleep(pace_seconds)


async def _manager_loop(app, username: str, settings: WebSettings, metrics: Metrics, stop_at: float) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await _timed(
            metrics, "manager_login",
            client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD}),
        )
        if response is None or response.status_code != 200:
            return
        while time.perf_counter() < stop_at:
            await _timed(metrics, "management_overview", client.get("/api/v1/management/overview"))
            await _timed(metrics, "management_sectors", client.get("/api/v1/management/sectors"))
            await asyncio.sleep(1.0)


def _report(metrics: Metrics, *, operator_count: int, seconds: float, pool_max: int, thread_pool: int) -> dict:
    by_endpoint: dict[str, list[Sample]] = {}
    for sample in metrics.samples:
        by_endpoint.setdefault(sample.endpoint, []).append(sample)

    rows = []
    total = 0
    error_breakdown: Counter[tuple[str, int, str]] = Counter()
    transport_errors: Counter[str] = Counter()
    for endpoint, samples in sorted(by_endpoint.items()):
        latencies = [s.ms for s in samples]
        errors = [s for s in samples if s.status == 0 or s.status >= 400]
        total += len(samples)
        for sample in samples:
            if sample.transport_error:
                transport_errors[f"{endpoint}: {sample.transport_error}"] += 1
            elif sample.status >= 400:
                error_breakdown[(endpoint, sample.status, sample.code or "<sem_codigo>")] += 1
        rows.append({
            "endpoint": endpoint,
            "requests": len(samples),
            "ok": len(samples) - len(errors),
            "errors": len(errors),
            "p50_ms": round(_percentile(latencies, 50), 1),
            "p95_ms": round(_percentile(latencies, 95), 1),
            "p99_ms": round(_percentile(latencies, 99), 1),
            "max_ms": round(max(latencies), 1) if latencies else 0.0,
        })

    return {
        "operators_simulated": operator_count,
        "duration_seconds": seconds,
        "pgpool_max_size": pool_max,
        "sync_thread_pool_size": thread_pool,
        "total_requests": total,
        "by_endpoint": rows,
        "errors_by_endpoint_status_code": [
            {"endpoint": ep, "status": status, "code": code, "count": count}
            for (ep, status, code), count in error_breakdown.most_common()
        ],
        "transport_failures": [
            {"description": desc, "count": count} for desc, count in transport_errors.most_common()
        ],
    }


def _print_report(report: dict) -> None:
    print()
    print("=" * 86)
    print(
        f"TESTE DE CARGA — {report['operators_simulated']} operadores, "
        f"{report['duration_seconds']:.0f}s, PGPOOL_MAX_SIZE={report['pgpool_max_size']}, "
        f"thread_pool={report['sync_thread_pool_size']}"
    )
    print("=" * 86)
    header = f"{'endpoint':<18}{'reqs':>7}{'ok':>7}{'erros':>7}{'p50ms':>9}{'p95ms':>9}{'p99ms':>9}{'maxms':>9}"
    print(header)
    print("-" * len(header))
    for row in report["by_endpoint"]:
        print(
            f"{row['endpoint']:<18}{row['requests']:>7}{row['ok']:>7}{row['errors']:>7}"
            f"{row['p50_ms']:>9}{row['p95_ms']:>9}{row['p99_ms']:>9}{row['max_ms']:>9}"
        )
    print("-" * len(header))
    print(f"Total: {report['total_requests']} requisições.")

    print()
    if report["transport_failures"]:
        print("FALHAS DE TRANSPORTE (timeout do cliente, ação travou/não respondeu no prazo):")
        for row in report["transport_failures"]:
            print(f"  {row['count']:>5}x  {row['description']}")
    else:
        print("Nenhuma ação travou: toda requisição recebeu resposta dentro do timeout de "
              f"{REQUEST_TIMEOUT_SECONDS:.0f}s.")

    print()
    if report["errors_by_endpoint_status_code"]:
        print("ERROS POR ENDPOINT / STATUS / CÓDIGO (toda ocorrência, sem filtro):")
        for row in report["errors_by_endpoint_status_code"]:
            print(f"  {row['count']:>5}x  {row['endpoint']:<18} HTTP {row['status']}  {row['code']}")
    else:
        print("Nenhum erro HTTP em nenhum endpoint.")

    print()
    real_bugs = [
        row for row in report["errors_by_endpoint_status_code"]
        if row["status"] >= 500 or row["code"] in {"internal_error", "database_unavailable"}
    ]
    if real_bugs:
        print("PONTO CRÍTICO — parecem falhas reais de sistema (5xx / erro interno):")
        for row in real_bugs:
            print(f"  {row['count']:>5}x  {row['endpoint']:<18} HTTP {row['status']}  {row['code']}")
    else:
        print("Nenhum 5xx / erro interno — os erros observados (se houver) são recusas de "
              "regra de negócio (409/403/422), não falhas de sistema.")


async def _run(args: argparse.Namespace) -> None:
    base = load_postgres_config(testing=True)
    schema, dsn = _dedicated_schema(base.dsn)
    print(f"Schema isolado criado em TEST_DATABASE_URL: {schema}")

    db = Database(dsn)
    try:
        operators, ingest_failures = _seed(db, args.operators)
        if ingest_failures:
            print(f"AVISO: {len(ingest_failures)} OP(s) de teste não ingeriram corretamente:")
            for failure in ingest_failures[:5]:
                print(f"  {failure['op']}: {failure['warnings']}")
        manager_name = "Gestor Carga"
        db.criar_usuario(manager_name, PASSWORD, "gestor")

        settings = WebSettings.from_env(environ={
            "GESTOR_WEB_ENV": "test",
            "GESTOR_WEB_SESSION_SECRET": uuid4().hex + uuid4().hex,
            "GESTOR_WEB_THREAD_POOL_SIZE": str(args.thread_pool),
        })
        app = create_app(settings=settings, database_factory=lambda: db)

        metrics = Metrics()
        pool_max = getattr(getattr(db, "_pool", None).config, "max_pool_size", None)

        print(
            f"Disparando {len(operators)} operadores + {args.managers} gestores por "
            f"{args.seconds:.0f}s contra o pool Postgres (max_size={pool_max}, "
            f"thread_pool={args.thread_pool})..."
        )
        async with app.router.lifespan_context(app):
            stop_at = time.perf_counter() + args.seconds
            tasks = [
                _operator_loop(app, operator, settings, metrics, stop_at, args.pace)
                for operator in operators
            ]
            tasks += [
                _manager_loop(app, manager_name, settings, metrics, stop_at)
                for _ in range(args.managers)
            ]
            await asyncio.gather(*tasks)

        report = _report(
            metrics,
            operator_count=len(operators),
            seconds=args.seconds,
            pool_max=pool_max,
            thread_pool=args.thread_pool,
        )
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _print_report(report)
        print(f"Relatório completo: {REPORT_PATH.relative_to(ROOT)}")
    finally:
        db.close()
        _drop_schema(base.dsn, schema)
        print(f"Schema isolado removido: {schema}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operators", type=int, default=40, help="Operadores simultâneos (padrão: 40)")
    parser.add_argument("--managers", type=int, default=5, help="Gestores simultâneos olhando dashboards")
    parser.add_argument("--seconds", type=float, default=45.0, help="Duração da carga sustentada")
    parser.add_argument("--pace", type=float, default=1.0, help="Pausa entre ações/ciclos de cada operador (s)")
    parser.add_argument(
        "--thread-pool", type=int, default=100,
        help="GESTOR_WEB_THREAD_POOL_SIZE simulado (padrão: 100, o default de produção)",
    )
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
