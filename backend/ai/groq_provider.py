"""Adaptador assíncrono da Groq, isolado do FastAPI e do domínio industrial."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import logging
import math
import re
import time
from typing import Any, Callable

from mes.ai.context_budget import estimate_request_tokens
from mes.contracts.ai import AIProviderError, AIProviderResponse, AIToolCall

try:
    from groq import AsyncGroq
except ImportError:  # O restante do MES deve iniciar mesmo sem o extra instalado.
    AsyncGroq = None


LOGGER = logging.getLogger(__name__)
STRICT_TOOL_RETRY_INSTRUCTION = (
    "Gere no máximo uma tool call e use somente o nome e os argumentos declarados. "
    "Os arguments devem ser um objeto JSON válido, sem campos adicionais."
)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,79}$")
_TOOL_NAME_PATTERNS = (
    re.compile(r"<(?:tool|function)=([A-Za-z_][A-Za-z0-9_-]{0,79})"),
    re.compile(
        r"(?:tool_name|function_name|name)\s*['\"]?\s*[:=]\s*['\"]([A-Za-z_][A-Za-z0-9_-]{0,79})"
    ),
)


def _safe_scalar(value: Any, *, limit: int, fallback: str) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return fallback
    text = " ".join(str(value).split())
    if not text or any(marker in text for marker in ("{", "}", "[", "]", "<tool", "<function")):
        return fallback
    return text[:limit]


class GroqProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        reasoning_effort: str = "medium",
        temperature: float = 0.2,
        max_completion_tokens: int = 512,
        request_token_budget: int = 6_000,
        timeout_seconds: float = 60.0,
        client=None,
        monotonic_func: Callable[[], float] | None = None,
    ):
        self.model = str(model)
        self.reasoning_effort = str(reasoning_effort)
        self.temperature = float(temperature)
        self.max_completion_tokens = int(max_completion_tokens)
        self.request_token_budget = int(request_token_budget)
        self.timeout_seconds = float(timeout_seconds)
        self._monotonic = monotonic_func or time.monotonic
        self._rate_limited_until = 0.0
        self._rate_limit_details: dict[str, Any] = {}
        self._api_key_present = bool(str(api_key or "").strip())
        if client is not None:
            self._client = client
        elif self._api_key_present and AsyncGroq is not None:
            self._client = AsyncGroq(
                api_key=str(api_key).strip(),
                timeout=self.timeout_seconds,
                # O provider controla os únicos retries permitidos. Em especial,
                # o SDK não pode repetir 429 automaticamente.
                max_retries=0,
            )
        else:
            self._client = None

    @property
    def configured(self) -> bool:
        return self._client is not None and self._api_key_present

    def _request(
        self,
        messages,
        *,
        tools,
        tool_choice,
        stream: bool,
        temperature: float | None = None,
    ):
        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else float(temperature),
            "reasoning_effort": self.reasoning_effort,
            "reasoning_format": "hidden",
            "max_completion_tokens": self.max_completion_tokens,
            "stream": stream,
        }
        if tools:
            request["tools"] = tools
            request["tool_choice"] = tool_choice
            request["parallel_tool_calls"] = False
        return request

    def _ensure_configured(self):
        if AsyncGroq is None and self._client is None:
            raise AIProviderError(
                "ai_sdk_unavailable",
                "O componente da Groq não está instalado no servidor.",
            )
        if not self.configured:
            raise AIProviderError(
                "ai_not_configured",
                "IA não configurada. Defina a chave da Groq no servidor.",
            )

    def _ensure_request_budget(self, messages, tools):
        estimated = estimate_request_tokens(
            list(messages),
            list(tools or []),
            self.max_completion_tokens,
        )
        if estimated > self.request_token_budget:
            LOGGER.warning(
                "Groq request_budget_blocked estimated_tokens=%s budget=%s",
                estimated,
                self.request_token_budget,
            )
            raise AIProviderError(
                "request_token_limit",
                "A consulta reuniu dados demais para o limite atual da IA.",
                retryable=False,
                technical_details={
                    "estimated_tokens": estimated,
                    "request_token_budget": self.request_token_budget,
                },
            )

    @staticmethod
    def _error_object(exc: Exception) -> Mapping[str, Any]:
        body = getattr(exc, "body", None)
        if isinstance(body, Mapping):
            error = body.get("error")
            if isinstance(error, Mapping):
                return error
            return body
        return {}

    @classmethod
    def _is_tool_use_failed(cls, exc: Exception) -> bool:
        if getattr(exc, "status_code", None) != 400:
            return False
        error = cls._error_object(exc)
        markers = {
            str(error.get("code") or "").casefold(),
            str(error.get("type") or "").casefold(),
        }
        return "tool_use_failed" in markers or "failed_generation" in error

    @staticmethod
    def _offered_tool_names(tools: list[dict[str, Any]]) -> set[str]:
        names = set()
        for schema in tools:
            function = schema.get("function") if isinstance(schema, Mapping) else None
            name = function.get("name") if isinstance(function, Mapping) else None
            if isinstance(name, str) and _SAFE_IDENTIFIER.fullmatch(name):
                names.add(name)
        return names

    @classmethod
    def _failed_generation_details(
        cls,
        exc: Exception,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        error = cls._error_object(exc)
        failed = error.get("failed_generation")
        offered_names = cls._offered_tool_names(tools)
        error_type = _safe_scalar(
            error.get("code") or error.get("type") or type(exc).__name__,
            limit=80,
            fallback="tool_use_failed",
        )
        reason = "tool_call_generation_invalid"
        tool_name = None

        parsed_failed: Mapping[str, Any] | None = failed if isinstance(failed, Mapping) else None
        if parsed_failed is None and isinstance(failed, str):
            try:
                candidate = json.loads(failed)
            except (json.JSONDecodeError, TypeError):
                candidate = None
            if isinstance(candidate, Mapping):
                parsed_failed = candidate

        if parsed_failed is not None:
            reason = _safe_scalar(
                parsed_failed.get("reason"),
                limit=240,
                fallback=reason,
            )
            raw_name = parsed_failed.get("tool_name") or parsed_failed.get("name")
            function = parsed_failed.get("function")
            if not raw_name and isinstance(function, Mapping):
                raw_name = function.get("name")
            if isinstance(raw_name, str) and raw_name in offered_names:
                tool_name = raw_name
        elif isinstance(failed, str):
            for pattern in _TOOL_NAME_PATTERNS:
                match = pattern.search(failed)
                if match and match.group(1) in offered_names:
                    tool_name = match.group(1)
                    break

        details = {"error_type": error_type, "reason": reason}
        if tool_name:
            details["tool"] = tool_name
        return details

    @staticmethod
    def _header(exc: Exception, name: str) -> str | None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers is None:
            return None
        try:
            value = headers.get(name)
        except AttributeError:
            return None
        text = " ".join(str(value or "").split())
        return text[:120] or None

    @classmethod
    def _retry_after_seconds(cls, exc: Exception) -> float | None:
        value = cls._header(exc, "retry-after")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())

    @classmethod
    def _rate_limit_error_details(cls, exc: Exception) -> dict[str, Any]:
        details: dict[str, Any] = {}
        for header, key in (
            ("x-ratelimit-remaining-tokens", "remaining_tokens"),
            ("x-ratelimit-reset-tokens", "reset_tokens"),
            ("retry-after", "retry_after"),
        ):
            value = cls._header(exc, header)
            if value is not None:
                details[key] = value
        return details

    @classmethod
    def _request_limit_error_details(cls, exc: Exception) -> dict[str, Any]:
        error = cls._error_object(exc)
        message = str(error.get("message") or "")
        details: dict[str, Any] = {
            "error_type": _safe_scalar(
                error.get("code") or error.get("type") or type(exc).__name__,
                limit=80,
                fallback="request_too_large",
            )
        }
        limit_match = re.search(r"\bLimit:\s*([0-9]+)", message, re.IGNORECASE)
        requested_match = re.search(r"\bRequested:\s*([0-9]+)", message, re.IGNORECASE)
        if limit_match:
            details["limit_tokens"] = int(limit_match.group(1))
        if requested_match:
            details["requested_tokens"] = int(requested_match.group(1))
        return details

    @staticmethod
    def _rate_limit_error(details: dict[str, Any]) -> AIProviderError:
        return AIProviderError(
            "groq_rate_limited",
            "Limite temporário da IA atingido. Aguarde alguns segundos e tente novamente.",
            retryable=True,
            technical_details=details,
        )

    def _ensure_rate_limit_window(self):
        remaining = self._rate_limited_until - self._monotonic()
        if remaining <= 0:
            return
        details = dict(self._rate_limit_details)
        details["retry_after"] = str(max(1, math.ceil(remaining)))
        raise self._rate_limit_error(details)

    def _map_error(
        self,
        exc: Exception,
        *,
        request_id: str | None,
        attempt: int,
    ) -> AIProviderError:
        name = type(exc).__name__
        status = getattr(exc, "status_code", None)
        if isinstance(exc, TimeoutError) or name in {"APITimeoutError", "TimeoutException"}:
            return AIProviderError(
                "groq_timeout",
                "A Groq excedeu o tempo máximo da consulta. Tente novamente.",
                retryable=True,
            )
        if status in {401, 403} or name in {"AuthenticationError", "PermissionDeniedError"}:
            return AIProviderError(
                "groq_authentication_failed",
                "A configuração da Groq foi recusada. Verifique a chave no servidor.",
            )
        if status == 413:
            details = self._request_limit_error_details(exc)
            LOGGER.warning(
                "Groq request_token_limit request_id=%s error_type=%s attempt=%s limit_tokens=%s requested_tokens=%s",
                request_id,
                details.get("error_type"),
                attempt,
                details.get("limit_tokens"),
                details.get("requested_tokens"),
            )
            return AIProviderError(
                "request_token_limit",
                "A consulta reuniu dados demais para o limite atual da IA.",
                retryable=False,
                technical_details=details,
            )
        if status == 429 or name == "RateLimitError":
            details = self._rate_limit_error_details(exc)
            retry_after = self._retry_after_seconds(exc)
            if retry_after is not None and retry_after > 0:
                self._rate_limited_until = self._monotonic() + retry_after
                self._rate_limit_details = dict(details)
            LOGGER.warning(
                "Groq rate_limit request_id=%s error_type=%s attempt=%s remaining_tokens=%s reset_tokens=%s retry_after=%s",
                request_id,
                name,
                attempt,
                details.get("remaining_tokens"),
                details.get("reset_tokens"),
                details.get("retry_after"),
            )
            return self._rate_limit_error(details)
        if status and int(status) >= 500:
            return AIProviderError(
                "groq_unavailable",
                "A Groq está temporariamente indisponível. Tente novamente.",
                retryable=True,
            )
        if name in {"APIConnectionError", "ConnectError", "ConnectionError"}:
            return AIProviderError(
                "groq_connection_failed",
                "Não foi possível conectar à Groq. Verifique a rede e tente novamente.",
                retryable=True,
            )
        return AIProviderError(
            "groq_invalid_response",
            "A Groq não conseguiu produzir uma resposta válida.",
            retryable=True,
        )

    @staticmethod
    def _assistant_message(message, tool_calls: tuple[AIToolCall, ...]) -> dict[str, Any]:
        if hasattr(message, "model_dump"):
            dumped = message.model_dump(exclude_none=True, mode="json")
            if isinstance(dumped, dict):
                return dumped
        result: dict[str, Any] = {
            "role": "assistant",
            "content": str(message.content) if message.content else None,
        }
        if tool_calls:
            result["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }
                for call in tool_calls
            ]
        return result

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        tool_choice: str = "auto",
        request_id: str | None = None,
    ) -> AIProviderResponse:
        self._ensure_configured()
        self._ensure_rate_limit_window()
        self._ensure_request_budget(messages, tools)
        request_messages = list(messages)
        for attempt in (1, 2):
            try:
                self._ensure_request_budget(request_messages, tools)
                temperature = self.temperature if attempt == 1 else min(self.temperature, 0.1)
                async with asyncio.timeout(self.timeout_seconds):
                    response = await self._client.chat.completions.create(
                        **self._request(
                            request_messages,
                            tools=tools,
                            tool_choice=tool_choice,
                            stream=False,
                            temperature=temperature,
                        )
                    )
                if not response.choices:
                    raise ValueError("Resposta sem escolhas.")
                choice = response.choices[0]
                message = choice.message
                content = str(message.content) if message.content else None
                tool_calls = tuple(
                    AIToolCall(
                        id=str(call.id),
                        name=str(call.function.name),
                        arguments=str(call.function.arguments or "{}"),
                    )
                    for call in (message.tool_calls or ())
                )
                if len(tool_calls) > 1:
                    LOGGER.warning(
                        "Groq parallel_tool_calls_rejected request_id=%s count=%s attempt=%s",
                        request_id,
                        len(tool_calls),
                        attempt,
                    )
                    raise AIProviderError(
                        "groq_parallel_tool_calls_rejected",
                        "Não foi possível consultar os dados necessários neste momento.",
                    )
                usage = response.usage.model_dump(exclude_none=True) if response.usage else {}
                return AIProviderResponse(
                    content=content,
                    tool_calls=tool_calls,
                    assistant_message=self._assistant_message(message, tool_calls),
                    usage=usage,
                    finish_reason=str(choice.finish_reason) if choice.finish_reason else None,
                )
            except asyncio.CancelledError:
                raise
            except AIProviderError:
                raise
            except Exception as exc:
                if self._is_tool_use_failed(exc):
                    details = self._failed_generation_details(exc, tools)
                    LOGGER.warning(
                        "Groq tool_use_failed request_id=%s error_type=%s tool=%s reason=%s attempt=%s",
                        request_id,
                        details.get("error_type"),
                        details.get("tool"),
                        details.get("reason"),
                        attempt,
                    )
                    if attempt == 1 and tools:
                        request_messages = [
                            *messages,
                            {"role": "system", "content": STRICT_TOOL_RETRY_INSTRUCTION},
                        ]
                        continue
                    raise AIProviderError(
                        "groq_tool_use_failed",
                        "Não foi possível consultar os dados necessários neste momento.",
                        technical_details={**details, "attempt": attempt},
                    ) from exc
                raise self._map_error(
                    exc,
                    request_id=request_id,
                    attempt=attempt,
                ) from exc
        raise AssertionError("Fluxo de retry da Groq terminou sem resultado.")

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "none",
        request_id: str | None = None,
    ):
        self._ensure_configured()
        self._ensure_rate_limit_window()
        self._ensure_request_budget(messages, tools or [])
        try:
            async with asyncio.timeout(self.timeout_seconds):
                stream = await self._client.chat.completions.create(
                    **self._request(
                        messages,
                        tools=tools or [],
                        tool_choice=tool_choice,
                        stream=True,
                    )
                )
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yield str(delta.content)
        except asyncio.CancelledError:
            raise
        except AIProviderError:
            raise
        except Exception as exc:
            raise self._map_error(exc, request_id=request_id, attempt=1) from exc
