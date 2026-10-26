"""Auditoria "quem mudou o quê" das telas de gestão (migration 66, 26/10/2026).

Rotas: contra bancos em memória (``FakeDatabase`` e o repositório do Diretoria),
com a mesma allowlist do ``Database`` real. Banco: schema isolado em
``TEST_DATABASE_URL`` (nunca o REAL), só quando a variável existe.
"""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, time
from decimal import Decimal
from unittest import mock
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database.change_audit_repository import (
    CAMPOS_AUDITAVEIS,
    ChangeAuditRepositoryMixin,
    sanitizar_auditoria,
)
from backend.api.config import WebSettings
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import create_app
from backend.api.schemas.auth import SessionUser
from mes.services.change_audit import auditar
from tests.fakes import FakeDatabase
from tests.test_director_summary import NOW, _Repo

SENHA = "senha-forte-123"
M = "/api/v1/management"
D = "/api/v1/diretoria"


def _settings():
    return WebSettings(
        environment="test",
        session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
        allowed_hosts=("testserver",),
        allowed_origins=("http://testserver",),
    )


def _user(role, uid, name):
    return SessionUser(
        id=uid, name=name, role=role, management_access=True, andon_access=True,
        operator_access=False,
    )


ADMIN = _user("admin", 900, "Admin Z")


class _AuditMemory:
    """Mesma regra do ``Database``: allowlist antes de guardar; nunca levanta."""

    def _init_audit(self):
        self.auditoria = []
        self.consultas = []
        self.falhar_auditoria = False

    def registrar_auditoria(self, *, entidade, chave, acao, usuario_id=None, usuario_nome=None,
                            antes=None, depois=None):
        if self.falhar_auditoria:
            raise RuntimeError("banco do log fora do ar")
        self.auditoria.append({
            "entidade": entidade, "chave": chave, "acao": acao,
            "usuario_id": usuario_id, "usuario_nome": usuario_nome,
            "antes": sanitizar_auditoria(entidade, antes),
            "depois": sanitizar_auditoria(entidade, depois),
        })
        return True

    def listar_auditoria(self, **filtros):
        self.consultas.append(filtros)
        return [
            {"id": i + 1, "quando": datetime(2026, 10, 26, 9, 0), **linha}
            for i, linha in enumerate(self.auditoria)
            if not (filtros.get("excluir_entidades") and linha["entidade"] in filtros["excluir_entidades"])
            and not (filtros.get("entidades") and linha["entidade"] not in filtros["entidades"])
        ]


class _ManagementDb(_AuditMemory, FakeDatabase):
    def __init__(self):
        FakeDatabase.__init__(self)
        self._init_audit()
        self.turnos = []

    def listar_parametros_turno(self, *, somente_ativos=False, vigente_em=None):
        return [dict(t) for t in self.turnos]

    def salvar_parametro_turno(self, *, nome, tipo, hora_inicio, hora_fim, ativo=True, ordem=1,
                               parametro_id=None):
        alvo = next((t for t in self.turnos if t["id"] == parametro_id), None)
        if alvo is None:
            alvo = {"id": len(self.turnos) + 1}
            self.turnos.append(alvo)
        alvo.update(nome=nome, tipo=tipo, hora_inicio=hora_inicio, hora_fim=hora_fim,
                    ativo=bool(ativo), ordem=ordem)
        return dict(alvo)

    def remover_parametro_turno(self, parametro_id):
        antes = len(self.turnos)
        self.turnos = [t for t in self.turnos if t["id"] != parametro_id]
        return len(self.turnos) < antes


class _CostDb(_AuditMemory, _Repo):
    def __init__(self):
        _Repo.__init__(self)
        self._init_audit()

    def listar_custos_hora_recurso(self):
        return [{"recurso": k, "valor_hora": v} for k, v in self.resource_rates.items()]

    def listar_custos_hora_operador(self):
        return [{"operador_id": k, "valor_hora": v} for k, v in self.operator_rates.items()]


class _ApiCase(unittest.TestCase):
    def _build(self, db):
        self.db = db
        self.app = create_app(settings=_settings(), database_factory=lambda: db)
        self.app.dependency_overrides[get_database] = lambda: db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def _as(self, user):
        # Não substitui require_admin_user: a trava real é que deve negar.
        self.app.dependency_overrides[get_current_user] = lambda: user


class RotasDeGestaoGravamAuditoriaTests(_ApiCase):
    def setUp(self):
        self._build(_ManagementDb())
        self._as(ADMIN)

    def _unica(self):
        self.assertEqual(len(self.db.auditoria), 1, self.db.auditoria)
        return self.db.auditoria[0]

    def test_criar_alterar_e_excluir_usuario_gravam_quem_e_antes_depois(self):
        criado = self.client.post(
            f"{M}/users", json={"nome": "Novo", "nivel": "operador_corte", "ativo": True, "senha": SENHA}
        )
        self.assertEqual(criado.status_code, 200)
        uid = criado.json()["item"]["id"]
        log = self._unica()
        self.assertEqual((log["entidade"], log["acao"], log["chave"]), ("usuario", "criar", str(uid)))
        self.assertEqual((log["usuario_id"], log["usuario_nome"]), (900, "Admin Z"))
        self.assertIsNone(log["antes"])
        self.assertEqual(log["depois"]["nivel_atribuido"], "operador_corte")

        self.db.auditoria.clear()
        alterado = self.client.post(
            f"{M}/users", json={"id": uid, "nome": "Novo", "nivel": "operador_dobra", "ativo": False}
        )
        self.assertEqual(alterado.status_code, 200)
        log = self._unica()
        self.assertEqual(log["acao"], "alterar")
        self.assertEqual(log["antes"]["nivel_atribuido"], "operador_corte")
        self.assertTrue(log["antes"]["ativo"])
        self.assertEqual(log["depois"]["nivel_atribuido"], "operador_dobra")
        self.assertFalse(log["depois"]["ativo"])

        self.db.auditoria.clear()
        self.assertEqual(self.client.delete(f"{M}/users/{uid}").status_code, 200)
        log = self._unica()
        self.assertEqual(log["acao"], "excluir")
        self.assertEqual(log["antes"]["nome"], "Novo")
        self.assertIsNone(log["depois"])

    def test_senha_hash_e_session_version_nunca_aparecem_no_log(self):
        criado = self.client.post(
            f"{M}/users", json={"nome": "Novo", "nivel": "operador_corte", "ativo": True, "senha": SENHA}
        )
        uid = criado.json()["item"]["id"]
        self.client.post(
            f"{M}/users",
            json={"id": uid, "nome": "Novo", "nivel": "operador_corte", "ativo": True, "senha": "outra-senha-456"},
        )
        texto = json.dumps(self.db.auditoria, default=str).lower()
        for proibido in (SENHA, "outra-senha-456", "senha", "hash", "token", "session_version"):
            self.assertNotIn(proibido, texto)

    def test_niveis_pausas_e_turnos(self):
        self.assertEqual(
            self.client.post(f"{M}/levels", json={"rotulo": "Líder Teste", "nivel_base": "lider"}).status_code, 200
        )
        log = self._unica()
        self.assertEqual((log["entidade"], log["acao"], log["chave"]), ("nivel", "criar", "lider_teste"))
        self.db.auditoria.clear()
        self.assertEqual(self.client.delete(f"{M}/levels/lider_teste").status_code, 200)
        log = self._unica()
        self.assertEqual((log["acao"], log["antes"]["rotulo"]), ("excluir", "Líder Teste"))

        self.db.auditoria.clear()
        pausa = {"tipo_setor": "Corte", "nome": "Almoço", "hora_inicio": "12:00:00", "hora_fim": "13:00:00",
                 "ativo": True, "ordem": 1}
        salva = self.client.post(f"{M}/pauses", json=pausa)
        self.assertEqual(salva.status_code, 200, salva.text)
        pid = salva.json()["item"]["id"]
        self.assertEqual(self._unica()["acao"], "criar")
        self.db.auditoria.clear()
        self.client.post(f"{M}/pauses", json={**pausa, "id": pid, "hora_fim": "13:30:00"})
        log = self._unica()
        self.assertEqual(log["acao"], "alterar")
        self.assertNotEqual(log["antes"]["hora_fim"], log["depois"]["hora_fim"])
        self.db.auditoria.clear()
        self.assertEqual(self.client.delete(f"{M}/pauses/{pid}").status_code, 200)
        self.assertEqual(self._unica()["acao"], "excluir")

        self.db.auditoria.clear()
        turno = {"nome": "Turno 1", "tipo": "expediente", "hora_inicio": "07:00:00", "hora_fim": "17:00:00",
                 "ativo": True, "ordem": 1}
        salvo = self.client.post(f"{M}/shift-parameters", json=turno)
        self.assertEqual(salvo.status_code, 200, salvo.text)
        tid = salvo.json()["item"]["id"]
        self.assertEqual((self._unica()["entidade"], self._unica()["acao"]), ("turno", "criar"))
        self.db.auditoria.clear()
        self.client.post(f"{M}/shift-parameters", json={**turno, "id": tid, "hora_fim": "18:00:00"})
        self.assertEqual(self._unica()["acao"], "alterar")
        self.db.auditoria.clear()
        self.assertEqual(self.client.delete(f"{M}/shift-parameters/{tid}").status_code, 200)
        self.assertEqual(self._unica()["acao"], "excluir")

    def test_falha_ao_gravar_o_log_nao_derruba_a_rota(self):
        self.db.falhar_auditoria = True
        with self.assertLogs(level="ERROR"):
            resposta = self.client.post(
                f"{M}/users", json={"nome": "Resiste", "nivel": "operador_corte", "ativo": True, "senha": SENHA}
            )
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(self.db.usuario_existe("Resiste"))

    def test_falha_ao_ler_o_antes_nao_derruba_a_rota(self):
        criado = self.client.post(
            f"{M}/users", json={"nome": "Resiste", "nivel": "operador_corte", "ativo": True, "senha": SENHA}
        ).json()["item"]["id"]
        original = self.db.obter_usuario_por_id
        chamadas = []

        def leitura_quebrada(user_id):
            chamadas.append(user_id)
            if len(chamadas) == 1:  # a leitura do "antes"; a do fim da rota segue normal
                raise RuntimeError("leitura falhou")
            return original(user_id)

        with mock.patch.object(self.db, "obter_usuario_por_id", leitura_quebrada), self.assertLogs(level="ERROR"):
            resposta = self.client.post(
                f"{M}/users", json={"id": criado, "nome": "Resiste", "nivel": "operador_dobra", "ativo": True}
            )
        self.assertEqual(resposta.status_code, 200)

    def test_operacao_recusada_nao_gera_log(self):
        self.assertEqual(self.client.delete(f"{M}/users/9999").status_code, 404)
        self.assertEqual(self.client.delete(f"{M}/pauses/9999").status_code, 404)
        self.assertEqual(self.db.auditoria, [])


class LeituraDoLogTests(_ApiCase):
    def setUp(self):
        self._build(_ManagementDb())

    def test_admin_le_com_filtros_e_custos_ficam_de_fora(self):
        self._as(ADMIN)
        self.db.auditoria.append({"entidade": "custo_recurso", "chave": "LASER1", "acao": "criar",
                                  "usuario_id": 1, "usuario_nome": "x", "antes": None,
                                  "depois": {"valor_hora": "10"}})
        self.client.post(f"{M}/levels", json={"rotulo": "Líder Teste", "nivel_base": "lider"})
        resposta = self.client.get(
            f"{M}/audit", params={"entidade": "nivel", "chave": "lider_teste", "usuario": "Admin",
                                  "desde": "2026-10-01", "ate": "2026-10-31", "limite": 5}
        )
        self.assertEqual(resposta.status_code, 200, resposta.text)
        corpo = resposta.json()
        self.assertEqual(corpo["count"], 1)
        self.assertEqual(corpo["items"][0]["entidade"], "nivel")
        filtro = self.db.consultas[-1]
        self.assertEqual((filtro["entidade"], filtro["chave"], filtro["usuario"], filtro["limite"]),
                         ("nivel", "lider_teste", "Admin", 5))
        self.assertEqual(filtro["desde"], datetime(2026, 10, 1))
        self.assertEqual(filtro["ate"], datetime(2026, 11, 1))
        self.assertEqual(set(filtro["excluir_entidades"]), {"custo_recurso", "custo_pessoa"})
        sem_filtro = self.client.get(f"{M}/audit").json()
        self.assertNotIn("custo_recurso", {i["entidade"] for i in sem_filtro["items"]})

    def test_quem_nao_e_admin_nao_le_o_log(self):
        for role in ("supervisor", "operador_corte"):
            self._as(_user(role, 3, "Fulano"))
            self.assertEqual(self.client.get(f"{M}/audit").status_code, 403, role)

    def test_limite_acima_do_maximo_e_recusado(self):
        self._as(ADMIN)
        self.assertEqual(self.client.get(f"{M}/audit", params={"limite": 501}).status_code, 422)


class CustosTests(_ApiCase):
    def setUp(self):
        self._build(_CostDb())
        self.diretoria = _user("diretoria", 77, "Diretor")
        self._as(self.diretoria)
        patcher = mock.patch(
            "backend.api.routers.director.request_now_func", return_value=lambda: NOW
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_custo_de_recurso_e_pessoa_gravam_antes_e_depois(self):
        self.assertEqual(self.client.put(f"{D}/custos/recurso/laser1", json={"valor_hora": 100.0}).status_code, 200)
        log = self.db.auditoria[-1]
        self.assertEqual((log["entidade"], log["acao"], log["usuario_nome"]), ("custo_recurso", "criar", "Diretor"))
        self.client.put(f"{D}/custos/recurso/laser1", json={"valor_hora": 120.0})
        log = self.db.auditoria[-1]
        self.assertEqual(log["acao"], "alterar")
        self.assertEqual((log["antes"]["valor_hora"], log["depois"]["valor_hora"]), (Decimal("100"), Decimal("120")))

        self.client.put(f"{D}/custos/pessoa/1", json={"valor_hora": 60.0})
        self.assertEqual(self.db.auditoria[-1]["acao"], "criar")
        self.client.put(f"{D}/custos/pessoa/1", json={"valor_hora": 77.0})
        log = self.db.auditoria[-1]
        self.assertEqual((log["entidade"], log["chave"], log["acao"]), ("custo_pessoa", "1", "alterar"))

    def test_falha_no_log_nao_derruba_o_custo(self):
        self.db.falhar_auditoria = True
        with self.assertLogs(level="ERROR"):
            resposta = self.client.put(f"{D}/custos/recurso/laser1", json={"valor_hora": 90.0})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.db.resource_rates["LASER1"], Decimal("90.0"))

    def test_leitura_dos_custos_so_para_diretoria_e_so_custos(self):
        self.client.put(f"{D}/custos/recurso/laser1", json={"valor_hora": 100.0})
        self.db.auditoria.append({"entidade": "usuario", "chave": "1", "acao": "criar", "usuario_id": 1,
                                  "usuario_nome": "x", "antes": None, "depois": {"nome": "a"}})
        itens = self.client.get(f"{D}/custos/auditoria").json()["items"]
        self.assertEqual({i["entidade"] for i in itens}, {"custo_recurso"})
        self._as(_user("supervisor", 3, "Fulano"))
        self.assertEqual(self.client.get(f"{D}/custos/auditoria").status_code, 403)


class AllowlistETratamentoDeErroTests(unittest.TestCase):
    def test_allowlist_descarta_segredos_por_construcao(self):
        bruto = {"nome": "x", "nivel_atribuido": "admin", "unidade": "U", "ativo": True, "senha": "s",
                 "senha_hash": "h", "token": "t", "session_version": 4}
        self.assertEqual(
            sanitizar_auditoria("usuario", bruto),
            {"nome": "x", "nivel_atribuido": "admin", "unidade": "U", "ativo": True},
        )
        self.assertIsNone(sanitizar_auditoria("entidade_desconhecida", bruto))
        for campos in CAMPOS_AUDITAVEIS.values():
            for campo in campos:
                self.assertFalse(any(p in campo for p in ("senha", "hash", "token", "session")), campo)

    def test_registrar_auditoria_real_nunca_levanta(self):
        class Quebrado(ChangeAuditRepositoryMixin):
            def connection(self):
                raise RuntimeError("sem banco")

        with self.assertLogs(level="ERROR"):
            self.assertFalse(Quebrado().registrar_auditoria(entidade="usuario", chave="1", acao="criar",
                                                            depois={"nome": "x"}))
        with self.assertLogs(level="ERROR"):
            self.assertFalse(Quebrado().registrar_auditoria(entidade="nada", chave="1", acao="criar"))

    def test_auditar_engole_erro_e_ignora_banco_sem_o_metodo(self):
        class Explode:
            def registrar_auditoria(self, **_):
                raise RuntimeError("x")

        with self.assertLogs(level="ERROR"):
            self.assertFalse(auditar(Explode(), ADMIN, "usuario", 1, depois={"nome": "a"}))
        self.assertFalse(auditar(object(), ADMIN, "usuario", 1, depois={"nome": "a"}))
        self.assertFalse(auditar(Explode(), ADMIN, "usuario", 1))


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class AuditoriaPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        from app.database.config import load_postgres_config
        from app.database.database import Database

        base = load_postgres_config(testing=True)
        self.admin_dsn = base.dsn
        self.schema = "auditoria_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self._drop_schema)
        self.db = Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}"))

    def _drop_schema(self):
        import psycopg
        from psycopg import sql

        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _scalar(self, query, params=()):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return list(cursor.fetchone().values())[0]

    def test_migration_cria_tabela_e_indices_e_e_idempotente(self):
        from app.database.migrations import MIGRATIONS, SCHEMA_VERSION

        self.assertGreaterEqual(SCHEMA_VERSION, 66)
        self.assertEqual(self.db.obter_schema_version(), SCHEMA_VERSION)
        indices = {
            r["indexname"] for r in self._rows(
                "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
                " AND tablename = 'auditoria_alteracoes'"
            )
        }
        self.assertTrue({"idx_auditoria_entidade_chave", "idx_auditoria_quando"} <= indices)
        self.db.create_tables()  # reaplicar não pode falhar
        _, statements = MIGRATIONS[66]
        with self.db.connection() as connection, connection.cursor() as cursor:
            for statement in statements:  # os próprios statements são idempotentes
                cursor.execute(statement)

    def test_rollback_documentado_e_reaplicacao(self):
        self.db.registrar_auditoria(entidade="nivel", chave="x", acao="criar", depois={"nome": "x"})
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("DROP TABLE auditoria_alteracoes")
            cursor.execute("DELETE FROM schema_migrations WHERE version = 66")
        self.db.create_tables()
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM auditoria_alteracoes"), 0)
        self.assertEqual(self.db.obter_schema_version(), 66)

    def _rows(self, query, params=()):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall()

    def test_grava_lista_filtra_e_aplica_allowlist(self):
        self.assertTrue(self.db.registrar_auditoria(
            entidade="usuario", chave="7", acao="alterar", usuario_id=900, usuario_nome="Admin Z",
            antes={"nome": "A", "nivel_atribuido": "x", "senha": "segredo", "session_version": 1},
            depois={"nome": "A", "nivel_atribuido": "y", "senha_hash": "h", "token": "t"},
        ))
        self.assertTrue(self.db.registrar_auditoria(
            entidade="turno", chave="2", acao="alterar", usuario_id=1, usuario_nome="Outro",
            antes={"hora_fim": time(17, 0)}, depois={"hora_fim": time(18, 0), "ativo": True},
        ))
        self.assertTrue(self.db.registrar_auditoria(
            entidade="custo_recurso", chave="LASER1", acao="criar", usuario_id=1, usuario_nome="Outro",
            depois={"recurso": "LASER1", "valor_hora": Decimal("12.50")},
        ))
        linhas = self.db.listar_auditoria(entidade="usuario", chave="7")
        self.assertEqual(len(linhas), 1)
        linha = linhas[0]
        self.assertEqual((linha["usuario_id"], linha["usuario_nome"], linha["acao"]), (900, "Admin Z", "alterar"))
        self.assertEqual(linha["antes"], {"nome": "A", "nivel_atribuido": "x"})
        self.assertEqual(linha["depois"], {"nome": "A", "nivel_atribuido": "y"})
        gravado = self._scalar("SELECT COALESCE(string_agg(antes::text || depois::text, ''), '') FROM auditoria_alteracoes")
        for proibido in ("segredo", "senha", "hash", "token", "session_version"):
            self.assertNotIn(proibido, gravado)
        self.assertEqual(self.db.listar_auditoria(usuario="900")[0]["entidade"], "usuario")
        self.assertEqual(len(self.db.listar_auditoria(usuario="outr")), 2)
        # Número gigante ou dígito não-ASCII não pode estourar (500): vira busca por nome.
        self.assertEqual(self.db.listar_auditoria(usuario="9" * 25), [])
        self.assertEqual(self.db.listar_auditoria(usuario="²"), [])
        self.assertEqual(
            {r["entidade"] for r in self.db.listar_auditoria(excluir_entidades=["custo_recurso", "custo_pessoa"])},
            {"usuario", "turno"},
        )
        self.assertEqual(
            [r["entidade"] for r in self.db.listar_auditoria(entidades=["custo_recurso"])], ["custo_recurso"]
        )
        self.assertEqual(self.db.listar_auditoria(limite=1)[0]["entidade"], "custo_recurso")  # mais recente
        agora = datetime.now()
        self.assertEqual(len(self.db.listar_auditoria(desde=datetime(2000, 1, 1), ate=agora.replace(year=agora.year + 1))), 3)
        self.assertEqual(self.db.listar_auditoria(ate=datetime(2000, 1, 1)), [])

    def test_falha_do_banco_nao_levanta(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("DROP TABLE auditoria_alteracoes")
        with self.assertLogs(level="ERROR"):
            self.assertFalse(self.db.registrar_auditoria(entidade="nivel", chave="x", acao="criar",
                                                         depois={"nome": "x"}))

    def test_tabela_e_protegida_no_reset_do_banco_de_teste(self):
        from scripts import resetar_banco_teste as reset

        self.assertIn("auditoria_alteracoes", reset.PROTECTED_TABLES)
        self.assertNotIn("auditoria_alteracoes", reset.TRUNCATE_TABLES)


if __name__ == "__main__":
    unittest.main()
