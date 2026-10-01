"""Roteamento de comandos do bot de fábrica e formatação pura."""

from datetime import datetime, time
import os
import unittest
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.core.operator_sectors import WELDING_SECTOR_NAMES
from backend.api.config import WebSettings
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.database.config import load_postgres_config
from app.database.database import Database

from mes.services.telegram_bot import (
    TelegramBotReply,
    TelegramFactoryBotService,
    _formatar_duracao,
    _formatar_percentual,
)
from mes.services.telegram_intents import parse_telegram_intent
from mes.services.telegram_digest import (
    DigestDestination,
    TelegramFactoryDigestScheduler,
    build_digest_destinations,
    build_digest_text,
    closed_report_period,
)
from mes.services.telegram_presenter import TelegramPresenter


class FormattingTests(unittest.TestCase):
    def test_duracao_formata_horas_minutos_e_menos_de_um_minuto(self):
        self.assertEqual(_formatar_duracao(30), "menos de 1min")
        self.assertEqual(_formatar_duracao(90), "1min")
        self.assertEqual(_formatar_duracao(3661), "1h 1min")

    def test_percentual_usa_o_valor_ja_em_escala_percentual(self):
        # MetricValue guarda 96.5 significando 96.5%, não 0.965.
        self.assertEqual(_formatar_percentual({"value": 96.5}), "96,5%")
        self.assertEqual(_formatar_percentual({"value": None}), "sem dado")
        self.assertEqual(_formatar_percentual(None), "sem dado")

    def test_presenter_op_tem_contexto_completo_escapado_e_sem_cabecalho_repetido(self):
        view = TelegramPresenter().my_status(
            operator={"nome": "Operador <teste>", "cracha": "42"},
            participations=[{
                "op": "TESTE-01",
                "setor": "Pintura",
                "peca": "PEÇA-01",
                "descricao": "Descrição <teste>",
                "etapa_roteiro": "JATO & CORTE",
                "quantidade": 20,
                "recurso": "Recurso & 01",
            }],
            now=datetime(2026, 9, 17, 8, 4),
        )

        self.assertNotIn("GESTOR DE PEÇAS", view.text)
        self.assertIn("👤", view.text)
        self.assertIn("🧾 OP: <b>TESTE-01</b>", view.text)
        self.assertIn("Setor: Pintura", view.text)
        self.assertIn("Peça: PEÇA-01", view.text)
        self.assertIn("Descrição: Descrição &lt;teste&gt;", view.text)
        self.assertIn("Etapa roteiro: JATO &amp; CORTE", view.text)
        self.assertIn("Quantidade: 20", view.text)
        self.assertIn("Operador &lt;teste&gt; • Recurso &amp; 01", view.text)

    def test_op_sem_setor_ou_operador_nao_inventa_colunas(self):
        text = TelegramPresenter().totvs_outbox_error({
            "production_order": "OP-SEM-CONTEXTO",
            "payload_context": {"resource": "RECURSO-01"},
            "last_delivery_class": "technical",
            "last_error_message": "indisponível",
        })

        self.assertIn("🧾 OP: <b>OP-SEM-CONTEXTO</b>", text)
        self.assertNotIn("Setor:", text)
        self.assertNotIn("Operador", text)


CODIGO_VALIDO = "ABCD2345"


class _FakeDb:
    """Só os métodos que os handlers testados aqui realmente chamam."""

    def __init__(self):
        self.operadores = {"1": {"id": 1, "cracha": "1", "nome": "Iago"}}
        self.vinculos = {}
        self.participacoes = {}
        self.chats_descobertos = {}
        self.codigos = {CODIGO_VALIDO: "1"}

    def registrar_chat_telegram_descoberto(self, chat_id, tipo, titulo):
        self.chats_descobertos[str(chat_id)] = {"tipo": tipo, "titulo": titulo}

    def vincular_telegram_por_codigo(self, codigo, chat_id):
        # A regra real (hash, validade, uso único, freio) é coberta contra o
        # PostgreSQL em TelegramLinkCodeDatabaseTests; aqui só o roteamento.
        cracha = self.codigos.pop(str(codigo).strip().upper(), None)
        if cracha is None:
            return {"status": "invalido"}
        self.vinculos[chat_id] = cracha
        return {"status": "ok", "operador": self.operadores[cracha]}

    def buscar_operador_por_telegram(self, chat_id):
        cracha = self.vinculos.get(chat_id)
        return self.operadores.get(cracha) if cracha else None

    def participacoes_ativas_por_cracha(self, cracha):
        return self.participacoes.get(cracha, [])


def _fake_service():
    service = TelegramFactoryBotService(
        _FakeDb(), now_func=lambda: datetime(2026, 9, 16, 15, 0, 0)
    )
    service.facade = _BotFacade()
    return service


def _update(text, *, chat_type="private", chat_id="42", title=None, update_type="message"):
    chat = {"id": chat_id, "type": chat_type}
    if title is not None:
        chat["title"] = title
    return {update_type: {"chat": chat, "text": text}}


def _callback(data, *, chat_id="42", message_id=77):
    return {
        "callback_query": {
            "id": "callback-1",
            "data": data,
            "message": {
                "message_id": message_id,
                "chat": {"id": chat_id, "type": "private"},
            },
        }
    }


class _BotFacade:
    def __init__(self):
        self.analytics = self._Analytics()
        self.management = self._Management()

    @staticmethod
    def andon(_filters):
        return {
            "summary": {"production": 3, "downtime": 1, "setup": 1, "rework": 0},
            "sectors": [
                {"name": "Corte", "resources": [{
                    "name": "LASER <01>",
                    "state": {"category": "parada", "display_label": "Manutenção & ajuste", "duration_seconds": 1920},
                }]},
                {"name": "Solda", "resources": [{"name": "Solda 01", "state": {"category": "producao"}}]},
                {"name": "Pintura", "resources": [{"name": "Cabine", "state": {"category": "setup"}}]},
                {"name": "Caldeiraria", "resources": [
                    {"name": "Dobra", "state": {"category": "producao"}},
                    {"name": "Serra", "state": {"category": "producao"}},
                ]},
            ],
        }

    class _Analytics:
        @staticmethod
        def quality(filters):
            values = {None: 1248, "Corte": 10, "Pintura": 20, "Dobra": 3, "Usinagem": 5, "Serra": 2}
            return {"totals": {"boa": values.get(filters.setor, 1), "refugo": 1, "retrabalho": 0}}

        @staticmethod
        def downtimes(_filters):
            return {"total_seconds": 3420, "by_reason": []}

    class _Management:
        @staticmethod
        def get_overview(_filters):
            return {"kpis": {"oee": {"value": 83.2}, "availability": {"value": 90.0}}}


class CommandRoutingTests(unittest.TestCase):
    def test_ignora_mensagem_de_grupo(self):
        service = _fake_service()
        self.assertIsNone(service.handle_update(_update("/ajuda", chat_type="group")))

    def test_descobre_grupo_e_canal_sem_responder(self):
        service = _fake_service()
        self.assertIsNone(
            service.handle_update(
                _update("oi", chat_type="supergroup", chat_id="-1001", title="Alertas")
            )
        )
        self.assertIsNone(
            service.handle_update(
                _update("oi", chat_type="supergroup", chat_id="-1001", title="Alertas TESTE")
            )
        )
        self.assertIsNone(
            service.handle_update(
                _update(
                    "oi",
                    chat_type="channel",
                    chat_id="-1002",
                    title="Produção",
                    update_type="channel_post",
                )
            )
        )
        self.assertEqual(
            service.db.chats_descobertos,
            {
                "-1001": {"tipo": "supergroup", "titulo": "Alertas TESTE"},
                "-1002": {"tipo": "channel", "titulo": "Produção"},
            },
        )

    def test_ignora_update_sem_texto(self):
        service = _fake_service()
        self.assertIsNone(service.handle_update({"message": {"chat": {"id": "42", "type": "private"}}}))

    def test_comando_desconhecido_devolve_ajuda(self):
        service = _fake_service()
        reply = service.handle_update(_update("/isso_nao_existe"))
        self.assertIsInstance(reply, TelegramBotReply)
        self.assertIn("/vincular", reply.text)

    def test_vincular_sem_codigo_pede_codigo_da_gestao(self):
        service = _fake_service()
        reply = service.handle_update(_update("/vincular"))
        self.assertIn("/vincular CÓDIGO", reply.text)
        self.assertIn("gestão", reply.text)

    def test_vincular_codigo_invalido_avisa_sem_vincular(self):
        service = _fake_service()
        reply = service.handle_update(_update("/vincular ZZZZ9999"))
        self.assertIn("inválido", reply.text)
        self.assertIsNone(service.db.buscar_operador_por_telegram("42"))

    def test_cracha_puro_nao_vincula(self):
        service = _fake_service()
        reply = service.handle_update(_update("/vincular 1"))
        self.assertNotIn("Pronto", reply.text)
        self.assertIsNone(service.db.buscar_operador_por_telegram("42"))

    def test_vincular_e_meustatus_sem_operacao_aberta(self):
        service = _fake_service()
        vinculo = service.handle_update(_update(f"/vincular {CODIGO_VALIDO}"))
        self.assertIn("Iago", vinculo.text)
        status = service.handle_update(_update("/meustatus"))
        self.assertIn("Nenhuma operação em aberto", status.text)

    def test_meustatus_lista_participacao_ativa(self):
        service = _fake_service()
        service.handle_update(_update(f"/vincular {CODIGO_VALIDO}"))
        service.db.participacoes["1"] = [
            {
                "op": "00601315003",
                "numero_operacao": "10",
                "recurso": "LASER1",
                "data_inicio": datetime(2026, 9, 16, 14, 30, 0),
            }
        ]
        status = service.handle_update(_update("/meustatus"))
        self.assertIn("00601315003", status.text)
        self.assertIn("LASER1", status.text)
        self.assertIn("30min", status.text)

    def test_start_e_menu_sem_vinculo_so_ensinam_a_vincular(self):
        service = _fake_service()
        service._snapshot = lambda: self.fail("chat não vinculado não pode consultar a fábrica")
        for command in ("/start", "/menu"):
            reply = service.handle_update(_update(command))
            self.assertIn("Vincular ao Gestor de Peças", reply.text)
            self.assertIn("/vincular CÓDIGO", reply.text)
            self.assertNotIn("Menu principal", reply.text)
            self.assertNotIn("1248", reply.text)
            self.assertEqual(reply.parse_mode, "HTML")
        for data in ("gp:home", "gp:factory", "gp:production", "gp:stops"):
            self.assertIn("Vincular ao Gestor de Peças", service.handle_update(_callback(data)).text)

    def test_menu_vinculado_exibe_nome_e_meu_status(self):
        service = _fake_service()
        service.handle_update(_update(f"/vincular {CODIGO_VALIDO}"))
        reply = service.handle_update(_update("/menu"))
        self.assertIn("Olá, Iago", reply.text)
        callbacks = {button["callback_data"] for row in reply.reply_markup["inline_keyboard"] for button in row}
        self.assertIn("gp:me", callbacks)

    def test_callbacks_principais_editam_mesma_mensagem_e_sao_respondidos(self):
        service = _fake_service()
        service.handle_update(_update(f"/vincular {CODIGO_VALIDO}"))
        for data in ("gp:home", "gp:factory", "gp:production", "gp:stops", "gp:fronts", "gp:help"):
            reply = service.handle_update(_callback(data))
            self.assertEqual(reply.message_id, 77)
            self.assertEqual(reply.callback_query_id, "callback-1")
            self.assertTrue(reply.reply_markup["inline_keyboard"])

    def test_quatro_frentes_atualizar_voltar_e_menu(self):
        service = _fake_service()
        service.handle_update(_update(f"/vincular {CODIGO_VALIDO}"))
        for front in ("corte", "solda", "pintura", "caldeiraria"):
            reply = service.handle_update(_callback(f"gp:front:{front}"))
            callbacks = {button["callback_data"] for row in reply.reply_markup["inline_keyboard"] for button in row}
            self.assertIn(f"gp:prod:{front}", callbacks)
            self.assertIn(f"gp:stops:{front}", callbacks)
            self.assertIn(f"gp:res:{front}", callbacks)
            self.assertIn(f"gp:front:{front}", callbacks)
            self.assertIn("gp:fronts", callbacks)
            self.assertIn("gp:home", callbacks)

    def test_botao_recursos_lista_recursos_do_setor(self):
        service = _fake_service()
        service.handle_update(_update(f"/vincular {CODIGO_VALIDO}"))
        reply = service.handle_update(_callback("gp:res:corte"))
        self.assertIn("Recursos · Corte", reply.text)
        self.assertIn("LASER &lt;01&gt;", reply.text)
        callbacks = {button["callback_data"] for row in reply.reply_markup["inline_keyboard"] for button in row}
        self.assertIn("gp:res:corte", callbacks)
        self.assertIn("gp:front:corte", callbacks)

    def test_frente_conta_e_colore_recursos_pela_categoria_canonica_do_andon(self):
        service = _fake_service()
        service.handle_update(_update(f"/vincular {CODIGO_VALIDO}"))
        snapshot = _BotFacade.andon(None)
        self.assertEqual(
            service._front_summary(snapshot, "corte"),
            {"production": 0, "downtime": 1, "setup": 0, "rework": 0},
        )
        self.assertEqual(service._front_summary(snapshot, "caldeiraria")["production"], 2)
        reply = service.handle_update(_callback("gp:res:corte"))
        self.assertIn("🔴 <b>LASER &lt;01&gt;</b>", reply.text)

    def test_comando_recursos_aceita_frente_por_texto_e_pede_frente_quando_ausente(self):
        service = _fake_service()
        service.handle_update(_update(f"/vincular {CODIGO_VALIDO}"))
        reply = service.handle_update(_update("/recursos solda"))
        self.assertIn("Recursos · Solda", reply.text)
        self.assertIn("Solda 01", reply.text)

        sem_frente = service.handle_update(_update("/recursos"))
        self.assertIn("Escolha uma frente", sem_frente.text)

    def test_html_dinamico_e_escapado(self):
        service = _fake_service()
        service.handle_update(_update(f"/vincular {CODIGO_VALIDO}"))
        reply = service.handle_update(_update("/fabrica"))
        self.assertIn("LASER &lt;01&gt;", reply.text)
        self.assertIn("Manutenção &amp; ajuste", reply.text)
        self.assertNotIn("LASER <01>", reply.text)

    def test_linguagem_natural_e_intent_desconhecida(self):
        service = _fake_service()
        service.handle_update(_update(f"/vincular {CODIGO_VALIDO}"))
        cases = {
            "como tá a fábrica?": "Status da fábrica",
            "tem parada no corte?": "Paradas · Corte",
            "produção da solda": "Produção · Solda",
            "recursos da solda": "Recursos · Solda",
            "como está a pintura?": "Pintura",
            "meu status": "Meu status",
            "o que você sabe fazer?": "Ajuda",
            "frase que não conheço": "Menu principal",
        }
        for text, expected in cases.items():
            self.assertIn(expected, service.handle_update(_update(text)).text)


class _PollingDb(_FakeDb):
    def __init__(self, cursor=None):
        super().__init__()
        self.cursor = cursor

    def obter_cursor_telegram_bot(self, bot_key):
        return self.cursor


def _dated(update, sent_at):
    next(iter(update.values()))["date"] = sent_at
    return update


def _raise(*_args, **_kwargs):
    raise RuntimeError("banco fora")


class PollingRobustnessTests(unittest.TestCase):
    NOW = 1_790_000_000.0

    def _service(self, db):
        service = TelegramFactoryBotService(
            db, now_func=lambda: datetime(2026, 9, 16, 15, 0, 0), epoch_func=lambda: self.NOW
        )
        service.facade = _BotFacade()
        return service

    def test_update_envenenado_e_descartado_com_log_error_sem_levantar(self):
        # O laço de polling só avança o cursor depois de handle_update; se ele
        # levantar, o mesmo update volta para sempre.
        db = _FakeDb()
        db.registrar_chat_telegram_descoberto = _raise
        service = self._service(db)
        venenos = (
            _update("oi", chat_type="group", chat_id="-1"),
            {"update_id": 9, "callback_query": {"message": "não é dict"}},
            {"update_id": 10, "message": 7},
        )
        for update in venenos:
            with self.assertLogs("mes.services.telegram_bot", level="ERROR"):
                self.assertIsNone(service.handle_update(update))

    def test_backlog_antigo_ignorado_na_primeira_rodada_sem_cursor(self):
        service = self._service(_PollingDb(cursor=None))
        self.assertIsNone(service.handle_update(_dated(_update("/ajuda"), self.NOW - 3600)))
        recente = service.handle_update(_dated(_update("/ajuda"), self.NOW - 30))
        self.assertIn("Ajuda", recente.text)

    def test_com_cursor_gravado_processa_mensagem_atrasada(self):
        service = self._service(_PollingDb(cursor=42))
        reply = service.handle_update(_dated(_update("/ajuda"), self.NOW - 3600))
        self.assertIn("Ajuda", reply.text)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "TEST_DATABASE_URL não configurada")
class TelegramLinkCodeDatabaseTests(unittest.TestCase):
    """Código de uso único, freio persistido e desvínculo contra o PostgreSQL
    de TESTE, num schema descartável (padrão de test_database_professionalization)."""

    def setUp(self):
        base = load_postgres_config(testing=True)
        self.schema = "gestor_test_" + uuid4().hex
        with psycopg.connect(base.dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.admin_dsn = base.dsn
        self.dsn = make_conninfo(base.dsn, options=f"-c search_path={self.schema}")
        self.db = Database(self.dsn)
        self.db.cadastrar_operador_apontamento("501", "Ana", ativo=True, fonte="teste")
        self.db.cadastrar_operador_apontamento("502", "Bruno", ativo=True, fonte="teste")
        ids = {row["cracha"]: row["id"] for row in self.db.listar_operadores_apontamento()}
        self.ana, self.bruno = ids["501"], ids["502"]
        self.service = TelegramFactoryBotService(self.db, now_func=lambda: datetime(2026, 10, 1, 9, 0))
        self.service.facade = _BotFacade()

    def tearDown(self):
        self.db.close()
        with psycopg.connect(self.admin_dsn, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(self.schema)))

    def _code(self, operador_id):
        result = self.db.gerar_codigo_vinculo_telegram(operador_id, criado_por="admin")
        self.assertEqual(result["status"], "ok")
        return result["codigo"]

    def test_codigo_valido_vincula_e_so_o_hash_fica_no_banco(self):
        code = self._code(self.ana)
        reply = self.service.handle_update(_update(f"/vincular {code.lower()}", chat_id="900"))
        self.assertIn("Pronto, Ana", reply.text)
        self.assertEqual(self.db.buscar_operador_por_telegram("900")["cracha"], "501")
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT codigo_hash FROM telegram_codigos_vinculo")
            stored = [row["codigo_hash"] for row in cursor.fetchall()]
        self.assertNotIn(code, stored)
        self.assertEqual(len(stored[0]), 64)

    def test_codigo_reutilizado_e_recusado(self):
        code = self._code(self.ana)
        self.assertEqual(self.db.vincular_telegram_por_codigo(code, "900")["status"], "ok")
        self.assertEqual(self.db.vincular_telegram_por_codigo(code, "901")["status"], "invalido")
        self.assertIsNone(self.db.buscar_operador_por_telegram("901"))

    def test_codigo_expirado_e_recusado(self):
        code = self._code(self.ana)
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE telegram_codigos_vinculo SET expira_em = LOCALTIMESTAMP - INTERVAL '1 second'"
            )
        self.assertEqual(self.db.vincular_telegram_por_codigo(code, "900")["status"], "invalido")
        self.assertIsNone(self.db.buscar_operador_por_telegram("900"))

    def test_cracha_puro_nao_vincula(self):
        self._code(self.ana)
        reply = self.service.handle_update(_update("/vincular 501", chat_id="900"))
        self.assertIn("inválido", reply.text)
        self.assertIsNone(self.db.buscar_operador_por_telegram("900"))

    def test_revincular_bloqueado_ate_a_gestao_desvincular(self):
        self.assertEqual(self.db.vincular_telegram_por_codigo(self._code(self.ana), "900")["status"], "ok")
        self.assertEqual(self.db.gerar_codigo_vinculo_telegram(self.ana)["status"], "ja_vinculado")
        # Chat já ligado à Ana não troca para o Bruno em silêncio.
        code_bruno = self._code(self.bruno)
        self.assertEqual(
            self.db.vincular_telegram_por_codigo(code_bruno, "900")["status"], "chat_ja_vinculado"
        )
        self.assertEqual(self.db.buscar_operador_por_telegram("900")["cracha"], "501")

        self.assertEqual(self.db.desvincular_telegram_operador(self.ana), {"chat_anterior": "900"})
        self.assertIsNone(self.db.buscar_operador_por_telegram("900"))
        self.assertEqual(self.db.vincular_telegram_por_codigo(self._code(self.ana), "901")["status"], "ok")

    def test_freio_persistido_vale_para_outro_processo_e_recusa_codigo_certo(self):
        for _ in range(5):
            self.assertEqual(self.db.vincular_telegram_por_codigo("ZZZZ9999", "900")["status"], "invalido")
        code = self._code(self.ana)
        other_process = Database(self.dsn)
        try:
            self.assertEqual(other_process.vincular_telegram_por_codigo(code, "900")["status"], "limite")
            self.assertEqual(other_process.vincular_telegram_por_codigo(code, "901")["status"], "ok")
        finally:
            other_process.close()
        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE telegram_vinculo_tentativas SET janela_inicio = LOCALTIMESTAMP - INTERVAL '11 minutes'"
            )
        self.assertEqual(self.db.vincular_telegram_por_codigo("ZZZZ9999", "900")["status"], "invalido")


class IntentParserTests(unittest.TestCase):
    def test_detecta_intencao_e_frente_sem_calcular_nada(self):
        intent = parse_telegram_intent("Tem alguma parada na usinagem?")
        self.assertEqual((intent.name, intent.front), ("stoppages", "caldeiraria"))
        self.assertEqual(parse_telegram_intent("xyz").name, "unknown")

        recursos = parse_telegram_intent("quais recursos tem na solda?")
        self.assertEqual((recursos.name, recursos.front), ("resources", "solda"))


class DigestPeriodTests(unittest.TestCase):
    def test_quinzenal_reaproveita_o_mesmo_calculo_do_relatorio_agendado(self):
        # O digest não reimplementa período fechado; usa a mesma função do
        # ReportScheduler. Este teste trava a dependência, não o cálculo em si
        # (já coberto em tests/test_report_automation_messaging.py).
        local = datetime(2026, 9, 16, 19, 0)
        start, end = closed_report_period("quinzenal", local)
        self.assertEqual((start, end), (datetime(2026, 9, 1), datetime(2026, 9, 16)))


class _FakeFacade:
    class _Management:
        @staticmethod
        def get_overview(_filters):
            return {
                "kpis": {
                    "oee": {"value": 42.0},
                    "availability": {"value": 90.0},
                    "performance": {"value": 47.0},
                    "ftt": {"value": 100.0},
                }
            }

    class _Analytics:
        @staticmethod
        def quality(_filters):
            return {"totals": {"boa": 10, "refugo": 1, "retrabalho": 0}}

        @staticmethod
        def downtimes(_filters):
            return {"by_reason": [{"motivo": "Manutenção", "segundos": 3600}]}

    management = _Management()
    analytics = _Analytics()


class DigestTextTests(unittest.TestCase):
    def test_build_digest_text_inclui_periodo_kpis_e_paradas(self):
        texto = build_digest_text(
            _FakeFacade(),
            frequency="diario",
            start=datetime(2026, 9, 15),
            end=datetime(2026, 9, 16),
        )
        self.assertIn("Resumo diário", texto)
        self.assertIn("Peças boas: <b>10</b>", texto)
        self.assertIn("OEE: <b>42%</b>", texto)
        self.assertIn("Manutenção · <b>1h</b>", texto)
        self.assertIn("Dia anterior: <b>15/09</b>", texto)
        self.assertNotIn("consolidados", texto)


class DigestDestinationTests(unittest.TestCase):
    def test_configuracao_le_mapa_setorial_do_ambiente(self):
        settings = WebSettings.from_env({
            "GESTOR_WEB_SESSION_SECRET": "segredo-de-teste-com-tamanho-suficiente-123456",
            "GESTOR_TELEGRAM_SECTOR_CHAT_IDS": (
                '{"corte":"-1001","solda":"-1002","pintura":"-1003",'
                '"caldeiraria":"-1004"}'
            ),
        })
        self.assertEqual(
            settings.telegram_sector_chat_ids,
            {
                "corte": "-1001",
                "solda": "-1002",
                "pintura": "-1003",
                "caldeiraria": "-1004",
            },
        )

    def test_destinos_derivam_os_paineis_canonicos_do_andon(self):
        destinations = build_digest_destinations(
            factory_chat_id="-1000",
            sector_chat_ids={
                "corte": "-1001",
                "solda": "-1002",
                "pintura": "-1003",
                "caldeiraria": "-1004",
            },
        )
        by_key = {item.key: item for item in destinations}
        self.assertEqual(by_key["global"].sectors, ())
        self.assertEqual(by_key["corte"].sectors, ("Corte",))
        self.assertEqual(by_key["pintura"].sectors, ("Pintura",))
        self.assertEqual(by_key["caldeiraria"].sectors, ("Dobra", "Usinagem", "Serra"))
        self.assertEqual(by_key["solda"].sectors, WELDING_SECTOR_NAMES)

    def test_recusa_escopo_desconhecido_e_chat_repetido(self):
        with self.assertRaisesRegex(ValueError, "desconhecidos"):
            build_digest_destinations(
                factory_chat_id="-1000", sector_chat_ids={"usinagem": "-1001"}
            )
        with self.assertRaisesRegex(ValueError, "dois escopos"):
            build_digest_destinations(
                factory_chat_id="-1000", sector_chat_ids={"corte": "-1000"}
            )


class _RoutingFacade:
    VALUES = {
        "Dobra": (3, 1, 0),
        "Usinagem": (5, 0, 1),
        "Serra": (2, 0, 0),
        "Pintura": (99, 99, 99),
    }

    def __init__(self):
        self.requested = []
        self.management = self._Management(self)
        self.analytics = self._Analytics(self)

    class _Management:
        def __init__(self, owner):
            self.owner = owner

        def get_overview(self, filters):
            self.owner.requested.append(("overview", filters.setor))
            return {
                "hours": {"productive_seconds": 3600, "downtime_seconds": 600},
                "kpis": {
                    "oee": {"value": 42.0},
                    "availability": {"value": 90.0},
                    "ftt": {"value": 100.0},
                },
            }

    class _Analytics:
        def __init__(self, owner):
            self.owner = owner

        def quality(self, filters):
            self.owner.requested.append(("quality", filters.setor))
            good, scrap, rework = self.owner.VALUES[filters.setor]
            return {"totals": {"boa": good, "refugo": scrap, "retrabalho": rework}}

        def downtimes(self, filters):
            self.owner.requested.append(("downtimes", filters.setor))
            return {"by_reason": [{"motivo": f"Parada {filters.setor}", "segundos": 600}]}


class SectorDigestTextTests(unittest.TestCase):
    def test_caldeiraria_consolida_so_seus_tres_setores_sem_inventar_oee(self):
        facade = _RoutingFacade()
        text = build_digest_text(
            facade,
            frequency="diario",
            start=datetime(2026, 9, 15),
            end=datetime(2026, 9, 16),
            destination=DigestDestination(
                "caldeiraria",
                "Caldeiraria",
                "-1004",
                ("Dobra", "Usinagem", "Serra"),
            ),
        )
        self.assertIn("Caldeiraria", text)
        self.assertIn("Peças boas: <b>10</b>", text)
        self.assertIn("Refugo: <b>1</b>", text)
        self.assertIn("Retrabalho: <b>1</b>", text)
        self.assertNotIn("OEE", text)
        requested_sectors = {sector for _kind, sector in facade.requested}
        self.assertEqual(requested_sectors, {"Dobra", "Usinagem", "Serra"})
        self.assertNotIn("Pintura", requested_sectors)


class _DigestDb:
    def __init__(self):
        self.sent_periods = {}

    def ultimo_envio_digest_telegram(self, key):
        return self.sent_periods.get(key)

    def registrar_envio_digest_telegram(self, key, period_end, _sent_at):
        self.sent_periods[key] = period_end


class DigestSchedulerTests(unittest.TestCase):
    def test_dedupe_e_independente_por_frequencia_e_destino(self):
        db = _DigestDb()
        sent = []
        scheduler = TelegramFactoryDigestScheduler(
            db,
            bot_token="token",
            destinations=(
                DigestDestination("global", "Fábrica", "-1000"),
                DigestDestination("corte", "Corte", "-1001", ("Corte",)),
            ),
            run_time=time(18, 0),
            timezone=ZoneInfo("America/Sao_Paulo"),
            now_func=lambda: datetime(2026, 9, 16, 19, 0),
            sender=lambda **message: sent.append(message) or True,
        )
        scheduler.facade = _FakeFacade()
        now = datetime(2026, 9, 16, 19, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))

        first = scheduler.run_due(local_now=now)
        second = scheduler.run_due(local_now=now)

        self.assertEqual(len(sent), 6)
        self.assertTrue(all(item.sent for item in first))
        self.assertTrue(all(item.reason == "periodo_ja_enviado" for item in second))
        self.assertEqual(
            set(db.sent_periods),
            {
                "diario", "quinzenal", "mensal",
                "diario:corte", "quinzenal:corte", "mensal:corte",
            },
        )

    def test_falha_em_um_destino_nao_bloqueia_os_demais(self):
        db = _DigestDb()
        sent = []

        def sender(**message):
            if message["chat_id"] == "-1000":
                raise RuntimeError("falha simulada")
            sent.append(message)
            return True

        scheduler = TelegramFactoryDigestScheduler(
            db,
            bot_token="token",
            destinations=(
                DigestDestination("global", "Fábrica", "-1000"),
                DigestDestination("corte", "Corte", "-1001", ("Corte",)),
            ),
            run_time=time(18, 0),
            timezone=ZoneInfo("America/Sao_Paulo"),
            now_func=lambda: datetime(2026, 9, 16, 19, 0),
            sender=sender,
        )
        scheduler.facade = _FakeFacade()
        now = datetime(2026, 9, 16, 19, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))

        with self.assertLogs("mes.services.telegram_digest", level="ERROR"):
            outcomes = scheduler.run_due(local_now=now)

        self.assertEqual(len(outcomes), 6)
        self.assertEqual(len(sent), 3)
        self.assertTrue(all(o.reason == "erro" for o in outcomes if o.destination == "global"))
        self.assertTrue(all(o.sent for o in outcomes if o.destination == "corte"))
        self.assertEqual(
            set(db.sent_periods), {"diario:corte", "quinzenal:corte", "mensal:corte"}
        )


if __name__ == "__main__":
    unittest.main()
