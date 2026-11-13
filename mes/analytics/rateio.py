"""Rateio explícito de tempo sem confundir tempo físico com tempo atribuído."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Hashable, Iterable, Mapping, Sequence

from app.core.resource_mapping import resolve_resource_identity
from mes.analytics.intervals import merge_intervals
from mes.domain import AllocationStrategy, EventCategory

def allocate_duration(
    physical_seconds: float,
    operation_keys: Sequence[str],
    *,
    strategy: AllocationStrategy,
    weights: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Distribui tempo físico sem criar minutos artificiais.

    A função não escolhe uma regra por conta própria. O chamador é obrigado a
    informar a estratégia. Em qualquer estratégia a soma atribuída é igual ao
    tempo físico (salvo arredondamento de ponto flutuante).
    """

    keys = [str(key) for key in operation_keys if str(key)]
    if not keys:
        return {}
    total = max(0.0, float(physical_seconds or 0))
    if strategy == AllocationStrategy.EQUAL:
        base = {key: 1.0 for key in keys}
    elif strategy in {
        AllocationStrategy.QUANTITY,
        AllocationStrategy.STANDARD_TIME,
        AllocationStrategy.PROPORTIONAL,
        AllocationStrategy.MANUAL,
    }:
        if not weights:
            raise ValueError(f"A estratégia {strategy.value} exige pesos explícitos.")
        base = {key: max(0.0, float(weights.get(key, 0) or 0)) for key in keys}
    else:  # defesa para enums futuros
        raise ValueError(f"Estratégia de rateio não suportada: {strategy}")

    weight_total = sum(base.values())
    if weight_total <= 0:
        raise ValueError("Os pesos do rateio devem possuir soma maior que zero.")

    result = {key: total * (weight / weight_total) for key, weight in base.items()}
    # Fecha a diferença de ponto flutuante no último item para garantir conservação.
    last = keys[-1]
    result[last] += total - sum(result.values())
    return result


def canonical_resource_key(resource) -> str:
    """Chave única do recurso físico: identidade canônica, sem caixa.

    Alias ("Laser Ensis 3015"), código ("LASER1") e variações de caixa do mesmo
    posto resultam na mesma chave. É a identidade usada pelo rateio e por quem
    agrupa o resultado dele (por exemplo, o arredondamento por recurso).
    """

    return str(resolve_resource_identity(resource) or resource or "").strip().upper()


# ----------------------------------------------------------------------
# Rateio por crachá — Metodologia de Tempos e Rateios V2 (Manufatura,
# 13/11/2026), regra máxima de tempo do Gestor.
#
# * Só a PRODUÇÃO conta HM/HH; setup, parada etc. ficam nas suas categorias.
# * Em cada trecho, o crachá que atende ``n`` OPs dá ``dt/n`` de HH a cada uma.
# * HH da OP = soma das frações dos crachás; HM da OP = maior fração × dt.
# * Crachás exclusivos no mesmo recurso são frentes independentes: cada OP
#   recebe o trecho inteiro (o HM do recurso pode passar do relógio).
# * OP produzindo sem crachá: HM pendente, HH zero (nunca inventa tempo).
# * Caso misto (frações diferentes na mesma OP) usa a maior fração e é
#   marcado como "regra proposta"; crachá em dois recursos é "conflito".
# ----------------------------------------------------------------------

REASON_EXCLUSIVE = "exclusivo"
REASON_SHARED = "rateio_cracha"
REASON_PROPOSED = "rateio_cracha_regra_proposta"
REASON_CONFLICT = "conflito_cracha_recursos"
REASON_PENDING = "pendente_sem_cracha"


@dataclass(frozen=True)
class TrailSlice:
    """Linha da trilha de auditoria: um trecho contínuo de uma execução."""

    key: Hashable
    resource: str
    start: datetime
    end: datetime
    seconds: float
    badges: tuple  # ((crachá, fração), ...)
    hm_seconds: float
    hh_seconds: float
    reason: str


@dataclass(frozen=True)
class BadgeAllocation:
    hm: dict          # execução -> HM operacional (s)
    hh: dict          # execução -> HH (s)
    pending: dict     # execução -> produção sem crachá (s)
    proposed: frozenset
    conflict: frozenset
    hh_by_badge: dict  # crachá -> {execução: HH (s)}
    clock: dict       # recurso canônico -> relógio com alguma OP produzindo (s)
    trail: tuple

    def flag(self, key) -> str | None:
        """O alerta mais forte da execução, para quem mostra um rótulo só."""

        if self.pending.get(key, 0.0) > 0:
            return REASON_PENDING
        if key in self.conflict:
            return REASON_CONFLICT
        if key in self.proposed:
            return REASON_PROPOSED
        return None


def production_spans(timeline) -> list[tuple]:
    """Intervalos [início, fim) de PRODUÇÃO de uma ``TimelineResult``."""

    if timeline is None:
        return []
    return [
        (segment.start, segment.end)
        for segment in timeline.segments
        if segment.category == EventCategory.PRODUCTION
    ]


def participation_rows(rows: Iterable[Mapping]) -> list[tuple]:
    """Linhas de ``participacoes_operador`` -> ``(apontamento, crachá, início, fim)``."""

    result = []
    for row in rows or ():
        badge = str(row.get("cracha_resolvido") or row.get("cracha") or "").strip()
        if row.get("apontamento_id") is None or not badge or row.get("data_inicio") is None:
            continue
        result.append((row["apontamento_id"], badge, row["data_inicio"], row.get("data_fim")))
    return result


def _intersect(spans, start, end):
    return [
        (max(span_start, start), min(span_end, end))
        for span_start, span_end in spans
        if max(span_start, start) < min(span_end, end)
    ]


def allocate_by_badge(
    executions: Iterable[tuple[Hashable, str, Iterable[tuple]]],
    participations: Iterable[tuple[Hashable, str, datetime, datetime | None]],
) -> BadgeAllocation:
    """Motor de HM/HH por crachá.

    ``executions``: ``(chave, recurso, [(início, fim), ...])`` com os trechos
    de PRODUÇÃO de cada execução (OP + operação).
    ``participations``: ``(chave, crachá, início, fim)``; ``fim=None`` é
    vínculo aberto. Participação de execução fora de ``executions`` é ignorada.

    Intervalos semiabertos; o resultado não depende da ordem de entrada.
    """

    production: dict = {}
    resource_of: dict = {}
    for key, resource, spans in executions:
        merged = merge_intervals(spans)
        if merged:
            production[key] = merge_intervals(production.get(key, []) + merged)
            resource_of[key] = canonical_resource_key(resource)

    # O vínculo crachá↔execução só vale enquanto a execução produz; sobreposição
    # do mesmo crachá na mesma execução vira um intervalo só (E03).
    linked: dict = defaultdict(list)
    for key, badge, start, end in participations:
        spans = production.get(key)
        badge = str(badge or "").strip().upper()
        if not spans or not badge or start is None:
            continue
        linked[(badge, key)].extend(_intersect(spans, start, end or spans[-1][1]))

    edges: dict = defaultdict(lambda: ([], [], [], []))
    for key, spans in production.items():
        for start, end in spans:
            edges[start][0].append(key)
            edges[end][1].append(key)
    for pair, spans in linked.items():
        for start, end in merge_intervals(spans):
            edges[start][2].append(pair)
            edges[end][3].append(pair)

    hm: dict = {key: 0.0 for key in production}
    hh: dict = {key: 0.0 for key in production}
    pending: dict = defaultdict(float)
    hh_by_badge: dict = defaultdict(lambda: defaultdict(float))
    clock: dict = defaultdict(float)
    proposed, conflict = set(), set()
    trail: list = []
    last_slice: dict = {}

    active_keys, active_pairs = set(), set()
    previous = None
    for moment in sorted(edges):
        if previous is not None and active_keys:
            dt = (moment - previous).total_seconds()
            ops_of_badge: dict = defaultdict(set)
            for badge, key in active_pairs:
                ops_of_badge[badge].add(key)
            badges_of_op: dict = defaultdict(list)
            for badge, keys in ops_of_badge.items():
                for key in keys:
                    badges_of_op[key].append(badge)
            for resource in {resource_of[key] for key in active_keys}:
                clock[resource] += dt
            for key in sorted(active_keys, key=str):
                badges = sorted(badges_of_op.get(key, ()))
                fractions = tuple((badge, 1.0 / len(ops_of_badge[badge])) for badge in badges)
                if not badges:
                    reason, slice_hm, slice_hh = REASON_PENDING, 0.0, 0.0
                    pending[key] += dt
                else:
                    slice_hm = dt * max(fraction for _badge, fraction in fractions)
                    slice_hh = sum(dt * fraction for _badge, fraction in fractions)
                    for badge, fraction in fractions:
                        hh_by_badge[badge][key] += dt * fraction
                    if any(
                        len({resource_of[other] for other in ops_of_badge[badge]}) > 1
                        for badge in badges
                    ):
                        reason = REASON_CONFLICT
                        conflict.add(key)
                    elif len({fraction for _badge, fraction in fractions}) > 1:
                        reason = REASON_PROPOSED
                        proposed.add(key)
                    elif fractions[0][1] < 1.0:
                        reason = REASON_SHARED
                    else:
                        reason = REASON_EXCLUSIVE
                hm[key] += slice_hm
                hh[key] += slice_hh
                # Trechos seguidos iguais viram uma linha só na trilha.
                prior = last_slice.get(key)
                if (
                    prior is not None
                    and trail[prior].end == previous
                    and trail[prior].badges == fractions
                    and trail[prior].reason == reason
                ):
                    item = trail[prior]
                    trail[prior] = TrailSlice(
                        key, item.resource, item.start, moment, item.seconds + dt,
                        fractions, item.hm_seconds + slice_hm,
                        item.hh_seconds + slice_hh, reason,
                    )
                else:
                    last_slice[key] = len(trail)
                    trail.append(TrailSlice(
                        key, resource_of[key], previous, moment, dt, fractions,
                        slice_hm, slice_hh, reason,
                    ))
        opened, closed, pair_opened, pair_closed = edges[moment]
        active_keys.difference_update(closed)
        active_keys.update(opened)
        active_pairs.difference_update(pair_closed)
        active_pairs.update(pair_opened)
        previous = moment

    return BadgeAllocation(
        hm=hm,
        hh=hh,
        pending=dict(pending),
        proposed=frozenset(proposed),
        conflict=frozenset(conflict),
        hh_by_badge={badge: dict(per_key) for badge, per_key in hh_by_badge.items()},
        clock=dict(clock),
        trail=tuple(sorted(trail, key=lambda item: (item.start, str(item.key)))),
    )
