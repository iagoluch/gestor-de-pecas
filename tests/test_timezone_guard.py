"""BK-11: o processo recusa subir com o SO fora do fuso da aplicação."""

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import sys
import unittest

from app.database.config import PostgresConfig, verificar_fuso_do_host
from app.database.connection import PostgresPoolManager
from app.database.errors import DatabaseConfigurationError

ROOT = Path(__file__).resolve().parents[1]


def _rodar_com_tz(tz: str, codigo: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "TZ": tz, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


class FusoDoHostTests(unittest.TestCase):
    def test_host_em_utc_e_recusado_com_mensagem_clara(self):
        with self.assertRaises(DatabaseConfigurationError) as erro:
            verificar_fuso_do_host(
                "America/Sao_Paulo", agora=datetime(2026, 9, 29, 12, tzinfo=timezone.utc)
            )
        self.assertIn("UTC+00:00", str(erro.exception))
        self.assertIn("America/Sao_Paulo (UTC-03:00)", str(erro.exception))

    def test_host_no_fuso_da_aplicacao_passa(self):
        brt = timezone(timedelta(hours=-3))
        verificar_fuso_do_host("America/Sao_Paulo", agora=datetime(2026, 9, 29, 12, tzinfo=brt))

    def test_fuso_configurado_invalido_e_recusado(self):
        with self.assertRaises(DatabaseConfigurationError):
            verificar_fuso_do_host("America/Nao_Existe")

    def test_startup_da_api_com_tz_utc_nao_sobe(self):
        recusado = _rodar_com_tz("UTC0", "import backend.api.main")
        self.assertNotEqual(recusado.returncode, 0)
        self.assertIn("diverge do fuso da aplicação America/Sao_Paulo", recusado.stderr)
        # Controle positivo: o mesmo import sobe com o SO em UTC-3.
        aceito = _rodar_com_tz("BRT3", "import backend.api.main")
        self.assertEqual(aceito.returncode, 0, aceito.stderr[-2000:])

    def test_pool_de_script_tambem_recusa(self):
        codigo = (
            "from app.database.config import PostgresConfig\n"
            "from app.database.connection import PostgresPoolManager\n"
            "PostgresPoolManager(PostgresConfig('postgresql://x@127.0.0.1:1/x_test'),"
            " open_immediately=False)\n"
        )
        recusado = _rodar_com_tz("UTC0", codigo)
        self.assertNotEqual(recusado.returncode, 0)
        self.assertIn("DatabaseConfigurationError", recusado.stderr)


class _ConexaoQueRecusaSetConfig:
    def __init__(self):
        self.comandos = []

    def execute(self, sql, params=None):
        self.comandos.append(sql)
        raise RuntimeError("permission denied to set parameter")

    def commit(self):
        raise AssertionError("não deveria confirmar após falha")


class ConfiguracaoDeSessaoTests(unittest.TestCase):
    def test_set_config_falho_nao_entrega_conexao_ao_pool(self):
        # Antes era só um warning e a conexão seguia com o fuso do servidor.
        gerente = PostgresPoolManager.__new__(PostgresPoolManager)
        gerente.config = PostgresConfig(dsn="postgresql://x@127.0.0.1:1/x_test")
        conexao = _ConexaoQueRecusaSetConfig()
        with self.assertRaises(RuntimeError):
            gerente._configure_session(conexao)
        self.assertEqual(len(conexao.comandos), 1)
        self.assertIn("TimeZone", conexao.comandos[0])


if __name__ == "__main__":
    unittest.main()
