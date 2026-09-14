"""Limpeza controlada do banco TESTE, em três escopos explícitos.

Escopos (excludentes, escolha um):

``--cenario`` (padrão)
    Remove **somente** o cenário criado por ``scripts/seed_cenario_gui.py``
    (prefixo ``ZZ`` / ``zz-gui:``) e tudo que a execução gerou em cima dele:
    apontamentos, eventos, estados de recurso, inspeções, Destaque, Corte,
    outbox e histórico. Não encosta em nenhuma outra OP.

``--execucao``
    Apaga toda a **movimentação** do banco de teste — apontamentos, eventos,
    quantidades, estados, rateios, Corte, Qualidade, Destaque, outbox,
    histórico e inconsistências — preservando o planejamento (OPs, roteiros,
    tarefas, catálogo SigmaNEST) e todos os cadastros.

``--planejamento``
    Faz o que ``--execucao`` faz e ainda remove o planejamento: OPs, roteiros,
    tarefas, planos/nestings e a correlação SigmaNEST.

Em qualquer escopo, **nunca** são tocados: usuários, recursos, motivos/status,
calendários e turnos, crachás de operador, conversas da IAgo e migrations.
Esses são cadastro, não dado de teste.

Segurança:

* opera exclusivamente em ``TEST_DATABASE_URL`` via ``load_postgres_config``,
  que recusa banco cujo nome não contenha ``test``, recusa DSN igual ao
  ``DATABASE_URL`` e respeita ``GESTOR_EXPECTED_DATABASE``;
* ``--dry-run`` conta tudo sem apagar nada;
* a exclusão roda em uma única transação, sob *advisory lock*, na ordem das
  chaves estrangeiras — nada fica órfão e nenhum ``FK violation`` acontece;
* ``--execucao`` e ``--planejamento`` exigem ``--confirmar`` porque atingem
  dados fora do cenário.

Uso::

    .venv/Scripts/python.exe scripts/limpar_cenario_gui.py --dry-run
    .venv/Scripts/python.exe scripts/limpar_cenario_gui.py
    .venv/Scripts/python.exe scripts/limpar_cenario_gui.py --execucao --confirmar
    .venv/Scripts/python.exe scripts/limpar_cenario_gui.py --planejamento --confirmar
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.config import load_postgres_config  # noqa: E402
from app.database.database import Database  # noqa: E402

from scripts.seed_cenario_gui import (  # noqa: E402
    AUTOR_CENARIO,
    PREFIXO,
    PREFIXO_PLANO,
    TAG_CENARIO,
)


LOCK_ID = 874_210_310

OP_LIKE = f"{PREFIXO}%"
PLANO_LIKE = f"{PREFIXO_PLANO}%"


# ---------------------------------------------------------------------------
# Cada passo é (rótulo, SQL, parâmetros). A ordem importa: filhos antes de pais
# sempre que a FK não for CASCADE. Onde a FK é CASCADE, o passo explícito serve
# de contagem auditável — apagar duas vezes a mesma linha é inofensivo.
# ---------------------------------------------------------------------------
def _passos_cenario() -> list[tuple[str, str, dict]]:
    escopo = {
        "op": OP_LIKE,
        "plano": PLANO_LIKE,
        "tag": TAG_CENARIO,
        "autor": AUTOR_CENARIO,
    }
    return [
        (
            "sessoes_recurso",
            # Só a sessão física cujo rateio inteiro pertence ao cenário. Uma
            # sessão compartilhada com outra OP permanece intacta.
            """
            DELETE FROM sessoes_recurso s
            WHERE EXISTS (
                SELECT 1 FROM rateios_tempo_op r
                WHERE r.sessao_recurso_id = s.id AND r.op LIKE %(op)s
            )
            AND NOT EXISTS (
                SELECT 1 FROM rateios_tempo_op r
                WHERE r.sessao_recurso_id = s.id AND r.op NOT LIKE %(op)s
            )
            """,
            escopo,
        ),
        ("rateios_tempo_op", "DELETE FROM rateios_tempo_op WHERE op LIKE %(op)s", escopo),
        (
            "eventos_quantidade_producao",
            "DELETE FROM eventos_quantidade_producao WHERE op LIKE %(op)s",
            escopo,
        ),
        (
            "participacoes_operador",
            "DELETE FROM participacoes_operador WHERE op LIKE %(op)s",
            escopo,
        ),
        (
            "eventos_estado_recurso",
            "DELETE FROM eventos_estado_recurso WHERE op LIKE %(op)s",
            escopo,
        ),
        (
            "inconsistencias_dados",
            "DELETE FROM inconsistencias_dados WHERE op LIKE %(op)s",
            escopo,
        ),
        (
            "totvs_outbox_attempts",
            """
            DELETE FROM totvs_outbox_attempts
            WHERE outbox_id IN (
                SELECT id FROM totvs_outbox WHERE production_order LIKE %(op)s
            )
            """,
            escopo,
        ),
        (
            "totvs_outbox",
            "DELETE FROM totvs_outbox WHERE production_order LIKE %(op)s",
            escopo,
        ),
        (
            "totvs_op_sync_requests",
            "DELETE FROM totvs_op_sync_requests WHERE codigo_op LIKE %(op)s",
            escopo,
        ),
        (
            "qualidade_inspecoes",
            # CASCADE remove peças, resultados de cota e RNC vinculados.
            "DELETE FROM qualidade_inspecoes WHERE codigo_op LIKE %(op)s",
            escopo,
        ),
        (
            "apontamentos_operacionais",
            # CASCADE remove eventos_apontamento_operador.
            "DELETE FROM apontamentos_operacionais WHERE op LIKE %(op)s",
            escopo,
        ),
        (
            "apontamentos_corte",
            # FK NO ACTION para o plano: precisa sair antes dele.
            """
            DELETE FROM apontamentos_corte
            WHERE plano_hash LIKE %(plano)s OR codigo_tarefa LIKE %(op)s
            """,
            escopo,
        ),
        (
            "historico",
            """
            DELETE FROM historico
            WHERE op LIKE %(op)s
               OR tarefa_id IN (SELECT id FROM tarefas WHERE codigo_tarefa LIKE %(op)s)
            """,
            escopo,
        ),
        (
            "catalogo_sigmanest_planos_corte",
            """
            DELETE FROM catalogo_sigmanest_planos_corte
            WHERE plano_hash LIKE %(plano)s OR codigo_tarefa LIKE %(op)s
            """,
            escopo,
        ),
        (
            "catalogo_sigmanest_ops",
            """
            DELETE FROM catalogo_sigmanest_ops
            WHERE codigo_op LIKE %(op)s OR codigo_tarefa LIKE %(op)s
            """,
            escopo,
        ),
        (
            "catalogo_sigmanest_programas",
            "DELETE FROM catalogo_sigmanest_programas WHERE codigo_tarefa LIKE %(op)s",
            escopo,
        ),
        (
            "catalogo_sigmanest_tarefas",
            "DELETE FROM catalogo_sigmanest_tarefas WHERE codigo_tarefa LIKE %(op)s",
            escopo,
        ),
        (
            "eventos_destaque_tarefa",
            """
            DELETE FROM eventos_destaque_tarefa
            WHERE tarefa_id IN (SELECT id FROM tarefas WHERE codigo_tarefa LIKE %(op)s)
            """,
            escopo,
        ),
        (
            "op_por_tarefa",
            """
            DELETE FROM op_por_tarefa
            WHERE codigo_op LIKE %(op)s
               OR tarefa_id IN (SELECT id FROM tarefas WHERE codigo_tarefa LIKE %(op)s)
            """,
            escopo,
        ),
        ("tarefas", "DELETE FROM tarefas WHERE codigo_tarefa LIKE %(op)s", escopo),
        (
            "qualidade_cotas_template",
            # Só os templates assinados pelo cenário. Um template cadastrado
            # por um operador para o mesmo produto permanece intacto.
            """
            DELETE FROM qualidade_cotas_template
            WHERE template_id IN (
                SELECT id FROM qualidade_templates_produto
                WHERE criado_por_nome = %(autor)s
            )
            """,
            escopo,
        ),
        (
            "qualidade_templates_produto",
            "DELETE FROM qualidade_templates_produto WHERE criado_por_nome = %(autor)s",
            escopo,
        ),
        (
            "catalogo_operacoes_op",
            "DELETE FROM catalogo_operacoes_op WHERE codigo_op LIKE %(op)s",
            escopo,
        ),
        (
            "catalogo_pcp_ops",
            "DELETE FROM catalogo_pcp_ops WHERE codigo_op LIKE %(op)s",
            escopo,
        ),
        (
            "eventos_sistema",
            "DELETE FROM eventos_sistema WHERE referencia = %(tag)s",
            escopo,
        ),
    ]


def _passos_execucao() -> list[tuple[str, str, dict]]:
    """Zera a movimentação do banco de teste, preservando o planejamento."""

    vazio: dict = {}
    return [
        ("rateios_tempo_op", "DELETE FROM rateios_tempo_op", vazio),
        ("sessoes_recurso", "DELETE FROM sessoes_recurso", vazio),
        ("eventos_quantidade_producao", "DELETE FROM eventos_quantidade_producao", vazio),
        ("participacoes_operador", "DELETE FROM participacoes_operador", vazio),
        ("eventos_estado_recurso", "DELETE FROM eventos_estado_recurso", vazio),
        ("inconsistencias_dados", "DELETE FROM inconsistencias_dados", vazio),
        ("totvs_outbox_attempts", "DELETE FROM totvs_outbox_attempts", vazio),
        ("totvs_outbox", "DELETE FROM totvs_outbox", vazio),
        ("totvs_op_sync_requests", "DELETE FROM totvs_op_sync_requests", vazio),
        ("qualidade_inspecoes", "DELETE FROM qualidade_inspecoes", vazio),
        ("apontamentos_operacionais", "DELETE FROM apontamentos_operacionais", vazio),
        ("apontamentos_corte", "DELETE FROM apontamentos_corte", vazio),
        ("eventos_destaque_tarefa", "DELETE FROM eventos_destaque_tarefa", vazio),
        ("historico", "DELETE FROM historico", vazio),
        (
            "tarefas (reabre o Destaque)",
            """
            UPDATE tarefas SET
                status = NULL,
                data_inicio_destaque = NULL,
                data_finalizacao = NULL,
                data_despacho = NULL
            WHERE status IS NOT NULL
               OR data_inicio_destaque IS NOT NULL
               OR data_finalizacao IS NOT NULL
               OR data_despacho IS NOT NULL
            """,
            vazio,
        ),
    ]


def _passos_planejamento() -> list[tuple[str, str, dict]]:
    """Execução + planejamento. Cadastro e usuários permanecem."""

    vazio: dict = {}
    return _passos_execucao() + [
        (
            "qualidade_cotas_template",
            """
            DELETE FROM qualidade_cotas_template
            WHERE template_id IN (
                SELECT id FROM qualidade_templates_produto WHERE criado_por_nome = %(autor)s
            )
            """,
            {"autor": AUTOR_CENARIO},
        ),
        (
            "qualidade_templates_produto",
            "DELETE FROM qualidade_templates_produto WHERE criado_por_nome = %(autor)s",
            {"autor": AUTOR_CENARIO},
        ),
        (
            "catalogo_sigmanest_planos_corte",
            "DELETE FROM catalogo_sigmanest_planos_corte",
            vazio,
        ),
        ("catalogo_sigmanest_ops", "DELETE FROM catalogo_sigmanest_ops", vazio),
        ("catalogo_sigmanest_programas", "DELETE FROM catalogo_sigmanest_programas", vazio),
        ("catalogo_sigmanest_tarefas", "DELETE FROM catalogo_sigmanest_tarefas", vazio),
        ("op_por_tarefa", "DELETE FROM op_por_tarefa", vazio),
        ("tarefas", "DELETE FROM tarefas", vazio),
        ("catalogo_operacoes_op", "DELETE FROM catalogo_operacoes_op", vazio),
        ("catalogo_pcp_ops", "DELETE FROM catalogo_pcp_ops", vazio),
        (
            "eventos_sistema (cargas de teste)",
            "DELETE FROM eventos_sistema WHERE referencia = %(tag)s",
            {"tag": TAG_CENARIO},
        ),
    ]


ESCOPOS = {
    "cenario": _passos_cenario,
    "execucao": _passos_execucao,
    "planejamento": _passos_planejamento,
}


def _contar(cursor, sql: str, parametros: dict) -> int:
    """Quantas linhas o DELETE/UPDATE atingiria, sem executá-lo."""

    corpo = sql.strip()
    if corpo.upper().startswith("DELETE FROM"):
        # "DELETE FROM x alias WHERE ..." -> "SELECT COUNT(*) FROM x alias WHERE ..."
        consulta = "SELECT COUNT(*) AS total FROM" + corpo[len("DELETE FROM"):]
    elif corpo.upper().startswith("UPDATE"):
        alvo = corpo[len("UPDATE"):].strip().split()[0]
        onde = corpo[corpo.upper().index("WHERE"):]
        consulta = f"SELECT COUNT(*) AS total FROM {alvo} {onde}"
    else:  # pragma: no cover - todos os passos são DELETE ou UPDATE
        raise ValueError(f"Passo não contável: {corpo[:40]}")
    cursor.execute(consulta, parametros)
    return int(cursor.fetchone()["total"])


def _sobrou_do_cenario(cursor) -> dict:
    """Conferência final: nada do cenário pode restar após a limpeza."""

    cursor.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM catalogo_pcp_ops WHERE codigo_op LIKE %(op)s) AS ops,
            (SELECT COUNT(*) FROM catalogo_operacoes_op WHERE codigo_op LIKE %(op)s) AS etapas,
            (SELECT COUNT(*) FROM tarefas WHERE codigo_tarefa LIKE %(op)s) AS tarefas,
            (SELECT COUNT(*) FROM catalogo_sigmanest_planos_corte
              WHERE plano_hash LIKE %(plano)s) AS planos,
            (SELECT COUNT(*) FROM catalogo_sigmanest_ops WHERE codigo_op LIKE %(op)s) AS linhas_peca,
            (SELECT COUNT(*) FROM apontamentos_operacionais WHERE op LIKE %(op)s) AS apontamentos,
            (SELECT COUNT(*) FROM apontamentos_corte WHERE plano_hash LIKE %(plano)s) AS cortes,
            (SELECT COUNT(*) FROM qualidade_templates_produto
              WHERE criado_por_nome = %(autor)s) AS templates
        """,
        {"op": OP_LIKE, "plano": PLANO_LIKE, "autor": AUTOR_CENARIO},
    )
    return dict(cursor.fetchone())


def executar(escopo: str, *, dry_run: bool) -> dict:
    config = load_postgres_config(testing=True)
    alvo = config.safe_target
    nome_banco = str(alvo.get("dbname") or "").casefold()
    if "test" not in nome_banco:
        raise RuntimeError(
            "Limpeza recusada: TEST_DATABASE_URL deve apontar para um banco de teste."
        )

    passos = ESCOPOS[escopo]()
    db = Database(config=config)
    afetados: dict[str, int] = {}
    try:
        with db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
            for rotulo, sql, parametros in passos:
                if dry_run:
                    afetados[rotulo] = _contar(cursor, sql, parametros)
                    continue
                cursor.execute(sql, parametros)
                afetados[rotulo] = cursor.rowcount
            restante = _sobrou_do_cenario(cursor)
            if dry_run:
                # Nada foi gravado; desfaz a transação de contagem.
                conexao.rollback()
        return {
            "modo": "dry-run" if dry_run else "aplicado",
            "escopo": escopo,
            "alvo": alvo,
            "linhas": afetados,
            "total": sum(afetados.values()),
            "restante_do_cenario": restante,
        }
    finally:
        db.close()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument(
        "--cenario",
        dest="escopo",
        action="store_const",
        const="cenario",
        help="Padrão: remove apenas o cenário ZZ criado pelo seed.",
    )
    grupo.add_argument(
        "--execucao",
        dest="escopo",
        action="store_const",
        const="execucao",
        help="Apaga toda a movimentação, preservando o planejamento.",
    )
    grupo.add_argument(
        "--planejamento",
        dest="escopo",
        action="store_const",
        const="planejamento",
        help="Apaga movimentação e planejamento; cadastros permanecem.",
    )
    parser.add_argument(
        "--confirmar",
        action="store_true",
        help="Obrigatório para --execucao e --planejamento.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Só conta, não apaga.")
    parser.add_argument("--json", action="store_true", help="Somente JSON na saída.")
    parser.set_defaults(escopo="cenario")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.escopo != "cenario" and not (args.confirmar or args.dry_run):
        print(
            f"O escopo --{args.escopo} atinge dados fora do cenário de teste.\n"
            "Rode antes com --dry-run e, se concordar, repita com --confirmar.",
            file=sys.stderr,
        )
        return 2

    resultado = executar(args.escopo, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))
        return 0

    print(f"Modo: {resultado['modo']} | Escopo: {resultado['escopo']}")
    print(f"Banco: {resultado['alvo']}")
    verbo = "seriam removidas" if args.dry_run else "removidas"
    print(f"\nLinhas {verbo}:")
    for rotulo, quantidade in resultado["linhas"].items():
        if quantidade:
            print(f"  {rotulo:<34} {quantidade}")
    if not resultado["total"]:
        print("  (nada a remover)")
    print(f"\nTotal: {resultado['total']}")
    print("\nResíduo do cenário ZZ no banco:")
    for chave, valor in resultado["restante_do_cenario"].items():
        print(f"  {chave:<14} {valor}")
    print(
        "\nPreservados em todos os escopos: usuários, recursos, motivos de parada, "
        "calendários/turnos, crachás e migrations."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
