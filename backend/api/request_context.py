"""Correlação por requisição nos logs de ``backend/``, ``mes/`` e ``app/`` (BK-13)."""

from __future__ import annotations

import logging
from contextvars import ContextVar

# Definido pelo middleware ``request_context`` enquanto a requisição roda. O
# contexto é copiado para a task do endpoint e para o threadpool dos ``def``.
REQUEST_ID: ContextVar[str | None] = ContextVar("request_id", default=None)

LOG_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"


class RequestIdFilter(logging.Filter):
    """Anota cada registro com o ``request_id`` corrente (``-`` fora de requisição)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = REQUEST_ID.get() or "-"
        return True


def configure_logging() -> None:
    """Garante o ``request_id`` em todo handler raiz, sem trocar a configuração do host.

    Sob o uvicorn o logger raiz não tem handler e os avisos da aplicação caíam
    no ``lastResort`` só com a mensagem; aqui ganham um handler com o ID. Se o
    host já configurou handlers, eles só recebem o filtro. Idempotente.
    """

    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        root.addHandler(handler)
    for handler in root.handlers:
        if not any(isinstance(item, RequestIdFilter) for item in handler.filters):
            handler.addFilter(RequestIdFilter())
