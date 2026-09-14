import unittest

from mes.services.task_lookup import TarefaLookupService


class FakeDb:
    def __init__(self):
        self.tarefas = {}
        self.catalogo = {}

    def buscar_tarefa_por_codigo(self, codigo):
        return self.tarefas.get(str(codigo).strip().upper())

    def materializar_tarefa_catalogo(self, codigo):
        tarefa = self.catalogo.get(str(codigo).strip().upper())
        if tarefa:
            self.tarefas[tarefa["codigo_tarefa"]] = dict(tarefa)
            return dict(tarefa)
        return None


class TarefaLookupServiceTests(unittest.TestCase):
    def test_busca_tarefa_no_postgresql_de_teste(self):
        db = FakeDb()
        db.tarefas["T100"] = {"id": 1, "codigo_tarefa": "T100"}

        result = TarefaLookupService(db, operador="TESTE").buscar_local(" t100 ")

        self.assertTrue(result.ok)
        self.assertEqual(result.source, "postgresql_test")
        self.assertEqual(result.tarefa["codigo_tarefa"], "T100")

    def test_catalogo_local_pode_materializar_sem_conexao_externa(self):
        db = FakeDb()
        db.catalogo["T150"] = {"id": 15, "codigo_tarefa": "T150"}

        result = TarefaLookupService(db).buscar_local("t150")

        self.assertTrue(result.ok)
        self.assertEqual(result.source, "catalogo_local")
        self.assertEqual(result.tarefa["id"], 15)

    def test_tarefa_ausente_nao_dispara_fallback(self):
        result = TarefaLookupService(FakeDb()).buscar_local("T-NAO-EXISTE")

        self.assertFalse(result.ok)
        self.assertEqual(result.source, "postgresql_test")
        self.assertEqual(result.error, "not_found")
        self.assertIn("banco de teste", result.message)


if __name__ == "__main__":
    unittest.main()
