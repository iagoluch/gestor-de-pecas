"""Contratos serializáveis consumidos pela API Web."""

from .frontend import FRONTEND_CONTRACT_VERSION, MANAGEMENT_SECTIONS
from .management import AnalyticsFilter, MetricValue, NestingTiming
from .ai import (
    AIConversationNotFoundError,
    AIProviderError,
    AIRequestContext,
    AIServiceConfig,
    AIServiceError,
    AIStreamEvent,
    AIToolCall,
    AIToolError,
    AIUnavailableError,
    MAX_AI_CONVERSATION_TITLE_CHARS,
    MAX_AI_MESSAGE_CHARS,
)
from .insights import InsightEvidence, KpiExplanation, ManagementException
from .corporate import (
    CorporateIntegrationStatus,
    CorporateMessageIngestion,
    CorporatePlanningGateway,
)
from .reports import (
    REPORT_PERIOD_KINDS,
    build_report_idempotency_key,
    REPORT_TYPES,
    ReportError,
    ReportRequest,
    resolve_report_period,
)
from .messaging import DocumentMessagingProvider, MessagingError

__all__ = [
    "AnalyticsFilter",
    "build_report_idempotency_key",
    "AIConversationNotFoundError",
    "AIProviderError",
    "AIRequestContext",
    "AIServiceConfig",
    "AIServiceError",
    "AIStreamEvent",
    "AIToolCall",
    "AIToolError",
    "AIUnavailableError",
    "MAX_AI_CONVERSATION_TITLE_CHARS",
    "MAX_AI_MESSAGE_CHARS",
    "MetricValue",
    "NestingTiming",
    "InsightEvidence",
    "KpiExplanation",
    "ManagementException",
    "FRONTEND_CONTRACT_VERSION",
    "MANAGEMENT_SECTIONS",
    "CorporateIntegrationStatus",
    "CorporateMessageIngestion",
    "CorporatePlanningGateway",
    "REPORT_PERIOD_KINDS",
    "REPORT_TYPES",
    "ReportError",
    "ReportRequest",
    "resolve_report_period",
    "DocumentMessagingProvider",
    "MessagingError",
]
