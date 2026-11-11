import io
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi import Path as ApiPath
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from backend.api.dependencies.auth import get_current_user, require_management_user
from backend.api.dependencies.clock import request_now_func
from backend.api.errors import AppError
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import PageParams, analytics_filter, pagination
from backend.api.report_workbook.kit import MUTED, NAVY, WHITE, fill, filters_label, font, period_label, safe_text
from backend.api.schemas.auth import SessionUser
from mes.contracts import AnalyticsFilter
from mes.services import audit_reports


router = APIRouter(prefix="/audit", tags=["Auditoria"])


@router.get("/appointments")
def appointments(
    filters: AnalyticsFilter = Depends(analytics_filter),
    params: PageParams = Depends(pagination),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    payload = facade.ordens_producao(filters)
    items = list(payload.get("items", []))
    return {
        "periodo": payload.get("periodo"),
        "availability": payload.get("availability"),
        "items": params.slice(items),
        "page": params.meta(len(items)),
    }


def _paged_events(payload, params: PageParams):
    items = list(payload.get("items", []))
    return {"summary": payload.get("summary"), "items": params.slice(items), "page": params.meta(len(items))}


@router.get("/status-events")
def status_events(
    filters: AnalyticsFilter = Depends(analytics_filter),
    params: PageParams = Depends(pagination),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
    evento_recurso: str | None = Query(default=None, max_length=120),
    evento_status: str | None = Query(default=None, max_length=160),
    evento_classe: str | None = Query(default=None, max_length=60),
    evento_op: str | None = Query(default=None, max_length=120),
    em_aberto: bool = Query(default=False),
):
    """Filtros ``evento_*`` são da tabela da tela; ``opcoes`` vem sem eles aplicados."""
    payload = facade.eventos_status(
        filters, recurso=evento_recurso, status=evento_status, classe=evento_classe, op=evento_op, em_aberto=em_aberto,
    )
    return {**_paged_events(payload, params), "opcoes": payload.get("opcoes")}


@router.get("/production-events")
def production_events(
    filters: AnalyticsFilter = Depends(analytics_filter),
    params: PageParams = Depends(pagination),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    return _paged_events(facade.eventos_producao(filters), params)


@router.get("")
def audit(
    filters: AnalyticsFilter = Depends(analytics_filter),
    params: PageParams = Depends(pagination),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    payload = facade.auditoria(filters)
    issues = list(payload.get("issues", []))
    return {
        **{key: value for key, value in payload.items() if key != "issues"},
        "issues": params.slice(issues),
        "page": params.meta(len(issues)),
    }


@router.get("/reliability")
def reliability(
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
):
    payload = facade.auditoria(filters)
    return {
        "periodo": payload.get("periodo"),
        "records_analyzed": payload.get("records_analyzed"),
        "resource_states_analyzed": payload.get("resource_states_analyzed"),
        "rateio_sessions_analyzed": payload.get("rateio_sessions_analyzed"),
        "by_severity": payload.get("by_severity"),
        "reliability_percentage": payload.get("reliability_percentage"),
        "reliability_reason": payload.get("reliability_reason"),
        "physical_state_source": payload.get("physical_state_source"),
    }


# --- Auditoria Analítica: tipos 01 a 21 numa rota só ------------------------------

TipoRelatorio = Literal[
    "01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11",
    "12", "13", "14", "15", "16", "17", "18", "19", "20", "21",
]


@router.get("/reports")
def report_catalog(user: SessionUser = Depends(get_current_user)):
    """Só os tipos que a conta pode abrir (a guarda de cada módulo de origem)."""
    catalogo = audit_reports.catalogo(user)
    if not catalogo["tipos"]:
        raise AppError("forbidden", "Sem acesso à Auditoria Analítica.", status_code=403)
    return catalogo


def _guard(tipo, user):
    if not audit_reports.pode_ver(audit_reports.TIPOS[tipo], user):
        raise AppError("forbidden", "Seu nível não abre este tipo de relatório.", status_code=403)


def _now(request):
    # Mesmo relógio da Diretoria (``clock.now`` em simulação), para o as_of bater.
    now_func = request_now_func(request) if request is not None else None
    return now_func() if now_func is not None else None


def _run_report(facade, tipo, filters, user, request=None, **table):
    """Envelope do tipo, ou ``(None, resposta de erro)`` com ``estado: erro``."""
    _guard(tipo, user)
    now = _now(request)
    try:
        return audit_reports.run(facade, tipo, filters, user=user, now=now, **table), None
    except audit_reports.ForaDoEscopo:
        raise AppError("trace_out_of_scope", "Esta OP não passou pelo seu setor.", status_code=403)
    except Exception:  # noqa: BLE001 -- a falha vira estado "erro" explícito, com log
        logging.exception("Falha na Auditoria Analítica tipo=%s", tipo)
        body = {
            "tipo": tipo,
            "estado": "erro",
            "as_of": audit_reports.as_of_for(filters, now),
            "detail": "Não foi possível consultar este relatório agora. Tente de novo.",
        }
        return None, JSONResponse(status_code=500, content=jsonable_encoder(body))


@router.get("/reports/{tipo}")
def report(
    request: Request,
    tipo: TipoRelatorio = ApiPath(...),
    filters: AnalyticsFilter = Depends(analytics_filter),
    params: PageParams = Depends(pagination),
    user: SessionUser = Depends(get_current_user),
    facade=Depends(get_frontend_facade),
    evento_status: str | None = Query(default=None, max_length=160),
    evento_classe: str | None = Query(default=None, max_length=60),
    em_aberto: bool = Query(default=False),
):
    """Filtros ``evento_*`` e ``em_aberto`` só valem no tipo 01."""
    table = {"status": evento_status, "classe": evento_classe, "em_aberto": em_aberto} if tipo == "01" else {}
    payload, error = _run_report(facade, tipo, filters, user, request, **table)
    if error is not None:
        return error
    items = payload.pop("items")
    return {**payload, "items": params.slice(items), "page": params.meta(len(items))}


_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_XLSX_HEADER_ROW = 5


def _xlsx_cell(value):
    # Texto livre do chão de fábrica não pode virar fórmula no Excel (BK-04).
    if isinstance(value, bool):
        return "sim" if value else "não"
    if isinstance(value, (dict, list)):
        return safe_text(str(value))
    return safe_text(value) if isinstance(value, str) else value


def _filter_line(filters, table) -> str:
    partes = [f"Período: {period_label(filters)}", filters_label(filters)]
    extras = (("status", "Evento"), ("classe", "Classe"))
    partes.extend(f"{rotulo}: {table[chave]}" for chave, rotulo in extras if table.get(chave))
    if table.get("em_aberto"):
        partes.append("Só em aberto")
    return "Filtro: " + " • ".join(partes)


@router.get("/reports/{tipo}/export.xlsx")
def report_export_xlsx(
    request: Request,
    tipo: TipoRelatorio = ApiPath(...),
    filters: AnalyticsFilter = Depends(analytics_filter),
    user: SessionUser = Depends(get_current_user),
    facade=Depends(get_frontend_facade),
    evento_status: str | None = Query(default=None, max_length=160),
    evento_classe: str | None = Query(default=None, max_length=60),
    em_aberto: bool = Query(default=False),
):
    """Planilha Excel com todas as linhas e todos os campos do tipo, com os mesmos filtros da tela."""
    table = {"status": evento_status, "classe": evento_classe, "em_aberto": em_aberto} if tipo == "01" else {}
    payload, error = _run_report(facade, tipo, filters, user, request, **table)
    if error is not None:
        return error
    campos = [campo["chave"] for campo in payload["campos"]]
    rotulos = {campo["chave"]: campo["rotulo"] for campo in payload["campos"]}
    # Campo novo na fonte que o catálogo ainda não conhece também sai, no fim.
    for item in payload["items"]:
        campos.extend(key for key in item if key not in campos)
    as_of = jsonable_encoder(payload["as_of"])
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = f"Auditoria tipo {tipo}"
    sheet["A1"] = safe_text(f"Auditoria analítica — tipo {tipo}: {payload['titulo']}")
    sheet["A1"].font = font(size=14, bold=True, color=NAVY)
    sheet["A2"] = safe_text(_filter_line(filters, table))
    sheet["A3"] = f"Referência (as_of): {as_of}"
    for cell in (sheet["A2"], sheet["A3"]):
        cell.font = font(color=MUTED)
    for col, key in enumerate(campos, start=1):
        cell = sheet.cell(row=_XLSX_HEADER_ROW, column=col, value=safe_text(rotulos.get(key, key)))
        cell.font = font(bold=True, color=WHITE)
        cell.fill = fill(NAVY)
        sheet.column_dimensions[get_column_letter(col)].width = max(12, min(40, len(str(cell.value)) + 4))
    for row, item in enumerate(jsonable_encoder(payload["items"]), start=_XLSX_HEADER_ROW + 1):
        for col, key in enumerate(campos, start=1):
            sheet.cell(row=row, column=col, value=_xlsx_cell(item.get(key)))
    sheet.freeze_panes = sheet.cell(row=_XLSX_HEADER_ROW + 1, column=1)
    output = io.BytesIO()
    workbook.save(output)
    return Response(
        content=output.getvalue(),
        media_type=_XLSX_MEDIA,
        headers={
            "Content-Disposition": f'attachment; filename="auditoria_tipo_{tipo}.xlsx"',
            "X-Gestor-As-Of": as_of,
        },
    )