""""Finalizar Ret." (manufatura, 20/10/2026): encerra o retrabalho sem finalizar a OP.

A OP sai de Retrabalho e volta a Em processo; boas e refugo informados entram
como peças recuperadas (fora do FTT, regra de 19/10/2026). Campo vazio vale 0
e o crachá é sempre exigido.
"""

import unittest

from mes.domain import OperatorState, can_transition
from tests import test_operator_state_machine as _maquina


class FinalizarRetrabalhoTests(unittest.TestCase):
    ACAO = "Finalizar Retrabalho"

    def setUp(self):
        base = _maquina.OperatorStateMachineTests()
        self.database, self.service, self.operation = base._service()
        self._execute = lambda action, **extra: base._execute(
            self.service, self.operation, action, **extra
        )
        self.assertTrue(self._execute("Retrabalho").ok)

    def _status(self):
        return self.database.appointments[0]["status"]

    def test_so_boas_volta_a_em_processo_e_marca_a_recuperada(self):
        result = self._execute(self.ACAO, pecas_boas=1, operadores_cracha=["1"])
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.data["status"], "Em processo")  # não finaliza a OP
        self.assertEqual(result.data["quantidade_boa"], 1)
        self.assertIsNone(result.data.get("data_fim"))
        self.assertEqual(
            [(e["tipo"], e["quantidade"], e["quantidade_recuperada"])
             for e in self.database.quantity_events],
            [("boa", 1, 1)],
        )
        self.assertEqual(self.database.operator_events[-1]["estado"], "producao")

    def test_so_refugo_com_responsavel_e_valido(self):
        result = self._execute(self.ACAO, refugo=1, operadores_cracha=["1"])
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.data["status"], "Em processo")
        self.assertEqual(result.data["quantidade_refugo"], 1)
        self.assertEqual(
            [(e["tipo"], e["quantidade_recuperada"]) for e in self.database.quantity_events],
            [("refugo", 1)],
        )

    def test_zero_a_zero_so_encerra_o_retrabalho_sem_lancar_peca(self):
        result = self._execute(self.ACAO, pecas_boas=None, refugo="", operadores_cracha=["1"])
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.data["status"], "Em processo")
        self.assertEqual(self.database.quantity_events, [])

    def test_cracha_e_obrigatorio_mesmo_com_zero_a_zero(self):
        result = self._execute(self.ACAO)
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "cracha_obrigatorio")
        self.assertEqual(self._status(), "Retrabalho")

    def test_cracha_invalido_e_recusado(self):
        result = self._execute(self.ACAO, pecas_boas=1, operadores_cracha=["999"])
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "cracha_invalido")
        self.assertEqual(self._status(), "Retrabalho")
        self.assertEqual(self.database.quantity_events, [])

    def test_refugo_sem_responsavel_exige_o_cracha_de_quem_autoriza(self):
        self.database.operator_badges.append(
            {"id": 2, "cracha": "2", "nome": "Op", "ativo": True, "autorizador_retrabalho": False}
        )
        recusado = self._execute(self.ACAO, refugo=1, operadores_cracha=["2"])
        self.assertFalse(recusado.ok)
        self.assertEqual(recusado.code, "refugo_autorizacao_obrigatoria")
        self.assertEqual(self._status(), "Retrabalho")
        autorizado = self._execute(
            self.ACAO, refugo=1, operadores_cracha=["2"], cracha_refugo="1"
        )
        self.assertTrue(autorizado.ok, autorizado.message)

    def test_nao_ultrapassa_o_saldo_da_op(self):
        result = self._execute(self.ACAO, pecas_boas=3, operadores_cracha=["1"])  # OP de 2
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "quantidade_inconsistente")
        self.assertEqual(self._status(), "Retrabalho")

    def test_so_vale_para_op_em_retrabalho(self):
        self.assertFalse(self._execute("Início").ok)  # regra geral
        self.assertTrue(self._execute("Parada", motivo_codigo="0029").ok)
        self.assertTrue(self._execute("Retomar").ok)  # volta ao Retrabalho
        self.assertTrue(self._execute(self.ACAO, operadores_cracha=["1"]).ok)
        # Já em Em processo: o botão não existe e a API recusa.
        repetido = self._execute(self.ACAO, operadores_cracha=["1"])
        self.assertFalse(repetido.ok)
        self.assertEqual(repetido.code, "fim_retrabalho_incompativel")

    def test_regra_geral_continua_recusando_retrabalho_para_producao(self):
        self.assertFalse(can_transition(OperatorState.REWORK, OperatorState.PRODUCTION))
        self.assertEqual(self._execute("Início").code, "transicao_invalida")

    def test_depois_de_encerrar_o_operador_pode_finalizar_a_op(self):
        self.assertTrue(self._execute(self.ACAO, pecas_boas=1, operadores_cracha=["1"]).ok)
        final = self._execute("Finalizado", pecas_boas=1, operadores_cracha=["1"])
        self.assertTrue(final.ok, final.message)
        self.assertEqual(final.data["status"], "Finalizado")


if __name__ == "__main__":
    unittest.main()
