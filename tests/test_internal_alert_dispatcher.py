"""Despachante dos alertas internos: chat certo, PENDENTE preservado, descarte só se obsoleto."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from app.database.first_piece_repository import _mesclar_entrega_telegram
from mes.integrations.notifications.telegram import TelegramSendResult
from mes.services.internal_alert_dispatcher import InternalAlertTelegramDispatcher

NOW = datetime(2026, 10, 1, 10, 0, 0)


class _Db:
    def __init__(self, alerts):
        self.alerts = {a["id"]: a for a in alerts}

    def listar_alertas_pendentes_telegram(self, *, limite=20):
        pend = [a for a in self.alerts.values() if a["status_notificacao"] == "PENDENTE"]
        return sorted(pend, key=lambda a: a["id"])[:limite]

    def marcar_alerta_enviado(self, alerta_id, *, agora):
        a = self.alerts[alerta_id]
        a.update(status_notificacao="ENVIADA", notificado_em=agora)

    def descartar_alerta_interno(self, alerta_id, *, agora, motivo):
        self.alerts[alerta_id].update(status_notificacao="DESCARTADA", resolvido_em=agora, motivo=motivo)

    def registrar_tentativa_alerta_interno(self, alerta_id, *, agora, erro):
        a = self.alerts[alerta_id]
        a["detalhes"] = _mesclar_entrega_telegram(a.get("detalhes"), agora=agora, erro=erro, contar=True)


def _alert(id=1, setor="Corte", **over):
    return {
        "id": id, "tipo": "REFUGO", "severidade": "ATENCAO", "destinatario": "PCP",
        "status_notificacao": "PENDENTE", "canal_previsto": "telegram", "tipo_setor": setor,
        "codigo_recurso": "LASER1", "titulo": "Refugo registrado — OP A1",
        "mensagem": "A OP A1 registrou 2 refugo(s).", "criado_em": NOW - timedelta(minutes=5),
        "detalhes": None, "resolvido_em": None, **over,
    }


class _Sender:
    def __init__(self, ok=True):
        self.ok, self.calls = ok, []

    def __call__(self, **kw):
        self.calls.append(kw)
        return TelegramSendResult(ok=self.ok, error=None if self.ok else "HTTP 500")


def _dispatcher(db, sender, **over):
    kw = dict(
        bot_token="t", factory_chat_id="-1", sector_chat_ids={"corte": "-2"},
        outbound_allowed=True, sender=sender, now_func=lambda: NOW,
    )
    return InternalAlertTelegramDispatcher(db, **{**kw, **over})


class DispatcherTests(unittest.TestCase):
    def test_envia_ao_chat_do_setor_e_marca_enviada(self):
        db, sender = _Db([_alert()]), _Sender()
        cycle = _dispatcher(db, sender).run_once()
        self.assertEqual(cycle.sent, 1)
        self.assertEqual(sender.calls[0]["chat_id"], "-2")
        self.assertEqual(db.alerts[1]["status_notificacao"], "ENVIADA")
        self.assertEqual(db.alerts[1]["notificado_em"], NOW)
        texto = sender.calls[0]["text"]
        self.assertIn("Refugo registrado", texto)
        self.assertNotIn("REFUGO", texto)

    def test_setor_sem_chat_proprio_cai_no_chat_da_fabrica(self):
        db, sender = _Db([_alert(setor="Pintura")]), _Sender()
        _dispatcher(db, sender).run_once()
        self.assertEqual(sender.calls[0]["chat_id"], "-1")

    def test_sem_chat_ou_com_telegram_desligado_nao_envia_nem_descarta(self):
        velho = _alert(criado_em=NOW - timedelta(days=9))
        for nome, over in {
            "sem chat": dict(factory_chat_id="", sector_chat_ids={}),
            "desligado": dict(outbound_allowed=False),
        }.items():
            with self.subTest(nome):
                db, sender = _Db([dict(velho)]), _Sender()
                _dispatcher(db, sender, **over).run_once()
                self.assertEqual(sender.calls, [])
                self.assertEqual(db.alerts[1]["status_notificacao"], "PENDENTE")

    def test_setor_sem_destino_fica_pendente_mas_expira_pela_idade(self):
        so_solda = dict(factory_chat_id="", sector_chat_ids={"pintura": "-3"})
        db, sender = _Db([_alert(1), _alert(2, criado_em=NOW - timedelta(days=2))]), _Sender()
        cycle = _dispatcher(db, sender, **so_solda).run_once()
        self.assertEqual((cycle.sent, cycle.deferred, cycle.discarded), (0, 1, 1))
        self.assertEqual(db.alerts[1]["status_notificacao"], "PENDENTE")
        self.assertEqual(db.alerts[2]["status_notificacao"], "DESCARTADA")

    def test_alertas_adiados_nao_escondem_os_novos_atras_deles(self):
        # 25 alertas do Corte sem chat do Corte; o da Pintura (id 100) vem depois.
        db = _Db([_alert(i) for i in range(1, 26)] + [_alert(100, setor="Pintura")])
        sender = _Sender()
        d = _dispatcher(db, sender, factory_chat_id="", sector_chat_ids={"pintura": "-3"}, batch_size=5)
        cycle = d.run_once()
        self.assertEqual(cycle.sent, 1)
        self.assertEqual(sender.calls[0]["chat_id"], "-3")
        self.assertEqual(db.alerts[100]["status_notificacao"], "ENVIADA")

    def test_lote_limita_so_as_tentativas_de_envio(self):
        db, sender = _Db([_alert(i) for i in range(1, 8)]), _Sender()
        cycle = _dispatcher(db, sender, batch_size=3).run_once()
        self.assertEqual(cycle.sent, 3)

    def test_falha_mantem_pendente_registra_tentativa_e_espera_para_repetir(self):
        db, sender = _Db([_alert()]), _Sender(ok=False)
        d = _dispatcher(db, sender)
        self.assertEqual(d.run_once().failed, 1)
        self.assertEqual(db.alerts[1]["status_notificacao"], "PENDENTE")
        self.assertIn('"tentativas": 1', db.alerts[1]["detalhes"])
        self.assertIn("HTTP 500", db.alerts[1]["detalhes"])
        cycle = d.run_once()  # mesmo instante: ainda em espera
        self.assertEqual((cycle.failed, cycle.deferred), (0, 1))
        self.assertEqual(len(sender.calls), 1)
        later = _dispatcher(db, _Sender(), now_func=lambda: NOW + timedelta(minutes=2))
        self.assertEqual(later.run_once().sent, 1)

    def test_descarta_so_o_que_deixou_de_valer(self):
        db = _Db([
            _alert(1, criado_em=NOW - timedelta(days=2)),
            _alert(2, resolvido_em=NOW - timedelta(minutes=1)),
            _alert(3),
        ])
        sender = _Sender()
        cycle = _dispatcher(db, sender).run_once()
        self.assertEqual((cycle.discarded, cycle.sent), (2, 1))
        self.assertEqual(db.alerts[1]["status_notificacao"], "DESCARTADA")
        self.assertEqual(db.alerts[2]["status_notificacao"], "DESCARTADA")
        self.assertEqual(db.alerts[3]["status_notificacao"], "ENVIADA")

    def test_mensagem_nao_expoe_cracha_nem_tipo_cru(self):
        alerta = _alert(
            tipo="PRIMEIRA_PECA_LIBERADA", destinatario="SUPERVISAO",
            mensagem="Ana (crachá 0042) liberou o retrabalho da OP A1.",
        )
        db, sender = _Db([alerta]), _Sender()
        _dispatcher(db, sender).run_once()
        texto = sender.calls[0]["text"]
        self.assertIn("Ana liberou", texto)
        for bruto in ("0042", "crachá", "PRIMEIRA_PECA_LIBERADA", "SUPERVISAO"):
            self.assertNotIn(bruto, texto)
        self.assertIn("Supervisão", texto)


class RepositoryDetailsTests(unittest.TestCase):
    def test_historico_de_entrega_preserva_detalhes_existentes(self):
        antes = '{"cracha": "1", "autorizado_por": "Ana"}'
        depois = _mesclar_entrega_telegram(antes, agora=NOW, erro="HTTP 500", contar=True)
        self.assertIn('"cracha": "1"', depois)
        self.assertIn('"tentativas": 1', depois)
        de_novo = _mesclar_entrega_telegram(depois, agora=NOW, erro=None, contar=True)
        self.assertIn('"tentativas": 2', de_novo)
        self.assertIsNotNone(_mesclar_entrega_telegram("texto livre", agora=NOW, erro=None, contar=False))


if __name__ == "__main__":
    unittest.main()
