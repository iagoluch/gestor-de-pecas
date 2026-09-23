"""`ResourceStateService` (mes/services/resource_state.py) e a categorização
analítica associada (mes/analytics/resource_state.py) não tinham nenhum
teste dedicado. Este arquivo cobre a lógica de negócio real do módulo:
o default de `planejado` em paradas manuais, a derivação de "sem_demanda",
os guards contra métodos ausentes no db, e a agregação de `resumo_periodo`
(totals, productive_seconds, unknown_seconds, by_resource/by_sector).
"""

from __future__ import annotations

import unittest

from mes.analytics.resource_state import physical_state_category
from mes.domain import EventCategory
from mes.services.resource_state import ResourceStateService


class _FakeDB:
    """Stub mínimo: grava a chamada e devolve um valor fixo."""

    def __init__(self):
        self.calls = []

    def transicionar_estado_recurso(self, recurso, categoria, **kwargs):
        self.calls.append((recurso, categoria, kwargs))
        return {"recurso": recurso, "categoria": categoria, **kwargs}


class RegistrarEstadoTests(unittest.TestCase):
    def setUp(self):
        self.db = _FakeDB()
        self.service = ResourceStateService(self.db, "OP-1")

    def test_parada_manual_sem_planejado_explicito_vira_nao_planejada(self):
        self.service.registrar_estado("CNC-01", EventCategory.DOWNTIME.value)
        _, categoria, kwargs = self.db.calls[0]
        self.assertEqual(categoria, EventCategory.DOWNTIME.value)
        self.assertFalse(kwargs["planejado"])

    def test_planejado_explicito_nao_e_sobrescrito(self):
        self.service.registrar_estado(
            "CNC-01", EventCategory.DOWNTIME.value, planejado=True
        )
        _, _, kwargs = self.db.calls[0]
        self.assertTrue(kwargs["planejado"])

    def test_categorias_fora_de_downtime_nao_ganham_default_de_planejado(self):
        self.service.registrar_estado("CNC-01", EventCategory.PRODUCTION.value)
        _, _, kwargs = self.db.calls[0]
        self.assertIsNone(kwargs["planejado"])

    def test_operador_vazio_vira_sistema(self):
        service = ResourceStateService(self.db, "   ")
        self.assertEqual(service.operador, "SISTEMA")
        service_none = ResourceStateService(self.db, None)
        self.assertEqual(service_none.operador, "SISTEMA")

    def test_categoria_invalida_levanta_erro_do_cliente(self):
        with self.assertRaises(ValueError):
            self.service.registrar_estado("CNC-01", "categoria_que_nao_existe")


class EncerrarAtualGuardTests(unittest.TestCase):
    """`encerrar`/`atual` não podem quebrar quando o db (real ou fake em
    teste) ainda não implementa o método opcional."""

    def test_encerrar_sem_metodo_no_db_devolve_none(self):
        service = ResourceStateService(object(), "OP-1")
        self.assertIsNone(service.encerrar("CNC-01"))

    def test_atual_sem_metodo_no_db_devolve_none(self):
        service = ResourceStateService(object(), "OP-1")
        self.assertIsNone(service.atual("CNC-01"))

    def test_encerrar_delega_quando_db_implementa(self):
        class DB:
            def encerrar_estado_recurso(self, recurso, *, data_hora=None):
                return {"recurso": recurso, "data_hora": data_hora}

        service = ResourceStateService(DB(), "OP-1")
        self.assertEqual(
            service.encerrar("CNC-01", data_hora="2026-09-23T10:00:00"),
            {"recurso": "CNC-01", "data_hora": "2026-09-23T10:00:00"},
        )


class ResumoPeriodoTests(unittest.TestCase):
    """Agregação consumida por relatórios/Andon: cada segundo tem que cair
    exatamente em um bucket, e produtivo/desconhecido são somas derivadas."""

    def _service_com_linhas(self, rows):
        class DB:
            def listar_estados_recurso_periodo(self, inicio, fim, **kwargs):
                return rows

        return ResourceStateService(DB(), "OP-1")

    def test_totais_por_categoria_e_produtivo(self):
        rows = [
            {"recurso": "CNC-01", "tipo_setor": "Corte", "categoria": "producao", "segundos_periodo": 100},
            {"recurso": "CNC-01", "tipo_setor": "Corte", "categoria": "parada", "segundos_periodo": 50},
            {"recurso": "CNC-02", "tipo_setor": "Solda", "categoria": "setup", "segundos_periodo": 30},
        ]
        service = self._service_com_linhas(rows)
        resumo = service.resumo_periodo("2026-09-01", "2026-09-02")
        self.assertEqual(resumo["totals"]["producao"], 100.0)
        self.assertEqual(resumo["totals"]["parada"], 50.0)
        self.assertEqual(resumo["totals"]["setup"], 30.0)
        # Produção + Setup são produtivos; Parada não é.
        self.assertEqual(resumo["productive_seconds"], 130.0)

    def test_fila_sem_op_vira_sem_demanda_e_nao_fila(self):
        rows = [
            {"recurso": "CNC-01", "tipo_setor": "Corte", "categoria": "fila", "segundos_periodo": 40, "op": None},
            {"recurso": "CNC-01", "tipo_setor": "Corte", "categoria": "fila", "segundos_periodo": 20, "op": "OP-123"},
        ]
        service = self._service_com_linhas(rows)
        resumo = service.resumo_periodo("2026-09-01", "2026-09-02")
        self.assertEqual(resumo["totals"]["sem_demanda"], 40.0)
        self.assertEqual(resumo["totals"]["fila"], 20.0)

    def test_categoria_desconhecida_soma_em_unknown_seconds(self):
        rows = [
            {"recurso": "CNC-01", "tipo_setor": "Corte", "categoria": "isso_nao_existe", "segundos_periodo": 15},
        ]
        service = self._service_com_linhas(rows)
        resumo = service.resumo_periodo("2026-09-01", "2026-09-02")
        self.assertEqual(resumo["unknown_seconds"], 15.0)
        self.assertEqual(resumo["totals"]["desconhecido"], 15.0)

    def test_agrupamento_por_recurso_e_setor_soma_todas_as_linhas(self):
        rows = [
            {"recurso": "CNC-01", "tipo_setor": "Corte", "categoria": "producao", "segundos_periodo": 100},
            {"recurso": "CNC-01", "tipo_setor": "Corte", "categoria": "parada", "segundos_periodo": 50},
        ]
        service = self._service_com_linhas(rows)
        resumo = service.resumo_periodo("2026-09-01", "2026-09-02")
        recurso = next(r for r in resumo["by_resource"] if r["recurso"] == "CNC-01")
        self.assertEqual(recurso["producao"], 100.0)
        self.assertEqual(recurso["parada"], 50.0)
        setor = next(s for s in resumo["by_sector"] if s["setor"] == "Corte")
        self.assertEqual(setor["producao"], 100.0)

    def test_sem_linhas_devolve_estrutura_zerada_sem_quebrar(self):
        service = self._service_com_linhas([])
        resumo = service.resumo_periodo("2026-09-01", "2026-09-02")
        self.assertEqual(resumo["productive_seconds"], 0.0)
        self.assertEqual(resumo["unknown_seconds"], 0.0)
        self.assertEqual(resumo["by_resource"], [])
        self.assertEqual(resumo["by_sector"], [])

    def test_db_sem_metodo_de_listagem_devolve_lista_vazia(self):
        service = ResourceStateService(object(), "OP-1")
        resumo = service.resumo_periodo("2026-09-01", "2026-09-02")
        self.assertEqual(resumo["items"], [])
        self.assertEqual(resumo["productive_seconds"], 0.0)


class PhysicalStateCategoryTests(unittest.TestCase):
    """A derivação de `sem_demanda` é fonte única (Andon, análises e
    exportações dependem dela) — cobre os dois lados da decisão."""

    def test_fila_sem_op_e_sem_demanda(self):
        row = {"categoria": "fila", "op": None}
        self.assertEqual(physical_state_category(row), EventCategory.NO_DEMAND)

    def test_fila_com_op_continua_fila(self):
        row = {"categoria": "fila", "op": "OP-1"}
        self.assertEqual(physical_state_category(row), EventCategory.QUEUE)

    def test_categoria_ausente_ou_invalida_vira_desconhecido(self):
        self.assertEqual(physical_state_category({}), EventCategory.UNKNOWN)
        self.assertEqual(
            physical_state_category({"categoria": "algo_invalido"}), EventCategory.UNKNOWN
        )

    def test_producao_nao_e_afetada_pela_derivacao(self):
        row = {"categoria": "producao", "op": None}
        self.assertEqual(physical_state_category(row), EventCategory.PRODUCTION)


if __name__ == "__main__":
    unittest.main()
