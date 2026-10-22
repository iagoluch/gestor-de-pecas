"""Corpos da fila manual por recurso (``/areas/{area_id}/queue``)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AddQueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    resource: str = Field(min_length=1, max_length=120)
    op: str = Field(min_length=1, max_length=80)

    @field_validator("op")
    @classmethod
    def _sem_caractere_nulo(cls, valor: str) -> str:
        if chr(0) in valor:
            raise ValueError("A OP não pode conter caractere nulo.")
        return valor


class ReorderQueueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    resource: str = Field(min_length=1, max_length=120)
    operation_ids: list[int] = Field(max_length=500)
