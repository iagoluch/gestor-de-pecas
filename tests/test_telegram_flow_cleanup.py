"""Fluxo do Telegram limpo: rótulos humanos, limites, digest, prefixo [TESTE] e polling.

Cobre M3 (sem dado bruto), M4 (rótulo do período), M7 (config do digest) e a
parte segura de A2 (prefixo de ambiente e recuo em 401/409). Nenhum teste fala
com a API real do Telegram.
"""

from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, time as day_time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.api import main as api_main
from mes.integrations.notifications import telegram as tg
from mes.services.display_labels import (
    CLASSIFICATION_CONFLICT_REASON,
    role_label,
    strip_status_code_prefix,
)
from mes.services.telegram_digest import build_digest_text
from mes.services.telegram_presenter import (
    TELEGRAM_MAX_CHARS,
    TelegramPresenter,
    fit_telegram_text,
    more_line,
    truncate,
)

NOW = datetime(2026, 10, 1, 9, 30)


class DisplayLabelTests(unittest.TestCase):
    def test_papel_vira_texto_humano_e_desconhecido_vira_none(self):
        self.assertEqual(role_label("operador_corte"), "Operador de Corte")
        self.assertEqual(role_label("supervisor"), "Supervisor")
        self.assertEqual(role_label("operador_solda_estacao_3"), "Operador Solda — Estação 3")
        self.assertIsNone(role_label("papel_que_nao_existe"))
        self.assertIsNone(role_label(None))

    def test_prefixo_de_codigo_do_motivo_e_removido(self):
        self.assertEqual(strip_status_code_prefix("12 - Falta de material"), "Falta de material")
        self.assertEqual(strip_status_code_prefix("0029 - Falta", "0029"), "Falta")
        self.assertEqual(strip_status_code_prefix("Manutenção"), "Manutenção")
        self.assertEqual(strip_status_code_prefix("Troca 2 - lado"), "Troca 2 - lado")


class PresenterCleanTextTests(unittest.TestCase):
    presenter = TelegramPresenter()

    def test_chamada_sem_cracha_email_nem_role_cru(self):
        texto = self.presenter.chamada({
            "solicitante_nome": "Maria", "solicitante_nivel": "operador_solda_estacao_3",
            "solicitante_cracha": "0042", "solicitante_email": "m@x.com", "motivo": "Qualidade",
        }, now=NOW)
        self.assertIn("Solicitado por: Maria (Operador Solda — Estação 3)", texto)
        for bruto in ("0042", "m@x.com", "operador_solda_estacao_3", "crachá"):
            self.assertNotIn(bruto, texto)

    def test_papel_sem_traducao_e_omitido(self):
        texto = self.presenter.chamada(
            {"solicitante_nome": "Maria", "solicitante_nivel": "xyz_interno", "motivo": "x"}, now=NOW
        )
        self.assertIn("Solicitado por: Maria\n", texto)
        self.assertNotIn("xyz_interno", texto)

    def test_erro_totvs_tem_frase_curta_e_detalhe_truncado(self):
        longo = "ERRO " + "x" * 2000
        texto = self.presenter.totvs_outbox_error({
            "production_order": "A1", "delivery_class": "functional", "error_message": longo,
        })
        self.assertIn("não o aceitou", texto)
        self.assertIn("Detalhe técnico", texto)
        self.assertLess(len(texto), 700)
        self.assertIn("…", texto)

    def test_listas_cortadas_mostram_mais_n(self):
        stopped = [{"name": f"R{i}", "reason": "m", "duration_seconds": 60} for i in range(15)]
        view = self.presenter.factory(summary={"downtime": 15}, stopped=stopped, now=NOW)
        self.assertIn("e mais <b>3</b>", view.text)
        items = [{"name": f"R{i}", "state": {}} for i in range(25)]
        view = self.presenter.resources(front="corte", items=items, now=NOW)
        self.assertIn("e mais <b>5</b>", view.text)
        self.assertIsNone(more_line(0))

    def test_fit_respeita_4096_e_nao_deixa_tag_aberta(self):
        texto = "\n".join(f"<b>linha {i}</b> " + "y" * 50 for i in range(200))
        cortado = fit_telegram_text(texto)
        self.assertLessEqual(len(cortado), TELEGRAM_MAX_CHARS)
        self.assertTrue(cortado.endswith("…"))
        self.assertEqual(cortado.count("<b>"), cortado.count("</b>"))
        sem_quebra = fit_telegram_text("<b>" + "z" * 5000)
        self.assertLessEqual(len(sem_quebra), TELEGRAM_MAX_CHARS)
        self.assertEqual(sem_quebra.count("<b>"), sem_quebra.count("</b>"))
        self.assertEqual(truncate("abcdef", 4), "abc…")


class _Facade:
    def __init__(self, reasons):
        self._reasons = reasons
        reasons_ = reasons

        class _Mgmt:
            @staticmethod
            def get_overview(_f):
                return {"kpis": {}, "hours": {"productive_seconds": 3600, "downtime_seconds": 600}}

        class _An:
            @staticmethod
            def quality(_f):
                return {"totals": {"boa": 1, "refugo": 0, "retrabalho": 0}}

            @staticmethod
            def downtimes(_f):
                return {"by_reason": reasons_}

        self.management, self.analytics = _Mgmt(), _An()


class DigestLabelTests(unittest.TestCase):
    def _texto(self, frequency, start, end, reasons=()):
        return build_digest_text(_Facade(list(reasons)), frequency=frequency, start=start, end=end)

    def test_diario_mostra_o_dia_anterior_e_nao_consolidado_ate(self):
        texto = self._texto("diario", datetime(2026, 9, 29), datetime(2026, 9, 30))
        self.assertIn("Dia anterior: <b>29/09</b>", texto)
        self.assertNotIn("29/09 a 30/09", texto)
        self.assertNotIn("consolidados", texto)

    def test_intervalo_usa_ultimo_dia_inclusivo(self):
        texto = self._texto("quinzenal", datetime(2026, 9, 16), datetime(2026, 10, 1))
        self.assertIn("Período: <b>16/09 a 30/09</b>", texto)

    def test_principal_parada_sem_codigo_e_sem_conflito(self):
        texto = self._texto("diario", datetime(2026, 9, 29), datetime(2026, 9, 30), [
            {"motivo": CLASSIFICATION_CONFLICT_REASON, "segundos": 99999},
            {"motivo": "12 - Falta de material", "segundos": 1800},
            {"motivo": "Falta de material", "segundos": 1800},
        ])
        self.assertIn("Principal parada: Falta de material · <b>1h</b>", texto)
        self.assertNotIn("12 -", texto)
        self.assertNotIn("Conflito", texto)


class DigestConfigTests(unittest.TestCase):
    def _settings(self, **over):
        base = dict(
            telegram_digest_timezone="America/Sao_Paulo", telegram_digest_daily_time="18:00",
            telegram_factory_chat_id="-100", telegram_sector_chat_ids={},
        )
        return SimpleNamespace(**{**base, **over})

    def test_config_valida_devolve_fuso_horario_e_destinos(self):
        fuso, horario, destinos = api_main.prepare_telegram_digest_config(self._settings())
        self.assertEqual(horario, day_time(18, 0))
        self.assertEqual(destinos[0].chat_id, "-100")

    def test_config_invalida_loga_error_e_desabilita(self):
        casos = {
            "fuso": self._settings(telegram_digest_timezone="Marte/Olimpo"),
            "horário": self._settings(telegram_digest_daily_time="18h"),
            "destinos": self._settings(telegram_sector_chat_ids={"inexistente": "-5"}),
            "sem chat": self._settings(telegram_factory_chat_id=""),
        }
        for nome, settings in casos.items():
            with self.subTest(nome), self.assertLogs(level="ERROR") as logs:
                self.assertIsNone(api_main.prepare_telegram_digest_config(settings))
            self.assertIn("DESABILITADO", logs.output[0])


class TestPrefixTests(unittest.TestCase):
    def tearDown(self):
        tg.configure_message_prefix(None)

    def _enviar(self, texto="Olá"):
        resposta = MagicMock(status_code=200)
        resposta.json.return_value = {"ok": True, "result": {"message_id": 1}}
        with patch.object(tg.httpx, "post", return_value=resposta) as post:
            tg.send_telegram_message(bot_token="t", chat_id="1", text=texto, parse_mode="HTML")
        return post.call_args.kwargs["json"]["text"]

    def test_fora_de_producao_prefixa_teste_uma_vez(self):
        tg.configure_message_prefix("development")
        self.assertEqual(self._enviar(), "[TESTE] Olá")
        self.assertEqual(self._enviar("[TESTE] Olá"), "[TESTE] Olá")

    def test_producao_nao_prefixa(self):
        tg.configure_message_prefix("production")
        self.assertEqual(self._enviar(), "Olá")

    def test_envio_central_corta_texto_acima_do_limite(self):
        tg.configure_message_prefix("development")
        self.assertLessEqual(len(self._enviar("a" * 9000)), TELEGRAM_MAX_CHARS)


class PollingRejectionTests(unittest.TestCase):
    def test_409_e_401_viram_excecao_dedicada(self):
        for status in (401, 409):
            with self.subTest(status), patch.object(
                tg.httpx, "get", return_value=MagicMock(status_code=status, text="x")
            ):
                with self.assertRaises(tg.TelegramPollingRejected) as ctx:
                    tg.fetch_telegram_updates(bot_token="t")
                self.assertEqual(ctx.exception.status_code, status)

    def test_laco_recua_de_60s_ate_5min_com_error(self):
        pausas = []

        async def sleep(seconds):
            pausas.append(seconds)
            if len(pausas) >= 5:
                raise asyncio.CancelledError

        async def lider(*_a):
            return True

        app = SimpleNamespace(state=SimpleNamespace(
            settings=SimpleNamespace(telegram_bot_poll_interval_seconds=3, telegram_bot_token="t"),
            database_manager=SimpleNamespace(get=lambda: SimpleNamespace()),
        ))
        with patch.object(api_main, "_leader_cycle", lider), \
                patch.object(api_main, "TelegramFactoryBotService", lambda db: None), \
                patch.object(api_main, "fetch_telegram_updates", side_effect=tg.TelegramPollingRejected(409)), \
                patch.object(api_main.asyncio, "sleep", sleep), \
                self.assertLogs(level="ERROR") as logs:
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(api_main._telegram_bot_loop(app))
        self.assertEqual(pausas, [60, 120, 240, 300, 300])
        self.assertEqual(len(logs.output), 5)
        self.assertIn("409", logs.output[0])


if __name__ == "__main__":
    unittest.main()
