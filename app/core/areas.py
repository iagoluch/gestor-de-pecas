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
    "lider_solda": ("solda",),
}

#: Nível personalizado que enxerga todas as áreas.
NIVEIS_COM_TODAS_AS_AREAS = ("gerente_industrial",)


def areas_for_user(nivel_atribuido, nivel_efetivo):
    """Áreas visíveis para a conta, na ordem de ``AREAS``.

    Nível embutido (admin, gestor, diretoria…) vê todas. Nível personalizado só
    vê o que está mapeado: PCP, Controladoria etc. não têm área de fábrica.
    """

    if not can_access_management_web(nivel_efetivo):
        return []
    atribuido = nivel_atribuido or nivel_efetivo
    if atribuido in AREAS_POR_NIVEL:
        ids = set(AREAS_POR_NIVEL[atribuido])
    elif atribuido == nivel_efetivo or atribuido in NIVEIS_COM_TODAS_AS_AREAS:
        ids = set(AREAS)
    else:
        ids = set()
    return [{"id": id_, "label": label, "setores": list(setores)}
            for id_, (label, setores) in AREAS.items() if id_ in ids]
