"""Sessões HMAC curtas, transportadas somente em cookie HttpOnly."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import base64
import hashlib
import hmac
import json
import secrets
import time

from backend.api.errors import AppError


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


@dataclass(frozen=True)
class SessionClaims:
    user_id: int
    username: str
    role: str
    issued_at: int
    expires_at: int
    csrf: str
    session_id: str


class SessionSigner:
    def __init__(self, secret: str, *, ttl_seconds: int):
        self._secret = secret.encode("utf-8")
        self.ttl_seconds = ttl_seconds

    def issue(self, *, user_id: int, username: str, role: str, now: int | None = None):
        issued_at = int(time.time() if now is None else now)
        claims = SessionClaims(
            user_id=int(user_id),
            username=str(username),
            role=str(role),
            issued_at=issued_at,
            expires_at=issued_at + self.ttl_seconds,
            csrf=secrets.token_urlsafe(24),
            session_id=secrets.token_urlsafe(18),
        )
        payload = json.dumps(
            asdict(claims), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return f"{_b64_encode(payload)}.{_b64_encode(signature)}", claims

    def decode(self, token: str, *, now: int | None = None) -> SessionClaims:
        try:
            payload_text, signature_text = str(token or "").split(".", 1)
            payload = _b64_decode(payload_text)
            received = _b64_decode(signature_text)
            expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(received, expected):
                raise ValueError("invalid signature")
            raw = json.loads(payload.decode("utf-8"))
            claims = SessionClaims(**raw)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError, UnicodeError) as exc:
            raise AppError(
                "invalid_session",
                "A sessão é inválida. Entre novamente.",
                status_code=401,
            ) from exc
        current = int(time.time() if now is None else now)
        if claims.expires_at <= current:
            raise AppError(
                "expired_session",
                "A sessão expirou. Entre novamente.",
                status_code=401,
            )
        return claims

