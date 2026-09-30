import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.static import SpaStaticFiles


class SpaFallbackTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        Path(self._tmp.name, "index.html").write_text("<html>spa</html>", encoding="utf-8")
        app = FastAPI()
        app.mount("/", SpaStaticFiles(self._tmp.name), name="web")
        self.client = TestClient(app)

    def tearDown(self):
        self._tmp.cleanup()

    def test_rota_do_react_cai_no_index(self):
        response = self.client.get("/operador/123")
        self.assertEqual(response.status_code, 200)
        self.assertIn("spa", response.text)

    def test_rota_de_api_inexistente_devolve_404_e_nao_o_index(self):
        response = self.client.get("/api/v1/ready")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("spa", response.text)


if __name__ == "__main__":
    unittest.main()
