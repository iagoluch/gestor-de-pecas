"""Contratos HTTP da Qualidade. Transporte apenas: a regra vive no serviço."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QualityDimensionInput(BaseModel):
    sequencia: int = Field(ge=1, le=200)
    descricao: str | None = Field(default=None, max_length=200)
    padrao: str = Field(min_length=1, max_length=120)
    unidade: str | None = Field(default=None, max_length=20)


class QualityTemplateRequest(BaseModel):
    produto: str = Field(min_length=1, max_length=60)
    cotas: list[QualityDimensionInput] = Field(min_length=1, max_length=60)


class QualityMeasureInput(BaseModel):
    sequencia: int = Field(ge=1, le=200)
    medida: str = Field(min_length=1, max_length=60)
    status: str = Field(min_length=1, max_length=20)


class QualityRncInput(BaseModel):
    motivo: str = Field(min_length=3, max_length=500)
    observacao: str | None = Field(default=None, max_length=500)


class QualityPieceRequest(BaseModel):
    numero_peca: int = Field(ge=1, le=100_000)
    resultado: str = Field(min_length=1, max_length=20)
    medidas: list[QualityMeasureInput] = Field(min_length=1, max_length=60)
    rnc: QualityRncInput | None = None
    badges: list[str] = Field(default_factory=list, max_length=10)


class QualityOpenRequest(BaseModel):
    op: str = Field(min_length=1, max_length=60)


class QualityBypassRequest(BaseModel):
    """Seguir sem a inspeção formal, pela regra transitória de implantação."""

    op: str = Field(min_length=1, max_length=40)
    badges: list[str] = Field(default_factory=list, max_length=10)
    motivo: str | None = Field(default=None, max_length=240)


class QualityFinishRequest(BaseModel):
    badges: list[str] = Field(default_factory=list, max_length=10)


class QualityDrawingRequest(BaseModel):
    """Envio do desenho/PDF em base64.

    O conteúdo chega embutido no JSON para não introduzir uma dependência nova
    de upload multipart apenas por causa desta tela.
    """

    produto: str = Field(min_length=1, max_length=60)
    filename: str = Field(min_length=1, max_length=240)
    conteudo_base64: str = Field(min_length=1)
