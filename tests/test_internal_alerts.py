"""`InternalAlertService` (mes/services/internal_alerts.py) não tinha
nenhum teste dedicado. A regra mais crítica do módulo é explícita no seu
próprio docstring: "falha ao alertar nunca derruba o fluxo produtivo" —
isso depende de dois blocos `except Exception` silenciosos que nenhum
teste exercitava. Também cobre `routing_for` (mes/domain/internal_alerts.py),
que decide destinatário/severidade de cada tipo de alerta.
"""

from __future__ import annotations

from datetime import datetime
import unittest

from mes.domain.internal_alerts import (
    ALERT_FIRST_PIECE_RELEASED,
    ALERT_FIRST_PIECE_REWORK,
    ALERT_FIRST_PIECE_SCRAP,
    ALERT_LATER_PIECE_REWORK,
    ALERT_NEW_ORDER_NEEDED,
    ALERT_REPLACEMENT_NEEDED,
    ALERT_SCRAP,
    NOTIFICATION_PENDING,
    RECIPIENT_PCP,
    RECIPIENT_REWORK_RESPONSIBLE,
    RECIPIENT_SUPERVISION,
    SEVERITY_ATTENTION,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    routing_for,
)
from mes.services.internal_alerts import InternalAlertService


class RoutingForTests(unittest.TestCase):
    def test_cada_tipo_conhecido_tem_roteamento_proprio(self):
        casos = {
            ALERT_FIRST_PIECE_REWORK: (RECIPIENT_REWORK_RESPONSIBLE, SEVERITY_CRITICAL),
            ALERT_FIRST_PIECE_RELEASED: (RECIPIENT_SUPERVISION, SEVERITY_INFO),
            ALERT_FIRST_PIECE_SCRAP: (RECIPIENT_PCP, SEVERITY_ATTENTION),
            ALERT_LATER_PIECE_REWORK: (RECIPIENT_SUPERVISION, SEVERITY_ATTENTION),
            ALERT_SCRAP: (RECIPIENT_PCP, SEVERITY_ATTENTION),
            ALERT_REPLACEMENT_NEEDED: (RECIPIENT_PCP, SEVERITY_ATTENTION),
            ALERT_NEW_ORDER_NEEDED: (RECIPIENT_PCP, SEVERITY_CRITICAL),
        }
        for tipo, esperado in casos.items():
            with self.subTest(tipo=tipo):
                self.assertEqual(routing_for(tipo), esperado)

    def test_tipo_desconhecido_cai_no_padrao_supervisao_info(self):
        self.assertEqual(
            routing_for("TIPO_QUE_NAO_EXISTE"), (RECIPIENT_SUPERVISION, SEVERITY_INFO)
        )
        self.assertEqual(routing_for(""), (RECIPIENT_SUPERVISION, SEVERITY_INFO))
        self.assertEqual(routing_for(None), (RECIPIENT_SUPERVISION, SEVERITY_INFO))

    def test_roteamento_e_case_insensitive(self):
        self.assertEqual(
            routing_for(ALERT_SCRAP.lower()), routing_for(ALERT_SCRAP)
        )


class _DB:
    def __init__(self, *, falha_alerta=False, falha_evento=False, sem_metodo_alerta=False):
        self.falha_alerta = falha_alerta
        self.falha_evento = falha_evento
        self.sem_metodo_alerta = sem_metodo_alerta
        self.alertas_gravados = []
        self.eventos_gravados = []
        if sem_metodo_alerta:
            self.registrar_alerta_interno = None

    def registrar_alerta_interno(self, **kwargs):
        if self.falha_alerta:
            raise RuntimeError("banco indisponível")
        linha = dict(kwargs)
        self.alertas_gravados.append(linha)
        return linha

    def registrar_evento_sistema(self, **kwargs):
        if self.falha_evento:
            raise RuntimeError("trilha indisponível")
        self.eventos_gravados.append(dict(kwargs))


class RegistrarTests(unittest.TestCase):
    def _service(self, **kwargs):
        db = kwargs.pop("db", None) or _DB(**kwargs)
        service = InternalAlertService(
            db, "OP-77", now_func=lambda: datetime(2026, 9, 23, 10, 0, 0)
        )
        return service, db

    def test_grava_alerta_com_status_pendente_e_roteamento_correto(self):
        service, db = self._service()
        linha = service.registrar(
            ALERT_SCRAP, titulo="t", mensagem="m", codigo_op="OP-1"
        )
        self.assertIsNotNone(linha)
        self.assertEqual(linha["status_notificacao"], NOTIFICATION_PENDING)
        self.assertEqual(linha["destinatario"], RECIPIENT_PCP)
        self.assertEqual(linha["severidade"], SEVERITY_ATTENTION)
        self.assertEqual(linha["criado_por"], "OP-77")

    def test_grava_tambem_espelha_em_eventos_sistema(self):
        service, db = self._service()
        service.registrar(ALERT_SCRAP, titulo="t", mensagem="m", codigo_op="OP-1")
        self.assertEqual(len(db.eventos_gravados), 1)
        self.assertEqual(db.eventos_gravados[0]["tipo"], f"alerta_{ALERT_SCRAP.lower()}")
        self.assertEqual(db.eventos_gravados[0]["referencia"], "OP-1")

    def test_db_sem_metodo_de_alerta_devolve_none_sem_quebrar(self):
        service, db = self._service(sem_metodo_alerta=True)
        linha = service.registrar(ALERT_SCRAP, titulo="t", mensagem="m")
        self.assertIsNone(linha)

    def test_falha_ao_gravar_alerta_nao_propaga_excecao(self):
        # Regra central do módulo: o apontamento do operador não pode ser
        # recusado porque o aviso não coube no banco.
        service, db = self._service(falha_alerta=True)
        try:
            linha = service.registrar(ALERT_SCRAP, titulo="t", mensagem="m")
        except Exception as exc:  # pragma: no cover - falha do teste se cair aqui
            self.fail(f"registrar() propagou exceção: {exc!r}")
        self.assertIsNone(linha)

    def test_falha_ao_espelhar_evento_nao_impede_o_alerta_gravado(self):
        service, db = self._service(falha_evento=True)
        try:
            linha = service.registrar(ALERT_SCRAP, titulo="t", mensagem="m")
        except Exception as exc:  # pragma: no cover
            self.fail(f"registrar() propagou exceção da trilha: {exc!r}")
        # O alerta em si foi gravado com sucesso; só a trilha falhou.
        self.assertIsNotNone(linha)
        self.assertEqual(len(db.alertas_gravados), 1)
        self.assertEqual(db.eventos_gravados, [])

    def test_operador_vazio_vira_sistema(self):
        db = _DB()
        service = InternalAlertService(db, "   ")
        self.assertEqual(service.operador, "SISTEMA")


class FatosIndustriaisTests(unittest.TestCase):
    """Os atalhos de alto nível (Wave 5) montam título/mensagem certos e
    chamam `registrar` com o tipo correspondente."""

    def setUp(self):
        self.db = _DB()
        self.service = InternalAlertService(self.db, "OP-1")
        self.contexto = {"codigo_op": "OP-500", "numero_operacao": "10"}

    def test_primeira_peca_em_retrabalho(self):
        linha = self.service.primeira_peca_em_retrabalho(self.contexto)
        self.assertEqual(linha["tipo"], ALERT_FIRST_PIECE_REWORK)
        self.assertIn("OP-500", linha["titulo"])

    def test_primeira_peca_liberada_registra_cracha_nos_detalhes(self):
        linha = self.service.primeira_peca_liberada(
            self.contexto, cracha="123", autorizado_por="Fulano"
        )
        self.assertEqual(linha["tipo"], ALERT_FIRST_PIECE_RELEASED)
        self.assertEqual(linha["detalhes"], {"cracha": "123", "autorizado_por": "Fulano"})

    def test_refugo_registrado_carrega_quantidade(self):
        linha = self.service.refugo_registrado(self.contexto, quantidade=3)
        self.assertEqual(linha["tipo"], ALERT_SCRAP)
        self.assertEqual(linha["quantidade"], 3)

    def test_nova_op_necessaria_usa_severidade_critica(self):
        linha = self.service.nova_op_necessaria(self.contexto, quantidade=5)
        self.assertEqual(linha["tipo"], ALERT_NEW_ORDER_NEEDED)
        self.assertEqual(linha["severidade"], SEVERITY_CRITICAL)


class ListarResumoGuardTests(unittest.TestCase):
    def test_listar_sem_metodo_no_db_devolve_lista_vazia(self):
        service = InternalAlertService(object())
        self.assertEqual(service.listar(), [])

    def test_resumo_sem_metodo_no_db_devolve_lista_vazia(self):
        service = InternalAlertService(object())
        self.assertEqual(service.resumo(), [])


if __name__ == "__main__":
    unittest.main()
