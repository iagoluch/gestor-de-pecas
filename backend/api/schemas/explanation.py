"""Resposta de ``GET /management/explicacao`` (espelha ``ExplanationTree.to_dict``)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExplanationNode(BaseModel):
    kind: str
    label: str
    seconds: float
    children: list["ExplanationNode"] = Field(default_factory=list)
    detail: dict[str, Any] | None = None
    truncated: bool = False


class ExplanationResponse(BaseModel):
    metric: str
    label: str
    total_seconds: float
    average_seconds: float | None = None
    resource_count: int
    day_count: int
    parent_total_seconds: float
    siblings: list[dict[str, Any]]
    reason: str
    rule: str
    children: list[ExplanationNode]
    excluded: list[dict[str, Any]]
    reconciliation: dict[str, Any]
    calculated_at: str
    truncated: bool
    notes: list[str] = Field(default_factory=list)


ExplanationNode.model_rebuild()
