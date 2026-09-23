"""Chave segura e consistente para o freio de autenticação."""

import ipaddress

from fastapi import Request

from backend.integrations.totvs_soap import _arrived_through_public_host


def login_throttle_key(request: Request, username: str) -> str:
    """Combina usuário e IP efetivo sem confiar em cabeçalhos arbitrários.

    O Cloudflare Tunnel termina no loopback. O cabeçalho ``CF-Connecting-IP``
    só é aceito nesse caminho identificado pelo hostname público configurado e
    quando contém um endereço IP válido.
    """

    client = request.client
    ip = str(getattr(client, "host", "") or "desconhecido")
    if ip in {"127.0.0.1", "::1", "localhost"} and _arrived_through_public_host(request):
        forwarded = str(request.headers.get("CF-Connecting-IP") or "").strip()
        try:
            ipaddress.ip_address(forwarded)
        except ValueError:
            pass
        else:
            ip = forwarded
    return f"{ip}:{username.strip().casefold()}"
