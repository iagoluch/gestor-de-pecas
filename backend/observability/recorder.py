"""Captura de eventos e de latência da API em execução.

Duas séries, com custos deliberadamente diferentes:

* **eventos** — um registro por ocorrência que interessa ao desenvolvedor:
  erro real, bloqueio esperado, validação recusada e toda ação que muda estado
  (``POST``/``DELETE``). Vai para ``_events/<data>.jsonl`` linha a linha porque
  o volume é baixo e cada linha é evidência.
* **latência** — ``GET`` de polling é a maior parte do tráfego e não cabe linha
  a linha. O agregado é por minuto e por rota (``_metrics/<data>.jsonl``), com
  contagem, média, p95, máximo e distribuição de status. É isso que permite
  responder "o turno ficou lento às 14h" sem guardar 200 mil linhas.

Nada aqui grava no PostgreSQL. O observatório escreve apenas em disco.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
import threading
from typing import Any, Iterator

from backend.observability.classification import (
    DEFECT_CLASSIFICATIONS,
    EXPECTED_BLOCK,
    OK,
    SEV_ERROR,
    SEV_INFO,
    classify_http,
    sanitize,
)


EVENTS_DIRNAME = "_events"
METRICS_DIRNAME = "_metrics"

#: Métodos que mudam estado industrial. Sucesso deles é "ação relevante" e
#: merece registro; sucesso de ``GET`` é polling e vira apenas métrica.
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _percentile(ordered: list[float], fraction: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


@dataclass
class _Bucket:
    minute: str
    route: str
    method: str
    count: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    samples: list[float] = field(default_factory=list)
    status: Counter = field(default_factory=Counter)

    def add(self, latency_ms: float, status_code: int) -> None:
        self.count += 1
        self.total_ms += latency_ms
        self.max_ms = max(self.max_ms, latency_ms)
        if len(self.samples) < 200:
            self.samples.append(latency_ms)
        self.status[str(status_code)] += 1

    def as_row(self) -> dict:
        ordered = sorted(self.samples)
        return {
            "minute": self.minute,
            "route": self.route,
            "method": self.method,
            "count": self.count,
            "avg_ms": round(self.total_ms / self.count, 2) if self.count else 0.0,
            "p50_ms": round(_percentile(ordered, 0.50), 2),
            "p95_ms": round(_percentile(ordered, 0.95), 2),
            "max_ms": round(self.max_ms, 2),
            "status": dict(self.status),
        }


class DevObservatoryRecorder:
    """Escritor único do Dev Observatory, seguro para uso concorrente."""

    def __init__(
        self,
        report_dir: str | Path,
        *,
        now_func=None,
        latency_warning_ms: float = 1_000.0,
        latency_error_ms: float = 3_000.0,
        buffer_size: int = 600,
    ):
        self.report_dir = Path(report_dir)
        self.events_dir = self.report_dir / EVENTS_DIRNAME
        self.metrics_dir = self.report_dir / METRICS_DIRNAME
        self._now = now_func or datetime.now
        self.latency_warning_ms = float(latency_warning_ms)
        self.latency_error_ms = float(latency_error_ms)
        self._lock = threading.Lock()
        self._sequence = 0
        self._events: deque[dict] = deque(maxlen=buffer_size)
        self._traffic: deque[dict] = deque(maxlen=300)
        self._buckets: dict[tuple[str, str, str], _Bucket] = {}
        self.classification_counter: Counter = Counter()
        self.code_counter: Counter = Counter()
        self.started_at = self._now()
        self._directories_ready = False

    # ------------------------------------------------------------------
    # Persistência
    # ------------------------------------------------------------------
    def _ensure_directories(self) -> None:
        if self._directories_ready:
            return
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.metrics_dir.mkdir(parents=True, exist_ok=True)
        self._directories_ready = True

    def _append(self, path: Path, payload: dict) -> None:
        try:
            self._ensure_directories()
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        except Exception:  # pragma: no cover - observar nunca pode quebrar o request
            logging.debug("Dev Observatory: falha ao persistir %s", path, exc_info=True)

    def events_path(self, moment: datetime) -> Path:
        return self.events_dir / f"{moment.date().isoformat()}.jsonl"

    def metrics_path(self, moment: datetime) -> Path:
        return self.metrics_dir / f"{moment.date().isoformat()}.jsonl"

    def database_samples_path(self, moment: datetime) -> Path:
        return self.metrics_dir / f"db-{moment.date().isoformat()}.jsonl"

    def record_database_sample(self, environment: str, sample: dict) -> dict:
        """Amostra periódica do PostgreSQL.

        Os contadores de ``pg_stat_database`` são cumulativos desde o último
        reset; sem uma amostra no início e outra no fim não existe delta de
        deadlock ou de rollback por turno. É para isso que a série existe.
        """

        moment = self._now()
        statistics = dict(sample.get("statistics") or {})
        connections = dict(sample.get("connections") or {})
        row = {
            "timestamp": moment.isoformat(),
            "environment": environment,
            "database": (sample.get("target") or {}).get("dbname"),
            "connections": connections,
            "locks": dict(sample.get("locks") or {}),
            "cache_hit_ratio": sample.get("cache_hit_ratio"),
            "slow_queries": len(sample.get("slow_queries") or ()),
            "blocked": len(sample.get("blocked") or ()),
            "statistics": statistics,
            "tables": dict(sample.get("tables") or {}),
        }
        self._append(self.database_samples_path(moment), row)
        return row

    def database_samples_between(
        self, start: datetime, end: datetime, *, environment: str | None = None
    ) -> list[dict]:
        rows = []
        for day in self._days_between(start, end):
            for row in self._read_jsonl(self.database_samples_path(day)):
                moment = _parse(row.get("timestamp"))
                if moment is None or not (start <= moment < end):
                    continue
                if environment and row.get("environment") != environment:
                    continue
                rows.append(row)
        rows.sort(key=lambda row: str(row.get("timestamp") or ""))
        return rows

    # ------------------------------------------------------------------
    # Captura
    # ------------------------------------------------------------------
    def record_request(
        self,
        *,
        method: str,
        path: str,
        route: str,
        status: int,
        latency_ms: float,
        request_id: str | None = None,
        user: str | None = None,
        role: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        unhandled: bool = False,
        exception: str | None = None,
        traceback_text: str | None = None,
        details: dict | None = None,
    ) -> dict:
        moment = self._now()
        classification, severity = classify_http(
            status=status,
            error_code=error_code,
            unhandled=unhandled,
            latency_ms=latency_ms,
            latency_warning_ms=self.latency_warning_ms,
            latency_error_ms=self.latency_error_ms,
        )
        entry = {
            "timestamp": moment.isoformat(),
            "method": method,
            "path": path,
            "route": route,
            "status": status,
            "latency_ms": round(float(latency_ms), 2),
            "classification": classification,
            "severity": severity,
            "request_id": request_id,
            "user": user,
            "role": role,
            "error_code": error_code,
            "error_message": error_message,
            "exception": exception,
            "traceback": traceback_text,
            "details": sanitize(details) if details else None,
        }

        with self._lock:
            self._sequence += 1
            entry["sequence"] = self._sequence
            self.classification_counter[classification] += 1
            if error_code:
                self.code_counter[error_code] += 1
            self._traffic.append(
                {
                    "timestamp": entry["timestamp"],
                    "method": method,
                    "route": route,
                    "status": status,
                    "latency_ms": entry["latency_ms"],
                    "classification": classification,
                }
            )
            key = (moment.strftime("%Y-%m-%dT%H:%M"), route, method)
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(minute=key[0], route=route, method=method)
                self._buckets[key] = bucket
            bucket.add(float(latency_ms), status)
            keep = classification != OK or method.upper() in MUTATING_METHODS
            if keep:
                self._events.append(entry)

        if keep:
            self._append(self.events_path(moment), entry)
        return entry

    def record_note(self, *, action: str, message: str, details: dict | None = None) -> dict:
        """Evento do próprio observatório (relatório gerado, ciclo, etc.)."""

        moment = self._now()
        entry = {
            "timestamp": moment.isoformat(),
            "method": "-",
            "path": action,
            "route": action,
            "status": 0,
            "latency_ms": None,
            "classification": OK,
            "severity": SEV_INFO,
            "error_code": None,
            "error_message": message,
            "details": sanitize(details) if details else None,
        }
        with self._lock:
            self._sequence += 1
            entry["sequence"] = self._sequence
            self._events.append(entry)
        self._append(self.events_path(moment), entry)
        return entry

    # ------------------------------------------------------------------
    # Agregação de latência
    # ------------------------------------------------------------------
    def flush_metrics(self, *, force: bool = False) -> int:
        """Grava os minutos já fechados. ``force`` fecha também o minuto atual."""

        current_minute = self._now().strftime("%Y-%m-%dT%H:%M")
        with self._lock:
            ready = [
                key for key in self._buckets
                if force or key[0] != current_minute
            ]
            rows = [self._buckets.pop(key).as_row() for key in ready]
        for row in rows:
            moment = datetime.fromisoformat(row["minute"])
            self._append(self.metrics_path(moment), row)
        return len(rows)

    # ------------------------------------------------------------------
    # Leitura
    # ------------------------------------------------------------------
    def recent_events(self, *, limit: int = 120, classification: str | None = None) -> list[dict]:
        with self._lock:
            items = list(self._events)
        if classification:
            wanted = {value.strip() for value in classification.split(",") if value.strip()}
            items = [item for item in items if item.get("classification") in wanted]
        return list(reversed(items[-limit:]))

    def recent_traffic(self, *, limit: int = 120) -> list[dict]:
        with self._lock:
            items = list(self._traffic)
        return list(reversed(items[-limit:]))

    def live_summary(self) -> dict:
        with self._lock:
            classifications = dict(self.classification_counter)
            codes = self.code_counter.most_common(10)
            open_buckets = [bucket.as_row() for bucket in self._buckets.values()]
            started_at = self.started_at
        total = sum(classifications.values())
        defects = sum(
            count for name, count in classifications.items()
            if name in DEFECT_CLASSIFICATIONS
        )
        latency_rows = sorted(open_buckets, key=lambda row: row["p95_ms"], reverse=True)
        return {
            "started_at": started_at.isoformat(),
            "requests": total,
            "classifications": classifications,
            "defects": defects,
            "expected_blocks": classifications.get(EXPECTED_BLOCK, 0),
            "top_codes": [{"code": code, "count": count} for code, count in codes],
            "slowest_routes": latency_rows[:8],
            "thresholds": {
                "latency_warning_ms": self.latency_warning_ms,
                "latency_error_ms": self.latency_error_ms,
            },
        }

    # ------------------------------------------------------------------
    def _read_jsonl(self, path: Path) -> Iterator[dict]:
        if not path.is_file():
            return
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue
        except OSError:  # pragma: no cover - arquivo removido durante a leitura
            return

    def _days_between(self, start: datetime, end: datetime) -> list[datetime]:
        days = []
        cursor = start
        while cursor.date() <= end.date():
            days.append(cursor)
            cursor += timedelta(days=1)
        return days

    def events_between(self, start: datetime, end: datetime) -> list[dict]:
        rows = []
        for day in self._days_between(start, end):
            for row in self._read_jsonl(self.events_path(day)):
                moment = _parse(row.get("timestamp"))
                if moment is not None and start <= moment < end:
                    rows.append(row)
        rows.sort(key=lambda row: str(row.get("timestamp") or ""))
        return rows

    def metrics_between(self, start: datetime, end: datetime) -> list[dict]:
        rows = []
        for day in self._days_between(start, end):
            for row in self._read_jsonl(self.metrics_path(day)):
                moment = _parse(row.get("minute"))
                if moment is not None and start <= moment < end:
                    rows.append(row)
        rows.sort(key=lambda row: str(row.get("minute") or ""))
        return rows


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def summarize_latency(rows: list[dict]) -> dict:
    """Consolida os agregados por minuto em um retrato do período."""

    total = sum(int(row.get("count") or 0) for row in rows)
    if not total:
        return {
            "requests": 0,
            "avg_ms": None,
            "p95_ms": None,
            "max_ms": None,
            "status": {},
            "slowest_routes": [],
        }
    weighted = sum(float(row.get("avg_ms") or 0.0) * int(row.get("count") or 0) for row in rows)
    status: Counter = Counter()
    by_route: dict[str, dict] = {}
    for row in rows:
        for code, count in (row.get("status") or {}).items():
            status[str(code)] += int(count)
        key = f"{row.get('method')} {row.get('route')}"
        entry = by_route.setdefault(
            key,
            {"route": key, "count": 0, "weighted_ms": 0.0, "p95_ms": 0.0, "max_ms": 0.0},
        )
        count = int(row.get("count") or 0)
        entry["count"] += count
        entry["weighted_ms"] += float(row.get("avg_ms") or 0.0) * count
        entry["p95_ms"] = max(entry["p95_ms"], float(row.get("p95_ms") or 0.0))
        entry["max_ms"] = max(entry["max_ms"], float(row.get("max_ms") or 0.0))
    routes = [
        {
            "route": entry["route"],
            "count": entry["count"],
            "avg_ms": round(entry["weighted_ms"] / entry["count"], 2) if entry["count"] else 0.0,
            "p95_ms": round(entry["p95_ms"], 2),
            "max_ms": round(entry["max_ms"], 2),
        }
        for entry in by_route.values()
    ]
    routes.sort(key=lambda item: item["p95_ms"], reverse=True)
    return {
        "requests": total,
        "avg_ms": round(weighted / total, 2),
        "p95_ms": round(max((float(row.get("p95_ms") or 0.0) for row in rows), default=0.0), 2),
        "max_ms": round(max((float(row.get("max_ms") or 0.0) for row in rows), default=0.0), 2),
        "status": dict(sorted(status.items())),
        "slowest_routes": routes[:10],
    }


__all__ = [
    "DevObservatoryRecorder",
    "MUTATING_METHODS",
    "SEV_ERROR",
    "summarize_latency",
]
