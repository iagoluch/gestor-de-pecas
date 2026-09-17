"""Resumos automáticos de fábrica no Telegram (diário/quinzenal/mensal).

Reaproveita a mesma definição de "período fechado" já usada nos relatórios
agendados (``closed_report_period``) e os mesmos serviços de leitura da tela
gerencial (``FrontendBackendFacade``): nenhum número novo é calculado aqui,
só formatado como texto curto para celular em vez de planilha.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from collections import defaultdict
import logging

from app.core.operator_sectors import OPERATOR_SECTORS
from mes.contracts import AnalyticsFilter
from mes.integrations.notifications.telegram import send_telegram_message
from mes.services.andon import ANDON_PANEL_BY_SECTOR
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.report_scheduler import closed_report_period
from mes.services.telegram_presenter import (
    format_duration,
    format_number,
    format_percent,
    html,
)


LOGGER = logging.getLogger(__name__)

FREQUENCY_LABELS = {
    "diario": "Resumo diário",
    "quinzenal": "Resumo quinzenal",
    "mensal": "Fechamento mensal",
}

# Frequências enviadas ao grupo, na ordem em que o ciclo tenta cada uma.
DIGEST_FREQUENCIES = ("diario", "quinzenal", "mensal")

SECTOR_DESTINATION_ORDER = ("corte", "solda", "pintura", "caldeiraria")
SECTOR_DESTINATION_LABELS = {
    "corte": "Corte",
    "solda": "Solda",
    "pintura": "Pintura",
    "caldeiraria": "Caldeiraria",
}


def canonical_sectors_for_panel(panel: str) -> tuple[str, ...]:
    """Deriva o escopo do mesmo agrupamento canônico usado pelo Andon."""

    return tuple(
        sector.name
        for sector in OPERATOR_SECTORS
        if ANDON_PANEL_BY_SECTOR.get(sector.name.casefold()) == panel
    )


@dataclass(frozen=True)
class DigestDestination:
    key: str
    label: str
    chat_id: str
    sectors: tuple[str, ...] = ()


def build_digest_destinations(
    *, factory_chat_id: str | None, sector_chat_ids: dict[str, str] | None = None
) -> tuple[DigestDestination, ...]:
    """Valida a configuração e entrega destinos sem sobreposição."""

    configured = {
        str(key).strip().casefold(): str(value).strip()
        for key, value in (sector_chat_ids or {}).items()
        if str(value).strip()
    }
    unknown = sorted(set(configured) - set(SECTOR_DESTINATION_ORDER))
    if unknown:
        raise ValueError(
            "Destinos Telegram desconhecidos: " + ", ".join(unknown)
        )

    destinations = []
    global_chat = str(factory_chat_id or "").strip()
    if global_chat:
        destinations.append(DigestDestination("global", "Fábrica", global_chat))
    for key in SECTOR_DESTINATION_ORDER:
        chat_id = configured.get(key)
        if not chat_id:
            continue
        label = SECTOR_DESTINATION_LABELS[key]
        sectors = canonical_sectors_for_panel(label)
        if not sectors:
            raise ValueError(f"O painel canônico {label!r} não possui setores.")
        destinations.append(DigestDestination(key, label, chat_id, sectors))

    chat_ids = [destination.chat_id for destination in destinations]
    if len(chat_ids) != len(set(chat_ids)):
        raise ValueError("Um chat do Telegram não pode receber dois escopos de digest.")
    return tuple(destinations)


def _percentual(metrica) -> str:
    # MetricValue já guarda o valor em escala percentual (0-100, unit="%"),
    # não em fração 0-1 — ver mes/analytics/oee.py:_percent_metric.
    return format_percent(metrica) or "sem dado"


def _formatar_duracao(segundos) -> str:
    return format_duration(segundos)


def _formatar_resumo(
    *,
    label: str,
    frequency: str,
    start: datetime,
    end: datetime,
    good: int,
    scrap: int,
    rework: int,
    productive_seconds: float | None,
    downtime_seconds: float | None,
    kpis: dict | None,
    top_stops: list[dict],
) -> str:
    titulo = FREQUENCY_LABELS.get(frequency, "Resumo")
    linhas = [
        "🏭 <b>GESTOR DE PEÇAS</b>",
        f"📊 <b>{html(label)} · {html(titulo)}</b>",
        "",
        f"📅 Período: <b>{start:%d/%m} a {end:%d/%m}</b>",
        f"📈 Peças boas: <b>{format_number(good)}</b>",
        f"📦 Refugo: <b>{format_number(scrap)}</b>",
        f"📦 Retrabalho: <b>{format_number(rework)}</b>",
    ]
    if kpis is not None:
        linhas.append(
            f"OEE: <b>{_percentual(kpis.get('oee'))}</b> · "
            f"Disp.: <b>{_percentual(kpis.get('availability'))}</b> · "
            f"FTT: <b>{_percentual(kpis.get('ftt'))}</b>"
        )
    elif productive_seconds is not None and downtime_seconds is not None:
        linhas.append(
            f"⏱️ Produtivo: <b>{_formatar_duracao(productive_seconds)}</b> · "
            f"Paradas: <b>{_formatar_duracao(downtime_seconds)}</b>"
        )
    if top_stops:
        principal = top_stops[0]
        motivo = principal.get("motivo") or "Não informado"
        linhas.append(
            f"🔴 Principal parada: {html(motivo)} · "
            f"<b>{_formatar_duracao(principal.get('segundos'))}</b>"
        )
    linhas.extend(["", f"🕐 <b>Dados consolidados até {end:%H:%M}</b>"])
    return "\n".join(linhas)


def build_digest_text(
    facade: FrontendBackendFacade,
    *,
    frequency: str,
    start: datetime,
    end: datetime,
    destination: DigestDestination | None = None,
) -> str:
    target = destination or DigestDestination("global", "Fábrica", "")
    sectors = target.sectors or (None,)
    good = scrap = rework = 0
    productive_seconds = downtime_seconds = 0.0
    stops = defaultdict(float)
    global_kpis = None

    for sector in sectors:
        filtros = AnalyticsFilter(inicio=start, fim=end, setor=sector)
        overview = facade.management.get_overview(filtros)
        qualidade = facade.analytics.quality(filtros)
        paradas = facade.analytics.downtimes(filtros)
        totals = qualidade.get("totals") or {}
        hours = overview.get("hours") or {}
        good += int(totals.get("boa") or 0)
        scrap += int(totals.get("refugo") or 0)
        rework += int(totals.get("retrabalho") or 0)
        productive_seconds += float(hours.get("productive_seconds") or 0)
        downtime_seconds += float(hours.get("downtime_seconds") or 0)
        for item in paradas.get("by_reason") or ():
            stops[str(item.get("motivo") or "Não informado")] += float(
                item.get("segundos") or 0
            )
        if sector is None or len(sectors) == 1:
            global_kpis = overview.get("kpis") or {}

    top_stops = [
        {"motivo": reason, "segundos": seconds}
        for reason, seconds in sorted(
            stops.items(), key=lambda item: (-item[1], item[0].casefold())
        )[:3]
    ]
    return _formatar_resumo(
        label=target.label,
        frequency=frequency,
        start=start,
        end=end,
        good=good,
        scrap=scrap,
        rework=rework,
        productive_seconds=productive_seconds,
        downtime_seconds=downtime_seconds,
        kpis=global_kpis,
        top_stops=top_stops,
    )


@dataclass(frozen=True)
class DigestOutcome:
    frequency: str
    destination: str
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
        destinations: tuple[DigestDestination, ...],
        run_time,
        timezone,
        now_func=None,
        simulation_mode: bool = False,
        sender=send_telegram_message,
    ):
        self.db = db
        self.bot_token = bot_token
        self.destinations = tuple(destinations)
        self.run_time = run_time
        self.timezone = timezone
        self._now = now_func or datetime.now
        self.facade = FrontendBackendFacade(
            db, now_func=self._now, simulation_mode=simulation_mode
        )
        self._sender = sender

    def run_due(self, *, local_now: datetime | None = None) -> list[DigestOutcome]:
        if not self.bot_token or not self.destinations:
            return []
        agora_local = local_now or datetime.now(self.timezone)
        outcomes: list[DigestOutcome] = []
        if agora_local.time().replace(tzinfo=None) < self.run_time:
            return outcomes
        for frequencia in DIGEST_FREQUENCIES:
            for destination in self.destinations:
                outcomes.append(self._processar(frequencia, destination, agora_local))
        return outcomes

    def _processar(
        self,
        frequencia: str,
        destination: DigestDestination,
        agora_local: datetime,
    ) -> DigestOutcome:
        start, end = closed_report_period(frequencia, agora_local)
        periodo_fim: date = end.date()
        dedupe_key = (
            frequencia
            if destination.key == "global"
            else f"{frequencia}:{destination.key}"
        )
        ja_enviado = self.db.ultimo_envio_digest_telegram(dedupe_key)
        if ja_enviado is not None and ja_enviado >= periodo_fim:
            return DigestOutcome(
                frequencia,
                destination.key,
                sent=False,
                reason="periodo_ja_enviado",
            )
        texto = build_digest_text(
            self.facade,
            frequency=frequencia,
            start=start.replace(tzinfo=None),
            end=end.replace(tzinfo=None),
            destination=destination,
        )
        enviado = self._sender(
            bot_token=self.bot_token,
            chat_id=destination.chat_id,
            text=texto,
            parse_mode="HTML",
        )
        if not enviado:
            return DigestOutcome(
                frequencia, destination.key, sent=False, reason="falha_envio"
            )
        self.db.registrar_envio_digest_telegram(
            dedupe_key, periodo_fim, self._now().replace(microsecond=0)
        )
        return DigestOutcome(frequencia, destination.key, sent=True)


__all__ = [
    "DIGEST_FREQUENCIES",
    "DigestDestination",
    "DigestOutcome",
    "TelegramFactoryDigestScheduler",
    "build_digest_destinations",
    "build_digest_text",
    "canonical_sectors_for_panel",
]
