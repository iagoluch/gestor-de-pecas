import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from backend.api.report_workbook import build_report_workbook
from mes.contracts import ReportError, ReportRequest, resolve_report_period
from mes.contracts import AIRequestContext
from mes.services.ai_tools import AIToolRegistry
from mes.services.industrial_reports import IndustrialReportService
from tests.fakes import FakeDatabase


NOW = datetime(2026, 8, 26, 10, 30)


class CanonicalReportFacade:
    def inicio(self, filters):
        metric = lambda value: {
            "value": value,
            "availability": "disponivel",
            "unit": "%",
            "source": "ManagementService.get_overview",
        }
        return {
            "periodo": filters.to_dict(),
            "kpis": {
                "oee": metric(82.4),
                "availability": metric(91.0),
                "performance": metric(92.0),
                "ftt": metric(98.4),
            },
            "production": {"good": 120, "scrap": 3, "rework": 2, "ops": 4},
            # Mesmas chaves do contrato canônico de ManagementService.get_overview.
            "sectors": [{
                "setor": "Usinagem",
                "producao_boa": 120,
                "refugo": 3,
                "retrabalho": 2,
                "ops": 4,
                "tempo_produtivo_segundos": 3600.0,
            }],
            "insights": {"exceptions": [{"title": "Parada registrada"}]},
        }

    def analise(self, key, filters):
        if key == "oee":
            return {"value": 82.4, "availability": "disponivel", "source": "OeeCalculator"}
        if key == "paradas":
            return {"items": [{"recurso": "Romi", "motivo": "=2+2", "segundos": 900}]}
        if key == "setup":
            return {"items": [{"recurso": "Centro 1", "segundos": 300}]}
        if key == "qualidade":
            return {"totals": {"boa": 120, "refugo": 3, "retrabalho": 2, "ftt": 96.0}}
        raise AssertionError(key)

    def producao_realizada(self, filters):
        return {"production": {"good": 120, "scrap": 3, "rework": 2}, "sectors": []}

    def ordens_producao(self, filters):
        return {"items": [{"op": "OP-1", "status": "Em processo", "quantidade_boa": 120}]}

    def consulta_operacional(self, filters):
        return {"resources": [{"recurso": "Romi", "categoria": "parada"}]}

    def nestings(self, filters):
        return {"items": [{"tarefa": "T-1", "nesting": 1, "real_segundos": 300}]}

    def insights(self, filters):
        return {"exceptions": [{"key": "downtime", "severity": "warning"}]}

    def rastreabilidade(self, op):
        return {"op": op, "trajectory": [{"operation": "10", "resource": "Romi"}]}

    def auditoria(self, filters):
        return {"items": [{"tipo": "conflito_estado", "status": "aberto"}]}


class IndustrialReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = FakeDatabase()
        self.service = IndustrialReportService(
            CanonicalReportFacade(),
            self.database,
            artifact_dir=self.temp.name,
            workbook_builder=build_report_workbook,
            now_func=lambda: NOW,
        )

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def request(report_type="completo", **kwargs):
        return ReportRequest(
            report_type=report_type,
            inicio=datetime(2026, 8, 1),
            fim=NOW,
            **kwargs,
        )

    def test_periodos_diario_semanal_mensal_e_personalizado(self):
        self.assertEqual(resolve_report_period("hoje", now=NOW), (datetime(2026, 8, 26), NOW))
        self.assertEqual(
            resolve_report_period("semana_anterior", now=NOW),
            (datetime(2026, 8, 17), datetime(2026, 8, 24)),
        )
        self.assertEqual(
            resolve_report_period("mes_anterior", now=NOW),
            (datetime(2026, 7, 1), datetime(2026, 8, 1)),
        )
        custom = (datetime(2026, 8, 2), datetime(2026, 8, 5))
        self.assertEqual(
            resolve_report_period("personalizado", now=NOW, inicio=custom[0], fim=custom[1]),
            custom,
        )

    def test_workbook_completo_preserva_kpi_oficial_utf8_e_formula_injection(self):
        artifact = self.service.generate(
            self.request(setor="Usinagem"), created_by=7, source="manual"
        )
        record, path = self.service.get(artifact["id"], user_id=7)
        self.assertEqual(record["filters"]["setor"], "Usinagem")
        self.assertTrue(path.is_file())
        workbook = load_workbook(path, data_only=False)
        try:
            # Abas em português, painel executivo primeiro e auditoria oculta no fim.
            self.assertEqual(workbook.sheetnames, [
                "Visão Geral", "Indicadores", "Produção", "OPs", "Paradas", "Setup",
                "Qualidade", "Recursos", "Setores", "Nestings", "Exceções", "Auditoria",
                "Dados Técnicos",
            ])
            self.assertEqual(workbook["Dados Técnicos"].sheet_state, "hidden")
            oee = workbook["Visão Geral"]["A15"]
            self.assertAlmostEqual(oee.value, 0.824)
            self.assertEqual(oee.number_format, "[<0.001]0.000%;0.0%")
            self.assertEqual(workbook["Paradas"].freeze_panes, "A10")
            values = [cell.value for row in workbook["Paradas"].iter_rows() for cell in row]
            self.assertIn("'=2+2", values)
            formulas = [
                cell.coordinate
                for sheet in workbook.worksheets
                for row in sheet.iter_rows()
                for cell in row
                if cell.data_type == "f"
            ]
            self.assertEqual(formulas, [])
            self.assertIn("Produção", workbook.sheetnames)
        finally:
            workbook.close()

    def test_idempotencia_nao_gera_copia_duplicada(self):
        first = self.service.generate(
            self.request("paradas"),
            created_by=7,
            source="automatico",
            idempotency_key="schedule:1:2026-08-25",
        )
        second = self.service.generate(
            self.request("paradas"),
            created_by=7,
            source="automatico",
            idempotency_key="schedule:1:2026-08-25",
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(self.database.generated_reports), 1)

    def test_propriedade_expiracao_e_path_sao_validados_no_backend(self):
        artifact = self.service.generate(self.request("ops"), created_by=7, source="chat")
        with self.assertRaisesRegex(ReportError, "não encontrado"):
            self.service.get(artifact["id"], user_id=8)
        self.database.generated_reports[0]["storage_path"] = str(Path(self.temp.name).parent / "fora.xlsx")
        with self.assertRaisesRegex(ReportError, "não está disponível"):
            self.service.get(artifact["id"], user_id=7)

    def test_relatorio_sem_dados_nao_cria_aba_vazia(self):
        facade = CanonicalReportFacade()
        facade.nestings = lambda _filters: {"items": [], "availability": "sem_registros"}
        service = IndustrialReportService(
            facade,
            self.database,
            artifact_dir=self.temp.name,
            workbook_builder=build_report_workbook,
            now_func=lambda: NOW,
        )
        artifact = service.generate(self.request("nestings"), created_by=7, source="manual")
        _record, path = service.get(artifact["id"], user_id=7)
        workbook = load_workbook(path, read_only=True)
        try:
            # A seção ainda possui availability e, portanto, é útil; não existe
            # uma tabela vazia ou planilha padrão sem título. A aba técnica
            # preserva a rastreabilidade sem aparecer para o gestor.
            self.assertEqual(workbook.sheetnames, ["Visão Geral", "Nestings", "Dados Técnicos"])
            self.assertNotIn("Sheet", workbook.sheetnames)
        finally:
            workbook.close()

    def test_tool_do_chat_gera_artifact_estruturado_sem_sql(self):
        calls = []

        class ReportSpy:
            def generate(self, request, *, created_by, source, idempotency_key=None):
                calls.append((request, created_by, source, idempotency_key))
                return {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "name": "gestor_paradas.xlsx",
                    "type": request.report_type,
                    "status": "pronto",
                    "download_url": "/api/v1/reports/artifacts/00000000-0000-0000-0000-000000000001/download",
                }

        registry = AIToolRegistry(
            CanonicalReportFacade(),
            now_func=lambda: NOW,
            report_service=ReportSpy(),
        )
        selected = {
            schema["function"]["name"]
            for schema in registry.select_schemas(
                "Gere um Excel das paradas da Usinagem desta semana"
            )
        }
        self.assertEqual(selected, {"generate_industrial_report"})
        result = registry.execute(
            "generate_industrial_report",
            {
                "report_type": "paradas",
                "period_kind": "esta_semana",
                "setor": "Usinagem",
                "include_executive_analysis": False,
            },
            AIRequestContext(user_id=7, management_access=True),
        )
        self.assertEqual(result["data"]["artifact"]["status"], "pronto")
        self.assertEqual(calls[0][0].setor, "Usinagem")
        self.assertEqual((calls[0][1], calls[0][2]), (7, "chat"))
        # A tool do chat também deriva chave determinística de idempotência.
        self.assertTrue(str(calls[0][3] or "").startswith("report:v1:"))
        self.assertNotIn("sql", str(result).casefold())


if __name__ == "__main__":
    unittest.main()
