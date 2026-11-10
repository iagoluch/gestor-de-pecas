import csv
import io
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi import Path as ApiPath
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response

from backend.api.dependencies.auth import require_management_user
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.dependencies.filters import PageParams, analytics_filter, pagination
from backend.api.report_workbook.kit import safe_text
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


# --- Auditoria Analítica (Etapa 2): tipos 01 e 02 numa rota só ------------------

TipoRelatorio = Literal["01", "02"]


@router.get("/reports")
def report_catalog(_user: SessionUser = Depends(require_management_user)):
    return audit_reports.catalogo()


def _run_report(facade, tipo, filters, **table):
    """Envelope do tipo, ou ``(None, resposta de erro)`` com ``estado: erro``."""
    try:
        return audit_reports.run(facade, tipo, filters, **table), None
    except Exception:  # noqa: BLE001 -- a falha vira estado "erro" explícito, com log
        logging.exception("Falha na Auditoria Analítica tipo=%s", tipo)
        body = {
            "tipo": tipo,
            "estado": "erro",
            "as_of": audit_reports.as_of_for(filters),
            "detail": "Não foi possível consultar este relatório agora. Tente de novo.",
        }
        return None, JSONResponse(status_code=500, content=jsonable_encoder(body))


@router.get("/reports/{tipo}")
def report(
    tipo: TipoRelatorio = ApiPath(...),
    filters: AnalyticsFilter = Depends(analytics_filter),
    params: PageParams = Depends(pagination),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
    evento_status: str | None = Query(default=None, max_length=160),
    evento_classe: str | None = Query(default=None, max_length=60),
    em_aberto: bool = Query(default=False),
):
    """Filtros ``evento_*`` e ``em_aberto`` só valem no tipo 01."""
    table = {"status": evento_status, "classe": evento_classe, "em_aberto": em_aberto} if tipo == "01" else {}
    payload, error = _run_report(facade, tipo, filters, **table)
    if error is not None:
        return error
    items = payload.pop("items")
    return {**payload, "items": params.slice(items), "page": params.meta(len(items))}


def _csv_cell(value):
    # Texto livre do chão de fábrica não pode virar fórmula no Excel (BK-04).
    if isinstance(value, bool):
        return "sim" if value else "não"
    return safe_text(value) if isinstance(value, str) else value


@router.get("/reports/{tipo}/export.csv")
def report_export_csv(
    tipo: TipoRelatorio = ApiPath(...),
    filters: AnalyticsFilter = Depends(analytics_filter),
    _user: SessionUser = Depends(require_management_user),
    facade=Depends(get_frontend_facade),
    evento_status: str | None = Query(default=None, max_length=160),
    evento_classe: str | None = Query(default=None, max_length=60),
    em_aberto: bool = Query(default=False),
):
    """Todas as linhas e todos os campos do tipo, com os mesmos filtros da tela."""
    table = {"status": evento_status, "classe": evento_classe, "em_aberto": em_aberto} if tipo == "01" else {}
    payload, error = _run_report(facade, tipo, filters, **table)
    if error is not None:
        return error
    campos = [campo["chave"] for campo in payload["campos"]]
    rotulos = {campo["chave"]: campo["rotulo"] for campo in payload["campos"]}
    # Campo novo na fonte que o catálogo ainda não conhece também sai, no fim.
    for item in payload["items"]:
        campos.extend(key for key in item if key not in campos)
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow([rotulos.get(key, key) for key in campos])
    for item in jsonable_encoder(payload["items"]):
        writer.writerow([_csv_cell(item.get(key)) for key in campos])
    as_of = jsonable_encoder(payload["as_of"])
    return Response(
        content=("\ufeff" + output.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="auditoria_tipo_{tipo}.csv"',
            "X-Gestor-As-Of": as_of,
        },
    )
