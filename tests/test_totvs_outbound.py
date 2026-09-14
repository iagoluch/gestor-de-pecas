from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from html import escape
import unittest
from xml.etree import ElementTree as ET

import httpx

from backend.integrations.totvs_wspcp import (
    TotvsWspcpClient,
    WSPCP_SERVICE_NAMESPACE,
    WSPCP_SOAP_ACTION,
    WspcpClientConfig,
    build_wspcp_envelope,
)
from mes.integrations.totvs.errors import TotvsContractError, TotvsIntegrationError
from mes.integrations.totvs.outbound_ack import parse_wspcp_ack
from mes.integrations.totvs.outbound_mapper import (
    build_production_appointment_xml,
    build_stop_report_xml,
    map_production_appointment,
    map_stop_report,
    map_terminal_production_appointment,
    terminal_approved_quantity,
)
from mes.integrations.totvs.outbound_models import (
    CanonicalExecutionEvent,
    CanonicalTerminalMilestone,
)
from mes.integrations.totvs.outbound_service import TotvsOutboundService


NOW = datetime(2026, 8, 31, 12, 30, 0)


def canonical_event(**changes):
    event = CanonicalExecutionEvent(
        event_id=101,
        appointment_id=20,
        state="parcial",
        event_time=NOW,
        production_order="A9717101001",
        operation="10",
        activity_id="159934",
        resource_code="ROBO P",
        item_code="SPCX05001043P",
        item_description="CONJUNTO",
        warehouse_code="00",
        company_id="01",
        branch_id="010004",
        operator_code="1234",
        good_quantity=Decimal("2"),
        scrap_quantity=Decimal("0"),
        rework_quantity=Decimal("0"),
        planned_quantity=Decimal("30"),
        accumulated_good_quantity=Decimal("2"),
        execution_started_at=NOW - timedelta(minutes=15),
        previous_state="producao",
        previous_event_time=NOW - timedelta(minutes=15),
    )
    return replace(event, **changes)


class ProductionAppointmentMapperTests(unittest.TestCase):
    def test_maps_identity_quantities_timestamps_and_resource(self):
        contract = map_production_appointment(canonical_event())
        self.assertEqual(contract.production_order_number, "A9717101001")
        self.assertEqual(contract.activity_id, "159934")
        self.assertEqual(contract.activity_code, "10")
        self.assertEqual(contract.machine_code, "ROBO P")
        self.assertEqual(contract.item_code, "SPCX05001043P")
        self.assertEqual(contract.approved_quantity, Decimal("2"))
        self.assertEqual(contract.report_quantity, Decimal("2"))
        self.assertEqual(contract.start_report_datetime, NOW - timedelta(minutes=15))
        self.assertEqual(contract.end_report_datetime, NOW)
        self.assertFalse(contract.close_operation)

    def test_unknown_activity_id_is_omitted_instead_of_invented(self):
        # A matriz oficial PC-Factory traz "--" para ActivityID no Protheus e o
        # adapter MATI681 lê apenas ActivityCode. Sem o ID vindo do
        # ProductionOrder o Gestor omite o elemento em vez de inventar um id.
        contract = map_production_appointment(canonical_event(activity_id=""))
        self.assertIsNone(contract.activity_id)
        message = build_production_appointment_xml(contract)
        self.assertNotIn("<ActivityID", message.xml)
        self.assertIn("<ActivityCode>10</ActivityCode>", message.xml)

    def test_final_event_closes_operation(self):
        contract = map_production_appointment(
            canonical_event(state="finalizado", good_quantity=Decimal("1"))
        )
        self.assertTrue(contract.close_operation)

    def test_scrap_requires_explicit_totvs_waste_code(self):
        event = canonical_event(good_quantity=Decimal("0"), scrap_quantity=Decimal("1"))
        with self.assertRaisesRegex(TotvsContractError, "waste_code"):
            map_production_appointment(event)
        contract = map_production_appointment(event, waste_code="41")
        self.assertEqual(contract.waste_code, "41")

    def test_rework_is_not_silently_reclassified(self):
        with self.assertRaisesRegex(TotvsContractError, "Retrabalho"):
            map_production_appointment(
                canonical_event(good_quantity=Decimal("0"), rework_quantity=Decimal("1"))
            )

    def test_zero_quantity_needs_homologation_switch(self):
        event = canonical_event(state="producao", good_quantity=Decimal("0"))
        with self.assertRaisesRegex(TotvsContractError, "allow_zero_quantity"):
            map_production_appointment(event)
        contract = map_production_appointment(event, allow_zero_quantity=True)
        self.assertEqual(contract.report_quantity, 0)

    def test_divergent_resource_is_blocked(self):
        with self.assertRaisesRegex(TotvsContractError, "divergência"):
            map_production_appointment(canonical_event(resource_divergent=True))

    def test_xml_contract_and_stable_idempotency_key(self):
        first = map_production_appointment(canonical_event())
        second = map_production_appointment(canonical_event())
        self.assertEqual(first.idempotency_key, second.idempotency_key)
        message = build_production_appointment_xml(first)
        root = ET.fromstring(message.xml)
        values = {node.tag: node.text for node in root.iter()}
        self.assertEqual(values["Transaction"], "productionappointment")
        self.assertEqual(values["ProductionOrderNumber"], "A9717101001")
        self.assertEqual(values["ActivityCode"], "10")
        self.assertEqual(values["ApprovedQuantity"], "2")
        self.assertEqual(values["ScrapQuantity"], "0")
        self.assertEqual(values["StartReportDateTime"], "2026-08-31T12:15:00")
        self.assertEqual(values["EndReportDateTime"], "2026-08-31T12:30:00")
        self.assertEqual(values["CloseOperation"], "false")
        self.assertEqual(values["ReworkQuantity"], "0")
        key = next(node for node in root.iter("key"))
        self.assertEqual(key.attrib["name"], "IDPCFactory")
        self.assertEqual(key.text, first.idempotency_key)


class StopReportMapperTests(unittest.TestCase):
    def test_maps_completed_stop_on_resume(self):
        event = canonical_event(
            event_id=102,
            state="producao",
            good_quantity=Decimal("0"),
            previous_state="parada",
            previous_event_time=NOW - timedelta(minutes=5),
            previous_reason="Aguardando material",
            previous_resource_status_code="PCF-17",
        )
        contract = map_stop_report(event, stop_reason_code="44")
        self.assertEqual(contract.machine_code, "ROBO P")
        self.assertEqual(contract.stop_reason_code, "44")
        self.assertEqual(contract.start_datetime, NOW - timedelta(minutes=5))
        self.assertEqual(contract.end_datetime, NOW)
        message = build_stop_report_xml(contract)
        root = ET.fromstring(message.xml)
        values = {node.tag: node.text for node in root.iter()}
        self.assertEqual(values["Transaction"], "stopreport")
        self.assertEqual(values["StopReasonCode"], "44")
        self.assertNotIn("StopType", values)

    def test_open_stop_or_unmapped_reason_is_blocked(self):
        with self.assertRaises(TotvsContractError):
            map_stop_report(canonical_event(previous_state="producao"), stop_reason_code="44")
        event = canonical_event(
            state="producao",
            previous_state="parada",
            previous_event_time=NOW - timedelta(minutes=1),
        )
        with self.assertRaisesRegex(TotvsContractError, "StopReasonCode"):
            map_stop_report(event, stop_reason_code="")


class WspcpAckTests(unittest.TestCase):
    def _soap(self, inner: str) -> str:
        return (
            '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:wspcp="http://webservices.totvs.com.br/">'
            "<soapenv:Body><wspcp:RECEIVEMESSAGERESPONSE>"
            "<wspcp:RECEIVEMESSAGERESULT>"
            + escape(inner)
            + "</wspcp:RECEIVEMESSAGERESULT></wspcp:RECEIVEMESSAGERESPONSE>"
            "</soapenv:Body></soapenv:Envelope>"
        )

    def test_parses_success_ack_and_internal_id(self):
        inner = (
            "<TOTVSMessage><MessageInformation><Transaction>PRODUCTIONAPPOINTMENT</Transaction>"
            "</MessageInformation><ResponseMessage><ProcessingInformation><Status>OK</Status>"
            "</ProcessingInformation><ReturnContent><ListOfInternalId>"
            '<InternalId Name="PRODUCTIONAPPOINTMENTINTERNALID">987</InternalId>'
            "</ListOfInternalId></ReturnContent></ResponseMessage></TOTVSMessage>"
        )
        ack = parse_wspcp_ack(self._soap(inner))
        self.assertTrue(ack.accepted)
        self.assertEqual(ack.transaction, "PRODUCTIONAPPOINTMENT")
        self.assertEqual(ack.internal_ids, (("PRODUCTIONAPPOINTMENTINTERNALID", "987"),))
        self.assertIn("RECEIVEMESSAGERESULT", ack.raw_soap)

    def test_parses_real_internal_id_with_child_elements(self):
        # Formato realmente devolvido pelo WSPCP TESTE em 01/09/2026, com Name,
        # Origin e Destination como elementos filhos de InternalId.
        inner = (
            "<TOTVSMessage><MessageInformation><Transaction>STOPREPORT</Transaction>"
            "</MessageInformation><ResponseMessage><ProcessingInformation><Status>OK</Status>"
            "</ProcessingInformation><ReturnContent><ListOfInternalId><InternalId>"
            "<Name>STOPREPORTINTERNALID</Name><Origin />"
            "<Destination>783162</Destination>"
            "</InternalId></ListOfInternalId></ReturnContent></ResponseMessage></TOTVSMessage>"
        )
        ack = parse_wspcp_ack(self._soap(inner))
        self.assertTrue(ack.accepted)
        self.assertEqual(ack.transaction, "STOPREPORT")
        self.assertEqual(ack.internal_ids, (("STOPREPORTINTERNALID", "783162"),))

    def test_real_business_rejection_keeps_protheus_message(self):
        # Rejeição funcional real do MATA681 em 01/09/2026 após CloseOperation.
        inner = (
            "<TOTVSMessage><MessageInformation><Transaction>PRODUCTIONAPPOINTMENT</Transaction>"
            "</MessageInformation><ResponseMessage><ProcessingInformation><Status>ERROR</Status>"
            '<ListOfMessages><Message type="ERROR" code="1">AJUDA:A680OPTOT  Capacidade da '
            "Operacao desta OP ja esta totalizada. | Tabela SH6 | Ord.Producao - H6_OP "
            ":=A9717101001 -- Invalido|</Message></ListOfMessages>"
            "</ProcessingInformation></ResponseMessage></TOTVSMessage>"
        )
        ack = parse_wspcp_ack(self._soap(inner))
        self.assertFalse(ack.accepted)
        self.assertFalse(ack.already_processed)
        self.assertTrue(any("A680OPTOT" in message for message in ack.messages))

    def test_duplicate_success_key_is_recognized_without_hiding_error(self):
        inner = (
            "<TOTVSMessage><ResponseMessage><ProcessingInformation><Status>ERROR</Status>"
            "<ListOfMessages><Message><Code>3</Code><Detail>Registro processado</Detail>"
            "</Message></ListOfMessages></ProcessingInformation></ResponseMessage></TOTVSMessage>"
        )
        ack = parse_wspcp_ack(self._soap(inner))
        self.assertFalse(ack.success)
        self.assertTrue(ack.already_processed)
        self.assertTrue(ack.accepted)

    def test_parses_real_wspcp_message_attribute_and_text(self):
        inner = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<TOTVSMessage><MessageInformation><Transaction></Transaction>'
            '</MessageInformation><ResponseMessage><ProcessingInformation>'
            '<Status>ERROR</Status><ListOfMessages>'
            '<Message type="ERROR" code="1">Não foi possível interpretar o arquivo XML. '
            'Document is empty</Message></ListOfMessages>'
            '</ProcessingInformation></ResponseMessage></TOTVSMessage>'
        )
        ack = parse_wspcp_ack(self._soap(inner))
        self.assertFalse(ack.accepted)
        self.assertEqual(ack.status, "ERROR")
        self.assertIsNone(ack.transaction)
        self.assertEqual(
            ack.messages,
            ("1 - Não foi possível interpretar o arquivo XML. Document is empty",),
        )
        self.assertEqual(ack.duplicate_code, 1)

    def test_invalid_payload_fault_and_dtd_are_rejected(self):
        with self.assertRaises(TotvsContractError):
            parse_wspcp_ack("não é XML")
        with self.assertRaises(TotvsContractError):
            parse_wspcp_ack("<!DOCTYPE x><TOTVSMessage/>")
        fault = (
            '<Envelope><Body><Fault><faultstring>Falha controlada</faultstring>'
            "</Fault></Body></Envelope>"
        )
        with self.assertRaisesRegex(TotvsContractError, "Falha controlada"):
            parse_wspcp_ack(fault)


class WspcpGatewayTests(unittest.TestCase):
    def test_envelope_uses_real_wsdl_namespace_cdata_and_cxml(self):
        envelope = build_wspcp_envelope("<TOTVSMessage/>", service_namespace=WSPCP_SERVICE_NAMESPACE)
        self.assertIn("<wspcp:RECEIVEMESSAGE>", envelope)
        self.assertIn("<wspcp:CXML><![CDATA[<TOTVSMessage/>]]>", envelope)
        self.assertIn(f'xmlns:wspcp="{WSPCP_SERVICE_NAMESPACE}"', envelope)

    def test_real_wsdl_action_and_http_status_are_preserved(self):
        inner = (
            "<TOTVSMessage><ResponseMessage><ProcessingInformation>"
            "<Status>OK</Status></ProcessingInformation></ResponseMessage></TOTVSMessage>"
        )
        soap = WspcpAckTests()._soap(inner)

        def handler(request):
            self.assertEqual(request.headers["SOAPAction"], WSPCP_SOAP_ACTION)
            self.assertEqual(request.headers["Content-Type"], "text/xml; charset=utf-8")
            return httpx.Response(200, text=soap)

        client = TotvsWspcpClient(
            WspcpClientConfig(endpoint="https://teste/WSPCP.apw"),
            transport=httpx.MockTransport(handler),
        )
        message = build_production_appointment_xml(map_production_appointment(canonical_event()))
        ack = client.send(message)
        self.assertEqual(ack.http_status, 200)
        self.assertEqual(ack.raw_soap, soap)

    def test_credentials_require_explicit_authentication_mode(self):
        client = TotvsWspcpClient(
            WspcpClientConfig(
                endpoint="https://teste/WSPCP.apw",
                username="usuario",
                password="segredo",
            ),
            transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        )
        message = build_production_appointment_xml(map_production_appointment(canonical_event()))
        with self.assertRaisesRegex(TotvsIntegrationError, "mecanismo"):
            client.send(message)

    def test_basic_auth_is_opt_in_and_configurable(self):
        def handler(request):
            self.assertTrue(request.headers["Authorization"].startswith("Basic "))
            inner = (
                "<TOTVSMessage><ResponseMessage><ProcessingInformation>"
                "<Status>OK</Status></ProcessingInformation></ResponseMessage></TOTVSMessage>"
            )
            return httpx.Response(200, text=WspcpAckTests()._soap(inner))

        client = TotvsWspcpClient(
            WspcpClientConfig(
                endpoint="https://teste/WSPCP.apw",
                authentication_mode="basic",
                username="usuario",
                password="segredo",
            ),
            transport=httpx.MockTransport(handler),
        )
        message = build_production_appointment_xml(map_production_appointment(canonical_event()))
        self.assertTrue(client.send(message).accepted)

    def test_http_error_is_controlled(self):
        transport = httpx.MockTransport(lambda request: httpx.Response(500, text="erro"))
        client = TotvsWspcpClient(
            WspcpClientConfig(
                endpoint="https://teste/WSPCP.apw",
                service_namespace="urn:wspcp-teste",
            ),
            transport=transport,
        )
        message = build_production_appointment_xml(map_production_appointment(canonical_event()))
        with self.assertRaisesRegex(TotvsIntegrationError, "HTTP 500"):
            client.send(message)

    def test_real_authentication_fault_keeps_http_and_fault_detail(self):
        fault = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
            '<SOAP-ENV:Body><SOAP-ENV:Fault><faultcode>Receiver</faultcode>'
            '<faultstring>AUTHENTICATION: USER NOT AUTHORIZED</faultstring>'
            '</SOAP-ENV:Fault></SOAP-ENV:Body></SOAP-ENV:Envelope>'
        )
        client = TotvsWspcpClient(
            WspcpClientConfig(endpoint="https://teste/WSPCP.apw"),
            transport=httpx.MockTransport(lambda request: httpx.Response(500, text=fault)),
        )
        message = build_production_appointment_xml(map_production_appointment(canonical_event()))
        with self.assertRaisesRegex(
            TotvsIntegrationError, "HTTP 500.*AUTHENTICATION: USER NOT AUTHORIZED"
        ):
            client.send(message)


if __name__ == "__main__":
    unittest.main()


def terminal_milestone(**changes):
    """Marco terminal real da OP A9716901001 (99/ALMOX4, ActivityID 128285)."""

    milestone = CanonicalTerminalMilestone(
        production_order="A9716901001",
        item_code="PNT002002003",
        item_description="BRACO ARTICULACAO",
        warehouse_code="01",
        company_id="01",
        branch_id="010004",
        planned_quantity=Decimal("10"),
        terminal_operation="99",
        terminal_resource_code="ALMOX4",
        terminal_activity_id="128285",
        last_operation="20",
        last_operation_good_quantity=Decimal("10"),
        last_operation_scrap_quantity=Decimal("1"),
        last_operation_rework_quantity=Decimal("0"),
        execution_started_at=NOW - timedelta(hours=2),
        execution_finished_at=NOW,
        operator_code="1234",
        pointable_operations=2,
        concluded_operations=2,
    )
    return replace(milestone, **changes)


class _TerminalRepositoryStub:
    def __init__(self, milestone):
        self.milestone = milestone
        self.calls = []

    def buscar_evento_canonico_outbound_totvs(self, evento_id: int):  # pragma: no cover
        raise AssertionError("o marco terminal não lê eventos de operação")

    def buscar_marco_terminal_outbound_totvs(self, codigo_op: str):
        self.calls.append(codigo_op)
        return self.milestone


class TerminalMilestoneMapperTests(unittest.TestCase):
    def test_uses_real_totvs_activity_and_machine_codes(self):
        contract = map_terminal_production_appointment(terminal_milestone())
        self.assertEqual(contract.activity_code, "99")
        self.assertEqual(contract.machine_code, "ALMOX4")
        self.assertEqual(contract.activity_id, "128285")
        self.assertEqual(contract.production_order_number, "A9716901001")
        self.assertTrue(contract.close_operation)

    def test_activity_id_may_be_omitted(self):
        contract = map_terminal_production_appointment(
            terminal_milestone(terminal_activity_id=None)
        )
        self.assertIsNone(contract.activity_id)
        message = build_production_appointment_xml(contract)
        self.assertNotIn("<ActivityID", message.xml)
        self.assertIn("<ActivityCode>99</ActivityCode>", message.xml)
        self.assertIn("<MachineCode>ALMOX4</MachineCode>", message.xml)

    def test_quantity_is_the_good_actually_concluded_not_the_plan(self):
        milestone = terminal_milestone(
            planned_quantity=Decimal("10"),
            last_operation_good_quantity=Decimal("7"),
        )
        self.assertEqual(terminal_approved_quantity(milestone), Decimal("7"))
        contract = map_terminal_production_appointment(milestone)
        self.assertEqual(contract.approved_quantity, Decimal("7"))
        self.assertEqual(contract.report_quantity, Decimal("7"))

    def test_scrap_is_never_counted_as_good(self):
        milestone = terminal_milestone(
            last_operation_good_quantity=Decimal("6"),
            last_operation_scrap_quantity=Decimal("4"),
        )
        contract = map_terminal_production_appointment(milestone)
        self.assertEqual(contract.approved_quantity, Decimal("6"))
        self.assertEqual(contract.scrap_quantity, Decimal("0"))

    def test_rework_blocks_the_terminal_like_the_regular_appointment(self):
        milestone = terminal_milestone(last_operation_rework_quantity=Decimal("1"))
        with self.assertRaisesRegex(TotvsContractError, "Retrabalho"):
            map_terminal_production_appointment(milestone)

    def test_open_operation_does_not_trigger_the_terminal(self):
        milestone = terminal_milestone(
            concluded_operations=1, open_operations=("20",)
        )
        self.assertFalse(milestone.execution_completed)
        with self.assertRaisesRegex(TotvsContractError, "operações ainda em aberto"):
            map_terminal_production_appointment(milestone)

    def test_ingestion_alone_does_not_trigger_the_terminal(self):
        # Roteiro recém-recebido: nenhuma operação concluída ainda.
        milestone = terminal_milestone(
            pointable_operations=2,
            concluded_operations=0,
            open_operations=("10", "20"),
            last_operation_good_quantity=Decimal("0"),
            execution_started_at=None,
            execution_finished_at=None,
        )
        self.assertFalse(milestone.execution_completed)
        with self.assertRaises(TotvsContractError):
            map_terminal_production_appointment(milestone)

    def test_zero_good_quantity_is_not_emitted(self):
        milestone = terminal_milestone(last_operation_good_quantity=Decimal("0"))
        with self.assertRaisesRegex(TotvsContractError, "maior que zero"):
            map_terminal_production_appointment(milestone)

    def test_good_above_plan_is_refused_instead_of_being_capped(self):
        milestone = terminal_milestone(last_operation_good_quantity=Decimal("31"))
        with self.assertRaisesRegex(TotvsContractError, "maior que a planejada"):
            map_terminal_production_appointment(milestone)

    def test_reprocessing_keeps_the_same_idempotency_key(self):
        first = map_terminal_production_appointment(terminal_milestone())
        second = map_terminal_production_appointment(
            terminal_milestone(execution_finished_at=NOW + timedelta(minutes=5))
        )
        self.assertEqual(first.idempotency_key, second.idempotency_key)
        self.assertEqual(first.message_uuid, second.message_uuid)
        regular = map_production_appointment(canonical_event())
        self.assertNotEqual(first.idempotency_key, regular.idempotency_key)

    def test_divergent_resource_blocks_the_terminal(self):
        with self.assertRaisesRegex(TotvsContractError, "divergência de recurso"):
            map_terminal_production_appointment(
                terminal_milestone(resource_divergent=True)
            )

    def test_service_builds_the_terminal_message_from_the_read_model(self):
        repository = _TerminalRepositoryStub(terminal_milestone())
        service = TotvsOutboundService(repository)
        milestone, message = service.build_terminal_production_appointment("A9716901001")
        self.assertEqual(repository.calls, ["A9716901001"])
        self.assertEqual(milestone.terminal_operation, "99")
        self.assertEqual(message.transaction, "productionappointment")
        self.assertIn("<CloseOperation>true</CloseOperation>", message.xml)
        self.assertIn("<ApprovedQuantity>10</ApprovedQuantity>", message.xml)

    def test_service_refuses_op_without_terminal_milestone(self):
        service = TotvsOutboundService(_TerminalRepositoryStub(None))
        with self.assertRaisesRegex(TotvsContractError, "marco terminal"):
            service.build_terminal_production_appointment("SEM-TERMINAL")
