from __future__ import annotations

from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import backup_banco_teste as backup  # noqa: E402


class _Config:
    safe_target = {"dbname": "gestor_pecas_test", "user": "gestor"}


class BackupBancoTesteTests(unittest.TestCase):
    def test_dry_run_nao_executa_docker_nem_cria_diretorio(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary) / "nao-criado"
            with (
                patch.object(backup, "_test_config", return_value=_Config()),
                patch.object(backup.subprocess, "run") as run,
                patch("sys.stdout", new_callable=io.StringIO) as stdout,
            ):
                self.assertEqual(backup.main(["--dry-run", "--output-dir", str(output_dir)]), 0)
            run.assert_not_called()
            self.assertFalse(output_dir.exists())
            self.assertEqual(json.loads(stdout.getvalue())["database"], "gestor_pecas_test")

    def test_confirmacao_errada_nao_resolve_configuracao(self):
        with (
            patch.object(backup, "_test_config") as config,
            patch("sys.stderr", new_callable=io.StringIO),
        ):
            with self.assertRaises(SystemExit):
                backup.main(["--confirmar", "gestor_pecas", "--output-dir", "C:/temp"])
        config.assert_not_called()

    def test_backup_grava_manifesto_so_depois_de_validar_o_arquivo(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            plan = backup.BackupPlan(
                database="gestor_pecas_test",
                user="gestor",
                service="postgres",
                output_dir=output_dir,
                archive_path=output_dir / "teste.dump",
                manifest_path=output_dir / "teste.dump.json",
            )

            def fake_run(command, **kwargs):
                stream = kwargs.get("stdout")
                if stream not in {None, backup.subprocess.DEVNULL}:
                    stream.write(b"PGDMP")

                class Completed:
                    returncode = 0
                    stderr = b""

                return Completed()

            with patch.object(backup.subprocess, "run", side_effect=fake_run) as run:
                manifest = backup.create_backup(
                    plan,
                    created_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
                )

            self.assertTrue(plan.archive_path.is_file())
            self.assertTrue(plan.manifest_path.is_file())
            self.assertEqual(json.loads(plan.manifest_path.read_text(encoding="utf-8")), manifest)
            self.assertEqual(run.call_count, 2)
            self.assertIn("pg_dump", run.call_args_list[0].args[0])
            self.assertIn("pg_restore", run.call_args_list[1].args[0])

    def test_falha_remove_artefatos_parciais(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            plan = backup.BackupPlan(
                database="gestor_pecas_test",
                user="gestor",
                service="postgres",
                output_dir=output_dir,
                archive_path=output_dir / "teste.dump",
                manifest_path=output_dir / "teste.dump.json",
            )
            with patch.object(backup, "_run_checked", side_effect=RuntimeError("falhou")):
                with self.assertRaisesRegex(RuntimeError, "falhou"):
                    backup.create_backup(plan)
            self.assertFalse(list(output_dir.iterdir()))


if __name__ == "__main__":
    unittest.main()
