"""Preferências pessoais da dashboard home.

Fonte única do default de ``dashboard_home``: a migration 71 usa o mesmo
JSON como ``DEFAULT`` de ``user_preferences.dashboard_home``. Quem tem valor
gravado manda; quem não tem recebe a tela atual (todos os cards visíveis).
"""

DASHBOARD_CARD_KEYS = (
    "producao_boa",
    "oee",
    "disponibilidade",
    "performance",
    "ftt",
    "simulation",
    "planned_vs_actual",
    "exceptions",
    "time_composition",
    "top_losses",
    "live_events",
    "sectors_table",
    "top_resources",
    "audit_issues",
)

DASHBOARD_CARD_KEY_SET = frozenset(DASHBOARD_CARD_KEYS)

DEFAULT_DASHBOARD_HOME = {
    "cards": {key: True for key in DASHBOARD_CARD_KEYS},
    "order": list(DASHBOARD_CARD_KEYS),
}


def dashboard_default() -> dict:
    """Cópia do default, segura para devolver ao cliente."""
    return {
        "cards": dict(DEFAULT_DASHBOARD_HOME["cards"]),
        "order": list(DEFAULT_DASHBOARD_HOME["order"]),
    }


def normalizar_dashboard_home(value):
    """Devolve um ``{"cards": {...}, "order": [...]}`` seguro.

    Valores inválidos, chaves desconhecidas e listas corrompidas caem no
    padrão: uma conta com JSON inválido vê a tela normal em vez de uma
    dashboard quebrada.
    """

    if not isinstance(value, dict):
        return dashboard_default()
    cards = value.get("cards")
    if not isinstance(cards, dict):
        return dashboard_default()
    normalized_cards = {
        key: bool(cards.get(key, True))
        for key in DASHBOARD_CARD_KEYS
    }

    raw_order = value.get("order")
    normalized_order: list[str] = []
    if isinstance(raw_order, list):
        for item in raw_order:
            key = str(item or "").strip()
            if key in DASHBOARD_CARD_KEY_SET and key not in normalized_order:
                normalized_order.append(key)
    normalized_order.extend(
        key for key in DASHBOARD_CARD_KEYS if key not in normalized_order
    )

    return {"cards": normalized_cards, "order": normalized_order}


__all__ = [
    "DASHBOARD_CARD_KEYS",
    "DEFAULT_DASHBOARD_HOME",
    "dashboard_default",
    "normalizar_dashboard_home",
]
