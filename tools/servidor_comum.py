"""Funções compartilhadas pelos scripts locais de iniciar/reiniciar/parar o servidor Web.

Uso puramente local (127.0.0.1:8001), sem Cloudflare e sem tocar no ``.env``.
A segurança de banco já vem de ``app/database/database.py``: sem
``GESTOR_WEB_ENV=production`` explícito, ``Database()`` só enxerga
``TEST_DATABASE_URL`` (e recusa se o nome do banco não contiver "test").
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_HOST = "127.0.0.1"
WEB_PORT = 8001
LOCAL_URL = f"http://{WEB_HOST}:{WEB_PORT}"
COMPOSE_PATH = PROJECT_ROOT / "compose.yaml"


def runtime_directory() -> Path:
    runtime = Path(tempfile.gettempdir()) / "gestor-pecas-runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    return runtime


def pid_file() -> Path:
    return runtime_directory() / "servidor.pid"


def find_python() -> Path:
    project_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if project_python.is_file():
        return project_python.resolve()
    current = Path(sys.executable)
    if current.is_file():
        return current.resolve()
    raise SystemExit("Nenhum executável Python válido foi encontrado.")


def port_is_available(host: str = WEB_HOST, port: int = WEB_PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((host, port))
        except OSError:
            return False
    return True


def pids_listening_on_port(port: int = WEB_PORT) -> list[int]:
    """Descobre PIDs ouvindo a porta via ``netstat`` — funciona mesmo sem pidfile."""

    result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True,
        text=True,
        check=False,
    )
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0] != "TCP":
            continue
        local_address, state, pid_text = parts[1], parts[3], parts[4]
        if state != "LISTENING" or not local_address.endswith(f":{port}"):
            continue
        try:
            pids.add(int(pid_text))
        except ValueError:
            continue
    return sorted(pids)


def read_tracked_pid() -> int | None:
    path = pid_file()
    if not path.is_file():
        return None
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def write_tracked_pid(pid: int) -> None:
    pid_file().write_text(str(pid), encoding="utf-8")


def clear_tracked_pid() -> None:
    path = pid_file()
    if path.is_file():
        path.unlink()


def kill_pid(pid: int) -> bool:
    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def wait_for_health(*, attempts: int = 30, interval: float = 1.0) -> dict:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            request = Request(
                f"{LOCAL_URL}/api/v1/system/health",
                headers={"User-Agent": "GestorServidorLocal/1.0"},
            )
            with urlopen(request, timeout=5) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("status") != "ok":
                raise RuntimeError(f"status={payload.get('status')!r}")
            return payload
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            last_error = exc
            time.sleep(interval)
    raise SystemExit(f"O servidor não respondeu em {LOCAL_URL} a tempo ({last_error}).")


def start_postgres() -> None:
    import shutil

    docker = shutil.which("docker")
    if not docker or not COMPOSE_PATH.is_file():
        print("Aviso: Docker/compose.yaml não encontrados; pulando o start automático do PostgreSQL.")
        return
    print("Verificando o PostgreSQL do Compose (sem recriar volume)...")
    subprocess.run(
        [docker, "compose", "-f", str(COMPOSE_PATH), "up", "-d", "postgres"],
        cwd=PROJECT_ROOT,
        check=False,
        timeout=90,
    )
