"""Comandos privados do bot de fábrica no Telegram, para o funcionário.

Escopo deliberadamente somente-leitura: o bot responde perguntas usando os
mesmos serviços de domínio da tela (nenhuma regra nova, nenhum cálculo
duplicado), mas não apoia nenhuma ação — apontar, autorizar refugo, liberar
primeira peça continuam exclusivos da Tela do Operador. Isso evita reabrir
identidade/crachá como caminho de escrita a partir de um canal sem os mesmos
controles (recurso exclusivo, gate de primeira peça, etc.).

O vínculo crachá -> chat (``/vincular``) usa o mesmo modelo de confiança já
aceito em qualquer apontamento do Gestor: quem digita o crachá é quem
autoriza. Não há PIN adicional porque não existe em nenhum outro lugar do
sistema.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
import logging

from mes.contracts import AnalyticsFilter
from mes.services.frontend_facade import FrontendBackendFacade


LOGGER = logging.getLogger(__name__)

AJUDA_TEXTO = (
    "Comandos do Gestor de Peças:\n"
    "/vincular <crachá> — liga este chat ao seu crachá\n"
    "/meustatus — o que você está apontando agora\n"
    "/fabrica — panorama geral: quem está parado e por quê\n"
    "/producao — resumo de produção de hoje (peças boas, refugo, OEE)\n"
    "/paradas — principais motivos de parada de hoje\n"
    "/ajuda — esta mensagem"
)


def _formatar_duracao(segundos) -> str:
    total = int(segundos or 0)
    horas, resto = divmod(total, 3600)
    minutos = resto // 60
    if horas:
        return f"{horas}h{minutos:02d}min"
    if minutos:
        return f"{minutos}min"
    return "menos de 1min"


def _formatar_percentual(metrica) -> str:
    # MetricValue já guarda o valor em escala percentual (0-100, unit="%"),
    # não em fração 0-1 — ver mes/analytics/oee.py:_percent_metric.
    valor = (metrica or {}).get("value")
    if valor is None:
        return "sem dado"
    return f"{float(valor):.0f}%"


@dataclass(frozen=True)
class TelegramBotReply:
    chat_id: str
    text: str


class TelegramFactoryBotService:
    """Roteia comandos recebidos por DM para os serviços de domínio existentes."""

    def __init__(self, db, *, now_func=None, simulation_mode=False):
        self.db = db
        self._now = now_func or datetime.now
        self.facade = FrontendBackendFacade(
            db, now_func=self._now, simulation_mode=simulation_mode
        )
        self._commands = {
            "/start": self._cmd_ajuda,
            "/ajuda": self._cmd_ajuda,
            "/help": self._cmd_ajuda,
            "/vincular": self._cmd_vincular,
            "/meustatus": self._cmd_meustatus,
            "/fabrica": self._cmd_fabrica,
            "/producao": self._cmd_producao,
            "/paradas": self._cmd_paradas,
        }

    # ------------------------------------------------------------------
    def handle_update(self, update: dict) -> TelegramBotReply | None:
        """Processa uma atualização do ``getUpdates``; ``None`` = nada a responder.

        Só reage a mensagens de texto em conversa privada. O grupo da fábrica
        é canal de aviso (admin -> todos), não de comando (todos -> bot):
        misturar os dois sentidos no mesmo chat criaria ruído para quem só
        quer ver os alertas.
        """

        message = update.get("message") or {}
        chat = message.get("chat") or {}
        if str(chat.get("type") or "").strip().casefold() != "private":
            return None
        texto = str(message.get("text") or "").strip()
        if not texto:
            return None
        chat_id = str(chat.get("id") or "").strip()
        if not chat_id:
            return None
        comando, _, resto = texto.partition(" ")
        comando = comando.split("@", 1)[0].casefold()
        handler = self._commands.get(comando)
        if handler is None:
            return TelegramBotReply(chat_id, AJUDA_TEXTO)
        try:
            texto_resposta = handler(chat_id, resto.strip())
        except Exception:
            LOGGER.exception("Falha ao executar comando %s do bot de fábrica.", comando)
            texto_resposta = (
                "Não consegui buscar essa informação agora. Tente de novo em instantes."
            )
        return TelegramBotReply(chat_id, texto_resposta)

    # ------------------------------------------------------------------
    def _operador_do_chat(self, chat_id: str) -> dict | None:
        return self.db.buscar_operador_por_telegram(chat_id)

    def _cmd_ajuda(self, chat_id: str, _resto: str) -> str:
        return AJUDA_TEXTO

    def _cmd_vincular(self, chat_id: str, resto: str) -> str:
        cracha = resto.strip()
        if not cracha:
            return "Uso: /vincular <seu crachá> (o mesmo número que você usa no posto)."
        operador = self.db.vincular_telegram_operador(cracha, chat_id)
        if operador is None:
            return (
                f"Crachá {cracha!r} não encontrado ou inativo. Confira o número "
                "com o supervisor."
            )
        return (
            f"Pronto, {operador['nome']}! Este chat ficou ligado ao crachá "
            f"{operador['cracha']}. Use /meustatus para ver o que está em produção."
        )

    def _cmd_meustatus(self, chat_id: str, _resto: str) -> str:
        operador = self._operador_do_chat(chat_id)
        if operador is None:
            return "Você ainda não vinculou seu crachá aqui. Mande /vincular <crachá>."
        participacoes = self.db.participacoes_ativas_por_cracha(operador["cracha"])
        if not participacoes:
            return f"{operador['nome']}, você não tem nenhuma operação em aberto agora."
        linhas = [f"{operador['nome']}, agora você está em:"]
        agora = self._now()
        for item in participacoes:
            inicio = item.get("data_inicio")
            decorrido = _formatar_duracao((agora - inicio).total_seconds()) if inicio else "?"
            linhas.append(
                f"• OP {item.get('op')} / operação {item.get('numero_operacao')} — "
                f"{item.get('recurso')} — há {decorrido}"
            )
        return "\n".join(linhas)

    def _periodo_hoje(self) -> AnalyticsFilter:
        agora = self._now()
        inicio = datetime.combine(agora.date(), dt_time.min)
        return AnalyticsFilter(inicio=inicio, fim=agora)

    def _cmd_fabrica(self, chat_id: str, _resto: str) -> str:
        snapshot = self.facade.andon(self._periodo_hoje())
        resumo = snapshot.get("summary") or {}
        linhas = [
            f"Fábrica agora — {resumo.get('resources', 0)} recursos monitorados:",
            f"🟢 Em produção: {resumo.get('production', 0)}",
            f"🔴 Parados: {resumo.get('downtime', 0)}",
            f"🟡 Setup/retrabalho: {resumo.get('setup', 0) + resumo.get('rework', 0)}",
        ]
        parados = []
        for setor in snapshot.get("sectors") or []:
            for recurso in setor.get("resources") or []:
                estado = recurso.get("state") or {}
                if estado.get("category") != "downtime":
                    continue
                duracao = _formatar_duracao(estado.get("duration_seconds"))
                parados.append(
                    f"• {recurso.get('name')} ({setor.get('name')}) — "
                    f"{estado.get('display_label') or 'motivo não informado'} — há {duracao}"
                )
        if parados:
            linhas.append("")
            linhas.append("Parados agora:")
            linhas.extend(parados[:15])
            if len(parados) > 15:
                linhas.append(f"... e mais {len(parados) - 15} recurso(s).")
        return "\n".join(linhas)

    def _cmd_producao(self, chat_id: str, _resto: str) -> str:
        filtros = self._periodo_hoje()
        overview = self.facade.management.get_overview(filtros)
        qualidade = self.facade.analytics.quality(filtros)
        kpis = overview.get("kpis") or {}
        totals = qualidade.get("totals") or {}
        return (
            "Produção de hoje:\n"
            f"Peças boas: {totals.get('boa', 0)}\n"
            f"Refugo: {totals.get('refugo', 0)}\n"
            f"Retrabalho: {totals.get('retrabalho', 0)}\n"
            f"OEE: {_formatar_percentual(kpis.get('oee'))}\n"
            f"Disponibilidade: {_formatar_percentual(kpis.get('availability'))}\n"
            f"Performance: {_formatar_percentual(kpis.get('performance'))}\n"
            f"FTT (qualidade de 1ª): {_formatar_percentual(kpis.get('ftt'))}"
        )

    def _cmd_paradas(self, chat_id: str, _resto: str) -> str:
        filtros = self._periodo_hoje()
        paradas = self.facade.analytics.downtimes(filtros)
        motivos = (paradas.get("by_reason") or [])[:8]
        if not motivos:
            return "Sem paradas registradas hoje até agora."
        linhas = ["Principais paradas de hoje:"]
        for item in motivos:
            motivo = item.get("motivo") or "Não informado"
            linhas.append(f"• {motivo} — {_formatar_duracao(item.get('segundos'))}")
        return "\n".join(linhas)


__all__ = ["TelegramBotReply", "TelegramFactoryBotService"]
