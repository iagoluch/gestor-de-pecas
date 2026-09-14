"""Tools estritamente read-only sobre a fronteira canônica do frontend."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from itertools import islice
import json
import logging
import math
import re
from typing import Any, Callable
import unicodedata

from mes.contracts import (
    AIRequestContext,
    AIToolError,
    AnalyticsFilter,
    REPORT_PERIOD_KINDS,
    REPORT_TYPES,
    ReportError,
    ReportRequest,
    build_report_idempotency_key,
    resolve_report_period,
)


MAX_TOOL_LIST_ITEMS = 100
MAX_TOOL_STRING_CHARS = 2_000
MAX_TOOL_ARGUMENT_CHARS = 160
MAX_TOOL_PERIOD = timedelta(days=366)
DEFAULT_TOOL_RESULT_MAX_CHARS = 10_000
MAX_AI_KPI_EVIDENCE = 5
MAX_AI_KPI_CAUSES = 3
MAX_AI_KPI_RESOURCES = 3
LOGGER = logging.getLogger(__name__)


FILTER_FIELDS = {
    "inicio": {"type": "string", "maxLength": 40, "description": "Data/hora inicial ISO 8601."},
    "fim": {"type": "string", "maxLength": 40, "description": "Data/hora final ISO 8601."},
    "setor": {"type": "string", "maxLength": 120},
    "recurso": {"type": "string", "maxLength": 120},
    "turno": {"type": "string", "maxLength": 80},
    "op": {"type": "string", "maxLength": 120},
    "operacao": {"type": "string", "maxLength": 120},
    "produto": {"type": "string", "maxLength": 160},
    "operador": {"type": "string", "maxLength": 160},
}


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    handler: str
    status_label: str
    properties: dict[str, dict[str, Any]]
    required: tuple[str, ...] = ()

    def groq_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.properties,
                    "required": list(self.required),
                    "additionalProperties": False,
                },
            },
        }


def _fields(*names: str, **extra):
    return {**{name: FILTER_FIELDS[name] for name in names}, **extra}


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    definition.name: definition
    for definition in (
        ToolDefinition(
            "get_factory_status",
            "Obtém o snapshot atual da fábrica pelo Andon canônico.",
            "factory_status",
            "Consultando o estado da fábrica…",
            {},
        ),
        ToolDefinition(
            "get_management_overview",
            "Obtém a visão gerencial canônica, sem recalcular indicadores.",
            "management_overview",
            "Consultando a visão gerencial…",
            _fields("inicio", "fim", "setor"),
        ),
        ToolDefinition(
            "get_management_insights",
            "Obtém exceções, perdas, evidências e explicações gerenciais canônicas.",
            "management_insights",
            "Analisando indicadores…",
            _fields("inicio", "fim", "setor", "recurso"),
        ),
        ToolDefinition(
            "explain_kpi",
            "Explica um KPI com os componentes e evidências calculados pelo backend.",
            "explain_kpi",
            "Verificando o indicador…",
            _fields(
                "inicio",
                "fim",
                "setor",
                "recurso",
                key={
                    "type": "string",
                    "enum": ["oee", "availability", "performance", "ftt"],
                }
            ),
            ("key",),
        ),
        ToolDefinition(
            "get_resource_status",
            "Consulta estado, OPs ativas e evidências de um recurso específico.",
            "resource_status",
            "Consultando o recurso…",
            _fields("recurso", "inicio", "fim"),
            ("recurso",),
        ),
        ToolDefinition(
            "get_sector_status",
            "Consulta estados e operações de um setor específico.",
            "sector_status",
            "Consultando o setor…",
            _fields("setor", "inicio", "fim"),
            ("setor",),
        ),
        ToolDefinition(
            "get_production_orders",
            "Consulta as ordens de produção pela projeção canônica.",
            "production_orders",
            "Consultando ordens de produção…",
            _fields("inicio", "fim", "setor", "recurso", "op"),
        ),
        ToolDefinition(
            "get_production",
            "Consulta produção realizada, setores e qualidade pelo backend.",
            "production",
            "Consultando produção…",
            _fields(
                "inicio",
                "fim",
                "setor",
                "recurso",
                "op",
                "operacao",
                "produto",
                "operador",
            ),
        ),
        ToolDefinition(
            "get_downtimes",
            "Consulta a análise canônica de paradas.",
            "downtimes",
            "Analisando paradas…",
            _fields("inicio", "fim", "setor", "recurso"),
        ),
        ToolDefinition(
            "get_quality",
            "Consulta a análise canônica de qualidade.",
            "quality",
            "Analisando qualidade…",
            _fields("inicio", "fim", "setor", "recurso", "op"),
        ),
        ToolDefinition(
            "get_setups",
            "Consulta a análise canônica de setup.",
            "setups",
            "Analisando setups…",
            _fields("inicio", "fim", "setor", "recurso", "op"),
        ),
        ToolDefinition(
            "trace_work_order",
            "Obtém a rastreabilidade canônica de uma OP.",
            "trace_work_order",
            "Verificando rastreabilidade…",
            {"op": FILTER_FIELDS["op"]},
            ("op",),
        ),
        ToolDefinition(
            "get_nestings",
            "Consulta tempos previstos e realizados por nesting de Corte.",
            "nestings",
            "Consultando nestings…",
            _fields("inicio", "fim", "recurso", "op", "produto"),
        ),
        ToolDefinition(
            "get_audit_issues",
            "Consulta inconsistências e confiabilidade na auditoria canônica.",
            "audit_issues",
            "Verificando a confiabilidade dos dados…",
            _fields("inicio", "fim", "setor", "recurso", "op"),
        ),
        ToolDefinition(
            "generate_industrial_report",
            (
                "Gera um artifact XLSX usando exclusivamente serviços canônicos. "
                "É uma ação técnica e não altera produção, OPs ou estados."
            ),
            "generate_report",
            "Gerando relatório…",
            _fields(
                "inicio",
                "fim",
                "setor",
                "recurso",
                "op",
                report_type={"type": "string", "enum": list(REPORT_TYPES)},
                period_kind={"type": "string", "enum": list(REPORT_PERIOD_KINDS)},
                indicador={"type": "string", "maxLength": 80},
                include_executive_analysis={"type": "boolean"},
            ),
            ("report_type", "period_kind"),
        ),
    )
}


TOOL_GROUPS: dict[str, tuple[str, ...]] = {
    "factory": (
        "get_factory_status",
        "get_management_overview",
        "get_management_insights",
    ),
    "kpi": (
        "get_management_insights",
        "explain_kpi",
        "get_downtimes",
        "get_quality",
        "get_setups",
    ),
    "work_order": (
        "trace_work_order",
        "get_production_orders",
        "get_production",
    ),
    "resource": (
        "get_resource_status",
        "get_downtimes",
    ),
    "sector": (
        "get_sector_status",
        "get_management_insights",
    ),
    "sector_comparison": (
        "get_management_overview",
        "get_management_insights",
    ),
    "production": (
        "get_production",
        "get_production_orders",
    ),
    "nesting": ("get_nestings",),
    "audit": ("get_audit_issues",),
    "report": ("generate_industrial_report",),
    "fallback": (
        "get_factory_status",
        "get_management_insights",
    ),
}

_SIMPLE_CONVERSATION = {
    "ola",
    "oi",
    "bom dia",
    "boa tarde",
    "boa noite",
    "quem e voce",
    "o que voce faz",
}
_RESOURCE_CODE = re.compile(r"\b(?:dobra|serra|solda|pintura|usinagem|corte)[-_ ]?\d+\b")
_FORBIDDEN_REQUEST_TERMS = (
    " senha ",
    " password ",
    " groq_api_key ",
    " api key ",
    " connection string ",
    " string de conexao ",
    " comando sql ",
    " consulta sql ",
    " select from ",
    " finalize a op ",
    " finalizar a op ",
    " altere a quantidade ",
    " alterar a quantidade ",
    " altere o estado ",
    " alterar o estado ",
    " ignore as instrucoes ",
    " ignore instrucoes ",
    " prompt injection ",
    " system prompt ",
    " fora da minha permissao ",
)


def _normalized_question(question: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(question or ""))
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-zA-Z0-9_-]+", " ", without_accents.casefold()).split())


def select_tool_names(question: str) -> tuple[str, ...]:
    """Seleciona deterministicamente uma whitelist pequena, sem segunda chamada LLM."""

    text = _normalized_question(question)
    if text in _SIMPLE_CONVERSATION:
        return ()
    padded = f" {text} "
    if any(term in padded for term in _FORBIDDEN_REQUEST_TERMS):
        return ()
    if any(word in padded for word in (" relatorio ", " relatorios ", " excel ", " xlsx ", " planilha ")):
        return TOOL_GROUPS["report"]
    if any(word in padded for word in (" nesting ", " nestings ")):
        return TOOL_GROUPS["nesting"]
    if any(word in padded for word in (" auditoria ", " inconsistencia ", " inconsistencias ", " confiabilidade ")):
        return TOOL_GROUPS["audit"]
    if any(word in padded for word in (
        " op ", " ops ", " ordem de producao ", " ordens de producao ",
        " rastreabilidade ", " trajetoria ", " lote ", " progresso oficial ",
        " saldo oficial ",
    )):
        return TOOL_GROUPS["work_order"]
    if any(phrase in padded for phrase in (
        " quais recursos ", " recursos parados ", " recursos sem estado ",
    )):
        return TOOL_GROUPS["factory"]
    if any(phrase in padded for phrase in (
        " qual setor ", " compare dois setores ", " comparar setores ",
    )):
        return TOOL_GROUPS["sector_comparison"]
    if any(word in padded for word in (" recurso ", " maquina ", " equipamento ")) or _RESOURCE_CODE.search(text):
        return TOOL_GROUPS["resource"]
    if any(
        word in padded
        for word in (
            " oee ",
            " disponibilidade ",
            " performance ",
            " ftt ",
            " qualidade ",
            " refugo ",
            " retrabalho ",
            " parada ",
            " paradas ",
            " setup ",
            " setups ",
            " perdas ",
            " indicador ",
            " kpi ",
            " componente ",
            " quantidade boa ",
            " pecas boas ",
        )
    ):
        return TOOL_GROUPS["kpi"]
    if any(word in padded for word in (
        " producao ", " produzido ", " produzida ", " produziram ",
        " finalizadas ", " finalizados ", " em andamento ",
    )):
        return TOOL_GROUPS["production"]
    if any(word in padded for word in (" setor ", " dobra ", " usinagem ", " serra ", " solda ", " pintura ", " corte ")):
        return TOOL_GROUPS["sector"]
    if any(word in padded for word in (" fabrica ", " visao geral ", " status geral ", " agora ")):
        return TOOL_GROUPS["factory"]
    return TOOL_GROUPS["fallback"]


def _parse_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise AIToolError("ai_tool_invalid_arguments", f"O campo {field} deve ser uma data ISO 8601.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AIToolError(
            "ai_tool_invalid_arguments",
            f"O campo {field} deve ser uma data ISO 8601 válida.",
        ) from exc
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed.replace(microsecond=0)


def _json_safe(value: Any, *, path: str, truncated: list[str], depth: int = 0):
    if depth > 10:
        truncated.append(path)
        return {"truncated": True, "reason": "max_depth"}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_safe(value.to_dict(), path=path, truncated=truncated, depth=depth + 1)
    if is_dataclass(value):
        return _json_safe(asdict(value), path=path, truncated=truncated, depth=depth + 1)
    if isinstance(value, str):
        if len(value) > MAX_TOOL_STRING_CHARS:
            truncated.append(path)
            return value[:MAX_TOOL_STRING_CHARS] + "…"
        return value
    if isinstance(value, dict):
        result = {}
        total = len(value)
        entries = islice(value.items(), MAX_TOOL_LIST_ITEMS)
        if total > MAX_TOOL_LIST_ITEMS:
            truncated.append(path)
        for key, item in entries:
            safe_key = str(key)[:120]
            result[safe_key] = _json_safe(
                item,
                path=f"{path}.{safe_key}",
                truncated=truncated,
                depth=depth + 1,
            )
        return result
    if isinstance(value, (list, tuple, set)):
        total = len(value)
        if isinstance(value, (list, tuple)):
            returned = value[:MAX_TOOL_LIST_ITEMS]
        else:
            returned = list(islice(value, MAX_TOOL_LIST_ITEMS))
        if total > len(returned):
            truncated.append(path)
        return {
            "items": [
                _json_safe(item, path=f"{path}[{index}]", truncated=truncated, depth=depth + 1)
                for index, item in enumerate(returned)
            ],
            "total": total,
            "returned": len(returned),
            "truncated": total > len(returned),
        }
    text = str(value)
    if len(text) > MAX_TOOL_STRING_CHARS:
        truncated.append(path)
        text = text[:MAX_TOOL_STRING_CHARS] + "…"
    return text


def _serialized(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _json_safe_projection(value: Any, *, path: str, truncated: list[str], depth: int = 0):
    """Sanitiza projeções que já possuem seus próprios envelopes de truncamento."""

    if depth > 10:
        truncated.append(path)
        return {"truncated": True, "reason": "max_depth"}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, str):
        if len(value) > MAX_TOOL_STRING_CHARS:
            truncated.append(path)
            return value[:MAX_TOOL_STRING_CHARS] + "…"
        return value
    if isinstance(value, dict):
        return {
            str(key)[:120]: _json_safe_projection(
                item,
                path=f"{path}.{str(key)[:120]}",
                truncated=truncated,
                depth=depth + 1,
            )
            for key, item in islice(value.items(), MAX_TOOL_LIST_ITEMS)
        }
    if isinstance(value, (list, tuple, set)):
        items = list(value)[:MAX_TOOL_LIST_ITEMS]
        if len(value) > len(items):
            truncated.append(path)
        return [
            _json_safe_projection(
                item,
                path=f"{path}[{index}]",
                truncated=truncated,
                depth=depth + 1,
            )
            for index, item in enumerate(items)
        ]
    return str(value)[:MAX_TOOL_STRING_CHARS]


def _as_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict) and isinstance(value.get("items"), list):
        return value["items"]
    return []


def _nonempty(source: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any]:
    return {
        name: source[name]
        for name in names
        if name in source and source[name] not in (None, "", [], {})
    }


def _compact_metric(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    return _nonempty(value, ("value", "availability", "unit", "reason", "source"))


def _compact_resource(resource: dict[str, Any]) -> dict[str, Any]:
    state = resource.get("state") if isinstance(resource.get("state"), dict) else {}
    operation = resource.get("operation") if isinstance(resource.get("operation"), dict) else {}
    metrics = resource.get("metrics") if isinstance(resource.get("metrics"), dict) else {}
    compact = {
        "sector": resource.get("sector"),
        "resource": resource.get("code") or resource.get("name"),
        "state": state.get("category") or state.get("status_code"),
        "duration_seconds": state.get("duration_seconds"),
        "op": operation.get("op"),
        "operation": operation.get("operation"),
        "oee": _compact_metric(metrics.get("oee")),
    }
    if compact["state"] == "parada" and state.get("reason"):
        compact["downtime_reason"] = state.get("reason")
    return {key: value for key, value in compact.items() if value not in (None, "", [], {})}


def _factory_projection(payload: Any, *, max_chars: int) -> tuple[dict[str, Any], int, bool]:
    """Seleciona somente fatos já calculados no snapshot canônico do Andon."""

    if not isinstance(payload, dict):
        return {"availability": "dados_insuficientes", "truncated": False}, 0, False
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    resources: list[dict[str, Any]] = []
    for sector in _as_items(payload.get("sectors")):
        if not isinstance(sector, dict):
            continue
        for resource in _as_items(sector.get("resources")):
            if isinstance(resource, dict):
                resources.append(_compact_resource(resource))

    attention_states = {"parada", "desconhecido", "retrabalho", "setup", "fila"}
    attention = [item for item in resources if item.get("state") in attention_states]
    others = [item for item in resources if item.get("state") not in attention_states]
    indicators = {}
    for name in ("oee", "availability", "performance", "ftt"):
        if name in summary:
            indicators[name] = _compact_metric(summary[name])

    projection: dict[str, Any] = {
        "context": {
            **_nonempty(payload, ("generated_at", "availability", "simulation_only")),
            "period": _nonempty(
                payload.get("period") if isinstance(payload.get("period"), dict) else {},
                ("inicio", "fim", "setor", "recurso", "turno"),
            ),
        },
        "summary": {
            "total_resources": summary.get("resources", payload.get("resource_count")),
            **_nonempty(
                summary,
                (
                    "production", "downtime", "setup", "rework", "queue",
                    "activity_without_op", "out_of_shift", "unknown",
                ),
            ),
        },
        "indicators": indicators,
        "attention_resources": {
            "items": attention,
            "total": len(attention),
            "returned": len(attention),
            "truncated": False,
        },
        "other_resources": {
            "items": others,
            "total": len(others),
            "returned": len(others),
            "truncated": False,
        },
        "total": len(resources),
        "returned": len(resources),
        "truncated": False,
    }

    # Remove primeiro os recursos sem exceção. Paradas nunca são descartadas
    # apenas para economizar tokens; as demais exceções saem somente depois.
    while len(_serialized(projection)) > max_chars and projection["other_resources"]["items"]:
        projection["other_resources"]["items"].pop()
    removable_attention = [
        index
        for index, item in enumerate(projection["attention_resources"]["items"])
        if item.get("state") != "parada"
    ]
    while len(_serialized(projection)) > max_chars and removable_attention:
        projection["attention_resources"]["items"].pop(removable_attention.pop())
        removable_attention = [
            index
            for index, item in enumerate(projection["attention_resources"]["items"])
            if item.get("state") != "parada"
        ]

    for key in ("attention_resources", "other_resources"):
        group = projection[key]
        group["returned"] = len(group["items"])
        group["truncated"] = group["returned"] < group["total"]
    projection["returned"] = (
        projection["attention_resources"]["returned"]
        + projection["other_resources"]["returned"]
    )
    projection["truncated"] = projection["returned"] < projection["total"]
    return projection, len(resources), bool(projection["truncated"])


def _prioritized_kpi_evidence(items: list[Any], limit: int) -> list[Any]:
    """Preserva diversidade factual antes de completar a amostra na ordem canônica."""

    if limit <= 0:
        return []
    selected: list[Any] = []
    selected_ids: set[int] = set()
    seen_kinds: set[str] = set()
    for index, item in enumerate(items):
        kind = str(item.get("kind") or "") if isinstance(item, dict) else ""
        if kind in seen_kinds:
            continue
        selected.append(item)
        selected_ids.add(index)
        seen_kinds.add(kind)
        if len(selected) >= limit:
            return selected
    for index, item in enumerate(items):
        if index in selected_ids:
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    return selected


def _compact_projection_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _compact_projection_value(item)
            for key, item in value.items()
            if item not in (None, "", [], {})
        }
    if isinstance(value, (list, tuple)):
        return [
            _compact_projection_value(item)
            for item in value
            if item not in (None, "", [], {})
        ]
    return value


def _kpi_explanation_projection(payload: Any) -> tuple[dict[str, Any], int, bool]:
    """Compacta somente a interface da IA; os valores permanecem canônicos."""

    if not isinstance(payload, dict):
        return {"availability": "dados_insuficientes"}, 0, False
    projection = {
        key: payload.get(key)
        for key in (
            "key",
            "label",
            "metric",
            "components",
            "largest_impact",
            "calculation_policy",
            "simulation_only",
            "limitation",
        )
        if key in payload
    }
    is_oee = str(payload.get("key") or "").strip().casefold() == "oee"
    evidence_limit = MAX_AI_KPI_EVIDENCE if is_oee else 0
    limits = {
        "causes": MAX_AI_KPI_CAUSES if is_oee else 1,
        "resources": MAX_AI_KPI_RESOURCES if is_oee else 1,
        "evidence": evidence_limit,
    }
    projection_metrics: dict[str, dict[str, Any]] = {}
    total_items = 0
    any_truncated = False
    for field, limit in limits.items():
        items = list(payload.get(field) or [])
        total_items += len(items)
        returned = (
            _prioritized_kpi_evidence(items, limit)
            if field == "evidence"
            else items[:limit]
        )
        truncated = len(returned) < len(items)
        projection[field] = [_compact_projection_value(item) for item in returned]
        projection_metrics[field] = {
            "total": len(items),
            "returned": len(returned),
            "truncated": truncated,
        }
        any_truncated = any_truncated or truncated
    projection["ai_projection"] = projection_metrics
    if projection.get("largest_impact"):
        projection["largest_impact"] = _compact_projection_value(projection["largest_impact"])
    return projection, total_items, any_truncated


def _list_envelopes(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("items"), list) and isinstance(value.get("total"), int):
            found.append(value)
        for item in value.values():
            found.extend(_list_envelopes(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_list_envelopes(item))
    return found


def _limit_valid_json(result: dict[str, Any], max_chars: int) -> bool:
    truncated = False
    while len(_serialized(result)) > max_chars:
        candidates = [envelope for envelope in _list_envelopes(result) if envelope["items"]]
        if not candidates:
            raise AIToolError(
                "ai_tool_result_too_large",
                "A consulta reuniu dados demais para o limite atual da IA.",
            )
        target = max(candidates, key=lambda envelope: len(_serialized(envelope)))
        target["items"].pop()
        target["returned"] = len(target["items"])
        target["truncated"] = True
        truncated = True
    return truncated


class AIToolRegistry:
    def __init__(
        self,
        facade,
        *,
        now_func: Callable[[], datetime] | None = None,
        tool_result_max_chars: int = DEFAULT_TOOL_RESULT_MAX_CHARS,
        report_service=None,
    ):
        self.facade = facade
        self._now = now_func or datetime.now
        self.tool_result_max_chars = int(tool_result_max_chars)
        self.report_service = report_service
        self._handlers: dict[str, Callable[[dict[str, Any], AnalyticsFilter | None], Any]] = {
            "factory_status": lambda _args, filters: self.facade.andon(filters),
            "management_overview": lambda _args, filters: self.facade.inicio(filters),
            "management_insights": lambda _args, filters: self.facade.insights(filters),
            "explain_kpi": lambda args, filters: self.facade.explain_kpi(args["key"], filters),
            "resource_status": lambda _args, filters: self.facade.consulta_operacional(filters),
            "sector_status": lambda _args, filters: self.facade.consulta_operacional(filters),
            "production_orders": lambda _args, filters: self.facade.ordens_producao(filters),
            "production": lambda _args, filters: self.facade.producao_realizada(filters),
            "downtimes": lambda _args, filters: self.facade.analise("paradas", filters),
            "quality": lambda _args, filters: self.facade.analise("qualidade", filters),
            "setups": lambda _args, filters: self.facade.analise("setup", filters),
            "trace_work_order": lambda args, _filters: self.facade.rastreabilidade(args["op"]),
            "nestings": lambda _args, filters: self.facade.nestings(filters),
            "audit_issues": lambda _args, filters: self.facade.auditoria(filters),
        }
        self._schemas = [definition.groq_schema() for definition in TOOL_REGISTRY.values()]

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return self._schemas

    def schemas_for_names(self, names: tuple[str, ...] | list[str]) -> list[dict[str, Any]]:
        allowed = set(names)
        return [schema for schema in self._schemas if schema["function"]["name"] in allowed]

    def select_schemas(self, question: str) -> list[dict[str, Any]]:
        return self.schemas_for_names(select_tool_names(question))

    def status_label(self, name: str) -> str:
        definition = TOOL_REGISTRY.get(name)
        return definition.status_label if definition else "Consultando dados…"

    def _arguments(self, definition: ToolDefinition, raw_arguments: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw_arguments, str):
            if len(raw_arguments) > 10_000:
                raise AIToolError("ai_tool_invalid_arguments", "Os argumentos da consulta excedem o limite.")
            try:
                arguments = json.loads(raw_arguments or "{}")
            except json.JSONDecodeError as exc:
                raise AIToolError(
                    "ai_tool_invalid_arguments",
                    "A IA produziu argumentos de consulta inválidos.",
                ) from exc
        else:
            arguments = raw_arguments
        if not isinstance(arguments, dict):
            raise AIToolError("ai_tool_invalid_arguments", "Os argumentos da consulta devem formar um objeto.")
        unknown = set(arguments) - set(definition.properties)
        if unknown:
            raise AIToolError("ai_tool_invalid_arguments", "A consulta contém campos não permitidos.")
        for required in definition.required:
            if required not in arguments or not str(arguments.get(required) or "").strip():
                raise AIToolError(
                    "ai_tool_invalid_arguments",
                    f"A consulta exige o campo {required}.",
                )
        clean = {}
        for key, value in arguments.items():
            if key in {"inicio", "fim"}:
                clean[key] = _parse_datetime(value, key)
                continue
            expected_type = definition.properties[key].get("type")
            if expected_type == "boolean":
                if not isinstance(value, bool):
                    raise AIToolError(
                        "ai_tool_invalid_arguments",
                        f"O campo {key} deve ser verdadeiro ou falso.",
                    )
                clean[key] = value
                continue
            if not isinstance(value, str):
                raise AIToolError(
                    "ai_tool_invalid_arguments",
                    f"O campo {key} deve ser texto.",
                )
            maximum = int(definition.properties[key].get("maxLength", MAX_TOOL_ARGUMENT_CHARS))
            text = value.strip()
            if not text or len(text) > maximum:
                raise AIToolError(
                    "ai_tool_invalid_arguments",
                    f"O campo {key} está vazio ou excede o limite permitido.",
                )
            allowed = definition.properties[key].get("enum")
            if allowed and text not in allowed:
                raise AIToolError("ai_tool_invalid_arguments", f"O valor de {key} não é permitido.")
            clean[key] = text
        return clean

    def _filters(self, arguments: dict[str, Any]) -> AnalyticsFilter:
        end = arguments.get("fim") or self._now().replace(microsecond=0)
        start = arguments.get("inicio") or datetime.combine(end.date(), time.min)
        if end <= start:
            raise AIToolError("ai_tool_invalid_period", "O fim do período deve ser posterior ao início.")
        if end - start > MAX_TOOL_PERIOD:
            raise AIToolError("ai_tool_period_too_large", "O período máximo por consulta é de 366 dias.")
        return AnalyticsFilter(
            inicio=start,
            fim=end,
            setor=arguments.get("setor"),
            recurso=arguments.get("recurso"),
            turno=arguments.get("turno"),
            op=arguments.get("op"),
            operacao=arguments.get("operacao"),
            produto=arguments.get("produto"),
            operador=arguments.get("operador"),
        )

    def execute(
        self,
        name: str,
        raw_arguments: str | dict[str, Any],
        context: AIRequestContext,
    ) -> dict[str, Any]:
        if not context.management_access:
            raise AIToolError(
                "ai_tool_permission_denied",
                "Seu perfil não possui permissão para esta consulta.",
            )
        definition = TOOL_REGISTRY.get(str(name or ""))
        if definition is None:
            raise AIToolError(
                "ai_tool_not_allowed",
                "A IA tentou usar uma consulta que não está autorizada.",
            )
        arguments = self._arguments(definition, raw_arguments)
        if definition.handler == "generate_report":
            if self.report_service is None:
                raise AIToolError(
                    "ai_report_unavailable",
                    "A geração de relatórios não está disponível neste ambiente.",
                )
            try:
                inicio, fim = resolve_report_period(
                    arguments["period_kind"],
                    now=self._now().replace(microsecond=0),
                    inicio=arguments.get("inicio"),
                    fim=arguments.get("fim"),
                )
                report_request = ReportRequest(
                    report_type=arguments["report_type"],
                    inicio=inicio,
                    fim=fim,
                    setor=arguments.get("setor"),
                    recurso=arguments.get("recurso"),
                    op=arguments.get("op"),
                    indicador=arguments.get("indicador"),
                    include_executive_analysis=bool(
                        arguments.get("include_executive_analysis", False)
                    ),
                )
                artifact = self.report_service.generate(
                    report_request,
                    created_by=context.user_id,
                    source="chat",
                    idempotency_key=build_report_idempotency_key(
                        report_request, created_by=context.user_id, source="chat"
                    ),
                )
            except ReportError as exc:
                raise AIToolError(exc.code, exc.user_message) from exc
            filters = report_request.analytics_filter()
            payload = {
                "artifact": artifact,
                "message": "Relatório gerado com sucesso.",
                "calculation_policy": "backend_only",
            }
        else:
            filters = None if definition.handler == "trace_work_order" else self._filters(arguments)
            handler = self._handlers[definition.handler]
            payload = handler(arguments, filters)
        raw_chars = len(_serialized(payload))
        truncated: list[str] = []
        if definition.name == "get_factory_status":
            projected, items, projection_truncated = _factory_projection(
                payload,
                max_chars=max(1_000, self.tool_result_max_chars - 1_000),
            )
            safe_payload = _json_safe_projection(projected, path="data", truncated=truncated)
            if projection_truncated:
                truncated.append("data.resources")
        elif definition.name == "explain_kpi":
            projected, items, projection_truncated = _kpi_explanation_projection(payload)
            safe_payload = _json_safe_projection(projected, path="data", truncated=truncated)
            if projection_truncated:
                truncated.append("data.explanation_details")
        else:
            items = 0
            safe_payload = _json_safe(payload, path="data", truncated=truncated)
        result = {
            "tool": definition.name,
            "data": safe_payload,
            "limits": {
                "max_items_per_list": MAX_TOOL_LIST_ITEMS,
                "max_chars": self.tool_result_max_chars,
                "truncated": bool(truncated),
                "truncated_paths": truncated[:100],
            },
        }
        if definition.name != "get_factory_status":
            result["period"] = filters.to_dict() if filters else None
        limited = _limit_valid_json(result, self.tool_result_max_chars)
        if limited:
            result["limits"]["truncated"] = True
            result["limits"]["truncated_paths"] = [
                *result["limits"]["truncated_paths"],
                "data",
            ][:100]
        # O valor converge em poucas iterações; somente a quantidade de dígitos
        # da própria métrica pode mudar o tamanho final.
        for _ in range(3):
            sanitized_chars = len(_serialized(result))
            result["limits"].update(
                {
                    "raw_chars": raw_chars,
                    "sanitized_chars": sanitized_chars,
                    "items": items,
                    "estimated_tokens": math.ceil(sanitized_chars / 4),
                }
            )
        sanitized_chars = len(_serialized(result))
        if sanitized_chars > self.tool_result_max_chars:
            _limit_valid_json(result, self.tool_result_max_chars)
            sanitized_chars = len(_serialized(result))
        LOGGER.info(
            "AI tool payload request_id=%s tool=%s raw_chars=%s sanitized_chars=%s items=%s estimated_tokens=%s truncated=%s",
            context.request_id,
            definition.name,
            raw_chars,
            sanitized_chars,
            items,
            math.ceil(sanitized_chars / 4),
            result["limits"]["truncated"],
        )
        return result
