"""Inicia o Gestor de Peças localmente (127.0.0.1:8001), sem Cloudflare.

Uso::

    python tools/iniciar_servidor.py

Sobe o PostgreSQL do Compose se necessário e o servidor Web em segundo
plano, sempre no banco TESTE — sem ``GESTOR_WEB_ENV=production`` explícito,
``Database()`` só enxerga ``TEST_DATABASE_URL`` (guarda em
app/database/database.py). Não altera o ``.env``.

Se a porta já estiver ocupada, use ``reiniciar_servidor.py``.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime

from servidor_comum import (
    LOCAL_URL,
    PROJECT_ROOT,
    WEB_HOST,
    WEB_PORT,
    find_python,
    pids_listening_on_port,
    port_is_available,
    runtime_directory,
    start_postgres,
    wait_for_health,
    write_tracked_pid,
)


def main() -> int:
    if not port_is_available(WEB_HOST, WEB_PORT):
        ocupada_por = pids_listening_on_port(WEB_PORT)
        print(f"A porta {WEB_PORT} já está em uso (PID {ocupada_por or '?'}).")
        print("Use `python tools/reiniciar_servidor.py` para reiniciar, ou `python tools/parar_servidor.py` para derrubar.")
        return 1

    start_postgres()

    python = find_python()
    runtime = runtime_directory()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = runtime / f"servidor-{stamp}.log"
    command = [
        str(python), "-m", "uvicorn", "backend.api.main:app",
        "--host", WEB_HOST, "--port", str(WEB_PORT),
    ]

    print(f"Iniciando a API Web em {LOCAL_URL}...")
    with log_path.open("w", encoding="utf-8", newline="") as log:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    write_tracked_pid(process.pid)

    try:
        health = wait_for_health()
    except SystemExit as exc:
        print(str(exc))
        print(f"Log: {log_path}")
        return 1

    print(f"Servidor no ar: {LOCAL_URL} (PID {process.pid}, schema {health.get('schema_version')}).")
    print(f"Log: {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
