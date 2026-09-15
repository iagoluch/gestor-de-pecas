"""Wave 6A — calendário operacional, hora extra planejada e classificação de parada.

Os 18 casos temporais homologados com a Manufatura:

01. 08:00 → dentro do turno.
02. 17:30 → fim do turno normal.
03. 18:00 sem HE planejada → fora do turno.
04. 18:00 com HE planejada → janela operacional válida.
05. 21:30 com HE planejada → limite da janela de HE.
06. 01:00 sem HE → fora do turno.
07. 06:00 com HE planejada → janela operacional válida.
08. 07:30 com HE planejada → janela operacional válida.
09. 07:30 sem HE → fora do turno.
10. parada almoço planejada → amarela, não afeta OEE.
11. parada café planejada → amarela, não afeta OEE.
12. parada não planejada → vermelha, impacto operacional conforme regra vigente.
13. "Sem apontamento" → não planejada.
14. "Recurso s/op" → não planejada.
15. mesmo fora de turno em múltiplos setores → não duplica o intervalo global.
16. hora extra planejada → não bloqueia apontamento.
17. fora de turno sem HE → não bloqueia apontamento.
18. recurso sem estado físico → comportamento do alerta.
"""

from datetime import date, datetime, time
import unittest

from mes.analytics.oee import calculate_oee, oee_seconds_by_category
from mes.analytics.physical_time import consolidate_physical_time
from mes.analytics.resource_state import build_physical_state_inputs, classify_state_row
from mes.contracts import AnalyticsFilter
from mes.domain import (
    EventCategory,
    IssueSeverity,
    ManufacturingRules,
    NO_APPOINTMENT_STOP_REASON,
    RESOURCE_WITHOUT_OP_STOP_REASON,
    ShiftWindowKind,
    StopClassification,
)
from mes.services.audit import AuditService
from mes.services.calendar import CalendarService


# Quarta-feira. O calendário de teste cobre segunda a sexta.
DIA = date(2026, 9, 9)
HORA_EXTRA_NOITE = (DIA, time(17, 30), time(21, 30))
HORA_EXTRA_MANHA = (DIA, time(6, 0), time(8, 0))


class _CalendarRepo:
    """Calendário de teste: turno 08:00–17:30 e hora extra como exceção.

    Hora extra planejada não é um segundo turno cadastrado: é uma exceção
    ``disponivel_extra`` do calendário, exatamente como o sistema já configura
    disponibilidade extra hoje.
    """

    def __init__(self, overtime=()):
        self._overtime = tuple(overtime)

    def listar_turnos_recurso(self, _resource):
        return [
            {
                "id": 100 + weekday,
                "calendario_codigo": "FABRICA-TESTE",
                "calendario_nome": "Fábrica (teste)",
                "timezone": "America/Sao_Paulo",
                "nome": "Turno normal",
                "dia_semana": weekday,
                "hora_inicio": time(8, 0),
                "hora_fim": time(17, 30),
                "cruza_meia_noite": False,
                "minutos_intervalo": 0,
            }
            for weekday in range(5)
        ]

    def listar_intervalos_turno(self, _turno_id):
        return []

    def listar_excecoes_calendario_periodo(self, calendario_codigo, inicio, fim):
        return [
            {
                "calendario_codigo": calendario_codigo,
                "data": day,
                "tipo": "disponivel_extra",
                "hora_inicio": start,
                "hora_fim": end,
                "motivo": "Hora extra planejada",
                "ativo": True,
            }
            for day, start, end in self._overtime
            if inicio.date() <= day <= fim.date()
        ]


def _stop_state(
    *,
    recurso,
    setor,
    inicio,
    fim,
    motivo=None,
    grupo=None,
    nome_status=None,
    planejado_evento=None,
    categoria=EventCategory.DOWNTIME.value,
):
    """Linha de ``eventos_estado_recurso`` como a consulta canônica a entrega."""

    return {
        "id": abs(hash((recurso, inicio, motivo))) % 100000,
        "recurso": recurso,
        "tipo_setor": setor,
        "categoria": categoria,
        "motivo": motivo,
        "data_inicio": inicio,
        "data_fim": fim,
        "planejado": planejado_evento,
        "status_nome": nome_status,
        "status_grupo_codigo": grupo,
        "status_planejado": None,
    }


class ShiftWindowTests(unittest.TestCase):
    """Casos 01 a 09 — classificação temporal do calendário operacional."""

    def setUp(self):
        self.sem_he = CalendarService(_CalendarRepo())
        self.com_he = CalendarService(
            _CalendarRepo((HORA_EXTRA_NOITE, HORA_EXTRA_MANHA))
        )

    def _kind(self, service, hora, minuto=0):
        return service.shift_window_kind("DOBRA1", datetime.combine(DIA, time(hora, minuto)))

    def test_caso_01_oito_horas_esta_dentro_do_turno(self):
        self.assertIs(self._kind(self.sem_he, 8), ShiftWindowKind.OFFICIAL_SHIFT)
        self.assertTrue(ManufacturingRules.is_operational_window(self._kind(self.sem_he, 8)))

    def test_caso_02_dezessete_e_trinta_e_o_fim_do_turno_normal(self):
        kind = self._kind(self.sem_he, 17, 30)
        self.assertIs(kind, ShiftWindowKind.OFFICIAL_SHIFT)
        self.assertIn(time(17, 30), ManufacturingRules.shift_end_boundaries)

    def test_caso_03_dezoito_horas_sem_hora_extra_e_fora_do_turno(self):
        kind = self._kind(self.sem_he, 18)
        self.assertIs(kind, ShiftWindowKind.OUT_OF_SHIFT)
        self.assertFalse(ManufacturingRules.counts_as_availability(kind))

    def test_caso_04_dezoito_horas_com_hora_extra_e_janela_operacional(self):
        kind = self._kind(self.com_he, 18)
        self.assertIs(kind, ShiftWindowKind.PLANNED_OVERTIME)
        self.assertTrue(ManufacturingRules.is_operational_window(kind))
        self.assertTrue(ManufacturingRules.counts_as_availability(kind))

    def test_caso_05_vinte_e_uma_e_trinta_e_o_limite_da_hora_extra(self):
        self.assertIs(self._kind(self.com_he, 21, 30), ShiftWindowKind.PLANNED_OVERTIME)
        self.assertIs(self._kind(self.com_he, 21, 31), ShiftWindowKind.OUT_OF_SHIFT)

    def test_caso_06_uma_da_manha_sem_hora_extra_e_fora_do_turno(self):
        self.assertIs(self._kind(self.com_he, 1), ShiftWindowKind.OUT_OF_SHIFT)
        self.assertIs(self._kind(self.sem_he, 1), ShiftWindowKind.OUT_OF_SHIFT)

    def test_caso_07_seis_horas_com_hora_extra_e_janela_operacional(self):
        self.assertIs(self._kind(self.com_he, 6), ShiftWindowKind.PLANNED_OVERTIME)

    def test_caso_08_sete_e_trinta_com_hora_extra_e_janela_operacional(self):
        self.assertIs(self._kind(self.com_he, 7, 30), ShiftWindowKind.PLANNED_OVERTIME)

    def test_caso_09_sete_e_trinta_sem_hora_extra_e_fora_do_turno(self):
        self.assertIs(self._kind(self.sem_he, 7, 30), ShiftWindowKind.OUT_OF_SHIFT)

    def test_hora_extra_planejada_entra_na_disponibilidade_do_periodo(self):
        inicio = datetime.combine(DIA, time(8, 0))
        fim = datetime.combine(DIA, time(22, 0))

        sem = self.sem_he.period_summary("DOBRA1", inicio, fim)
        com = self.com_he.period_summary("DOBRA1", inicio, fim)

        self.assertEqual(sem["tempo_disponivel_segundos"], 9.5 * 3600)
        self.assertEqual(sem["tempo_hora_extra_planejada_segundos"], 0.0)
        self.assertEqual(com["tempo_disponivel_segundos"], 13.5 * 3600)
        self.assertEqual(com["tempo_hora_extra_planejada_segundos"], 4 * 3600)
        self.assertEqual(
            com["janelas_hora_extra"],
            [(datetime.combine(DIA, time(17, 30)), datetime.combine(DIA, time(21, 30)))],
        )

    def test_fora_de_turno_e_o_complemento_da_janela_operacional(self):
        inicio = datetime.combine(DIA, time(0, 0))
        fim = datetime.combine(DIA, time(23, 59))

        sem = self.sem_he.out_of_shift_intervals("DOBRA1", inicio, fim)
        com = self.com_he.out_of_shift_intervals("DOBRA1", inicio, fim)

        self.assertEqual(
            sem,
            [
                (inicio, datetime.combine(DIA, time(8, 0))),
                (datetime.combine(DIA, time(17, 30)), fim),
            ],
        )
        self.assertEqual(
            com,
            [
                (inicio, datetime.combine(DIA, time(6, 0))),
                (datetime.combine(DIA, time(21, 30)), fim),
            ],
        )


class NoDemandStateTests(unittest.TestCase):
    """Fora de turno, sem HE e sem trabalho: ausência de demanda, não parada.

    É o complemento explícito da regra "fora de turno sem HE não vira parada
    não planejada": além de não contar como parada, o caso ganha nome próprio,
    distinto também da ociosidade dentro do turno.
    """

    def setUp(self):
        self.sem_he = CalendarService(_CalendarRepo())
        self.com_he = CalendarService(_CalendarRepo((HORA_EXTRA_NOITE,)))

    def _kind(self, service, hora, minuto=0):
        return service.shift_window_kind("DOBRA1", datetime.combine(DIA, time(hora, minuto)))

    def test_fora_de_turno_sem_he_e_sem_trabalho_e_sem_demanda(self):
        self.assertTrue(ManufacturingRules.resource_has_no_demand(
            category=EventCategory.OUT_OF_SHIFT.value,
            window_kind=self._kind(self.sem_he, 19),
        ))

    def test_dentro_do_turno_e_ociosidade_e_nunca_sem_demanda(self):
        self.assertFalse(ManufacturingRules.resource_has_no_demand(
            category=EventCategory.QUEUE.value,
            window_kind=self._kind(self.sem_he, 10),
        ))

    def test_retorno_automatico_das_0800_e_sem_demanda_sem_generalizar_fila(self):
        self.assertTrue(ManufacturingRules.resource_has_no_demand(
            category=EventCategory.QUEUE.value,
            window_kind=self._kind(self.sem_he, 8),
            active_operations=0,
            explicit_shift_return=True,
        ))

    def test_operacao_ativa_vence_o_retorno_do_turno(self):
        # Invariante do Andon: recurso com apontamento ativo está produzindo,
        # não "sem demanda" — nem mesmo com o estado de retorno do turno
        # pendurado no último evento físico do recurso.
        self.assertFalse(ManufacturingRules.resource_has_no_demand(
            category=EventCategory.QUEUE.value,
            window_kind=self._kind(self.sem_he, 8),
            active_operations=1,
            explicit_shift_return=True,
        ))

    def test_hora_extra_planejada_afasta_a_ausencia_de_demanda(self):
        self.assertFalse(ManufacturingRules.resource_has_no_demand(
            category=EventCategory.OUT_OF_SHIFT.value,
            window_kind=self._kind(self.com_he, 19),
        ))

    def test_alguem_trabalhando_afasta_a_ausencia_de_demanda(self):
        self.assertFalse(ManufacturingRules.resource_has_no_demand(
            category=EventCategory.OUT_OF_SHIFT.value,
            window_kind=self._kind(self.sem_he, 19),
            active_operations=1,
        ))

    def test_parada_declarada_fora_de_turno_continua_parada(self):
        # Uma parada lançada pelo operador não é convertida em "sem demanda"
        # só porque o relógio saiu do turno: ela tem motivo e dono.
        self.assertFalse(ManufacturingRules.resource_has_no_demand(
            category=EventCategory.DOWNTIME.value,
            window_kind=self._kind(self.sem_he, 19),
        ))

    def test_producao_fora_de_turno_continua_producao(self):
        self.assertFalse(ManufacturingRules.resource_has_no_demand(
            category=EventCategory.PRODUCTION.value,
            window_kind=self._kind(self.sem_he, 19),
        ))

    def test_sem_demanda_nao_e_parada_e_nao_afeta_oee(self):
        # A regra irmã continua valendo: fora de turno permanece classificado
        # como planejado e, portanto, fora do OEE.
        classification = ManufacturingRules.classify_stop(
            category=EventCategory.OUT_OF_SHIFT.value
        )
        self.assertIs(classification, StopClassification.PLANNED)
        self.assertFalse(ManufacturingRules.stop_affects_oee(classification))


class StopClassificationTests(unittest.TestCase):
    """Casos 10 a 14 — classificação central e cor derivada dela."""

    @staticmethod
    def _oee(seconds_by_category, planned_downtime_seconds=0.0):
        return calculate_oee(
            seconds_by_category=oee_seconds_by_category(
                seconds_by_category,
                planned_downtime_seconds=planned_downtime_seconds,
            ),
            good_quantity=100,
            scrap_quantity=0,
            rework_quantity=0,
            standard_run_seconds=3600.0,
        )

    def _assert_parada_planejada(self, state_row):
        classification = classify_state_row(state_row)
        self.assertIs(classification, StopClassification.PLANNED)
        self.assertEqual(
            ManufacturingRules.stop_classification_color(classification), "amarelo"
        )
        self.assertEqual(
            ManufacturingRules.stop_classification_ui_token(classification), "warning"
        )
        self.assertFalse(ManufacturingRules.stop_affects_oee(classification))

        sem_parada = {EventCategory.PRODUCTION: 7200.0}
        com_parada = {EventCategory.PRODUCTION: 7200.0, EventCategory.DOWNTIME: 2520.0}
        base = self._oee(sem_parada)
        planejada = self._oee(com_parada, planned_downtime_seconds=2520.0)
        self.assertEqual(
            base.time_bases["available_seconds"],
            planejada.time_bases["available_seconds"],
        )
        self.assertEqual(base.availability.value, planejada.availability.value)
        self.assertEqual(base.oee.value, planejada.oee.value)

    def test_caso_10_almoco_planejado_e_amarelo_e_nao_afeta_oee(self):
        # 12:10–12:52 é a pausa automática de almoço; no catálogo PCFactory o
        # motivo equivalente é `0062 INTERVALO`, do grupo `0002`.
        self._assert_parada_planejada(_stop_state(
            recurso="DOBRA1",
            setor="Dobra",
            inicio=datetime.combine(DIA, time(12, 10)),
            fim=datetime.combine(DIA, time(12, 52)),
            motivo="0062 - INTERVALO",
            grupo="0002",
            nome_status="INTERVALO",
            planejado_evento=True,
        ))

    def test_caso_11_cafe_planejado_e_amarelo_e_nao_afeta_oee(self):
        self._assert_parada_planejada(_stop_state(
            recurso="DOBRA1",
            setor="Dobra",
            inicio=datetime.combine(DIA, time(15, 30)),
            fim=datetime.combine(DIA, time(15, 45)),
            motivo="0009 - PAUSA PARA CAFÉ",
            grupo="0002",
            nome_status="PAUSA PARA CAFÉ",
            planejado_evento=True,
        ))

    def test_caso_12_parada_nao_planejada_e_vermelha_e_reduz_disponibilidade(self):
        classification = classify_state_row(_stop_state(
            recurso="DOBRA1",
            setor="Dobra",
            inicio=datetime.combine(DIA, time(10, 0)),
            fim=datetime.combine(DIA, time(10, 42)),
            motivo="0029 - AGUARDANDO PONTE",
            grupo="0004",
            nome_status="AGUARDANDO PONTE",
        ))
        self.assertIs(classification, StopClassification.UNPLANNED)
        self.assertEqual(
            ManufacturingRules.stop_classification_color(classification), "vermelho"
        )
        self.assertEqual(
            ManufacturingRules.stop_classification_ui_token(classification), "danger"
        )
        self.assertTrue(ManufacturingRules.stop_affects_oee(classification))

        base = self._oee({EventCategory.PRODUCTION: 7200.0})
        nao_planejada = self._oee(
            {EventCategory.PRODUCTION: 7200.0, EventCategory.DOWNTIME: 2520.0}
        )
        self.assertEqual(nao_planejada.time_bases["available_seconds"], 9720.0)
        self.assertLess(nao_planejada.availability.value, base.availability.value)
        self.assertLess(nao_planejada.oee.value, base.oee.value)

    def test_caso_13_sem_apontamento_e_sempre_nao_planejada(self):
        for motivo in (NO_APPOINTMENT_STOP_REASON, "Falta de Apontamento", "sem apontamento"):
            with self.subTest(motivo=motivo):
                self.assertIs(
                    ManufacturingRules.classify_stop(reason=motivo),
                    StopClassification.UNPLANNED,
                )
        # Nem um cadastro marcando o motivo como programado inverte a regra.
        self.assertIs(
            ManufacturingRules.classify_stop(
                reason=NO_APPOINTMENT_STOP_REASON,
                status_row={"grupo_codigo": "0002", "planejado": True},
                planned=True,
            ),
            StopClassification.UNPLANNED,
        )

    def test_caso_14_recurso_sem_op_e_sempre_nao_planejada(self):
        for motivo in (RESOURCE_WITHOUT_OP_STOP_REASON, "Recurso s/ op", "AGUARDANDO OP"):
            with self.subTest(motivo=motivo):
                self.assertIs(
                    ManufacturingRules.classify_stop(reason=motivo),
                    StopClassification.UNPLANNED,
                )
        self.assertIs(
            ManufacturingRules.classify_stop(
                reason=RESOURCE_WITHOUT_OP_STOP_REASON,
                status_row={"grupo_codigo": "0002"},
            ),
            StopClassification.UNPLANNED,
        )

    def test_parada_manual_sem_catalogo_permanece_nao_planejada(self):
        self.assertIs(
            ManufacturingRules.classify_stop(reason="Aguardando material"),
            StopClassification.UNPLANNED,
        )

    def test_fora_de_turno_sem_hora_extra_e_parada_planejada_amarela(self):
        classification = classify_state_row(_stop_state(
            recurso="DOBRA1",
            setor="Dobra",
            inicio=datetime.combine(DIA, time(17, 30)),
            fim=datetime.combine(date(2026, 9, 10), time(8, 0)),
            categoria=EventCategory.OUT_OF_SHIFT.value,
            motivo="Fim de turno — interrupção programada automática",
        ))
        self.assertIs(classification, StopClassification.PLANNED)
        self.assertEqual(
            ManufacturingRules.stop_classification_color(classification), "amarelo"
        )

    def test_pipeline_real_separa_parada_planejada_da_nao_planejada(self):
        inicio = datetime.combine(DIA, time(8, 0))
        fim = datetime.combine(DIA, time(17, 30))
        rows = [
            _stop_state(
                recurso="DOBRA1", setor="Dobra",
                inicio=datetime.combine(DIA, time(12, 10)),
                fim=datetime.combine(DIA, time(12, 52)),
                motivo="0062 - INTERVALO", grupo="0002", nome_status="INTERVALO",
            ),
            _stop_state(
                recurso="DOBRA1", setor="Dobra",
                inicio=datetime.combine(DIA, time(14, 0)),
                fim=datetime.combine(DIA, time(14, 30)),
                motivo="0029 - AGUARDANDO PONTE", grupo="0004",
                nome_status="AGUARDANDO PONTE",
            ),
        ]
        physical = consolidate_physical_time(
            build_physical_state_inputs(rows, inicio=inicio, fim=fim)
        )
        downtime = physical["totals_by_stop_classification"][EventCategory.DOWNTIME]

        self.assertEqual(downtime[StopClassification.PLANNED], 42 * 60)
        self.assertEqual(downtime[StopClassification.UNPLANNED], 30 * 60)
        self.assertEqual(physical["totals"][EventCategory.DOWNTIME], 72 * 60)

        base = oee_seconds_by_category(
            physical["totals"],
            planned_downtime_seconds=downtime[StopClassification.PLANNED],
        )
        self.assertEqual(base[EventCategory.DOWNTIME], 30 * 60)


class GlobalOutOfShiftTests(unittest.TestCase):
    """Caso 15 — fora de turno é grandeza global, não soma por setor."""

    def test_caso_15_fora_de_turno_em_varios_setores_nao_duplica_o_global(self):
        inicio = datetime.combine(DIA, time(17, 30))
        fim = datetime.combine(date(2026, 9, 10), time(8, 0))
        rows = [
            _stop_state(
                recurso=recurso, setor=setor, inicio=inicio, fim=fim,
                categoria=EventCategory.OUT_OF_SHIFT.value,
                motivo="Fim de turno — interrupção programada automática",
            )
            for recurso, setor in (
                ("LASER1", "Corte"), ("DOBRA1", "Dobra"), ("SOLDA1", "Solda")
            )
        ]
        physical = consolidate_physical_time(
            build_physical_state_inputs(rows, inicio=inicio, fim=fim)
        )
        esperado = 14.5 * 3600

        self.assertEqual(physical["totals"][EventCategory.OUT_OF_SHIFT], esperado)
        self.assertEqual(physical["out_of_shift_global_seconds"], esperado)
        self.assertEqual(physical["out_of_shift_attributed_seconds"], 3 * esperado)
        self.assertEqual(physical["out_of_shift_duplicated_seconds"], 2 * esperado)

        # A leitura por recurso e por setor continua correta no seu escopo.
        for recurso in ("LASER1", "DOBRA1", "SOLDA1"):
            self.assertEqual(
                physical["by_resource"][recurso][EventCategory.OUT_OF_SHIFT], esperado
            )
        for setor in ("Corte", "Dobra", "Solda"):
            self.assertEqual(
                physical["by_sector"][setor][EventCategory.OUT_OF_SHIFT], esperado
            )

    def test_fora_de_turno_parcialmente_sobreposto_usa_a_uniao(self):
        rows = [
            _stop_state(
                recurso="LASER1", setor="Corte",
                inicio=datetime.combine(DIA, time(17, 30)),
                fim=datetime.combine(DIA, time(20, 30)),
                categoria=EventCategory.OUT_OF_SHIFT.value,
            ),
            _stop_state(
                recurso="DOBRA1", setor="Dobra",
                inicio=datetime.combine(DIA, time(19, 30)),
                fim=datetime.combine(DIA, time(22, 30)),
                categoria=EventCategory.OUT_OF_SHIFT.value,
            ),
        ]
        physical = consolidate_physical_time(build_physical_state_inputs(
            rows,
            inicio=datetime.combine(DIA, time(17, 0)),
            fim=datetime.combine(DIA, time(23, 0)),
        ))
        self.assertEqual(physical["totals"][EventCategory.OUT_OF_SHIFT], 5 * 3600)
        self.assertEqual(physical["out_of_shift_attributed_seconds"], 6 * 3600)


class ClockNeverBlocksAppointmentTests(unittest.TestCase):
    """Casos 16 e 17 — o relógio, sozinho, nunca bloqueia apontamento."""

    def test_caso_16_hora_extra_planejada_nao_bloqueia_apontamento(self):
        service = CalendarService(_CalendarRepo((HORA_EXTRA_NOITE, HORA_EXTRA_MANHA)))
        for hora, minuto in ((18, 0), (21, 30), (6, 0), (7, 30)):
            momento = datetime.combine(DIA, time(hora, minuto))
            with self.subTest(momento=momento):
                self.assertIs(
                    service.shift_window_kind("DOBRA1", momento),
                    ShiftWindowKind.PLANNED_OVERTIME,
                )
                self.assertTrue(ManufacturingRules.appointment_allowed_at(momento))

    def test_caso_17_fora_de_turno_sem_hora_extra_nao_bloqueia_apontamento(self):
        service = CalendarService(_CalendarRepo())
        for hora, minuto in ((18, 0), (21, 30), (1, 0), (6, 0), (7, 30)):
            momento = datetime.combine(DIA, time(hora, minuto))
            with self.subTest(momento=momento):
                self.assertIs(
                    service.shift_window_kind("DOBRA1", momento),
                    ShiftWindowKind.OUT_OF_SHIFT,
                )
                self.assertTrue(ManufacturingRules.appointment_allowed_at(momento))
                self.assertFalse(ManufacturingRules.counts_as_availability(
                    service.shift_window_kind("DOBRA1", momento)
                ))


class _GapAuditRepo(_CalendarRepo):
    def listar_fatos_operacionais_periodo(self, *_args, **_kwargs):
        return []

    def listar_estados_recurso_periodo(self, *_args, **_kwargs):
        return [_stop_state(
            recurso="DOBRA1",
            setor="Dobra",
            inicio=datetime.combine(DIA, time(8, 0)),
            fim=datetime.combine(DIA, time(9, 0)),
            categoria=EventCategory.PRODUCTION.value,
        )]

    def listar_rateios_tempo_periodo(self, *_args, **_kwargs):
        return []

    def listar_configuracao_capacidade_recursos(self, **_kwargs):
        return [{
            "codigo": "DOBRA1",
            "tipo_setor": "Dobra",
            "calendario_codigo": "FABRICA-TESTE",
        }]


class PhysicalStateGapAlertTests(unittest.TestCase):
    """Caso 18 — recurso sem estado físico não gera alerta ao usuário.

    A lacuna descreve recurso ocioso dentro do turno, condição operacional
    normal já representada como parada não planejada ("Sem apontamento") nas
    métricas. O cálculo continua disponível como diagnóstico interno.
    """

    def setUp(self):
        self.service = AuditService(
            _GapAuditRepo(), now_func=lambda: datetime.combine(DIA, time(17, 30))
        )
        self.filters = AnalyticsFilter(
            datetime.combine(DIA, time(8, 0)),
            datetime.combine(DIA, time(17, 30)),
        )

    def test_caso_18_lacuna_de_calendario_nao_entra_nos_alertas(self):
        result = self.service.run_period(self.filters)

        tipos = {issue["type"] for issue in result["issues"]}
        self.assertNotIn("recurso_em_turno_sem_status", tipos)
        self.assertEqual(
            result["count"],
            sum(1 for issue in result["issues"] if issue["type"] != "recurso_em_turno_sem_status"),
        )

    def test_caso_18_a_lacuna_permanece_como_diagnostico_interno(self):
        result = self.service.run_period(self.filters)
        diagnostics = result["diagnostics"]

        self.assertFalse(diagnostics["presented_as_alert"])
        self.assertEqual(diagnostics["calendar_gap_count"], 1)
        self.assertEqual(diagnostics["calendar_gap_seconds"], 8.5 * 3600)
        self.assertEqual(
            diagnostics["calendar_gaps"][0]["severity"], IssueSeverity.INFO.value
        )
        self.assertEqual(
            diagnostics["calendar_gaps"][0]["type"], "recurso_em_turno_sem_status"
        )


if __name__ == "__main__":
    unittest.main()
