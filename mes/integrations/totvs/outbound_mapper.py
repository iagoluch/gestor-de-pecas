"""Mapeamento explícito de fatos canônicos para ProductionAppointment/StopReport."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5
from xml.etree import ElementTree as ET

from mes.integrations.totvs.errors import TotvsContractError
from mes.integrations.totvs.outbound_models import (
    CanonicalExecutionEvent,
    CanonicalTerminalMilestone,
    ProductionAppointmentContract,
    StopReportContract,
    TotvsOutboundIdentity,
    TotvsOutboundMessage,
)


PRODUCTION_APPOINTMENT_TRANSACTION = "productionappointment"
STOP_REPORT_TRANSACTION = "stopreport"
MESSAGE_TYPE = "BusinessMessage"


def _required(value, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise TotvsContractError(f"{field} é obrigatório no outbound TOTVS.")
    return text


def _non_negative(value, field: str) -> Decimal:
    amount = Decimal(str(value or 0))
    if amount < 0:
        raise TotvsContractError(f"{field} não pode ser negativo.")
    return amount


def _timestamp(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise TotvsContractError(f"{field} deve ser um timestamp válido.")
    return value.replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def _decimal(value: Decimal) -> str:
    return format(value, "f")


def _stable_uuid(kind: str, event_id: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"gestor-pecas:{kind}:evento-apontamento:{event_id}"))


def map_production_appointment(
    event: CanonicalExecutionEvent,
    *,
    waste_code: str | None = None,
    allow_zero_quantity: bool = False,
) -> ProductionAppointmentContract:
    """Converte um fato produtivo sem alterar OP, operação ou recurso.

    ``ReworkQuantity`` não é projetado: na implementação Protheus comprovada o
    campo não possui destino. Um valor canônico diferente de zero é bloqueado,
    evitando transformar retrabalho em peça boa ou refugo.
    """

    if event.resource_divergent:
        raise TotvsContractError(
            "O evento possui divergência de recurso; o outbound não escolherá um vencedor."
        )
    good = _non_negative(event.good_quantity, "good_quantity")
    scrap = _non_negative(event.scrap_quantity, "scrap_quantity")
    rework = _non_negative(event.rework_quantity, "rework_quantity")
    if rework:
        raise TotvsContractError(
            "Retrabalho não possui campo efetivo comprovado no MATA681/SH6 e não será enviado."
        )
    close_operation = event.state.strip().casefold() == "finalizado"
    if good + scrap == 0 and not close_operation and not allow_zero_quantity:
        raise TotvsContractError(
            "ProductionAppointment sem quantidade exige allow_zero_quantity explícito de homologação."
        )
    reason = str(waste_code or "").strip() or None
    if scrap and not reason:
        raise TotvsContractError(
            "Refugo exige waste_code TOTVS comprovado; o motivo do Gestor não é convertido implicitamente."
        )
    end = _timestamp(event.event_time, "event_time")
    start = _timestamp(event.execution_started_at or end, "execution_started_at")
    if start > end:
        raise TotvsContractError("execution_started_at não pode ser posterior ao evento.")
    message_uuid = _stable_uuid("productionappointment-message", event.event_id)
    key = _stable_uuid("productionappointment-key", event.event_id)
    return ProductionAppointmentContract(
        message_uuid=message_uuid,
        idempotency_key=key,
        company_id=_required(event.company_id, "CompanyId"),
        branch_id=_required(event.branch_id, "BranchId"),
        generated_on=end,
        machine_code=_required(event.resource_code, "MachineCode"),
        production_order_number=_required(event.production_order, "ProductionOrderNumber"),
        # ActivityID não possui destino no Protheus: a matriz oficial PC-Factory
        # traz "--" na coluna TABELA/CAMPO PROTHEUS e o adapter MATI681 lê apenas
        # ActivityCode. Quando o Gestor não recebeu o ID no ProductionOrder o
        # elemento é omitido, em vez de inventar um identificador do ERP.
        activity_id=str(event.activity_id or "").strip() or None,
        activity_code=_required(event.operation, "ActivityCode"),
        item_code=_required(event.item_code, "ItemCode"),
        report_quantity=good + scrap,
        approved_quantity=good,
        scrap_quantity=scrap,
        start_report_datetime=start,
        end_report_datetime=end,
        report_datetime=end,
        close_operation=close_operation,
        operator_code=str(event.operator_code or "").strip() or None,
        warehouse_code=str(event.warehouse_code or "").strip() or None,
        waste_code=reason,
    )


TERMINAL_KIND = "productionappointment-terminal"


def _stable_uuid_text(kind: str, reference: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"gestor-pecas:{kind}:{reference}"))


def terminal_approved_quantity(milestone: CanonicalTerminalMilestone) -> Decimal:
    """Quantidade boa efetivamente concluída da OP, para o marco terminal.

    Regra canônica única, usada pelo `ProductionAppointment` terminal:

    * a entrega da OP é o resultado da **última operação produtiva** do
      roteiro. Somar as operações intermediárias contaria a mesma peça várias
      vezes, uma por etapa;
    * apenas ``boa`` conta. ``refugo`` nunca vira peça boa e ``retrabalho`` não
      tem destino comprovado no MATA681/SH6 — ele bloqueia a emissão, como já
      acontece no apontamento comum;
    * a quantidade sai de ``eventos_quantidade_producao``, a fonte canônica de
      quantidade do Gestor, e não do planejamento da OP.

    O saldo planejado nunca é usado para "completar" o encerramento: se o
    Gestor concluiu menos que o planejado, é essa quantidade menor que segue, e
    o Protheus decide entre encerramento parcial e total.
    """

    good = _non_negative(milestone.last_operation_good_quantity, "good_quantity")
    rework = _non_negative(milestone.last_operation_rework_quantity, "rework_quantity")
    if rework:
        raise TotvsContractError(
            "Retrabalho não possui campo efetivo comprovado no MATA681/SH6 e não será enviado."
        )
    return good


def map_terminal_production_appointment(
    milestone: CanonicalTerminalMilestone,
) -> ProductionAppointmentContract:
    """Projeta o marco terminal do roteiro TOTVS como apontamento de encerramento.

    O marco terminal não é operação de operador: ele existe apenas como
    metadado recebido no ``ProductionOrder``. ``ActivityCode`` e ``MachineCode``
    são exatamente os que o TOTVS enviou; nada é inventado aqui.
    """

    if milestone.resource_divergent:
        raise TotvsContractError(
            "A execução possui divergência de recurso; o outbound não escolherá um vencedor."
        )
    if not milestone.execution_completed:
        pendentes = ", ".join(milestone.open_operations) or "nenhuma operação apontável"
        raise TotvsContractError(
            "O marco terminal exige a execução da OP concluída no Gestor; "
            f"operações ainda em aberto: {pendentes}."
        )
    end = _timestamp(
        milestone.execution_finished_at, "execution_finished_at"
    )
    start = _timestamp(milestone.execution_started_at or end, "execution_started_at")
    if start > end:
        raise TotvsContractError("execution_started_at não pode ser posterior à conclusão.")
    good = terminal_approved_quantity(milestone)
    if good <= 0:
        raise TotvsContractError(
            "O marco terminal exige quantidade boa concluída maior que zero."
        )
    planned = _non_negative(milestone.planned_quantity, "planned_quantity")
    if planned and good > planned:
        raise TotvsContractError(
            f"Quantidade boa concluída ({_decimal(good)}) maior que a planejada "
            f"({_decimal(planned)}); o Protheus recusaria o apontamento."
        )
    reference = f"{milestone.production_order}:{milestone.terminal_operation}"
    return ProductionAppointmentContract(
        message_uuid=_stable_uuid_text(f"{TERMINAL_KIND}-message", reference),
        idempotency_key=_stable_uuid_text(f"{TERMINAL_KIND}-key", reference),
        company_id=_required(milestone.company_id, "CompanyId"),
        branch_id=_required(milestone.branch_id, "BranchId"),
        generated_on=end,
        machine_code=_required(milestone.terminal_resource_code, "MachineCode"),
        production_order_number=_required(
            milestone.production_order, "ProductionOrderNumber"
        ),
        activity_id=str(milestone.terminal_activity_id or "").strip() or None,
        activity_code=_required(milestone.terminal_operation, "ActivityCode"),
        item_code=_required(milestone.item_code, "ItemCode"),
        report_quantity=good,
        approved_quantity=good,
        scrap_quantity=Decimal(0),
        start_report_datetime=start,
        end_report_datetime=end,
        report_datetime=end,
        close_operation=True,
        operator_code=str(milestone.operator_code or "").strip() or None,
        warehouse_code=str(milestone.warehouse_code or "").strip() or None,
        waste_code=None,
    )


def map_stop_report(
    resume_event: CanonicalExecutionEvent,
    *,
    stop_reason_code: str,
) -> StopReportContract:
    """Fecha a parada anterior quando o fato canônico registra retomada.

    StopReport_1_001 exige início e fim; por isso uma parada ainda aberta não é
    transmitida. O código SX5/44 é parâmetro explícito, nunca inferido do texto.
    """

    if resume_event.resource_divergent:
        raise TotvsContractError(
            "O evento possui divergência de recurso; o outbound não escolherá um vencedor."
        )
    if str(resume_event.previous_state or "").strip().casefold() != "parada":
        raise TotvsContractError(
            "StopReport exige uma retomada cujo evento imediatamente anterior seja parada."
        )
    start = _timestamp(resume_event.previous_event_time, "previous_event_time")
    end = _timestamp(resume_event.event_time, "event_time")
    if start >= end:
        raise TotvsContractError("A retomada deve ocorrer depois do início da parada.")
    message_uuid = _stable_uuid("stopreport-message", resume_event.event_id)
    key = _stable_uuid("stopreport-key", resume_event.event_id)
    return StopReportContract(
        message_uuid=message_uuid,
        idempotency_key=key,
        company_id=_required(resume_event.company_id, "CompanyId"),
        branch_id=_required(resume_event.branch_id, "BranchId"),
        generated_on=end,
        machine_code=_required(resume_event.resource_code, "MachineCode"),
        stop_reason_code=_required(stop_reason_code, "StopReasonCode"),
        start_datetime=start,
        end_datetime=end,
        report_datetime=end,
        operator_code=str(resume_event.operator_code or "").strip() or None,
    )


def _add(parent: ET.Element, name: str, value: object | None) -> ET.Element | None:
    if value is None:
        return None
    node = ET.SubElement(parent, name)
    node.text = str(value)
    return node


def _message_root(
    *,
    transaction: str,
    message_uuid: str,
    company_id: str,
    branch_id: str,
    generated_on: datetime,
    message_version: str,
    standard_version: str,
    identity: TotvsOutboundIdentity,
) -> ET.Element:
    root = ET.Element("TOTVSMessage")
    information = ET.SubElement(root, "MessageInformation", {"version": message_version})
    _add(information, "UUID", message_uuid)
    _add(information, "Type", MESSAGE_TYPE)
    _add(information, "Transaction", transaction)
    _add(information, "StandardVersion", standard_version)
    _add(information, "SourceApplication", identity.source_application)
    _add(information, "CompanyId", company_id)
    _add(information, "BranchId", branch_id)
    ET.SubElement(
        information,
        "Product",
        {"version": identity.product_version, "name": identity.product_name},
    )
    _add(information, "GeneratedOn", _iso(generated_on))
    _add(information, "ContextName", identity.context_name)
    _add(information, "DeliveryType", "Sync")
    return root


def _business_content(root: ET.Element, *, entity: str, key: str) -> ET.Element:
    message = ET.SubElement(root, "BusinessMessage")
    event = ET.SubElement(message, "BusinessEvent")
    _add(event, "Entity", entity)
    identification = ET.SubElement(event, "Identification")
    key_node = ET.SubElement(identification, "key", {"name": "IDPCFactory"})
    key_node.text = key
    _add(event, "Event", "upsert")
    return ET.SubElement(message, "BusinessContent")


def build_production_appointment_xml(
    contract: ProductionAppointmentContract,
    *,
    identity: TotvsOutboundIdentity = TotvsOutboundIdentity(),
) -> TotvsOutboundMessage:
    root = _message_root(
        transaction=PRODUCTION_APPOINTMENT_TRANSACTION,
        message_uuid=contract.message_uuid,
        company_id=contract.company_id,
        branch_id=contract.branch_id,
        generated_on=contract.generated_on,
        message_version="2.000",
        standard_version="2.0",
        identity=identity,
    )
    content = _business_content(
        root, entity=PRODUCTION_APPOINTMENT_TRANSACTION, key=contract.idempotency_key
    )
    _add(content, "MachineCode", contract.machine_code)
    _add(content, "ProductionOrderNumber", contract.production_order_number)
    _add(content, "ActivityID", contract.activity_id)
    _add(content, "ActivityCode", contract.activity_code)
    _add(content, "ItemCode", contract.item_code)
    _add(content, "ReportQuantity", _decimal(contract.report_quantity))
    _add(content, "ApprovedQuantity", _decimal(contract.approved_quantity))
    _add(content, "ScrapQuantity", _decimal(contract.scrap_quantity))
    # O XSD contém o campo, mas o Protheus/MATA681 não possui destino comprovado.
    _add(content, "ReworkQuantity", "0")
    _add(content, "StartReportDateTime", _iso(contract.start_report_datetime))
    _add(content, "EndReportDateTime", _iso(contract.end_report_datetime))
    _add(content, "IsProductionControlReport", "false")
    _add(content, "CQLiberated", "false")
    _add(content, "ReversedReport", "false")
    _add(content, "UpdateReport", "false")
    _add(content, "ReportDateTime", _iso(contract.report_datetime))
    _add(content, "WarehouseCode", contract.warehouse_code)
    _add(content, "CloseOperation", str(contract.close_operation).lower())
    if contract.scrap_quantity:
        wastes = ET.SubElement(content, "ListOfWasteAppointments")
        waste = ET.SubElement(wastes, "WasteAppointment")
        _add(waste, "ReportSequence", "1")
        _add(waste, "WasteCode", contract.waste_code)
        _add(waste, "ScrapQuantity", _decimal(contract.scrap_quantity))
        _add(waste, "ReworkQuantity", "0")
    if contract.operator_code:
        resources = ET.SubElement(content, "ListOfResourceAppointments")
        resource = ET.SubElement(resources, "ResourceAppointment")
        _add(resource, "OperatorCode", contract.operator_code)
    xml = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return TotvsOutboundMessage(
        transaction=PRODUCTION_APPOINTMENT_TRANSACTION,
        idempotency_key=contract.idempotency_key,
        xml='<?xml version="1.0" encoding="UTF-8"?>' + xml,
    )


def build_stop_report_xml(
    contract: StopReportContract,
    *,
    identity: TotvsOutboundIdentity = TotvsOutboundIdentity(),
) -> TotvsOutboundMessage:
    root = _message_root(
        transaction=STOP_REPORT_TRANSACTION,
        message_uuid=contract.message_uuid,
        company_id=contract.company_id,
        branch_id=contract.branch_id,
        generated_on=contract.generated_on,
        message_version="1.001",
        standard_version="1.0",
        identity=identity,
    )
    content = _business_content(root, entity=STOP_REPORT_TRANSACTION, key=contract.idempotency_key)
    _add(content, "MachineCode", contract.machine_code)
    _add(content, "OperatorCode", contract.operator_code)
    _add(content, "ReportDateTime", _iso(contract.report_datetime))
    _add(content, "ReversedReport", "false")
    _add(content, "StartDateTime", _iso(contract.start_datetime))
    _add(content, "EndDateTime", _iso(contract.end_datetime))
    _add(content, "StopReasonCode", contract.stop_reason_code)
    xml = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return TotvsOutboundMessage(
        transaction=STOP_REPORT_TRANSACTION,
        idempotency_key=contract.idempotency_key,
        xml='<?xml version="1.0" encoding="UTF-8"?>' + xml,
    )
