"""Aviso ao supervisor quando a outbox TOTVS para em ERROR (pendência 2 do piloto)."""

from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch

from mes.integrations.notifications.telegram import (
    answer_telegram_callback_query,
    build_outbox_error_notifier,
    deliver_telegram_message,
    edit_telegram_message,
    send_telegram_message,
)
from mes.services.telegram_presenter import TelegramPresenter
from mes.integrations.totvs.outbox import OutboxStatus
from mes.services.totvs_outbox_worker import TotvsOutboxWorker


class _FailingGateway:
    def send_result(self, message):
        raise RuntimeError("gateway não deveria ser chamado nestes testes")


class _FakeDatabaseFixedOutcome:
    """Devolve sempre o mesmo desfecho de ``concluir_item_outbound_totvs``.

    Suficiente para testar a fiação worker -> notifier sem depender de
    Postgres real nem da classificação de retry, já cobertas em
    ``test_totvs_outbox.py``.
    """

    def __init__(self, reserved_items, *, final: dict):
        self._reserved_items = list(reserved_items)
        self._final = final

    def _now(self):
        return datetime(2026, 9, 15, 8, 0, 0)

    def recuperar_envios_abandonados_totvs(self, now):
        return []

    def reservar_lote_outbound_totvs(self, *, worker, batch_size, lease_seconds, now):
        items, self._reserved_items = self._reserved_items, []
        return items

    def concluir_item_outbound_totvs(self, item_id, **kwargs):
        return {"id": item_id, **self._final}


def _reserved_item(item_id: int = 1) -> dict:
    return {
        "id": item_id,
        "attempts": 1,
        "last_attempt_at": datetime(2026, 9, 15, 7, 59, 0),
        "transaction": "productionappointment",
        "idempotency_key": "chave-1",
        "payload_xml": "<TOTVSMessage/>",
        "max_attempts": 12,
    }


class OutboxTelegramNotifierWiringTests(unittest.TestCase):
    def test_item_em_error_aciona_o_notifier_com_os_dados_do_item(self):
        final = {
            "status": OutboxStatus.ERROR.value,
            "production_order": "A9716901001",
            "operation_code": "10",
            "error_code": "ack_funcional_error",
            "error_message": "A680OPTOT Operacao ja totalizada",
        }
        database = _FakeDatabaseFixedOutcome([_reserved_item()], final=final)
        recebidos: list[dict] = []
        worker = TotvsOutboxWorker(
            database,
            gateway=_FailingGateway(),
            error_notifier=recebidos.append,
        )
        cycle = worker.run_once()
        self.assertEqual(cycle.failed, 1)
        self.assertEqual(len(recebidos), 1)
        self.assertEqual(recebidos[0]["production_order"], "A9716901001")
        self.assertEqual(recebidos[0]["error_code"], "ack_funcional_error")

    def test_item_enviado_com_sucesso_nao_aciona_o_notifier(self):
        final = {"status": OutboxStatus.SENT.value, "production_order": "A9716901001"}
        database = _FakeDatabaseFixedOutcome([_reserved_item()], final=final)
        recebidos: list[dict] = []
        worker = TotvsOutboxWorker(
            database,
            gateway=_FailingGateway(),
            error_notifier=recebidos.append,
        )
        cycle = worker.run_once()
        self.assertEqual(cycle.sent, 1)
        self.assertEqual(recebidos, [])

    def test_sem_notifier_configurado_nada_muda_no_ciclo(self):
        final = {"status": OutboxStatus.ERROR.value, "production_order": "A9716901001"}
        database = _FakeDatabaseFixedOutcome([_reserved_item()], final=final)
        worker = TotvsOutboxWorker(database, gateway=_FailingGateway())
        cycle = worker.run_once()
        self.assertEqual(cycle.failed, 1)

    def test_falha_ao_notificar_nao_derruba_o_ciclo(self):
        final = {"status": OutboxStatus.ERROR.value, "production_order": "A9716901001"}
        database = _FakeDatabaseFixedOutcome([_reserved_item()], final=final)

        def _quebra(item):
            raise RuntimeError("Telegram fora do ar")

        worker = TotvsOutboxWorker(database, gateway=_FailingGateway(), error_notifier=_quebra)
        cycle = worker.run_once()
        self.assertEqual(cycle.failed, 1)


class TelegramTokenLogRedactionTests(unittest.TestCase):
    def test_log_do_httpx_nao_expoe_token_do_bot(self):
        import httpx
        import logging

        # Mesmo formato que o httpx usa em INFO para cada requisição.
        url = httpx.URL("https://api.telegram.org/bot123456:SEGREDO-do-bot/sendMessage")
        with self.assertLogs("httpx", level="INFO") as captured:
            logging.getLogger("httpx").info(
                'HTTP Request: %s %s "%s %d %s"', "POST", url, "HTTP/1.1", 200, "OK"
            )
        output = "\n".join(captured.output)
        self.assertNotIn("SEGREDO-do-bot", output)
        self.assertNotIn("123456:", output)
        self.assertIn("api.telegram.org/bot***/sendMessage", output)


class BuildOutboxErrorNotifierTests(unittest.TestCase):
    def test_sem_token_ou_chat_id_devolve_none(self):
        self.assertIsNone(build_outbox_error_notifier(bot_token="", chat_id="-100"))
        self.assertIsNone(build_outbox_error_notifier(bot_token="abc", chat_id=""))
        self.assertIsNone(build_outbox_error_notifier(bot_token=None, chat_id=None))

    def test_configurado_envia_mensagem_formatada_ao_chat_certo(self):
        notify = build_outbox_error_notifier(bot_token="abc123", chat_id="-1009999")
        self.assertIsNotNone(notify)
        with patch(
            "mes.integrations.notifications.telegram.httpx.post"
        ) as mocked_post:
            mocked_post.return_value.status_code = 200
            mocked_post.return_value.json.return_value = {"ok": True}
            notify(
                {
                    "production_order": "A9716901001",
                    "operation_code": "10",
                    "error_code": "ack_funcional_error",
                    "error_message": "A680OPTOT Operacao ja totalizada",
                }
            )
        mocked_post.assert_called_once()
        args, kwargs = mocked_post.call_args
        self.assertIn("abc123", args[0])
        self.assertEqual(kwargs["json"]["chat_id"], "-1009999")
        self.assertIn("A9716901001", kwargs["json"]["text"])
        self.assertIn("A680OPTOT", kwargs["json"]["text"])
        self.assertEqual(kwargs["json"]["parse_mode"], "HTML")
        self.assertIn("Rejeição funcional", kwargs["json"]["text"])

    def test_falha_tecnica_tem_apresentacao_distinta_e_escapada(self):
        text = TelegramPresenter().totvs_outbox_error({
            "production_order": "OP<01>",
            "payload_context": {"resource_code": "LASER & 1"},
            "last_delivery_class": "transient",
            "last_error_message": "timeout <externo>",
            "last_attempt_at": datetime(2026, 9, 17, 8, 30),
        })
        self.assertIn("TOTVS indisponível", text)
        self.assertIn("OP&lt;01&gt;", text)
        self.assertIn("LASER &amp; 1", text)
        self.assertIn("Última tentativa às 08:30", text)


class SendTelegramMessageTests(unittest.TestCase):
    def test_send_edit_answer_e_markup_usam_metodos_e_ack_da_bot_api(self):
        markup = {"inline_keyboard": [[{"text": "Menu", "callback_data": "gp:home"}]]}
        with patch("mes.integrations.notifications.telegram.httpx.post") as mocked_post:
            mocked_post.return_value.status_code = 200
            mocked_post.return_value.json.return_value = {"ok": True}
            self.assertTrue(send_telegram_message(
                bot_token="abc", chat_id="1", text="<b>oi</b>",
                parse_mode="HTML", reply_markup=markup,
            ))
            self.assertTrue(edit_telegram_message(
                bot_token="abc", chat_id="1", message_id=9, text="<b>nova</b>",
                parse_mode="HTML", reply_markup=markup,
            ))
            self.assertTrue(answer_telegram_callback_query(
                bot_token="abc", callback_query_id="cb-1"
            ))
        methods = [call.args[0].rsplit("/", 1)[-1] for call in mocked_post.call_args_list]
        self.assertEqual(methods, ["sendMessage", "editMessageText", "answerCallbackQuery"])
        self.assertEqual(mocked_post.call_args_list[0].kwargs["json"]["reply_markup"], markup)

    def test_falha_na_edicao_faz_fallback_para_envio(self):
        with patch("mes.integrations.notifications.telegram.edit_telegram_message", return_value=False) as edit, patch(
            "mes.integrations.notifications.telegram.send_telegram_message", return_value=True
        ) as send:
            self.assertTrue(deliver_telegram_message(
                bot_token="abc", chat_id="1", message_id=9, text="oi",
                parse_mode="HTML", reply_markup={"inline_keyboard": []},
            ))
        edit.assert_called_once()
        send.assert_called_once()

    def test_edicao_sem_mudanca_nao_gera_nova_mensagem(self):
        with patch("mes.integrations.notifications.telegram.httpx.post") as post, patch(
            "mes.integrations.notifications.telegram.send_telegram_message"
        ) as send:
            post.return_value.status_code = 400
            post.return_value.text = "Bad Request: message is not modified"
            self.assertTrue(deliver_telegram_message(
                bot_token="abc", chat_id="1", message_id=9, text="igual"
            ))
        send.assert_not_called()

    def test_http_200_sem_ack_da_bot_api_retorna_false(self):
        with patch("mes.integrations.notifications.telegram.httpx.post") as mocked_post:
            mocked_post.return_value.status_code = 200
            mocked_post.return_value.json.return_value = {
                "ok": False,
                "description": "chat not found",
            }
            sent = send_telegram_message(bot_token="abc", chat_id="-1", text="oi")
        self.assertFalse(sent)

    def test_erro_http_e_logado_e_nunca_propaga(self):
        with patch("mes.integrations.notifications.telegram.httpx.post") as mocked_post:
            mocked_post.return_value.status_code = 400
            mocked_post.return_value.text = "chat not found"
            self.assertFalse(
                send_telegram_message(bot_token="abc", chat_id="-1", text="oi")
            )
        mocked_post.assert_called_once()

    def test_falha_de_rede_e_logada_e_nunca_propaga(self):
        import httpx

        with patch(
            "mes.integrations.notifications.telegram.httpx.post",
            side_effect=httpx.ConnectError("sem rede"),
        ):
            self.assertFalse(
                send_telegram_message(bot_token="abc", chat_id="-1", text="oi")
            )


if __name__ == "__main__":
    unittest.main()
