"""Código de uso único do vínculo do bot do Telegram (migration 55).

O código é curto para ser digitado no celular, mas só vale por poucos minutos,
uma única vez, e cada chat tem freio persistido de tentativas — juntos tornam
adivinhar inviável. O banco guarda apenas o SHA-256 do código normalizado.
"""

from __future__ import annotations

import hashlib
import secrets


# Sem 0/O, 1/I/L: o código é lido na tela e digitado no celular.
TELEGRAM_LINK_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
TELEGRAM_LINK_CODE_LENGTH = 8
TELEGRAM_LINK_CODE_TTL_SECONDS = 600
TELEGRAM_LINK_ATTEMPT_LIMIT = 5
TELEGRAM_LINK_ATTEMPT_WINDOW_SECONDS = 600


def gerar_codigo_vinculo_telegram() -> str:
    return "".join(
        secrets.choice(TELEGRAM_LINK_CODE_ALPHABET) for _ in range(TELEGRAM_LINK_CODE_LENGTH)
    )


def normalizar_codigo_vinculo_telegram(codigo) -> str:
    """Aceita minúsculas, espaços e hífen; recusa o que não pode ser código."""

    texto = "".join(str(codigo or "").split()).replace("-", "").upper()
    if len(texto) != TELEGRAM_LINK_CODE_LENGTH:
        return ""
    if any(char not in TELEGRAM_LINK_CODE_ALPHABET for char in texto):
        return ""
    return texto


def hash_codigo_vinculo_telegram(codigo: str) -> str:
    return hashlib.sha256(codigo.encode("utf-8")).hexdigest()


__all__ = [
    "TELEGRAM_LINK_ATTEMPT_LIMIT",
    "TELEGRAM_LINK_ATTEMPT_WINDOW_SECONDS",
    "TELEGRAM_LINK_CODE_LENGTH",
    "TELEGRAM_LINK_CODE_TTL_SECONDS",
    "gerar_codigo_vinculo_telegram",
    "hash_codigo_vinculo_telegram",
    "normalizar_codigo_vinculo_telegram",
]
