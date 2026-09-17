from datetime import datetime
from types import SimpleNamespace
import unittest

from mes.services.telegram_cut import (
    TelegramCutPlanNotifier,
    build_cut_plan_notifier,
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
