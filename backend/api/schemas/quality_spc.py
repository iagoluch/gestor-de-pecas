"""Contrato de resposta do SPC da Qualidade (somente leitura)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SpcMetric(BaseModel):
    """Mesmo formato do ``MetricValue`` do MES: sem dado = ``value`` nulo + motivo."""

    value: float | None
    availability: str
    unit: str | None = None
    reason: str | None = None


class SpcCota(BaseModel):
    sequencia: int
    descricao: str | None = None
    unidade: str


class SpcEspecificacao(BaseModel):
    nominal: float
    margem: float
    lsl: float
    usl: float


class SpcLimites(BaseModel):
    lcl: float
    centro: float
    ucl: float


class SpcSinal(BaseModel):
    grafico: str  # "x" (média/valor individual) ou "dispersao" (amplitude / amplitude móvel)
    regra: str  # "fora_dos_limites" ou "sete_do_mesmo_lado"


class SpcPonto(BaseModel):
    indice: int
    inspecao_id: int | None = None
    codigo_op: str | None = None
    inicio: datetime | None = None
    fim: datetime | None = None
    n: int
    media: float
    amplitude: float | None = None
    limites_x: SpcLimites | None = None
    limites_dispersao: SpcLimites | None = None
    fora_de_controle: list[SpcSinal]


class SpcSerie(BaseModel):
    produto: str
    cota: SpcCota
    padrao_snapshot: str
    especificacao: SpcEspecificacao
    tipo_grafico: str  # "xbar_r" ou "i_mr"
    n_medidas: int
    n_subgrupos: int
    subgrupos_unitarios_descartados: int
    media: float | None
    desvio_geral: float | None
    sigma_dentro: float | None
    sigma_fonte: str | None
    suficiente: bool
    motivo_insuficiente: str | None
    motivo_sem_limites: str | None = None
    limites_x: SpcLimites | None
    limites_dispersao: SpcLimites | None
    cpk: SpcMetric
    cpu: float | None
    cpl: float | None
    escopo_cpk: str
    rotulo_cpk: str
    pontos: list[SpcPonto]


class SpcAmostraMinima(BaseModel):
    medidas: int
    subgrupos: int


class SpcIgnoradas(BaseModel):
    padrao_nao_numerico: int
    medida_invalida: int


class SpcResponse(BaseModel):
    escopo_cpk: str
    rotulo_cpk: str
    amostra_minima: SpcAmostraMinima
    ignoradas: SpcIgnoradas
    truncado: bool
    series: list[SpcSerie]
