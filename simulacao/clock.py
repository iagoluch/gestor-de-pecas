"""Relógio virtual do simulador, espelhado no relógio da API.

A API usa ``reference_time + (monotonic() - anchor) * scale``
(``backend/api/clock.py``). O simulador usa exatamente a mesma conta, ancorada
no mesmo instante, e mede periodicamente a diferença contra
``/api/v1/system/capabilities`` para que a deriva vire métrica e não suposição.

Nenhuma espera do simulador é um ``sleep`` arbitrário: toda espera é expressa
em minutos virtuais e convertida pela escala. ``aguardar_virtual`` acorda em
fatias curtas e recalcula o alvo pelo próprio relógio, de modo que uma pausa do
relógio da API (``/system/simulation/clock``) também segure a fábrica.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from time import monotonic


#: Fatia máxima de espera real. Mantém o cancelamento responsivo e permite que
#: uma pausa do relógio seja percebida rapidamente.
_SLICE_SECONDS = 0.25


class VirtualClock:
    def __init__(self, reference_time: datetime, scale: float):
        if scale <= 0:
            raise ValueError("A escala do relógio virtual precisa ser positiva.")
        self.reference_time = reference_time
        self.scale = float(scale)
        self._anchor = monotonic()
        self._real_start = datetime.now().replace(microsecond=0)
        self._paused = False
        self._paused_at: datetime | None = None
        self._drift_seconds = 0.0

    # ------------------------------------------------------------------
    @property
    def real_start(self) -> datetime:
        return self._real_start

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def drift_seconds(self) -> float:
        """Diferença medida entre o relógio local e o relógio da API."""

        return self._drift_seconds

    def elapsed_real(self) -> float:
        return max(0.0, monotonic() - self._anchor)

    def now(self) -> datetime:
        if self._paused and self._paused_at is not None:
            return self._paused_at
        return (
            self.reference_time + timedelta(seconds=self.elapsed_real() * self.scale)
        ).replace(microsecond=0)

    def real_now(self) -> datetime:
        return datetime.now().replace(microsecond=0)

    def real_seconds_for(self, virtual_seconds: float) -> float:
        return max(0.0, float(virtual_seconds)) / self.scale

    def virtual_seconds_for(self, real_seconds: float) -> float:
        return max(0.0, float(real_seconds)) * self.scale

    # ------------------------------------------------------------------
    def pause(self) -> None:
        if not self._paused:
            self._paused_at = self.now()
            self._paused = True

    def resume(self) -> None:
        if self._paused and self._paused_at is not None:
            self.reference_time = self._paused_at
            self._anchor = monotonic()
            self._paused = False
            self._paused_at = None

    def resync(self, api_reference: datetime) -> float:
        """Alinha o relógio local ao da API e devolve o ajuste aplicado.

        A API ancora quando o processo dela sobe, alguns segundos depois do
        simulador. Sem este alinhamento os dois ficariam deslocados por toda a
        execução — e, a 8×, poucos segundos reais viram minutos de fábrica.
        """

        ajuste = (api_reference - self.now()).total_seconds()
        self.reference_time = api_reference
        self._anchor = monotonic()
        self._paused = False
        self._paused_at = None
        self._drift_seconds = 0.0
        return ajuste

    def observe_api(self, api_reference: datetime) -> float:
        """Registra a deriva contra o relógio efetivo da API."""

        self._drift_seconds = (api_reference - self.now()).total_seconds()
        return self._drift_seconds

    # ------------------------------------------------------------------
    async def aguardar_virtual(self, virtual_seconds: float) -> None:
        """Espera ``virtual_seconds`` de fábrica, não de relógio de parede."""

        alvo = self.now() + timedelta(seconds=max(0.0, float(virtual_seconds)))
        while True:
            restante_virtual = (alvo - self.now()).total_seconds()
            if restante_virtual <= 0:
                return
            fatia = min(_SLICE_SECONDS, max(0.01, self.real_seconds_for(restante_virtual)))
            await asyncio.sleep(fatia)

    async def aguardar_ate(self, alvo: datetime) -> None:
        while self.now() < alvo:
            restante = (alvo - self.now()).total_seconds()
            fatia = min(_SLICE_SECONDS, max(0.01, self.real_seconds_for(restante)))
            await asyncio.sleep(fatia)

    def stamp(self) -> dict:
        return {
            "real_timestamp": self.real_now().isoformat(),
            "simulation_timestamp": self.now().isoformat(),
        }
