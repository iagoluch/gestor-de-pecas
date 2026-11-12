""""Finalizar Ret." (manufatura, 20/10/2026): encerra o retrabalho sem finalizar a OP.

A OP sai de Retrabalho e volta a Em processo. Desde 12/11/2026 não lança peça
boa nem refugo (travava o saldo da OP): quem conta é o Finalizar normal. O
crachá é sempre exigido.
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

    def test_peca_boa_ou_refugo_sao_recusados_e_nao_mexem_no_saldo(self):
        # 12/11/2026: lançar peça aqui esgotava o saldo e travava a OP.
        for extra in ({"pecas_boas": 1}, {"refugo": 1, "cracha_refugo": "1"}):
            result = self._execute(self.ACAO, operadores_cracha=["1"], **extra)
            self.assertFalse(result.ok)
            self.assertEqual(result.code, "quantidade_invalida")
            self.assertEqual(self._status(), "Retrabalho")
        self.assertEqual(self.database.quantity_events, [])
        self.assertEqual(self.database.appointments[0].get("quantidade_boa") or 0, 0)

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
        result = self._execute(self.ACAO, operadores_cracha=["999"])
        self.assertFalse(result.ok)
        self.assertEqual(result.code, "cracha_invalido")
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
        self.assertTrue(self._execute(self.ACAO, operadores_cracha=["1"]).ok)
        final = self._execute("Finalizado", pecas_boas=2, operadores_cracha=["1"])
        self.assertTrue(final.ok, final.message)
        self.assertEqual(final.data["status"], "Finalizado")


if __name__ == "__main__":
    unittest.main()
