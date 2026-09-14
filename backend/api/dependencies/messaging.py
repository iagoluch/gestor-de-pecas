from fastapi import Depends, Request

from backend.api.database import get_database
from backend.api.dependencies.reports import get_report_service
from backend.messaging import TelegramProvider
from mes.services.report_messaging import ReportMessagingService


def get_report_messaging_service(
    request: Request,
    database=Depends(get_database),
    report_service=Depends(get_report_service),
):
    settings = request.app.state.settings
    provider = None
    if settings.telegram_configured:
        provider = TelegramProvider(
            bot_token=settings.telegram_bot_token,
            timeout_seconds=settings.telegram_timeout_seconds,
        )
    return ReportMessagingService(
        database,
        report_service,
        provider=provider,
        enabled=settings.telegram_enabled,
        configured=settings.telegram_configured,
        now_func=report_service._now,
    )


__all__ = ["get_report_messaging_service"]
