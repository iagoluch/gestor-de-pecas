"""Renderizador dos artifacts por seção (chat, agendamento e envio por Telegram).

Estes relatórios são compostos pelo ``ReportDataBuilder`` como um conjunto de
seções canônicas. A estrutura por seção é preservada; o que muda aqui é a
identidade visual, que passa a ser a mesma dos relatórios executivos, e a
separação entre a informação para pessoas e a informação de auditoria.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from .kit import (
    FORMATS,
    Card,
    Column,
    GREEN,
    ReportSheet,
    humanize,
    metric,
    ranking_chart,
    sheet_title,
    technical_sheet,
)
from .executive import FOOTER, OVERVIEW_SHEET


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
    "Exceções": "Exceções",
}

SUMMARY_CARDS = (
    ("OEE", "oee", "percent"),
    ("Disponibilidade", "availability", "percent"),
    ("Performance", "performance", "percent"),
    ("FTT", "ftt", "percent"),
)


def report_title(report_type: str) -> str:
    return REPORT_TITLES.get(report_type, humanize(report_type))


def _section_rows(value: Any) -> list[dict[str, Any]]:
    """Achata uma seção canônica em linhas legíveis (grupo, campo, valor)."""

    rows: list[dict[str, Any]] = []

    def visit(current: Any, path: tuple[str, ...] = ()):
        if isinstance(current, dict):
            for key, child in current.items():
                if isinstance(child, (dict, list)):
                    visit(child, (*path, str(key)))
                else:
                    rows.append({
                        "grupo": " › ".join(humanize(part) for part in path) or "Resumo",
                        "campo": humanize(str(key)),
                        "valor": child,
                    })
            return
        if isinstance(current, list):
            grupo = " › ".join(humanize(part) for part in path) or "Itens"
            for item in current:
                if isinstance(item, dict):
                    rows.append({"grupo": grupo, **item})
                else:
                    rows.append({"grupo": grupo, "valor": item})
            return
        rows.append({
            "grupo": " › ".join(humanize(part) for part in path) or "Resumo",
            "valor": current,
        })

    visit(value)
    return rows


def _columns_for(rows: Iterable[dict[str, Any]]) -> list[Column]:
    chaves: list[str] = []
    for row in rows:
        for key in row:
            if key not in chaves:
                chaves.append(key)
    colunas = []
    for chave in chaves:
        rotulo = {
            "grupo": "Grupo",
            "campo": "Campo",
            "valor": "Valor",
            "at": "Momento",
            "period_start": "Início do período",
            "period_end": "Fim do período",
            "unit": "Unidade",
        }.get(chave, humanize(chave))
        kind = "text"
        if chave.endswith(("segundos", "_seconds")):
            kind = "duration"
        elif chave in {"inicio", "fim", "start", "end", "at", "occurred_at", "period_start", "period_end"}:
            kind = "datetime"
        colunas.append(Column(chave, rotulo, kind))
    return colunas


def build_sections_workbook(
    workbook,
    report_type: str,
    payload: dict[str, Any],
    filters,
    generated_at: datetime,
) -> None:
    sections = payload.get("sections") if isinstance(payload.get("sections"), dict) else {}
    resumo = sections.get("Resumo Executivo") if isinstance(sections, dict) else None
    titulo = report_title(report_type)

    painel = ReportSheet(workbook.create_sheet(OVERVIEW_SHEET))
    painel.header(titulo, filters, generated_at=generated_at)

    overview = resumo if isinstance(resumo, dict) else {}
    kpis = overview.get("kpis") if isinstance(overview.get("kpis"), dict) else {}
    production = overview.get("production") if isinstance(overview.get("production"), dict) else {}

    cards = []
    if production:
        cards.extend([
            Card("Produção boa", production.get("good"), "int", "peças boas", "good"),
            Card("Refugo", production.get("scrap"), "int", "peças refugadas", "bad"),
            Card("Retrabalho", production.get("rework"), "int", "peças retrabalhadas", "warn"),
            Card("OPs", production.get("ops"), "int", "ordens com apontamento", "neutral"),
        ])
    for label, chave, kind in SUMMARY_CARDS:
        item = metric(kpis.get(chave))
        cards.append(Card(label, item.value, kind, "", "info", item.reason or item.state_label))
    if cards:
        painel.section("Indicadores do período")
        painel.kpis(cards)

    setores = overview.get("sectors") if isinstance(overview.get("sectors"), list) else []
    tabela_setores = None
    if setores:
        painel.section("Produção por setor")
        tabela_setores = painel.table(
            (
                Column("setor", "Setor", "text", 22),
                Column("producao_boa", "Produção boa", "int"),
                Column("refugo", "Refugo", "int"),
                Column("retrabalho", "Retrabalho", "int"),
                Column("tempo_produtivo_segundos", "Tempo produtivo", "duration"),
            ),
            [row for row in setores if isinstance(row, dict)],
            autofilter=False,
            freeze=False,
        )
    tem_producao = any(
        isinstance(row.get("producao_boa"), (int, float)) for row in setores if isinstance(row, dict)
    )
    if tabela_setores is not None and tabela_setores.rows and tem_producao:
        ranking_chart(
            painel.ws, tabela_setores,
            title="Produção boa por setor (peças)",
            label_key="setor", value_key="producao_boa",
            anchor=f"A{painel.row}", color=GREEN, number_format=FORMATS["int"],
        )
        painel.row += 17
    painel.footer(FOOTER)
    painel.print_setup()

    usados = {OVERVIEW_SHEET.casefold()}
    for nome, conteudo in (sections or {}).items():
        if nome == "Resumo Executivo":
            continue
        linhas = _section_rows(conteudo)
        if not linhas:
            continue
        titulo_aba = sheet_title(SECTION_ALIASES.get(str(nome), str(nome)), usados)
        colunas = _columns_for(linhas)
        aba = ReportSheet(workbook.create_sheet(titulo_aba), width=max(4, len(colunas)))
        aba.header(f"{titulo} — {titulo_aba}", filters, generated_at=generated_at)
        aba.section(str(nome))
        aba.table(colunas, linhas)
        aba.footer(FOOTER)
        aba.print_setup()

    technical_sheet(workbook, payload, filters, generated_at=generated_at)


__all__ = ["build_sections_workbook", "report_title", "REPORT_TITLES"]
