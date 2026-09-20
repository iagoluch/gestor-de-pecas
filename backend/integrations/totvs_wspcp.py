"""Gateway HTTP/SOAP isolado para o WSPCP do Protheus.

O domínio recebe apenas ``TotvsOutboundMessage`` e ``TotvsOutboundAck``. A
política de outbox/retry vive fora daqui: este módulo transporta e reporta, não
decide reenvio.

``send`` mantém o comportamento homologado na Etapa 5 (levanta
``TotvsIntegrationError`` em qualquer falha). ``send_result`` é a variante usada
pelo worker da outbox: ela não levanta por falha de transporte, HTTP ou ACK,
devolvendo um resultado estruturado para que a classificação — transitório,
autenticação, funcional — seja feita pelo domínio e não por texto de exceção.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import os

import httpx

from mes.integrations.totvs.errors import TotvsContractError, TotvsIntegrationError
from mes.integrations.totvs.outbound_ack import parse_wspcp_ack
from mes.integrations.totvs.outbound_models import TotvsOutboundAck, TotvsOutboundMessage


SOAP_ENVELOPE_NAMESPACE = "http://schemas.xmlsoap.org/soap/envelope/"
WSPCP_SERVICE_NAMESPACE = "http://webservices.totvs.com.br/"
WSPCP_SOAP_ACTION = "http://webservices.totvs.com.br/RECEIVEMESSAGE"


def build_wspcp_envelope(
    message_xml: str,
    *,
    service_namespace: str,
) -> str:
    payload = str(message_xml or "").strip()
    if not payload:
        raise ValueError("O XML de negócio não pode ficar vazio.")
    cdata = payload.replace("]]>", "]]]]><![CDATA[>")
    namespace = str(service_namespace or "").strip()
    if not namespace:
        raise ValueError("O namespace do WSPCP deve vir do WSDL do ambiente.")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<soapenv:Envelope xmlns:soapenv="{SOAP_ENVELOPE_NAMESPACE}" '
        f'xmlns:wspcp="{namespace}">'
        "<soapenv:Header/><soapenv:Body><wspcp:RECEIVEMESSAGE>"
        f"<wspcp:CXML><![CDATA[{cdata}]]></wspcp:CXML>"
        "</wspcp:RECEIVEMESSAGE></soapenv:Body></soapenv:Envelope>"
    )


@dataclass(frozen=True)
class WspcpClientConfig:
    endpoint: str
    service_namespace: str = WSPCP_SERVICE_NAMESPACE
    timeout_seconds: float = 30.0
    username: str | None = None
    password: str | None = None
    authentication_mode: str | None = None
    soap_action: str = WSPCP_SOAP_ACTION
    verify_tls: bool = True


@dataclass(frozen=True)
class WspcpSendResult:
    """Resultado estruturado de uma tentativa, sem política de retry embutida.

    ``transport_failure`` distingue falha de rede de resposta HTTP.
    ``soap_fault`` preserva o texto do Fault porque o WSPCP TESTE responde
    credencial inválida como HTTP 500 + Fault ``AUTHENTICATION``, e não como
    401/403 — sem esse texto, uma senha errada seria confundida com
    indisponibilidade temporária e entraria em retry longo.
    """

    ack: TotvsOutboundAck | None = None
    http_status: int | None = None
    transport_failure: str | None = None
    soap_fault: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw_response: str | None = None

    @property
    def accepted(self) -> bool:
        return self.ack is not None and self.ack.accepted


def _transport_failure_kind(exc: Exception) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "conexao_recusada"
    if isinstance(exc, httpx.NetworkError):
        return "falha_de_rede"
    return "falha_de_transporte"


class TotvsWspcpClient:
    def __init__(self, config: WspcpClientConfig, *, transport=None):
        self.config = config
        self._transport = transport

    def send(self, message: TotvsOutboundMessage) -> TotvsOutboundAck:
        """Envio estrito da Etapa 5: qualquer falha vira exceção controlada."""

        result = self.send_result(message)
        if result.ack is None:
            raise TotvsIntegrationError(
                result.error_message or "Falha de comunicação com WSPCP.",
                code=result.error_code or "totvs_integration_error",
            )
        if result.http_status is not None and result.http_status >= 400:
            raise TotvsIntegrationError(
                result.error_message
                or f"WSPCP retornou HTTP {result.http_status} sem SOAP Fault válido."
            )
        return result.ack

    def send_result(self, message: TotvsOutboundMessage) -> WspcpSendResult:
        """Transmite e reporta; a decisão de reenviar é do domínio da outbox."""

        endpoint = str(self.config.endpoint or "").strip()
        if not endpoint:
            raise TotvsIntegrationError("Endpoint WSPCP não configurado.")
        headers = {"Content-Type": "text/xml; charset=utf-8"}
        if self.config.soap_action:
            headers["SOAPAction"] = self.config.soap_action
        auth = self._http_auth()
        envelope = build_wspcp_envelope(
            message.xml, service_namespace=self.config.service_namespace
        )
        try:
            with httpx.Client(
                timeout=self.config.timeout_seconds,
                verify=self.config.verify_tls,
                transport=self._transport,
            ) as client:
                response = client.post(
                    endpoint,
                    content=envelope.encode("utf-8"),
                    headers=headers,
                    auth=auth,
                )
        except httpx.HTTPError as exc:
            kind = _transport_failure_kind(exc)
            return WspcpSendResult(
                transport_failure=kind,
                error_code=kind,
                error_message=f"Falha de comunicação com WSPCP: {exc}",
            )
        try:
            ack = parse_wspcp_ack(response.text)
        except TotvsContractError as exc:
            detail = str(exc)
            return WspcpSendResult(
                http_status=response.status_code,
                soap_fault=detail if "SOAP Fault" in detail else None,
                error_code=getattr(exc, "code", "invalid_totvs_contract"),
                error_message=f"WSPCP retornou HTTP {response.status_code}: {detail}",
                raw_response=response.text,
            )
        ack = replace(ack, http_status=response.status_code, raw_soap=response.text)
        if response.is_error:
            return WspcpSendResult(
                ack=ack,
                http_status=response.status_code,
                error_code=f"http_{response.status_code}",
                error_message=(
                    f"WSPCP retornou HTTP {response.status_code} sem SOAP Fault válido."
                ),
                raw_response=response.text,
            )
        return WspcpSendResult(
            ack=ack,
            http_status=response.status_code,
            error_message=" | ".join(ack.messages) if ack.messages else None,
            raw_response=response.text,
        )

    @classmethod
    def from_env(cls, env=None, *, transport=None) -> "TotvsWspcpClient | None":
        """Monta o client a partir do ambiente, sem nome de banco na lógica.

        O mesmo código serve TESTE e o piloto REAL; o que muda é o ``.env``.
        Sem endpoint configurado o resultado é ``None`` e o worker apenas não
        entrega — a fila continua durável e nada é perdido.
        """

        environ = env if env is not None else os.environ
        endpoint = str(environ.get("GESTOR_TOTVS_OUTBOUND_ENDPOINT") or "").strip()
        if not endpoint:
            return None
        try:
            timeout = float(
                str(environ.get("GESTOR_TOTVS_OUTBOUND_TIMEOUT_SECONDS") or "30").strip()
            )
        except ValueError as exc:
            raise TotvsIntegrationError(
                "GESTOR_TOTVS_OUTBOUND_TIMEOUT_SECONDS deve ser numérico."
            ) from exc
        return cls(
            WspcpClientConfig(
                endpoint=endpoint,
                service_namespace=str(
                    environ.get("GESTOR_TOTVS_OUTBOUND_SERVICE_NAMESPACE")
                    or WSPCP_SERVICE_NAMESPACE
                ).strip(),
                timeout_seconds=timeout,
                username=str(environ.get("GESTOR_TOTVS_OUTBOUND_USERNAME") or "") or None,
                password=environ.get("GESTOR_TOTVS_OUTBOUND_PASSWORD") or None,
                authentication_mode=str(
                    environ.get("GESTOR_TOTVS_OUTBOUND_AUTH_MODE") or ""
                ).strip()
                or None,
                soap_action=str(
                    environ.get("GESTOR_TOTVS_OUTBOUND_SOAP_ACTION") or WSPCP_SOAP_ACTION
                ).strip(),
                verify_tls=str(
                    environ.get("GESTOR_TOTVS_OUTBOUND_VERIFY_TLS") or "true"
                ).strip().casefold()
                not in {"0", "false", "nao", "não", "no", "off"},
            ),
            transport=transport,
        )

    def _http_auth(self):
        mode = str(self.config.authentication_mode or "").strip().casefold()
        username = str(self.config.username or "").strip()
        password = self.config.password
        if not mode:
            if username or password:
                raise TotvsIntegrationError(
                    "Credenciais WSPCP configuradas sem mecanismo de autenticação comprovado."
                )
            return None
        if mode != "basic":
            raise TotvsIntegrationError(
                f"Mecanismo de autenticação WSPCP não suportado: {mode!r}."
            )
        if not username or password is None or password == "":  # nosec B105 -- validação de presença, não senha hardcoded
            raise TotvsIntegrationError(
                "Autenticação Basic do WSPCP exige usuário e senha no .env."
            )
        return httpx.BasicAuth(username, password)
