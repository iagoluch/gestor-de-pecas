"""Interpretação determinística de perguntas privadas do bot de fábrica."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


@dataclass(frozen=True)
class TelegramIntent:
    name: str
    front: str | None = None


def _plain(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"\s+", " ", "".join(
        char for char in normalized if not unicodedata.combining(char)
    ).casefold()).strip()


def front_from_text(text: str) -> str | None:
    return _front(_plain(text))


def _front(text: str) -> str | None:
    if "corte" in text:
        return "corte"
    if "solda" in text:
        return "solda"
    if "pintura" in text:
        return "pintura"
    if any(word in text for word in ("caldeiraria", "dobra", "usinagem", "serra")):
        return "caldeiraria"
    return None


def parse_telegram_intent(text: str) -> TelegramIntent:
    """Seleciona uma consulta existente; não interpreta nem calcula dados."""

    plain = _plain(text)
    front = _front(plain)
    if any(term in plain for term in ("meu status", "o que estou", "onde estou")):
        return TelegramIntent("my_status")
    if any(term in plain for term in ("vincular", "crach", "associar")):
        return TelegramIntent("link_badge")
    if any(term in plain for term in ("ajuda", "o que voce sabe", "o que sabe fazer")):
        return TelegramIntent("help")
    if any(term in plain for term in ("parada", "parado", "paradas", "maquina parada")):
        return TelegramIntent("stoppages", front)
    if any(term in plain for term in ("producao", "produzido", "pecas", "resultado")):
        return TelegramIntent("production", front)
    if any(term in plain for term in ("recurso", "recursos", "maquinas", "equipamentos")):
        return TelegramIntent("resources", front)
    if front and any(term in plain for term in ("como esta", "como ta", "status", "situacao")):
        return TelegramIntent("front_overview", front)
    if any(term in plain for term in ("fabrica", "panorama", "como estamos")):
        return TelegramIntent("factory_status")
    return TelegramIntent("unknown")


__all__ = ["TelegramIntent", "parse_telegram_intent", "front_from_text"]
