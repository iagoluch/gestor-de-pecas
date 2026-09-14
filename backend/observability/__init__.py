"""Dev Observatory — observabilidade permanente do Gestor de Peças.

Ferramenta do desenvolvedor, não do operador. Reúne em um lugar só o que já
existe espalhado pelo sistema:

* eventos classificados (erro real x bloqueio esperado) capturados no funil de
  erros da API;
* estado corrente de cada posto, lido da projeção canônica
  ``FrontendBackendFacade.consulta_operacional``;
* métricas de latência, PostgreSQL e processo;
* relatório automático por turno, com janelas vindas de
  ``mes.domain.manufacturing_rules``.

Regra absoluta: o observatório **nunca escreve no banco**. A persistência dele
é em disco (``dev_reports/``) e o acesso ao banco REAL é somente leitura
garantida pelo próprio PostgreSQL (ver ``readonly_db``).
"""

from backend.observability.classification import (
    CLASSIFICATIONS,
    DEFECT_CLASSIFICATIONS,
    EXPECTED_BLOCK,
    EXPECTED_VALIDATION,
    OK,
    PERFORMANCE_ERROR,
    REAL_ERROR,
    TECHNICAL_ERROR,
    classify_http,
    sanitize,
)
from backend.observability.recorder import DevObservatoryRecorder, summarize_latency

__all__ = [
    "CLASSIFICATIONS",
    "DEFECT_CLASSIFICATIONS",
    "DevObservatoryRecorder",
    "EXPECTED_BLOCK",
    "EXPECTED_VALIDATION",
    "OK",
    "PERFORMANCE_ERROR",
    "REAL_ERROR",
    "TECHNICAL_ERROR",
    "classify_http",
    "sanitize",
    "summarize_latency",
]
