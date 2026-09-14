"""Reconcilia dataset ouro, SQL direto, serviços e API no banco dedicado."""

from __future__ import annotations

import asyncio
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
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
from backend.api.realtime import RealtimeBroker  # noqa: E402
from mes.contracts import AnalyticsFilter  # noqa: E402
from mes.services.frontend_facade import FrontendBackendFacade  # noqa: E402
from mes.services.industrial_analytics import IndustrialAnalyticsService  # noqa: E402
from mes.services.traceability import TraceabilityService  # noqa: E402
from tests.homologacao_extrema.seed_homologacao_extrema import (  # noqa: E402
    END,
    EXPECTED_PATH,
    START,
    TARGET_DATABASE,
    _load_dsns,
    _safe_target,
)


OUTPUT_PATH = Path(__file__).with_name("actual_results.json")
API_MATRIX_PATH = Path(__file__).with_name("api_matrix.json")
EXPORT_PATH = Path(__file__).with_name("exports") / "dados_analiticos.csv"


class Checkbook:
    def __init__(self):
        self.items: list[dict] = []

    def check(self, name, actual, expected, *, severity="blocking"):
        passed = actual == expected
        self.items.append(
            {
                "name": name,
                "status": "PASS" if passed else "FAIL",
                "severity": severity,
                "actual": actual,
                "expected": expected,
            }
        )
        return passed

    def truth(self, name, condition, *, detail=None, severity="blocking"):
        return self.check(name, bool(condition), True, severity=severity)


def _database(target_dsn: str) -> Database:
    return Database(
        config=PostgresConfig(
            dsn=target_dsn,
            min_pool_size=1,
            max_pool_size=12,
            pool_timeout=10,
        )
    )


def _sql_snapshot(db: Database) -> dict:
    with db.connection() as connection, connection.cursor() as cursor:
        database_name = cursor.execute(
            "SELECT current_database() AS database_name"
        ).fetchone()["database_name"]
        schema_version = cursor.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        ).fetchone()["version"]
        counts = cursor.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM catalogo_pcp_ops) AS orders,
                (SELECT COUNT(*) FROM catalogo_operacoes_op) AS operations,
                (SELECT COUNT(*) FROM apontamentos_operacionais) AS appointments,
                (SELECT COUNT(*) FROM eventos_quantidade_producao) AS quantity_events,
                (SELECT COUNT(*) FROM tarefas) AS tasks,
                (SELECT COUNT(*) FROM catalogo_sigmanest_planos_corte) AS cut_plans,
                (SELECT COUNT(*) FROM apontamentos_corte) AS cut_appointments,
                (SELECT COUNT(*) FROM eventos_destaque_tarefa) AS highlight_events,
                (SELECT COUNT(*) FROM operadores_apontamento) AS operator_badges,
                (SELECT COUNT(*) FROM inconsistencias_dados) AS data_issues,
                (SELECT COUNT(*) FROM usuarios) AS users
            """
        ).fetchone()
        quantities = cursor.execute(
            """
            SELECT
                (SELECT COALESCE(SUM(quantidade), 0) FROM catalogo_pcp_ops) AS planned,
                COALESCE(SUM(quantidade) FILTER (WHERE tipo = 'boa'), 0) AS good,
                COALESCE(SUM(quantidade) FILTER (WHERE tipo = 'refugo'), 0) AS scrap,
                COALESCE(SUM(quantidade) FILTER (WHERE tipo = 'retrabalho'), 0) AS rework
            FROM eventos_quantidade_producao
            """
        ).fetchone()
        statuses = {
            row["status"]: row["total"]
            for row in cursor.execute(
                "SELECT status, COUNT(*) AS total FROM apontamentos_operacionais GROUP BY status ORDER BY status"
            ).fetchall()
        }
        edge = cursor.execute(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE categoria = 'parada' AND op IS NULL
                      AND planejado IS FALSE AND automatico IS FALSE
                      AND referencia_origem LIKE 'sem-op:parada:%'
                ) AS manual_no_op_stops,
                COUNT(*) FILTER (
                    WHERE categoria = 'atividade_sem_op' AND op IS NULL
                ) AS productive_no_op_activities,
                COUNT(*) FILTER (
                    WHERE tipo_interrupcao = 'fim_turno'
                      AND planejado IS TRUE AND automatico IS TRUE
                ) AS automatic_shift_interruptions,
                COUNT(*) FILTER (WHERE data_inicio = data_fim) AS zero_duration_events
            FROM eventos_estado_recurso
            """
        ).fetchone()
        cutoff_times = [
            row["cutoff"]
            for row in cursor.execute(
                """
                SELECT DISTINCT to_char(data_inicio, 'HH24:MI:SS') AS cutoff
                FROM eventos_estado_recurso
                WHERE tipo_interrupcao = 'fim_turno'
                ORDER BY cutoff
                """
            ).fetchall()
        ]
        rateio = [
            dict(row)
            for row in cursor.execute(
                """
                SELECT s.id, s.segundos_fisicos,
                       COALESCE(SUM(r.segundos_atribuidos), 0) AS segundos_rateados,
                       COUNT(r.id) AS ops
                FROM sessoes_recurso s
                LEFT JOIN rateios_tempo_op r ON r.sessao_recurso_id = s.id
                GROUP BY s.id, s.segundos_fisicos
                ORDER BY s.id
                """
            ).fetchall()
        ]
        duplicate_quantity_origins = cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM (
                SELECT origem, referencia_origem, tipo
                FROM eventos_quantidade_producao
                WHERE referencia_origem IS NOT NULL
                GROUP BY origem, referencia_origem, tipo
                HAVING COUNT(*) > 1
            ) duplicated
            """
        ).fetchone()["total"]
        invalid_good = cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM apontamentos_operacionais
            WHERE quantidade_boa > quantidade OR quantidade_boa < 0
               OR quantidade_refugo < 0 OR quantidade_retrabalho < 0
            """
        ).fetchone()["total"]
        completed_with_scrap = cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM apontamentos_operacionais
            WHERE status = 'Finalizado'
              AND quantidade_boa = quantidade
              AND quantidade_refugo > 0
            """
        ).fetchone()["total"]
        unicode_description = cursor.execute(
            """
            SELECT produto_descricao
            FROM catalogo_pcp_ops
            WHERE codigo_op = 'HOMEXT00001'
            """
        ).fetchone()["produto_descricao"]
        missing_root_scrap = cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM eventos_quantidade_producao
            WHERE tipo = 'refugo' AND causa_raiz IS NULL
            """
        ).fetchone()["total"]
        nesting_own_times = cursor.execute(
            """
            SELECT COUNT(*) AS total
            FROM catalogo_sigmanest_planos_corte plano
            WHERE plano.tempo_previsto_segundos IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM apontamentos_corte corte
                  WHERE corte.plano_hash = plano.plano_hash
                    AND corte.tempo_previsto_segundos IS NULL
              )
            """
        ).fetchone()["total"]
    return {
        "database": database_name,
        "schema_version": schema_version,
        "counts": dict(counts),
        "quantities": {key: int(value) for key, value in dict(quantities).items()},
        "statuses": statuses,
        "edge": dict(edge),
        "cutoff_times": cutoff_times,
        "rateio": rateio,
        "duplicate_quantity_origins": duplicate_quantity_origins,
        "invalid_good_quantities": invalid_good,
        "completed_orders_with_separate_scrap": completed_with_scrap,
        "unicode_description": unicode_description,
        "missing_root_scrap_events": missing_root_scrap,
        "nestings_with_own_planned_time": nesting_own_times,
    }


def _service_snapshot(db: Database, filters: AnalyticsFilter) -> tuple[dict, dict]:
    analytics = IndustrialAnalyticsService(db, now_func=lambda: END)
    facade = FrontendBackendFacade(db, now_func=lambda: END)
    traceability = TraceabilityService(db)
    calls = {
        "overview": lambda: facade.inicio(filters),
        "operations": lambda: facade.consulta_operacional(filters),
        "production": lambda: facade.producao(filters),
        "orders": lambda: facade.ordens_producao(filters),
        "nestings": lambda: facade.nestings(filters),
        "analytics": lambda: facade.analises(filters),
        "audit": lambda: facade.auditoria(filters),
        "trace": lambda: traceability.trace_op("HOMEXT00001"),
        "time_breakdown": lambda: analytics.time_breakdown(filters),
        "quality": lambda: analytics.quality(filters),
        "chronoanalysis": lambda: analytics.chronoanalysis(filters),
        "planned_vs_actual": lambda: analytics.planned_vs_actual(filters),
    }
    payload = {}
    performance = {}
    for name, call in calls.items():
        start = time.perf_counter()
        payload[name] = call()
        performance[name] = round((time.perf_counter() - start) * 1000, 3)

    repeated = []
    for _ in range(25):
        start = time.perf_counter()
        facade.inicio(filters)
        repeated.append((time.perf_counter() - start) * 1000)
    performance["overview_repeated_ms"] = {
        "samples": len(repeated),
        "median": round(statistics.median(repeated), 3),
        "p95": round(sorted(repeated)[int(len(repeated) * 0.95) - 1], 3),
        "max": round(max(repeated), 3),
    }
    return payload, performance


async def _exercise_realtime() -> dict:
    broker = RealtimeBroker()
    first = broker.stream()
    second = broker.stream()
    connected_a = await asyncio.wait_for(anext(first), timeout=1)
    connected_b = await asyncio.wait_for(anext(second), timeout=1)
    published = broker.publish("homologacao_multiusuario")
    refresh_a, refresh_b = await asyncio.gather(
        asyncio.wait_for(anext(first), timeout=1),
        asyncio.wait_for(anext(second), timeout=1),
    )
    tick = await asyncio.wait_for(anext(first), timeout=2)
    await first.aclose()
    await second.aclose()
    return {
        "connected_clients": 2,
        "published_revision": published["revision"],
        "both_received_publish": (
            'event: refresh' in refresh_a
            and 'event: refresh' in refresh_b
            and 'homologacao_multiusuario' in refresh_a
            and 'homologacao_multiusuario' in refresh_b
        ),
        "continuous_tick_without_mutation": "live_tick" in tick,
        "connected_event_ok": "event: connected" in connected_a and "event: connected" in connected_b,
    }


def _api_snapshot(target_dsn: str, primary_db: Database) -> dict:
    password = secrets.token_urlsafe(32)
    suffix = secrets.token_hex(5)
    manager_name = f"Homologação API Gestor {suffix}"
    operator_name = f"Homologação API Operador {suffix}"
    manager_id = primary_db.criar_usuario(manager_name, password, "gestor")
    operator_id = primary_db.criar_usuario(operator_name, password, "operador_dobra")
    if not manager_id or not operator_id:
        raise RuntimeError("Não foi possível criar usuários efêmeros da API.")

    settings = WebSettings(
        environment="test",
        session_secret="homologacao-extrema-local-session-secret-2026-with-safe-length",
        session_ttl_seconds=3600,
        cookie_secure=False,
        allowed_origins=("http://testserver",),
        allowed_hosts=("testserver",),
        serve_static=True,
        stream_interval_seconds=5,
        database_retry_seconds=1,
    )
    app = create_app(settings=settings, database_factory=lambda: _database(target_dsn))
    period = {
        "inicio": START.isoformat(),
        "fim": END.isoformat(),
    }
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
        "/api/v1/traceability/orders/HOMEXT00001",
        "/api/v1/traceability/nestings",
    )
    results = []
    report = {}
    try:
        with TestClient(app) as client:
            no_auth = client.get("/api/v1/management/overview", params=period)
            invalid_login = client.post(
                "/api/v1/auth/login",
                json={"username": manager_name, "password": "senha-incorreta"},
            )
            login = client.post(
                "/api/v1/auth/login",
                json={"username": manager_name, "password": password},
            )
            for path in paths:
                start = time.perf_counter()
                params = period if path not in {"/api/v1/system/health", "/api/v1/system/capabilities"} else None
                response = client.get(path, params=params)
                results.append(
                    {
                        "path": path,
                        "status": response.status_code,
                        "milliseconds": round((time.perf_counter() - start) * 1000, 3),
                        "bytes": len(response.content),
                    }
                )
            page = client.get("/api/v1/orders", params={**period, "page": 2, "page_size": 17})
            filtered = client.get(
                "/api/v1/orders",
                params={**period, "setor": "Dobra", "produto": "PÇ-HOM"},
            )
            invalid_period = client.get(
                "/api/v1/orders",
                params={"inicio": END.isoformat(), "fim": START.isoformat()},
            )
            csv_response = client.get(
                "/api/v1/reports/dados_analiticos/export.csv",
                params=period,
            )
            EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            EXPORT_PATH.write_bytes(csv_response.content)
            csv_text = csv_response.content.decode("utf-8-sig", errors="strict")
            csv_rows = list(csv.DictReader(csv_text.splitlines(), delimiter=";"))
            app_root = client.get("/")

        with TestClient(app) as operator_client:
            operator_login = operator_client.post(
                "/api/v1/auth/login",
                json={"username": operator_name, "password": password},
            )
            denied_management = operator_client.get(
                "/api/v1/management/overview",
                params=period,
            )
            operator_context = operator_client.get("/api/v1/operator/context")

        with TestClient(app) as concurrent_client:
            concurrent_login = concurrent_client.post(
                "/api/v1/auth/login",
                json={"username": manager_name, "password": password},
            )
            if concurrent_login.status_code != 200:
                raise RuntimeError("Login da sessão multiusuário falhou.")

            def concurrent_request(_index):
                started = time.perf_counter()
                response = concurrent_client.get("/api/v1/management/overview", params=period)
                return {
                    "status": response.status_code,
                    "milliseconds": round((time.perf_counter() - started) * 1000, 3),
                }

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [executor.submit(concurrent_request, index) for index in range(24)]
                concurrent_results = [future.result() for future in as_completed(futures)]

        report = {
            "no_auth_status": no_auth.status_code,
            "invalid_login_status": invalid_login.status_code,
            "manager_login_status": login.status_code,
            "manager_cookie_http_only": "httponly" in login.headers.get("set-cookie", "").casefold(),
            "routes": results,
            "all_routes_ok": all(row["status"] == 200 for row in results),
            "pagination": page.json().get("page") if page.status_code == 200 else None,
            "filtered_count": filtered.json().get("page", {}).get("total") if filtered.status_code == 200 else None,
            "invalid_period_status": invalid_period.status_code,
            "csv_status": csv_response.status_code,
            "csv_utf8_bom": csv_response.content.startswith(b"\xef\xbb\xbf"),
            "csv_has_accents": "Peça" in csv_response.content.decode("utf-8-sig", errors="replace"),
            "csv_rows": len(csv_rows),
            "csv_export_path": str(EXPORT_PATH.relative_to(ROOT)),
            "spa_status": app_root.status_code,
            "operator_login_status": operator_login.status_code,
            "operator_management_denied": denied_management.status_code,
            "operator_context_status": operator_context.status_code,
            "concurrency": {
                "requests": len(concurrent_results),
                "successes": sum(row["status"] == 200 for row in concurrent_results),
                "max_milliseconds": max(
                    row["milliseconds"] or 0 for row in concurrent_results
                ),
            },
        }
        return report
    finally:
        with primary_db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM usuarios WHERE id = ANY(%s)",
                ([manager_id, operator_id],),
            )
        API_MATRIX_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )


def reconcile() -> dict:
    expected = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    _operational, _common_test, target_dsn, _maintenance = _load_dsns()
    target = _safe_target(target_dsn)
    if target["dbname"].casefold() != TARGET_DATABASE.casefold():
        raise RuntimeError("Reconciliação recusada: banco-alvo inesperado.")

    checks = Checkbook()
    db = _database(target_dsn)
    try:
        sql_result = _sql_snapshot(db)
        checks.check("database_name", sql_result["database"], TARGET_DATABASE)
        checks.check("schema_version", sql_result["schema_version"], expected["schema_version"])
        for key, value in expected["counts"].items():
            checks.check(f"count:{key}", sql_result["counts"][key], value)
        checks.check("users_copied", sql_result["counts"]["users"], expected["users_copied"])
        for key, value in expected["quantities"].items():
            checks.check(f"quantity:{key}", sql_result["quantities"][key], value)
        checks.check("appointment_statuses", sql_result["statuses"], expected["statuses"])
        for key in (
            "manual_no_op_stops",
            "productive_no_op_activities",
            "automatic_shift_interruptions",
            "zero_duration_events",
        ):
            checks.check(f"edge:{key}", sql_result["edge"][key], expected["edge_cases"][key])
        checks.check("official_cutoffs", sql_result["cutoff_times"], expected["rules"]["official_cutoffs"])
        checks.truth(
            "rateio_conserves_physical_time",
            bool(sql_result["rateio"])
            and all(row["segundos_fisicos"] == row["segundos_rateados"] for row in sql_result["rateio"]),
        )
        checks.check("quantity_origin_duplicates", sql_result["duplicate_quantity_origins"], 0)
        checks.check("invalid_good_quantities", sql_result["invalid_good_quantities"], 0)
        checks.truth(
            "scrap_is_separate_from_completion",
            sql_result["completed_orders_with_separate_scrap"] > 0,
        )
        checks.truth(
            "utf8_long_description",
            all(token in sql_result["unicode_description"] for token in ("proteção", "aço", "operação", "acentuação")),
        )
        checks.truth("missing_data_remains_visible", sql_result["missing_root_scrap_events"] > 0)
        checks.check("nestings_keep_own_planned_time", sql_result["nestings_with_own_planned_time"], 48)

        filters = AnalyticsFilter(inicio=START, fim=END)
        services, service_performance = _service_snapshot(db, filters)
        time_payload = services["time_breakdown"]
        quality = services["quality"]
        checks.check("service_quality_good", quality["totals"]["boa"], expected["quantities"]["good"])
        checks.check("service_quality_scrap", quality["totals"]["refugo"], expected["quantities"]["scrap"])
        checks.check("service_quality_rework", quality["totals"]["retrabalho"], expected["quantities"]["rework"])
        checks.check("service_physical_state_source", time_payload["physical_state_source"], "eventos_estado_recurso")
        checks.truth("service_conflict_is_not_silently_discarded", time_payload["conflicting_state_seconds"] >= 1800)
        checks.truth("service_does_not_multiply_physical_time", time_payload["overlap_removed_seconds"] >= 0)
        checks.truth("traceability_has_timeline", bool(services["trace"].get("timeline")))
        checks.truth(
            "management_has_no_correction_module",
            "correc" not in json.dumps(
                services["overview"], ensure_ascii=False, default=str
            ).casefold(),
        )
        checks.truth("service_overview_p95_under_2000ms", service_performance["overview_repeated_ms"]["p95"] < 2000)

        realtime = asyncio.run(_exercise_realtime())
        checks.truth("sse_two_clients_receive_publish", realtime["both_received_publish"])
        checks.truth("sse_continuous_tick_without_mutation", realtime["continuous_tick_without_mutation"])

        api = _api_snapshot(target_dsn, db)
        checks.check("api_requires_auth", api["no_auth_status"], 401)
        checks.check("api_rejects_invalid_login", api["invalid_login_status"], 401)
        checks.check("api_manager_login", api["manager_login_status"], 200)
        checks.truth("api_session_cookie_http_only", api["manager_cookie_http_only"])
        checks.truth("api_all_domain_routes", api["all_routes_ok"])
        checks.check("api_invalid_period", api["invalid_period_status"], 400)
        checks.check("api_csv_export", api["csv_status"], 200)
        checks.truth("api_csv_utf8_bom", api["csv_utf8_bom"])
        checks.truth("api_csv_has_accents", api["csv_has_accents"])
        checks.truth("api_csv_has_rows", api["csv_rows"] > 0)
        checks.check("api_operator_denied_management", api["operator_management_denied"], 403)
        checks.check("api_concurrent_requests", api["concurrency"]["successes"], api["concurrency"]["requests"])

        failures = [item for item in checks.items if item["status"] == "FAIL"]
        payload = {
            "target": target,
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "expected": expected,
            "sql": sql_result,
            "services": {
                "overview": services["overview"],
                "operations": services["operations"],
                "quality": quality,
                "time_breakdown": time_payload,
                "audit": services["audit"],
                "trace": services["trace"],
            },
            "performance": service_performance,
            "realtime": realtime,
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
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        return payload
    finally:
        db.close()


if __name__ == "__main__":
    result = reconcile()
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    if result["summary"]["failed"]:
        print(json.dumps(
            [item for item in result["checks"] if item["status"] == "FAIL"],
            ensure_ascii=False,
            indent=2,
            default=str,
        ))
        raise SystemExit(1)
