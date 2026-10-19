"""Consulta operacional: duração da parada inteira, não só do último trecho.

Relato de campo (19/10/2026): recurso sem demanda desde a volta do turno
(08:00), almoço 12:10–12:52 e de novo sem demanda. O card mostrava "Início
12:52" porque só olhava o estado aberto; o certo é 08:00, com o trecho atual
publicado à parte.
"""

from datetime import datetime
import unittest

from mes.contracts import AnalyticsFilter
from mes.domain import SHIFT_START_NO_DEMAND_TYPE
from mes.services.frontend_facade import FrontendBackendFacade
from tests.test_backend_canonical_v11 import _CanonicalRepo


AGORA = datetime(2026, 10, 19, 13, 40)


def _estado(id_, categoria, inicio, fim, **extra):
    return {
        "id": id_, "recurso": "LASER1", "tipo_setor": "Corte",
        "categoria": categoria, "data_inicio": inicio, "data_fim": fim,
        "automatico": True, **extra,
    }


class _StreakRepo(_CanonicalRepo):
    def __init__(self, historico):
        super().__init__()
        self.historico = historico

    def listar_estados_recurso_atuais(self, **_kwargs):
        return [row for row in self.historico if row["data_fim"] is None]

    def listar_estados_recurso_periodo(self, *_args, **_kwargs):
        return list(self.historico)

    def listar_fatos_operacionais_periodo(self, *_args, **_kwargs):
        return []


def _card(historico):
    facade = FrontendBackendFacade(_StreakRepo(historico), now_func=lambda: AGORA)
    filtros = AnalyticsFilter(datetime(2026, 10, 19), datetime(2026, 10, 19, 23, 59))
    itens = facade.consulta_operacional(filtros)
    itens = itens["resources"]
    return next(item for item in itens if item["recurso"] == "LASER1")


class StopStreakTests(unittest.TestCase):
    def test_sem_demanda_atravessando_o_almoco_conta_desde_a_volta_do_turno(self):
        card = _card([
            _estado(1, "fora_turno", datetime(2026, 10, 18, 17, 30), datetime(2026, 10, 19, 8, 0)),
            _estado(2, "fila", datetime(2026, 10, 19, 8, 0), datetime(2026, 10, 19, 12, 10),
                    tipo_interrupcao=SHIFT_START_NO_DEMAND_TYPE),
            _estado(3, "parada", datetime(2026, 10, 19, 12, 10), datetime(2026, 10, 19, 12, 52),
                    planejado=True, tipo_interrupcao="intervalo_programado"),
            _estado(4, "fila", datetime(2026, 10, 19, 12, 52), None,
                    tipo_interrupcao="recurso_sem_demanda"),
        ])

        self.assertEqual(card["inicio"], datetime(2026, 10, 19, 8, 0))
        self.assertAlmostEqual(card["duracao_segundos"], (5 * 60 + 40) * 60)
        self.assertEqual(card["inicio_estado_atual"], datetime(2026, 10, 19, 12, 52))
        self.assertAlmostEqual(card["duracao_estado_atual_segundos"], 48 * 60)

    def test_producao_antes_encerra_a_parada(self):
        card = _card([
            _estado(1, "producao", datetime(2026, 10, 19, 8, 0), datetime(2026, 10, 19, 12, 10)),
            _estado(2, "parada", datetime(2026, 10, 19, 12, 10), None, planejado=True),
        ])

        self.assertEqual(card["inicio"], datetime(2026, 10, 19, 12, 10))
        self.assertEqual(card["inicio_estado_atual"], datetime(2026, 10, 19, 12, 10))

    def test_buraco_entre_estados_nao_emenda(self):
        card = _card([
            _estado(1, "parada", datetime(2026, 10, 19, 8, 0), datetime(2026, 10, 19, 10, 0)),
            _estado(2, "parada", datetime(2026, 10, 19, 11, 0), None),
        ])

        self.assertEqual(card["inicio"], datetime(2026, 10, 19, 11, 0))

    def test_recurso_produzindo_mantem_o_inicio_do_estado(self):
        card = _card([
            _estado(1, "parada", datetime(2026, 10, 19, 8, 0), datetime(2026, 10, 19, 9, 0)),
            _estado(2, "producao", datetime(2026, 10, 19, 9, 0), None),
        ])

        self.assertEqual(card["inicio"], datetime(2026, 10, 19, 9, 0))


if __name__ == "__main__":
    unittest.main()
