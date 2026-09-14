import asyncio
import unittest

from backend.api.realtime import RealtimeBroker


class RealtimeBrokerTests(unittest.IsolatedAsyncioTestCase):
    async def test_canal_emite_atualizacao_continua_sem_acao_de_apontamento(self):
        broker = RealtimeBroker()
        stream = broker.stream()
        connected = await anext(stream)
        tick = await asyncio.wait_for(anext(stream), timeout=1.5)
        await stream.aclose()

        self.assertIn("event: connected", connected)
        self.assertIn("event: refresh", tick)
        self.assertIn('"topic": "live_tick"', tick)

    async def test_publicacao_explicita_acorda_canal_imediatamente(self):
        broker = RealtimeBroker()
        stream = broker.stream()
        await anext(stream)
        broker.publish("operator_action")
        event = await asyncio.wait_for(anext(stream), timeout=0.2)
        await stream.aclose()

        self.assertIn('"topic": "operator_action"', event)


if __name__ == "__main__":
    unittest.main()
