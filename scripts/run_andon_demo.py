"""Prepara e executa a demonstração contínua do Andon."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from simulacao.andon_demo import (  # noqa: E402
    DEFAULT_VISIBLE_RESOURCES,
    AndonDemo,
    ensure_demo_database,
    open_demo_database,
    seed_demo_catalogs,
)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Andon DEMO contínuo e isolado.")
    parser.add_argument("--prepare", action="store_true", help="Cria/migra o banco DEMO e monta o warm start.")
    parser.add_argument("--seed", type=int, default=None, help="Seed opcional para reproduzir o cenário.")
    parser.add_argument(
        "--resources", type=int, default=DEFAULT_VISIBLE_RESOURCES,
        help="Quantidade alvo de recursos ativos (mínimo 8).",
    )
    parser.add_argument("--once", action="store_true", help="Executa um passo e encerra (diagnóstico/teste).")
    parser.add_argument("--poll-seconds", type=float, default=2.0, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _console_utf8():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def main(argv=None) -> int:
    _console_utf8()
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.prepare:
        source_dsn, demo_dsn = ensure_demo_database()
    else:
        source_dsn = demo_dsn = None
    database = open_demo_database()
    try:
        demo = AndonDemo(database, seed=args.seed, resource_count=args.resources)
        with demo.instance_lock():
            copied = (
                seed_demo_catalogs(source_dsn, demo_dsn)
                if source_dsn is not None and demo_dsn is not None
                else None
            )
            summary = demo.prepare()
            if copied is not None:
                summary["catalogs_copied"] = copied
            print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
            if args.once:
                print(json.dumps(demo.step(), ensure_ascii=False, default=str))
                return 0
            print("Andon DEMO ativo continuamente. Encerre com Ctrl+C.")
            demo.run_forever(poll_seconds=args.poll_seconds)
    except KeyboardInterrupt:
        print("\nAndon DEMO encerrado de forma limpa pelo operador.")
        return 130
    finally:
        database.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
