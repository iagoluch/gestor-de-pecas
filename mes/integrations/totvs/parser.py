"""Parser seguro e namespace-agnostic do XML de negócio TOTVSMessage."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import ParseError  # nosec B405 -- só o tipo de exceção; parse real usa defusedxml (SafeElementTree) abaixo

from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException

from mes.integrations.totvs.errors import (
    TotvsContractError,
    TotvsIdentityConflictError,
    TotvsPayloadTooLargeError,
    TotvsUnsupportedMessageError,
    TotvsXmlParseError,
    TotvsXmlSecurityError,
)
from mes.integrations.totvs.models import (
    ProductionOrderMessage,
    TotvsActivityOrder,
    TotvsBusinessEvent,
    TotvsMaterialOrder,
    TotvsMessageMetadata,
    TotvsProductionOrder,
    TotvsWhoIsMessage,
)
from mes.integrations.totvs.response import is_whois_transaction


DEFAULT_MAX_XML_BYTES = 1_048_576


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _child(parent, name: str):
    if parent is None:
        return None
    for item in list(parent):
        if _local_name(item.tag) == name:
            return item
    return None


def _children(parent, name: str):
    if parent is None:
        return ()
    return tuple(item for item in list(parent) if _local_name(item.tag) == name)


def _text(parent, name: str) -> str | None:
    item = _child(parent, name)
    if item is None or item.text is None:
        return None
    value = item.text.strip()
    return value or None


def _attribute(element, name: str) -> str | None:
    if element is None:
        return None
    return str(element.attrib.get(name) or "").strip() or None


def _decimal(value: str | None, field: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise TotvsContractError(f"Campo numérico inválido: {field}.") from exc


def _datetime(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    candidate = value.strip()
    try:
        if len(candidate) == 8 and candidate.isdigit():
            parsed_date = datetime.strptime(candidate, "%Y%m%d").date()
            return datetime.combine(parsed_date, datetime.min.time())
        return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TotvsContractError(f"Data/hora inválida: {field}.") from exc


def _date(value: str | None, field: str) -> date | None:
    parsed = _datetime(value, field)
    return parsed.date() if parsed is not None else None


def _boolean(value: str | None, field: str) -> bool | None:
    if value is None:
        return None
    normalized = value.casefold()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise TotvsContractError(f"Booleano inválido: {field}.")


class TotvsMessageParser:
    """Converte XML não confiável em DTOs, sem acesso a banco ou HTTP."""

    def __init__(self, *, max_xml_bytes: int = DEFAULT_MAX_XML_BYTES):
        if max_xml_bytes <= 0:
            raise ValueError("max_xml_bytes deve ser positivo.")
        self.max_xml_bytes = int(max_xml_bytes)

    def payload_bytes(self, payload: str | bytes) -> bytes:
        if isinstance(payload, str):
            raw = payload.encode("utf-8")
        elif isinstance(payload, bytes):
            raw = payload
        else:
            raise TotvsXmlParseError("O payload TOTVS deve ser texto ou bytes UTF-8.")
        if len(raw) > self.max_xml_bytes:
            raise TotvsPayloadTooLargeError(
                f"XML TOTVS excede o limite de {self.max_xml_bytes} bytes."
            )
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise TotvsXmlParseError("O XML TOTVS deve usar UTF-8 válido.") from exc
        return raw

    def _secure_root(self, payload: str | bytes):
        raw = self.payload_bytes(payload)
        lowered = raw.lower()
        if b"<!doctype" in lowered or b"<!entity" in lowered:
            raise TotvsXmlSecurityError("DTD e entidades não são permitidos no XML TOTVS.")
        try:
            root = SafeElementTree.fromstring(raw)
        except DefusedXmlException as exc:
            raise TotvsXmlSecurityError("Construção XML insegura recusada.") from exc
        except ParseError as exc:
            raise TotvsXmlParseError("XML TOTVS malformado.") from exc
        if _local_name(root.tag) != "TOTVSMessage":
            raise TotvsContractError("Elemento raiz TOTVSMessage ausente.")
        return root, raw

    @staticmethod
    def _metadata(root, information) -> TotvsMessageMetadata:
        product = _child(information, "Product")
        return TotvsMessageMetadata(
            uuid=_text(information, "UUID"),
            message_type=_text(information, "Type"),
            transaction=_text(information, "Transaction") or "",
            standard_version=_text(information, "StandardVersion"),
            source_application=_text(information, "SourceApplication"),
            company_id=_text(information, "CompanyId"),
            branch_id=_text(information, "BranchId"),
            user_id=_text(information, "UserId"),
            generated_on=_datetime(_text(information, "GeneratedOn"), "GeneratedOn"),
            context_name=_text(information, "ContextName"),
            delivery_type=_text(information, "DeliveryType"),
            message_version=str(information.attrib.get("version") or "").strip() or None,
            schema_location=next(
                (
                    str(value).strip()
                    for key, value in root.attrib.items()
                    if _local_name(key) == "noNamespaceSchemaLocation" and str(value).strip()
                ),
                None,
            ),
            product_name=_attribute(product, "name"),
            product_version=_attribute(product, "version"),
        )

    def read_metadata(self, payload: str | bytes) -> TotvsMessageMetadata:
        """Lê só o MessageInformation, para roteamento e para montar a resposta."""

        root, _ = self._secure_root(payload)
        information = _child(root, "MessageInformation")
        if information is None:
            raise TotvsContractError("Estrutura obrigatória do TOTVSMessage está incompleta.")
        return self._metadata(root, information)

    def parse_whois(self, payload: str | bytes) -> TotvsWhoIsMessage:
        """Interpreta o WhoIs de diagnóstico; nenhum dado de negócio é extraído."""

        root, raw = self._secure_root(payload)
        information = _child(root, "MessageInformation")
        if information is None:
            raise TotvsContractError("Estrutura obrigatória do TOTVSMessage está incompleta.")
        metadata = self._metadata(root, information)
        if not is_whois_transaction(metadata.transaction):
            raise TotvsUnsupportedMessageError(
                f"Transaction não suportada: {metadata.transaction or '<vazia>'}."
            )
        business_event = _child(_child(root, "BusinessMessage"), "BusinessEvent")
        identification = _child(business_event, "Identification")
        keys = []
        for item in _children(identification, "key"):
            name = str(item.attrib.get("name") or "").strip()
            if name:
                keys.append((name, str(item.text or "").strip()))
        return TotvsWhoIsMessage(
            metadata=metadata,
            identification=tuple(keys),
            raw_xml=raw.decode("utf-8"),
        )

    def parse(self, payload: str | bytes) -> ProductionOrderMessage:
        root, raw = self._secure_root(payload)
        information = _child(root, "MessageInformation")
        business_message = _child(root, "BusinessMessage")
        business_event = _child(business_message, "BusinessEvent")
        business_content = _child(business_message, "BusinessContent")
        if information is None or business_event is None or business_content is None:
            raise TotvsContractError("Estrutura obrigatória do TOTVSMessage está incompleta.")

        metadata = self._metadata(root, information)
        identification = _child(business_event, "Identification")
        internal_id = None
        for key in _children(identification, "key"):
            if str(key.attrib.get("name") or "").strip() == "InternalID":
                internal_id = str(key.text or "").strip() or None
                break
        event = TotvsBusinessEvent(
            entity=_text(business_event, "Entity") or "",
            event=_text(business_event, "Event") or "",
            internal_id=internal_id,
        )
        self._validate_supported_message(metadata, event)

        unique_id = _text(business_content, "ProductionOrderUniqueID")
        if unique_id and internal_id and unique_id != internal_id:
            raise TotvsIdentityConflictError(
                "ProductionOrderUniqueID diverge do InternalID informado pelo TOTVS."
            )
        if not unique_id and not internal_id:
            raise TotvsContractError("Identificador corporativo da ProductionOrder ausente.")

        number = _text(business_content, "Number")
        item_code = _text(business_content, "ItemCode")
        item_description = _text(business_content, "ItemDescription")
        quantity = _decimal(_text(business_content, "Quantity"), "Quantity")
        if not number or not item_code or not item_description or quantity is None:
            raise TotvsContractError("Cabeçalho obrigatório da ProductionOrder está incompleto.")

        activity_list = _child(business_content, "ListOfActivityOrders")
        activities = tuple(
            self._parse_activity(item)
            for item in _children(activity_list, "ActivityOrder")
        )
        material_list = _child(business_content, "ListOfMaterialOrders")
        materials = tuple(
            self._parse_material(item)
            for item in _children(material_list, "MaterialOrder")
        )
        order = TotvsProductionOrder(
            number=number,
            production_order_unique_id=unique_id,
            item_code=item_code,
            item_description=item_description,
            order_type=_text(business_content, "Type"),
            quantity=quantity,
            report_quantity=_decimal(
                _text(business_content, "ReportQuantity"), "ReportQuantity"
            ),
            unit_of_measure_code=_text(business_content, "UnitOfMeasureCode"),
            warehouse_code=_text(business_content, "WarehouseCode"),
            status_order_type=_text(business_content, "StatusOrderType"),
            report_order_type=_text(business_content, "ReportOrderType"),
            release_order_date=_datetime(
                _text(business_content, "ReleaseOrderDate"), "ReleaseOrderDate"
            ),
            start_order_date_time=_datetime(
                _text(business_content, "StartOrderDateTime"), "StartOrderDateTime"
            ),
            end_order_date_time=_datetime(
                _text(business_content, "EndOrderDateTime"), "EndOrderDateTime"
            ),
            script_code=_text(business_content, "ScriptCode"),
            priority=_text(business_content, "Priority"),
            activities=activities,
            materials=materials,
        )
        return ProductionOrderMessage(
            metadata=metadata,
            event=event,
            production_order=order,
            raw_xml=raw.decode("utf-8"),
        )

    @staticmethod
    def _validate_supported_message(
        metadata: TotvsMessageMetadata,
        event: TotvsBusinessEvent,
    ) -> None:
        if metadata.transaction.casefold() != "productionorder":
            raise TotvsUnsupportedMessageError(
                f"Transaction não suportada: {metadata.transaction or '<vazia>'}."
            )
        if event.entity.casefold() != "productionorder":
            raise TotvsUnsupportedMessageError(
                f"Entity não suportada: {event.entity or '<vazia>'}."
            )
        if event.event.casefold() != "upsert":
            raise TotvsUnsupportedMessageError(
                f"Event não suportado: {event.event or '<vazio>'}."
            )

    @staticmethod
    def _parse_activity(item) -> TotvsActivityOrder:
        return TotvsActivityOrder(
            production_order_number=_text(item, "ProductionOrderNumber"),
            activity_id=_text(item, "ActivityID"),
            activity_code=_text(item, "ActivityCode"),
            activity_description=_text(item, "ActivityDescription"),
            split=_text(item, "Split"),
            item_code=_text(item, "ItemCode"),
            item_description=_text(item, "ItemDescription"),
            activity_type=_text(item, "ActivityType"),
            work_center_code=_text(item, "WorkCenterCode"),
            work_center_description=_text(item, "WorkCenterDescription"),
            unit_time_type=_text(item, "UnitTimeType"),
            time_resource=_decimal(_text(item, "TimeResource"), "ActivityOrder.TimeResource"),
            time_machine=_decimal(_text(item, "TimeMachine"), "ActivityOrder.TimeMachine"),
            time_setup=_decimal(_text(item, "TimeSetup"), "ActivityOrder.TimeSetup"),
            script_code=_text(item, "ScriptCode"),
            resource_quantity=_decimal(
                _text(item, "ResourceQuantity"), "ActivityOrder.ResourceQuantity"
            ),
            production_quantity=_decimal(
                _text(item, "ProductionQuantity"), "ActivityOrder.ProductionQuantity"
            ),
            activity_quantity=_decimal(
                _text(item, "ActivityQuantity"), "ActivityOrder.ActivityQuantity"
            ),
            unit_activity_code=_text(item, "UnitActivityCode"),
            machine_code=_text(item, "MachineCode"),
            start_plan_date_time=_datetime(
                _text(item, "StartPlanDateTime"), "ActivityOrder.StartPlanDateTime"
            ),
            end_plan_date_time=_datetime(
                _text(item, "EndPlanDateTime"), "ActivityOrder.EndPlanDateTime"
            ),
            is_activity_start=_boolean(
                _text(item, "IsActivityStart"), "ActivityOrder.IsActivityStart"
            ),
            is_activity_end=_boolean(
                _text(item, "IsActivityEnd"), "ActivityOrder.IsActivityEnd"
            ),
            time_mod=_decimal(_text(item, "TimeMOD"), "ActivityOrder.TimeMOD"),
            time_ind_mes=_decimal(_text(item, "TimeIndMES"), "ActivityOrder.TimeIndMES"),
        )

    @staticmethod
    def _parse_material(item) -> TotvsMaterialOrder:
        return TotvsMaterialOrder(
            material_id=_text(item, "MaterialID"),
            material_code=_text(item, "MaterialCode"),
            material_description=_text(item, "MaterialDescription"),
            activity_code=_text(item, "ActivityCode"),
            warehouse_code=_text(item, "WarehouseCode"),
            material_date=_date(_text(item, "MaterialDate"), "MaterialOrder.MaterialDate"),
            material_quantity=_decimal(
                _text(item, "MaterialQuantity"), "MaterialOrder.MaterialQuantity"
            ),
            request_type=_text(item, "RequestType"),
        )

