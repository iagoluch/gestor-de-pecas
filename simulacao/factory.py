"""A fábrica simulada: postos concorrentes dirigindo a API real.

Cada posto é uma task assíncrona independente com a própria sessão HTTP, o
próprio gerador aleatório (derivado do seed) e o próprio ritmo. Não existe fila
global: Dobra não espera Usinagem, e uma parada na Serra não congela a Solda.

Três regras estruturais valem para todos os postos:

1. **tempo é virtual.** Nenhuma espera é ``sleep`` de relógio de parede; tudo
   passa por ``VirtualClock.aguardar_virtual`` e vira minuto de fábrica.
2. **o estado vem do Gestor.** O posto lê o próprio Workbench antes de agir e
   adota o WIP que encontrar, como faria um operador que chega no turno e
   encontra a máquina com OP aberta.
3. **recusa não é bug.** O que o simulador provoca de propósito é declarado em
   ``expect``; o resto é registrado para o detector decidir.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
import random
import re
from typing import Any

from simulacao.api_client import ApiResponse, ApiSession
from simulacao.clock import VirtualClock
from simulacao.config import Posto, SimulationConfig
from simulacao.telemetry import (
    DATA_INCONSISTENCY,
    SEV_ERROR,
    SEV_INFO,
    SIMULATOR_ERROR,
    Telemetry,
)


CALDEIRARIA = {"Dobra", "Usinagem", "Serra"}
SEM_SETUP = {"Solda", "Pintura"}

#: Casos obrigatórios da seção 12, na ordem em que o posto os percorre.
CASOS_COTA = ("dentro", "limite_inferior", "limite_superior", "abaixo", "acima")

#: Casos que, por construção, caem fora da faixa do padrão cadastrado. É o que
#: o backend precisa devolver como ``NAO_CONFORME`` — no portão da primeira
#: peça e na inspeção dimensional da Qualidade, que usam a mesma conta.
FORA_DA_FAIXA = frozenset({"abaixo", "acima"})

#: Cotas padrão que o simulador cadastra quando o produto ainda não tem
#: template. São as mesmas para o portão da primeira peça e para a inspeção
#: dimensional: um produto só tem um template, e ele é do produto, não da tela.
COTAS_PADRAO = (
    {"sequencia": 1, "descricao": "Comprimento", "padrao": "1200,0 +/- 1,0", "unidade": "mm"},
    {"sequencia": 2, "descricao": "Largura", "padrao": "420,0 +/- 0,8", "unidade": "mm"},
    {"sequencia": 3, "descricao": "Espessura", "padrao": "12,0 +/- 0,2", "unidade": "mm"},
)

_NUMERO = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


def _decimal(valor) -> Decimal | None:
    texto = str(valor if valor is not None else "").strip()
    if not texto or not _NUMERO.match(texto):
        return None
    try:
        return Decimal(texto.replace(",", "."))
    except InvalidOperation:
        return None


def parse_padrao(padrao) -> tuple[Decimal, Decimal] | None:
    """Extrai ``(referência, margem)`` do padrão cadastrado da cota."""

    texto = str(padrao or "").strip()
    if not texto:
        return None
    for separador in ("+/-", "+-", "±"):
        if separador in texto:
            referencia_txt, _, margem_txt = texto.partition(separador)
            referencia = _decimal(referencia_txt)
            margem = _decimal(margem_txt)
            if referencia is None or margem is None:
                return None
            return referencia, abs(margem)
    referencia = _decimal(texto)
    return (referencia, Decimal(0)) if referencia is not None else None


@dataclass
class PostoState:
    """Contexto por operador exigido pela seção 28."""

    id: str
    nome: str
    setor: str
    recurso: str
    cracha: str
    login: str
    fluxo: str
    viewport_port: int = 0
    estado: str = "fora_do_turno"
    acao_atual: str = "aguardando entrada no turno"
    proxima_acao: str = ""
    ultima_acao: str = ""
    op: str | None = None
    produto: str | None = None
    operacao: str | None = None
    desde: str = ""
    desde_virtual: datetime | None = None
    jobs_concluidos: int = 0
    jobs_parciais: int = 0
    paradas: int = 0
    retrabalhos: int = 0
    refugos: int = 0
    bloqueios_esperados: int = 0
    erros: int = 0
    ocioso: bool = True
    ultimo_erro: str = ""

    def tempo_no_estado(self, agora: datetime) -> str:
        if self.desde_virtual is None:
            return ""
        total = max(0, int((agora - self.desde_virtual).total_seconds()))
        horas, resto = divmod(total, 3600)
        minutos, segundos = divmod(resto, 60)
        return f"{horas:02d}:{minutos:02d}:{segundos:02d}"

    def as_dict(self, agora: datetime) -> dict:
        return {
            "id": self.id,
            "nome": self.nome,
            "setor": self.setor,
            "recurso": self.recurso,
            "cracha": self.cracha,
            "login": self.login,
            "fluxo": self.fluxo,
            "viewport_port": self.viewport_port,
            "estado": self.estado,
            "acao_atual": self.acao_atual,
            "proxima_acao": self.proxima_acao,
            "ultima_acao": self.ultima_acao,
            "op": self.op,
            "produto": self.produto,
            "operacao": self.operacao,
            "tempo_no_estado": self.tempo_no_estado(agora),
            "jobs_concluidos": self.jobs_concluidos,
            "jobs_parciais": self.jobs_parciais,
            "paradas": self.paradas,
            "retrabalhos": self.retrabalhos,
            "refugos": self.refugos,
            "bloqueios_esperados": self.bloqueios_esperados,
            "erros": self.erros,
            "ocioso": self.ocioso,
            "ultimo_erro": self.ultimo_erro,
        }


@dataclass
class FactoryContext:
    """Tudo o que os postos compartilham sem precisar se conhecer."""

    config: SimulationConfig
    clock: VirtualClock
    telemetry: Telemetry
    encerrando: asyncio.Event
    motivos_planejados: list[dict] = field(default_factory=list)
    motivos_nao_planejados: list[dict] = field(default_factory=list)
    estados: dict[str, PostoState] = field(default_factory=dict)
    ops_em_uso: set[str] = field(default_factory=set)
    contadores: dict[str, int] = field(default_factory=dict)
    eventos_importantes: asyncio.Queue | None = None
    templates_criados: set[str] = field(default_factory=set)
    #: Última fila lida por setor. É o único jeito de um posto encontrar uma OP
    #: que pertence ao roteiro de outro setor — insumo do erro humano "apontei
    #: no setor errado" (Wave 5.1, `setor_roteiro`/`setor_divergente`).
    fila_por_setor: dict[str, list[dict]] = field(default_factory=dict)

    def publicar_fila(self, setor: str, cartoes: list[dict]) -> None:
        self.fila_por_setor[setor] = [dict(item) for item in cartoes[:8]]

    def incrementar(self, chave: str, valor: int = 1) -> None:
        self.contadores[chave] = self.contadores.get(chave, 0) + valor

    def fase_atual(self) -> str:
        agora = self.clock.now()
        atual = self.config.fases[0]
        for fase in self.config.fases:
            if agora >= self.config.virtual_at(fase.inicio):
                atual = fase
        return atual.nome

    def ocupacao_alvo(self) -> float:
        agora = self.clock.now()
        alvo = self.config.fases[0].ocupacao_alvo
        for fase in self.config.fases:
            if agora >= self.config.virtual_at(fase.inicio):
                alvo = fase.ocupacao_alvo
        return alvo

    async def sinalizar_evento(self, payload: dict) -> None:
        """Avisa o capturador de tela que algo relevante aconteceu (seção 29)."""

        if self.eventos_importantes is None:
            return
        try:
            self.eventos_importantes.put_nowait(payload)
        except asyncio.QueueFull:
            pass


class BasePosto:
    """Comportamento comum a qualquer posto simulado."""

    def __init__(
        self,
        posto: Posto,
        sessao: ApiSession,
        contexto: FactoryContext,
        *,
        viewport_port: int = 0,
    ):
        self.posto = posto
        self.sessao = sessao
        self.ctx = contexto
        self.rng = random.Random(f"{contexto.config.seed}:{posto.id}")
        self.state = PostoState(
            id=posto.id,
            nome=posto.nome,
            setor=posto.setor,
            recurso=posto.recurso,
            cracha=posto.cracha,
            login=posto.login,
            fluxo=posto.fluxo,
            viewport_port=viewport_port,
        )
        contexto.estados[posto.id] = self.state

    # ------------------------------------------------------------------
    @property
    def clock(self) -> VirtualClock:
        return self.ctx.clock

    @property
    def comportamento(self) -> dict:
        return self.ctx.config.comportamento

    def minutos(self, chave: str) -> float:
        menor, maior = self.ctx.config.processo_minutos[chave]
        base = self.rng.uniform(menor, maior)
        variacao = self.comportamento.get("variacao_tempo", 0.2)
        fator = 1.0 + self.rng.uniform(-variacao, variacao)
        return max(0.5, base * fator)

    def sorteio(self, chave: str) -> bool:
        return self.rng.random() < float(self.comportamento.get(chave, 0.0))

    def marcar(
        self,
        estado: str,
        acao: str,
        *,
        proxima: str = "",
        op: str | None = None,
        produto: str | None = None,
        operacao: str | None = None,
        ocioso: bool | None = None,
    ) -> None:
        agora = self.clock.now()
        if estado != self.state.estado or acao != self.state.acao_atual:
            self.state.desde_virtual = agora
            self.state.desde = agora.isoformat()
        self.state.ultima_acao = self.state.acao_atual
        self.state.estado = estado
        self.state.acao_atual = acao
        self.state.proxima_acao = proxima
        if op is not None:
            self.state.op = op or None
        if produto is not None:
            self.state.produto = produto or None
        if operacao is not None:
            self.state.operacao = operacao or None
        if ocioso is not None:
            self.state.ocioso = ocioso

    async def esperar(self, minutos_virtuais: float) -> None:
        await self.clock.aguardar_virtual(minutos_virtuais * 60.0)

    def encerrando(self) -> bool:
        return self.ctx.encerrando.is_set()

    # ------------------------------------------------------------------
    async def executar(self) -> None:
        """Ciclo de vida do posto, do atraso de entrada ao fim do turno."""

        try:
            atraso = self.minutos("atraso_entrada")
            self.marcar("fora_do_turno", f"entra em {atraso:.0f} min de fábrica",
                        proxima="abrir o posto", ocioso=True)
            await self.esperar(atraso)
            await self.abrir_posto()
            while not self.encerrando():
                try:
                    await self.ciclo()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # defeito do próprio simulador
                    self.state.erros += 1
                    self.state.ultimo_erro = f"{type(exc).__name__}: {exc}"
                    self.ctx.telemetry.registrar_evento(
                        operator=self.posto.cracha,
                        resource=self.posto.recurso,
                        sector=self.posto.setor,
                        op=self.state.op,
                        action="ciclo_do_posto",
                        classification=SIMULATOR_ERROR,
                        severity=SEV_ERROR,
                        exception=f"{type(exc).__name__}: {exc}",
                        result="falha",
                    )
                    await self.esperar(self.minutos("pausa_entre_jobs"))
        except asyncio.CancelledError:
            raise
        finally:
            self.marcar("encerrado", "posto encerrado", ocioso=True)

    async def abrir_posto(self) -> None:
        self.marcar("abrindo", "abrindo o posto", proxima="ler a fila", ocioso=True)
        await self.sessao.call("GET", "/operator/context", action="abrir_posto")

    async def ciclo(self) -> None:  # pragma: no cover - especializado
        raise NotImplementedError

    # ------------------------------------------------------------------
    async def respeitar_ocupacao(self) -> bool:
        """Humaniza a ocupação da fábrica conforme a fase (seção 8)."""

        alvo = self.ctx.ocupacao_alvo()
        if self.rng.random() <= alvo:
            return True
        self.marcar(
            "ocioso",
            f"aguardando demanda ({self.ctx.fase_atual()})",
            proxima="retomar quando a fase liberar",
            ocioso=True,
        )
        await self.esperar(self.minutos("pausa_entre_jobs"))
        return False


class PostoBancada(BasePosto):
    """Dobra, Usinagem, Serra, Solda e Pintura — o fluxo de posto homologado."""

    @property
    def caldeiraria(self) -> bool:
        return self.posto.setor in CALDEIRARIA

    # ------------------------------------------------------------------
    async def ciclo(self) -> None:
        if not await self.respeitar_ocupacao():
            return
        cartoes = await self.ler_workbench()
        if cartoes is None:
            await self.esperar(self.minutos("pausa_entre_jobs"))
            return
        producao = cartoes.get("production") or []
        if producao:
            await self.continuar_wip(producao[0])
            return
        # Posto livre inspeciona antes de puxar OP nova: a inspeção dimensional
        # é o que libera a etapa seguinte do roteiro de quem já produziu.
        if await self.inspecao_dimensional():
            return
        fila = [item for item in (cartoes.get("queue") or []) if item.get("op")]
        self.ctx.publicar_fila(self.posto.setor, fila)
        if not fila:
            alheio = self._cartao_de_outro_setor()
            if alheio is not None:
                await self.apontar_em_setor_incorreto(alheio)
                return
            await self.sem_demanda()
            return
        cartao = self.escolher(fila)
        if cartao is None:
            await self.esperar(self.minutos("pausa_entre_jobs"))
            return
        await self.executar_job(cartao)

    async def ler_workbench(self) -> dict | None:
        resposta = await self.sessao.call(
            "GET",
            "/operator/workbench",
            params={"resource": self.posto.recurso},
            action="ler_workbench",
        )
        return resposta.data if resposta.ok and isinstance(resposta.data, dict) else None

    def escolher(self, fila: list[dict]) -> dict | None:
        """Escolha humanizada: normalmente a primeira, às vezes outra."""

        disponiveis = [item for item in fila if str(item.get("op")) not in self.ctx.ops_em_uso]
        if not disponiveis:
            return None
        if len(disponiveis) > 1 and self.sorteio("prob_troca_op"):
            return self.rng.choice(disponiveis[:5])
        return disponiveis[0]

    def _cartao_de_outro_setor(self) -> dict | None:
        """OP cujo roteiro pertence a outro setor — o insumo do apontamento errado.

        Só é procurada quando o próprio posto está sem fila: é assim que o erro
        acontece no chão de fábrica (o operador ocioso puxa a OP que enxergou no
        quadro do vizinho). Setores donos do próprio recurso (Pintura, Solda)
        não divergem entre si, então o alvo é sempre um setor diferente.
        """

        if not self.sorteio("prob_erro_humano"):
            return None
        candidatos = [
            cartao
            for setor, cartoes in self.ctx.fila_por_setor.items()
            if setor != self.posto.setor
            for cartao in cartoes
            if cartao.get("op") and str(cartao["op"]) not in self.ctx.ops_em_uso
        ]
        return self.rng.choice(candidatos) if candidatos else None

    async def apontar_em_setor_incorreto(self, cartao: dict) -> None:
        """Wave 5.1 — apontamento em setor incorreto, do bloqueio à exceção.

        O Gestor tem de recusar o Início sem confirmação e, depois de a exceção
        ser autorizada por crachá, gravar ``setor_roteiro`` ao lado do setor
        realmente apontado (``setor_divergente``). O ciclo segue pelo fluxo
        normal do posto: a OP foi mesmo executada no lugar errado.
        """

        op = str(cartao.get("op") or "")
        self.marcar(
            "erro_setor",
            "puxou OP do quadro de outro setor",
            proxima="tentar apontar fora do roteiro",
            op=op,
        )
        recusa = await self.acao(
            "Início",
            cartao,
            extra={"badges": [self.posto.cracha]},
            expect=(
                "confirmacao_recurso_obrigatoria",
                "confirmacao_etapa_anterior_obrigatoria",
                "operator_operation_unavailable",
                "operator_operation_not_actionable",
                "operacao_nao_apontavel",
                "operator_resource_occupied",
            ),
            rotulo="erro_humano_apontar_setor_incorreto",
        )
        if recusa.ok:
            # Aceitar sem confirmação apagaria a exceção: ninguém saberia que a
            # OP saiu do roteiro. É defeito, não comportamento humano.
            self.ctx.telemetry.registrar_evento(
                operator=self.posto.cracha,
                resource=self.posto.recurso,
                sector=self.posto.setor,
                op=op,
                action="apontamento_setor_incorreto_aceito_sem_confirmacao",
                classification=DATA_INCONSISTENCY,
                severity=SEV_ERROR,
                result="setor divergente sem exceção autorizada",
                details={"resposta": recusa.data},
            )
            return
        self.state.bloqueios_esperados += 1
        if recusa.code not in {
            "confirmacao_recurso_obrigatoria",
            "confirmacao_etapa_anterior_obrigatoria",
        }:
            await self.esperar(self.minutos("pausa_entre_jobs"))
            return
        self.ctx.incrementar("apontamentos_setor_incorreto")
        await self.executar_job(cartao)

    async def sem_demanda(self) -> None:
        """Sem OP na fila o posto para de verdade — é 'Recurso s/op'."""

        self.marcar("sem_op", "sem OP na fila", proxima="registrar parada de recurso", ocioso=True)
        if self.sorteio("prob_erro_humano"):
            await self.digitar_op_inexistente()
        if self.ctx.motivos_nao_planejados and self.rng.random() < 0.35:
            motivo = self.escolher_motivo(planejado=False)
            await self.parada_de_recurso(motivo)
        await self.esperar(self.minutos("pausa_entre_jobs"))

    async def digitar_op_inexistente(self) -> None:
        """Erro humano clássico: digitar uma OP que não existe (seção 19)."""

        codigo = f"OPX{self.rng.randint(10_000, 99_999)}"
        consulta = await self.sessao.call(
            "GET",
            f"/operator/operations/{codigo}",
            params={"resource": self.posto.recurso},
            action="erro_humano_consulta_op_inexistente",
            op=codigo,
            expect=("operator_workflow_mismatch",),
        )
        if consulta.ok and isinstance(consulta.data, dict) and consulta.data.get("items"):
            return
        recusa = await self.sessao.call(
            "POST",
            "/operator/actions",
            json={
                "action": "Início",
                "resource": self.posto.recurso,
                "op": codigo,
                "operation_number": "10",
                "badges": [self.posto.cracha],
            },
            action="erro_humano_apontar_op_inexistente",
            op=codigo,
            expect=("operator_operation_unavailable", "operator_operation_not_actionable",
                    "operator_op_required"),
        )
        if not recusa.ok:
            self.state.bloqueios_esperados += 1

    # ------------------------------------------------------------------
    def escolher_motivo(self, *, planejado: bool) -> dict:
        fonte = (
            self.ctx.motivos_planejados if planejado else self.ctx.motivos_nao_planejados
        )
        return self.rng.choice(fonte) if fonte else {}

    async def parada_de_recurso(self, motivo: dict) -> ApiResponse | None:
        if not motivo:
            return None
        payload = {
            "action": "Parada",
            "resource": self.posto.recurso,
            "stop_reason_code": motivo.get("codigo"),
            "comment": "Simulação: posto sem OP disponível na fila.",
        }
        return await self.sessao.call(
            "POST",
            "/operator/actions",
            json=payload,
            action="parada_recurso_sem_op",
            expect=("recurso_ja_parado", "motivo_parada_invalido"),
        )

    # ------------------------------------------------------------------
    async def continuar_wip(self, cartao: dict) -> None:
        """Adota uma OP que já estava aberta no posto (turno anterior/retomada)."""

        op = str(cartao.get("op") or "")
        status = str(cartao.get("status") or "")
        self.ctx.ops_em_uso.add(op)
        self.marcar(
            "retomando",
            f"assumindo WIP em {status}",
            proxima="retomar produção",
            op=op,
            produto=str(cartao.get("product") or ""),
            operacao=str(cartao.get("operation") or ""),
            ocioso=False,
        )
        try:
            if status == "Parada":
                await self.acao("Retomar", cartao, expect=("transicao_invalida",))
            elif status == "Setup":
                await self.acao("Retornar", cartao, expect=("transicao_invalida",))
            await self.esperar(self.minutos("comum") * 0.4)
            # O WIP herdado pode não ter passado pelo portão da primeira peça —
            # é exatamente o que o operador encontra ao assumir uma máquina no
            # início do turno. Sem isso, o Finalizar seria recusado e a OP ficaria
            # presa: o portão precisa ser percorrido antes de encerrar.
            if not await self.portao_primeira_peca(cartao, adotado=True):
                self.marcar("bloqueado", "primeira peça pendente no WIP assumido",
                            proxima="aguardar responsável")
                await self.esperar(self.minutos("pausa_entre_jobs"))
                return
            await self.encerrar_job(cartao, adotado=True)
        finally:
            self.ctx.ops_em_uso.discard(op)

    # ------------------------------------------------------------------
    async def executar_job(self, cartao: dict) -> None:
        op = str(cartao.get("op") or "")
        self.ctx.ops_em_uso.add(op)
        self.marcar(
            "iniciando",
            "iniciando a OP",
            proxima="produzir a primeira peça",
            op=op,
            produto=str(cartao.get("product") or ""),
            operacao=str(cartao.get("operation") or ""),
            ocioso=False,
        )
        try:
            iniciado = await self.iniciar(cartao)
            if not iniciado:
                await self.esperar(self.minutos("pausa_entre_jobs"))
                return
            await self.ctx.sinalizar_evento(
                {"posto": self.posto.id, "evento": "inicio", "op": op}
            )
            await self.esperar(self.minutos("primeira_peca"))

            liberado = await self.portao_primeira_peca(cartao)
            if not liberado:
                # O portão não liberou: a OP fica aberta, em WIP legítimo.
                self.marcar("bloqueado", "primeira peça pendente", proxima="aguardar responsável")
                await self.esperar(self.minutos("pausa_entre_jobs"))
                return

            await self.produzir(cartao)
            await self.encerrar_job(cartao)
        finally:
            self.ctx.ops_em_uso.discard(op)
            self.marcar("ocioso", "entre trabalhos", proxima="ler a fila", ocioso=True)
            await self.esperar(self.minutos("pausa_entre_jobs"))

    # ------------------------------------------------------------------
    def _payload_base(self, cartao: dict) -> dict:
        payload: dict[str, Any] = {
            "resource": self.posto.recurso,
            "op": str(cartao.get("op") or ""),
        }
        operation_id = cartao.get("catalogo_operacao_id") or cartao.get("id_operacao")
        if operation_id:
            payload["operation_id"] = int(operation_id)
        numero = cartao.get("numero_operacao")
        if numero:
            payload["operation_number"] = str(numero)
        return payload

    def crachas(self) -> list[str]:
        """Vários operadores na mesma OP quando a carga pede (seção 18)."""

        equipe = [self.posto.cracha]
        if self.sorteio("prob_operador_extra") and self.ctx.config.crachas_apoio:
            equipe.append(self.rng.choice(list(self.ctx.config.crachas_apoio)))
        return equipe

    async def acao(
        self,
        acao: str,
        cartao: dict,
        *,
        expect: tuple[str, ...] = (),
        extra: dict | None = None,
        rotulo: str | None = None,
    ) -> ApiResponse:
        payload = {**self._payload_base(cartao), "action": acao, **(extra or {})}
        return await self.sessao.call(
            "POST",
            "/operator/actions",
            json=payload,
            action=rotulo or f"acao_{acao.casefold()}",
            op=payload.get("op"),
            expect=expect,
            state_before=self.state.estado,
        )

    # ------------------------------------------------------------------
    async def iniciar(self, cartao: dict) -> bool:
        resposta = await self.acao(
            "Início",
            cartao,
            extra={"badges": self.crachas()},
            expect=(
                "operator_resource_occupied",
                "operacao_ativa_diferente",
                "operacao_finalizada",
                "operacao_nao_apontavel",
                "primeira_peca_bloqueada",
            ),
        )
        if resposta.ok:
            self.marcar("producao", "produzindo", proxima="conferir a primeira peça")
            # Erro humano: duplo clique no Iniciar (seção 19).
            if self.sorteio("prob_duplo_clique"):
                duplicado = await self.acao(
                    "Início",
                    cartao,
                    extra={"badges": [self.posto.cracha]},
                    expect=("transicao_invalida", "acao_repetida", "operator_resource_occupied"),
                    rotulo="erro_humano_duplo_clique",
                )
                if duplicado.ok:
                    # Um segundo Início aceito em produção seria estado impossível.
                    self.ctx.telemetry.registrar_evento(
                        operator=self.posto.cracha,
                        resource=self.posto.recurso,
                        sector=self.posto.setor,
                        op=str(cartao.get("op") or ""),
                        action="duplo_inicio_aceito",
                        classification=DATA_INCONSISTENCY,
                        severity=SEV_ERROR,
                        result="dupla_iniciacao",
                        details={"resposta": duplicado.data},
                    )
                else:
                    self.state.bloqueios_esperados += 1
            return True

        if resposta.code == "confirmacao_etapa_anterior_obrigatoria":
            self.state.bloqueios_esperados += 1
            return await self._confirmar_excecao(cartao, etapa_anterior=True)
        if resposta.code == "confirmacao_recurso_obrigatoria":
            self.state.bloqueios_esperados += 1
            return await self._confirmar_excecao(cartao, recurso_divergente=True)
        if resposta.code in {
            "operator_resource_occupied",
            "operacao_ativa_diferente",
            "operacao_finalizada",
            "operacao_nao_apontavel",
            "primeira_peca_bloqueada",
        }:
            self.state.bloqueios_esperados += 1
        return False

    async def _confirmar_excecao(
        self, cartao: dict, *, etapa_anterior: bool = False, recurso_divergente: bool = False
    ) -> bool:
        """A exceção operacional exige crachá autorizado — e é assim que passa."""

        invalido = await self.acao(
            "Início",
            cartao,
            extra={
                "badges": [self.ctx.config.cracha_invalido],
                "confirm_previous_step": etapa_anterior,
                "confirm_resource_divergence": recurso_divergente or etapa_anterior,
            },
            expect=("cracha_invalido", "cracha_autorizacao_obrigatorio"),
            rotulo="erro_humano_cracha_inexistente",
        )
        if not invalido.ok:
            self.state.bloqueios_esperados += 1
        autorizado = await self.acao(
            "Início",
            cartao,
            extra={
                "badges": [self.posto.cracha, self.ctx.config.autorizador_cracha],
                "confirm_previous_step": etapa_anterior,
                "confirm_resource_divergence": recurso_divergente or etapa_anterior,
            },
            expect=("operator_resource_occupied", "operacao_ativa_diferente"),
            rotulo="confirmacao_excecao_operacional",
        )
        if autorizado.ok:
            self.marcar("producao", "produzindo após confirmação", proxima="conferir a primeira peça")
            return True
        return False

    # ------------------------------------------------------------------
    async def portao_primeira_peca(self, cartao: dict, *, adotado: bool = False) -> bool:
        if self.caldeiraria:
            return await self._portao_estruturado(cartao, adotado=adotado)
        return await self._portao_simples(cartao)

    async def _portao_simples(self, cartao: dict) -> bool:
        """Solda e Pintura: peça produzida + inspeção, sem checklist de cotas."""

        await self.sessao.call(
            "POST",
            "/operator/first-piece",
            json={**self._payload_base(cartao), "action": "produzida"},
            action="primeira_peca_produzida",
            op=str(cartao.get("op") or ""),
            expect=("primeira_peca_ja_produzida", "primeira_peca_bloqueada"),
        )
        nao_conforme = self.sorteio("prob_primeira_peca_nao_conforme")
        resultado = "RETRABALHO" if nao_conforme else "CONFORME"
        resposta = await self.sessao.call(
            "POST",
            "/operator/first-piece",
            json={
                **self._payload_base(cartao),
                "action": "inspecionar",
                "result": resultado,
                "note": "Simulação — inspeção da primeira peça no posto.",
            },
            action="primeira_peca_inspecao",
            op=str(cartao.get("op") or ""),
            expect=("primeira_peca_bloqueada",),
        )
        if not resposta.ok:
            return False
        if not nao_conforme:
            return True
        self.state.retrabalhos += 1
        await self.ctx.sinalizar_evento(
            {"posto": self.posto.id, "evento": "retrabalho", "op": cartao.get("op")}
        )
        return await self._desbloquear_e_reinspecionar(cartao)

    async def _portao_estruturado(self, cartao: dict, *, adotado: bool = False) -> bool:
        """Caldeiraria (Wave 6B): Finalizar exige Setup; Setup abre o checklist."""

        # 1) Erro humano deliberado: tentar finalizar antes do portão. Só vale
        # para OP recém-iniciada: em WIP herdado a primeira peça pode já estar
        # aprovada, e aí o Finalizar seria aceito — encerrando a OP por engano
        # do simulador, não por defeito do Gestor.
        if not adotado and self.sorteio("prob_erro_humano"):
            prematuro = await self.acao(
                "Finalizado",
                cartao,
                extra={"badges": [self.posto.cracha], "good": 1},
                expect=(
                    "primeira_peca_gate_obrigatorio",
                    "primeira_peca_setup_pendente",
                    "primeira_peca_nao_produzida",
                    "primeira_peca_inspecao_pendente",
                ),
                rotulo="erro_humano_finalizar_cedo",
            )
            if not prematuro.ok:
                self.state.bloqueios_esperados += 1

        # 2) Setup — o apontamento de estado que habilita o checklist.
        setup = await self.acao(
            "Setup",
            cartao,
            extra={"setup_type": "Setup de simulação"},
            expect=("transicao_invalida", "setup_indisponivel_setor"),
        )
        if not setup.ok:
            return False
        self.marcar("setup", "em setup", proxima="preencher o checklist")
        await self.esperar(self.minutos("setup"))
        await self.ctx.sinalizar_evento(
            {"posto": self.posto.id, "evento": "setup", "op": cartao.get("op")}
        )

        estado = await self._ler_primeira_peca(cartao)
        cotas = await self._garantir_cotas(cartao, estado)
        if not cotas:
            return False

        if self.sorteio("prob_duplo_clique"):
            # Abandonar o popup sem enviar: a OP tem de continuar sem liberar o
            # lote, e o operador volta a ele depois (seção 19).
            self.ctx.telemetry.registrar_evento(
                operator=self.posto.cracha,
                resource=self.posto.recurso,
                sector=self.posto.setor,
                op=str(cartao.get("op") or ""),
                action="erro_humano_abandono_do_popup",
                result="checklist aberto e fechado sem envio",
                severity=SEV_INFO,
            )
            await self.esperar(self.minutos("pausa_entre_jobs"))

        caso = CASOS_COTA[self.ctx.contadores.get("casos_cota", 0) % len(CASOS_COTA)]
        self.ctx.incrementar("casos_cota")
        if caso in FORA_DA_FAIXA and not self.sorteio("prob_primeira_peca_nao_conforme"):
            caso = "dentro"
        medidas = self._montar_medidas(cotas, caso)
        destino = (
            "REFUGO"
            if caso in FORA_DA_FAIXA and self.sorteio("prob_destino_refugo")
            else "RETRABALHO"
        )
        payload = {
            **self._payload_base(cartao),
            "action": "checklist",
            "measures": medidas,
            "note": f"Simulação — caso de cota '{caso}'.",
        }
        if caso in FORA_DA_FAIXA:
            payload["destination"] = destino
            if destino == "REFUGO":
                payload["badge"] = self.ctx.config.autorizador_cracha
        resposta = await self.sessao.call(
            "POST",
            "/operator/first-piece",
            json=payload,
            action="primeira_peca_checklist",
            op=str(cartao.get("op") or ""),
            expect=(
                "primeira_peca_bloqueada",
                "primeira_peca_setup_pendente",
                "primeira_peca_checklist_ausente",
            ),
        )
        await self.ctx.sinalizar_evento(
            {"posto": self.posto.id, "evento": "checklist", "op": cartao.get("op"), "caso": caso}
        )
        if not resposta.ok:
            return False

        dados = resposta.data if isinstance(resposta.data, dict) else {}
        conforme = bool((dados.get("data") or {}).get("conforme", caso not in FORA_DA_FAIXA))
        if not conforme:
            if destino == "REFUGO":
                self.state.refugos += 1
                await self.esperar(self.minutos("primeira_peca"))
                if not await self._reinspecionar(cartao, cotas):
                    return False
            else:
                self.state.retrabalhos += 1
                if not await self._desbloquear_e_reinspecionar(cartao, cotas=cotas):
                    return False

        # 3) Retomada automática pela transição canônica "Retornar" (Wave 6B).
        retorno = await self.acao(
            "Retornar", cartao, expect=("transicao_invalida",), rotulo="retomada_apos_checklist"
        )
        if retorno.ok:
            self.marcar("producao", "produzindo (lote liberado)", proxima="finalizar")
            return True
        # Já pode estar em produção se o portão devolveu antes; confirma pela API.
        return True

    async def _ler_primeira_peca(self, cartao: dict) -> dict:
        payload = self._payload_base(cartao)
        params = {"op": payload["op"], "resource": self.posto.recurso}
        if "operation_id" in payload:
            params["operation_id"] = payload["operation_id"]
        resposta = await self.sessao.call(
            "GET",
            "/operator/first-piece",
            params=params,
            action="ler_primeira_peca",
            op=payload["op"],
        )
        return resposta.data if resposta.ok and isinstance(resposta.data, dict) else {}

    async def _garantir_cotas(self, cartao: dict, estado: dict) -> list[dict]:
        checklist = (estado or {}).get("checklist") or {}
        cotas = ((checklist.get("template") or {}).get("cotas")) or []
        if cotas:
            return list(cotas)
        produto = str(checklist.get("produto") or cartao.get("product") or "").strip()
        if not produto or produto in self.ctx.templates_criados:
            return []
        # Cadastro do padrão de cotas pelo mesmo editor que a Qualidade usa.
        if not await self._cadastrar_template(produto):
            return []
        estado = await self._ler_primeira_peca(cartao)
        checklist = (estado or {}).get("checklist") or {}
        return list(((checklist.get("template") or {}).get("cotas")) or [])

    async def _cadastrar_template(self, produto: str) -> bool:
        """Cadastra as cotas padrão do produto pelo editor da própria Qualidade."""

        criado = await self.sessao.call(
            "POST",
            "/quality/templates",
            json={"produto": produto, "cotas": [dict(item) for item in COTAS_PADRAO]},
            action="cadastro_template_qualidade",
            expect=("quality_sector_unavailable", "qualidade_template_protegido"),
        )
        if not criado.ok:
            return False
        self.ctx.templates_criados.add(produto)
        return True

    def _montar_medidas(self, cotas: list[dict], caso: str) -> list[dict]:
        """Medidas do caso pedido, com o status que o backend deve calcular.

        O ``status`` vai junto de propósito: a inspeção dimensional o exige no
        contrato, o backend o recalcula quando o padrão é numérico, e a
        divergência entre o que o simulador previu e o que o Gestor decidiu é
        justamente o que expõe um defeito na conta de conformidade.
        """

        medidas = []
        for indice, cota in enumerate(cotas):
            sequencia = int(cota.get("sequencia") or indice + 1)
            faixa = parse_padrao(cota.get("padrao"))
            if faixa is None:
                medidas.append(
                    {"sequencia": sequencia, "medida": str(cota.get("padrao") or "0"),
                     "status": "CONFORME"}
                )
                continue
            referencia, margem = faixa
            passo = margem if margem > 0 else Decimal("0.5")
            # Só a primeira cota recebe o caso sorteado: uma peça com várias
            # cotas fora da faixa não distingue qual regra foi exercitada.
            caso_da_cota = caso if indice == 0 else "dentro"
            alvo = {
                "dentro": referencia,
                "limite_inferior": referencia - margem,
                "limite_superior": referencia + margem,
                "abaixo": referencia - margem - passo,
                "acima": referencia + margem + passo,
            }[caso_da_cota]
            medidas.append(
                {
                    "sequencia": sequencia,
                    "medida": f"{alvo}",
                    "status": "NAO_CONFORME" if caso_da_cota in FORA_DA_FAIXA else "CONFORME",
                }
            )
        return medidas

    async def _desbloquear_e_reinspecionar(
        self, cartao: dict, cotas: list[dict] | None = None
    ) -> bool:
        """Retrabalho da primeira peça: bloqueio, crachás recusados e liberação."""

        payload = self._payload_base(cartao)
        op = payload["op"]
        # Produzir com a OP bloqueada precisa ser recusado.
        bloqueado = await self.acao(
            "Início", cartao, expect=("primeira_peca_bloqueada", "transicao_invalida"),
            rotulo="tentativa_producao_bloqueada",
        )
        if not bloqueado.ok:
            self.state.bloqueios_esperados += 1

        for cracha, rotulo in (
            (self.ctx.config.cracha_invalido, "autorizacao_cracha_inexistente"),
            ("SIM00", "autorizacao_cracha_sem_permissao"),
        ):
            recusa = await self.sessao.call(
                "POST",
                "/operator/first-piece",
                json={**payload, "action": "autorizar", "badge": cracha},
                action=rotulo,
                op=op,
                expect=(
                    "primeira_peca_cracha_invalido",
                    "primeira_peca_responsavel_nao_autorizado",
                    "cracha_invalido",
                    "primeira_peca_autorizacao_invalida",
                    "primeira_peca_sem_bloqueio",
                ),
            )
            if not recusa.ok:
                self.state.bloqueios_esperados += 1

        liberacao = await self.sessao.call(
            "POST",
            "/operator/first-piece",
            json={
                **payload,
                "action": "autorizar",
                "badge": self.ctx.config.autorizador_cracha,
                "note": "Simulação — responsável liberou o retrabalho da primeira peça.",
            },
            action="autorizacao_responsavel",
            op=op,
            expect=("primeira_peca_sem_bloqueio",),
        )
        if not liberacao.ok:
            return False
        await self.esperar(self.minutos("retrabalho"))
        return await self._reinspecionar(cartao, cotas)

    async def _reinspecionar(self, cartao: dict, cotas: list[dict] | None) -> bool:
        payload = self._payload_base(cartao)
        op = payload["op"]
        if self.caldeiraria:
            if not cotas:
                estado = await self._ler_primeira_peca(cartao)
                cotas = await self._garantir_cotas(cartao, estado)
            if not cotas:
                return False
            resposta = await self.sessao.call(
                "POST",
                "/operator/first-piece",
                json={
                    **payload,
                    "action": "checklist",
                    "measures": self._montar_medidas(cotas, "dentro"),
                    "note": "Simulação — reinspeção após retrabalho/refugo.",
                },
                action="primeira_peca_reinspecao",
                op=op,
                expect=("primeira_peca_bloqueada", "primeira_peca_setup_pendente"),
            )
            return resposta.ok
        await self.sessao.call(
            "POST",
            "/operator/first-piece",
            json={**payload, "action": "produzida"},
            action="primeira_peca_produzida_novamente",
            op=op,
            expect=("primeira_peca_ja_produzida",),
        )
        resposta = await self.sessao.call(
            "POST",
            "/operator/first-piece",
            json={**payload, "action": "inspecionar", "result": "CONFORME",
                  "note": "Simulação — reinspeção aprovada."},
            action="primeira_peca_reinspecao",
            op=op,
            expect=("primeira_peca_bloqueada",),
        )
        return resposta.ok

    # ------------------------------------------------------------------
    # Inspeção dimensional da Qualidade — a operação INSPECAO do roteiro
    # ------------------------------------------------------------------
    async def inspecao_dimensional(self) -> bool:
        """Executa a inspeção dimensional de uma OP da fila do próprio setor.

        A Qualidade não é um posto separado nem um perfil novo: é a operação
        ``INSPECAO`` do roteiro, medida peça a peça pelo mesmo setor que
        produziu a peça. Por isso o fluxo vive aqui e só existe na Caldeiraria
        (Dobra, Usinagem e Serra) — Corte, Solda e Pintura não possuem a aba.

        O posto só puxa a fila quando está livre, antes de começar uma OP nova:
        a inspeção é o que destrava a etapa seguinte do roteiro, e o operador
        que acabou de produzir é quem a executa.

        Devolve ``True`` quando a inspeção consumiu o ciclo do posto.
        """

        if not self.caldeiraria or self.encerrando():
            return False
        if not self.sorteio("prob_inspecao_qualidade"):
            return False
        item = await self._proxima_da_fila_qualidade()
        if item is None:
            return False
        op = str(item.get("op") or "")
        # Mesma trava dos postos: duas pessoas medindo a mesma OP disputariam a
        # sequência de peças, e o conflito seria do simulador, não do Gestor.
        self.ctx.ops_em_uso.add(op)
        self.marcar(
            "inspecao",
            "inspeção dimensional na fila da Qualidade",
            proxima="medir as cotas peça a peça",
            op=op,
            produto=str(item.get("produto") or ""),
            operacao=str(item.get("operacao") or ""),
            ocioso=False,
        )
        try:
            await self._executar_inspecao(op)
        finally:
            self.ctx.ops_em_uso.discard(op)
            self.marcar("ocioso", "entre trabalhos", proxima="ler a fila",
                        op="", produto="", operacao="", ocioso=True)
            await self.esperar(self.minutos("pausa_entre_jobs"))
        return True

    async def _proxima_da_fila_qualidade(self) -> dict | None:
        resposta = await self.sessao.call(
            "GET",
            "/quality/queue",
            action="ler_fila_qualidade",
            expect=("quality_sector_unavailable",),
        )
        if not resposta.ok or not isinstance(resposta.data, dict):
            return None
        for item in resposta.data.get("items") or ():
            op = str(item.get("op") or "")
            if op and op not in self.ctx.ops_em_uso:
                return dict(item)
        return None

    @staticmethod
    def _estado_da_inspecao(resposta: ApiResponse) -> dict:
        """Extrai o estado da inspeção da envelopagem padrão do roteador."""

        dados = resposta.data if isinstance(resposta.data, dict) else {}
        return dict(dados.get("data") or {})

    async def _executar_inspecao(self, op: str) -> None:
        abertura = await self.sessao.call(
            "POST",
            "/quality/inspections",
            json={"op": op},
            action="abrir_inspecao_qualidade",
            op=op,
            expect=(
                "qualidade_op_nao_elegivel",
                "qualidade_op_outro_setor",
                "qualidade_operacao_inexistente",
                "qualidade_inspecao_concluida",
                "operator_resource_occupied",
                "operacao_ativa_diferente",
            ),
        )
        if not abertura.ok:
            self.state.bloqueios_esperados += 1
            return
        estado = self._estado_da_inspecao(abertura)
        inspecao_id = int(estado.get("id") or 0)
        if not inspecao_id:
            return
        cotas = await self._cotas_da_inspecao(estado, inspecao_id, op)
        if not cotas:
            return

        self.ctx.incrementar("inspecoes_qualidade")
        await self.ctx.sinalizar_evento(
            {"posto": self.posto.id, "evento": "inspecao_qualidade", "op": op}
        )
        total = int(estado.get("quantidade_total") or 0)
        proxima = estado.get("peca_atual")
        erro_humano = self.sorteio("prob_erro_humano")
        while proxima and not self.encerrando():
            numero = int(proxima)
            self.marcar(
                "inspecao",
                f"medindo cotas da peça {numero} de {total}",
                proxima="registrar a peça inspecionada",
            )
            await self.esperar(self.minutos("inspecao_peca"))
            estado = await self._registrar_peca_inspecionada(
                inspecao_id, numero, total, cotas, op,
                erro_humano=erro_humano and numero == 1,
            )
            if estado is None:
                break
            proxima = estado.get("peca_atual")
        await self._fechar_inspecao(inspecao_id, op)

    async def _cotas_da_inspecao(self, estado: dict, inspecao_id: int, op: str) -> list[dict]:
        """Cotas do template do produto, cadastrando-as se o produto ainda não tem."""

        cotas = list(((estado.get("template") or {}).get("cotas")) or [])
        if cotas:
            return cotas
        produto = str(estado.get("produto") or "").strip()
        if not produto or produto in self.ctx.templates_criados:
            return []
        if not await self._cadastrar_template(produto):
            return []
        releitura = await self.sessao.call(
            "GET",
            f"/quality/inspections/{inspecao_id}",
            action="ler_inspecao_qualidade",
            op=op,
            expect=("quality_inspection_not_found",),
        )
        if not releitura.ok or not isinstance(releitura.data, dict):
            return []
        return list(((releitura.data.get("template") or {}).get("cotas")) or [])

    async def _registrar_peca_inspecionada(
        self,
        inspecao_id: int,
        numero: int,
        total: int,
        cotas: list[dict],
        op: str,
        *,
        erro_humano: bool = False,
    ) -> dict | None:
        """Mede uma unidade contra o template; abre RNC quando reprova.

        Devolve o estado seguinte da inspeção, ou ``None`` quando a inspeção
        não pode continuar (recusa do Gestor ou última peça já fechada).
        """

        caso = CASOS_COTA[self.ctx.contadores.get("casos_cota_inspecao", 0) % len(CASOS_COTA)]
        self.ctx.incrementar("casos_cota_inspecao")
        if caso in FORA_DA_FAIXA and not self.sorteio("prob_inspecao_nao_conforme"):
            caso = "dentro"
        nao_conforme = caso in FORA_DA_FAIXA
        medidas = self._montar_medidas(cotas, caso)
        destino = (
            "Refugo" if self.sorteio("prob_destino_refugo") else "Retrabalho"
        )
        payload: dict[str, Any] = {
            "numero_peca": numero,
            "resultado": destino if nao_conforme else "Aprovada",
            "medidas": medidas,
            "badges": self.crachas(),
        }
        if nao_conforme:
            # RNC é obrigatória antes de concluir a peça: sem ela o Gestor tem
            # de recusar a gravação, e é isso que o erro humano abaixo prova.
            payload["rnc"] = {
                "motivo": f"Simulação — cota fora do padrão dimensional (caso '{caso}').",
                "observacao": "RNC aberta pelo operador durante a inspeção dimensional.",
            }

        if erro_humano:
            await self._erro_humano_na_peca(inspecao_id, numero, total, medidas, op, nao_conforme)

        resposta = await self.sessao.call(
            "POST",
            f"/quality/inspections/{inspecao_id}/pieces",
            json=payload,
            action="registrar_peca_inspecionada",
            op=op,
            expect=(
                "qualidade_sequencia_peca",
                "qualidade_inspecao_concluida",
                "qualidade_inspecao_completa",
                "qualidade_peca_duplicada",
                "qualidade_retrabalho_sem_operacao_anterior",
            ),
        )
        if not resposta.ok:
            self.state.bloqueios_esperados += 1
            return None
        self.ctx.incrementar("pecas_inspecionadas")
        if nao_conforme:
            self.ctx.incrementar("rnc_qualidade")
            if destino == "Refugo":
                self.state.refugos += 1
            else:
                self.state.retrabalhos += 1
            await self.ctx.sinalizar_evento(
                {"posto": self.posto.id, "evento": "rnc_qualidade", "op": op, "peca": numero}
            )
        return self._estado_da_inspecao(resposta)

    async def _erro_humano_na_peca(
        self,
        inspecao_id: int,
        numero: int,
        total: int,
        medidas: list[dict],
        op: str,
        nao_conforme: bool,
    ) -> None:
        """Os dois enganos que a inspeção tem de recusar antes de gravar."""

        if nao_conforme:
            # Aprovar uma peça com cota fora da faixa (e sem RNC) é o engano que
            # a regra existe para impedir.
            recusa = await self.sessao.call(
                "POST",
                f"/quality/inspections/{inspecao_id}/pieces",
                json={
                    "numero_peca": numero,
                    "resultado": "Aprovada",
                    "medidas": medidas,
                    "badges": self.crachas(),
                },
                action="erro_humano_aprovar_peca_nao_conforme",
                op=op,
                expect=("qualidade_aprovacao_nao_conforme", "qualidade_rnc_obrigatoria"),
            )
            if not recusa.ok:
                self.state.bloqueios_esperados += 1
            return
        fora_de_ordem = numero + max(1, total - numero)
        recusa = await self.sessao.call(
            "POST",
            f"/quality/inspections/{inspecao_id}/pieces",
            json={
                "numero_peca": fora_de_ordem,
                "resultado": "Aprovada",
                "medidas": medidas,
                "badges": self.crachas(),
            },
            action="erro_humano_peca_fora_de_sequencia",
            op=op,
            expect=("qualidade_sequencia_peca", "qualidade_inspecao_completa"),
        )
        if not recusa.ok:
            self.state.bloqueios_esperados += 1

    async def _fechar_inspecao(self, inspecao_id: int, op: str) -> None:
        """Fecha a inspeção — ou confirma que a última peça já a fechou.

        Registrar a última unidade encerra a inspeção pelo fluxo canônico. O
        ``finish`` continua sendo o caminho de quem voltou à tela com a última
        peça já gravada, e o duplo clique no botão precisa ser recusado.
        """

        leitura = await self.sessao.call(
            "GET",
            f"/quality/inspections/{inspecao_id}",
            action="ler_inspecao_qualidade",
            op=op,
            expect=("quality_inspection_not_found",),
        )
        dados = leitura.data if leitura.ok and isinstance(leitura.data, dict) else {}
        aberta = str(dados.get("status") or "") == "EM_INSPECAO"
        if not aberta:
            self.ctx.incrementar("inspecoes_concluidas")
            if not self.sorteio("prob_duplo_clique"):
                return
        fechamento = await self.sessao.call(
            "POST",
            f"/quality/inspections/{inspecao_id}/finish",
            json={"badges": self.crachas()},
            action=(
                "finalizar_inspecao_qualidade"
                if aberta
                else "erro_humano_finalizar_inspecao_concluida"
            ),
            op=op,
            expect=(
                "qualidade_inspecao_concluida",
                "qualidade_inspecao_incompleta",
                "qualidade_cracha_obrigatorio",
            ),
        )
        if fechamento.ok:
            self.ctx.incrementar("inspecoes_concluidas")
        else:
            self.state.bloqueios_esperados += 1

    # ------------------------------------------------------------------
    async def produzir(self, cartao: dict) -> None:
        classe = self._classe_do_job()
        restante = self.minutos(classe)
        self.marcar("producao", f"produzindo ({classe})", proxima="finalizar a OP")
        while restante > 0 and not self.encerrando():
            fatia = min(restante, self.rng.uniform(6.0, 18.0))
            await self.esperar(fatia)
            restante -= fatia
            if restante <= 0:
                break
            if self.sorteio("prob_parada"):
                await self._parar_e_retomar(cartao)
            elif self.sorteio("prob_retrabalho_posterior"):
                await self._retrabalho_posterior(cartao)
            elif self.sorteio("prob_setup_extra") and self.caldeiraria:
                await self._setup_extra(cartao)

    def _classe_do_job(self) -> str:
        if self.posto.setor == "Solda":
            return "soldado"
        if self.posto.setor == "Pintura":
            return "pintura"
        return self.rng.choices(
            ["simples", "comum", "complexa"], weights=[0.35, 0.45, 0.20], k=1
        )[0]

    async def _parar_e_retomar(self, cartao: dict) -> None:
        planejada = self.sorteio("prob_parada_planejada")
        motivo = self.escolher_motivo(planejado=planejada)
        if not motivo:
            return
        comentario = (
            "Simulação — parada planejada do turno."
            if planejada
            else "Simulação — interrupção não planejada do posto."
        )
        parada = await self.acao(
            "Parada",
            cartao,
            extra={"stop_reason_code": motivo.get("codigo"), "comment": comentario},
            expect=("transicao_invalida", "comentario_obrigatorio", "motivo_parada_invalido"),
        )
        if not parada.ok:
            return
        self.state.paradas += 1
        self.marcar(
            "parada",
            f"parada {'planejada' if planejada else 'não planejada'}: {motivo.get('nome')}",
            proxima="retomar",
        )
        await self.ctx.sinalizar_evento(
            {"posto": self.posto.id, "evento": "parada", "op": cartao.get("op"),
             "planejada": planejada}
        )
        await self.esperar(
            self.minutos("parada_longa" if not planejada else "parada_curta")
        )
        if self.sorteio("prob_erro_humano"):
            # Retomada incompatível: pedir "Retornar" estando em Parada.
            incompativel = await self.acao(
                "Retornar", cartao, expect=("transicao_invalida",),
                rotulo="erro_humano_retomada_incompativel",
            )
            if not incompativel.ok:
                self.state.bloqueios_esperados += 1
        retomada = await self.acao("Retomar", cartao, expect=("transicao_invalida",))
        if retomada.ok:
            self.marcar("producao", "produzindo após retomada", proxima="finalizar a OP")
            await self.ctx.sinalizar_evento(
                {"posto": self.posto.id, "evento": "retomada", "op": cartao.get("op")}
            )

    async def _retrabalho_posterior(self, cartao: dict) -> None:
        entrada = await self.acao("Retrabalho", cartao, expect=("transicao_invalida",))
        if not entrada.ok:
            return
        self.state.retrabalhos += 1
        self.marcar("retrabalho", "retrabalho de peça do lote", proxima="voltar a produzir")
        await self.ctx.sinalizar_evento(
            {"posto": self.posto.id, "evento": "retrabalho", "op": cartao.get("op")}
        )
        await self.esperar(self.minutos("retrabalho"))
        # Retrabalho volta a produzir por Parada→Retomar (transição canônica).
        motivo = self.escolher_motivo(planejado=False)
        if motivo:
            parada = await self.acao(
                "Parada",
                cartao,
                extra={
                    "stop_reason_code": motivo.get("codigo"),
                    "comment": "Simulação — conferência após retrabalho.",
                },
                expect=("transicao_invalida", "comentario_obrigatorio"),
            )
            if parada.ok:
                await self.esperar(self.minutos("parada_curta"))
                await self.acao("Retomar", cartao, expect=("transicao_invalida",))
        self.marcar("producao", "produzindo após retrabalho", proxima="finalizar a OP")

    async def _setup_extra(self, cartao: dict) -> None:
        setup = await self.acao(
            "Setup", cartao, extra={"setup_type": "Ajuste de ferramenta"},
            expect=("transicao_invalida", "setup_indisponivel_setor"),
        )
        if not setup.ok:
            return
        self.marcar("setup", "ajuste de ferramenta", proxima="voltar a produzir")
        await self.esperar(self.minutos("setup") * 0.6)
        await self.acao("Retornar", cartao, expect=("transicao_invalida",))
        self.marcar("producao", "produzindo após ajuste", proxima="finalizar a OP")

    # ------------------------------------------------------------------
    async def encerrar_job(self, cartao: dict, *, adotado: bool = False) -> None:
        planejado = int(cartao.get("qty") or cartao.get("quantidade") or 0)
        boas_anteriores = int(cartao.get("good") or 0)
        refugo_anterior = int(cartao.get("scrap") or 0)
        saldo = max(0, planejado - boas_anteriores - refugo_anterior)
        if saldo <= 0:
            saldo = max(1, planejado or 1)

        parcial = self.sorteio("prob_finalizacao_parcial") and saldo > 2
        alvo = self.rng.randint(1, max(1, saldo - 1)) if parcial else saldo
        refugo = 0
        if self.sorteio("prob_refugo") and alvo > 1:
            refugo = self.rng.randint(1, max(1, alvo // 4))
        boas = max(0, alvo - refugo)
        if boas + refugo <= 0:
            boas = 1

        extra: dict[str, Any] = {
            "badges": self.crachas(),
            "good": boas,
            "scrap": refugo,
            "lot": f"LOTE-{self.clock.now():%Y%m%d}-{self.posto.id.upper()}",
        }
        if refugo:
            extra["scrap_reason"] = "Simulação — peça fora do padrão dimensional."
            extra["root_cause"] = "Simulação — desgaste de ferramenta."
            extra["scrap_authorization_badge"] = self.ctx.config.autorizador_cracha

        # Erro humano: crachá inexistente na finalização (seção 19).
        if self.sorteio("prob_erro_humano"):
            recusa = await self.acao(
                "Finalizado",
                cartao,
                extra={**extra, "badges": [self.ctx.config.cracha_invalido]},
                expect=("cracha_invalido",),
                rotulo="erro_humano_cracha_invalido_finalizacao",
            )
            if not recusa.ok:
                self.state.bloqueios_esperados += 1

        resposta = await self.acao(
            "Finalizado",
            cartao,
            extra=extra,
            expect=(
                "primeira_peca_gate_obrigatorio",
                "primeira_peca_setup_pendente",
                "primeira_peca_inspecao_pendente",
                "primeira_peca_bloqueada",
                "quantidade_inconsistente",
                "transicao_invalida",
            ),
        )
        if resposta.ok:
            dados = resposta.data if isinstance(resposta.data, dict) else {}
            if str(dados.get("code") or "") == "finalizacao_parcial":
                self.state.jobs_parciais += 1
            else:
                self.state.jobs_concluidos += 1
            if refugo:
                self.state.refugos += refugo
            await self.ctx.sinalizar_evento(
                {"posto": self.posto.id, "evento": "finalizacao", "op": cartao.get("op"),
                 "parcial": str(dados.get("code") or "") == "finalizacao_parcial"}
            )
        else:
            self.state.bloqueios_esperados += 1
        self.marcar("ocioso", "entre trabalhos", proxima="ler a fila",
                    op="", produto="", operacao="", ocioso=True)


class PostoCorte(BasePosto):
    """Fila automática do Corte: tarefa → programa → nesting → chapa."""

    async def abrir_posto(self) -> None:
        self.marcar("abrindo", "abrindo o posto de Corte", proxima="ler a fila", ocioso=True)
        await self.sessao.call("GET", "/operator/context", action="abrir_posto")
        await self.sessao.call(
            "GET",
            "/cutting/queue",
            params={"resource": self.posto.recurso},
            action="ler_fila_corte",
        )

    async def ciclo(self) -> None:
        if not await self.respeitar_ocupacao():
            return
        fila = await self._ler_fila()
        if fila is None:
            await self.esperar(self.minutos("pausa_entre_jobs"))
            return
        ativo = next((item for item in fila if item.get("status") == "Em processo"), None)
        if ativo is not None:
            await self._concluir_nesting(ativo)
            return
        aguardando = [item for item in fila if item.get("status") == "Aguardando"]
        if not aguardando:
            await self._sem_demanda()
            return
        tarefa = aguardando[0] if not self.sorteio("prob_troca_op") else self.rng.choice(
            aguardando[: min(6, len(aguardando))]
        )
        await self._iniciar_nesting(tarefa)

    async def _ler_fila(self) -> list[dict] | None:
        resposta = await self.sessao.call(
            "GET",
            "/cutting/queue",
            params={"resource": self.posto.recurso},
            action="ler_fila_corte",
        )
        if not resposta.ok or not isinstance(resposta.data, dict):
            return None
        return list(resposta.data.get("items") or [])

    async def _sem_demanda(self) -> None:
        self.marcar("sem_op", "sem tarefa liberada", proxima="aguardar planejamento", ocioso=True)
        if self.rng.random() < 0.2:
            # Exercita o botão Atualizar: o SigmaNEST está fora de alcance nesta
            # estação e a falha precisa aparecer como indisponibilidade tratada.
            await self.sessao.call(
                "POST",
                "/cutting/sync",
                params={"resource": self.posto.recurso},
                action="sincronizar_corte",
                expect=("cutting_sync_unavailable",),
            )
        await self.esperar(self.minutos("pausa_entre_jobs"))

    async def _iniciar_nesting(self, tarefa: dict) -> None:
        hashes = list(tarefa.get("plano_hashes_aguardando") or tarefa.get("plano_hashes") or [])
        if not hashes:
            await self.esperar(self.minutos("pausa_entre_jobs"))
            return
        plano = hashes[0]
        self.marcar(
            "iniciando",
            f"iniciando nesting {tarefa.get('nesting_atual') or ''}",
            proxima="cortar as chapas",
            op=str(tarefa.get("codigo_tarefa") or ""),
            produto=str(tarefa.get("material") or ""),
            operacao=str(tarefa.get("programa_atual") or tarefa.get("programa") or ""),
            ocioso=False,
        )
        resposta = await self.sessao.call(
            "POST",
            "/cutting/actions",
            json={"action": "Início", "resource": self.posto.recurso, "plan_hash": plano},
            action="corte_inicio",
            op=str(tarefa.get("codigo_tarefa") or ""),
            expect=("plano_indisponivel", "estado_alterado"),
        )
        if not resposta.ok:
            self.state.bloqueios_esperados += 1
            await self.esperar(self.minutos("pausa_entre_jobs"))
            return
        self.marcar("producao", "cortando", proxima="finalizar o nesting")
        await self.ctx.sinalizar_evento(
            {"posto": self.posto.id, "evento": "inicio", "op": tarefa.get("codigo_tarefa")}
        )

    async def _concluir_nesting(self, tarefa: dict) -> None:
        chapas = int(tarefa.get("quantidade_chapas") or 1)
        self.marcar(
            "producao",
            f"cortando ({tarefa.get('nestings_concluidos', 0)}/{chapas} chapas)",
            proxima="finalizar o nesting",
            op=str(tarefa.get("codigo_tarefa") or ""),
            produto=str(tarefa.get("material") or ""),
            ocioso=False,
        )
        await self.esperar(self.minutos("corte_nesting"))
        if self.sorteio("prob_parada"):
            planejada = self.sorteio("prob_parada_planejada")
            motivo = (
                self.rng.choice(self.ctx.motivos_planejados)
                if planejada and self.ctx.motivos_planejados
                else (self.rng.choice(self.ctx.motivos_nao_planejados)
                      if self.ctx.motivos_nao_planejados else None)
            )
            if motivo:
                parada = await self.sessao.call(
                    "POST",
                    "/cutting/actions",
                    json={
                        "action": "Parada",
                        "resource": self.posto.recurso,
                        "stop_reason_code": motivo.get("codigo"),
                        "comment": "Simulação — interrupção do corte.",
                    },
                    action="corte_parada",
                    expect=("ja_parado", "motivo_invalido", "comentario_obrigatorio"),
                )
                if parada.ok:
                    self.state.paradas += 1
                    self.marcar("parada", f"parada: {motivo.get('nome')}", proxima="retomar")
                    await self.ctx.sinalizar_evento(
                        {"posto": self.posto.id, "evento": "parada",
                         "op": tarefa.get("codigo_tarefa"), "planejada": planejada}
                    )
                    await self.esperar(self.minutos("parada_curta"))
                    await self.sessao.call(
                        "POST",
                        "/cutting/actions",
                        json={"action": "Retomada", "resource": self.posto.recurso},
                        action="corte_retomada",
                        expect=("nao_parado", "sem_corte_ativo", "fora_turno_nao_retomavel"),
                    )
                    self.marcar("producao", "cortando após retomada", proxima="finalizar o nesting")

        ativos = list(tarefa.get("apontamento_ids_em_processo") or [])
        if not ativos:
            ativos = list(tarefa.get("apontamento_ids") or [])
        if not ativos:
            return
        resposta = await self.sessao.call(
            "POST",
            "/cutting/actions",
            json={
                "action": "Finalizado",
                "resource": self.posto.recurso,
                "appointment_id": int(ativos[0]),
            },
            action="corte_finalizacao",
            op=str(tarefa.get("codigo_tarefa") or ""),
            expect=("estado_alterado",),
        )
        if resposta.ok:
            self.state.jobs_concluidos += 1
            await self.ctx.sinalizar_evento(
                {"posto": self.posto.id, "evento": "finalizacao",
                 "op": tarefa.get("codigo_tarefa")}
            )
        else:
            self.state.bloqueios_esperados += 1


class PostoDestaque(BasePosto):
    """Destaque: só o Laser libera chapa; o Plasma nunca entra nesta fila."""

    async def abrir_posto(self) -> None:
        self.marcar("abrindo", "abrindo o posto de Destaque", proxima="ler a fila", ocioso=True)
        await self.sessao.call("GET", "/operator/context", action="abrir_posto")

    async def ciclo(self) -> None:
        if not await self.respeitar_ocupacao():
            return
        resposta = await self.sessao.call(
            "GET", "/highlight/queue", action="ler_fila_destaque"
        )
        if not resposta.ok or not isinstance(resposta.data, dict):
            await self.esperar(self.minutos("pausa_entre_jobs"))
            return
        itens = list(resposta.data.get("items") or [])
        if not itens:
            self.marcar("sem_op", "sem tarefa disponível para destaque",
                        proxima="aguardar corte", ocioso=True)
            await self.esperar(self.minutos("pausa_entre_jobs"))
            return

        completas = [item for item in itens if item.get("situacao") == "COMPLETA"]
        parciais = [item for item in itens if item.get("situacao") == "PARCIAL"]
        # Erro humano deliberado: destacar a tarefa inteira ainda incompleta.
        if parciais and self.sorteio("prob_erro_humano"):
            alvo = parciais[0]
            recusa = await self.sessao.call(
                "POST",
                "/highlight/actions",
                json={"action": "Início", "task_code": alvo.get("codigo_tarefa")},
                action="erro_humano_destaque_tarefa_incompleta",
                op=str(alvo.get("codigo_tarefa") or ""),
                expect=("tarefa_corte_incompleto", "destaque_nao_liberado",
                        "tarefa_destaque_duplicada", "status_existente"),
            )
            if not recusa.ok:
                self.state.bloqueios_esperados += 1

        # "Disponível" na fila do Gestor é o plano que ainda tem trabalho, o que
        # inclui o que já está em 'inicio'. Para receber Início, porém, o escopo
        # precisa estar 'aguardando' ou 'parada' — apontar um plano já iniciado
        # devolve 409 status_existente para sempre. Escolher pelo critério da
        # fila prendia o posto no primeiro plano deixado aberto por outra
        # execução, e o Destaque nunca fechava um ciclo.
        def iniciaveis(item: dict) -> list[dict]:
            return [
                plano_item
                for plano_item in (item.get("planos") or [])
                if plano_item.get("status_corte") == "Finalizado"
                and str(plano_item.get("estado_destaque") or "aguardando")
                in {"aguardando", "parada"}
            ]

        alvo = next((item for item in completas + parciais if iniciaveis(item)), None)
        if alvo is None:
            self.marcar("sem_op", "nenhuma chapa liberada para destaque",
                        proxima="aguardar corte", ocioso=True)
            await self.esperar(self.minutos("pausa_entre_jobs"))
            return
        codigo = str(alvo.get("codigo_tarefa") or "")
        # A tarefa inteira só é escopo válido quando o Gestor ainda não a
        # colocou em execução; caso contrário o escopo legítimo é a chapa.
        escopo_tarefa = (
            alvo.get("situacao") == "COMPLETA"
            and str(alvo.get("status_tarefa") or "")
            not in {"Destacando", "Finalizado", "Despachado"}
        )
        plano = None if escopo_tarefa else iniciaveis(alvo)[0].get("plano_hash")

        self.marcar(
            "iniciando",
            "iniciando destaque",
            proxima="finalizar destaque",
            op=codigo,
            produto=str(alvo.get("material") or ""),
            operacao="chapa" if plano else "tarefa completa",
            ocioso=False,
        )
        inicio = await self.sessao.call(
            "POST",
            "/highlight/actions",
            json={"action": "Início", "task_code": codigo, "plan_hash": plano},
            action="destaque_inicio",
            op=codigo,
            expect=("status_existente", "destaque_nao_liberado", "plano_destaque_indisponivel",
                    "plano_destaque_duplicado", "tarefa_corte_incompleto"),
        )
        if not inicio.ok:
            self.state.bloqueios_esperados += 1
            await self.esperar(self.minutos("pausa_entre_jobs"))
            return
        self.marcar("producao", "destacando peças", proxima="finalizar destaque")
        await self.ctx.sinalizar_evento(
            {"posto": self.posto.id, "evento": "inicio", "op": codigo}
        )
        await self.esperar(self.minutos("destaque"))

        if self.sorteio("prob_parada") and self.ctx.motivos_nao_planejados:
            motivo = self.rng.choice(self.ctx.motivos_nao_planejados)
            parada = await self.sessao.call(
                "POST",
                "/highlight/actions",
                json={
                    "action": "Parada",
                    "task_code": codigo,
                    "stop_reason_code": motivo.get("codigo"),
                    "comment": "Simulação — interrupção do destaque.",
                },
                action="destaque_parada",
                op=codigo,
                expect=("status_invalido", "motivo_parada_invalido", "comentario_obrigatorio",
                        "recurso_ja_parado"),
            )
            if parada.ok:
                self.state.paradas += 1
                self.marcar("parada", f"parada: {motivo.get('nome')}", proxima="retomar")
                await self.esperar(self.minutos("parada_curta"))
                await self.sessao.call(
                    "POST",
                    "/highlight/actions",
                    json={"action": "Início", "task_code": codigo, "plan_hash": plano},
                    action="destaque_retomada",
                    op=codigo,
                    expect=("status_existente",),
                )
                self.marcar("producao", "destacando após retomada", proxima="finalizar destaque")

        # Crachá inexistente é recusa esperada no Fim do destaque.
        if self.sorteio("prob_erro_humano"):
            recusa = await self.sessao.call(
                "POST",
                "/highlight/actions",
                json={"action": "Fim", "task_code": codigo, "plan_hash": plano,
                      "badge": self.ctx.config.cracha_invalido},
                action="erro_humano_destaque_cracha_invalido",
                op=codigo,
                expect=("highlight_badge_invalid",),
            )
            if not recusa.ok:
                self.state.bloqueios_esperados += 1

        fim = await self.sessao.call(
            "POST",
            "/highlight/actions",
            json={"action": "Fim", "task_code": codigo, "plan_hash": plano,
                  "badge": self.posto.cracha},
            action="destaque_fim",
            op=codigo,
            expect=("status_invalido", "destaque_parado", "status_alterado",
                    "highlight_badge_invalid"),
        )
        if fim.ok:
            self.state.jobs_concluidos += 1
            await self.ctx.sinalizar_evento(
                {"posto": self.posto.id, "evento": "finalizacao", "op": codigo}
            )
        else:
            self.state.bloqueios_esperados += 1
        self.marcar("ocioso", "entre trabalhos", proxima="ler a fila",
                    op="", produto="", operacao="", ocioso=True)
        await self.esperar(self.minutos("pausa_entre_jobs"))
