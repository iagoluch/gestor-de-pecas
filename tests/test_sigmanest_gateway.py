"""`mes/integrations/sigmanest/gateway.py` não tinha nenhum teste dedicado.

O módulo é a fronteira entre o planejamento do SigmaNEST (tarefas/nestings/
peças) e o catálogo canônico de OPs do TOTVS já conhecido pelo Gestor. A regra
central é `SigmaNestPlanningService.correlacionar`: liga peça→OP **somente**
quando a OP já existe no Gestor, e nunca promove uma OP vista no SigmaNEST a
OP nova — o TOTVS continua sendo a fonte da identidade. Isso envolve
normalização de código (`limpa_codigo`, case/whitespace), peças sem OP,
dedupe de OPs desconhecidas e agregação em `CorrelacaoOrdem` (tarefas,
programas, máquinas). Nada disso estava coberto.
"""

from __future__ import annotations

import unittest

from mes.integrations.sigmanest.gateway import (
    CorrelacaoOrdem,
    SigmaNestPlanningService,
)
from mes.integrations.sigmanest.models import (
    SigmaNestCutPlan,
    SigmaNestPartLine,
    SigmaNestPlanningSnapshot,
    SigmaNestTask,
)


def _part(wo_number: str, part_name: str = "PECA-1") -> SigmaNestPartLine:
    return SigmaNestPartLine(
        program_name="PROG-1",
        sheet_name="CHAPA-1",
        part_name=part_name,
        wo_number=wo_number,
    )


def _plan(
    task_name: str,
    parts: tuple[SigmaNestPartLine, ...],
    *,
    program_name: str = "PROG-1",
    machine_name: str = "",
) -> SigmaNestCutPlan:
    return SigmaNestCutPlan(
        task_name=task_name,
        program_name=program_name,
        sheet_name="CHAPA-1",
        machine_name=machine_name,
        parts=parts,
    )


def _snapshot(*plans: SigmaNestCutPlan) -> SigmaNestPlanningSnapshot:
    tasks = tuple(
        SigmaNestTask(task_name=plan.task_name, plans=(plan,)) for plan in plans
    )
    return SigmaNestPlanningSnapshot(tasks=tasks)


class CorrelacionarTests(unittest.TestCase):
    def test_liga_peca_a_op_ja_conhecida(self):
        part = _part("OP-100")
        plan = _plan("TAREFA-1", (part,))
        snapshot = _snapshot(plan)

        encontradas, desconhecidas = SigmaNestPlanningService.correlacionar(
            snapshot, ["OP-100"]
        )

        self.assertIn("OP-100", encontradas)
        self.assertEqual(encontradas["OP-100"].ocorrencias, ((plan, part),))
        self.assertEqual(desconhecidas, ())

    def test_op_do_sigmanest_ausente_no_catalogo_vira_desconhecida_sem_criar_correlacao(
        self,
    ):
        part = _part("OP-999")
        plan = _plan("TAREFA-1", (part,))
        snapshot = _snapshot(plan)

        encontradas, desconhecidas = SigmaNestPlanningService.correlacionar(
            snapshot, ["OP-100"]
        )

        self.assertEqual(encontradas, {})
        self.assertEqual(desconhecidas, ("OP-999",))

    def test_normalizacao_de_codigo_ignora_caixa_e_espacos(self):
        part = _part("  op-100  ")
        plan = _plan("TAREFA-1", (part,))
        snapshot = _snapshot(plan)

        encontradas, desconhecidas = SigmaNestPlanningService.correlacionar(
            snapshot, [" Op-100 "]
        )

        self.assertIn("OP-100", encontradas)
        self.assertEqual(desconhecidas, ())

    def test_peca_sem_op_e_ignorada(self):
        part = _part("")
        plan = _plan("TAREFA-1", (part,))
        snapshot = _snapshot(plan)

        encontradas, desconhecidas = SigmaNestPlanningService.correlacionar(
            snapshot, ["OP-100"]
        )

        self.assertEqual(encontradas, {})
        self.assertEqual(desconhecidas, ())

    def test_op_desconhecida_repetida_aparece_uma_unica_vez_e_preserva_ordem(self):
        plan1 = _plan("TAREFA-1", (_part("OP-A"), _part("OP-B")))
        plan2 = _plan("TAREFA-2", (_part("OP-B"), _part("OP-A")))
        snapshot = _snapshot(plan1, plan2)

        _, desconhecidas = SigmaNestPlanningService.correlacionar(snapshot, [])

        self.assertEqual(desconhecidas, ("OP-A", "OP-B"))

    def test_mesma_op_em_varios_nestings_gera_multiplas_ocorrencias(self):
        part1 = _part("OP-100")
        part2 = _part("OP-100")
        plan1 = _plan("TAREFA-1", (part1,))
        plan2 = _plan("TAREFA-2", (part2,))
        snapshot = _snapshot(plan1, plan2)

        encontradas, _ = SigmaNestPlanningService.correlacionar(snapshot, ["OP-100"])

        self.assertEqual(
            encontradas["OP-100"].ocorrencias, ((plan1, part1), (plan2, part2))
        )

    def test_snapshot_vazio_nao_gera_correlacoes_nem_desconhecidas(self):
        snapshot = SigmaNestPlanningSnapshot()

        encontradas, desconhecidas = SigmaNestPlanningService.correlacionar(
            snapshot, ["OP-100"]
        )

        self.assertEqual(encontradas, {})
        self.assertEqual(desconhecidas, ())

    def test_ordens_conhecidas_com_codigo_vazio_sao_descartadas(self):
        part = _part("OP-100")
        plan = _plan("TAREFA-1", (part,))
        snapshot = _snapshot(plan)

        # "" e None não podem virar uma correlação "coringa" que aceita
        # qualquer peça sem OP.
        encontradas, desconhecidas = SigmaNestPlanningService.correlacionar(
            snapshot, ["", None, "OP-100"]
        )

        self.assertIn("OP-100", encontradas)
        self.assertEqual(desconhecidas, ())


class CorrelacaoOrdemTests(unittest.TestCase):
    def test_correlacionada_reflete_se_ha_ocorrencias(self):
        vazia = CorrelacaoOrdem("OP-1")
        self.assertFalse(vazia.correlacionada)

        plan = _plan("TAREFA-1", (_part("OP-1"),))
        cheia = CorrelacaoOrdem("OP-1", ((plan, plan.parts[0]),))
        self.assertTrue(cheia.correlacionada)

    def test_tarefas_programas_e_maquinas_deduplicam_preservando_ordem(self):
        part_a = _part("OP-1")
        part_b = _part("OP-1")
        plan1 = _plan(
            "TAREFA-1", (part_a,), program_name="PROG-A", machine_name="LASER-1"
        )
        plan2 = _plan(
            "TAREFA-1", (part_b,), program_name="PROG-B", machine_name="LASER-1"
        )
        correlacao = CorrelacaoOrdem(
            "OP-1", ((plan1, part_a), (plan2, part_b))
        )

        self.assertEqual(correlacao.tarefas, ("TAREFA-1",))
        self.assertEqual(correlacao.programas, ("PROG-A", "PROG-B"))
        self.assertEqual(correlacao.maquinas, ("LASER-1",))

    def test_maquina_em_branco_e_excluida_da_lista_de_maquinas(self):
        part = _part("OP-1")
        plan = _plan("TAREFA-1", (part,), machine_name="   ")
        correlacao = CorrelacaoOrdem("OP-1", ((plan, part),))

        self.assertEqual(correlacao.maquinas, ())


class _FakeGateway:
    """Fake do Protocol `SigmaNestPlanningGateway`: sem banco, só registra."""

    def __init__(self, snapshot: SigmaNestPlanningSnapshot):
        self._snapshot = snapshot
        self.chamadas = []

    def ler_planejamento(self, *, desde=None, tarefas=None):
        self.chamadas.append({"desde": desde, "tarefas": tarefas})
        return self._snapshot


class SigmaNestPlanningServiceSnapshotTests(unittest.TestCase):
    def test_snapshot_repassa_argumentos_ao_gateway_e_devolve_o_resultado(self):
        esperado = _snapshot(_plan("TAREFA-1", (_part("OP-1"),)))
        gateway = _FakeGateway(esperado)
        service = SigmaNestPlanningService(gateway)

        resultado = service.snapshot(desde="2026-09-01", tarefas=["TAREFA-1"])

        self.assertIs(resultado, esperado)
        self.assertEqual(
            gateway.chamadas, [{"desde": "2026-09-01", "tarefas": ["TAREFA-1"]}]
        )

    def test_snapshot_sem_argumentos_usa_padroes_none(self):
        gateway = _FakeGateway(SigmaNestPlanningSnapshot())
        service = SigmaNestPlanningService(gateway)

        service.snapshot()

        self.assertEqual(gateway.chamadas, [{"desde": None, "tarefas": None}])


if __name__ == "__main__":
    unittest.main()
