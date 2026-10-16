"""Explicação clicável (Fase 1) — consolidação reutilizável e divisor da média.

Tarefa 2: ``ManagementService.physical_consolidation`` é a mesma conta que
``get_overview`` publica, e ``hours.resource_count`` passa a ser o número de
recursos que tiveram turno/calendário no período (``hours.day_count`` informa
os dias).

Sobre o "sem demanda" (spec, seção 8): no overview, ``NO_DEMAND`` vem SÓ dos
estados gravados em ``eventos_estado_recurso``. ``physical_state_category``
reclassifica, na leitura, toda ``fila`` sem OP; nada é sintetizado a partir do
calendário. Por isso o tempo sem demanda de dias passados já é explicável pelos
mesmos ids de evento (``estado_recurso:<id>``).
"""

from datetime import datetime, time
import unittest

from mes.contracts import AnalyticsFilter
from mes.domain import EventCategory
from mes.services.management import ManagementService
from mes.services.metric_explanation import (
    MetricExplanationService,
    UnknownMetricError,
)


QUARTA = datetime(2026, 8, 19)  # dia_semana 2
QUINTA = datetime(2026, 8, 20)  # dia_semana 3


def _estado(id_, recurso, categoria, inicio, fim, **extra):
    return {
        "id": id_,
        "recurso": recurso,
        "tipo_setor": "Dobra",
        "categoria": categoria,
        "data_inicio": inicio,
        "data_fim": fim,
        **extra,
    }


def _turno(dia_semana):
    return {
        "id": dia_semana,
        "nome": "Diurno",
        "dia_semana": dia_semana,
        "hora_inicio": time(8, 0),
        "hora_fim": time(16, 0),
        "cruza_meia_noite": False,
        "minutos_intervalo": 0,
    }


class _Repo:
    """Repositório mínimo: só estados físicos e turnos por recurso."""

    def __init__(self, estados, turnos=None):
        self._estados = estados
        self._turnos = {k.casefold(): v for k, v in (turnos or {}).items()}

    def listar_fatos_operacionais_periodo(self, *_a, **_k):
        return []

    def listar_estados_recurso_periodo(self, *_a, **_k):
        return [dict(row) for row in self._estados]

    def listar_eventos_quantidade_periodo(self, *_a, **_k):
        return []

    def listar_tempos_nesting_corte(self, **_k):
        return []

    def possui_calendario_produtivo(self, *_a):
        return bool(self._turnos)

    def listar_turnos_recurso(self, recurso):
        return [dict(t) for t in self._turnos.get(str(recurso).casefold(), [])]

    def listar_rateios_tempo_periodo(self, *_a, **_k):
        return []

    def listar_inconsistencias_dados(self, **_k):
        return []


def _service(repo):
    return ManagementService(repo, now_func=lambda: datetime(2026, 8, 21, 12, 0))


class OverviewNumbersUnchangedTests(unittest.TestCase):
    """Caracterização: os números do overview não mudam com a extração."""

    def setUp(self):
        estados = [
            _estado(1, "DOBRA1", "fora_turno", QUARTA, QUARTA.replace(hour=8),
                    automatico=True, planejado=True, tipo_interrupcao="fim_turno"),
            _estado(2, "DOBRA1", "producao", QUARTA.replace(hour=8), QUARTA.replace(hour=9)),
            _estado(3, "DOBRA1", "parada", QUARTA.replace(hour=9), QUARTA.replace(hour=10),
                    planejado=True, motivo="Reunião"),
            _estado(4, "DOBRA1", "parada", QUARTA.replace(hour=10), QUARTA.replace(hour=12),
                    planejado=False, motivo="Falta de material"),
            _estado(5, "DOBRA1", "fila", QUARTA.replace(hour=12), QUARTA.replace(hour=14)),
        ]
        self.filters = AnalyticsFilter(QUARTA, QUARTA.replace(hour=23, minute=59))
        self.overview = _service(_Repo(estados, {"DOBRA1": [_turno(2)]})).get_overview(self.filters)

    def test_overview_numbers_unchanged_after_extraction(self):
        # Valores calculados à mão e conferidos no overview ANTES da extração.
        hours = self.overview["hours"]
        self.assertEqual(hours["no_demand_seconds"], 2 * 3600)
        self.assertEqual(hours["downtime_seconds"], 3 * 3600)
        self.assertEqual(hours["planned_downtime_seconds"], 1 * 3600)
        self.assertEqual(hours["unplanned_downtime_seconds"], 2 * 3600)
        self.assertEqual(hours["production_seconds"], 1 * 3600)
        self.assertEqual(hours["out_of_shift_seconds"], 8 * 3600)
        self.assertEqual(hours["physical_measured_seconds"], 14 * 3600)

    def test_physical_consolidation_is_the_same_calculation(self):
        consolidation = _service(_Repo([], {})).physical_consolidation(self.filters)
        self.assertEqual(
            set(consolidation),
            {
                "consolidated", "calendar_resources", "days", "calculated_at",
                "state_rows", "legacy_without_interval",
            },
        )

        service = _service(_Repo(
            [_estado(2, "DOBRA1", "producao", QUARTA.replace(hour=8), QUARTA.replace(hour=9))],
            {"DOBRA1": [_turno(2)]},
        ))
        result = service.physical_consolidation(self.filters)
        self.assertEqual(result["consolidated"]["totals"][EventCategory.PRODUCTION], 3600)
        self.assertEqual(result["calendar_resources"], {"DOBRA1"})
        self.assertEqual(result["days"], 1)
        self.assertEqual(result["calculated_at"], datetime(2026, 8, 21, 12, 0))
        # Mesma origem que o overview publica: segmentos carregam o id do evento.
        segment = result["consolidated"]["segments"][0]
        self.assertEqual(segment.source_refs, ("estado_recurso:2",))


class DivisorTests(unittest.TestCase):
    def test_resource_count_is_resources_with_calendar(self):
        estados = [
            _estado(i, f"DOBRA{i}", "producao", QUARTA.replace(hour=8), QUARTA.replace(hour=9))
            for i in (1, 2, 3)
        ]
        repo = _Repo(estados, {"DOBRA1": [_turno(2)], "DOBRA2": [_turno(2)]})
        filters = AnalyticsFilter(QUARTA, QUARTA.replace(hour=23, minute=59))

        hours = _service(repo).get_overview(filters)["hours"]

        self.assertEqual(hours["resource_count"], 2)
        self.assertEqual(hours["day_count"], 1)

    def test_multi_day_divisor_is_distinct_resources(self):
        estados = [
            _estado(1, "A", "producao", QUARTA.replace(hour=8), QUARTA.replace(hour=9)),
            _estado(2, "B", "producao", QUINTA.replace(hour=8), QUINTA.replace(hour=9)),
            # Sexta: turno cadastrado só fora do período pedido; não conta.
            _estado(3, "C", "producao", QUINTA.replace(hour=10), QUINTA.replace(hour=11)),
        ]
        repo = _Repo(estados, {"A": [_turno(2)], "B": [_turno(3)], "C": [_turno(4)]})
        filters = AnalyticsFilter(QUARTA, QUINTA.replace(hour=23, minute=59))

        hours = _service(repo).get_overview(filters)["hours"]

        self.assertEqual(hours["resource_count"], 2)
        self.assertEqual(hours["day_count"], 2)

    def test_day_count_treats_midnight_end_as_exclusive(self):
        repo = _Repo([], {})
        filters = AnalyticsFilter(QUARTA, datetime(2026, 8, 21))
        self.assertEqual(_service(repo).physical_consolidation(filters)["days"], 2)


class ResourceCountPerDayTests(unittest.TestCase):
    def test_resource_with_shifts_on_two_days_counts_once(self):
        # Revisão da Tarefa 2 (M1): divisor = recursos distintos, não recurso x dia.
        estados = [
            _estado(1, "A", "producao", QUARTA.replace(hour=8), QUARTA.replace(hour=9)),
            _estado(2, "A", "producao", QUINTA.replace(hour=8), QUINTA.replace(hour=9)),
        ]
        repo = _Repo(estados, {"A": [_turno(2), _turno(3)]})
        filters = AnalyticsFilter(QUARTA, QUINTA.replace(hour=23, minute=59))

        hours = _service(repo).get_overview(filters)["hours"]

        self.assertEqual(hours["resource_count"], 1)
        self.assertEqual(hours["day_count"], 2)


# -- Serviço de explicação (Tarefa 3) ---------------------------------------

H = 3600


def _at(day, hour, minute=0):
    return day.replace(hour=hour, minute=minute)


def _full_day_states():
    """Quarta-feira com todas as categorias de tempo, resultado conhecido.

    sem demanda 6 h (Dobra 5 h = DOBRA2 3 + DOBRA1 2; Corte 1 h), parada
    planejada 1 h (almoço), não planejada 2 h, a esclarecer 1 h (DOBRA3).
    """

    return [
        _estado(1, "DOBRA1", "fora_turno", _at(QUARTA, 0), _at(QUARTA, 8),
                automatico=True, planejado=True, tipo_interrupcao="fim_turno"),
        _estado(2, "DOBRA1", "producao", _at(QUARTA, 8), _at(QUARTA, 9),
                operador="Ana", origem="app"),
        _estado(3, "DOBRA1", "parada", _at(QUARTA, 9), _at(QUARTA, 10),
                planejado=True, motivo="Almoço"),
        _estado(4, "DOBRA1", "parada", _at(QUARTA, 10), _at(QUARTA, 12),
                planejado=False, motivo="Falta de material"),
        _estado(5, "DOBRA1", "fila", _at(QUARTA, 12), _at(QUARTA, 14),
                operador="Sistema", origem="sistema"),
        _estado(6, "DOBRA2", "fila", _at(QUARTA, 8), _at(QUARTA, 11)),
        _estado(7, "LASER1", "fila", _at(QUARTA, 8), _at(QUARTA, 9),
                tipo_setor="Corte", operador="Maria", origem="sistema"),
        # Conflito: produção e setup ao mesmo tempo no mesmo recurso (9h-10h).
        _estado(8, "DOBRA3", "producao", _at(QUARTA, 8), _at(QUARTA, 10)),
        _estado(9, "DOBRA3", "setup", _at(QUARTA, 9), _at(QUARTA, 11)),
        _estado(10, "DOBRA4", "retrabalho", _at(QUARTA, 8), _at(QUARTA, 9)),
        _estado(11, "DOBRA4", "atividade_sem_op", _at(QUARTA, 9), _at(QUARTA, 10)),
    ]


_FULL_DAY_TURNOS = {
    name: [_turno(2)]
    for name in ("DOBRA1", "DOBRA2", "DOBRA3", "DOBRA4", "LASER1")
}

_METRIC_TO_HOURS_KEY = {
    "tempo.producao": "production_seconds",
    "tempo.setup": "setup_seconds",
    "tempo.sem_demanda": "no_demand_seconds",
    "tempo.parada_planejada": "planned_downtime_seconds",
    "tempo.parada_nao_planejada": "unplanned_downtime_seconds",
    "tempo.a_esclarecer": "conflicting_state_seconds",
    "tempo.fora_turno": "out_of_shift_seconds",
    "tempo.retrabalho": "rework_seconds",
    "tempo.atividade_sem_op": "activity_without_op_seconds",
}


def _explainer(estados=None, turnos=None):
    repo = _Repo(
        _full_day_states() if estados is None else estados,
        _FULL_DAY_TURNOS if turnos is None else turnos,
    )
    return MetricExplanationService(_service(repo), repo), repo


def _day_filters(day=QUARTA):
    return AnalyticsFilter(day, day.replace(hour=23, minute=59))


def _count_nodes(nodes):
    return sum(1 + _count_nodes(node.children) for node in nodes)


def _assert_totals_equal_overview(case, explainer, repo, filters):
    hours = _service(repo).get_overview(filters)["hours"]
    expected = {
        metric: hours[key] for metric, key in _METRIC_TO_HOURS_KEY.items()
    }
    # Mesma conta do cartão da Visão Geral (frontend_facade.inicio()).
    expected["tempo.parada_nao_planejada"] = (
        hours["downtime_seconds"] - hours["planned_downtime_seconds"]
    )
    for metric, number in expected.items():
        with case.subTest(metric=metric):
            tree = explainer.explain(metric, filters)
            case.assertEqual(tree.total_seconds, number)
            case.assertTrue(tree.reconciliation["ok"], tree.reconciliation)
            case.assertEqual(tree.reconciliation["diff_seconds"], 0)


class _LegacyRepo(_Repo):
    """Sem estados gravados: só apontamentos (timeline) e nesting sem horário."""

    def __init__(self, facts, nestings=(), turnos=None):
        super().__init__([], turnos)
        self._facts = facts
        self._nestings = list(nestings)

    def listar_fatos_operacionais_periodo(self, *_a, **_k):
        return [dict(fact) for fact in self._facts]

    def listar_tempos_nesting_corte(self, **_k):
        return [dict(row) for row in self._nestings]


def _fact(fact_id, machine, sector, start, finish, events):
    return {
        "id": fact_id, "op": f"OP-{fact_id}", "tipo_setor": sector, "maquina": machine,
        "status": "Finalizado", "data_inicio": start, "data_fim": finish,
        "quantidade_boa": 1, "quantidade_refugo": 0, "quantidade_retrabalho": 0,
        "tempo_medio_segundos": 60, "eventos": events,
    }


class LegacyReadingTests(unittest.TestCase):
    """Leitura sem estado canônico (fallback por apontamento + nesting legado)."""

    def setUp(self):
        self.filters = _day_filters()
        facts = [
            _fact(1, "DOBRA1", "Dobra", _at(QUARTA, 8), _at(QUARTA, 10), [
                {"id": 11, "estado": "producao", "data_hora": _at(QUARTA, 8)},
                {"id": 12, "estado": "parada", "data_hora": _at(QUARTA, 9)},
                {"id": 13, "estado": "finalizado", "data_hora": _at(QUARTA, 10)},
            ]),
        ]
        nestings = [{
            "maquina": "LASER1", "status": "finalizado",
            "real_periodo_segundos": 5400, "previsto_segundos": 0,
        }]
        self.repo = _LegacyRepo(
            facts, nestings, {"DOBRA1": [_turno(2)], "LASER1": [_turno(2)]}
        )
        self.explainer = MetricExplanationService(_service(self.repo), self.repo)

    def test_producao_includes_nesting_without_interval_like_overview(self):
        hours = _service(self.repo).get_overview(self.filters)["hours"]
        tree = self.explainer.explain("tempo.producao", self.filters)

        self.assertEqual(hours["production_seconds"], 1 * H + 5400)
        self.assertEqual(tree.total_seconds, hours["production_seconds"])
        self.assertTrue(tree.reconciliation["ok"], tree.reconciliation)
        self.assertEqual(sum(s.seconds for s in tree.children), tree.total_seconds)
        corte = next(s for s in tree.children if s.label == "Corte")
        stretch = corte.children[0].children[0]
        self.assertEqual(corte.children[0].label, "LASER1")
        self.assertEqual(stretch.label, "Apontamento de nesting sem horário de início/fim")
        self.assertEqual(stretch.seconds, 5400)
        self.assertEqual(stretch.detail["origin"], "nesting")
        self.assertIsNone(stretch.detail["start"])
        self.assertIsNone(stretch.detail["record_id"])

    def test_parent_total_matches_measured_seconds(self):
        hours = _service(self.repo).get_overview(self.filters)["hours"]
        tree = self.explainer.explain("tempo.producao", self.filters)
        self.assertEqual(
            tree.parent_total_seconds,
            hours["measured_seconds"] - hours["out_of_shift_attributed_seconds"],
        )
        sibling = next(s for s in tree.siblings if s["metric"] == "tempo.producao")
        self.assertEqual(sibling["seconds"], hours["production_seconds"])

    def test_nao_planejada_matches_home_card_without_classification(self):
        # Sem estado canônico a parada não vem classificada; o cartão mostra
        # parada total menos a planejada, e a explicação tem de bater com ele.
        hours = _service(self.repo).get_overview(self.filters)["hours"]
        planned = self.explainer.explain("tempo.parada_planejada", self.filters)
        unplanned = self.explainer.explain("tempo.parada_nao_planejada", self.filters)

        self.assertEqual(hours["downtime_seconds"], 1 * H)
        self.assertEqual(hours["unplanned_downtime_seconds"], 0)  # por classe
        self.assertEqual(unplanned.total_seconds, 1 * H)
        self.assertEqual(
            planned.total_seconds + unplanned.total_seconds, hours["downtime_seconds"]
        )
        self.assertTrue(unplanned.reconciliation["ok"])

    def test_all_totals_equal_overview(self):
        _assert_totals_equal_overview(self, self.explainer, self.repo, self.filters)


class MetricExplanationTests(unittest.TestCase):
    def setUp(self):
        self.explainer, self.repo = _explainer()
        self.filters = _day_filters()

    def test_sem_demanda_tree_sums_to_total(self):
        tree = self.explainer.explain("tempo.sem_demanda", self.filters)

        self.assertEqual(tree.total_seconds, 6 * H)
        self.assertTrue(tree.reconciliation["ok"])
        self.assertEqual(sum(s.seconds for s in tree.children), tree.total_seconds)
        for sector in tree.children:
            self.assertEqual(sum(r.seconds for r in sector.children), sector.seconds)
            for resource in sector.children:
                self.assertEqual(sum(t.seconds for t in resource.children), resource.seconds)
        self.assertEqual(
            [(s.label, s.seconds) for s in tree.children],
            [("Dobra", 5 * H), ("Corte", 1 * H)],
        )
        self.assertEqual(
            [(r.label, r.seconds) for r in tree.children[0].children],
            [("DOBRA2", 3 * H), ("DOBRA1", 2 * H)],
        )

    def test_total_equals_overview_number(self):
        _assert_totals_equal_overview(self, self.explainer, self.repo, self.filters)

    def test_every_metric_is_non_trivial_in_the_fixture(self):
        # Protege os testes acima de passarem por vácuo (tudo zero).
        for metric in _METRIC_TO_HOURS_KEY:
            with self.subTest(metric=metric):
                self.assertGreater(
                    self.explainer.explain(metric, self.filters).total_seconds, 0
                )

    def test_parada_two_lines_plus_a_esclarecer_sum(self):
        hours = _service(self.repo).get_overview(self.filters)["hours"]
        planned = self.explainer.explain("tempo.parada_planejada", self.filters)
        unplanned = self.explainer.explain("tempo.parada_nao_planejada", self.filters)
        unclear = self.explainer.explain("tempo.a_esclarecer", self.filters)

        self.assertEqual(planned.total_seconds, 1 * H)
        self.assertEqual(unplanned.total_seconds, 2 * H)
        self.assertEqual(unclear.total_seconds, 1 * H)
        # Parada consolidada = planejada + não planejada; o conflito vira a
        # terceira linha, nunca escondido dentro de uma das duas.
        self.assertEqual(
            planned.total_seconds + unplanned.total_seconds, hours["downtime_seconds"]
        )
        self.assertEqual(unclear.total_seconds, hours["conflicting_state_seconds"])

    def test_stretch_detail_has_origin_and_record_id(self):
        tree = self.explainer.explain("tempo.sem_demanda", self.filters)
        corte = next(s for s in tree.children if s.label == "Corte")
        stretch = corte.children[0].children[0]

        self.assertEqual(stretch.kind, "stretch")
        self.assertEqual(stretch.detail["record_id"], "estado_recurso:7")
        self.assertEqual(stretch.detail["origin"], "sistema")
        self.assertEqual(stretch.detail["who"], "Maria")
        self.assertEqual(stretch.detail["start"], _at(QUARTA, 8).isoformat())
        self.assertEqual(stretch.detail["end"], _at(QUARTA, 9).isoformat())

    def test_who_is_none_when_event_has_no_operator(self):
        tree = self.explainer.explain("tempo.sem_demanda", self.filters)
        dobra2 = next(
            r for s in tree.children for r in s.children if r.label == "DOBRA2"
        )
        detail = dobra2.children[0].detail
        self.assertIsNone(detail["who"])
        self.assertEqual(detail["record_id"], "estado_recurso:6")
        # Sem a coluna de origem, a origem é o tipo da fonte do registro.
        self.assertEqual(detail["origin"], "estado_recurso")

    def test_details_come_from_consolidation_without_repository(self):
        # Os estados já vêm da consolidação: nenhuma leitura extra.
        service = MetricExplanationService(_service(self.repo), None)
        tree = service.explain("tempo.sem_demanda", self.filters)
        corte = next(s for s in tree.children if s.label == "Corte")
        detail = corte.children[0].children[0].detail
        self.assertEqual(detail["who"], "Maria")
        self.assertEqual(detail["record_id"], "estado_recurso:7")

    def test_no_extra_state_query(self):
        calls = []
        original = self.repo.listar_estados_recurso_periodo

        def counting(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        self.repo.listar_estados_recurso_periodo = counting
        self.explainer.explain("tempo.sem_demanda", self.filters)
        self.assertEqual(len(calls), 1)  # só a da consolidação

    def test_excluded_items_listed_with_reason(self):
        tree = self.explainer.explain("tempo.sem_demanda", self.filters)

        almoco = [e for e in tree.excluded if "Almoço" in e["label"]]
        self.assertEqual(len(almoco), 1)
        self.assertEqual(almoco[0]["seconds"], 1 * H)
        self.assertTrue(almoco[0]["reason"].strip())
        self.assertIn("Parada planejada", almoco[0]["label"])
        for item in tree.excluded:
            self.assertTrue(item["reason"].strip())
            self.assertGreater(item["seconds"], 0)
        # Fora de turno é calendário, não tempo do recurso dentro do turno.
        self.assertFalse(any("Fora de turno" in e["label"] for e in tree.excluded))

    def test_parent_total_and_siblings(self):
        tree = self.explainer.explain("tempo.sem_demanda", self.filters)
        by_metric = {s["metric"]: s["seconds"] for s in tree.siblings}

        self.assertEqual(list(by_metric), [
            "tempo.producao", "tempo.setup", "tempo.sem_demanda",
            "tempo.parada_planejada", "tempo.parada_nao_planejada", "tempo.a_esclarecer",
        ])
        self.assertEqual(by_metric["tempo.sem_demanda"], tree.total_seconds)
        # Tempo do turno = tempo físico medido menos o fora de turno.
        hours = _service(self.repo).get_overview(self.filters)["hours"]
        self.assertEqual(
            tree.parent_total_seconds,
            hours["physical_measured_seconds"] - hours["out_of_shift_attributed_seconds"],
        )

    def test_average_uses_calendar_resource_count(self):
        tree = self.explainer.explain("tempo.sem_demanda", self.filters)
        self.assertEqual(tree.resource_count, 5)
        self.assertEqual(tree.day_count, 1)
        self.assertEqual(tree.average_seconds, 6 * H / 5)
        self.assertEqual(tree.notes, [])

    def test_fora_turno_is_calendar_number_without_average(self):
        tree = self.explainer.explain("tempo.fora_turno", self.filters)
        self.assertEqual(tree.total_seconds, 8 * H)
        self.assertIsNone(tree.average_seconds)
        self.assertEqual(tree.siblings, [])
        self.assertTrue(tree.reconciliation["ok"])

    def test_fora_turno_same_hours_in_two_resources_counted_once(self):
        estados = [
            _estado(1, "DOBRA1", "fora_turno", _at(QUARTA, 0), _at(QUARTA, 8)),
            _estado(2, "DOBRA2", "fora_turno", _at(QUARTA, 0), _at(QUARTA, 8)),
        ]
        explainer, repo = _explainer(estados, {"DOBRA1": [_turno(2)], "DOBRA2": [_turno(2)]})
        tree = explainer.explain("tempo.fora_turno", self.filters)
        hours = _service(repo).get_overview(self.filters)["hours"]

        self.assertEqual(tree.total_seconds, 8 * H)
        self.assertEqual(tree.total_seconds, hours["out_of_shift_seconds"])
        self.assertEqual(sum(s.seconds for s in tree.children), 16 * H)
        self.assertTrue(tree.reconciliation["ok"])
        self.assertEqual(tree.excluded[0]["seconds"], 8 * H)

    def test_resource_without_calendar_is_flagged_not_dropped(self):
        estados = [
            _estado(1, "DOBRA1", "fila", _at(QUARTA, 8), _at(QUARTA, 10)),
            _estado(2, "SEMTURNO", "fila", _at(QUARTA, 8), _at(QUARTA, 11)),
        ]
        explainer, _repo = _explainer(estados, {"DOBRA1": [_turno(2)]})
        tree = explainer.explain("tempo.sem_demanda", self.filters)

        self.assertEqual(tree.total_seconds, 5 * H)
        self.assertEqual(tree.resource_count, 1)
        self.assertEqual(tree.average_seconds, 5 * H)  # divisor não mudou
        self.assertEqual(len(tree.notes), 1)
        self.assertIn("1 recurso sem turno cadastrado", tree.notes[0])
        self.assertIn("3.0 h", tree.notes[0])

    def test_unknown_metric_raises(self):
        with self.assertRaises(UnknownMetricError):
            self.explainer.explain("tempo.inexistente", self.filters)

    def test_rule_applied_is_explained_on_conflict_stretch(self):
        tree = self.explainer.explain("tempo.a_esclarecer", self.filters)
        detail = tree.children[0].children[0].children[0].detail
        self.assertEqual(detail["record_id"], "estado_recurso:8, estado_recurso:9")
        self.assertIn("incompatíveis", detail["rule"])

    def test_empty_period(self):
        explainer, _repo = _explainer([], {})
        tree = explainer.explain("tempo.sem_demanda", self.filters)

        self.assertEqual(tree.total_seconds, 0)
        self.assertEqual(tree.children, [])
        self.assertTrue(tree.reconciliation["ok"])
        self.assertIn("nenhum registro no período", tree.reason.lower())
        self.assertIsNone(tree.average_seconds)
        self.assertEqual(tree.resource_count, 0)
        self.assertFalse(tree.truncated)

    def test_empty_metric_with_data_in_period_says_so(self):
        estados = [_estado(1, "DOBRA1", "producao", _at(QUARTA, 8), _at(QUARTA, 9))]
        explainer, _repo = _explainer(estados, {"DOBRA1": [_turno(2)]})
        tree = explainer.explain("tempo.sem_demanda", self.filters)

        self.assertEqual(tree.total_seconds, 0)
        self.assertEqual(tree.reason, "Nenhum registro desta métrica no período.")

    def test_outvoted_stop_does_not_lend_operator_or_reason(self):
        estados = [
            _estado(20, "DOBRA1", "producao", _at(QUARTA, 8), _at(QUARTA, 10),
                    operador="Ana", origem="app"),
            _estado(21, "DOBRA1", "parada", _at(QUARTA, 9), _at(QUARTA, 10),
                    operador="Beto", origem="app", motivo="Quebra", planejado=False),
        ]
        explainer, _repo = _explainer(estados, {"DOBRA1": [_turno(2)]})
        tree = explainer.explain("tempo.producao", self.filters)
        stretches = tree.children[0].children[0].children
        prevailed = next(t for t in stretches if t.detail["start"] == _at(QUARTA, 9).isoformat())

        self.assertEqual(prevailed.detail["who"], "Ana")
        self.assertNotIn("motivo", prevailed.detail)
        self.assertIn("vale produção", prevailed.detail["rule"])
        # A parada vencida some da parada (produção prevalece) e não vira "quem".
        stop = explainer.explain("tempo.parada_nao_planejada", self.filters)
        self.assertEqual(stop.total_seconds, 0)

    def test_segment_crossing_period_boundary_is_clipped(self):
        estados = [
            _estado(1, "DOBRA1", "fila", _at(QUARTA, 22), _at(QUINTA, 2)),
        ]
        explainer, repo = _explainer(estados, {"DOBRA1": [_turno(2)]})
        filters = AnalyticsFilter(QUARTA, QUINTA)  # [qua 00:00, qui 00:00)

        tree = explainer.explain("tempo.sem_demanda", filters)

        self.assertEqual(tree.total_seconds, 2 * H)
        stretch = tree.children[0].children[0].children[0]
        self.assertEqual(stretch.seconds, 2 * H)
        self.assertEqual(stretch.detail["end"], QUINTA.isoformat())
        self.assertEqual(
            tree.total_seconds,
            _service(repo).get_overview(filters)["hours"]["no_demand_seconds"],
        )

    def test_truncation_flag(self):
        estados = [
            _estado(i, f"DOBRA{i}", "fila", _at(QUARTA, 8), _at(QUARTA, 8 + i))
            for i in range(1, 11)
        ]
        turnos = {f"DOBRA{i}": [_turno(2)] for i in range(1, 11)}
        explainer, _repo = _explainer(estados, turnos)
        full = explainer.explain("tempo.sem_demanda", self.filters)
        tree = explainer.explain("tempo.sem_demanda", self.filters, max_nodes=3)

        self.assertFalse(full.truncated)
        self.assertTrue(tree.truncated)
        self.assertEqual(tree.total_seconds, sum(range(1, 11)) * H)
        self.assertTrue(tree.reconciliation["ok"])
        sector = tree.children[0]
        self.assertEqual(sector.seconds, tree.total_seconds)
        self.assertEqual(sum(r.seconds for r in sector.children), sector.seconds)
        self.assertEqual(sector.children[0].label, "DOBRA10")
        self.assertEqual(sector.children[-1].label, "outros 9 recursos")
        self.assertLessEqual(_count_nodes(tree.children), 3)

    def test_truncation_keeps_every_level_closing(self):
        full = self.explainer.explain("tempo.sem_demanda", self.filters, max_nodes=400)
        full_count = _count_nodes(full.children)
        for limit in (1, 2, 3, 5, 8, 12):
            with self.subTest(max_nodes=limit):
                tree = self.explainer.explain(
                    "tempo.sem_demanda", self.filters, max_nodes=limit
                )
                self.assertTrue(tree.reconciliation["ok"])
                self.assertEqual(tree.total_seconds, 6 * H)
                self.assertLessEqual(_count_nodes(tree.children), max(1, limit))
                self.assertEqual(sum(n.seconds for n in tree.children), 6 * H)
                if limit < full_count:
                    self.assertTrue(tree.truncated)

                def check(node):
                    if node.kind == "stretch" or node.label.startswith("outros"):
                        return
                    # Nenhum corte em silêncio: ou fecha com o pai, ou está marcado.
                    closes = abs(sum(c.seconds for c in node.children) - node.seconds) < 0.01
                    self.assertTrue(closes or node.truncated, (node.label, node.children))
                    for child in node.children:
                        check(child)

                for sector in tree.children:
                    check(sector)

    def test_truncation_marks_cut_nodes_when_no_room_for_outros(self):
        tree = self.explainer.explain("tempo.sem_demanda", self.filters, max_nodes=3)
        # 3 nós: um setor, um recurso, "outros" no nível de recursos; o recurso
        # mantido não tem espaço para seus trechos e fica marcado como cortado.
        resource = tree.children[0].children[0]
        self.assertEqual(resource.kind, "resource")
        self.assertTrue(resource.truncated or resource.children)

    def test_to_dict_is_json_ready(self):
        import json

        payload = self.explainer.explain("tempo.sem_demanda", self.filters).to_dict()
        json.dumps(payload)
        self.assertEqual(payload["metric"], "tempo.sem_demanda")
        self.assertEqual(payload["children"][0]["kind"], "sector")
        self.assertEqual(payload["calculated_at"], "2026-08-21T12:00:00")


class TimeCompositionFacadeTests(unittest.TestCase):
    """Cartão "Composição do tempo" da Visão Geral (frontend_facade.inicio)."""

    @staticmethod
    def _composition(estados, turnos):
        from mes.services.frontend_facade import FrontendBackendFacade

        repo = _Repo(estados, turnos)
        facade = FrontendBackendFacade(repo, now_func=lambda: datetime(2026, 8, 21, 12, 0))
        payload = facade.inicio(_day_filters(), include_insights=False)
        return payload["time_composition"], payload["hours"]

    def test_time_composition_lines(self):
        composition, hours = self._composition(_full_day_states(), _FULL_DAY_TURNOS)
        items = {item["label"]: item for item in composition["items"]}

        for label in ("Parada planejada", "Parada não planejada", "A esclarecer"):
            self.assertIn(label, items)
        self.assertNotIn("Parada", items)
        self.assertEqual(items["Parada planejada"]["seconds"], 1 * H)
        self.assertEqual(items["Parada não planejada"]["seconds"], 2 * H)
        self.assertEqual(items["A esclarecer"]["seconds"], 1 * H)
        self.assertEqual(
            items["Parada planejada"]["seconds"] + items["Parada não planejada"]["seconds"],
            hours["downtime_seconds"],
        )
        self.assertEqual(items["A esclarecer"]["seconds"], hours["conflicting_state_seconds"])

        explainer, _ = _explainer()
        for item in composition["items"]:
            metric = item["metric"]
            if metric is None:
                continue
            with self.subTest(metric=metric):
                explainer.explain(metric, _day_filters())  # não levanta UnknownMetricError
        self.assertEqual(items["Produção"]["metric"], "tempo.producao")
        self.assertEqual(items["Recurso sem demanda"]["metric"], "tempo.sem_demanda")
        self.assertEqual(items["Fora do turno"]["metric"], "tempo.fora_turno")

    def test_time_composition_average_uses_calendar_resource_count(self):
        composition, hours = self._composition(_full_day_states(), _FULL_DAY_TURNOS)
        items = {item["label"]: item for item in composition["items"]}

        self.assertEqual(composition["resource_count"], hours["resource_count"])
        self.assertEqual(composition["day_count"], hours["day_count"])
        self.assertEqual(composition["resource_count"], 5)
        self.assertIsNone(composition["average_note"])
        self.assertEqual(items["Recurso sem demanda"]["average_seconds"], 6 * H / 5)
        self.assertEqual(items["Parada planejada"]["average_seconds"], 1 * H / 5)
        self.assertEqual(items["A esclarecer"]["average_seconds"], 1 * H / 5)
        # Fora do turno é número de calendário: sem média.
        self.assertIsNone(items["Fora do turno"]["average_seconds"])

    def test_time_composition_without_calendar_has_no_average(self):
        composition, _ = self._composition(_full_day_states(), {})

        self.assertEqual(composition["resource_count"], 0)
        self.assertTrue(composition["average_note"])
        for item in composition["items"]:
            self.assertIsNone(item["average_seconds"])


if __name__ == "__main__":
    unittest.main()
