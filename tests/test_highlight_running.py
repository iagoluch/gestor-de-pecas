"""Destaques em execução: a Parada do posto só age sobre o que realmente roda."""

from __future__ import annotations

import unittest

from backend.api.routers.highlight import _destaques_em_execucao


class _Db:
    def __init__(self, grupos):
        self._grupos = grupos

    def listar_fila_destaque(self, limite=10000):
        return self._grupos


class _Service:
    def __init__(self, estados):
        self._estados = estados

    def estado_destaque(self, tarefa_id):
        return self._estados.get(tarefa_id)


class DestaquesEmExecucaoTests(unittest.TestCase):
    def test_plano_iniciado_e_parado_nao_vira_tarefa_em_execucao(self):
        # O início de um plano grava status "Destacando" na tarefa; sem evento
        # da tarefa inteira o estado vem desse status e parece "inicio".
        grupos = [{
            "tarefa_id": 7, "codigo_tarefa": "T-7",
            "planos": [{"plano_hash": "A", "estado_destaque": "fim"},
                       {"plano_hash": "B", "estado_destaque": "aguardando"}],
        }]
        service = _Service({7: {"estado": "inicio", "evento": None}})
        self.assertEqual(_destaques_em_execucao(_Db(grupos), service), [])

    def test_tarefa_iniciada_inteira_com_evento_proprio_conta(self):
        grupos = [{"tarefa_id": 7, "codigo_tarefa": "T-7", "planos": []}]
        service = _Service({7: {"estado": "retomada", "evento": {"id": 1}}})
        self.assertEqual(_destaques_em_execucao(_Db(grupos), service), [(7, "T-7", None)])

    def test_plano_em_execucao_conta_por_plano(self):
        grupos = [{
            "tarefa_id": 7, "codigo_tarefa": "T-7",
            "planos": [{"plano_hash": "A", "estado_destaque": "inicio"},
                       {"plano_hash": "B", "estado_destaque": "retomada"}],
        }]
        self.assertEqual(
            _destaques_em_execucao(_Db(grupos), _Service({})),
            [(7, "T-7", "A"), (7, "T-7", "B")],
        )


if __name__ == "__main__":
    unittest.main()
