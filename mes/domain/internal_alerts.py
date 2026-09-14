"""Taxonomia dos alertas internos preparados para notificação futura.

A Wave 5 pediu que retrabalho, refugo, necessidade de reposição e necessidade
de nova OP deixassem de morrer no log e passassem a existir como **evento com
destinatário e notificação pendente**, pronto para o Telegram sem que o
Telegram exista agora.

Este módulo é apenas o vocabulário. Ele não envia nada, não conhece provedor,
não conhece banco. Quem grava é ``mes/services/internal_alerts.py``; quem um
dia entregar lerá ``status_notificacao = 'PENDENTE'``.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Tipos de alerta
# ---------------------------------------------------------------------------
ALERT_FIRST_PIECE_REWORK = "PRIMEIRA_PECA_RETRABALHO"
ALERT_FIRST_PIECE_RELEASED = "PRIMEIRA_PECA_LIBERADA"
ALERT_FIRST_PIECE_SCRAP = "PRIMEIRA_PECA_REFUGO"
ALERT_LATER_PIECE_REWORK = "RETRABALHO_PECA_POSTERIOR"
ALERT_SCRAP = "REFUGO"
ALERT_REPLACEMENT_NEEDED = "NECESSIDADE_REPOSICAO"
ALERT_NEW_ORDER_NEEDED = "NECESSIDADE_NOVA_OP"

ALERT_TYPES = (
    ALERT_FIRST_PIECE_REWORK,
    ALERT_FIRST_PIECE_RELEASED,
    ALERT_FIRST_PIECE_SCRAP,
    ALERT_LATER_PIECE_REWORK,
    ALERT_SCRAP,
    ALERT_REPLACEMENT_NEEDED,
    ALERT_NEW_ORDER_NEEDED,
)


# ---------------------------------------------------------------------------
# Destinatários lógicos
# ---------------------------------------------------------------------------
# O destinatário é um papel industrial, nunca uma pessoa nem um chat_id. A
# tradução para um canal concreto é responsabilidade de quem for entregar.
RECIPIENT_REWORK_RESPONSIBLE = "RESPONSAVEL_RETRABALHO"
RECIPIENT_SUPERVISION = "SUPERVISAO"
RECIPIENT_PCP = "PCP"

ALERT_RECIPIENTS = (
    RECIPIENT_REWORK_RESPONSIBLE,
    RECIPIENT_SUPERVISION,
    RECIPIENT_PCP,
)


# ---------------------------------------------------------------------------
# Severidade e ciclo de vida da notificação
# ---------------------------------------------------------------------------
SEVERITY_INFO = "INFO"
SEVERITY_ATTENTION = "ATENCAO"
SEVERITY_CRITICAL = "CRITICO"
ALERT_SEVERITIES = (SEVERITY_INFO, SEVERITY_ATTENTION, SEVERITY_CRITICAL)

NOTIFICATION_PENDING = "PENDENTE"
NOTIFICATION_SENT = "ENVIADA"
NOTIFICATION_DISCARDED = "DESCARTADA"
NOTIFICATION_STATUSES = (
    NOTIFICATION_PENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_DISCARDED,
)

# Canal previsto. Registrar o canal não liga integração alguma: ele existe para
# que a entrega futura saiba o que estava previsto quando o fato aconteceu.
CHANNEL_TELEGRAM = "telegram"
CHANNEL_INTERNAL = "interno"


# Destinatário e severidade padrão de cada tipo. Decisão funcional registrada
# uma única vez; nenhum chamador escolhe por conta própria.
ALERT_ROUTING = {
    ALERT_FIRST_PIECE_REWORK: (RECIPIENT_REWORK_RESPONSIBLE, SEVERITY_CRITICAL),
    ALERT_FIRST_PIECE_RELEASED: (RECIPIENT_SUPERVISION, SEVERITY_INFO),
    ALERT_FIRST_PIECE_SCRAP: (RECIPIENT_PCP, SEVERITY_ATTENTION),
    ALERT_LATER_PIECE_REWORK: (RECIPIENT_SUPERVISION, SEVERITY_ATTENTION),
    ALERT_SCRAP: (RECIPIENT_PCP, SEVERITY_ATTENTION),
    ALERT_REPLACEMENT_NEEDED: (RECIPIENT_PCP, SEVERITY_ATTENTION),
    ALERT_NEW_ORDER_NEEDED: (RECIPIENT_PCP, SEVERITY_CRITICAL),
}


def routing_for(alert_type: str) -> tuple[str, str]:
    """Destinatário e severidade canônicos de um tipo de alerta."""

    return ALERT_ROUTING.get(
        str(alert_type or "").strip().upper(),
        (RECIPIENT_SUPERVISION, SEVERITY_INFO),
    )


__all__ = [
    "ALERT_FIRST_PIECE_RELEASED",
    "ALERT_FIRST_PIECE_REWORK",
    "ALERT_FIRST_PIECE_SCRAP",
    "ALERT_LATER_PIECE_REWORK",
    "ALERT_NEW_ORDER_NEEDED",
    "ALERT_RECIPIENTS",
    "ALERT_REPLACEMENT_NEEDED",
    "ALERT_ROUTING",
    "ALERT_SCRAP",
    "ALERT_SEVERITIES",
    "ALERT_TYPES",
    "CHANNEL_INTERNAL",
    "CHANNEL_TELEGRAM",
    "NOTIFICATION_DISCARDED",
    "NOTIFICATION_PENDING",
    "NOTIFICATION_SENT",
    "NOTIFICATION_STATUSES",
    "RECIPIENT_PCP",
    "RECIPIENT_REWORK_RESPONSIBLE",
    "RECIPIENT_SUPERVISION",
    "SEVERITY_ATTENTION",
    "SEVERITY_CRITICAL",
    "SEVERITY_INFO",
    "routing_for",
]
