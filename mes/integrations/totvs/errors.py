"""Erros controlados da ingestão TOTVS ProductionOrder V1."""

from __future__ import annotations


class TotvsIntegrationError(RuntimeError):
    """Falha segura com código estável, sem incluir o payload recebido."""

    code = "totvs_integration_error"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code or self.code


class TotvsPayloadTooLargeError(TotvsIntegrationError):
    code = "payload_too_large"


class TotvsXmlSecurityError(TotvsIntegrationError):
    code = "xml_security_violation"


class TotvsXmlParseError(TotvsIntegrationError):
    code = "malformed_xml"


class TotvsContractError(TotvsIntegrationError):
    code = "invalid_totvs_contract"


class TotvsUnsupportedMessageError(TotvsIntegrationError):
    code = "unsupported_totvs_message"


class TotvsIdentityConflictError(TotvsIntegrationError):
    code = "corporate_identity_conflict"


class TotvsTemporalConflictError(TotvsIntegrationError):
    code = "corporate_temporal_conflict"


class TotvsIntegrationDisabledError(TotvsIntegrationError):
    code = "totvs_integration_disabled"


class TotvsStoredMessageError(TotvsIntegrationError):
    code = "stored_message_error"

