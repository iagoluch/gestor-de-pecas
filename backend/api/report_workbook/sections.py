"""Renderizador dos artifacts por seção (chat, agendamento e envio por Telegram).

Estes relatórios são compostos pelo ``ReportDataBuilder`` como um conjunto de
seções canônicas. Cada seção tem um layout dedicado: colunas escolhidas à mão,
rótulos de negócio, tipos nativos, ordenação e totais quando fazem sentido.
Ids internos, flags e estruturas aninhadas nunca são despejados na planilha;
seção ou campo sem layout é ignorado (com registro em debug), não vira tabela
genérica.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Callable

from .executive import (
    FOOTER,
    ISSUE_LABELS,
    OVERVIEW_SHEET,
    SEVERITY_LABELS,
    SEVERITY_TONES,
    STATUS_TONES,
    _gerencial_destaques,
)
from .kit import (
    AMBER,
    AVAILABILITY_LABELS,
    FORMATS,
    GREEN,
    RED,
    Card,
    Column,
    Ranking,
    ReportSheet,
    pick_cards,
    write_resumo,
    duration_text,
    humanize,
    metric,
    number_text,
    pareto_chart,
    ranking_chart,
    readable_code,
    sheet_title,
    trend_chart,
)

_LOG = logging.getLogger(__name__)


REPORT_TITLES = {
    "completo": "Relatório Industrial Completo",
    "gerencial": "Relatório Gerencial",
    "producao": "Relatório de Produção",
    "perdas": "Relatório de Perdas",
    "indicadores": "Relatório de Indicadores",
    "dados_analiticos": "Dados Analíticos",
    "ops": "Ordens de Produção",
    "paradas": "Paradas",
    "setup": "Setup",
    "qualidade": "Qualidade",
    "recursos": "Recursos",
    "setores": "Setores",
    "nestings": "Nestings",
    "excecoes": "Exceções",
    "rastreabilidade": "Rastreabilidade",
    "auditoria": "Auditoria",
}

SECTION_ALIASES = {
    "OEE": "Indicadores",
}

# OEE = Disponibilidade × Performance × FTT (mes/analytics/oee.py): o FTT é o
# fator de qualidade do OEE.
SUMMARY_CARDS = (
    ("OEE", "oee"),
    ("Disponibilidade", "availability"),
    ("Performance", "performance"),
    ("Qualidade (FTT)", "ftt"),
)


def report_title(report_type: str) -> str:
    return REPORT_TITLES.get(report_type, humanize(report_type))


# --- Vocabulário dos códigos canônicos ---------------------------------------

CATEGORY_LABELS = {
    "producao": "Produção",
    "parada": "Parada",
    "setup": "Setup",
    "retrabalho": "Retrabalho",
    "atividade_sem_op": "Atividade sem OP",
    "sem_demanda": "Sem demanda",
    "fora_turno": "Fora do turno",
    "fila": "Na fila",
    "livre": "Livre",
    "aguardando": "Aguardando",
    "desconhecido": "Estado não identificado",
}

STOP_CLASS_LABELS = {
    "planejada": "Planejada",
    "nao_planejada": "Não planejada",
}

EXCEPTION_SEVERITY_LABELS = {
    "alta": "Alta",
    "atencao": "Atenção",
    "informativa": "Informativa",
}

EXCEPTION_SEVERITY_TONES = (("Alta", RED), ("Atenção", AMBER))

CRITERION_LABELS = {
    "tempo_fisico_de_parada_no_periodo": "Tempo de parada no período",
}

TIMELINE_LABELS = {
    "inicio_operacao": "Início da operação",
    "fim_operacao": "Fim da operação",
    "estado_fisico_recurso": "Estado do recurso",
    "participacao_operador": "Participação de operador",
    "inicio_nesting": "Início do nesting",
    "fim_nesting": "Fim do nesting",
    "quantidade_boa": "Quantidade boa registrada",
    "quantidade_refugo": "Refugo registrado",
    "quantidade_retrabalho": "Retrabalho registrado",
}

QUALITY_EVENT_LABELS = {
    "boa": "Boa",
    "refugo": "Refugo",
    "retrabalho": "Retrabalho",
}

UNIT_SUFFIX = {"%": "%", "pecas": " peças", "peças": " peças", "unidades": " un."}

SEVERITY_ORDER = {"critico": 0, "erro": 1, "aviso": 2, "info": 3}


# --- Leitura defensiva do payload --------------------------------------------

def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _number(value: Any):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _code_text(value: Any, labels: dict[str, str]) -> str | None:
    """Código canônico em linguagem de negócio; nunca o código cru."""

    return readable_code(value, labels)


def _sum(rows: list[dict[str, Any]], key: str):
    valores = [_number(row.get(key)) for row in rows]
    presentes = [valor for valor in valores if valor is not None]
    return sum(presentes) if presentes else None


def _sort_desc(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (_number(row.get(key)) is None, -(_number(row.get(key)) or 0.0)))


def _sort_text(rows: list[dict[str, Any]], *keys: str) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: tuple(str(row.get(key) or "~").casefold() for key in keys))


def _value_with_unit(value: Any, unit: Any) -> str | None:
    numero = _number(value)
    if numero is None:
        return None
    unidade = str(unit or "").strip().casefold()
    if unidade in {"segundos", "s", "seconds"}:
        return duration_text(numero)
    return f"{number_text(numero)}{UNIT_SUFFIX.get(unidade, '')}"


def _pareto_rows(rows: list[dict[str, Any]], label_key: str, value_key: str) -> list[dict[str, Any]]:
    """Ordena do maior para o menor e acrescenta participação e acumulado.

    É apresentação do que o backend já somou por motivo; nenhum indicador
    industrial é derivado daqui.
    """

    validas = [row for row in rows if _number(row.get(value_key)) is not None and row.get(label_key)]
    ordenadas = _sort_desc(validas, value_key)
    total = sum(float(row[value_key]) for row in ordenadas)
    acumulado = 0.0
    saida = []
    for row in ordenadas:
        valor = float(row[value_key])
        acumulado += valor
        saida.append({
            "rotulo": row[label_key],
            "valor": row[value_key],
            "participacao": valor / total * 100 if total > 0 else None,
            "acumulado": acumulado / total * 100 if total > 0 else None,
        })
    return saida


def _availability_notice(sheet: ReportSheet, data: dict[str, Any], fallback: str) -> None:
    codigo = str(data.get("availability") or "").strip()
    estado = AVAILABILITY_LABELS.get(codigo)
    motivo = str(data.get("reason") or "").strip()
    texto = " — ".join(parte for parte in (estado, motivo) if parte) or fallback
    sheet.empty(texto)


# --- Contexto de escrita de uma aba ------------------------------------------

@dataclass
class _Context:
    overview: dict[str, Any]


class _Sheet:
    """Aba de seção: só a primeira tabela congela o cabeçalho e filtra."""

    def __init__(self, sheet: ReportSheet):
        self.sheet = sheet
        self.tables = 0

    def table(self, columns, rows, **kwargs):
        first = self.tables == 0
        self.tables += 1
        kwargs.setdefault("freeze", first)
        kwargs.setdefault("autofilter", first)
        return self.sheet.table(columns, rows, **kwargs)


def _pareto_block(target: _Sheet, rows, *, label: str, value_label: str, kind: str, title: str, color=RED) -> None:
    if not rows:
        return
    sheet = target.sheet
    tabela = target.table(
        (
            Column("rotulo", label, "text", 34),
            Column("valor", value_label, kind),
            Column("participacao", "% do total", "percent"),
            Column("acumulado", "% acumulado", "percent"),
        ),
        rows,
    )
    if len(rows) >= 2:
        pareto_chart(
            sheet.ws, tabela,
            title=title, label_key="rotulo", value_key="valor", cumulative_key="acumulado",
            anchor=f"A{sheet.row}", color=color, number_format=FORMATS.get(kind),
            width=26.0,
        )
        sheet.row += 17


# --- Layouts por seção --------------------------------------------------------

SECTOR_COLUMNS = (
    Column("setor", "Setor", "text", 22),
    Column("producao_boa", "Produção boa", "int"),
    Column("refugo", "Refugo", "int"),
    Column("retrabalho", "Retrabalho", "int"),
    Column("ops", "OPs", "int"),
    Column("tempo_producao_segundos", "Produção", "duration"),
    Column("tempo_setup_segundos", "Setup", "duration"),
    Column("tempo_parada_segundos", "Parada", "duration"),
    Column("tempo_retrabalho_segundos", "Retrabalho (tempo)", "duration"),
    Column("tempo_sem_demanda_segundos", "Sem demanda", "duration"),
    Column("tempo_fora_turno_segundos", "Fora do turno", "duration"),
    Column("tempo_produtivo_segundos", "Tempo produtivo", "duration"),
)

SECTOR_TOTAL_KEYS = ("producao_boa", "refugo", "retrabalho")


def _sector_table(target: _Sheet, rows: list[dict[str, Any]]) -> None:
    ordenadas = _sort_desc(rows, "producao_boa")
    totais = {"setor": "Total"}
    for chave in SECTOR_TOTAL_KEYS:
        totais[chave] = _sum(ordenadas, chave)
    target.table(SECTOR_COLUMNS, ordenadas, totals=totais if len(ordenadas) > 1 else None)


def _render_indicadores(target: _Sheet, data: dict[str, Any], ctx: _Context) -> None:
    sheet = target.sheet
    kpis = _dict(ctx.overview.get("kpis"))
    cards = []
    for label, chave in SUMMARY_CARDS:
        fonte = kpis.get(chave) if chave in kpis else (data if chave == "oee" else None)
        item = metric(fonte)
        cards.append(Card(label, item.value, "percent", "", "info", item.reason or item.state_label))
    sheet.section("OEE decomposto", "OEE = Disponibilidade × Performance × Qualidade (FTT).")
    sheet.kpis(cards)

    perdas = _dict(data.get("losses_breakdown"))
    tempos = [
        {"motivo": "Parada não planejada", "segundos": perdas.get("parada_nao_planejada_segundos")},
        {"motivo": "Parada planejada", "segundos": perdas.get("parada_planejada_segundos")},
        {"motivo": "Sem demanda", "segundos": perdas.get("sem_demanda_segundos")},
    ]
    # Ritmo (pode ser negativo) e fora do turno não são perda de tempo comparável:
    # ficam de fora do Pareto para não distorcer os percentuais.
    pareto = _pareto_rows(tempos, "motivo", "segundos")
    if pareto:
        sheet.section("Pareto das perdas de tempo")
        _pareto_block(target, pareto, label="Perda", value_label="Tempo", kind="duration",
                      title="Perdas de tempo (Pareto)")
    pecas = [
        {"perda": "Refugo", "quantidade": perdas.get("refugo_quantidade")},
        {"perda": "Retrabalho", "quantidade": perdas.get("retrabalho_quantidade")},
    ]
    if any(_number(row["quantidade"]) is not None for row in pecas):
        sheet.section("Perdas de qualidade")
        target.table((Column("perda", "Perda", "text", 24), Column("quantidade", "Peças", "int")), pecas)

    evolucao = _dict(data.get("evolution"))
    pontos = [
        {"periodo": ponto.get("period_start") or ponto.get("at"), "valor": ponto.get("value")}
        for ponto in _rows(evolucao.get("points"))
    ]
    if pontos:
        sheet.section("Evolução do OEE")
        tabela = target.table(
            (Column("periodo", "Início do intervalo", "datetime", 20), Column("valor", "OEE", "percent")),
            pontos,
        )
        if trend_chart(sheet.ws, tabela, title="Evolução do OEE", label_key="periodo",
                       value_key="valor", anchor=f"D{tabela.header_row}", number_format=FORMATS["percent"]):
            sheet.row = max(sheet.row, tabela.header_row + 17)


def _render_producao(target: _Sheet, data: dict[str, Any], ctx: _Context) -> None:
    sheet = target.sheet
    producao = _dict(data.get("production"))
    sheet.section("Produção do período")
    sheet.kpis([
        Card("Produção boa", producao.get("good"), "int", "peças boas", "good"),
        Card("Refugo", producao.get("scrap"), "int", "peças refugadas", "bad"),
        Card("Retrabalho", producao.get("rework"), "int", "peças retrabalhadas", "warn"),
        Card("OPs", producao.get("ops"), "int", "ordens com apontamento", "neutral"),
    ])
    setores = _rows(data.get("sectors"))
    if setores:
        sheet.section("Produção por setor")
        _sector_table(target, setores)


def _render_setores(target: _Sheet, data: dict[str, Any], ctx: _Context) -> None:
    setores = _rows(data.get("items"))
    if not setores:
        _availability_notice(target.sheet, data, "Nenhum setor com registro no período.")
        return
    target.sheet.section("Indicadores por setor")
    _sector_table(target, setores)


OP_COLUMNS = (
    Column("op", "OP", "text", 16),
    Column("produto", "Produto", "text", 18),
    Column("descricao", "Descrição", "text", 30),
    Column("operacao_atual", "Operação", "text", 10),
    Column("descricao_operacao", "Descrição da operação", "text", 26),
    Column("setor", "Setor", "text", 16),
    Column("recurso_planejado", "Recurso planejado", "text", 18),
    Column("recurso_real", "Recurso real", "text", 18),
    Column("status", "Status", "text", 14, tones=STATUS_TONES),
    Column("prioridade", "Prioridade", "text", 12),
    Column("prazo_entrega", "Prazo de entrega", "date"),
    Column("inicio_planejado", "Início planejado", "datetime"),
    Column("fim_planejado", "Fim planejado", "datetime"),
    Column("inicio_real", "Início real", "datetime"),
    Column("fim_real", "Fim real", "datetime"),
    Column("operador_inicio", "Operador (início)", "text", 20),
    Column("operador_fim", "Operador (fim)", "text", 20),
    Column("quantidade_planejada", "Qtd. planejada", "int"),
    Column("quantidade_boa", "Qtd. boa", "int"),
    Column("refugo", "Refugo", "int"),
    Column("retrabalho", "Retrabalho", "int"),
    Column("quantidade_atendida", "Qtd. atendida", "int"),
    Column("saldo_quantidade", "Saldo", "int"),
    Column("progresso_percentual", "Progresso", "percent"),
    Column("proxima_operacao", "Próxima operação", "text", 14),
)


def _render_ops(target: _Sheet, data: dict[str, Any], ctx: _Context) -> None:
    itens = _rows(data.get("items"))
    if not itens:
        _availability_notice(target.sheet, data, "Nenhuma ordem de produção no período.")
        return
    linhas = [{**row, "status": _code_text(row.get("status"), {})} for row in _sort_text(itens, "op", "operacao_atual")]
    target.sheet.section("Ordens de produção")
    totais = {"op": "Total"}
    for chave in ("quantidade_boa", "refugo", "retrabalho"):
        totais[chave] = _sum(linhas, chave)
    target.table(OP_COLUMNS, linhas, totals=totais if len(linhas) > 1 else None)


def _segment_renderer(kind: str) -> Callable[[_Sheet, dict[str, Any], _Context], None]:
    setup = kind == "setup"

    def render(target: _Sheet, data: dict[str, Any], ctx: _Context) -> None:
        sheet = target.sheet
        itens = _rows(data.get("items"))
        if not itens and not _rows(data.get("by_reason")):
            _availability_notice(sheet, data, "Nenhum registro de setup no período." if setup
                                 else "Nenhuma parada registrada no período.")
            return
        pareto = _pareto_rows(_rows(data.get("by_reason")), "motivo", "segundos")
        if pareto:
            sheet.section("Tempo por motivo")
            _pareto_block(target, pareto, label="Motivo", value_label="Tempo", kind="duration",
                          title="Tempo de setup por motivo" if setup else "Tempo parado por motivo (Pareto)")
        if not itens:
            return
        colunas = [
            Column("recurso", "Recurso", "text", 18),
            Column("setor", "Setor", "text", 16),
            Column("op", "OP", "text", 14),
            Column("operacao", "Operação", "text", 10),
            Column("produto", "Produto", "text", 16),
            Column("tipo_setup" if setup else "motivo", "Tipo de setup" if setup else "Motivo", "text", 26),
            Column("inicio", "Início", "datetime"),
            Column("fim", "Fim", "datetime"),
            Column("segundos", "Duração", "duration"),
        ]
        if not setup:
            colunas.append(Column("programada", "Programada", "text", 12))
        colunas.append(Column("em_andamento", "Em andamento", "text", 13))
        linhas = [
            {**row, "motivo": _code_text(row.get("motivo"), {}), "tipo_setup": _code_text(row.get("tipo_setup"), {})}
            for row in sorted(itens, key=lambda row: (str(row.get("inicio") or "~"), str(row.get("recurso") or "")))
        ]
        sheet.section("Setups registrados" if setup else "Paradas registradas")
        total = _number(data.get("total_seconds"))
        totais = {colunas[0].key: "Total sem sobreposição", "segundos": total} if total is not None else None
        target.table(colunas, linhas, totals=totais)

    return render


def _render_qualidade(target: _Sheet, data: dict[str, Any], ctx: _Context) -> None:
    sheet = target.sheet
    totais = _dict(data.get("totals"))
    ftt = metric(data.get("ftt")) if isinstance(data.get("ftt"), dict) else metric(None)
    sheet.section("Qualidade do período")
    sheet.kpis([
        Card("Produção boa", totais.get("boa"), "int", "peças boas", "good"),
        Card("Refugo", totais.get("refugo"), "int", "peças refugadas", "bad"),
        Card("Retrabalho", totais.get("retrabalho"), "int", "peças retrabalhadas", "warn"),
        Card("FTT", ftt.value, "percent", "primeira vez certo", "info", ftt.reason or ftt.state_label),
    ])
    for chave, titulo, rotulo in (("by_sector", "Por setor", ("setor", "Setor")),
                                  ("by_product", "Por produto", ("produto", "Produto"))):
        linhas = _sort_desc(_rows(data.get(chave)), "refugo")
        if linhas:
            sheet.section(titulo)
            target.table(
                (Column(rotulo[0], rotulo[1], "text", 22), Column("boa", "Boa", "int"),
                 Column("refugo", "Refugo", "int"), Column("retrabalho", "Retrabalho", "int")),
                linhas,
                totals={rotulo[0]: "Total", "boa": _sum(linhas, "boa"), "refugo": _sum(linhas, "refugo"),
                        "retrabalho": _sum(linhas, "retrabalho")} if len(linhas) > 1 else None,
            )
    for chave, titulo, cor in (("scrap_reasons", "Motivos de refugo", RED), ("rework_reasons", "Motivos de retrabalho", AMBER)):
        pareto = _pareto_rows(_rows(data.get(chave)), "motivo", "quantidade")
        if pareto:
            sheet.section(titulo)
            _pareto_block(target, pareto, label="Motivo", value_label="Peças", kind="int",
                          title=f"{titulo} (Pareto)", color=cor)
    evidencias = _rows(data.get("evidence"))
    if evidencias:
        linhas = [{**row, "tipo": _code_text(row.get("type"), QUALITY_EVENT_LABELS)} for row in evidencias]
        linhas.sort(key=lambda row: str(row.get("occurred_at") or "~"))
        sheet.section("Registros de qualidade")
        target.table(
            (Column("occurred_at", "Momento", "datetime"), Column("tipo", "Tipo", "text", 14),
             Column("quantity", "Peças", "int"), Column("sector", "Setor", "text", 16),
             Column("resource", "Recurso", "text", 18), Column("op", "OP", "text", 14),
             Column("operation", "Operação", "text", 10), Column("product", "Produto", "text", 16),
             Column("reason", "Motivo", "text", 28)),
            linhas,
        )
    if not (totais or evidencias or _rows(data.get("by_sector"))):
        _availability_notice(sheet, data, "Nenhum registro de qualidade no período.")


RESOURCE_COLUMNS = (
    Column("setor", "Setor", "text", 16),
    Column("recurso", "Recurso", "text", 20),
    Column("situacao", "Situação", "text", 18),
    Column("classificacao", "Tipo de parada", "text", 16),
    Column("motivo", "Motivo", "text", 26),
    Column("inicio_estado_atual", "Desde", "datetime"),
    Column("duracao_estado_atual_segundos", "Tempo na situação", "duration"),
    Column("op_estado", "OP", "text", 14),
    Column("operacao_estado", "Operação", "text", 10),
    Column("produto_estado", "Produto", "text", 16),
    Column("operador_estado", "Operador", "text", 18),
    Column("quantidade_ops_ativas", "OPs ativas", "int"),
)

SITUATION_TONES = (("Parada", RED), ("Produção", GREEN), ("Setup", AMBER), ("Retrabalho", AMBER))


def _render_recursos(target: _Sheet, data: dict[str, Any], ctx: _Context) -> None:
    recursos = _rows(data.get("resources"))
    if not recursos:
        _availability_notice(target.sheet, data, "Nenhum recurso com registro no período.")
        return
    linhas = [
        {
            **row,
            "situacao": _code_text(row.get("categoria"), CATEGORY_LABELS),
            "classificacao": _code_text(row.get("classificacao_parada"), STOP_CLASS_LABELS),
        }
        for row in _sort_text(recursos, "setor", "recurso")
    ]
    target.sheet.section("Situação dos recursos")
    target.table(
        tuple(Column(c.key, c.label, c.kind, c.width, tones=SITUATION_TONES) if c.key == "situacao" else c
              for c in RESOURCE_COLUMNS),
        linhas,
    )


NESTING_COLUMNS = (
    Column("tarefa", "Tarefa", "text", 14),
    Column("programa", "Plano", "text", 16),
    Column("nesting", "Nesting", "int"),
    Column("maquina", "Máquina", "text", 16),
    Column("material", "Material", "text", 18),
    Column("espessura", "Espessura", "number"),
    Column("inicio", "Início", "datetime"),
    Column("fim", "Fim", "datetime"),
    Column("previsto_segundos", "Tempo previsto", "duration"),
    Column("real_segundos", "Tempo real", "duration"),
    Column("desvio_segundos", "Desvio", "duration"),
    Column("desvio_percentual", "Desvio %", "percent"),
    Column("status", "Status", "text", 14, tones=STATUS_TONES),
    Column("operador_inicio", "Operador", "text", 18),
)


def _render_nestings(target: _Sheet, data: dict[str, Any], ctx: _Context) -> None:
    itens = _rows(data.get("items"))
    if not itens:
        _availability_notice(target.sheet, data, "Nenhum nesting registrado no período.")
        return
    linhas = [{**row, "status": _code_text(row.get("status"), {})}
              for row in sorted(itens, key=lambda row: (str(row.get("inicio") or "~"), str(row.get("tarefa") or "")))]
    target.sheet.section("Nestings do Corte", "Plano é a chapa com as OPs; nesting é cada repetição dessa chapa.")
    target.table(NESTING_COLUMNS, linhas, totals={"tarefa": "Total", "real_segundos": _sum(linhas, "real_segundos")}
                 if len(linhas) > 1 else None)


def _render_excecoes(target: _Sheet, data: dict[str, Any], ctx: _Context) -> None:
    sheet = target.sheet
    excecoes = _rows(data.get("exceptions"))
    if excecoes:
        linhas = [
            {
                **row,
                "severidade": _code_text(row.get("severity"), EXCEPTION_SEVERITY_LABELS),
                "valor_atual": _value_with_unit(row.get("current_value"), row.get("unit")),
                "referencia": _value_with_unit(row.get("reference_value"), row.get("unit")),
                "impacto": _value_with_unit(row.get("impact_value"), row.get("impact_unit")),
            }
            for row in sorted(excecoes, key=lambda row: (_number(row.get("priority")) is None, _number(row.get("priority")) or 0))
        ]
        sheet.section("Exceções do período")
        target.table(
            (Column("severidade", "Severidade", "text", 12, tones=EXCEPTION_SEVERITY_TONES),
             Column("title", "Exceção", "text", 34, wrap=True), Column("summary", "Resumo", "text", 46, wrap=True),
             Column("sector", "Setor", "text", 16), Column("resource", "Recurso", "text", 18),
             Column("op", "OP", "text", 14), Column("valor_atual", "Valor atual", "text", 14),
             Column("referencia", "Referência", "text", 14), Column("impacto", "Impacto", "text", 14),
             Column("cause", "Causa", "text", 30, wrap=True)),
            linhas,
        )
    perdas = _rows(data.get("losses"))
    if perdas:
        sheet.section("Maiores perdas")
        target.table(
            (Column("rank", "Posição", "int"), Column("cause", "Causa", "text", 36),
             Column("impacto", "Impacto", "text", 16)),
            [{**row, "impacto": _value_with_unit(row.get("impact_value"), row.get("impact_unit"))}
             for row in sorted(perdas, key=lambda row: _number(row.get("rank")) or 0)],
        )
    criticos = _rows(data.get("critical_resources"))
    if criticos:
        sheet.section("Recursos críticos")
        target.table(
            (Column("rank", "Posição", "int"), Column("resource", "Recurso", "text", 22),
             Column("impact_value", "Tempo de parada", "duration"), Column("criterio", "Critério", "text", 30)),
            [{**row, "criterio": _code_text(row.get("criterion"), CRITERION_LABELS)}
             for row in sorted(criticos, key=lambda row: _number(row.get("rank")) or 0)],
        )
    for limite in _rows(data.get("limitations")):
        mensagem = str(limite.get("message") or "").strip()
        if mensagem:
            sheet.notice(mensagem, tone="warn")
    if not (excecoes or perdas or criticos):
        _availability_notice(sheet, data, "Nenhuma exceção identificada no período.")


def _render_rastreabilidade(target: _Sheet, data: dict[str, Any], ctx: _Context) -> None:
    sheet = target.sheet
    operacoes = _rows(data.get("operations"))
    eventos = _rows(data.get("timeline"))
    if data.get("op"):
        sheet.facts([("OP", str(data.get("op")))])
    if operacoes:
        sheet.section("Roteiro executado")
        target.table(
            (Column("operacao", "Operação", "text", 10), Column("descricao_operacao", "Descrição", "text", 26),
             Column("produto", "Produto", "text", 16), Column("setor_exibicao", "Setor", "text", 16),
             Column("recurso_previsto", "Recurso previsto", "text", 18), Column("recurso_real", "Recurso real", "text", 18),
             Column("status", "Status", "text", 14, tones=STATUS_TONES),
             Column("operador_inicio", "Operador (início)", "text", 18), Column("operador_fim", "Operador (fim)", "text", 18),
             Column("inicio", "Início", "datetime"), Column("fim", "Fim", "datetime"),
             Column("quantidade_boa", "Boa", "int"), Column("refugo", "Refugo", "int"),
             Column("retrabalho", "Retrabalho", "int"), Column("lote", "Lote", "text", 12)),
            [{**row, "setor_exibicao": row.get("setor_exibicao") or row.get("setor"),
              "status": _code_text(row.get("status"), {})} for row in operacoes],
        )
    if eventos:
        sheet.section("Linha do tempo")
        target.table(
            (Column("timestamp", "Momento", "datetime"), Column("evento", "Evento", "text", 26),
             Column("situacao", "Situação", "text", 16), Column("motivo", "Motivo", "text", 26),
             Column("operator", "Operador", "text", 18), Column("resource", "Recurso", "text", 18),
             Column("operation", "Operação", "text", 10), Column("quantity", "Peças", "int")),
            [
                {
                    **row,
                    "evento": _code_text(row.get("type"), TIMELINE_LABELS),
                    "situacao": _code_text(row.get("status"), CATEGORY_LABELS),
                    "motivo": _code_text(row.get("reason"), {}),
                }
                for row in sorted(eventos, key=lambda row: str(row.get("timestamp") or "~"))
            ],
        )
    if not (operacoes or eventos):
        _availability_notice(sheet, data, "Nenhum registro de rastreabilidade para esta OP.")


def _render_auditoria(target: _Sheet, data: dict[str, Any], ctx: _Context) -> None:
    sheet = target.sheet
    problemas = _rows(data.get("issues"))
    diagnostico = _dict(data.get("diagnostics"))
    sheet.section("Resumo da auditoria")
    sheet.kpis([
        Card("Registros analisados", _number(data.get("records_analyzed")), "int", "apontamentos", "neutral"),
        Card("Inconsistências", _number(data.get("count")) if data.get("count") is not None else (len(problemas) if problemas else None),
             "int", "ocorrências", "warn"),
        Card("Lacunas de calendário", _number(diagnostico.get("calendar_gap_count")), "int", "intervalos", "info"),
        Card("Tempo em lacunas", _number(diagnostico.get("calendar_gap_seconds")), "duration_card", "sem estado registrado", "info"),
    ])
    if data.get("reliability_percentage") is None and data.get("reliability_reason"):
        sheet.notice(str(data.get("reliability_reason")), tone="muted")
    por_severidade = _dict(data.get("by_severity"))
    linhas_sev = [
        {"severidade": SEVERITY_LABELS.get(chave), "quantidade": por_severidade.get(chave)}
        for chave in SEVERITY_ORDER if chave in por_severidade
    ]
    if linhas_sev:
        sheet.section("Inconsistências por severidade")
        target.table((Column("severidade", "Severidade", "text", 18, tones=SEVERITY_TONES),
                      Column("quantidade", "Quantidade", "int")), linhas_sev, autofilter=False, freeze=False)
    if problemas:
        linhas = [
            {
                **row,
                "severidade": SEVERITY_LABELS.get(str(row.get("severity") or "")) or _code_text(row.get("severity"), {}),
                "ocorrencia": _code_text(row.get("type"), ISSUE_LABELS),
            }
            for row in sorted(problemas, key=lambda row: (SEVERITY_ORDER.get(str(row.get("severity")), 9),
                                                          str(row.get("start") or "~")))
        ]
        sheet.section("Inconsistências encontradas")
        target.table(
            (Column("severidade", "Severidade", "text", 12, tones=SEVERITY_TONES),
             Column("ocorrencia", "Ocorrência", "text", 34), Column("message", "Descrição", "text", 50, wrap=True),
             Column("op", "OP", "text", 14), Column("operation", "Operação", "text", 10),
             Column("resource", "Recurso", "text", 18), Column("sector", "Setor", "text", 16),
             Column("start", "Início", "datetime"), Column("end", "Fim", "datetime"),
             Column("seconds", "Duração", "duration")),
            linhas,
        )
    elif not linhas_sev:
        sheet.empty("Nenhuma inconsistência encontrada no período.")


RENDERERS: dict[str, Callable[[_Sheet, dict[str, Any], _Context], None]] = {
    "OEE": _render_indicadores,
    "Indicadores": _render_indicadores,
    "Produção": _render_producao,
    "OPs": _render_ops,
    "Paradas": _segment_renderer("paradas"),
    "Setup": _segment_renderer("setup"),
    "Qualidade": _render_qualidade,
    "Recursos": _render_recursos,
    "Setores": _render_setores,
    "Nestings": _render_nestings,
    "Exceções": _render_excecoes,
    "Rastreabilidade": _render_rastreabilidade,
    "Auditoria": _render_auditoria,
}


# --- Visão Geral --------------------------------------------------------------

def _overview_cards(overview: dict[str, Any]) -> list[Card]:
    kpis = _dict(overview.get("kpis"))
    production = _dict(overview.get("production"))
    cards = []
    if production:
        cards.extend([
            Card("Produção boa", production.get("good"), "int", "peças boas", "good"),
            Card("Refugo", production.get("scrap"), "int", "peças refugadas", "bad"),
            Card("Retrabalho", production.get("rework"), "int", "peças retrabalhadas", "warn"),
            Card("OPs", production.get("ops"), "int", "ordens com apontamento", "neutral"),
        ])
    if kpis:
        for label, chave in SUMMARY_CARDS:
            item = metric(kpis.get(chave))
            cards.append(Card(label, item.value, "percent", "", "info", item.reason or item.state_label))
    return cards


def _overview(workbook, titulo: str, overview: dict[str, Any], filters, generated_at: datetime) -> None:
    painel = ReportSheet(workbook.create_sheet(OVERVIEW_SHEET))
    painel.header(titulo, filters, generated_at=generated_at)
    cards = _overview_cards(overview)
    if cards:
        painel.section("Indicadores do período")
        painel.kpis(cards)
    else:
        painel.empty("Os indicadores consolidados do período não estão disponíveis para este relatório.")

    setores = _rows(overview.get("sectors"))
    if setores:
        painel.section("Produção por setor")
        tabela = painel.table(
            (
                Column("setor", "Setor", "text", 22),
                Column("producao_boa", "Produção boa", "int"),
                Column("refugo", "Refugo", "int"),
                Column("retrabalho", "Retrabalho", "int"),
                Column("tempo_produtivo_segundos", "Tempo produtivo", "duration"),
            ),
            _sort_desc(setores, "producao_boa"),
            autofilter=False,
            freeze=False,
        )
        if any(_number(row.get("producao_boa")) is not None for row in setores):
            ranking_chart(
                painel.ws, tabela,
                title="Produção boa por setor (peças)",
                label_key="setor", value_key="producao_boa",
                anchor=f"A{painel.row}", color=GREEN, number_format=FORMATS["int"],
            )
            painel.row += 17
    painel.footer(FOOTER)
    painel.print_setup()


def build_sections_resumo(workbook, report_type: str, overview: dict[str, Any], filters, generated_at: datetime) -> None:
    """Formato simples: a Visão Geral reduzida a uma página (cartões, pontos e 1 ranking)."""

    write_resumo(
        workbook,
        title=report_title(report_type),
        filters=filters,
        generated_at=generated_at,
        cards=pick_cards(
            _overview_cards(overview),
            ("OEE", "Produção boa", "Disponibilidade", "Performance", "Qualidade (FTT)", "Refugo"),
        ),
        points=_gerencial_destaques(overview),
        ranking=Ranking(
            "Produção boa por setor", "Setor", "Peças boas", "int",
            [(row.get("setor"), _number(row.get("producao_boa"))) for row in _rows(overview.get("sectors"))],
            GREEN,
        ),
        footer=FOOTER,
    )


def build_sections_workbook(
    workbook,
    report_type: str,
    payload: dict[str, Any],
    filters,
    generated_at: datetime,
    *,
    modo: str = "tecnico",
) -> None:
    sections = _dict(payload.get("sections"))
    overview = _dict(sections.get("Resumo Executivo"))
    if modo == "simples":
        build_sections_resumo(workbook, report_type, overview, filters, generated_at)
        return
    titulo = report_title(report_type)
    _overview(workbook, titulo, overview, filters, generated_at)

    contexto = _Context(overview=overview)
    usados = {OVERVIEW_SHEET.casefold()}
    for nome, conteudo in sections.items():
        if nome == "Resumo Executivo":
            continue
        renderer = RENDERERS.get(str(nome))
        if renderer is None:
            _LOG.debug("Seção sem layout na exportação XLSX ignorada: %s", nome)
            continue
        if isinstance(conteudo, list):
            conteudo = {"items": conteudo}
        if not isinstance(conteudo, dict) or not conteudo:
            _LOG.debug("Seção vazia ou sem estrutura ignorada: %s", nome)
            continue
        titulo_aba = sheet_title(SECTION_ALIASES.get(str(nome), str(nome)), usados)
        aba = ReportSheet(workbook.create_sheet(titulo_aba), width=12)
        aba.header(f"{titulo} — {titulo_aba}", filters, generated_at=generated_at)
        renderer(_Sheet(aba), conteudo, contexto)
        aba.footer(FOOTER)
        aba.print_setup()


__all__ = ["build_sections_resumo", "build_sections_workbook", "report_title", "REPORT_TITLES"]
