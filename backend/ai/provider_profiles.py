"""Provedores de IA OpenAI-compatíveis permitidos e o que cada um aceita.

Sem dependência de SDK: a configuração valida o endereço no boot e o adaptador
usa o mesmo perfil para montar só os campos que o provedor aceita.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class AIProviderProfile:
    name: str
    host: str
    default_base_url: str
    default_model: str
    # Groq usa max_completion_tokens; NIM/OpenRouter aceitam o clássico max_tokens.
    max_tokens_field: str = "max_tokens"
    # reasoning_effort/reasoning_format são extensões da Groq; outros provedores
    # podem recusar campos desconhecidos.
    groq_reasoning: bool = False
    send_parallel_tool_calls: bool = False
    extra_body: dict[str, Any] = field(default_factory=dict)


NVIDIA = AIProviderProfile(
    name="nvidia",
    host="integrate.api.nvidia.com",
    default_base_url="https://integrate.api.nvidia.com/v1",
    # Catálogo público /v1/models (07/10/2026): gpt-oss-120b e llama-3.3 não
    # estão hospedados; o card do Nemotron 3 Super indica tool use/agentic.
    default_model="nvidia/nemotron-3-super-120b-a12b",
    # Raciocínio desligado pelo chat template (documentado no card do modelo):
    # com ligado, o rastro de raciocínio consome o max_tokens e cada rodada de
    # tool fica bem mais lenta.
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
)
GROQ = AIProviderProfile(
    name="groq",
    host="api.groq.com",
    default_base_url="https://api.groq.com/openai/v1",
    default_model="openai/gpt-oss-120b",
    max_tokens_field="max_completion_tokens",
    groq_reasoning=True,
    send_parallel_tool_calls=True,
)
OPENROUTER = AIProviderProfile(
    name="openrouter",
    host="openrouter.ai",
    default_base_url="https://openrouter.ai/api/v1",
    default_model="openai/gpt-oss-120b",
    send_parallel_tool_calls=True,
)

PROFILES_BY_HOST = {profile.host: profile for profile in (NVIDIA, GROQ, OPENROUTER)}


def resolve_provider_profile(base_url: str) -> AIProviderProfile:
    """Exige https e host da allowlist; impede mandar a chave para outro destino."""

    allowed = ", ".join(sorted(PROFILES_BY_HOST))
    message = f"GESTOR_AI_BASE_URL deve usar https e um destes hosts: {allowed}."
    try:
        parts = urlsplit(str(base_url or "").strip())
        port = parts.port
    except ValueError:
        raise ValueError(message) from None
    host = (parts.hostname or "").casefold()
    if (
        parts.scheme.casefold() != "https"
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or parts.query
        or parts.fragment
        or host not in PROFILES_BY_HOST
    ):
        raise ValueError(message)
    return PROFILES_BY_HOST[host]
