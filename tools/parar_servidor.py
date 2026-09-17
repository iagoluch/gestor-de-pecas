"""Derruba o Gestor de Peças local que estiver ouvindo a porta 8001.

Uso::

    python tools/parar_servidor.py

Funciona mesmo se o servidor tiver sido iniciado fora deste script: usa a
porta como fonte de verdade (via ``netstat``), não só o PID salvo por
``iniciar_servidor.py``.
"""

from __future__ import annotations

import sys

from servidor_comum import (
    WEB_PORT,
    clear_tracked_pid,
    kill_pid,
    pids_listening_on_port,
    port_is_available,
    read_tracked_pid,
)


def main() -> int:
    if port_is_available():
        print(f"A porta {WEB_PORT} já está livre.")
        clear_tracked_pid()
        return 0

    pids = pids_listening_on_port(WEB_PORT)
    tracked = read_tracked_pid()
    if tracked and tracked not in pids:
        pids.append(tracked)
    if not pids:
        print(f"A porta {WEB_PORT} está ocupada, mas nenhum PID foi identificado. Encerre manualmente.")
        return 1

    for pid in pids:
        print(f"Encerrando processo {pid}...")
        if not kill_pid(pid):
            print(f"Não foi possível encerrar o PID {pid} (talvez já tenha terminado).")
    clear_tracked_pid()
    print("Servidor encerrado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
