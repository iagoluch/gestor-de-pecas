from fastapi import Depends, Request

from backend.api.database import get_database
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.report_workbook import build_report_workbook
from mes.services.industrial_reports import IndustrialReportService


def get_report_service(
    request: Request,
    database=Depends(get_database),
    facade=Depends(get_frontend_facade),
):
    settings = request.app.state.settings
    return IndustrialReportService(
        facade,
        database,
        artifact_dir=settings.report_artifact_dir,
        workbook_builder=build_report_workbook,
        now_func=getattr(facade, "_now", None),
        expiration_hours=settings.report_expiration_hours,
        max_bytes=settings.report_max_bytes,
        messaging_available=settings.telegram_configured,
    )


__all__ = ["get_report_service"]
