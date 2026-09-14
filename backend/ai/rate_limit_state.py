"""Estado HTTP compartilhado para refletir o cooldown informado pelo provider."""

from __future__ import annotations

from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import math
import re
from threading import Lock
from typing import Any, Callable


_DURATION_PATTERN = re.compile(r"(?P<value>[0-9]+(?:\.[0-9]+)?)(?P<unit>ms|s|m|h)", re.IGNORECASE)


class AIRateLimitState:
    """Manté o bloqueio da aplicação sem expor detalhes do provedor à UI."""

    def __init__(
        self,
        *,
        fallback_seconds: int = 30,
        now: Callable[[], datetime] | None = None,
    ):
        self._fallback_seconds = max(1, min(300, int(fallback_seconds)))
        self._now = now or (lambda: datetime.now().astimezone())
        self._blocked_until: datetime | None = None
        self._lock = Lock()

    @staticmethod
    def _duration_seconds(value: Any, now: datetime) -> float | None:
        text = " ".join(str(value or "").split())
        if not text:
            return None
        try:
            return max(0.0, float(text))
        except ValueError:
            pass
        matches = list(_DURATION_PATTERN.finditer(text))
        if matches and "".join(match.group(0) for match in matches).casefold() == text.casefold():
            factors = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
            return sum(float(match.group("value")) * factors[match.group("unit").casefold()] for match in matches)
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=now.tzinfo)
        return max(0.0, (parsed.astimezone(now.tzinfo) - now).total_seconds())

    def activate(self, details: dict[str, Any] | None = None) -> dict[str, Any]:
        safe_details = details if isinstance(details, dict) else {}
        now = self._now()
        seconds = self._duration_seconds(safe_details.get("retry_after"), now)
        if seconds is None or seconds <= 0:
            seconds = self._duration_seconds(safe_details.get("reset_tokens"), now)
        if seconds is None or seconds <= 0:
            seconds = float(self._fallback_seconds)
        candidate = now + timedelta(seconds=max(1.0, min(3600.0, seconds)))
        with self._lock:
            if self._blocked_until is None or candidate > self._blocked_until:
                self._blocked_until = candidate
            return self._snapshot_locked(now)

    def snapshot(self) -> dict[str, Any]:
        now = self._now()
        with self._lock:
            return self._snapshot_locked(now)

    def _snapshot_locked(self, now: datetime) -> dict[str, Any]:
        if self._blocked_until is None or self._blocked_until <= now:
            self._blocked_until = None
            return {
                "active": False,
                "retry_after_seconds": 0,
                "blocked_until": None,
            }
        remaining = max(1, math.ceil((self._blocked_until - now).total_seconds()))
        return {
            "active": True,
            "retry_after_seconds": remaining,
            "blocked_until": self._blocked_until.isoformat(),
        }
