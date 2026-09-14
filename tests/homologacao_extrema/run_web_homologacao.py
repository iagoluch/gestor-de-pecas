"""Inicia o Web exclusivamente no banco dedicado da homologação extrema."""

from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.homologacao_extrema.seed_homologacao_extrema import (  # noqa: E402
    TARGET_DATABASE,
    _load_dsns,
    _safe_target,
)


def main() -> None:
    _operational, _common_test, target_dsn, _maintenance = _load_dsns()
    target = _safe_target(target_dsn)
    if target["dbname"].casefold() != TARGET_DATABASE.casefold():
        raise RuntimeError("Inicialização recusada: banco de homologação inesperado.")
    os.environ["TEST_DATABASE_URL"] = target_dsn
    os.environ["GESTOR_EXPECTED_DATABASE"] = TARGET_DATABASE
    os.environ["GESTOR_TEST_MODE"] = "1"
    os.environ["GESTOR_WEB_ENV"] = "development"
    os.environ["GESTOR_WEB_SERVE_STATIC"] = "1"
    os.environ["GESTOR_WEB_PUBLIC_HOST"] = "gestor-peca"
    os.chdir(ROOT)

    import uvicorn

    print(
        "Web de homologação em http://127.0.0.1:8000/ — "
        f"banco de teste {target['dbname']} ({target['host']}:{target['port']}); sem integração externa."
    )
    uvicorn.run("backend.api.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
