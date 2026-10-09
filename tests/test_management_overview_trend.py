"""Contrato de ``GET /management/overview/trend`` (``get_overview_trend``).

A tendência não tem fórmula própria: cada ponto, o período anterior e o resumo
vêm de ``get_overview``. Estes testes provam o contrato do payload, a ordem dos
pontos, a equivalência com o OEE canônico e o custo (uma única janela lida).
"""

import unittest
from datetime import datetime, timedelta

from mes.contracts import AnalyticsFilter
from mes.domain import DataAvailability
from mes.services.management import ManagementService
from tests.test_oee_consistency import _ThreeDayOeeRepo

AGORA = datetime(2026, 8, 21)
KPI_KEYS = {"oee", "availability", "performance", "ftt"}
HOURS_KEYS = {
    "production_seconds",
    "setup_seconds",
    "downtime_seconds",
    "rework_seconds",
    "activity_without_op_seconds",
    "no_demand_seconds",
    "out_of_shift_seconds",
}


class _SpyRepo(_ThreeDayOeeRepo):
    def __init__(self):
        self.fact_windows = []

    def listar_fatos_operacionais_periodo(self, inicio, fim, **kwargs):
        self.fact_windows.append((inicio, fim))
        return super().listar_fatos_operacionais_periodo(inicio, fim, **kwargs)


class _EventsRepo(_ThreeDayOeeRepo):
    def __init__(self, rows):
        self.rows = rows
        self.received = []

    def listar_estados_recurso_atuais(self, **kwargs):
        self.received.append(kwargs)
        return list(self.rows)


def _service(repo=None, simulation_mode=False):
    return ManagementService(
        repo or _ThreeDayOeeRepo(), now_func=lambda: AGORA, simulation_mode=simulation_mode
    )


class OverviewTrendContractTests(unittest.TestCase):
    def setUp(self):
        self.filters = AnalyticsFilter(datetime(2026, 8, 19), datetime(2026, 8, 21))
        self.trend = _service().get_overview_trend(self.filters)

    def test_contrato_do_payload(self):
        self.assertEqual(
            set(self.trend),
            {
                "bucket_days", "availability", "reason", "points", "previous",
                "sector_summary", "recent_events", "calculation_policy",
            },
        )
        self.assertEqual(self.trend["bucket_days"], 1)
        self.assertEqual(self.trend["availability"], DataAvailability.AVAILABLE.value)
        self.assertIsNone(self.trend["reason"])
        point = self.trend["points"][0]
        self.assertEqual(
            set(point),
            {
                "period_start", "period_end", "production", "kpis", "hours",
                "planned_quantity", "sectors",
            },
        )
        self.assertEqual(set(point["production"]), {"good", "scrap", "rework"})
        self.assertEqual(set(point["kpis"]), KPI_KEYS)
        self.assertEqual(set(point["hours"]), HOURS_KEYS)
        self.assertEqual(set(point["kpis"]["oee"]), {"value", "availability", "unit", "reason"})

    def test_pontos_em_ordem_e_um_por_intervalo(self):
        service = _service()
        bounds = service._bucket_bounds(self.filters)
        points = self.trend["points"]
        self.assertEqual(len(points), len(bounds))
        self.assertEqual(len(points), 2)
        self.assertEqual(
            [(p["period_start"], p["period_end"]) for p in points],
            [(i.isoformat(), f.isoformat()) for i, f in bounds],
        )
        self.assertEqual(points, sorted(points, key=lambda p: p["period_start"]))

    def test_pontos_replicam_o_overview_canonico_do_intervalo(self):
        service = _service()
        for point, (inicio, fim) in zip(
            self.trend["points"], service._bucket_bounds(self.filters)
        ):
            overview = _service().get_overview(AnalyticsFilter(inicio, fim))
            self.assertEqual(point["kpis"], {k: overview["kpis"][k] for k in KPI_KEYS})
            self.assertEqual(
                point["production"],
                {k: overview["production"][k] for k in ("good", "scrap", "rework")},
            )
            self.assertEqual(
                point["hours"], {k: overview["hours"][k] for k in HOURS_KEYS}
            )
        self.assertEqual(self.trend["points"][0]["production"]["good"], 9)
        self.assertEqual(self.trend["points"][0]["kpis"]["oee"]["value"], 25.0)

    def test_setores_do_ponto_vem_do_overview(self):
        self.assertEqual(
            self.trend["points"][0]["sectors"], [{"setor": "Dobra", "producao_boa": 9}]
        )

    def test_planned_quantity_nulo_fora_de_simulacao(self):
        self.assertTrue(all(p["planned_quantity"] is None for p in self.trend["points"]))

    def test_planned_quantity_vem_da_simulacao_quando_ativa(self):
        trend = _service(simulation_mode=True).get_overview_trend(self.filters)
        self.assertTrue(all(isinstance(p["planned_quantity"], int) for p in trend["points"]))

    def test_resumo_por_setor_traz_oee_do_overview(self):
        overview = _service().get_overview(self.filters)
        # Setor único: o OEE do setor é o próprio OEE do total.
        self.assertEqual(overview["kpis"]["oee"]["value"], 25.0)
        self.assertEqual(
            self.trend["sector_summary"],
            [{
                "setor": "Dobra", "oee": overview["kpis"]["oee"],
                "resources_total": 1, "resources_with_production": 1,
            }],
        )


class _TwoSectorRepo(_ThreeDayOeeRepo):
    """Dobra (25%) e Solda (parada planejada, refugo e peça sem padrão)."""

    DIA = datetime(2026, 8, 20)

    def _at(self, hour, minute=0):
        return self.DIA.replace(hour=hour, minute=minute)

    def listar_fatos_operacionais_periodo(self, inicio, fim, **_kwargs):
        def fact(fid, sector, machine, start, finish, good, scrap, standard):
            return {
                "id": fid, "op": f"OP-{fid}", "tipo_setor": sector, "maquina": machine,
                "status": "Finalizado", "data_inicio": start, "data_fim": finish,
                "quantidade_boa": good, "quantidade_refugo": scrap,
                "quantidade_retrabalho": 0, "tempo_medio_segundos": standard,
                "eventos": [
                    {"id": fid * 10 + 1, "estado": "producao", "data_hora": start},
                    {"id": fid * 10 + 2, "estado": "finalizado", "data_hora": finish},
                ],
            }

        return [
            fact(1, "Dobra", "DOBRA1", self._at(8), self._at(9), 9, 0, 100),
            fact(2, "Solda", "SOLDA1", self._at(8), self._at(10), 20, 2, 300),
            # Peça boa sem tempo padrão: Performance da Solda fica parcial.
            fact(3, "Solda", "SOLDA1", self._at(9), self._at(10), 4, 0, None),
        ]

    def listar_estados_recurso_periodo(self, inicio, fim, **_kwargs):
        def state(sid, resource, sector, category, start, finish, **extra):
            return {
                "id": sid, "recurso": resource, "tipo_setor": sector,
                "categoria": category, "data_inicio": start, "data_fim": finish, **extra,
            }

        return [
            state(1, "DOBRA1", "Dobra", "producao", self._at(8), self._at(9)),
            state(2, "SOLDA1", "Solda", "producao", self._at(8), self._at(10)),
            state(3, "SOLDA1", "Solda", "parada", self._at(10), self._at(10, 30), planejado=True),
            state(4, "SOLDA1", "Solda", "parada", self._at(10, 30), self._at(11), planejado=False),
        ]

    def listar_eventos_quantidade_periodo(self, inicio, fim, **_kwargs):
        return [
            {"tipo": "boa", "quantidade": 9, "tipo_setor": "Dobra", "recurso": "DOBRA1"},
            {"tipo": "boa", "quantidade": 24, "tipo_setor": "Solda", "recurso": "SOLDA1"},
            {"tipo": "refugo", "quantidade": 2, "tipo_setor": "Solda", "recurso": "SOLDA1"},
        ]


class OverviewSectorOeeTests(unittest.TestCase):
    """OEE por setor: calculador canônico sobre as bases do setor, sem fórmula nova."""

    def setUp(self):
        self.filters = AnalyticsFilter(datetime(2026, 8, 19), datetime(2026, 8, 21))
        self.overview = _service(_TwoSectorRepo()).get_overview(self.filters)
        self.by_sector = {item["setor"]: item for item in self.overview["sector_kpis"]}

    def test_exemplo_manual_por_setor(self):
        self.assertEqual(sorted(self.by_sector), ["Dobra", "Solda"])
        dobra = self.by_sector["Dobra"]["metrics"]
        # Dobra: A = 3600/3600; P = 9 x 100 s / 3600 s; FTT = 9/9.
        self.assertAlmostEqual(dobra["availability"]["value"], 100.0)
        self.assertAlmostEqual(dobra["performance"]["value"], 25.0)
        self.assertAlmostEqual(dobra["oee"]["value"], 25.0)
        self.assertEqual(dobra["oee"]["availability"], DataAvailability.AVAILABLE.value)

        solda = self.by_sector["Solda"]
        # Solda: 30 min de parada planejada saem da base; os 30 min não
        # planejados ficam. A = 7200 / (7200 + 1800) = 80%.
        self.assertEqual(solda["parada_planejada_segundos"], 1800.0)
        self.assertAlmostEqual(solda["metrics"]["availability"]["value"], 80.0)
        # P = 20 x 300 s / 7200 s (4 peças sem padrão ficam fora de S_boas).
        self.assertAlmostEqual(solda["metrics"]["performance"]["value"], 6000 / 7200 * 100)
        self.assertEqual(solda["pecas_boas_sem_tempo_padrao"], 4)
        # FTT = 24 / (24 + 2).
        self.assertAlmostEqual(solda["metrics"]["ftt"]["value"], 24 / 26 * 100)
        self.assertAlmostEqual(
            solda["metrics"]["oee"]["value"], 0.8 * (6000 / 7200) * (24 / 26) * 100
        )
        self.assertEqual(
            solda["metrics"]["oee"]["availability"], DataAvailability.PARTIAL.value
        )
        self.assertEqual(solda["calculation_policy"], "canonical_oee")

    def test_soma_das_bases_dos_setores_reproduz_o_oee_total(self):
        from mes.analytics.oee import calculate_oee
        from mes.domain import EventCategory

        rows = self.overview["sectors"]
        sector_kpis = self.overview["sector_kpis"]
        total = lambda key: sum(float(row[key]) for row in rows)  # noqa: E731
        planned = sum(item["parada_planejada_segundos"] for item in sector_kpis)
        recalculated = calculate_oee(
            seconds_by_category={
                EventCategory.PRODUCTION: total("tempo_producao_segundos"),
                EventCategory.SETUP: total("tempo_setup_segundos"),
                EventCategory.REWORK: total("tempo_retrabalho_segundos"),
                EventCategory.ACTIVITY_WITHOUT_OP: total("tempo_atividade_sem_op_segundos"),
                EventCategory.DOWNTIME: total("tempo_parada_segundos") - planned,
                EventCategory.NO_DEMAND: total("tempo_sem_demanda_segundos"),
                EventCategory.QUEUE: total("tempo_fila_segundos"),
            },
            good_quantity=int(total("producao_boa")),
            scrap_quantity=int(total("refugo")),
            rework_quantity=int(total("retrabalho")),
            standard_run_seconds=sum(
                item["kpi_time_bases"]["standard_run_seconds"] for item in sector_kpis
            ),
            good_without_standard_quantity=sum(
                item["pecas_boas_sem_tempo_padrao"] for item in sector_kpis
            ),
        )
        self.assertEqual(recalculated.metrics_dict(), self.overview["kpis"])
        for key in ("available_seconds", "worked_seconds", "standard_run_seconds"):
            self.assertAlmostEqual(
                sum(item["kpi_time_bases"][key] for item in sector_kpis),
                self.overview["kpi_time_bases"][key],
            )
        self.assertEqual(
            planned, self.overview["hours"]["planned_downtime_seconds"]
        )

    def test_resumo_da_tendencia_le_o_oee_publicado_por_setor(self):
        trend = _service(_TwoSectorRepo()).get_overview_trend(self.filters)
        summary = {item["setor"]: item["oee"] for item in trend["sector_summary"]}
        self.assertEqual(summary["Dobra"], self.by_sector["Dobra"]["metrics"]["oee"])
        self.assertEqual(summary["Solda"], self.by_sector["Solda"]["metrics"]["oee"])

    def test_setor_sem_leitura_publicada_fica_nulo(self):
        overview = {
            "sectors": [{"setor": "Pintura"}],
            "resource_kpis": [],
            "sector_kpis": [],
        }
        self.assertEqual(
            ManagementService._trend_sector_summary(overview),
            [{"setor": "Pintura", "oee": None, "resources_total": 0, "resources_with_production": 0}],
        )


class _StateOnlyResourceRepo(_TwoSectorRepo):
    """PINT1 só tem estado (sem demanda): sem apontamento nem quantidade."""

    def listar_estados_recurso_periodo(self, inicio, fim, **kwargs):
        rows = super().listar_estados_recurso_periodo(inicio, fim, **kwargs)
        rows.append({
            "id": 9, "recurso": "PINT1", "tipo_setor": "Pintura",
            "categoria": "sem_demanda", "data_inicio": self._at(8), "data_fim": self._at(10),
        })
        return rows


class OverviewStateOnlyResourceTests(unittest.TestCase):
    def test_recurso_so_com_estado_mantem_o_setor_no_resumo(self):
        filters = AnalyticsFilter(datetime(2026, 8, 19), datetime(2026, 8, 21))
        trend = _service(_StateOnlyResourceRepo()).get_overview_trend(filters)
        summary = {item["setor"]: item for item in trend["sector_summary"]}
        self.assertNotIn("Não informado", summary)
        self.assertEqual(summary["Pintura"]["resources_total"], 1)
        self.assertEqual(summary["Pintura"]["resources_with_production"], 0)


class _CountingRepo(_ThreeDayOeeRepo):
    def __init__(self):
        self.calls = {"calendar": 0, "issues": 0}

    def possui_calendario_produtivo(self, setor, recurso):
        self.calls["calendar"] += 1
        return True

    def listar_inconsistencias_dados(self, somente_abertas=True):
        self.calls["issues"] += 1
        return []


class OverviewTrendCostTests(unittest.TestCase):
    def test_leituras_sem_periodo_sao_feitas_uma_vez_por_janela(self):
        repo = _CountingRepo()
        filters = AnalyticsFilter(datetime(2026, 8, 10), datetime(2026, 8, 20))
        _service(repo).get_overview_trend(filters)
        self.assertEqual(repo.calls, {"calendar": 1, "issues": 1})


class OverviewTrendPreviousPeriodTests(unittest.TestCase):
    def test_periodo_anterior_tem_mesma_duracao_e_leitura_canonica(self):
        filters = AnalyticsFilter(datetime(2026, 8, 19), datetime(2026, 8, 21))
        previous = _service().get_overview_trend(filters)["previous"]

        self.assertEqual(set(previous), {"period_start", "period_end", "production", "kpis"})
        start = datetime.fromisoformat(previous["period_start"])
        end = datetime.fromisoformat(previous["period_end"])
        self.assertEqual(start, datetime(2026, 8, 17))
        self.assertLess(end, filters.inicio)
        self.assertLess(filters.inicio - end, timedelta(seconds=1))
        self.assertLess(
            abs((end - start) - (filters.fim - filters.inicio)), timedelta(seconds=1)
        )
        # 18/08 08:00 pertence ao período anterior.
        self.assertEqual(previous["production"]["good"], 9)
        overview = _service().get_overview(AnalyticsFilter(start, end))
        self.assertEqual(previous["kpis"], {k: overview["kpis"][k] for k in KPI_KEYS})

    def test_periodo_anterior_invalido_vira_null(self):
        filters = AnalyticsFilter(datetime(2000, 1, 5), datetime(2000, 1, 10))
        self.assertIsNone(_service().get_overview_trend(filters)["previous"])

    def test_uma_unica_janela_cobre_intervalos_total_e_anterior(self):
        repo = _SpyRepo()
        filters = AnalyticsFilter(datetime(2026, 8, 19), datetime(2026, 8, 21))
        _service(repo).get_overview_trend(filters)

        self.assertEqual(len(repo.fact_windows), 1)
        inicio, fim = repo.fact_windows[0]
        self.assertEqual(inicio, datetime(2026, 8, 17))
        self.assertEqual(fim, filters.fim)


class OverviewTrendWithoutDataTests(unittest.TestCase):
    def test_periodo_sem_dados_preserva_pontos_e_sinaliza_ausencia(self):
        filters = AnalyticsFilter(datetime(2026, 1, 1), datetime(2026, 1, 4))
        trend = _service().get_overview_trend(filters)

        self.assertEqual(len(trend["points"]), 3)
        self.assertEqual(trend["availability"], DataAvailability.NO_RECORDS.value)
        self.assertTrue(trend["reason"])
        for point in trend["points"]:
            self.assertIsNone(point["kpis"]["oee"]["value"])
            self.assertEqual(point["production"], {"good": 0, "scrap": 0, "rework": 0})
            self.assertEqual(point["sectors"], [])
        self.assertEqual(trend["sector_summary"], [])
        self.assertEqual(trend["recent_events"], [])
        self.assertEqual(trend["previous"]["production"]["good"], 0)

    def test_serie_parcial_quando_apenas_alguns_intervalos_tem_oee(self):
        filters = AnalyticsFilter(datetime(2026, 8, 18), datetime(2026, 8, 23))
        trend = _service().get_overview_trend(filters)
        values = [p["kpis"]["oee"]["value"] is not None for p in trend["points"]]

        self.assertEqual(len(trend["points"]), 5)
        self.assertIn(False, values)
        self.assertEqual(trend["availability"], DataAvailability.PARTIAL.value)
        self.assertIn("parcial", trend["reason"].lower())


class OverviewTrendRecentEventsTests(unittest.TestCase):
    def _row(self, resource, started, **extra):
        return {
            "recurso": resource, "tipo_setor": "Dobra", "categoria": "producao",
            "data_inicio": started, **extra,
        }

    def test_sem_metodo_no_repositorio_devolve_lista_vazia(self):
        filters = AnalyticsFilter(datetime(2026, 8, 19), datetime(2026, 8, 21))
        self.assertEqual(_service().get_overview_trend(filters)["recent_events"], [])

    def test_eventos_ordenados_limitados_a_8_e_dentro_do_periodo(self):
        rows = [
            self._row(f"R{i}", datetime(2026, 8, 20, 8, i)) for i in range(10)
        ] + [self._row("FORA", datetime(2026, 8, 1, 8, 0))]
        rows[0]["status_nome"] = "Setup"
        repo = _EventsRepo(rows)
        filters = AnalyticsFilter(
            datetime(2026, 8, 19), datetime(2026, 8, 21), setor="Dobra"
        )
        events = _service(repo).get_overview_trend(filters)["recent_events"]

        self.assertEqual(len(events), 8)
        self.assertEqual(events[0], {
            "resource": "R9", "resource_name": "R9", "sector": "Dobra", "state": "producao",
            "at": datetime(2026, 8, 20, 8, 9).isoformat(),
        })
        # Código com nome oficial publica o nome limpo, sem alterar a identidade.
        torno = _service(_EventsRepo([self._row("TORNOC", datetime(2026, 8, 20, 8, 0))])).get_overview_trend(filters)["recent_events"]
        self.assertEqual((torno[0]["resource"], torno[0]["resource_name"]), ("TORNOC", "Torno Mecânico"))
        self.assertNotIn("FORA", [e["resource"] for e in events])
        self.assertEqual(
            [e["at"] for e in events], sorted((e["at"] for e in events), reverse=True)
        )
        self.assertEqual(repo.received[0]["setor"], "Dobra")
        self.assertEqual(repo.received[0]["reference_time"], filters.fim)


if __name__ == "__main__":
    unittest.main()
