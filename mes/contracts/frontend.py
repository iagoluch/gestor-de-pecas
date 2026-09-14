"""Contrato estável entre os casos de uso do backend e as interfaces.

O contrato é deliberadamente neutro a transporte: FastAPI e qualquer
frontend Web podem consumir a mesma estrutura sem mover regra industrial para
a camada visual.
"""

FRONTEND_CONTRACT_VERSION = "2026-08-19.1"

MANAGEMENT_SECTIONS = (
    "inicio",
    "consulta_operacional",
    "producao",
    "analises",
    "auditoria",
    "rastreabilidade",
)

__all__ = ["FRONTEND_CONTRACT_VERSION", "MANAGEMENT_SECTIONS"]
