"""O estado de sincronização enviado ao operador não vaza o texto bruto do erro."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from backend.api.routers.cutting import _sync_state
from mes.services.sigmanest_refresh import SigmaNestRefreshCoordinator, SigmaNestRefreshState


def _request(ultimo_erro):
    state = SigmaNestRefreshState()
    state.ultimo_erro = ultimo_erro
    coordinator = SimpleNamespace(state=state)
    app_state = SimpleNamespace(
        sigmanest_refresh=coordinator,
        settings=SimpleNamespace(sigmanest_sync_enabled=True),
    )
    return SimpleNamespace(app=SimpleNamespace(state=app_state))


class CuttingSyncStateTests(unittest.TestCase):
    def test_erro_bruto_do_odbc_nao_chega_ao_operador(self):
        bruto = "[08001] Server=SQL-PROD;Database=SigmaNest;UID=svc_mes"
        estado = _sync_state(_request(bruto), SimpleNamespace())
        self.assertEqual(estado["erro"], SigmaNestRefreshCoordinator.MENSAGEM_ERRO)
        self.assertNotIn("SQL-PROD", str(estado))

    def test_sem_erro_continua_nulo(self):
        self.assertIsNone(_sync_state(_request(None), SimpleNamespace())["erro"])


if __name__ == "__main__":
    unittest.main()
