"""Ambiente da simulação: quem sobe a API TESTE e com qual configuração.

A API roda em processo separado por dois motivos concretos: a seção 24 pede a
memória do processo da API isolada da memória do simulador, e a seção 40 exige
um encerramento ordenado que não dependa de matar o interpretador do simulador.

O isolamento contra o banco REAL é **estrutural**, não uma promessa:

* ``DATABASE_URL`` entra vazia no processo filho. ``python-dotenv`` roda com
  ``override=False`` e não repõe uma chave que já existe no ambiente, então o
  DSN produtivo simplesmente não existe dentro da API;
* ``Database.__init__`` (app/database/database.py) já carrega sempre
  ``load_postgres_config(testing=True)`` e recusa qualquer banco cujo nome não
  contenha ``test``;
* ``GESTOR_EXPECTED_DATABASE`` fixa o alvo exato.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import secrets
import subprocess
import sys
from typing import Any

from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict

from simulacao.config import EXPECTED_DATABASE, FORBIDDEN_DATABASE, PROJECT_ROOT, SimulationConfig


@dataclass
class ApiProcess:
    process: subprocess.Popen
    log_path: Path
    port: int

    @property
    def pid(self) -> int:
        return self.process.pid

    def vivo(self) -> bool:
        return self.process.poll() is None

    def encerrar(self, timeout: float = 25.0) -> int | None:
        """Encerramento ordenado: pede saída e só então força (seção 40)."""

        if self.process.poll() is not None:
            return self.process.returncode
        try:
            self.process.terminate()
            return self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            return self.process.wait(timeout=10)


def carregar_env_arquivo() -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in dotenv_values(PROJECT_ROOT / ".env").items()
        if value is not None
    }


def alvo_teste(env_file: dict[str, str]) -> dict[str, str]:
    dsn = (env_file.get("TEST_DATABASE_URL") or "").strip()
    if not dsn:
        raise RuntimeError("TEST_DATABASE_URL não configurada no .env.")
    return {
        str(key): str(value)
        for key, value in conninfo_to_dict(dsn).items()
        if key != "password"
    }


def test_dsn(env_file: dict[str, str]) -> str:
    return (env_file.get("TEST_DATABASE_URL") or "").strip()


def montar_ambiente(config: SimulationConfig, env_file: dict[str, str]) -> dict[str, str]:
    """Ambiente do processo da API. Nunca inclui o DSN produtivo."""

    dsn = test_dsn(env_file)
    alvo = conninfo_to_dict(dsn)
    nome_banco = str(alvo.get("dbname") or "")
    if nome_banco.casefold() != EXPECTED_DATABASE:
        raise RuntimeError(
            f"Alvo recusado: TEST_DATABASE_URL aponta para '{nome_banco}', "
            f"esperado '{EXPECTED_DATABASE}'."
        )
    if nome_banco.casefold() == FORBIDDEN_DATABASE:
        raise RuntimeError("Alvo recusado: o banco REAL nunca pode ser alvo da simulação.")

    ambiente = dict(os.environ)
    ambiente.update(env_file)
    ambiente.update(
        {
            # --- isolamento --------------------------------------------------
            "DATABASE_URL": "",
            "POSTGRES_DB": "",
            "TEST_DATABASE_URL": dsn,
            "GESTOR_EXPECTED_DATABASE": EXPECTED_DATABASE,
            "GESTOR_TEST_MODE": "1",
            # --- relógio virtual (seção 2) ------------------------------------
            "GESTOR_SIMULATION_MODE": "1",
            "GESTOR_SIMULATION_NOW": config.virtual_start.isoformat(timespec="seconds"),
            "GESTOR_SIMULATION_TIME_SCALE": f"{config.time_scale:.6f}",
            # --- web ----------------------------------------------------------
            "GESTOR_WEB_ENV": "development",
            "GESTOR_WEB_SERVE_STATIC": "1",
            "GESTOR_WEB_COOKIE_SECURE": "0",
            "GESTOR_WEB_ALLOWED_HOSTS": "127.0.0.1,localhost,testserver",
            "GESTOR_WEB_ALLOWED_ORIGINS": (
                f"http://127.0.0.1:{config.observatory_port},"
                f"http://localhost:{config.observatory_port}"
            ),
            "GESTOR_WEB_SESSION_SECRET": secrets.token_urlsafe(48),
            "GESTOR_WEB_STREAM_INTERVAL_SECONDS": "5",
            # --- integrações --------------------------------------------------
            # Recepção ProductionOrder ligada: é o pipeline canônico de ingestão.
            "GESTOR_TOTVS_ENABLED": "true",
            "GESTOR_TOTVS_SOAP_ENABLED": "true",
            # Envio ao WSPCP desligado: nenhuma produção sai daqui.
            "GESTOR_TOTVS_OUTBOX_WORKER_ENABLED": "0",
            # Ciclo do SigmaNEST desligado: a rede industrial não é alcançável
            # desta estação e o catálogo de Corte já está projetado no TESTE. O
            # botão Atualizar continua exercitável e a falha dele é observada.
            "GESTOR_SIGMANEST_SYNC_ENABLED": "0",
            "GESTOR_REPORT_AUTOMATION_ENABLED": "0",
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return ambiente


def iniciar_api(config: SimulationConfig, ambiente: dict[str, str], log_path: Path) -> ApiProcess:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8", errors="replace")
    comando = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(config.api_port),
        "--log-level",
        "info",
        "--no-access-log",
    ]
    processo = subprocess.Popen(
        comando,
        cwd=str(PROJECT_ROOT),
        env=ambiente,
        stdout=handle,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    return ApiProcess(process=processo, log_path=log_path, port=config.api_port)


def memoria_processo(pid: int) -> dict[str, Any]:
    try:
        import psutil
    except ImportError:  # pragma: no cover
        return {}
    try:
        processo = psutil.Process(pid)
        with processo.oneshot():
            memoria = processo.memory_info()
            return {
                "pid": pid,
                "rss_mb": round(memoria.rss / (1024 * 1024), 2),
                "vms_mb": round(memoria.vms / (1024 * 1024), 2),
                "threads": processo.num_threads(),
                "cpu_percent": processo.cpu_percent(interval=None),
                "conexoes": len(processo.net_connections(kind="tcp")),
            }
    except Exception:
        return {"pid": pid, "erro": "processo indisponível"}
