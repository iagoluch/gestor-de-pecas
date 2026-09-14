"""Sincroniza o planejamento de Corte do SigmaNEST para o PostgreSQL do Gestor.

Leitura do SigmaNEST é **somente leitura**; a escrita ocorre apenas nas tabelas
canônicas de planejamento do Gestor (`catalogo_sigmanest_*`). Nenhuma OP é
criada e nenhum apontamento é gerado.

Uso:

```
python scripts/sincronizar_sigmanest.py                    # incremental
python scripts/sincronizar_sigmanest.py --desde 2026-08-01 # janela explícita
python scripts/sincronizar_sigmanest.py --dry-run          # só diagnostica
```
"""

from __future__ import annotations

import argparse
from datetime import datetime
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

from app.database.database import Database  # noqa: E402
from backend.integrations.sigmanest_sqlserver import (  # noqa: E402
    SigmaNestSqlServerGateway,
    mask_dsn,
)
from mes.services.sigmanest_sync import (  # noqa: E402
    DEFAULT_OVERLAP_DAYS,
    SigmaNestSyncService,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desde", help="data inicial YYYY-MM-DD (padrão: marca d'água)")
    parser.add_argument(
        "--overlap-dias",
        type=int,
        default=DEFAULT_OVERLAP_DAYS,
        help="sobreposição da janela incremental",
    )
    parser.add_argument("--tarefa", action="append", help="limitar a tarefas específicas")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="lê o SigmaNEST e relata, sem gravar no Gestor",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    desde = datetime.fromisoformat(args.desde) if args.desde else None
    gateway = SigmaNestSqlServerGateway()
    print(f"SigmaNEST (read-only): {mask_dsn(gateway.dsn)}")

    database = Database()
    try:
        print(f"Gestor: {database.safe_target}")
        service = SigmaNestSyncService(database, gateway)
        janela = desde if desde is not None else service.marca_dagua(
            overlap_days=args.overlap_dias
        )
        print(f"Janela de leitura a partir de: {janela or 'início do histórico'}")

        if args.dry_run:
            snapshot = service.planning.snapshot(desde=janela, tarefas=args.tarefa)
            print(
                f"[dry-run] tarefas={len(snapshot.tasks)} nestings={len(snapshot.plans)} "
                f"pecas={len(snapshot.part_lines)} OPs={len(snapshot.ordens_de_producao)}"
            )
            return 0

        resultado = service.sincronizar(
            desde=desde, overlap_days=args.overlap_dias, tarefas=args.tarefa
        )
        print(resultado.resumo())
        print(f"projetado: {resultado.projetado}")
        print(
            f"nestings já concluídos na origem: "
            f"{resultado.nestings_concluidos_na_origem}"
        )
        if resultado.ordens_sem_op_no_gestor:
            amostra = ", ".join(resultado.ordens_sem_op_no_gestor[:10])
            print(
                f"OPs vistas no SigmaNEST sem correspondência no Gestor "
                f"({len(resultado.ordens_sem_op_no_gestor)}): {amostra}…"
            )
        return 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
