import importlib
import os
from pathlib import Path
import unittest


class ImportCompatibilityTests(unittest.TestCase):
    def test_backend_web_and_package_imports_continue_working(self):
        from app.database.database import Database, limpa_codigo
        from backend.api.main import create_app
        from mes.services.operational_reports import OperationalReportService
        from mes.services.production import ProductionService
        from mes.services.task_lookup import TarefaLookupService

        self.assertTrue(callable(Database))
        self.assertEqual(limpa_codigo(" t100 "), "T100")
        self.assertTrue(callable(create_app))
        self.assertTrue(callable(TarefaLookupService))
        self.assertTrue(callable(ProductionService))
        self.assertTrue(callable(OperationalReportService))

    def test_new_package_imports_continue_working(self):
        modules = [
            "backend.api.main",
            "backend.api.routers.operator",
            "app.database.database",
            "mes.domain.operator_state_machine",
            "mes.services.task_lookup",
            "mes.services.production",
            "mes.services.operational_reports",
            "mes.contracts.corporate",
            "mes.services.corporate_integration",
        ]
        loaded = [importlib.import_module(name) for name in modules]
        self.assertEqual(len(loaded), len(modules))
        self.assertTrue(hasattr(loaded[0], "create_app"))

    def test_entrypoints_e_pacotes_desktop_foram_removidos(self):
        for path in (
            "gestordepeca.py",
            "gestordepeca_teste.py",
            os.path.join("app", "main_window.py"),
            os.path.join("app", "launcher.py"),
            os.path.join("app", "ui", "__init__.py"),
        ):
            self.assertFalse(Path(path).exists(), path)

    def test_pacote_qlik_nao_existe_mais(self):
        """Wave 3: o pacote saiu do repositório, não só do import."""

        self.assertFalse(Path("qlik").exists())
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("qlik")

    def test_legacy_root_wrappers_were_removed(self):
        for path in (
            "database.py",
            "dashboard.py",
            "historico.py",
            "relatorios.py",
            "widgets.py",
            "qlik_reader.py",
            os.path.join("mes", "runtime.py"),
        ):
            self.assertFalse(os.path.exists(path), path)


if __name__ == "__main__":
    unittest.main()
