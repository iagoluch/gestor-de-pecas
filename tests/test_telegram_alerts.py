"""Chat mestre de alerta: parada de recurso e contexto do posto."""

import asyncio
import httpx
from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import BackgroundTasks

from mes.integrations.notifications.telegram import (
    TelegramSendResult,
    send_telegram_message_checked,
    telegram_outbound_allowed,
)
from mes.services import telegram_alerts
from mes.services.telegram_alerts import (
    alert_resource_stop,
    deliver_chamada,
    schedule_resource_stop_alert,
    station_context,
)


def _settings(**overrides):
    base = {
        "telegram_enabled": True,
        "telegram_bot_token": "token-teste",
        "chamada_telegram_chat_id": "-100999",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeAppointments:
    """Só o que ``station_context`` consulta."""

    def __init__(self, rows=(), erro=None):
        self.rows = list(rows)
        self.erro = erro
        self.chamadas = []

    def listar_apontamentos_operacionais(self, tipo_setor, maquina=None, somente_ativos=True):
        self.chamadas.append((tipo_setor, maquina))
        if self.erro is not None:
            raise self.erro
        return list(self.rows)


class AlertResourceStopTests(unittest.TestCase):
    def test_parada_com_op_vai_em_html_para_o_chat_mestre(self):
        with patch.object(telegram_alerts, "send_telegram_message", return_value=True) as enviar:
            enviado = alert_resource_stop(
                _settings(),
                {
                    "maquina": "Serra <01>", "tipo_setor": "Serra", "op": "012345",
                    "produto_codigo": "ABC-123", "produto_descricao": "Suporte & base",
                    "motivo_parada": "0007 - Manutenção", "comentario": "Correia rompida",
                },
                ocorrido_em=datetime(2026, 9, 21, 14, 32),
            )

        self.assertTrue(enviado)
        kwargs = enviar.call_args.kwargs
        self.assertEqual(kwargs["chat_id"], "-100999")
        self.assertEqual(kwargs["parse_mode"], "HTML")
        texto = kwargs["text"]
        self.assertIn("🔴 <b>Parada registrada</b>", texto)
        self.assertIn("Máquina: <b>Serra &lt;01&gt;</b>", texto)
        self.assertIn("OP: <b>012345</b>", texto)
        self.assertIn("Peça: <b>ABC-123</b>", texto)
        self.assertIn("Descrição: <b>Suporte &amp; base</b>", texto)
        self.assertIn("🔧 Motivo: <b>0007 - Manutenção</b>", texto)
        self.assertIn("Comentário: Correia rompida", texto)
        self.assertIn("📅 Data: <b>21/09/2026</b>", texto)
        self.assertIn("🕐 Hora: <b>14:32</b>", texto)

    def test_estado_fisico_aninhado_do_corte_e_achatado(self):
        with patch.object(telegram_alerts, "send_telegram_message", return_value=True) as enviar:
            alert_resource_stop(
                _settings(),
                {
                    "maquina": "Laser Ensis 3015", "codigo_tarefa": "T-9981",
                    "estado_recurso": {
                        "recurso": "Laser Ensis 3015", "tipo_setor": "Corte",
                        "motivo": "0123 - Falta de material", "comentario": None,
                    },
                },
            )

        texto = enviar.call_args.kwargs["text"]
        self.assertIn("Máquina: <b>Laser Ensis 3015</b>", texto)
        self.assertIn("Tarefa: <b>T-9981</b>", texto)
        self.assertIn("Setor: <b>Corte</b>", texto)
        self.assertIn("🔧 Motivo: <b>0123 - Falta de material</b>", texto)
        self.assertNotIn("Comentário:", texto)

    def test_sem_chat_mestre_configurado_nao_envia_nada(self):
        with patch.object(telegram_alerts, "send_telegram_message") as enviar:
            enviado = alert_resource_stop(
                _settings(chamada_telegram_chat_id=""), {"maquina": "Serra 01"}
            )

        self.assertFalse(enviado)
        enviar.assert_not_called()

    def test_falha_do_canal_nunca_derruba_o_apontamento(self):
        with patch.object(
            telegram_alerts, "send_telegram_message", side_effect=RuntimeError("boom")
        ):
            self.assertFalse(alert_resource_stop(_settings(), {"maquina": "Serra 01"}))


class _FakeChamadaRow:
    def __init__(self, falha=None):
        self.falha = falha
        self.marcado = []

    def marcar_chamada_telegram(self, chamada_id, *, enviado, erro=None):
        if self.falha is not None:
            raise self.falha
        self.marcado.append((chamada_id, enviado, erro))
        return {"id": chamada_id}


class ScheduleStopAlertTests(unittest.TestCase):
    def test_agenda_em_vez_de_enviar_dentro_do_request(self):
        tarefas = BackgroundTasks()
        with patch.object(telegram_alerts, "send_telegram_message", return_value=True) as enviar:
            agendado = schedule_resource_stop_alert(
                tarefas, _settings(), {"maquina": "Serra 01", "motivo": "0007 - Manutenção"}
            )

            # Nada saiu ainda: a resposta ao posto não espera o Telegram.
            enviar.assert_not_called()
            self.assertTrue(agendado)
            self.assertEqual(len(tarefas.tasks), 1)

            asyncio.run(tarefas())
            enviar.assert_called_once()

        self.assertIn("Máquina: <b>Serra 01</b>", enviar.call_args.kwargs["text"])

    def test_sem_chat_mestre_nao_enfileira_tarefa(self):
        tarefas = BackgroundTasks()

        agendado = schedule_resource_stop_alert(
            tarefas, _settings(chamada_telegram_chat_id=""), {"maquina": "Serra 01"}
        )

        self.assertFalse(agendado)
        self.assertEqual(tarefas.tasks, [])

    def test_horario_e_congelado_no_agendamento(self):
        tarefas = BackgroundTasks()
        schedule_resource_stop_alert(
            tarefas, _settings(), {"maquina": "Serra 01"},
            ocorrido_em=datetime(2026, 9, 21, 14, 32),
        )
        with patch.object(telegram_alerts, "send_telegram_message", return_value=True) as enviar:
            asyncio.run(tarefas())

        self.assertIn("🕐 Hora: <b>14:32</b>", enviar.call_args.kwargs["text"])


class DeliverChamadaTests(unittest.TestCase):
    def test_envio_bem_sucedido_fica_gravado_na_chamada(self):
        db = _FakeChamadaRow()
        with patch.object(
            telegram_alerts, "send_telegram_message_checked", return_value=TelegramSendResult(ok=True)
        ):
            self.assertTrue(
                deliver_chamada(db, 7, bot_token="t", chat_id="-100999", texto="oi")
            )

        self.assertEqual(db.marcado, [(7, True, None)])

    def test_falha_de_envio_grava_o_motivo_real_e_nao_levanta(self):
        db = _FakeChamadaRow()
        with patch.object(
            telegram_alerts,
            "send_telegram_message_checked",
            return_value=TelegramSendResult(ok=False, error="HTTP 400: chat not found", attempts=1),
        ):
            self.assertFalse(
                deliver_chamada(db, 7, bot_token="t", chat_id="-100999", texto="oi")
            )

        self.assertEqual(
            db.marcado, [(7, False, "Falha ao enviar pelo Telegram: HTTP 400: chat not found")]
        )

    def test_excecao_inesperada_no_envio_vira_falha_registrada(self):
        db = _FakeChamadaRow()
        with patch.object(
            telegram_alerts, "send_telegram_message_checked", side_effect=RuntimeError("boom")
        ):
            self.assertFalse(
                deliver_chamada(db, 7, bot_token="t", chat_id="-100999", texto="oi")
            )

        self.assertFalse(db.marcado[0][1])
        self.assertIn("erro inesperado", db.marcado[0][2])

    def test_falha_ao_persistir_o_desfecho_tambem_e_silenciosa(self):
        db = _FakeChamadaRow(falha=RuntimeError("banco fora"))
        with patch.object(
            telegram_alerts, "send_telegram_message_checked", return_value=TelegramSendResult(ok=True)
        ):
            self.assertTrue(
                deliver_chamada(db, 7, bot_token="t", chat_id="-100999", texto="oi")
            )


class TelegramDesligadoTests(unittest.TestCase):
    """``TELEGRAM_ENABLED=false`` desliga a saída mesmo com token e chat."""

    def test_flag_desligada_nao_envia_parada_nem_agenda(self):
        settings = _settings(telegram_enabled=False)
        tarefas = BackgroundTasks()
        with patch.object(telegram_alerts, "send_telegram_message") as enviar:
            self.assertFalse(alert_resource_stop(settings, {"maquina": "Serra 01"}))
            self.assertFalse(schedule_resource_stop_alert(tarefas, settings, {"maquina": "Serra 01"}))

        enviar.assert_not_called()
        self.assertEqual(tarefas.tasks, [])

    def test_settings_sem_o_atributo_conta_como_desligado(self):
        self.assertFalse(telegram_outbound_allowed(SimpleNamespace(telegram_bot_token="t")))
        self.assertTrue(telegram_outbound_allowed(SimpleNamespace(telegram_enabled=True)))


def _resposta(status, corpo=None):
    return httpx.Response(status, json=corpo or {})


class SendTelegramMessageCheckedTests(unittest.TestCase):
    def _enviar(self, respostas):
        esperas = []
        with patch(
            "mes.integrations.notifications.telegram.httpx.post", side_effect=respostas
        ) as post:
            resultado = send_telegram_message_checked(
                bot_token="segredo", chat_id="-1", text="oi", sleep=esperas.append
            )
        return resultado, post, esperas

    def test_429_respeita_retry_after_e_depois_entrega(self):
        resultado, post, esperas = self._enviar([
            _resposta(429, {"ok": False, "parameters": {"retry_after": 3}}),
            _resposta(200, {"ok": True, "result": {"message_id": 1}}),
        ])

        self.assertTrue(resultado.ok)
        self.assertEqual(resultado.attempts, 2)
        self.assertEqual(esperas, [3.0])
        self.assertEqual(post.call_count, 2)

    def test_retry_after_acima_do_limite_falha_sem_dormir(self):
        resultado, post, esperas = self._enviar([
            _resposta(429, {"ok": False, "parameters": {"retry_after": 600}}),
        ])

        self.assertFalse(resultado.ok)
        self.assertIn("retry_after=600", resultado.error)
        self.assertEqual(esperas, [])
        self.assertEqual(post.call_count, 1)

    def test_5xx_repete_com_backoff_e_esgota_as_tentativas(self):
        resultado, post, esperas = self._enviar([_resposta(502)] * 3)

        self.assertFalse(resultado.ok)
        self.assertEqual(resultado.attempts, 3)
        self.assertEqual(post.call_count, 3)
        self.assertEqual(len(esperas), 2)
        self.assertIn("HTTP 502", resultado.error)

    def test_erro_permanente_nao_repete_e_informa_o_motivo(self):
        resultado, post, esperas = self._enviar([
            _resposta(400, {"ok": False, "description": "Bad Request: chat not found"}),
        ])

        self.assertFalse(resultado.ok)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(esperas, [])
        self.assertIn("chat not found", resultado.error)

    def test_falha_de_conexao_repete_mas_timeout_de_leitura_nao(self):
        resultado, post, _ = self._enviar([
            httpx.ConnectError("sem rede"),
            _resposta(200, {"ok": True, "result": {}}),
        ])
        self.assertTrue(resultado.ok)
        self.assertEqual(post.call_count, 2)

        resultado, post, _ = self._enviar([httpx.ReadTimeout("lento")])
        self.assertFalse(resultado.ok)
        self.assertEqual(post.call_count, 1)

    def test_motivo_da_falha_nunca_expoe_o_token(self):
        resultado, _, _ = self._enviar(
            [httpx.ConnectError("https://api.telegram.org/botsegredo/x")] * 3
        )

        self.assertFalse(resultado.ok)
        self.assertNotIn("segredo", resultado.error)


class StationContextTests(unittest.TestCase):
    def test_apontamento_ativo_do_posto_vira_contexto_do_aviso(self):
        db = _FakeAppointments([
            {
                "op": "012345", "numero_operacao": "0020", "peca": "ABC-123",
                "produto_codigo": "ABC-123", "produto_descricao": "Suporte lateral",
                "status": "Em processo",
            },
            {"op": "999999", "status": "Aguardando"},
        ])

        contexto = station_context(db, setor="Serra", recurso="Serra 01")

        self.assertEqual(db.chamadas, [("Serra", "Serra 01")])
        self.assertEqual(contexto["maquina"], "Serra 01")
        self.assertEqual(contexto["setor"], "Serra")
        self.assertEqual(contexto["op"], "012345")
        self.assertEqual(contexto["produto_descricao"], "Suporte lateral")

    def test_posto_sem_apontamento_ativo_devolve_apenas_maquina_e_setor(self):
        contexto = station_context(_FakeAppointments(), setor="Corte", recurso="Laser Ensis 3015")

        self.assertEqual(contexto, {"maquina": "Laser Ensis 3015", "setor": "Corte"})

    def test_falha_na_consulta_nao_impede_o_aviso(self):
        db = _FakeAppointments(erro=RuntimeError("banco fora"))

        contexto = station_context(db, setor="Corte", recurso="Laser Ensis 3015")

        self.assertEqual(contexto, {"maquina": "Laser Ensis 3015", "setor": "Corte"})


if __name__ == "__main__":
    unittest.main()
