"""Fonte de tempo da API, com aceleração exclusiva do modo de simulação.

O relógio nunca altera Windows ou PostgreSQL. Em modo normal ele apenas delega
para ``datetime.now``. Em simulação, ancora uma data virtual em
``time.monotonic`` para que todas as requisições observem o mesmo avanço
contínuo, inclusive quando são atendidas por threads diferentes.

O relógio de simulação também pode ser pausado e retomado. Pausar congela a
data virtual no instante corrente, sem perder a escala configurada, para que a
fábrica simulada possa ser inspecionada nas telas sem continuar avançando.
Fora do modo de simulação, pausar não tem efeito: o tempo real nunca é tocado.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock
from time import monotonic


class ApplicationClock:
    """Relógio monotônico compartilhado pela instância FastAPI."""

    def __init__(
        self,
        *,
        simulation_mode: bool = False,
        reference_time: datetime | None = None,
        scale: float = 0.0,
        monotonic_func=monotonic,
    ):
        self.simulation_mode = bool(simulation_mode)
        self.reference_time = reference_time
        self.scale = max(0.0, float(scale or 0.0))
        self._monotonic = monotonic_func
        self._real_anchor = self._monotonic()
        self._paused = False
        self._lock = Lock()

    @property
    def paused(self) -> bool:
        return bool(self.simulation_mode and self._paused)

    @property
    def running(self) -> bool:
        return bool(
            self.simulation_mode
            and self.reference_time is not None
            and self.scale > 0
            and not self._paused
        )

    def now(self) -> datetime:
        if not self.simulation_mode or self.reference_time is None:
            return datetime.now().replace(microsecond=0)
        if not self.running:
            return self.reference_time.replace(microsecond=0)
        elapsed_real = max(0.0, self._monotonic() - self._real_anchor)
        return (
            self.reference_time + timedelta(seconds=elapsed_real * self.scale)
        ).replace(microsecond=0)

    def pause(self) -> bool:
        """Congela a data virtual. Retorna ``True`` quando o estado mudou."""

        if not self.simulation_mode:
            return False
        with self._lock:
            if self._paused:
                return False
            self.reference_time = self.now()
            self._paused = True
            return True

    def resume(self) -> bool:
        """Retoma a contagem a partir da data virtual congelada."""

        if not self.simulation_mode:
            return False
        with self._lock:
            if not self._paused:
                return False
            self._real_anchor = self._monotonic()
            self._paused = False
            return True


__all__ = ["ApplicationClock"]
