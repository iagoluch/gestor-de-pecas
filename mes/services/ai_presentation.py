"""Apresentação determinística da IA Industrial: dado legível, nunca estrutura interna.

Duas fronteiras, ambas sem LLM:

* ``present_tool_result`` converte o resultado canônico de uma tool (já
  sanitizado por ``AIToolRegistry``) na leitura que o modelo recebe: rótulos em
  português no lugar de chaves técnicas, percentuais/durações/datas no padrão
  brasileiro, estados e situações do dado humanizados, sem IDs, envelopes de
  truncamento, nome de tool ou metadados de limite. O valor canônico não é
  recalculado — só formatado.
* ``sanitize_assistant_text`` / ``AssistantTextStream`` limpam o texto final do
  modelo antes de chegar ao usuário e ao histórico: blocos de código, JSON cru,
  nomes de tools, pares ``chave=valor`` técnicos, identificadores snake_case,
  datas ISO e segundos brutos. O prompt também proíbe isso, mas o prompt é
  probabilístico; esta camada é a garantia.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
import re
from typing import Any

from mes.domain import DataAvailability
from mes.services.andon import STATE_LABELS
from mes.services.telegram_presenter import format_duration


AVAILABILITY_LABELS = {
    DataAvailability.AVAILABLE.value: "Disponível",
    DataAvailability.PARTIAL.value: "Parcial",
    DataAvailability.NO_RECORDS.value: "Sem registros no período",
    DataAvailability.INSUFFICIENT_DATA.value: "Dados insuficientes",
    DataAvailability.NOT_CONFIGURED.value: "Não configurado",
    DataAvailability.NOT_APPLICABLE.value: "Não se aplica",
}

#: Origem interna do dado em linguagem de gestão. Nome de tabela nunca chega ao
#: usuário; origem desconhecida é omitida em vez de exibida crua.
SOURCE_LABELS = {
    "eventos_estado_recurso": "estado físico do recurso",
    "timeline_apontamentos_fallback": "apontamentos (histórico de reserva)",
    "eventos_quantidade_producao": "eventos de quantidade de produção",
    "apontamentos_operacionais_fallback": "apontamentos operacionais (reserva)",
    "calendario_x_estado_recurso": "calendário confrontado com o estado do recurso",
    "estado_canonico": "estado oficial do recurso",
}

SEVERITY_LABELS = {
    "info": "Informativo",
    "informativa": "Informativa",
    "aviso": "Aviso",
    "atencao": "Atenção",
    "alta": "Alta",
    "erro": "Erro",
    "critico": "Crítico",
}

VALUE_LABELS = {**STATE_LABELS, **AVAILABILITY_LABELS, **SEVERITY_LABELS}

#: Chaves compostas cuja tradução palavra a palavra ficaria fora de ordem.
KEY_LABELS = {
    "attention_resources": "Recursos em atenção",
    "other_resources": "Demais recursos",
    "total_resources": "Total de recursos",
    "resource_count": "Total de recursos",
    "downtime_reason": "Motivo da parada",
    "largest_impact": "Maior impacto",
    "activity_without_op": "Atividade sem OP",
    "out_of_shift": "Fora de turno",
    "no_demand": "Sem demanda",
    "sem_demanda": "Sem demanda",
    "generated_at": "Gerado em",
    "started_at": "Início",
    "good_quantity": "Quantidade boa",
    "scrap_quantity": "Quantidade de refugo",
    "rework_quantity": "Quantidade de retrabalho",
    "planned_quantity": "Quantidade planejada",
    "planned_downtime": "Parada planejada",
    "unplanned_downtime": "Parada não planejada",
    "simulation_only": "Somente simulação",
    "by_resource": "Por recurso",
    "by_sector": "Por setor",
    "by_reason": "Por motivo",
    "by_severity": "Por severidade",
    "impact_value": "Valor do impacto",
    "impact_unit": "Unidade do impacto",
    "product_description": "Descrição do produto",
    "operation_description": "Descrição da operação",
    "active_operations": "Operações ativas",
    "status_code": "Situação",
    "display_label": "Descrição",
    "label": "Descrição",
    "key": "Indicador",
    "message": "Mensagem",
    "items": "Itens",
}

#: Tradução palavra a palavra para chaves técnicas sem rótulo dedicado.
WORD_LABELS = {
    "resource": "recurso", "resources": "recursos", "sector": "setor", "sectors": "setores",
    "state": "estado", "states": "estados", "status": "situação", "category": "categoria",
    "categoria": "categoria", "duration": "duração", "duracao": "duração", "time": "tempo",
    "op": "OP", "ops": "OPs", "oee": "OEE", "ftt": "FTT", "kpi": "KPI", "kpis": "KPIs",
    "mtbf": "MTBF", "mttr": "MTTR", "operation": "operação", "operations": "operações",
    "operacao": "operação", "operacoes": "operações", "product": "produto",
    "description": "descrição", "descricao": "descrição", "quantity": "quantidade",
    "good": "boa", "scrap": "refugo", "rework": "retrabalho", "production": "produção",
    "producao": "produção", "downtime": "parada", "downtimes": "paradas", "queue": "fila",
    "planned": "planejado", "planejado": "planejado", "planejada": "planejada",
    "actual": "real", "standard": "padrão", "padrao": "padrão", "shift": "turno",
    "activity": "atividade", "without": "sem", "demand": "demanda", "count": "quantidade",
    "value": "valor", "unit": "unidade", "reason": "justificativa", "reasons": "motivos",
    "source": "origem", "sources": "origens", "fonte": "origem", "start": "início",
    "end": "fim", "inicio": "início", "period": "período", "periodo": "período",
    "summary": "resumo", "context": "contexto", "indicators": "indicadores", "metrics": "indicadores",
    "metric": "indicador", "evidence": "evidências", "causes": "causas", "cause": "causa",
    "impact": "impacto", "components": "componentes", "name": "nome", "code": "código",
    "codigo": "código", "severity": "severidade", "operator": "operador", "order": "ordem",
    "orders": "ordens", "quality": "qualidade", "availability": "disponibilidade",
    "physical": "físico", "percentual": "(%)", "percentage": "(%)", "percent": "(%)",
    "utilizacao": "utilização", "utilization": "utilização", "simulation": "simulação",
    "limitation": "limitação", "issues": "inconsistências", "by": "por", "total": "total",
    "segments": "trechos", "losses": "perdas", "thresholds": "limites", "capacity": "capacidade",
    "load": "carga", "remaining": "restante", "available": "disponível", "worked": "trabalhado",
    "operational": "operacional", "unknown": "desconhecido", "running": "em produção",
    "reliability": "confiabilidade", "confiabilidade": "confiabilidade", "sem": "sem",
    "manutencao": "manutenção", "estacao": "estação", "maquina": "máquina",
    "reparos": "reparos", "concluidos": "concluídos", "sequencia": "sequência",
    "repeticao": "repetição", "prioridade": "prioridade", "entrega": "entrega",
}

#: Metadados internos que não informam nada ao gestor e só convidam o modelo a
#: citar estrutura: identificadores, versões, políticas de cálculo e de UI.
HIDDEN_KEYS = {
    "id", "tool", "limits", "ai_projection", "calculation_policy", "ui_policy",
    "schema_version", "rule_version", "source_field", "total_field", "color",
    "colors", "presentation_only", "frontend_layout", "download_url", "url",
    "telegram_destination_id", "truncated_paths",
    # Contadores de truncamento viram a observação de lista parcial.
    "returned", "truncated",
}
_HIDDEN_SUFFIXES = ("_id", "_ids", "_url", "_ui_tokens", "_colors", "_policy")
_SECONDS_SUFFIXES = ("_seconds", "_segundos")
_METRIC_KEYS = {"value", "availability", "unit", "reason", "source", "label"}
_ENVELOPE_KEYS = {"items", "total", "returned", "truncated"}
_SOURCE_KEYS = {"source", "fonte", "physical_state_source", "result_origin"}

_SNAKE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")
_ISO_DATETIME = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)

PARTIAL_NOTE = "Lista parcial: exibidos {returned} de {total} itens."
TRUNCATED_NOTE = (
    "Parte dos dados foi omitida por limite de tamanho; trate as listas como parciais."
)


# --- Formatação de valores ---------------------------------------------------


def format_decimal(value: float, places: int = 2) -> str:
    """Número no padrão brasileiro, sem zeros finais inúteis."""

    quantum = Decimal(1).scaleb(-places)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    rendered = f"{rounded:.{places}f}"
    if places:
        rendered = rendered.rstrip("0").rstrip(".")
    integer, _, fraction = rendered.partition(".")
    sign = "-" if integer.startswith("-") else ""
    digits = integer.lstrip("-")
    grouped = f"{int(digits or 0):,}".replace(",", ".")
    return f"{sign}{grouped}" + (f",{fraction}" if fraction else "")


def format_seconds(value: Any) -> str:
    """Duração legível sem perder segundos em tempos curtos (ex.: ritmo por peça)."""

    seconds = float(value)
    sign = "-" if seconds < 0 else ""
    total = int(round(abs(seconds)))
    if total < 60:
        return f"{sign}{total}s"
    if total < 600:
        minutes, rest = divmod(total, 60)
        return f"{sign}{minutes}min {rest}s" if rest else f"{sign}{minutes}min"
    return sign + format_duration(total)


def format_datetime_text(value: str) -> str | None:
    match = _ISO_DATETIME.match(value.strip())
    if not match:
        return None
    year, month, day, hour, minute = match.groups()
    rendered = f"{day}/{month}/{year}"
    return f"{rendered} {hour}:{minute}" if hour is not None else rendered


def humanize_identifier(value: str, *, capitalize: bool = False) -> str:
    """``operador_solda_estacao_3`` → ``operador solda estação 3``."""

    raw = str(value)
    known = VALUE_LABELS.get(raw) or SOURCE_LABELS.get(raw)
    if known:
        return known
    words = [WORD_LABELS.get(part, part) for part in raw.split("_") if part]
    text = " ".join(words)
    return text[:1].upper() + text[1:] if capitalize else text


def key_label(key: str) -> str:
    raw = str(key)
    if raw in KEY_LABELS:
        return KEY_LABELS[raw]
    return humanize_identifier(raw, capitalize=True) if raw else raw


def _format_number(value: float | int, unit: str | None = None) -> str:
    if unit == "%":
        return format_decimal(value, 1) + "%"
    rendered = format_decimal(value, 2) if isinstance(value, float) else format_decimal(value, 0)
    if unit in (None, "", "count"):
        return rendered
    if unit in ("s", "seconds", "segundos"):
        return format_seconds(value)
    return f"{rendered} {unit}"


def _present_scalar(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, bool):
        return "sim" if value else "não"
    if isinstance(value, (int, float)):
        if key and key.endswith(_SECONDS_SUFFIXES):
            return format_seconds(value)
        return value if isinstance(value, int) else format_decimal(value, 2)
    if isinstance(value, str):
        if key in _SOURCE_KEYS:
            return SOURCE_LABELS.get(value) or (None if _SNAKE.match(value) else value)
        if value in VALUE_LABELS:
            return VALUE_LABELS[value]
        formatted_date = format_datetime_text(value)
        if formatted_date:
            return formatted_date
        if _SNAKE.match(value):
            return humanize_identifier(value, capitalize=True)
        return value
    return value


def _metric_text(metric: dict[str, Any]) -> str:
    value = metric.get("value")
    availability = metric.get("availability")
    reason = metric.get("reason")
    parts: list[str] = []
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        parts.append(_format_number(value, metric.get("unit")))
    elif value is not None:
        parts.append(str(_present_scalar(value)))
    else:
        parts.append("sem valor")
    if availability and availability != DataAvailability.AVAILABLE.value:
        parts.append(f"({AVAILABILITY_LABELS.get(availability, humanize_identifier(availability))})")
    if reason:
        parts.append(f"— {_present_scalar(reason)}")
    return " ".join(parts)


def _is_metric(value: dict[str, Any]) -> bool:
    return "value" in value and set(value) <= _METRIC_KEYS


def _is_envelope(value: dict[str, Any]) -> bool:
    return isinstance(value.get("items"), list) and set(value) <= _ENVELOPE_KEYS


def _hidden(key: str) -> bool:
    return key in HIDDEN_KEYS or key.endswith(_HIDDEN_SUFFIXES)


def _key_for_seconds(key: str) -> str:
    base = key
    for suffix in _SECONDS_SUFFIXES:
        if key.endswith(suffix):
            base = key[: -len(suffix)]
            break
    if not base or base in ("duration", "duracao", "total"):
        return "Duração" if base != "total" else "Tempo total"
    label = key_label(base)
    lowered = label.casefold()
    if "tempo" in lowered or "duração" in lowered or label.isupper():
        return label
    return f"{label} (duração)"


def present_value(value: Any, *, key: str | None = None, depth: int = 0) -> Any:
    if depth > 12:
        return None
    if isinstance(value, dict):
        if _is_metric(value):
            return _metric_text(value)
        if _is_envelope(value):
            items = present_value(value["items"], key=key, depth=depth + 1)
            total = value.get("total")
            returned = value.get("returned", len(value["items"]))
            if value.get("truncated") and isinstance(total, int):
                return {
                    "Itens": items,
                    "Observação": PARTIAL_NOTE.format(returned=returned, total=total),
                }
            return items
        presented: dict[str, Any] = {}
        for raw_key, item in value.items():
            name = str(raw_key)
            if _hidden(name) or item in (None, "", [], {}):
                continue
            if name in ("availability",) and isinstance(item, str):
                label = "Situação do dado"
            elif name.endswith(_SECONDS_SUFFIXES) and isinstance(item, (int, float)):
                label = _key_for_seconds(name)
            else:
                label = key_label(name)
            rendered = present_value(item, key=name, depth=depth + 1)
            if rendered in (None, "", [], {}):
                continue
            presented[label] = rendered
        return presented
    if isinstance(value, (list, tuple)):
        return [
            rendered
            for rendered in (present_value(item, key=key, depth=depth + 1) for item in value)
            if rendered not in (None, "", [], {})
        ]
    return _present_scalar(value, key=key)


def present_tool_result(result: Any) -> dict[str, Any]:
    """Leitura que o modelo recebe de uma tool, sem estrutura técnica."""

    if not isinstance(result, dict):
        return {"Dados": present_value(result)}
    error = result.get("error")
    if isinstance(error, dict):
        return {
            "Consulta não concluída": str(
                error.get("message") or "Não foi possível obter os dados desta consulta."
            )
        }
    presented: dict[str, Any] = {}
    period = present_value(result.get("period")) if result.get("period") else None
    if period:
        presented["Período consultado"] = period
    data = present_value(result.get("data"))
    presented["Dados"] = data if data not in (None, "", [], {}) else "Sem dados retornados."
    limits = result.get("limits") if isinstance(result.get("limits"), dict) else {}
    if limits.get("truncated"):
        presented["Observação"] = TRUNCATED_NOTE
    return presented


# --- Sanitização do texto final ------------------------------------------------


_TOOL_NAMES = (
    "get_factory_status", "get_management_overview", "get_management_insights",
    "explain_kpi", "get_resource_status", "get_sector_status", "get_production_orders",
    "get_production", "get_downtimes", "get_quality", "get_setups", "trace_work_order",
    "get_nestings", "get_audit_issues", "generate_industrial_report",
)
_TOOL_NAME_RE = re.compile(
    r"`?\b(?:" + "|".join(sorted(map(re.escape, _TOOL_NAMES), key=len, reverse=True)) + r")\b`?"
)
_FENCE_RE = re.compile(r"```[^\n`]*\n?[\s\S]*?(?:```|$)")
_INLINE_CODE_RE = re.compile(r"`([^`\n]{1,200})`")
#: Campos técnicos em inglês que só aparecem em texto quando o modelo copia o payload.
_TECH_FIELDS = {
    "availability", "reason", "source", "status", "state", "category", "value", "unit",
    "key", "label", "severity", "kind", "code", "total", "returned", "truncated",
}
_IDENT = r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"
_PAIR_RE = re.compile(
    rf"(?<![\w/.@\\-])(?P<key>{_IDENT})\s*(?P<sep>=|:)[ \t]*[`\"']?(?P<value>{_IDENT}(?![\w/@-]))?[`\"']?"
)
_SNAKE_TOKEN_RE = re.compile(r"(?<![\w/.@\\-])[a-z][a-z0-9]*(?:_[a-z0-9]+)+(?![\w/@\\-])")
_ISO_TEXT_RE = re.compile(
    r"(?<![\w/])\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?(?![\w/])"
)
_RAW_SECONDS_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(?:segundos|seconds|seg)\b", re.IGNORECASE)
_DOT_PERCENT_RE = re.compile(r"(?<![\d.,])(\d+)\.(\d+)\s?%")
#: Decimal com ponto que não é milhar brasileiro (exatamente três dígitos).
_DOT_DECIMAL_RE = re.compile(r"(?<![\d.,/])(\d+)\.(\d{1,2}|\d{4,})(?![\d.,/]|\.\d)")
_STATE_KEYS = {"availability", "status", "state", "category", "estado", "situacao"}
_SOURCE_TEXT_KEYS = {"source", "fonte", "sources", "fontes", "tabela", "table", "tool", "tools"}


def _strip_json_objects(text: str) -> str:
    """Remove objetos JSON crus (``{"chave": ...}``), inclusive aninhados."""

    output: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in "{[":
            probe = index + 1
            while probe < length and text[probe] in " \t\r\n":
                probe += 1
            looks_json = probe < length and (
                (char == "{" and text[probe] == '"')
                or (char == "[" and text[probe] == "{")
            )
            if looks_json:
                depth = 0
                in_string = False
                cursor = index
                while cursor < length:
                    current = text[cursor]
                    if in_string:
                        if current == "\\":
                            cursor += 1
                        elif current == '"':
                            in_string = False
                    elif current == '"':
                        in_string = True
                    elif current in "{[":
                        depth += 1
                    elif current in "}]":
                        depth -= 1
                        if depth == 0:
                            break
                    cursor += 1
                index = cursor + 1
                continue
        output.append(char)
        index += 1
    return "".join(output)


def _replace_pair(match: re.Match[str]) -> str:
    key = match.group("key")
    separator = match.group("sep")
    value = match.group("value")
    technical_key = "_" in key or key in _TECH_FIELDS or key in _SOURCE_TEXT_KEYS
    # ``:`` é pontuação natural em português; só vira par técnico com chave técnica.
    if separator == ":" and not technical_key:
        return match.group(0)
    if separator == "=" and not technical_key and not value:
        return match.group(0)
    if key in _SOURCE_TEXT_KEYS:
        if value and value in SOURCE_LABELS:
            return f"origem: {SOURCE_LABELS[value]}"
        return "" if value else match.group(0)
    rendered_value = humanize_identifier(value) if value else ""
    if key in _STATE_KEYS:
        return rendered_value if value else match.group(0)
    label = key_label(key)
    if not value:
        return f"{label}: "
    return f"{label}: {rendered_value}"


def _replace_snake(match: re.Match[str]) -> str:
    return humanize_identifier(match.group(0))


def _replace_iso(match: re.Match[str]) -> str:
    return format_datetime_text(match.group(0)) or match.group(0)


def _replace_raw_seconds(match: re.Match[str]) -> str:
    number = float(match.group(1).replace(",", "."))
    if number < 60:
        return match.group(0)
    return format_seconds(number)


def _replace_dot_percent(match: re.Match[str]) -> str:
    return format_decimal(float(f"{match.group(1)}.{match.group(2)}"), 1) + "%"


def _replace_dot_decimal(match: re.Match[str]) -> str:
    return f"{match.group(1)},{match.group(2)}"


def _tidy(text: str) -> str:
    return (
        re.sub(r"\(\s*\)|\[\s*\]", "", text)
        .replace(" ,", ",")
        .replace(" .", ".")
    )


def sanitize_fragment(text: str) -> str:
    """Sanitiza um trecho sem aparar as bordas (seguro para streaming)."""

    if not text:
        return text
    cleaned = _FENCE_RE.sub("", text)
    cleaned = _strip_json_objects(cleaned)
    cleaned = _TOOL_NAME_RE.sub("consulta do sistema", cleaned)
    cleaned = _INLINE_CODE_RE.sub(r"\1", cleaned)
    cleaned = _ISO_TEXT_RE.sub(_replace_iso, cleaned)
    cleaned = _PAIR_RE.sub(_replace_pair, cleaned)
    cleaned = _SNAKE_TOKEN_RE.sub(_replace_snake, cleaned)
    cleaned = _RAW_SECONDS_RE.sub(_replace_raw_seconds, cleaned)
    cleaned = _DOT_PERCENT_RE.sub(_replace_dot_percent, cleaned)
    cleaned = _DOT_DECIMAL_RE.sub(_replace_dot_decimal, cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return _tidy(cleaned)


def sanitize_assistant_text(text: str) -> str:
    """Texto final do assistente, pronto para leitura gerencial e persistência."""

    cleaned = sanitize_fragment(str(text or ""))
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


_BOUNDARY_RE = re.compile(r"[.!?;][ \t]+|\n")


def _balanced(prefix: str) -> bool:
    if prefix.count("```") % 2:
        return False
    if prefix.replace("```", "").count("`") % 2:
        return False
    return prefix.count("{") <= prefix.count("}") and prefix.count("[") <= prefix.count("]")


class AssistantTextStream:
    """Libera deltas sanitizados somente em fronteiras seguras de frase.

    Regras como ``chave = valor`` ou um bloco de código podem chegar partidas
    entre deltas; o trecho só é liberado quando nenhuma delas pode estar aberta.
    O texto persistido continua sendo ``sanitize_assistant_text`` do total.
    """

    def __init__(self):
        self._pending = ""
        self._emitted_any = False

    def feed(self, delta: str) -> str:
        self._pending += str(delta or "")
        cut = 0
        for match in _BOUNDARY_RE.finditer(self._pending):
            if _balanced(self._pending[: match.end()]):
                cut = match.end()
        if not cut:
            return ""
        ready, self._pending = self._pending[:cut], self._pending[cut:]
        return self._emit(ready)

    def flush(self) -> str:
        ready, self._pending = self._pending, ""
        return self._emit(ready)

    def _emit(self, ready: str) -> str:
        text = sanitize_fragment(ready)
        if not self._emitted_any:
            text = text.lstrip()
        if text:
            self._emitted_any = True
        return text
