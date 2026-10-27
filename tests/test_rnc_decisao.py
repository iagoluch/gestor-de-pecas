"""Decisão sobre uma RNC existente (migration 67, 26/10/2026).

Sem Postgres: permissão, lista fechada (422), 404, regra do aviso e catálogo da
migration, contra um banco em memória. Com Postgres (schema descartável criado
em ``TEST_DATABASE_URL``, nunca o REAL): histórico insert-only, ausência de
efeito sobre eventos de quantidade/peça/RNC, auditoria e migration idempotente.
"""

from __future__ import annotations

import inspect
import os
import re
import unittest
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.permissions import can_access_management_web
from app.database import quality_rnc_decision_repository
from app.database.change_audit_repository import CAMPOS_AUDITAVEIS
from app.database.migrations import EXPECTED_TABLES, MIGRATIONS, SCHEMA_VERSION
from backend.api.config import WebSettings
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import create_app
from backend.api.schemas.auth import SessionUser
from backend.api.schemas.quality import QualityRncDecisionRequest
from mes.services.quality_rnc_decision import DECISOES, aviso_de_contradicao
from tests.fakes import FakeDatabase

Q = "/api/v1/quality"
AGORA = datetime(2026, 10, 26, 9, 0)


def _settings():
    return WebSettings(
        environment="test",
        session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
        allowed_hosts=("testserver",),
        allowed_origins=("http://testserver",),
    )


def _user(role, uid=700, nome=None):
    return SessionUser(
        id=uid, name=nome or f"Conta {role}", role=role,
        management_access=can_access_management_web(role),
        andon_access=True, operator_access=role.startswith("operador_"),
    )


QUALIDADE = _user("qualidade", 701, "Sandro")
NAO_AUTORIZADOS = ("gestor", "supervisor", "lider", "manufatura", "diretoria", "operador_dobra")


class _ApiCase(unittest.TestCase):
    def _build(self, db):
        self.db = db
        self.app = create_app(settings=_settings(), database_factory=lambda: db)
        self.app.dependency_overrides[get_database] = lambda: db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def _as(self, role_or_user):
        user = role_or_user if isinstance(role_or_user, SessionUser) else _user(role_or_user)
        # Não substitui require_qualidade_user: a trava real é que deve negar.
        self.app.dependency_overrides[get_current_user] = lambda: user


class _BancoEmMemoria(FakeDatabase):
    """Só o que as rotas tocam; registra chamadas para provar que 403/422 nem chegam lá."""

    def __init__(self):
        super().__init__()
        self.chamadas = []
        self.rncs = {7: {"id": 7, "codigo": "RNC-1-0001", "codigo_op": "OP1", "produto_codigo": "P",
                         "numero_peca": 1, "motivo": "furo fora", "resultado_peca": "REFUGO"}}
        self.decisoes = []

    def buscar_rnc_com_resultado(self, rnc_id):
        self.chamadas.append(("buscar", rnc_id))
        return self.rncs.get(rnc_id)

    def registrar_decisao_rnc(self, rnc_id, *, decisao, justificativa, usuario_id, usuario_nome,
                              quando=None):
        self.chamadas.append(("registrar", rnc_id))
        linha = {"id": len(self.decisoes) + 1, "rnc_id": rnc_id, "decisao": decisao,
                 "justificativa": justificativa, "decidido_por_id": usuario_id,
                 "decidido_por_nome": usuario_nome, "quando": quando or AGORA}
        self.decisoes.append(linha)
        return dict(linha)

    def listar_decisoes_rnc(self, rnc_id):
        return [dict(d) for d in reversed(self.decisoes) if d["rnc_id"] == rnc_id]

    def listar_rncs_para_decisao(self, *, limite, somente_sem_decisao=False):
        self.chamadas.append(("listar_rncs", limite, somente_sem_decisao))
        itens = []
        for rnc in self.rncs.values():
            historico = self.listar_decisoes_rnc(rnc["id"])
            vigente = None
            if historico:
                v = historico[0]
                vigente = {k: v[k] for k in ("decisao", "justificativa", "decidido_por_nome", "quando")}
            if somente_sem_decisao and vigente:
                continue
            itens.append({
                "id": rnc["id"], "codigo": rnc["codigo"], "motivo": rnc["motivo"],
                "resultado_peca": rnc["resultado_peca"], "numero_peca": rnc["numero_peca"],
                "op": rnc["codigo_op"], "produto": rnc["produto_codigo"], "recurso": "DOBRA1",
                "criada_em": AGORA, "decisao_vigente": vigente,
            })
        return itens[:limite]


class PermissaoValidacaoE404Tests(_ApiCase):
    def setUp(self):
        self._build(_BancoEmMemoria())

    def test_somente_qualidade_e_admin_decidem_e_leem(self):
        corpo = {"decisao": "quarentena", "justificativa": "aguardar laudo"}
        for role in NAO_AUTORIZADOS:
            self._as(role)
            for resposta in (
                self.client.post(f"{Q}/rnc/7/decisions", json=corpo),
                self.client.get(f"{Q}/rnc/7/decisions"),
            ):
                self.assertEqual(resposta.status_code, 403, role)
                self.assertEqual(resposta.json()["code"], "quality_templates_access_denied", role)
        self.assertEqual(self.db.chamadas, [])  # nem chegou a consultar o banco
        for role in ("qualidade", "admin"):
            self._as(role)
            self.assertEqual(self.client.post(f"{Q}/rnc/7/decisions", json=corpo).status_code, 200, role)
            self.assertEqual(self.client.get(f"{Q}/rnc/7/decisions").status_code, 200, role)

    def test_lista_fechada_e_justificativa_invalida_dao_422_sem_gravar(self):
        self._as(QUALIDADE)
        invalidos = [
            {"decisao": "descartar", "justificativa": "motivo válido"},
            {"decisao": "USAR_COMO_ESTA", "justificativa": "motivo válido"},
            {"decisao": "sucatear", "justificativa": "   "},
            {"decisao": "sucatear", "justificativa": "ab"},
            {"decisao": "sucatear", "justificativa": "x" * 501},
            {"decisao": "sucatear", "justificativa": "motivo\x00válido"},  # Postgres recusa NUL
            {"decisao": "sucatear"},
            {"justificativa": "motivo válido"},
            {"decisao": "sucatear", "justificativa": "motivo válido", "resultado": "APROVADA"},
        ]
        for corpo in invalidos:
            resposta = self.client.post(f"{Q}/rnc/7/decisions", json=corpo)
            self.assertEqual(resposta.status_code, 422, corpo)
        self.assertEqual(self.db.decisoes, [])

    def test_lista_fechada_do_schema_espelha_a_do_servico(self):
        literal = QualityRncDecisionRequest.model_fields["decisao"].annotation.__args__
        self.assertEqual(set(literal), set(DECISOES))

    def test_rnc_inexistente_da_404_na_escrita_e_na_leitura(self):
        self._as(QUALIDADE)
        corpo = {"decisao": "sucatear", "justificativa": "sem conserto"}
        for resposta in (
            self.client.post(f"{Q}/rnc/999/decisions", json=corpo),
            self.client.get(f"{Q}/rnc/999/decisions"),
        ):
            self.assertEqual(resposta.status_code, 404)
            self.assertEqual(resposta.json()["code"], "quality_rnc_not_found")
        self.assertEqual(self.db.decisoes, [])
        self.assertEqual(self.client.get(f"{Q}/rnc/0/decisions").status_code, 422)  # id inválido

    def test_contradicao_devolve_aviso_mas_grava(self):
        self._as(QUALIDADE)
        resposta = self.client.post(
            f"{Q}/rnc/7/decisions", json={"decisao": "usar_como_esta", "justificativa": "cliente aceitou"}
        )
        self.assertEqual(resposta.status_code, 200, resposta.text)
        corpo = resposta.json()
        self.assertEqual(corpo["resultado_peca"], "REFUGO")
        self.assertIn("REFUGO", corpo["aviso"])
        self.assertEqual(corpo["aviso"], corpo["decisao"]["aviso"])
        self.assertEqual(len(self.db.decisoes), 1)

    def test_decisao_coerente_vem_sem_aviso(self):
        self._as("admin")
        resposta = self.client.post(
            f"{Q}/rnc/7/decisions", json={"decisao": "sucatear", "justificativa": "sem conserto"}
        )
        self.assertEqual(resposta.status_code, 200)
        self.assertIsNone(resposta.json()["aviso"])


class ListagemDeRncsTests(_ApiCase):
    def setUp(self):
        self._build(_BancoEmMemoria())

    def test_nao_qualidade_recebe_403_sem_consultar_o_banco(self):
        for role in NAO_AUTORIZADOS:
            self._as(role)
            resposta = self.client.get(f"{Q}/rnc")
            self.assertEqual(resposta.status_code, 403, role)
            self.assertEqual(resposta.json()["code"], "quality_templates_access_denied", role)
        self.assertEqual(self.db.chamadas, [])
        for role in ("qualidade", "admin"):
            self._as(role)
            self.assertEqual(self.client.get(f"{Q}/rnc").status_code, 200, role)

    def test_formato_do_item_e_aviso_so_com_decisao_vigente(self):
        self._as(QUALIDADE)
        corpo = self.client.get(f"{Q}/rnc").json()
        self.assertEqual(corpo["count"], 1)
        item = corpo["items"][0]
        self.assertEqual(
            set(item),
            {"id", "codigo", "motivo", "resultado_peca", "numero_peca", "op", "produto",
             "recurso", "criada_em", "decisao_vigente", "aviso"},
        )
        self.assertIsNone(item["decisao_vigente"])
        self.assertIsNone(item["aviso"])

        self.client.post(f"{Q}/rnc/7/decisions",
                         json={"decisao": "usar_como_esta", "justificativa": "cliente aceitou"})
        item = self.client.get(f"{Q}/rnc").json()["items"][0]
        self.assertEqual(item["decisao_vigente"]["decisao"], "usar_como_esta")
        self.assertEqual(item["decisao_vigente"]["decidido_por_nome"], "Sandro")
        self.assertEqual(item["aviso"], aviso_de_contradicao("REFUGO", "usar_como_esta"))
        self.assertIn("REFUGO", item["aviso"])

        self.client.post(f"{Q}/rnc/7/decisions", json={"decisao": "sucatear", "justificativa": "sem conserto"})
        item = self.client.get(f"{Q}/rnc").json()["items"][0]
        self.assertEqual(item["decisao_vigente"]["decisao"], "sucatear")  # a última vale
        self.assertIsNone(item["aviso"])

    def test_filtros_chegam_ao_repositorio_e_limite_e_validado(self):
        self._as(QUALIDADE)
        self.client.get(f"{Q}/rnc?limite=5&somente_sem_decisao=true")
        self.assertIn(("listar_rncs", 5, True), self.db.chamadas)
        self.client.get(f"{Q}/rnc")
        self.assertIn(("listar_rncs", 100, False), self.db.chamadas)
        for invalido in ("limite=0", "limite=201", "limite=abc"):
            self.assertEqual(self.client.get(f"{Q}/rnc?{invalido}").status_code, 422, invalido)
        self.client.post(f"{Q}/rnc/7/decisions", json={"decisao": "quarentena", "justificativa": "laudo"})
        self.assertEqual(self.client.get(f"{Q}/rnc?somente_sem_decisao=true").json(),
                         {"items": [], "count": 0})


class AvisoDeContradicaoTests(unittest.TestCase):
    def test_contradicoes_conhecidas(self):
        for resultado, decisao in (
            ("REFUGO", "usar_como_esta"),
            ("REFUGO", "retrabalhar"),
            ("RETRABALHO", "usar_como_esta"),
        ):
            aviso = aviso_de_contradicao(resultado, decisao)
            self.assertTrue(aviso and resultado in aviso, (resultado, decisao))

    def test_combinacoes_coerentes_ou_sem_resultado_nao_avisam(self):
        for resultado in ("REFUGO", "RETRABALHO", "APROVADA", None, "", "DESCONHECIDO"):
            for decisao in DECISOES:
                esperado_aviso = (resultado, decisao) in {
                    ("REFUGO", "usar_como_esta"),
                    ("REFUGO", "retrabalhar"),
                    ("RETRABALHO", "usar_como_esta"),
                }
                self.assertEqual(
                    aviso_de_contradicao(resultado, decisao) is not None, esperado_aviso,
                    (resultado, decisao),
                )

    def test_caixa_do_resultado_nao_importa(self):
        self.assertIsNotNone(aviso_de_contradicao("refugo", "usar_como_esta"))


class CatalogoDaMigrationTests(unittest.TestCase):
    def test_versao_catalogo_e_tabelas_esperadas(self):
        self.assertGreaterEqual(SCHEMA_VERSION, 67)
        self.assertIn(67, MIGRATIONS)
        self.assertIn("qualidade_rnc_decisoes", EXPECTED_TABLES)
        descricao, statements = MIGRATIONS[67]
        self.assertTrue(descricao)
        for statement in statements:
            self.assertRegex(statement, r"(?i)IF NOT EXISTS|OR REPLACE|IF EXISTS|CREATE TRIGGER")

    def test_repositorio_nao_tem_update_nem_delete(self):
        fonte = inspect.getsource(quality_rnc_decision_repository).lower()
        self.assertIsNone(re.search(r"update\s+\w+\s+set", fonte))
        self.assertIsNone(re.search(r"delete\s+from", fonte))
        self.assertNotIn("eventos_quantidade", fonte)
        metodos = [n for n in dir(quality_rnc_decision_repository.QualityRncDecisionRepositoryMixin)
                   if not n.startswith("_")]
        self.assertEqual(
            sorted(metodos),
            ["buscar_rnc_com_resultado", "listar_decisoes_rnc", "listar_rncs_para_decisao",
             "registrar_decisao_rnc"],
        )

    def test_allowlist_da_auditoria_cobre_a_entidade_sem_segredos(self):
        self.assertEqual(
            CAMPOS_AUDITAVEIS["rnc_decisao"], ("rnc_id", "rnc_codigo", "decisao", "justificativa")
        )

    def test_reset_do_teste_trunca_a_filha_junto_com_a_rnc(self):
        from scripts import limpar_apontamentos_teste as limpar
        from scripts import resetar_banco_teste as reset

        # TRUNCATE de qualidade_rnc exige a filha (FK) na mesma instrução.
        self.assertIn("qualidade_rnc_decisoes", reset.TRUNCATE_TABLES)
        self.assertNotIn("qualidade_rnc_decisoes", reset.PROTECTED_TABLES)
        self.assertIn("qualidade_rnc_decisoes", limpar.ALLOWED_DEPENDENTS)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class DecisaoPostgresTests(_ApiCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        from app.database.config import load_postgres_config
        from app.database.database import Database

        base = load_postgres_config(testing=True)
        self.admin_dsn = base.dsn
        self.schema = "rnc_decisao_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self._drop_schema)
        self._build(Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}")))
        self._as(QUALIDADE)
        self._ops = 0

    def _drop_schema(self):
        import psycopg
        from psycopg import sql

        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _rows(self, query, params=()):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()

    def _scalar(self, query, params=()):
        return list(self._rows(query, params)[0].values())[0]

    def _semear(self, resultado="REFUGO"):
        """RNC + peça com o resultado dado, direto no banco (sem o fluxo do operador)."""

        self._ops += 1
        op = f"OP-DEC-{self._ops}"
        inspecao = self.db.abrir_inspecao_qualidade(
            codigo_op=op, numero_operacao="90", produto_codigo="PRD_X", tipo_setor="Dobra",
            codigo_recurso="DOBRA1", quantidade_total=5, operador="Op", iniciada_em=AGORA,
        )
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO qualidade_rnc (codigo, inspecao_id, numero_peca, codigo_op,"
                " produto_codigo, tipo_setor, codigo_recurso, operador, motivo, registrada_em)"
                " VALUES (%s, %s, 1, %s, 'PRD_X', 'Dobra', 'DOBRA1', 'Op', 'cota fora', %s)"
                " RETURNING id",
                (f"RNC-{inspecao['id']}-0001", inspecao["id"], op, AGORA),
            )
            rnc_id = cursor.fetchone()["id"]
            cursor.execute(
                "INSERT INTO qualidade_pecas_inspecionadas (inspecao_id, numero_peca, resultado,"
                " possui_nao_conformidade, rnc_id, operador, registrada_em)"
                " VALUES (%s, 1, %s, TRUE, %s, 'Op', %s)",
                (inspecao["id"], resultado, rnc_id, AGORA),
            )
        return rnc_id

    def _decidir(self, rnc_id, decisao, justificativa="motivo registrado", **extra):
        return self.client.post(
            f"{Q}/rnc/{rnc_id}/decisions", json={"decisao": decisao, "justificativa": justificativa, **extra}
        )

    def test_migration_cria_tabela_indice_e_e_idempotente(self):
        self.assertEqual(self.db.obter_schema_version(), SCHEMA_VERSION)
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM qualidade_rnc_decisoes"), 0)
        indices = {r["indexname"] for r in self._rows(
            "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
            " AND tablename = 'qualidade_rnc_decisoes'"
        )}
        self.assertIn("idx_qualidade_rnc_decisoes_rnc", indices)
        self.db.create_tables()  # reaplicar não pode falhar
        _, statements = MIGRATIONS[67]
        with self.db.connection() as connection, connection.cursor() as cursor:
            for statement in statements:  # os próprios statements são idempotentes
                cursor.execute(statement)
        tabelas = {r["tablename"] for r in self._rows(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
        )}
        self.assertTrue(set(EXPECTED_TABLES) <= tabelas)

    def test_rollback_documentado_e_reaplicacao(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("DROP TABLE qualidade_rnc_decisoes")
            cursor.execute("DROP FUNCTION qualidade_rnc_decisoes_somente_insercao()")
            cursor.execute("DELETE FROM schema_migrations WHERE version = 67")
        self.db.create_tables()
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM qualidade_rnc_decisoes"), 0)
        self.assertEqual(self.db.obter_schema_version(), SCHEMA_VERSION)

    def test_historico_insert_only_a_vigente_e_a_ultima(self):
        rnc_id = self._semear("REFUGO")
        for decisao in ("quarentena", "retrabalhar", "sucatear"):
            self.assertEqual(self._decidir(rnc_id, decisao, f"justif {decisao}").status_code, 200)
        corpo = self.client.get(f"{Q}/rnc/{rnc_id}/decisions").json()
        self.assertEqual([i["decisao"] for i in corpo["items"]], ["sucatear", "retrabalhar", "quarentena"])
        self.assertEqual(corpo["vigente"]["decisao"], "sucatear")
        self.assertEqual([i["vigente"] for i in corpo["items"]], [True, False, False])
        self.assertEqual(corpo["rnc"]["resultado_peca"], "REFUGO")
        self.assertEqual(corpo["vigente"]["decidido_por_id"], QUALIDADE.id)
        self.assertEqual(corpo["vigente"]["decidido_por_nome"], "Sandro")
        # Avisos recalculados em cada linha: "retrabalhar" contradiz REFUGO, as outras não.
        self.assertEqual([bool(i["aviso"]) for i in corpo["items"]], [False, True, False])
        # O banco recusa UPDATE; o histórico fica intacto.
        import psycopg

        with self.assertRaises(psycopg.errors.Error):
            self._rows("UPDATE qualidade_rnc_decisoes SET decisao = 'usar_como_esta'")
        self.assertEqual(self._scalar("SELECT COUNT(DISTINCT decisao) FROM qualidade_rnc_decisoes"), 3)
        # E a lista fechada também vale direto no banco.
        with self.assertRaises(psycopg.errors.CheckViolation):
            self._rows(
                "INSERT INTO qualidade_rnc_decisoes (rnc_id, decisao, justificativa,"
                " decidido_por_id, decidido_por_nome) VALUES (%s, 'jogar_fora', 'abc', 1, 'x')",
                (rnc_id,),
            )

    def test_listagem_de_rncs_ordem_vigente_filtro_e_limite(self):
        antiga, recente = self._semear("REFUGO"), self._semear("RETRABALHO")
        self._decidir(antiga, "quarentena")
        self._decidir(antiga, "usar_como_esta", "cliente aceitou")
        corpo = self.client.get(f"{Q}/rnc").json()
        self.assertEqual(corpo["count"], 2)
        self.assertEqual([i["id"] for i in corpo["items"]], [recente, antiga])  # mais recente primeiro
        sem, com = corpo["items"]
        self.assertIsNone(sem["decisao_vigente"])
        self.assertIsNone(sem["aviso"])
        self.assertEqual((sem["resultado_peca"], sem["motivo"], sem["produto"], sem["recurso"]),
                         ("RETRABALHO", "cota fora", "PRD_X", "DOBRA1"))
        self.assertEqual(com["decisao_vigente"]["decisao"], "usar_como_esta")  # última decisão
        self.assertEqual(com["decisao_vigente"]["decidido_por_nome"], "Sandro")
        self.assertIn("REFUGO", com["aviso"])
        so_sem = self.client.get(f"{Q}/rnc?somente_sem_decisao=true").json()
        self.assertEqual([i["id"] for i in so_sem["items"]], [recente])
        self.assertEqual(self.client.get(f"{Q}/rnc?limite=1").json()["count"], 1)
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM qualidade_rnc_decisoes"), 2)  # só leitura
        self._as("gestor")
        self.assertEqual(self.client.get(f"{Q}/rnc").status_code, 403)

    def test_decisoes_de_uma_rnc_nao_aparecem_em_outra(self):
        a, b = self._semear("REFUGO"), self._semear("RETRABALHO")
        self._decidir(a, "sucatear")
        self.assertEqual(self.client.get(f"{Q}/rnc/{b}/decisions").json()["items"], [])
        self.assertIsNone(self.client.get(f"{Q}/rnc/{b}/decisions").json()["vigente"])

    def test_contradicao_avisa_e_grava_e_coerente_nao_avisa(self):
        refugo = self._semear("REFUGO")
        resposta = self._decidir(refugo, "usar_como_esta", "cliente aceitou")
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertIn("REFUGO", resposta.json()["aviso"])
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM qualidade_rnc_decisoes"), 1)  # gravou

        retrabalho = self._semear("RETRABALHO")
        coerente = self._decidir(retrabalho, "retrabalhar", "voltar para a dobra")
        self.assertEqual(coerente.status_code, 200)
        self.assertIsNone(coerente.json()["aviso"])
        self.assertIsNone(self._decidir(refugo, "sucatear", "sem conserto").json()["aviso"])

    def test_decisao_nao_cria_evento_nem_altera_peca_ou_rnc(self):
        rnc_id = self._semear("REFUGO")
        consultas = {
            "eventos_quantidade_producao": "SELECT COUNT(*) FROM eventos_quantidade_producao",
            "apontamentos_operacionais": "SELECT COUNT(*) FROM apontamentos_operacionais",
            "eventos_apontamento_operador": "SELECT COUNT(*) FROM eventos_apontamento_operador",
            "eventos_estado_recurso": "SELECT COUNT(*) FROM eventos_estado_recurso",
            "historico": "SELECT COUNT(*) FROM historico",
            "totvs_outbox": "SELECT COUNT(*) FROM totvs_outbox",
            "peca": "SELECT * FROM qualidade_pecas_inspecionadas ORDER BY id",
            "rnc": "SELECT * FROM qualidade_rnc ORDER BY id",
            "inspecao": "SELECT * FROM qualidade_inspecoes ORDER BY id",
        }
        antes = {nome: self._rows(q) for nome, q in consultas.items()}
        for decisao in DECISOES:
            self.assertEqual(self._decidir(rnc_id, decisao).status_code, 200)
        depois = {nome: self._rows(q) for nome, q in consultas.items()}
        self.assertEqual(antes, depois)
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM qualidade_rnc_decisoes"), len(DECISOES))

    def test_permissao_real_no_banco_negado_nao_grava(self):
        rnc_id = self._semear("REFUGO")
        for role in NAO_AUTORIZADOS:
            self._as(role)
            self.assertEqual(self._decidir(rnc_id, "sucatear").status_code, 403, role)
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM qualidade_rnc_decisoes"), 0)
        self._as("admin")
        self.assertEqual(self._decidir(rnc_id, "sucatear").status_code, 200)

    def test_rnc_inexistente_da_404_e_nao_grava(self):
        self.assertEqual(self._decidir(424242, "sucatear").status_code, 404)
        self.assertEqual(self.client.get(f"{Q}/rnc/424242/decisions").status_code, 404)
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM qualidade_rnc_decisoes"), 0)

    def test_lista_fechada_e_422_sem_gravar(self):
        rnc_id = self._semear("REFUGO")
        self.assertEqual(self._decidir(rnc_id, "descartar").status_code, 422)
        self.assertEqual(self._decidir(rnc_id, "sucatear", "  ").status_code, 422)
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM qualidade_rnc_decisoes"), 0)

    def test_grava_na_auditoria_e_falha_da_auditoria_nao_derruba_a_rota(self):
        rnc_id = self._semear("REFUGO")
        codigo = self._scalar("SELECT codigo FROM qualidade_rnc WHERE id = %s", (rnc_id,))
        self.assertEqual(self._decidir(rnc_id, "quarentena", "aguardar laudo").status_code, 200)
        linhas = self.db.listar_auditoria(entidade="rnc_decisao", chave=codigo)
        self.assertEqual(len(linhas), 1)
        linha = linhas[0]
        self.assertEqual((linha["acao"], linha["usuario_id"], linha["usuario_nome"]),
                         ("criar", QUALIDADE.id, "Sandro"))
        self.assertIsNone(linha["antes"])
        self.assertEqual(linha["depois"], {"rnc_id": rnc_id, "rnc_codigo": codigo,
                                           "decisao": "quarentena", "justificativa": "aguardar laudo"})

        def quebrado(**_):
            raise RuntimeError("log fora do ar")

        self.db.registrar_auditoria = quebrado
        with self.assertLogs(level="ERROR"):
            resposta = self._decidir(rnc_id, "sucatear", "sem conserto")
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM qualidade_rnc_decisoes"), 2)

    def test_apagar_a_rnc_leva_o_historico_junto_sem_travar_a_limpeza_do_teste(self):
        rnc_id = self._semear("REFUGO")
        self._decidir(rnc_id, "sucatear")
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM qualidade_inspecoes")  # cascata inspeção -> RNC -> decisões
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM qualidade_rnc_decisoes"), 0)


if __name__ == "__main__":
    unittest.main()
