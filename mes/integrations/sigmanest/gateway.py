"""Porta de leitura do planejamento SigmaNEST e correlação com a OP do TOTVS.

Fronteira obrigatória: nenhum consumidor do Gestor conhece tabelas, colunas ou
SQL do SigmaNEST. O domínio de apontamento não é tocado por este módulo — ele
apenas descreve planejamento.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from app.core.normalization import limpa_codigo
from mes.integrations.sigmanest.models import (
    SigmaNestCutPlan,
    SigmaNestPartLine,
    SigmaNestPlanningSnapshot,
)


class SigmaNestPlanningGateway(Protocol):
    """Contrato somente leitura do banco SigmaNEST."""

    def ler_planejamento(
        self,
        *,
        desde=None,
        tarefas: Iterable[str] | None = None,
    ) -> SigmaNestPlanningSnapshot:
        """Retorna tarefas/programas/nestings com suas peças, sem escrever nada."""


@dataclass(frozen=True)
class CorrelacaoOrdem:
    """Onde uma OP do TOTVS está sendo processada no Corte.

    Uma OP pode aparecer em vários nestings, e um nesting contém várias OPs.
    Por isso a correlação é uma lista de ocorrências, nunca um vínculo 1:1.
    """

    codigo_op: str
    ocorrencias: tuple[tuple[SigmaNestCutPlan, SigmaNestPartLine], ...] = ()

    @property
    def tarefas(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(plan.codigo_tarefa for plan, _ in self.ocorrencias))

    @property
    def programas(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(str(plan.program_name).strip() for plan, _ in self.ocorrencias)
        )

    @property
    def maquinas(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                str(plan.machine_name).strip()
                for plan, _ in self.ocorrencias
                if str(plan.machine_name or "").strip()
            )
        )

    @property
    def correlacionada(self) -> bool:
        return bool(self.ocorrencias)


class SigmaNestPlanningService:
    """Correlaciona planejamento SigmaNEST com as OPs já recebidas do TOTVS.

    O serviço nunca cria OP. Ele apenas responde, para OPs que já existem no
    catálogo canônico do Gestor, em qual tarefa/programa/nesting o produto
    daquela OP está sendo cortado.
    """

    def __init__(self, gateway: SigmaNestPlanningGateway):
        self.gateway = gateway

    def snapshot(self, *, desde=None, tarefas: Iterable[str] | None = None):
        return self.gateway.ler_planejamento(desde=desde, tarefas=tarefas)

    @staticmethod
    def correlacionar(
        snapshot: SigmaNestPlanningSnapshot,
        ordens_conhecidas: Iterable[str],
    ) -> tuple[dict[str, CorrelacaoOrdem], tuple[str, ...]]:
        """Liga peça→OP somente quando a OP já existe no domínio canônico.

        Retorna as correlações encontradas e a lista de OPs vistas no SigmaNEST
        que **não** existem no Gestor. Essas permanecem auditáveis e nunca são
        promovidas a OP nova: o TOTVS continua sendo a fonte da identidade.
        """

        conhecidas = {
            limpa_codigo(codigo)
            for codigo in ordens_conhecidas or ()
            if limpa_codigo(codigo)
        }
        encontradas: dict[str, list[tuple[SigmaNestCutPlan, SigmaNestPartLine]]] = {}
        desconhecidas: list[str] = []
        for plan in snapshot.plans:
            for part in plan.parts:
                codigo = part.codigo_op
                if not codigo:
                    continue
                if codigo not in conhecidas:
                    desconhecidas.append(codigo)
                    continue
                encontradas.setdefault(codigo, []).append((plan, part))
        return (
            {
                codigo: CorrelacaoOrdem(codigo, tuple(ocorrencias))
                for codigo, ocorrencias in encontradas.items()
            },
            tuple(dict.fromkeys(desconhecidas)),
        )
