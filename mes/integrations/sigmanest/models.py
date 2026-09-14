"""DTOs neutros do planejamento de Corte do SigmaNEST.

Modelo funcional comprovado na auditoria de 27/08/2026 (`SNDBase2026`):

```text
Tarefa (ProgArchive.TaskName)
  └─ Programa (ProgArchive.ProgramName) + Chapa (SheetName)   → o nesting
       └─ Linhas de peça (STPIPArc.PartName + WONumber)       → os produtos
```

Regra funcional obrigatória: **a OP pertence ao produto/peça**. Tarefa,
programa e nesting agrupam produtos e não possuem OP própria. Por isso a OP
(`WONumber`) só existe em :class:`SigmaNestPartLine`, nunca em
:class:`SigmaNestTask` nem em :class:`SigmaNestCutPlan`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


def _texto(valor) -> str:
    return str(valor if valor is not None else "").strip()


def _codigo(valor) -> str:
    """Normaliza identificador comparável sem alterar o conteúdo real.

    A auditoria mostrou `WONumber` sem espaços nas bordas, porém com 65 linhas
    em caixa baixa. A comparação é feita em maiúsculas, do mesmo modo que
    ``app.core.normalization.limpa_codigo`` já faz no restante do Gestor.
    """

    return _texto(valor).upper()


# Regra funcional confirmada de roteamento pós-Corte. Os campos de processo do
# SigmaNEST foram mapeados por comprovação direta em 958 linhas reais
# (100% de igualdade contra o histórico já gravado no Gestor):
#
#     Part.Data3 → DOBRA      Part.Data5 → SOLDA
#     Part.Data4 → USINAGEM   Part.Data6 → CHANFRO
#
# ``Data1`` é texto livre de categoria e ``Data2`` permanece sem semântica
# confirmada; nenhum dos dois participa do roteamento.
SETOR_DESTINO_DOBRA = "Aguardando Dobra"
SETOR_DESTINO_USINAGEM = "Aguardando Usinagem"
SETOR_DESTINO_PADRAO = "Almoxarifado"


def _afirmativo(valor) -> bool:
    return _texto(valor).upper() == "SIM"


@dataclass(frozen=True)
class SigmaNestPartLine:
    """Uma peça/produto dentro de um nesting. **É aqui que a OP existe.**"""

    program_name: str
    sheet_name: str
    part_name: str
    wo_number: str
    qty_in_process: int = 0
    master_part_qty: int = 0
    cutting_time_seconds: float | None = None
    true_area: float | None = None
    trans_type: str = ""
    material: str = ""
    thickness: float | None = None
    dobra: str = ""
    usinagem: str = ""
    solda: str = ""
    chanfro: str = ""

    @property
    def setor_destino(self) -> str:
        """Destino da peça após o Corte, pela regra canônica já validada."""

        if _afirmativo(self.dobra):
            return SETOR_DESTINO_DOBRA
        if _afirmativo(self.usinagem):
            return SETOR_DESTINO_USINAGEM
        return SETOR_DESTINO_PADRAO

    @property
    def quantidade(self) -> int:
        """Peças da chapa. ``MasterPartQty`` é constante entre os TransType."""

        return max(0, int(self.master_part_qty or self.qty_in_process or 0))

    @property
    def codigo_op(self) -> str:
        """Identidade correlacionável com `catalogo_pcp_ops.codigo_op`.

        Comprovado por dados reais: `Wo.WONumber` é textualmente igual a
        `ProductionOrder.Number` do TOTVS.
        """

        return _codigo(self.wo_number)

    @property
    def produto_codigo(self) -> str:
        """Produto observado no SigmaNEST.

        **Não é chave de correlação.** Em 13,3% das linhas auditadas o código do
        SigmaNEST é um prefixo do código do Protheus (sufixo corporativo
        ausente). Serve para conferência e diagnóstico, nunca para o vínculo.
        """

        return _texto(self.part_name)


@dataclass(frozen=True)
class SigmaNestCutPlan:
    """Um nesting: programa + chapa dentro de uma tarefa."""

    task_name: str
    program_name: str
    sheet_name: str
    machine_name: str
    repeat_id: int | None = None
    archive_packet_id: int | None = None
    used_area: float | None = None
    scrap_fraction: float | None = None
    cutting_time_seconds: float | None = None
    posted_at: datetime | None = None
    completed_at: datetime | None = None
    trans_type: str = ""
    parts: tuple[SigmaNestPartLine, ...] = ()

    @property
    def codigo_tarefa(self) -> str:
        return _codigo(self.task_name)

    @property
    def ordens_de_producao(self) -> tuple[str, ...]:
        """Todas as OPs presentes no nesting, sem deduzir uma OP dominante."""

        return tuple(dict.fromkeys(part.codigo_op for part in self.parts if part.codigo_op))


@dataclass(frozen=True)
class SigmaNestTask:
    """Uma tarefa de Corte. Agrupa programas; **não possui OP**."""

    task_name: str
    material: str = ""
    thickness: float | None = None
    plans: tuple[SigmaNestCutPlan, ...] = ()

    @property
    def codigo_tarefa(self) -> str:
        return _codigo(self.task_name)

    @property
    def programas(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(_texto(plan.program_name) for plan in self.plans))

    @property
    def ordens_de_producao(self) -> tuple[str, ...]:
        ordens: list[str] = []
        for plan in self.plans:
            ordens.extend(plan.ordens_de_producao)
        return tuple(dict.fromkeys(ordens))


@dataclass(frozen=True)
class SigmaNestPlanningSnapshot:
    """Recorte de planejamento lido do SigmaNEST em um instante."""

    tasks: tuple[SigmaNestTask, ...] = ()
    read_at: datetime | None = None
    source: str = "sigmanest"
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def plans(self) -> tuple[SigmaNestCutPlan, ...]:
        return tuple(plan for task in self.tasks for plan in task.plans)

    @property
    def part_lines(self) -> tuple[SigmaNestPartLine, ...]:
        return tuple(part for plan in self.plans for part in plan.parts)

    @property
    def ordens_de_producao(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(part.codigo_op for part in self.part_lines if part.codigo_op)
        )
