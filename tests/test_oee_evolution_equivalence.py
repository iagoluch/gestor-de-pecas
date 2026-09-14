"""Equivalência da evolução do OEE antes e depois da leitura em lote (D3).

A otimização removeu o N+1 de ``get_oee_evolution``: os insumos passaram a ser
lidos uma vez para a janela inteira e fatiados em memória. O cálculo continua
sendo o de ``mes/analytics/oee.py``, chamado através do mesmo ``get_overview``.

Este teste prova que a troca não move nenhum número: para vários períodos e
tamanhos de bucket, a série produzida com e sem a leitura em lote é idêntica.
"""

import contextlib
import os
import unittest
from datetime import datetime

from app.database.config import load_postgres_config
from app.database.database import Database
from mes.contracts import AnalyticsFilter
from mes.services.management import ManagementService


# Janela coberta pelas simulações históricas dos bancos de teste.
AGORA = datetime(2026, 8, 24, 8, 32)

PERIODOS = {
    "um_dia": (datetime(2026, 8, 20, 0, 0), datetime(2026, 8, 21, 0, 0)),
    "uma_semana": (datetime(2026, 8, 10, 0, 0), datetime(2026, 8, 17, 0, 0)),
    "um_mes": (datetime(2026, 7, 1, 0, 0), datetime(2026, 8, 1, 0, 0)),
    "tres_meses": (datetime(2026, 6, 1, 6, 0), AGORA),
    "periodo_quebrado": (datetime(2026, 7, 15, 13, 27), datetime(2026, 8, 9, 4, 3)),
}


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class OeeEvolutionEquivalenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = Database(load_postgres_config(testing=True).dsn)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def servico(self):
        return ManagementService(self.db, now_func=lambda: AGORA)

    def evolucao_sem_lote(self, filters):
        """Caminho anterior: uma consulta por bucket."""

        servico = self.servico()
        servico._janela_prefetch = lambda *_args, **_kwargs: contextlib.nullcontext()
        return servico.get_oee_evolution(filters)

    def evolucao_com_lote(self, filters):
        return self.servico().get_oee_evolution(filters)

    def test_series_identicas_em_varios_periodos(self):
        for nome, (inicio, fim) in PERIODOS.items():
            with self.subTest(periodo=nome):
                filters = AnalyticsFilter(inicio=inicio, fim=fim)
                antiga = self.evolucao_sem_lote(filters)
                nova = self.evolucao_com_lote(filters)

                self.assertEqual(antiga["availability"], nova["availability"])
                self.assertEqual(antiga.get("reason"), nova.get("reason"))
                self.assertEqual(len(antiga["points"]), len(nova["points"]))

                for anterior, atual in zip(antiga["points"], nova["points"]):
                    self.assertEqual(anterior["period_start"], atual["period_start"])
                    self.assertEqual(anterior["period_end"], atual["period_end"])
                    self.assertEqual(anterior["unit"], atual["unit"])
                    self.assertAlmostEqual(anterior["value"], atual["value"], places=9)
                    for componente in ("oee", "availability", "performance", "ftt"):
                        esperado = anterior["components"][componente]
                        obtido = atual["components"][componente]
                        self.assertEqual(esperado.get("availability"), obtido.get("availability"))
                        if esperado.get("value") is None:
                            self.assertIsNone(obtido.get("value"))
                        else:
                            self.assertAlmostEqual(esperado["value"], obtido["value"], places=9)

    def test_serie_em_lote_coincide_com_o_resumo_canonico_do_bucket(self):
        """Cada ponto continua sendo o OEE canônico do seu próprio período."""

        inicio, fim = PERIODOS["um_mes"]
        filters = AnalyticsFilter(inicio=inicio, fim=fim)
        serie = self.evolucao_com_lote(filters)
        if not serie["points"]:
            self.skipTest(
                "O banco TESTE ativo não possui fatos na janela histórica de julho/2026."
            )

        for ponto in serie["points"][:3]:
            bucket = AnalyticsFilter(
                inicio=datetime.fromisoformat(ponto["period_start"]),
                fim=datetime.fromisoformat(ponto["period_end"]),
            )
            # Serviço novo, sem prefetch: consulta direta ao banco para o bucket.
            resumo = self.servico().get_overview(bucket)["kpis"]["oee"]
            self.assertAlmostEqual(ponto["value"], resumo["value"], places=9)

    def test_leitura_em_lote_nao_consulta_o_banco_por_bucket(self):
        """A janela é lida uma vez; os buckets não voltam ao PostgreSQL."""

        inicio, fim = PERIODOS["tres_meses"]
        filters = AnalyticsFilter(inicio=inicio, fim=fim)
        servico = self.servico()
        chamadas = {"facts": 0, "quantidade": 0, "estados": 0}

        original = {
            "facts": self.db.listar_fatos_operacionais_periodo,
            "quantidade": self.db.listar_eventos_quantidade_periodo,
            "estados": self.db.listar_estados_recurso_periodo,
        }

        def contar(nome, fn):
            def wrapper(*args, **kwargs):
                chamadas[nome] += 1
                return fn(*args, **kwargs)
            return wrapper

        self.db.listar_fatos_operacionais_periodo = contar("facts", original["facts"])
        self.db.listar_eventos_quantidade_periodo = contar("quantidade", original["quantidade"])
        self.db.listar_estados_recurso_periodo = contar("estados", original["estados"])
        try:
            servico.get_oee_evolution(filters)
        finally:
            for nome, fn in original.items():
                setattr(
                    self.db,
                    {
                        "facts": "listar_fatos_operacionais_periodo",
                        "quantidade": "listar_eventos_quantidade_periodo",
                        "estados": "listar_estados_recurso_periodo",
                    }[nome],
                    fn,
                )

        for nome, total in chamadas.items():
            with self.subTest(consulta=nome):
                self.assertEqual(total, 1, f"{nome} deveria ser lido uma única vez, foi {total}")


if __name__ == "__main__":
    unittest.main()
