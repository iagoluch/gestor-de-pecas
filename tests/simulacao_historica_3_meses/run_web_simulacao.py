"""Inicia o Web no banco isolado da simulação histórica de três meses."""

from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.simulacao_historica_3_meses.seed_simulacao_historica import (  # noqa: E402
    SIMULATED_NOW,
    TARGET_DATABASE,
    _safe_dsns,
)


def main() -> None:
    _operational, _common_test, target_dsn, _maintenance, safe = _safe_dsns()
    target = safe["target"]
    if str(target.get("dbname") or "").casefold() != TARGET_DATABASE.casefold():
        raise RuntimeError("Inicialização recusada: banco da simulação inesperado.")

    os.environ["TEST_DATABASE_URL"] = target_dsn
    os.environ["GESTOR_EXPECTED_DATABASE"] = TARGET_DATABASE
    os.environ["GESTOR_TEST_MODE"] = "1"
    os.environ["GESTOR_WEB_ENV"] = "development"
    os.environ["GESTOR_WEB_SERVE_STATIC"] = "1"
    os.environ["GESTOR_WEB_PUBLIC_HOST"] = "gestor-peca"
    os.environ["GESTOR_SIMULATION_MODE"] = "1"
    os.environ["GESTOR_SIMULATION_NOW"] = SIMULATED_NOW.isoformat(timespec="seconds")
    os.chdir(ROOT)

    port = int(os.getenv("GESTOR_WEB_PORT", "8000"))
    if not 1024 <= port <= 65535:
        raise RuntimeError("GESTOR_WEB_PORT deve estar entre 1024 e 65535.")

    import uvicorn

    print(
        f"Web da simulação em http://127.0.0.1:{port}/ — "
        f"banco de teste {target['dbname']} ({target['host']}:{target['port']}); sem integração externa."
    )
    uvicorn.run("backend.api.main:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
