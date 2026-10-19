"""Contratos HTTP da aba Diretoria (16/10/2026).

Espelham exatamente o que ``mes.services.director_summary`` devolve. Os únicos
campos em R$ do sistema vivem aqui; nenhuma outra resposta da gestão os expõe.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, StrictFloat


class DirectorPeriod(BaseModel):
    nome: str
    inicio: str
    fim: str


class DirectorCards(BaseModel):
    produzido: int | float
    horas_paradas: float
    custo_parada: float
    # Mesmo objeto de OEE da Visão Geral (valor, componentes, motivo).
    eficiencia_oee: dict[str, Any] | float | None = None


class DirectorLoss(BaseModel):
    setor: str | None = None
    horas_paradas: float
    custo: float
    motivo_principal: str | None = None
    custo_completo: bool


class DirectorSectorRank(BaseModel):
    nome: str | None = None
    oee: float


class DirectorPanelResponse(BaseModel):
    periodo: DirectorPeriod
    cards: DirectorCards
    onde_perdemos: list[DirectorLoss]
    melhor_setor: DirectorSectorRank | None = None
    pior_setor: DirectorSectorRank | None = None
    custo_completo: bool
    custos_faltando: int
    aviso: str | None = None


class DirectorStopReason(BaseModel):
    motivo: str
    horas: float


class DirectorPerson(BaseModel):
    nome: str | None = None
    horas: float
    custo: float
    custo_completo: bool


class DirectorSheetResponse(BaseModel):
    texto: str
    trabalhou_h: float
    disponivel_h: float
    produzido: int | float
    custo_trabalho: float
    parado_h: float
    custo_parada: float
    motivo_principal: str | None = None
    paradas_por_motivo: list[DirectorStopReason]
    sem_demanda_h: float
    fora_turno_h: float
    pessoas: list[DirectorPerson]
    custo_parada_completo: bool
    custos_faltando_parada: int
    custo_trabalho_completo: bool
    custos_faltando_trabalho: int
    custo_completo: bool
    custos_faltando: int


class DirectorResourceRate(BaseModel):
    recurso: str
    nome: str | None = None
    setor: str | None = None
    valor_hora: float | None = None


class DirectorPersonRate(BaseModel):
    operador_id: int
    nome: str | None = None
    cracha: str | None = None
    valor_hora: float | None = None


class DirectorCostsResponse(BaseModel):
    recursos: list[DirectorResourceRate]
    pessoas: list[DirectorPersonRate]


class DirectorRateRequest(BaseModel):
    """Valor por hora em R$. A regra (> 0, até 2 casas) é do serviço: 422 estruturado."""

    model_config = ConfigDict(extra="forbid")

    # Estrito: número JSON (inteiro ou decimal); recusa true/false e texto ("NaN", "12").
    valor_hora: StrictFloat
