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
            {"consolidated", "calendar_resources", "days", "calculated_at"},
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


if __name__ == "__main__":
    unittest.main()
