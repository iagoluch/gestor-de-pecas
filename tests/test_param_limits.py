"""Limites de tamanho em parâmetros de path/query/body (auditoria 2026-10-07, A7).

Strings enormes não podem chegar a ILIKE/= no PostgreSQL: o limite estourado
responde 422 padrão do FastAPI antes de qualquer acesso ao banco.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.main import create_app
from backend.api.schemas.auth import SessionUser
from backend.api.config import WebSettings
from tests.test_chamadas import _FakeChamadaDatabase

BIG = "A" * 500
API = "/api/v1"

_ADMIN = SessionUser(
    id=3, name="Admin Z", role="admin",
    management_access=True, andon_access=True, operator_access=True,
)

# (descrição, método, rota, kwargs do request)
_REJEITADOS = [
    ("path op do operador", "get", f"/operator/operations/{BIG}", {}),
    ("path op do sync", "post", f"/operator/operations/{BIG}/sync", {}),
    ("path task_code", "get", f"/highlight/tasks/{BIG}", {}),
    ("path op da rastreabilidade", "get", f"/traceability/orders/{BIG}", {}),
    ("query q dos contatos", "get", "/chamadas/contatos", {"params": {"q": BIG}}),
    ("query setor dos contatos", "get", "/chamadas/contatos", {"params": {"setor": BIG}}),
    ("query recipient", "get", "/management/internal-alerts", {"params": {"recipient": BIG}}),
    ("query sector da primeira peça", "get", "/management/first-pieces", {"params": {"sector": BIG}}),
    (
        "query do histórico de tempo padrão",
        "get",
        "/management/standard-times/manual/history",
        {"params": {"produto_codigo": BIG, "numero_operacao": "10", "codigo_recurso": "R"}},
    ),
    (
        "query do DELETE de tempo padrão",
        "delete",
        "/management/standard-times/manual",
        {"params": {"produto_codigo": "P", "numero_operacao": "10", "codigo_recurso": BIG}},
    ),
    (
        "nome do nível na exclusão (SEC-06)",
        "delete",
        "/management/levels/" + "n" * 61,
        {},
    ),
    (
        "body setores com item grande",
        "post",
        "/chamadas/admin/contatos",
        {"json": {"nome": "N", "funcao": "F", "setores": [BIG]}},
    ),
    (
        "body setores com itens demais",
        "post",
        "/chamadas/admin/contatos",
        {"json": {"nome": "N", "funcao": "F", "setores": [f"S{i}" for i in range(21)]}},
    ),
]


class ParamLimitTests(unittest.TestCase):
    def setUp(self):
        self.db = _FakeChamadaDatabase()
        settings = WebSettings(
            environment="test",
            session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
            allowed_hosts=("testserver",),
            allowed_origins=("http://testserver",),
        )
        self.facade = MagicMock()
        self.facade.rastreabilidade.return_value = {"op": "OP1"}
        app = create_app(settings=settings, database_factory=lambda: self.db)
        app.dependency_overrides[get_database] = lambda: self.db
        app.dependency_overrides[get_frontend_facade] = lambda: self.facade
        app.dependency_overrides[require_csrf] = lambda: None
        app.dependency_overrides[get_current_user] = lambda: _ADMIN
        self.client = TestClient(app)

    def test_valores_acima_do_limite_dao_422(self):
        for descricao, metodo, rota, kwargs in _REJEITADOS:
            with self.subTest(descricao):
                resposta = getattr(self.client, metodo)(API + rota, **kwargs)
                self.assertEqual(resposta.status_code, 422, resposta.text[:200])

    def test_valor_normal_continua_passando(self):
        contatos = self.client.get(
            f"{API}/chamadas/contatos", params={"q": "Fulano", "setor": "Corte"}
        )
        self.assertEqual(contatos.status_code, 200)

        rastreio = self.client.get(f"{API}/traceability/orders/PCMIXQ01001")
        self.assertEqual(rastreio.status_code, 200)
        self.facade.rastreabilidade.assert_called_once_with("PCMIXQ01001")

        setores = self.client.post(
            f"{API}/chamadas/admin/contatos",
            json={"nome": "Beltrano", "funcao": "Líder", "setores": ["Corte", "Solda"]},
        )
        self.assertEqual(setores.status_code, 200, setores.text[:200])


if __name__ == "__main__":
    unittest.main()
