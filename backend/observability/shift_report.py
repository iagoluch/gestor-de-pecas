"""Relatório automático de turno para o desenvolvedor.

As janelas **não** são redefinidas aqui. Elas saem de
``mes.domain.manufacturing_rules``: ``OFFICIAL_WORK_WINDOW`` (08:00–17:30) e
``OVERTIME_WINDOWS`` (06:00–08:00 e 17:30–21:30) são a mesma fonte de verdade
que o calendário produtivo e o ``ShiftBoundaryService`` usam. Se a Manufatura
mudar o horário, o relatório acompanha sem edição.

O relatório é do desenvolvedor, não da gestão: ele responde "o que quebrou no
turno, o que foi recusado por regra e o sistema respondeu rápido o bastante".
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path

from backend.observability.classification import (
    DEFECT_CLASSIFICATIONS,
    EXPECTED_BLOCK,
    EXPECTED_VALIDATION,
    OK,
    PERFORMANCE_ERROR,
    REAL_ERROR,
    TECHNICAL_ERROR,
)
from backend.observability.recorder import MUTATING_METHODS, summarize_latency
from mes.domain.manufacturing_rules import OFFICIAL_WORK_WINDOW, OVERTIME_WINDOWS


@dataclass(frozen=True)
class ShiftWindow:
    key: str
    label: str
    start: datetime
    end: datetime

    @property
    def directory_name(self) -> str:
        return f"{self.start.date().isoformat()}_{self.key}"

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "directory": self.directory_name,
        }


def _combine(day: date, moment: time) -> datetime:
    return datetime.combine(day, moment)


def _overtime_key(start: time, official_start: time) -> tuple[str, str]:
    if start < official_start:
        return "he_manha", "Hora extra da manhã"
    return "he_noite", "Hora extra da noite"


def shift_windows_for_date(day: date) -> list[ShiftWindow]:
    """Janelas canônicas do dia, em ordem cronológica."""

    official_start, official_end = OFFICIAL_WORK_WINDOW
    windows = [
        ShiftWindow(
            key="turno",
            label=f"Turno oficial {official_start.strftime('%H:%M')}–{official_end.strftime('%H:%M')}",
            start=_combine(day, official_start),
            end=_combine(day, official_end),
        )
    ]
    for start, end in OVERTIME_WINDOWS:
        key, label = _overtime_key(start, official_start)
        window_start = _combine(day, start)
        window_end = _combine(day, end)
        if window_end <= window_start:
            window_end += timedelta(days=1)
        windows.append(
            ShiftWindow(
                key=key,
                label=f"{label} {start.strftime('%H:%M')}–{end.strftime('%H:%M')}",
                start=window_start,
                end=window_end,
            )
        )
    windows.sort(key=lambda window: window.start)
    return windows


def closed_windows(now: datetime, *, lookback_days: int = 1) -> list[ShiftWindow]:
    """Janelas que já terminaram dentro da janela de recuperação.

    Cobre o dia anterior para que uma API que ficou fora do ar durante o fim do
    turno ainda gere o relatório ao voltar, sem reprocessar histórico antigo.
    """

    windows: list[ShiftWindow] = []
    for offset in range(-max(0, lookback_days), 1):
        for window in shift_windows_for_date(now.date() + timedelta(days=offset)):
            if window.end <= now:
                windows.append(window)
    floor = now - timedelta(days=max(1, lookback_days))
    return [window for window in windows if window.end >= floor]


def current_window(now: datetime) -> ShiftWindow | None:
    for offset in (-1, 0):
        for window in shift_windows_for_date(now.date() + timedelta(days=offset)):
            if window.start <= now < window.end:
                return window
    return None


def find_window(day: date, key: str) -> ShiftWindow | None:
    for window in shift_windows_for_date(day):
        if window.key == key:
            return window
    return None


# ---------------------------------------------------------------------------
# Geração
# ---------------------------------------------------------------------------
def _group_events(events: list[dict]) -> dict:
    real_errors: dict[tuple, dict] = {}
    blocks: Counter = Counter()
    block_samples: dict[str, dict] = {}
    validations: Counter = Counter()
    actions: Counter = Counter()
    classifications: Counter = Counter()

    for event in events:
        classification = str(event.get("classification") or "")
        classifications[classification] += 1
        route = f"{event.get('method')} {event.get('route')}"
        if classification in {REAL_ERROR, TECHNICAL_ERROR, PERFORMANCE_ERROR}:
            key = (classification, route, str(event.get("error_code") or event.get("exception") or ""))
            entry = real_errors.setdefault(
                key,
                {
                    "classification": classification,
                    "route": route,
                    "code": event.get("error_code"),
                    "exception": event.get("exception"),
                    "count": 0,
                    "first_at": event.get("timestamp"),
                    "last_at": event.get("timestamp"),
                    "status": event.get("status"),
                    "message": event.get("error_message"),
                    "traceback": event.get("traceback"),
                    "request_id": event.get("request_id"),
                    "max_latency_ms": event.get("latency_ms"),
                },
            )
            entry["count"] += 1
            entry["last_at"] = event.get("timestamp")
            if event.get("traceback") and not entry.get("traceback"):
                entry["traceback"] = event.get("traceback")
            latency = event.get("latency_ms")
            if latency is not None and (entry["max_latency_ms"] or 0) < latency:
                entry["max_latency_ms"] = latency
        elif classification == EXPECTED_BLOCK:
            code = str(event.get("error_code") or "sem_codigo")
            blocks[code] += 1
            block_samples.setdefault(
                code,
                {
                    "route": route,
                    "status": event.get("status"),
                    "message": event.get("error_message"),
                },
            )
        elif classification == EXPECTED_VALIDATION:
            validations[f"{event.get('status')} {route}"] += 1
        elif classification == OK and str(event.get("method") or "").upper() in MUTATING_METHODS:
            actions[route] += 1

    return {
        "classifications": dict(classifications),
        "real_errors": sorted(real_errors.values(), key=lambda item: item["count"], reverse=True),
        "expected_blocks": [
            {"code": code, "count": count, **block_samples.get(code, {})}
            for code, count in blocks.most_common()
        ],
        "expected_validations": [
            {"route": route, "count": count} for route, count in validations.most_common()
        ],
        "actions": [{"route": route, "count": count} for route, count in actions.most_common()],
    }


def _database_delta(samples: list[dict]) -> dict:
    if not samples:
        return {"available": False, "reason": "Sem amostras de banco na janela."}
    first = samples[0]
    last = samples[-1]

    def delta(field: str) -> float:
        return float((last.get("statistics") or {}).get(field) or 0) - float(
            (first.get("statistics") or {}).get(field) or 0
        )

    table_growth = {}
    first_tables = first.get("tables") or {}
    last_tables = last.get("tables") or {}
    for name, value in last_tables.items():
        before = first_tables.get(name)
        if before is None or before < 0 or value < 0:
            continue
        if value - before:
            table_growth[name] = value - before

    connection_peak = max(
        (float((row.get("connections") or {}).get("conexoes") or 0) for row in samples),
        default=0.0,
    )
    idle_in_transaction_peak = max(
        (float((row.get("connections") or {}).get("idle_in_transaction") or 0) for row in samples),
        default=0.0,
    )
    longest_query = max(
        (float((row.get("connections") or {}).get("query_ativa_mais_longa_s") or 0) for row in samples),
        default=0.0,
    )
    ungranted_locks = max(
        (float((row.get("locks") or {}).get("nao_concedidos") or 0) for row in samples),
        default=0.0,
    )
    return {
        "available": True,
        "samples": len(samples),
        "database": last.get("database"),
        "first_at": first.get("timestamp"),
        "last_at": last.get("timestamp"),
        "deadlocks": delta("deadlocks"),
        "rollbacks": delta("xact_rollback"),
        "commits": delta("xact_commit"),
        "temp_files": delta("temp_files"),
        "size_growth_bytes": delta("tamanho_bytes"),
        "connection_peak": connection_peak,
        "idle_in_transaction_peak": idle_in_transaction_peak,
        "longest_active_query_s": round(longest_query, 2),
        "ungranted_locks_peak": ungranted_locks,
        "cache_hit_ratio": last.get("cache_hit_ratio"),
        "table_growth": table_growth,
        "blocked_observations": sum(int(row.get("blocked") or 0) for row in samples),
        "slow_query_observations": sum(int(row.get("slow_queries") or 0) for row in samples),
    }


def _recommendations(grouped: dict, latency: dict, database: dict, thresholds: dict) -> list[dict]:
    """Recomendações determinísticas. Nada de adivinhação: cada item aponta a evidência."""

    items: list[dict] = []
    for error in grouped["real_errors"]:
        if error["classification"] == REAL_ERROR:
            items.append(
                {
                    "priority": "alta",
                    "title": f"Exceção não tratada em {error['route']} ({error['count']}x)",
                    "action": (
                        "Reproduza a rota com o mesmo payload e trate a causa na camada de domínio. "
                        "Exceção não tratada vira 500 para o operador e perde a ação dele."
                    ),
                    "evidence": error.get("exception") or error.get("message"),
                }
            )
        elif error["classification"] == TECHNICAL_ERROR:
            items.append(
                {
                    "priority": "alta",
                    "title": f"Falha de infraestrutura em {error['route']} ({error['count']}x)",
                    "action": (
                        "Verifique disponibilidade do PostgreSQL/integração no horário indicado. "
                        "Não é bug de regra, mas interrompe o apontamento."
                    ),
                    "evidence": error.get("message"),
                }
            )
        else:
            items.append(
                {
                    "priority": "média",
                    "title": f"Resposta lenta em {error['route']} ({error['count']}x)",
                    "action": (
                        f"Acima de {thresholds.get('latency_error_ms')} ms. Analise o plano da consulta "
                        "e o número de idas ao banco nesta rota."
                    ),
                    "evidence": f"máximo observado {error.get('max_latency_ms')} ms",
                }
            )

    slowest = (latency.get("slowest_routes") or [])[:1]
    if slowest and slowest[0]["p95_ms"] >= float(thresholds.get("latency_warning_ms") or 1000):
        items.append(
            {
                "priority": "média",
                "title": f"p95 de {slowest[0]['p95_ms']} ms em {slowest[0]['route']}",
                "action": (
                    "Rota mais lenta do turno. Se ela for de polling do operador, o custo se multiplica "
                    "por posto ativo."
                ),
                "evidence": f"{slowest[0]['count']} chamadas no turno",
            }
        )

    if database.get("available"):
        if float(database.get("deadlocks") or 0) > 0:
            items.append(
                {
                    "priority": "alta",
                    "title": f"{int(database['deadlocks'])} deadlock(s) no turno",
                    "action": (
                        "Deadlock indica duas transações tocando as mesmas linhas em ordens diferentes. "
                        "Revise a ordem de atualização em apontamentos_operacionais/eventos_estado_recurso."
                    ),
                    "evidence": f"pg_stat_database.deadlocks no banco {database.get('database')}",
                }
            )
        if float(database.get("idle_in_transaction_peak") or 0) >= 2:
            items.append(
                {
                    "priority": "média",
                    "title": "Conexões paradas dentro de transação",
                    "action": (
                        "Transação aberta sem trabalho segura locks e bloqueia o pool. "
                        "Procure caminho que abre conexão e não fecha no erro."
                    ),
                    "evidence": f"pico de {int(database['idle_in_transaction_peak'])} idle in transaction",
                }
            )
        if float(database.get("ungranted_locks_peak") or 0) > 0:
            items.append(
                {
                    "priority": "média",
                    "title": "Locks não concedidos observados",
                    "action": "Verifique concorrência entre o worker da outbox e o apontamento do operador.",
                    "evidence": f"pico de {int(database['ungranted_locks_peak'])} locks aguardando",
                }
            )

    if not items:
        items.append(
            {
                "priority": "nenhuma",
                "title": "Nenhum defeito detectado no turno",
                "action": "Bloqueios esperados e validações continuam listados para conferência de regra.",
                "evidence": None,
            }
        )
    return items


def _format_markdown(payload: dict) -> str:
    window = payload["window"]
    summary = payload["summary"]
    latency = payload["latency"]
    database = payload["database"]
    grouped = payload["events"]

    lines = [
        f"# Relatório de turno — {window['label']}",
        "",
        f"- **Janela:** {window['start']} → {window['end']}",
        f"- **Gerado em:** {payload['generated_at']}",
        f"- **Ambiente da API:** {payload['environment']['name']} "
        f"(`{payload['environment']['database']}`)",
        f"- **Requisições no turno:** {latency.get('requests') or 0}",
        f"- **Defeitos:** {summary['defects']}  |  "
        f"**Bloqueios esperados:** {summary['expected_blocks']}  |  "
        f"**Validações recusadas:** {summary['expected_validations']}  |  "
        f"**Ações de escrita:** {summary['actions']}",
        "",
        "## 1. Recomendações",
        "",
    ]
    for item in payload["recommendations"]:
        lines.append(f"### [{item['priority']}] {item['title']}")
        lines.append("")
        lines.append(item["action"])
        if item.get("evidence"):
            lines.append("")
            lines.append(f"> Evidência: {item['evidence']}")
        lines.append("")

    lines += ["## 2. Erros encontrados no turno", ""]
    if not grouped["real_errors"]:
        lines.append("Nenhum erro real, técnico ou de performance registrado nesta janela.")
        lines.append("")
    else:
        lines.append("| Classificação | Rota | Código/Exceção | Ocorrências | Primeira | Última |")
        lines.append("| --- | --- | --- | ---: | --- | --- |")
        for error in grouped["real_errors"]:
            lines.append(
                f"| {error['classification']} | `{error['route']}` | "
                f"{error.get('code') or error.get('exception') or '—'} | {error['count']} | "
                f"{error['first_at']} | {error['last_at']} |"
            )
        lines.append("")
        for error in grouped["real_errors"]:
            if not error.get("traceback"):
                continue
            lines.append(f"<details><summary>Stack trace — {error['route']}</summary>")
            lines.append("")
            lines.append("```")
            lines.append(str(error["traceback"]).strip())
            lines.append("```")
            lines.append("")
            lines.append("</details>")
            lines.append("")

    lines += ["## 3. Bloqueios esperados (regra funcionando)", ""]
    if not grouped["expected_blocks"]:
        lines.append("Nenhuma recusa de negócio nesta janela.")
        lines.append("")
    else:
        lines.append("| Código | Ocorrências | Rota | Mensagem |")
        lines.append("| --- | ---: | --- | --- |")
        for block in grouped["expected_blocks"]:
            lines.append(
                f"| `{block['code']}` | {block['count']} | `{block.get('route') or '—'}` | "
                f"{block.get('message') or '—'} |"
            )
        lines.append("")
    if grouped["expected_validations"]:
        lines.append("Validações de contrato recusadas:")
        lines.append("")
        for item in grouped["expected_validations"]:
            lines.append(f"- `{item['route']}` — {item['count']}x")
        lines.append("")

    lines += ["## 4. Ações de escrita registradas", ""]
    if not grouped["actions"]:
        lines.append("Nenhuma ação de escrita no turno.")
        lines.append("")
    else:
        for item in grouped["actions"]:
            lines.append(f"- `{item['route']}` — {item['count']}x")
        lines.append("")

    lines += ["## 5. Performance da API", ""]
    if not latency.get("requests"):
        lines.append("Sem amostras de latência nesta janela.")
        lines.append("")
    else:
        lines.append(
            f"- Média {latency['avg_ms']} ms · p95 {latency['p95_ms']} ms · máximo {latency['max_ms']} ms"
        )
        lines.append(f"- Distribuição de status: {latency['status']}")
        lines.append("")
        lines.append("| Rota | Chamadas | Média (ms) | p95 (ms) | Máx (ms) |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for route in latency["slowest_routes"]:
            lines.append(
                f"| `{route['route']}` | {route['count']} | {route['avg_ms']} | "
                f"{route['p95_ms']} | {route['max_ms']} |"
            )
        lines.append("")

    lines += ["## 6. PostgreSQL no turno", ""]
    if not database.get("available"):
        lines.append(database.get("reason") or "Sem amostras.")
        lines.append("")
    else:
        lines.append(f"- Banco: `{database.get('database')}` ({database['samples']} amostras)")
        lines.append(
            f"- Commits {int(database['commits'])} · rollbacks {int(database['rollbacks'])} · "
            f"deadlocks {int(database['deadlocks'])}"
        )
        lines.append(
            f"- Pico de conexões {int(database['connection_peak'])} · "
            f"idle in transaction {int(database['idle_in_transaction_peak'])} · "
            f"locks aguardando {int(database['ungranted_locks_peak'])}"
        )
        lines.append(
            f"- Consulta ativa mais longa observada: {database['longest_active_query_s']} s · "
            f"cache hit {database.get('cache_hit_ratio')}"
        )
        lines.append(f"- Crescimento do banco: {int(database['size_growth_bytes'])} bytes")
        if database.get("table_growth"):
            lines.append("")
            lines.append("| Tabela | Linhas novas |")
            lines.append("| --- | ---: |")
            for name, growth in sorted(
                database["table_growth"].items(), key=lambda item: item[1], reverse=True
            ):
                lines.append(f"| `{name}` | {growth} |")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "Gerado automaticamente pelo Dev Observatory. Fonte: eventos capturados no funil de erros "
        "da API, agregados de latência por minuto e amostras somente leitura do PostgreSQL."
    )
    lines.append("")
    return "\n".join(lines)


def build_report(
    window: ShiftWindow,
    recorder,
    *,
    environment: dict,
    generated_at: datetime | None = None,
) -> dict:
    events = recorder.events_between(window.start, window.end)
    latency = summarize_latency(recorder.metrics_between(window.start, window.end))
    database = _database_delta(
        recorder.database_samples_between(window.start, window.end, environment="test")
    )
    grouped = _group_events(events)
    thresholds = {
        "latency_warning_ms": recorder.latency_warning_ms,
        "latency_error_ms": recorder.latency_error_ms,
    }
    defects = sum(
        count for name, count in grouped["classifications"].items()
        if name in DEFECT_CLASSIFICATIONS
    )
    payload = {
        "window": window.as_dict(),
        "generated_at": (generated_at or datetime.now()).isoformat(timespec="seconds"),
        "environment": environment,
        "summary": {
            "events": len(events),
            "defects": defects,
            "expected_blocks": grouped["classifications"].get(EXPECTED_BLOCK, 0),
            "expected_validations": grouped["classifications"].get(EXPECTED_VALIDATION, 0),
            "actions": sum(item["count"] for item in grouped["actions"]),
            "classifications": grouped["classifications"],
        },
        "events": grouped,
        "latency": latency,
        "database": database,
        "thresholds": thresholds,
    }
    payload["recommendations"] = _recommendations(grouped, latency, database, thresholds)
    return payload


def write_report(report_dir: str | Path, payload: dict) -> Path:
    directory = Path(report_dir) / payload["window"]["directory"]
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    markdown_path = directory / "report.md"
    markdown_path.write_text(_format_markdown(payload), encoding="utf-8")
    return markdown_path


def report_exists(report_dir: str | Path, window: ShiftWindow) -> bool:
    return (Path(report_dir) / window.directory_name / "report.md").is_file()


def list_reports(report_dir: str | Path) -> list[dict]:
    base = Path(report_dir)
    if not base.is_dir():
        return []
    items = []
    for directory in sorted(base.iterdir(), reverse=True):
        if not directory.is_dir() or directory.name.startswith("_"):
            continue
        markdown = directory / "report.md"
        if not markdown.is_file():
            continue
        summary = {}
        data_path = directory / "report.json"
        if data_path.is_file():
            try:
                summary = json.loads(data_path.read_text(encoding="utf-8")).get("summary") or {}
            except (OSError, json.JSONDecodeError):
                summary = {}
        items.append(
            {
                "name": directory.name,
                "generated_at": datetime.fromtimestamp(markdown.stat().st_mtime).isoformat(
                    timespec="seconds"
                ),
                "size_bytes": markdown.stat().st_size,
                "summary": summary,
            }
        )
    return items
