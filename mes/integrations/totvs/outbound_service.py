"""Caso de uso manual/controlado do outbound, pronto para futura outbox."""

from __future__ import annotations

from typing import Protocol

from mes.integrations.totvs.errors import TotvsContractError
from mes.integrations.totvs.outbound_mapper import (
    build_production_appointment_xml,
    build_stop_report_xml,
    map_production_appointment,
    map_stop_report,
    map_terminal_production_appointment,
)
from mes.integrations.totvs.outbound_models import (
    CanonicalExecutionEvent,
    CanonicalTerminalMilestone,
    TotvsOutboundAck,
    TotvsOutboundMessage,
)


class TotvsOutboundFactRepository(Protocol):
    def buscar_evento_canonico_outbound_totvs(
        self, evento_id: int
    ) -> CanonicalExecutionEvent | None: ...

    def buscar_marco_terminal_outbound_totvs(
        self, codigo_op: str
    ) -> CanonicalTerminalMilestone | None: ...


class TotvsOutboundGateway(Protocol):
    def send(self, message: TotvsOutboundMessage) -> TotvsOutboundAck: ...


class TotvsOutboundService:
    """Orquestra leitura -> mapper -> gateway sem conhecer execução do operador."""

    def __init__(self, repository: TotvsOutboundFactRepository, gateway: TotvsOutboundGateway | None = None):
        self.repository = repository
        self.gateway = gateway

    def _event(self, event_id: int) -> CanonicalExecutionEvent:
        event = self.repository.buscar_evento_canonico_outbound_totvs(int(event_id))
        if event is None:
            raise TotvsContractError(f"Evento canônico {event_id} não encontrado.")
        return event

    def build_production_appointment(
        self,
        event_id: int,
        *,
        waste_code: str | None = None,
        allow_zero_quantity: bool = False,
    ) -> tuple[CanonicalExecutionEvent, TotvsOutboundMessage]:
        event = self._event(event_id)
        contract = map_production_appointment(
            event,
            waste_code=waste_code,
            allow_zero_quantity=allow_zero_quantity,
        )
        return event, build_production_appointment_xml(contract)

    def build_terminal_production_appointment(
        self, codigo_op: str
    ) -> tuple[CanonicalTerminalMilestone, TotvsOutboundMessage]:
        """Monta o apontamento do marco terminal quando a OP já foi concluída.

        Não existe gatilho na ingestão nem na tela: o fato é lido do estado
        canônico atual e o mapper recusa a emissão enquanto houver operação
        apontável em aberto.
        """

        milestone = self.repository.buscar_marco_terminal_outbound_totvs(str(codigo_op))
        if milestone is None:
            raise TotvsContractError(
                f"OP {codigo_op} não possui marco terminal recebido do TOTVS."
            )
        contract = map_terminal_production_appointment(milestone)
        return milestone, build_production_appointment_xml(contract)

    def build_stop_report(
        self,
        event_id: int,
        *,
        stop_reason_code: str,
    ) -> tuple[CanonicalExecutionEvent, TotvsOutboundMessage]:
        event = self._event(event_id)
        contract = map_stop_report(event, stop_reason_code=stop_reason_code)
        return event, build_stop_report_xml(contract)

    def send(self, message: TotvsOutboundMessage) -> TotvsOutboundAck:
        if self.gateway is None:
            raise TotvsContractError("Gateway outbound não configurado para envio.")
        return self.gateway.send(message)
