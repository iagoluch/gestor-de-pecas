import unittest
from datetime import datetime

from mes.services.person_hours import horas_por_pessoa


def _p(cracha, inicio, fim, recurso="1303", op="OP1", nome=None):
    return {"cracha_resolvido": cracha, "nome_resolvido": nome or cracha, "recurso": recurso, "op": op,
            "data_inicio": datetime(2026, 11, 12, *inicio), "data_fim": datetime(2026, 11, 12, *fim) if fim else None}


INICIO = datetime(2026, 11, 12, 0, 0)
FIM = datetime(2026, 11, 13, 0, 0)
AGORA = datetime(2026, 11, 12, 12, 0)


class PersonHoursTests(unittest.TestCase):
    def test_cada_pessoa_conta_o_proprio_tempo_sem_dividir(self):
        result = horas_por_pessoa([_p("1", (8, 0), (10, 0), nome="Ana"), _p("2", (8, 0), (10, 0), nome="Bruno")], INICIO, FIM, AGORA)
        self.assertEqual([(p["nome"], p["segundos"]) for p in result["pessoas"]], [("Ana", 7200.0), ("Bruno", 7200.0)])
        self.assertEqual(result["total_segundos"], 14400.0)

    def test_ops_simultaneas_no_mesmo_posto_nao_contam_duas_vezes(self):
        rows = [_p("1", (8, 0), (10, 0), op="A"), _p("1", (9, 0), (11, 0), op="B")]
        pessoa = horas_por_pessoa(rows, INICIO, FIM, AGORA)["pessoas"][0]
        self.assertEqual(pessoa["segundos"], 3 * 3600.0)
        self.assertEqual(pessoa["ops"], 2)

    def test_aberta_conta_ate_agora_e_periodo_corta(self):
        rows = [_p("1", (11, 0), None), _p("2", (23, 0), None)]
        pessoas = {p["cracha"]: p for p in horas_por_pessoa(rows, INICIO, FIM, AGORA)["pessoas"]}
        self.assertEqual(pessoas["1"]["segundos"], 3600.0)
        self.assertTrue(pessoas["1"]["trabalhando_agora"])
        self.assertNotIn("2", pessoas)  # começou depois de "agora"

    def test_periodo_passado_nao_marca_trabalhando_agora(self):
        rows = [_p("1", (8, 0), None)]
        pessoa = horas_por_pessoa(rows, INICIO, datetime(2026, 11, 12, 10, 0), AGORA)["pessoas"][0]
        self.assertEqual(pessoa["segundos"], 7200.0)
        self.assertFalse(pessoa["trabalhando_agora"])

    def test_filtro_com_fuso_nao_quebra(self):
        from datetime import timezone
        inicio = INICIO.astimezone(timezone.utc)
        result = horas_por_pessoa([_p("1", (8, 0), (9, 0))], inicio, FIM, AGORA)
        self.assertEqual(result["pessoas"][0]["segundos"], 3600.0)

    def test_horas_por_maquina(self):
        rows = [_p("1", (8, 0), (9, 0), recurso="1303"), _p("1", (9, 0), (9, 30), recurso="1304")]
        pessoa = horas_por_pessoa(rows, INICIO, FIM, AGORA)["pessoas"][0]
        self.assertEqual(pessoa["recursos"], [{"recurso": "1303", "segundos": 3600.0}, {"recurso": "1304", "segundos": 1800.0}])


if __name__ == "__main__":
    unittest.main()
