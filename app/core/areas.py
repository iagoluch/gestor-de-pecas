"""Áreas da fábrica na tela de gestão e quem enxerga cada uma (fonte única).

Para incluir uma área ou mudar quem a vê, edite só as duas tabelas abaixo; o
menu e a página de área do frontend são montados a partir do que a sessão traz.
"""

from app.core.permissions import can_access_management_web

#: id da área -> (rótulo no menu, setores do catálogo que a compõem).
AREAS = {
    "dobra-corte": ("Dobra e Corte", ("Dobra", "Corte")),
    "usinagem": ("Usinagem", ("Usinagem",)),
    "serra": ("Serra", ("Serra",)),
    "solda": ("Solda", ("Solda Aço", "Solda Alumínio", "Solda Robô")),
    "pintura": ("Pintura", ("Pintura",)),
    "prototipo": ("Protótipo", ("Protótipo",)),
    "projetos-ferramentaria": ("Projetos/Ferramentaria", ("Proj. Ferramentaria",)),
}

#: Nível gravado na conta (migration 61) -> áreas que ele enxerga. O
#: Almoxarifado ainda não tem setor no catálogo, então não gera área própria.
AREAS_POR_NIVEL = {
    "supervisor_caldeiraria": ("dobra-corte", "usinagem", "serra"),
    "supervisor_almoxarifado_solda_pintura": ("solda", "pintura"),
    "supervisor_prototipo": ("prototipo",),
    "lider_dobra_corte": ("dobra-corte",),
    "lider_usinagem": ("usinagem",),
    "lider_serra": ("serra",),
    "lider_pintura_almoxarifado": ("pintura",),
    "lider_pintura": ("pintura",),
    "lider_almoxarifado": (),
    "lider_projetos_ferramentaria": ("projetos-ferramentaria",),
    "lider_solda": ("solda",),
}

#: Únicos níveis que enxergam todas as áreas. As demais contas (Diretoria,
#: Qualidade, Manufatura, Gestor…) só veem a área que o nível delas mapeia.
NIVEIS_COM_TODAS_AS_AREAS = ("admin", "gerente_industrial")


def areas_for_user(nivel_atribuido, nivel_efetivo):
    """Áreas visíveis para a conta, na ordem de ``AREAS``.

    Cada área é exclusiva de quem trabalha nela: só vê o que o nível mapeia.
    Exceção: admin e gerente industrial veem todas.
    """

    if not can_access_management_web(nivel_efetivo):
        return []
    atribuido = nivel_atribuido or nivel_efetivo
    if atribuido in AREAS_POR_NIVEL:
        ids = set(AREAS_POR_NIVEL[atribuido])
    elif atribuido in NIVEIS_COM_TODAS_AS_AREAS:
        ids = set(AREAS)
    else:
        ids = set()
    return [{"id": id_, "label": label, "setores": list(setores)}
            for id_, (label, setores) in AREAS.items() if id_ in ids]


def queue_areas_for_user(nivel_atribuido, nivel_efetivo=None):
    """Ids das áreas cuja fila manual a conta pode ordenar.

    Líder e supervisor, cada um nas áreas do próprio nível, e o admin em todas
    (decisão de 16/10/2026). Gestor, gerente, Qualidade e Diretoria só enxergam.
    """

    atribuido = nivel_atribuido or nivel_efetivo
    if atribuido == "admin":
        return list(AREAS)
    return list(AREAS_POR_NIVEL.get(atribuido, ()))


def recursos_da_area(area_id):
    """Recursos apontáveis da área, para a fila manual (``[]`` se a área não existe).

    Vêm dos postos de ``OPERATOR_SECTORS``; a fila automática (Corte) e o
    Destaque ficam de fora. ``resource`` é a identidade canônica, ``station`` o
    nome do posto que o operador abre (o que ``listar_cartoes`` recebe).
    """

    from app.core.operator_sectors import OPERATOR_SECTORS
    from app.core.resource_mapping import resolve_resource_identity, resource_display_name

    if area_id not in AREAS:
        return []
    setores = {setor.casefold() for setor in AREAS[area_id][1]}
    return [
        {
            "resource": resolve_resource_identity(station),
            "nome": resource_display_name(station),
            "setor": sector.name,
            "station": station,
        }
        for sector in OPERATOR_SECTORS
        if sector.name.casefold() in setores and not sector.automatic_queue
        for station in sector.resources
    ]
