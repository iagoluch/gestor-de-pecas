"""Tempo padrão estimado: recálculo.

Camada fina entre a API/jobs e ``StandardTimeRepositoryMixin``. A prioridade
da fonte e a estatística vivem em ``mes/domain/standard_time.py``.

Tempo manual (decisão do usuário, 04/11/2026): o Gestor não grava mais tempo
padrão manual; só vale o do Protheus, ajustado pela engenharia direto no ERP.
Os manuais já gravados ficam no banco, mas não contam (ver o domínio).

Vigência (decisão do dono, 06/10/2026): período já fechado não muda por causa
de tempo padrão novo. O Protheus segue a regra própria do catálogo e não é
versionado aqui. O estimado só alcança fatos iniciados em ou após ``vigente_desde`` da chave
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

import json
import logging
import threading
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, time, timedelta

from mes.contracts import AnalyticsFilter
from mes.domain.standard_time import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_MIN_SAMPLES,
    estimate_standard_seconds,
    normalize_key,
)
from mes.services.industrial_analytics import IndustrialAnalyticsService

ESTIMATE_EVENT_TYPE = "tempo_padrao_estimado_recalculado"
#: Tamanho da janela de leitura de fatos no recálculo.
CHUNK_DAYS = 14
RECALCULATION_BUSY_CODE = "standard_time_recalculation_in_progress"
#: Código estável das rotas de escrita do tempo manual, desativadas em 04/11/2026.
MANUAL_DISABLED_CODE = "standard_time_manual_disabled"
MANUAL_DISABLED_MESSAGE = (
    "O Gestor não cadastra mais tempo padrão manual: só vale o tempo do Protheus. "
    "A engenharia de manufatura ajusta direto no ERP."
)
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


class RecalculationJob:
    """Estado do recálculo manual em segundo plano (botão da tela).

    Só em memória do processo: um reinício perde o estado (volta a ``idle``) e
    um recálculo em voo morre com o processo. A garantia de unicidade continua
    sendo ``_RECALCULATION_LOCK`` (e o advisory lock do repositório); este
    objeto só informa o progresso para o ``GET`` de status.

    ``start`` adquire ``_RECALCULATION_LOCK`` na thread da requisição, para o
    409 ser síncrono, e a thread de trabalho o libera ao terminar.
    """

    IDLE, RUNNING, DONE, ERROR = "idle", "running", "done", "error"

    def __init__(self):
        self._state_lock = threading.Lock()
        self._reset_state()

    def _reset_state(self) -> None:
        self._status = self.IDLE
        self._started_at = None
        self._finished_at = None
        self._error = None
        self._summary = None

    def reset(self) -> None:
        """Volta a ``idle`` (uso em testes); não toca no lock do recálculo."""

        with self._state_lock:
            self._reset_state()

    def snapshot(self) -> dict:
        with self._state_lock:
            return {
                "status": self._status,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "error": self._error,
                "summary": self._summary,
            }

    def start(self, service: "StandardTimeService") -> datetime:
        """Dispara o recálculo em thread; 409 se já houver um em andamento."""

        if not _RECALCULATION_LOCK.acquire(blocking=False):
            raise StandardTimeRecalculationBusy()
        try:
            started_at = service._now()
            with self._state_lock:
                self._status = self.RUNNING
                self._started_at = started_at
                self._finished_at = None
                self._error = None
                self._summary = None
            threading.Thread(
                target=self._run,
                args=(service,),
                name="gestor-standard-time-manual",
                daemon=True,
            ).start()
        except BaseException:
            _RECALCULATION_LOCK.release()
            raise
        return started_at

    def _run(self, service: "StandardTimeService") -> None:
        summary = None
        error = None
        try:
            try:
                summary = service._recalculate(None, DEFAULT_LOOKBACK_DAYS, DEFAULT_MIN_SAMPLES)
            except Exception as exc:
                # Nunca engolir: stack no log; o status leva só uma mensagem curta.
                logging.exception("Recálculo manual do tempo padrão estimado falhou.")
                if isinstance(exc, StandardTimeRuleError):
                    error = exc.message
                else:
                    error = f"Falha ao recalcular ({type(exc).__name__}). Consulte o log do servidor."
            # O estado final é gravado antes de soltar o lock, para um novo
            # ``start`` não ser sobrescrito por este término.
            with self._state_lock:
                self._finished_at = service._now()
                if error is None:
                    self._status, self._summary = self.DONE, summary
                else:
                    self._status, self._error = self.ERROR, error
        finally:
            _RECALCULATION_LOCK.release()


RECALCULATION_JOB = RecalculationJob()


class StandardTimeService:
    def __init__(self, db, now_func=None):
        self.db = db
        self._now = now_func or datetime.now

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
        # Janelas curtas: a consulta de fatos de 180 dias de uma vez estoura o
        # ``statement_timeout`` (30 s) em volume alto. Execução que cruza a
        # fronteira de duas janelas não é amostra (efeito desprezível).
        # Um serviço por janela: o cache de fatos/timelines morre com ela, e a
        # memória fica limitada a uma janela. A leitura de fatos é enxuta (sem
        # operadores por evento, que as amostras não usam).
        samples = []
        chunk_start = window_start
        while chunk_start < window_end:
            chunk_end = min(chunk_start + timedelta(days=CHUNK_DAYS), window_end)
            analytics = IndustrialAnalyticsService(
                self.db, now_func=lambda: now, lean_facts=True
            )
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
            # JSON para a explicação do resumo (std.recalculo) reler os números sem refazer a conta.
            detalhes=json.dumps({k: v.isoformat() if isinstance(v, datetime) else v for k, v in summary.items()}),
            data_hora=now,
        )
        return summary

    def last_estimate_run(self):
        """Instante do último recálculo (``None`` se nunca rodou)."""

        event = self.db.ultimo_evento_sistema(tipos=[ESTIMATE_EVENT_TYPE])
        return event.get("data_hora") if event else None
