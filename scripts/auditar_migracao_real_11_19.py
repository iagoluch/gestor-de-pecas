"""Pré-voo READ-ONLY da promoção de schema 11 → 19 no banco do Gestor.

Este comando **não escreve**. A garantia não é boa intenção: a conexão é aberta
com ``default_transaction_read_only=on`` e cada transação declara
``SET TRANSACTION READ ONLY``, então qualquer `INSERT`/`UPDATE`/`DELETE`/`DDL`
acidental seria recusado pelo próprio PostgreSQL.

Ele responde a uma pergunta objetiva: **as migrations 12 a 19 encontram no
banco alvo exatamente o que esperam, e os dados existentes conseguem receber as
constraints novas?**

```powershell
python scripts\\auditar_migracao_real_11_19.py --alvo real
python scripts\\auditar_migracao_real_11_19.py --alvo teste
python scripts\\auditar_migracao_real_11_19.py --dsn postgresql://...
```
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env", override=False)

import psycopg  # noqa: E402
from psycopg.conninfo import make_conninfo  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.database.schema import SCHEMA_VERSION  # noqa: E402


# Categorias aceitas pela CHECK reescrita na migration 12. Um valor histórico
# fora desta lista faria a migration falhar ao validar as linhas existentes.
CATEGORIAS_MIGRATION_12 = (
    "fila",
    "producao",
    "parada",
    "setup",
    "retrabalho",
    "atividade_sem_op",
    "fora_turno",
    "desconhecido",
    "sem_demanda",
)

# Tabelas que as migrations 12–19 pressupõem já existirem.
TABELAS_PRESSUPOSTAS = (
    "usuarios",
    "eventos_estado_recurso",
    "apontamentos_operacionais",
    "eventos_apontamento_operador",
    "catalogo_pcp_ops",
    "catalogo_operacoes_op",
    "catalogo_sigmanest_planos_corte",
    "catalogo_sigmanest_ops",
    "catalogo_sigmanest_tarefas",
)

# Tabelas que as migrations 12–19 criam; nenhuma pode existir de antemão.
TABELAS_CRIADAS = (
    "ai_conversations",
    "ai_messages",
    "ai_knowledge",
    "generated_reports",
    "messaging_destinations",
    "report_schedules",
    "report_deliveries",
    "totvs_integration_messages",
    "totvs_outbox",
    "totvs_outbox_attempts",
)

# Colunas que as migrations adicionam; nenhuma pode existir de antemão.
COLUNAS_ADICIONADAS = {
    "apontamentos_operacionais": ("estado_retorno",),
    "eventos_apontamento_operador": ("estado_retorno",),
    "catalogo_pcp_ops": (
        "totvs_unique_id",
        "totvs_company_id",
        "totvs_branch_id",
        "totvs_generated_on",
        "totvs_source_application",
        "totvs_payload_hash",
    ),
    "catalogo_operacoes_op": (
        "totvs_activity_id",
        "totvs_work_center_code",
        "totvs_machine_code",
        "marco_terminal",
    ),
    "catalogo_sigmanest_planos_corte": (
        "sigmanest_repeat_id",
        "sigmanest_archive_packet_id",
        "sigmanest_comp_date",
        "sigmanest_trans_type",
        "sigmanest_synced_at",
    ),
    "catalogo_sigmanest_ops": ("sigmanest_synced_at",),
    "catalogo_sigmanest_tarefas": ("sigmanest_synced_at",),
}

VOLUMES = (
    "usuarios",
    "tarefas",
    "historico",
    "apontamentos_operacionais",
    "eventos_apontamento_operador",
    "eventos_quantidade_producao",
    "eventos_estado_recurso",
    "catalogo_pcp_ops",
    "catalogo_operacoes_op",
    "catalogo_recursos_pcfactory",
    "catalogo_sigmanest_planos_corte",
    "apontamentos_corte",
)


def _dsn(args) -> tuple[str, str]:
    if args.dsn:
        return args.dsn, "explícito"
    if args.alvo == "real":
        value = os.environ.get("DATABASE_URL")
        if not value:
            raise SystemExit("DATABASE_URL não configurada no .env.")
        return value, "DATABASE_URL"
    value = os.environ.get("TEST_DATABASE_URL")
    if not value:
        raise SystemExit("TEST_DATABASE_URL não configurada no .env.")
    return value, "TEST_DATABASE_URL"


class ReadOnlyInspector:
    def __init__(self, dsn: str):
        # Dupla trava: a sessão nasce somente leitura e cada transação repete a
        # declaração. Um DDL acidental aqui seria recusado pelo servidor.
        self.connection = psycopg.connect(
            make_conninfo(dsn, options="-c default_transaction_read_only=on"),
            autocommit=False,
            row_factory=dict_row,
        )
        self.connection.execute("SET TRANSACTION READ ONLY")

    def rows(self, query, params=()):
        with self.connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def scalar(self, query, params=()):
        found = self.rows(query, params)
        return next(iter(found[0].values())) if found else None

    def close(self):
        self.connection.rollback()
        self.connection.close()


def auditar(inspector: ReadOnlyInspector) -> dict:  # noqa: C901 - checklist linear
    achados: list[dict] = []

    def registrar(severidade, migration, item, detalhe):
        achados.append(
            {
                "severidade": severidade,
                "migration": migration,
                "item": item,
                "detalhe": detalhe,
            }
        )

    versao = inspector.scalar(
        "SELECT MAX(version) AS v FROM schema_migrations"
    )
    aplicadas = [
        dict(row)
        for row in inspector.rows(
            "SELECT version, descricao, applied_at FROM schema_migrations ORDER BY version"
        )
    ]

    tabelas = {
        row["table_name"]
        for row in inspector.rows(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
    }
    colunas = {}
    for row in inspector.rows(
        """
        SELECT table_name, column_name, data_type, is_nullable, column_default
        FROM information_schema.columns WHERE table_schema = 'public'
        """
    ):
        colunas.setdefault(row["table_name"], {})[row["column_name"]] = row

    # --- pré-condições estruturais ------------------------------------
    for tabela in TABELAS_PRESSUPOSTAS:
        if tabela not in tabelas:
            registrar(
                "BLOQUEANTE",
                "12-19",
                f"tabela ausente: {tabela}",
                "As migrations pressupõem esta tabela; a cadeia falharia.",
            )
    for tabela in TABELAS_CRIADAS:
        if tabela in tabelas:
            registrar(
                "BLOQUEANTE",
                "14-19",
                f"tabela já existe: {tabela}",
                "A migration executaria CREATE TABLE sobre um objeto existente.",
            )
    for tabela, esperadas in COLUNAS_ADICIONADAS.items():
        existentes = colunas.get(tabela, {})
        for coluna in esperadas:
            if coluna in existentes:
                registrar(
                    "BLOQUEANTE",
                    "13-18",
                    f"coluna já existe: {tabela}.{coluna}",
                    "ADD COLUMN falharia; o schema divergiu do esperado.",
                )

    # --- migration 12: CHECK reescrita sobre dados existentes ----------
    categorias = []
    if "eventos_estado_recurso" in tabelas:
        categorias = inspector.rows(
            """
            SELECT categoria, COUNT(*) AS total
            FROM eventos_estado_recurso GROUP BY categoria ORDER BY total DESC
            """
        )
        fora = [
            item
            for item in categorias
            if str(item["categoria"]) not in CATEGORIAS_MIGRATION_12
        ]
        if fora:
            registrar(
                "BLOQUEANTE",
                "12",
                "categoria fora da CHECK nova",
                f"Valores existentes que violariam a constraint: {fora}",
            )

    # --- migration 16: constraint que será removida e UNIQUE nova ------
    constraint_16 = inspector.scalar(
        """
        SELECT COUNT(*) AS total FROM pg_constraint
        WHERE conname = 'uq_catalogo_operacao_op_recurso'
          AND conrelid = 'public.catalogo_operacoes_op'::regclass
        """
    ) if "catalogo_operacoes_op" in tabelas else 0
    if not constraint_16:
        registrar(
            "BLOQUEANTE",
            "16",
            "constraint uq_catalogo_operacao_op_recurso ausente",
            "A migration executa DROP CONSTRAINT sem IF EXISTS e falharia.",
        )
    duplicados_legacy = []
    if "catalogo_operacoes_op" in tabelas:
        duplicados_legacy = inspector.rows(
            """
            SELECT codigo_op, numero_operacao, codigo_recurso, COUNT(*) AS total
            FROM catalogo_operacoes_op
            GROUP BY codigo_op, numero_operacao, codigo_recurso
            HAVING COUNT(*) > 1
            ORDER BY total DESC LIMIT 20
            """
        )
        if duplicados_legacy:
            registrar(
                "BLOQUEANTE",
                "16",
                "duplicatas em (codigo_op, numero_operacao, codigo_recurso)",
                "uq_catalogo_operacao_legacy é UNIQUE parcial e seria recusada: "
                f"{duplicados_legacy}",
            )

    # --- migration 18: CHECK do marco terminal sobre linhas atuais -----
    violacoes_18 = None
    ativo_nullable = None
    if "catalogo_operacoes_op" in tabelas:
        ativo = colunas.get("catalogo_operacoes_op", {}).get("ativo")
        ativo_nullable = ativo["is_nullable"] if ativo else None
        # Toda linha existente nasce com marco_terminal = FALSE, então precisa
        # satisfazer o ramo (tipo_setor IS NOT NULL AND ativo IS NOT NULL).
        violacoes_18 = inspector.scalar(
            """
            SELECT COUNT(*) AS total FROM catalogo_operacoes_op
            WHERE tipo_setor IS NULL OR ativo IS NULL
            """
        )
        if violacoes_18:
            registrar(
                "BLOQUEANTE",
                "18",
                "linhas violariam ck_catalogo_operacao_marco_terminal",
                f"{violacoes_18} operação(ões) com tipo_setor ou ativo nulos.",
            )

    # --- migration 15/14: FK para usuarios -----------------------------
    if "usuarios" in tabelas:
        usuarios = inspector.scalar("SELECT COUNT(*) AS total FROM usuarios")
    else:
        usuarios = None

    volumes = {}
    for tabela in VOLUMES:
        if tabela in tabelas:
            volumes[tabela] = inspector.scalar(f"SELECT COUNT(*) AS total FROM {tabela}")

    # --- janela de manutenção ------------------------------------------
    maior = max((valor for valor in volumes.values() if valor is not None), default=0)
    janela = (
        "curta (segundos): todas as operações são ADD COLUMN com default constante, "
        "CREATE TABLE/INDEX e validação de CHECK sobre tabelas pequenas"
        if maior < 500_000
        else "avaliar: alguma tabela passa de 500 mil linhas e a validação de "
        "CHECK/UNIQUE exige varredura completa com lock de ALTER TABLE"
    )

    return {
        "schema_version_registrada": versao,
        "schema_version_da_aplicacao": SCHEMA_VERSION,
        "gap": (
            f"{versao} -> {SCHEMA_VERSION}"
            if versao != SCHEMA_VERSION
            else "sem gap"
        ),
        "migrations_aplicadas": aplicadas,
        "tabelas_publicas": sorted(tabelas),
        "categorias_eventos_estado_recurso": categorias,
        "constraint_uq_catalogo_operacao_op_recurso_presente": bool(constraint_16),
        "duplicatas_catalogo_operacoes_op": duplicados_legacy,
        "catalogo_operacoes_op_ativo_is_nullable": ativo_nullable,
        "linhas_que_violariam_check_18": violacoes_18,
        "usuarios": usuarios,
        "volumes": volumes,
        "janela_de_manutencao": janela,
        "achados": achados,
        "apto_para_promocao": not any(
            item["severidade"] == "BLOQUEANTE" for item in achados
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Pré-voo READ-ONLY da promoção 11 → 19.")
    parser.add_argument("--alvo", choices=("real", "teste"), default="real")
    parser.add_argument("--dsn")
    args = parser.parse_args()
    dsn, origem = _dsn(args)

    inspector = ReadOnlyInspector(dsn)
    try:
        info = inspector.rows(
            "SELECT current_database() AS banco, version() AS versao, "
            "current_setting('transaction_read_only') AS somente_leitura"
        )[0]
        resultado = auditar(inspector)
    finally:
        inspector.close()

    # A evidência é arquivada; forçamos UTF-8 para o texto não corromper
    # acentos quando a saída é redirecionada em console Windows.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    resultado = {
        "banco": info["banco"],
        "origem_do_dsn": origem,
        "postgres": str(info["versao"]).split(",")[0],
        "transacao_somente_leitura": info["somente_leitura"],
        **resultado,
    }
    print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))
    return 0 if resultado["apto_para_promocao"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
