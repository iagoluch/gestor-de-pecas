"""Aponta (Inicio+Finalizado) os nestings de Corte de uma OP cujo SigmaNEST
ja trouxe sigmanest_comp_date preenchido -- cenario de OP historica/legado
que a fila operacional esconde de proposito (nunca cria apontamento sozinha,
ver comentario em Database.listar_fila_corte).

Decisao do usuario (21/09/2026): enquanto o sistema novo entra em producao,
OPs cujo Corte ja veio concluido na origem (SigmaNEST) devem ser apontadas
como etapa finalizada mesmo fora da janela normal da fila, para nao travar
o roteiro por causa de uma incompatibilidade esperada da migracao.

Usa os mesmos metodos de persistencia do fluxo real
(Database.iniciar_apontamento_corte / finalizar_apontamento_corte) -- so
contorna o filtro de VISIBILIDADE da fila (comp_date / cutoff), que existe
para o operador nao ver trabalho ja cortado, nao para impedir o apontamento
retroativo pedido explicitamente aqui.

Uso: python scripts/apontar_corte_concluido_origem.py <codigo_op>
Requer TEST_DATABASE_URL configurado (.env) e GESTOR_EXPECTED_DATABASE=gestor_pecas_test.
"""

import os
import sys

sys.path.insert(0, ".")

from app.database.config import load_postgres_config
from app.database.database import Database
from mes.services.cut import CutService

EXPECTED_DATABASE = "gestor_pecas_test"
OPERADOR = "corte"


def _test_dsn():
    environ = dict(os.environ)
    environ["GESTOR_EXPECTED_DATABASE"] = EXPECTED_DATABASE
    return load_postgres_config(testing=True, environ=environ).dsn


def apontar_op(codigo_op):
    db = Database(_test_dsn())
    with db.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT sig_op.codigo_tarefa, plano.plano_hash, plano.programa,
                   plano.maquina_sigmanest, plano.data_programa, plano.sigmanest_comp_date
            FROM catalogo_sigmanest_ops sig_op
            JOIN catalogo_sigmanest_planos_corte plano
              ON plano.codigo_tarefa = sig_op.codigo_tarefa
             AND plano.programa = sig_op.programa
             AND plano.ativo = TRUE
            LEFT JOIN apontamentos_corte a ON a.plano_hash = plano.plano_hash
            WHERE sig_op.ativo = TRUE
              AND UPPER(sig_op.codigo_op) = UPPER(%s)
              AND plano.sigmanest_comp_date IS NOT NULL
              AND a.id IS NULL
            ORDER BY plano.programa
            """,
            (codigo_op,),
        )
        pendentes = cur.fetchall()

    if not pendentes:
        print(f"Nenhum plano pendente de apontamento (ja apontado ou sem comp_date) para {codigo_op}.")
        return

    for plano in pendentes:
        cutoff = plano["data_programa"]
        maquina = CutService.machine_display(plano["maquina_sigmanest"])
        started = db.iniciar_apontamento_corte(
            plano["plano_hash"],
            maquina,
            OPERADOR,
            cutoff,
            data_inicio=plano["sigmanest_comp_date"],
        )
        if not started:
            print(f"  FALHA ao iniciar programa {plano['programa']} ({plano['plano_hash'][:12]}...)")
            continue
        finished = db.finalizar_apontamento_corte(
            started["id"], OPERADOR, data_fim=plano["sigmanest_comp_date"]
        )
        if finished:
            print(f"  OK programa {plano['programa']} -> apontamento {finished['id']} Finalizado em {finished['data_fim']}")
        else:
            print(f"  FALHA ao finalizar programa {plano['programa']}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Uso: python scripts/apontar_corte_concluido_origem.py <codigo_op>")
    apontar_op(sys.argv[1])
