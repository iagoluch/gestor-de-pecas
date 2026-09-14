from __future__ import annotations

import csv
import io
import json
from datetime import datetime
import asyncio

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi import Path as ApiPath
from fastapi.responses import FileResponse, Response

from backend.api.dependencies.auth import require_csrf, require_management_user
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import analytics_filter
from backend.api.dependencies.reports import get_report_service
from backend.api.dependencies.messaging import get_report_messaging_service
from backend.api.errors import AppError
from backend.api.schemas.reports import (
    ReportGenerateRequest,
    ReportScheduleCreateRequest,
    ReportSendRequest,
)
from backend.api.schemas.auth import SessionUser
from mes.contracts import (
    AnalyticsFilter,
    build_report_idempotency_key,
    MessagingError,
    ReportError,
    ReportRequest,
    resolve_report_period,
)

from backend.api.report_workbook import build_report_workbook


router = APIRouter(prefix="/reports", tags=["Relatórios"])


def _report_error(exc: ReportError):
    return AppError(exc.code, exc.user_message, status_code=exc.status_code)


@router.post("/generate", status_code=201)
async def generate_report(
    payload: ReportGenerateRequest,
    user: SessionUser = Depends(require_management_user),
    _csrf: None = Depends(require_csrf),
    service=Depends(get_report_service),
):
    try:
        now = service._now().replace(microsecond=0)
        inicio, fim = resolve_report_period(
            payload.period_kind,
            now=now,
            inicio=payload.inicio,
            fim=payload.fim,
        )
        request = ReportRequest(
            report_type=payload.report_type,
            inicio=inicio,
            fim=fim,
            setor=payload.setor,
            recurso=payload.recurso,
            op=payload.op,
            indicador=payload.indicador,
            include_executive_analysis=payload.include_executive_analysis,
        )
        # Chave determinística: dois cliques simultâneos convergem para o mesmo
        # artifact em vez de gerarem dois arquivos.
        return await asyncio.to_thread(
            service.generate,
            request,
            created_by=user.id,
            source="manual",
            idempotency_key=build_report_idempotency_key(
                request, created_by=user.id, source="manual"
            ),
        )
    except ReportError as exc:
        raise _report_error(exc) from exc


@router.get("/artifacts/{report_id}")
def report_artifact(
    report_id: str = ApiPath(min_length=36, max_length=36),
    user: SessionUser = Depends(require_management_user),
    service=Depends(get_report_service),
):
    try:
        record, _path = service.get(report_id, user_id=user.id)
        return service.view(record, user_id=user.id)
    except ReportError as exc:
        raise _report_error(exc) from exc


@router.post("/artifacts/{report_id}/send")
async def send_report_artifact(
    payload: ReportSendRequest,
    report_id: str = ApiPath(min_length=36, max_length=36),
    user: SessionUser = Depends(require_management_user),
    _csrf: None = Depends(require_csrf),
    service=Depends(get_report_messaging_service),
):
    try:
        return await service.send_report(
            report_id,
            user_id=user.id,
            destination_id=payload.destination_id,
        )
    except ReportError as exc:
        raise _report_error(exc) from exc
    except MessagingError as exc:
        raise AppError(exc.code, exc.user_message, status_code=exc.status_code) from exc


@router.get("/artifacts/{report_id}/download")
def download_report_artifact(
    report_id: str = ApiPath(min_length=36, max_length=36),
    user: SessionUser = Depends(require_management_user),
    service=Depends(get_report_service),
):
    try:
        record, path = service.get(report_id, user_id=user.id)
        service.repository.registrar_download_relatorio(report_id, user.id, service._now())
        return FileResponse(
            path,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=record["filename"],
        )
    except ReportError as exc:
        raise _report_error(exc) from exc


@router.get("/schedules")
def list_report_schedules(
    user: SessionUser = Depends(require_management_user),
    service=Depends(get_report_service),
):
    return {"items": service.repository.listar_agendamentos_relatorio(user.id)}


@router.post("/schedules", status_code=201)
def create_report_schedule(
    payload: ReportScheduleCreateRequest,
    user: SessionUser = Depends(require_management_user),
    _csrf: None = Depends(require_csrf),
    service=Depends(get_report_service),
):
    if payload.destination_id is not None and not service.repository.obter_destino_mensagem(
        payload.destination_id, user.id, provider="telegram"
    ):
        raise AppError("messaging_destination_not_found", "Destino não encontrado.", status_code=404)
    return service.repository.criar_agendamento_relatorio(
        created_by=user.id,
        name=payload.name,
        report_type=payload.report_type,
        frequency=payload.frequency,
        filters={key: value for key, value in {
            "setor": payload.setor,
            "recurso": payload.recurso,
            "op": payload.op,
        }.items() if value},
        run_time=payload.run_time,
        timezone=payload.timezone,
        enabled=payload.enabled,
        destination_id=payload.destination_id,
        created_at=service._now(),
    )


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_report_schedule(
    schedule_id: int = ApiPath(ge=1),
    user: SessionUser = Depends(require_management_user),
    _csrf: None = Depends(require_csrf),
    service=Depends(get_report_service),
):
    if not service.repository.excluir_agendamento_relatorio(schedule_id, user.id):
        raise AppError("report_schedule_not_found", "Agendamento não encontrado.", status_code=404)
    return Response(status_code=204)


@router.get("/{report_type}")
def report(
    report_type: str,
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    return facade.relatorio(report_type, filters)


def _tabular_rows(payload):
    encoded = jsonable_encoder(payload)
    candidates = []
    if isinstance(encoded, dict):
        for value in encoded.values():
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
                candidates = value
                break
            if isinstance(value, dict):
                for nested in value.values():
                    if isinstance(nested, list) and nested and all(isinstance(item, dict) for item in nested):
                        candidates = nested
                        break
            if candidates:
                break
    if candidates:
        return candidates
    return [{"dados": json.dumps(encoded, ensure_ascii=False, separators=(",", ":"))}]


@router.get("/{report_type}/export.csv")
def export_csv(
    report_type: str,
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    rows = _tabular_rows(facade.relatorio(report_type, filters))
    columns = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore", delimiter=";")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
            for key, value in row.items()
        })
    content = "\ufeff" + output.getvalue()
    safe_type = report_type.strip().casefold().replace("-", "_")
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="gestor_{safe_type}.csv"'},
    )


@router.get("/{report_type}/export.xlsx")
def export_xlsx(
    report_type: str,
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    """Entrega um Excel normal e formatado com a verdade já calculada no backend."""

    payload = facade.relatorio(report_type, filters)
    content = build_report_workbook(report_type, payload, filters)
    safe_type = report_type.strip().casefold().replace("-", "_")
    filename = f"gestor_{safe_type}_{datetime.now():%Y-%m-%d}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
