import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.ai.groq_provider import GroqProvider
from backend.ai.rate_limit_state import AIRateLimitState
from backend.api.config import WebSettings
from backend.api.main import create_app
from mes.ai.context_budget import (
    build_budgeted_context,
    estimate_request_tokens,
    fit_messages_to_budget,
)
from mes.ai.prompts.system_prompt import build_system_prompt
from mes.contracts.ai import (
    AIConversationNotFoundError,
    AIProviderError,
    AIProviderResponse,
    AIRequestContext,
    AIServiceConfig,
    AIToolCall,
    AIToolError,
)
from mes.services.ai_service import AIService
from mes.services.ai_tools import AIToolRegistry, TOOL_REGISTRY
from scripts.run_simulacao_residencia import configure_environment
from tests.fakes import FakeDatabase


class FakeProvider:
    configured = True

    def __init__(self, plans=None, chunks=None, stream_error=None):
        self.plans = list(plans or [AIProviderResponse(content="Resposta confirmada.")])
        self.chunks = list(chunks or ["Resposta ", "confirmada."])
        self.stream_error = stream_error
        self.complete_messages = []
        self.stream_messages = []

    async def complete(self, messages, *, tools, tool_choice="auto", request_id=None):
        self.complete_messages.append((list(messages), list(tools), tool_choice))
        return self.plans.pop(0) if self.plans else AIProviderResponse(content="fim")

    async def stream(self, messages, *, tools=None, tool_choice="none", request_id=None):
        self.stream_messages.append((list(messages), list(tools or []), tool_choice))
        if self.stream_error:
            raise self.stream_error
        for chunk in self.chunks:
            yield chunk


class FacadeSpy:
    def __init__(self):
        self.calls = []

    def _return(self, name, *args):
        self.calls.append((name, args))
        return {"source": name, "availability": "dados_insuficientes", "items": list(range(120))}

    def andon(self, filters): return self._return("andon", filters)
    def inicio(self, filters): return self._return("inicio", filters)
    def insights(self, filters): return self._return("insights", filters)
    def explain_kpi(self, key, filters): return self._return("explain_kpi", key, filters)
    def consulta_operacional(self, filters): return self._return("consulta_operacional", filters)
    def ordens_producao(self, filters): return self._return("ordens_producao", filters)
    def producao_realizada(self, filters): return self._return("producao_realizada", filters)
    def analise(self, key, filters): return self._return("analise", key, filters)
    def rastreabilidade(self, op): return self._return("rastreabilidade", op)
    def nestings(self, filters): return self._return("nestings", filters)
    def auditoria(self, filters): return self._return("auditoria", filters)


def tool_response(name, arguments="{}", call_id="call-1"):
    call = AIToolCall(id=call_id, name=name, arguments=arguments)
    return AIProviderResponse(
        content=None,
        tool_calls=(call,),
        assistant_message={
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }],
        },
        finish_reason="tool_calls",
    )


class AIToolRegistryTests(unittest.TestCase):
    def setUp(self):
        self.facade = FacadeSpy()
        self.registry = AIToolRegistry(
            self.facade,
            now_func=lambda: datetime(2026, 8, 24, 12, 0),
        )
        self.context = AIRequestContext(user_id=1, management_access=True)

    def test_registry_eh_whitelist_read_only_sem_tools_proibidas(self):
        forbidden = {
            "execute_sql", "start_production", "finish_order",
            "stop_production", "update_quantity", "delete_event",
        }
        self.assertFalse(forbidden & set(TOOL_REGISTRY))
        self.assertIn("get_management_overview", TOOL_REGISTRY)
        self.assertIn("trace_work_order", TOOL_REGISTRY)
        self.assertNotIn("get_occurrences", TOOL_REGISTRY)
        self.assertTrue(all(schema["function"]["parameters"]["additionalProperties"] is False for schema in self.registry.schemas))
        serialized = json.dumps(self.registry.schemas)
        self.assertNotIn("oneOf", serialized)
        self.assertNotIn("anyOf", serialized)
        self.assertNotIn("allOf", serialized)
        factory_schema = self.registry.schemas_for_names(["get_factory_status"])[0]
        self.assertEqual(factory_schema["function"]["parameters"]["properties"], {})

    def test_roteamento_deterministico_limita_tools_por_intencao(self):
        cases = {
            "Como está a fábrica agora?": {
                "get_factory_status", "get_management_overview", "get_management_insights",
            },
            "Explique o OEE e as paradas": {
                "get_management_insights", "explain_kpi", "get_downtimes", "get_quality", "get_setups",
            },
            "Rastreie a OP 123": {
                "trace_work_order", "get_production_orders", "get_production",
            },
            "Qual é o estado da máquina DOBRA4?": {
                "get_resource_status", "get_downtimes",
            },
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                selected = self.registry.select_schemas(question)
                self.assertEqual(
                    {schema["function"]["name"] for schema in selected},
                    expected,
                )

        fallback = self.registry.select_schemas("Preciso de um resumo útil")
        self.assertLessEqual(len(fallback), 2)
        self.assertEqual(self.registry.select_schemas("Quem é você?"), [])

    def test_tools_reutilizam_exatamente_os_metodos_da_facade(self):
        calls = {
            "get_factory_status": ({}, "andon"),
            "get_management_overview": ({}, "inicio"),
            "get_management_insights": ({}, "insights"),
            "explain_kpi": ({"key": "oee"}, "explain_kpi"),
            "get_resource_status": ({"recurso": "DOBRA-01"}, "consulta_operacional"),
            "get_sector_status": ({"setor": "Dobra"}, "consulta_operacional"),
            "get_production_orders": ({}, "ordens_producao"),
            "get_production": ({}, "producao_realizada"),
            "get_downtimes": ({}, "analise"),
            "get_quality": ({}, "analise"),
            "get_setups": ({}, "analise"),
            "trace_work_order": ({"op": "OP-1"}, "rastreabilidade"),
            "get_nestings": ({}, "nestings"),
            "get_audit_issues": ({}, "auditoria"),
        }
        for tool_name, (arguments, expected) in calls.items():
            with self.subTest(tool=tool_name):
                self.registry.execute(tool_name, arguments, self.context)
                self.assertEqual(self.facade.calls[-1][0], expected)

    def test_argumentos_periodo_permissao_e_tool_inexistente_sao_rejeitados(self):
        with self.assertRaises(AIToolError):
            self.registry.execute("execute_sql", {}, self.context)
        with self.assertRaises(AIToolError):
            self.registry.execute("get_quality", {"campo": "x"}, self.context)
        calls_before = len(self.facade.calls)
        with self.assertRaises(AIToolError):
            self.registry.execute("get_quality", '{"setor":', self.context)
        self.assertEqual(len(self.facade.calls), calls_before)
        with self.assertRaises(AIToolError):
            self.registry.execute(
                "get_quality",
                {"inicio": "2025-01-01T00:00:00", "fim": "2026-08-24T00:00:00"},
                self.context,
            )
        with self.assertRaises(AIToolError):
            self.registry.execute(
                "get_quality",
                {},
                AIRequestContext(user_id=2, management_access=False),
            )

    def test_payload_informa_truncamento_e_preserva_dados_insuficientes(self):
        payload = self.registry.execute("get_quality", {}, self.context)
        self.assertEqual(payload["data"]["availability"], "dados_insuficientes")
        self.assertTrue(payload["data"]["items"]["truncated"])
        self.assertEqual(payload["data"]["items"]["total"], 120)
        self.assertTrue(payload["limits"]["truncated"])

    def test_factory_status_projeta_payload_compacto_sem_recalcular(self):
        class LargeAndonFacade(FacadeSpy):
            def andon(self, filters):
                resources = []
                for index in range(48):
                    stopped = index < 6
                    resources.append({
                        "code": f"REC-{index:02d}",
                        "name": f"Recurso duplicado {index}",
                        "sector": "Dobra",
                        "presentation_only": "NAO_ENVIAR_" + ("x" * 400),
                        "state": {
                            "category": "parada" if stopped else "producao",
                            "label": "label duplicada",
                            "duration_seconds": 120 + index,
                            "reason": "Aguardando manutenção" if stopped else None,
                            "source": "estado_canonico",
                        },
                        "operation": {
                            "op": f"OP-{index}",
                            "operation": "10",
                            "product_description": "x" * 300,
                        },
                        "metrics": {
                            "oee": {"value": 37.25, "availability": "disponivel", "unit": "%"},
                        },
                    })
                return {
                    "generated_at": "2026-08-25T10:00:00",
                    "resource_count": 48,
                    "summary": {
                        "resources": 48,
                        "production": 42,
                        "downtime": 6,
                        "setup": 0,
                        "rework": 0,
                        "queue": 0,
                        "unknown": 0,
                        "oee": {"value": 37.25, "availability": "disponivel", "unit": "%"},
                    },
                    "sectors": [{"name": "Dobra", "resources": resources}],
                    "frontend_layout": "NAO_ENVIAR_" + ("z" * 5_000),
                }

        registry = AIToolRegistry(
            LargeAndonFacade(),
            now_func=lambda: datetime(2026, 8, 25, 10, 0),
            tool_result_max_chars=3_500,
        )
        result = registry.execute("get_factory_status", {}, self.context)
        serialized = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        data = result["data"]
        self.assertLessEqual(len(serialized), 3_500)
        self.assertNotIn("NAO_ENVIAR", serialized)
        self.assertEqual(data["summary"]["total_resources"], 48)
        self.assertEqual(data["indicators"]["oee"]["value"], 37.25)
        self.assertEqual(data["indicators"]["oee"]["unit"], "%")
        self.assertEqual(data["attention_resources"]["returned"], 6)
        self.assertEqual(
            {item["resource"] for item in data["attention_resources"]["items"]},
            {f"REC-{index:02d}" for index in range(6)},
        )
        self.assertTrue(data["truncated"])
        self.assertTrue(result["limits"]["truncated"])
        self.assertGreater(result["limits"]["raw_chars"], len(serialized))
        self.assertEqual(json.loads(serialized)["data"]["returned"], data["returned"])


class AIContextBudgetTests(unittest.TestCase):
    def test_budget_nunca_mantem_resposta_sem_a_pergunta_do_mesmo_turno(self):
        history = []
        for index in range(12):
            history.extend([
                {"role": "user", "content": f"pergunta-{index} " + ("p" * 700)},
                {"role": "assistant", "content": f"resposta-{index} " + ("r" * 700)},
            ])
        question = "Qual é o estado atual?"
        history.append({"role": "user", "content": question})

        messages, metrics = build_budgeted_context(
            history=history,
            knowledge=[],
            question=question,
            tools=[],
            request_token_budget=2_400,
            max_completion_tokens=512,
        )

        selected = messages[1:-1]
        self.assertTrue(metrics["truncated"])
        self.assertEqual([item["role"] for item in selected], ["user", "assistant"])
        self.assertIn("pergunta-11", selected[0]["content"])
        self.assertIn("resposta-11", selected[1]["content"])

    def test_budget_global_reduz_historico_e_knowledge_preservando_pergunta(self):
        history = [
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"mensagem-{index} " + ("h" * 900),
            }
            for index in range(20)
        ]
        question = "Como está a fábrica agora?"
        history.append({"role": "user", "content": question})
        knowledge = [
            {
                "status_validacao": "validado",
                "tipo": "regra",
                "conteudo": f"fábrica {index} " + ("k" * 900),
            }
            for index in range(10)
        ]
        tools = [AIToolRegistry(FacadeSpy()).schemas_for_names(["get_factory_status"])[0]]
        messages, metrics = build_budgeted_context(
            history=history,
            knowledge=knowledge,
            question=question,
            tools=tools,
            request_token_budget=2_000,
            max_completion_tokens=512,
        )
        self.assertEqual(messages[-1], {"role": "user", "content": question})
        self.assertLess(metrics["history_returned"], metrics["history_total"])
        self.assertLess(metrics["knowledge_returned"], metrics["knowledge_total"])
        self.assertLessEqual(estimate_request_tokens(messages, tools, 512), 2_000)

    def test_budget_da_segunda_chamada_preserva_assistant_tool_e_id(self):
        messages = [
            {"role": "system", "content": build_system_prompt()},
            *({"role": "user", "content": "antiga " + ("x" * 700)} for _ in range(8)),
            {"role": "user", "content": "Como está a fábrica agora?"},
            {"role": "assistant", "tool_calls": [{"id": "call-exato"}]},
            {
                "role": "tool",
                "tool_call_id": "call-exato",
                "name": "get_factory_status",
                "content": "{\"ok\":true}",
            },
        ]
        fitted, metrics = fit_messages_to_budget(
            messages,
            tools=[],
            request_token_budget=1_900,
            max_completion_tokens=512,
        )
        self.assertTrue(metrics["within_budget"])
        self.assertGreater(metrics["history_messages_removed"], 0)
        self.assertEqual(fitted[-2]["role"], "assistant")
        self.assertEqual(fitted[-1]["tool_call_id"], "call-exato")


class AIServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.user_id = self.db.criar_usuario("Gestor IA", "senha", "gestor")
        self.facade = FacadeSpy()
        self.tools = AIToolRegistry(
            self.facade,
            now_func=lambda: datetime(2026, 8, 24, 12, 0),
        )
        self.context = AIRequestContext(user_id=self.user_id, management_access=True, request_id="req-1")

    def service(self, provider, *, history=20, rounds=6, enabled=True, configured=True):
        return AIService(
            self.db,
            provider,
            self.tools,
            AIServiceConfig(
                enabled=enabled,
                configured=configured,
                model="openai/gpt-oss-120b",
                max_tool_rounds=rounds,
                max_history_messages=history,
            ),
        )

    @staticmethod
    async def collect(generator):
        return [event async for event in generator]

    def test_historico_limitado_system_prompt_e_assistant_persistido_ao_final(self):
        provider = FakeProvider()
        service = self.service(provider, history=2)
        conversation = service.create_conversation(self.user_id)
        self.db.adicionar_mensagem_ia(conversation["id"], self.user_id, "user", "antiga 1")
        self.db.adicionar_mensagem_ia(conversation["id"], self.user_id, "assistant", "antiga 2")
        self.db.adicionar_mensagem_ia(conversation["id"], self.user_id, "user", "antiga 3")
        events = asyncio.run(self.collect(service.stream_message(
            conversation["id"], "Como está a fábrica?", self.context
        )))
        planning_messages = provider.complete_messages[0][0]
        self.assertEqual(planning_messages[0]["role"], "system")
        self.assertIn("Quantidade Produzida", planning_messages[0]["content"])
        self.assertEqual([item["role"] for item in planning_messages[1:]], ["user", "user"])
        saved = service.get_conversation(conversation["id"], self.user_id)
        self.assertEqual(saved["messages"][-1]["role"], "assistant")
        self.assertEqual(saved["messages"][-1]["content"], "Resposta confirmada.")
        self.assertEqual(events[-1].event, "done")
        self.assertNotIn("system", [item["role"] for item in saved["messages"]])

    def test_prompt_usa_somente_conhecimento_validado_e_com_limite(self):
        knowledge = [
            {
                "tipo": "regra",
                "conteudo": "CONHECIMENTO VALIDADO " + ("x" * 3_000),
                "status_validacao": "validado",
            },
            {
                "tipo": "rascunho",
                "conteudo": "NÃO PODE ENTRAR NO PROMPT",
                "status_validacao": "rascunho",
            },
        ] * 30
        prompt = build_system_prompt(knowledge)
        self.assertIn("CONHECIMENTO VALIDADO", prompt)
        self.assertNotIn("NÃO PODE ENTRAR NO PROMPT", prompt)
        self.assertLess(len(prompt), 20_000)

    def test_prompt_preserva_regras_e_orienta_sintese_gerencial(self):
        prompt = build_system_prompt()
        self.assertIn("Comece pela conclusão", prompt)
        self.assertIn("não como relatório de banco", prompt)
        self.assertIn("Use tabela somente quando solicitada", prompt)
        self.assertIn("priorize exceções, desvios", prompt)
        self.assertIn("Estado desconhecido é falta de estado identificado", prompt)
        self.assertIn("Nunca invente causa, meta, responsável, impacto", prompt)
        self.assertIn("não diga \"impactando\"", prompt)
        self.assertIn("não são estado operacional", prompt)
        self.assertIn("Não acrescente \"próximos passos\"", prompt)
        self.assertIn("Quantidade Produzida significa peças boas", prompt)
        self.assertIn("Setup é produtivo", prompt)
        self.assertIn("não executa SQL", prompt)
        self.assertIn("somente leitura", prompt)

    def test_tool_call_passa_pela_facade_e_limite_impede_loop(self):
        provider = FakeProvider(plans=[tool_response("get_quality")], chunks=["Qualidade sem base oficial."])
        service = self.service(provider, rounds=1)
        conversation = service.create_conversation(self.user_id)
        events = asyncio.run(self.collect(service.stream_message(
            conversation["id"], "Como está a qualidade?", self.context
        )))
        self.assertEqual(len(provider.complete_messages), 1)
        self.assertEqual(self.facade.calls[-1][0], "analise")
        self.assertTrue(any(event.data.get("message", "").startswith("Analisando qualidade") for event in events if event.event == "status"))
        assistant = service.get_conversation(conversation["id"], self.user_id)["messages"][-1]
        self.assertTrue(assistant["metadata"]["tool_limit_reached"])
        self.assertEqual(assistant["metadata"]["tools"], ["get_quality"])
        final_instruction = provider.stream_messages[0][0][-1]
        self.assertEqual(final_instruction["role"], "system")
        self.assertIn("somente 3 a 8 frases naturais", final_instruction["content"])
        self.assertIn("sem títulos, listas, tabelas", final_instruction["content"])
        self.assertIn("sem atribuir impacto, sem novas tools", final_instruction["content"])

    def test_conversa_simples_nao_envia_tools_desnecessarias(self):
        provider = FakeProvider(chunks=["Olá! Sou a IA Industrial."])
        service = self.service(provider)
        conversation = service.create_conversation(self.user_id)
        events = asyncio.run(self.collect(service.stream_message(
            conversation["id"], "Olá", self.context
        )))
        self.assertEqual(provider.complete_messages, [])
        self.assertEqual(provider.stream_messages[0][1], [])
        self.assertEqual(provider.stream_messages[0][2], "none")
        self.assertEqual(events[-1].event, "done")

    def test_sequencia_assistant_tool_preserva_tool_call_id_exato(self):
        provider = FakeProvider(plans=[
            tool_response("get_quality", call_id="call_groq_exato_123"),
            AIProviderResponse(content="Qualidade consultada."),
        ])
        service = self.service(provider, rounds=2)
        conversation = service.create_conversation(self.user_id)
        asyncio.run(self.collect(service.stream_message(
            conversation["id"], "Como está a qualidade?", self.context
        )))
        second_round = provider.complete_messages[1][0]
        self.assertEqual(second_round[-2]["role"], "assistant")
        self.assertEqual(
            second_round[-2]["tool_calls"][0]["id"],
            "call_groq_exato_123",
        )
        self.assertEqual(second_round[-1]["role"], "tool")
        self.assertEqual(second_round[-1]["tool_call_id"], "call_groq_exato_123")
        self.assertEqual(second_round[-1]["name"], "get_quality")

    def test_argumento_json_invalido_nao_executa_tool_e_retorna_erro_controlado(self):
        provider = FakeProvider(plans=[
            tool_response("get_quality", arguments='{"setor":'),
            AIProviderResponse(content="Não foi possível usar os argumentos recebidos."),
        ])
        service = self.service(provider, rounds=2)
        conversation = service.create_conversation(self.user_id)
        asyncio.run(self.collect(service.stream_message(
            conversation["id"], "Como está a qualidade?", self.context
        )))
        self.assertEqual(self.facade.calls, [])
        tool_message = provider.complete_messages[1][0][-1]
        self.assertEqual(tool_message["role"], "tool")
        self.assertEqual(
            json.loads(tool_message["content"])["error"]["code"],
            "ai_tool_invalid_arguments",
        )

    def test_tool_valida_mas_fora_do_subconjunto_selecionado_eh_bloqueada(self):
        provider = FakeProvider(plans=[
            tool_response("get_audit_issues"),
            AIProviderResponse(content="Consulta recusada de forma controlada."),
        ])
        service = self.service(provider, rounds=2)
        conversation = service.create_conversation(self.user_id)
        asyncio.run(self.collect(service.stream_message(
            conversation["id"], "Como está a qualidade?", self.context
        )))
        self.assertEqual(self.facade.calls, [])
        tool_message = provider.complete_messages[1][0][-1]
        self.assertEqual(
            json.loads(tool_message["content"])["error"]["code"],
            "ai_tool_not_selected",
        )

    def test_falha_ou_cancelamento_nao_persiste_assistant_concluido(self):
        provider = FakeProvider(
            plans=[AIProviderResponse(content=None)],
            stream_error=asyncio.CancelledError(),
        )
        service = self.service(provider)
        conversation = service.create_conversation(self.user_id)
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(self.collect(service.stream_message(
                conversation["id"], "Consulta cancelada", self.context
            )))
        messages = service.get_conversation(conversation["id"], self.user_id)["messages"]
        self.assertEqual([item["role"] for item in messages], ["user"])

    def test_retry_reutiliza_pergunta_pendente_sem_duplicar_user(self):
        provider = FakeProvider()
        service = self.service(provider)
        conversation = service.create_conversation(self.user_id)
        self.db.adicionar_mensagem_ia(conversation["id"], self.user_id, "user", "Pergunta pendente")
        asyncio.run(self.collect(service.stream_message(
            conversation["id"], "Pergunta pendente", self.context, retry=True
        )))
        roles = [item["role"] for item in service.get_conversation(conversation["id"], self.user_id)["messages"]]
        self.assertEqual(roles, ["user", "assistant"])

    def test_exclusao_remove_somente_conversa_do_proprio_gestor(self):
        provider = FakeProvider()
        service = self.service(provider)
        conversation = service.create_conversation(self.user_id, "Pergunta do gestor")
        self.db.adicionar_mensagem_ia(
            conversation["id"], self.user_id, "user", "Como está a fábrica?"
        )
        other_user = self.db.criar_usuario("Outro Gestor Exclusão", "senha", "gestor")
        with self.assertRaises(AIConversationNotFoundError):
            service.delete_conversation(conversation["id"], other_user)
        self.assertIsNotNone(service.get_conversation(conversation["id"], self.user_id))

        service.delete_conversation(conversation["id"], self.user_id)
        with self.assertRaises(AIConversationNotFoundError):
            service.get_conversation(conversation["id"], self.user_id)
        self.assertFalse(
            any(item["conversation_id"] == conversation["id"] for item in self.db.ai_messages)
        )


class _RecordingCompletions:
    def __init__(self, results):
        self.results = list(results)
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class _Client:
    def __init__(self, results):
        self.completions = _RecordingCompletions(results)
        self.chat = SimpleNamespace(completions=self.completions)


def _completion(*, content="ok", tool_name=None, arguments="{}", call_id="call-1"):
    tool_calls = []
    finish_reason = "stop"
    if tool_name:
        tool_calls = [SimpleNamespace(
            id=call_id,
            function=SimpleNamespace(name=tool_name, arguments=arguments),
        )]
        finish_reason = "tool_calls"
        content = None
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=None)


def _api_error(name, status, body=None, headers=None):
    error = type(name, (Exception,), {})()
    error.status_code = status
    error.body = body
    error.response = SimpleNamespace(headers=dict(headers or {}))
    return error


class GroqProviderTests(unittest.TestCase):
    @staticmethod
    def schema(name="get_factory_status"):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": "Consulta segura.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            },
        }

    def provider(self, results, *, monotonic_func=None):
        client = _Client(results)
        provider = GroqProvider(
            api_key="chave-de-teste",
            model="openai/gpt-oss-120b",
            client=client,
            timeout_seconds=1,
            monotonic_func=monotonic_func,
        )
        return provider, client

    def test_payload_desabilita_parallel_e_usa_tool_choice_auto(self):
        provider, client = self.provider([
            _completion(tool_name="get_factory_status", call_id="call-original-groq"),
        ])
        response = asyncio.run(provider.complete(
            [{"role": "user", "content": "status"}],
            tools=[self.schema()],
        ))
        request = client.completions.requests[0]
        self.assertIs(request["parallel_tool_calls"], False)
        self.assertEqual(request["tool_choice"], "auto")
        self.assertNotIn("response_format", request)
        self.assertEqual(response.finish_reason, "tool_calls")
        self.assertEqual(response.assistant_message["tool_calls"][0]["id"], "call-original-groq")

    def test_sdk_nao_recebe_retries_automaticos(self):
        fake_client = SimpleNamespace()
        with patch("backend.ai.groq_provider.AsyncGroq", return_value=fake_client) as factory:
            provider = GroqProvider(
                api_key="chave-de-teste",
                model="openai/gpt-oss-120b",
            )
        self.assertIs(provider._client, fake_client)
        self.assertEqual(factory.call_args.kwargs["max_retries"], 0)

    def test_resposta_com_multiplas_tools_eh_bloqueada(self):
        calls = [
            SimpleNamespace(
                id=f"call-{index}",
                function=SimpleNamespace(name="get_factory_status", arguments="{}"),
            )
            for index in (1, 2)
        ]
        response = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=None, tool_calls=calls),
                finish_reason="tool_calls",
            )],
            usage=None,
        )
        provider, client = self.provider([response])
        with self.assertRaises(AIProviderError) as caught:
            asyncio.run(provider.complete([], tools=[self.schema()]))
        self.assertEqual(caught.exception.code, "groq_parallel_tool_calls_rejected")
        self.assertEqual(len(client.completions.requests), 1)

    def test_mapeia_timeout_rate_limit_autenticacao_e_erro_geral(self):
        errors = [
            (type("APITimeoutError", (Exception,), {})(), "groq_timeout"),
            (type("AuthenticationError", (Exception,), {})(), "groq_authentication_failed"),
            (RuntimeError("falha"), "groq_invalid_response"),
        ]
        for error, expected in errors:
            with self.subTest(expected=expected):
                provider, _client = self.provider([error])
                with self.assertRaises(AIProviderError) as caught:
                    asyncio.run(provider.complete([], tools=[]))
                self.assertEqual(caught.exception.code, expected)

    def test_tool_use_failed_tem_somente_um_retry_e_log_seguro(self):
        failed = _api_error(
            "BadRequestError",
            400,
            body={
                "error": {
                    "type": "invalid_request_error",
                    "code": "tool_use_failed",
                    "failed_generation": {
                        "reason": "Tool call arguments are not valid JSON",
                        "tool_name": "get_factory_status",
                        "attempted_arguments": "SEGREDO_INDUSTRIAL_NAO_LOGAR",
                    },
                }
            },
        )
        provider, client = self.provider([
            failed,
            _completion(tool_name="get_factory_status"),
        ])
        with self.assertLogs("backend.ai.groq_provider", level="WARNING") as captured:
            response = asyncio.run(provider.complete(
                [{"role": "user", "content": "Como está a fábrica?"}],
                tools=[self.schema()],
                request_id="req-seguro-1",
            ))
        self.assertEqual(len(client.completions.requests), 2)
        self.assertEqual(response.finish_reason, "tool_calls")
        self.assertLessEqual(client.completions.requests[1]["temperature"], 0.1)
        self.assertEqual(
            client.completions.requests[1]["tools"],
            client.completions.requests[0]["tools"],
        )
        self.assertIn("objeto JSON válido", client.completions.requests[1]["messages"][-1]["content"])
        safe_log = " ".join(captured.output)
        self.assertIn("req-seguro-1", safe_log)
        self.assertIn("get_factory_status", safe_log)
        self.assertNotIn("SEGREDO_INDUSTRIAL_NAO_LOGAR", safe_log)

        provider, client = self.provider([failed, failed])
        with self.assertRaises(AIProviderError) as caught:
            asyncio.run(provider.complete([], tools=[self.schema()], request_id="req-2"))
        self.assertEqual(caught.exception.code, "groq_tool_use_failed")
        self.assertEqual(
            caught.exception.user_message,
            "Não foi possível consultar os dados necessários neste momento.",
        )
        self.assertEqual(len(client.completions.requests), 2)

    def test_rate_limit_nao_repete_e_respeita_retry_after(self):
        clock = [100.0]
        rate_limit = _api_error(
            "RateLimitError",
            429,
            headers={
                "retry-after": "5",
                "x-ratelimit-remaining-tokens": "0",
                "x-ratelimit-reset-tokens": "5s",
            },
        )
        provider, client = self.provider(
            [rate_limit, _completion(content="liberado")],
            monotonic_func=lambda: clock[0],
        )
        with self.assertRaises(AIProviderError) as caught:
            asyncio.run(provider.complete([], tools=[]))
        self.assertEqual(caught.exception.code, "groq_rate_limited")
        self.assertEqual(
            caught.exception.user_message,
            "Limite temporário da IA atingido. Aguarde alguns segundos e tente novamente.",
        )
        self.assertEqual(caught.exception.technical_details["retry_after"], "5")
        self.assertEqual(len(client.completions.requests), 1)

        with self.assertRaises(AIProviderError):
            asyncio.run(provider.complete([], tools=[]))
        self.assertEqual(len(client.completions.requests), 1)

        clock[0] += 5.1
        response = asyncio.run(provider.complete([], tools=[]))
        self.assertEqual(response.content, "liberado")
        self.assertEqual(len(client.completions.requests), 2)

    def test_413_eh_request_token_limit_e_nao_repete(self):
        too_large = _api_error(
            "APIStatusError",
            413,
            body={
                "error": {
                    "code": "rate_limit_exceeded",
                    "type": "tokens",
                    "message": "Limit: 8000 TPM Requested: 9473 tokens",
                }
            },
        )
        provider, client = self.provider([too_large, _completion(content="não deve chamar")])
        with self.assertRaises(AIProviderError) as caught:
            asyncio.run(provider.complete([], tools=[]))
        self.assertEqual(caught.exception.code, "request_token_limit")
        self.assertFalse(caught.exception.retryable)
        self.assertEqual(
            caught.exception.user_message,
            "A consulta reuniu dados demais para o limite atual da IA.",
        )
        self.assertEqual(caught.exception.technical_details["limit_tokens"], 8000)
        self.assertEqual(caught.exception.technical_details["requested_tokens"], 9473)
        self.assertEqual(len(client.completions.requests), 1)

    def test_cancelamento_eh_propagado(self):
        provider, _client = self.provider([asyncio.CancelledError()])
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(provider.complete([], tools=[]))


class AISettingsTests(unittest.TestCase):
    def test_defaults_de_budget_e_completion(self):
        settings = WebSettings.from_env({
            "GESTOR_WEB_ENV": "test",
            "GESTOR_WEB_SESSION_SECRET": "test-secret-that-is-long-enough-for-session-signatures-123456",
        })
        self.assertEqual(settings.ai_max_completion_tokens, 640)
        self.assertEqual(settings.ai_request_token_budget, 6_000)
        self.assertEqual(settings.ai_tool_result_max_chars, 10_000)

    def test_variaveis_sao_validadas_e_a_chave_nao_aparece_no_repr(self):
        settings = WebSettings.from_env({
            "GESTOR_WEB_ENV": "test",
            "GESTOR_WEB_SESSION_SECRET": "test-secret-that-is-long-enough-for-session-signatures-123456",
            "GESTOR_AI_ENABLED": "true",
            "GROQ_API_KEY": "segredo-local-de-teste",
            "GESTOR_AI_MODEL": "openai/gpt-oss-120b",
            "GESTOR_AI_REASONING_EFFORT": "high",
            "GESTOR_AI_TEMPERATURE": "0.1",
            "GESTOR_AI_MAX_COMPLETION_TOKENS": "1024",
            "GESTOR_AI_MAX_TOOL_ROUNDS": "4",
            "GESTOR_AI_MAX_HISTORY_MESSAGES": "12",
            "GESTOR_AI_TIMEOUT_SECONDS": "30",
        })
        self.assertTrue(settings.ai_enabled)
        self.assertTrue(settings.ai_configured)
        self.assertEqual(settings.ai_reasoning_effort, "high")
        self.assertEqual(settings.ai_max_tool_rounds, 4)
        self.assertNotIn("segredo-local-de-teste", repr(settings))

        with self.assertRaises(RuntimeError):
            WebSettings.from_env({
                "GESTOR_WEB_ENV": "test",
                "GESTOR_WEB_SESSION_SECRET": "test-secret-that-is-long-enough-for-session-signatures-123456",
                "GESTOR_AI_REASONING_EFFORT": "extremo",
            })

    def test_entrypoint_residencial_carrega_configuracao_da_ia_do_env(self):
        local_values = {
            "POSTGRES_USER": "usuario-teste",
            "POSTGRES_PASSWORD": "senha-teste",
            # O entrypoint residencial exige o banco dedicado explicitamente;
            # não existe mais default embutido apontando para um banco real.
            "GESTOR_RESIDENCE_SIMULATION_DATABASE": "gestor_pecas_test_simulacao_exemplo",
            "GROQ_API_KEY": "chave-somente-de-teste",
            "GESTOR_AI_ENABLED": "true",
        }
        with patch.dict(os.environ, {}, clear=True), patch(
            "scripts.run_simulacao_residencia.dotenv_values",
            return_value=local_values,
        ):
            target = configure_environment()
            self.assertEqual(target["host"], "127.0.0.1")
            self.assertEqual(target["port"], "15432")
            self.assertEqual(os.environ["GROQ_API_KEY"], "chave-somente-de-teste")
            self.assertEqual(os.environ["GESTOR_AI_ENABLED"], "true")


class AIRateLimitStateTests(unittest.TestCase):
    def test_cooldown_usa_retry_after_e_finaliza_pela_autoridade_backend(self):
        clock = [datetime(2026, 8, 25, 10, 0, tzinfo=timezone(timedelta(hours=-3)))]
        state = AIRateLimitState(now=lambda: clock[0])
        active = state.activate({"retry_after": "5", "reset_tokens": "1m"})
        self.assertTrue(active["active"])
        self.assertEqual(active["retry_after_seconds"], 5)
        self.assertEqual(active["blocked_until"], "2026-08-25T10:00:05-03:00")

        clock[0] += timedelta(seconds=6)
        finished = state.snapshot()
        self.assertFalse(finished["active"])
        self.assertEqual(finished["retry_after_seconds"], 0)
        self.assertIsNone(finished["blocked_until"])

    def test_cooldown_usa_reset_do_backend_e_fallback_seguro(self):
        clock = [datetime(2026, 8, 25, 10, 0, tzinfo=timezone.utc)]
        state = AIRateLimitState(fallback_seconds=17, now=lambda: clock[0])
        self.assertEqual(
            state.activate({"reset_tokens": "1m2s"})["retry_after_seconds"],
            62,
        )
        clock[0] += timedelta(seconds=70)
        self.assertEqual(state.activate({})["retry_after_seconds"], 17)


def ai_settings(*, enabled=True, api_key="chave-local-de-teste"):
    return WebSettings(
        environment="test",
        session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
        allowed_hosts=("testserver",),
        allowed_origins=("http://testserver",),
        ai_enabled=enabled,
        ai_api_key=api_key,
    )


class AIApiTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.manager_id = self.db.criar_usuario("Gestor IA", "senha-ia", "gestor")
        self.other_id = self.db.criar_usuario("Outro Gestor", "senha-outro", "gestor")
        self.db.criar_usuario("Operador IA", "senha-operador", "operador_dobra")
        self.app = create_app(settings=ai_settings(), database_factory=lambda: self.db)
        self.app.state.ai_provider = FakeProvider(
            plans=[
                tool_response("get_management_overview"),
                AIProviderResponse(content="Fábrica consultada."),
            ],
            chunks=["Fábrica ", "consultada."],
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()

    def login(self, username="Gestor IA", password="senha-ia"):
        response = self.client.post("/api/v1/auth/login", json={"username": username, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def csrf(self):
        return {"X-CSRF-Token": self.client.cookies.get("gestor_csrf")}

    def test_status_exige_gestor_e_nunca_expoe_chave(self):
        self.assertEqual(self.client.get("/api/v1/ai/status").status_code, 401)
        self.login("Operador IA", "senha-operador")
        self.assertEqual(self.client.get("/api/v1/ai/status").status_code, 403)
        self.login()
        response = self.client.get("/api/v1/ai/status")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["configured"])
        serialized = json.dumps(response.json()).casefold()
        self.assertNotIn("api_key", serialized)
        self.assertNotIn("chave-local", serialized)
        self.assertEqual(
            response.json()["cooldown"],
            {"active": False, "retry_after_seconds": 0, "blocked_until": None},
        )

    def test_429_publica_cooldown_estruturado_e_bloqueia_nova_chamada(self):
        self.app.state.ai_provider = FakeProvider(
            stream_error=AIProviderError(
                "groq_rate_limited",
                "mensagem técnica do provider",
                retryable=True,
                technical_details={
                    "retry_after": "37",
                    "remaining_tokens": "0",
                    "reset_tokens": "37s",
                    "api_key": "SEGREDO_NAO_EXPOR",
                },
            )
        )
        self.login()
        created = self.client.post("/api/v1/ai/conversations", headers=self.csrf(), json={}).json()
        first = self.client.post(
            f"/api/v1/ai/conversations/{created['id']}/messages",
            headers=self.csrf(),
            json={"content": "Olá"},
        )
        self.assertEqual(first.status_code, 200)
        self.assertIn('"code":"rate_limit"', first.text)
        self.assertIn('"retry_after_seconds":37', first.text)
        self.assertIn('"blocked_until":', first.text)
        self.assertNotIn("groq", first.text.casefold())
        self.assertNotIn("SEGREDO_NAO_EXPOR", first.text)

        status = self.client.get("/api/v1/ai/status").json()
        self.assertTrue(status["cooldown"]["active"])
        self.assertGreater(status["cooldown"]["retry_after_seconds"], 0)
        calls_before = len(self.app.state.ai_provider.stream_messages)
        blocked = self.client.post(
            f"/api/v1/ai/conversations/{created['id']}/messages",
            headers=self.csrf(),
            json={"content": "Outra pergunta"},
        )
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["code"], "rate_limit")
        self.assertTrue(blocked.json()["details"]["retryable"])
        self.assertIn("blocked_until", blocked.json()["details"])
        self.assertEqual(len(self.app.state.ai_provider.stream_messages), calls_before)
        serialized = json.dumps(blocked.json())
        self.assertNotIn("SEGREDO_NAO_EXPOR", serialized)
        self.assertNotIn("remaining_tokens", serialized)

    def test_413_publica_consulta_grande_sem_iniciar_cooldown(self):
        self.app.state.ai_provider = FakeProvider(
            stream_error=AIProviderError(
                "request_token_limit",
                "mensagem técnica",
                retryable=False,
                technical_details={"requested_tokens": 9473, "api_key": "SEGREDO_NAO_EXPOR"},
            )
        )
        self.login()
        created = self.client.post("/api/v1/ai/conversations", headers=self.csrf(), json={}).json()
        response = self.client.post(
            f"/api/v1/ai/conversations/{created['id']}/messages",
            headers=self.csrf(),
            json={"content": "Olá"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('"code":"request_token_limit"', response.text)
        self.assertIn('"retryable":false', response.text)
        self.assertNotIn("SEGREDO_NAO_EXPOR", response.text)
        self.assertFalse(self.client.get("/api/v1/ai/status").json()["cooldown"]["active"])

    def test_conversa_csrf_persistencia_streaming_e_reabertura(self):
        self.login()
        denied = self.client.post("/api/v1/ai/conversations", json={})
        self.assertEqual(denied.status_code, 403)
        created = self.client.post("/api/v1/ai/conversations", headers=self.csrf(), json={})
        self.assertEqual(created.status_code, 201, created.text)
        conversation_id = created.json()["id"]
        streamed = self.client.post(
            f"/api/v1/ai/conversations/{conversation_id}/messages",
            headers=self.csrf(),
            json={"content": "Como está a fábrica agora?"},
        )
        self.assertEqual(streamed.status_code, 200, streamed.text)
        self.assertIn("event: status", streamed.text)
        self.assertIn("event: delta", streamed.text)
        self.assertIn("event: done", streamed.text)
        reopened = self.client.get(f"/api/v1/ai/conversations/{conversation_id}")
        self.assertEqual([item["role"] for item in reopened.json()["messages"]], ["user", "assistant"])
        self.assertEqual(reopened.json()["messages"][-1]["content"], "Fábrica consultada.")

    def test_idor_recusa_conversa_de_outro_usuario(self):
        self.login()
        created = self.client.post("/api/v1/ai/conversations", headers=self.csrf(), json={}).json()
        self.login("Outro Gestor", "senha-outro")
        response = self.client.get(f"/api/v1/ai/conversations/{created['id']}")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "ai_conversation_not_found")

    def test_exclusao_exige_csrf_e_respeita_proprietario(self):
        self.login()
        created = self.client.post(
            "/api/v1/ai/conversations", headers=self.csrf(), json={"title": "Excluir esta"}
        ).json()
        denied = self.client.delete(f"/api/v1/ai/conversations/{created['id']}")
        self.assertEqual(denied.status_code, 403)

        self.login("Outro Gestor", "senha-outro")
        foreign = self.client.delete(
            f"/api/v1/ai/conversations/{created['id']}", headers=self.csrf()
        )
        self.assertEqual(foreign.status_code, 404)

        self.login()
        deleted = self.client.delete(
            f"/api/v1/ai/conversations/{created['id']}", headers=self.csrf()
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(deleted.content, b"")
        self.assertEqual(
            self.client.get(f"/api/v1/ai/conversations/{created['id']}").status_code,
            404,
        )

    def test_ia_sem_chave_nao_impede_restante_da_api(self):
        app = create_app(settings=ai_settings(api_key=""), database_factory=lambda: self.db)
        with TestClient(app) as client:
            login = client.post("/api/v1/auth/login", json={"username": "Gestor IA", "password": "senha-ia"})
            self.assertEqual(login.status_code, 200)
            status = client.get("/api/v1/ai/status")
            self.assertFalse(status.json()["configured"])
            overview = client.get("/api/v1/management/overview")
            self.assertEqual(overview.status_code, 200, overview.text)

    def test_openapi_expoe_contrato_da_ia(self):
        paths = self.client.get("/api/openapi.json").json()["paths"]
        self.assertIn("/api/v1/ai/status", paths)
        self.assertIn("/api/v1/ai/conversations/{conversation_id}/messages", paths)
        self.assertIn("delete", paths["/api/v1/ai/conversations/{conversation_id}"])


if __name__ == "__main__":
    unittest.main()
