"""Executa a simulação industrial prolongada (soak) no ambiente TESTE.

Uso típico::

    python scripts/run_simulacao_industrial.py --duration 60m --factory-duration 8h --seed 20260912

A velocidade virtual é derivada de ``factory-duration / duration``; ela não é
digitada. Nada é executado se o pre-flight reprovar.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from simulacao.config import load_config  # noqa: E402
from simulacao.runner import SimulationRunner  # noqa: E402


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Simulação industrial prolongada do Gestor de Peças (somente TESTE)."
    )
    parser.add_argument("--duration", default="60m", help="Duração real (ex.: 60m).")
    parser.add_argument("--factory-duration", default="8h", help="Duração virtual (ex.: 8h).")
    parser.add_argument("--seed", type=int, default=20260912, help="Seed determinístico.")
    parser.add_argument(
        "--virtual-start",
        default=None,
        help="Início virtual ISO 8601 (padrão vem de config/simulacao_industrial.json).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Arquivo JSON do cenário; pode declarar base_config para herdar a configuração industrial.",
    )
    parser.add_argument("--api-port", type=int, default=None, help="Porta da API TESTE.")
    parser.add_argument(
        "--observatory-port", type=int, default=None, help="Porta do observatório."
    )
    parser.add_argument(
        "--ops-iniciais", type=int, default=None,
        help="Sobrepõe o tamanho do lote inicial de OPs sintéticas.",
    )
    parser.add_argument(
        "--ops-continuas", type=int, default=None,
        help="Sobrepõe o total de OPs liberadas ao longo do turno.",
    )
    parser.add_argument(
        "--sem-observatorio",
        action="store_true",
        help="Não sobe o observatório nem os viewports (execução headless).",
    )
    parser.add_argument(
        "--sem-capturas",
        action="store_true",
        help="Não abre o Chrome headless de captura visual.",
    )
    return parser.parse_args(argv)


def _console_utf8() -> None:
    """O console do Windows nasce em cp1252 e engasga com '→' ou '×'.

    Reconfigurar aqui evita que uma linha de log derrube uma execução de uma
    hora por causa de um caractere.
    """

    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if callable(reconfigurar):
            try:
                reconfigurar(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv=None) -> int:
    _console_utf8()
    args = parse_args(argv)
    config = load_config(
        duration=args.duration,
        factory_duration=args.factory_duration,
        seed=args.seed,
        virtual_start=args.virtual_start,
        api_port=args.api_port,
        observatory_port=args.observatory_port,
        ops_iniciais=args.ops_iniciais,
        ops_continuas=args.ops_continuas,
        config_file=args.config or PROJECT_ROOT / "config" / "simulacao_industrial.json",
    )
    runner = SimulationRunner(
        config,
        sem_observatorio=args.sem_observatorio,
        sem_capturas=args.sem_capturas,
    )
    try:
        return asyncio.run(runner.executar())
    except KeyboardInterrupt:
        print("\nExecução interrompida pelo operador; artefatos preservados.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
