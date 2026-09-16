"""Resumos automáticos de fábrica para o grupo de Telegram (diário/quinzenal/mensal).

Reaproveita a mesma definição de "período fechado" já usada nos relatórios
agendados (``closed_report_period``) e os mesmos serviços de leitura da tela
gerencial (``FrontendBackendFacade``): nenhum número novo é calculado aqui,
só formatado como texto curto para celular em vez de planilha.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging

from mes.contracts import AnalyticsFilter
from mes.integrations.notifications.telegram import send_telegram_message
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.report_scheduler import closed_report_period


LOGGER = logging.getLogger(__name__)

FREQUENCY_LABELS = {
    "diario": "Resumo diário",
    "quinzenal": "Resumo quinzenal",
    "mensal": "Fechamento mensal",
}

# Frequências enviadas ao grupo, na ordem em que o ciclo tenta cada uma.
DIGEST_FREQUENCIES = ("diario", "quinzenal", "mensal")


def _percentual(metrica) -> str:
    # MetricValue já guarda o valor em escala percentual (0-100, unit="%"),
    # não em fração 0-1 — ver mes/analytics/oee.py:_percent_metric.
    valor = (metrica or {}).get("value")
    if valor is None:
        return "sem dado"
    return f"{float(valor):.0f}%"


def _formatar_duracao(segundos) -> str:
    total = int(segundos or 0)
    horas, resto = divmod(total, 3600)
    minutos = resto // 60
    if horas:
        return f"{horas}h{minutos:02d}min"
    return f"{minutos}min" if minutos else "menos de 1min"


def build_digest_text(
    facade: FrontendBackendFacade, *, frequency: str, start: datetime, end: datetime
) -> str:
    filtros = AnalyticsFilter(inicio=start, fim=end)
    overview = facade.management.get_overview(filtros)
    qualidade = facade.analytics.quality(filtros)
    paradas = facade.analytics.downtimes(filtros)
    kpis = overview.get("kpis") or {}
    totals = qualidade.get("totals") or {}
    top_paradas = (paradas.get("by_reason") or [])[:5]

    titulo = FREQUENCY_LABELS.get(frequency, "Resumo")
    linhas = [
        f"📊 {titulo} — {start:%d/%m} a {end:%d/%m}",
        "",
        f"Peças boas: {totals.get('boa', 0)}",
        f"Refugo: {totals.get('refugo', 0)}",
        f"Retrabalho: {totals.get('retrabalho', 0)}",
        f"OEE: {_percentual(kpis.get('oee'))}",
        f"Disponibilidade: {_percentual(kpis.get('availability'))}",
        f"Performance: {_percentual(kpis.get('performance'))}",
        f"FTT (qualidade de 1ª): {_percentual(kpis.get('ftt'))}",
    ]
    if top_paradas:
        linhas.append("")
        linhas.append("Principais paradas do período:")
        for item in top_paradas:
            motivo = item.get("motivo") or "Não informado"
            linhas.append(f"• {motivo} — {_formatar_duracao(item.get('segundos'))}")
    return "\n".join(linhas)


@dataclass(frozen=True)
class DigestOutcome:
    frequency: str
    sent: bool
    reason: str | None = None


class TelegramFactoryDigestScheduler:
    """Ciclo idempotente: um resumo por frequência por período fechado.

    Mesmo padrão de idempotência do ``ReportScheduler`` (período fechado +
    registro do último enviado), só que a "chave" fica em uma tabela própria
    (``telegram_digest_envios``) em vez do artefato de relatório completo —
    este resumo não gera arquivo, só texto.
    """

    def __init__(
        self,
        db,
        *,
        bot_token: str,
        chat_id: str,
        run_time,
        timezone,
        now_func=None,
        simulation_mode: bool = False,
        sender=send_telegram_message,
    ):
        self.db = db
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.run_time = run_time
        self.timezone = timezone
        self._now = now_func or datetime.now
        self.facade = FrontendBackendFacade(
            db, now_func=self._now, simulation_mode=simulation_mode
        )
        self._sender = sender

    def run_due(self, *, local_now: datetime | None = None) -> list[DigestOutcome]:
        if not self.bot_token or not self.chat_id:
            return []
        agora_local = local_now or datetime.now(self.timezone)
        outcomes: list[DigestOutcome] = []
        if agora_local.time().replace(tzinfo=None) < self.run_time:
            return outcomes
        for frequencia in DIGEST_FREQUENCIES:
            outcomes.append(self._processar(frequencia, agora_local))
        return outcomes

    def _processar(self, frequencia: str, agora_local: datetime) -> DigestOutcome:
        start, end = closed_report_period(frequencia, agora_local)
        periodo_fim: date = end.date()
        ja_enviado = self.db.ultimo_envio_digest_telegram(frequencia)
        if ja_enviado is not None and ja_enviado >= periodo_fim:
            return DigestOutcome(frequencia, sent=False, reason="periodo_ja_enviado")
        texto = build_digest_text(
            self.facade,
            frequency=frequencia,
            start=start.replace(tzinfo=None),
            end=end.replace(tzinfo=None),
        )
        enviado = self._sender(bot_token=self.bot_token, chat_id=self.chat_id, text=texto)
        if not enviado:
            return DigestOutcome(frequencia, sent=False, reason="falha_envio")
        self.db.registrar_envio_digest_telegram(
            frequencia, periodo_fim, self._now().replace(microsecond=0)
        )
        return DigestOutcome(frequencia, sent=True)


__all__ = [
    "DIGEST_FREQUENCIES",
    "DigestOutcome",
    "TelegramFactoryDigestScheduler",
    "build_digest_text",
]
