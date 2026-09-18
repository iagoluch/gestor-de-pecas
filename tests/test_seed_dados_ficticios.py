import unittest

from app.core.operator_sectors import operator_route_resource_label
from scripts.seed_dados_ficticios import SourceOperation, destination_after_cut


def _route(number, resource, sector):
    return SourceOperation(
        filial="01",
        tipo="OF",
        roteiro="TESTE",
        produto_codigo="P1",
        numero_operacao=str(number),
        codigo_recurso=resource,
        descricao_operacao=sector or resource,
        produto_descricao="Peça de teste",
        tempo_medio_segundos=60,
        codigo_op="FICOPR99999",
        tipo_setor=sector,
        origem_aba="Teste",
    )


class SeedDadosFicticiosTest(unittest.TestCase):
    def test_destino_e_primeiro_setor_real_depois_do_corte(self):
        route = [
            _route(30, "TCNC-1", "Usinagem"),
            _route(10, "LASER", "Corte"),
            _route(20, "DOBRA3", "Dobra"),
        ]

        self.assertEqual(destination_after_cut(route), "1303")

    def test_pintura_e_solda_usam_o_nome_do_setor_enquanto_etapas_nao_foram_definidas(self):
        self.assertEqual(
            destination_after_cut(
                [_route(10, "LASER", "Corte"), _route(20, "PINT.L", "Pintura")]
            ),
            "Pintura",
        )
        self.assertEqual(
            destination_after_cut(
                [_route(10, "LASER", "Corte"), _route(20, "SOLDA4", "Solda")]
            ),
            "Soldagem",
        )

    def test_recursos_de_usinagem_usam_os_cinco_nomes_publicos_das_telas(self):
        expected = {
            "CNC-01": "Romi D 1000",
            "CNC-02": "Eurostec",
            "FRESA1": "Fresadora FTV31",
            "TCNC-1": "Romi GL 350M",
            "TORNOC": "Torno Mecânico",
        }

        for resource, public_name in expected.items():
            with self.subTest(resource=resource):
                self.assertEqual(
                    operator_route_resource_label("Usinagem", resource),
                    public_name,
                )

        self.assertEqual(
            destination_after_cut(
                [_route(10, "LASER", "Corte"), _route(20, "TCNC-1", "Usinagem")]
            ),
            "Romi GL 350M",
        )

    def test_corte_sem_proxima_operacao_vai_para_almoxarifado(self):
        self.assertEqual(
            destination_after_cut([_route(10, "PLASMA", "Corte")]),
            "Almoxarifado",
        )


if __name__ == "__main__":
    unittest.main()
