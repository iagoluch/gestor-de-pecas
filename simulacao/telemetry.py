"""Registro de evidências da simulação (seções 35, 38, 39 e 42).

Cada artefato é um JSONL append-only gravado em ``simulation_runs/<run>/``. O
buffer em memória é limitado de propósito: o observatório precisa dos eventos
recentes, mas a simulação não pode crescer sem limite em RAM. A verdade
completa está sempre no arquivo.

Nada aqui filtra severidade: mascarar erro é proibido pela seção 46. O que o
classificador decide é *como* a ocorrência é rotulada, nunca se ela existe.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
import threading
from typing import Any


# --- Classificações canônicas (seção 19) -----------------------------------
EXPECTED_BLOCK = "EXPECTED_BLOCK"
EXPECTED_VALIDATION = "EXPECTED_VALIDATION"
REAL_ERROR = "REAL_ERROR"
TECHNICAL_ERROR = "TECHNICAL_ERROR"
UI_ERROR = "UI_ERROR"
PERFORMANCE_ERROR = "PERFORMANCE_ERROR"
DATA_INCONSISTENCY = "DATA_INCONSISTENCY"
SIMULATOR_ERROR = "SIMULATOR_ERROR"
OK = "OK"

# --- Severidades (seção 35) -------------------------------------------------
SEV_INFO = "INFO"
SEV_EXPECTED = "EXPECTED_BLOCK"
SEV_WARNING = "WARNING"
SEV_ERROR = "ERROR"
SEV_CRITICAL = "CRITICAL"


#: Campos que nunca podem aparecer em um artefato, mesmo que cheguem por engano
#: dentro de um payload de erro (seção 38).
_REDACTED_KEYS = frozenset(
    {
        "password",
        "senha",
        "senha_hash",
        "token",
        "authorization",
        "cookie",
        "set-cookie",
        "api_key",
        "apikey",
        "groq_api_key",
        "secret",
        "session",
    }
)


def sanitize(value: Any, *, depth: int = 0) -> Any:
    """Remove segredos de qualquer estrutura antes de gravá-la."""

    if depth > 8:
        return "<profundidade máxima>"
    if isinstance(value, dict):
        return {
            key: ("<omitido>" if str(key).strip().casefold() in _REDACTED_KEYS
                  else sanitize(item, depth=depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize(item, depth=depth + 1) for item in value[:200]]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


@dataclass
class _Stream:
    path: Path
    buffer: deque = field(default_factory=lambda: deque(maxlen=400))
    count: int = 0


class Telemetry:
    """Escritor único de artefatos, seguro para uso concorrente."""

    STREAMS = (
        "events",
        "errors",
        "expected_blocks",
        "performance",
        "visual_events",
        "database_metrics",
        "consistency",
    )

    def __init__(self, run_dir: Path, clock):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        (self.run_dir / "screenshots").mkdir(exist_ok=True)
        self._clock = clock
        self._lock = threading.Lock()
        self._sequence = 0
        self._files: dict[str, Any] = {}
        self._streams = {
            name: _Stream(self.run_dir / f"{name}.jsonl") for name in self.STREAMS
        }
        for name, stream in self._streams.items():
            self._files[name] = stream.path.open("a", encoding="utf-8")
        self.severity_counter: Counter = Counter()
        self.classification_counter: Counter = Counter()
        self.code_counter: Counter = Counter()

    # ------------------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            for handle in self._files.values():
                try:
                    handle.flush()
                    handle.close()
                except Exception:  # pragma: no cover - encerramento tolerante
                    pass
            self._files.clear()

    def _write(self, stream_name: str, payload: dict) -> dict:
        with self._lock:
            self._sequence += 1
            payload["sequence"] = self._sequence
            stream = self._streams[stream_name]
            stream.count += 1
            stream.buffer.append(payload)
            handle = self._files.get(stream_name)
            if handle is not None:
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
                handle.flush()
        return payload

    # ------------------------------------------------------------------
    def registrar_evento(
        self,
        *,
        operator: str | None = None,
        resource: str | None = None,
        sector: str | None = None,
        op: str | None = None,
        product: str | None = None,
        action: str,
        endpoint: str | None = None,
        http_status: int | None = None,
        latency_ms: float | None = None,
        result: str = "",
        state_before: str | None = None,
        state_after: str | None = None,
        classification: str = OK,
        severity: str = SEV_INFO,
        error_code: str | None = None,
        exception: str | None = None,
        correlation_id: str | None = None,
        details: dict | None = None,
    ) -> dict:
        payload = {
            **self._clock.stamp(),
            "operator": operator,
            "resource": resource,
            "sector": sector,
            "op": op,
            "product": product,
            "action": action,
            "endpoint": endpoint,
            "http_status": http_status,
            "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
            "result": result,
            "state_before": state_before,
            "state_after": state_after,
            "classification": classification,
            "severity": severity,
            "error_code": error_code,
            "exception": exception,
            "correlation_id": correlation_id,
            "details": sanitize(details or {}),
        }
        self.severity_counter[severity] += 1
        self.classification_counter[classification] += 1
        if error_code:
            self.code_counter[error_code] += 1
        self._write("events", payload)
        if classification == EXPECTED_BLOCK:
            self._write("expected_blocks", payload)
        elif severity in {SEV_ERROR, SEV_CRITICAL} or classification in {
            REAL_ERROR,
            TECHNICAL_ERROR,
            DATA_INCONSISTENCY,
            SIMULATOR_ERROR,
            PERFORMANCE_ERROR,
        }:
            self._write("errors", payload)
        return payload

    def registrar_performance(self, sample: dict) -> dict:
        return self._write("performance", {**self._clock.stamp(), **sanitize(sample)})

    def registrar_banco(self, sample: dict) -> dict:
        return self._write("database_metrics", {**self._clock.stamp(), **sanitize(sample)})

    def registrar_visual(self, sample: dict) -> dict:
        return self._write("visual_events", {**self._clock.stamp(), **sanitize(sample)})

    def registrar_consistencia(self, sample: dict) -> dict:
        return self._write("consistency", {**self._clock.stamp(), **sanitize(sample)})

    # ------------------------------------------------------------------
    def recentes(self, stream_name: str, limit: int = 60) -> list[dict]:
        stream = self._streams.get(stream_name)
        if stream is None:
            return []
        return list(stream.buffer)[-limit:]

    def totais(self) -> dict:
        return {name: stream.count for name, stream in self._streams.items()}

    def salvar_json(self, nome: str, payload: Any) -> Path:
        destino = self.run_dir / nome
        destino.write_text(
            json.dumps(sanitize(payload), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return destino
