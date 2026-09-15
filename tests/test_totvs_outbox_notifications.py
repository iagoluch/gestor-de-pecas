"""Aviso ao supervisor quando a outbox TOTVS para em ERROR (pendência 2 do piloto)."""

from __future__ import annotations

from datetime import datetime
import unittest
from unittest.mock import patch

from mes.integrations.notifications.telegram import (
    build_outbox_error_notifier,
    send_telegram_message,
)
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


class SendTelegramMessageTests(unittest.TestCase):
    def test_erro_http_e_logado_e_nunca_propaga(self):
        with patch("mes.integrations.notifications.telegram.httpx.post") as mocked_post:
            mocked_post.return_value.status_code = 400
            mocked_post.return_value.text = "chat not found"
            send_telegram_message(bot_token="abc", chat_id="-1", text="oi")
        mocked_post.assert_called_once()

    def test_falha_de_rede_e_logada_e_nunca_propaga(self):
        import httpx

        with patch(
            "mes.integrations.notifications.telegram.httpx.post",
            side_effect=httpx.ConnectError("sem rede"),
        ):
            send_telegram_message(bot_token="abc", chat_id="-1", text="oi")


if __name__ == "__main__":
    unittest.main()
