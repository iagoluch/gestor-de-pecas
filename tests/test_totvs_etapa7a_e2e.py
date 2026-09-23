"""Regressão integrada da Etapa 7A em schema PostgreSQL isolado.

O ProductionOrder atravessa HTTP de verdade e todo o pipeline canônico. O ACK
final é controlado somente neste teste automatizado; portanto ele prova a
máquina de entrega/estado da outbox, não substitui um ACK de negócio do WSPCP.
"""

import os
import unittest

import httpx

from app.database.config import load_postgres_config
from backend.integrations.totvs_wspcp import TotvsWspcpClient, WspcpClientConfig
from scripts.homologar_totvs_e2e_etapa7a import run_homologation


ACK_OK = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
    "<SOAP-ENV:Body><RECEIVEMESSAGERESPONSE><RECEIVEMESSAGERESULT>"
    "&lt;TOTVSMessage&gt;&lt;ResponseMessage&gt;&lt;ProcessingInformation&gt;"
    "&lt;Status&gt;OK&lt;/Status&gt;&lt;/ProcessingInformation&gt;"
    "&lt;ReturnContent&gt;&lt;ListOfInternalId&gt;&lt;InternalId&gt;"
    "&lt;Name&gt;ID&lt;/Name&gt;&lt;Destination&gt;ETAPA7A-AUTO&lt;/Destination&gt;"
    "&lt;/InternalId&gt;&lt;/ListOfInternalId&gt;&lt;/ReturnContent&gt;"
    "&lt;/ResponseMessage&gt;&lt;/TOTVSMessage&gt;"
    "</RECEIVEMESSAGERESULT></RECEIVEMESSAGERESPONSE></SOAP-ENV:Body>"
    "</SOAP-ENV:Envelope>"
)


class _FastTransportFailure:
    def send_result(self, _message):
        raise OSError("transporte controladamente indisponível")


def _ack_gateway() -> TotvsWspcpClient:
    return TotvsWspcpClient(
        WspcpClientConfig(endpoint="https://wspcp-teste-controlado/WSPCP.apw"),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, text=ACK_OK)),
    )


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class TotvsEtapa7AE2ETests(unittest.TestCase):
    def test_pipeline_controlado_chega_a_sent_sem_atalho_de_dominio(self):
        evidence = run_homologation(
            load_postgres_config(testing=True),
            delivery_gateway=_ack_gateway(),
            delivery_kind="ack_controlado_automatizado",
            failure_gateway=_FastTransportFailure(),
        )

        self.assertEqual(evidence["status"], "confirmado")
        self.assertEqual(evidence["provisionamento"]["lookup_inicial"], "miss")
        self.assertEqual(evidence["provisionamento"]["http_calls"], 1)
        self.assertEqual(
            [item["status"] for item in evidence["provisionamento"]["resultados_concorrentes"]],
            ["sincronizada", "sincronizada"],
        )
        self.assertEqual(evidence["provisionamento"]["segunda_consulta"]["status"], "local")
        self.assertEqual(
            [
                (
                    item["activity_code"],
                    item["activity_description"],
                    item["work_center_code"],
                    item["machine_code"],
                )
                for item in evidence["roteiro"]["activities_received"]
            ],
            [
                ("01", "IMPRESSAO OP", "PCP", "PCP"),
                ("10", "CORTE", "CORTE", "LASER"),
                ("20", "INSPECAO", "CALDER", "INSPEC"),
                ("99", "FINALIZADA", "ALMOX4", "ALMOX4"),
            ],
        )
        catalog = {
            item["numero_operacao"]: item for item in evidence["roteiro"]["catalog"]
        }
        self.assertEqual(
            [item["numero_operacao"] for item in evidence["roteiro"]["catalog"]],
            ["10", "20", "99"],
        )
        self.assertEqual(catalog["10"]["codigo_recurso"], "LASER1")
        self.assertTrue(catalog["10"]["ativo"])
        # A operação de inspeção entra como metadado do roteiro, inativa: a aba
        # Qualidade a executa, o posto do operador nunca a enxerga.
        self.assertTrue(catalog["20"]["inspecao_qualidade"])
        self.assertFalse(catalog["20"]["ativo"])
        self.assertIsNone(catalog["20"]["tipo_setor"])
        self.assertEqual(catalog["20"]["totvs_machine_code"], "INSPEC")
        self.assertTrue(catalog["99"]["marco_terminal"])
        self.assertFalse(catalog["99"]["ativo"])
        self.assertEqual(evidence["roteiro"]["operator_visible_operations"], ["10"])
        self.assertEqual(evidence["roteiro"]["outbox_after_ingestion"], 0)
        self.assertEqual(evidence["sigmanest"]["status"], "nao_aplicavel")

        facts = evidence["execucao_canonica"]["facts"]
        self.assertEqual(facts["appointments"], 1)
        self.assertGreaterEqual(facts["operator_events"], 6)
        self.assertGreaterEqual(facts["resource_events"], 1)
        self.assertGreaterEqual(facts["history"], 1)
        # Wave 4: a OP real prevê 2 peças e boas + refugo têm esse teto.
        self.assertEqual(facts["good_quantity"], 1)
        self.assertEqual(facts["scrap_quantity"], 1)
        self.assertEqual(facts["rework_quantity"], 0)

        initial = evidence["outbox_initial"]
        self.assertEqual(len(initial), 4)
        self.assertEqual(len({item["idempotency_key"] for item in initial}), 4)
        terminal = next(
            item for item in initial if item["event_type"] == "production_appointment_terminal"
        )
        self.assertEqual(terminal["payload_fields"]["activity_code"], "99")
        self.assertEqual(terminal["payload_fields"]["machine_code"], "ALMOX4")
        self.assertEqual(terminal["payload_fields"]["approved_quantity"], "1")
        self.assertEqual(terminal["payload_fields"]["scrap_quantity"], "0")

        # Ordem causal por OP (F19): o ciclo offline só tenta a obrigação mais
        # antiga; as outras três esperam em PENDING.
        self.assertEqual(evidence["retry"]["cycle"]["reagendados"], 1)
        self.assertEqual(
            sorted(item["status"] for item in evidence["retry"]["items"]),
            ["PENDING", "PENDING", "PENDING", "RETRY"],
        )
        self.assertTrue(evidence["restart_and_lease"]["payloads_preserved"])
        self.assertEqual(evidence["restart_and_lease"]["recovered"], 1)
        self.assertTrue(evidence["delivery"]["executed"])
        self.assertEqual(evidence["delivery"]["kind"], "ack_controlado_automatizado")
        # Um item por OP por ciclo: quatro ciclos, um envio em cada.
        self.assertEqual(
            [cycle["enviados"] for cycle in evidence["delivery"]["cycles"]], [1, 1, 1, 1]
        )
        self.assertEqual(evidence["delivery"]["duplicate_cycle_reserved"], 0)
        self.assertTrue(all(item["status"] == "SENT" for item in evidence["delivery"]["items"]))
        self.assertTrue(
            all(item["last_ack_status"] == "OK" for item in evidence["delivery"]["items"])
        )
        self.assertEqual(evidence["final_metrics"]["sent"], 4)
        self.assertEqual(evidence["final_metrics"]["retry"], 0)


if __name__ == "__main__":
    unittest.main()
