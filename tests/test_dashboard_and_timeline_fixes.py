import unittest

from tests.fakes import FakeDatabase


class DashboardTimelineFixesTests(unittest.TestCase):
    def _db(self):
        return None, FakeDatabase()

    def _cleanup(self, path):
        return None

    def test_despacho_preserva_maquina_corrigida(self):
        path, db = self._db()
        try:
            tarefa_id = db.inserir_tarefa("T900")
            op_id = db.inserir_op_na_tarefa(tarefa_id, "00601316024", "PECA", "Aguardando Dobra", 1)
            db.atualizar_op(op_id, "Romi 300", 1)
            db.atualizar_tarefa_status(tarefa_id, "Despachado")
            # Simula o fluxo real: tarefa finalizada e despachada com OP corrigida para máquina.
            db.atualizar_tarefa_status(tarefa_id, "Finalizado")
            db.despachar_tarefa(tarefa_id, "Iago - Dev", maquinas_dobra=["Gasparini"], maquinas_usinagem=["Romi 300"])
            atual = db.get_current_ops(search="00601316024")[0]
            self.assertEqual(atual["setor"], "Romi 300")
        finally:
            self._cleanup(path)

    def test_timeline_encontra_op_mesmo_sem_zero_inicial(self):
        path, db = self._db()
        try:
            db.inserir_historico("00601316024", "Movimentação", "Aguardando Dobra", "", 1, "Iago", "PECA", None)
            timeline = db.get_op_timeline("601316024")
            self.assertEqual(len(timeline), 1)
            self.assertEqual(timeline[0]["op"], "00601316024")
        finally:
            self._cleanup(path)

    def test_contagem_de_ops_por_tarefa_usa_uma_consulta_agrupada(self):
        path, db = self._db()
        try:
            tarefa_1 = db.inserir_tarefa("T910")
            tarefa_2 = db.inserir_tarefa("T911")
            db.inserir_op_na_tarefa(tarefa_1, "OP910-A", "PECA", "Aguardando Dobra", 1)
            db.inserir_op_na_tarefa(tarefa_1, "OP910-B", "PECA", "Aguardando Dobra", 1)
            db.inserir_op_na_tarefa(tarefa_2, "OP911-A", "PECA", "Aguardando Usinagem", 1)

            self.assertEqual(db.get_op_counts_by_task([tarefa_1, tarefa_2]), {tarefa_1: 2, tarefa_2: 1})
            self.assertEqual(db.get_op_counts_by_task([]), {})
        finally:
            self._cleanup(path)

    def test_primeira_op_por_tarefa_preserva_ordem_sem_consultas_individuais(self):
        path, db = self._db()
        try:
            tarefa_1 = db.inserir_tarefa("T912")
            tarefa_2 = db.inserir_tarefa("T913")
            db.inserir_op_na_tarefa(tarefa_1, "OP912-A", "PECA", "Dobra", 1)
            db.inserir_op_na_tarefa(tarefa_1, "OP912-B", "PECA", "Dobra", 1)
            db.inserir_op_na_tarefa(tarefa_2, "OP913-A", "PECA", "Usinagem", 1)

            primeiras = db.get_first_op_codes_by_task([tarefa_1, tarefa_2])

            self.assertEqual(primeiras, {tarefa_1: "OP912-A", tarefa_2: "OP913-A"})
            self.assertEqual(db.get_first_op_codes_by_task([]), {})
        finally:
            self._cleanup(path)

    def test_ultimas_ops_despachadas_nao_mostra_tarefa_ou_maquina(self):
        path, db = self._db()
        try:
            tarefa_id = db.inserir_tarefa("T901")
            db.inserir_op_na_tarefa(tarefa_id, "OP901", "PECA", "Aguardando Dobra", 1)
            db.atualizar_tarefa_status(tarefa_id, "Destacando")
            db.inserir_historico("T901", "Movimentação", "Organização de Pallets", "", 0, "Iago", "", tarefa_id, data_hora="2026-07-06 14:00:00")
            db.inserir_historico("OP901", "Movimentação", "Gasparini", "", 1, "Iago", "PECA", tarefa_id, data_hora="2026-07-06 14:10:00")
            db.atualizar_tarefa_status(tarefa_id, "Finalizado")
            db.despachar_tarefa(tarefa_id, "Iago")
            rows = db.ultimas_ops_despachadas(limite=10)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["op"], "OP901")
            self.assertNotEqual(rows[0]["setor"], "Gasparini")
        finally:
            self._cleanup(path)


if __name__ == "__main__":
    unittest.main()
