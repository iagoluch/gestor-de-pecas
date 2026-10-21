"""Toda planilha exportada é documento limpo: nada de saída bruta do backend.

Gera cada tipo de relatório com payload no formato canônico — inclusive com os
campos técnicos que o backend publica (ids, uuids, códigos, fontes, flags) — e
varre todas as células de todas as abas atrás de vazamento de dado cru.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from io import BytesIO
import re
import tempfile
import unittest

from openpyxl import load_workbook

from backend.api.report_workbook import build_report_workbook
from mes.contracts import AnalyticsFilter, ReportRequest
from mes.services.industrial_reports import IndustrialReportService
from tests.fakes import FakeDatabase
from tests.test_intelligence_reports import NOW, CanonicalReportFacade


UUID = "3f2b8c1e-9a4d-4e6f-8b21-7c5d9e0a1b2c"
INICIO = "2026-08-26T07:00:00"
FIM = "2026-08-26T07:15:00"

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
SNAKE_RE = re.compile(r"\b[a-z0-9]+_[a-z0-9_]+\b")
WORD_RE = re.compile(r"\b(None|nan|NaN|null|True|False)\b")

SECTION_TYPES = (
    "completo", "ops", "paradas", "setup", "qualidade", "recursos", "setores",
    "nestings", "excecoes", "rastreabilidade", "auditoria", "indicadores", "producao",
    "gerencial",
)


def metric(value, reason=None):
    return {
        "value": value,
        "availability": "disponivel" if value is not None else "dados_insuficientes",
        "unit": "%",
        "reason": reason,
        "source": "ManagementService.get_overview",
    }


SECTORS = [
    {
        "setor": "Usinagem", "producao_boa": 120, "refugo": 3, "retrabalho": 2, "ops": 4,
        "tempo_producao_segundos": 3600.0, "tempo_setup_segundos": 300.0,
        "tempo_parada_segundos": 900.0, "tempo_retrabalho_segundos": 0.0,
        "tempo_atividade_sem_op_segundos": 0.0, "tempo_sem_demanda_segundos": 1200.0,
        "tempo_fila_segundos": 0.0, "tempo_fora_turno_segundos": 0.0,
        "tempo_produtivo_segundos": 3600.0,
    },
    {
        "setor": "Corte", "producao_boa": 80, "refugo": 0, "retrabalho": 0, "ops": 2,
        "tempo_producao_segundos": 1800.0, "tempo_setup_segundos": None,
        "tempo_parada_segundos": 0.0, "tempo_produtivo_segundos": 1800.0,
    },
]

SEGMENTS = {
    "count": 2,
    "total_seconds": 1500.0,
    "raw_attributed_seconds": 1600.0,
    "overlap_removed_seconds": 100.0,
    "conflicting_label_seconds": 0.0,
    "kind": "parada",
    "items": [
        {
            "apontamento_id": UUID, "evento_id": 991, "estado_recurso_id": 77, "op": "PCMIXQ01001",
            "operacao": "10", "produto": "PC-100", "setor": "Usinagem", "recurso": "Romi",
            "inicio": INICIO, "fim": FIM, "segundos": 900.0, "codigo_status": "PARADA_MANUT",
            "motivo": "Manutenção corretiva", "programada": False, "automatica": True,
            "tipo_interrupcao": "nao_planejada", "tipo_setup": "troca_ferramenta",
            "fonte": "eventos_estado_recurso", "em_andamento": False,
        },
        {
            "apontamento_id": None, "op": None, "recurso": "Centro 1", "setor": "Usinagem",
            "inicio": "2026-08-26T08:00:00", "fim": None, "segundos": 600.0, "motivo": None,
            "programada": True, "em_andamento": True, "fonte": "timeline_apontamentos_fallback",
        },
    ],
    "by_reason": [{"motivo": "Manutenção corretiva", "segundos": 900.0}, {"motivo": "Falta de material", "segundos": 700.0}],
    "by_resource": [{"recurso": "Romi", "segundos": 900.0}],
}

QUALITY = {
    "totals": {"boa": 120, "refugo": 3, "retrabalho": 2},
    "by_sector": [{"setor": "Usinagem", "boa": 120, "refugo": 3, "retrabalho": 2}],
    "by_product": [{"produto": "PC-100", "descricao": "Peça", "boa": 120, "refugo": 3, "retrabalho": 2}],
    "scrap_reasons": [{"motivo": "Cota fora", "quantidade": 3}],
    "rework_reasons": [{"motivo": "Rebarba", "quantidade": 2}],
    "evidence": [{
        "source": "eventos_quantidade_producao", "event_id": UUID, "type": "refugo", "quantity": 3,
        "sector": "Usinagem", "resource": "Romi", "op": "PCMIXQ01001", "operation": "10",
        "product": "PC-100", "reason": "Cota fora", "occurred_at": INICIO,
    }],
    "ftt": metric(96.0),
    "availability": "disponivel",
}

OVERVIEW_EXTRAS = {
    "kpis_estendidos": {"utilization": metric(None, "Calendário produtivo não configurado."), "productivity": metric(88.0)},
    "sector_highlights": [
        {"key": "maior_producao", "label": "Maior produção", "sector": "Usinagem", "value": 120, "unit": "peças"},
        {"key": "maior_refugo", "label": "Maior refugo", "sector": "Corte", "value": 0, "unit": "peças"},
    ],
    "hours": {"downtime_seconds": 1500.0},
    "time_composition": {
        "items": [
            {"label": "Produção", "seconds": 5400.0, "source_field": "tempo_producao_segundos", "summed": True, "percentage": 60.0},
            {"label": "Recurso sem demanda", "seconds": 1200.0, "source_field": "tempo_sem_demanda_segundos", "percentage": 13.3},
        ],
        "total_seconds": 9000.0,
    },
    "kpi_losses_breakdown": {
        "fora_de_turno_segundos": 0.0, "sem_demanda_segundos": 1200.0, "parada_planejada_segundos": 600.0,
        "parada_nao_planejada_segundos": 900.0, "ritmo_segundos": 120.0,
        "refugo_quantidade": 3, "retrabalho_quantidade": 2,
    },
    "resource_kpis": [{
        "resource": "Romi", "sector": "Usinagem",
        "metrics": {"oee": metric(80.0), "availability": metric(90.0), "performance": metric(92.0), "ftt": metric(97.0)},
        "kpi_time_bases": {"available_seconds": 28800.0, "operational_seconds": 25000.0, "productive_gross_seconds": 23000.0},
    }],
    "data_quality": {"calendar_configured": True, "facts": 10, "physical_state_rows": 5,
                     "physical_state_source": "fonte_nova_sem_rotulo", "status": "status_desconhecido"},
    "production_plan": {"value": None, "reason": "Planejado depende do contrato TOTVS."},
    "rateio": {"availability": "parcial", "reason": "Rateio parcial no período."},
}

INSIGHTS = {
    "exceptions": [{
        "id": UUID, "type": "physical_downtime_in_period", "severity": "alta", "priority": 1,
        "entity_type": "resource", "entity_id": UUID, "title": "Parada longa no Romi",
        "summary": "Romi ficou 15min parado.", "justification": "Tempo acima do limite.",
        "sector": "Usinagem", "resource": "Romi", "op": "PCMIXQ01001", "operation": "10",
        "current_value": 900.0, "reference_value": 600.0, "deviation": 300.0, "unit": "segundos",
        "cause": "Manutenção corretiva", "impact_value": 900.0, "impact_unit": "segundos",
        "evidence": {"apontamento_id": UUID},
    }],
    "exception_count": 1,
    "losses": [{"rank": 1, "type": "parada", "cause": "Manutenção corretiva", "impact_value": 900.0,
                "impact_unit": "segundos", "evidence": {"ids": [UUID]}}],
    "critical_resources": [{"rank": 1, "resource": "Romi", "impact_value": 900.0,
                            "criterion": "tempo_fisico_de_parada_no_periodo", "evidence": [UUID]}],
    "limitations": [{"code": "kpi_targets_not_configured", "message": "Metas de KPI não configuradas."}],
    "availability": "disponivel",
}

AUDIT = {
    "issues": [
        {"type": "op_sem_operador", "severity": "aviso", "message": "OP sem operador no início.",
         "appointment_id": UUID, "op": "PCMIXQ01001", "operation": "10", "resource": "Romi",
         "sector": "Usinagem", "start": INICIO, "end": FIM, "seconds": 900.0, "source": "apontamentos"},
        {"type": "tipo_novo_sem_rotulo", "severity": "gravissimo", "message": "Ocorrência nova.",
         "appointment_id": None, "start": None, "end": None, "seconds": None},
    ],
    "count": 2,
    "by_severity": {"aviso": 1, "gravissimo": 1},
    "diagnostics": {
        "calendar_gaps": [{"type": "recurso_em_turno_sem_status", "severity": "info", "message": "Turno sem estado.",
                           "resource": "Romi", "sector": "Usinagem", "start": INICIO, "end": FIM, "seconds": 900.0}],
        "calendar_gap_count": 1, "calendar_gap_seconds": 900.0, "reason": "Diagnóstico de cobertura do turno.",
    },
    "physical_state_source": "eventos_estado_recurso",
    "records_analyzed": 10, "resource_states_analyzed": 5, "rateio_sessions_analyzed": 0,
    "reliability_percentage": None, "reliability_reason": "Sem base para confiabilidade.",
}

ORDERS = {
    "items": [{
        "apontamento_id": UUID, "op": "PCMIXQ01001", "produto": "PC-100", "descricao": "Peça usinada",
        "operacao_atual": "10", "descricao_operacao": "Tornear", "sequencia": 1, "setor": "Usinagem",
        "recurso_planejado": "Romi", "recurso_real": "Romi", "prioridade": 2, "inicio_planejado": INICIO,
        "fim_planejado": FIM, "prazo_entrega": "2026-08-30", "inicio_real": INICIO, "fim_real": None,
        "operador_inicio": "Ana", "operador_fim": None, "quantidade_planejada": 130, "quantidade_boa": 120,
        "refugo": 3, "retrabalho": 2, "quantidade_atendida": 120, "saldo_quantidade": 10,
        "progresso_percentual": 92.3, "status": "em_processo", "proxima_operacao": "20",
        "fonte": "apontamentos_operacionais_fallback",
    }],
    "count": 1,
    "availability": "disponivel",
}

NESTINGS = {
    "items": [{
        "apontamento_id": UUID, "plano_hash": "a1b2c3d4e5", "tarefa": "T-1", "programa": "PL-77",
        "nesting": 1, "maquina": "LASER1", "material": "SAE 1020", "espessura": 3.0,
        "inicio": INICIO, "fim": FIM, "previsto_segundos": 600.0, "real_segundos": 900.0,
        "status": "finalizado", "operador_inicio": "Ana", "operador_fim": "Ana",
        "desvio_segundos": 300.0, "desvio_percentual": 50.0, "real_periodo_segundos": 900.0,
    }],
    "count": 1,
    "availability": "disponivel",
    "time_policy": {"rule": "periodo"},
}


class RichCanonicalFacade(CanonicalReportFacade):
    """Mesmas seções da fixture original, no formato canônico completo."""

    def inicio(self, filters):
        base = super().inicio(filters)
        return {**base, **OVERVIEW_EXTRAS, "sectors": SECTORS, "insights": INSIGHTS,
                "production": {"good": 200, "scrap": 3, "rework": 2, "ops": 6, "resources": 3}}

    def analise(self, key, filters):
        if key == "oee":
            return {
                **metric(82.4),
                "evolution": {"points": [{"period_start": "2026-08-25T00:00:00", "value": 80.0},
                                         {"period_start": "2026-08-26T00:00:00", "value": 84.0}],
                              "bucket_days": 1, "availability": "disponivel"},
                "extended_metrics": {"x": metric(1.0)},
                "losses_breakdown": OVERVIEW_EXTRAS["kpi_losses_breakdown"],
            }
        if key in {"paradas", "setup"}:
            return SEGMENTS
        if key == "qualidade":
            return QUALITY
        return super().analise(key, filters)

    def producao_realizada(self, filters):
        return {"periodo": filters.to_dict(), "production": {"good": 200, "scrap": 3, "rework": 2, "ops": 6},
                "sectors": SECTORS, "quality": QUALITY}

    def ordens_producao(self, filters):
        return ORDERS

    def consulta_operacional(self, filters):
        return {"periodo": filters.to_dict(), "agora": INICIO, "count": 1, "resources": [{
            "recurso": "Romi", "setor": "Usinagem", "categoria": "parada", "classificacao_parada": "nao_planejada",
            "motivo": "Manutenção corretiva", "comentario": None, "causa_raiz": None, "inicio": INICIO,
            "duracao_segundos": 900.0, "inicio_estado_atual": INICIO, "duracao_estado_atual_segundos": 900.0,
            "planejado": False, "automatico": True, "op_estado": "PCMIXQ01001", "operacao_estado": "10",
            "produto_estado": "PC-100", "operador_estado": "Ana", "ops_ativas": [{"op": "PCMIXQ01001"}],
            "quantidade_ops_ativas": 1, "sem_demanda": False, "estado_recurso_id": 77,
            "codigo_status": "PARADA_MANUT", "cor_parada": "#B3261E", "fonte": "eventos_estado_recurso",
            "conta_operador_ativa": True, "tem_apontamento_canonico": True, "codigo_tarefa_corte": None,
        }]}

    def nestings(self, filters):
        return NESTINGS

    def insights(self, filters):
        return INSIGHTS

    def rastreabilidade(self, op):
        return {
            "op": op,
            "operations": [{
                "apontamento_id": UUID, "operacao": "10", "descricao_operacao": "Tornear", "produto": "PC-100",
                "recurso_previsto": "Romi", "recurso_real": "Romi", "setor": "Usinagem", "setor_roteiro": "Usinagem",
                "setor_divergente": False, "setor_exibicao": "Usinagem", "status": "finalizado",
                "operador_inicio": "Ana", "operador_fim": "Ana", "inicio": INICIO, "fim": FIM,
                "quantidade_boa": 120, "refugo": 3, "retrabalho": 2, "lote": "L1", "eventos": [{"id": UUID}],
            }],
            "timeline": [
                {"timestamp": INICIO, "type": "inicio_operacao", "status": "producao", "reason": None,
                 "operator": "Ana", "resource": "Romi", "operation": "10", "source": "apontamentos",
                 "record_id": UUID, "appointment_id": UUID},
                {"timestamp": FIM, "type": "evento_novo_sem_rotulo", "status": "parada", "reason": "falta_material",
                 "operator": None, "resource": "Romi", "operation": "10", "quantity": 3},
            ],
            "source_refs": {"apontamentos": [UUID]},
        }

    def auditoria(self, filters):
        return AUDIT


def executive_payloads() -> dict[str, dict]:
    overview = RichCanonicalFacade().inicio(AnalyticsFilter(inicio=datetime(2026, 8, 1), fim=NOW))
    return {
        "gerencial": {"type": "gerencial", "overview": overview},
        "producao": {"type": "producao", "production": overview["production"], "sectors": SECTORS,
                     "quality": QUALITY, "orders": ORDERS},
        "perdas": {"type": "perdas", "paradas": SEGMENTS, "setup": SEGMENTS, "qualidade": QUALITY,
                   "tempos": {"by_sector": SECTORS, "availability": "parcial", "reason": "Cobertura parcial."},
                   "losses": {"oee_losses": OVERVIEW_EXTRAS["kpi_losses_breakdown"], "conflicting_state_seconds": 600.0,
                              "planned_downtime_seconds": 600.0, "unplanned_downtime_seconds": 900.0,
                              "rework_seconds": 0.0}},
        "indicadores": {"type": "indicadores", "analytics": {
            "tempos": {"by_sector": SECTORS}, "qualidade": QUALITY,
            "capacidade": {"items": [{"codigo": "LASER1", "nome": "Laser 1", "tipo_setor": "Corte",
                                      "capacidade_segundos": 28800.0, "carga_segundos": 20000.0,
                                      "capacidade_restante_segundos": 8800.0, "utilizacao_percentual": 69.4, "fila": 2}],
                           "recursos": 2, "recursos_com_calendario": 1, "recursos_sem_calendario": 1,
                           "reason": "Um recurso sem calendário.", "bottleneck_resource": "LASER1",
                           "bottleneck_utilizacao_percentual": 69.4},
            "confiabilidade": {"por_recurso": [{"recurso": "Romi", "falhas": 1, "segundos": 900.0}],
                               "motivos": [{"motivo": "Manutenção corretiva", "quantidade": 1}],
                               "taxonomia": "", "mtbf_segundos": 7200.0, "mttr_segundos": 900.0, "falhas": 1,
                               "availability": "disponivel"},
            "oee": RichCanonicalFacade().analise("oee", None),
            "kpis": overview["kpis"], "kpis_estendidos": overview["kpis_estendidos"],
            "recursos": overview["resource_kpis"],
        }},
        "dados_analiticos": {"type": "dados_analiticos", "orders": ORDERS, "audit": AUDIT, "nestings": NESTINGS},
    }


EXPECTED_EXECUTIVE_SHEETS = {
    "gerencial": ["Visão Geral", "Setores", "Recursos", "Perdas", "Qualidade dos Dados"],
    "producao": ["Visão Geral", "Setores", "Produtos", "Ordens", "Qualidade dos Dados"],
    "indicadores": ["Visão Geral", "Recursos", "Utilização", "Confiabilidade", "Evolução do OEE", "Qualidade dos Dados"],
    "dados_analiticos": ["Visão Geral", "Ordens", "Inconsistências", "Diagnósticos", "Diagnósticos (detalhe)",
                         "Nestings", "Qualidade dos Dados"],
}


class CleanWorkbookMixin:
    def assert_clean(self, content: bytes, label: str):
        workbook = load_workbook(BytesIO(content))
        try:
            self.assertEqual(workbook.sheetnames[0], "Visão Geral", label)
            for sheet in workbook.worksheets:
                where = f"{label} › {sheet.title}"
                self.assertEqual(sheet.sheet_state, "visible", f"{where}: aba oculta")
                self.assertNotIn("técnic", sheet.title.casefold(), where)
                self.assertEqual(sheet.oddFooter.right.text, "Página &P de &N", where)
                for row in sheet.iter_rows():
                    for cell in row:
                        if cell.data_type == "f":
                            self.fail(f"{where} {cell.coordinate}: fórmula {cell.value!r}")
                        if not isinstance(cell.value, str):
                            continue
                        texto = cell.value
                        local = f"{where} {cell.coordinate}: {texto!r}"
                        self.assertIsNone(UUID_RE.search(texto), local)
                        self.assertIsNone(SNAKE_RE.search(texto), local)
                        self.assertIsNone(WORD_RE.search(texto), local)
                        self.assertNotIn("{", texto, local)
                        self.assertFalse(texto.lstrip("'").startswith("["), local)
                        self.assertNotIn("Traceback", texto, local)
                        self.assertNotIn("(código:", texto, local)
            return list(workbook.sheetnames)
        finally:
            workbook.close()


class SectionWorkbookCleanTests(CleanWorkbookMixin, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def _generate(self, facade, report_type):
        service = IndustrialReportService(
            facade, FakeDatabase(), artifact_dir=self.temp.name,
            workbook_builder=build_report_workbook, now_func=lambda: NOW,
        )
        request = ReportRequest(
            report_type=report_type, inicio=datetime(2026, 8, 1), fim=NOW,
            op="PCMIXQ01001" if report_type == "rastreabilidade" else None,
        )
        artifact = service.generate(request, created_by=7, source="manual")
        _record, path = service.get(artifact["id"], user_id=7)
        return path.read_bytes()

    def test_secoes_canonicas_completas_nao_vazam_dado_cru(self):
        for report_type in SECTION_TYPES:
            with self.subTest(report_type=report_type):
                self.assert_clean(self._generate(RichCanonicalFacade(), report_type), report_type)

    def test_fixture_minima_nao_vaza_dado_cru(self):
        for report_type in SECTION_TYPES:
            with self.subTest(report_type=report_type):
                self.assert_clean(self._generate(CanonicalReportFacade(), report_type), report_type)

    def test_tempo_total_de_paradas_usa_o_total_sem_sobreposicao(self):
        workbook = load_workbook(BytesIO(self._generate(RichCanonicalFacade(), "paradas")))
        try:
            valores = [cell.value for row in workbook["Paradas"].iter_rows() for cell in row]
            # 1500 s publicado pelo backend (sobreposição removida), não 900 + 600 somados de novo
            # nem os 1600 s atribuídos.
            self.assertIn("Total sem sobreposição", valores)
            self.assertIn(timedelta(seconds=1500), valores)
        finally:
            workbook.close()

    def test_secao_desconhecida_e_ignorada(self):
        content = build_report_workbook(
            "completo",
            {"sections": {"Resumo Executivo": {}, "Campo Novo": {"x_y": [1, 2]}}},
            AnalyticsFilter(inicio=datetime(2026, 8, 1), fim=NOW),
            generated_at=NOW,
        )
        self.assertEqual(self.assert_clean(content, "desconhecida"), ["Visão Geral"])

    def test_cabecalho_sgq_traz_periodo_filtros_e_emissao(self):
        workbook = load_workbook(BytesIO(self._generate(RichCanonicalFacade(), "ops")))
        try:
            for sheet in workbook.worksheets:
                contexto = sheet["A3"].value
                self.assertIn("Período: 01/08/2026 00:00", contexto)
                self.assertIn("Filtros: Todos os setores", contexto)
                self.assertRegex(contexto, r"Emitido em: \d{2}/\d{2}/\d{4} \d{2}:\d{2}$")
                self.assertNotIn("Gerado em", contexto)
                self.assertEqual(sheet.oddHeader.left.text, "Gestor de Peças")
                self.assertTrue(sheet.oddHeader.right.text.startswith("Ordens de Produção"))
                self.assertTrue(sheet.oddFooter.left.text.startswith("Emitido em "))
        finally:
            workbook.close()


class ExecutiveWorkbookCleanTests(CleanWorkbookMixin, unittest.TestCase):
    def test_relatorios_executivos_nao_vazam_dado_cru(self):
        filtros = AnalyticsFilter(inicio=datetime(2026, 8, 1), fim=NOW, setor="Usinagem")
        for report_type, payload in executive_payloads().items():
            with self.subTest(report_type=report_type):
                content = build_report_workbook(report_type, payload, filtros, generated_at=NOW)
                abas = self.assert_clean(content, report_type)
                if report_type in EXPECTED_EXECUTIVE_SHEETS:
                    self.assertEqual(abas, EXPECTED_EXECUTIVE_SHEETS[report_type])

    def test_payload_vazio_ainda_entrega_visao_geral(self):
        filtros = AnalyticsFilter(inicio=datetime(2026, 8, 1), fim=NOW)
        for report_type in ("gerencial", "producao", "perdas", "indicadores", "dados_analiticos", "desconhecido"):
            with self.subTest(report_type=report_type):
                self.assert_clean(build_report_workbook(report_type, {}, filtros, generated_at=NOW), report_type)


if __name__ == "__main__":
    unittest.main()


class PercentFormatTests(unittest.TestCase):
    def test_inteiro_sem_casas_e_fracionado_com_duas(self):
        from backend.api.report_workbook.kit import percent_format

        self.assertEqual(percent_format(0.96), "0%")
        self.assertEqual(percent_format(0.85), "0%")
        self.assertEqual(percent_format(0.9045), "0.00%")
        self.assertEqual(percent_format(0.4689), "0.00%")
        self.assertEqual(percent_format(0.00004), "0.000%")
