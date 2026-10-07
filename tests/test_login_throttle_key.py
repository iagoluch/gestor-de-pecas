import unittest

from starlette.requests import Request

from backend.api.security.login_throttle import login_throttle_key


def _request(client_ip, forwarded=None):
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "headers": headers, "client": (client_ip, 1234)})


class LoginThrottleKeyTests(unittest.TestCase):
    def test_atras_do_nginx_usa_o_ip_encaminhado(self):
        self.assertEqual(login_throttle_key(_request("127.0.0.1", "10.1.2.3"), " Ana "), "10.1.2.3:ana")

    def test_conexao_direta_ignora_o_cabecalho(self):
        self.assertEqual(login_throttle_key(_request("10.1.2.9", "6.6.6.6"), "ana"), "10.1.2.9:ana")

    def test_cabecalho_invalido_no_loopback_cai_no_socket(self):
        self.assertEqual(login_throttle_key(_request("127.0.0.1", "lixo"), "ana"), "127.0.0.1:ana")


if __name__ == "__main__":
    unittest.main()
