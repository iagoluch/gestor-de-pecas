"""Botão de chamada: repositório (Postgres real, schema isolado) e rotas da API."""

from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database.config import load_postgres_config
from app.database.database import Database
from backend.api.config import WebSettings
from backend.api.dependencies.auth import (
    get_current_user,
    require_admin_user,
    require_csrf,
    require_management_user,
)
from backend.api.database import get_database
from backend.api.main import create_app
from backend.api.routers.chamadas import MOTIVOS
from backend.api.schemas.auth import SessionUser


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class ChamadaRepositoryTests(unittest.TestCase):
    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "gestor_chamadas_test_" + uuid4().hex
        self.admin_dsn = base.dsn
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        isolated_dsn = make_conninfo(base.dsn, options=f"-c search_path={self.schema}")
        self.db = Database(isolated_dsn)

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def test_contato_upsert_por_nome_e_funcao_case_insensitive(self):
        primeiro = self.db.salvar_chamada_contato(nome="Fulano", funcao="Líder")
        repetido = self.db.salvar_chamada_contato(nome="fulano", funcao="líder", ativo=False)
        self.assertEqual(primeiro["id"], repetido["id"])
        self.assertFalse(repetido["ativo"])

    def test_busca_filtra_por_nome_ou_funcao_e_ignora_inativos(self):
        self.db.salvar_chamada_contato(nome="Fulano", funcao="Líder")
        self.db.salvar_chamada_contato(nome="Ciclano", funcao="Supervisor", ativo=False)
        ativos = self.db.listar_chamada_contatos()
        self.assertEqual([c["nome"] for c in ativos], ["Fulano"])
        por_funcao = self.db.listar_chamada_contatos(somente_ativos=False, busca="supervi")
        self.assertEqual([c["nome"] for c in por_funcao], ["Ciclano"])

    def test_busca_normal_nunca_traz_telegram_do_contato(self):
        self.db.salvar_chamada_contato(nome="Fulano", funcao="Líder", telegram_chat_id="123456789")
        contato = self.db.listar_chamada_contatos()[0]
        self.assertNotIn("telegram_chat_id", contato)

    def test_listagem_completa_traz_telegram_para_o_admin(self):
        self.db.salvar_chamada_contato(nome="Fulano", funcao="Líder", telegram_chat_id="123456789")
        contato = self.db.listar_chamada_contatos(completo=True)[0]
        self.assertEqual(contato["telegram_chat_id"], "123456789")

    def test_registrar_chamada_devolve_o_telegram_do_contato_para_roteamento(self):
        com_telegram = self.db.salvar_chamada_contato(
            nome="Fulano", funcao="Líder", telegram_chat_id="123456789"
        )
        sem_telegram = self.db.salvar_chamada_contato(nome="Ciclano", funcao="Supervisor")

        chamada_1 = self.db.registrar_chamada(
            contato_id=com_telegram["id"], motivo="Manutenção", comentario="x",
            solicitante_nome="y", solicitante_nivel="z",
        )
        self.assertEqual(chamada_1["contato_telegram_chat_id"], "123456789")

        chamada_2 = self.db.registrar_chamada(
            contato_id=sem_telegram["id"], motivo="Manutenção", comentario="x",
            solicitante_nome="y", solicitante_nivel="z",
        )
        self.assertIsNone(chamada_2["contato_telegram_chat_id"])

    def test_registrar_chamada_guarda_retrato_do_contato(self):
        contato = self.db.salvar_chamada_contato(nome="Fulano", funcao="Líder")
        chamada = self.db.registrar_chamada(
            contato_id=contato["id"],
            motivo="Manutenção",
            comentario="Máquina parada",
            solicitante_nome="Operador X",
            solicitante_nivel="operador_corte",
        )
        self.assertEqual(chamada["contato_nome"], "Fulano")
        self.assertEqual(chamada["contato_funcao"], "Líder")
        self.assertFalse(chamada["telegram_enviado"])

        # Remover o contato depois não apaga nem corrompe o histórico.
        self.db.remover_chamada_contato(contato["id"])
        historico = self.db.listar_chamadas()
        self.assertEqual(historico[0]["contato_nome"], "Fulano")
        self.assertIsNone(historico[0]["contato_id"])

    def test_motivo_e_comentario_sao_obrigatorios(self):
        contato = self.db.salvar_chamada_contato(nome="Fulano", funcao="Líder")
        with self.assertRaises(ValueError):
            self.db.registrar_chamada(
                contato_id=contato["id"],
                motivo="",
                comentario="algo",
                solicitante_nome="x",
                solicitante_nivel="y",
            )
        with self.assertRaises(ValueError):
            self.db.registrar_chamada(
                contato_id=contato["id"],
                motivo="Manutenção",
                comentario="   ",
                solicitante_nome="x",
                solicitante_nivel="y",
            )

    def test_chamada_recusa_contato_inativo_ou_inexistente(self):
        contato = self.db.salvar_chamada_contato(nome="Fulano", funcao="Líder", ativo=False)
        with self.assertRaises(ValueError):
            self.db.registrar_chamada(
                contato_id=contato["id"],
                motivo="Outro",
                comentario="x",
                solicitante_nome="y",
                solicitante_nivel="z",
            )
        with self.assertRaises(ValueError):
            self.db.registrar_chamada(
                contato_id=999999,
                motivo="Outro",
                comentario="x",
                solicitante_nome="y",
                solicitante_nivel="z",
            )

    def test_apenas_um_contato_padrao_da_gestao_por_vez(self):
        self.assertIsNone(self.db.buscar_contato_padrao_gestao())
        primeiro = self.db.salvar_chamada_contato(nome="Fulano", funcao="Líder", padrao_gestao=True)
        self.assertEqual(self.db.buscar_contato_padrao_gestao()["id"], primeiro["id"])

        segundo = self.db.salvar_chamada_contato(nome="Ciclano", funcao="Supervisor", padrao_gestao=True)
        padrao_atual = self.db.buscar_contato_padrao_gestao()
        self.assertEqual(padrao_atual["id"], segundo["id"])

        atualizado_primeiro = self.db.listar_chamada_contatos(somente_ativos=False)
        primeiro_row = next(c for c in atualizado_primeiro if c["id"] == primeiro["id"])
        self.assertFalse(primeiro_row["padrao_gestao"])

    def test_contato_padrao_inativo_nao_e_devolvido(self):
        contato = self.db.salvar_chamada_contato(
            nome="Fulano", funcao="Líder", padrao_gestao=True, ativo=False
        )
        self.assertTrue(contato["padrao_gestao"])
        self.assertIsNone(self.db.buscar_contato_padrao_gestao())

    def test_sininho_conta_tudo_antes_da_primeira_leitura(self):
        usuario_id = self.db.criar_usuario("Gestor Sininho", "senha-123", "gestor")
        contato = self.db.salvar_chamada_contato(nome="Fulano", funcao="Líder")
        self.assertEqual(self.db.contar_chamadas_nao_vistas(usuario_id), 0)
        self.db.registrar_chamada(
            contato_id=contato["id"], motivo="Manutenção", comentario="x",
            solicitante_nome="Operador", solicitante_nivel="operador_corte",
        )
        # Sem nunca ter marcado como visto, a chamada já existente conta.
        self.assertEqual(self.db.contar_chamadas_nao_vistas(usuario_id), 1)

    def test_marcar_visto_zera_o_sininho_ate_a_proxima_chamada(self):
        usuario_id = self.db.criar_usuario("Gestor Sininho", "senha-123", "gestor")
        contato = self.db.salvar_chamada_contato(nome="Fulano", funcao="Líder")
        self.db.registrar_chamada(
            contato_id=contato["id"], motivo="Manutenção", comentario="x",
            solicitante_nome="Operador", solicitante_nivel="operador_corte",
        )
        self.db.marcar_chamadas_vistas(usuario_id)
        self.assertEqual(self.db.contar_chamadas_nao_vistas(usuario_id), 0)

        self.db.registrar_chamada(
            contato_id=contato["id"], motivo="Qualidade", comentario="y",
            solicitante_nome="Operador", solicitante_nivel="operador_corte",
        )
        self.assertEqual(self.db.contar_chamadas_nao_vistas(usuario_id), 1)

    def test_sininho_e_por_conta_cada_usuario_tem_o_proprio_estado(self):
        gestor_a = self.db.criar_usuario("Gestor A", "senha-123", "gestor")
        gestor_b = self.db.criar_usuario("Gestor B", "senha-123", "gestor")
        contato = self.db.salvar_chamada_contato(nome="Fulano", funcao="Líder")
        self.db.registrar_chamada(
            contato_id=contato["id"], motivo="Manutenção", comentario="x",
            solicitante_nome="Operador", solicitante_nivel="operador_corte",
        )
        self.db.marcar_chamadas_vistas(gestor_a)
        self.assertEqual(self.db.contar_chamadas_nao_vistas(gestor_a), 0)
        self.assertEqual(self.db.contar_chamadas_nao_vistas(gestor_b), 1)

    def test_marcar_telegram_atualiza_o_registro(self):
        contato = self.db.salvar_chamada_contato(nome="Fulano", funcao="Líder")
        chamada = self.db.registrar_chamada(
            contato_id=contato["id"],
            motivo="Qualidade",
            comentario="x",
            solicitante_nome="y",
            solicitante_nivel="z",
        )
        atualizada = self.db.marcar_chamada_telegram(chamada["id"], enviado=True, erro=None)
        self.assertTrue(atualizada["telegram_enviado"])
        falha = self.db.marcar_chamada_telegram(chamada["id"], enviado=False, erro="timeout")
        self.assertFalse(falha["telegram_enviado"])
        self.assertEqual(falha["telegram_erro"], "timeout")


class _FakeChamadaDatabase:
    """Fake mínimo — só os métodos que o router de chamadas usa."""

    def __init__(self):
        self.contatos = {
            1: {
                "id": 1, "nome": "Fulano", "funcao": "Líder", "ativo": True,
                "padrao_gestao": False, "telegram_chat_id": None, "setores": [],
            }
        }
        self.chamadas = []
        self.operadores = {
            "0042": {"cracha": "0042", "nome": "Maria Operadora", "ativo": True},
        }
        self._next_id = 1
        self.vistas = {}

    def buscar_operadores_apontamento(self, crachas):
        return [
            dict(self.operadores[cracha])
            for cracha in crachas
            if cracha in self.operadores and self.operadores[cracha]["ativo"]
        ]

    def buscar_contato_padrao_gestao(self):
        item = next(
            (dict(c) for c in self.contatos.values() if c["padrao_gestao"] and c["ativo"]), None
        )
        if item is not None:
            item.pop("telegram_chat_id", None)
        return item

    def listar_chamada_contatos(self, *, somente_ativos=True, busca=None, completo=False, setor=None):
        items = list(self.contatos.values())
        if somente_ativos:
            items = [c for c in items if c["ativo"]]
        if setor:
            items = [c for c in items if not c.get("setores") or setor in c["setores"]]
        if completo:
            return [dict(c) for c in items]
        return [{k: v for k, v in c.items() if k != "telegram_chat_id"} for c in items]

    def registrar_chamada(
        self,
        *,
        contato_id,
        motivo,
        comentario,
        solicitante_nome,
        solicitante_nivel,
        solicitante_cracha=None,
        solicitante_email=None,
    ):
        contato = self.contatos.get(contato_id)
        if contato is None or not contato["ativo"]:
            raise ValueError("Contato selecionado não existe ou não está mais ativo.")
        if not str(motivo or "").strip() or not str(comentario or "").strip():
            raise ValueError("Motivo e comentário da chamada são obrigatórios.")
        self._next_id += 1
        chamada = {
            "id": self._next_id,
            "contato_id": contato_id,
            "contato_nome": contato["nome"],
            "contato_funcao": contato["funcao"],
            "motivo": motivo,
            "comentario": comentario,
            "solicitante_nome": solicitante_nome,
            "solicitante_nivel": solicitante_nivel,
            "solicitante_cracha": solicitante_cracha,
            "solicitante_email": solicitante_email,
            "telegram_enviado": False,
            "telegram_erro": None,
        }
        self.chamadas.append(chamada)
        resultado = dict(chamada)
        resultado["contato_telegram_chat_id"] = contato.get("telegram_chat_id")
        return resultado

    def marcar_chamada_telegram(self, chamada_id, *, enviado, erro=None):
        for chamada in self.chamadas:
            if chamada["id"] == chamada_id:
                chamada["telegram_enviado"] = enviado
                chamada["telegram_erro"] = erro
                return dict(chamada)
        return None

    def salvar_chamada_contato(
        self, *, contato_id=None, nome, funcao, ativo=True, padrao_gestao=False,
        telegram_chat_id=None, setores=None,
    ):
        if not str(nome or "").strip() or not str(funcao or "").strip():
            raise ValueError("Nome e função do contato são obrigatórios.")
        if contato_id is None:
            contato_id = max(self.contatos, default=0) + 1
        if padrao_gestao:
            for outro in self.contatos.values():
                outro["padrao_gestao"] = False
        self.contatos[contato_id] = {
            "id": contato_id, "nome": nome, "funcao": funcao, "ativo": ativo,
            "padrao_gestao": padrao_gestao, "telegram_chat_id": telegram_chat_id,
            "setores": list(setores or []),
        }
        return dict(self.contatos[contato_id])

    def remover_chamada_contato(self, contato_id):
        return self.contatos.pop(contato_id, None) is not None

    def listar_chamadas(self, *, limite=100):
        return list(reversed(self.chamadas))[:limite]

    def contar_chamadas_nao_vistas(self, usuario_id):
        visto_em = self.vistas.get(usuario_id)
        if visto_em is None:
            return len(self.chamadas)
        return sum(1 for c in self.chamadas if c["id"] > visto_em)

    def marcar_chamadas_vistas(self, usuario_id, *, quando=None):
        self.vistas[usuario_id] = max((c["id"] for c in self.chamadas), default=0)


def _settings(**overrides):
    return WebSettings(
        environment="test",
        session_secret="test-secret-that-is-long-enough-for-session-signatures-123456",
        allowed_hosts=("testserver",),
        allowed_origins=("http://testserver",),
        **overrides,
    )


def _operator_user():
    return SessionUser(
        id=1, name="Operador X", role="operador_corte",
        management_access=False, andon_access=False, operator_access=True,
    )


def _management_user():
    return SessionUser(
        id=2, name="Gestor Y", role="supervisor",
        management_access=True, andon_access=True, operator_access=False,
    )


def _admin_user():
    return SessionUser(
        id=3, name="Admin Z", role="admin",
        management_access=True, andon_access=True, operator_access=False,
    )


class ChamadaApiTests(unittest.TestCase):
    def setUp(self):
        self.db = _FakeChamadaDatabase()
        self.app = create_app(settings=_settings(), database_factory=lambda: self.db)
        self.app.dependency_overrides[get_database] = lambda: self.db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.client = TestClient(self.app)

    def _as(self, user):
        self.app.dependency_overrides[get_current_user] = lambda: user
        self.app.dependency_overrides[require_management_user] = (
            lambda: user if user.management_access else self._forbid()
        )
        self.app.dependency_overrides[require_admin_user] = (
            lambda: user if user.role == "admin" else self._forbid()
        )

    @staticmethod
    def _forbid():
        from backend.api.errors import AppError

        raise AppError("management_access_denied", "sem acesso", status_code=403)

    def test_operador_e_gestao_conseguem_buscar_contatos_e_motivos(self):
        for user in (_operator_user(), _management_user()):
            with self.subTest(role=user.role):
                self._as(user)
                resposta = self.client.get("/api/v1/chamadas/contatos")
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(resposta.json()["items"][0]["nome"], "Fulano")

                motivos = self.client.get("/api/v1/chamadas/motivos")
                self.assertEqual(motivos.json()["items"], list(MOTIVOS))

    def test_criar_chamada_sem_telegram_configurado_registra_mas_nao_envia(self):
        self._as(_operator_user())
        resposta = self.client.post(
            "/api/v1/chamadas",
            json={
                "contato_id": 1, "motivo": "Manutenção", "comentario": "Máquina parada",
                "solicitante_cracha": "0042",
            },
        )
        self.assertEqual(resposta.status_code, 200)
        corpo = resposta.json()
        self.assertTrue(corpo["ok"])
        self.assertFalse(corpo["telegram_enviado"])
        self.assertEqual(corpo["item"]["contato_nome"], "Fulano")
        self.assertEqual(corpo["item"]["solicitante_cracha"], "0042")
        self.assertEqual(corpo["item"]["solicitante_nome"], "Maria Operadora")

    def test_operador_sem_cracha_e_recusado(self):
        self._as(_operator_user())
        resposta = self.client.post(
            "/api/v1/chamadas",
            json={"contato_id": 1, "motivo": "Manutenção", "comentario": "Máquina parada"},
        )
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(resposta.json()["code"], "chamada_identificacao_obrigatoria")

    def test_operador_com_cracha_inexistente_e_recusado_sem_registrar(self):
        self._as(_operator_user())
        resposta = self.client.post(
            "/api/v1/chamadas",
            json={
                "contato_id": 1, "motivo": "Manutenção", "comentario": "Máquina parada",
                "solicitante_cracha": "9999",
            },
        )
        self.assertEqual(resposta.status_code, 422)
        self.assertEqual(resposta.json()["code"], "chamada_cracha_invalido")
        self.assertEqual(self.db.chamadas, [])

    def test_gestao_sem_nome_ou_email_e_recusada(self):
        self._as(_management_user())
        sem_nome = self.client.post(
            "/api/v1/chamadas",
            json={
                "contato_id": 1, "motivo": "Manutenção", "comentario": "x",
                "solicitante_email": "gestor@empresa.com",
            },
        )
        self.assertEqual(sem_nome.status_code, 422)

        sem_email = self.client.post(
            "/api/v1/chamadas",
            json={
                "contato_id": 1, "motivo": "Manutenção", "comentario": "x",
                "solicitante_nome_manual": "Gestor de Verdade",
            },
        )
        self.assertEqual(sem_email.status_code, 422)

    def test_gestao_com_nome_e_email_usa_esses_dados_como_solicitante(self):
        self._as(_management_user())
        resposta = self.client.post(
            "/api/v1/chamadas",
            json={
                "contato_id": 1, "motivo": "Manutenção", "comentario": "x",
                "solicitante_nome_manual": "Gestor de Verdade",
                "solicitante_email": "gestor@empresa.com",
            },
        )
        self.assertEqual(resposta.status_code, 200)
        item = resposta.json()["item"]
        self.assertEqual(item["solicitante_nome"], "Gestor de Verdade")
        self.assertEqual(item["solicitante_email"], "gestor@empresa.com")
        self.assertIsNone(item["solicitante_cracha"])

    def test_criar_chamada_com_telegram_configurado_envia_e_persiste(self):
        self.app = create_app(
            settings=_settings(
                telegram_bot_token="token-teste", chamada_telegram_chat_id="-100999"
            ),
            database_factory=lambda: self.db,
        )
        self.app.dependency_overrides[get_database] = lambda: self.db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.client = TestClient(self.app)
        self._as(_operator_user())
        with patch(
            "backend.api.routers.chamadas.send_telegram_message", return_value=True
        ) as mocked:
            resposta = self.client.post(
                "/api/v1/chamadas",
                json={
                    "contato_id": 1, "motivo": "Qualidade", "comentario": "Peça fora do padrão",
                    "solicitante_cracha": "0042",
                },
            )
        self.assertEqual(resposta.status_code, 200)
        self.assertTrue(resposta.json()["telegram_enviado"])
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.kwargs["chat_id"], "-100999")
        self.assertIn("Maria Operadora (operador_corte) — crachá 0042", mocked.call_args.kwargs["text"])

    def test_contato_com_telegram_proprio_e_avisado_direto_nao_no_chat_geral(self):
        self.db.contatos[1]["telegram_chat_id"] = "555111222"
        self.app = create_app(
            settings=_settings(
                telegram_bot_token="token-teste", chamada_telegram_chat_id="-100999"
            ),
            database_factory=lambda: self.db,
        )
        self.app.dependency_overrides[get_database] = lambda: self.db
        self.app.dependency_overrides[require_csrf] = lambda: None
        self.client = TestClient(self.app)
        self._as(_operator_user())
        with patch(
            "backend.api.routers.chamadas.send_telegram_message", return_value=True
        ) as mocked:
            resposta = self.client.post(
                "/api/v1/chamadas",
                json={
                    "contato_id": 1, "motivo": "Qualidade", "comentario": "x",
                    "solicitante_cracha": "0042",
                },
            )
        self.assertTrue(resposta.json()["telegram_enviado"])
        # Vai direto pro Telegram do contato, não pro chat geral do ambiente.
        self.assertEqual(mocked.call_args.kwargs["chat_id"], "555111222")

    def test_motivo_fora_da_lista_e_recusado(self):
        self._as(_operator_user())
        resposta = self.client.post(
            "/api/v1/chamadas",
            json={"contato_id": 1, "motivo": "Motivo Inventado", "comentario": "x"},
        )
        self.assertEqual(resposta.status_code, 422)

    def test_comentario_vazio_e_recusado_pelo_schema(self):
        self._as(_operator_user())
        resposta = self.client.post(
            "/api/v1/chamadas",
            json={"contato_id": 1, "motivo": "Manutenção", "comentario": ""},
        )
        self.assertEqual(resposta.status_code, 422)

    def test_admin_contatos_exige_conta_admin_gestao_comum_nao_basta(self):
        self._as(_operator_user())
        resposta = self.client.get("/api/v1/chamadas/admin/contatos")
        self.assertEqual(resposta.status_code, 403)

        # Gestão comum (supervisor, líder, etc.) vê/faz chamadas, mas não
        # decide quem entra na lista de contatos — decisão do usuário, 14/09/2026.
        self._as(_management_user())
        resposta = self.client.get("/api/v1/chamadas/admin/contatos")
        self.assertEqual(resposta.status_code, 403)

        self._as(_admin_user())
        resposta = self.client.get("/api/v1/chamadas/admin/contatos")
        self.assertEqual(resposta.status_code, 200)

    def test_gestao_comum_continua_vendo_o_historico_de_chamadas(self):
        self._as(_management_user())
        resposta = self.client.get("/api/v1/chamadas/admin/historico")
        self.assertEqual(resposta.status_code, 200)

    def test_contato_padrao_gestao_disponivel_a_qualquer_usuario_autenticado(self):
        self.db.contatos[1]["padrao_gestao"] = True
        for user in (_operator_user(), _management_user()):
            with self.subTest(role=user.role):
                self._as(user)
                resposta = self.client.get("/api/v1/chamadas/contato-padrao-gestao")
                self.assertEqual(resposta.status_code, 200)
                self.assertEqual(resposta.json()["item"]["nome"], "Fulano")

    def test_contato_padrao_gestao_nulo_quando_ninguem_marcado(self):
        self._as(_operator_user())
        resposta = self.client.get("/api/v1/chamadas/contato-padrao-gestao")
        self.assertIsNone(resposta.json()["item"])

    def test_sininho_exige_acesso_gerencial(self):
        self._as(_operator_user())
        resposta = self.client.get("/api/v1/chamadas/nao-vistas")
        self.assertEqual(resposta.status_code, 403)

    def test_sininho_conta_e_zera_ao_marcar_visto(self):
        self._as(_management_user())
        self.client.post(
            "/api/v1/chamadas",
            json={
                "contato_id": 1, "motivo": "Manutenção", "comentario": "x",
                "solicitante_nome_manual": "Gestor", "solicitante_email": "g@empresa.com",
            },
        )
        contagem = self.client.get("/api/v1/chamadas/nao-vistas")
        self.assertEqual(contagem.json()["count"], 1)

        self.client.post("/api/v1/chamadas/marcar-vistas")
        contagem = self.client.get("/api/v1/chamadas/nao-vistas")
        self.assertEqual(contagem.json()["count"], 0)

    def test_gestao_cria_edita_e_remove_contato(self):
        self._as(_admin_user())
        criado = self.client.post(
            "/api/v1/chamadas/admin/contatos",
            json={"nome": "Beltrano", "funcao": "Manutenção", "ativo": True},
        )
        self.assertEqual(criado.status_code, 200)
        contato_id = criado.json()["item"]["id"]

        editado = self.client.post(
            "/api/v1/chamadas/admin/contatos",
            json={"id": contato_id, "nome": "Beltrano", "funcao": "Manutenção Sênior", "ativo": True},
        )
        self.assertEqual(editado.json()["item"]["funcao"], "Manutenção Sênior")

        removido = self.client.delete(f"/api/v1/chamadas/admin/contatos/{contato_id}")
        self.assertEqual(removido.status_code, 200)

        inexistente = self.client.delete("/api/v1/chamadas/admin/contatos/999999")
        self.assertEqual(inexistente.status_code, 404)


if __name__ == "__main__":
    unittest.main()
