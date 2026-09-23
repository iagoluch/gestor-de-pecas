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


def _completed(stdout: bytes = b""):
    class Completed:
        returncode = 0
        stderr = b""

    result = Completed()
    result.stdout = stdout
    return result


class VerificarERestaurarTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.archive = Path(self._temporary.name) / "gestor_pecas_test_x.dump"
        self.archive.write_bytes(b"PGDMP-conteudo")
        self.manifest = {
            "database": "gestor_pecas_test",
            "archive": self.archive.name,
            "bytes": self.archive.stat().st_size,
            "sha256": backup._sha256(self.archive),
        }
        self._write_manifest()

    def _write_manifest(self):
        Path(str(self.archive) + ".json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def _main(self, *argv):
        with patch("sys.stdout", new_callable=io.StringIO), patch("sys.stderr", new_callable=io.StringIO) as err:
            code = backup.main(list(argv))
        return code, err.getvalue()

    def test_verificar_confere_manifesto_e_estrutura(self):
        with patch.object(backup.subprocess, "run", return_value=_completed()) as run:
            code, log = self._main("--verificar", str(self.archive))
        self.assertEqual(code, backup.EXIT_OK)
        self.assertIn("pg_restore", run.call_args.args[0])
        self.assertIn('"verify_ok"', log)

    def test_verificar_com_sha_divergente_sai_com_codigo_de_integridade(self):
        self.archive.write_bytes(b"PGDMP-conteuXo")  # mesmo tamanho, conteúdo diferente
        with patch.object(backup.subprocess, "run") as run:
            code, log = self._main("--verificar", str(self.archive))
        self.assertEqual(code, backup.EXIT_INTEGRITY)
        run.assert_not_called()
        self.assertIn('"integrity_failed"', log)

    def test_verificar_sem_manifesto_sai_com_codigo_de_integridade(self):
        Path(str(self.archive) + ".json").unlink()
        with patch.object(backup.subprocess, "run") as run:
            code, _ = self._main("--verificar", str(self.archive))
        self.assertEqual(code, backup.EXIT_INTEGRITY)
        run.assert_not_called()

    def test_restaurar_recusa_alvo_errado_sem_tocar_no_docker(self):
        casos = [
            ("gestor_pecas", "gestor_pecas"),  # banco REAL
            ("gestor_pecas_test", "gestor_pecas_test"),  # banco TESTE de origem
            ("postgres", "postgres"),
            ("gestor_restore_x", "gestor_restore_y"),  # confirmação divergente
            ("outro_banco", "outro_banco"),  # sem o prefixo descartável
            ("gestor_restore_X;drop", "gestor_restore_X;drop"),
        ]
        for alvo, confirmacao in casos:
            with self.subTest(alvo=alvo), patch.object(backup, "_test_config") as config, patch.object(
                backup.subprocess, "run"
            ) as run:
                code, log = self._main(
                    "--restaurar", str(self.archive), "--alvo", alvo, "--confirmar-alvo", confirmacao
                )
                self.assertEqual(code, backup.EXIT_REFUSED)
                run.assert_not_called()
                config.assert_not_called()
                self.assertIn('"refused"', log)

    def test_restaurar_recusa_alvo_que_ja_tem_tabelas(self):
        respostas = [_completed(), _completed(b"12\n")]
        with patch.object(backup, "_test_config", return_value=_Config()), patch.object(
            backup.subprocess, "run", side_effect=respostas
        ) as run:
            code, _ = self._main(
                "--restaurar", str(self.archive), "--alvo", "gestor_restore_ensaio",
                "--confirmar-alvo", "gestor_restore_ensaio",
            )
        self.assertEqual(code, backup.EXIT_REFUSED)
        self.assertEqual(run.call_count, 2)  # verificação + sonda; nenhum pg_restore de dados

    def test_restaurar_em_alvo_vazio_executa_pg_restore_no_alvo(self):
        respostas = [_completed(), _completed(b"0\n"), _completed()]
        with patch.object(backup, "_test_config", return_value=_Config()), patch.object(
            backup.subprocess, "run", side_effect=respostas
        ) as run:
            code, log = self._main(
                "--restaurar", str(self.archive), "--alvo", "gestor_restore_ensaio",
                "--confirmar-alvo", "gestor_restore_ensaio",
            )
        self.assertEqual(code, backup.EXIT_OK)
        restore_command = run.call_args_list[-1].args[0]
        self.assertIn("pg_restore", restore_command)
        self.assertIn("gestor_restore_ensaio", restore_command)
        self.assertIn("--single-transaction", restore_command)
        self.assertIn('"restore_ok"', log)

    def test_falha_do_docker_sai_com_codigo_de_execucao(self):
        with patch.object(backup, "_test_config", return_value=_Config()), patch.object(
            backup, "_run_checked", side_effect=RuntimeError("docker indisponível")
        ):
            code, log = self._main("--confirmar", "gestor_pecas_test", "--output-dir", self._temporary.name)
        self.assertEqual(code, backup.EXIT_FAILURE)
        self.assertIn('"failed"', log)


if __name__ == "__main__":
    unittest.main()
