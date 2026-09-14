"""Catálogo central das telas operacionais organizadas por setor.

Os recursos listados aqui identificam postos/telas. Dados produtivos como OP,
operação, produto, quantidades e motivos de parada virão do PostgreSQL.
"""

from dataclasses import dataclass

from app.core.resource_mapping import (
    RESOURCE_FRIENDLY_NAMES,
    resource_display_name,
)


@dataclass(frozen=True)
class OperatorSector:
    level: str
    name: str
    route: str
    resources: tuple[str, ...] = ()
    automatic_queue: bool = False


# Estações fixas de Pintura (Wave 5.1). Mesma abordagem das estações de Solda:
# a estação é o posto que o operador abre e fica identificável individualmente
# em apontamento, fila, histórico, Andon e gestão. Por ora existe **um único
# login de Pintura** — não há perfil por estação nem seletor arbitrário: a
# escolha usa a mesma grade de postos já usada por Dobra, Usinagem e Serra.
PAINTING_STATIONS = (
    "Jato",
    "Preparação",
    "Pintura",
    "Secagem",
    "Inspeção Final",
)


OPERATOR_SECTORS = (
    OperatorSector("operador_destaque", "Destaque", "Destaque"),
    OperatorSector("operador_dobra", "Dobra", "Dobra", ("1303", "2204", "Gasparini")),
    OperatorSector(
        "operador_usinagem",
        "Usinagem",
        "Usinagem",
        ("Eurostec", "Fresadora FTV31", "Romi D 1000", "Romi GL 350M", "Torno Mecânico"),
    ),
    OperatorSector("operador_serra", "Serra", "Serra", ("SFG-330", "S4220", "SFHA-10")),
    OperatorSector(
        "operador_corte",
        "Corte",
        "Corte",
        ("Plasma TerraBlade 4", "Laser Ensis 3015"),
        automatic_queue=True,
    ),
    OperatorSector("operador_pintura", "Pintura", "Pintura", PAINTING_STATIONS),
    OperatorSector(
        "operador_solda",
        "Solda",
        "Solda",
        tuple(f"Estação {number}" for number in range(1, 11)),
    ),
    # Montagem possui regra funcional fechada pela Manufatura: recurso com
    # pertencimento canônico é apontável pelo próprio setor, com início,
    # execução e fim, como Pintura e Solda. O cadastro oficial ainda não
    # possui recurso com ``tipo_setor='Montagem'``, portanto o setor entra
    # sem posto configurado. Nenhum código/nome é promovido por semelhança:
    # a lista só deve crescer quando a Manufatura classificar os recursos.
    OperatorSector("operador_montagem", "Montagem", "Montagem"),
)

WELDING_STATIONS = tuple(f"Estação {number}" for number in range(1, 11))
WELDING_OPERATOR_PROFILES = tuple(
    OperatorSector(
        f"operador_solda_estacao_{number}",
        "Solda",
        "Solda",
        (station,),
    )
    for number, station in enumerate(WELDING_STATIONS, start=1)
)

# ``OPERATOR_SECTORS`` continua sendo o catálogo único dos setores/rotas.
# Perfis fixos podem compartilhar a mesma rota sem duplicar a definição do
# setor; autenticação resolve pelo catálogo completo abaixo.
OPERATOR_PROFILES = OPERATOR_SECTORS + WELDING_OPERATOR_PROFILES
OPERATOR_SECTOR_BY_LEVEL = {sector.level: sector for sector in OPERATOR_PROFILES}
OPERATOR_SECTOR_BY_ROUTE = {sector.route: sector for sector in OPERATOR_SECTORS}
OPERATOR_LEVELS = tuple(OPERATOR_SECTOR_BY_LEVEL)


# Traduções confirmadas entre o código do recurso no roteiro/PC Factory e o
# nome público usado nas telas atuais do operador. Pintura e Solda permanecem
# no nível do setor até que suas etapas internas sejam definidas.
ROUTE_RESOURCE_ALIASES = RESOURCE_FRIENDLY_NAMES


def operator_route_resource_label(
    tipo_setor,
    codigo_recurso,
    recurso_nome=None,
    *,
    setor_atual=None,
    recurso_atual=None,
):
    """Converte o código técnico sem substituí-lo pelo posto atualmente aberto.

    ``setor_atual`` e ``recurso_atual`` continuam aceitos por compatibilidade,
    mas não participam da resolução. Isso impede que a tela esconda uma
    divergência entre o roteiro corporativo e a máquina escolhida.
    """

    del tipo_setor, setor_atual, recurso_atual
    return resource_display_name(codigo_recurso, recurso_nome)


def sector_display_label(setor_atual, setor_roteiro=None):
    """Rótulo do setor no formato ``Atual (Original)``.

    Quando a OP foi apontada no setor correto, os dois são o mesmo e o rótulo é
    apenas o nome do setor. Quando divergem — apontamento em setor incorreto
    confirmado pelo crachá do operador — o setor de origem continua visível
    entre parênteses. O evento histórico nunca é reescrito: quem mostra a
    correção é este rótulo, não uma alteração do passado.
    """

    atual = str(setor_atual or "").strip()
    original = str(setor_roteiro or "").strip()
    if not atual:
        return original
    if not original or original.casefold() == atual.casefold():
        return atual
    return f"{atual} ({original})"


def operator_sector_for_level(level):
    return OPERATOR_SECTOR_BY_LEVEL.get(str(level or "").strip().lower())


def is_operator_level(level):
    return operator_sector_for_level(level) is not None
