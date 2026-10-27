"""Líder de um setor não lê dados de outro setor (primeira peça, alertas, OP e IA)."""

import unittest

from fastapi.testclient import TestClient

from app.core.areas import trace_in_scope
from app.core.permissions import can_access_management_web
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.main import create_app
from backend.api.schemas.auth import SessionUser
from mes.contracts import AIToolError
from mes.services.ai_tools import AIToolRegistry
from mes.services.management import ManagementService
from tests.fakes import FakeDatabase
from tests.test_rnc_decisao import _settings


def _user(role, scope=None):
    return SessionUser(
        id=900, name=f"Conta {role}", role=role,
        management_access=can_access_management_web(role),
        andon_access=True, operator_access=False, sector_scope=scope,
    )


_TRACE_PINTURA = {"operations": [{"setor": "Pintura", "setor_roteiro": "Pintura"}]}


class _Db(FakeDatabase):
    def __init__(self):
        super().__init__()
        self.pp_args = []

    def listar_primeiras_pecas(self, **kw):
        self.pp_args.append(kw)
        return []


class _Facade:
    def rastreabilidade(self, op):
        return _TRACE_PINTURA


class RotasComEscopo(unittest.TestCase):
    def _client(self, user):
        self.db = _Db()
        app = create_app(settings=_settings(), database_factory=lambda: self.db)
        app.dependency_overrides[get_database] = lambda: self.db
        app.dependency_overrides[require_csrf] = lambda: None
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_frontend_facade] = lambda: _Facade()
        return TestClient(app)

    def test_primeira_peca_lider_nao_le_outro_setor(self):
        client = self._client(_user("lider", ["Pintura"]))
        self.assertEqual(client.get("/api/v1/management/first-pieces?sector=Solda").status_code, 200)
        self.assertEqual(self.db.pp_args[-1]["tipo_setor"], "Pintura")

    def test_primeira_peca_gestor_sem_escopo_passa_o_setor(self):
        client = self._client(_user("gestor"))
        client.get("/api/v1/management/first-pieces?sector=Solda")
        self.assertEqual(self.db.pp_args[-1]["tipo_setor"], "Solda")

    def test_alertas_internos_so_do_proprio_setor(self):
        client = self._client(_user("lider", ["Pintura"]))
        for setor in ("Pintura", "Solda"):
            self.db.internal_alerts.append({
                "tipo": "PRIMEIRA_PECA", "destinatario": "PCP", "severidade": "ALTA",
                "status_notificacao": "PENDENTE", "tipo_setor": setor, "quantidade": 1,
            })
        body = client.get("/api/v1/management/internal-alerts").json()
        self.assertEqual([row["tipo_setor"] for row in body["items"]], ["Pintura"])
        self.assertEqual(sum(row["total"] for row in body["summary"]), 1)

    def test_alertas_ignoram_maiuscula_do_setor(self):
        client = self._client(_user("lider", ["Pintura"]))
        self.db.internal_alerts.append({
            "tipo": "PRIMEIRA_PECA", "destinatario": "PCP", "severidade": "ALTA",
            "status_notificacao": "PENDENTE", "tipo_setor": "PINTURA", "quantidade": 1,
        })
        self.assertEqual(len(client.get("/api/v1/management/internal-alerts").json()["items"]), 1)

    def _pausa(self, setor):
        return next(row for row in self.db.automatic_pauses if row["tipo_setor"] == setor)

    def test_lider_so_ve_e_mexe_nas_pausas_do_proprio_setor(self):
        client = self._client(_user("lider", ["Pintura"]))
        setores = {row["tipo_setor"] for row in client.get("/api/v1/management/pauses").json()["items"]}
        self.assertEqual(setores, {"Pintura"})
        nova = {"tipo_setor": "Solda", "nome": "Café", "hora_inicio": "09:00", "hora_fim": "09:10", "ordem": 9}
        self.assertEqual(client.post("/api/v1/management/pauses", json=nova).status_code, 403)
        alheia = self._pausa("Solda")
        tomada = {**nova, "id": alheia["id"], "tipo_setor": "Pintura"}
        self.assertEqual(client.post("/api/v1/management/pauses", json=tomada).status_code, 403)
        self.assertEqual(client.delete(f"/api/v1/management/pauses/{alheia['id']}").status_code, 403)
        self.assertEqual(client.delete(f"/api/v1/management/pauses/{self._pausa('Pintura')['id']}").status_code, 200)

    def test_gestor_sem_escopo_mexe_em_qualquer_pausa(self):
        client = self._client(_user("gestor"))
        alheia = self._pausa("Solda")
        self.assertEqual(client.delete(f"/api/v1/management/pauses/{alheia['id']}").status_code, 200)

    def test_op_de_outro_setor_e_recusada(self):
        self.assertEqual(
            self._client(_user("lider", ["Solda"])).get("/api/v1/traceability/orders/OP1").status_code, 403
        )
        self.assertEqual(
            self._client(_user("lider", ["Pintura"])).get("/api/v1/traceability/orders/OP1").status_code, 200
        )
        self.assertEqual(
            self._client(_user("gestor")).get("/api/v1/traceability/orders/OP1").status_code, 200
        )


class InconsistenciasDaTelaInicial(unittest.TestCase):
    def test_so_as_do_setor_filtrado(self):
        db = FakeDatabase()
        db.listar_inconsistencias_dados = lambda **_kw: [
            {"id": 1, "recurso": "LASER1"}, {"id": 2, "recurso": "Gasparini"}, {"id": 3, "recurso": None},
        ]
        service = ManagementService(db)
        self.assertEqual([row["id"] for row in service._load_open_issues("Dobra")], [2])
        self.assertEqual([row["id"] for row in service._load_open_issues(None)], [1, 2, 3])


class FerramentasDaIAComEscopo(unittest.TestCase):
    def test_setor_pedido_pela_ia_cai_no_setor_da_conta(self):
        registry = AIToolRegistry(_Facade(), sector_scope=["Pintura"])
        self.assertEqual(registry._filters({"setor": "Solda"}).setor, "Pintura")
        self.assertEqual(registry._filters({}).setor, "Pintura")
        self.assertEqual(AIToolRegistry(_Facade())._filters({"setor": "Solda"}).setor, "Solda")

    def test_ia_nao_abre_op_de_outro_setor(self):
        with self.assertRaises(AIToolError):
            AIToolRegistry(_Facade(), sector_scope=["Solda"])._trace("OP1")
        self.assertIs(AIToolRegistry(_Facade(), sector_scope=["Pintura"])._trace("OP1"), _TRACE_PINTURA)

    def test_op_vale_pelo_setor_do_roteiro(self):
        trace = {"operations": [{"setor": "Solda", "setor_roteiro": "Pintura"}]}
        self.assertTrue(trace_in_scope(trace, ["pintura"]))
        self.assertFalse(trace_in_scope({"operations": []}, ["Pintura"]))


if __name__ == "__main__":
    unittest.main()
