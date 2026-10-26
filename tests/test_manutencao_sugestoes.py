"""Sugestões de manutenção (migration 68, 26/10/2026).

Sem Postgres: geração a partir das paradas (só NÃO planejada do grupo de
manutenção, >= 10 min), idempotência, aceitar/descartar, 409/404/422, permissão
(nível atribuído ``manutencao`` e admin) e auditoria, contra um banco em memória.
Com Postgres (schema descartável em ``TEST_DATABASE_URL``, nunca o REAL): migration
idempotente, CHECKs, gatilho "decidida não volta a sugerida" e decisão sem corrida.
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.permissions import USER_LEVELS, can_access_management_web, can_manage_maintenance
from app.database.change_audit_repository import CAMPOS_AUDITAVEIS
from app.database.manutencao_sugestoes_repository import ManutencaoSugestoesRepositoryMixin
from app.database.migrations import EXPECTED_TABLES, MIGRATIONS, SCHEMA_VERSION
from backend.api.config import WebSettings
from backend.api.database import get_database
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.main import create_app
from backend.api.schemas.auth import SessionUser
from mes.services.maintenance_suggestions import (
    MIN_PARADA_SEGUNDOS,
    MaintenanceSuggestionError,
    MaintenanceSuggestionService,
)
from tests.fakes import FakeDatabase

M = "/api/v1/maintenance/suggestions"
AGORA = datetime(2026, 10, 26, 12, 0)

CATALOGO = [
    {"codigo": "0011", "nome": "QUEBRA DE MAQUINA", "grupo_codigo": "0003", "setup": False, "retrabalho": False},
    {"codigo": "0010", "nome": "MANUTENCAO PREVENTIVA", "grupo_codigo": "0002", "setup": False, "retrabalho": False},
    {"codigo": "9999", "nome": "FALTA DE PECAS", "grupo_codigo": "0006", "setup": False, "retrabalho": False},
    {"codigo": "1005", "nome": "SETUP", "grupo_codigo": "0003", "setup": True, "retrabalho": False},
]


def _estado(ident, inicio, fim, *, codigo="0011", planejado=False, recurso="DOBRA1", automatico=False,
            categoria="parada"):
    return {
        "id": ident, "categoria": categoria, "recurso": recurso, "tipo_setor": "Dobra",
        "codigo_status_recurso": codigo, "motivo": codigo, "planejado": planejado,
        "automatico": automatico, "data_inicio": inicio, "data_fim": fim,
        "inicio_periodo": inicio, "fim_periodo": fim, "op": "OP-1",
    }


def _h(dia, hora, minuto=0):
    return datetime(2026, 10, dia, hora, minuto)


class _BancoEmMemoria(FakeDatabase):
    """Estados físicos + catálogo + a tabela de sugestões com a semântica do SQL."""

    def __init__(self, estados=None):
        super().__init__()
        self.estados = list(estados or [])
        self.sugestoes = []
        self.auditoria = []
        self.chamadas_decisao = 0

    def _now(self):
        return AGORA

    def listar_status_recursos(self, **_kwargs):
        return [dict(r) for r in CATALOGO]

    def listar_fatos_operacionais_periodo(self, *_a, **_k):
        return []

    def listar_tempos_nesting_corte(self, **_k):
        return []

    def listar_estados_recurso_periodo(self, _i, _f, *, categoria=None, **_k):
        rows = [dict(r) for r in self.estados]
        return [r for r in rows if categoria is None or r["categoria"] == categoria]

    # --- repositório (espelha ON CONFLICT e UPDATE ... WHERE status = 'sugerida')
    def gravar_sugestoes_manutencao(self, paradas):
        for p in paradas:
            atual = next((s for s in self.sugestoes
                          if (s["recurso"], s["parada_inicio"]) == (p["recurso"], p["parada_inicio"])), None)
            if atual is None:
                self.sugestoes.append({
                    "id": len(self.sugestoes) + 1, "setor": p.get("setor"), "op": p.get("op"),
                    "status": "sugerida", "criada_em": AGORA, "decidido_por_id": None,
                    "decidido_por_nome": None, "decidido_em": None, "nota": None,
                    **{k: p[k] for k in ("recurso", "parada_inicio", "parada_fim", "parada_segundos", "motivo")},
                })
            elif atual["status"] == "sugerida":
                atual["parada_fim"], atual["parada_segundos"] = p["parada_fim"], p["parada_segundos"]
        return len(paradas)

    def listar_sugestoes_manutencao(self, status, limite=200):
        rows = [dict(s) for s in self.sugestoes if s["status"] == status]
        rows.sort(key=lambda s: (s["parada_inicio"], s["id"]), reverse=True)
        return rows[:limite]

    def buscar_sugestao_manutencao(self, sugestao_id):
        return next((dict(s) for s in self.sugestoes if s["id"] == sugestao_id), None)

    def decidir_sugestao_manutencao(self, sugestao_id, *, status, usuario_id, usuario_nome, nota=None,
                                    quando=None):
        self.chamadas_decisao += 1
        s = next((s for s in self.sugestoes if s["id"] == sugestao_id and s["status"] == "sugerida"), None)
        if s is None:
            return None
        s.update(status=status, decidido_por_id=usuario_id, decidido_por_nome=usuario_nome,
                 decidido_em=quando or AGORA, nota=nota)
        return dict(s)

    def registrar_auditoria(self, **kwargs):
        self.auditoria.append(kwargs)
        return True


def _estados_padrao():
    return [
        _estado(1, _h(25, 8), _h(25, 8, 25)),                      # 25 min corretiva: SIM
        _estado(2, _h(25, 9), _h(25, 9, 10), recurso="DOBRA2"),     # exatamente 10 min: SIM
        _estado(3, _h(25, 10), _h(25, 10, 9, ), recurso="DOBRA3"),  # 9 min: não
        _estado(4, _h(25, 11), _h(25, 12), codigo="9999"),          # falta de peças: não
        _estado(5, _h(25, 13), _h(25, 14), codigo="0010"),          # preventiva (grupo 0002): não
        _estado(6, _h(25, 14), _h(25, 15), codigo="1005"),          # setup no grupo 0003: não
        _estado(7, _h(25, 15), _h(25, 16), planejado=True),         # corretiva programada: não
        _estado(8, _h(25, 16), _h(25, 17), automatico=True),        # intervalo automático: não
        _estado(9, _h(25, 17), _h(25, 18), categoria="producao"),   # produção: não
    ]


def _settings():
    return WebSettings(
        environment="test",
        session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
        allowed_hosts=("testserver",),
        allowed_origins=("http://testserver",),
    )


def _user(role="lider", assigned="manutencao", uid=800, nome="Mantenedor"):
    return SessionUser(
        id=uid, name=nome, role=role, assigned_level=assigned,
        management_access=can_access_management_web(role),
        andon_access=True, operator_access=role.startswith("operador_"),
    )


class _ApiCase(unittest.TestCase):
    def _build(self, db):
        self.db = db
        self.app = create_app(settings=_settings(), database_factory=lambda: db)
        self.app.dependency_overrides[get_database] = lambda: db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def _as(self, user):
        # Não substitui require_manutencao_user: a trava real é que deve negar.
        self.app.dependency_overrides[get_current_user] = lambda: user


class GeracaoTests(unittest.TestCase):
    def _servico(self, db):
        return MaintenanceSuggestionService(db, 800, "Mantenedor", now_func=lambda: AGORA)

    def test_gera_so_nao_planejada_do_grupo_manutencao_com_10_min_ou_mais(self):
        db = _BancoEmMemoria(_estados_padrao())
        itens = self._servico(db).listar()
        self.assertEqual(sorted(i["recurso"] for i in itens), ["DOBRA1", "DOBRA2"])
        self.assertEqual({i["status"] for i in itens}, {"sugerida"})
        por = {i["recurso"]: i for i in itens}
        self.assertEqual(por["DOBRA1"]["parada_segundos"], 25 * 60)
        self.assertEqual(por["DOBRA2"]["parada_segundos"], MIN_PARADA_SEGUNDOS)
        self.assertEqual(por["DOBRA1"]["parada_fim"], _h(25, 8, 25))
        self.assertEqual(por["DOBRA1"]["op"], "OP-1")
        self.assertEqual(MIN_PARADA_SEGUNDOS, 600)

    def test_idempotente_rodar_duas_vezes_mantem_as_mesmas_linhas(self):
        db = _BancoEmMemoria(_estados_padrao())
        servico = self._servico(db)
        primeira = servico.listar()
        segunda = servico.listar()
        servico.gerar()
        self.assertEqual(primeira, segunda)
        self.assertEqual(len(db.sugestoes), 2)

    def test_parada_em_curso_fica_sem_fim_e_a_duracao_e_atualizada_enquanto_sugerida(self):
        db = _BancoEmMemoria([_estado(1, _h(26, 11), None)])  # em curso desde 11:00; agora 12:00
        item = self._servico(db).listar()[0]
        self.assertIsNone(item["parada_fim"])
        self.assertEqual(item["parada_segundos"], 3600)
        db.estados = [_estado(1, _h(26, 11), _h(26, 11, 40))]  # a parada terminou
        item = self._servico(db).listar()[0]
        self.assertEqual((item["parada_fim"], item["parada_segundos"]), (_h(26, 11, 40), 40 * 60))
        self.assertEqual(len(db.sugestoes), 1)

    def test_parada_recortada_na_borda_da_janela_nao_gera_sugestao_nova(self):
        # Começou antes da janela (7 dias a partir da meia-noite): o início vem
        # recortado em 19/10 00:00 e mudaria a chave a cada dia se fosse gravado.
        db = _BancoEmMemoria([_estado(1, _h(18, 23), _h(19, 1))])
        db.estados[0]["inicio_periodo"] = _h(19, 0)
        self.assertEqual(self._servico(db).listar(), [])
        self.assertEqual(db.sugestoes, [])

    def test_sem_catalogo_nao_infere_manutencao_pelo_texto(self):
        db = _BancoEmMemoria(_estados_padrao())
        db.listar_status_recursos = lambda **_k: []
        self.assertEqual(self._servico(db).listar(), [])

    def test_decidida_nunca_volta_a_sugerida_nem_e_duplicada(self):
        db = _BancoEmMemoria(_estados_padrao())
        servico = self._servico(db)
        alvo = servico.listar()[0]
        servico.descartar(alvo["id"], "ruído")
        db.estados = [dict(e) for e in db.estados]
        restantes = servico.listar()
        self.assertNotIn(alvo["id"], [i["id"] for i in restantes])
        self.assertEqual(servico.listar("descartada")[0]["id"], alvo["id"])
        self.assertEqual(len(db.sugestoes), 2)
        self.assertEqual(db.sugestoes[alvo["id"] - 1]["status"], "descartada")

    def test_status_invalido_e_erro_de_regra(self):
        with self.assertRaises(MaintenanceSuggestionError) as erro:
            self._servico(_BancoEmMemoria()).listar("qualquer")
        self.assertEqual(erro.exception.status_code, 422)


class ApiTests(_ApiCase):
    def setUp(self):
        self._build(_BancoEmMemoria(_estados_padrao()))
        self._as(_user())

    def _ids(self):
        return {i["recurso"]: i["id"] for i in self.client.get(M).json()["items"]}

    def test_contrato_do_get_e_do_post(self):
        corpo = self.client.get(M).json()
        self.assertEqual(set(corpo), {"status", "limit", "count", "items"})
        self.assertEqual((corpo["status"], corpo["limit"], corpo["count"]), ("sugerida", 200, 2))
        self.assertEqual(
            set(corpo["items"][0]),
            {"id", "recurso", "setor", "parada_inicio", "parada_fim", "parada_segundos", "motivo", "op",
             "status", "criada_em", "decidido_por_id", "decidido_por_nome", "decidido_em", "nota"},
        )
        ids = self._ids()
        resposta = self.client.post(f"{M}/{ids['DOBRA1']}/accept", json={"nota": "  chamar eletricista "})
        self.assertEqual(resposta.status_code, 200, resposta.text)
        corpo = resposta.json()
        self.assertEqual(set(corpo), {"ok", "item"})
        item = corpo["item"]
        self.assertEqual((item["status"], item["nota"], item["decidido_por_id"], item["decidido_por_nome"]),
                         ("aceita", "chamar eletricista", 800, "Mantenedor"))
        self.assertIsNotNone(item["decidido_em"])

    def test_aceitar_descartar_e_filtro_por_status(self):
        ids = self._ids()
        self.assertEqual(self.client.post(f"{M}/{ids['DOBRA1']}/accept").status_code, 200)  # sem corpo
        self.assertEqual(self.client.post(f"{M}/{ids['DOBRA2']}/discard", json={}).status_code, 200)
        self.assertEqual(self.client.get(M).json()["count"], 0)
        self.assertEqual([i["recurso"] for i in self.client.get(M, params={"status": "aceita"}).json()["items"]],
                         ["DOBRA1"])
        descartadas = self.client.get(M, params={"status": "descartada"}).json()["items"]
        self.assertEqual([i["recurso"] for i in descartadas], ["DOBRA2"])
        self.assertIsNone(descartadas[0]["nota"])
        self.assertEqual(self.client.get(M, params={"status": "xis"}).status_code, 422)

    def test_decidir_de_novo_da_409_estruturado_e_nao_muda_nada(self):
        ids = self._ids()
        sid = ids["DOBRA1"]
        self.assertEqual(self.client.post(f"{M}/{sid}/accept").status_code, 200)
        for acao in ("accept", "discard"):
            resposta = self.client.post(f"{M}/{sid}/{acao}")
            self.assertEqual(resposta.status_code, 409)
            corpo = resposta.json()
            self.assertEqual(corpo["code"], "maintenance_suggestion_already_decided")
            self.assertEqual(corpo["details"]["status"], "aceita")
            self.assertEqual(corpo["details"]["decidido_por_nome"], "Mantenedor")
        self.assertEqual(self.db.sugestoes[sid - 1]["status"], "aceita")

    def test_id_inexistente_404_e_invalido_422_e_nota_longa_422(self):
        self.assertEqual(self.client.post(f"{M}/9999/accept").status_code, 404)
        self.assertEqual(self.client.post(f"{M}/9999/discard").json()["code"], "maintenance_suggestion_not_found")
        self.assertEqual(self.client.post(f"{M}/0/accept").status_code, 422)
        sid = self._ids()["DOBRA1"]
        self.assertEqual(self.client.post(f"{M}/{sid}/accept", json={"nota": "x" * 501}).status_code, 422)
        self.assertEqual(self.client.post(f"{M}/{sid}/accept", json={"outro": 1}).status_code, 422)
        self.assertEqual(self.db.sugestoes[sid - 1]["status"], "sugerida")

    def test_so_manutencao_e_admin_leem_e_decidem(self):
        sid = self._ids()["DOBRA1"]
        self.db.chamadas_decisao = 0
        negados = [
            _user("lider", None), _user("lider", "lider_pintura"), _user("lider", "lider_solda"),
            _user("qualidade", "qualidade"), _user("gestor", "gestor"), _user("supervisor", "supervisor"),
            _user("diretoria", "diretoria"), _user("operador_dobra", "operador_dobra"),
        ]
        for usuario in negados:
            self._as(usuario)
            for resposta in (
                self.client.get(M),
                self.client.post(f"{M}/{sid}/accept"),
                self.client.post(f"{M}/{sid}/discard"),
            ):
                self.assertEqual(resposta.status_code, 403, usuario.assigned_level)
                self.assertEqual(resposta.json()["code"], "maintenance_access_denied")
        self.assertEqual(self.db.chamadas_decisao, 0)
        self.assertEqual(self.db.sugestoes[sid - 1]["status"], "sugerida")
        for ok in (_user("admin", "admin"), _user("lider", "manutencao")):
            self._as(ok)
            self.assertEqual(self.client.get(M).status_code, 200)
        self._as(_user("admin", "admin"))
        self.assertEqual(self.client.post(f"{M}/{sid}/accept").status_code, 200)

    def test_decisao_vai_para_a_auditoria_com_antes_e_depois(self):
        sid = self._ids()["DOBRA1"]
        self.client.post(f"{M}/{sid}/discard", json={"nota": "falso alarme"})
        self.assertEqual(len(self.db.auditoria), 1)
        a = self.db.auditoria[0]
        self.assertEqual((a["entidade"], a["chave"], a["acao"], a["usuario_id"], a["usuario_nome"]),
                         ("manutencao_sugestao", str(sid), "alterar", 800, "Mantenedor"))
        self.assertEqual(a["antes"], {"status": "sugerida"})
        self.assertEqual(a["depois"]["status"], "descartada")
        self.assertEqual(a["depois"]["nota"], "falso alarme")
        self.assertEqual(a["depois"]["recurso"], "DOBRA1")
        self.client.post(f"{M}/{sid}/discard")  # 409 não audita de novo
        self.assertEqual(len(self.db.auditoria), 1)

    def test_falha_da_auditoria_nao_derruba_a_decisao(self):
        def quebrado(**_):
            raise RuntimeError("log fora do ar")

        self.db.registrar_auditoria = quebrado
        sid = self._ids()["DOBRA1"]
        with self.assertLogs(level="ERROR"):
            self.assertEqual(self.client.post(f"{M}/{sid}/accept").status_code, 200)


class CatalogoPermissaoEScriptsTests(unittest.TestCase):
    def test_versao_catalogo_e_migration(self):
        self.assertGreaterEqual(SCHEMA_VERSION, 68)
        self.assertIn(68, MIGRATIONS)
        self.assertIn("manutencao_sugestoes", EXPECTED_TABLES)
        descricao, statements = MIGRATIONS[68]
        self.assertTrue(descricao)
        self.assertIn("ON CONFLICT (nome) DO NOTHING", statements[0])
        self.assertIn("'manutencao', 'Manutenção', 'lider'", statements[0])
        for statement in statements:
            self.assertRegex(statement, r"(?i)IF NOT EXISTS|OR REPLACE|IF EXISTS|CREATE TRIGGER|ON CONFLICT")

    def test_allowlist_da_auditoria(self):
        self.assertEqual(
            CAMPOS_AUDITAVEIS["manutencao_sugestao"],
            ("sugestao_id", "recurso", "parada_inicio", "status", "nota"),
        )

    def test_permissao_le_o_nivel_atribuido_porque_o_efetivo_e_lider(self):
        self.assertTrue(can_manage_maintenance("lider", "manutencao"))
        self.assertTrue(can_manage_maintenance("admin", "admin"))
        self.assertTrue(can_manage_maintenance("admin"))
        for role, assigned in (("lider", None), ("lider", "lider_pintura"), ("qualidade", "qualidade"),
                               ("gestor", None), ("operador_dobra", "operador_dobra")):
            self.assertFalse(can_manage_maintenance(role, assigned), (role, assigned))
        # Nível atribuído sozinho não basta: o efetivo precisa ter acesso à gestão web.
        self.assertFalse(can_manage_maintenance("operador_dobra", "manutencao"))
        self.assertFalse(can_manage_maintenance(None, "manutencao"))
        # Nível personalizado (niveis_acesso), como os da migration 65: fora de USER_LEVELS.
        self.assertNotIn("manutencao", USER_LEVELS)

    def test_scripts_de_limpeza_do_teste_conhecem_a_tabela(self):
        from scripts import limpar_apontamentos_teste as limpar
        from scripts import resetar_banco_teste as reset

        self.assertIn("manutencao_sugestoes", reset.TRUNCATE_TABLES)
        self.assertNotIn("manutencao_sugestoes", reset.PROTECTED_TABLES)
        self.assertIn("manutencao_sugestoes", limpar.BASE_FACT_TABLES)

    def test_repositorio_nao_tem_delete_nem_volta_para_sugerida(self):
        import inspect
        import re

        from app.database import manutencao_sugestoes_repository as repo

        fonte = inspect.getsource(repo).lower()
        self.assertIsNone(re.search(r"delete\s+from", fonte))
        self.assertNotIn("totvs", fonte.replace("com o totvs", ""))
        self.assertNotIn("set status = 'sugerida'", fonte)
        self.assertTrue(hasattr(ManutencaoSugestoesRepositoryMixin, "decidir_sugestao_manutencao"))


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class SugestoesPostgresTests(_ApiCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        from app.database.config import load_postgres_config
        from app.database.database import Database

        base = load_postgres_config(testing=True)
        self.admin_dsn = base.dsn
        self.schema = "manut_sug_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self._drop_schema)
        self._build(Database(make_conninfo(base.dsn, options=f"-c search_path={self.schema}")))
        self._as(_user())

    def _drop_schema(self):
        import psycopg
        from psycopg import sql

        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _rows(self, query, params=()):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall() if cursor.description else []

    def _scalar(self, query, params=()):
        return list(self._rows(query, params)[0].values())[0]

    def _parada(self, recurso="DOBRA1", inicio=None, segundos=1500, fim=None):
        return {"recurso": recurso, "setor": "Dobra", "parada_inicio": inicio or _h(25, 8),
                "parada_fim": fim, "parada_segundos": segundos, "motivo": "QUEBRA", "op": "OP-1"}

    def test_migration_cria_nivel_tabela_indice_e_e_idempotente(self):
        self.assertEqual(self.db.obter_schema_version(), SCHEMA_VERSION)
        nivel = self._rows("SELECT rotulo, nivel_base FROM niveis_acesso WHERE nome = 'manutencao'")
        self.assertEqual([dict(r) for r in nivel], [{"rotulo": "Manutenção", "nivel_base": "lider"}])
        indices = {r["indexname"] for r in self._rows(
            "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
            " AND tablename = 'manutencao_sugestoes'")}
        self.assertIn("idx_manutencao_sugestoes_status", indices)
        self.db.create_tables()
        _, statements = MIGRATIONS[68]
        with self.db.connection() as connection, connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM niveis_acesso WHERE nome = 'manutencao'"), 1)

    def test_rollback_documentado_e_reaplicacao(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("DROP TABLE manutencao_sugestoes")
            cursor.execute("DROP FUNCTION manutencao_sugestoes_decisao_imutavel()")
            cursor.execute("DELETE FROM niveis_acesso WHERE nome = 'manutencao'")
            cursor.execute("DELETE FROM schema_migrations WHERE version = 68")
        self.db.create_tables()
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM manutencao_sugestoes"), 0)
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM niveis_acesso WHERE nome = 'manutencao'"), 1)
        self.assertEqual(self.db.obter_schema_version(), SCHEMA_VERSION)

    def test_gravar_e_idempotente_e_atualiza_so_enquanto_sugerida(self):
        self.db.gravar_sugestoes_manutencao([self._parada()])
        self.db.gravar_sugestoes_manutencao([self._parada()])
        self.assertEqual(self._scalar("SELECT COUNT(*) FROM manutencao_sugestoes"), 1)
        self.db.gravar_sugestoes_manutencao([self._parada(segundos=3000, fim=_h(25, 8, 50))])
        linha = self.db.listar_sugestoes_manutencao("sugerida")[0]
        self.assertEqual((linha["parada_segundos"], linha["parada_fim"]), (3000, _h(25, 8, 50)))
        self.db.decidir_sugestao_manutencao(linha["id"], status="descartada", usuario_id=1, usuario_nome="x")
        self.db.gravar_sugestoes_manutencao([self._parada(segundos=9000)])
        depois = self.db.buscar_sugestao_manutencao(linha["id"])
        self.assertEqual((depois["status"], depois["parada_segundos"]), ("descartada", 3000))
        self.assertEqual(self.db.listar_sugestoes_manutencao("sugerida"), [])

    def test_decisao_atomica_so_uma_vence(self):
        self.db.gravar_sugestoes_manutencao([self._parada()])
        sid = self.db.listar_sugestoes_manutencao("sugerida")[0]["id"]
        primeira = self.db.decidir_sugestao_manutencao(sid, status="aceita", usuario_id=1, usuario_nome="A")
        segunda = self.db.decidir_sugestao_manutencao(sid, status="descartada", usuario_id=2, usuario_nome="B")
        self.assertEqual(primeira["status"], "aceita")
        self.assertIsNone(segunda)
        self.assertEqual(self.db.buscar_sugestao_manutencao(sid)["decidido_por_nome"], "A")

    def test_banco_recusa_estado_incoerente_e_volta_para_sugerida(self):
        import psycopg

        self.db.gravar_sugestoes_manutencao([self._parada()])
        sid = self.db.listar_sugestoes_manutencao("sugerida")[0]["id"]
        with self.assertRaises(psycopg.errors.CheckViolation):  # decidida sem quem/quando
            self._rows("UPDATE manutencao_sugestoes SET status = 'aceita' WHERE id = %s", (sid,))
        with self.assertRaises(psycopg.errors.CheckViolation):  # status fora da lista
            self._rows("UPDATE manutencao_sugestoes SET status = 'x' WHERE id = %s", (sid,))
        with self.assertRaises(psycopg.errors.CheckViolation):  # nota > 500
            self._rows("UPDATE manutencao_sugestoes SET nota = %s WHERE id = %s", ("x" * 501, sid))
        self.db.decidir_sugestao_manutencao(sid, status="aceita", usuario_id=1, usuario_nome="A")
        with self.assertRaises(psycopg.errors.Error):  # gatilho: decidida nunca volta
            self._rows(
                "UPDATE manutencao_sugestoes SET status = 'sugerida', decidido_por_id = NULL,"
                " decidido_por_nome = NULL, decidido_em = NULL WHERE id = %s", (sid,))
        with self.assertRaises(psycopg.errors.Error):  # nem troca de aceita para descartada
            self._rows("UPDATE manutencao_sugestoes SET status = 'descartada' WHERE id = %s", (sid,))
        self.assertEqual(self.db.buscar_sugestao_manutencao(sid)["status"], "aceita")

    def test_api_real_get_lazy_sem_paradas_permissao_409_404_e_auditoria(self):
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO catalogo_status_recursos (codigo, nome, grupo_codigo, grupo_nome, habilitado,"
                " setup, retrabalho, oculto, requer_comentario, sincronizado_em)"
                " VALUES ('0011', 'QUEBRA', '0003', 'MANUTENÇÃO', TRUE, FALSE, FALSE, FALSE, FALSE, %s)",
                (AGORA,),
            )
        resposta = self.client.get(M)  # exercita a consulta real de paradas (vazia)
        self.assertEqual(resposta.status_code, 200, resposta.text)
        self.assertEqual(resposta.json()["items"], [])
        self.db.gravar_sugestoes_manutencao([self._parada(inicio=datetime.now().replace(microsecond=0))])
        sid = self.db.listar_sugestoes_manutencao("sugerida")[0]["id"]
        self._as(_user("lider", "lider_pintura"))
        self.assertEqual(self.client.post(f"{M}/{sid}/accept").status_code, 403)
        self.assertEqual(self.db.buscar_sugestao_manutencao(sid)["status"], "sugerida")
        self._as(_user())
        self.assertEqual(self.client.post(f"{M}/{sid}/accept", json={"nota": "ok"}).status_code, 200)
        self.assertEqual(self.client.post(f"{M}/{sid}/discard").status_code, 409)
        self.assertEqual(self.client.post(f"{M}/987654/accept").status_code, 404)
        linhas = self.db.listar_auditoria(entidade="manutencao_sugestao", chave=str(sid))
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["acao"], "alterar")
        self.assertEqual(linhas[0]["depois"]["status"], "aceita")


if __name__ == "__main__":
    unittest.main()
