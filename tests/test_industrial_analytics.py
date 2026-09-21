from datetime import datetime, time, timedelta
import unittest

from mes.analytics.physical_time import PhysicalInputSegment, consolidate_physical_time
from mes.analytics.rateio import allocate_duration
from mes.analytics.timeline import build_operator_timeline
from mes.contracts import AnalyticsFilter
from mes.domain import AllocationStrategy, DataAvailability, EventCategory
from mes.services.audit import AuditService
from mes.services.calendar import CalendarService
from mes.services.industrial_analytics import IndustrialAnalyticsService
from mes.services.management import ManagementService
from mes.services.rateio import RateioService
from mes.services.traceability import TraceabilityService


class TimelineTests(unittest.TestCase):
    def test_producao_parada_retorno_separa_lead_time_de_tempo_produtivo(self):
        events = [
            {"id": 1, "estado": "producao", "data_hora": datetime(2026, 8, 19, 8, 0)},
            {"id": 2, "estado": "parada", "data_hora": datetime(2026, 8, 19, 8, 30)},
            {"id": 3, "estado": "producao", "data_hora": datetime(2026, 8, 19, 9, 0)},
            {"id": 4, "estado": "finalizado", "data_hora": datetime(2026, 8, 19, 10, 0)},
        ]
        result = build_operator_timeline(
            events,
            start=datetime(2026, 8, 19, 8, 0),
            end=datetime(2026, 8, 19, 10, 0),
        )
        self.assertEqual(result.seconds(EventCategory.PRODUCTION), 90 * 60)
        self.assertEqual(result.seconds(EventCategory.DOWNTIME), 30 * 60)
        self.assertEqual(result.physical_seconds, 120 * 60)

    def test_parcial_nao_troca_estado_fisico(self):
        events = [
            {"id": 1, "estado": "producao", "data_hora": datetime(2026, 8, 19, 8, 0)},
            {"id": 2, "estado": "parcial", "data_hora": datetime(2026, 8, 19, 8, 20)},
            {"id": 3, "estado": "finalizado", "data_hora": datetime(2026, 8, 19, 9, 0)},
        ]
        result = build_operator_timeline(
            events,
            start=datetime(2026, 8, 19, 8, 0),
            end=datetime(2026, 8, 19, 9, 0),
        )
        self.assertEqual(result.seconds(EventCategory.PRODUCTION), 3600)


class PhysicalTimeConsolidationTests(unittest.TestCase):
    def test_duas_ops_simultaneas_mesmo_recurso_nao_duplicam_tempo_fisico(self):
        segments = [
            PhysicalInputSegment(
                "DOBRA1", "Dobra", EventCategory.PRODUCTION,
                datetime(2026, 8, 19, 8, 0), datetime(2026, 8, 19, 9, 0), "OP1",
            ),
            PhysicalInputSegment(
                "DOBRA1", "Dobra", EventCategory.PRODUCTION,
                datetime(2026, 8, 19, 8, 0), datetime(2026, 8, 19, 9, 0), "OP2",
            ),
        ]
        result = consolidate_physical_time(segments)
        self.assertEqual(result["raw_attributed_seconds"], 7200)
        self.assertEqual(result["physical_seconds"], 3600)
        self.assertEqual(result["totals"][EventCategory.PRODUCTION], 3600)
        self.assertEqual(result["overlap_removed_seconds"], 3600)
        self.assertEqual(result["conflicting_state_seconds"], 0)

    def test_recursos_diferentes_nao_sao_colapsados(self):
        segments = [
            PhysicalInputSegment(
                "DOBRA1", "Dobra", EventCategory.PRODUCTION,
                datetime(2026, 8, 19, 8, 0), datetime(2026, 8, 19, 9, 0), "OP1",
            ),
            PhysicalInputSegment(
                "DOBRA2", "Dobra", EventCategory.PRODUCTION,
                datetime(2026, 8, 19, 8, 0), datetime(2026, 8, 19, 9, 0), "OP2",
            ),
        ]
        result = consolidate_physical_time(segments)
        self.assertEqual(result["physical_seconds"], 7200)
        self.assertEqual(result["overlap_removed_seconds"], 0)

    def test_estados_conflitantes_virao_desconhecido_sem_inflar_tempo(self):
        segments = [
            PhysicalInputSegment(
                "DOBRA1", "Dobra", EventCategory.PRODUCTION,
                datetime(2026, 8, 19, 8, 0), datetime(2026, 8, 19, 9, 0), "OP1",
            ),
            PhysicalInputSegment(
                "DOBRA1", "Dobra", EventCategory.DOWNTIME,
                datetime(2026, 8, 19, 8, 30), datetime(2026, 8, 19, 9, 0), "OP2",
            ),
        ]
        result = consolidate_physical_time(segments)
        self.assertEqual(result["physical_seconds"], 3600)
        self.assertEqual(result["conflicting_state_seconds"], 1800)
        self.assertEqual(result["totals"][EventCategory.PRODUCTION], 1800)
        self.assertEqual(result["totals"][EventCategory.UNKNOWN], 1800)


class RateioTests(unittest.TestCase):
    def test_rateio_conserva_tempo_fisico(self):
        result = allocate_duration(
            3600,
            ["OP-A", "OP-B", "OP-C"],
            strategy=AllocationStrategy.EQUAL,
        )
        self.assertAlmostEqual(sum(result.values()), 3600)
        self.assertTrue(all(value == 1200 for value in result.values()))

    def test_rateio_proporcional_exige_pesos(self):
        with self.assertRaises(ValueError):
            allocate_duration(
                3600,
                ["OP-A", "OP-B"],
                strategy=AllocationStrategy.STANDARD_TIME,
            )


class AuditTests(unittest.TestCase):
    def test_confiabilidade_retorna_contagens_sem_inventar_percentual(self):
        rows = [
            # Refugo sem peça boa não deve mascarar uma finalização inconsistente.
            {"id": 1, "status": "Finalizado", "quantidade_boa": 0, "quantidade_refugo": 3, "maquina": "R1"},
            {"id": 2, "status": "Em processo", "quantidade_boa": 0, "quantidade_refugo": 0, "maquina": "R2", "operador_inicio": None},
        ]
        result = AuditService().data_quality_summary(rows)
        self.assertEqual(result["records_analyzed"], 2)
        self.assertEqual(result["records_with_issue"], 2)
        self.assertEqual(result["reliability_percentage"], None)

    def test_ops_simultaneas_em_producao_nao_sao_inconsistencia_por_si_so(self):
        rows = [
            {
                "id": 10, "op": "OP1", "status": "Finalizado", "maquina": "DOBRA1",
                "operador_inicio": "A", "quantidade_boa": 1,
                "data_inicio": datetime(2026, 8, 19, 8, 0),
                "data_fim": datetime(2026, 8, 19, 9, 0),
                "eventos": [
                    {"id": 1, "estado": "producao", "data_hora": datetime(2026, 8, 19, 8, 0)},
                    {"id": 2, "estado": "finalizado", "data_hora": datetime(2026, 8, 19, 9, 0)},
                ],
            },
            {
                "id": 11, "op": "OP2", "status": "Finalizado", "maquina": "DOBRA1",
                "operador_inicio": "B", "quantidade_boa": 1,
                "data_inicio": datetime(2026, 8, 19, 8, 0),
                "data_fim": datetime(2026, 8, 19, 9, 0),
                "eventos": [
                    {"id": 3, "estado": "producao", "data_hora": datetime(2026, 8, 19, 8, 0)},
                    {"id": 4, "estado": "finalizado", "data_hora": datetime(2026, 8, 19, 9, 0)},
                ],
            },
        ]
        issues = AuditService().inspect_operational_rows(rows)
        self.assertFalse(any(issue["type"] == "recurso_com_multiplas_execucoes" for issue in issues))
        self.assertEqual(AuditService().inspect_timeline_conflicts(rows), [])

    def test_estados_fisicos_conflitantes_no_mesmo_recurso_sao_auditados(self):
        rows = [
            {
                "id": 20, "op": "OP1", "status": "Finalizado", "maquina": "DOBRA1",
                "operador_inicio": "A", "quantidade_boa": 1,
                "data_inicio": datetime(2026, 8, 19, 8, 0),
                "data_fim": datetime(2026, 8, 19, 9, 0),
                "eventos": [
                    {"id": 5, "estado": "producao", "data_hora": datetime(2026, 8, 19, 8, 0)},
                    {"id": 6, "estado": "finalizado", "data_hora": datetime(2026, 8, 19, 9, 0)},
                ],
            },
            {
                "id": 21, "op": "OP2", "status": "Finalizado", "maquina": "DOBRA1",
                "operador_inicio": "B", "quantidade_boa": 1,
                "data_inicio": datetime(2026, 8, 19, 8, 30),
                "data_fim": datetime(2026, 8, 19, 9, 0),
                "eventos": [
                    {"id": 7, "estado": "parada", "data_hora": datetime(2026, 8, 19, 8, 30)},
                    {"id": 8, "estado": "finalizado", "data_hora": datetime(2026, 8, 19, 9, 0)},
                ],
            },
        ]
        issues = AuditService().inspect_timeline_conflicts(rows)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "sobreposicao_estados_incompativeis")
        self.assertEqual(issues[0]["seconds"], 1800)



class _CalendarRepo:
    def listar_turnos_recurso(self, _resource):
        return [{
            "id": 1,
            "nome": "Noturno",
            "dia_semana": 0,  # segunda-feira
            "hora_inicio": time(22, 0),
            "hora_fim": time(6, 0),
            "cruza_meia_noite": True,
            "minutos_intervalo": 30,
        }]


class CalendarTests(unittest.TestCase):
    def test_turno_noturno_e_resolvido_no_dia_seguinte(self):
        result = CalendarService(_CalendarRepo()).resolve_shift(
            "LASER01", datetime(2026, 8, 18, 2, 0)  # terça, dentro do turno de segunda
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["inicio"], datetime(2026, 8, 17, 22, 0))
        self.assertEqual(result["fim"], datetime(2026, 8, 18, 6, 0))
        self.assertEqual(result["tempo_disponivel_segundos"], 7 * 3600 + 30 * 60)


class _RateioRepo:
    def registrar_rateio_recurso(self, *args, **kwargs):
        return {"args": args, "kwargs": kwargs}


class RateioServiceTests(unittest.TestCase):
    def test_nao_aceita_mesma_op_operacao_duplicada_na_sessao(self):
        service = RateioService(_RateioRepo())
        with self.assertRaises(ValueError):
            service.registrar(
                "DOBRA1",
                datetime(2026, 8, 19, 8, 0),
                datetime(2026, 8, 19, 9, 0),
                [
                    {"op": "OP1", "numero_operacao": "20"},
                    {"op": "OP1", "numero_operacao": "20"},
                ],
                strategy=AllocationStrategy.EQUAL,
            )


class _ManagementRepo:
    def listar_fatos_operacionais_periodo(self, *_args, **_kwargs):
        return [
            {
                "id": 1,
                "op": "OP1",
                "tipo_setor": "Dobra",
                "maquina": "DOBRA1",
                "status": "Finalizado",
                "data_inicio": datetime(2026, 8, 19, 8, 0),
                "data_fim": datetime(2026, 8, 19, 10, 0),
                "quantidade_boa": 10,
                "quantidade_refugo": 1,
                "quantidade_retrabalho": 2,
                "produto_codigo": "P1",
                "numero_operacao": "20",
                "codigo_recurso": "DOBRA-ROTEIRO",
                "tempo_medio_segundos": 500.0,
                "eventos": [
                    {"id": 1, "estado": "producao", "data_hora": datetime(2026, 8, 19, 8, 0)},
                    {"id": 2, "estado": "parada", "data_hora": datetime(2026, 8, 19, 8, 30)},
                    {"id": 3, "estado": "producao", "data_hora": datetime(2026, 8, 19, 9, 0)},
                    {"id": 4, "estado": "finalizado", "data_hora": datetime(2026, 8, 19, 10, 0)},
                ],
            }
        ]

    def possui_calendario_produtivo(self, *_args):
        return False

    def listar_tempos_nesting_corte(self, **_kwargs):
        return [
            {
                "apontamento_id": 8,
                "tarefa": "T1",
                "programa": "P1",
                "nesting": 1,
                "maquina": "Laser Ensis 3015",
                "status": "Finalizado",
                "real_segundos": 600.0,
                "previsto_segundos": 540.0,
            }
        ]

    def listar_inconsistencias_dados(self, **_kwargs):
        return []


class ManagementTests(unittest.TestCase):
    def test_overview_expoe_oee_canonico_quando_os_dados_sao_suficientes(self):
        service = ManagementService(_ManagementRepo(), now_func=lambda: datetime(2026, 8, 19, 11, 0))
        filters = AnalyticsFilter(
            datetime(2026, 8, 19, 0, 0),
            datetime(2026, 8, 19, 23, 59),
        )
        result = service.get_overview(filters)
        self.assertEqual(result["production"]["good"], 10)
        self.assertEqual(result["production"]["scrap"], 1)
        self.assertEqual(result["production"]["availability"], DataAvailability.AVAILABLE.value)
        self.assertEqual(result["hours"]["production_seconds"], 6000)
        self.assertEqual(result["hours"]["cutting_production_seconds"], 600)
        self.assertEqual(result["hours"]["downtime_seconds"], 1800)
        self.assertEqual(result["cutting"]["completed_nestings"], 1)
        self.assertEqual(result["kpis"]["oee"]["availability"], DataAvailability.AVAILABLE.value)
        self.assertAlmostEqual(result["kpis"]["availability"]["value"], 6000 / 7800 * 100)
        self.assertAlmostEqual(result["kpis"]["performance"]["value"], 5000 / 6000 * 100)
        self.assertAlmostEqual(result["kpis"]["ftt"]["value"], 10 / 13 * 100)
        self.assertAlmostEqual(
            result["kpis"]["oee"]["value"],
            6000 / 7800 * 5000 / 6000 * 10 / 13 * 100,
        )
        self.assertEqual(result["kpi_contract"]["unit"], "percent_0_100")

    def test_filtro_de_outro_setor_nao_mistura_nestings_de_corte(self):
        service = ManagementService(_ManagementRepo())
        filters = AnalyticsFilter(
            datetime(2026, 8, 19, 0, 0),
            datetime(2026, 8, 19, 23, 59),
            setor="Dobra",
        )
        result = service.get_overview(filters)
        self.assertEqual(result["cutting"]["nestings"], 0)
        self.assertEqual(result["hours"]["cutting_production_seconds"], 0)
        self.assertEqual(result["hours"]["production_seconds"], 5400)

    def test_ausencia_de_evento_de_quantidade_nao_vira_zero_medido(self):
        class EmptyQuantityRepo(_ManagementRepo):
            def listar_fatos_operacionais_periodo(self, *_args, **_kwargs):
                return []

            def listar_eventos_quantidade_periodo(self, *_args, **_kwargs):
                return []

            def listar_tempos_nesting_corte(self, **_kwargs):
                return []

        service = ManagementService(EmptyQuantityRepo())
        result = service.get_overview(AnalyticsFilter(
            datetime(2026, 8, 19, 0, 0),
            datetime(2026, 8, 19, 23, 59),
        ))
        self.assertEqual(result["production"]["availability"], DataAvailability.NO_RECORDS.value)
        self.assertIsNotNone(result["production"]["reason"])
        self.assertIsNone(result["kpis"]["oee"]["value"])
        self.assertEqual(result["kpis"]["oee"]["availability"], DataAvailability.NO_RECORDS.value)


class IndustrialAnalyticsServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = IndustrialAnalyticsService(
            _ManagementRepo(), now_func=lambda: datetime(2026, 8, 19, 11, 0)
        )
        self.filters = AnalyticsFilter(
            datetime(2026, 8, 19, 0, 0),
            datetime(2026, 8, 19, 23, 59),
        )

    def test_paradas_usam_timeline_e_preservam_motivo(self):
        result = self.service.downtimes(self.filters)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["total_seconds"], 1800)
        self.assertEqual(result["items"][0]["evento_id"], 2)

    def test_tempo_padrao_x_real_separa_padrao_unitario(self):
        result = self.service.standard_vs_actual(self.filters)
        row = result["items"][0]
        self.assertEqual(row["tempo_padrao_unitario_segundos"], 500.0)
        self.assertEqual(row["tempo_producao_real_segundos"], 5400)
        self.assertEqual(row["tempo_real_por_peca_segundos"], 540)

    def test_cronoanalise_gera_estatistica_por_produto_operacao_recurso(self):
        result = self.service.chronoanalysis(self.filters)
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(result["groups"][0]["amostras"], 1)
        self.assertEqual(result["groups"][0]["media_segundos_por_peca"], 540)

    def test_capacidade_nao_e_inventada_quando_repository_nao_expoe_configuracao(self):
        result = self.service.capacity_configuration(self.filters)
        self.assertEqual(result["availability"], DataAvailability.NOT_CONFIGURED.value)
        self.assertEqual(result["items"], [])
        # A grandeza publicada é tempo; capacidade em peças não é estimada.
        self.assertEqual(result["unidade"], "tempo")

    def test_confiabilidade_sem_catalogo_de_manutencao_fica_nao_configurada(self):
        result = self.service.reliability(self.filters)
        self.assertEqual(result["availability"], DataAvailability.NOT_CONFIGURED.value)
        self.assertIsNone(result["mtbf_segundos"])
        self.assertIsNone(result["mttr_segundos"])
        self.assertEqual(result["falhas"], 0)


class _ReliabilityRepo(_ManagementRepo):
    """Catálogo real de motivos: só o grupo 0003 é manutenção corretiva."""

    STATUS = [
        {"codigo": "0011", "nome": "MANUTENÇÃO CORRETIVA", "grupo_codigo": "0003",
         "setup": False, "retrabalho": False},
        {"codigo": "0010", "nome": "MANUTENÇÃO PREVENTIVA", "grupo_codigo": "0002",
         "setup": False, "retrabalho": False},
        {"codigo": "9999", "nome": "FALTA DE PEÇAS", "grupo_codigo": "0006",
         "setup": False, "retrabalho": False},
        {"codigo": "1005", "nome": "SETUP", "grupo_codigo": "0003",
         "setup": True, "retrabalho": False},
    ]

    def __init__(self, estados=None, status=None):
        self.estados = estados if estados is not None else []
        self.status = self.STATUS if status is None else status

    def listar_fatos_operacionais_periodo(self, *_args, **_kwargs):
        # A confiabilidade é medida sobre o estado físico do recurso, não sobre
        # a timeline por OP; o repositório deixa isso explícito.
        return []

    def listar_status_recursos(self, **_kwargs):
        return [dict(row) for row in self.status]

    def listar_estados_recurso_periodo(self, _inicio, _fim, *, categoria=None, **_kwargs):
        rows = [dict(row) for row in self.estados]
        if categoria is not None:
            rows = [row for row in rows if row.get("categoria") == categoria]
        return rows

    def listar_tempos_nesting_corte(self, **_kwargs):
        return []


def _estado(identificador, categoria, inicio, fim, *, codigo=None, planejado=False,
            recurso="DOBRA1"):
    return {
        "id": identificador,
        "categoria": categoria,
        "recurso": recurso,
        "tipo_setor": "Dobra",
        "codigo_status_recurso": codigo,
        "motivo": codigo,
        "planejado": planejado,
        "automatico": False,
        "data_inicio": inicio,
        "data_fim": fim,
        "inicio_periodo": inicio,
        "fim_periodo": fim,
    }


class _CapacityRepo(_ReliabilityRepo):
    """Recursos com e sem calendário produtivo cadastrado."""

    def __init__(self, estados=None, *, com_calendario=("DOBRA1",)):
        super().__init__(estados or [])
        self.com_calendario = {str(code).casefold() for code in com_calendario}

    def listar_configuracao_capacidade_recursos(self, **_kwargs):
        return [
            {"codigo": "DOBRA1", "nome": "Gasparini", "tipo_setor": "Dobra",
             "capacidade_valor": None, "capacidade_unidade": None,
             "calendario_codigo": "PADRAO"},
            {"codigo": "DOBRA2", "nome": "2204", "tipo_setor": "Dobra",
             "capacidade_valor": None, "capacidade_unidade": None,
             "calendario_codigo": None},
        ]

    def listar_turnos_recurso(self, resource):
        if str(resource or "").casefold() not in self.com_calendario:
            return []
        # Quarta-feira, 19/08/2026: turno de 8 h sem intervalo declarado.
        return [{
            "id": 1,
            "nome": "Diurno",
            "dia_semana": 2,
            "hora_inicio": time(8, 0),
            "hora_fim": time(16, 0),
            "cruza_meia_noite": False,
            "minutos_intervalo": 0,
        }]


class CapacityTests(unittest.TestCase):
    """Capacidade real = calendário produtivo; nada é estimado sem ele."""

    filters = AnalyticsFilter(
        datetime(2026, 8, 19, 0, 0), datetime(2026, 8, 19, 23, 59)
    )

    def _service(self, repo):
        return IndustrialAnalyticsService(
            repo, now_func=lambda: datetime(2026, 8, 19, 23, 0)
        )

    def test_utilizacao_temporal_usa_calendario_e_tempo_fisico_ocupado(self):
        estados = [
            _estado(1, "producao", datetime(2026, 8, 19, 8, 0), datetime(2026, 8, 19, 10, 0)),
            _estado(2, "setup", datetime(2026, 8, 19, 10, 0), datetime(2026, 8, 19, 12, 0)),
            # Parada ocupa o calendário mas não é carga produtiva do recurso.
            _estado(3, "parada", datetime(2026, 8, 19, 12, 0), datetime(2026, 8, 19, 13, 0),
                    codigo="9999"),
        ]
        result = self._service(_CapacityRepo(estados)).capacity_configuration(self.filters)
        self.assertEqual(result["unidade"], "tempo")
        # Um recurso tem calendário, o outro não: disponibilidade parcial.
        self.assertEqual(result["availability"], DataAvailability.PARTIAL.value)
        self.assertEqual(result["recursos_com_calendario"], 1)
        self.assertEqual(result["recursos_sem_calendario"], 1)

        gasparini = next(item for item in result["items"] if item["codigo"] == "DOBRA1")
        self.assertEqual(gasparini["capacidade_segundos"], 8 * 3600)
        self.assertEqual(gasparini["carga_segundos"], 4 * 3600)
        self.assertAlmostEqual(gasparini["utilizacao_percentual"], 50.0)
        self.assertEqual(gasparini["capacidade_restante_segundos"], 4 * 3600)

        # Sem calendário nenhum número é inventado para o segundo recurso.
        outro = next(item for item in result["items"] if item["codigo"] == "DOBRA2")
        self.assertIsNone(outro["capacidade_segundos"])
        self.assertIsNone(outro["utilizacao_percentual"])
        self.assertEqual(outro["calendario_availability"], DataAvailability.NOT_CONFIGURED.value)

        self.assertEqual(result["bottleneck_resource"], "DOBRA1")
        self.assertAlmostEqual(result["utilizacao_percentual"], 50.0)

    def test_capacidade_planejada_nao_avanca_com_os_segundos_do_relogio(self):
        repo = _CapacityRepo([], com_calendario=("DOBRA1", "DOBRA2"))
        inicio_turno = datetime(2026, 8, 19, 8, 0)

        antes = IndustrialAnalyticsService(
            repo, now_func=lambda: inicio_turno + timedelta(seconds=1)
        ).capacity_configuration(self.filters)
        depois = IndustrialAnalyticsService(
            repo, now_func=lambda: inicio_turno + timedelta(seconds=59)
        ).capacity_configuration(self.filters)

        # O filtro cobre o dia inteiro: a capacidade é o turno planejado de
        # 8 h para cada recurso, independentemente do segundo da consulta.
        # Caso o relógio fosse usado como fim, o total da fábrica avançaria um
        # segundo por recurso e os minutos exibidos saltariam artificialmente.
        self.assertEqual(antes["total_capacity_seconds"], 16 * 3600)
        self.assertEqual(depois["total_capacity_seconds"], 16 * 3600)
        self.assertEqual(
            antes["total_capacity_seconds"], depois["total_capacity_seconds"]
        )

    def test_sem_calendario_algum_a_capacidade_permanece_nao_configurada(self):
        repo = _CapacityRepo([], com_calendario=())
        result = self._service(repo).capacity_configuration(self.filters)
        self.assertEqual(result["availability"], DataAvailability.NOT_CONFIGURED.value)
        self.assertIsNone(result["total_capacity_seconds"])
        self.assertIsNone(result["utilizacao_percentual"])
        self.assertIsNone(result["bottleneck_resource"])
        self.assertTrue(
            all(item["capacidade_segundos"] is None for item in result["items"])
        )


class ReliabilityTests(unittest.TestCase):
    """MTBF/MTTR sobre a taxonomia de manutenção já existente no catálogo."""

    filters = AnalyticsFilter(
        datetime(2026, 8, 19, 0, 0), datetime(2026, 8, 19, 23, 59)
    )

    def _service(self, estados, **kwargs):
        return IndustrialAnalyticsService(
            _ReliabilityRepo(estados, **kwargs),
            now_func=lambda: datetime(2026, 8, 19, 23, 0),
        )

    def test_mtbf_e_mttr_usam_tempo_operacional_e_falhas_corretivas(self):
        estados = [
            # 4 h de produção: tempo operacional canônico.
            _estado(1, "producao", datetime(2026, 8, 19, 8, 0), datetime(2026, 8, 19, 12, 0)),
            # Duas falhas corretivas: 30 min + 90 min de reparo.
            _estado(2, "parada", datetime(2026, 8, 19, 12, 0), datetime(2026, 8, 19, 12, 30),
                    codigo="0011"),
            _estado(3, "parada", datetime(2026, 8, 19, 14, 0), datetime(2026, 8, 19, 15, 30),
                    codigo="0011"),
        ]
        result = self._service(estados).reliability(self.filters)
        self.assertEqual(result["availability"], DataAvailability.AVAILABLE.value)
        self.assertEqual(result["falhas"], 2)
        self.assertEqual(result["reparos_concluidos"], 2)
        self.assertEqual(result["tempo_operacional_segundos"], 4 * 3600)
        self.assertEqual(result["tempo_reparo_segundos"], 2 * 3600)
        self.assertEqual(result["mtbf_segundos"], 4 * 3600 / 2)
        self.assertEqual(result["mttr_segundos"], 2 * 3600 / 2)
        self.assertEqual(result["por_recurso"][0]["recurso"], "DOBRA1")
        self.assertEqual(result["por_recurso"][0]["falhas"], 2)

    def test_falta_de_material_preventiva_e_setup_nunca_viram_falha(self):
        estados = [
            _estado(1, "producao", datetime(2026, 8, 19, 8, 0), datetime(2026, 8, 19, 12, 0)),
            _estado(2, "parada", datetime(2026, 8, 19, 12, 0), datetime(2026, 8, 19, 13, 0),
                    codigo="9999"),
            _estado(3, "parada", datetime(2026, 8, 19, 13, 0), datetime(2026, 8, 19, 14, 0),
                    codigo="0010"),
            # Motivo dentro do grupo de manutenção, porém marcado como setup.
            _estado(4, "parada", datetime(2026, 8, 19, 14, 0), datetime(2026, 8, 19, 15, 0),
                    codigo="1005"),
            # Manutenção corretiva planejada não é quebra.
            _estado(5, "parada", datetime(2026, 8, 19, 15, 0), datetime(2026, 8, 19, 16, 0),
                    codigo="0011", planejado=True),
        ]
        result = self._service(estados).reliability(self.filters)
        self.assertEqual(result["falhas"], 0)
        self.assertIsNone(result["mtbf_segundos"])
        self.assertIsNone(result["mttr_segundos"])
        self.assertEqual(result["availability"], DataAvailability.NO_RECORDS.value)
        self.assertIn("Nenhuma falha", result["reason"])

    def test_periodo_sem_registro_algum_nao_inventa_numero(self):
        result = self._service([]).reliability(self.filters)
        self.assertEqual(result["availability"], DataAvailability.NO_RECORDS.value)
        self.assertIsNone(result["mtbf_segundos"])
        self.assertEqual(result["tempo_operacional_segundos"], 0)

    def test_catalogo_sem_grupo_de_manutencao_fica_nao_configurado(self):
        estados = [
            _estado(1, "parada", datetime(2026, 8, 19, 8, 0), datetime(2026, 8, 19, 9, 0),
                    codigo="9999"),
        ]
        result = self._service(
            estados,
            status=[{"codigo": "9999", "nome": "FALTA DE PEÇAS", "grupo_codigo": "0006",
                     "setup": False, "retrabalho": False}],
        ).reliability(self.filters)
        self.assertEqual(result["availability"], DataAvailability.NOT_CONFIGURED.value)
        self.assertIsNone(result["mtbf_segundos"])



class _NoEventRepo(_ManagementRepo):
    def listar_fatos_operacionais_periodo(self, *_args, **_kwargs):
        return [{
            "id": 77,
            "op": "OP-SEM-EVENTO",
            "tipo_setor": "Dobra",
            "maquina": "DOBRA1",
            "status": "Finalizado",
            "data_inicio": datetime(2026, 8, 19, 8, 0),
            "data_fim": datetime(2026, 8, 19, 9, 0),
            "quantidade_boa": 5,
            "quantidade_refugo": 0,
            "quantidade_retrabalho": 0,
            "produto_codigo": "P1",
            "numero_operacao": "20",
            "tempo_medio_segundos": 600.0,
            "eventos": [],
        }]

    def listar_tempos_nesting_corte(self, **_kwargs):
        return []


class MissingTimelineEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.filters = AnalyticsFilter(
            datetime(2026, 8, 19, 0, 0),
            datetime(2026, 8, 19, 23, 59),
        )

    def test_sem_eventos_lead_time_nao_vira_producao_por_inferencia(self):
        result = IndustrialAnalyticsService(_NoEventRepo()).time_breakdown(self.filters)
        self.assertEqual(result["totals"][EventCategory.PRODUCTION.value], 0)
        self.assertEqual(result["totals"][EventCategory.UNKNOWN.value], 3600)

    def test_tempo_padrao_x_real_fica_indisponivel_sem_evento_ou_rateio(self):
        row = IndustrialAnalyticsService(_NoEventRepo()).standard_vs_actual(self.filters)["items"][0]
        self.assertIsNone(row["tempo_producao_real_segundos"])
        self.assertEqual(row["fonte_tempo_producao"], "dados_insuficientes")


class _ConcurrentManagementRepo(_ManagementRepo):
    def listar_fatos_operacionais_periodo(self, *_args, **_kwargs):
        base = {
            "tipo_setor": "Dobra",
            "maquina": "DOBRA1",
            "status": "Finalizado",
            "data_inicio": datetime(2026, 8, 19, 8, 0),
            "data_fim": datetime(2026, 8, 19, 9, 0),
            "quantidade_boa": 10,
            "quantidade_refugo": 0,
            "quantidade_retrabalho": 0,
            "produto_codigo": "P1",
            "numero_operacao": "20",
            "codigo_recurso": "DOBRA1",
            "tempo_medio_segundos": 180.0,
            "eventos": [
                {"id": 1, "estado": "producao", "data_hora": datetime(2026, 8, 19, 8, 0)},
                {"id": 2, "estado": "finalizado", "data_hora": datetime(2026, 8, 19, 9, 0)},
            ],
        }
        one = dict(base, id=1, op="OP1")
        two = dict(base, id=2, op="OP2")
        two["eventos"] = [
            {"id": 3, "estado": "producao", "data_hora": datetime(2026, 8, 19, 8, 0)},
            {"id": 4, "estado": "finalizado", "data_hora": datetime(2026, 8, 19, 9, 0)},
        ]
        return [one, two]

    def listar_tempos_nesting_corte(self, **_kwargs):
        return []

    def listar_rateios_tempo_periodo(self, *_args, **_kwargs):
        return [{
            "id": 99,
            "recurso": "DOBRA1",
            "tipo_setor": "Dobra",
            "segundos_fisicos_periodo": 3600.0,
            "rateios": [
                {"op": "OP1", "numero_operacao": "20", "segundos_atribuidos_periodo": 1800.0},
                {"op": "OP2", "numero_operacao": "20", "segundos_atribuidos_periodo": 1800.0},
            ],
        }]


class ConcurrentManagementTests(unittest.TestCase):
    def setUp(self):
        self.repo = _ConcurrentManagementRepo()
        self.filters = AnalyticsFilter(
            datetime(2026, 8, 19, 0, 0),
            datetime(2026, 8, 19, 23, 59),
        )

    def test_overview_mantem_3600_segundos_fisicos_com_duas_ops(self):
        result = ManagementService(self.repo).get_overview(self.filters)
        self.assertEqual(result["hours"]["production_seconds"], 3600)
        self.assertEqual(result["hours"]["physical_measured_seconds"], 3600)
        self.assertEqual(result["hours"]["raw_attributed_timeline_seconds"], 7200)
        self.assertEqual(result["hours"]["overlap_removed_seconds"], 3600)
        self.assertEqual(result["rateio"]["physical_seconds"], 3600)
        self.assertEqual(result["rateio"]["attributed_seconds"], 3600)
        self.assertTrue(result["rateio"]["conservation_ok"])

    def test_tempo_padrao_x_real_prefere_tempo_rateado_por_op(self):
        result = IndustrialAnalyticsService(self.repo).standard_vs_actual(self.filters)
        self.assertEqual(len(result["items"]), 2)
        self.assertTrue(all(row["tempo_producao_real_segundos"] == 1800 for row in result["items"]))
        self.assertTrue(all(row["fonte_tempo_producao"] == "rateio" for row in result["items"]))


class _ConcurrentDowntimeRepo(_ConcurrentManagementRepo):
    def listar_fatos_operacionais_periodo(self, *_args, **_kwargs):
        rows = super().listar_fatos_operacionais_periodo()
        rows[0]["eventos"] = [
            {"id": 10, "estado": "parada", "data_hora": datetime(2026, 8, 19, 8, 0), "motivo": "Falta material"},
            {"id": 11, "estado": "finalizado", "data_hora": datetime(2026, 8, 19, 9, 0)},
        ]
        rows[1]["eventos"] = [
            {"id": 12, "estado": "parada", "data_hora": datetime(2026, 8, 19, 8, 0), "motivo": "Falta material"},
            {"id": 13, "estado": "finalizado", "data_hora": datetime(2026, 8, 19, 9, 0)},
        ]
        return rows


class ConcurrentDowntimeTests(unittest.TestCase):
    def test_pareto_de_parada_nao_duplica_mesma_parada_em_ops_simultaneas(self):
        filters = AnalyticsFilter(
            datetime(2026, 8, 19, 0, 0),
            datetime(2026, 8, 19, 23, 59),
        )
        result = IndustrialAnalyticsService(_ConcurrentDowntimeRepo()).downtimes(filters)
        self.assertEqual(result["raw_attributed_seconds"], 7200)
        self.assertEqual(result["total_seconds"], 3600)
        self.assertEqual(result["overlap_removed_seconds"], 3600)
        self.assertEqual(result["by_reason"][0]["motivo"], "Falta material")
        self.assertEqual(result["by_reason"][0]["segundos"], 3600)


class _TraceRepo:
    def listar_fatos_operacionais_periodo(self, *_args, **kwargs):
        self.op_filter = kwargs.get("op")
        return [{
            "id": 31, "op": "OP9", "numero_operacao": "10", "tipo_setor": "Dobra",
            "maquina": "DOBRA1", "status": "Finalizado", "quantidade_boa": 4,
            "quantidade_refugo": 1, "quantidade_retrabalho": 0, "eventos": [],
        }]

    def listar_eventos_quantidade_periodo(self, *_args, **kwargs):
        return [{"id": 50, "tipo": "boa", "quantidade": 4, "op": kwargs.get("op")}]

    def listar_nestings_corte_por_op(self, op):
        return [{"apontamento_id": 70, "tarefa": "T9", "nesting": 1, "op_ref": op}]

    def get_op_timeline(self, op):
        return [{"id": 80, "op": op, "tipo": "Movimentação"}]


class TraceabilityTests(unittest.TestCase):
    def test_drilldown_preserva_ids_das_fontes(self):
        repo = _TraceRepo()
        result = TraceabilityService(repo).trace_op("OP9")
        self.assertEqual(repo.op_filter, "OP9")
        self.assertEqual(result["source_refs"]["operations"], [31])
        self.assertEqual(result["source_refs"]["quantity_events"], [50])
        self.assertEqual(result["source_refs"]["cutting_nestings"], [70])
        self.assertEqual(
            {item["source"] for item in result["timeline"]},
            {"eventos_quantidade_producao", "apontamentos_corte", "historico_legado"},
        )



if __name__ == "__main__":
    unittest.main()
