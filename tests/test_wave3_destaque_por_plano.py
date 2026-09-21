"""Wave 3 — o Destaque trabalha por plano, não por fila de máquina.

Regra do ``Fluxo de apontamento.docx``: *"quando um plano é concluído, ele pode
ser destacado logo em seguida pelo operador de destaque, vai apontar dentro da
tela de apontamento o plano ou a tarefa completa contendo os planos cortados e
não cortados"*.

O que estes testes fixam:

* um plano cortado aparece imediatamente, sem esperar a tarefa inteira;
* um plano ainda em Corte **não** aparece como disponível;
* o plano nunca aparece solto: a tarefa pai encabeça sempre;
* PARCIAL vira COMPLETA quando todas as chapas foram cortadas;
* o plano já destacado continua visível dentro da tarefa, com seu estado;
* a quantidade de chapas vem do SigmaNEST — nada de ``1 nesting = 1 chapa``;
* quando a última chapa é destacada, a tarefa fecha pela regra canônica.
"""

from __future__ import annotations

from datetime import date, datetime
import unittest

from mes.services.cut import CutService
from mes.services.production import ProductionService
from tests.fakes import FakeDatabase


class DestaquePorPlanoTests(unittest.TestCase):
    CHAPAS = ("A", "B", "C", "D")

    def setUp(self):
        self.db = FakeDatabase()
        self.tarefa_id = self.db.inserir_tarefa("T001", material="A36", espessura=6.35)
        self.db.inserir_op_na_tarefa(self.tarefa_id, "OP-D1", "PECA-1", "Dobra", 5)
        self.db.cut_plans.extend([
            {
                "plano_hash": f"hash-{letra}",
                "codigo_tarefa": "T001",
                "programa": "8501",
                "nome_chapa": "CHAPA 3000 x 1500",
                # Cada linha é uma chapa física: mesmo programa, repetição
                # diferente. É assim que o SigmaNEST expressa a quantidade.
                "sequencia_nesting": indice,
                "sigmanest_repeat_id": indice,
                "material": "A36",
                "espessura": 6.35,
                "maquina_sigmanest": "AMADA_ENSIS",
                "quantidade_processo": 3,
                "tempo_previsto_segundos": 300,
                "data_programa": date(2026, 9, 1),
                "ativo": True,
            }
            for indice, letra in enumerate(self.CHAPAS, start=1)
        ])
        self.corte = CutService(self.db, "Cortador", cutoff_date="2026-01-01")
        self.destaque = ProductionService(self.db, "Destacador")

    # ------------------------------------------------------------------
    def _cortar(self, letra):
        """Inicia e finaliza uma chapa específica no Corte."""

        plano = f"hash-{letra}"
        iniciado = self.db.iniciar_apontamento_corte(
            plano, "Laser Ensis 3015", "Cortador", "2026-01-01",
            data_inicio=datetime(2026, 9, 3, 8, 0),
        )
        self.assertIsNotNone(iniciado, f"chapa {letra} não iniciou")
        finalizado = self.db.finalizar_apontamento_corte(
            iniciado["id"], "Cortador", data_fim=datetime(2026, 9, 3, 9, 0)
        )
        self.assertIsNotNone(finalizado, f"chapa {letra} não finalizou")

    def _fila(self):
        return self.db.listar_fila_destaque()

    def _tarefa(self):
        fila = self._fila()
        return fila[0] if fila else None

    # ------------------------------------------------------------------
    def test_sem_chapa_cortada_a_tarefa_nao_aparece_no_destaque(self):
        self.assertEqual(self._fila(), [])

    def test_plano_cortado_aparece_sozinho_sem_esperar_a_tarefa(self):
        self._cortar("A")
        tarefa = self._tarefa()
        self.assertIsNotNone(tarefa)
        self.assertEqual(tarefa["codigo_tarefa"], "T001")
        self.assertEqual(tarefa["situacao"], "PARCIAL")
        self.assertEqual(tarefa["chapas_total"], 4)
        self.assertEqual(tarefa["chapas_cortadas"], 1)
        self.assertEqual(tarefa["chapas_disponiveis"], 1)
        self.assertEqual(tarefa["progresso_corte"], "1 de 4 planos cortados")

        disponiveis = [
            plano for plano in tarefa["planos"]
            if plano["status_corte"] == "Finalizado"
        ]
        self.assertEqual([plano["plano_hash"] for plano in disponiveis], ["hash-A"])

    def test_plano_ainda_em_corte_nao_aparece_como_disponivel(self):
        self._cortar("A")
        tarefa = self._tarefa()
        pendentes = [
            plano for plano in tarefa["planos"]
            if plano["status_corte"] != "Finalizado"
        ]
        self.assertEqual(len(pendentes), 3)
        self.assertTrue(all(plano["estado_destaque"] == "aguardando" for plano in pendentes))

    def test_segundo_plano_concluido_agrupa_na_mesma_tarefa(self):
        self._cortar("A")
        self._cortar("B")
        fila = self._fila()
        # Uma tarefa, dois planos disponíveis: nada de plano solto nem de
        # tarefa duplicada.
        self.assertEqual(len(fila), 1)
        self.assertEqual(fila[0]["chapas_cortadas"], 2)
        self.assertEqual(fila[0]["chapas_disponiveis"], 2)
        self.assertEqual(fila[0]["situacao"], "PARCIAL")

    def test_plano_destacado_continua_visivel_dentro_da_tarefa(self):
        self._cortar("A")
        self._cortar("B")
        self.assertTrue(
            self.destaque.registrar_destacando(self.tarefa_id, "T001", plano_hash="hash-A").ok
        )
        concluido = self.destaque.registrar_finalizado(
            self.tarefa_id, "T001", operador_identificacao="Iago", plano_hash="hash-A"
        )
        self.assertTrue(concluido.ok, concluido.message)
        self.assertEqual(concluido.code, "plano_destacado")

        tarefa = self._tarefa()
        estados = {plano["plano_hash"]: plano["estado_destaque"] for plano in tarefa["planos"]}
        self.assertEqual(estados["hash-A"], "fim")
        self.assertEqual(estados["hash-B"], "aguardando")
        self.assertEqual(tarefa["chapas_destacadas"], 1)
        self.assertEqual(tarefa["chapas_disponiveis"], 1)

    def test_parada_e_retomada_preservam_o_escopo_do_plano(self):
        self._cortar("A")
        self.assertTrue(
            self.destaque.registrar_destacando(
                self.tarefa_id, "T001", plano_hash="hash-A"
            ).ok
        )

        parada = self.destaque.registrar_parada_destaque(
            self.tarefa_id,
            "T001",
            motivo_codigo="0029",
            plano_hash="hash-A",
        )
        self.assertTrue(parada.ok, parada.message)
        self.assertEqual(
            self.destaque.estado_destaque(
                self.tarefa_id, plano_hash="hash-A"
            )["estado"],
            "parada",
        )
        # A parada do plano não cria um estado paralelo no escopo da tarefa.
        self.assertNotEqual(
            self.destaque.estado_destaque(self.tarefa_id)["estado"], "parada"
        )

        retomada = self.destaque.registrar_destacando(
            self.tarefa_id, "T001", plano_hash="hash-A"
        )
        self.assertTrue(retomada.ok, retomada.message)
        self.assertEqual(
            self.destaque.estado_destaque(
                self.tarefa_id, plano_hash="hash-A"
            )["estado"],
            "retomada",
        )

    def test_tarefa_vira_completa_quando_todas_as_chapas_sao_cortadas(self):
        for letra in self.CHAPAS:
            self._cortar(letra)
        tarefa = self._tarefa()
        self.assertEqual(tarefa["situacao"], "COMPLETA")
        self.assertEqual(tarefa["progresso_corte"], "4 de 4 planos cortados")
        self.assertEqual(tarefa["chapas_cortadas"], tarefa["chapas_total"])

    def test_ultimo_plano_destacado_fecha_a_tarefa_pela_regra_canonica(self):
        for letra in self.CHAPAS:
            self._cortar(letra)
        for letra in self.CHAPAS[:-1]:
            self.destaque.registrar_destacando(self.tarefa_id, "T001", plano_hash=f"hash-{letra}")
            resultado = self.destaque.registrar_finalizado(
                self.tarefa_id, "T001", operador_identificacao="Iago",
                plano_hash=f"hash-{letra}",
            )
            self.assertEqual(resultado.code, "plano_destacado", resultado.message)

        ultima = self.CHAPAS[-1]
        self.destaque.registrar_destacando(self.tarefa_id, "T001", plano_hash=f"hash-{ultima}")
        fechamento = self.destaque.registrar_finalizado(
            self.tarefa_id, "T001", operador_identificacao="Iago",
            plano_hash=f"hash-{ultima}",
        )
        self.assertTrue(fechamento.ok, fechamento.message)
        self.assertEqual(fechamento.code, "tarefa_finalizada")
        tarefa = self.db.buscar_tarefa_por_codigo("T001")
        self.assertEqual(tarefa["status"], "Finalizado")

    def test_quantidade_de_chapas_vem_do_planejamento_e_nao_do_programa(self):
        """Quatro chapas do MESMO programa: contar programas daria 1."""

        for letra in self.CHAPAS:
            self._cortar(letra)
        tarefa = self._tarefa()
        programas = {plano["programa"] for plano in tarefa["planos"]}
        self.assertEqual(programas, {"8501"})
        self.assertEqual(tarefa["chapas_total"], 4)
        repeticoes = sorted(plano["repeticao"] for plano in tarefa["planos"])
        self.assertEqual(repeticoes, [1, 2, 3, 4])

    def test_destaque_da_tarefa_inteira_continua_disponivel(self):
        """O fluxo oficial permite apontar o plano OU a tarefa completa."""

        for letra in self.CHAPAS:
            self._cortar(letra)
        iniciado = self.destaque.registrar_destacando(self.tarefa_id, "T001")
        self.assertTrue(iniciado.ok, iniciado.message)
        finalizado = self.destaque.registrar_finalizado(
            self.tarefa_id, "T001", operador_identificacao="Iago"
        )
        self.assertTrue(finalizado.ok, finalizado.message)
        self.assertEqual(
            self.db.buscar_tarefa_por_codigo("T001")["status"], "Finalizado"
        )


if __name__ == "__main__":
    unittest.main()
