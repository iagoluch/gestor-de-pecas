"""Integração corporativa de entrada TOTVS ProductionOrder V1 e WhoIs."""

from .errors import TotvsIntegrationError
from .mapper import TotvsProductionOrderMapper
from .models import TotvsDiagnosticResult, TotvsIngestionResult, TotvsMessageOutcome
from .parser import TotvsMessageParser
from .service import (
    TotvsProductionOrderIngestionService,
    build_gestor_identity,
    build_totvs_ingestion_service,
)
from .response import (
    TotvsGestorIdentity,
    build_response_message,
    is_whois_transaction,
)
from .outbound_mapper import (
    build_production_appointment_xml,
    build_stop_report_xml,
    map_production_appointment,
    map_stop_report,
)
from .outbound_models import (
    CanonicalExecutionEvent,
    TotvsOutboundAck,
    TotvsOutboundIdentity,
    TotvsOutboundMessage,
)
from .outbound_service import TotvsOutboundService
from .outbound_enqueue import (
    OutboundEnqueueConfig,
    load_outbound_enqueue_config,
    plan_execution_event,
    plan_terminal_milestone,
)
from .outbox import (
    DeliveryAttempt,
    DeliveryClass,
    OutboxEnqueueRequest,
    OutboxStatus,
    classify_attempt,
)

__all__ = [
    "TotvsDiagnosticResult",
    "TotvsGestorIdentity",
    "TotvsIngestionResult",
    "TotvsIntegrationError",
    "TotvsMessageOutcome",
    "TotvsMessageParser",
    "TotvsProductionOrderIngestionService",
    "TotvsProductionOrderMapper",
    "CanonicalExecutionEvent",
    "TotvsOutboundAck",
    "TotvsOutboundIdentity",
    "TotvsOutboundMessage",
    "TotvsOutboundService",
    "DeliveryAttempt",
    "DeliveryClass",
    "OutboundEnqueueConfig",
    "OutboxEnqueueRequest",
    "OutboxStatus",
    "classify_attempt",
    "load_outbound_enqueue_config",
    "plan_execution_event",
    "plan_terminal_milestone",
    "build_gestor_identity",
    "build_response_message",
    "build_totvs_ingestion_service",
    "build_production_appointment_xml",
    "build_stop_report_xml",
    "is_whois_transaction",
    "map_production_appointment",
    "map_stop_report",
]

