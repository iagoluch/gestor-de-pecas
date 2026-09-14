"""Inicia o Gestor Web no banco TESTE e o expõe por Cloudflare Quick Tunnel.

Uso normal::

    python iniciar_sistema_teste_cloudflare.py

O inicializador protege por nome exato os bancos ``gestor_pecas_test`` e
``gestor_pecas``, atualiza somente as chaves Web necessárias no ``.env`` e
valida a aplicação local e publicamente antes de abrir o navegador.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import webbrowser


PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"
COMPOSE_PATH = PROJECT_ROOT / "compose.yaml"
WEB_INDEX_PATH = PROJECT_ROOT / "web" / "dist" / "index.html"

TEST_DATABASE = "gestor_pecas_test"
REAL_DATABASE = "gestor_pecas"
WEB_HOST = "127.0.0.1"
WEB_PORT = 8001
LOCAL_URL = f"http://{WEB_HOST}:{WEB_PORT}"
QUICK_TUNNEL_PATTERN = re.compile(
    r"https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.trycloudflare\.com",
    re.IGNORECASE,
)


class InitializationError(RuntimeError):
    """Falha segura e apresentável ao iniciar o ambiente TESTE."""


@dataclass(frozen=True)
class DatabaseTarget:
    host: str
    port: int
    database: str
    user: str


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen
    log_path: Path
    log_handle: object | None = None


def _configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _print_step(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def _load_env() -> dict[str, str]:
    if not ENV_PATH.is_file():
        raise InitializationError(
            f"{ENV_PATH.name} não existe. Crie-o a partir de .env.example e configure as credenciais locais."
        )
    try:
        from dotenv import dotenv_values
    except ImportError as exc:
        raise InitializationError(
            "Dependência python-dotenv ausente. Instale requirements.txt no Python usado para executar o arquivo."
        ) from exc

    raw_values = dotenv_values(ENV_PATH)
    return {
        str(key): str(value)
        for key, value in raw_values.items()
        if key and value is not None
    }


def _parse_database_target(dsn: str, *, variable: str) -> DatabaseTarget:
    if not dsn.strip():
        raise InitializationError(f"{variable} não está configurada no .env.")
    try:
        from psycopg.conninfo import conninfo_to_dict

        values = conninfo_to_dict(dsn)
        host = str(values.get("host") or "").strip()
        port = int(str(values.get("port") or "5432"))
        database = str(values.get("dbname") or "").strip()
        user = str(values.get("user") or "").strip()
    except Exception as exc:
        raise InitializationError(f"{variable} possui um DSN PostgreSQL inválido.") from exc

    if not host or not database or not user:
        raise InitializationError(
            f"{variable} precisa informar host, banco e usuário explicitamente."
        )
    return DatabaseTarget(host=host, port=port, database=database, user=user)


def _validate_database_barriers(values: Mapping[str, str]) -> tuple[str, DatabaseTarget]:
    test_dsn = str(values.get("TEST_DATABASE_URL") or "").strip()
    real_dsn = str(values.get("DATABASE_URL") or "").strip()
    test_target = _parse_database_target(test_dsn, variable="TEST_DATABASE_URL")
    real_target = _parse_database_target(real_dsn, variable="DATABASE_URL")

    if test_target.database != TEST_DATABASE:
        raise InitializationError(
            "Inicialização recusada: TEST_DATABASE_URL deve apontar exatamente para "
            f"{TEST_DATABASE!r}; alvo encontrado: {test_target.database!r}."
        )
    if real_target.database != REAL_DATABASE:
        raise InitializationError(
            "Inicialização recusada: DATABASE_URL deve continuar protegendo exatamente "
            f"o banco REAL {REAL_DATABASE!r}; alvo encontrado: {real_target.database!r}."
        )
    if test_dsn == real_dsn or test_target == real_target:
        raise InitializationError(
            "Inicialização recusada: TEST_DATABASE_URL e DATABASE_URL não podem ser o mesmo alvo."
        )
    if test_target.host.casefold() not in {"127.0.0.1", "localhost", "::1"}:
        raise InitializationError(
            "Inicialização recusada: o banco TESTE deste inicializador deve estar no PostgreSQL local."
        )
    return test_dsn, test_target


def _safe_target_text(target: DatabaseTarget) -> str:
    return (
        f"host={target.host} porta={target.port} banco={target.database} "
        f"usuário={target.user}"
    )


def _find_cloudflared() -> Path:
    candidates = [
        shutil.which("cloudflared"),
        r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        r"C:\Program Files\cloudflared\cloudflared.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise InitializationError(
        "cloudflared não foi encontrado no PATH nem em Program Files. Instale-o antes de iniciar."
    )


def _find_python() -> Path:
    project_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if project_python.is_file():
        return project_python.resolve()
    current = Path(sys.executable)
    if current.is_file():
        return current.resolve()
    raise InitializationError("Nenhum executável Python válido foi encontrado.")


def _run_checked(command: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise InitializationError(f"Comando não encontrado: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise InitializationError(f"Tempo esgotado ao executar: {command[0]}") from exc
    if result.returncode != 0:
        detail = (result.stdout or "").strip().splitlines()
        suffix = f" Detalhe: {detail[-1]}" if detail else ""
        raise InitializationError(f"Falha ao executar {' '.join(command[:3])}.{suffix}")
    return result


def _check_prerequisites() -> tuple[Path, Path]:
    if not COMPOSE_PATH.is_file():
        raise InitializationError("compose.yaml não foi encontrado na raiz do projeto.")
    if not WEB_INDEX_PATH.is_file():
        raise InitializationError(
            "web/dist/index.html não existe. Compile o frontend antes de usar o inicializador."
        )
    docker = shutil.which("docker")
    if not docker:
        raise InitializationError("Docker CLI não foi encontrado no PATH.")
    _run_checked([docker, "info", "--format", "{{.ServerVersion}}"], timeout=20)
    services = _run_checked(
        [docker, "compose", "-f", str(COMPOSE_PATH), "config", "--services"],
        timeout=20,
    ).stdout.splitlines()
    if "postgres" not in {item.strip() for item in services}:
        raise InitializationError("O serviço postgres não existe no compose.yaml.")
    return Path(docker), _find_cloudflared()


def _start_postgres(docker: Path) -> None:
    _print_step("Iniciando/verificando o PostgreSQL do Compose sem recriar volume...")
    _run_checked(
        [str(docker), "compose", "-f", str(COMPOSE_PATH), "up", "-d", "postgres"],
        timeout=90,
    )


def _probe_database(test_dsn: str, *, attempts: int = 20) -> int:
    try:
        import psycopg
    except ImportError as exc:
        raise InitializationError(
            "Dependência psycopg ausente. Instale requirements.txt no Python usado para executar o arquivo."
        ) from exc

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with psycopg.connect(test_dsn, connect_timeout=5) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
                    cursor.execute("SELECT current_database()")
                    active_database = str(cursor.fetchone()[0])
                    cursor.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
                    schema_version = int(cursor.fetchone()[0])
                connection.rollback()
            if active_database != TEST_DATABASE:
                raise InitializationError(
                    f"A conexão efetiva alcançou {active_database!r}, não {TEST_DATABASE!r}."
                )
            return schema_version
        except InitializationError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(1)
    raise InitializationError(
        f"O PostgreSQL TESTE não respondeu após {attempts} tentativas."
    ) from last_error


def _expected_schema_version() -> int:
    from app.database.schema import SCHEMA_VERSION

    return int(SCHEMA_VERSION)


def _port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind((host, port))
        except OSError:
            return False
    return True


def _runtime_directory() -> Path:
    runtime = Path(tempfile.gettempdir()) / "gestor-pecas-runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    return runtime


def _creation_flags() -> int:
    return int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) if os.name == "nt" else 0


def _pump_lines(stream, log_path: Path, output_queue: queue.Queue[str]) -> None:
    with log_path.open("w", encoding="utf-8", newline="") as log:
        for line in iter(stream.readline, ""):
            log.write(line)
            log.flush()
            output_queue.put(line)
    stream.close()


def _tail(path: Path, *, lines: int = 12) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


def _start_quick_tunnel(cloudflared: Path, runtime: Path) -> tuple[ManagedProcess, str]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = runtime / f"cloudflared-{stamp}.log"
    command = [
        str(cloudflared),
        "tunnel",
        "--url",
        LOCAL_URL,
        "--no-autoupdate",
        "--protocol",
        "http2",
    ]
    _print_step("Solicitando uma nova URL temporária ao Cloudflare...")
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_creation_flags(),
    )
    assert process.stdout is not None
    output_queue: queue.Queue[str] = queue.Queue()
    thread = threading.Thread(
        target=_pump_lines,
        args=(process.stdout, log_path, output_queue),
        name="cloudflared-log",
        daemon=True,
    )
    thread.start()
    managed = ManagedProcess("Cloudflare", process, log_path)

    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            detail = _tail(log_path)
            _stop_process(managed)
            raise InitializationError(
                "cloudflared terminou antes de gerar a URL."
                + (f"\n{detail}" if detail else "")
            )
        try:
            line = output_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        match = QUICK_TUNNEL_PATTERN.search(line)
        if match:
            return managed, match.group(0).rstrip("/")

    _stop_process(managed)
    raise InitializationError(
        "cloudflared não forneceu uma URL trycloudflare.com em 45 segundos."
    )


def _update_env(updates: Mapping[str, str], runtime: Path) -> Path | None:
    original = ENV_PATH.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in original else "\n"
    had_final_newline = original.endswith(("\n", "\r"))
    lines = original.splitlines()
    pending = dict(updates)
    assignment = re.compile(
        r"^(?P<prefix>\s*(?:export\s+)?)(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P<equals>\s*=).*$"
    )
    changed = False

    for index, line in enumerate(lines):
        match = assignment.match(line)
        if not match:
            continue
        key = match.group("key")
        if key not in updates:
            continue
        replacement = f"{match.group('prefix')}{key}{match.group('equals')}{updates[key]}"
        if replacement != line:
            lines[index] = replacement
            changed = True
        pending.pop(key, None)

    if pending:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("# Atualizado automaticamente por iniciar_sistema_teste_cloudflare.py")
        lines.extend(f"{key}={value}" for key, value in pending.items())
        changed = True

    if not changed:
        return None

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = runtime / f"env-antes-cloudflare-{stamp}.bak"
    shutil.copy2(ENV_PATH, backup)
    replacement_text = newline.join(lines) + (newline if had_final_newline else "")
    temp_path = ENV_PATH.with_name(f".{ENV_PATH.name}.{os.getpid()}.tmp")
    try:
        temp_path.write_text(replacement_text, encoding="utf-8", newline="")
        shutil.copymode(ENV_PATH, temp_path)
        os.replace(temp_path, ENV_PATH)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return backup


def _restore_env(backup: Path | None) -> None:
    if backup is None or not backup.is_file():
        return
    shutil.copy2(backup, ENV_PATH)
    _print_step("Falha de inicialização: o .env anterior foi restaurado.")


def _child_environment(values: Mapping[str, str], updates: Mapping[str, str]) -> dict[str, str]:
    child = os.environ.copy()
    child.update({str(key): str(value) for key, value in values.items()})
    child.update({str(key): str(value) for key, value in updates.items()})
    return child


def _allowed_hosts_with_tunnel(values: Mapping[str, str], public_host: str) -> str:
    configured = str(values.get("GESTOR_WEB_ALLOWED_HOSTS") or "")
    hosts: list[str] = []
    for host in ("127.0.0.1", "localhost", *configured.split(",")):
        normalized = host.strip()
        if not normalized:
            continue
        if normalized.casefold().endswith(".trycloudflare.com"):
            continue
        if normalized not in hosts:
            hosts.append(normalized)
    hosts.append(public_host)
    return ",".join(hosts)


def _start_api(python: Path, environment: Mapping[str, str], runtime: Path) -> ManagedProcess:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = runtime / f"uvicorn-{stamp}.log"
    log_handle = log_path.open("w", encoding="utf-8", newline="")
    command = [
        str(python),
        "-m",
        "uvicorn",
        "backend.api.main:app",
        "--host",
        WEB_HOST,
        "--port",
        str(WEB_PORT),
    ]
    _print_step(f"Iniciando a API Web em {LOCAL_URL}...")
    try:
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            creationflags=_creation_flags(),
        )
    except Exception:
        log_handle.close()
        raise
    return ManagedProcess("API Web", process, log_path, log_handle)


def _request_json(url: str, *, timeout: float = 8.0) -> dict:
    request = Request(url, headers={"User-Agent": "GestorTesteInitializer/1.0"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise InitializationError(f"{url} respondeu HTTP {response.status}.")
        content_type = str(response.headers.get("Content-Type") or "")
        if "application/json" not in content_type:
            raise InitializationError(f"{url} não respondeu JSON.")
        return json.loads(response.read().decode("utf-8"))


def _request_root(url: str, *, timeout: float = 8.0) -> None:
    request = Request(f"{url}/", headers={"User-Agent": "GestorTesteInitializer/1.0"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise InitializationError(f"{url}/ respondeu HTTP {response.status}.")


def _format_request_error(exc: Exception | None) -> str:
    if exc is None:
        return "erro não identificado"
    if isinstance(exc, HTTPError):
        return f"HTTP {exc.code}: {exc.reason}"
    return f"{type(exc).__name__}: {exc}"


def _verify_simulation_clock(
    capabilities: dict, simulation: "SimulationClockOptions"
) -> None:
    """Confere que o relógio da API é exatamente o que foi pedido.

    O padrão é exigir simulação **desligada**: um relógio virtual ligado sem
    pedido explícito falsearia todo dado gravado. Quando a simulação é pedida,
    a exigência não afrouxa, ela inverte — a API precisa estar em simulação, em
    execução, na escala pedida e na mesma data virtual solicitada.
    """

    estado = capabilities.get("simulation") or {}
    if not simulation.enabled:
        if estado.get("enabled") is not False:
            raise InitializationError("A API iniciou indevidamente em modo de simulação.")
        return
    if estado.get("enabled") is not True or not estado.get("running"):
        raise InitializationError("A API não iniciou com o relógio virtual em execução.")
    if float(estado.get("time_scale") or 0.0) != float(simulation.time_scale):
        raise InitializationError(
            f"A API iniciou com escala {estado.get('time_scale')}, "
            f"e não {simulation.time_scale}."
        )
    referencia = str(estado.get("reference_time") or "")
    esperado = datetime.fromisoformat(simulation.reference_time).date()
    try:
        atual = datetime.fromisoformat(referencia).date()
    except ValueError as exc:
        raise InitializationError(
            f"A API devolveu uma data virtual ilegível: {referencia!r}."
        ) from exc
    if atual != esperado:
        raise InitializationError(
            f"A API está na data virtual {atual}, e não {esperado}."
        )


def _verify_application(
    base_url: str,
    *,
    api_process: ManagedProcess,
    attempts: int,
    interval: float,
    simulation: "SimulationClockOptions | None" = None,
) -> tuple[int, dict]:
    """Validação rígida usada somente no acesso LOCAL.

    Se esta etapa falhar, a API realmente não está pronta e a inicialização deve
    ser abortada.
    """
    simulation = simulation or SimulationClockOptions()
    last_error: Exception | None = None
    for _ in range(attempts):
        if api_process.process.poll() is not None:
            detail = _tail(api_process.log_path)
            raise InitializationError(
                "A API Web terminou durante a inicialização."
                + (f"\n{detail}" if detail else "")
            )
        try:
            _request_root(base_url)
            health = _request_json(f"{base_url}/api/v1/system/health")
            capabilities = _request_json(f"{base_url}/api/v1/system/capabilities")
            if health.get("status") != "ok" or health.get("database") != "available":
                raise InitializationError("Health não confirmou banco disponível.")
            if capabilities.get("active_data_source") != "postgresql_test_only":
                raise InitializationError("Capabilities não confirmou postgresql_test_only.")
            _verify_simulation_clock(capabilities, simulation)
            return int(health.get("schema_version") or 0), capabilities
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, InitializationError) as exc:
            last_error = exc
            time.sleep(interval)
    raise InitializationError(
        f"A validação LOCAL de {base_url} não concluiu após {attempts} tentativas. "
        f"Último erro: {_format_request_error(last_error)}"
    ) from last_error


def _verify_public_tunnel(
    public_url: str,
    *,
    api_process: ManagedProcess,
    tunnel_process: ManagedProcess,
    attempts: int = 12,
    interval: float = 1.5,
) -> tuple[int | None, str | None]:
    """Valida o Quick Tunnel sem derrubar uma API local saudável.

    Quick Tunnels podem levar alguns segundos para propagar DNS/edge e também
    podem responder temporariamente com 502/530. A segurança do banco já foi
    validada localmente; portanto uma falha transitória de borda não deve matar
    a API nem o próprio tunnel.
    """
    last_error: Exception | None = None

    for _ in range(attempts):
        if api_process.process.poll() is not None:
            detail = _tail(api_process.log_path)
            raise InitializationError(
                "A API Web terminou durante a validação pública."
                + (f"\n{detail}" if detail else "")
            )
        if tunnel_process.process.poll() is not None:
            detail = _tail(tunnel_process.log_path)
            raise InitializationError(
                "O Cloudflare Tunnel encerrou durante a validação pública."
                + (f"\n{detail}" if detail else "")
            )

        try:
            # Para provar que o tunnel está encaminhando corretamente, basta a
            # raiz estática e o health. As barreiras de fonte de dados/simulação
            # já foram validadas de forma rígida no localhost.
            _request_root(public_url, timeout=6.0)
            health = _request_json(
                f"{public_url}/api/v1/system/health",
                timeout=6.0,
            )
            if health.get("status") != "ok" or health.get("database") != "available":
                raise InitializationError("Health público não confirmou banco disponível.")
            return int(health.get("schema_version") or 0), None
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, InitializationError) as exc:
            last_error = exc
            time.sleep(interval)

    return None, _format_request_error(last_error)


def _stop_process(managed: ManagedProcess | None) -> None:
    if managed is None:
        return
    process = managed.process
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    if managed.log_handle is not None:
        managed.log_handle.close()


def _check_mode() -> int:
    values = _load_env()
    test_dsn, target = _validate_database_barriers(values)
    docker, cloudflared = _check_prerequisites()
    schema = _probe_database(test_dsn, attempts=1)
    expected_schema = _expected_schema_version()
    if schema > expected_schema:
        raise InitializationError(
            f"O banco está no schema {schema}, mas este checkout conhece somente o schema {expected_schema}."
        )
    if not _port_is_available(WEB_HOST, WEB_PORT):
        raise InitializationError(
            f"A porta {WEB_PORT} já está ocupada; a inicialização automática seria recusada."
        )
    _print_step(f"Barreiras do banco confirmadas: {_safe_target_text(target)}")
    _print_step(
        f"PostgreSQL acessível em leitura; schema atual: {schema}; schema do código: {expected_schema}."
    )
    _print_step(f"Docker: {docker}")
    _print_step(f"Cloudflared: {cloudflared}")
    _print_step("Verificação concluída sem alterar o .env nem iniciar processos.")
    return 0


@dataclass(frozen=True)
class SimulationClockOptions:
    """Relógio virtual acelerado, exclusivo do banco TESTE.

    Nasce desligado. Quando ligado, a API continua na mesma porta e no mesmo
    banco: apenas a fonte de tempo da aplicação passa a ser virtual, o que
    permite observar um turno inteiro pelas telas em poucos minutos.
    """

    enabled: bool = False
    reference_time: str = ""
    time_scale: float = 0.0

    def env_updates(self) -> dict[str, str]:
        if not self.enabled:
            return {"GESTOR_SIMULATION_MODE": "0"}
        return {
            "GESTOR_SIMULATION_MODE": "1",
            "GESTOR_SIMULATION_NOW": self.reference_time,
            "GESTOR_SIMULATION_TIME_SCALE": str(self.time_scale),
        }


def _simulation_options(args: argparse.Namespace) -> SimulationClockOptions:
    if not getattr(args, "simulacao", False):
        return SimulationClockOptions()
    raw_reference = str(getattr(args, "simulacao_inicio", "") or "").strip()
    if not raw_reference:
        raise InitializationError(
            "--simulacao exige --simulacao-inicio no formato ISO 8601."
        )
    try:
        reference = datetime.fromisoformat(raw_reference)
    except ValueError as exc:
        raise InitializationError(
            "--simulacao-inicio deve estar no formato ISO 8601, por exemplo 2026-09-14T07:40:00."
        ) from exc
    scale = float(getattr(args, "simulacao_escala", 0.0) or 0.0)
    if not 0 < scale <= 3600:
        raise InitializationError("--simulacao-escala deve ficar entre 0 e 3600.")
    return SimulationClockOptions(
        enabled=True,
        reference_time=reference.isoformat(),
        time_scale=scale,
    )


def _run(*, open_browser: bool, simulation: SimulationClockOptions | None = None) -> int:
    simulation = simulation or SimulationClockOptions()
    values = _load_env()
    test_dsn, target = _validate_database_barriers(values)
    docker, cloudflared = _check_prerequisites()
    python = _find_python()
    runtime = _runtime_directory()
    tunnel: ManagedProcess | None = None
    api: ManagedProcess | None = None
    env_backup: Path | None = None
    initialization_complete = False

    _print_step(f"Alvo TESTE protegido: {_safe_target_text(target)}")
    if not _port_is_available(WEB_HOST, WEB_PORT):
        raise InitializationError(
            f"A porta {WEB_PORT} já está ocupada. O inicializador não encerrará outro processo automaticamente."
        )

    try:
        _start_postgres(docker)
        database_schema = _probe_database(test_dsn)
        expected_schema = _expected_schema_version()
        if database_schema > expected_schema:
            raise InitializationError(
                f"O banco está no schema {database_schema}, acima do schema {expected_schema} deste checkout."
            )
        _print_step(
            f"Conexão somente leitura confirmada em {TEST_DATABASE}; schema {database_schema}."
        )

        tunnel, public_url = _start_quick_tunnel(cloudflared, runtime)
        public_host = urlsplit(public_url).hostname or ""
        if not public_host.endswith(".trycloudflare.com"):
            raise InitializationError("O Cloudflare retornou um hostname público inesperado.")

        updates = {
            "GESTOR_EXPECTED_DATABASE": TEST_DATABASE,
            "GESTOR_WEB_ENV": "development",
            "GESTOR_WEB_SERVE_STATIC": "1",
            "GESTOR_WEB_ALLOWED_HOSTS": _allowed_hosts_with_tunnel(values, public_host),
            "GESTOR_WEB_PUBLIC_HOST": public_host,
            "GESTOR_WEB_COOKIE_SECURE": "1",
        }
        updates.update(simulation.env_updates())
        env_backup = _update_env(updates, runtime)
        _print_step(f".env atualizado para o hostname temporário {public_host}.")
        if simulation.enabled:
            _print_step(
                "Relógio virtual ligado: início "
                f"{simulation.reference_time}, escala {simulation.time_scale}x. "
                "Somente a fonte de tempo da API muda; banco e Windows seguem intocados."
            )

        api = _start_api(python, _child_environment(values, updates), runtime)
        local_schema, _ = _verify_application(
            LOCAL_URL,
            api_process=api,
            attempts=30,
            interval=1.0,
            simulation=simulation,
        )
        if local_schema != expected_schema:
            raise InitializationError(
                f"A API informou schema {local_schema}, mas o checkout exige schema {expected_schema}."
            )
        _print_step(
            f"Validação local concluída: health=ok, schema={local_schema}, fonte=postgresql_test_only."
        )

        public_schema, public_error = _verify_public_tunnel(
            public_url,
            api_process=api,
            tunnel_process=tunnel,
        )

        if public_schema is not None and public_schema != local_schema:
            raise InitializationError(
                "A URL pública respondeu com um schema diferente da API local."
            )

        # A partir daqui a API local e o banco TESTE já foram validados. Uma
        # eventual demora/erro transitório do edge Cloudflare não pode mais
        # provocar rollback do .env e encerramento automático da API.
        initialization_complete = True

        if public_schema is None:
            _print_step(
                "AVISO: o Quick Tunnel ainda não respondeu à validação automática "
                f"({public_error}). A API local está saudável; o túnel permanecerá ativo "
                "para permitir a propagação do Cloudflare."
            )
            schema_for_display = local_schema
        else:
            _print_step("Validação pública do Cloudflare concluída.")
            schema_for_display = public_schema

        print("\nSistema TESTE iniciado.", flush=True)
        print(f"Local:      {LOCAL_URL}", flush=True)
        print(f"Cloudflare: {public_url}", flush=True)
        print(f"Banco:      {TEST_DATABASE} (schema {schema_for_display})", flush=True)
        print(f"Logs:       {runtime}", flush=True)
        print("\nO Quick Tunnel é temporário. Pressione Ctrl+C para encerrar API e túnel.\n", flush=True)

        if open_browser:
            webbrowser.open(public_url, new=2)

        while True:
            if api.process.poll() is not None:
                raise InitializationError(
                    "A API Web encerrou inesperadamente.\n" + _tail(api.log_path)
                )
            if tunnel.process.poll() is not None:
                raise InitializationError(
                    "O Cloudflare Tunnel encerrou inesperadamente.\n" + _tail(tunnel.log_path)
                )
            time.sleep(1)
    except KeyboardInterrupt:
        if not initialization_complete:
            _restore_env(env_backup)
        _print_step("Encerramento solicitado pelo usuário.")
        return 0
    except Exception:
        if not initialization_complete:
            _restore_env(env_backup)
        raise
    finally:
        _stop_process(api)
        _stop_process(tunnel)
        _print_step("API e Cloudflare iniciados por este arquivo foram encerrados.")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inicia o Gestor no banco TESTE com Cloudflare Quick Tunnel."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="valida configuração e dependências sem alterar o .env nem iniciar processos",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="não abre a URL pública automaticamente no navegador",
    )
    parser.add_argument(
        "--simulacao",
        action="store_true",
        help="inicia a API com relógio virtual acelerado (somente banco TESTE)",
    )
    parser.add_argument(
        "--simulacao-inicio",
        metavar="ISO8601",
        help="data/hora virtual inicial, por exemplo 2026-09-14T07:40:00",
    )
    parser.add_argument(
        "--simulacao-escala",
        type=float,
        default=16.0,
        metavar="FATOR",
        help="minutos de fábrica por minuto real (padrão: 16)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    args = _parse_args(argv)
    try:
        if args.check:
            return _check_mode()
        return _run(
            open_browser=not args.no_browser,
            simulation=_simulation_options(args),
        )
    except InitializationError as exc:
        print(f"\nERRO SEGURO: {exc}", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:
        print(f"\nERRO INESPERADO: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
