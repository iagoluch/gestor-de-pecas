"""Contrato neutro de planejamento de Corte originado no SigmaNEST.

Este pacote não conhece SQL Server, ODBC nem FastAPI. Ele define os DTOs e a
porta consumida pelos serviços do Gestor. A implementação de transporte vive em
``backend/integrations/sigmanest_sqlserver.py``.
"""

from mes.integrations.sigmanest.models import (
    SigmaNestCutPlan,
    SigmaNestPartLine,
    SigmaNestPlanningSnapshot,
    SigmaNestTask,
)
from mes.integrations.sigmanest.gateway import (
    SigmaNestPlanningGateway,
    SigmaNestPlanningService,
)

__all__ = [
    "SigmaNestCutPlan",
    "SigmaNestPartLine",
    "SigmaNestPlanningGateway",
    "SigmaNestPlanningService",
    "SigmaNestPlanningSnapshot",
    "SigmaNestTask",
]
