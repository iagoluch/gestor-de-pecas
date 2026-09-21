"""Reconstrói o frontend e reinicia o ambiente TESTE local.

Uso::

    python reiniciar_build.py

O comando falha antes de reiniciar o backend se o build do frontend não passar.
Assim a porta 8001 nunca fica servindo uma versão parcialmente compilada.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"


def run(command: list[str], *, cwd: Path) -> None:
    print(f"> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    try:
        run([npm, "run", "build"], cwd=WEB)
        run([sys.executable, str(ROOT / "tools" / "reiniciar_servidor.py")], cwd=ROOT)
    except subprocess.CalledProcessError as exc:
        print(f"Comando falhou com código {exc.returncode}.", file=sys.stderr)
        return exc.returncode or 1
    print("Build do frontend e backend TESTE reiniciados com sucesso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
