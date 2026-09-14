"""Contratos neutros do outbound Gestor -> TOTVS WSPCP.

Estes DTOs não conhecem SOAP, HTTP, FastAPI ou a tela do operador. O fato de
origem é sempre um evento canônico já confirmado e persistido.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class CanonicalExecutionEvent:
    event_id: int
    appointment_id: int
    state: str
    event_time: datetime
    production_order: str
    operation: str
    activity_id: str
    resource_code: str
    item_code: str
    item_description: str | None
    warehouse_code: str | None
    company_id: str
    branch_id: str
    operator_code: str | None
    good_quantity: Decimal
    scrap_quantity: Decimal
    rework_quantity: Decimal
    planned_quantity: Decimal
    accumulated_good_quantity: Decimal
    event_reason: str | None = None
    # Motivo do refugo gravado no próprio evento de quantidade. É ele, e não
    # o texto livre da transição, que mapeia para o WasteCode do Protheus.
    scrap_reason: str | None = None
    resource_status_code: str | None = None
    execution_started_at: datetime | None = None
    previous_state: str | None = None
    previous_event_time: datetime | None = None
    previous_reason: str | None = None
    previous_resource_status_code: str | None = None
    previous_interruption_planned: bool | None = None
    resource_divergent: bool = False


@dataclass(frozen=True)
class CanonicalTerminalMilestone:
    """Fato canônico do encerramento produtivo de uma OP.

    Reúne o marco terminal recebido no ``ProductionOrder`` (que não é operação
    de operador) com o resultado real da última operação produtiva executada no
    Gestor. Nada aqui é planejamento: as quantidades vêm de
    ``eventos_quantidade_producao``.
    """

    production_order: str
    item_code: str
    item_description: str | None
    warehouse_code: str | None
    company_id: str
    branch_id: str
    planned_quantity: Decimal
    # Marco terminal preservado do roteiro TOTVS.
    terminal_operation: str
    terminal_resource_code: str
    terminal_activity_id: str | None
    # Última operação produtiva apontável do roteiro e o que ela concluiu.
    last_operation: str
    last_operation_good_quantity: Decimal
    last_operation_scrap_quantity: Decimal
    last_operation_rework_quantity: Decimal
    execution_started_at: datetime | None
    execution_finished_at: datetime | None
    operator_code: str | None
    # Fechamento da execução segundo a máquina de estados do operador.
    pointable_operations: int
    concluded_operations: int
    open_operations: tuple[str, ...] = ()
    resource_divergent: bool = False

    @property
    def execution_completed(self) -> bool:
        return (
            self.pointable_operations > 0
            and self.concluded_operations == self.pointable_operations
            and not self.open_operations
        )


@dataclass(frozen=True)
class TotvsOutboundIdentity:
    source_application: str = "GESTOR_PECAS"
    product_name: str = "GESTOR_PECAS"
    product_version: str = "1.0"
    context_name: str = "GESTOR_PECAS"


@dataclass(frozen=True)
class ProductionAppointmentContract:
    message_uuid: str
    idempotency_key: str
    company_id: str
    branch_id: str
    generated_on: datetime
    machine_code: str
    production_order_number: str
    # Opcional: sem destino comprovado no Protheus (MATI681 lê apenas ActivityCode).
    activity_id: str | None
    activity_code: str
    item_code: str
    report_quantity: Decimal
    approved_quantity: Decimal
    scrap_quantity: Decimal
    start_report_datetime: datetime
    end_report_datetime: datetime
    report_datetime: datetime
    close_operation: bool
    operator_code: str | None = None
    warehouse_code: str | None = None
    waste_code: str | None = None


@dataclass(frozen=True)
class StopReportContract:
    message_uuid: str
    idempotency_key: str
    company_id: str
    branch_id: str
    generated_on: datetime
    machine_code: str
    stop_reason_code: str
    start_datetime: datetime
    end_datetime: datetime
    report_datetime: datetime
    operator_code: str | None = None


@dataclass(frozen=True)
class TotvsOutboundMessage:
    transaction: str
    idempotency_key: str
    xml: str


@dataclass(frozen=True)
class TotvsOutboundAck:
    status: str
    transaction: str | None
    messages: tuple[str, ...]
    internal_ids: tuple[tuple[str | None, str], ...]
    raw_xml: str
    duplicate_code: int | None = None
    http_status: int | None = None
    raw_soap: str | None = None

    @property
    def success(self) -> bool:
        return self.status.strip().upper() == "OK"

    @property
    def already_processed(self) -> bool:
        return self.duplicate_code == 3

    @property
    def accepted(self) -> bool:
        return self.success or self.already_processed
