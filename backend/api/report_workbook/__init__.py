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

from .executive import BUILDERS
from .sections import REPORT_TITLES, build_sections_workbook, report_title


def _normalize(report_type: str) -> str:
    return str(report_type or "").strip().casefold().replace("-", "_")


def build_report_workbook(
    report_type: str,
    payload: Any,
    filters: AnalyticsFilter,
    *,
    generated_at: datetime | None = None,
) -> bytes:
    """Gera o arquivo Excel a partir do payload já calculado pelo backend."""

    tipo = _normalize(report_type)
    dados = jsonable_encoder(payload)
    if not isinstance(dados, dict):
        dados = {"dados": dados}
    momento = generated_at or datetime.now()

    workbook = Workbook()
    workbook.remove(workbook.active)
    try:
        construtor = BUILDERS.get(tipo)
        if construtor is not None and "sections" not in dados:
            construtor(workbook, dados, filters, momento)
        elif "sections" in dados:
            build_sections_workbook(workbook, tipo, dados, filters, momento)
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
            )
        if not workbook.sheetnames:
            # Nunca entrega arquivo sem aba nem despeja o payload: a Visão Geral
            # diz que não há dado publicado para o relatório.
            build_sections_workbook(workbook, tipo, {"sections": {}}, filters, momento)
        workbook.calculation.fullCalcOnLoad = True
        output = BytesIO()
        workbook.save(output)
        return output.getvalue()
    finally:
        workbook.close()


__all__ = ["REPORT_TITLES", "build_report_workbook", "report_title"]
