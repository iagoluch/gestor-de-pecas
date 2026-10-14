"""Zera dados operacionais e de catálogo, mantendo logins e configuração de recursos.

Uso único para preparar o ambiente de exploração (sem produção em andamento).
Mantém: usuarios, niveis_acesso, operadores_apontamento, schema_migrations e a
configuração de recursos (catálogo de recursos/status, calendário, turnos,
intervalos, exceções, parâmetros de turno, pausas automáticas, destinos de mensagem).
Todo o resto vira TRUNCATE em uma única transação, sem CASCADE (se uma tabela
mantida referenciar uma apagada, o PostgreSQL recusa e nada é alterado).

    python scripts/limpar_banco_exploracao.py --alvo TEST --dry-run
    python scripts/limpar_banco_exploracao.py --alvo REAL --confirmar gestor_pecas
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import dotenv_values  # noqa: E402

ALVOS = {"TEST": ("TEST_DATABASE_URL", "gestor_pecas_test"), "REAL": ("DATABASE_URL", "gestor_pecas")}
MANTER = frozenset({
    "usuarios", "niveis_acesso", "operadores_apontamento", "schema_migrations",
    "catalogo_recursos_pcfactory", "catalogo_status_recursos",
    "calendarios_produtivos", "turnos_produtivos", "intervalos_turno_produtivo",
    "excecoes_calendario_produtivo", "parametros_turno", "parametros_turno_historico",
    "pausas_automaticas_setor", "messaging_destinations",
})


def _contagens(cur, tabelas) -> dict[str, int]:
    out = {}
    for t in sorted(tabelas):
        cur.execute(sql.SQL("SELECT COUNT(*) FROM public.{}").format(sql.Identifier(t)))
        out[t] = cur.fetchone()[0]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--alvo", required=True, choices=sorted(ALVOS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--confirmar", metavar="NOME_DO_BANCO")
    args = ap.parse_args()
    variavel, esperado = ALVOS[args.alvo]
    if not args.dry_run and args.confirmar != esperado:
        print(f"Recusado: use --dry-run ou --confirmar {esperado}", file=sys.stderr)
        return 2
    dsn = (dotenv_values(PROJECT_ROOT / ".env").get(variavel) or "").strip()
    if conninfo_to_dict(dsn).get("dbname") != esperado:
        print(f"Recusado: {variavel} não aponta para {esperado}", file=sys.stderr)
        return 2
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        if cur.fetchone()[0] != esperado:
            print("Recusado: banco conectado diferente do esperado", file=sys.stderr)
            return 2
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        todas = {r[0] for r in cur.fetchall()}
        faltando = MANTER - todas
        if faltando:
            print(f"Recusado: tabelas a manter inexistentes: {sorted(faltando)}", file=sys.stderr)
            return 2
        apagar = todas - MANTER
        antes_manter = _contagens(cur, MANTER)
        antes_apagar = _contagens(cur, apagar)
        print(f"Banco {esperado}: {sum(antes_apagar.values())} linhas em {len(apagar)} tabelas a apagar")
        if args.dry_run:
            for t, n in antes_apagar.items():
                if n:
                    print(f"  apagaria {t}: {n}")
            conn.rollback()
            return 0
        cur.execute(sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY").format(
            sql.SQL(", ").join(sql.SQL("public.") + sql.Identifier(t) for t in sorted(apagar))))
        depois_manter = _contagens(cur, MANTER)
        depois_apagar = _contagens(cur, apagar)
        if depois_manter != antes_manter or any(depois_apagar.values()):
            conn.rollback()
            print("ERRO: verificação falhou; transação desfeita", file=sys.stderr)
            return 1
        conn.commit()
        print("OK. Mantido:", {t: n for t, n in depois_manter.items() if n})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
