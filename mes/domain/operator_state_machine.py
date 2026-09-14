"""Máquina de estados canônica do apontamento de operador.

Este módulo concentra a regra funcional compartilhada por serviços, API e
persistência. A camada de infraestrutura pode traduzir os estados para os
nomes legados das colunas, mas não mantém um segundo mapa de transições.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class OperatorState(str, Enum):
    QUEUED = "fila"
    PRODUCTION = "producao"
    STOPPED = "parada"
    SETUP = "setup"
    REWORK = "retrabalho"
    FINISHED = "finalizado"


class OperatorAction(str, Enum):
    START = "Início"
    STOP = "Parada"
    SETUP = "Setup"
    REWORK = "Retrabalho"
    RESUME = "Retomar"
    RETURN = "Retornar"
    FINISH = "Finalizado"


ALLOWED_TRANSITIONS: Mapping[OperatorState, tuple[OperatorState, ...]] = {
    OperatorState.QUEUED: (
        OperatorState.PRODUCTION,
        OperatorState.STOPPED,
        OperatorState.SETUP,
        OperatorState.REWORK,
    ),
    OperatorState.PRODUCTION: (
        OperatorState.STOPPED,
        OperatorState.SETUP,
        OperatorState.REWORK,
        OperatorState.FINISHED,
    ),
    OperatorState.STOPPED: (
        OperatorState.PRODUCTION,
        OperatorState.REWORK,
        OperatorState.FINISHED,
    ),
    OperatorState.SETUP: (
        OperatorState.PRODUCTION,
        OperatorState.REWORK,
        OperatorState.FINISHED,
    ),
    OperatorState.REWORK: (
        OperatorState.STOPPED,
        OperatorState.SETUP,
        OperatorState.FINISHED,
    ),
    OperatorState.FINISHED: (),
}


OPERATOR_STATUS_BY_STATE: Mapping[OperatorState, str] = {
    OperatorState.QUEUED: "Aguardando",
    OperatorState.PRODUCTION: "Em processo",
    OperatorState.STOPPED: "Parada",
    OperatorState.SETUP: "Setup",
    OperatorState.REWORK: "Retrabalho",
    OperatorState.FINISHED: "Finalizado",
}
OPERATOR_STATE_BY_STATUS: Mapping[str, OperatorState] = {
    status: state for state, status in OPERATOR_STATUS_BY_STATE.items()
}


_DIRECT_ACTION_TARGETS: Mapping[OperatorAction, OperatorState] = {
    OperatorAction.START: OperatorState.PRODUCTION,
    OperatorAction.STOP: OperatorState.STOPPED,
    OperatorAction.SETUP: OperatorState.SETUP,
    OperatorAction.REWORK: OperatorState.REWORK,
    OperatorAction.FINISH: OperatorState.FINISHED,
}
_RETURNABLE_STATES = frozenset({OperatorState.PRODUCTION, OperatorState.REWORK})
_TEMPORARY_STATES = frozenset({OperatorState.STOPPED, OperatorState.SETUP})


@dataclass(frozen=True)
class TransitionValidation:
    ok: bool
    missing_fields: tuple[str, ...] = ()
    message: str = ""


def operator_state_from_status(status: object) -> OperatorState | None:
    return OPERATOR_STATE_BY_STATUS.get(str(status or "").strip())


def operator_status_for_state(state: OperatorState | str) -> str:
    return OPERATOR_STATUS_BY_STATE[OperatorState(state)]


def can_transition(current: OperatorState | str, target: OperatorState | str) -> bool:
    try:
        source = OperatorState(current)
        destination = OperatorState(target)
    except (TypeError, ValueError):
        return False
    return destination in ALLOWED_TRANSITIONS[source]


def resolve_operator_action(
    action: OperatorAction | str,
    current: OperatorState | str,
    return_state: OperatorState | str | None = None,
) -> OperatorState | None:
    """Resolve ações de UX preservando a atividade interrompida.

    ``Início`` continua aceito por compatibilidade com clientes existentes. Em
    Parada/Setup ele possui semântica de retomada e respeita ``return_state``.
    Os nomes explícitos ``Retomar`` e ``Retornar`` são aceitos pela API Web.
    """

    try:
        parsed_action = OperatorAction(action)
        source = OperatorState(current)
    except (TypeError, ValueError):
        return None
    try:
        previous = OperatorState(return_state) if return_state else None
    except (TypeError, ValueError):
        previous = None

    if parsed_action == OperatorAction.RESUME:
        if source != OperatorState.STOPPED:
            return None
        return previous if previous in _RETURNABLE_STATES else OperatorState.PRODUCTION
    if parsed_action == OperatorAction.RETURN:
        if source != OperatorState.SETUP:
            return None
        return previous if previous in _RETURNABLE_STATES else OperatorState.PRODUCTION
    if parsed_action == OperatorAction.START and source in _TEMPORARY_STATES:
        return previous if previous in _RETURNABLE_STATES else OperatorState.PRODUCTION
    target = _DIRECT_ACTION_TARGETS.get(parsed_action)
    return target if target is not None and can_transition(source, target) else None


#: Código histórico devolvido para qualquer recusa da máquina de estados.
#: Continua sendo o contrato aceito por clientes antigos: os códigos
#: específicos abaixo apenas o refinam e sempre o acompanham em ``details``.
GENERIC_INVALID_TRANSITION_CODE = "transicao_invalida"

_STATE_LABELS: Mapping[OperatorState, str] = {
    OperatorState.QUEUED: "na fila",
    OperatorState.PRODUCTION: "em produção",
    OperatorState.STOPPED: "em parada",
    OperatorState.SETUP: "em setup",
    OperatorState.REWORK: "em retrabalho",
    OperatorState.FINISHED: "finalizado",
}


@dataclass(frozen=True)
class InvalidTransition:
    """Motivo específico de uma recusa da máquina de estados."""

    code: str
    message: str
    current: OperatorState | None = None
    requested: OperatorState | None = None

    def as_details(self) -> dict:
        return {
            "codigo_generico": GENERIC_INVALID_TRANSITION_CODE,
            "estado_atual": self.current.value if self.current else None,
            "estado_solicitado": self.requested.value if self.requested else None,
        }


def explain_invalid_transition(
    action: OperatorAction | str,
    current: OperatorState | str,
    return_state: OperatorState | str | None = None,
) -> InvalidTransition:
    """Diferencia as recusas que hoje compartilham ``transicao_invalida``.

    A recusa em si não muda: o que muda é o operador conseguir ler o motivo.
    São situações realmente distintas — repetir a ação, reentrar numa etapa já
    finalizada, retomar o que não está parado e retornar do que não está em
    setup — e cada uma tem uma frase própria. Qualquer outro caso continua no
    código genérico, sem inventar hierarquia.
    """

    try:
        parsed_action = OperatorAction(action)
    except (TypeError, ValueError):
        return InvalidTransition(
            GENERIC_INVALID_TRANSITION_CODE,
            "Ação incompatível com o estado atual do apontamento.",
        )
    try:
        source = OperatorState(current)
    except (TypeError, ValueError):
        source = None

    requested = _DIRECT_ACTION_TARGETS.get(parsed_action)
    label = _STATE_LABELS.get(source, "no estado atual") if source else "no estado atual"

    if source == OperatorState.FINISHED:
        return InvalidTransition(
            "etapa_ja_finalizada",
            "Esta etapa já foi finalizada e não aceita novos apontamentos.",
            source,
            requested,
        )
    if parsed_action == OperatorAction.RESUME:
        return InvalidTransition(
            "retomada_incompativel",
            f"Só é possível retomar um apontamento em parada; ele está {label}.",
            source,
            requested,
        )
    if parsed_action == OperatorAction.RETURN:
        return InvalidTransition(
            "retorno_incompativel",
            f"Só é possível retornar de um setup; o apontamento está {label}.",
            source,
            requested,
        )
    if requested is not None and source == requested:
        return InvalidTransition(
            "acao_ja_registrada",
            f"Esta ação já está registrada: o apontamento já está {label}.",
            source,
            requested,
        )
    return InvalidTransition(
        GENERIC_INVALID_TRANSITION_CODE,
        "Ação incompatível com o estado atual do apontamento.",
        source,
        requested,
    )


def return_state_for_transition(
    current: OperatorState | str,
    target: OperatorState | str,
    current_return_state: OperatorState | str | None = None,
) -> OperatorState | None:
    """Calcula o contexto persistido ao entrar em Parada ou Setup."""

    source = OperatorState(current)
    destination = OperatorState(target)
    if destination not in _TEMPORARY_STATES:
        return None
    if source in _RETURNABLE_STATES:
        return source
    try:
        previous = OperatorState(current_return_state) if current_return_state else None
    except (TypeError, ValueError):
        previous = None
    return previous if previous in _RETURNABLE_STATES else None


def validate_transition(current, target, payload=None) -> TransitionValidation:
    try:
        source = OperatorState(current)
        destination = OperatorState(target)
    except (TypeError, ValueError):
        return TransitionValidation(False, message="Estado de apontamento inválido.")
    if not can_transition(source, destination):
        return TransitionValidation(False, message="Transição de apontamento inválida.")

    payload = payload or {}
    required: list[str] = []
    if source == OperatorState.QUEUED and destination in {
        OperatorState.PRODUCTION,
        OperatorState.STOPPED,
        OperatorState.SETUP,
        OperatorState.REWORK,
    }:
        required.extend(("op", "operacao", "recurso"))
    if destination == OperatorState.STOPPED:
        required.append("motivo_parada")
    if destination == OperatorState.FINISHED:
        required.extend(("pecas_boas", "refugo"))

    missing = [
        field for field in dict.fromkeys(required)
        if payload.get(field) in (None, "")
    ]
    if (
        destination == OperatorState.FINISHED
        and not payload.get("operadores_cracha")
        and payload.get("operador_id") in (None, "")
    ):
        missing.append("operador_id")
    if missing:
        return TransitionValidation(
            False,
            tuple(missing),
            "Dados obrigatórios não informados.",
        )
    return TransitionValidation(True)


__all__ = [
    "ALLOWED_TRANSITIONS",
    "OPERATOR_STATE_BY_STATUS",
    "OPERATOR_STATUS_BY_STATE",
    "OperatorAction",
    "OperatorState",
    "TransitionValidation",
    "can_transition",
    "operator_state_from_status",
    "operator_status_for_state",
    "resolve_operator_action",
    "return_state_for_transition",
    "validate_transition",
]
