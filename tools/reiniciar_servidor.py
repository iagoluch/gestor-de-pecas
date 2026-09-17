"""Reinicia o Gestor de Peças local: derruba o que estiver na porta 8001 e sobe de novo.

Uso::

    python tools/reiniciar_servidor.py

O backend não recarrega código Python sozinho (uvicorn roda sem
``--reload``): depois de qualquer alteração em rotas, serviços ou nos
exportadores de relatório, rode este script para ver o efeito. Mudanças só
de frontend não precisam disso — use a tela Sistema > Rebuild frontend
(o servidor serve ``web/dist`` direto, sem cache).
"""

from __future__ import annotations

import sys
import time

import iniciar_servidor
import parar_servidor
from servidor_comum import WEB_PORT, port_is_available


def main() -> int:
    parar_servidor.main()
    for _ in range(20):
        if port_is_available():
            break
        time.sleep(0.5)
    else:
        print(f"A porta {WEB_PORT} continua ocupada; encerre manualmente antes de tentar de novo.")
        return 1
    return iniciar_servidor.main()


if __name__ == "__main__":
    sys.exit(main())
