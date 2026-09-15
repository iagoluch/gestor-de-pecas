"""Regra industrial da **primeira peça** — o portão de liberação do lote.

Regra recebida da gestão na Wave 5, em uma frase: a inspeção deixa de ser peça
a peça e passa a ser a aprovação da **primeira peça** da operação; enquanto ela
não estiver validada, a operação não pode ser finalizada.

O portão é avaliado sempre com os mesmos cinco fatos, nesta ordem:

1. não existe bloqueio ativo (retrabalho da primeira peça aguardando responsável);
2. a primeira peça foi produzida;
3. o Setup foi apontado, **quando a operação possui Setup configurado**;
4. a inspeção da primeira peça foi concluída;
5. o resultado dela é ``CONFORME``.

Este módulo é puro: ele não conhece banco, HTTP, React nem sessão. Ele recebe
fatos e devolve a decisão com o código de erro canônico correspondente, para
que backend e frontend nunca escrevam duas versões da mesma regra.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.operator_sectors import WELDING_SECTOR_NAMES
from app.core.quality import sector_has_quality


# ---------------------------------------------------------------------------
# Estados da primeira peça
# ---------------------------------------------------------------------------
# ``PENDENTE``   a operação começou e a primeira peça ainda não saiu da máquina.
# ``PRODUZIDA``  a primeira peça existe e aguarda a inspeção do próprio operador.
# ``CONFORME``   inspecionada e aprovada: o lote inteiro está liberado.
# ``RETRABALHO`` reprovada com retrabalho: a OP fica BLOQUEADA até o responsável.
# ``REFUGO``     reprovada e descartada: é preciso produzir outra primeira peça.
FIRST_PIECE_PENDING = "PENDENTE"
FIRST_PIECE_PRODUCED = "PRODUZIDA"
FIRST_PIECE_CONFORMING = "CONFORME"
FIRST_PIECE_REWORK = "RETRABALHO"
FIRST_PIECE_SCRAP = "REFUGO"

FIRST_PIECE_STATUSES = (
    FIRST_PIECE_PENDING,
    FIRST_PIECE_PRODUCED,
    FIRST_PIECE_CONFORMING,
    FIRST_PIECE_REWORK,
    FIRST_PIECE_SCRAP,
)

# Resultados que o operador pode registrar na inspeção da primeira peça.
FIRST_PIECE_RESULTS = (
    FIRST_PIECE_CONFORMING,
    FIRST_PIECE_REWORK,
    FIRST_PIECE_SCRAP,
)

# Ocorrências que exigem o crachá do responsável designado.
#
# O retrabalho da primeira peça **bloqueia** a OP e é desbloqueado pelo crachá.
# O refugo não bloqueia, mas desde o ajuste da Wave 6B ele também é decisão de
# responsável: a autorização acontece antes do descarte, com o mesmo cadastro
# de crachás e a mesma auditoria. As duas ocorrências existem separadas para
# que a auditoria não confunda um caso com o outro.
FIRST_PIECE_BLOCK_OCCURRENCE = "RETRABALHO_PRIMEIRA_PECA"
FIRST_PIECE_SCRAP_OCCURRENCE = "REFUGO_PRIMEIRA_PECA"

# Refugo apontado na finalização da operação (peças descartadas do lote, não a
# primeira peça). Também exige o crachá do responsável designado.
PRODUCTION_SCRAP_OCCURRENCE = "REFUGO_APONTAMENTO"

# Setores cujo posto representa o próprio setor e que **não possuem Setup**
# configurado no Gestor. A lista não é estética: ela é a mesma barreira que o
# ``OperatorFlowService`` já aplicava ao recusar a ação Setup. Inventar Setup
# aqui criaria uma exigência industrial que a fábrica não tem.
# Wave 6F — os cinco setores que substituíram a antiga "Solda" herdam a mesma
# ausência de Setup que o setor único tinha.
SECTORS_WITHOUT_SETUP = ("Pintura", *WELDING_SECTOR_NAMES)

# Setores com fluxo operacional próprio: eles não passam pelo posto de bancada
# e por isso não participam do portão da primeira peça.
#
# Solda e Pintura entram aqui por decisão do usuário (15/09/2026): esses dois
# setores têm esquema de qualidade próprio, fora do domínio da primeira peça —
# no Gestor eles existem só como recurso apontável para contar tempo (Iniciar/
# Parada/Finalizar/Retrabalho), sem checklist nem conferência de lote.
SECTORS_OUTSIDE_FIRST_PIECE = ("Corte", "Destaque", "Qualidade", "Pintura", *WELDING_SECTOR_NAMES)


def _normalized(value) -> str:
    return str(value or "").strip().casefold()


def sector_has_setup(sector) -> bool:
    """Indica se o setor possui Setup segundo a configuração já existente."""

    key = _normalized(sector)
    if not key:
        return False
    return key not in {_normalized(name) for name in SECTORS_WITHOUT_SETUP}


def normalize_first_piece_result(value) -> str:
    """Normaliza o resultado informado pelo operador, ou devolve vazio."""

    candidate = str(value or "").strip().upper()
    candidate = candidate.replace("Ã", "A").replace("-", "_").replace(" ", "_")
    if candidate in {"NAO_CONFORME", "NAOCONFORME"}:
        # A tela do operador fala em "Não conforme"; industrialmente isso é
        # retrabalho até que o operador diga que a peça foi descartada.
        return FIRST_PIECE_REWORK
    return candidate if candidate in FIRST_PIECE_RESULTS else ""


def first_piece_applies(sector, operation) -> bool:
    """Diz se a operação selecionada está sujeita ao portão da primeira peça.

    Ficam de fora: Corte e Destaque (fluxos próprios), a faixa interna da
    Qualidade, o marco terminal, a própria operação ``INSPECAO`` do roteiro, e
    Solda/Pintura por completo — esses dois setores têm esquema de qualidade
    próprio e no Gestor existem só como recurso apontável para contar tempo.
    """

    if _normalized(sector) in {_normalized(name) for name in SECTORS_OUTSIDE_FIRST_PIECE}:
        return False
    row = dict(operation or {})
    if row.get("marco_terminal"):
        return False
    if row.get("inspecao_qualidade"):
        return False
    return True


# Wave 6B — código que recusa a **finalização** enquanto a primeira peça não
# foi aprovada. Ele não é um estado novo: é a mesma primeira peça pendente.
# Produzir nunca é bloqueado por ele, e a conferência acontece no botão Setup —
# por isso a frase manda o operador para lá, em vez de abrir um popup aqui.
FIRST_PIECE_GATE_REQUIRED = "primeira_peca_gate_obrigatorio"
FIRST_PIECE_GATE_REQUIRED_MESSAGE = (
    "Aponte o Setup desta operação para conferir a primeira peça antes de "
    "finalizar."
)


def first_piece_gate_is_structured(sector, operation) -> bool:
    """Diz se a operação usa o portão estruturado do Iniciar (Wave 6B).

    O checklist de cotas é a inspeção dimensional que só a Caldeiraria possui
    (``Dobra``, ``Usinagem`` e ``Serra``, em ``app/core/quality.py``). Solda,
    Pintura e Corte continuam com o fluxo que já tinham: nenhuma lista de
    setores nova é criada aqui, para não existirem duas autoridades.
    """

    return first_piece_applies(sector, operation) and sector_has_quality(sector)


@dataclass(frozen=True)
class FirstPieceGate:
    """Decisão do portão, pronta para virar resposta HTTP ou estado de botão."""

    aplicavel: bool
    liberado: bool
    status: str = FIRST_PIECE_PENDING
    peca_produzida: bool = False
    setup_obrigatorio: bool = False
    setup_registrado: bool = False
    inspecao_concluida: bool = False
    bloqueio_ativo: bool = False
    # Wave 6B — sinal derivado (não persistido) que diz à tela que a entrada
    # deste portão é o popup Setup/Qualidade do botão Iniciar.
    gate_estruturado: bool = False
    code: str = ""
    message: str = ""
    pendencias: tuple[str, ...] = field(default_factory=tuple)

    def como_dicionario(self) -> dict:
        return {
            "aplicavel": self.aplicavel,
            "liberado": self.liberado,
            "status": self.status,
            "peca_produzida": self.peca_produzida,
            "setup_obrigatorio": self.setup_obrigatorio,
            "setup_registrado": self.setup_registrado,
            "inspecao_concluida": self.inspecao_concluida,
            "bloqueio_ativo": self.bloqueio_ativo,
            "gate_estruturado": self.gate_estruturado,
            "code": self.code,
            "message": self.message,
            "pendencias": list(self.pendencias),
        }


LIBERADO = FirstPieceGate(
    aplicavel=True,
    liberado=True,
    status=FIRST_PIECE_CONFORMING,
    peca_produzida=True,
    inspecao_concluida=True,
    message="Primeira peça aprovada. O lote está liberado.",
)

NAO_APLICAVEL = FirstPieceGate(
    aplicavel=False,
    liberado=True,
    status=FIRST_PIECE_CONFORMING,
    message="Esta operação não está sujeita à regra da primeira peça.",
)


def evaluate_first_piece_gate(
    *,
    aplicavel: bool,
    status: str = FIRST_PIECE_PENDING,
    peca_produzida: bool = False,
    setup_obrigatorio: bool = False,
    setup_registrado: bool = False,
    bloqueio_ativo: bool = False,
    gate_estruturado: bool = False,
) -> FirstPieceGate:
    """Avalia o portão da primeira peça a partir dos fatos já persistidos."""

    if not aplicavel:
        return NAO_APLICAVEL

    estado = str(status or FIRST_PIECE_PENDING).strip().upper()
    if estado not in FIRST_PIECE_STATUSES:
        estado = FIRST_PIECE_PENDING
    inspecao_concluida = estado in {
        FIRST_PIECE_CONFORMING,
        FIRST_PIECE_REWORK,
        FIRST_PIECE_SCRAP,
    }

    def recusa(code: str, message: str, pendencia: str) -> FirstPieceGate:
        return FirstPieceGate(
            aplicavel=True,
            liberado=False,
            status=estado,
            peca_produzida=bool(peca_produzida),
            setup_obrigatorio=bool(setup_obrigatorio),
            setup_registrado=bool(setup_registrado),
            inspecao_concluida=inspecao_concluida,
            bloqueio_ativo=bool(bloqueio_ativo),
            gate_estruturado=bool(gate_estruturado),
            code=code,
            message=message,
            pendencias=(pendencia,),
        )

    if bloqueio_ativo:
        return recusa(
            "primeira_peca_bloqueada",
            "A primeira peça entrou em retrabalho e a OP está bloqueada. "
            "Chame o responsável para liberar com o crachá dele.",
            "autorizacao_do_responsavel",
        )
    # Wave 6B — no portão estruturado o operador produz normalmente e a
    # conferência da primeira peça acontece no **Setup**: é o botão Setup que
    # abre o checklist. Por isso a finalização tem uma pendência só, e ela
    # orienta o operador para esse botão. "Peça não produzida" e "inspeção
    # pendente" descrevem o mesmo passo aqui e não são pedidos separados.
    if gate_estruturado and estado != FIRST_PIECE_CONFORMING:
        return recusa(
            FIRST_PIECE_GATE_REQUIRED,
            FIRST_PIECE_GATE_REQUIRED_MESSAGE,
            "setup",
        )
    if not peca_produzida:
        return recusa(
            "primeira_peca_nao_produzida",
            "Produza e registre a primeira peça antes de finalizar a operação.",
            "primeira_peca",
        )
    if setup_obrigatorio and not setup_registrado:
        return recusa(
            "primeira_peca_setup_pendente",
            "Aponte o Setup desta operação antes de finalizar.",
            "setup",
        )
    if estado in {FIRST_PIECE_PENDING, FIRST_PIECE_PRODUCED}:
        return recusa(
            "primeira_peca_inspecao_pendente",
            "Inspecione a primeira peça antes de finalizar a operação.",
            "inspecao",
        )
    if estado == FIRST_PIECE_SCRAP:
        return recusa(
            "primeira_peca_refugada",
            "A primeira peça foi refugada. Produza e inspecione outra primeira peça.",
            "primeira_peca",
        )
    if estado != FIRST_PIECE_CONFORMING:
        return recusa(
            "primeira_peca_nao_conforme",
            "A primeira peça não está conforme. O lote não pode ser liberado.",
            "inspecao",
        )
    return FirstPieceGate(
        aplicavel=True,
        liberado=True,
        status=FIRST_PIECE_CONFORMING,
        peca_produzida=True,
        setup_obrigatorio=bool(setup_obrigatorio),
        setup_registrado=bool(setup_registrado),
        inspecao_concluida=True,
        bloqueio_ativo=False,
        gate_estruturado=bool(gate_estruturado),
        message="Primeira peça aprovada. O lote está liberado.",
    )


__all__ = [
    "FIRST_PIECE_BLOCK_OCCURRENCE",
    "FIRST_PIECE_SCRAP_OCCURRENCE",
    "PRODUCTION_SCRAP_OCCURRENCE",
    "FIRST_PIECE_CONFORMING",
    "FIRST_PIECE_GATE_REQUIRED",
    "FIRST_PIECE_GATE_REQUIRED_MESSAGE",
    "FIRST_PIECE_PENDING",
    "FIRST_PIECE_PRODUCED",
    "FIRST_PIECE_RESULTS",
    "FIRST_PIECE_REWORK",
    "FIRST_PIECE_SCRAP",
    "FIRST_PIECE_STATUSES",
    "FirstPieceGate",
    "SECTORS_OUTSIDE_FIRST_PIECE",
    "SECTORS_WITHOUT_SETUP",
    "evaluate_first_piece_gate",
    "first_piece_applies",
    "first_piece_gate_is_structured",
    "normalize_first_piece_result",
    "sector_has_setup",
]
