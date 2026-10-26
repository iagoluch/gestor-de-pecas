"""Genealogia por peça na rastreabilidade da OP (somente leitura)."""

import unittest
from datetime import datetime

from mes.services.traceability import TraceabilityService
from tests.fakes import FakeDatabase


class _DbComInspecao(FakeDatabase):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows
        self.codigos = []

    def listar_pecas_inspecionadas_por_op(self, codigo_op):
        self.codigos.append(codigo_op)
        return self.rows


def _linha(peca_id, numero, resultado, sequencia=None, status=None, **extra):
    return {
        "inspecao_id": 7, "numero_operacao": "30", "peca_id": peca_id,
        "numero_peca": numero, "resultado": resultado, "rnc_id": None,
        "rnc_codigo": None, "operador": "Ana", "registrada_em": datetime(2026, 10, 26, 8, numero),
        "sequencia": sequencia, "descricao_snapshot": f"Cota {sequencia}" if sequencia else None,
        "padrao_snapshot": "10 ±0,1" if sequencia else None, "unidade_snapshot": "mm" if sequencia else None,
        "medida": "10,4" if sequencia else None, "cota_status": status, **extra,
    }


class GenealogiaPorPecaTests(unittest.TestCase):
    def test_agrupa_cotas_por_peca_e_conta_nao_conformes(self):
        db = _DbComInspecao([
            _linha(1, 1, "APROVADA", 1, "CONFORME"),
            _linha(1, 1, "APROVADA", 2, "CONFORME"),
            _linha(2, 2, "RETRABALHO", 1, "NAO_CONFORME", rnc_id=5, rnc_codigo="RNC-5"),
            _linha(2, 2, "RETRABALHO", 2, "CONFORME", rnc_id=5, rnc_codigo="RNC-5"),
            _linha(3, 3, "REFUGO"),
        ])

        pieces = TraceabilityService(db).trace_op("op-1")["pieces"]

        self.assertEqual([p["numero_peca"] for p in pieces], [1, 2, 3])
        self.assertEqual([len(p["cotas"]) for p in pieces], [2, 2, 0])
        self.assertEqual([p["total_cotas_nao_conformes"] for p in pieces], [0, 1, 0])
        self.assertEqual(pieces[1]["rnc_codigo"], "RNC-5")
        self.assertEqual(pieces[1]["cotas"][0], {
            "descricao": "Cota 1", "padrao": "10 ±0,1", "unidade": "mm",
            "medida": "10,4", "status": "NAO_CONFORME",
        })
        self.assertEqual(db.codigos, ["op-1"])

    def test_op_sem_inspecao_devolve_lista_vazia(self):
        self.assertEqual(TraceabilityService(_DbComInspecao([])).trace_op("OP-X")["pieces"], [])

    def test_repositorio_sem_o_metodo_nao_quebra_a_resposta(self):
        self.assertEqual(TraceabilityService(FakeDatabase()).trace_op("OP-X")["pieces"], [])


if __name__ == "__main__":
    unittest.main()
