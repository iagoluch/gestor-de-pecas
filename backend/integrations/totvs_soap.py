"""Porta SOAP 1.1 compatível com PcfIntegService.receiveMessage."""

from __future__ import annotations

import asyncio
import logging
from xml.etree.ElementTree import ParseError  # nosec B405 -- só o tipo de exceção; parse real usa defusedxml (SafeElementTree) abaixo
from xml.sax.saxutils import escape  # nosec B406 -- só escape() de string, não faz parse de XML

from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException
from fastapi import APIRouter, Request
from fastapi.responses import Response

from mes.integrations.totvs.errors import TotvsIntegrationError


SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
SERVICE_NS = "http://tempuri.org/"
RECEIVE_ACTION = "http://tempuri.org/EAIService/receiveMessage"
router = APIRouter(tags=["TOTVS SOAP"])

#: Valores de ``GESTOR_WEB_PUBLIC_HOST`` que descrevem a própria máquina ou a
#: rede da fábrica. Enquanto o host público for um deles, não existe publicação
#: externa e a porta do ERP segue acessível exatamente como sempre.
_INTERNAL_PUBLIC_HOSTS = frozenset(
    {"gestor-peca", "localhost", "testserver", "127.0.0.1", "::1"}
)


def _arrived_through_public_host(request: Request) -> bool:
    """A requisição entrou pelo hostname publicado na internet?

    Este receptor não é autenticado — é o contrato do EAI do Protheus, que fala
    com o Gestor pela rede interna da fábrica. Quando o sistema é publicado por
    um túnel (``iniciar_sistema_teste_cloudflare.py`` grava o hostname em
    ``GESTOR_WEB_PUBLIC_HOST`` e o acrescenta a ``GESTOR_WEB_ALLOWED_HOSTS``), o
    mesmo endpoint passaria a aceitar ``ProductionOrder`` de qualquer um que
    descobrisse a URL — gravando OP no banco sem credencial alguma. A porta do
    ERP, portanto, existe apenas no caminho interno.
    """

    settings = request.app.state.settings
    public_host = str(getattr(settings, "public_host", "") or "").strip().casefold()
    if not public_host or public_host in _INTERNAL_PUBLIC_HOSTS:
        return False
    return str(request.url.hostname or "").strip().casefold() == public_host


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _namespace(tag: str) -> str:
    value = str(tag)
    return value[1:].split("}", 1)[0] if value.startswith("{") else ""


def _xml_response(content: str, *, status_code: int = 200) -> Response:
    return Response(
        content=content.encode("utf-8"),
        status_code=status_code,
        media_type="text/xml; charset=utf-8",
    )


def _fault(code: str, message: str, *, status_code: int = 500) -> Response:
    safe_code = escape(str(code or "soap_error"))
    safe_message = escape(str(message or "Falha SOAP."))
    return _xml_response(
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>"
        f"<soap:Envelope xmlns:soap=\"{SOAP_ENV}\">"
        "<soap:Body><soap:Fault>"
        "<faultcode>soap:Server</faultcode>"
        f"<faultstring>{safe_message}</faultstring>"
        f"<detail><code>{safe_code}</code></detail>"
        "</soap:Fault></soap:Body></soap:Envelope>",
        status_code=status_code,
    )


def _extract_business_xml(body: bytes) -> str:
    lowered = body.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValueError("DTD e entidades não são permitidos no envelope SOAP.")
    try:
        root = SafeElementTree.fromstring(body)
    except (ParseError, DefusedXmlException) as exc:
        raise ValueError("Envelope SOAP malformado ou inseguro.") from exc
    if _local_name(root.tag) != "Envelope" or _namespace(root.tag) != SOAP_ENV:
        raise ValueError("Envelope SOAP 1.1 inválido.")
    body_node = next(
        (
            child
            for child in list(root)
            if _local_name(child.tag) == "Body" and _namespace(child.tag) == SOAP_ENV
        ),
        None,
    )
    if body_node is None or len(list(body_node)) != 1:
        raise ValueError("SOAP Body deve conter exatamente uma operação.")
    operation = list(body_node)[0]
    if _local_name(operation.tag) != "receiveMessage" or _namespace(operation.tag) != SERVICE_NS:
        raise ValueError("Operação SOAP não suportada.")
    parameters = [child for child in list(operation) if _local_name(child.tag) == "pXmlDocument"]
    if len(parameters) != 1 or list(parameters[0]):
        raise ValueError("Parâmetro pXmlDocument ausente ou inválido.")
    payload = parameters[0].text
    if payload is None or not payload.strip():
        raise ValueError("Parâmetro pXmlDocument ausente ou vazio.")
    return payload


def _process_business_xml(state, business_xml: str):
    database = state.database_manager.get()
    service = state.totvs_service_factory(database)
    return service.handle_message(business_xml)


async def _read_limited_body(request: Request, maximum: int) -> bytes | None:
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > maximum:
            return None
    return bytes(content)


def _wsdl(address: str) -> str:
    safe_address = escape(address, {'"': "&quot;"})
    return (
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>"
        "<wsdl:definitions name=\"EAIServiceClass\" targetNamespace=\"http://tempuri.org/\" "
        "xmlns:wsdl=\"http://schemas.xmlsoap.org/wsdl/\" "
        "xmlns:xs=\"http://www.w3.org/2001/XMLSchema\" "
        "xmlns:soap=\"http://schemas.xmlsoap.org/wsdl/soap/\" "
        "xmlns:tns=\"http://tempuri.org/\">"
        "<wsdl:types><xs:schema elementFormDefault=\"qualified\" targetNamespace=\"http://tempuri.org/\">"
        "<xs:element name=\"receiveMessage\"><xs:complexType><xs:sequence>"
        "<xs:element minOccurs=\"0\" name=\"pXmlDocument\" nillable=\"true\" type=\"xs:string\"/>"
        "</xs:sequence></xs:complexType></xs:element>"
        "<xs:element name=\"receiveMessageResponse\"><xs:complexType><xs:sequence>"
        "<xs:element minOccurs=\"0\" name=\"receiveMessageResult\" nillable=\"true\" type=\"xs:string\"/>"
        "</xs:sequence></xs:complexType></xs:element>"
        "</xs:schema></wsdl:types>"
        "<wsdl:message name=\"EAIService_receiveMessage_InputMessage\"><wsdl:part name=\"parameters\" element=\"tns:receiveMessage\"/></wsdl:message>"
        "<wsdl:message name=\"EAIService_receiveMessage_OutputMessage\"><wsdl:part name=\"parameters\" element=\"tns:receiveMessageResponse\"/></wsdl:message>"
        "<wsdl:portType name=\"EAIService\"><wsdl:operation name=\"receiveMessage\">"
        "<wsdl:input message=\"tns:EAIService_receiveMessage_InputMessage\"/>"
        "<wsdl:output message=\"tns:EAIService_receiveMessage_OutputMessage\"/>"
        "</wsdl:operation></wsdl:portType>"
        "<wsdl:binding name=\"EAIServicePortBinding_EAIService\" type=\"tns:EAIService\">"
        "<soap:binding transport=\"http://schemas.xmlsoap.org/soap/http\"/>"
        "<wsdl:operation name=\"receiveMessage\">"
        f"<soap:operation soapAction=\"{RECEIVE_ACTION}\" style=\"document\"/>"
        "<wsdl:input><soap:body use=\"literal\"/></wsdl:input>"
        "<wsdl:output><soap:body use=\"literal\"/></wsdl:output>"
        "</wsdl:operation></wsdl:binding>"
        "<wsdl:service name=\"EAIServiceClass\"><wsdl:port name=\"EAIServicePortBinding_EAIService\" binding=\"tns:EAIServicePortBinding_EAIService\">"
        f"<soap:address location=\"{safe_address}\"/>"
        "</wsdl:port></wsdl:service></wsdl:definitions>"
    )


@router.get("/PcfIntegService")
def get_wsdl(request: Request):
    settings = request.app.state.settings
    if not settings.totvs_soap_enabled:
        return _fault(
            "totvs_soap_disabled",
            "Receptor SOAP TOTVS desabilitado por configuração.",
            status_code=503,
        )
    if _arrived_through_public_host(request):
        return _fault(
            "totvs_soap_internal_only",
            "O receptor TOTVS responde somente na rede interna.",
            status_code=403,
        )
    address = str(request.base_url).rstrip("/") + "/PcfIntegService"
    return _xml_response(_wsdl(address))


@router.post("/PcfIntegService")
async def receive_message(request: Request):
    settings = request.app.state.settings
    if not settings.totvs_soap_enabled:
        return _fault(
            "totvs_soap_disabled",
            "Receptor SOAP TOTVS desabilitado por configuração.",
            status_code=503,
        )
    # Antes de qualquer leitura de corpo: mensagem vinda do túnel não é do ERP.
    if _arrived_through_public_host(request):
        return _fault(
            "totvs_soap_internal_only",
            "O receptor TOTVS responde somente na rede interna.",
            status_code=403,
        )
    action = str(request.headers.get("SOAPAction") or "").strip().strip('"')
    if action != RECEIVE_ACTION:
        return _fault("invalid_soap_action", "SOAPAction não suportado.")
    max_soap_bytes = settings.totvs_max_xml_bytes * 5 + 16_384
    body = await _read_limited_body(request, max_soap_bytes)
    if body is None:
        return _fault("soap_payload_too_large", "Envelope SOAP excede o limite configurado.")
    try:
        business_xml = _extract_business_xml(body)
        if len(business_xml.encode("utf-8")) > settings.totvs_max_xml_bytes:
            return _fault("payload_too_large", "pXmlDocument excede o limite configurado.")
        # Banco e processamento são bloqueantes: rodam fora do event loop, numa
        # única thread, como qualquer rota síncrona do FastAPI.
        outcome = await asyncio.to_thread(_process_business_xml, request.app.state, business_xml)
    except ValueError as exc:
        return _fault("invalid_soap_envelope", str(exc))
    except TotvsIntegrationError as exc:
        return _fault(exc.code, str(exc))
    except Exception:
        logging.exception("Falha não prevista no receptor SOAP TOTVS.")
        return _fault("totvs_processing_error", "Falha interna ao processar a mensagem TOTVS.")

    # Mensagens suportadas (WhoIs e ProductionOrder) devolvem o TOTVSMessage/ResponseMessage
    # produzido pelo serviço. O valor configurado permanece apenas como fallback de compatibilidade.
    result = escape(
        outcome.soap_result
        if outcome.soap_result is not None
        else settings.totvs_soap_success_result
    )
    return _xml_response(
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>"
        f"<soap:Envelope xmlns:soap=\"{SOAP_ENV}\">"
        f"<soap:Body><receiveMessageResponse xmlns=\"{SERVICE_NS}\">"
        f"<receiveMessageResult>{result}</receiveMessageResult>"
        "</receiveMessageResponse></soap:Body></soap:Envelope>"
    )
