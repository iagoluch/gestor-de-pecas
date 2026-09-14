"""Inicia o Gestor Web na base local de simulação residencial.

As credenciais continuam vindo do ``.env`` local e nunca são impressas. O
banco-alvo precisa conter simultaneamente ``test`` e ``simulacao`` no nome,
mantendo os indicadores fictícios separados de qualquer ambiente produtivo.
"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys

from dotenv import dotenv_values
from psycopg.conninfo import make_conninfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Sem default: o banco dedicado da simulação residencial precisa ser informado em
# GESTOR_RESIDENCE_SIMULATION_DATABASE. Nunca aponte para o banco de TESTE oficial.
DEFAULT_DATABASE = ""
SIMULATION_REFERENCE_TIME = datetime(2026, 8, 24, 8, 32, 0)


def _required(values: dict, name: str) -> str:
    value = str(os.environ.get(name) or values.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"{name} precisa estar configurada no .env local.")
    return value


def configure_environment() -> dict[str, str]:
    values = dict(dotenv_values(PROJECT_ROOT / ".env"))
    for name, value in values.items():
        if value is not None:
            os.environ.setdefault(str(name), str(value))
    database = str(
        os.environ.get("GESTOR_RESIDENCE_SIMULATION_DATABASE")
        or values.get("GESTOR_RESIDENCE_SIMULATION_DATABASE")
        or DEFAULT_DATABASE
    ).strip()
    safe_name = database.casefold()
    if "test" not in safe_name or "simulacao" not in safe_name:
        raise RuntimeError(
            "O banco residencial precisa conter 'test' e 'simulacao' no nome."
        )

    host = str(
        os.environ.get("GESTOR_RESIDENCE_DB_HOST")
        or values.get("GESTOR_RESIDENCE_DB_HOST")
        or "127.0.0.1"
    ).strip()
    port = str(
        os.environ.get("GESTOR_RESIDENCE_DB_PORT")
        or values.get("GESTOR_RESIDENCE_DB_PORT")
        or "15432"
    ).strip()
    user = _required(values, "POSTGRES_USER")
    password = _required(values, "POSTGRES_PASSWORD")
    dsn = make_conninfo(
        host=host,
        port=port,
        dbname=database,
        user=user,
        password=password,
        connect_timeout="8",
        application_name="gestor_simulacao_residencia",
    )

    os.environ["TEST_DATABASE_URL"] = dsn
    os.environ["GESTOR_EXPECTED_DATABASE"] = database
    os.environ["GESTOR_TEST_MODE"] = "1"
    os.environ["GESTOR_WEB_ENV"] = "development"
    os.environ["GESTOR_WEB_SERVE_STATIC"] = "1"
    os.environ["GESTOR_WEB_ALLOWED_HOSTS"] = "127.0.0.1,localhost"
    os.environ["GESTOR_SIMULATION_MODE"] = "1"
    os.environ["GESTOR_SIMULATION_NOW"] = SIMULATION_REFERENCE_TIME.isoformat(
        timespec="seconds"
    )
    return {"host": host, "port": port, "dbname": database}


def main() -> None:
    target = configure_environment()
    os.chdir(PROJECT_ROOT)
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    import uvicorn

    print(
        "Gestor de Peças em modo de simulação: http://127.0.0.1:8000/ — "
        f"banco {target['dbname']} ({target['host']}:{target['port']})."
    )
    uvicorn.run("backend.api.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
