"""Alertas internos com destinatário e notificação pendente.

A Wave 5 pediu explicitamente para **não** implementar Telegram agora e, ao
mesmo tempo, para não deixar o fato industrial morrer no log. Este serviço é
exatamente essa fronteira: ele grava a obrigação de avisar alguém.

Regras que valem aqui:

* o destinatário é um papel (``PCP``, ``SUPERVISAO``, ``RESPONSAVEL_RETRABALHO``),
  nunca uma pessoa ou um ``chat_id``;
* toda linha nasce com ``status_notificacao = 'PENDENTE'`` e ``canal_previsto``
  registrado, para que a entrega futura seja uma leitura e não uma arqueologia;
* falha ao alertar **nunca** derruba o fluxo produtivo — o apontamento do
  operador não pode ser recusado porque o aviso não coube no banco;
* o mesmo fato também vai para ``eventos_sistema``, que continua sendo a trilha
  canônica de eventos técnicos do Gestor.
"""

from __future__ import annotations

from datetime import datetime
import logging

from mes.domain.internal_alerts import (
    ALERT_FIRST_PIECE_RELEASED,
    ALERT_FIRST_PIECE_REWORK,
    ALERT_FIRST_PIECE_SCRAP,
    ALERT_LATER_PIECE_REWORK,
    ALERT_NEW_ORDER_NEEDED,
    ALERT_REPLACEMENT_NEEDED,
    ALERT_SCRAP,
    CHANNEL_TELEGRAM,
    NOTIFICATION_PENDING,
    routing_for,
)


class InternalAlertService:
    """Registra alertas internos preparados para a notificação futura."""

    def __init__(self, db, operador="SISTEMA", *, now_func=None):
        self.db = db
        self.operador = str(operador or "SISTEMA").strip() or "SISTEMA"
        self._now = now_func or (lambda: datetime.now().replace(microsecond=0))

    # ------------------------------------------------------------------
    def registrar(
        self,
        tipo,
        *,
        titulo,
        mensagem,
        codigo_op=None,
        catalogo_operacao_id=None,
        numero_operacao=None,
        tipo_setor=None,
        codigo_recurso=None,
        produto_codigo=None,
        quantidade=None,
        detalhes=None,
        canal_previsto=CHANNEL_TELEGRAM,
    ):
        """Grava um alerta. Devolve a linha ou ``None`` se o banco recusar."""

        destinatario, severidade = routing_for(tipo)
        registrar = getattr(self.db, "registrar_alerta_interno", None)
        if not callable(registrar):
            return None
        agora = self._now()
        try:
            linha = registrar(
                tipo=tipo,
                severidade=severidade,
                destinatario=destinatario,
                canal_previsto=canal_previsto,
                status_notificacao=NOTIFICATION_PENDING,
                codigo_op=codigo_op,
                catalogo_operacao_id=catalogo_operacao_id,
                numero_operacao=numero_operacao,
                tipo_setor=tipo_setor,
                codigo_recurso=codigo_recurso,
                produto_codigo=produto_codigo,
                titulo=titulo,
                mensagem=mensagem,
                quantidade=quantidade,
                detalhes=detalhes,
                criado_por=self.operador,
                criado_em=agora,
            )
        except Exception:  # pragma: no cover - alerta não bloqueia produção
            logging.exception("Falha ao registrar alerta interno %s.", tipo)
            return None
        self._espelhar_em_eventos_sistema(tipo, codigo_op, mensagem, detalhes, agora)
        return linha

    def _espelhar_em_eventos_sistema(self, tipo, codigo_op, mensagem, detalhes, agora):
        registrar = getattr(self.db, "registrar_evento_sistema", None)
        if not callable(registrar):
            return
        try:
            registrar(
                tipo=f"alerta_{str(tipo).lower()}",
                origem="InternalAlertService",
                referencia=codigo_op,
                mensagem=mensagem,
                operador=self.operador,
                detalhes=None if detalhes is None else str(detalhes),
                data_hora=agora,
            )
        except Exception:  # pragma: no cover - trilha não bloqueia produção
            logging.exception("Falha ao espelhar alerta interno em eventos_sistema.")

    # ------------------------------------------------------------------
    # Fatos industriais da Wave 5
    # ------------------------------------------------------------------
    def primeira_peca_em_retrabalho(self, contexto):
        """A primeira peça reprovou: a OP está bloqueada até o responsável."""

        return self.registrar(
            ALERT_FIRST_PIECE_REWORK,
            titulo=f"Primeira peça em retrabalho — OP {contexto.get('codigo_op')}",
            mensagem=(
                f"A primeira peça da OP {contexto.get('codigo_op')} "
                f"(operação {contexto.get('numero_operacao') or '—'}) entrou em "
                f"retrabalho no recurso {contexto.get('recurso_apontado') or contexto.get('codigo_recurso') or '—'}. "
                "A OP está bloqueada e aguarda o crachá do responsável no posto."
            ),
            **_campos(contexto),
        )

    def primeira_peca_liberada(self, contexto, *, cracha, autorizado_por):
        """O responsável liberou o bloqueio no posto, com o próprio crachá."""

        return self.registrar(
            ALERT_FIRST_PIECE_RELEASED,
            titulo=f"Retrabalho da primeira peça liberado — OP {contexto.get('codigo_op')}",
            mensagem=(
                f"{autorizado_por or 'Responsável'} (crachá {cracha}) liberou o "
                f"retrabalho da primeira peça da OP {contexto.get('codigo_op')}. "
                "A primeira peça precisa ser reinspecionada antes de liberar o lote."
            ),
            detalhes={"cracha": cracha, "autorizado_por": autorizado_por},
            **_campos(contexto),
        )

    def primeira_peca_refugada(self, contexto):
        return self.registrar(
            ALERT_FIRST_PIECE_SCRAP,
            titulo=f"Primeira peça refugada — OP {contexto.get('codigo_op')}",
            mensagem=(
                f"A primeira peça da OP {contexto.get('codigo_op')} foi refugada. "
                "O operador precisa produzir e inspecionar outra primeira peça, "
                "e o refugo consome o saldo planejado."
            ),
            quantidade=1,
            **_campos(contexto),
        )

    def retrabalho_peca_posterior(self, contexto, *, quantidade):
        """Retrabalho depois da primeira peça aprovada: o fluxo continua."""

        return self.registrar(
            ALERT_LATER_PIECE_REWORK,
            titulo=f"Retrabalho durante o lote — OP {contexto.get('codigo_op')}",
            mensagem=(
                f"A OP {contexto.get('codigo_op')} registrou {quantidade} peça(s) em "
                "retrabalho após a primeira peça já aprovada. O fluxo continua; o "
                "retrabalho pendente não consome o saldo planejado."
            ),
            quantidade=quantidade,
            **_campos(contexto),
        )

    def refugo_registrado(self, contexto, *, quantidade):
        return self.registrar(
            ALERT_SCRAP,
            titulo=f"Refugo registrado — OP {contexto.get('codigo_op')}",
            mensagem=(
                f"A OP {contexto.get('codigo_op')} registrou {quantidade} refugo(s). "
                "Refugo consome o saldo planejado e nunca vira peça boa."
            ),
            quantidade=quantidade,
            **_campos(contexto),
        )

    def reposicao_necessaria(self, contexto, *, quantidade):
        return self.registrar(
            ALERT_REPLACEMENT_NEEDED,
            titulo=f"OP aguardando reposição — OP {contexto.get('codigo_op')}",
            mensagem=(
                f"A OP {contexto.get('codigo_op')} fechou o saldo com refugo. "
                f"Faltam {quantidade} peça(s) boa(s) para atender a quantidade "
                "planejada e a OP fica aguardando reposição."
            ),
            quantidade=quantidade,
            **_campos(contexto),
        )

    def nova_op_necessaria(self, contexto, *, quantidade):
        return self.registrar(
            ALERT_NEW_ORDER_NEEDED,
            titulo=f"Necessidade de nova OP — {quantidade} peça(s)",
            mensagem=(
                f"O PCP precisa providenciar {quantidade} peça(s) de reposição da OP "
                f"{contexto.get('codigo_op')} ({contexto.get('produto_codigo') or 'produto não identificado'}). "
                "Nenhuma OP foi criada automaticamente nesta etapa."
            ),
            quantidade=quantidade,
            **_campos(contexto),
        )

    # ------------------------------------------------------------------
    def listar(self, **filtros):
        loader = getattr(self.db, "listar_alertas_internos", None)
        if not callable(loader):
            return []
        return [dict(row) for row in (loader(**filtros) or ())]

    def resumo(self):
        loader = getattr(self.db, "resumo_alertas_internos", None)
        if not callable(loader):
            return []
        return [dict(row) for row in (loader() or ())]


def _campos(contexto) -> dict:
    """Reduz o contexto industrial aos campos que o alerta guarda."""

    dados = dict(contexto or {})
    return {
        "codigo_op": dados.get("codigo_op"),
        "catalogo_operacao_id": dados.get("catalogo_operacao_id"),
        "numero_operacao": dados.get("numero_operacao"),
        "tipo_setor": dados.get("tipo_setor"),
        "codigo_recurso": dados.get("codigo_recurso"),
        "produto_codigo": dados.get("produto_codigo"),
    }


__all__ = ["InternalAlertService"]
