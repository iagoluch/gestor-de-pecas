"""Tempo padrão por peça: fontes, prioridade e estimativa estatística.

Regras (decisões do usuário, 06/10/2026):

* prioridade da fonte: ``protheus`` (valor real) > ``manual`` (engenharia de
  manufatura) > ``estimado`` (P25 das execuções boas do Gestor) > ``None``;
* a Performance **oficial** usa só ``protheus`` e ``manual``; a **estimada**
  usa também ``estimado`` e é publicada em campo separado;
* o Corte nunca recebe tempo manual nem estimado: o previsto vem do SigmaNEST;
* manual e estimado têm vigência (ver ``mes/services/standard_time.py``): valem
  só para fatos iniciados a partir do instante em que passaram a existir.

Este módulo é puro: sem banco, sem relógio, sem I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

SOURCE_PROTHEUS = "protheus"
SOURCE_MANUAL = "manual"
SOURCE_ESTIMATED = "estimado"

#: Fontes aceitas na Performance oficial (tudo que não é estimativa do Gestor).
OFFICIAL_SOURCES = frozenset({SOURCE_PROTHEUS, SOURCE_MANUAL})

#: Setor cujo previsto vem do SigmaNEST (espelha ``mapper._SECTOR_WITHOUT_TOTVS_STANDARD``).
SECTOR_WITHOUT_STANDARD_TIME = "corte"

#: Amostra mínima de execuções elegíveis (já sem outliers) para estimar.
DEFAULT_MIN_SAMPLES = 5
#: Percentil usado como "capacidade demonstrada" (decisão A).
DEFAULT_PERCENTILE = 25.0
#: Multiplicador do IQR para descartar outliers.
IQR_FACTOR = 1.5
#: Teto aceito para o tempo manual: 24 h por peça.
MAX_MANUAL_SECONDS_PER_PIECE = 86400.0
#: Histórico considerado no cálculo do estimado.
DEFAULT_LOOKBACK_DAYS = 180


def sector_accepts_standard_time(sector) -> bool:
    return str(sector or "").strip().casefold() != SECTOR_WITHOUT_STANDARD_TIME


def _strip_key_part(value) -> str:
    # Só o espaço ASCII: é exatamente o que o ``BTRIM`` do SQL remove. ``str.strip()``
    # sem argumento também tira tab/quebra/NBSP, e a chave do Python deixaria de
    # casar com a do banco (``UPPER(BTRIM(coluna))``) para valores com esses bytes.
    return str(value or "").strip(" ")


def normalize_key(produto, operacao, recurso) -> tuple[str, str, str]:
    """Chave canônica ``(produto, operação, recurso)`` das tabelas de padrão.

    Equivale a ``UPPER(BTRIM(x))`` (produto/recurso) e ``BTRIM(x)`` (operação)
    do SQL; ver ``tests/test_standard_time_postgres.py``.
    """

    return (
        _strip_key_part(produto).upper(),
        _strip_key_part(operacao),
        _strip_key_part(recurso).upper(),
    )


def resolve_fact_standard(fact: Mapping) -> tuple[float | None, str | None]:
    """Tempo padrão efetivo e fonte de um fato operacional.

    Fatos que trazem ``tempo_padrao_fonte`` (consulta atual) são usados como
    estão. Fatos legados/dublês só com ``tempo_medio_segundos`` valem como
    ``protheus``, que é o significado histórico dessa coluna.
    """

    if "tempo_padrao_fonte" in fact:
        value = _positive(fact.get("tempo_padrao_segundos"))
        source = fact.get("tempo_padrao_fonte")
        return (value, source) if value is not None and source else (None, None)
    legacy = fact.get("tempo_medio_segundos")
    if legacy is None:
        return None, None
    return float(legacy), SOURCE_PROTHEUS


def official_standard_seconds(fact: Mapping) -> float | None:
    value, source = resolve_fact_standard(fact)
    return value if source in OFFICIAL_SOURCES else None


def estimated_view_standard_seconds(fact: Mapping) -> float | None:
    """Padrão da leitura "estimada": oficial + estimado."""

    value, _source = resolve_fact_standard(fact)
    return value


def _positive(value) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if number > 0 else None


def percentile(values: Iterable[float], pct: float) -> float:
    """Percentil por interpolação linear entre ranks (método 7, o do NumPy).

    ``rank = pct/100 * (n - 1)``; o resultado interpola entre os dois valores
    ordenados vizinhos de ``rank``. Exige ao menos um valor.
    """

    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentil exige ao menos um valor")
    rank = (pct / 100.0) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def drop_outliers(values: Iterable[float]) -> list[float]:
    """Remove valores fora de ``[Q1 - 1,5 IQR, Q3 + 1,5 IQR]`` (quartis método 7)."""

    data = sorted(float(value) for value in values)
    if len(data) < 4:
        return data
    q1 = percentile(data, 25.0)
    q3 = percentile(data, 75.0)
    spread = (q3 - q1) * IQR_FACTOR
    low, high = q1 - spread, q3 + spread
    return [value for value in data if low <= value <= high]


@dataclass(frozen=True)
class StandardEstimate:
    segundos_por_peca: float
    amostras: int
    amostras_brutas: int


def estimate_standard_seconds(
    samples: Iterable[float],
    *,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    pct: float = DEFAULT_PERCENTILE,
) -> StandardEstimate | None:
    """P25 dos segundos/peça após descartar outliers; ``None`` abaixo do mínimo.

    Valores não positivos ou não numéricos são ignorados. O mínimo vale para a
    amostra **depois** do descarte de outliers: poucas amostras consistentes
    não viram padrão.
    """

    clean = [float(v) for v in samples if v is not None and float(v) > 0]
    kept = drop_outliers(clean)
    if len(kept) < max(1, int(min_samples)):
        return None
    return StandardEstimate(
        segundos_por_peca=percentile(kept, pct),
        amostras=len(kept),
        amostras_brutas=len(clean),
    )


__all__ = [
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_MIN_SAMPLES",
    "MAX_MANUAL_SECONDS_PER_PIECE",
    "OFFICIAL_SOURCES",
    "SOURCE_ESTIMATED",
    "SOURCE_MANUAL",
    "SOURCE_PROTHEUS",
    "StandardEstimate",
    "drop_outliers",
    "estimate_standard_seconds",
    "estimated_view_standard_seconds",
    "normalize_key",
    "official_standard_seconds",
    "percentile",
    "resolve_fact_standard",
    "sector_accepts_standard_time",
]
