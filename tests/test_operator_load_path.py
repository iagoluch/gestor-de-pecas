"""Regressões do caminho do operador sob carga (BK-01)."""

import unittest
from types import SimpleNamespace

import anyio

from app.database.database import Database
from backend.api.dependencies.bulkhead import management_read_slot


class _PoolQueNaoPodeSerUsado:
    def __init__(self):
        self.checkouts = 0

    def connection(self):
        self.checkouts += 1
        return SimpleNamespace()


class ConexaoReentranteTests(unittest.TestCase):
    def _db(self):
        db = object.__new__(Database)
        db._pool = _PoolQueNaoPodeSerUsado()
        return db

    def test_leitura_aninhada_reusa_a_conexao_da_transacao(self):
        # Pedir outra conexão com uma já presa é hold-and-wait: 40 ações num
        # pool de 4 esgotavam o PGPOOL_TIMEOUT e viravam 503.
        db = self._db()
        conexao = object()
        cursor = SimpleNamespace(connection=conexao)
        with db._na_conexao_da_transacao(cursor):
            with db.connection() as usada:
                self.assertIs(usada, conexao)
        self.assertEqual(db._pool.checkouts, 0)

    def test_fora_do_escopo_e_em_outro_banco_volta_ao_pool(self):
        db, outro = self._db(), self._db()
        with db._na_conexao_da_transacao(SimpleNamespace(connection=object())):
            outro.connection()
        db.connection()
        with db._na_conexao_da_transacao(None):
            db.connection()
        self.assertEqual((db._pool.checkouts, outro._pool.checkouts), (2, 1))


class BulkheadGerencialTests(unittest.TestCase):
    def test_leituras_gerenciais_respeitam_o_teto_e_gravacoes_passam(self):
        app = SimpleNamespace(state=SimpleNamespace(management_read_limiter=anyio.CapacityLimiter(2)))
        dentro = {"GET": 0, "POST": 0}
        pico = {"GET": 0, "POST": 0}

        async def requisicao(metodo):
            slot = management_read_slot(SimpleNamespace(method=metodo, app=app))
            await slot.__anext__()
            dentro[metodo] += 1
            pico[metodo] = max(pico[metodo], dentro[metodo])
            await anyio.sleep(0.02)
            dentro[metodo] -= 1
            await slot.aclose()

        async def cenario():
            async with anyio.create_task_group() as grupo:
                for metodo in ["GET"] * 6 + ["POST"] * 4:
                    grupo.start_soon(requisicao, metodo)

        anyio.run(cenario)
        self.assertEqual(pico, {"GET": 2, "POST": 4})


if __name__ == "__main__":
    unittest.main()
