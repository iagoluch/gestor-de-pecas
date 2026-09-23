"""``ProtheusProductModelGateway`` (mes/integrations/totvs/product_model_gateway.py)
não tinha nenhum teste dedicado.

O módulo é só transporte, mas isso ainda deixa lógica real para testar: como
cada resposta HTTP (200 com/sem "modelo", 404, 4xx/5xx, JSON ausente ou
malformado, "productCode" faltando) vira um ``ProductModelRequestResult``, e
como ``from_env`` monta a config (endpoint ausente => sem gateway, timeout
inválido cai no default, herança de credencial do pull de OP, verify_tls).

Segue o padrão de ``tests/test_totvs_on_demand.py``: transporte real via
``httpx.MockTransport``, sem tocar rede.
"""

from __future__ import annotations

import httpx
import unittest

from mes.integrations.totvs.product_model_gateway import (
    DEFAULT_TIMEOUT_SECONDS,
    ProductModelGatewayConfig,
    ProductModelRequestResult,
    ProtheusProductModelGateway,
)


def _gateway(handler, **config_kwargs) -> ProtheusProductModelGateway:
    config_kwargs.setdefault("endpoint", "https://protheus.invalid/model")
    return ProtheusProductModelGateway(
        ProductModelGatewayConfig(**config_kwargs),
        transport=httpx.MockTransport(handler),
    )


class RequestProductModelTests(unittest.TestCase):
    def test_200_com_modelo_e_aceito(self):
        gateway = _gateway(
            lambda request: httpx.Response(
                200, json={"productCode": "SSM014007071", "modelo": "MOD-1"}
            )
        )
        result = gateway.request_product_model(
            company_id="01", branch_id="010004", product_code="SSM014007071"
        )
        self.assertEqual(
            result,
            ProductModelRequestResult(accepted=True, modelo="MOD-1"),
        )

    def test_200_com_modelo_vazio_vira_string_vazia_nao_none(self):
        gateway = _gateway(
            lambda request: httpx.Response(200, json={"productCode": "X", "modelo": ""})
        )
        result = gateway.request_product_model(
            company_id="01", branch_id="010004", product_code="X"
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.modelo, "")

    def test_200_sem_chave_modelo_tambem_vira_string_vazia(self):
        gateway = _gateway(lambda request: httpx.Response(200, json={"productCode": "X"}))
        result = gateway.request_product_model(
            company_id="01", branch_id="010004", product_code="X"
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.modelo, "")

    def test_404_e_nao_encontrado_nao_indisponibilidade(self):
        gateway = _gateway(lambda request: httpx.Response(404, json={"status": "notFound"}))
        result = gateway.request_product_model(
            company_id="01", branch_id="010004", product_code="ZZ999"
        )
        self.assertTrue(result.not_found)
        self.assertFalse(result.accepted)
        self.assertIsNone(result.unavailable_reason)

    def test_http_500_vira_indisponibilidade_com_codigo_do_status(self):
        gateway = _gateway(lambda request: httpx.Response(500, text="erro interno"))
        result = gateway.request_product_model(
            company_id="01", branch_id="010004", product_code="X"
        )
        self.assertFalse(result.accepted)
        self.assertFalse(result.not_found)
        self.assertEqual(result.unavailable_reason, "http_500")
        self.assertEqual(result.detail, "erro interno")

    def test_falha_de_rede_e_classificada_pelo_transporte_comum(self):
        def handler(request):
            raise httpx.ConnectError("recusada", request=request)

        gateway = _gateway(handler)
        result = gateway.request_product_model(
            company_id="01", branch_id="010004", product_code="X"
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.unavailable_reason, "conexao_recusada")

    def test_timeout_e_classificado_como_timeout(self):
        def handler(request):
            raise httpx.ReadTimeout("timeout", request=request)

        gateway = _gateway(handler)
        result = gateway.request_product_model(
            company_id="01", branch_id="010004", product_code="X"
        )
        self.assertEqual(result.unavailable_reason, "timeout")

    def test_200_com_corpo_nao_json_vira_indisponibilidade(self):
        gateway = _gateway(
            lambda request: httpx.Response(
                200, text="<html>não é json</html>", headers={"content-type": "text/html"}
            )
        )
        result = gateway.request_product_model(
            company_id="01", branch_id="010004", product_code="X"
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.unavailable_reason, "resposta_sem_json")

    def test_200_com_json_que_nao_e_objeto_vira_indisponibilidade(self):
        gateway = _gateway(lambda request: httpx.Response(200, json=["não", "é", "objeto"]))
        result = gateway.request_product_model(
            company_id="01", branch_id="010004", product_code="X"
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.unavailable_reason, "resposta_sem_json")

    def test_200_sem_productcode_e_contrato_quebrado_nao_sem_modelo(self):
        """O docstring do gateway é explícito: productCode ausente é contrato
        quebrado, não "modelo ausente" — não pode virar ``accepted``."""

        gateway = _gateway(lambda request: httpx.Response(200, json={"modelo": "MOD-1"}))
        result = gateway.request_product_model(
            company_id="01", branch_id="010004", product_code="X"
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.unavailable_reason, "resposta_fora_do_contrato")

    def test_campos_ausentes_no_payload_viram_string_vazia_no_corpo(self):
        capturado = {}

        def handler(request):
            capturado["body"] = request.content.decode("utf-8")
            return httpx.Response(200, json={"productCode": "X", "modelo": "M"})

        gateway = _gateway(handler)
        gateway.request_product_model(company_id=None, branch_id=None, product_code="  X  ")
        self.assertIn('"companyId":""', capturado["body"])
        self.assertIn('"branchId":""', capturado["body"])
        self.assertIn('"productCode":"X"', capturado["body"])

    def test_credencial_configurada_e_enviada_como_basic_auth(self):
        capturado = {}

        def handler(request):
            capturado["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json={"productCode": "X", "modelo": "M"})

        gateway = _gateway(handler, username="user1", password="senha1")
        gateway.request_product_model(company_id="01", branch_id="010004", product_code="X")
        self.assertTrue(capturado["auth"], "esperava header Authorization com basic auth")
        self.assertTrue(capturado["auth"].startswith("Basic "))

    def test_sem_username_nao_envia_auth(self):
        capturado = {}

        def handler(request):
            capturado["auth"] = request.headers.get("authorization")
            return httpx.Response(200, json={"productCode": "X", "modelo": "M"})

        gateway = _gateway(handler)
        gateway.request_product_model(company_id="01", branch_id="010004", product_code="X")
        self.assertIsNone(capturado["auth"])


class FromEnvTests(unittest.TestCase):
    def test_sem_endpoint_nao_existe_gateway(self):
        self.assertIsNone(ProtheusProductModelGateway.from_env({}))

    def test_endpoint_em_branco_tambem_nao_existe_gateway(self):
        self.assertIsNone(
            ProtheusProductModelGateway.from_env({"GESTOR_TOTVS_MODEL_PULL_ENDPOINT": "   "})
        )

    def test_config_minima_usa_defaults(self):
        gateway = ProtheusProductModelGateway.from_env(
            {"GESTOR_TOTVS_MODEL_PULL_ENDPOINT": "https://protheus.invalid/model"}
        )
        self.assertIsNotNone(gateway)
        self.assertEqual(gateway.config.endpoint, "https://protheus.invalid/model")
        self.assertEqual(gateway.config.timeout_seconds, DEFAULT_TIMEOUT_SECONDS)
        self.assertIsNone(gateway.config.username)
        self.assertTrue(gateway.config.verify_tls)

    def test_timeout_invalido_cai_no_default(self):
        gateway = ProtheusProductModelGateway.from_env(
            {
                "GESTOR_TOTVS_MODEL_PULL_ENDPOINT": "https://protheus.invalid/model",
                "GESTOR_TOTVS_MODEL_PULL_TIMEOUT_SECONDS": "not-a-number",
            }
        )
        self.assertEqual(gateway.config.timeout_seconds, DEFAULT_TIMEOUT_SECONDS)

    def test_timeout_zero_ou_negativo_cai_no_default(self):
        for valor in ("0", "-5"):
            with self.subTest(valor=valor):
                gateway = ProtheusProductModelGateway.from_env(
                    {
                        "GESTOR_TOTVS_MODEL_PULL_ENDPOINT": "https://protheus.invalid/model",
                        "GESTOR_TOTVS_MODEL_PULL_TIMEOUT_SECONDS": valor,
                    }
                )
                self.assertEqual(gateway.config.timeout_seconds, DEFAULT_TIMEOUT_SECONDS)

    def test_timeout_valido_e_respeitado(self):
        gateway = ProtheusProductModelGateway.from_env(
            {
                "GESTOR_TOTVS_MODEL_PULL_ENDPOINT": "https://protheus.invalid/model",
                "GESTOR_TOTVS_MODEL_PULL_TIMEOUT_SECONDS": "7.5",
            }
        )
        self.assertEqual(gateway.config.timeout_seconds, 7.5)

    def test_credencial_propria_tem_prioridade_sobre_a_do_pull_de_op(self):
        gateway = ProtheusProductModelGateway.from_env(
            {
                "GESTOR_TOTVS_MODEL_PULL_ENDPOINT": "https://protheus.invalid/model",
                "GESTOR_TOTVS_MODEL_PULL_USERNAME": "modelo_user",
                "GESTOR_TOTVS_MODEL_PULL_PASSWORD": "modelo_pass",
                "GESTOR_TOTVS_OP_PULL_USERNAME": "op_user",
                "GESTOR_TOTVS_OP_PULL_PASSWORD": "op_pass",
            }
        )
        self.assertEqual(gateway.config.username, "modelo_user")
        self.assertEqual(gateway.config.password, "modelo_pass")

    def test_credencial_herda_a_do_pull_de_op_quando_ausente(self):
        gateway = ProtheusProductModelGateway.from_env(
            {
                "GESTOR_TOTVS_MODEL_PULL_ENDPOINT": "https://protheus.invalid/model",
                "GESTOR_TOTVS_OP_PULL_USERNAME": "op_user",
                "GESTOR_TOTVS_OP_PULL_PASSWORD": "op_pass",
            }
        )
        self.assertEqual(gateway.config.username, "op_user")
        self.assertEqual(gateway.config.password, "op_pass")

    def test_verify_tls_desligado_por_valores_reconhecidos(self):
        for valor in ("0", "false", "False", "no"):
            with self.subTest(valor=valor):
                gateway = ProtheusProductModelGateway.from_env(
                    {
                        "GESTOR_TOTVS_MODEL_PULL_ENDPOINT": "https://protheus.invalid/model",
                        "GESTOR_TOTVS_MODEL_PULL_VERIFY_TLS": valor,
                    }
                )
                self.assertFalse(gateway.config.verify_tls)

    def test_verify_tls_padrao_e_ligado(self):
        gateway = ProtheusProductModelGateway.from_env(
            {"GESTOR_TOTVS_MODEL_PULL_ENDPOINT": "https://protheus.invalid/model"}
        )
        self.assertTrue(gateway.config.verify_tls)


if __name__ == "__main__":
    unittest.main()
