"""Servidor LAN da fábrica simulada; preserva .env e recusa banco operacional."""
from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    from dotenv import load_dotenv
    from psycopg.conninfo import conninfo_to_dict

    load_dotenv(ROOT / ".env", override=False)
    target = "gestor_pecas_test"
    test_dsn = os.environ.get("TEST_DATABASE_URL", "")
    test = conninfo_to_dict(test_dsn)
    operational = conninfo_to_dict(os.environ.get("DATABASE_URL", ""))
    if test.get("dbname") != target:
        raise RuntimeError("TEST_DATABASE_URL deve apontar para gestor_pecas_test.")
    if all(test.get(k) == operational.get(k) for k in ("host", "port", "dbname")):
        raise RuntimeError("Banco TESTE coincide com operacional; execução recusada.")
    os.environ.update({
        "GESTOR_EXPECTED_DATABASE": target,
        "GESTOR_TEST_MODE": "1",
        "GESTOR_WEB_ENV": "development",
        "GESTOR_WEB_SERVE_STATIC": "1",
        "GESTOR_WEB_ALLOWED_HOSTS": "127.0.0.1,localhost,10.10.1.248,gestor-peca",
        "GESTOR_WEB_PUBLIC_HOST": "gestor-peca",
        "GESTOR_WEB_COOKIE_SECURE": "0",
        "GESTOR_SIMULATION_MODE": "0",
        "GESTOR_SIMULATION_TIME_SCALE": "0",
        "GESTOR_ANDON_DEMO_MODE": "0",
        "GESTOR_TOTVS_ENABLED": "0",
        "GESTOR_TOTVS_SOAP_ENABLED": "0",
        "GESTOR_TOTVS_OUTBOX_ENABLED": "0",
        "GESTOR_TOTVS_OUTBOX_WORKER_ENABLED": "0",
        "GESTOR_TOTVS_OP_PULL_ENDPOINT": "",
        "GESTOR_SIGMANEST_SYNC_ENABLED": "0",
        "GESTOR_REPORT_AUTOMATION_ENABLED": "0",
        "GESTOR_AI_ENABLED": "0",
        "GESTOR_DEV_OBSERVATORY_ENABLED": "0",
        "TELEGRAM_ENABLED": "1",
    })
    if not os.environ.get("GESTOR_CHAMADA_TELEGRAM_CHAT_ID"):
        os.environ["GESTOR_CHAMADA_TELEGRAM_CHAT_ID"] = os.environ.get(
            "GESTOR_TELEGRAM_FACTORY_CHAT_ID", ""
        )
    from app.database.config import load_postgres_config
    import psycopg

    config = load_postgres_config(testing=True)
    with psycopg.connect(config.dsn) as connection:
        actual = connection.execute("SELECT current_database()").fetchone()[0]
        if actual != target:
            raise RuntimeError("Identidade PostgreSQL inesperada.")
    print(f"Servidor TESTE: {actual}; relógio real; TOTVS bloqueado; Telegram ativo.", flush=True)
    os.chdir(ROOT)
    import uvicorn
    from dataclasses import replace
    from backend.api.config import WebSettings
    from backend.api.main import create_app

    application = create_app(settings=replace(
        WebSettings.from_env(),
        session_cookie_name="gestor_factory_test_session",
    ))

    @application.middleware("http")
    async def test_identity(request, call_next):
        response = await call_next(request)
        response.headers["X-Gestor-Factory-Test"] = actual
        return response

    uvicorn.run(application, host="0.0.0.0", port=int(os.getenv("GESTOR_TEST_SIM_PORT", "8002")))  # 8001 é da API REAL


if __name__ == "__main__":
    main()
