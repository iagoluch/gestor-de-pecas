"""Gera, verifica e restaura backups PostgreSQL do banco oficial de TESTE.

O backup só aceita ``gestor_pecas_test`` e exige a confirmação literal antes de
executar ``pg_dump``. A saída é um arquivo custom do PostgreSQL (``.dump``),
verificado com ``pg_restore --list`` e acompanhado de um manifesto SHA-256.
A restauração só aceita um banco descartável ``gestor_restore_*`` já criado e
vazio, e confere o manifesto antes de gravar qualquer dado.

O script não remove backups antigos, não agenda execução e não copia dados para
fora da máquina: agendamento, retenção, cópia externa, monitoramento e ensaio
de restauração são responsabilidade da infraestrutura (docs/BACKUP_TESTE.md).

Códigos de saída: 0 sucesso; 1 falha de execução (Docker/pg_dump/pg_restore);
2 uso inválido ou alvo recusado; 3 falha de integridade (manifesto/SHA-256).

Uso::

    python scripts/backup_banco_teste.py --dry-run --output-dir backups/test
    python scripts/backup_banco_teste.py --confirmar gestor_pecas_test --output-dir backups/test
    python scripts/backup_banco_teste.py --verificar backups/test/<arquivo>.dump
    python scripts/backup_banco_teste.py --restaurar backups/test/<arquivo>.dump \\
        --alvo gestor_restore_ensaio --confirmar-alvo gestor_restore_ensaio
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

from psycopg.conninfo import conninfo_to_dict


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.config import load_postgres_config  # noqa: E402


EXPECTED_DATABASE = "gestor_pecas_test"
RESTORE_PREFIX = "gestor_restore_"
# Bancos que nunca podem receber uma restauração, mesmo com o prefixo correto.
PROTECTED_DATABASES = frozenset(
    {"gestor_pecas", EXPECTED_DATABASE, "postgres", "template0", "template1"}
)
_RESTORE_NAME = re.compile(r"^[a-z0-9_]{1,63}$")

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_REFUSED = 2
EXIT_INTEGRITY = 3


class BackupRefused(RuntimeError):
    """Alvo ou configuração recusados antes de qualquer efeito."""


class BackupIntegrityError(RuntimeError):
    """Arquivo divergente do manifesto ou estrutura inválida."""


def _log(event: str, **fields) -> None:
    record = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    print(json.dumps(record, ensure_ascii=False, default=str), file=sys.stderr, flush=True)


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
        raise BackupRefused(
            "Backup recusado: GESTOR_EXPECTED_DATABASE deve ser exatamente "
            f"{EXPECTED_DATABASE!r}."
        )
    environ = dict(os.environ)
    environ["GESTOR_EXPECTED_DATABASE"] = EXPECTED_DATABASE
    config = load_postgres_config(testing=True, environ=environ)
    database = str(conninfo_to_dict(config.dsn).get("dbname") or "").strip()
    if database != EXPECTED_DATABASE:
        raise BackupRefused(
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
        raise BackupRefused("Backup recusado: usuário do banco TESTE ausente.")
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


def _run_checked(command: list[str], *, stdout=None, stdin=None):
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
    return completed


def create_backup(plan: BackupPlan, *, created_at: datetime | None = None) -> dict:
    """Executa dump, valida o formato e grava manifesto atômico."""

    plan.output_dir.mkdir(parents=True, exist_ok=True)
    partial_archive = plan.archive_path.with_suffix(plan.archive_path.suffix + ".partial")
    partial_manifest = plan.manifest_path.with_suffix(plan.manifest_path.suffix + ".partial")
    if plan.archive_path.exists() or plan.manifest_path.exists():
        raise BackupRefused(f"Backup recusado: destino já existe: {plan.archive_path.name}.")
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


def _compose_command(service: str, *postgres_args: str) -> list[str]:
    return ["docker", "compose", "exec", "-T", str(service or "").strip() or "postgres", *postgres_args]


def _load_manifest(archive: Path) -> dict:
    manifest_path = archive.with_name(archive.name + ".json")
    if not archive.is_file():
        raise BackupIntegrityError(f"Arquivo de backup não encontrado: {archive.name}.")
    if not manifest_path.is_file():
        raise BackupIntegrityError(f"Manifesto ausente: {manifest_path.name}.")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BackupIntegrityError(f"Manifesto ilegível: {manifest_path.name}.") from exc
    if not isinstance(manifest, dict) or manifest.get("archive") != archive.name:
        raise BackupIntegrityError("Manifesto não corresponde a este arquivo de backup.")
    if manifest.get("database") != EXPECTED_DATABASE:
        raise BackupIntegrityError(
            f"Manifesto de banco inesperado: {manifest.get('database')!r}."
        )
    return manifest


def verify_backup(archive: Path, *, service: str = "postgres") -> dict:
    """Confere tamanho e SHA-256 contra o manifesto e a estrutura com pg_restore --list."""

    archive = archive.expanduser().resolve()
    manifest = _load_manifest(archive)
    size = archive.stat().st_size
    if size != manifest.get("bytes"):
        raise BackupIntegrityError(
            f"Tamanho divergente do manifesto: {size} != {manifest.get('bytes')}."
        )
    digest = _sha256(archive)
    if digest != manifest.get("sha256"):
        raise BackupIntegrityError("SHA-256 divergente do manifesto: arquivo alterado ou corrompido.")
    with archive.open("rb") as source:
        try:
            _run_checked(
                _compose_command(service, "pg_restore", "--list"),
                stdout=subprocess.DEVNULL,
                stdin=source,
            )
        except RuntimeError as exc:
            raise BackupIntegrityError(f"pg_restore --list recusou o arquivo: {exc}") from exc
    return {"archive": archive.name, "bytes": size, "sha256": digest, "verified": True}


def _configured_database_names() -> set[str]:
    names = set()
    for key in ("DATABASE_URL", "TEST_DATABASE_URL"):
        dsn = str(os.environ.get(key) or "").strip()
        if not dsn:
            continue
        try:
            name = str(conninfo_to_dict(dsn).get("dbname") or "").strip()
        except Exception:  # DSN inválido não pode liberar a restauração
            continue
        if name:
            names.add(name)
    return names


def validate_restore_target(target: str | None, confirmation: str | None) -> str:
    """Só aceita banco descartável gestor_restore_*, confirmado literalmente."""

    name = str(target or "").strip()
    if not name:
        raise BackupRefused("Restauração recusada: informe --alvo.")
    if name != str(confirmation or "").strip():
        raise BackupRefused("Restauração recusada: --confirmar-alvo deve repetir --alvo literalmente.")
    if not _RESTORE_NAME.match(name) or not name.startswith(RESTORE_PREFIX):
        raise BackupRefused(
            f"Restauração recusada: o alvo deve começar com {RESTORE_PREFIX!r} "
            "e conter só letras minúsculas, dígitos e '_'."
        )
    if name in PROTECTED_DATABASES or name in _configured_database_names():
        raise BackupRefused(f"Restauração recusada: {name!r} é um banco protegido.")
    return name


def restore_backup(archive: Path, *, target: str, user: str, service: str = "postgres") -> dict:
    """Restaura um backup verificado em banco descartável, já criado e vazio."""

    verification = verify_backup(archive, service=service)
    probe = _run_checked(
        _compose_command(
            service,
            "psql",
            "-U",
            user,
            "-d",
            target,
            "-tAc",
            "SELECT count(*) FROM pg_tables "
            "WHERE schemaname NOT IN ('pg_catalog', 'information_schema')",
        ),
        stdout=subprocess.PIPE,
    )
    tables = (probe.stdout or b"").decode("utf-8", errors="replace").strip()
    if tables != "0":
        raise BackupRefused(
            f"Restauração recusada: o banco {target!r} não está vazio (tabelas: {tables or '?'})."
        )
    with archive.expanduser().resolve().open("rb") as source:
        _run_checked(
            _compose_command(
                service,
                "pg_restore",
                "-U",
                user,
                "--dbname",
                target,
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                "--single-transaction",
            ),
            stdin=source,
        )
    return {**verification, "restored_to": target}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backup restaurável do banco oficial de TESTE.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="mostra o plano sem executar Docker ou criar arquivos")
    mode.add_argument("--confirmar", metavar="BANCO", help="deve ser literalmente gestor_pecas_test")
    mode.add_argument("--verificar", metavar="ARQUIVO", type=Path, help="confere manifesto, SHA-256 e pg_restore --list")
    mode.add_argument("--restaurar", metavar="ARQUIVO", type=Path, help="restaura em banco descartável gestor_restore_*")
    parser.add_argument("--output-dir", type=Path, help="diretório local para o dump e manifesto (backup/dry-run)")
    parser.add_argument("--alvo", help="banco de destino da restauração (gestor_restore_*)")
    parser.add_argument("--confirmar-alvo", help="repetição literal de --alvo")
    parser.add_argument("--docker-service", default="postgres", help="serviço PostgreSQL no compose (padrão: postgres)")
    return parser


def _run(args, parser: argparse.ArgumentParser) -> int:
    if args.verificar is not None:
        _log("verify_started", archive=str(args.verificar))
        result = verify_backup(args.verificar, service=args.docker_service)
        _log("verify_ok", **result)
        print(json.dumps(result, ensure_ascii=False))
        return EXIT_OK
    if args.restaurar is not None:
        target = validate_restore_target(args.alvo, args.confirmar_alvo)
        user = str(_test_config().safe_target["user"] or "").strip()
        if not user:
            raise BackupRefused("Restauração recusada: usuário do banco TESTE ausente.")
        _log("restore_started", archive=str(args.restaurar), target=target)
        result = restore_backup(args.restaurar, target=target, user=user, service=args.docker_service)
        _log("restore_ok", **result)
        print(json.dumps(result, ensure_ascii=False))
        return EXIT_OK
    if args.output_dir is None:
        parser.error("--output-dir é obrigatório para --dry-run e --confirmar.")
    if not args.dry_run and str(args.confirmar or "").strip() != EXPECTED_DATABASE:
        parser.error(f"--confirmar deve ser literalmente {EXPECTED_DATABASE!r}.")
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
        return EXIT_OK
    _log("backup_started", database=plan.database, archive=plan.archive_path.name)
    manifest = create_backup(plan)
    _log("backup_ok", archive=manifest["archive"], bytes=manifest["bytes"], sha256=manifest["sha256"])
    print(json.dumps(manifest, ensure_ascii=False))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return _run(args, parser)
    except BackupRefused as exc:
        _log("refused", reason=str(exc))
        return EXIT_REFUSED
    except BackupIntegrityError as exc:
        _log("integrity_failed", reason=str(exc))
        return EXIT_INTEGRITY
    except (RuntimeError, OSError) as exc:
        _log("failed", reason=str(exc))
        return EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
