"""TOTVSMessage/ResponseMessage devolvido dentro de `receiveMessageResult`.

Contrato comprovado nos fontes originais do Protheus 12.1.2510:

* `pcpxfun.prx::PCPWebsPPI` é o consumidor real de `receiveMessageResult`, tanto
  no PCPA109 (WhoIs) quanto no PCPA111/MATA650 (SC2/ProductionOrder). Ele faz
  `oTXML:Parse(cReturn)` e só considera sucesso quando
  `/TOTVSMessage/ResponseMessage/ProcessingInformation/Status` == "OK".
  Texto puro ("OK") não passa pelo Parse e vira
  "Não foi possível realizar o parse do XML de retorno do TOTVS MES".
* `WSPCP.prw::getReturn` é o construtor oficial dessa resposta e vale para todas
  as transações: `Type=Response`, `Transaction` = AllTrim(Upper(Transaction
  recebida)), `UUID` recebido repetido em MessageInformation e ReceivedMessage,
  `SentBy` = Product/@name recebido, `Status` = OK/ERROR e `ListOfMessages`
  somente no erro. Não há `ReturnContent` para WhoIs nem para ProductionOrder.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4
from xml.sax.saxutils import escape, quoteattr

from mes.integrations.totvs.models import TotvsMessageMetadata


WHOIS_TRANSACTION = "WhoIs"
RESPONSE_TYPE = "Response"
RESPONSE_MESSAGE_VERSION = "1.000"
DEFAULT_STANDARD_VERSION = "1.0"
STATUS_OK = "OK"
STATUS_ERROR = "ERROR"
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"


@dataclass(frozen=True)
class TotvsGestorIdentity:
    """Identidade própria do Gestor: não se passa por PCFactory, PPI ou WSPCP."""

    source_application: str = "GESTOR_PECAS"
    product_name: str = "GESTOR_PECAS"
    product_version: str = "1.0"
    context_name: str = "GESTOR_PECAS"


DEFAULT_GESTOR_IDENTITY = TotvsGestorIdentity()


def is_whois_transaction(transaction: str | None) -> bool:
    return str(transaction or "").strip().casefold() == WHOIS_TRANSACTION.casefold()


def _element(name: str, value: str | None) -> str:
    if value is None:
        return ""
    return f"<{name}>{escape(str(value))}</{name}>"


def build_response_message(
    metadata: TotvsMessageMetadata,
    *,
    identity: TotvsGestorIdentity = DEFAULT_GESTOR_IDENTITY,
    status: str = STATUS_OK,
    now: datetime | None = None,
    uuid_factory=uuid4,
) -> str:
    """Monta a resposta lida pelo PCPWebsPPI para a mensagem recebida."""

    moment = (now or datetime.now()).replace(microsecond=0).strftime(TIMESTAMP_FORMAT)
    received_uuid = str(metadata.uuid or "").strip()
    # getReturn reaproveita o UUID recebido nos dois pontos; só geramos um
    # quando o Protheus não enviou nenhum.
    correlation_uuid = received_uuid or str(uuid_factory())
    # getReturn: cTransac := AllTrim(Upper(Transaction recebida)).
    transaction = str(metadata.transaction or "").strip().upper()
    # getReturn: cProdName := Product/@name da mensagem recebida.
    sent_by = (
        str(metadata.product_name or "").strip()
        or str(metadata.source_application or "").strip()
    )
    standard_version = (
        str(metadata.standard_version or "").strip() or DEFAULT_STANDARD_VERSION
    )
    company_id = str(metadata.company_id or "").strip() or None
    branch_id = str(metadata.branch_id or "").strip() or None
    product = (
        f"<Product name={quoteattr(identity.product_name)} "
        f"version={quoteattr(identity.product_version)}/>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<TOTVSMessage>"
        f'<MessageInformation version="{RESPONSE_MESSAGE_VERSION}">'
        + _element("UUID", correlation_uuid)
        + _element("Type", RESPONSE_TYPE)
        + _element("Transaction", transaction)
        + _element("StandardVersion", standard_version)
        + _element("SourceApplication", identity.source_application)
        + _element("CompanyId", company_id)
        + _element("BranchId", branch_id)
        + product
        + _element("GeneratedOn", moment)
        + _element("ContextName", identity.context_name)
        + "</MessageInformation>"
        "<ResponseMessage>"
        "<ReceivedMessage>"
        + _element("SentBy", sent_by)
        + _element("UUID", received_uuid or correlation_uuid)
        + "</ReceivedMessage>"
        "<ProcessingInformation>"
        + _element("ProcessedOn", moment)
        + _element("Status", status)
        + "</ProcessingInformation>"
        "</ResponseMessage>"
        "</TOTVSMessage>"
    )
