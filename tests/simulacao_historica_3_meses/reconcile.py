"""Reconcilia a simulação histórica entre SQL, serviços e API Web."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import csv
import json
from pathlib import Path
import secrets
import statistics
import sys
import time

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.config import PostgresConfig  # noqa: E402
from app.database.database import Database  # noqa: E402
from backend.api.config import WebSettings  # noqa: E402
from backend.api.main import create_app  # noqa: E402
from mes.contracts import AnalyticsFilter  # noqa: E402
from mes.services.frontend_facade import FrontendBackendFacade  # noqa: E402
from tests.simulacao_historica_3_meses.seed_simulacao_historica import (  # noqa: E402
    EXPECTED_PATH,
    SEED_TAG,
    SIMULATED_NOW,
    START,
    TARGET_DATABASE,
    _safe_dsns,
)


OUTPUT_PATH = Path(__file__).with_name("actual_results.json")
API_MATRIX_PATH = Path(__file__).with_name("api_matrix.json")
EXPORT_PATH = Path(__file__).with_name("exports") / "dados_analiticos.csv"

MONTHS = {
    "6": (datetime(2026, 6, 1, 6), datetime(2026, 6, 30, 23, 59, 59)),
    "7": (datetime(2026, 7, 1), datetime(2026, 7, 31, 23, 59, 59)),
    "8": (datetime(2026, 8, 1), SIMULATED_NOW),
}

TARGET_RANGES = {
    "6": {"oee": (76, 82), "availability": (86, 92), "performance": (88, 94), "ftt": (96, 99)},
    "7": {"oee": (81, 87), "availability": (90, 95), "performance": (92, 97), "ftt": (97, 99.5)},
    "8": {"oee": (84, 90), "availability": (92, 97), "performance": (94, 98), "ftt": (98, 99.7)},
}


class Checkbook:
    def __init__(self):
        self.items: list[dict] = []

    def check(self, name, actual, expected, *, severity="blocking"):
        passed = actual == expected
        self.items.append({
            "name": name,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "actual": actual,
            "expected": expected,
        })
        return passed

    def close(self, name, actual, expected, *, tolerance=1e-6, severity="blocking"):
        passed = abs(float(actual) - float(expected)) <= tolerance
        self.items.append({
            "name": name,
            "status": "PASS" if passed else "FAIL",
            "severity": severity,
            "actual": actual,
            "expected": expected,
            "tolerance": tolerance,
        })
        return passed

    def truth(self, name, condition, *, detail=None, severity="blocking"):
        return self.check(name, bool(condition), True, severity=severity)


def _database(target_dsn: str) -> Database:
    return Database(config=PostgresConfig(
        dsn=target_dsn,
        min_pool_size=1,
        max_pool_size=12,
        pool_timeout=15,
    ))


def _counts(cursor) -> dict:
    return dict(cursor.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM catalogo_pcp_ops) AS orders,
            (SELECT COUNT(*) FROM catalogo_operacoes_op) AS operations,
            (SELECT COUNT(*) FROM apontamentos_operacionais) AS appointments,
            (SELECT COUNT(*) FROM operadores_apontamento) AS operator_badges,
            (SELECT COUNT(*) FROM eventos_quantidade_producao) AS quantity_events,
            (SELECT COUNT(*) FROM eventos_estado_recurso) AS resource_state_events,
            (SELECT COUNT(*) FROM eventos_apontamento_operador) AS operator_events,
            (SELECT COUNT(*) FROM participacoes_operador) AS participations,
            (SELECT COUNT(*) FROM historico) AS history_events,
            (SELECT COUNT(*) FROM eventos_estado_recurso WHERE tipo_interrupcao = 'fim_turno') AS automatic_shift_interruptions,
            (SELECT COUNT(*) FROM tarefas) AS tasks,
            (SELECT COUNT(*) FROM catalogo_sigmanest_planos_corte) AS plans,
            (SELECT COUNT(*) FROM apontamentos_corte) AS cut_appointments,
            (SELECT COUNT(*) FROM apontamentos_corte WHERE status = 'Finalizado') AS completed_cuttings,
            (SELECT COUNT(*) FROM eventos_destaque_tarefa) AS highlight_events,
            (SELECT COALESCE(SUM(tempo_previsto_segundos), 0) FROM catalogo_sigmanest_planos_corte) AS predicted_cutting_seconds,
            (SELECT COALESCE(SUM(EXTRACT(EPOCH FROM (data_fim - data_inicio))), 0) FROM apontamentos_corte WHERE status = 'Finalizado') AS completed_actual_cutting_seconds,
            (SELECT COUNT(*) FROM inconsistencias_dados) AS data_issues,
            (SELECT COUNT(*) FROM usuarios) AS users
        """
    ).fetchone())


def _month_sql(cursor, start: datetime, end: datetime) -> dict:
    quantity = dict(cursor.execute(
        """
        SELECT
            COALESCE(SUM(quantidade) FILTER (WHERE tipo = 'boa'), 0) AS good,
            COALESCE(SUM(quantidade) FILTER (WHERE tipo = 'refugo'), 0) AS scrap,
            COALESCE(SUM(quantidade) FILTER (WHERE tipo = 'retrabalho'), 0) AS rework
        FROM eventos_quantidade_producao
        WHERE data_hora BETWEEN %s AND %s
        """,
        (start, end),
    ).fetchone())
    facts = dict(cursor.execute(
        """
        SELECT
            COUNT(*) AS orders,
            COALESCE(SUM(p.quantidade), 0) AS planned,
            COALESCE(SUM(c.tempo_medio_segundos * a.quantidade_boa), 0) AS standard_run_seconds
        FROM apontamentos_operacionais a
        LEFT JOIN catalogo_pcp_ops p ON p.codigo_op = a.op
        LEFT JOIN catalogo_operacoes_op c ON c.id = a.catalogo_operacao_id
        WHERE COALESCE(a.data_inicio, a.data_entrada) <= %s
          AND COALESCE(a.data_fim, %s) >= %s
        """,
        (end, SIMULATED_NOW, start),
    ).fetchone())
    base_rows = cursor.execute(
        """
        SELECT categoria,
               COALESCE(SUM(EXTRACT(EPOCH FROM (
                   LEAST(COALESCE(data_fim, %s), %s) - GREATEST(data_inicio, %s)
               ))), 0) AS seconds
        FROM eventos_estado_recurso
        WHERE data_inicio <= %s
          AND COALESCE(data_fim, %s) >= %s
          AND referencia_origem NOT LIKE 'sim3m:conflito:%%'
        GROUP BY categoria
        """,
        (SIMULATED_NOW, end, start, end, SIMULATED_NOW, start),
    ).fetchall()
    totals = defaultdict(float, {row["categoria"]: float(row["seconds"] or 0) for row in base_rows})
    overlaps = cursor.execute(
        """
        SELECT b.categoria,
               COALESCE(SUM(EXTRACT(EPOCH FROM (
                   LEAST(COALESCE(b.data_fim, %s), c.data_fim, %s)
                   - GREATEST(b.data_inicio, c.data_inicio, %s)
               ))), 0) AS seconds
        FROM eventos_estado_recurso b
        JOIN eventos_estado_recurso c
          ON UPPER(c.recurso) = UPPER(b.recurso)
         AND c.referencia_origem LIKE 'sim3m:conflito:%%'
         AND b.referencia_origem NOT LIKE 'sim3m:conflito:%%'
         AND b.data_inicio < c.data_fim
         AND COALESCE(b.data_fim, %s) > c.data_inicio
        WHERE c.data_inicio <= %s
          AND c.data_fim >= %s
          AND b.categoria <> 'parada'
        GROUP BY b.categoria
        """,
        (SIMULATED_NOW, end, start, SIMULATED_NOW, end, start),
    ).fetchall()
    conflict_seconds = 0.0
    for row in overlaps:
        seconds = float(row["seconds"] or 0)
        totals[row["categoria"]] -= seconds
        conflict_seconds += seconds
    totals["desconhecido"] += conflict_seconds
    available = sum(totals[key] for key in (
        "producao", "setup", "retrabalho", "atividade_sem_op",
        "parada", "fila", "desconhecido",
    ))
    worked = sum(totals[key] for key in (
        "producao", "setup", "retrabalho", "atividade_sem_op",
    ))
    operational = available - totals["fila"]
    net = float(facts["standard_run_seconds"] or 0) + sum(
        totals[key] for key in ("setup", "retrabalho", "atividade_sem_op")
    )
    quality_total = sum(int(quantity[key] or 0) for key in ("good", "scrap", "rework"))
    ftt = int(quantity["good"] or 0) / quality_total if quality_total else 0.0
    availability = worked / available if available else 0.0
    performance = net / worked if worked else 0.0
    return {
        "orders": int(facts["orders"] or 0),
        "planned": int(facts["planned"] or 0),
        "good": int(quantity["good"] or 0),
        "scrap": int(quantity["scrap"] or 0),
        "rework": int(quantity["rework"] or 0),
        "seconds": {
            "available": available,
            "worked": worked,
            "production": totals["producao"],
            "setup": totals["setup"],
            "rework": totals["retrabalho"],
            "no_op": totals["atividade_sem_op"],
            "downtime": totals["parada"],
            "queue": totals["fila"],
            "unknown": totals["desconhecido"],
            "standard_run": float(facts["standard_run_seconds"] or 0),
        },
        "kpis": {
            "availability": availability * 100.0,
            "performance": performance * 100.0,
            "ftt": ftt * 100.0,
            "oee": availability * performance * ftt * 100.0,
            "utilization": worked / operational * 100.0 if operational else 0.0,
            "productivity": totals["producao"] / operational * 100.0 if operational else 0.0,
            "ae": net / available * 100.0 if available else 0.0,
        },
    }


def _sql_snapshot(db: Database) -> dict:
    with db.connection() as connection, connection.cursor() as cursor:
        identity = dict(cursor.execute(
            "SELECT current_database() AS database_name, current_setting('transaction_read_only') AS read_only"
        ).fetchone())
        schema_version = int(cursor.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        ).fetchone()["version"])
        counts = _counts(cursor)
        months = {month: _month_sql(cursor, *bounds) for month, bounds in MONTHS.items()}
        current = dict(cursor.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM eventos_estado_recurso WHERE data_fim IS NULL) AS active_resources,
              (SELECT COUNT(*) FROM apontamentos_operacionais WHERE status = 'Aguardando' AND data_inicio IS NULL) AS queued_resources,
              (SELECT COUNT(*) FROM apontamentos_corte WHERE status = 'Em processo' AND data_fim IS NULL) AS active_cuttings,
              (SELECT COUNT(*) FROM tarefas WHERE status = 'Destacando' AND data_finalizacao IS NULL) AS active_highlights
            """
        ).fetchone())
        current_categories = {
            row["categoria"]: int(row["total"])
            for row in cursor.execute(
                "SELECT categoria, COUNT(*) AS total FROM eventos_estado_recurso WHERE data_fim IS NULL GROUP BY categoria ORDER BY categoria"
            ).fetchall()
        }
        rateio = [dict(row) for row in cursor.execute(
            """
            SELECT s.id, s.segundos_fisicos,
                   COALESCE(SUM(r.segundos_atribuidos), 0) AS segundos_rateados,
                   COUNT(r.id) AS ops
            FROM sessoes_recurso s
            LEFT JOIN rateios_tempo_op r ON r.sessao_recurso_id = s.id
            GROUP BY s.id, s.segundos_fisicos ORDER BY s.id
            """
        ).fetchall()]
        max_timestamp = cursor.execute(
            """
            SELECT MAX(ts) AS value FROM (
                SELECT MAX(data_hora) AS ts FROM eventos_quantidade_producao
                UNION ALL SELECT MAX(data_inicio) FROM eventos_estado_recurso
                UNION ALL SELECT MAX(data_fim) FROM eventos_estado_recurso
                UNION ALL SELECT MAX(data_hora) FROM eventos_apontamento_operador
                UNION ALL SELECT MAX(data_entrada) FROM apontamentos_operacionais
                UNION ALL SELECT MAX(data_inicio) FROM apontamentos_operacionais
                UNION ALL SELECT MAX(data_fim) FROM apontamentos_operacionais
                UNION ALL SELECT MAX(fim_planejado) FROM catalogo_pcp_ops
                UNION ALL SELECT MAX(prazo_entrega) FROM catalogo_pcp_ops
                UNION ALL SELECT MAX(data_inicio) FROM apontamentos_corte
                UNION ALL SELECT MAX(data_fim) FROM apontamentos_corte
                UNION ALL SELECT MAX(data_hora) FROM eventos_destaque_tarefa
                UNION ALL SELECT MAX(data_hora) FROM eventos_sistema
            ) timestamps
            """
        ).fetchone()["value"]
        boundaries = dict(cursor.execute(
            """
            SELECT MIN(data_inicio) AS first_state,
                   MAX(COALESCE(data_fim, %s)) AS last_state
            FROM eventos_estado_recurso
            """,
            (SIMULATED_NOW,),
        ).fetchone())
        cross_month_cuttings = int(cursor.execute(
            """
            SELECT COUNT(*) AS total FROM apontamentos_corte
            WHERE data_fim IS NOT NULL
              AND date_trunc('month', data_inicio) <> date_trunc('month', data_fim)
            """
        ).fetchone()["total"])
        daily = [dict(row) for row in cursor.execute(
            """
            SELECT DATE(data_hora) AS period, tipo, SUM(quantidade) AS quantity
            FROM eventos_quantidade_producao
            GROUP BY DATE(data_hora), tipo ORDER BY period, tipo
            """
        ).fetchall()]
        weekly = [dict(row) for row in cursor.execute(
            """
            SELECT date_trunc('week', data_hora)::date AS period, tipo, SUM(quantidade) AS quantity
            FROM eventos_quantidade_producao
            GROUP BY date_trunc('week', data_hora)::date, tipo ORDER BY period, tipo
            """
        ).fetchall()]
        cutoff_times = [row["value"] for row in cursor.execute(
            """
            SELECT DISTINCT to_char(data_inicio, 'HH24:MI:SS') AS value
            FROM eventos_estado_recurso
            WHERE tipo_interrupcao = 'fim_turno'
            ORDER BY value
            """
        ).fetchall()]
        duplicates = int(cursor.execute(
            """
            SELECT COUNT(*) AS total FROM (
              SELECT origem, referencia_origem, tipo
              FROM eventos_quantidade_producao
              WHERE referencia_origem IS NOT NULL
              GROUP BY origem, referencia_origem, tipo HAVING COUNT(*) > 1
            ) duplicated
            """
        ).fetchone()["total"])
        stale_historical_active = int(cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM apontamentos_operacionais
            WHERE data_fim IS NOT NULL
              AND status <> 'Finalizado'
            """
        ).fetchone()["total"])
    return {
        "identity": identity,
        "schema_version": schema_version,
        "counts": {key: int(value) for key, value in counts.items()},
        "months": months,
        "current": {key: int(value) for key, value in current.items()},
        "current_categories": current_categories,
        "rateio": rateio,
        "max_timestamp": max_timestamp,
        "boundaries": boundaries,
        "cross_month_cuttings": cross_month_cuttings,
        "daily": daily,
        "weekly": weekly,
        "cutoff_times": cutoff_times,
        "duplicate_quantity_origins": duplicates,
        "stale_historical_active": stale_historical_active,
    }


def _service_snapshot(db: Database) -> dict:
    facade = FrontendBackendFacade(
        db,
        now_func=lambda: SIMULATED_NOW,
        simulation_mode=True,
    )
    months = {}
    timings = defaultdict(list)
    for month, bounds in MONTHS.items():
        filters = AnalyticsFilter(*bounds)
        started = time.perf_counter()
        overview = facade.inicio(filters)
        timings["overview"].append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        quality = facade.analise("qualidade", filters)
        timings["quality"].append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        time_breakdown = facade.analise("tempos", filters)
        timings["time_breakdown"].append((time.perf_counter() - started) * 1000)
        months[month] = {
            "overview": overview,
            "quality": quality,
            "time_breakdown": time_breakdown,
        }

    full = AnalyticsFilter(START, SIMULATED_NOW)
    started = time.perf_counter()
    current = facade.consulta_operacional(full)
    timings["operations_current"].append((time.perf_counter() - started) * 1000)
    filters = {
        "sector": facade.ordens_producao(AnalyticsFilter(START, SIMULATED_NOW, setor="Corte")),
        "resource": facade.ordens_producao(AnalyticsFilter(START, SIMULATED_NOW, recurso="1303")),
        "op": facade.ordens_producao(AnalyticsFilter(START, SIMULATED_NOW, op="SIM3M000001")),
        "operation": facade.ordens_producao(AnalyticsFilter(START, SIMULATED_NOW, operacao="10")),
        "product": facade.ordens_producao(AnalyticsFilter(START, SIMULATED_NOW, produto="PÇ-SIM-001")),
        "operator": facade.ordens_producao(AnalyticsFilter(START, SIMULATED_NOW, operador="Operador Simulação 01")),
    }
    timing_summary = {
        key: {
            "samples": len(values),
            "median_ms": round(statistics.median(values), 3),
            "max_ms": round(max(values), 3),
        }
        for key, values in timings.items()
    }
    return {
        "months": months,
        "current": current,
        "filters": {key: value["count"] for key, value in filters.items()},
        "performance": timing_summary,
    }


def _api_snapshot(target_dsn: str, primary_db: Database) -> dict:
    password = secrets.token_urlsafe(32)
    suffix = secrets.token_hex(5)
    manager_name = f"Simulação API Gestor {suffix}"
    manager_id = primary_db.criar_usuario(manager_name, password, "gestor")
    if not manager_id:
        raise RuntimeError("Não foi possível criar o usuário efêmero da API.")
    settings = WebSettings(
        environment="test",
        session_secret="simulacao-historica-session-secret-with-safe-length-20260824",
        session_ttl_seconds=3600,
        cookie_secure=False,
        allowed_origins=("http://testserver",),
        allowed_hosts=("testserver", "gestor-peca"),
        serve_static=True,
        stream_interval_seconds=5,
        database_retry_seconds=1,
        simulation_mode=True,
        simulation_reference_time=SIMULATED_NOW,
    )
    app = create_app(settings=settings, database_factory=lambda: _database(target_dsn))
    paths = (
        "/api/v1/system/health",
        "/api/v1/system/capabilities",
        "/api/v1/management/overview",
        "/api/v1/management/sectors",
        "/api/v1/management/alerts",
        "/api/v1/operations/overview",
        "/api/v1/operations/resources",
        "/api/v1/operations/orders",
        "/api/v1/operations/time",
        "/api/v1/orders",
        "/api/v1/orders/production",
        "/api/v1/orders/planned-vs-actual",
        "/api/v1/analytics/oee",
        "/api/v1/analytics/hours-utilization",
        "/api/v1/analytics/downtimes",
        "/api/v1/analytics/setups",
        "/api/v1/analytics/quality",
        "/api/v1/analytics/standard-vs-actual",
        "/api/v1/analytics/chronoanalysis",
        "/api/v1/analytics/capacity",
        "/api/v1/audit/appointments",
        "/api/v1/audit",
        "/api/v1/audit/reliability",
        "/api/v1/reports/gerencial",
        "/api/v1/reports/producao",
        "/api/v1/reports/perdas",
        "/api/v1/reports/indicadores",
        "/api/v1/reports/dados_analiticos",
        "/api/v1/traceability/orders/SIM3M000001",
        "/api/v1/traceability/nestings",
    )
    report = {}
    try:
        with TestClient(app) as client:
            unauthenticated = client.get("/api/v1/management/overview")
            login = client.post("/api/v1/auth/login", json={"username": manager_name, "password": password})
            route_results = []
            full_params = {"inicio": START.isoformat(), "fim": SIMULATED_NOW.isoformat()}
            for path in paths:
                params = None if path.startswith("/api/v1/system/") else full_params
                started = time.perf_counter()
                response = client.get(path, params=params)
                route_results.append({
                    "path": path,
                    "status": response.status_code,
                    "milliseconds": round((time.perf_counter() - started) * 1000, 3),
                    "bytes": len(response.content),
                })
            months = {}
            for month, bounds in MONTHS.items():
                response = client.get("/api/v1/management/overview", params={
                    "inicio": bounds[0].isoformat(),
                    "fim": bounds[1].isoformat(),
                })
                payload = response.json()
                months[month] = {
                    "status": response.status_code,
                    "good": payload.get("production", {}).get("good"),
                    "planned": payload.get("simulation", {}).get("planned_quantity"),
                    "kpis": {
                        key: payload.get("kpis", {}).get(key, {}).get("value")
                        for key in ("availability", "performance", "ftt", "oee")
                    },
                }
            page = client.get("/api/v1/orders", params={**full_params, "page": 2, "page_size": 17})
            operation_filter = client.get("/api/v1/orders", params={**full_params, "operacao": "10", "page": 1, "page_size": 17})
            invalid_period = client.get("/api/v1/orders", params={"inicio": SIMULATED_NOW.isoformat(), "fim": START.isoformat()})
            csv_response = client.get("/api/v1/reports/dados_analiticos/export.csv", params=full_params)
            EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            EXPORT_PATH.write_bytes(csv_response.content)
            csv_text = csv_response.content.decode("utf-8-sig", errors="strict")
            csv_rows = list(csv.DictReader(csv_text.splitlines(), delimiter=";"))
            csrf = client.cookies.get(settings.csrf_cookie_name)
            logout = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
            session_after_logout = client.get("/api/v1/auth/session")
            report = {
                "unauthenticated_status": unauthenticated.status_code,
                "login_status": login.status_code,
                "cookie_http_only": "httponly" in login.headers.get("set-cookie", "").casefold(),
                "routes": route_results,
                "all_routes_ok": all(row["status"] == 200 for row in route_results),
                "months": months,
                "pagination": page.json().get("page") if page.status_code == 200 else None,
                "operation_filter_total": operation_filter.json().get("page", {}).get("total") if operation_filter.status_code == 200 else None,
                "invalid_period_status": invalid_period.status_code,
                "csv_status": csv_response.status_code,
                "csv_utf8_bom": csv_response.content.startswith(b"\xef\xbb\xbf"),
                "csv_has_accents": "Peça" in csv_text,
                "csv_rows": len(csv_rows),
                "logout_status": logout.status_code,
                "session_after_logout_status": session_after_logout.status_code,
            }
    finally:
        with primary_db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM usuarios WHERE id = %s", (manager_id,))
        API_MATRIX_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
    return report


def _reconcile_month(checks: Checkbook, month: str, expected: dict, sql: dict, service: dict, api: dict) -> None:
    prefix = f"month:{month}"
    for key in ("orders", "planned", "good", "scrap", "rework"):
        checks.check(f"{prefix}:sql:{key}", sql[key], expected[key])
    expected_seconds = {
        "available": expected["seconds:available"],
        "worked": expected["seconds:worked"],
        "production": expected["seconds:production"],
        "setup": expected["seconds:setup"],
        "rework": expected["seconds:rework"],
        "no_op": expected["seconds:no_op"],
        "downtime": expected["seconds:downtime"],
        "queue": expected["seconds:queue"],
        "unknown": expected.get("seconds:unknown", 0),
        "standard_run": expected["seconds:standard_run"],
    }
    for key, value in expected_seconds.items():
        checks.close(f"{prefix}:sql:seconds:{key}", sql["seconds"][key], value, tolerance=0.01)
    for key, value in expected["kpis"].items():
        checks.close(f"{prefix}:sql:kpi:{key}", sql["kpis"][key], value, tolerance=1e-6)
    overview = service["overview"]
    simulation = overview["simulation"]
    checks.check(f"{prefix}:service:good", overview["production"]["good"], expected["good"])
    checks.check(f"{prefix}:service:scrap", overview["production"]["scrap"], expected["scrap"])
    checks.check(f"{prefix}:service:rework", overview["production"]["rework"], expected["rework"])
    checks.check(f"{prefix}:service:planned", simulation["planned_quantity"], expected["planned"])
    for key in ("availability", "performance", "ftt", "oee"):
        value = overview["kpis"][key]["value"]
        checks.close(f"{prefix}:service:kpi:{key}", value, expected["kpis"][key], tolerance=1e-6)
        low, high = TARGET_RANGES[month][key]
        checks.truth(f"{prefix}:target_range:{key}", low <= value <= high, detail=f"{low}..{high}")
        checks.close(f"{prefix}:api:kpi:{key}", api["kpis"][key], value, tolerance=1e-6)
    checks.check(f"{prefix}:api:status", api["status"], 200)
    checks.check(f"{prefix}:api:good", api["good"], expected["good"])
    checks.check(f"{prefix}:api:planned", api["planned"], expected["planned"])
    checks.check(f"{prefix}:quality:ftt_availability", service["quality"]["ftt"]["availability"], "disponivel")
    checks.check(f"{prefix}:physical_source", service["time_breakdown"]["physical_state_source"], "eventos_estado_recurso")


def reconcile() -> dict:
    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    _operational, _common_test, target_dsn, _maintenance, safe = _safe_dsns()
    target = safe["target"]
    if target["dbname"].casefold() != TARGET_DATABASE.casefold():
        raise RuntimeError("Reconciliação recusada: banco-alvo inesperado.")
    checks = Checkbook()
    db = _database(target_dsn)
    try:
        sql = _sql_snapshot(db)
        services = _service_snapshot(db)
        api = _api_snapshot(target_dsn, db)

        checks.check("database_name", sql["identity"]["database_name"], TARGET_DATABASE)
        checks.check("schema_version", sql["schema_version"], expected["schema_version"])
        checks.check("dataset_tag", SEED_TAG, expected["dataset"])
        checks.check("users_copied", sql["counts"]["users"], expected["users_copied"])
        for key, value in expected["counts"].items():
            checks.check(f"count:{key}", sql["counts"][key], value)
        for month in MONTHS:
            _reconcile_month(
                checks,
                month,
                expected["months"][month],
                sql["months"][month],
                services["months"][month],
                api["months"][month],
            )

        checks.truth("monthly_oee_improves", all(
            expected["months"][left]["kpis"]["oee"] < expected["months"][right]["kpis"]["oee"]
            for left, right in (("6", "7"), ("7", "8"))
        ))
        checks.truth("planned_actual_has_above_and_below_months", any(
            row["good"] > row["planned"] for row in expected["months"].values()
        ) and any(row["good"] < row["planned"] for row in expected["months"].values()))
        checks.check("no_future_data", sql["max_timestamp"] <= SIMULATED_NOW, True)
        checks.check("first_state_boundary", sql["boundaries"]["first_state"], START)
        checks.check("last_state_boundary", sql["boundaries"]["last_state"], SIMULATED_NOW)
        checks.check("official_shift_cutoffs", sql["cutoff_times"], ["17:30:00", "21:30:00"])
        checks.check("current_active_resources", sql["current"]["active_resources"], expected["current"]["active_resources"])
        checks.check("current_queued_resources", sql["current"]["queued_resources"], expected["current"]["queued_or_free_resources"])
        checks.truth("current_has_production", sql["current_categories"].get("producao", 0) > 0)
        checks.truth("current_has_setup", sql["current_categories"].get("setup", 0) > 0)
        checks.truth("current_has_downtime", sql["current_categories"].get("parada", 0) > 0)
        checks.check("current_cuttings", sql["current"]["active_cuttings"], 12)
        checks.check("current_highlights", sql["current"]["active_highlights"], 6)
        checks.truth("cuttings_cross_months", sql["cross_month_cuttings"] >= 2)
        checks.truth("rateio_exists", bool(sql["rateio"]))
        checks.truth("rateio_conserves_physical_time", all(
            float(row["segundos_fisicos"]) == float(row["segundos_rateados"])
            for row in sql["rateio"]
        ))
        checks.check("quantity_origin_duplicates", sql["duplicate_quantity_origins"], 0)
        checks.check("closed_history_has_no_active_status", sql["stale_historical_active"], 0)

        current_resources = services["current"]["resources"]
        checks.check("service_current_resource_catalog", services["current"]["count"], 24)
        checks.check("service_current_queued_or_free", sum(
            row["categoria"] in {"aguardando", "livre"} for row in current_resources
        ), 12)
        for name, count in services["filters"].items():
            checks.truth(f"filter:{name}:returns_rows", count > 0)
            checks.truth(f"filter:{name}:narrows_result", count < expected["counts"]["orders"])
        checks.truth("daily_aggregation_present", len(sql["daily"]) > 150)
        checks.truth("weekly_aggregation_present", len(sql["weekly"]) >= 36)
        checks.check("daily_good_recomposes_total", sum(
            int(row["quantity"]) for row in sql["daily"] if row["tipo"] == "boa"
        ), sum(row["good"] for row in expected["months"].values()))
        checks.check("weekly_good_recomposes_total", sum(
            int(row["quantity"]) for row in sql["weekly"] if row["tipo"] == "boa"
        ), sum(row["good"] for row in expected["months"].values()))

        checks.check("api_requires_authentication", api["unauthenticated_status"], 401)
        checks.check("api_login", api["login_status"], 200)
        checks.truth("api_cookie_http_only", api["cookie_http_only"])
        checks.truth("api_all_critical_routes", api["all_routes_ok"])
        checks.check("api_pagination_page", api["pagination"]["page"], 2)
        checks.check("api_pagination_size", api["pagination"]["page_size"], 17)
        checks.truth("api_operation_filter", 0 < api["operation_filter_total"] < expected["counts"]["orders"])
        checks.check("api_invalid_period", api["invalid_period_status"], 400)
        checks.check("api_csv", api["csv_status"], 200)
        checks.truth("api_csv_utf8_bom", api["csv_utf8_bom"])
        checks.truth("api_csv_accents", api["csv_has_accents"])
        checks.truth("api_csv_rows", api["csv_rows"] > 0)
        checks.check("api_logout", api["logout_status"], 204)
        checks.check("api_session_closed_after_logout", api["session_after_logout_status"], 401)
        aggregate_prefixes = (
            "/api/v1/audit",
            "/api/v1/reports",
            "/api/v1/management/alerts",
            "/api/v1/analytics/hours-utilization",
            "/api/v1/operations/time",
        )
        standard_routes = [
            row for row in api["routes"]
            if not row["path"].startswith(aggregate_prefixes)
        ]
        aggregate_routes = [
            row for row in api["routes"]
            if row["path"].startswith(aggregate_prefixes)
        ]
        checks.truth("api_standard_route_performance_under_5s", max(
            row["milliseconds"] for row in standard_routes
        ) < 5000)
        checks.truth("api_aggregate_route_performance_under_8s", max(
            row["milliseconds"] for row in aggregate_routes
        ) < 8000)
        checks.truth("service_performance_under_5s", max(
            item["max_ms"] for item in services["performance"].values()
        ) < 5000)

        failures = [item for item in checks.items if item["status"] == "FAIL"]
        result = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "target": target,
            "expected_path": str(EXPECTED_PATH.relative_to(ROOT)),
            "sql": sql,
            "services": services,
            "api": api,
            "checks": checks.items,
            "summary": {
                "total": len(checks.items),
                "passed": len(checks.items) - len(failures),
                "failed": len(failures),
                "gate": "PASS" if not failures else "FAIL",
            },
        }
        OUTPUT_PATH.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"summary": result["summary"], "failures": failures}, ensure_ascii=False, indent=2, default=str))
        if failures:
            raise SystemExit(1)
        return result
    finally:
        db.close()


if __name__ == "__main__":
    reconcile()
