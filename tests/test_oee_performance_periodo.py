"""Performance por período: S_boas e "sem padrão" seguem as peças boas do período.

Bug de 16/10/2026: o tempo padrão das peças boas e as peças sem padrão usavam
``quantidade_boa`` do apontamento inteiro em cada dia que ele tocava, enquanto
as peças boas vinham dos eventos de quantidade do período. Um apontamento
22h-02h finalizado com 100 peças somava 100 x padrão nos dois dias: o dia
anterior mostrava Performance acima de 100% sem nenhuma peça boa, e uma OP sem
padrão cruzando o dia bloqueava a Performance de um dia que só tinha peças com
padrão.
"""

import unittest
from datetime import datetime
from unittest import mock

from mes.contracts import AnalyticsFilter
from mes.services import management as management_module
from mes.services.management import ManagementService, _JanelaPrefetch
from tests.test_backend_canonical_v11 import _CanonicalRepo
from tests.test_oee_prefetch_janela_dia import _estados_como_sql

AGORA = datetime(2026, 10, 15, 14, 0)
DIA_13 = (datetime(2026, 10, 13, 0, 0), datetime(2026, 10, 13, 23, 59, 59))
DIA_14 = (datetime(2026, 10, 14, 0, 0), datetime(2026, 10, 14, 23, 59, 59))
JANELA = AnalyticsFilter(inicio=DIA_13[0], fim=DIA_14[1])
PADRAO_SEGUNDOS = 120


def _fato(id_, op, inicio, fim, boas, *, padrao=None, eventos_id=0):
    fato = {
        "id": id_, "op": op, "tipo_setor": "Dobra", "maquina": "DOBRA1",
        "status": "Finalizado", "operador_inicio": "A", "produto_codigo": op,
        "numero_operacao": "20", "quantidade": boas, "quantidade_boa": boas,
        "quantidade_refugo": 0, "quantidade_retrabalho": 0,
        "data_inicio": inicio, "data_fim": fim,
        # Formato da consulta real: cada evento traz a quantidade lançada nele.
        "eventos": [
            {"id": eventos_id + 1, "estado": "producao", "quantidade_boa": 0,
             "quantidade_refugo": 0, "data_hora": inicio},
            {"id": eventos_id + 2, "estado": "finalizado", "quantidade_boa": boas,
             "quantidade_refugo": 0, "data_hora": fim},
        ],
    }
    if padrao is not None:
        fato["tempo_medio_segundos"] = padrao
    return fato


def _estado(id_, inicio, fim):
    return {
        "id": id_, "recurso": "DOBRA1", "tipo_setor": "Dobra", "categoria": "producao",
        "origem": "apontamento_operador", "data_inicio": inicio, "data_fim": fim,
    }


def _boa(op, quantidade, momento):
    return {"tipo": "boa", "quantidade": quantidade, "op": op, "recurso": "DOBRA1",
            "tipo_setor": "Dobra", "produto_codigo": op, "data_hora": momento}


class _Repo(_CanonicalRepo):
    """Predicados das consultas reais de ``app/database/database.py``."""

    def __init__(self, fatos, estados, quantidades):
        self.fatos, self.estados, self.quantidades = fatos, estados, quantidades

    def listar_fatos_operacionais_periodo(self, inicio, fim, **_kwargs):
        return [
            dict(row) for row in self.fatos
            if row["data_inicio"] <= fim and (row["data_fim"] or AGORA) >= inicio
        ]

    def listar_estados_recurso_periodo(self, inicio, fim, categoria=None, **_kwargs):
        return _estados_como_sql(self.estados, inicio, fim, categoria)

    def listar_eventos_quantidade_periodo(self, inicio, fim, **_kwargs):
        return [dict(row) for row in self.quantidades if inicio <= row["data_hora"] <= fim]


class _PrefetchAgoraFixo(_JanelaPrefetch):
    def __init__(self, **kwargs):
        kwargs["agora"] = AGORA
        super().__init__(**kwargs)


class PerformancePorPeriodoTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(management_module, "_JanelaPrefetch", _PrefetchAgoraFixo)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _dias(self, repo):
        """Resumos por dia pelos dois caminhos: consulta direta e evolução (prefetch)."""

        servico = ManagementService(repo, now_func=lambda: AGORA)
        bounds = servico._bucket_bounds(JANELA)
        self.assertEqual(len(bounds), 2)
        diretos = [
            ManagementService(repo, now_func=lambda: AGORA).get_overview(
                AnalyticsFilter(inicio=inicio, fim=fim)
            )
            for inicio, fim in bounds
        ]
        with servico._janela_prefetch(JANELA, periodos=bounds):
            em_lote = [
                servico.get_overview(AnalyticsFilter(inicio=inicio, fim=fim))
                for inicio, fim in bounds
            ]
        return diretos, em_lote

    def test_apontamento_que_cruza_a_meia_noite_nao_infla_o_dia_anterior(self):
        repo = _Repo(
            fatos=[_fato(1, "OP1", datetime(2026, 10, 13, 22, 0),
                         datetime(2026, 10, 14, 2, 0), 100, padrao=PADRAO_SEGUNDOS)],
            estados=[_estado(1, datetime(2026, 10, 13, 22, 0), datetime(2026, 10, 14, 2, 0))],
            quantidades=[_boa("OP1", 100, datetime(2026, 10, 14, 2, 0))],
        )
        total = ManagementService(repo, now_func=lambda: AGORA).get_overview(JANELA)
        total_padrao = total["kpi_time_bases"]["standard_run_seconds"]
        self.assertEqual(total_padrao, 100 * PADRAO_SEGUNDOS)

        for caminho, (anterior, seguinte) in zip(("direto", "prefetch"), self._dias(repo)):
            with self.subTest(caminho=caminho):
                self.assertEqual(anterior["production"]["good"], 0)
                self.assertEqual(anterior["kpi_time_bases"]["standard_run_seconds"], 0)
                performance = anterior["kpis"]["performance"]["value"]
                self.assertTrue(performance is None or performance <= 100, performance)

                self.assertEqual(seguinte["production"]["good"], 100)
                self.assertEqual(
                    anterior["kpi_time_bases"]["standard_run_seconds"]
                    + seguinte["kpi_time_bases"]["standard_run_seconds"],
                    total_padrao,
                )

    def test_op_sem_padrao_que_cruza_o_dia_nao_bloqueia_a_performance_do_dia(self):
        repo = _Repo(
            fatos=[
                _fato(1, "OPCOM", datetime(2026, 10, 13, 20, 0),
                      datetime(2026, 10, 13, 21, 0), 30, padrao=60, eventos_id=0),
                _fato(2, "OPSEM", datetime(2026, 10, 13, 22, 0),
                      datetime(2026, 10, 14, 2, 0), 100, eventos_id=10),
            ],
            estados=[
                _estado(1, datetime(2026, 10, 13, 20, 0), datetime(2026, 10, 13, 21, 0)),
                _estado(2, datetime(2026, 10, 13, 22, 0), datetime(2026, 10, 14, 2, 0)),
            ],
            quantidades=[
                _boa("OPCOM", 30, datetime(2026, 10, 13, 21, 0)),
                _boa("OPSEM", 100, datetime(2026, 10, 14, 2, 0)),
            ],
        )
        for caminho, (anterior, seguinte) in zip(("direto", "prefetch"), self._dias(repo)):
            with self.subTest(caminho=caminho):
                self.assertEqual(anterior["production"]["good"], 30)
                self.assertEqual(anterior["kpi_time_bases"]["standard_run_seconds"], 30 * 60)
                self.assertIsNotNone(anterior["kpis"]["performance"]["value"])
                setor = {item["setor"]: item for item in anterior["sector_kpis"]}["Dobra"]
                self.assertEqual(setor["pecas_boas_sem_tempo_padrao"], 0)

                # As 100 peças sem padrão ficam no dia em que foram lançadas.
                setor = {item["setor"]: item for item in seguinte["sector_kpis"]}["Dobra"]
                self.assertEqual(setor["pecas_boas_sem_tempo_padrao"], 100)
                self.assertIsNone(seguinte["kpis"]["performance"]["value"])


if __name__ == "__main__":
    unittest.main()
