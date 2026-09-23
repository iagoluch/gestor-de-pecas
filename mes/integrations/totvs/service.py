"""Caso de uso canônico de ingestão ProductionOrder, independente do transporte."""

from __future__ import annotations

import hashlib
import logging
from typing import Protocol

from mes.contracts.corporate import CorporateIntegrationStatus
from mes.integrations.totvs.errors import (
    TotvsIntegrationDisabledError,
    TotvsIntegrationError,
    TotvsStoredMessageError,
)
from mes.integrations.totvs.mapper import TotvsProductionOrderMapper
from mes.integrations.totvs.models import (
    ProductionOrderMessage,
    TotvsDiagnosticResult,
    TotvsIngestionResult,
    TotvsMappingResult,
    TotvsMessageMetadata,
    TotvsMessageOutcome,
    TotvsWhoIsMessage,
)
from mes.integrations.totvs.parser import TotvsMessageParser
from mes.integrations.totvs.resource_mapping import TotvsResourceResolver
from mes.integrations.totvs.response import (
    DEFAULT_GESTOR_IDENTITY,
    TotvsGestorIdentity,
    build_response_message,
    is_whois_transaction,
)


class TotvsProductionOrderRepository(Protocol):
    def registrar_mensagem_totvs(self, *, payload_hash: str, payload_raw: str) -> dict:
        ...

    def aplicar_production_order_totvs(
        self,
        *,
        message_id: int,
        payload_hash: str,
        message: ProductionOrderMessage,
        mapping: TotvsMappingResult,
    ) -> dict:
        ...

    def marcar_mensagem_totvs_erro(
        self,
        message_id: int,
        *,
        error_code: str,
        error_message: str,
        message: ProductionOrderMessage | None = None,
    ) -> None:
        ...

    def registrar_diagnostico_totvs(
        self,
        *,
        message_id: int,
        message: TotvsWhoIsMessage,
    ) -> dict:
        ...

    def listar_codigos_recursos_totvs(self) -> tuple[str, ...]:
        ...

    def listar_setores_recursos_totvs(self) -> tuple[tuple[str, str], ...]:
        ...


def _result_from_row(row: dict, *, idempotent: bool = False) -> TotvsIngestionResult:
    warnings = row.get("warnings") or ()
    return TotvsIngestionResult(
        message_id=int(row["id"]),
        payload_hash=str(row["payload_hash"]),
        transaction=row.get("transaction"),
        external_id=row.get("external_id"),
        status=str(row.get("status") or "error"),
        action="duplicate" if idempotent else str(row.get("result_action") or "error"),
        activities_parsed=int(row.get("activities_parsed") or 0),
        activities_projected=int(row.get("activities_projected") or 0),
        warnings=tuple(str(item) for item in warnings),
        idempotent=idempotent,
    )


class TotvsProductionOrderIngestionService:
    def __init__(
        self,
        repository: TotvsProductionOrderRepository,
        *,
        enabled: bool = False,
        parser: TotvsMessageParser | None = None,
        mapper: TotvsProductionOrderMapper | None = None,
        identity: TotvsGestorIdentity = DEFAULT_GESTOR_IDENTITY,
    ):
        self.repository = repository
        self.enabled = bool(enabled)
        self.parser = parser or TotvsMessageParser()
        self.mapper = mapper or TotvsProductionOrderMapper()
        self.identity = identity

    def status(self) -> CorporateIntegrationStatus:
        return CorporateIntegrationStatus(
            provider="totvs_production_order_push_v1",
            configured=self.enabled,
            planning_read_enabled=self.enabled,
            execution_write_enabled=False,
            reason=(
                "Ingestão TOTVS ProductionOrder V1 habilitada."
                if self.enabled
                else "Ingestão TOTVS ProductionOrder V1 desabilitada por configuração."
            ),
        )

    def handle_message(self, payload: str | bytes) -> TotvsMessageOutcome:
        """Roteia a mensagem recebida sem alterar o fluxo de ProductionOrder."""

        if not self.enabled:
            raise TotvsIntegrationDisabledError(
                "A ingestão TOTVS ProductionOrder está desabilitada por configuração."
            )
        raw = self.parser.payload_bytes(payload)
        metadata = self._peek_metadata(raw)
        transaction = metadata.transaction if metadata is not None else ""
        if is_whois_transaction(transaction):
            diagnostic = self.handle_whois(raw)
            return TotvsMessageOutcome(
                transaction=transaction,
                soap_result=diagnostic.response_xml,
                diagnostic=diagnostic,
            )
        # Qualquer outra mensagem (inclusive XML inválido) segue o caminho atual,
        # que registra a inbox e reporta o mesmo erro de hoje.
        ingestion = self.ingest(raw)
        # A resposta de sucesso só existe depois que a OP foi aplicada e commitada.
        response = (
            build_response_message(metadata, identity=self.identity)
            if metadata is not None
            else None
        )
        return TotvsMessageOutcome(
            transaction=transaction,
            soap_result=response,
            ingestion=ingestion,
        )

    def handle_whois(self, payload: str | bytes) -> TotvsDiagnosticResult:
        """Responde o WhoIs como diagnóstico auditável, sem efeito de negócio."""

        if not self.enabled:
            raise TotvsIntegrationDisabledError(
                "A ingestão TOTVS ProductionOrder está desabilitada por configuração."
            )
        raw = self.parser.payload_bytes(payload)
        payload_hash = hashlib.sha256(raw).hexdigest()
        inbox = self.repository.registrar_mensagem_totvs(
            payload_hash=payload_hash,
            payload_raw=raw.decode("utf-8"),
        )
        message_id = int(inbox["id"])
        try:
            message = self.parser.parse_whois(raw)
            response_xml = build_response_message(message.metadata, identity=self.identity)
        except TotvsIntegrationError as exc:
            self.repository.marcar_mensagem_totvs_erro(
                message_id,
                error_code=exc.code,
                error_message=str(exc)[:500],
            )
            raise
        already_final = str(inbox.get("status") or "") in {"processed", "ignored", "error"}
        row = (
            inbox
            if already_final
            else self.repository.registrar_diagnostico_totvs(
                message_id=message_id,
                message=message,
            )
        )
        return TotvsDiagnosticResult(
            message_id=message_id,
            payload_hash=payload_hash,
            transaction=message.metadata.transaction,
            status=str(row.get("status") or "ignored"),
            action=str(row.get("result_action") or "diagnostic"),
            response_xml=response_xml,
            idempotent=already_final,
        )

    def _peek_metadata(self, raw: bytes) -> TotvsMessageMetadata | None:
        try:
            return self.parser.read_metadata(raw)
        except TotvsIntegrationError:
            return None

    def ingest(self, payload: str | bytes) -> TotvsIngestionResult:
        if not self.enabled:
            raise TotvsIntegrationDisabledError(
                "A ingestão TOTVS ProductionOrder está desabilitada por configuração."
            )
        raw = self.parser.payload_bytes(payload)
        payload_hash = hashlib.sha256(raw).hexdigest()
        payload_text = raw.decode("utf-8")
        inbox = self.repository.registrar_mensagem_totvs(
            payload_hash=payload_hash,
            payload_raw=payload_text,
        )
        if not inbox.get("created"):
            if inbox.get("status") in {"processed", "ignored"}:
                return _result_from_row(inbox, idempotent=True)
            if inbox.get("status") == "error":
                raise TotvsStoredMessageError(
                    "A mesma mensagem já foi recusada anteriormente; consulte a inbox de integração.",
                    code=str(inbox.get("error_code") or "stored_message_error"),
                )

        parsed = None
        try:
            parsed = self.parser.parse(raw)
            mapping = self.mapper.map(parsed)
            applied = self.repository.aplicar_production_order_totvs(
                message_id=int(inbox["id"]),
                payload_hash=payload_hash,
                message=parsed,
                mapping=mapping,
            )
            return _result_from_row(
                applied,
                idempotent=bool(applied.get("already_final")),
            )
        except TotvsIntegrationError as exc:
            self.repository.marcar_mensagem_totvs_erro(
                int(inbox["id"]),
                error_code=exc.code,
                error_message=str(exc)[:500],
                message=parsed,
            )
            raise
        except Exception as exc:
            logging.exception(
                "Falha controlada ao aplicar mensagem TOTVS (hash=%s)",
                payload_hash,
            )
            self.repository.marcar_mensagem_totvs_erro(
                int(inbox["id"]),
                error_code="processing_error",
                error_message="Falha interna ao aplicar ProductionOrder."[:500],
                message=parsed,
            )
            raise TotvsIntegrationError(
                "Falha interna ao aplicar ProductionOrder.",
                code="processing_error",
            ) from exc


def build_totvs_ingestion_service(repository, settings) -> TotvsProductionOrderIngestionService:
    known_codes = tuple(repository.listar_codigos_recursos_totvs())
    known_sectors = tuple(repository.listar_setores_recursos_totvs())
    resolver = TotvsResourceResolver(
        resource_aliases=settings.totvs_resource_map,
        sector_aliases=settings.totvs_sector_map,
        known_resource_codes=known_codes,
        known_resource_sectors=known_sectors,
    )
    return TotvsProductionOrderIngestionService(
        repository,
        enabled=settings.totvs_enabled,
        parser=TotvsMessageParser(max_xml_bytes=settings.totvs_max_xml_bytes),
        mapper=TotvsProductionOrderMapper(
            resolver,
            default_branch_id=next(
                iter(getattr(settings, "totvs_op_pull_branch_ids", ()) or ()), None
            ),
        ),
        identity=build_gestor_identity(settings),
    )


def build_gestor_identity(settings) -> TotvsGestorIdentity:
    """Identidade canônica e configurável usada nas respostas ao TOTVS."""

    def _value(attribute: str, default: str) -> str:
        return str(getattr(settings, attribute, "") or "").strip() or default

    return TotvsGestorIdentity(
        source_application=_value(
            "totvs_identity_source_application",
            DEFAULT_GESTOR_IDENTITY.source_application,
        ),
        product_name=_value(
            "totvs_identity_product_name", DEFAULT_GESTOR_IDENTITY.product_name
        ),
        product_version=_value(
            "totvs_identity_product_version", DEFAULT_GESTOR_IDENTITY.product_version
        ),
        context_name=_value(
            "totvs_identity_context_name", DEFAULT_GESTOR_IDENTITY.context_name
        ),
    )
