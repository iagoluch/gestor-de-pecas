"""Aba gerencial de cotas padrão da Qualidade (06/10/2026).

Nível ``qualidade`` (conta do Sandro), listagem sob ``/management`` e edição pelo
endpoint existente ``POST /quality/templates``. O SQL real da listagem é coberto
por ``QualityTemplateListingPostgresTests`` (schema descartável de
``TEST_DATABASE_URL``).
"""

from __future__ import annotations

from datetime import datetime
import os
import unittest
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.core.permissions import (
    CONSULTATION_TABS_BY_LEVEL,
    MANAGEMENT_WEB_LEVELS,
    NAVIGATION_BY_LEVEL,
    USER_LEVELS,
    can_access_management_web,
    can_manage_quality_template,
    can_manage_quality_templates,
    consultation_tabs_for_level,
    navigation_for_level,
    normalize_user_level,
)
from app.database.config import load_postgres_config
from app.database.database import Database
from backend.api.config import WebSettings
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import create_app
from backend.api.schemas.auth import SessionUser
from mes.services.display_labels import role_label
from tests.fakes import FakeDatabase

URL = "/api/v1/management/quality-templates"


def _settings():
    return WebSettings(
        environment="test",
        session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
        allowed_hosts=("testserver",),
        allowed_origins=("http://testserver",),
    )


def _user(role, uid=5):
    return SessionUser(
        id=uid,
        name=f"Conta {role}",
        role=role,
        management_access=can_access_management_web(role),
        andon_access=True,
        operator_access=role.startswith("operador_"),
    )


def _cotas(*padroes):
    return [{"sequencia": i, "descricao": None, "padrao": p} for i, p in enumerate(padroes, 1)]


class QualidadeLevelTests(unittest.TestCase):
    def test_qualidade_comporta_se_como_gestor_nas_leituras(self):
        self.assertIn("qualidade", USER_LEVELS)
        self.assertEqual(normalize_user_level("Qualidade"), "qualidade")
        self.assertIn("qualidade", MANAGEMENT_WEB_LEVELS)
        self.assertTrue(can_access_management_web("qualidade"))
        self.assertEqual(NAVIGATION_BY_LEVEL["qualidade"], NAVIGATION_BY_LEVEL["gestor"])
        self.assertEqual(navigation_for_level("qualidade"), navigation_for_level("gestor"))
        self.assertEqual(
            CONSULTATION_TABS_BY_LEVEL["qualidade"], CONSULTATION_TABS_BY_LEVEL["gestor"]
        )
        self.assertEqual(
            consultation_tabs_for_level("qualidade"), consultation_tabs_for_level("gestor")
        )
        self.assertEqual(role_label("qualidade"), "Qualidade")

    def test_listagem_so_qualidade_e_admin_mas_edicao_inclui_supervisor_e_lider(self):
        for level in ("qualidade", "admin"):
            self.assertTrue(can_manage_quality_templates(level), level)
        for level in ("gestor", "supervisor", "lider", "manufatura", "diretoria", "operador_dobra"):
            self.assertFalse(can_manage_quality_templates(level), level)
        for level in ("qualidade", "admin", "supervisor", "lider"):
            self.assertTrue(can_manage_quality_template(level), level)
        for level in ("gestor", "manufatura", "diretoria", "operador_dobra"):
            self.assertFalse(can_manage_quality_template(level), level)


class QualityTemplatesApiTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.db.catalog_operations.append(
            {"codigo_op": "OP1", "produto_codigo": "PROD-B", "produto_descricao": "Suporte B"}
        )
        self.app = create_app(settings=_settings(), database_factory=lambda: self.db)
        self.app.dependency_overrides[get_database] = lambda: self.db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def _as(self, role, uid=5):
        self.app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    def _salvar(self, produto, *padroes):
        return self.client.post(
            "/api/v1/quality/templates", json={"produto": produto, "cotas": _cotas(*padroes)}
        )

    def test_listagem_403_para_nao_autorizados_e_200_para_qualidade_e_admin(self):
        for role in ("gestor", "supervisor", "lider", "manufatura", "diretoria", "operador_dobra"):
            self._as(role)
            negado = self.client.get(URL)
            self.assertEqual(negado.status_code, 403, role)
            self.assertEqual(negado.json()["code"], "quality_templates_access_denied", role)
        for role in ("qualidade", "admin"):
            self._as(role)
            self.assertEqual(self.client.get(URL).status_code, 200, role)

    def test_contrato_da_listagem(self):
        self._as("operador_dobra")
        self.assertEqual(self._salvar("PROD-A", "10", "20").status_code, 200)
        self.assertEqual(self._salvar("PROD-B", "30").status_code, 200)
        self._as("qualidade")
        corpo = self.client.get(URL).json()
        self.assertEqual((corpo["total"], corpo["limit"], corpo["offset"]), (2, 100, 0))
        a, b = corpo["items"]
        self.assertEqual(
            set(a),
            {"produto_codigo", "produto_descricao", "revisao", "quantidade_cotas",
             "atualizado_por", "atualizado_em", "ativo"},
        )
        self.assertEqual((a["produto_codigo"], a["quantidade_cotas"], a["revisao"]), ("PROD-A", 2, 1))
        self.assertIsNone(a["produto_descricao"])
        self.assertEqual(b["produto_descricao"], "Suporte B")
        self.assertEqual(a["atualizado_por"], "Conta operador_dobra")
        self.assertTrue(a["ativo"])

    def test_busca_parcial_paginacao_e_validacao(self):
        self._as("operador_dobra")
        for produto in ("AAA-1", "AAA-2", "BBB-1"):
            self._salvar(produto, "1")
        self._as("admin")
        self.assertEqual(self.client.get(URL, params={"produto": "aaa"}).json()["total"], 2)
        pagina = self.client.get(URL, params={"limit": 1, "offset": 1}).json()
        self.assertEqual([i["produto_codigo"] for i in pagina["items"]], ["AAA-2"])
        self.assertEqual((pagina["total"], pagina["limit"], pagina["offset"]), (3, 1, 1))
        for params in ({"limit": 0}, {"limit": 501}, {"offset": -1}):
            erro = self.client.get(URL, params=params)
            self.assertEqual(erro.status_code, 422, params)
            self.assertEqual(erro.json()["code"], "validation_error")

    def test_qualidade_edita_template_salvo_e_operador_continua_barrado(self):
        self._as("operador_dobra", uid=11)
        self.assertEqual(self._salvar("PROD-A", "125,0").status_code, 200)
        barrado = self._salvar("PROD-A", "999,0")
        self.assertEqual(barrado.status_code, 409)
        self.assertEqual(barrado.json()["code"], "qualidade_template_protegido")

        self._as("qualidade", uid=22)
        lido = self.client.get("/api/v1/quality/templates/PROD-A")
        self.assertEqual(lido.status_code, 200, lido.text)
        self.assertTrue(lido.json()["can_edit"])
        editado = self._salvar("PROD-A", "130,0", "40,0")
        self.assertEqual(editado.status_code, 200, editado.text)
        self.assertEqual(editado.json()["data"]["revisao"], 2)
        item = self.client.get(URL).json()["items"][0]
        self.assertEqual((item["revisao"], item["quantidade_cotas"]), (2, 2))
        self.assertEqual(item["atualizado_por"], "Conta qualidade")
        contexto = self.client.get("/api/v1/quality/context").json()
        self.assertTrue(contexto["can_edit_template"])
        self.assertFalse(contexto["available"])

    def test_gestor_continua_sem_acesso_ao_cadastro_de_cotas(self):
        self._as("gestor")
        self.assertEqual(self.client.get("/api/v1/quality/templates/PROD-A").status_code, 403)
        self.assertEqual(self._salvar("PROD-A", "1").status_code, 403)

    def test_gestao_de_usuarios_aceita_qualidade(self):
        self._as("admin", uid=900)
        criado = self.client.post(
            "/api/v1/management/users",
            json={"nome": "Sandro", "nivel": "qualidade", "ativo": True, "senha": "senha-forte-123"},
        )
        self.assertEqual(criado.status_code, 200, criado.text)
        self.assertEqual(criado.json()["item"]["nivel"], "qualidade")
        niveis = self.client.get("/api/v1/management/users").json()["levels"]
        self.assertIn("qualidade", niveis)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class QualityTemplateListingPostgresTests(unittest.TestCase):
    AGORA = datetime(2026, 10, 6, 9, 0)

    def setUp(self):
        base = load_postgres_config(testing=True)
        self.admin_dsn = base.dsn
        self.schema = "cotas_padrao_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self._drop_schema)
        self.db = Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}"))

    def _drop_schema(self):
        db = getattr(self, "db", None)
        if db is not None:
            db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _salvar(self, produto, *padroes, nova_revisao=False, descricao=None):
        return self.db.salvar_template_qualidade(
            produto, _cotas(*padroes), produto_descricao=descricao, usuario_nome="Sandro",
            agora=self.AGORA, nova_revisao=nova_revisao,
        )

    def test_listagem_conta_cotas_ativas_busca_e_descricao_do_catalogo(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO catalogo_pcp_ops (codigo_op, produto_codigo, produto_descricao,"
                " quantidade, data_emissao, local_estoque, sincronizado_em)"
                " VALUES ('OP1', 'PRD_B', 'Suporte B', 1, %s, '01', %s)",
                (self.AGORA.date(), self.AGORA),
            )
            cursor.execute(
                "INSERT INTO catalogo_operacoes_op (codigo_op, produto_codigo, produto_descricao,"
                " numero_operacao, codigo_recurso, descricao_operacao, tipo_setor, ordem,"
                " sincronizado_em) VALUES ('OP1', 'PRD_B', 'Suporte B', '10', 'DOBRA1',"
                " 'DOBRA', 'Dobra', 1, %s)",
                (self.AGORA,),
            )
        self._salvar("PRD_A", "1", "2", "3", descricao="Própria A")
        self._salvar("PRD_A", "1", "2", nova_revisao=True)  # cota 3 inativada, revisão 2
        self._salvar("PRD_B", "9")
        self._salvar("PRDXB", "9")  # '_' da busca não pode virar curinga

        tudo = self.db.listar_templates_qualidade()
        self.assertEqual(tudo["total"], 3)
        # A ordem segue o collation do banco (que pode ignorar '_'): compara por código.
        por_codigo = {i["produto_codigo"]: i for i in tudo["items"]}
        a, b, c = por_codigo["PRD_A"], por_codigo["PRD_B"], por_codigo["PRDXB"]
        self.assertEqual((a["revisao"], a["quantidade_cotas"]), (2, 2))
        self.assertEqual(a["produto_descricao"], "Própria A")
        self.assertEqual(
            (a["atualizado_por"], a["atualizado_em"], a["ativo"]), ("Sandro", self.AGORA, True)
        )
        self.assertEqual(b["produto_descricao"], "Suporte B")
        self.assertIsNone(c["produto_descricao"])

        filtrado = self.db.listar_templates_qualidade(produto="d_b")
        self.assertEqual([i["produto_codigo"] for i in filtrado["items"]], ["PRD_B"])
        self.assertEqual(filtrado["total"], 1)
        ordem = [i["produto_codigo"] for i in tudo["items"]]
        pagina = self.db.listar_templates_qualidade(limite=1, deslocamento=2)
        self.assertEqual([i["produto_codigo"] for i in pagina["items"]], ordem[2:])
        self.assertEqual(pagina["total"], 3)
        self.assertEqual(self.db.listar_templates_qualidade(produto="%")["total"], 0)


if __name__ == "__main__":
    unittest.main()
