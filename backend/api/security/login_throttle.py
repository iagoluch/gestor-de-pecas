"""Chave segura e consistente para o freio de autenticação."""

import ipaddress

from fastapi import Request


def login_throttle_key(request: Request, username: str) -> str:
    """Combina usuário e IP efetivo sem confiar em cabeçalhos arbitrários.

    Atrás do nginx da VM todos chegam pelo loopback, e o nginx sobrescreve
    ``X-Forwarded-For`` com o IP real (deploy/nginx.conf). Só nesse caminho o
    cabeçalho é aceito, e só se for um IP válido; conexão direta (ex.: LAN na
    :8001) usa o IP do socket e ignora o cabeçalho.
    """

    client = request.client
    ip = str(getattr(client, "host", "") or "desconhecido")
    if ip in {"127.0.0.1", "::1", "localhost"}:
        forwarded = str(request.headers.get("X-Forwarded-For") or "").strip()
        try:
            ipaddress.ip_address(forwarded)
        except ValueError:
            pass
        else:
            ip = forwarded
    return f"{ip}:{username.strip().casefold()}"
