from fastapi import Depends, Request
import os

from backend.api.database import get_database
from mes.services.frontend_facade import FrontendBackendFacade


def get_frontend_facade(request: Request, database=Depends(get_database)):
    settings = request.app.state.settings
    if settings.simulation_mode:
        database_name = str((getattr(database, "safe_target", {}) or {}).get("dbname") or "")
        safe_name = database_name.casefold()
        expected = str(os.getenv("GESTOR_EXPECTED_DATABASE") or "").strip().casefold()
        legacy_explicit = bool({"homolog", "simulacao"} & set(safe_name.split("_")))
        if "test" not in safe_name or not (
            legacy_explicit or (expected and expected == safe_name)
        ):
            raise RuntimeError(
                "Modo de simulação recusado: o banco ativo não é um alvo explícito de teste/homologação."
            )
    clock = getattr(request.app.state, "clock", None)
    now_func = clock.now if settings.simulation_mode and clock is not None else None
    return FrontendBackendFacade(
        database,
        now_func=now_func,
        simulation_mode=settings.simulation_mode,
    )
