"""Contratos neutros para entrega opcional de artefatos industriais."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class MessagingError(RuntimeError):
    def __init__(
        self,
        code: str,
        user_message: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
    ):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.status_code = status_code
        self.retryable = retryable


class DocumentMessagingProvider(Protocol):
    async def send_document(
        self,
        *,
        destination_ref: str,
        path: Path,
        filename: str,
        caption: str,
    ) -> dict[str, Any]: ...


__all__ = ["DocumentMessagingProvider", "MessagingError"]
