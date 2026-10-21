"""Exportação XLSX dos relatórios do Gestor de Peças.

Arquitetura:

* ``kit``      — identidade visual e primitivas (cabeçalho, cartão, tabela,
                 gráfico, estado sem dado);
* ``executive``— os cinco relatórios de gestão (Gerencial, Produção, Perdas,
                 Indicadores e Dados Analíticos);
* ``sections`` — os artifacts por seção usados pelo chat, pelo agendamento e
                 pelo envio por Telegram.

O Excel é uma camada de apresentação: nenhum indicador industrial é calculado
aqui. Quando o backend não publica o dado, a planilha mostra a ausência com a
justificativa oficial — nunca zero.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import Any

from fastapi.encoders import jsonable_encoder
from openpyxl import Workbook

from mes.contracts import AnalyticsFilter

from .executive import BUILDERS, RESUMOS
from .sections import REPORT_TITLES, build_sections_workbook, report_title

# "tecnico": todas as abas, listas completas. "simples": uma aba "Resumo" que
# cabe numa folha A4 paisagem, para leitura de diretoria.
MODOS = ("tecnico", "simples")


def _normalize(report_type: str) -> str:
    return str(report_type or "").strip().casefold().replace("-", "_")


def _normalize_modo(modo: str) -> str:
    valor = str(modo or "").strip().casefold().replace("é", "e")
    if valor not in MODOS:
        raise ValueError(f"Modo de planilha inválido: {modo!r}. Use 'tecnico' ou 'simples'.")
    return valor


def build_report_workbook(
    report_type: str,
    payload: Any,
    filters: AnalyticsFilter,
    *,
    generated_at: datetime | None = None,
    modo: str = "tecnico",
) -> bytes:
    """Gera o arquivo Excel a partir do payload já calculado pelo backend."""

    modo = _normalize_modo(modo)
    tipo = _normalize(report_type)
    dados = jsonable_encoder(payload)
    if not isinstance(dados, dict):
        dados = {"dados": dados}
    momento = generated_at or datetime.now()
    construtores = RESUMOS if modo == "simples" else BUILDERS

    workbook = Workbook()
    workbook.remove(workbook.active)
    try:
        construtor = construtores.get(tipo)
        if construtor is not None and "sections" not in dados:
            construtor(workbook, dados, filters, momento)
        elif "sections" in dados:
            build_sections_workbook(workbook, tipo, dados, filters, momento, modo=modo)
        else:
            build_sections_workbook(
                workbook,
                tipo,
                {"sections": {
                    str(chave): valor
                    for chave, valor in dados.items()
                    if isinstance(valor, (dict, list))
                }},
                filters,
                momento,
                modo=modo,
            )
        if not workbook.sheetnames:
            # Nunca entrega arquivo sem aba nem despeja o payload: a Visão Geral
            # diz que não há dado publicado para o relatório.
            build_sections_workbook(workbook, tipo, {"sections": {}}, filters, momento, modo=modo)
        workbook.calculation.fullCalcOnLoad = True
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()
    finally:
        workbook.close()


__all__ = ["MODOS", "REPORT_TITLES", "build_report_workbook", "report_title"]
