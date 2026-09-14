"""Matriz central de visibilidade por nivel de usuario."""

from app.core.operator_sectors import (
    OPERATOR_LEVELS,
    WELDING_OPERATOR_PROFILES,
    operator_sector_for_level,
)
from app.core.quality import can_edit_quality_template, sector_has_quality

USER_LEVELS = (
    "admin",
    "lider",
    "supervisor",
    "manufatura",
    "gestor",
    "diretoria",
    "andon",
    "operador_destaque",
    "operador_dobra",
    "operador_usinagem",
    "operador_serra",
    "operador_corte",
    "operador_pintura",
    # Wave 6F — a antiga Solda (nível genérico ``operador_solda`` + os dez
    # ``operador_solda_estacao_N``) foi substituída pelas contas por estação dos
    # cinco setores da frente de Solda. Os níveis vêm do catálogo para não
    # existir uma segunda lista para o mesmo conceito.
    *(profile.level for profile in WELDING_OPERATOR_PROFILES),
    "operador_montagem",
    "almoxarifado",
)

MANAGEMENT_WEB_LEVELS = (
    "admin",
    "lider",
    "supervisor",
    "manufatura",
    "gestor",
    "diretoria",
)

DEFAULT_USER_LEVEL = "operador_destaque"

NAVIGATION_BY_LEVEL = {
    "admin": (
        "Tela Inicial",
        "Tarefas",
        "Dobra",
        "Usinagem",
        "Serra",
        "Corte",
        "Consulta Operacional",
        "Relatórios",
        "Cadastro",
    ),
    "supervisor": (
        "Tela Inicial",
        "Consulta Operacional",
        "Relatórios",
        "Cadastro",
    ),
    "lider": (
        "Tela Inicial",
        "Consulta Operacional",
        "Relatórios",
    ),
    "manufatura": (
        "Tela Inicial",
        "Consulta Operacional",
        "Relatórios",
    ),
    "gestor": (
        "Tela Inicial",
        "Consulta Operacional",
        "Relatórios",
    ),
    "diretoria": (
        "Tela Inicial",
        "Consulta Operacional",
        "Relatórios",
    ),
    "andon": (),
    "operador_destaque": ("Destaque",),
    "operador_dobra": ("Dobra",),
    "operador_usinagem": ("Usinagem",),
    "operador_serra": ("Serra",),
    "operador_corte": ("Corte",),
    "operador_pintura": ("Pintura",),
    "operador_montagem": ("Montagem",),
    "almoxarifado": (
        "Tela Inicial",
        "Consulta Operacional",
    ),
}
for _operator_level in OPERATOR_LEVELS:
    NAVIGATION_BY_LEVEL.setdefault(
        _operator_level,
        (operator_sector_for_level(_operator_level).name,),
    )

# Indices estaveis do QTabWidget da Consulta Operacional.
ALL_OPERATIONAL_CONSULTATION_TABS = (0, 1, 2, 3, 4, 5, 6, 7, 8)
CONSULTATION_TABS_BY_LEVEL = {
    "admin": ALL_OPERATIONAL_CONSULTATION_TABS,
    "lider": ALL_OPERATIONAL_CONSULTATION_TABS,
    "supervisor": ALL_OPERATIONAL_CONSULTATION_TABS,
    "manufatura": ALL_OPERATIONAL_CONSULTATION_TABS,
    "gestor": ALL_OPERATIONAL_CONSULTATION_TABS,
    "diretoria": ALL_OPERATIONAL_CONSULTATION_TABS,
    "andon": (),
    "operador_destaque": (),
    "operador_dobra": (),
    "operador_usinagem": (),
    "operador_serra": (),
    "operador_corte": (),
    "operador_pintura": (),
    "operador_montagem": (),
    "almoxarifado": ALL_OPERATIONAL_CONSULTATION_TABS,
}
for _operator_level in OPERATOR_LEVELS:
    CONSULTATION_TABS_BY_LEVEL.setdefault(_operator_level, ())

USER_MANAGEMENT_LEVELS = ("admin", "supervisor")


def normalize_user_level(level):
    normalized = str(level or "").strip().lower()
    if normalized == "comum":
        return DEFAULT_USER_LEVEL
    return normalized if normalized in USER_LEVELS else DEFAULT_USER_LEVEL


def navigation_for_level(level):
    return NAVIGATION_BY_LEVEL[normalize_user_level(level)]


def consultation_tabs_for_level(level):
    return CONSULTATION_TABS_BY_LEVEL[normalize_user_level(level)]


def can_manage_users(level):
    return normalize_user_level(level) in USER_MANAGEMENT_LEVELS


def can_access_management_web(level):
    return normalize_user_level(level) in MANAGEMENT_WEB_LEVELS


def can_access_andon_web(level):
    normalized = normalize_user_level(level)
    return normalized == "andon" or normalized in MANAGEMENT_WEB_LEVELS


def operator_sector_for_user_level(level):
    return operator_sector_for_level(normalize_user_level(level))


def is_sector_operator(level):
    return normalize_user_level(level) in OPERATOR_LEVELS


def quality_sector_for_user_level(level):
    """Setor operacional do usuário quando ele possui Qualidade habilitada.

    A Qualidade não cria perfil próprio: ela aparece dentro da experiência
    normal do operador e depende exclusivamente do setor canônico já
    autenticado.
    """

    sector = operator_sector_for_user_level(level)
    if sector is None or not sector_has_quality(sector.name):
        return None
    return sector


def can_access_quality(level):
    """Quem pode abrir a área de Qualidade: operador habilitado ou editor."""

    normalized = normalize_user_level(level)
    return bool(
        quality_sector_for_user_level(normalized)
        or can_edit_quality_template(normalized)
    )


def can_manage_quality_template(level):
    """Alteração de template salvo é exclusiva de Supervisor/Líder."""

    return can_edit_quality_template(normalize_user_level(level))
