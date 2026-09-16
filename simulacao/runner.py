"""Orquestração das dez fases da simulação industrial prolongada (seção 45)."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime
import json
from pathlib import Path
import time

import psycopg

from simulacao import environment, preflight as preflight_mod, provision
from simulacao.api_client import ApiSession, SessionFactory
from simulacao.clock import VirtualClock
from simulacao.config import RUNS_ROOT, SimulationConfig
from simulacao.dbobserver import DatabaseObserver
from simulacao.detector import Detector
from simulacao.factory import (
    BasePosto,
    FactoryContext,
    PostoBancada,
    PostoCorte,
    PostoDestaque,
)
from simulacao.ingestion import ClienteIngestao, GeradorDeOrdens
from simulacao.monitors import (
    MonitorState,
    Supervisor,
    coletor_api,
    coletor_banco,
    coletor_processos,
    coletor_relogio,
)
from simulacao.observatory import ServidorObservatorio, ViewportAlvo, pagina_observatorio
from simulacao.report import gerar_relatorio
from simulacao.resource_selection import avaliar_corte, avaliar_destaque, avaliar_workbench
from simulacao.telemetry import (
    SEV_ERROR,
    SEV_INFO,
    SEV_WARNING,
    SIMULATOR_ERROR,
    UI_ERROR,
    Telemetry,
)
from simulacao.visual import ChromeCDP


PERFIS_SIMULACAO = {
    "sim_corte": "operador_corte",
    "sim_destaque": "operador_destaque",
    "sim_dobra": "operador_dobra",
    "sim_usinagem": "operador_usinagem",
    "sim_serra": "operador_serra",
    "sim_pintura": "operador_pintura",
    "sim_solda_aco1": "estacao1aco",
    "sim_solda_aco2": "estacao2aco",
    "sim_solda_aco3": "estacao3aco",
    "sim_solda_aco4": "estacao4aco",
    "sim_solda_alu1": "estacao1alu",
    "sim_solda_alu2": "estacao2alu",
    "sim_solda_robo": "robo1",
    "sim_ferramentaria": "projetos",
    "sim_prototipo": "prototipo",
    "sim_supervisor": "supervisor",
    # O rodízio de 10 s entre Andon e Solda (useTvRotation) só roda no perfil
    # dedicado de TV. Observar o Andon pela sessão de gestão mostrava a tela
    # parada — o ciclo existia e nunca era exercido.
    "sim_andon": "andon",
}

#: Eventos que justificam uma captura de tela (seção 29).
EVENTOS_CAPTURAVEIS = {
    "inicio",
    "setup",
    "checklist",
    "retrabalho",
    "refugo",
    "parada",
    "retomada",
    "finalizacao",
    "erro",
}


class SimulationRunner:
    def __init__(self, config: SimulationConfig, *, sem_observatorio: bool = False,
                 sem_capturas: bool = False):
        self.config = config
        self.sem_observatorio = sem_observatorio
        self.sem_capturas = sem_capturas
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = RUNS_ROOT / self.run_id
        self.clock = VirtualClock(config.virtual_start, config.time_scale)
        self.telemetry: Telemetry | None = None
        self.observer: DatabaseObserver | None = None
        self.detector: Detector | None = None
        self.sessions: SessionFactory | None = None
        self.api: environment.ApiProcess | None = None
        self.monitor = MonitorState()
        self.postos: list[BasePosto] = []
        self.tarefas: list[asyncio.Task] = []
        self.encerrando = asyncio.Event()
        self.parar_monitores = asyncio.Event()
        self.observatorio: ServidorObservatorio | None = None
        self.chrome: ChromeCDP | None = None
        self.contexto: FactoryContext | None = None
        self.supervisor: Supervisor | None = None
        self.sessao_supervisor: ApiSession | None = None
        self.sessao_andon: ApiSession | None = None
        self.ingestao_cliente: ClienteIngestao | None = None
        self.gerador: GeradorDeOrdens | None = None
        self.estado_fase = "preflight"
        self.preflight: preflight_mod.ResultadoPreflight | None = None
        self.baseline: dict = {}
        self.resumo_ingestao: dict = {"inicial": [], "continua": []}
        self.capturas: list[dict] = []
        self.problemas_visuais: list[dict] = []
        self.ia: list[dict] = []
        self.iniciado_em_real: datetime | None = None
        self._ultima_captura: dict[str, float] = {}
        self.selecao_postos: list[dict] = []
        self._calendar_snapshot: list[dict] = []

    # ------------------------------------------------------------------
    # FASE 1 — PREFLIGHT
    # ------------------------------------------------------------------
    async def fase_preflight(self) -> bool:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        env_file = environment.carregar_env_arquivo()
        # `montar_ambiente` é quem prova o alvo: só depois dele o observador
        # abre conexão com o banco.
        ambiente = environment.montar_ambiente(self.config, env_file)

        dsn = environment.test_dsn(env_file)
        alvo = environment.alvo_teste(env_file)
        self.observer = DatabaseObserver(dsn=dsn, database=str(alvo.get("dbname") or ""))

        # O TESTE é reaproveitado entre execuções. A janela virtual é resolvida
        # antes de qualquer artefato para que o relógio — o do simulador e o da
        # API — nasça já à frente do histórico gravado.
        config_ajustada, checagem_janela = preflight_mod.resolver_janela_virtual(
            self.observer, self.config
        )
        if config_ajustada.virtual_start != self.config.virtual_start:
            self.config = config_ajustada
            self.clock = VirtualClock(self.config.virtual_start, self.config.time_scale)
            ambiente = environment.montar_ambiente(self.config, env_file)

        self.telemetry = Telemetry(self.run_dir, self.clock)
        resultado = preflight_mod.preflight_local(self.config, env_file, ambiente)
        resultado.adicionar(checagem_janela)
        preflight_mod.preflight_banco(self.observer, resultado)
        preflight_mod.preflight_turno(self.observer, self.config, resultado)

        if not resultado.aprovado:
            self.preflight = resultado
            self._salvar_preflight(resultado)
            return False

        self._preparar_calendario_do_cenario()

        # A API sobe só depois que o alvo está provado.
        self.api = environment.iniciar_api(
            self.config, ambiente, self.run_dir / "api_teste.log"
        )
        self.sessions = SessionFactory(
            base_url=self.config.api_base,
            telemetry=self.telemetry,
            thresholds=self.config.thresholds,
        )
        sessao = self.sessions.build(identity="preflight")
        if not await self._aguardar_api(sessao):
            resultado.adicionar(
                preflight_mod.Checagem(
                    "api_subiu", False, "A API TESTE não respondeu no tempo esperado."
                )
            )
            self.preflight = resultado
            self._salvar_preflight(resultado)
            return False
        await preflight_mod.preflight_api(sessao, self.config, resultado)
        await self._alinhar_relogio(sessao)
        self.preflight = resultado
        self._salvar_preflight(resultado)
        return resultado.aprovado

    async def _alinhar_relogio(self, sessao: ApiSession) -> None:
        """Zera a diferença entre o relógio do simulador e o da API."""

        resposta = await sessao.call(
            "GET", "/system/capabilities", action="alinhar_relogio", registrar=False
        )
        if not resposta.ok or not isinstance(resposta.data, dict):
            return
        referencia = (resposta.data.get("simulation") or {}).get("reference_time")
        if not referencia:
            return
        try:
            ajuste = self.clock.resync(datetime.fromisoformat(referencia))
        except ValueError:
            return
        if self.telemetry is not None:
            self.telemetry.registrar_evento(
                action="alinhamento_do_relogio_virtual",
                result=f"ajuste de {ajuste:.1f}s virtuais",
                details={"referencia_api": referencia},
            )

    async def _aguardar_api(self, sessao: ApiSession, timeout: float = 120.0) -> bool:
        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            if self.api is not None and not self.api.vivo():
                return False
            resposta = await sessao.call(
                "GET", "/system/health", action="aguardar_api", registrar=False, retries=0
            )
            if resposta.ok:
                return True
            await asyncio.sleep(1.5)
        return False

    def _salvar_preflight(self, resultado: preflight_mod.ResultadoPreflight) -> None:
        if self.telemetry is None:
            return
        self.telemetry.salvar_json("preflight.json", resultado.as_dict())
        for checagem in resultado.checagens:
            self.telemetry.registrar_evento(
                action=f"preflight:{checagem.nome}",
                result="ok" if checagem.ok else "falhou",
                severity=SEV_INFO if checagem.ok else (SEV_ERROR if checagem.critico else SEV_WARNING),
                details={"detalhe": checagem.detalhe, **checagem.dados},
            )

    def _preparar_calendario_do_cenario(self) -> None:
        """Desliga janelas extras do dia somente quando o cenário as declara.

        O snapshot é persistido antes da alteração e restaurado no ``finally``
        de ``executar``. Assim o cenário de 15/09 não transforma H1/H2 em uma
        regra permanente do calendário TESTE.
        """

        names = tuple(str(name) for name in self.config.calendar.get("disable_shift_names", ()))
        if not names or self.observer is None or self.telemetry is None:
            return
        weekday = self.config.virtual_start.weekday()
        placeholders = ", ".join("%s" for _ in names)
        self._calendar_snapshot = self.observer.consultar(
            f"SELECT id, nome, dia_semana, ativo FROM turnos_produtivos "
            f"WHERE dia_semana = %s AND nome IN ({placeholders}) ORDER BY id",
            (weekday, *names),
        )
        (self.run_dir / "snapshots").mkdir(exist_ok=True)
        self.telemetry.salvar_json("snapshots/calendario_turnos.json", self._calendar_snapshot)
        if not self._calendar_snapshot:
            return
        with psycopg.connect(self.observer.dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE turnos_produtivos SET ativo = FALSE WHERE id = ANY(%s)",
                ([row["id"] for row in self._calendar_snapshot],),
            )
        self.telemetry.registrar_evento(
            action="calendario_cenario_normalizado",
            result="janelas extras desativadas temporariamente",
            details={"turnos": self._calendar_snapshot},
        )

    def _restaurar_calendario_do_cenario(self) -> None:
        if not self._calendar_snapshot or self.observer is None:
            return
        with psycopg.connect(self.observer.dsn) as connection, connection.cursor() as cursor:
            for row in self._calendar_snapshot:
                cursor.execute(
                    "UPDATE turnos_produtivos SET ativo = %s WHERE id = %s",
                    (bool(row["ativo"]), row["id"]),
                )
        if self.telemetry is not None:
            self.telemetry.salvar_json("snapshots/calendario_restaurado.json", self._calendar_snapshot)

    # ------------------------------------------------------------------
    # FASE 2 — START
    # ------------------------------------------------------------------
    async def fase_start(self) -> None:
        assert self.telemetry and self.sessions and self.observer
        self.estado_fase = "start"
        self.baseline = preflight_mod.registrar_baseline(self.observer)
        self.telemetry.salvar_json("baseline_test.json", self.baseline)
        self.detector = Detector(observer=self.observer, telemetry=self.telemetry)
        baseline_detector = await asyncio.to_thread(self.detector.capturar_baseline)
        self.telemetry.salvar_json("baseline_detector.json", baseline_detector)

        provisionado = await asyncio.to_thread(
            provision.garantir_usuarios, PERFIS_SIMULACAO, self.config.sim_password
        )
        self.telemetry.salvar_json(
            "provisionamento_usuarios.json",
            {
                "criados": provisionado.usuarios_criados,
                "atualizados": provisionado.usuarios_atualizados,
                "recusados": provisionado.usuarios_recusados,
            },
        )

        self.sessao_supervisor = self.sessions.build(
            identity="sim_supervisor", sector="Gestão", operator_badge="GESTAO"
        )
        login = await self.sessao_supervisor.login("sim_supervisor", self.config.sim_password)
        if not login.ok:
            raise RuntimeError("A sessão de gestão não autenticou; a simulação não pode observar.")

        # TV de gestão à vista: perfil próprio, porque é o perfil que ativa o
        # ciclo automático entre Andon e Solda. A sessão de gestão continua
        # navegando por conta própria, como um gestor de verdade.
        self.sessao_andon = self.sessions.build(
            identity="sim_andon", sector="Andon", operator_badge="ANDON"
        )
        if not (await self.sessao_andon.login("sim_andon", self.config.sim_password)).ok:
            self.sessao_andon = None

        crachas = [
            {"cracha": posto.cracha, "nome": posto.nome} for posto in self.config.postos
        ]
        crachas += [
            {"cracha": codigo, "nome": f"SIMULAÇÃO — Operador de apoio {codigo}"}
            for codigo in self.config.crachas_apoio
        ]
        crachas += [
            {
                "cracha": self.config.autorizador_cracha,
                "nome": "SIMULAÇÃO — Responsável autorizador",
                "autorizador_retrabalho": True,
            },
            {"cracha": "SIM00", "nome": "SIMULAÇÃO — Crachá sem autorização"},
        ]
        resultado_crachas = await provision.garantir_crachas(self.sessao_supervisor, crachas)
        self.telemetry.salvar_json("provisionamento_crachas.json", resultado_crachas)

        planejados, nao_planejados = await self._catalogo_de_motivos()

        self.contexto = FactoryContext(
            config=self.config,
            clock=self.clock,
            telemetry=self.telemetry,
            encerrando=self.encerrando,
            motivos_planejados=planejados,
            motivos_nao_planejados=nao_planejados,
            eventos_importantes=asyncio.Queue(maxsize=500),
        )
        self.telemetry.salvar_json(
            "motivos_parada.json",
            {
                "planejados": [
                    {"codigo": i.get("codigo"), "nome": i.get("nome")} for i in planejados
                ],
                "nao_planejados": [
                    {"codigo": i.get("codigo"), "nome": i.get("nome")} for i in nao_planejados
                ],
            },
        )

        # Massa de OPs pelo pipeline canônico.
        self.ingestao_cliente = ClienteIngestao(self.config.api_base)
        self.gerador = GeradorDeOrdens(
            self.config.ingestao, self.config.seed, token=self.run_id[-6:]
        )
        await self.ingerir(int(self.config.ingestao["lote_inicial"]), rotulo="inicial")

        self.supervisor = Supervisor(
            sessao=self.sessao_supervisor,
            config=self.config,
            clock=self.clock,
            telemetry=self.telemetry,
            observer=self.observer,
            detector=self.detector,
            estado=self.monitor,
            parar=self.parar_monitores,
        )

        await self._montar_postos()
        if not self.sem_observatorio:
            await self._montar_observatorio()
        if not self.sem_capturas:
            self.chrome = ChromeCDP()
            if not await self.chrome.iniciar():
                self.telemetry.registrar_evento(
                    action="captura_visual_indisponivel",
                    severity=SEV_WARNING,
                    result=self.chrome.motivo_indisponivel,
                )

    async def _catalogo_de_motivos(self) -> tuple[list[dict], list[dict]]:
        """Motivos de parada separados pela classificação canônica do Gestor.

        Dois detalhes de contrato que já custaram uma execução inteira sem
        nenhuma parada registrada:

        * ``/operator/stop-reasons`` está atrás de ``require_operator_user``.
          A sessão de gestão não tem acesso de operador e recebe 403 — por isso
          a leitura usa um login de posto;
        * a separação planejada/não planejada vem do campo ``classificacao``
          (``planejada``/``nao_planejada``), calculado pelo próprio Gestor em
          ``ManufacturingRules.classify_stop``. O campo ``cor`` da API é o token
          de UI (``warning``/``danger``), não a cor do documento. O simulador
          não recria o mapeamento por grupo nem por nome.
        """

        assert self.sessions and self.telemetry
        posto = self.config.postos[0]
        sessao = self.sessions.build(
            identity=f"catalogo_motivos:{posto.login}",
            sector=posto.setor,
            operator_badge=posto.cracha,
        )
        try:
            login = await sessao.login(posto.login, self.config.sim_password)
            if not login.ok:
                self.telemetry.registrar_evento(
                    action="ler_motivos_parada",
                    result="login de operador recusado",
                    severity=SEV_ERROR,
                    error_code="catalogo_motivos_indisponivel",
                    details={"login": posto.login, "http_status": login.status},
                )
                return [], []
            motivos = await sessao.call(
                "GET", "/operator/stop-reasons", action="ler_motivos_parada", registrar=False
            )
        finally:
            await sessao.aclose()

        if not motivos.ok or not isinstance(motivos.data, dict):
            self.telemetry.registrar_evento(
                action="ler_motivos_parada",
                result="catálogo de motivos indisponível",
                severity=SEV_ERROR,
                error_code="catalogo_motivos_indisponivel",
                details={"http_status": motivos.status},
            )
            return [], []

        planejados, nao_planejados = [], []
        for item in motivos.data.get("items") or []:
            if item.get("setup") or item.get("retrabalho"):
                continue
            if not item.get("habilitado") or item.get("oculto"):
                continue
            if str(item.get("classificacao") or "") == "planejada":
                planejados.append(item)
            else:
                nao_planejados.append(item)

        if not planejados or not nao_planejados:
            self.telemetry.registrar_evento(
                action="ler_motivos_parada",
                result=(
                    f"catálogo incompleto: {len(planejados)} planejados / "
                    f"{len(nao_planejados)} não planejados"
                ),
                severity=SEV_WARNING,
                details={"total_recebido": len(motivos.data.get("items") or [])},
            )
        return planejados, nao_planejados

    async def ingerir(self, quantidade: int, *, rotulo: str) -> list[dict]:
        assert self.gerador and self.ingestao_cliente and self.telemetry
        ordens = self.gerador.gerar(quantidade)
        resultados = []
        for ordem in ordens:
            resultado = await self.ingestao_cliente.ingerir(ordem, self.clock.now())
            resultados.append(resultado)
            if not resultado["ok"]:
                self.telemetry.registrar_evento(
                    action="ingestao_production_order",
                    op=ordem.numero,
                    result="falha",
                    severity=SEV_ERROR,
                    error_code="ingestao_recusada",
                    details=resultado,
                )
        self.resumo_ingestao[rotulo if rotulo in self.resumo_ingestao else "continua"] += resultados
        aceitas = sum(1 for item in resultados if item["ok"])
        self.telemetry.registrar_evento(
            action=f"ingestao_lote_{rotulo}",
            result=f"{aceitas}/{len(resultados)} OPs aceitas",
            severity=SEV_INFO if aceitas == len(resultados) else SEV_WARNING,
            details={"rotulo": rotulo, "aceitas": aceitas, "total": len(resultados)},
        )
        return resultados

    async def _montar_postos(self) -> None:
        assert self.sessions and self.contexto
        porta = self.config.viewport_base_port
        corte_libera_destaque = False
        pendentes_destaque = []
        for posto in self.config.postos:
            if posto.fluxo == "destaque":
                pendentes_destaque.append(posto)
                continue
            sessao = self.sessions.build(
                identity=posto.login,
                sector=posto.setor,
                resource=posto.recurso,
                operator_badge=posto.cracha,
            )
            login = await sessao.login(posto.login, self.config.sim_password)
            if not login.ok:
                self.telemetry.registrar_evento(
                    action="login_posto",
                    operator=posto.cracha,
                    resource=posto.recurso,
                    sector=posto.setor,
                    result="falha",
                    severity=SEV_ERROR,
                    error_code=login.code or "login_recusado",
                )
                self.selecao_postos.append({
                    "posto": posto.id, "recurso": posto.recurso, "setor": posto.setor,
                    "selecionado": False, "motivo": "login_recusado",
                })
                continue
            if posto.fluxo == "corte":
                resposta = await sessao.call(
                    "GET", "/cutting/queue", params={"resource": posto.recurso},
                    action="validar_vinculo_operacional", registrar=False,
                )
                decisao = avaliar_corte(resposta.data if resposta.ok else None, posto.recurso)
                corte_libera_destaque = corte_libera_destaque or bool(decisao.get("libera_destaque"))
            else:
                resposta = await sessao.call(
                    "GET", "/operator/workbench", params={"resource": posto.recurso},
                    action="validar_vinculo_operacional", registrar=False,
                )
                decisao = avaliar_workbench(resposta.data if resposta.ok else None, posto.recurso)
            self.selecao_postos.append({
                "posto": posto.id, "recurso": posto.recurso, "setor": posto.setor,
                "fluxo": posto.fluxo, "status_http": resposta.status, **decisao,
            })
            if not decisao["selecionado"]:
                await sessao.aclose()
                continue
            classe = {
                "corte": PostoCorte,
                "destaque": PostoDestaque,
            }.get(posto.fluxo, PostoBancada)
            self.postos.append(classe(posto, sessao, self.contexto, viewport_port=porta))
            porta += 1

        for posto in pendentes_destaque:
            decisao = avaliar_destaque(corte_libera_destaque=corte_libera_destaque)
            registro = {
                "posto": posto.id, "recurso": posto.recurso, "setor": posto.setor,
                "fluxo": posto.fluxo, **decisao,
            }
            self.selecao_postos.append(registro)
            if not decisao["selecionado"]:
                continue
            sessao = self.sessions.build(
                identity=posto.login,
                sector=posto.setor,
                resource=posto.recurso,
                operator_badge=posto.cracha,
            )
            login = await sessao.login(posto.login, self.config.sim_password)
            if not login.ok:
                registro.update({"selecionado": False, "motivo": "login_recusado"})
                continue
            self.postos.append(PostoDestaque(posto, sessao, self.contexto, viewport_port=porta))
            porta += 1
        self.telemetry.salvar_json("selecao_postos.json", {
            "modo": self.config.selecao_postos["modo"],
            "postos": self.selecao_postos,
            "total_configurados": len(self.config.postos),
            "total_selecionados": len(self.postos),
        })

    async def _montar_observatorio(self) -> None:
        self.observatorio = ServidorObservatorio(
            observatory_port=self.config.observatory_port,
            api_base=self.config.api_base,
            provedor_estado=self.estado_observatorio,
            pagina=pagina_observatorio,
        )
        for posto in self.postos:
            self.observatorio.registrar_viewport(
                ViewportAlvo(
                    posto_id=posto.posto.id,
                    nome=posto.posto.nome,
                    porta=posto.state.viewport_port,
                    cookies=posto.sessao.cookies,
                    recurso=posto.posto.recurso,
                )
            )
        if self.sessao_supervisor is not None:
            self.observatorio.registrar_viewport(
                ViewportAlvo(
                    posto_id="gestao",
                    nome="SIMULAÇÃO — Gestão",
                    porta=self.config.viewport_base_port + 90,
                    cookies=self.sessao_supervisor.cookies,
                )
            )
        if self.sessao_andon is not None:
            self.observatorio.registrar_viewport(
                ViewportAlvo(
                    posto_id="andon_tv",
                    nome="SIMULAÇÃO — TV Andon/Solda",
                    porta=self.config.viewport_base_port + 91,
                    cookies=self.sessao_andon.cookies,
                )
            )
        await self.observatorio.iniciar()

    # ------------------------------------------------------------------
    # FASES 3-7 — operação, picos, falhas humanas e observação
    # ------------------------------------------------------------------
    async def fase_operacao(self) -> None:
        assert self.telemetry and self.detector and self.supervisor
        self.estado_fase = "operacao"
        self.iniciado_em_real = datetime.now()

        for indice, posto in enumerate(self.postos):
            self.tarefas.append(
                asyncio.create_task(posto.executar(), name=f"posto-{posto.posto.id}")
            )
            # Entrada progressiva (fase 3): os postos não abrem todos juntos.
            if indice % 4 == 3:
                await asyncio.sleep(0.4)

        self.tarefas += [
            asyncio.create_task(
                coletor_api(
                    sessions=self.sessions,
                    telemetry=self.telemetry,
                    estado=self.monitor,
                    parar=self.parar_monitores,
                    thresholds=self.config.thresholds,
                ),
                name="coletor-api",
            ),
            asyncio.create_task(
                coletor_banco(
                    observer=self.observer,
                    telemetry=self.telemetry,
                    estado=self.monitor,
                    parar=self.parar_monitores,
                    thresholds=self.config.thresholds,
                ),
                name="coletor-banco",
            ),
            asyncio.create_task(
                coletor_processos(
                    api_pid=self.api.pid,
                    telemetry=self.telemetry,
                    estado=self.monitor,
                    parar=self.parar_monitores,
                    thresholds=self.config.thresholds,
                ),
                name="coletor-processos",
            ),
            asyncio.create_task(
                coletor_relogio(
                    sessao=self.sessao_supervisor,
                    clock=self.clock,
                    telemetry=self.telemetry,
                    parar=self.parar_monitores,
                ),
                name="coletor-relogio",
            ),
            asyncio.create_task(self.supervisor.executar(), name="supervisor"),
            asyncio.create_task(self._laco_detector(), name="detector"),
            asyncio.create_task(self._laco_ingestao(), name="ingestao-continua"),
            asyncio.create_task(self._laco_checkpoints(), name="checkpoints"),
            asyncio.create_task(self._laco_capturas(), name="capturas"),
            asyncio.create_task(self._laco_ia(), name="ia"),
        ]

        limite_real = time.monotonic() + self.config.duration_seconds
        while time.monotonic() < limite_real and self.clock.now() < self.config.virtual_end:
            if self.api is not None and not self.api.vivo():
                self.telemetry.registrar_evento(
                    action="api_encerrou_inesperadamente",
                    classification=SIMULATOR_ERROR,
                    severity=SEV_ERROR,
                    result="processo_da_api_morreu",
                )
                break
            await asyncio.sleep(1.0)

    async def _laco_detector(self, intervalo_virtual_min: float = 12.0) -> None:
        while not self.parar_monitores.is_set():
            await self.clock.aguardar_virtual(intervalo_virtual_min * 60)
            if self.parar_monitores.is_set():
                break
            await asyncio.to_thread(self.detector.executar, fase=self.contexto.fase_atual())

    async def _laco_ingestao(self) -> None:
        """O PCP libera OP ao longo do turno, não só na abertura."""

        total = int(self.config.ingestao["lote_continuo"])
        if total <= 0:
            return
        lotes = 6
        por_lote = max(1, total // lotes)
        for _ in range(lotes):
            await self.clock.aguardar_virtual(65 * 60)
            if self.parar_monitores.is_set():
                return
            await self.ingerir(por_lote, rotulo="continua")

    async def _laco_ia(self) -> None:
        while not self.parar_monitores.is_set():
            await self.clock.aguardar_virtual(55 * 60)
            if self.parar_monitores.is_set():
                return
            resultado = await self.supervisor.perguntar_ia()
            self.ia.append({"instante_virtual": self.clock.now().isoformat(), **resultado})

    async def _laco_checkpoints(self) -> None:
        for checkpoint in self.config.checkpoints:
            alvo = self.config.virtual_at(checkpoint["hora"])
            if alvo <= self.clock.now():
                continue
            await self.clock.aguardar_ate(alvo)
            if self.parar_monitores.is_set():
                return
            await self._checkpoint(checkpoint["nome"])

    async def _checkpoint(self, nome: str) -> None:
        assert self.telemetry
        self.telemetry.registrar_evento(
            action=f"checkpoint:{nome}",
            result=f"fase {self.contexto.fase_atual()}",
            details={
                "fabrica": self._resumo_fabrica(),
                "api": self.monitor.api,
                "banco_conexoes": (self.monitor.banco or {}).get("conexoes"),
            },
        )
        snapshot = {
            "checkpoint": nome,
            **self.clock.stamp(),
            "fabrica": self._resumo_fabrica(),
            "setores": self._resumo_setores(),
            "api": self.monitor.api,
            "andon": self.monitor.andon,
            "consistencia": self.monitor.consistencia,
        }
        (self.run_dir / "checkpoints").mkdir(exist_ok=True)
        (self.run_dir / "checkpoints" / f"{nome}.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        await self._capturar_paineis(nome)
        await self._comparar_ui_api(nome)

    async def _capturar_paineis(self, nome: str) -> None:
        if self.chrome is None or not self.chrome.disponivel:
            return
        base = self.config.viewport_base_port + 90
        paineis = [
            ("observatorio", f"http://127.0.0.1:{self.config.observatory_port}/simulation-observatory"),
            ("andon", f"http://127.0.0.1:{base}/andon"),
            ("gestao_visao_geral", f"http://127.0.0.1:{base}/inicio/visao-geral"),
            ("gestao_setores", f"http://127.0.0.1:{base}/inicio/setores"),
            ("solda_gerencial", f"http://127.0.0.1:{base}/welding-management"),
        ]
        # A TV entra no ciclo sozinha: abrir /andon no perfil dedicado e esperar
        # mais de 10 s captura a segunda visão sem navegar para ela.
        if self.sessao_andon is not None:
            paineis.append(("tv_andon", f"http://127.0.0.1:{base + 1}/andon"))
        for rotulo, url in paineis:
            await self._capturar(f"{nome}__{rotulo}", url, contexto={"checkpoint": nome, "painel": rotulo})

    async def _laco_capturas(self) -> None:
        """Consome a fila de eventos relevantes e captura com parcimônia."""

        assert self.contexto is not None
        fila = self.contexto.eventos_importantes
        while not self.parar_monitores.is_set():
            try:
                evento = await asyncio.wait_for(fila.get(), timeout=3.0)
            except asyncio.TimeoutError:
                continue
            if self.chrome is None or not self.chrome.disponivel:
                continue
            posto = next((p for p in self.postos if p.posto.id == evento.get("posto")), None)
            if posto is None:
                continue
            tipo = str(evento.get("evento") or "")
            if tipo not in EVENTOS_CAPTURAVEIS:
                continue
            chave = f"{posto.posto.id}:{tipo}"
            agora = time.monotonic()
            if agora - self._ultima_captura.get(chave, -1e9) < 240:
                continue
            self._ultima_captura[chave] = agora
            url = f"http://127.0.0.1:{posto.state.viewport_port}/operador"
            await self._capturar(
                f"{posto.posto.id}__{tipo}",
                url,
                contexto={
                    "posto": posto.posto.id,
                    "operador": posto.posto.cracha,
                    "setor": posto.posto.setor,
                    "recurso": posto.posto.recurso,
                    "op": evento.get("op"),
                    "evento": tipo,
                    "estado": posto.state.estado,
                },
            )

    #: Teto de capturas por execução. A seção 29 pede evidência em evento
    #: relevante, e a 42 proíbe o capturador virar o gargalo da simulação.
    ORCAMENTO_DE_CAPTURAS = 240

    async def _capturar(self, rotulo: str, url: str, *, contexto: dict) -> None:
        assert self.telemetry
        if self.chrome is None or not self.chrome.disponivel:
            return
        if len(self.capturas) >= self.ORCAMENTO_DE_CAPTURAS:
            return
        instante = self.clock.now().strftime("%H%M%S")
        destino = self.run_dir / "screenshots" / f"{instante}__{rotulo}.png"
        resultado = await self.chrome.capturar(url, destino)
        registro = {
            **self.clock.stamp(),
            "rotulo": rotulo,
            "rota": url,
            "arquivo": Path(resultado.arquivo).name if resultado.arquivo else None,
            "erro": resultado.erro,
            "auditoria": resultado.auditoria,
            **contexto,
        }
        self.capturas.append(registro)
        self.telemetry.registrar_visual(registro)
        problemas = list((resultado.auditoria or {}).get("problemas") or [])
        if problemas:
            self.problemas_visuais.append(registro)
            self.telemetry.registrar_evento(
                operator=contexto.get("operador"),
                resource=contexto.get("recurso"),
                sector=contexto.get("setor"),
                op=contexto.get("op"),
                action=f"problema_visual:{','.join(problemas)}",
                classification=UI_ERROR,
                severity=SEV_WARNING,
                result=", ".join(problemas),
                details={"rota": url, "auditoria": resultado.auditoria,
                         "arquivo": registro["arquivo"]},
            )

    async def _comparar_ui_api(self, fase: str) -> None:
        """API × UI: o que o posto mostra precisa bater com o que a API diz."""

        if self.chrome is None or not self.chrome.disponivel or self.detector is None:
            return
        candidatos = [p for p in self.postos if p.state.op and p.posto.fluxo == "bancada"]
        if not candidatos:
            return
        for posto in candidatos[:3]:
            op_api = posto.state.op
            url = f"http://127.0.0.1:{posto.state.viewport_port}/operador"
            destino = (
                self.run_dir
                / "screenshots"
                / f"{self.clock.now():%H%M%S}__consistencia__{posto.posto.id}.png"
            )
            resultado = await self.chrome.capturar(url, destino)
            texto = str((resultado.auditoria or {}).get("amostra") or "")
            registro = {
                **self.clock.stamp(),
                "rotulo": f"consistencia__{posto.posto.id}",
                "rota": url,
                "arquivo": destino.name if resultado.arquivo else None,
                "posto": posto.posto.id,
                "op_api": op_api,
                "auditoria": resultado.auditoria,
                "erro": resultado.erro,
            }
            self.capturas.append(registro)
            self.telemetry.registrar_visual(registro)
            if resultado.erro or not texto:
                continue
            if op_api and op_api not in texto and "Carregando" not in texto:
                self.detector.registrar_divergencia(
                    tipo="DATA_VIEW_MISMATCH",
                    titulo="A tela do operador não exibe a OP que a API declara ativa",
                    severidade=SEV_WARNING,
                    evidencia={
                        "chave": posto.posto.id,
                        "op_api": op_api,
                        "estado_simulador": posto.state.estado,
                        "amostra_ui": texto[:300],
                        "arquivo": registro["arquivo"],
                    },
                    fase=fase,
                )

    # ------------------------------------------------------------------
    # Observatório — projeção do estado
    # ------------------------------------------------------------------
    def _resumo_fabrica(self) -> dict:
        estados = [posto.state for posto in self.postos]
        return {
            "postos": len(estados),
            "produzindo": sum(1 for e in estados if e.estado == "producao"),
            "parados": sum(1 for e in estados if e.estado == "parada"),
            "setup": sum(1 for e in estados if e.estado == "setup"),
            "inspecao": sum(1 for e in estados if e.estado == "inspecao"),
            "retrabalho": sum(1 for e in estados if e.estado == "retrabalho"),
            "bloqueados": sum(1 for e in estados if e.estado == "bloqueado"),
            "ociosos": sum(1 for e in estados if e.ocioso),
            "ops_ativas": len({e.op for e in estados if e.op}),
            "ops_finalizadas": sum(e.jobs_concluidos for e in estados),
            "parciais": sum(e.jobs_parciais for e in estados),
            "fila": sum(1 for e in estados if e.estado == "sem_op"),
            "retrabalhos": sum(e.retrabalhos for e in estados),
            "refugos": sum(e.refugos for e in estados),
            "bloqueios_esperados": sum(e.bloqueios_esperados for e in estados),
            "erros_simulador": sum(e.erros for e in estados),
        }

    def _resumo_setores(self) -> list[dict]:
        agrupado: dict[str, dict] = {}
        for posto in self.postos:
            estado = posto.state
            item = agrupado.setdefault(
                estado.setor,
                {"setor": estado.setor, "postos": 0, "produzindo": 0, "parados": 0,
                 "ociosos": 0, "finalizados": 0, "parciais": 0, "retrabalhos": 0,
                 "refugos": 0, "bloqueios": 0},
            )
            item["postos"] += 1
            item["produzindo"] += 1 if estado.estado == "producao" else 0
            item["parados"] += 1 if estado.estado == "parada" else 0
            item["ociosos"] += 1 if estado.ocioso else 0
            item["finalizados"] += estado.jobs_concluidos
            item["parciais"] += estado.jobs_parciais
            item["retrabalhos"] += estado.retrabalhos
            item["refugos"] += estado.refugos
            item["bloqueios"] += estado.bloqueios_esperados
        return sorted(agrupado.values(), key=lambda item: item["setor"])

    def estado_observatorio(self) -> dict:
        agora_virtual = self.clock.now()
        decorrido = self.clock.elapsed_real()
        restante = max(0.0, self.config.duration_seconds - decorrido)
        return {
            "config": {
                "seed": self.config.seed,
                "run_id": self.run_id,
                "duracao_real_min": round(self.config.duration_seconds / 60, 1),
                "duracao_virtual_h": round(self.config.factory_seconds / 3600, 2),
            },
            "estado": self.estado_fase,
            "fase": self.contexto.fase_atual() if self.contexto else "-",
            "relogio": {
                "real": datetime.now().isoformat(),
                "virtual": agora_virtual.isoformat(),
                "escala": round(self.config.time_scale, 3),
                "progresso": min(1.0, decorrido / self.config.duration_seconds),
                "restante_real": f"{int(restante // 60):02d}:{int(restante % 60):02d}",
                "deriva_segundos": round(self.clock.drift_seconds, 2),
            },
            "fabrica": self._resumo_fabrica(),
            "setores": self._resumo_setores(),
            "postos": [posto.state.as_dict(agora_virtual) for posto in self.postos],
            "performance": self.monitor.api,
            "banco": self.monitor.banco,
            "processos": self.monitor.processos,
            "andon": self.monitor.andon,
            "consistencia": self.monitor.consistencia,
            "alertas": list(reversed(self.monitor.alertas[-40:])),
            "eventos": list(reversed(self.telemetry.recentes("events", 40))) if self.telemetry else [],
            "bloqueios": list(reversed(self.telemetry.recentes("expected_blocks", 25)))
            if self.telemetry
            else [],
            "erros": list(reversed(self.telemetry.recentes("errors", 25))) if self.telemetry else [],
        }

    # ------------------------------------------------------------------
    # FASES 8-10 — consistência, encerramento e relatório
    # ------------------------------------------------------------------
    async def fase_encerramento(self) -> dict:
        assert self.telemetry and self.detector and self.observer
        self.estado_fase = "encerrando"
        self.encerrando.set()

        # 1) Para de gerar evento novo e dá tempo para o que está em voo acabar.
        await asyncio.sleep(min(20.0, max(5.0, self.config.duration_seconds * 0.01)))
        self.parar_monitores.set()
        for tarefa in self.tarefas:
            tarefa.cancel()
        for tarefa in self.tarefas:
            with suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(tarefa, timeout=10)
        self.tarefas.clear()

        # 2) Última passada do detector, já com a fábrica em repouso.
        await asyncio.to_thread(self.detector.executar, fase="encerramento")

        estado_final = await self._coletar_estado_final()
        self.telemetry.salvar_json("final_state.json", estado_final)
        return estado_final

    async def _coletar_estado_final(self) -> dict:
        assert self.observer and self.detector
        consulta = self.observer.consultar

        def seguro(sql: str, args: tuple = ()) -> list[dict]:
            try:
                return consulta(sql, args)
            except Exception as exc:
                return [{"erro": f"{type(exc).__name__}: {exc}"}]

        inicio = self.config.virtual_start
        fim = self.config.virtual_end
        estado = {
            **self.clock.stamp(),
            "run_id": self.run_id,
            "janela_virtual": {"inicio": inicio.isoformat(), "fim": fim.isoformat()},
            "wip": seguro(
                """
                SELECT status, COUNT(*) AS total
                FROM apontamentos_operacionais
                WHERE status <> 'Finalizado' GROUP BY status ORDER BY total DESC
                """
            ),
            "wip_detalhe": seguro(
                """
                SELECT id, op, tipo_setor, maquina, status, numero_operacao,
                       quantidade, quantidade_boa, quantidade_refugo, data_inicio
                FROM apontamentos_operacionais
                WHERE status <> 'Finalizado' ORDER BY tipo_setor, maquina
                """
            ),
            "producao_da_janela": seguro(
                """
                SELECT tipo_setor,
                       COUNT(*) FILTER (WHERE status = 'Finalizado') AS finalizados,
                       SUM(COALESCE(quantidade_boa,0)) AS boas,
                       SUM(COALESCE(quantidade_refugo,0)) AS refugo,
                       SUM(COALESCE(quantidade_retrabalho,0)) AS retrabalho
                FROM apontamentos_operacionais
                WHERE data_entrada >= %s
                GROUP BY tipo_setor ORDER BY tipo_setor
                """,
                (inicio,),
            ),
            "eventos_por_estado": seguro(
                """
                SELECT estado, COUNT(*) AS total
                FROM eventos_apontamento_operador
                WHERE data_hora >= %s GROUP BY estado ORDER BY total DESC
                """,
                (inicio,),
            ),
            "quantidades": seguro(
                """
                SELECT tipo, COUNT(*) AS eventos, SUM(quantidade) AS quantidade
                FROM eventos_quantidade_producao
                WHERE data_hora >= %s GROUP BY tipo ORDER BY tipo
                """,
                (inicio,),
            ),
            # A categoria canônica de parada é 'parada' (EventCategory.DOWNTIME.value)
            # e o CHECK da tabela nem aceita outro valor: filtrar por 'downtime'
            # devolvia sempre zero linha e zerava os critérios de sucesso.
            # "Planejada" é definição do catálogo de motivos; as interrupções
            # automáticas (intervalo programado) não têm código e trazem a
            # classificação no próprio evento.
            "paradas": seguro(
                """
                SELECT e.codigo_status_recurso, COALESCE(s.nome, e.motivo) AS nome,
                       COALESCE(s.planejado, e.planejado, FALSE) AS planejado,
                       COUNT(*) AS ocorrencias,
                       ROUND(SUM(EXTRACT(EPOCH FROM (COALESCE(e.data_fim, %s) - e.data_inicio)))/60.0, 1)
                           AS minutos
                FROM eventos_estado_recurso e
                LEFT JOIN catalogo_status_recursos s ON s.codigo = e.codigo_status_recurso
                WHERE e.data_inicio >= %s AND e.categoria = 'parada'
                GROUP BY 1,2,3 ORDER BY minutos DESC NULLS LAST LIMIT 25
                """,
                (fim, inicio),
            ),
            "participacoes": seguro(
                """
                SELECT cracha, nome, COUNT(*) AS participacoes,
                       COUNT(*) FILTER (WHERE data_fim IS NULL) AS abertas,
                       ROUND(SUM(EXTRACT(EPOCH FROM (COALESCE(data_fim, %s) - data_inicio)))/60.0, 1)
                           AS minutos_pessoa
                FROM participacoes_operador
                WHERE data_inicio >= %s GROUP BY 1,2 ORDER BY minutos_pessoa DESC NULLS LAST
                """,
                (fim, inicio),
            ),
            "ops_com_varios_operadores": seguro(
                """
                SELECT op, numero_operacao, COUNT(DISTINCT cracha) AS operadores,
                       STRING_AGG(DISTINCT cracha, ', ') AS crachas
                FROM participacoes_operador
                WHERE data_inicio >= %s
                GROUP BY op, numero_operacao HAVING COUNT(DISTINCT cracha) > 1
                ORDER BY operadores DESC LIMIT 30
                """,
                (inicio,),
            ),
            # Wave 5.1 — apontamento em setor incorreto. O setor do roteiro é
            # preservado ao lado do setor onde a OP foi realmente apontada.
            "apontamentos_setor_divergente": seguro(
                """
                SELECT tipo_setor AS setor_apontado, setor_roteiro, maquina,
                       COUNT(*) AS apontamentos,
                       STRING_AGG(DISTINCT op, ', ') AS ops
                FROM apontamentos_operacionais
                WHERE data_inicio >= %s AND setor_divergente IS TRUE
                GROUP BY 1,2,3 ORDER BY apontamentos DESC LIMIT 20
                """,
                (inicio,),
            ),
            "primeira_peca": seguro(
                """
                SELECT status, COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE bloqueio_ativo) AS bloqueadas
                FROM qualidade_primeira_peca
                WHERE criada_em >= %s GROUP BY status ORDER BY total DESC
                """,
                (inicio,),
            ),
            # Inspeção dimensional da Qualidade: sessões da operação INSPECAO,
            # peças medidas contra o template de cotas e RNCs abertas.
            "inspecao_dimensional": seguro(
                """
                SELECT s.status,
                       COUNT(DISTINCT s.id) AS inspecoes,
                       COUNT(p.id) AS pecas,
                       COUNT(p.id) FILTER (WHERE p.resultado = 'APROVADA') AS aprovadas,
                       COUNT(p.id) FILTER (WHERE p.resultado = 'RETRABALHO') AS retrabalho,
                       COUNT(p.id) FILTER (WHERE p.resultado = 'REFUGO') AS refugo,
                       COUNT(p.rnc_id) AS rnc
                FROM qualidade_inspecoes s
                LEFT JOIN qualidade_pecas_inspecionadas p ON p.inspecao_id = s.id
                WHERE s.iniciada_em >= %s
                GROUP BY s.status ORDER BY inspecoes DESC
                """,
                (inicio,),
            ),
            "cotas_inspecionadas": seguro(
                """
                SELECT c.status, COUNT(*) AS cotas
                FROM qualidade_resultados_cota c
                JOIN qualidade_pecas_inspecionadas p ON p.id = c.peca_id
                JOIN qualidade_inspecoes s ON s.id = p.inspecao_id
                WHERE s.iniciada_em >= %s
                GROUP BY c.status ORDER BY cotas DESC
                """,
                (inicio,),
            ),
            "autorizacoes_primeira_peca": seguro(
                """
                SELECT ocorrencia, decisao, COUNT(*) AS total
                FROM qualidade_primeira_peca_autorizacoes
                WHERE data_hora >= %s GROUP BY 1,2 ORDER BY total DESC
                """,
                (inicio,),
            ),
            "corte": seguro(
                """
                SELECT status, COUNT(*) AS total
                FROM apontamentos_corte GROUP BY status ORDER BY total DESC
                """
            ),
            "destaque": seguro(
                """
                SELECT estado, COUNT(*) AS total
                FROM eventos_destaque_tarefa WHERE data_hora >= %s
                GROUP BY estado ORDER BY total DESC
                """,
                (inicio,),
            ),
            "alertas_internos": seguro(
                """
                SELECT tipo, severidade, status_notificacao, COUNT(*) AS total
                FROM alertas_internos WHERE criado_em >= %s
                GROUP BY 1,2,3 ORDER BY total DESC
                """,
                (inicio,),
            ),
            "outbox": seguro(
                "SELECT status, COUNT(*) AS total, COUNT(sent_at) AS enviadas "
                "FROM totvs_outbox GROUP BY status"
            ),
            "ops_ingeridas": seguro(
                "SELECT COUNT(*) AS total FROM catalogo_pcp_ops WHERE codigo_op LIKE %s",
                (f"{self.config.ingestao['prefixo']}{self.gerador.token if self.gerador else ''}%",),
            ),
            "crescimento_tabelas": self.observer.crescimento_total(),
            "detector": self.detector.resumo(),
            "fabrica_simulador": self._resumo_fabrica(),
            "setores_simulador": self._resumo_setores(),
            "postos": [posto.state.as_dict(self.clock.now()) for posto in self.postos],
            "api": self.monitor.api,
            "banco": self.monitor.banco,
            "processos": self.monitor.processos,
            "ia": self.ia,
            "consistencia": self.monitor.consistencia,
        }
        return estado

    # ------------------------------------------------------------------
    async def encerrar_infra(self) -> None:
        if self.chrome is not None:
            await self.chrome.encerrar()
        if self.observatorio is not None:
            await self.observatorio.encerrar()
        if self.ingestao_cliente is not None:
            await self.ingestao_cliente.aclose()
        if self.sessions is not None:
            await self.sessions.aclose()
        if self.api is not None:
            self.api.encerrar()
        if self.telemetry is not None:
            self.telemetry.close()

    # ------------------------------------------------------------------
    async def executar(self) -> int:
        try:
            aprovado = await self.fase_preflight()
            if not aprovado:
                falhas = self.preflight.falhas_criticas if self.preflight else []
                print("\nPRE-FLIGHT REPROVADO — a simulação não será iniciada.")
                for item in falhas:
                    print(f"  [FALHA] {item.nome}: {item.detalhe}", flush=True)
                if self.telemetry is not None:
                    self.telemetry.salvar_json(
                        "simulation_config.json",
                        {**self.config.as_dict(), "run_id": self.run_id, "abortada": True},
                    )
                return 2

            self.telemetry.salvar_json(
                "simulation_config.json",
                {
                    **self.config.as_dict(),
                    "run_id": self.run_id,
                    "iniciado_em_real": datetime.now().isoformat(),
                    "observatorio": f"http://127.0.0.1:{self.config.observatory_port}/simulation-observatory",
                },
            )
            await self.fase_start()
            print(
                f"\nObservatório: http://127.0.0.1:{self.config.observatory_port}/simulation-observatory"
            )
            print(f"Artefatos:    {self.run_dir}")
            print(
                f"Relógio:      {self.config.virtual_start:%d/%m %H:%M} → "
                f"{self.config.virtual_end:%d/%m %H:%M} a {self.config.time_scale:.2f}×\n"
            )
            await self.fase_operacao()
            estado_final = await self.fase_encerramento()
            caminho = gerar_relatorio(
                run_dir=self.run_dir,
                config=self.config,
                run_id=self.run_id,
                preflight=self.preflight,
                baseline=self.baseline,
                estado_final=estado_final,
                telemetry=self.telemetry,
                detector=self.detector,
                capturas=self.capturas,
                problemas_visuais=self.problemas_visuais,
                ingestao=self.resumo_ingestao,
                monitor=self.monitor,
                clock=self.clock,
                postos=[p.state for p in self.postos],
            )
            print(f"Relatório final: {caminho}", flush=True)
            return 0
        except Exception as exc:
            if self.telemetry is not None:
                self.telemetry.registrar_evento(
                    action="falha_do_simulador",
                    classification=SIMULATOR_ERROR,
                    severity=SEV_ERROR,
                    result="execucao_interrompida",
                    exception=f"{type(exc).__name__}: {exc}",
                )
            raise
        finally:
            self._restaurar_calendario_do_cenario()
            await self.encerrar_infra()
