"""Preferências pessoais da dashboard home.

Fonte única do default de ``dashboard_home``: a migration 71 usa o mesmo
JSON como ``DEFAULT`` de ``user_preferences.dashboard_home``. Quem tem valor
gravado manda; quem não tem recebe a tela atual (os 14 blocos originais
visíveis, os 3 novos disponíveis para adicionar).
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
    "chamadas",
    "metas",
    "andon",
)

DASHBOARD_CARD_KEY_SET = frozenset(DASHBOARD_CARD_KEYS)

# Grade de 6 colunas × linhas automáticas. Cada bloco pode ocupar de
# (min_cols, min_rows) até (6, 4). "Máximo 6 colunas x 4 linhas", conforme
# pedido do usuário.
MAX_CARD_COLS = 6
MAX_CARD_ROWS = 4
MAX_CARDS_ON_SCREEN = 14

# (cols, rows, min_cols, min_rows)
CARD_SPECS = {
    "producao_boa": (2, 1, 1, 1),
    "oee": (1, 1, 1, 1),
    "disponibilidade": (1, 1, 1, 1),
    "performance": (1, 1, 1, 1),
    "ftt": (1, 1, 1, 1),
    "simulation": (6, 2, 3, 1),
    "planned_vs_actual": (3, 2, 2, 1),
    "exceptions": (3, 2, 2, 1),
    "time_composition": (2, 2, 2, 1),
    "top_losses": (2, 2, 2, 1),
    "live_events": (2, 2, 2, 1),
    "sectors_table": (6, 3, 4, 2),
    "top_resources": (3, 2, 2, 1),
    "audit_issues": (3, 2, 2, 1),
    "chamadas": (2, 2, 2, 1),
    "metas": (2, 2, 2, 1),
    "andon": (2, 2, 2, 1),
}

DEFAULT_DASHBOARD_HOME = {
    "cards": {key: key not in {"chamadas", "metas", "andon"} for key in DASHBOARD_CARD_KEYS},
    "order": list(DASHBOARD_CARD_KEYS),
    "sizes": {key: {"cols": spec[0], "rows": spec[1]} for key, spec in CARD_SPECS.items()},
}


def dashboard_default() -> dict:
    """Cópia do default, segura para devolver ao cliente."""
    return {
        "cards": dict(DEFAULT_DASHBOARD_HOME["cards"]),
        "order": list(DEFAULT_DASHBOARD_HOME["order"]),
        "sizes": {key: dict(size) for key, size in DEFAULT_DASHBOARD_HOME["sizes"].items()},
    }


def _normalizar_order(raw_order):
    order: list[str] = []
    seen = set()
    if isinstance(raw_order, list):
        for item in raw_order:
            key = str(item or "").strip()
            if key in DASHBOARD_CARD_KEY_SET and key not in seen:
                seen.add(key)
                order.append(key)
    order.extend(key for key in DASHBOARD_CARD_KEYS if key not in seen)
    return order


def _normalizar_sizes(raw_sizes):
    sizes = {}
    source = raw_sizes if isinstance(raw_sizes, dict) else {}
    for key in DASHBOARD_CARD_KEYS:
        spec = CARD_SPECS[key]
        _, _, min_cols, min_rows = spec
        raw = source.get(key)
        cols, rows = spec[0], spec[1]
        if isinstance(raw, dict):
            try:
                raw_cols = int(raw.get("cols", cols))
                raw_rows = int(raw.get("rows", rows))
                if min_cols <= raw_cols <= MAX_CARD_COLS:
                    cols = raw_cols
                if min_rows <= raw_rows <= MAX_CARD_ROWS:
                    rows = raw_rows
            except (TypeError, ValueError):
                pass
        sizes[key] = {"cols": cols, "rows": rows}
    return sizes


def normalizar_dashboard_home(value):
    """Devolve ``{"cards", "order", "sizes"}`` seguros.

    Valores inválidos, chaves desconhecidas ou mais de ``MAX_CARDS_ON_SCREEN``
    blocos ativos ficam no padrão/teto em vez de quebrar a tela.
    """

    if not isinstance(value, dict):
        return dashboard_default()
    cards = value.get("cards")
    if not isinstance(cards, dict):
        return dashboard_default()

    normalized_cards = {
        key: bool(cards.get(key, key not in {"chamadas", "metas", "andon"}))
        for key in DASHBOARD_CARD_KEYS
    }
    order = _normalizar_order(value.get("order"))
    sizes = _normalizar_sizes(value.get("sizes"))

    # Teto: só os primeiros MAX_CARDS_ON_SCREEN da ordem ficam visíveis.
    seen = 0
    for key in order:
        if normalized_cards[key]:
            seen += 1
            if seen > MAX_CARDS_ON_SCREEN:
                normalized_cards[key] = False

    return {"cards": normalized_cards, "order": order, "sizes": sizes}


__all__ = [
    "DASHBOARD_CARD_KEYS",
    "DEFAULT_DASHBOARD_HOME",
    "MAX_CARD_COLS",
    "MAX_CARD_ROWS",
    "MAX_CARDS_ON_SCREEN",
    "dashboard_default",
    "normalizar_dashboard_home",
]
