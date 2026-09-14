"""Regras de acompanhamento gerencial dos conjuntos soldados (Wave 6D).

Este módulo é puro: não consulta banco, não conhece FastAPI e não conhece
componente visual. Ele responde três perguntas da PCP/Liderança sobre uma OP de
Solda:

* qual a data que representa a **criação** da OP;
* qual a data que representa a **janela de prazo** da OP;
* a OP está ``A VENCER``, ``ATRASADA`` ou ``FINALIZADA``.

Fronteiras assumidas de propósito:

* **Atraso é acompanhamento, não trava.** Nada aqui bloqueia iniciar, parar,
  retomar ou finalizar. A autoridade da execução continua sendo a máquina de
  estados do operador; esta classificação é leitura.
* **A estação não é derivada.** A estação de Solda é uma escolha operacional do
  posto no momento em que ele pega a OP; não existe mapeamento determinístico
  produto/máquina → estação e não deve existir. Aqui só entra a estação
  observada no apontamento real.
* **Nada é estimado em silêncio.** Quando a OP não tem base temporal, o estado
  fica indisponível com motivo, em vez de virar "A VENCER" por eliminação.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from mes.domain.industrial import DataAvailability


#: Rótulo da frente acompanhada por esta visão.
#:
#: Wave 6F — desde o desmembramento da Solda em cinco setores, este valor é só
#: o nome da frente na tela (o mesmo do painel "Solda" no Andon). **Não** é o
#: filtro do roteiro: quem decide quais ``tipo_setor`` entram na consulta é
#: ``app.database.welding_repository.WELDING_MANAGEMENT_SECTORS``.
WELDING_SECTOR = "Solda"

#: Os três estados do acompanhamento da PCP. Não existe um quarto estado: a
#: ausência de base temporal é *ausência de estado*, não um estado novo.
WELDING_STATUS_DUE = "A VENCER"
WELDING_STATUS_LATE = "ATRASADA"
WELDING_STATUS_DONE = "FINALIZADA"
WELDING_STATUSES = (WELDING_STATUS_DUE, WELDING_STATUS_LATE, WELDING_STATUS_DONE)

#: Estado do apontamento operacional que prova conclusão. Data planejada,
#: existência da OP e fim de janela **não** substituem o apontamento.
FINISHED_APPOINTMENT_STATUS = "Finalizado"


# ----------------------------------------------------------------------
# Base temporal
# ----------------------------------------------------------------------
# O planejamento corporativo entrega hoje `inicio_planejado`, `fim_planejado` e
# o instante em que gerou a ordem. `data_emissao` e `prazo_entrega` são colunas
# do catálogo original por planilha e continuam válidas quando preenchidas, mas
# a ingestão corporativa atual não as alimenta. Por isso cada base é resolvida
# por precedência explícita e a leitura declara qual campo usou: a tela mostra
# "parcial" quando trabalha com a alternativa, em vez de fingir prazo oficial.
CREATION_BASIS_ISSUE = "emissao"
CREATION_BASIS_GENERATED = "geracao_planejamento"
DEADLINE_BASIS_DELIVERY = "prazo_entrega"
DEADLINE_BASIS_PLANNED_END = "fim_planejado"

BASIS_LABELS = {
    CREATION_BASIS_ISSUE: "Emissão da OP",
    CREATION_BASIS_GENERATED: "Geração da OP no planejamento",
    DEADLINE_BASIS_DELIVERY: "Prazo de entrega",
    DEADLINE_BASIS_PLANNED_END: "Fim planejado",
}


@dataclass(frozen=True)
class TemporalBasis:
    """Data escolhida para uma pergunta temporal, com a origem declarada."""

    value: datetime | None
    basis: str | None
    availability: str

    @property
    def label(self) -> str | None:
        return BASIS_LABELS.get(self.basis) if self.basis else None


def _as_datetime(value):
    if isinstance(value, datetime):
        return value.replace(microsecond=0)
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    return None


def _first_basis(candidates, primary_basis):
    """Primeira data preenchida da precedência, marcando se é a preferida."""

    for basis, raw in candidates:
        moment = _as_datetime(raw)
        if moment is None:
            continue
        availability = (
            DataAvailability.AVAILABLE.value
            if basis == primary_basis
            else DataAvailability.PARTIAL.value
        )
        return TemporalBasis(moment, basis, availability)
    return TemporalBasis(None, None, DataAvailability.INSUFFICIENT_DATA.value)


def resolve_creation_basis(order) -> TemporalBasis:
    """Data que representa "a OP foi criada"."""

    return _first_basis(
        (
            (CREATION_BASIS_ISSUE, order.get("data_emissao")),
            (CREATION_BASIS_GENERATED, order.get("data_geracao")),
        ),
        CREATION_BASIS_ISSUE,
    )


def resolve_deadline_basis(order) -> TemporalBasis:
    """Data que fecha a janela temporal da OP."""

    return _first_basis(
        (
            (DEADLINE_BASIS_DELIVERY, order.get("prazo_entrega")),
            (DEADLINE_BASIS_PLANNED_END, order.get("fim_planejado")),
        ),
        DEADLINE_BASIS_DELIVERY,
    )


# ----------------------------------------------------------------------
# Semana de criação
# ----------------------------------------------------------------------
def week_bounds(reference):
    """Semana civil (segunda 00:00 → domingo 23:59:59) que contém a referência."""

    moment = _as_datetime(reference)
    if moment is None:
        return None
    start = datetime.combine(moment.date() - timedelta(days=moment.weekday()), time.min)
    end = start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return start, end


def week_is_closed(reference, now):
    """A semana da referência já terminou no instante ``now``?

    Enquanto a semana de criação está em curso, a OP ainda pode receber
    apontamento; classificá-la como atrasada antes disso seria adiantar um
    julgamento que o calendário ainda não permite.
    """

    bounds = week_bounds(reference)
    moment = _as_datetime(now)
    if bounds is None or moment is None:
        return False
    return moment > bounds[1]


def appointed_in_creation_week(creation, first_appointment):
    """Houve apontamento da OP dentro da semana em que ela foi criada?

    ``first_appointment`` é o instante do apontamento mais antigo da OP. Um
    apontamento nunca antecede a criação da ordem, portanto "existe apontamento
    dentro da semana" equivale a "o primeiro apontamento cabe na semana".
    """

    bounds = week_bounds(creation)
    moment = _as_datetime(first_appointment)
    if bounds is None or moment is None:
        return False
    return moment <= bounds[1]


# ----------------------------------------------------------------------
# Classificação
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class WeldingStatus:
    """Estado de acompanhamento de uma OP de Solda.

    ``value`` vazio significa que a OP não tem base temporal conhecida. Nesse
    caso a tela explica a ausência; ela não mostra "A VENCER" por eliminação.
    """

    value: str | None
    availability: str
    reason: str

    @property
    def late(self) -> bool:
        return self.value == WELDING_STATUS_LATE

    @property
    def finished(self) -> bool:
        return self.value == WELDING_STATUS_DONE


def classify_welding_status(
    order,
    *,
    appointment_status=None,
    first_appointment=None,
    now,
) -> WeldingStatus:
    """Classifica a OP de Solda em A VENCER / ATRASADA / FINALIZADA.

    Ordem de decisão:

    1. **FINALIZADA** — existe apontamento operacional concluído da operação de
       Solda. Só o apontamento prova conclusão.
    2. **ATRASADA** — a OP foi criada em uma semana que já fechou e não recebeu
       apontamento nessa mesma semana; ou a janela de prazo já venceu.
    3. **A VENCER** — a OP ainda está dentro da janela de prazo.
    4. Sem base temporal, o estado permanece indisponível com motivo.
    """

    if str(appointment_status or "").strip() == FINISHED_APPOINTMENT_STATUS:
        return WeldingStatus(
            WELDING_STATUS_DONE,
            DataAvailability.AVAILABLE.value,
            "Solda concluída e apontada pelo posto.",
        )

    creation = resolve_creation_basis(order)
    deadline = resolve_deadline_basis(order)
    moment = _as_datetime(now)

    if (
        creation.value is not None
        and week_is_closed(creation.value, moment)
        and not appointed_in_creation_week(creation.value, first_appointment)
    ):
        return WeldingStatus(
            WELDING_STATUS_LATE,
            creation.availability,
            "Sem apontamento na semana em que a OP foi criada.",
        )

    if deadline.value is not None:
        if moment is not None and moment > deadline.value:
            return WeldingStatus(
                WELDING_STATUS_LATE,
                deadline.availability,
                "A janela de prazo da OP já venceu e a Solda não foi concluída.",
            )
        return WeldingStatus(
            WELDING_STATUS_DUE,
            deadline.availability,
            "A OP continua dentro da janela de prazo.",
        )

    return WeldingStatus(
        None,
        DataAvailability.INSUFFICIENT_DATA.value,
        "O planejamento ainda não informou o prazo desta OP.",
    )
