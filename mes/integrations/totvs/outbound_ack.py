"""Parser endurecido do SOAP e TOTVSMessage/ResponseMessage do WSPCP."""

from __future__ import annotations

from html import unescape
import re

from defusedxml import ElementTree as SafeET

from mes.integrations.totvs.errors import TotvsContractError
from mes.integrations.totvs.outbound_models import TotvsOutboundAck


_FORBIDDEN_XML = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1].casefold()


def _nodes(root, name: str):
    expected = name.casefold()
    return [node for node in root.iter() if _local_name(node.tag) == expected]


def _first_text(root, name: str) -> str | None:
    for node in _nodes(root, name):
        text = "".join(node.itertext()).strip()
        if text:
            return text
    return None


def _parse_xml(raw: str, *, label: str):
    text = str(raw or "").strip()
    if not text:
        raise TotvsContractError(f"{label} vazio retornado pelo TOTVS.")
    if _FORBIDDEN_XML.search(text):
        raise TotvsContractError(f"{label} contém DTD/ENTITY proibido.")
    try:
        return SafeET.fromstring(text)
    except Exception as exc:
        raise TotvsContractError(f"{label} inválido retornado pelo TOTVS.") from exc


def parse_wspcp_ack(raw_response: str) -> TotvsOutboundAck:
    outer = _parse_xml(raw_response, label="SOAP")
    faults = _nodes(outer, "Fault")
    if faults:
        detail = _first_text(faults[0], "faultstring") or "SOAP Fault sem detalhe."
        raise TotvsContractError(f"WSPCP retornou SOAP Fault: {detail}")

    if _local_name(outer.tag) == "totvsmessage":
        response_xml = str(raw_response).strip()
        response_root = outer
    else:
        # Nome/case publicado no WSDL TESTE: RECEIVEMESSAGERESULT. A busca por
        # local-name continua tolerante a prefixos XML, nunca ao contrato.
        result_nodes = _nodes(outer, "RECEIVEMESSAGERESULT")
        if not result_nodes:
            raise TotvsContractError("SOAP do WSPCP não contém ReceiveMessageResult.")
        result = result_nodes[0]
        direct = next((node for node in list(result) if _local_name(node.tag) == "totvsmessage"), None)
        if direct is not None:
            response_root = direct
            response_xml = SafeET.tostring(direct, encoding="unicode")
        else:
            response_xml = unescape("".join(result.itertext()).strip())
            response_root = _parse_xml(response_xml, label="TOTVSMessage/ResponseMessage")

    if _local_name(response_root.tag) != "totvsmessage":
        raise TotvsContractError("ReceiveMessageResult não contém TOTVSMessage.")
    status = _first_text(response_root, "Status")
    if not status:
        raise TotvsContractError("ACK TOTVS não contém ProcessingInformation/Status.")
    transaction = _first_text(response_root, "Transaction")
    messages: list[str] = []
    duplicate_code = None
    for node in _nodes(response_root, "Message"):
        # O WSPCP TESTE publica erros também como
        # <Message type="ERROR" code="1">texto</Message>, sem filhos
        # Code/Detail. Preservamos ambos os formatos comprovados.
        code = _first_text(node, "Code") or node.attrib.get("code") or node.attrib.get("Code")
        detail = _first_text(node, "Detail") or _first_text(node, "Description")
        if not detail:
            detail = "".join(node.itertext()).strip() or None
        combined = " - ".join(part for part in (code, detail) if part)
        if combined:
            messages.append(combined)
        if code and str(code).strip().isdigit() and int(code) in {1, 2, 3, 4}:
            duplicate_code = int(code)
    internal_ids: list[tuple[str | None, str]] = []
    for node in _nodes(response_root, "InternalId"):
        # Formato real do WSPCP TESTE: <InternalId><Name>..</Name><Origin/>
        # <Destination>783162</Destination></InternalId>. O formato compacto
        # com Name em atributo e o id no texto também é preservado.
        name = _first_text(node, "Name") or node.attrib.get("Name") or node.attrib.get("name")
        value = _first_text(node, "Destination") or _first_text(node, "Origin")
        if value is None:
            value = "".join(node.itertext()).strip()
        if value:
            internal_ids.append((name, value))
    return TotvsOutboundAck(
        status=status.strip().upper(),
        transaction=transaction,
        messages=tuple(messages),
        internal_ids=tuple(internal_ids),
        raw_xml=response_xml,
        duplicate_code=duplicate_code,
        raw_soap=None if response_root is outer else str(raw_response).strip(),
    )
