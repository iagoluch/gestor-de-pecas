"""Homologação controlada do receptor SOAP TOTVS em ambiente de TESTE.

O script não altera configuração do Protheus. Ele consulta o WSDL do Gestor e,
mediante confirmação explícita, envia um fixture ProductionOrder ou WhoIs para o
endpoint informado e valida HTTP 200 + receiveMessageResult.

O critério é o mesmo aplicado por `pcpxfun.prx::PCPWebsPPI` no PCPA109 e no
PCPA111: o retorno precisa ser um XML com
/TOTVSMessage/ResponseMessage/ProcessingInformation/Status = OK.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape


SOAP_ACTION = "http://tempuri.org/EAIService/receiveMessage"
SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"
SERVICE_NS = "http://tempuri.org/"


def _endpoint(value: str) -> str:
    value = str(value or "").strip().rstrip("/")
    if not value:
        raise ValueError("Endpoint vazio.")
    if value.endswith("/PcfIntegService"):
        return value
    return value + "/PcfIntegService"


def _read(url: str, *, method: str = "GET", body: bytes | None = None, headers=None) -> tuple[int, bytes]:
    request = Request(url, data=body, method=method, headers=headers or {})
    try:
        with urlopen(request, timeout=15) as response:
            return int(response.status), response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:800]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Falha de rede ao acessar {url}: {exc.reason}") from exc


def _soap_envelope(payload: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<soap:Envelope xmlns:soap="{SOAP_ENV}">'
        f'<soap:Body><receiveMessage xmlns="{SERVICE_NS}">'
        f"<pXmlDocument>{escape(payload)}</pXmlDocument>"
        "</receiveMessage></soap:Body></soap:Envelope>"
    ).encode("utf-8")


def _receive_result(response: bytes) -> str:
    root = ET.fromstring(response)
    for node in root.iter():
        if str(node.tag).rsplit("}", 1)[-1] == "receiveMessageResult":
            return str(node.text or "")
    raise RuntimeError("receiveMessageResult não encontrado na resposta SOAP.")


def _transaction(payload: str) -> str:
    root = ET.fromstring(payload)
    for node in root.iter():
        if str(node.tag).rsplit("}", 1)[-1] == "Transaction":
            return str(node.text or "").strip()
    return ""


def _processing_status(result: str) -> str:
    """Reproduz a leitura do PCPWebsPPI sobre o receiveMessageResult."""

    try:
        root = ET.fromstring(result)
    except ET.ParseError as exc:
        raise RuntimeError(
            "receiveMessageResult não é XML; o Protheus registraria "
            "'Não foi possível realizar o parse do XML de retorno do TOTVS MES'."
        ) from exc
    status = root.findtext("ResponseMessage/ProcessingInformation/Status")
    if status is None:
        raise RuntimeError(
            "ResponseMessage/ProcessingInformation/Status ausente no retorno."
        )
    return status.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida WSDL e chamada receiveMessage do Gestor TESTE."
    )
    parser.add_argument(
        "--endpoint",
        required=True,
        help="Base do Gestor ou URL terminada em /PcfIntegService.",
    )
    parser.add_argument(
        "--fixture",
        default=str(
            Path(__file__).resolve().parents[1]
            / "tests"
            / "fixtures"
            / "totvs"
            / "ok_productionorder_20260821103018_1079689c001 1.xml"
        ),
        help="XML ProductionOrder usado na homologação.",
    )
    parser.add_argument(
        "--ack",
        default="OK",
        help=(
            "Compatibilidade. O critério real é ProcessingInformation/Status; "
            "este valor é usado apenas na mensagem final."
        ),
    )
    parser.add_argument(
        "--confirm-test",
        action="store_true",
        help="Confirma explicitamente que o alvo é ambiente de TESTE/homologação.",
    )
    args = parser.parse_args()

    if not args.confirm_test:
        print(
            "RECUSADO: use --confirm-test somente depois de confirmar que o endpoint é do Gestor TESTE.",
            file=sys.stderr,
        )
        return 2

    endpoint = _endpoint(args.endpoint)
    fixture = Path(args.fixture).resolve()
    if not fixture.is_file():
        print(f"RECUSADO: fixture não encontrado: {fixture}", file=sys.stderr)
        return 2

    payload = fixture.read_text(encoding="utf-8")
    transaction = _transaction(payload)

    print(f"[1/2] Validando WSDL: {endpoint}?wsdl")
    status, wsdl = _read(endpoint + "?wsdl")
    wsdl_text = wsdl.decode("utf-8", errors="strict")
    if status != 200:
        raise RuntimeError(f"WSDL retornou HTTP {status}.")
    required = ("EAIServiceClass", "receiveMessage", SOAP_ACTION, "receiveMessageResult")
    missing = [item for item in required if item not in wsdl_text]
    if missing:
        raise RuntimeError(f"WSDL incompatível; faltam: {', '.join(missing)}")
    print("      APROVADO: contrato WSDL esperado encontrado.")

    print(f"[2/2] Enviando fixture: {fixture.name} (Transaction={transaction or '<vazia>'})")
    status, response = _read(
        endpoint,
        method="POST",
        body=_soap_envelope(payload),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{SOAP_ACTION}"',
        },
    )
    if status != 200:
        raise RuntimeError(f"receiveMessage retornou HTTP {status}.")
    result = _receive_result(response)
    status = _processing_status(result)
    if status.upper() != args.ack.upper():
        raise RuntimeError(f"Status={status!r}; o Protheus espera {args.ack!r}.")

    print(f"      APROVADO: HTTP 200 e ProcessingInformation/Status={status}.")
    print("HOMOLOGAÇÃO SOAP DO ENDPOINT: APROVADA")
    if transaction.casefold() == "whois":
        print('Próximo passo: repetir "Comunicação" no PCPA109.')
    else:
        print("Próximo passo: conferir a inbox e a OP no PostgreSQL TESTE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
