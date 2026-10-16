"""Chat da IA no painel de explicação: o servidor injeta a árvore recalculada.

Provedor falso (o mesmo de ``tests/test_ai``) e o repositório em memória do
endpoint de explicação; as conversas da IA vêm do ``FakeDatabase``.
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import create_app
from mes.ai.context_budget import estimate_tokens
from mes.ai.explanation_context import EXPLANATION_INSTRUCTION, build_explanation_context
from mes.ai.prompts.system_prompt import BASE_SYSTEM_PROMPT
from tests.fakes import FakeDatabase
from tests.test_ai import FakeProvider, ai_settings
from tests.test_explanation_endpoint import PERIOD, _Repo, _user

CONVERSATIONS = "/api/v1/ai/conversations"
REF = {"metric": "tempo.sem_demanda", "filters": dict(PERIOD)}


class _AiRepo(_Repo):
    """Repositório de explicação + conversas da IA em memória."""

    def __init__(self):
        super().__init__()
        self._ai = FakeDatabase()

    def close(self):
        return None

    def __getattr__(self, name):
        if name.startswith("_") or "_ia" not in name:
            raise AttributeError(name)
        return getattr(self._ai, name)


class _Case(unittest.TestCase):
    def setUp(self):
        self.db = _AiRepo()
        self.provider = FakeProvider(chunks=["Resposta ", "da IA."])
        self.app = create_app(settings=ai_settings(), database_factory=lambda: self.db)
        self.app.state.ai_provider = self.provider
        self.app.dependency_overrides[get_database] = lambda: self.db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self._as("gestor", management=True)

    def _as(self, role, *, management):
        self.app.dependency_overrides[get_current_user] = lambda: _user(role, management=management)

    def _ask(self, content="Por que a DOBRA1 está sem demanda?", **body):
        created = self.client.post(CONVERSATIONS, json={})
        self.assertEqual(created.status_code, 201, created.text)
        return self.client.post(
            f"{CONVERSATIONS}/{created.json()['id']}/messages",
            json={"content": content, **body},
        )

    def _system(self):
        self.assertEqual(len(self.provider.stream_messages), 1)
        messages, tools, _choice = self.provider.stream_messages[0]
        return messages, tools


class ExplanationAiContextTests(_Case):
    def test_context_contains_tree_values(self):
        response = self._ask(explanation=REF)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("event: done", response.text)
        messages, tools = self._system()
        system = messages[0]["content"]
        self.assertEqual(messages[-1], {"role": "user", "content": "Por que a DOBRA1 está sem demanda?"})
        self.assertEqual(tools, [])
        self.assertIn("Recurso sem demanda", system)
        self.assertIn("Total: 1h", system)
        self.assertIn("Dobra", system)
        self.assertIn("DOBRA1", system)
        self.assertIn("Regra:", system)

    def test_system_instruction_restricts_to_explanation(self):
        self._ask(explanation=REF)
        system = self._system()[0][0]["content"]
        self.assertTrue(system.startswith(BASE_SYSTEM_PROMPT))
        self.assertIn(EXPLANATION_INSTRUCTION, system)
        self.assertIn("SOMENTE", system)
        self.assertIn("não sei", system)
        self.assertIn("Rastreabilidade da OP", system)
        self.assertNotIn("TRUNCATED:", system)

    def test_truncated_tree_adds_warning_instruction(self):
        tree = {
            "metric": "tempo.producao", "label": "Produção", "total_seconds": 7200,
            "average_seconds": None, "resource_count": 1, "day_count": 1,
            "reason": "r", "rule": "regra", "excluded": [], "notes": [],
            "truncated": True,
            "children": [{"kind": "sector", "label": "Corte", "seconds": 7200,
                          "truncated": True, "detail": None, "children": []}],
        }
        text = build_explanation_context(tree, max_tokens=4000)
        self.assertIn("TRUNCATED:", text)
        self.assertIn("avise o usuário explicitamente", text)

    def test_client_cannot_inject_tree(self):
        for extra in ({"children": []}, {"total_seconds": 1}, {"tree": {"x": 1}}):
            response = self._ask(explanation={**REF, **extra})
            self.assertEqual(response.status_code, 422, extra)
        response = self._ask(explanation={**REF, "filters": {**REF["filters"], "children": []}})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.provider.stream_messages, [])

    def test_unknown_metric_is_422_before_the_provider(self):
        response = self._ask(explanation={"metric": "tempo.inexistente", "filters": dict(PERIOD)})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "unknown_metric")
        self.assertEqual(self.provider.stream_messages, [])

    def test_non_management_gets_403_and_provider_is_never_called(self):
        created = self.client.post(CONVERSATIONS, json={}).json()
        self._as("operador_dobra", management=False)
        response = self.client.post(
            f"{CONVERSATIONS}/{created['id']}/messages",
            json={"content": "Oi", "explanation": REF},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.provider.stream_messages, [])
        self.assertEqual(self.provider.complete_messages, [])

    def test_payload_without_explanation_keeps_the_original_messages(self):
        response = self._ask(content="Olá")
        self.assertEqual(response.status_code, 200, response.text)
        messages, _tools = self._system()
        self.assertEqual(
            messages,
            [
                {"role": "system", "content": BASE_SYSTEM_PROMPT},
                {"role": "user", "content": "Olá"},
            ],
        )


class ExplanationContextBudgetTests(unittest.TestCase):
    @staticmethod
    def _big_tree():
        resources = []
        for r in range(40):
            stretches = [
                {"kind": "stretch", "label": f"{h:02d}:00 → {h:02d}:30", "seconds": 1800.0 + h,
                 "children": [], "truncated": False,
                 "detail": {"who": None, "motivo": "sem OP apontada", "origin": "estado_recurso"}}
                for h in range(24)
            ]
            resources.append({"kind": "resource", "label": f"RECURSO{r:02d}", "seconds": 43200.0 + r,
                              "children": stretches, "truncated": False, "detail": None})
        sector = {"kind": "sector", "label": "Corte", "seconds": 1_800_000.0,
                  "children": resources, "truncated": False, "detail": None}
        return {
            "metric": "tempo.sem_demanda", "label": "Recurso sem demanda",
            "total_seconds": 1_800_000.0, "average_seconds": 45000.0, "resource_count": 40,
            "day_count": 1, "reason": "Sem OP.", "rule": "Regra do recurso sem demanda.",
            "excluded": [{"label": f"Item {i}", "seconds": 60, "reason": "fora da linha"} for i in range(30)],
            "notes": [], "truncated": False, "children": [sector],
        }

    def test_context_respects_token_budget(self):
        tree = self._big_tree()
        full = build_explanation_context(tree, max_tokens=10**9)
        self.assertGreater(estimate_tokens(full), 3000)
        self.assertNotIn("CONTEXTO REDUZIDO:", full)
        for budget in (3000, 1500, 800):
            text = build_explanation_context(tree, max_tokens=budget)
            self.assertLessEqual(estimate_tokens(text), budget, budget)
            self.assertIn("CONTEXTO REDUZIDO:", text)
            self.assertIn("Total: 500h", text)
            self.assertIn("outros", text)

    def test_service_keeps_whole_request_within_request_token_budget(self):
        from mes.ai.context_budget import estimate_request_tokens

        settings = ai_settings()
        provider = FakeProvider(chunks=["ok"])
        db = _AiRepo()
        app = create_app(settings=settings, database_factory=lambda: db)
        app.state.ai_provider = provider
        app.dependency_overrides[get_database] = lambda: db
        app.dependency_overrides[require_csrf] = lambda: None
        app.dependency_overrides[get_current_user] = lambda: _user("gestor", management=True)
        from backend.api.routers import ai as ai_router

        original = ai_router.explain_for_user
        ai_router.explain_for_user = lambda *_a, **_k: self._big_tree()
        try:
            with TestClient(app) as client:
                created = client.post(CONVERSATIONS, json={}).json()
                response = client.post(
                    f"{CONVERSATIONS}/{created['id']}/messages",
                    json={"content": "Resuma", "explanation": REF},
                )
        finally:
            ai_router.explain_for_user = original
        self.assertEqual(response.status_code, 200, response.text)
        messages = provider.stream_messages[0][0]
        used = estimate_request_tokens(messages, [], settings.ai_max_completion_tokens)
        self.assertLessEqual(used, settings.ai_request_token_budget)
        self.assertIn("CONTEXTO REDUZIDO:", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
