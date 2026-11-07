"""Reset rápido do banco de TESTE (gestor_pecas_test): apaga OPs, tarefas e apontamentos.

Uso:  python scripts/reset_rapido_teste.py

Sem simulação, sem backup, sem confirmação. Só funciona no banco gestor_pecas_test.

Feito para não quebrar quando o schema muda:
- não importa nada do app (só psycopg);
- tabela da lista que deixou de existir é ignorada;
- tabela filha (FK) das que serão limpas entra sozinha na limpeza, a não ser que seja
  protegida (aí o script para e avisa, sem apagar nada);
- tabela nova que não está em nenhuma lista é PRESERVADA e aparece num aviso;
- a API/outras conexões ao banco de teste são derrubadas e a limpeza é repetida se
  houver deadlock (a API reconecta sozinha).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

BANCO = "gestor_pecas_test"
RAIZ = Path(__file__).resolve().parents[1]

# O que é apagado: OPs, tarefas, apontamentos e tudo que deriva deles.
LIMPAR = {
    "alertas_internos", "qualidade_primeira_peca_autorizacoes", "qualidade_primeira_peca",
    "apontamentos_corte", "apontamentos_operacionais", "chamadas", "chamada_visualizacoes",
    "catalogo_operacoes_op", "catalogo_pcp_ops", "catalogo_sigmanest_ops",
    "catalogo_sigmanest_planos_corte", "catalogo_sigmanest_programas",
    "catalogo_sigmanest_tarefas", "eventos_apontamento_operador", "eventos_destaque_tarefa",
    "eventos_estado_recurso", "eventos_quantidade_producao", "fila_manual_recurso",
    "eventos_sistema", "historico", "inconsistencias_dados", "manutencao_sugestoes",
    "op_por_tarefa", "operadores_evento_apontamento", "participacoes_operador",
    "qualidade_inspecoes", "qualidade_pecas_inspecionadas", "qualidade_resultados_cota",
    "qualidade_rnc", "qualidade_rnc_decisoes", "rateios_tempo_op", "sessoes_recurso",
    "tarefas", "totvs_op_sync_requests", "totvs_outbox", "totvs_outbox_attempts",
}

# Cadastro/configuração: nunca apagado.
PROTEGIDAS = {
    "ai_conversations",
    "ai_knowledge",
    "ai_messages",
    "auditoria_alteracoes",
    "calendarios_produtivos",
    "catalogo_recursos_pcfactory",
    "catalogo_status_recursos",
    "chamada_contatos",
    "custo_hora_operador",
    "custo_hora_recurso",
    "excecoes_calendario_produtivo",
    "generated_reports",
    "intervalos_turno_produtivo",
    "log_sistema",
    "login_throttle",
    "messaging_destinations",
    "niveis_acesso",
    "operadores_apontamento",
    "parametros_turno",
    "parametros_turno_historico",
    "pausas_automaticas_setor",
    "qualidade_cotas_template",
    "qualidade_desenhos_produto",
    "qualidade_templates_produto",
    "report_deliveries",
    "report_schedules",
    "schema_migrations",
    "telegram_bot_cursors",
    "telegram_chats_descobertos",
    "telegram_codigos_vinculo",
    "telegram_corte_mensagens",
    "telegram_digest_envios",
    "telegram_vinculo_tentativas",
    "tempo_padrao_estimado",
    "tempo_padrao_manual",
    "tempo_padrao_manual_historico",
    "totvs_integration_messages",
    "turnos_produtivos",
    "user_preferences",
    "usuarios",
}


def _env(nome: str) -> str:
    if os.environ.get(nome):
        return os.environ[nome]
    arq = RAIZ / ".env"
    if arq.exists():
        for linha in arq.read_text(encoding="utf-8", errors="ignore").splitlines():
            if linha.startswith(nome + "="):
                return linha.split("=", 1)[1].strip().strip("\"'")
    return ""


def _fks(cur) -> list[tuple[str, str]]:
    """(filha, pai) de todas as FKs do schema public."""
    cur.execute(
        """SELECT cl.relname, pl.relname FROM pg_constraint c
           JOIN pg_class cl ON cl.oid = c.conrelid JOIN pg_class pl ON pl.oid = c.confrelid
           JOIN pg_namespace n ON n.oid = cl.relnamespace
           WHERE c.contype = 'f' AND n.nspname = 'public'"""
    )
    return cur.fetchall()


def _alvo(cur) -> tuple[list[str], list[str]]:
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    existentes = {r[0] for r in cur.fetchall()}
    alvo = LIMPAR & existentes
    fks = _fks(cur)
    mudou = True
    while mudou:  # fecha o conjunto: filhas das tabelas limpas também precisam ser limpas
        mudou = False
        for filha, pai in fks:
            if pai in alvo and filha not in alvo:
                if filha in PROTEGIDAS:
                    raise SystemExit(
                        f"ABORTADO: a tabela protegida '{filha}' tem FK para '{pai}'. "
                        "Nada foi apagado. Ajuste LIMPAR/PROTEGIDAS no script."
                    )
                alvo.add(filha)
                mudou = True
    novas = sorted(existentes - alvo - PROTEGIDAS - {"schema_migrations"})
    return sorted(alvo), novas


def main() -> int:
    url = _env("TEST_DATABASE_URL")
    destino = conninfo_to_dict(url) if url else {}
    if (
        destino.get("host") not in {"127.0.0.1", "localhost", "::1"}
        or destino.get("port") != "15432"
        or destino.get("hostaddr", destino.get("host")) not in {"127.0.0.1", "localhost", "::1"}
    ):
        print("ABORTADO: reset permitido somente no PostgreSQL local, porta 15432.", file=sys.stderr)
        return 1
    if not url or url.split("?")[0].rstrip("/").rsplit("/", 1)[-1] != BANCO:
        print(f"ABORTADO: TEST_DATABASE_URL ausente ou não aponta para {BANCO}.", file=sys.stderr)
        return 1

    for tentativa in range(1, 6):
        try:
            with psycopg.connect(url) as con:
                cur = con.cursor()
                if cur.execute("SELECT current_database()").fetchone()[0] != BANCO:
                    print("ABORTADO: banco conectado não é o de teste.", file=sys.stderr)
                    return 1
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()", (BANCO,)
                )
                alvo, novas = _alvo(cur)
                cur.execute("SET LOCAL lock_timeout = '15s'")
                cur.execute(
                    sql.SQL("TRUNCATE {} RESTART IDENTITY").format(
                        sql.SQL(", ").join(sql.Identifier("public", t) for t in alvo)
                    )
                )
                env = cur.execute(
                    "SELECT 1 FROM information_schema.columns WHERE table_name = "
                    "'totvs_integration_messages' AND column_name = 'transaction'"
                ).fetchone()
                removidos = 0
                if env:
                    cur.execute(
                        "DELETE FROM public.totvs_integration_messages "
                        "WHERE transaction = 'ProductionOrder'"
                    )
                    removidos = cur.rowcount
                con.commit()
            print(f"OK: {len(alvo)} tabelas limpas; {removidos} envelopes de OP do Protheus removidos.")
            if novas:
                print("AVISO: tabelas novas preservadas (não estão em nenhuma lista): " + ", ".join(novas))
            return 0
        except (psycopg.errors.DeadlockDetected, psycopg.errors.LockNotAvailable,
                psycopg.OperationalError) as exc:
            print(f"tentativa {tentativa}/5 falhou ({type(exc).__name__}); repetindo...")
            time.sleep(2)
    print("FALHOU após 5 tentativas. Pare a API da porta 8001 e rode de novo.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
