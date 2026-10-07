"""Tempo padrão manual e estimado: regras de escrita e recálculo.

Camada fina entre a API/jobs e ``StandardTimeRepositoryMixin``. A prioridade
da fonte e a estatística vivem em ``mes/domain/standard_time.py``.

Vigência (decisão do dono, 06/10/2026): período já fechado não muda por causa
de tempo padrão novo. O valor de um fato é o vigente no **instante de início do
apontamento**:

* manual: vale a partir do instante em que é definido, alterado ou removido
  (versões no histórico, ``vigente_desde``, TIMESTAMP); fato iniciado antes
  desse instante, mesmo no mesmo dia, mantém o valor que tinha, inclusive
  depois de remover o manual. Portanto a Performance **oficial** (Protheus +
  manual) de um período passado não muda por causa de manual novo. O Protheus
  segue a regra própria do catálogo e não é versionado aqui;
* estimado: só alcança fatos iniciados em ou após ``vigente_desde`` da chave
  (instante em que a estimativa passou a existir). Limitação aceita, pois é
  rótulo "estimada", em campo separado da Performance oficial: o P25
  recalculado a cada dia vale para todos os fatos entre ``vigente_desde`` e
  agora, e a chave que perde amostras e é removida no recálculo deixa de valer
  para todos os seus fatos.

O recálculo considera só execuções finalizadas **antes do início do dia do
cálculo**. Só um recálculo roda por vez no processo (endpoint manual e tick
diário compartilham ``_RECALCULATION_LOCK``); o concorrente recebe
``StandardTimeRecalculationBusy`` (409). O lock é de processo: com mais de um
processo da API o upsert idempotente continua seguro, mas o trabalho pode duplicar.
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, time, timedelta

from mes.contracts import AnalyticsFilter
from mes.domain.standard_time import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MIN_SAMPLES,
    MAX_MANUAL_SECONDS_PER_PIECE,
    estimate_standard_seconds,
    normalize_key,
    sector_accepts_standard_time,
)
from mes.services.industrial_analytics import IndustrialAnalyticsService

ESTIMATE_EVENT_TYPE = "tempo_padrao_estimado_recalculado"
#: Tamanho da janela de leitura de fatos no recálculo.
CHUNK_DAYS = 14
RECALCULATION_BUSY_CODE = "standard_time_recalculation_in_progress"
_RECALCULATION_LOCK = threading.Lock()


class StandardTimeRuleError(Exception):
    """Violação de regra com código estável e status HTTP sugerido."""

    def __init__(self, code: str, message: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class StandardTimeRecalculationBusy(StandardTimeRuleError):
    """Já existe um recálculo do estimado em andamento neste processo."""

    def __init__(self):
        super().__init__(
            RECALCULATION_BUSY_CODE,
            "Já existe um recálculo do tempo padrão estimado em andamento. Tente novamente em instantes.",
            409,
        )


@contextmanager
def _exclusive_recalculation():
    if not _RECALCULATION_LOCK.acquire(blocking=False):
        raise StandardTimeRecalculationBusy()
    try:
        yield
    finally:
        _RECALCULATION_LOCK.release()


class StandardTimeService:
    def __init__(self, db, now_func=None):
        self.db = db
        self._now = now_func or datetime.now

    # ------------------------------------------------------------------
    # Manual
    # ------------------------------------------------------------------
    def set_manual(
        self, produto, operacao, recurso, segundos_por_peca, *,
        observacao=None, usuario_id=None, usuario_nome=None,
    ) -> dict:
        key = normalize_key(produto, operacao, recurso)
        if not all(key):
            raise StandardTimeRuleError(
                "invalid_standard_time_key",
                "Informe produto, operação e recurso.",
                422,
            )
        seconds = self._validated_seconds(segundos_por_peca)
        context = self.db.obter_contexto_tempo_padrao(*key)
        if context is None:
            raise StandardTimeRuleError(
                "standard_time_operation_not_found",
                "Operação não encontrada no catálogo ativo (produto, operação e recurso).",
                404,
            )
        if any(not sector_accepts_standard_time(sector) for sector in context.get("setores") or ()):
            raise StandardTimeRuleError(
                "standard_time_sector_without_standard",
                "O Corte não recebe tempo padrão manual: o previsto vem do SigmaNEST.",
                409,
            )
        if context.get("tempo_protheus_segundos") is not None:
            raise StandardTimeRuleError(
                "standard_time_defined_by_protheus",
                "O Protheus já define o tempo padrão desta operação; o valor manual não é aceito.",
                409,
            )
        return self.db.definir_tempo_padrao_manual(
            *key, seconds,
            observacao=observacao, usuario_id=usuario_id, usuario_nome=usuario_nome,
        )

    def remove_manual(self, produto, operacao, recurso, *, usuario_id=None, usuario_nome=None) -> None:
        key = normalize_key(produto, operacao, recurso)
        removed = self.db.remover_tempo_padrao_manual(
            *key, usuario_id=usuario_id, usuario_nome=usuario_nome
        )
        if not removed:
            raise StandardTimeRuleError(
                "standard_time_manual_not_found",
                "Não há tempo padrão manual para esta operação.",
                404,
            )

    @staticmethod
    def _validated_seconds(value) -> float:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            seconds = float("nan")
        if not math.isfinite(seconds) or seconds <= 0 or seconds > MAX_MANUAL_SECONDS_PER_PIECE:
            raise StandardTimeRuleError(
                "invalid_standard_time",
                f"O tempo padrão deve ser maior que zero e no máximo {MAX_MANUAL_SECONDS_PER_PIECE:g} s por peça.",
                422,
            )
        return seconds

    # ------------------------------------------------------------------
    # Estimado
    # ------------------------------------------------------------------
    def recalculate_estimates(
        self, *, now: datetime | None = None,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        min_samples: int = DEFAULT_MIN_SAMPLES,
    ) -> dict:
        """Recalcula todas as chaves (idempotente) com P25 das execuções boas.

        Levanta ``StandardTimeRecalculationBusy`` se outro recálculo está em curso.
        """

        with _exclusive_recalculation():
            return self._recalculate(now, lookback_days, min_samples)

    def recalculate_estimates_if_due(self, now: datetime) -> bool:
        """Recalcula no máximo uma vez por dia; ``True`` quando recalculou.

        A checagem "já rodou hoje" acontece dentro do lock, então um recálculo
        manual que terminou há instantes não é repetido pelo tick diário.
        """

        with _exclusive_recalculation():
            last_run = self.last_estimate_run()
            if last_run is not None and last_run.date() >= now.date():
                return False
            self._recalculate(now, DEFAULT_LOOKBACK_DAYS, DEFAULT_MIN_SAMPLES)
            return True

    def _recalculate(self, now, lookback_days, min_samples) -> dict:
        now = now or self._now()
        window_end = datetime.combine(now.date(), time.min)
        window_start = window_end - timedelta(days=int(lookback_days))
        analytics = IndustrialAnalyticsService(self.db, now_func=lambda: now)
        # Janelas curtas: a consulta de fatos de 180 dias de uma vez estoura o
        # ``statement_timeout`` (30 s) em volume alto. Execução que cruza a
        # fronteira de duas janelas não é amostra (efeito desprezível).
        samples = []
        chunk_start = window_start
        while chunk_start < window_end:
            chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), window_end)
            samples.extend(
                analytics.standard_time_samples(
                    AnalyticsFilter(inicio=chunk_start, fim=chunk_end)
                )
            )
            chunk_start = chunk_end
        grouped = defaultdict(list)
        for sample in samples:
            key = normalize_key(sample["produto"], sample["operacao"], sample["recurso"])
            if all(key):
                grouped[key].append(sample)
        records = []
        for key, items in grouped.items():
            estimate = estimate_standard_seconds(
                [item["segundos_por_peca"] for item in items], min_samples=min_samples
            )
            if estimate is None:
                continue
            records.append({
                "produto": key[0],
                "operacao": key[1],
                "recurso": key[2],
                "segundos_por_peca": round(estimate.segundos_por_peca, 3),
                "amostras": estimate.amostras,
                "janela_inicio": min(item["inicio"] for item in items),
                "janela_fim": max(item["fim"] for item in items),
            })
        self.db.substituir_tempos_padrao_estimados(records, now)
        summary = {
            "calculado_em": now,
            "janela_inicio": window_start,
            "janela_fim": window_end,
            "execucoes_elegiveis": len(samples),
            "chaves_avaliadas": len(grouped),
            "chaves_estimadas": len(records),
            "amostra_minima": int(min_samples),
        }
        self.db.registrar_evento_sistema(
            tipo=ESTIMATE_EVENT_TYPE,
            origem="tempo_padrao",
            mensagem=(
                f"Tempo padrão estimado recalculado: {len(records)} de {len(grouped)} "
                f"chave(s) com amostra mínima ({len(samples)} execução(ões) elegível(is))."
            ),
            data_hora=now,
        )
        return summary

    def last_estimate_run(self):
        """Instante do último recálculo (``None`` se nunca rodou)."""

        event = self.db.ultimo_evento_sistema(tipos=[ESTIMATE_EVENT_TYPE])
        return event.get("data_hora") if event else None
