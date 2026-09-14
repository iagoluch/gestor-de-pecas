"""Adaptador server-side mínimo para envio de documentos pelo Telegram."""

from __future__ import annotations

from pathlib import Path

import httpx

from mes.contracts.messaging import MessagingError


class TelegramProvider:
    def __init__(self, *, bot_token: str, timeout_seconds: float = 30.0, client=None):
        self._bot_token = str(bot_token or "").strip()
        self.timeout_seconds = float(timeout_seconds)
        self._client = client

    def __repr__(self) -> str:
        return "TelegramProvider(configured=%s)" % bool(self._bot_token)

    async def send_document(
        self,
        *,
        destination_ref: str,
        path: Path,
        filename: str,
        caption: str,
    ) -> dict:
        if not self._bot_token:
            raise MessagingError(
                "messaging_not_configured",
                "O envio de relatórios ainda não está configurado.",
                status_code=503,
            )
        document_path = Path(path)
        if not document_path.is_file():
            raise MessagingError(
                "report_file_unavailable",
                "O arquivo do relatório não está disponível.",
                status_code=404,
            )
        url = f"https://api.telegram.org/bot{self._bot_token}/sendDocument"
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            with document_path.open("rb") as document:
                response = await client.post(
                    url,
                    data={"chat_id": str(destination_ref), "caption": str(caption)},
                    files={
                        "document": (
                            str(filename),
                            document,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
                    },
                )
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            if response.status_code >= 500 or response.status_code == 429:
                raise MessagingError(
                    "telegram_temporarily_unavailable",
                    "O Telegram está temporariamente indisponível. O arquivo continua disponível para download.",
                    status_code=502,
                    retryable=True,
                )
            if response.status_code >= 400 or not payload.get("ok"):
                raise MessagingError(
                    "telegram_delivery_rejected",
                    "O Telegram recusou o envio. Verifique o destino configurado.",
                    status_code=502,
                )
            result = payload.get("result") or {}
            return {"message_id": result.get("message_id"), "provider": "telegram"}
        except httpx.TimeoutException as exc:
            raise MessagingError(
                "telegram_timeout",
                "O Telegram não respondeu a tempo. O arquivo continua disponível para download.",
                status_code=504,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise MessagingError(
                "telegram_unavailable",
                "Não foi possível acessar o Telegram. O arquivo continua disponível para download.",
                status_code=502,
                retryable=True,
            ) from exc
        finally:
            if owns_client:
                await client.aclose()


__all__ = ["TelegramProvider"]
