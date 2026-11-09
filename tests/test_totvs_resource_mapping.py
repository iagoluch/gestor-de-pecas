from dataclasses import replace
from decimal import Decimal
from pathlib import Path
import unittest

from mes.integrations.totvs.mapper import TotvsProductionOrderMapper
from mes.integrations.totvs.models import TotvsActivityClassification
from mes.integrations.totvs.parser import TotvsMessageParser
from mes.integrations.totvs.resource_mapping import TotvsResourceResolver


FIXTURE = (
    Path(__file__).parent
    / "fixtures/totvs/ok_productionorder_20260827120232_a9716901001.xml"
)


class TotvsCatalogSectorPrecedenceTests(unittest.TestCase):
    def setUp(self):
        self.message = TotvsMessageParser().parse(FIXTURE.read_bytes())
        self.activity = replace(
            self.message.production_order.activities[1],
            # Assinatura observada na OP 00588501002: CORTE/CORTE/SERRA3.
            activity_description="CORTE",
            work_center_code="CORTE",
            machine_code="SERRA3",
            time_resource=Decimal("0.5"),
            unit_item_number=Decimal("1"),
            unit_time_type="1",
        )

    def map_activity(self, resolver, activity=None):
        return TotvsProductionOrderMapper(resolver).map(
            replace(
                self.message,
                production_order=replace(
                    self.message.production_order,
                    activities=(activity or self.activity,),
                ),
            )
        )

    def test_corte_na_serra3_preserva_recurso_setor_e_tempo_do_protheus(self):
        result = self.map_activity(
            TotvsResourceResolver(known_resource_sectors={"SERRA3": "Serra"})
        )
        self.assertEqual(len(result.operations), 1)
        operation = result.operations[0]
        self.assertEqual(operation.tipo_setor, "Serra")
        self.assertEqual(operation.codigo_recurso, "SERRA3")
        self.assertEqual(operation.descricao_operacao, "CORTE")
        self.assertEqual(operation.totvs_machine_code, "SERRA3")
        self.assertEqual(operation.totvs_work_center_code, "CORTE")
        self.assertEqual(operation.tempo_medio_segundos, Decimal("1800.000"))
        self.assertEqual(
            result.activity_treatments[0].classification,
            TotvsActivityClassification.POINTABLE_CONFIRMED,
        )

    def test_cadastro_confirmado_prevalece_nos_postos_existentes(self):
        resources = {
            "SERRA1": "Serra",
            "SERRA2": "Serra",
            "CNC-01": "Usinagem",
            "CNC-02": "Usinagem",
            "FRESA1": "Usinagem",
            "TCNC-1": "Usinagem",
            "TORNOC": "Usinagem",
            "DOBRA2": "Dobra",
            "ESTUFA": "Pintura",
            "PREMTG": "Protótipo",
            "DISPEX": "Proj. Ferramentaria",
            "ROBO P": "Solda Robô",
        }
        resolver = TotvsResourceResolver(known_resource_sectors=resources)
        for code, sector in resources.items():
            with self.subTest(resource=code):
                result = self.map_activity(
                    resolver, replace(self.activity, machine_code=code)
                )
                self.assertEqual(
                    [(op.codigo_recurso, op.tipo_setor) for op in result.operations],
                    [(code, sector)],
                )

    def test_sem_setor_cadastrado_nao_inventa_serra_pelo_codigo(self):
        resolver = TotvsResourceResolver(known_resource_codes={"SERRA3"})
        self.assertEqual(resolver.resolve_sector(self.activity), "Corte")

    def test_recurso_fora_do_inventario_nao_ganha_prioridade_por_cadastro(self):
        resolver = TotvsResourceResolver(
            known_resource_sectors={"SERRA-X": "Serra"}
        )
        result = self.map_activity(
            resolver, replace(self.activity, machine_code="SERRA-X")
        )
        self.assertEqual(result.operations, ())
        self.assertEqual(
            result.activity_treatments[0].classification,
            TotvsActivityClassification.PENDING_DECISION,
        )

    def test_machine_code_nao_e_substituido_pelo_work_center(self):
        resolver = TotvsResourceResolver(
            known_resource_sectors={"SERRA3": "Serra"}
        )
        result = self.map_activity(
            resolver,
            replace(self.activity, machine_code="SERRA-X", work_center_code="SERRA3"),
        )
        self.assertEqual(result.operations, ())

    def test_cadastro_prevalece_sobre_alias_de_descricao_generica(self):
        resolver = TotvsResourceResolver(
            known_resource_sectors={"SERRA3": "Serra"},
            sector_aliases={"CORTE": "Corte"},
        )
        self.assertEqual(resolver.resolve_sector(self.activity), "Serra")

    def test_classificacoes_especiais_continuam_fora_dos_postos(self):
        # Mesmo um cadastro indevido não transforma assinaturas especiais
        # em produção: o mapper deve classificá-las antes de resolver o setor.
        resolver = TotvsResourceResolver(
            resource_aliases={
                "PCP": "SERRA3", "INSPEC": "SERRA3", "ALMOX4": "SERRA3",
            },
            known_resource_sectors={
                "PCP": "Serra", "INSPEC": "Serra", "ALMOX4": "Serra",
                "SERRA3": "Serra",
                "PLASMA": "Corte", "CNC-01": "Usinagem",
            }
        )
        result = TotvsProductionOrderMapper(resolver).map(self.message)
        classifications = {
            item.activity_code: item.classification
            for item in result.activity_treatments
        }
        self.assertEqual(
            classifications["01"], TotvsActivityClassification.AUTOMATIC_SATISFIED
        )
        self.assertEqual(
            classifications["30"], TotvsActivityClassification.QUALITY_INSPECTION
        )
        self.assertEqual(
            classifications["99"], TotvsActivityClassification.TERMINAL_CONFIRMED
        )
        self.assertEqual(
            [
                (op.codigo_recurso, op.tipo_setor)
                for op in result.operations
                if not op.marco_terminal and not op.inspecao_qualidade
            ],
            [("PLASMA", "Corte"), ("CNC-01", "Usinagem")],
        )


if __name__ == "__main__":
    unittest.main()
