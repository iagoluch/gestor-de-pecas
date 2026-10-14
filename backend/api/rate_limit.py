"""Tetos em memória do processo: conexões SSE abertas e frequência de ações.

A API roda num único processo uvicorn (``deploy/instalar_vm.ps1``), então um
contador em memória basta. Nada aqui grava no banco.
"""

from __future__ import annotations

from collections import deque
from threading import Lock
import time
import weakref


class StreamLease:
    """Vaga ocupada por um stream; ``release`` pode ser chamado mais de uma vez."""

    def __init__(self, slots: "StreamSlots", user_id):
        self._slots = slots
        self._user_id = user_id
        self._released = False

    def release(self) -> None:
        with self._slots._lock:
            if self._released:
                return
            self._released = True
            self._slots._total -= 1
            if self._user_id is not None:
                remaining = self._slots._per_user_count.get(self._user_id, 1) - 1
                if remaining > 0:
                    self._slots._per_user_count[self._user_id] = remaining
                else:
                    self._slots._per_user_count.pop(self._user_id, None)


class StreamSlots:
    """Teto global e, opcionalmente, por usuário de streams abertos ao mesmo tempo."""

    def __init__(self, *, total: int, per_user: int | None = None):
        self.total_limit = int(total)
        self.per_user_limit = int(per_user) if per_user is not None else None
        self._lock = Lock()
        self._total = 0
        self._per_user_count: dict = {}

    @property
    def in_use(self) -> int:
        with self._lock:
            return self._total

    def try_acquire(self, user_id=None) -> StreamLease | None:
        with self._lock:
            if self._total >= self.total_limit:
                return None
            if self.per_user_limit is not None and user_id is not None:
                if self._per_user_count.get(user_id, 0) >= self.per_user_limit:
                    return None
                self._per_user_count[user_id] = self._per_user_count.get(user_id, 0) + 1
            self._total += 1
            return StreamLease(self, user_id if self.per_user_limit is not None else None)


def hold_while_streaming(lease: StreamLease, iterator):
    """Devolve a vaga quando o stream termina, por qualquer caminho.

    O ``finally`` cobre o fim normal e a desconexão. O ``weakref.finalize``
    cobre o caso raro do gerador nunca ter começado (cliente caiu antes do
    primeiro byte), quando o ``finally`` não chega a rodar.
    """

    async def guarded():
        try:
            async for chunk in iterator:
                yield chunk
        finally:
            lease.release()

    generator = guarded()
    weakref.finalize(generator, lease.release)
    return generator


class SlidingWindowLimiter:
    """No máximo ``limit`` eventos por chave dentro de ``window_seconds``."""

    _SWEEP_ABOVE = 1_000

    def __init__(self, *, limit: int, window_seconds: float = 60.0, clock=time.monotonic):
        self.limit = int(limit)
        self.window_seconds = float(window_seconds)
        self._clock = clock
        self._lock = Lock()
        self._hits: dict = {}

    def _trim(self, hits: deque, now: float) -> None:
        while hits and now - hits[0] >= self.window_seconds:
            hits.popleft()

    def hit(self, key) -> bool:
        """Registra a tentativa; ``False`` quando a chave já estourou o teto."""

        now = self._clock()
        with self._lock:
            if len(self._hits) > self._SWEEP_ABOVE:
                for stale_key in list(self._hits):
                    self._trim(self._hits[stale_key], now)
                    if not self._hits[stale_key]:
                        del self._hits[stale_key]
            hits = self._hits.setdefault(key, deque())
            self._trim(hits, now)
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True
