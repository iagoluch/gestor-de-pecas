"""Taxonomia canônica de ocorrências observadas em execução.

Os rótulos são os mesmos já usados pelo observatório da simulação
(``simulacao/telemetry.py``, seção 19). A definição vive aqui, no backend real,
porque o Dev Observatory é permanente e não pode depender de um pacote de
simulação: quem roda em produção/homologação é este módulo.

A distinção que importa para o desenvolvedor é uma só:

* ``EXPECTED_BLOCK``   — o Gestor **decidiu** recusar. Crachá inválido, OP já
  finalizada, primeira peça bloqueada. Não é bug; é a regra funcionando.
* ``EXPECTED_VALIDATION`` — recusa de contrato/entrada (422, 4xx sem código de
  negócio). Também não é bug, mas costuma indicar cliente desalinhado.
* ``REAL_ERROR``       — exceção não tratada. Sempre bug.
* ``TECHNICAL_ERROR``  — infraestrutura (banco indisponível, 5xx de
  dependência). Não é bug de regra, mas quebra o operador.
* ``PERFORMANCE_ERROR``— a resposta veio certa e tarde demais.
* ``OK``               — sucesso.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any


# --- Classificações canônicas ----------------------------------------------
EXPECTED_BLOCK = "EXPECTED_BLOCK"
EXPECTED_VALIDATION = "EXPECTED_VALIDATION"
REAL_ERROR = "REAL_ERROR"
TECHNICAL_ERROR = "TECHNICAL_ERROR"
PERFORMANCE_ERROR = "PERFORMANCE_ERROR"
OK = "OK"

CLASSIFICATIONS = (
    OK,
    EXPECTED_BLOCK,
    EXPECTED_VALIDATION,
    PERFORMANCE_ERROR,
    TECHNICAL_ERROR,
    REAL_ERROR,
)

#: Classificações que representam defeito do sistema, não decisão de negócio.
DEFECT_CLASSIFICATIONS = frozenset({REAL_ERROR, TECHNICAL_ERROR, PERFORMANCE_ERROR})

# --- Severidades ------------------------------------------------------------
SEV_INFO = "INFO"
SEV_EXPECTED = "EXPECTED_BLOCK"
SEV_WARNING = "WARNING"
SEV_ERROR = "ERROR"
SEV_CRITICAL = "CRITICAL"


#: Campos que nunca podem ser gravados em um artefato do observatório, mesmo
#: que cheguem por engano dentro de um payload de erro.
_REDACTED_KEYS = frozenset(
    {
        "apikey",
        "api_key",
        "authorization",
        "cookie",
        "csrf",
        "groq_api_key",
        "password",
        "secret",
        "senha",
        "senha_hash",
        "session",
        "set-cookie",
        "token",
        "x-csrf-token",
    }
)


def sanitize(value: Any, *, depth: int = 0) -> Any:
    """Remove segredos de qualquer estrutura antes de persisti-la."""

    if depth > 8:
        return "<profundidade máxima>"
    if isinstance(value, dict):
        return {
            str(key): (
                "<omitido>"
                if str(key).strip().casefold() in _REDACTED_KEYS
                else sanitize(item, depth=depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize(item, depth=depth + 1) for item in list(value)[:200]]
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def classify_http(
    *,
    status: int,
    error_code: str | None = None,
    unhandled: bool = False,
    latency_ms: float | None = None,
    latency_warning_ms: float = 1_000.0,
    latency_error_ms: float = 3_000.0,
) -> tuple[str, str]:
    """Classifica uma resposta HTTP já produzida pelo Gestor.

    ``unhandled`` vem do funil de erros: só o handler genérico de ``Exception``
    o liga, e ele significa exatamente "ninguém previu isto".
    """

    if unhandled:
        return REAL_ERROR, SEV_CRITICAL
    if status >= 500:
        return TECHNICAL_ERROR, SEV_ERROR
    if status == 503:
        return TECHNICAL_ERROR, SEV_ERROR
    if status < 400:
        if latency_ms is not None and latency_ms >= latency_error_ms:
            return PERFORMANCE_ERROR, SEV_ERROR
        if latency_ms is not None and latency_ms >= latency_warning_ms:
            return OK, SEV_WARNING
        return OK, SEV_INFO
    if status == 422:
        return EXPECTED_VALIDATION, SEV_WARNING
    if error_code and error_code not in {"http_error", "validation_error"}:
        # Código de negócio emitido por ``AppError``/``ReportError``: a recusa
        # foi uma decisão explícita do domínio.
        return EXPECTED_BLOCK, SEV_EXPECTED
    return EXPECTED_VALIDATION, SEV_WARNING
