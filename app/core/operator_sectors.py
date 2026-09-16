"""Catálogo central das telas operacionais organizadas por setor.

Os recursos listados aqui identificam postos/telas. Dados produtivos como OP,
operação, produto, quantidades e motivos de parada virão do PostgreSQL.
"""

from dataclasses import dataclass
import re
import unicodedata

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


def _sector_level_slug(name):
    """Identificador ASCII estável para o nome de um setor."""

    plain = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", plain.casefold())).strip("_")


# Wave 6F — a Solda deixa de ser um setor único com 10 estações genéricas e
# passa a ser cinco setores reais e distintos (decisão do usuário em
# 14/09/2026). Cada um tem ``tipo_setor`` próprio no catálogo, elegibilidade
# própria e contas próprias; "Solda Aço" é o sucessor direto do antigo setor
# "Solda" (mesmas 10 estações, mesma regra aberta), e os outros quatro nascem
# do mesmo desmembramento. "Proj. Ferramentaria" e "Protótipo" não são solda no
# sentido do processo, mas pertencem à mesma frente física e por isso entram no
# mesmo painel do Andon.
#
# A tupla é a fonte única: nome do setor -> postos -> logins. Ela alimenta os
# perfis de operador abaixo e a família consultada por Andon, Solda gerencial e
# regras de setor. Os postos de cada setor têm rótulo próprio de propósito: o
# Andon identifica recurso sem código de catálogo pelo nome do posto, então uma
# "Estação 1" repetida em dois setores voltaria a colapsar dois cards em um
# (mesma causa do bug corrigido em fb2c707).
WELDING_FAMILY_SECTORS = (
    (
        "Solda Aço",
        tuple(f"Estação {number}" for number in range(1, 7)),
        tuple(f"estacao{number}aco" for number in range(1, 7)),
    ),
    (
        "Solda Alumínio",
        tuple(f"Alumínio {number}" for number in range(1, 4)),
        tuple(f"estacao{number}alu" for number in range(1, 4)),
    ),
    ("Solda Robô", ("Robô 1",), ("robo1",)),
    # Proj. Ferramentaria e Protótipo têm uma conta só, mas cobrem mais de um
    # recurso nomeado do cadastro corporativo cada. Os nomes aqui já são os
    # próprios códigos do PC Factory (DISPEX/DISPG/SERVGE/DISPOS, PREMTG,
    # SOLDA4) — não é rótulo de posto físico como nos demais, porque não há
    # quiosque por recurso aqui, é um único login escolhendo entre eles.
    ("Proj. Ferramentaria", ("DISPEX", "DISPG", "SERVGE", "DISPOS"), ("projetos",)),
    ("Protótipo", ("PREMTG", "SOLDA4"), ("prototipo",)),
)

#: Sucessor direto do antigo setor "Solda", mesma regra. Contagem de estações
#: atualizada em 16/09/2026 (cadastro real de PCs por estação): 6 na Solda
#: Aço, 3 na Solda Alumínio — antes eram 10 e 6.
WELDING_STEEL_SECTOR = WELDING_FAMILY_SECTORS[0][0]

#: Nomes dos cinco setores que substituíram o antigo "Solda". Consultado por
#: quem precisa tratar a frente inteira como um bloco (Andon, acompanhamento
#: gerencial da Solda, regras de setor).
WELDING_SECTOR_NAMES = tuple(name for name, _stations, _levels in WELDING_FAMILY_SECTORS)

#: Setores da frente de Solda cujo login enxerga vários recursos ao mesmo
#: tempo e por isso pede seleção na tela, igual Dobra/Usinagem/Serra — ao
#: contrário dos demais, onde o posto é fixo pelo login e a tela vai direto
#: para o apontamento. Decisão do usuário em 14/09/2026: Robô fica fixo (só
#: existe "Robô 1"); Proj. Ferramentaria e Protótipo têm uma conta só cobrindo
#: recursos nomeados distintos e o operador escolhe qual está executando, com
#: o mesmo formulário de apontamento dos demais.
WELDING_OPEN_PICKER_SECTORS = frozenset({"Proj. Ferramentaria", "Protótipo"})


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
    # Montagem possui regra funcional fechada pela Manufatura: recurso com
    # pertencimento canônico é apontável pelo próprio setor, com início,
    # execução e fim, como Pintura e Solda. O cadastro oficial ainda não
    # possui recurso com ``tipo_setor='Montagem'``, portanto o setor entra
    # sem posto configurado. Nenhum código/nome é promovido por semelhança:
    # a lista só deve crescer quando a Manufatura classificar os recursos.
    OperatorSector("operador_montagem", "Montagem", "Montagem"),
) + tuple(
    # Entrada de *catálogo* dos cinco setores da frente de Solda: ela descreve
    # o setor inteiro (todos os postos) para quem precisa enumerar setores e
    # rotas. O ``level`` usa o prefixo ``setor_`` justamente porque **não é uma
    # conta**: a autenticação de Solda acontece só pelos perfis por estação
    # (``WELDING_OPERATOR_PROFILES``), que ficam fora de ``OPERATOR_SECTORS`` e
    # entram apenas em ``OPERATOR_PROFILES``.
    OperatorSector(f"setor_{_sector_level_slug(name)}", name, name, stations)
    for name, stations, _levels in WELDING_FAMILY_SECTORS
)

WELDING_STATIONS = WELDING_FAMILY_SECTORS[0][1]


def _weld_operator_profiles():
    """Gera os perfis por login da frente de Solda.

    Dois formatos: a maioria é uma conta por posto (o recurso é fixo pelo
    login, não escolhido na tela). Proj. Ferramentaria e Protótipo são uma
    conta só cobrindo vários recursos nomeados — aí o login enxerga a lista
    inteira e a tela pede seleção, igual Dobra/Usinagem/Serra.
    """

    profiles = []
    for name, stations, levels in WELDING_FAMILY_SECTORS:
        if name in WELDING_OPEN_PICKER_SECTORS:
            (level,) = levels
            profiles.append(OperatorSector(level, name, name, stations))
        else:
            profiles.extend(
                OperatorSector(level, name, name, (station,))
                for station, level in zip(stations, levels)
            )
    return tuple(profiles)


WELDING_OPERATOR_PROFILES = _weld_operator_profiles()

# ``OPERATOR_SECTORS`` continua sendo o catálogo único dos setores/rotas.
# Perfis fixos podem compartilhar a mesma rota sem duplicar a definição do
# setor; autenticação resolve pelo catálogo completo abaixo.
OPERATOR_PROFILES = tuple(
    sector for sector in OPERATOR_SECTORS if not sector.level.startswith("setor_")
) + WELDING_OPERATOR_PROFILES
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
