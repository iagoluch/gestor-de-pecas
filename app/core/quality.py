"""Regras canônicas da Qualidade, centralizadas em um único lugar.

A Qualidade **não** é um perfil de usuário. Ela é uma capacidade que alguns
setores possuem dentro da experiência normal do operador. Este módulo é a
autoridade única sobre:

* quais setores enxergam a aba Qualidade;
* qual assinatura industrial identifica a operação de inspeção no roteiro;
* qual faixa de execução a inspeção usa em ``apontamentos_operacionais``;
* quem pode alterar o template de cotas de um produto.

Habilitar um setor novo no futuro deve ser uma alteração *aqui*, e não um
``if setor == ...`` espalhado por backend e frontend.
"""

# Setores da Caldeiraria que possuem inspeção dimensional habilitada.
#
# Caldeiraria é o centro de trabalho (``WorkCenterCode=CALDER``) que agrupa os
# postos de bancada/máquina do Gestor. Corte fica **fora** por decisão
# funcional explícita desta etapa. Solda, Pintura e Montagem não entram: suas
# técnicas de inspeção são diferentes e ainda não possuem regra validada, e
# inventar uma seria pior do que deixar a aba indisponível.
QUALITY_ENABLED_SECTORS = ("Dobra", "Usinagem", "Serra")

# Setores em que a etapa "INSPECAO"/"INSPECAO QUALIDADE" do roteiro (a
# operação real cadastrada em ``catalogo_operacoes_op``, não a aba Qualidade)
# nunca é apontada por ninguém: o Gestor conclui essa etapa sozinho assim que
# a operação real anterior termina e segue para a próxima (decisão do
# usuário, 16/09/2026 — o recurso físico de inspeção da Caldeiraria não
# existe mais na fábrica).
#
# Isto é independente de ``QUALITY_ENABLED_SECTORS``/``sector_has_quality``:
# a aba Qualidade, os templates de cota, a primeira peça e a fila do
# inspetor continuam exatamente como estão para estes três setores. Só o
# marco de roteiro da INSPECAO passa a ser automático — nada mais muda.
INSPECTION_STEP_AUTO_SKIP_SECTORS = ("Dobra", "Usinagem", "Serra")

# Assinatura industrial exata da operação de inspeção no ProductionOrder.
# A chave é ``(ActivityDescription, WorkCenterCode, MachineCode)`` normalizada.
# Não existe prefixo, semelhança ou fuzzy matching: cada entrada é uma decisão
# funcional registrada. ``ActivityCode`` fica de fora porque a mesma operação
# real já foi observada como ``20`` e como ``30``.
QUALITY_INSPECTION_SIGNATURES = frozenset(
    {
        ("inspecao", "calder", "inspec"),
        ("inspecao qualidade", "calder", "inspec"),
    }
)

# Faixa de execução da inspeção em ``apontamentos_operacionais``.
#
# A inspeção é uma operação real do roteiro, executada em um recurso real
# (``INSPEC``), e por isso precisa de um apontamento canônico próprio. Ela não
# pode ocupar a faixa do setor do operador: o índice único parcial
# ``idx_apontamento_ativo_op_setor`` impede duas execuções ativas da mesma OP
# no mesmo setor, e a inspeção acontece **enquanto** o posto segue trabalhando.
# Este valor é um rótulo de fluxo dentro da execução, não um perfil de usuário
# e não um setor operacional novo.
QUALITY_APPOINTMENT_SECTOR = "Qualidade"

# Resultados possíveis de uma peça inspecionada.
QUALITY_RESULT_APPROVED = "APROVADA"
QUALITY_RESULT_REWORK = "RETRABALHO"
QUALITY_RESULT_SCRAP = "REFUGO"
QUALITY_PIECE_RESULTS = (
    QUALITY_RESULT_APPROVED,
    QUALITY_RESULT_REWORK,
    QUALITY_RESULT_SCRAP,
)

# Status possíveis de uma cota medida.
QUALITY_MEASURE_CONFORMING = "CONFORME"
QUALITY_MEASURE_NON_CONFORMING = "NAO_CONFORME"
QUALITY_MEASURE_STATUSES = (
    QUALITY_MEASURE_CONFORMING,
    QUALITY_MEASURE_NON_CONFORMING,
)

# Estados da sessão de inspeção de uma OP.
QUALITY_SESSION_OPEN = "EM_INSPECAO"
QUALITY_SESSION_FINISHED = "CONCLUIDA"
QUALITY_SESSION_STATUSES = (QUALITY_SESSION_OPEN, QUALITY_SESSION_FINISHED)

# Níveis que podem alterar o template de cotas já salvo de um produto.
# O operador comum cadastra a primeira definição e depois só visualiza.
QUALITY_TEMPLATE_EDITOR_LEVELS = ("admin", "supervisor", "lider")


def _normalized(value):
    return str(value or "").strip().casefold()


def sector_has_quality(sector):
    """Indica se um setor operacional possui inspeção de qualidade habilitada."""

    key = _normalized(sector)
    return any(_normalized(name) == key for name in QUALITY_ENABLED_SECTORS if key)


def inspection_step_auto_skipped(sector):
    """Indica se a etapa INSPECAO do roteiro deste setor é concluída sozinha."""

    key = _normalized(sector)
    return any(
        _normalized(name) == key for name in INSPECTION_STEP_AUTO_SKIP_SECTORS if key
    )


def is_quality_inspection_signature(
    activity_description, work_center_code, machine_code
):
    """Reconhece a operação de inspeção somente por assinatura exata."""

    return (
        _normalized(activity_description),
        _normalized(work_center_code),
        _normalized(machine_code),
    ) in QUALITY_INSPECTION_SIGNATURES


def normalize_piece_result(value):
    """Normaliza o resultado da peça, ou devolve vazio quando inválido."""

    candidate = str(value or "").strip().upper()
    return candidate if candidate in QUALITY_PIECE_RESULTS else ""


def normalize_measure_status(value):
    """Normaliza o status da cota, aceitando o rótulo exibido na tela."""

    candidate = str(value or "").strip().upper().replace("Ã", "A").replace("-", "_")
    candidate = candidate.replace(" ", "_")
    if candidate in {"NAO_CONFORME", "NAOCONFORME"}:
        return QUALITY_MEASURE_NON_CONFORMING
    if candidate == QUALITY_MEASURE_CONFORMING:
        return QUALITY_MEASURE_CONFORMING
    return ""


def can_edit_quality_template(level):
    """Somente Supervisor/Líder (e admin) alteram um template já salvo."""

    return _normalized(level) in {
        _normalized(item) for item in QUALITY_TEMPLATE_EDITOR_LEVELS
    }
