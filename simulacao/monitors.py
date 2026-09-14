"""Observabilidade contínua e comparação de fontes (seções 21-24, 31-34, 41).

Três coletores periódicos e um supervisor:

* ``coletor_api`` — janela de latência/erros do próprio cliente HTTP;
* ``coletor_banco`` — ``pg_stat_*`` somente leitura, com deltas;
* ``coletor_processos`` — memória/threads da API e do simulador;
* ``Supervisor`` — o que uma pessoa da gestão faria durante o turno: Andon,
  dashboards, gestão da Solda, IA e a conferência entre as fontes.

A coleta é periódica de propósito (seção 21): amostrar é barato, consultar tudo
a cada evento não é.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import os
from typing import Any

from simulacao.api_client import ApiSession, SessionFactory
from simulacao.clock import VirtualClock
from simulacao.config import SimulationConfig
from simulacao.dbobserver import DatabaseObserver
from simulacao.detector import Detector
from simulacao.environment import memoria_processo
from simulacao.telemetry import (
    PERFORMANCE_ERROR,
    SEV_CRITICAL,
    SEV_ERROR,
    SEV_WARNING,
    Telemetry,
)


@dataclass
class MonitorState:
    """Última leitura de cada coletor, exposta pelo observatório."""

    api: dict = field(default_factory=dict)
    banco: dict = field(default_factory=dict)
    processos: dict = field(default_factory=dict)
    andon: dict = field(default_factory=dict)
    gestao: dict = field(default_factory=dict)
    ia: dict = field(default_factory=dict)
    consistencia: dict = field(default_factory=dict)
    alertas: list = field(default_factory=list)

    def registrar_alerta(self, severidade: str, titulo: str, detalhe: Any = None) -> None:
        self.alertas.append({"severidade": severidade, "titulo": titulo, "detalhe": detalhe})
        if len(self.alertas) > 200:
            del self.alertas[: len(self.alertas) - 200]


async def coletor_api(
    *,
    sessions: SessionFactory,
    telemetry: Telemetry,
    estado: MonitorState,
    parar: asyncio.Event,
    thresholds: dict,
    intervalo: float = 10.0,
) -> None:
    erro_5xx_anterior = 0
    while not parar.is_set():
        amostra = sessions.metrics.snapshot()
        estado.api = amostra
        telemetry.registrar_performance({"fonte": "api", **amostra})

        limite_erro = float(thresholds.get("latencia_error_ms", 3000))
        limite_aviso = float(thresholds.get("latencia_warning_ms", 1000))
        if amostra["p95_ms"] >= limite_erro:
            estado.registrar_alerta(SEV_ERROR, f"p95 de {amostra['p95_ms']} ms acima do limite", amostra)
            telemetry.registrar_evento(
                action="threshold_latencia_p95",
                classification=PERFORMANCE_ERROR,
                severity=SEV_ERROR,
                result=f"p95={amostra['p95_ms']}ms",
                details=amostra,
            )
        elif amostra["p95_ms"] >= limite_aviso:
            estado.registrar_alerta(SEV_WARNING, f"p95 de {amostra['p95_ms']} ms", amostra)
        if amostra["5xx"] > erro_5xx_anterior:
            estado.registrar_alerta(
                SEV_ERROR, f"{amostra['5xx'] - erro_5xx_anterior} nova(s) resposta(s) 5xx", amostra
            )
            erro_5xx_anterior = amostra["5xx"]
        try:
            await asyncio.wait_for(parar.wait(), timeout=intervalo)
        except asyncio.TimeoutError:
            continue


async def coletor_banco(
    *,
    observer: DatabaseObserver,
    telemetry: Telemetry,
    estado: MonitorState,
    parar: asyncio.Event,
    thresholds: dict,
    intervalo: float = 20.0,
) -> None:
    deadlocks_base: float | None = None
    conexoes_historico: list[int] = []
    while not parar.is_set():
        try:
            amostra = await asyncio.to_thread(observer.coletar)
        except Exception as exc:
            telemetry.registrar_evento(
                action="coletor_banco",
                classification=PERFORMANCE_ERROR,
                severity=SEV_WARNING,
                result="coleta_indisponivel",
                exception=f"{type(exc).__name__}: {exc}",
            )
            await asyncio.sleep(intervalo)
            continue
        estado.banco = amostra
        telemetry.registrar_banco(amostra)

        deadlocks = float(amostra["estatisticas"].get("deadlocks") or 0)
        if deadlocks_base is None:
            deadlocks_base = deadlocks
        elif deadlocks > deadlocks_base:
            estado.registrar_alerta(SEV_CRITICAL, "Deadlock detectado no PostgreSQL", amostra["estatisticas"])
            telemetry.registrar_evento(
                action="threshold_deadlock",
                classification=PERFORMANCE_ERROR,
                severity=SEV_CRITICAL,
                result=f"deadlocks={deadlocks}",
                details=amostra["estatisticas"],
            )
            deadlocks_base = deadlocks

        conexoes = int(amostra["conexoes"].get("conexoes") or 0)
        conexoes_historico.append(conexoes)
        if len(conexoes_historico) > 12:
            conexoes_historico.pop(0)
        limite_conexoes = float(thresholds.get("conexoes_pg_warning", 40))
        if conexoes >= limite_conexoes:
            estado.registrar_alerta(SEV_WARNING, f"{conexoes} conexões abertas no PostgreSQL", amostra["conexoes"])
        if len(conexoes_historico) == 12 and all(
            conexoes_historico[i] < conexoes_historico[i + 1] for i in range(11)
        ):
            estado.registrar_alerta(
                SEV_WARNING, "Conexões crescendo continuamente — possível vazamento", conexoes_historico
            )
        if amostra.get("bloqueios"):
            estado.registrar_alerta(SEV_WARNING, "Sessões bloqueadas por lock", amostra["bloqueios"])
        try:
            await asyncio.wait_for(parar.wait(), timeout=intervalo)
        except asyncio.TimeoutError:
            continue


async def coletor_processos(
    *,
    api_pid: int,
    telemetry: Telemetry,
    estado: MonitorState,
    parar: asyncio.Event,
    thresholds: dict,
    intervalo: float = 20.0,
) -> None:
    historico: list[float] = []
    while not parar.is_set():
        api = memoria_processo(api_pid)
        simulador = memoria_processo(os.getpid())
        amostra = {"api": api, "simulador": simulador}
        estado.processos = amostra
        telemetry.registrar_performance({"fonte": "processos", **amostra})

        rss = float(api.get("rss_mb") or 0)
        if rss:
            historico.append(rss)
            if len(historico) > 10:
                historico.pop(0)
        crescimento = (historico[-1] - historico[0]) if len(historico) >= 6 else 0.0
        limite = float(thresholds.get("memoria_crescimento_mb", 150))
        if crescimento >= limite and all(
            historico[i] <= historico[i + 1] for i in range(len(historico) - 1)
        ):
            estado.registrar_alerta(
                SEV_WARNING,
                f"Memória da API crescendo {crescimento:.0f} MB de forma contínua",
                historico,
            )
            telemetry.registrar_evento(
                action="threshold_memoria",
                classification=PERFORMANCE_ERROR,
                severity=SEV_WARNING,
                result=f"crescimento={crescimento:.0f}MB",
                details={"serie": historico},
            )
        try:
            await asyncio.wait_for(parar.wait(), timeout=intervalo)
        except asyncio.TimeoutError:
            continue


class Supervisor:
    """A visão gerencial durante o turno e a conferência entre as fontes."""

    PERGUNTAS_IA = (
        "Qual é a situação da fábrica agora?",
        "Quais recursos estão parados e por quê?",
        "Quais são as maiores perdas de produção hoje?",
        "Como está o Corte hoje?",
        "Como está a Solda hoje?",
        "Como está a Pintura hoje?",
    )

    def __init__(
        self,
        *,
        sessao: ApiSession,
        config: SimulationConfig,
        clock: VirtualClock,
        telemetry: Telemetry,
        observer: DatabaseObserver,
        detector: Detector,
        estado: MonitorState,
        parar: asyncio.Event,
    ):
        self.sessao = sessao
        self.config = config
        self.clock = clock
        self.telemetry = telemetry
        self.observer = observer
        self.detector = detector
        self.estado = estado
        self.parar = parar
        self._conversa_id: int | None = None
        self._pergunta = 0

    # ------------------------------------------------------------------
    def _periodo(self) -> dict:
        dia = self.clock.now().date().isoformat()
        return {"start": dia, "end": dia}

    async def executar(self, intervalo_virtual_min: float = 14.0) -> None:
        while not self.parar.is_set():
            try:
                await self.ciclo()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.telemetry.registrar_evento(
                    action="ciclo_supervisor",
                    classification=PERFORMANCE_ERROR,
                    severity=SEV_WARNING,
                    result="falha",
                    exception=f"{type(exc).__name__}: {exc}",
                )
            await self.clock.aguardar_virtual(intervalo_virtual_min * 60)

    async def ciclo(self) -> None:
        periodo = self._periodo()
        andon = await self.sessao.call("GET", "/andon", params=periodo, action="ler_andon")
        if andon.ok and isinstance(andon.data, dict):
            self.estado.andon = self._resumo_andon(andon.data)
        visao = await self.sessao.call(
            "GET", "/management/overview", params=periodo, action="ler_gestao_visao_geral"
        )
        setores = await self.sessao.call(
            "GET", "/management/sectors", params=periodo, action="ler_gestao_setores"
        )
        await self.sessao.call(
            "GET", "/operations/overview", params=periodo, action="ler_consulta_operacional"
        )
        await self.sessao.call("GET", "/welding", action="ler_gestao_solda")
        await self.sessao.call(
            "GET", "/management/internal-alerts", params={"pending_only": True},
            action="ler_alertas_internos",
        )
        await self.sessao.call(
            "GET", "/management/first-pieces", action="ler_primeiras_pecas_gestao"
        )
        if visao.ok and isinstance(visao.data, dict):
            self.estado.gestao = self._resumo_gestao(visao.data, setores.data)
        await self.comparar_fontes(andon.data if andon.ok else None, visao.data if visao.ok else None)

    # ------------------------------------------------------------------
    @staticmethod
    def _resumo_andon(payload: dict) -> dict:
        setores = payload.get("sectors") or []
        recursos = []
        for setor in setores:
            for recurso in setor.get("resources") or []:
                estado = recurso.get("state") or {}
                recursos.append(
                    {
                        "setor": setor.get("name") or setor.get("sector"),
                        "code": recurso.get("code"),
                        "name": recurso.get("name"),
                        "categoria": estado.get("category"),
                        "rotulo": estado.get("display_label") or estado.get("label"),
                        "classificacao": estado.get("stop_classification"),
                        "op": (recurso.get("operation") or {}).get("op")
                        if isinstance(recurso.get("operation"), dict)
                        else None,
                    }
                )
        return {
            "resumo": payload.get("summary") or {},
            "recursos": recursos,
            "resource_count": payload.get("resource_count"),
            "simulation_only": payload.get("simulation_only"),
        }

    @staticmethod
    def _resumo_gestao(visao: dict, setores: Any) -> dict:
        indicadores = visao.get("kpis") or visao.get("indicadores") or {}
        return {
            "chaves": sorted(visao)[:16],
            "kpis": {
                chave: (valor.get("value") if isinstance(valor, dict) else valor)
                for chave, valor in (indicadores or {}).items()
            },
            "setores": (
                [item.get("setor") or item.get("sector") for item in setores.get("items", [])]
                if isinstance(setores, dict)
                else []
            ),
        }

    # ------------------------------------------------------------------
    async def comparar_fontes(self, andon: dict | None, gestao: dict | None) -> None:
        """Banco → API → Andon → Gestão, com divergência registrada (seção 31)."""

        fase = self.clock.now().strftime("%H:%M")
        canonico = await asyncio.to_thread(
            self.observer.consultar,
            """
            SELECT maquina, tipo_setor, status, op, numero_operacao
            FROM apontamentos_operacionais
            WHERE status IN ('Em processo', 'Parada', 'Setup', 'Retrabalho')
            """,
        )
        por_recurso = {
            (str(linha["tipo_setor"] or ""), str(linha["maquina"] or "")): linha
            for linha in canonico
        }
        ativos_api = 0
        divergencias = []
        if andon:
            for setor in andon.get("sectors") or []:
                for recurso in setor.get("resources") or []:
                    estado = (recurso.get("state") or {}).get("category")
                    nome = str(recurso.get("name") or "")
                    setor_nome = str(setor.get("name") or setor.get("sector") or "")
                    chave = (setor_nome, nome)
                    canonica = por_recurso.get(chave)
                    if estado == "production":
                        ativos_api += 1
                    # "sem_demanda" (Wave 6 / ManufacturingRules) é estado
                    # legítimo e esperado fora de turno — não é anomalia por si.
                    # Só vira divergência pelo mesmo motivo que "idle": o
                    # domínio nunca o declara com apontamento ativo, então vê-lo
                    # sobre uma execução viva no banco é estado impossível.
                    if canonica is not None and estado in {
                        "idle",
                        "queue",
                        "unknown",
                        "sem_demanda",
                    }:
                        divergencias.append(
                            {
                                "chave": f"{setor_nome}/{nome}",
                                "andon": estado,
                                "banco": canonica["status"],
                                "op": canonica["op"],
                            }
                        )
        for item in divergencias[:10]:
            self.detector.registrar_divergencia(
                tipo="STATE_VIEW_MISMATCH",
                titulo="Andon mostra recurso livre enquanto o banco registra execução ativa",
                severidade=SEV_WARNING,
                evidencia=item,
                fase=fase,
            )
        self.estado.consistencia = {
            "instante_virtual": self.clock.now().isoformat(),
            "recursos_ativos_banco": len(por_recurso),
            "recursos_em_producao_andon": ativos_api,
            "divergencias": divergencias[:10],
        }
        self.telemetry.registrar_consistencia(
            {"tipo": "andon_vs_banco", **self.estado.consistencia}
        )

    # ------------------------------------------------------------------
    async def perguntar_ia(self) -> dict:
        """Consulta gerencial real à IA (seção 34). O mecanismo não é alterado."""

        status = await self.sessao.call("GET", "/ai/status", action="ler_status_ia")
        if not status.ok or not isinstance(status.data, dict):
            return {"disponivel": False, "motivo": "status indisponível"}
        if not status.data.get("enabled") or not status.data.get("configured"):
            return {"disponivel": False, "motivo": "IA desabilitada ou não configurada"}
        if self._conversa_id is None:
            criada = await self.sessao.call(
                "POST",
                "/ai/conversations",
                json={"title": f"Simulação industrial {self.clock.now():%d/%m %H:%M}"},
                action="criar_conversa_ia",
            )
            if not criada.ok or not isinstance(criada.data, dict):
                return {"disponivel": False, "motivo": "não foi possível abrir conversa"}
            self._conversa_id = int(criada.data.get("id") or 0) or None
        if self._conversa_id is None:
            return {"disponivel": False, "motivo": "conversa sem identificador"}

        pergunta = self.PERGUNTAS_IA[self._pergunta % len(self.PERGUNTAS_IA)]
        self._pergunta += 1
        resposta = await self.sessao.call(
            "POST",
            f"/ai/conversations/{self._conversa_id}/messages",
            json={"content": pergunta, "retry": False},
            action="perguntar_ia",
            expect=("rate_limit", "ai_disabled", "ai_not_configured"),
        )
        texto = resposta.data if isinstance(resposta.data, str) else str(resposta.data or "")
        vazamentos = [
            marcador
            for marcador in ("SELECT ", "Traceback", "psycopg", "FROM apontamentos", "sqlalchemy")
            if marcador.casefold() in texto.casefold()
        ]
        resultado = {
            "disponivel": resposta.ok,
            "pergunta": pergunta,
            "latencia_ms": round(resposta.latency_ms, 1),
            "status": resposta.status,
            "tamanho_resposta": len(texto),
            "vazamento_tecnico": vazamentos,
        }
        if vazamentos:
            self.detector.registrar_divergencia(
                tipo="IA_VAZAMENTO_TECNICO",
                titulo="Resposta da IA expôs nomenclatura técnica ou SQL",
                severidade=SEV_ERROR,
                evidencia={"chave": "ia", "marcadores": vazamentos, "pergunta": pergunta},
                fase=self.clock.now().strftime("%H:%M"),
            )
        self.estado.ia = resultado
        return resultado


async def coletor_relogio(
    *,
    sessao: ApiSession,
    clock: VirtualClock,
    telemetry: Telemetry,
    parar: asyncio.Event,
    intervalo: float = 30.0,
) -> None:
    """Confere continuamente o relógio virtual do simulador contra o da API."""

    from datetime import datetime

    while not parar.is_set():
        resposta = await sessao.call(
            "GET", "/system/capabilities", action="ler_capacidades", registrar=False
        )
        if resposta.ok and isinstance(resposta.data, dict):
            simulacao = resposta.data.get("simulation") or {}
            referencia = simulacao.get("reference_time")
            if referencia:
                try:
                    deriva = clock.observe_api(datetime.fromisoformat(referencia))
                except ValueError:
                    deriva = 0.0
                telemetry.registrar_performance(
                    {
                        "fonte": "relogio",
                        "deriva_segundos": round(deriva, 3),
                        "escala_api": simulacao.get("time_scale"),
                        "rodando": simulacao.get("running"),
                    }
                )
                if abs(deriva) > 120:
                    telemetry.registrar_evento(
                        action="deriva_relogio_virtual",
                        classification=PERFORMANCE_ERROR,
                        severity=SEV_WARNING,
                        result=f"deriva={deriva:.1f}s",
                        details={"api": referencia, "simulador": clock.now().isoformat()},
                    )
        try:
            await asyncio.wait_for(parar.wait(), timeout=intervalo)
        except asyncio.TimeoutError:
            continue
