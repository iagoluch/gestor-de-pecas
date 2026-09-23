from datetime import datetime
from dataclasses import replace
import hashlib
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from fastapi.testclient import TestClient

from backend.api.config import WebSettings
from backend.api.main import create_app
from mes.integrations.totvs.errors import (
    TotvsIdentityConflictError,
    TotvsIntegrationError,
    TotvsUnsupportedMessageError,
    TotvsXmlParseError,
    TotvsXmlSecurityError,
)
from mes.contracts.corporate import CorporateMessageIngestion
from mes.integrations.totvs.mapper import TotvsProductionOrderMapper
from mes.integrations.totvs.parser import TotvsMessageParser
from mes.integrations.totvs.resource_mapping import TotvsResourceResolver
from mes.integrations.totvs.models import (
    TotvsActivityClassification,
    TotvsMessageOutcome,
)
from mes.integrations.totvs.service import (
    TotvsProductionOrderIngestionService,
    build_gestor_identity,
)
from mes.integrations.totvs.response import TotvsGestorIdentity, build_response_message
from tests.fakes import FakeDatabase


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "totvs"
PEND = FIXTURES / "pend_productionorder_20260818165346_10796502001.xml"
OK = FIXTURES / "ok_productionorder_20260821103018_1079689c001 1.xml"
WHOIS = FIXTURES / "whois_20260827102117_pcpa109.xml"
REAL_OP = FIXTURES / "ok_productionorder_20260827120232_a9716901001.xml"
SOAP_ACTION = "http://tempuri.org/EAIService/receiveMessage"

AUDITED_PAINTING_RESOURCES = (
    "ESTUFA",
    "INSPE2",
    "JATO",
    "PINT.L",
    "PREP",
    "RETOQ",
    "TINTA",
)
AUDITED_WELDING_RESOURCES = (
    "ALMOXS",
    "C X10",
    "CG- FIL05",
    "D01PRO",
    "D02510",
    "D02DSR",
    "D02DUO",
    "D02DXS",
    "D03510",
    "D04CHA",
    "D05510",
    "D05CAB",
    "D06510",
    "D06EIX",
    "D07510",
    "D14CHA",
    "D14EIX",
    "D14STQ",
    "HASTE",
    "MT NT",
    "P 2895",
    "P 3344",
    "ROBO P",
    "ROBO S",
    "S ART",
    "S ARTL",
    "S CAB",
    "S CEN",
    "S EIX",
    "S INT",
    "S PRI",
    "S TUB7",
    "SART",
    "SART5",
    "SEIXO",
    "SF5",
    "SL5",
    "SMSX",
    "SOLBER",
    "SOLDA PM05",
    "SOLDA4",
    "SOLTAN",
    "SRD",
    "SSRD",
)


class TotvsParserContractTests(unittest.TestCase):
    def setUp(self):
        self.parser = TotvsMessageParser()

    def test_xml_real_pendente_preserva_contrato_atividades_e_materiais(self):
        message = self.parser.parse(PEND.read_bytes())
        order = message.production_order
        self.assertEqual(message.metadata.uuid, "1")
        self.assertEqual(message.metadata.transaction, "ProductionOrder")
        self.assertEqual(message.event.entity, "ProductionOrder")
        self.assertEqual(message.event.event, "upsert")
        self.assertEqual(order.number, "10796502001")
        self.assertEqual(order.production_order_unique_id, "01|010004|10796502001")
        self.assertEqual(order.item_code, "IGN001000015")
        self.assertEqual(int(order.quantity), 22)
        self.assertEqual(len(order.activities), 9)
        self.assertEqual(len(order.materials), 1)
        self.assertEqual(order.activities[1].activity_id, "145026")
        self.assertEqual(order.materials[0].material_code, "5004000039")

    def test_xml_real_ok_preserva_op_alfanumerica_como_string(self):
        message = self.parser.parse(OK.read_bytes())
        order = message.production_order
        self.assertEqual(message.metadata.uuid, "1")
        self.assertEqual(order.number, "1079689C001")
        self.assertIsInstance(order.number, str)
        self.assertEqual(order.production_order_unique_id, "01|010004|1079689C001")
        self.assertEqual(order.item_code, "IPCX04014054P")
        self.assertEqual(int(order.quantity), 2)
        self.assertEqual(len(order.activities), 4)
        self.assertEqual(len(order.materials), 1)

    def test_uuid_repetido_nao_define_idempotencia(self):
        first = PEND.read_bytes()
        second = OK.read_bytes()
        self.assertEqual(self.parser.parse(first).metadata.uuid, self.parser.parse(second).metadata.uuid)
        self.assertNotEqual(hashlib.sha256(first).hexdigest(), hashlib.sha256(second).hexdigest())

    def test_xml_invalido_dtd_e_transaction_nao_suportada_sao_recusados(self):
        with self.assertRaises(TotvsXmlParseError):
            self.parser.parse("<TOTVSMessage>")
        with self.assertRaises(TotvsXmlSecurityError):
            self.parser.parse(
                "<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><TOTVSMessage>&e;</TOTVSMessage>"
            )
        unsupported = OK.read_text(encoding="utf-8").replace(
            "<Transaction>ProductionOrder</Transaction>",
            "<Transaction>Inventory</Transaction>",
            1,
        )
        with self.assertRaises(TotvsUnsupportedMessageError):
            self.parser.parse(unsupported)

    def test_identificadores_corporativos_divergentes_sao_erro(self):
        conflict = OK.read_text(encoding="utf-8").replace(
            ">01|010004|1079689C001</key>",
            ">01|010004|OUTRA</key>",
            1,
        )
        with self.assertRaises(TotvsIdentityConflictError):
            self.parser.parse(conflict)

    def test_mapper_nao_inventa_setor_e_aplica_alias_laser_oficial_exato(self):
        pending = self.parser.parse(PEND.read_bytes())
        ok = self.parser.parse(OK.read_bytes())
        conservative = TotvsProductionOrderMapper().map(pending)
        self.assertEqual(conservative.activities_parsed, 9)
        # O roteiro real repete o posto PINT.L (operações 40 e 60), com JATO no
        # meio (operação 50): são duas etapas de sequência diferentes, não uma
        # duplicata a colapsar — deduplicar faria o operador perder um passo
        # real de pintura (decisão de negócio confirmada em 2026-09-14).
        self.assertEqual(
            [
                (item.tipo_setor, item.codigo_recurso)
                for item in conservative.operations
                if not item.marco_terminal and not item.inspecao_qualidade
            ],
            [
                ("Corte", "LASER1"),
                ("Dobra", "DOBRA1"),
                ("Pintura", "PINT.L"),
                ("Pintura", "JATO"),
                ("Pintura", "PINT.L"),
            ],
        )
        self.assertFalse(any("MachineCode=LASER;" in warning for warning in conservative.warnings))
        explicit = TotvsProductionOrderMapper(
            TotvsResourceResolver(resource_aliases={"LASER": "LASER1"})
        )
        # As contagens consideram apenas as operações apontáveis; marco terminal
        # e inspeção da Qualidade são projetados à parte e nunca viram posto.
        def _apontaveis(mapping):
            return [
                op for op in mapping.operations
                if not op.marco_terminal and not op.inspecao_qualidade
            ]

        self.assertEqual(len(_apontaveis(explicit.map(pending))), 5)
        self.assertEqual(len(_apontaveis(explicit.map(ok))), 1)

    def test_op_real_classifica_cada_atividade_sem_inventar_semantica(self):
        result = TotvsProductionOrderMapper().map(self.parser.parse(REAL_OP.read_bytes()))
        self.assertEqual(
            [
                (
                    item.numero_operacao,
                    item.descricao_operacao,
                    item.tipo_setor,
                    item.codigo_recurso,
                    item.totvs_activity_id,
                )
                for item in result.operations
            ],
            [
                ("10", "CORTE", "Corte", "PLASMA", "108761"),
                ("20", "USINAGEM", "Usinagem", "CNC-01", "160893"),
                # A operação de inspeção é preservada com os metadados reais do
                # TOTVS e sem setor do Gestor: ela existe para a aba Qualidade e
                # para o outbound canônico, nunca como etapa de bancada.
                ("30", "INSPECAO", None, "INSPEC", "108763"),
                # O marco terminal é preservado com os metadados reais do TOTVS,
                # sem setor do Gestor: ele existe para o outbound, não para a
                # Tela do Operador.
                ("99", "FINALIZADA", None, "ALMOX4", "128285"),
            ],
        )
        inspecao = next(
            item for item in result.operations if item.inspecao_qualidade
        )
        self.assertEqual(inspecao.numero_operacao, "30")
        self.assertFalse(inspecao.marco_terminal)
        self.assertEqual(result.activities_parsed, 5)
        self.assertEqual(len(result.activity_treatments), 5)
        classifications = {
            item.activity_code: item.classification
            for item in result.activity_treatments
        }
        self.assertEqual(
            classifications,
            {
                "01": TotvsActivityClassification.AUTOMATIC_SATISFIED,
                "10": TotvsActivityClassification.POINTABLE_CONFIRMED,
                "20": TotvsActivityClassification.POINTABLE_CONFIRMED,
                "30": TotvsActivityClassification.QUALITY_INSPECTION,
                "99": TotvsActivityClassification.TERMINAL_CONFIRMED,
            },
        )
        self.assertFalse(
            any(
                item.classification
                == TotvsActivityClassification.NON_POINTABLE_CONFIRMED
                for item in result.activity_treatments
            )
        )
        self.assertEqual(len(result.warnings), 3)
        for activity_id, activity_code, machine_code, classification in (
            (
                "108760",
                "01",
                "PCP",
                TotvsActivityClassification.AUTOMATIC_SATISFIED,
            ),
            (
                "108763",
                "30",
                "INSPEC",
                TotvsActivityClassification.QUALITY_INSPECTION,
            ),
            (
                "128285",
                "99",
                "ALMOX4",
                TotvsActivityClassification.TERMINAL_CONFIRMED,
            ),
        ):
            warning = next(item for item in result.warnings if activity_id in item)
            self.assertIn(classification.value, warning)
            self.assertIn(f"ActivityCode={activity_code}", warning)
            self.assertIn(f"MachineCode={machine_code}", warning)
            self.assertIn("XML/inbox", warning)

    def test_etapas_especiais_nao_sao_liberadas_como_operacao_manual(self):
        result = TotvsProductionOrderMapper().map(
            self.parser.parse(REAL_OP.read_bytes())
        )
        by_code = {
            item.activity_code: item for item in result.activity_treatments
        }
        self.assertEqual(
            {
                operation.numero_operacao
                for operation in result.operations
                if not operation.marco_terminal
                and not operation.inspecao_qualidade
            },
            {"10", "20"},
        )
        self.assertEqual(
            {
                operation.numero_operacao
                for operation in result.operations
                if operation.inspecao_qualidade
            },
            {"30"},
        )
        self.assertEqual(
            {
                operation.numero_operacao
                for operation in result.operations
                if operation.marco_terminal
            },
            {"99"},
        )
        self.assertEqual(
            by_code["01"].classification,
            TotvsActivityClassification.AUTOMATIC_SATISFIED,
        )
        self.assertIn("cria apontamento fictício", by_code["01"].reason)
        self.assertEqual(
            by_code["30"].classification,
            TotvsActivityClassification.QUALITY_INSPECTION,
        )
        # A etapa é da aba Qualidade e continua fora do roteiro do posto.
        self.assertIn("aba Qualidade", by_code["30"].reason)
        self.assertIsNone(by_code["30"].sector)
        self.assertEqual(
            by_code["99"].classification,
            TotvsActivityClassification.TERMINAL_CONFIRMED,
        )
        self.assertIn("não finaliza", by_code["99"].reason)

    def test_marco_terminal_preservado_com_metadados_reais_e_nao_apontavel(self):
        """O marco terminal existe para o outbound, nunca como posto de operador."""

        result = TotvsProductionOrderMapper().map(
            self.parser.parse(REAL_OP.read_bytes())
        )
        terminais = [item for item in result.operations if item.marco_terminal]
        self.assertEqual(len(terminais), 1)
        terminal = terminais[0]
        # Metadados exatamente como o TOTVS enviou; nada é inventado.
        self.assertEqual(terminal.numero_operacao, "99")
        self.assertEqual(terminal.codigo_recurso, "ALMOX4")
        self.assertEqual(terminal.totvs_machine_code, "ALMOX4")
        self.assertEqual(terminal.totvs_activity_id, "128285")
        self.assertEqual(terminal.descricao_operacao, "FINALIZADA")
        # Sem setor do Gestor: não existe posto ALMOX4 e não será criado um.
        self.assertIsNone(terminal.tipo_setor)
        # Continua classificado como etapa terminal, não como operação manual.
        by_code = {item.activity_code: item for item in result.activity_treatments}
        self.assertEqual(
            by_code["99"].classification,
            TotvsActivityClassification.TERMINAL_CONFIRMED,
        )
        self.assertIsNone(by_code["99"].sector)
        self.assertIsNone(by_code["99"].resource_code)

    def test_default_branch_id_preenche_filial_ausente_no_cabecalho_e_operacoes(self):
        """Piloto roda em filial única; BranchId ausente vira a filial configurada."""

        sem_filial = REAL_OP.read_text(encoding="utf-8").replace(
            "<BranchId>010004</BranchId>", "<BranchId></BranchId>", 1
        )
        message = self.parser.parse(sem_filial.encode("utf-8"))
        self.assertIsNone(message.metadata.branch_id)

        result = TotvsProductionOrderMapper(default_branch_id="4").map(message)
        self.assertEqual(result.order.filial, "4")
        self.assertEqual(result.order.totvs_branch_id, "4")
        self.assertTrue(result.operations)
        self.assertTrue(all(item.filial == "4" for item in result.operations))

    def test_default_branch_id_nao_sobrescreve_filial_real_enviada_pelo_totvs(self):
        result = TotvsProductionOrderMapper(default_branch_id="4").map(
            self.parser.parse(REAL_OP.read_bytes())
        )
        self.assertEqual(result.order.filial, "010004")

    def test_marco_terminal_sem_activity_code_ou_recurso_nao_e_projetado(self):
        """Sem os metadados reais o marco terminal simplesmente não existe."""

        payload = REAL_OP.read_text(encoding="utf-8").replace(
            "<MachineCode>ALMOX4</MachineCode>", "<MachineCode></MachineCode>", 1
        )
        result = TotvsProductionOrderMapper().map(
            self.parser.parse(payload.encode("utf-8"))
        )
        self.assertEqual(
            [item for item in result.operations if item.marco_terminal], []
        )
        # Sem MachineCode a assinatura industrial deixa de bater e a atividade
        # cai em decisão pendente, preservada no XML/inbox — nunca projetada.
        by_code = {item.activity_code: item for item in result.activity_treatments}
        self.assertEqual(
            by_code["99"].classification,
            TotvsActivityClassification.PENDING_DECISION,
        )
        self.assertNotIn("99", {item.numero_operacao for item in result.operations})

    def test_ingestao_nao_finaliza_a_op_nem_gera_apontamento(self):
        """Receber o roteiro não conclui nada: o marco terminal é só metadado."""

        result = TotvsProductionOrderMapper().map(
            self.parser.parse(REAL_OP.read_bytes())
        )
        by_code = {item.activity_code: item for item in result.activity_treatments}
        self.assertIn("não finaliza a OP durante a ingestão", by_code["99"].reason)
        # A ingestão não produz quantidade nem estado de execução.
        for operation in result.operations:
            self.assertFalse(hasattr(operation, "quantidade_boa"))
        self.assertEqual(result.order.codigo_op, "A9716901001")

    def test_alias_laser_nao_autoriza_aproximacoes(self):
        payload = PEND.read_text(encoding="utf-8").replace(
            "<MachineCode>LASER</MachineCode>",
            "<MachineCode>LASER-X</MachineCode>",
            1,
        )
        result = TotvsProductionOrderMapper(
            TotvsResourceResolver(known_resource_codes={"LASER-X"})
        ).map(self.parser.parse(payload))
        self.assertFalse(
            any(operation.numero_operacao == "10" for operation in result.operations)
        )
        treatment = next(
            item for item in result.activity_treatments if item.activity_code == "10"
        )
        self.assertEqual(
            treatment.classification,
            TotvsActivityClassification.PENDING_DECISION,
        )
        self.assertIsNone(treatment.resource_code)

    def test_recursos_canonicos_de_pintura_e_inspecao_pintura_sao_apontaveis(self):
        result = TotvsProductionOrderMapper(
            TotvsResourceResolver(
                known_resource_sectors={
                    "PINT.L": "Pintura",
                    "INSPE2": "Pintura",
                    "PREP": "Pintura",
                }
            )
        ).map(self.parser.parse(PEND.read_bytes()))
        painting = [
            (
                operation.numero_operacao,
                operation.descricao_operacao,
                operation.codigo_recurso,
            )
            for operation in result.operations
            if operation.tipo_setor == "Pintura"
        ]
        self.assertEqual(
            painting,
            [
                ("40", "PREPARACAO", "PINT.L"),
                ("50", "JATEAMENTO", "JATO"),
                ("60", "PINTURA", "PINT.L"),
                ("70", "INSPECAO PINTURA", "INSPE2"),
            ],
        )
        jateamento = next(
            item for item in result.activity_treatments if item.activity_code == "50"
        )
        self.assertEqual(
            jateamento.classification,
            TotvsActivityClassification.POINTABLE_CONFIRMED,
        )
        self.assertEqual((jateamento.sector, jateamento.resource_code), ("Pintura", "JATO"))

        parsed = self.parser.parse(PEND.read_bytes())
        base_activity = parsed.production_order.activities[1]
        activities = tuple(
            replace(
                base_activity,
                activity_id=f"PINT-{index}",
                activity_code=str(100 + index),
                activity_description=f"ETAPA PINTURA {index}",
                work_center_code="PINT-WC",
                work_center_description="PINTURA",
                machine_code=resource,
            )
            for index, resource in enumerate(AUDITED_PAINTING_RESOURCES, start=1)
        )
        all_painting = TotvsProductionOrderMapper(
            TotvsResourceResolver(
                known_resource_sectors={
                    resource: "Pintura" for resource in AUDITED_PAINTING_RESOURCES
                }
            )
        ).map(
            replace(
                parsed,
                production_order=replace(
                    parsed.production_order,
                    activities=activities,
                ),
            )
        )
        self.assertEqual(
            [operation.codigo_recurso for operation in all_painting.operations],
            list(AUDITED_PAINTING_RESOURCES),
        )
        self.assertTrue(
            all(
                operation.tipo_setor == "Pintura"
                for operation in all_painting.operations
            )
        )

    def test_recurso_canonico_de_solda_e_apontavel_sem_alias_implicito(self):
        parsed = self.parser.parse(PEND.read_bytes())
        base_activity = parsed.production_order.activities[1]
        welding_activities = tuple(
            replace(
                base_activity,
                activity_id=f"SOLD-{index}",
                activity_code=str(200 + index),
                activity_description=f"ETAPA SOLDA {index}",
                work_center_code="SOLD-WC",
                work_center_description="SOLDAGEM",
                machine_code=resource,
            )
            for index, resource in enumerate(AUDITED_WELDING_RESOURCES, start=1)
        )
        message = replace(
            parsed,
            production_order=replace(
                parsed.production_order,
                activities=welding_activities,
            ),
        )
        result = TotvsProductionOrderMapper(
            TotvsResourceResolver(
                known_resource_sectors={
                    resource: "Solda Aço" for resource in AUDITED_WELDING_RESOURCES
                }
            )
        ).map(message)
        self.assertEqual(
            [operation.codigo_recurso for operation in result.operations],
            list(AUDITED_WELDING_RESOURCES),
        )
        self.assertTrue(
            all(operation.tipo_setor == "Solda Aço" for operation in result.operations)
        )

        welding_activity = welding_activities[0]
        unknown = replace(
            message,
            production_order=replace(
                message.production_order,
                activities=(replace(welding_activity, machine_code="SOLD-CANON-X"),),
            ),
        )
        unknown_result = TotvsProductionOrderMapper(
            TotvsResourceResolver(
                known_resource_sectors={
                    resource: "Solda Aço" for resource in AUDITED_WELDING_RESOURCES
                },
                known_resource_codes={"SOLD-CANON-X"},
            )
        ).map(unknown)
        self.assertEqual(unknown_result.operations, ())

    def _montagem_message(self, machine_code):
        parsed = self.parser.parse(PEND.read_bytes())
        base_activity = parsed.production_order.activities[1]
        assembly_activity = replace(
            base_activity,
            activity_id="MONT-1",
            activity_code="80",
            activity_description="MONTAGEM",
            work_center_code="MONT-WC",
            work_center_description="MONTAGEM",
            machine_code=machine_code,
        )
        return replace(
            parsed,
            production_order=replace(
                parsed.production_order,
                activities=(assembly_activity,),
            ),
        )

    def test_montagem_projeta_somente_por_pertencimento_cadastral(self):
        """Etapa 3: Montagem segue a mesma regra funcional de Pintura e Solda.

        O gatilho é exclusivamente ``tipo_setor`` do cadastro oficial. Sem
        recurso classificado como Montagem, a etapa permanece pendente e
        auditável, sem alias, prefixo ou recurso inventado.
        """

        message = self._montagem_message("MONT-01")

        sem_cadastro = TotvsProductionOrderMapper(TotvsResourceResolver()).map(message)
        self.assertEqual(sem_cadastro.operations, ())
        self.assertEqual(
            sem_cadastro.activity_treatments[0].classification,
            TotvsActivityClassification.PENDING_DECISION,
        )

        com_cadastro = TotvsProductionOrderMapper(
            TotvsResourceResolver(
                known_resource_sectors={"MONT-01": "Montagem"}
            )
        ).map(message)
        self.assertEqual(
            [
                (item.numero_operacao, item.tipo_setor, item.codigo_recurso)
                for item in com_cadastro.operations
            ],
            [("80", "Montagem", "MONT-01")],
        )
        self.assertEqual(
            com_cadastro.activity_treatments[0].classification,
            TotvsActivityClassification.POINTABLE_CONFIRMED,
        )

    def test_montagem_nao_promove_recurso_por_nome_semelhante(self):
        """Nome do catálogo continua sem autoridade sobre o setor."""

        resolver = TotvsResourceResolver(
            known_resource_codes={"MPRT1", "MONTAGEM PM05", "SOLDA4"},
        )
        for machine_code in ("MPRT1", "MONTAGEM PM05"):
            with self.subTest(machine_code=machine_code):
                result = TotvsProductionOrderMapper(resolver).map(
                    self._montagem_message(machine_code)
                )
                self.assertEqual(result.operations, ())
                self.assertEqual(
                    result.activity_treatments[0].classification,
                    TotvsActivityClassification.PENDING_DECISION,
                )

        # Recurso cadastrado em outro setor nunca é promovido para Montagem.
        outro_setor = TotvsProductionOrderMapper(
            TotvsResourceResolver(known_resource_sectors={"SOLDA4": "Solda Aço"})
        ).map(self._montagem_message("SOLDA4"))
        self.assertEqual(outro_setor.operations, ())
        self.assertEqual(
            outro_setor.activity_treatments[0].classification,
            TotvsActivityClassification.PENDING_DECISION,
        )

    def test_recurso_desconhecido_nao_sofre_prefixo_ou_fuzzy_matching(self):
        unknown = REAL_OP.read_text(encoding="utf-8").replace(
            "<MachineCode>PLASMA</MachineCode>",
            "<MachineCode>PLASMA-TERRA</MachineCode>",
            1,
        )
        result = TotvsProductionOrderMapper(
            TotvsResourceResolver(known_resource_codes={"PLASMA-TERRA"})
        ).map(self.parser.parse(unknown))
        self.assertEqual(
            [
            (item.numero_operacao, item.codigo_recurso)
            for item in result.operations
            if not item.marco_terminal and not item.inspecao_qualidade
        ],
            [("20", "CNC-01")],
        )
        treatment = next(
            item for item in result.activity_treatments if item.activity_code == "10"
        )
        self.assertEqual(
            treatment.classification,
            TotvsActivityClassification.PENDING_DECISION,
        )
        self.assertEqual(treatment.sector, "Corte")
        self.assertIsNone(treatment.resource_code)
        self.assertIn("PLASMA-TERRA", treatment.reason)

        approved_alias = TotvsProductionOrderMapper(
            TotvsResourceResolver(
                resource_aliases={"PLASMA-TERRA": "PLASMA"},
                known_resource_codes={"PLASMA-TERRA"},
            )
        ).map(self.parser.parse(unknown))
        self.assertEqual(
            [
                (item.numero_operacao, item.codigo_recurso)
                for item in approved_alias.operations
                if not item.marco_terminal and not item.inspecao_qualidade
            ],
            [("10", "PLASMA"), ("20", "CNC-01")],
        )

    def test_servico_implementa_porta_push_e_mantem_escrita_no_totvs_desabilitada(self):
        service = TotvsProductionOrderIngestionService(object(), enabled=False)
        self.assertIsInstance(service, CorporateMessageIngestion)
        self.assertFalse(service.status().execution_write_enabled)


class _StubTotvsService:
    def __init__(self, error=None):
        self.payloads = []
        self.error = error

    def ingest(self, payload):
        self.payloads.append(payload)
        if self.error:
            raise self.error
        return object()

    def handle_message(self, payload):
        return TotvsMessageOutcome(
            transaction="ProductionOrder",
            ingestion=self.ingest(payload),
        )


class _FakeTotvsRepository:
    """Inbox em memória; qualquer escrita de negócio fica visível ao teste."""

    def __init__(self):
        self.messages = []
        self.production_order_writes = []

    def _row(self, message_id):
        return self.messages[int(message_id) - 1]

    def registrar_mensagem_totvs(self, *, payload_hash, payload_raw):
        for row in self.messages:
            if row["payload_hash"] == payload_hash:
                return {**row, "created": False}
        row = {
            "id": len(self.messages) + 1,
            "payload_hash": payload_hash,
            "payload_raw": payload_raw,
            "transaction": None,
            "entity": None,
            "event": None,
            "external_id": None,
            "company_id": None,
            "branch_id": None,
            "source_application": None,
            "generated_on": None,
            "status": "received",
            "result_action": None,
            "error_code": None,
            "error_message": None,
            "warnings": [],
            "activities_parsed": 0,
            "activities_projected": 0,
        }
        self.messages.append(row)
        return {**row, "created": True}

    def registrar_diagnostico_totvs(self, *, message_id, message):
        row = self._row(message_id)
        metadata = message.metadata
        row.update(
            transaction=metadata.transaction,
            company_id=metadata.company_id,
            branch_id=metadata.branch_id,
            source_application=metadata.source_application,
            generated_on=metadata.generated_on,
            status="ignored",
            result_action="diagnostic",
        )
        return dict(row)

    def aplicar_production_order_totvs(self, *, message_id, payload_hash, message, mapping):
        self.production_order_writes.append(message.external_id)
        row = self._row(message_id)
        row.update(
            transaction=message.metadata.transaction,
            entity=message.event.entity,
            event=message.event.event,
            external_id=message.external_id,
            status="processed",
            result_action="inserted",
            activities_parsed=mapping.activities_parsed,
            activities_projected=len(mapping.operations),
            warnings=list(mapping.warnings),
        )
        return dict(row)

    def marcar_mensagem_totvs_erro(self, message_id, *, error_code, error_message, message=None):
        self._row(message_id).update(
            status="error",
            result_action="error",
            error_code=error_code,
            error_message=error_message,
        )

    def listar_codigos_recursos_totvs(self):
        return ()

    def listar_setores_recursos_totvs(self):
        return ()


def _settings(**overrides):
    values = {
        "environment": "test",
        "session_secret": "test-secret-that-is-long-enough-for-session-signatures-123456",
        "allowed_hosts": ("testserver",),
        "allowed_origins": ("http://testserver",),
        "session_ttl_seconds": 3600,
        "totvs_enabled": True,
        "totvs_soap_enabled": True,
        "totvs_soap_allowed_source_cidrs": ("10.10.1.0/24",),
        "totvs_soap_success_result": "OK",
    }
    values.update(overrides)
    return WebSettings(**values)


def _soap_envelope(payload: str, *, operation: str = "receiveMessage") -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f'<soap:Body><{operation} xmlns="http://tempuri.org/">'
        f"<pXmlDocument>{escape(payload)}</pXmlDocument>"
        f"</{operation}></soap:Body></soap:Envelope>"
    )


class TotvsSoapContractTests(unittest.TestCase):
    def _client(self, *, settings=None, service=None, source_ip="10.10.1.25"):
        database = FakeDatabase()
        app = create_app(settings=settings or _settings(), database_factory=lambda: database)
        stub = service or _StubTotvsService()
        app.state.totvs_service_factory = lambda _database: stub
        return TestClient(app, client=(source_ip, 50_000)), stub

    def test_wsdl_e_receive_message_usam_contrato_confirmado(self):
        client, service = self._client()
        with client:
            wsdl = client.get("/PcfIntegService?wsdl")
            self.assertEqual(wsdl.status_code, 200)
            self.assertIn("receiveMessageResult", wsdl.text)
            self.assertIn(SOAP_ACTION, wsdl.text)
            payload = OK.read_text(encoding="utf-8")
            response = client.post(
                "/PcfIntegService",
                content=_soap_envelope(payload).encode("utf-8"),
                headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{SOAP_ACTION}"'},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("<receiveMessageResult>OK</receiveMessageResult>", response.text)
        self.assertEqual(service.payloads, [payload])

    def test_receptor_desabilitado_action_operacao_e_payload_invalidos_falham(self):
        disabled, _ = self._client(
            settings=_settings(totvs_enabled=False, totvs_soap_enabled=False, totvs_soap_success_result="")
        )
        with disabled:
            self.assertEqual(disabled.get("/PcfIntegService?wsdl").status_code, 503)

        client, service = self._client()
        payload = OK.read_text(encoding="utf-8")
        with client:
            wrong_action = client.post(
                "/PcfIntegService",
                content=_soap_envelope(payload),
                headers={"SOAPAction": "wrong"},
            )
            wrong_operation = client.post(
                "/PcfIntegService",
                content=_soap_envelope(payload, operation="other"),
                headers={"SOAPAction": SOAP_ACTION},
            )
            missing = client.post(
                "/PcfIntegService",
                content=(
                    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
                    '<soap:Body><receiveMessage xmlns="http://tempuri.org/"/></soap:Body></soap:Envelope>'
                ),
                headers={"SOAPAction": SOAP_ACTION},
            )
        self.assertEqual(wrong_action.status_code, 500)
        self.assertEqual(wrong_operation.status_code, 500)
        self.assertEqual(missing.status_code, 500)
        self.assertFalse(service.payloads)

        limited, limited_service = self._client(
            settings=_settings(totvs_max_xml_bytes=1024)
        )
        with limited:
            too_large = limited.post(
                "/PcfIntegService",
                content=b"x" * (1024 * 5 + 16_384 + 1),
                headers={"SOAPAction": SOAP_ACTION},
            )
        self.assertEqual(too_large.status_code, 500)
        self.assertIn("soap_payload_too_large", too_large.text)
        self.assertFalse(limited_service.payloads)

    def test_receptor_nao_responde_pelo_hostname_publicado(self):
        """O receptor não é autenticado — é o contrato do EAI do Protheus, que
        fala pela rede interna. Enquanto o Gestor estiver publicado por um
        hostname externo, o mesmo endpoint gravaria OP para qualquer um que
        descobrisse a URL. A porta do ERP existe só no caminho interno."""

        publico = "dod-road-matches-clusters.trycloudflare.com"
        interno = "10.10.1.248"
        client, service = self._client(
            settings=_settings(
                allowed_hosts=("testserver", interno, publico),
                public_host=publico,
            )
        )
        payload = OK.read_text(encoding="utf-8")
        cabecalhos = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": f'"{SOAP_ACTION}"'}
        with client:
            pelo_tunel = client.post(
                "/PcfIntegService",
                content=_soap_envelope(payload).encode("utf-8"),
                headers={**cabecalhos, "Host": publico},
            )
            wsdl_pelo_tunel = client.get("/PcfIntegService", headers={"Host": publico})
            pela_rede_interna = client.post(
                "/PcfIntegService",
                content=_soap_envelope(payload).encode("utf-8"),
                headers={**cabecalhos, "Host": interno},
            )

        self.assertEqual(pelo_tunel.status_code, 403)
        self.assertIn("totvs_soap_internal_only", pelo_tunel.text)
        self.assertEqual(wsdl_pelo_tunel.status_code, 403)
        # Nada do túnel chega ao serviço de ingestão.
        self.assertEqual(service.payloads, [payload])
        self.assertEqual(pela_rede_interna.status_code, 200, pela_rede_interna.text)

    def test_sem_hostname_publicado_a_rede_interna_nao_muda(self):
        """``public_host`` no padrão da fábrica não bloqueia nada."""

        client, service = self._client(
            settings=_settings(
                allowed_hosts=("testserver", "gestor-peca"), public_host="gestor-peca"
            )
        )
        payload = OK.read_text(encoding="utf-8")
        with client:
            resposta = client.post(
                "/PcfIntegService",
                content=_soap_envelope(payload).encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": f'"{SOAP_ACTION}"',
                    "Host": "gestor-peca",
                },
            )
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(service.payloads, [payload])

    def test_allowlist_bloqueia_origem_desconhecida_sem_confiar_em_headers(self):
        client, service = self._client(source_ip="203.0.113.45")
        payload = OK.read_text(encoding="utf-8")
        headers = {
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{SOAP_ACTION}"',
            "X-Forwarded-For": "10.10.1.25",
        }
        with client:
            wsdl = client.get(
                "/PcfIntegService?wsdl",
                headers={"X-Forwarded-For": "10.10.1.25"},
            )
            response = client.post(
                "/PcfIntegService",
                content=_soap_envelope(payload).encode("utf-8"),
                headers=headers,
            )

        self.assertEqual(wsdl.status_code, 403)
        self.assertIn("totvs_soap_source_forbidden", wsdl.text)
        self.assertEqual(response.status_code, 403)
        self.assertIn("totvs_soap_source_forbidden", response.text)
        self.assertFalse(service.payloads)

    def test_excecao_controlada_nao_vaza_payload(self):
        service = _StubTotvsService(
            TotvsIntegrationError("Falha controlada.", code="processing_error")
        )
        client, _ = self._client(service=service)
        payload = OK.read_text(encoding="utf-8")
        with client:
            response = client.post(
                "/PcfIntegService",
                content=_soap_envelope(payload),
                headers={"SOAPAction": SOAP_ACTION},
            )
        self.assertEqual(response.status_code, 500)
        self.assertIn("processing_error", response.text)
        self.assertNotIn("1079689C001", response.text)

    def test_configuracao_nao_inventa_ack(self):
        base = {
            "GESTOR_WEB_ENV": "test",
            "GESTOR_WEB_SESSION_SECRET": "test-secret-that-is-long-enough-for-session-signatures-123456",
            "GESTOR_TOTVS_ENABLED": "true",
            "GESTOR_TOTVS_SOAP_ENABLED": "true",
        }
        with self.assertRaisesRegex(RuntimeError, "GESTOR_TOTVS_SOAP_SUCCESS_RESULT"):
            WebSettings.from_env(base)
        without_source = WebSettings.from_env(
            {**base, "GESTOR_TOTVS_SOAP_SUCCESS_RESULT": "ACK-EXTERNO"}
        )
        self.assertEqual(without_source.totvs_soap_allowed_source_cidrs, ())
        with self.assertRaisesRegex(RuntimeError, "IP/CIDR inválido"):
            WebSettings.from_env(
                {
                    **base,
                    "GESTOR_TOTVS_SOAP_SUCCESS_RESULT": "ACK-EXTERNO",
                    "GESTOR_TOTVS_SOAP_ALLOWED_SOURCE_CIDRS": "rede-totvs",
                }
            )
        configured = WebSettings.from_env(
            {
                **base,
                "GESTOR_TOTVS_SOAP_SUCCESS_RESULT": "ACK-EXTERNO",
                "GESTOR_TOTVS_SOAP_ALLOWED_SOURCE_CIDRS": "10.10.1.25, 10.10.2.0/24",
                "GESTOR_TOTVS_RESOURCE_MAP_JSON": '{"LASER":"LASER1"}',
            }
        )
        self.assertTrue(configured.totvs_enabled)
        self.assertEqual(
            configured.totvs_soap_allowed_source_cidrs,
            ("10.10.1.25/32", "10.10.2.0/24"),
        )
        self.assertEqual(configured.totvs_resource_map, {"LASER": "LASER1"})

    def test_allowlist_ausente_mantem_aplicacao_disponivel_mas_fecha_o_receptor(self):
        client, service = self._client(settings=_settings(totvs_soap_allowed_source_cidrs=()))
        payload = OK.read_text(encoding="utf-8")
        with client:
            wsdl = client.get("/PcfIntegService?wsdl")
            response = client.post(
                "/PcfIntegService",
                content=_soap_envelope(payload).encode("utf-8"),
                headers={"SOAPAction": SOAP_ACTION},
            )
        self.assertEqual(wsdl.status_code, 503)
        self.assertIn("totvs_soap_source_not_configured", wsdl.text)
        self.assertEqual(response.status_code, 503)
        self.assertIn("totvs_soap_source_not_configured", response.text)
        self.assertFalse(service.payloads)


def _receive_message_result(body: str) -> str:
    root = ET.fromstring(body)
    for node in root.iter():
        if str(node.tag).rsplit("}", 1)[-1] == "receiveMessageResult":
            return str(node.text or "")
    raise AssertionError("receiveMessageResult ausente na resposta SOAP.")


class TotvsResponseContractTests(unittest.TestCase):
    """Contrato comprovado em pcpxfun.prx::PCPWebsPPI e WSPCP.prw::getReturn.

    O mesmo PCPWebsPPI atende PCPA109 (WhoIs) e PCPA111/MATA650
    (SC2/ProductionOrder): faz Parse do receiveMessageResult e exige
    /TOTVSMessage/ResponseMessage/ProcessingInformation/Status = OK.
    """

    def setUp(self):
        self.parser = TotvsMessageParser()
        self.repository = _FakeTotvsRepository()
        self.service = TotvsProductionOrderIngestionService(
            self.repository,
            enabled=True,
            mapper=TotvsProductionOrderMapper(
                TotvsResourceResolver(resource_aliases={"LASER": "LASER1"})
            ),
        )

    def _client(self):
        database = FakeDatabase()
        app = create_app(settings=_settings(), database_factory=lambda: database)
        app.state.totvs_service_factory = lambda _database: self.service
        return TestClient(app, client=("10.10.1.25", 50_000))

    def test_parser_le_whois_real_sem_extrair_dado_de_negocio(self):
        message = self.parser.parse_whois(WHOIS.read_bytes())
        self.assertEqual(self.parser.read_metadata(WHOIS.read_bytes()).transaction, "WhoIs")
        self.assertEqual(message.metadata.transaction, "WhoIs")
        self.assertEqual(message.metadata.message_type, "BusinessMessage")
        self.assertEqual(message.metadata.context_name, "PROTHEUS")
        self.assertEqual(message.metadata.source_application, "SIGAPCP")
        self.assertEqual(message.metadata.company_id, "01")
        self.assertEqual(message.metadata.branch_id, "010004")
        self.assertEqual(message.metadata.schema_location, "whois_1_000.xsd")
        self.assertEqual(message.product_name, "PCPA109")
        self.assertEqual(message.product_version, "12.1.2510")
        self.assertEqual(
            dict(message.identification)["PRODUCT_ENDPOINT"],
            "10.0.2.5:8100/WSPCP?WSDL",
        )
        self.assertFalse(hasattr(message, "production_order"))

    def test_resposta_whois_usa_identidade_propria_e_correlaciona_uuid(self):
        message = self.parser.parse_whois(WHOIS.read_bytes())
        identity = TotvsGestorIdentity(
            source_application="GESTOR_TESTE",
            product_name="GESTOR_TESTE",
            product_version="9.9",
            context_name="GESTOR_TESTE",
        )
        xml = build_response_message(
            message.metadata,
            identity=identity,
            now=datetime(2026, 8, 27, 10, 21, 20),
        )
        root = ET.fromstring(xml)
        information = root.find("MessageInformation")
        self.assertEqual(information.get("version"), "1.000")
        self.assertEqual(information.findtext("SourceApplication"), "GESTOR_TESTE")
        self.assertEqual(information.find("Product").get("name"), "GESTOR_TESTE")
        self.assertEqual(information.find("Product").get("version"), "9.9")
        self.assertEqual(information.findtext("ContextName"), "GESTOR_TESTE")
        self.assertEqual(information.findtext("CompanyId"), "01")
        self.assertEqual(information.findtext("BranchId"), "010004")
        self.assertEqual(information.findtext("GeneratedOn"), "2026-08-27T10:21:20")
        self.assertEqual(information.findtext("UUID"), "UUID")
        received = root.find("ResponseMessage/ReceivedMessage")
        self.assertEqual(received.findtext("SentBy"), "PCPA109")
        self.assertEqual(received.findtext("UUID"), "UUID")
        self.assertNotIn("PCFactory", xml)
        self.assertNotIn("WSPCP", xml)
        self.assertNotIn("SIGAPCP", xml)

    def test_identidade_vem_da_configuracao_com_default_canonico(self):
        default = build_gestor_identity(_settings())
        self.assertEqual(default.source_application, "GESTOR_PECAS")
        self.assertEqual(default.product_name, "GESTOR_PECAS")
        self.assertEqual(default.context_name, "GESTOR_PECAS")
        configured = build_gestor_identity(
            WebSettings.from_env(
                {
                    "GESTOR_WEB_ENV": "test",
                    "GESTOR_WEB_SESSION_SECRET": "test-secret-that-is-long-enough-for-session-signatures-123456",
                    "GESTOR_TOTVS_IDENTITY_SOURCE_APPLICATION": "GESTOR_MES",
                    "GESTOR_TOTVS_IDENTITY_PRODUCT_VERSION": "2026.08",
                }
            )
        )
        self.assertEqual(configured.source_application, "GESTOR_MES")
        self.assertEqual(configured.product_version, "2026.08")
        self.assertEqual(configured.product_name, "GESTOR_PECAS")

    def test_whois_soap_responde_http_200_com_status_ok_e_sem_efeito_de_negocio(self):
        client = self._client()
        payload = WHOIS.read_text(encoding="utf-8")
        with client:
            response = client.post(
                "/PcfIntegService",
                content=_soap_envelope(payload).encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": f'"{SOAP_ACTION}"',
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        result = _receive_message_result(response.text)
        root = ET.fromstring(result)
        self.assertEqual(root.tag, "TOTVSMessage")
        self.assertEqual(root.findtext("MessageInformation/Type"), "Response")
        self.assertEqual(root.findtext("MessageInformation/Transaction"), "WHOIS")
        self.assertIsNotNone(root.find("ResponseMessage"))
        self.assertEqual(
            root.findtext("ResponseMessage/ProcessingInformation/Status"), "OK"
        )
        self.assertEqual(
            root.findtext("ResponseMessage/ReceivedMessage/SentBy"), "PCPA109"
        )
        self.assertIsNone(root.find("ResponseMessage/ReturnContent"))
        self.assertEqual(self.repository.production_order_writes, [])
        inbox = self.repository.messages
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["transaction"], "WhoIs")
        self.assertEqual(inbox[0]["status"], "ignored")
        self.assertEqual(inbox[0]["result_action"], "diagnostic")
        self.assertIsNone(inbox[0]["external_id"])
        self.assertIsNone(inbox[0]["entity"])
        self.assertIsNone(inbox[0]["event"])
        self.assertEqual(inbox[0]["activities_projected"], 0)

    def test_whois_repetido_continua_respondendo_ok_sem_novo_efeito(self):
        payload = WHOIS.read_bytes()
        first = self.service.handle_message(payload)
        second = self.service.handle_message(payload)
        self.assertFalse(first.diagnostic.idempotent)
        self.assertTrue(second.diagnostic.idempotent)
        for outcome in (first, second):
            root = ET.fromstring(outcome.soap_result)
            self.assertEqual(
                root.findtext("ResponseMessage/ProcessingInformation/Status"), "OK"
            )
        self.assertEqual(len(self.repository.messages), 1)
        self.assertEqual(self.repository.production_order_writes, [])

    def test_production_order_responde_totvsmessage_e_mantem_o_fluxo_atual(self):
        client = self._client()
        payload = OK.read_text(encoding="utf-8")
        with client:
            response = client.post(
                "/PcfIntegService",
                content=_soap_envelope(payload).encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": f'"{SOAP_ACTION}"',
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        root = ET.fromstring(_receive_message_result(response.text))
        self.assertEqual(root.findtext("MessageInformation/Transaction"), "PRODUCTIONORDER")
        self.assertEqual(
            root.findtext("ResponseMessage/ProcessingInformation/Status"), "OK"
        )
        self.assertEqual(
            self.repository.production_order_writes, ["01|010004|1079689C001"]
        )
        self.assertEqual(self.repository.messages[0]["status"], "processed")

    def test_op_real_a9716901001_responde_no_formato_lido_pelo_pcpa111(self):
        client = self._client()
        payload = REAL_OP.read_text(encoding="utf-8")
        with client:
            response = client.post(
                "/PcfIntegService",
                content=_soap_envelope(payload).encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": f'"{SOAP_ACTION}"',
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        result = _receive_message_result(response.text)
        # PCPWebsPPI faz oTXML:Parse(cReturn) antes de qualquer XPath.
        root = ET.fromstring(result)
        self.assertEqual(root.tag, "TOTVSMessage")
        self.assertEqual(root.findtext("MessageInformation/Type"), "Response")
        self.assertEqual(root.findtext("MessageInformation/Transaction"), "PRODUCTIONORDER")
        self.assertEqual(root.findtext("MessageInformation/UUID"), "1")
        self.assertEqual(
            root.findtext("ResponseMessage/ProcessingInformation/Status"), "OK"
        )
        # getReturn: SentBy = Product/@name recebido (MATA650 nesta OP real).
        self.assertEqual(
            root.findtext("ResponseMessage/ReceivedMessage/SentBy"), "MATA650"
        )
        self.assertEqual(root.findtext("ResponseMessage/ReceivedMessage/UUID"), "1")
        self.assertIsNone(root.find("ResponseMessage/ProcessingInformation/ListOfMessages"))
        self.assertIsNone(root.find("ResponseMessage/ReturnContent"))
        self.assertEqual(
            self.repository.production_order_writes, ["01|010004|A9716901001"]
        )

    def test_erro_ao_aplicar_a_op_nao_devolve_status_ok(self):
        def explode(**_kwargs):
            raise TotvsIntegrationError("Falha ao aplicar.", code="processing_error")

        self.repository.aplicar_production_order_totvs = explode
        client = self._client()
        payload = REAL_OP.read_text(encoding="utf-8")
        with client:
            response = client.post(
                "/PcfIntegService",
                content=_soap_envelope(payload).encode("utf-8"),
                headers={
                    "Content-Type": "text/xml; charset=utf-8",
                    "SOAPAction": f'"{SOAP_ACTION}"',
                },
            )
        self.assertEqual(response.status_code, 500)
        self.assertIn("processing_error", response.text)
        self.assertNotIn("<Status>OK</Status>", response.text)
        self.assertNotIn("receiveMessageResult", response.text)
        self.assertEqual(self.repository.messages[0]["status"], "error")

    def test_resposta_de_sucesso_so_e_montada_depois_da_persistencia(self):
        ordem = []
        original = self.repository.aplicar_production_order_totvs

        def registrar(**kwargs):
            ordem.append("persistiu")
            return original(**kwargs)

        self.repository.aplicar_production_order_totvs = registrar
        outcome = self.service.handle_message(REAL_OP.read_bytes())
        ordem.append("respondeu")
        self.assertEqual(ordem, ["persistiu", "respondeu"])
        self.assertEqual(outcome.ingestion.action, "inserted")
        self.assertEqual(
            ET.fromstring(outcome.soap_result).findtext(
                "ResponseMessage/ProcessingInformation/Status"
            ),
            "OK",
        )

    def test_transaction_desconhecida_continua_recusada_na_inbox(self):
        unsupported = OK.read_text(encoding="utf-8").replace(
            "<Transaction>ProductionOrder</Transaction>",
            "<Transaction>Inventory</Transaction>",
            1,
        )
        with self.assertRaises(TotvsUnsupportedMessageError):
            self.service.handle_message(unsupported)
        self.assertEqual(self.repository.messages[0]["status"], "error")
        self.assertEqual(
            self.repository.messages[0]["error_code"], "unsupported_totvs_message"
        )
        self.assertEqual(self.repository.production_order_writes, [])

    def test_xml_malformado_segue_o_erro_atual_sem_desviar_para_whois(self):
        with self.assertRaises(TotvsXmlParseError):
            self.service.handle_message("<TOTVSMessage>")
        self.assertEqual(self.repository.messages[0]["status"], "error")
        self.assertEqual(self.repository.messages[0]["error_code"], "malformed_xml")


if __name__ == "__main__":
    unittest.main()
