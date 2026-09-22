"""Mapeamento exato entre recursos do roteiro e postos do operador.

O código recebido do banco corporativo é a identidade do recurso e nunca deve
ser substituído pelo nome da tela.  Os nomes abaixo são apenas rótulos de
apresentação.  Um código sem cadastro mantém o próprio código visível.
"""


# Nomes públicos já confirmados para as telas existentes. As chaves são
# códigos completos do PC Factory; não existe busca por prefixo neste módulo.
RESOURCE_FRIENDLY_NAMES = {
    "DOBRA1": "Gasparini",
    "DOBRA2": "2204",
    "DOBRA3": "1303",
    "CNC-01": "Romi D 1000",
    "CNC-02": "Eurostec",
    "FRESA1": "Fresadora FTV31",
    "TCNC-1": "Romi GL 350M",
    "TORNOC": "Torno Mecânico",
    "SERRA1": "S4220",
    "SERRA2": "SFHA-10",
    "SERRA3": "SFG-330",
    "PLASMA": "Plasma TerraBlade 4",
    "LASER1": "Laser Ensis 3015",
    "PINT.L": "Pintura",
    # SOLDA4 é do Protótipo desde o desmembramento da Solda (Wave 6F, ver
    # WELDING_FAMILY_SECTORS em app.core.operator_sectors); o rótulo segue o
    # nome do cadastro ("SOLDAGEM"), não mais o setor genérico antigo.
    "SOLDA4": "Soldagem",
}


# Identidades canônicas: um mesmo recurso físico recebido com código
# corporativo diferente. O alias vale para **elegibilidade e leitura**; o
# ``codigo_recurso`` gravado na operação continua sendo o do roteiro, nunca é
# reescrito. Não é lista de semelhança: cada entrada exige decisão registrada.
#
# LASER → LASER1: decisão funcional/Manufatura de 27/08/2026. Vivia apenas no
# adaptador TOTVS, o que fazia ingestão e Tela do Operador divergirem para o
# mesmo recurso; centralizado aqui na Etapa 4C.
OFFICIAL_RESOURCE_ALIASES = {"LASER": "LASER1"}


# Relação explícita entre o nome do posto físico da interface e o código que
# ele representa.  Também aqui não há inferência por prefixo.
STATION_RESOURCE_CODES = {
    ("dobra", "gasparini"): "DOBRA1",
    ("dobra", "2204"): "DOBRA2",
    ("dobra", "1303"): "DOBRA3",
    ("usinagem", "romi d 1000"): "CNC-01",
    ("usinagem", "eurostec"): "CNC-02",
    ("usinagem", "fresadora ftv31"): "FRESA1",
    ("usinagem", "romi gl 350m"): "TCNC-1",
    ("usinagem", "torno mecânico"): "TORNOC",
    ("serra", "s4220"): "SERRA1",
    ("serra", "sfha-10"): "SERRA2",
    # SFG-330 é a terceira serra do posto. O cadastro nomeia SERRA3 como
    # "SERRA FRANHO RF-420" e a foto oficial do posto SFG-330 mostra uma
    # máquina FRANHO; SERRA1/SERRA2 já estão pareadas pelo modelo no nome, e o
    # painel de chão de fábrica lista exatamente três serras em produção
    # (SERRA1/SERRA2/SERRA3). Registrado na Etapa 4C como o único par de Serra
    # apoiado em marca + eliminação, e não em igualdade de modelo.
    ("serra", "sfg-330"): "SERRA3",
    ("corte", "plasma terrablade 4"): "PLASMA",
    ("corte", "laser ensis 3015"): "LASER1",
    # Wave 5.1 — estações de Pintura. Ao contrário de Solda, onde as estações
    # ainda não existem no cadastro corporativo e por isso compartilham
    # SOLDA4, a Pintura **já possui** um recurso registrado por etapa no PC
    # Factory. Cada estação é pareada com o código exato dela, de modo que o
    # posto da tela, o apontamento, a fila, o histórico, o Andon e a gestão
    # falem da mesma máquina real. RETOQ ("RETOQUE PINTURA 1") e TINTA
    # ("PINTURA LIQUIDA") continuam sem posto: a lista só cresce quando a
    # Manufatura declarar a estação correspondente.
    ("pintura", "jato"): "JATO",                 # JATEAMENTO
    ("pintura", "preparação"): "PREP",           # PREPARAÇÃO PINTURA
    ("pintura", "pintura"): "PINT.L",            # PINTURA F IV
    ("pintura", "secagem"): "ESTUFA",            # SECAGEM PINTURA
    ("pintura", "inspeção final"): "INSPE2",     # INSPEÇÃO PINTURA
}


# Setores cujo posto representa o próprio setor. Regra funcional validada com a
# Manufatura: todo recurso com pertencimento canônico ao setor é apontável pelo
# fluxo do setor, mantendo a identidade real do recurso no roteiro. Os demais
# setores continuam exigindo igualdade exata entre posto e recurso.
# Wave 6F — a antiga Solda foi desmembrada em cinco setores reais com
# ``tipo_setor`` próprio. As chaves são casefolded porque toda comparação de
# setor neste módulo é feita assim; a acentuação é a mesma do nome oficial em
# ``app.core.operator_sectors.WELDING_FAMILY_SECTORS``, e é por ela que o
# ``tipo_setor`` gravado no catálogo precisa bater.
#
# A lista fica aqui, escrita, e não é importada de ``operator_sectors``: aquele
# módulo importa este, e inverter a dependência criaria ciclo. O teste
# ``test_stage4c_resource_registry`` trava as duas pontas juntas.
WELDING_SECTOR_KEYS = frozenset(
    {"solda aço", "solda alumínio", "solda robô", "proj. ferramentaria", "protótipo"}
)


SECTOR_OWNED_RESOURCE_SECTORS = {"pintura", "montagem", *WELDING_SECTOR_KEYS}


# Setores onde o bloqueio de "recurso divergente do roteiro" (confirmação por
# crachá antes de apontar) fica desativado. Decisão do usuário em 14/09/2026:
# a Solda cresceu para múltiplas contas de recurso (Aço, Alumínio, Robô,
# Ferramentaria, Protótipo) e o bloqueio atrapalha o fluxo sem agregar controle
# real, porque o posto já é dono do setor (SECTOR_OWNED_RESOURCE_SECTORS). Não
# afeta o registro de auditoria (setor_roteiro/setor_divergente continuam
# gravados normalmente); só remove a exigência de crachá para prosseguir.
RESOURCE_CONFIRMATION_EXEMPT_SECTORS = set(WELDING_SECTOR_KEYS)


# Associação funcional oficial aprovada diretamente pela Manufatura, usada
# somente quando o cadastro ainda não declara o ``tipo_setor`` do recurso. Não
# é alias: o código do recurso permanece exatamente como está no roteiro.
# PINT.L entra na Wave 5.1 pelo mesmo motivo de JATO: com as estações de
# Pintura, o posto aberto pode ser "Jato" (código JATO) e a operação do roteiro
# vir como PINT.L. Sem o pertencimento declarado dos dois lados, o próprio setor
# dono do recurso ficaria impedido de apontá-lo. O código do roteiro continua
# intacto no apontamento.
OFFICIAL_RESOURCE_SECTORS = {"JATO": "Pintura", "PINT.L": "Pintura"}


def normalize_resource_code(value):
    """Normaliza somente caixa/espaços, preservando o código por inteiro."""

    return str(value or "").strip().upper()


def canonical_resource_code(code):
    """Resolve o código do recurso pela identidade canônica registrada.

    Serve para comparar recursos, nunca para reescrever o roteiro: quem grava
    o apontamento continua usando o código recebido. Sem alias registrado, o
    código volta inalterado.
    """

    normalized = normalize_resource_code(code)
    return OFFICIAL_RESOURCE_ALIASES.get(normalized, normalized)


def resource_display_name(code, catalog_name=None):
    """Resolve um rótulo por código exato e retorna o código se não houver mapa."""

    normalized = normalize_resource_code(code)
    if not normalized:
        return ""
    friendly = RESOURCE_FRIENDLY_NAMES.get(normalized)
    if friendly:
        return friendly
    exact_catalog_name = str(catalog_name or "").strip()
    return exact_catalog_name or str(code).strip()


_RESOURCE_DISPLAY_TO_CODE = {
    name.casefold(): code for code, name in RESOURCE_FRIENDLY_NAMES.items()
}


def resolve_resource_identity(value):
    """Resolve um valor de identidade de recurso ao código canônico quando o
    valor recebido for o nome de apresentação de um recurso mapeado.

    Cobre os dois jeitos conhecidos de um recurso chegar com identidade
    divergente da canônica:

    1. **Alias de código bruto** (``OFFICIAL_RESOURCE_ALIASES``, ex.: o TOTVS
       manda "LASER" e o resto do sistema usa "LASER1").
    2. **Nome de tela** em vez do código (ex.: Corte, via ``CUT_MACHINE_MAP``
       em ``mes/services/cut.py``, grava "Laser Ensis 3015" em vez de
       "LASER1").

    Sem esta resolução, o mesmo recurso físico acaba com duas identidades em
    ``eventos_estado_recurso`` e duplica cards/tempo — foi o que aconteceu com
    LASER1/PLASMA no Corte. Qualquer setor com um recurso mapeado em
    ``RESOURCE_FRIENDLY_NAMES``/``OFFICIAL_RESOURCE_ALIASES`` fica protegido
    automaticamente, sem precisar de tratamento por serviço: todo ponto de
    leitura/escrita de ``eventos_estado_recurso`` por ``recurso`` em
    ``app/database/database.py`` passa por aqui antes de consultar/gravar.
    Strings que não batem com nenhum código ou nome mapeado (identidades sem
    cadastro, como as estações de Solda) voltam inalteradas.
    """

    text = str(value or "").strip()
    if not text:
        return text
    normalized = normalize_resource_code(text)
    if normalized in OFFICIAL_RESOURCE_ALIASES or normalized in RESOURCE_FRIENDLY_NAMES:
        return canonical_resource_code(normalized)
    code = _RESOURCE_DISPLAY_TO_CODE.get(text.casefold())
    return canonical_resource_code(code) if code else text


def station_resource_code(sector, station):
    """Retorna o código exato representado por uma tela/posto conhecido.

    Solda não tem, propositalmente, uma entrada aqui: as 10 estações físicas
    não têm código de catálogo corporativo próprio (o TOTVS ainda não detalha
    o roteiro por estação). Antes esta função colapsava toda estação de Solda
    no código compartilhado ``SOLDA4``, o que fazia o Andon (``mes/services/
    andon.py``, que usa este código para identificar o recurso) tratar as 10
    estações como um único recurso — produzindo em paralelo em 3 estações
    aparecia como 1 card só, com os outros estados sobrescritos. Devolver ""
    aqui faz o Andon cair no caminho de recurso não cadastrado, que já usa o
    nome exato do posto (``Estação 1``, ``Estação 2``, ...) como identidade —
    cada estação vira um card distinto. Não afeta elegibilidade de apontamento:
    ``station_matches_route`` cai em ``sector_serves_resource`` para Solda de
    qualquer forma quando este retorno não bate com o recurso do roteiro.
    """

    sector_key = str(sector or "").strip().casefold()
    station_key = str(station or "").strip().casefold()
    return STATION_RESOURCE_CODES.get((sector_key, station_key), "")


def resource_canonical_sector(route_code, catalog_sector=None):
    """Resolve o setor do recurso por cadastro exato, nunca por nome.

    ``catalog_sector`` é o ``tipo_setor`` gravado em
    ``catalogo_recursos_pcfactory`` para o código exato do roteiro. A associação
    oficial só é consultada quando o cadastro está vazio.
    """

    declared = str(catalog_sector or "").strip()
    if declared:
        return declared
    code = normalize_resource_code(route_code)
    return OFFICIAL_RESOURCE_SECTORS.get(code, "") if code else ""


def sector_serves_resource(sector, route_code, resource_sector=None):
    """Indica se o setor é dono canônico do recurso do roteiro.

    Só vale para os setores cujo posto representa o próprio setor. O
    pertencimento vem exclusivamente do cadastro/associação oficial: nome,
    prefixo ou semelhança não criam elegibilidade.
    """

    sector_key = str(sector or "").strip().casefold()
    if sector_key not in SECTOR_OWNED_RESOURCE_SECTORS:
        return False
    if not normalize_resource_code(route_code):
        return False
    canonical = resource_canonical_sector(route_code, resource_sector)
    return bool(canonical) and canonical.casefold() == sector_key


def station_matches_route(sector, station, route_code, *, resource_sector=None):
    """Decide se o posto aberto pode enxergar/apontar a operação do roteiro.

    Postos que representam uma máquina específica continuam exigindo igualdade
    exata com o recurso do roteiro. Postos que representam o próprio setor
    (Pintura, Solda e Montagem) também aceitam qualquer recurso com
    pertencimento canônico ao setor, sem alterar ``codigo_recurso``.
    """

    # A comparação usa a identidade canônica dos dois lados: o roteiro pode
    # trazer um código corporativo com alias oficial registrado. O código
    # original permanece intacto no apontamento.
    expected = canonical_resource_code(route_code)
    current = canonical_resource_code(station_resource_code(sector, station))
    if current:
        if current == expected:
            return True
    # Permite um posto cadastrado diretamente com o próprio código técnico.
    elif canonical_resource_code(station) == expected:
        return True
    return sector_serves_resource(sector, route_code, resource_sector)
