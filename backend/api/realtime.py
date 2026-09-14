"""Notificações leves para atualização imediata das telas Web.

O canal apenas informa que a verdade do backend mudou. Os dados continuam
sendo carregados pelos endpoints canônicos, sem transportar regra de negócio
ou manter um estado paralelo no navegador.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from threading import Lock


@dataclass(frozen=True)
class RealtimeSubscriber:
    loop: asyncio.AbstractEventLoop
    queue: asyncio.Queue


class RealtimeBroker:
    """Distribui invalidações SSE entre as sessões conectadas ao processo."""

    def __init__(self):
        self._lock = Lock()
        self._subscribers: set[RealtimeSubscriber] = set()
        self._revision = 0

    @property
    def revision(self):
        with self._lock:
            return self._revision

    def subscribe(self):
        subscriber = RealtimeSubscriber(asyncio.get_running_loop(), asyncio.Queue(maxsize=1))
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber):
        with self._lock:
            self._subscribers.discard(subscriber)

    @staticmethod
    def _offer(queue, payload):
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        queue.put_nowait(payload)

    def publish(self, topic="data"):
        with self._lock:
            self._revision += 1
            revision = self._revision
            subscribers = tuple(self._subscribers)
        payload = {
            "revision": revision,
            "topic": str(topic or "data"),
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        for subscriber in subscribers:
            subscriber.loop.call_soon_threadsafe(self._offer, subscriber.queue, payload)
        return payload

    async def stream(self):
        subscriber = self.subscribe()
        connected = {"revision": self.revision, "topic": "connected"}
        yield self._event("connected", connected, retry=2000)
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(subscriber.queue.get(), timeout=1)
                except asyncio.TimeoutError:
                    payload = {
                        "revision": self.revision,
                        "topic": "live_tick",
                        "published_at": datetime.now(timezone.utc).isoformat(),
                    }
                yield self._event("refresh", payload)
        finally:
            self.unsubscribe(subscriber)

    @staticmethod
    def _event(event, payload, *, retry=None):
        lines = []
        if retry is not None:
            lines.append(f"retry: {int(retry)}")
        lines.extend((f"event: {event}", f"data: {json.dumps(payload, ensure_ascii=False)}", ""))
        return "\n".join(lines) + "\n"
