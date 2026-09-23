"""Gera e verifica um backup PostgreSQL restaurável do banco oficial de TESTE.

O script só aceita ``gestor_pecas_test`` e exige a confirmação literal antes de
executar ``pg_dump``. A saída é um arquivo custom do PostgreSQL (``.dump``),
verificado com ``pg_restore --list`` e acompanhado de um manifesto SHA-256.
Ele não remove backups antigos, não agenda execução e não copia dados para fora
da máquina: retenção, destino externo e teste de restauração são decisões de
operação que permanecem explícitas.

Uso::

    python scripts/backup_banco_teste.py --dry-run --output-dir D:\\backups\\gestor
    python scripts/backup_banco_teste.py --confirmar gestor_pecas_test \\
        --output-dir D:\\backups\\gestor
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from psycopg.conninfo import conninfo_to_dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.config import load_postgres_config  # noqa: E402


EXPECTED_DATABASE = "gestor_pecas_test"


@dataclass(frozen=True)
class BackupPlan:
    database: str
    user: str
    service: str
    output_dir: Path
    archive_path: Path
    manifest_path: Path


def _test_config():
    configured_guard = str(os.environ.get("GESTOR_EXPECTED_DATABASE") or "").strip()
    if configured_guard and configured_guard != EXPECTED_DATABASE:
        raise RuntimeError(
            "Backup recusado: GESTOR_EXPECTED_DATABASE deve ser exatamente "
            f"{EXPECTED_DATABASE!r}."
        )
    environ = dict(os.environ)
    environ["GESTOR_EXPECTED_DATABASE"] = EXPECTED_DATABASE
    config = load_postgres_config(testing=True, environ=environ)
    database = str(conninfo_to_dict(config.dsn).get("dbname") or "").strip()
    if database != EXPECTED_DATABASE:
        raise RuntimeError(
            "Backup recusado: TEST_DATABASE_URL deve apontar exatamente para "
            f"{EXPECTED_DATABASE!r}, não para {database!r}."
        )
    return config


def _build_plan(*, output_dir: Path, service: str, now: datetime) -> BackupPlan:
    config = _test_config()
    target = config.safe_target
    database = str(target["dbname"])
    user = str(target["user"])
    if not user:
        raise RuntimeError("Backup recusado: usuário do banco TESTE ausente.")
    stamp = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid4().hex[:8]
    filename = f"{database}_{stamp}_{suffix}.dump"
    resolved_output = output_dir.expanduser().resolve()
    return BackupPlan(
        database=database,
        user=user,
        service=str(service or "").strip() or "postgres",
        output_dir=resolved_output,
        archive_path=resolved_output / filename,
        manifest_path=resolved_output / f"{filename}.json",
    )


def _docker_command(plan: BackupPlan, *postgres_args: str) -> list[str]:
    return ["docker", "compose", "exec", "-T", plan.service, *postgres_args]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_checked(command: list[str], *, stdout=None, stdin=None) -> None:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        stdin=stdin,
        stdout=stdout,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Comando de backup falhou ({completed.returncode}): {detail}")


def create_backup(plan: BackupPlan, *, created_at: datetime | None = None) -> dict:
    """Executa dump, valida o formato e grava manifesto atômico."""

    plan.output_dir.mkdir(parents=True, exist_ok=True)
    partial_archive = plan.archive_path.with_suffix(plan.archive_path.suffix + ".partial")
    partial_manifest = plan.manifest_path.with_suffix(plan.manifest_path.suffix + ".partial")
    if plan.archive_path.exists() or plan.manifest_path.exists():
        raise RuntimeError(f"Backup recusado: destino já existe: {plan.archive_path.name}.")
    try:
        with partial_archive.open("xb") as output:
            _run_checked(
                _docker_command(
                    plan,
                    "pg_dump",
                    "-U",
                    plan.user,
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    "--dbname",
                    plan.database,
                ),
                stdout=output,
            )
        if not partial_archive.stat().st_size:
            raise RuntimeError("Backup recusado: pg_dump produziu arquivo vazio.")
        with partial_archive.open("rb") as source:
            _run_checked(
                _docker_command(plan, "pg_restore", "--list"),
                stdout=subprocess.DEVNULL,
                stdin=source,
            )
        partial_archive.replace(plan.archive_path)
        manifest = {
            "created_at": (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
            "database": plan.database,
            "format": "postgresql-custom",
            "archive": plan.archive_path.name,
            "bytes": plan.archive_path.stat().st_size,
            "sha256": _sha256(plan.archive_path),
            "verification": "pg_restore --list passou sem restaurar dados",
            "restore_requirement": "restaurar somente em banco descartável e isolado",
        }
        with partial_manifest.open("x", encoding="utf-8") as output:
            json.dump(manifest, output, ensure_ascii=False, indent=2)
            output.write("\n")
        partial_manifest.replace(plan.manifest_path)
        return manifest
    except Exception:
        partial_archive.unlink(missing_ok=True)
        partial_manifest.unlink(missing_ok=True)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backup restaurável do banco oficial de TESTE.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="mostra o plano sem executar Docker ou criar arquivos")
    mode.add_argument("--confirmar", metavar="BANCO", help="deve ser literalmente gestor_pecas_test")
    parser.add_argument("--output-dir", required=True, type=Path, help="diretório local para o dump e manifesto")
    parser.add_argument("--docker-service", default="postgres", help="serviço PostgreSQL no compose (padrão: postgres)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.dry_run and str(args.confirmar or "").strip() != EXPECTED_DATABASE:
        _parser().error(f"--confirmar deve ser literalmente {EXPECTED_DATABASE!r}.")
    plan = _build_plan(
        output_dir=args.output_dir,
        service=args.docker_service,
        now=datetime.now(timezone.utc),
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "database": plan.database,
                    "output_dir": str(plan.output_dir),
                    "archive": plan.archive_path.name,
                    "docker_service": plan.service,
                    "will_verify": "pg_restore --list",
                },
                ensure_ascii=False,
            )
        )
        return 0
    manifest = create_backup(plan)
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
