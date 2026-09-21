import unittest

from mes.domain import (
    ALLOWED_TRANSITIONS,
    PHYSICAL_STATE_VALUES,
    OperatorState,
    can_transition,
    resolve_operator_action,
    validate_transition,
)
from mes.services.operator_flow import OperatorFlowService
from tests.fakes import FakeDatabase
from tests.wave5_helpers import liberar_primeira_peca


class OperatorStateMachineTests(unittest.TestCase):
    def _service(self):
        database = FakeDatabase()
        task_id = database.inserir_tarefa("T-MAQUINA-ESTADOS")
        database.inserir_op_na_tarefa(
            task_id,
            "OP-MAQUINA-ESTADOS",
            "PEÇA",
            "Dobra",
            2,
        )
        operation = {
            "id": 901,
            "codigo_op": "OP-MAQUINA-ESTADOS",
            "numero_operacao": "20",
            "codigo_recurso": "DOBRA3",
            "descricao_operacao": "DOBRA",
            "tipo_setor": "Dobra",
            "produto_codigo": "PEÇA",
            "produto_descricao": "PEÇA DE TESTE",
            "quantidade": 2,
        }
        database.catalog_operations.append(operation)
        # Wave 6B: em Dobra o Iniciar passa pelo portão Setup/Qualidade. Estes
        # testes são da máquina de estados, então o posto já parte do estado em
        # que o operador está depois do popup: primeira peça aprovada.
        liberar_primeira_peca(
            database,
            "OPERADOR TESTE",
            op="OP-MAQUINA-ESTADOS",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
        )
        return database, OperatorFlowService(database, "OPERADOR TESTE"), operation

    def _execute(self, service, operation, action, **extra):
        return service.executar(
            action,
            op="OP-MAQUINA-ESTADOS",
            setor="Dobra",
            recurso="1303",
            operacao=operation,
            **extra,
        )

    def test_op_aberta_exige_inicio_antes_do_setup(self):
        cases = (
            ("Início", "Em processo", {}),
            ("Parada", "Parada", {"motivo_codigo": "0029"}),
            ("Retrabalho", "Retrabalho", {}),
        )
        for action, expected, extra in cases:
            with self.subTest(action=action):
                _database, service, operation = self._service()
                result = self._execute(service, operation, action, **extra)
                self.assertTrue(result.ok, result.message)
                self.assertEqual(result.data["status"], expected)

        _database, service, operation = self._service()
        setup = self._execute(service, operation, "Setup")
        self.assertFalse(setup.ok)
        self.assertEqual(setup.code, "setup_exige_inicio")

    def test_retrabalho_parada_retomar_retorna_ao_retrabalho(self):
        database, service, operation = self._service()
        self.assertTrue(self._execute(service, operation, "Retrabalho").ok)
        stopped = self._execute(
            service,
            operation,
            "Parada",
            motivo_codigo="0029",
        )
        self.assertTrue(stopped.ok, stopped.message)
        self.assertEqual(stopped.data["estado_retorno"], "retrabalho")

        resumed = self._execute(service, operation, "Retomar")
        self.assertTrue(resumed.ok, resumed.message)
        self.assertEqual(resumed.data["status"], "Retrabalho")
        self.assertIsNone(resumed.data["estado_retorno"])
        self.assertEqual(
            [event["estado"] for event in database.operator_events],
            ["fila", "retrabalho", "parada", "retrabalho"],
        )

    def test_retrabalho_setup_retornar_retorna_ao_retrabalho(self):
        _database, service, operation = self._service()
        self.assertTrue(self._execute(service, operation, "Retrabalho").ok)
        setup = self._execute(service, operation, "Setup")
        self.assertTrue(setup.ok, setup.message)
        self.assertEqual(setup.data["estado_retorno"], "retrabalho")

        returned = self._execute(service, operation, "Retornar")
        self.assertTrue(returned.ok, returned.message)
        self.assertEqual(returned.data["status"], "Retrabalho")

    def test_setup_pode_ir_para_producao_ou_retrabalho(self):
        for action, expected in (("Início", "Em processo"), ("Retrabalho", "Retrabalho")):
            with self.subTest(action=action):
                _database, service, operation = self._service()
                self.assertTrue(self._execute(service, operation, "Início").ok)
                self.assertTrue(self._execute(service, operation, "Setup").ok)
                result = self._execute(service, operation, action)
                self.assertTrue(result.ok, result.message)
                self.assertEqual(result.data["status"], expected)

    def test_retrabalho_nao_pode_ir_diretamente_para_producao(self):
        _database, service, operation = self._service()
        self.assertTrue(self._execute(service, operation, "Retrabalho").ok)

        result = self._execute(service, operation, "Início")

        self.assertFalse(result.ok)
        self.assertEqual(result.code, "transicao_invalida")
        self.assertFalse(can_transition(OperatorState.REWORK, OperatorState.PRODUCTION))
        self.assertIsNone(resolve_operator_action("Início", OperatorState.REWORK))

    def test_transicoes_sao_uma_definicao_de_dominio(self):
        self.assertTrue(can_transition(OperatorState.QUEUED, OperatorState.STOPPED))
        self.assertFalse(can_transition(OperatorState.QUEUED, OperatorState.SETUP))
        self.assertTrue(can_transition(OperatorState.REWORK, OperatorState.STOPPED))
        self.assertTrue(can_transition(OperatorState.REWORK, OperatorState.SETUP))
        self.assertFalse(can_transition(OperatorState.REWORK, OperatorState.PRODUCTION))
        self.assertFalse(can_transition(OperatorState.STOPPED, OperatorState.SETUP))
        self.assertEqual(
            resolve_operator_action("Retomar", OperatorState.STOPPED, OperatorState.REWORK),
            OperatorState.REWORK,
        )
        self.assertIn(OperatorState.REWORK, ALLOWED_TRANSITIONS[OperatorState.SETUP])

    def test_parada_direta_exige_contexto_da_op_e_motivo(self):
        validation = validate_transition(
            OperatorState.QUEUED,
            OperatorState.STOPPED,
            {"op": "OP-1", "operacao": "20", "recurso": "1303"},
        )
        self.assertFalse(validation.ok)
        self.assertEqual(validation.missing_fields, ("motivo_parada",))

    def test_estados_fisicos_canonicos_incluem_fila_ponta_a_ponta(self):
        self.assertEqual(
            PHYSICAL_STATE_VALUES,
            (
                "fila",
                "producao",
                "parada",
                "setup",
                "retrabalho",
                "atividade_sem_op",
                "fora_turno",
                "desconhecido",
            ),
        )


if __name__ == "__main__":
    unittest.main()
