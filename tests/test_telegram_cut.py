from datetime import datetime
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mes.services.telegram_cut import (
    TelegramCutPlanNotifier,
    build_cut_plan_notifier,
    notify_cut_plan_in_background,
)
from mes.services.telegram_presenter import TelegramPresenter
from tests.fakes import FakeDatabase


def _cut_item(**overrides):
    item = {
        "codigo_tarefa": "T<3500>",
        "programa_atual": "P&9000",
        "maquina": "Laser <01>",
        "status": "Em processo",
        "operador_inicio": "Cortador & Cia",
        "data_inicio": datetime(2026, 9, 17, 9, 5),
        "nestings": [{
            "programa": "P&9000",
            "sequencia": 1,
            "repeticao": 7,
            "status": "Em processo",
            "data_inicio": datetime(2026, 9, 17, 9, 5),
        }],
    }
    item.update(overrides)
    return item


class TelegramCutPresenterTests(unittest.TestCase):
    def test_apontamento_simples_escapa_html_e_omite_nesting_sem_repeticao(self):
        text = TelegramPresenter().cut_plan_event(
            item=_cut_item(), event="corte_iniciado", now=datetime(2026, 9, 17, 9, 5)
        )

        self.assertIn("T&lt;3500&gt;", text)
        self.assertIn("P&amp;9000", text)
        self.assertIn("Laser &lt;01&gt;", text)
        self.assertNotIn("Nesting:", text)
        self.assertIn("Ocorrido às 09:05", text)

    def test_repeticao_do_mesmo_plano_exibe_nesting_ativo(self):
        item = _cut_item(nestings=[
            {"programa": "P&9000", "sequencia": 1, "repeticao": 7, "status": "Finalizado"},
            {
                "programa": "P&9000", "sequencia": 2, "repeticao": 8,
                "status": "Em processo", "data_inicio": datetime(2026, 9, 17, 9, 20),
            },
        ])
        text = TelegramPresenter().cut_plan_event(
            item=item, event="corte_nesting_concluido", now=datetime(2026, 9, 17, 9, 20)
        )

        self.assertIn("Nesting: <b>8</b>", text)
        self.assertIn("Próximo nesting iniciado", text)

    def test_setor_aparece_e_operador_some_quando_apontamento_nao_informa(self):
        text = TelegramPresenter().cut_plan_event(
            item=_cut_item(operador_inicio=None, operador_fim=None),
            event="corte_iniciado",
            now=datetime(2026, 9, 17, 9, 5),
        )

        self.assertIn("Setor: <b>Corte</b>", text)
        self.assertNotIn("Operador", text)

    def test_sem_tarefa_plano_ou_recurso_nao_inventa_mensagem(self):
        presenter = TelegramPresenter()
        self.assertIsNone(presenter.cut_plan_event(
            item=_cut_item(codigo_tarefa=""), event="corte_iniciado", now=datetime.now()
        ))
        self.assertIsNone(presenter.cut_plan_event(
            item=_cut_item(programa_atual=None), event="corte_iniciado", now=datetime.now()
        ))
        self.assertIsNone(presenter.cut_plan_event(
            item=_cut_item(maquina=None), event="corte_iniciado", now=datetime.now()
        ))


class TelegramCutNotifierTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeDatabase()
        self.sent = []
        self.edited = []

        def sender(**payload):
            self.sent.append(payload)
            return 100 + len(self.sent)

        def editor(**payload):
            self.edited.append(payload)
            return True

        self.notifier = TelegramCutPlanNotifier(
            self.db,
            bot_token="token",
            chat_id="-100-corte",
            sender=sender,
            editor=editor,
        )

    def test_primeiro_apontamento_envia_e_guarda_correlacao(self):
        self.assertTrue(self.notifier.notify(_cut_item(), event="corte_iniciado"))

        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.edited, [])
        saved = self.db.obter_mensagem_telegram_corte(
            "-100-corte", "T<3500>", "Laser <01>"
        )
        self.assertEqual(saved["message_id"], 101)
        self.assertEqual(saved["programa"], "P&9000")
        self.assertEqual(self.sent[0]["parse_mode"], "HTML")

    def test_novo_nesting_atualiza_a_mesma_mensagem(self):
        self.notifier.notify(_cut_item(), event="corte_iniciado")
        repeated = _cut_item(nestings=[
            {"programa": "P&9000", "sequencia": 1, "repeticao": 7, "status": "Finalizado"},
            {
                "programa": "P&9000", "sequencia": 2, "repeticao": 8,
                "status": "Em processo", "data_inicio": datetime(2026, 9, 17, 9, 20),
            },
        ])

        self.assertTrue(self.notifier.notify(
            repeated, event="corte_nesting_concluido"
        ))

        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(self.edited), 1)
        self.assertEqual(self.edited[0]["message_id"], 101)
        self.assertIn("Nesting: <b>8</b>", self.edited[0]["text"])

    def test_avisos_simultaneos_do_mesmo_plano_nao_duplicam_a_mensagem(self):
        # I2: ler message_id -> enviar -> gravar é uma sequência. Sem
        # serialização, o segundo aviso não vê a mensagem ainda não gravada e
        # envia outra.
        dentro_do_envio = threading.Event()
        liberar_envio = threading.Event()

        def sender_lento(**payload):
            self.sent.append(payload)
            dentro_do_envio.set()
            self.assertTrue(liberar_envio.wait(timeout=5))
            return 100 + len(self.sent)

        self.notifier.sender = sender_lento
        resultados = {}

        def chamar(nome, evento):
            resultados[nome] = self.notifier.notify(_cut_item(), event=evento)

        primeiro = threading.Thread(target=chamar, args=("inicio", "corte_iniciado"))
        segundo = threading.Thread(target=chamar, args=("fim", "corte_finalizado"))
        primeiro.start()
        self.assertTrue(dentro_do_envio.wait(timeout=5))
        segundo.start()
        segundo.join(timeout=0.3)
        self.assertTrue(segundo.is_alive(), "o segundo aviso deveria esperar o primeiro")
        liberar_envio.set()
        primeiro.join(timeout=5)
        segundo.join(timeout=5)

        self.assertEqual(resultados, {"inicio": True, "fim": True})
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(self.edited), 1)
        self.assertEqual(self.edited[0]["message_id"], 101)

    def test_avisos_de_planos_diferentes_nao_se_bloqueiam(self):
        bloqueado = threading.Event()
        liberar = threading.Event()

        def sender_lento(**payload):
            if payload["text"].find("T&lt;3500&gt;") == -1:
                return 2  # plano diferente: responde na hora
            bloqueado.set()
            self.assertTrue(liberar.wait(timeout=5))
            return 1

        self.notifier.sender = sender_lento
        primeiro = threading.Thread(
            target=lambda: self.notifier.notify(_cut_item(), event="corte_iniciado")
        )
        primeiro.start()
        self.assertTrue(bloqueado.wait(timeout=5))
        outro = {}
        segundo = threading.Thread(
            target=lambda: outro.setdefault(
                "ok", self.notifier.notify(_cut_item(codigo_tarefa="T9"), event="corte_iniciado")
            )
        )
        segundo.start()
        segundo.join(timeout=2)
        try:
            self.assertFalse(segundo.is_alive(), "chave diferente não deve esperar")
        finally:
            liberar.set()
            primeiro.join(timeout=5)
            segundo.join(timeout=5)

    def test_falha_na_edicao_envia_nova_e_substitui_correlacao(self):
        self.notifier.notify(_cut_item(), event="corte_iniciado")
        self.notifier.editor = lambda **_payload: False

        self.assertTrue(self.notifier.notify(
            _cut_item(programa_atual="P9001"), event="corte_nesting_concluido"
        ))

        saved = self.db.obter_mensagem_telegram_corte(
            "-100-corte", "T<3500>", "Laser <01>"
        )
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(saved["message_id"], 102)
        self.assertEqual(saved["programa"], "P9001")

    def test_dado_incompleto_nao_envia_nem_persiste(self):
        self.assertFalse(self.notifier.notify(
            _cut_item(programa_atual=None), event="corte_iniciado"
        ))
        self.assertEqual(self.sent, [])
        self.assertEqual(self.edited, [])
        self.assertEqual(self.db.telegram_cut_messages, [])

    def test_flag_desligada_nao_cria_notifier_com_token_e_chat(self):
        settings = SimpleNamespace(
            telegram_enabled=False,
            telegram_bot_token="token",
            telegram_sector_chat_ids={"corte": "-100-corte"},
        )

        self.assertIsNone(build_cut_plan_notifier(self.db, settings))

    def test_aviso_em_background_envia_e_nunca_propaga_falha(self):
        settings = SimpleNamespace(
            telegram_enabled=True,
            telegram_bot_token="token",
            telegram_sector_chat_ids={"corte": "-100-corte"},
        )
        item = {
            "codigo_tarefa": "T-1", "programa": "P-1", "maquina": "Laser 1",
            "status": "Em processo",
        }
        with patch(
            "mes.services.telegram_cut.send_telegram_message_with_id", return_value=None
        ):
            self.assertFalse(
                notify_cut_plan_in_background(self.db, settings, item, event="corte_iniciado")
            )

        with patch.object(
            TelegramCutPlanNotifier, "notify", side_effect=RuntimeError("telegram caiu")
        ):
            self.assertFalse(
                notify_cut_plan_in_background(self.db, settings, item, event="corte_iniciado")
            )

    def test_factory_usa_destino_canonico_de_corte(self):
        settings = SimpleNamespace(
            telegram_enabled=True,
            telegram_bot_token="token",
            telegram_sector_chat_ids={"Corte": "-100-dinamico", "solda": "-200"},
        )
        notifier = build_cut_plan_notifier(self.db, settings)

        self.assertIsNotNone(notifier)
        self.assertEqual(notifier.chat_id, "-100-dinamico")
        self.assertIsNone(build_cut_plan_notifier(
            self.db,
            SimpleNamespace(
                telegram_enabled=True,
                telegram_bot_token="token",
                telegram_sector_chat_ids={"solda": "-200"},
            ),
        ))


if __name__ == "__main__":
    unittest.main()
