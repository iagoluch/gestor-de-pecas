"""Roteamento de comandos do bot de fábrica e formatação pura."""

from datetime import datetime
import unittest

from mes.services.telegram_bot import (
    TelegramBotReply,
    TelegramFactoryBotService,
    _formatar_duracao,
    _formatar_percentual,
)
from mes.services.telegram_digest import build_digest_text, closed_report_period


class FormattingTests(unittest.TestCase):
    def test_duracao_formata_horas_minutos_e_menos_de_um_minuto(self):
        self.assertEqual(_formatar_duracao(30), "menos de 1min")
        self.assertEqual(_formatar_duracao(90), "1min")
        self.assertEqual(_formatar_duracao(3661), "1h01min")

    def test_percentual_usa_o_valor_ja_em_escala_percentual(self):
        # MetricValue guarda 96.5 significando 96.5%, não 0.965.
        self.assertEqual(_formatar_percentual({"value": 96.5}), "96%")
        self.assertEqual(_formatar_percentual({"value": None}), "sem dado")
        self.assertEqual(_formatar_percentual(None), "sem dado")


class _FakeDb:
    """Só os métodos que os handlers testados aqui realmente chamam."""

    def __init__(self):
        self.operadores = {"1": {"id": 1, "cracha": "1", "nome": "Iago"}}
        self.vinculos = {}
        self.participacoes = {}

    def vincular_telegram_operador(self, cracha, chat_id):
        operador = self.operadores.get(str(cracha))
        if operador is None:
            return None
        self.vinculos[chat_id] = operador["cracha"]
        return operador

    def buscar_operador_por_telegram(self, chat_id):
        cracha = self.vinculos.get(chat_id)
        return self.operadores.get(cracha) if cracha else None

    def participacoes_ativas_por_cracha(self, cracha):
        return self.participacoes.get(cracha, [])


def _fake_service():
    service = TelegramFactoryBotService.__new__(TelegramFactoryBotService)
    service.db = _FakeDb()
    service._now = lambda: datetime(2026, 9, 16, 15, 0, 0)
    service.facade = None  # comandos testados aqui não tocam o facade
    service._commands = {
        "/ajuda": service._cmd_ajuda,
        "/vincular": service._cmd_vincular,
        "/meustatus": service._cmd_meustatus,
    }
    return service


def _update(text, *, chat_type="private", chat_id="42"):
    return {"message": {"chat": {"id": chat_id, "type": chat_type}, "text": text}}


class CommandRoutingTests(unittest.TestCase):
    def test_ignora_mensagem_de_grupo(self):
        service = _fake_service()
        self.assertIsNone(service.handle_update(_update("/ajuda", chat_type="group")))

    def test_ignora_update_sem_texto(self):
        service = _fake_service()
        self.assertIsNone(service.handle_update({"message": {"chat": {"id": "42", "type": "private"}}}))

    def test_comando_desconhecido_devolve_ajuda(self):
        service = _fake_service()
        reply = service.handle_update(_update("/isso_nao_existe"))
        self.assertIsInstance(reply, TelegramBotReply)
        self.assertIn("/vincular", reply.text)

    def test_vincular_sem_cracha_pede_uso_correto(self):
        service = _fake_service()
        reply = service.handle_update(_update("/vincular"))
        self.assertIn("Uso:", reply.text)

    def test_vincular_cracha_inexistente_avisa_sem_vincular(self):
        service = _fake_service()
        reply = service.handle_update(_update("/vincular 999"))
        self.assertIn("não encontrado", reply.text)
        self.assertIsNone(service.db.buscar_operador_por_telegram("42"))

    def test_vincular_e_meustatus_sem_operacao_aberta(self):
        service = _fake_service()
        vinculo = service.handle_update(_update("/vincular 1"))
        self.assertIn("Iago", vinculo.text)
        status = service.handle_update(_update("/meustatus"))
        self.assertIn("não tem nenhuma operação em aberto", status.text)

    def test_meustatus_lista_participacao_ativa(self):
        service = _fake_service()
        service.handle_update(_update("/vincular 1"))
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


class DigestPeriodTests(unittest.TestCase):
    def test_quinzenal_reaproveita_o_mesmo_calculo_do_relatorio_agendado(self):
        # O digest não reimplementa período fechado; usa a mesma função do
        # ReportScheduler. Este teste trava a dependência, não o cálculo em si
        # (já coberto em tests/test_report_automation_messaging.py).
        local = datetime(2026, 9, 16, 19, 0)
        start, end = closed_report_period("quinzenal", local)
        self.assertEqual((end - start).days, 14)


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
        self.assertIn("Peças boas: 10", texto)
        self.assertIn("OEE: 42%", texto)
        self.assertIn("Manutenção — 1h00min", texto)


if __name__ == "__main__":
    unittest.main()
