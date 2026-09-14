from fastapi import Depends, Request

from backend.api.database import get_database
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.reports import get_report_service
from mes.contracts.ai import AIServiceConfig
from mes.services.ai_service import AIService
from mes.services.ai_tools import AIToolRegistry


def get_ai_service(
    request: Request,
    database=Depends(get_database),
    facade=Depends(get_frontend_facade),
    report_service=Depends(get_report_service),
):
    settings = request.app.state.settings
    provider = request.app.state.ai_provider
    provider_configured = bool(getattr(provider, "configured", True))
    config = AIServiceConfig(
        enabled=settings.ai_enabled,
        configured=settings.ai_configured and provider_configured,
        model=settings.ai_model,
        max_tool_rounds=settings.ai_max_tool_rounds,
        max_history_messages=settings.ai_max_history_messages,
        request_token_budget=settings.ai_request_token_budget,
        max_completion_tokens=settings.ai_max_completion_tokens,
    )
    return AIService(
        database,
        provider,
        AIToolRegistry(
            facade,
            now_func=getattr(facade, "_now", None),
            tool_result_max_chars=settings.ai_tool_result_max_chars,
            report_service=report_service,
        ),
        config,
    )
