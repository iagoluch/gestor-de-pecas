"""Ensaio da promoção 11 → 19 fora do banco REAL.

O banco REAL só pode ser lido nesta fase, então o ensaio **não copia dados
reais**. Ele monta um banco de schema 11 representativo — mesmos volumes e
mesmas distribuições de valor observadas na auditoria READ-ONLY do REAL — e
executa a MESMA função ``apply_migrations`` que o piloto executará.

```text
schema isolado vazio
  → baseline + migrations 2..11        (parada deliberada em 11)
  → semente representativa do REAL
  → apply_migrations()                 (11 → 19, o caminho do piloto)
  → verificação de integridade
  → outbox exercitada de ponta a ponta
```

Nenhuma migration é enfraquecida para passar: o que roda aqui é exatamente o
que está em `app/database/migrations.py`.

```powershell
python scripts\\ensaiar_migracao_11_19.py
python scripts\\ensaiar_migracao_11_19.py --manter-schema
```
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env", override=False)

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from psycopg.conninfo import make_conninfo  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.database import migrations as migrations_module  # noqa: E402
from app.database.config import load_postgres_config  # noqa: E402
from app.database.database import Database  # noqa: E402
from app.database.migrations import apply_migrations  # noqa: E402
from app.database.schema import SCHEMA_VERSION  # noqa: E402
from mes.integrations.totvs.outbound_enqueue import OutboundEnqueueConfig  # noqa: E402
from mes.integrations.totvs.outbox import OutboxStatus  # noqa: E402
from mes.services.totvs_outbox_worker import TotvsOutboxWorker  # noqa: E402


PARTIDA = 11

# Perfil medido no REAL em 01/09/2026 pela auditoria READ-ONLY. O ensaio
# reproduz volume e forma dos dados, não os dados em si.
PERFIL_REAL = {
    "usuarios": 11,
    "tarefas": 7,
    "historico": 131,
    "apontamentos_operacionais": 2,
    "eventos_apontamento_operador": 4,
    "eventos_quantidade_producao": 0,
    "eventos_estado_recurso": 6,
    "catalogo_pcp_ops": 4542,
    "catalogo_operacoes_op": 66,
    "catalogo_recursos_pcfactory": 0,
    "catalogo_sigmanest_planos_corte": 425,
    "apontamentos_corte": 22,
}
# Distribuição real das categorias em eventos_estado_recurso: é ela que a
# CHECK reescrita da migration 12 precisa aceitar.
CATEGORIAS_REAIS = {"producao": 5, "fora_turno": 1}

TABELAS_CONFERIDAS = tuple(PERFIL_REAL)


def _construir_schema_11(connection) -> int:
    """Executa baseline + 2..11 parando deliberadamente em 11."""

    original = migrations_module.SCHEMA_VERSION
    migrations_module.SCHEMA_VERSION = PARTIDA
    try:
        return apply_migrations(connection)
    finally:
        migrations_module.SCHEMA_VERSION = original


def _semear(connection, agora: datetime) -> None:
    """Semente representativa: volume do REAL, conteúdo fictício."""

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO usuarios (nome, senha_hash, nivel, ativo)
            SELECT 'ensaio' || g, 'pbkdf2_sha256$1$x$y', 'operador_destaque', TRUE
            FROM generate_series(1, %s) g
            """,
            (PERFIL_REAL["usuarios"],),
        )
        cursor.execute(
            """
            INSERT INTO tarefas (codigo_tarefa, material, espessura, status)
            SELECT 'TAR-' || LPAD(g::TEXT, 5, '0'), 'ACO', 6.35, 'Em processo'
            FROM generate_series(1, %s) g
            """,
            (PERFIL_REAL["tarefas"],),
        )
        cursor.execute(
            """
            INSERT INTO historico (op, tipo, setor, motivo, quantidade, operador, data_hora, peca)
            SELECT 'OPENS' || LPAD(g::TEXT, 6, '0'), 'Movimentacao', 'Corte', '', 1,
                   'ENSAIO', %s - (g || ' minutes')::INTERVAL, 'PECA'
            FROM generate_series(1, %s) g
            """,
            (agora, PERFIL_REAL["historico"]),
        )
        # catalogo_pcp_ops é a maior tabela do REAL: é ela que dita se a janela
        # de manutenção é de segundos ou de minutos.
        cursor.execute(
            """
            INSERT INTO catalogo_pcp_ops (
                codigo_op, produto_codigo, produto_descricao, quantidade,
                data_emissao, local_estoque, sincronizado_em
            )
            SELECT 'OPENS' || LPAD(g::TEXT, 6, '0'),
                   'PROD' || MOD(g, 900), 'Produto de ensaio',
                   1 + MOD(g, 40), (%s - (g || ' hours')::INTERVAL)::DATE, '01', %s
            FROM generate_series(1, %s) g
            """,
            (agora, agora, PERFIL_REAL["catalogo_pcp_ops"]),
        )
        # Roteiro com a mesma forma do REAL: tipo_setor e ativo preenchidos,
        # que é exatamente a pré-condição da CHECK do marco terminal (18).
        cursor.execute(
            """
            INSERT INTO catalogo_operacoes_op (
                codigo_op, produto_codigo, produto_descricao, numero_operacao,
                codigo_recurso, descricao_operacao, tipo_setor, ordem, ativo,
                sincronizado_em
            )
            SELECT 'OPENS' || LPAD((((g - 1) / 2) + 1)::TEXT, 6, '0'),
                   'PROD' || MOD(g, 900), 'Produto de ensaio',
                   LPAD((10 * (1 + MOD(g, 2)))::TEXT, 2, '0'),
                   CASE WHEN MOD(g, 2) = 0 THEN 'LASER1' ELSE 'DOBRA1' END,
                   'Operacao de ensaio',
                   CASE WHEN MOD(g, 2) = 0 THEN 'Corte' ELSE 'Dobra' END,
                   1 + MOD(g, 2), TRUE, %s
            FROM generate_series(1, %s) g
            """,
            (agora, PERFIL_REAL["catalogo_operacoes_op"]),
        )
        cursor.execute(
            """
            INSERT INTO apontamentos_operacionais (
                op, peca, tipo_setor, maquina, status, quantidade,
                operador_fila, data_entrada, numero_operacao, codigo_recurso,
                produto_codigo
            )
            SELECT 'OPENS' || LPAD(g::TEXT, 6, '0'), 'PECA', 'Corte', 'LASER1',
                   'Finalizado', 5, 'ENSAIO', %s - (g || ' hours')::INTERVAL,
                   '10', 'LASER1', 'PROD1'
            FROM generate_series(1, %s) g
            """,
            (agora, PERFIL_REAL["apontamentos_operacionais"]),
        )
        cursor.execute(
            """
            INSERT INTO eventos_apontamento_operador (
                apontamento_id, estado, operador, data_hora
            )
            SELECT a.id, e.estado, 'ENSAIO', %s
            FROM apontamentos_operacionais a
            CROSS JOIN (VALUES ('fila'), ('producao')) AS e(estado)
            """,
            (agora,),
        )
        # Intervalos fechados: só um estado aberto por recurso é permitido
        # (idx_estado_recurso_aberto), e o que a migration 12 valida é o
        # conjunto de categorias, não a abertura.
        deslocamento = 0
        for categoria, quantidade in CATEGORIAS_REAIS.items():
            cursor.execute(
                """
                INSERT INTO eventos_estado_recurso (
                    recurso, categoria, data_inicio, data_fim, origem
                )
                SELECT 'LASER1', %s,
                       %s - ((g + %s) * 10 || ' minutes')::INTERVAL,
                       %s - ((g + %s) * 10 || ' minutes')::INTERVAL + INTERVAL '5 minutes',
                       'ensaio'
                FROM generate_series(1, %s) g
                """,
                (categoria, agora, deslocamento, agora, deslocamento, quantidade),
            )
            deslocamento += quantidade
        cursor.execute(
            """
            INSERT INTO catalogo_sigmanest_planos_corte (
                plano_hash, codigo_tarefa, programa, sequencia_nesting,
                quantidade_processo, maquina_qlik, sincronizado_em
            )
            SELECT 'HASH' || LPAD(g::TEXT, 8, '0'),
                   'TAR-' || LPAD((1 + MOD(g, %s))::TEXT, 5, '0'),
                   'PRG' || LPAD(g::TEXT, 6, '0'), 1, 1, 'LASER', %s
            FROM generate_series(1, %s) g
            """,
            (
                PERFIL_REAL["tarefas"],
                agora,
                PERFIL_REAL["catalogo_sigmanest_planos_corte"],
            ),
        )
        cursor.execute(
            """
            INSERT INTO apontamentos_corte (
                plano_hash, codigo_tarefa, programa, sequencia_nesting, maquina,
                quantidade_processo, status, operador_inicio, data_inicio,
                operador_fim, data_fim
            )
            SELECT 'HASH' || LPAD(g::TEXT, 8, '0'),
                   'TAR-' || LPAD((1 + MOD(g, %s))::TEXT, 5, '0'),
                   'PRG' || LPAD(g::TEXT, 6, '0'), 1, 'LASER1', 1, 'Finalizado',
                   'ENSAIO', %s - (g || ' hours')::INTERVAL,
                   'ENSAIO', %s - (g || ' hours')::INTERVAL + INTERVAL '30 minutes'
            FROM generate_series(1, %s) g
            """,
            (
                PERFIL_REAL["tarefas"],
                agora,
                agora,
                PERFIL_REAL["apontamentos_corte"],
            ),
        )


def _contagens(connection, tabelas) -> dict:
    resultado = {}
    with connection.cursor() as cursor:
        for tabela in tabelas:
            cursor.execute(
                "SELECT to_regclass(%s) AS existe", (f"{tabela}",)
            )
            if cursor.fetchone()["existe"] is None:
                resultado[tabela] = None
                continue
            cursor.execute(f"SELECT COUNT(*) AS total FROM {tabela}")
            resultado[tabela] = int(cursor.fetchone()["total"])
    return resultado


def _integridade(connection, schema: str) -> dict:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT conname FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = %s AND NOT c.convalidated
            """,
            (schema,),
        )
        constraints_invalidas = [row["conname"] for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT c.relname FROM pg_index i
            JOIN pg_class c ON c.oid = i.indexrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = %s AND (NOT i.indisvalid OR NOT i.indisready)
            """,
            (schema,),
        )
        indices_invalidos = [row["relname"] for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT COUNT(*) AS total FROM catalogo_operacoes_op
            WHERE NOT (
                (marco_terminal IS FALSE AND tipo_setor IS NOT NULL AND ativo IS NOT NULL)
                OR (marco_terminal IS TRUE AND ativo IS FALSE)
            )
            """
        )
        marco_incoerente = int(cursor.fetchone()["total"])
    return {
        "constraints_nao_validadas": constraints_invalidas,
        "indices_invalidos": indices_invalidos,
        "linhas_incoerentes_marco_terminal": marco_incoerente,
    }


def _exercitar_outbox(dsn: str) -> dict:
    """Depois de chegar a 19, a outbox precisa funcionar de verdade."""

    db = Database(
        dsn,
        auto_migrate=False,
        totvs_outbox_config=OutboundEnqueueConfig(enabled=True),
    )
    try:
        metricas_iniciais = db.metricas_outbound_totvs()["contagem"]
        with db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO totvs_outbox (
                    event_type, aggregate_type, aggregate_id, production_order,
                    operation_code, idempotency_key, transaction, payload_xml,
                    status, next_attempt_at, created_at, updated_at
                ) VALUES (
                    'production_appointment', 'execution_event', '1', 'OPENS000001',
                    '10', %s, 'productionappointment', '<TOTVSMessage/>',
                    'PENDING', %s, %s, %s
                ) RETURNING id
                """,
                (f"ensaio-{uuid4()}", db._now(), db._now(), db._now()),
            )
            item_id = cursor.fetchone()["id"]
        reservados = db.reservar_lote_outbound_totvs(worker="ensaio")
        # Sem gateway configurado o worker classifica como falha transitória e
        # reagenda: exatamente o comportamento de "TOTVS fora".
        ciclo = TotvsOutboxWorker(db, gateway=None, worker_name="ensaio").deliver(
            reservados[0]
        )
        historico = db.listar_tentativas_outbound_totvs(item_id)
        final = db.buscar_item_outbound_totvs(item_id)
        with db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM totvs_outbox WHERE id = %s", (item_id,))
        return {
            "metricas_iniciais": metricas_iniciais,
            "reservou": len(reservados) == 1,
            "estado_apos_falha_de_transporte": ciclo["status"],
            "backoff_agendado": final["next_attempt_at"] > final["last_attempt_at"],
            "tentativa_registrada": len(historico) == 1,
        }
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Ensaio da promoção 11 → 19.")
    parser.add_argument("--manter-schema", action="store_true")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    base = load_postgres_config(testing=True)
    schema = "ensaio11a19_" + uuid4().hex[:10]
    with psycopg.connect(base.dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = make_conninfo(base.dsn, options=f"-c search_path={schema}")
    agora = datetime.now().replace(microsecond=0) - timedelta(days=1)

    relatorio = {"schema_de_ensaio": schema, "partida": PARTIDA, "alvo": SCHEMA_VERSION}
    try:
        with psycopg.connect(dsn, row_factory=dict_row) as connection:
            versao_inicial = _construir_schema_11(connection)
            connection.commit()
            relatorio["schema_apos_construcao"] = versao_inicial
            _semear(connection, agora)
            connection.commit()
            antes = _contagens(connection, TABELAS_CONFERIDAS)
            relatorio["contagens_antes"] = antes

            inicio = datetime.now()
            versao_final = apply_migrations(connection)
            connection.commit()
            relatorio["duracao_das_migrations_segundos"] = round(
                (datetime.now() - inicio).total_seconds(), 3
            )
            relatorio["schema_apos_migrations"] = versao_final

            depois = _contagens(connection, TABELAS_CONFERIDAS)
            relatorio["contagens_depois"] = depois
            relatorio["dados_preservados"] = antes == depois
            novas = _contagens(
                connection,
                (
                    "ai_conversations",
                    "generated_reports",
                    "report_schedules",
                    "totvs_integration_messages",
                    "totvs_outbox",
                    "totvs_outbox_attempts",
                ),
            )
            relatorio["tabelas_novas"] = novas
            relatorio["integridade"] = _integridade(connection, schema)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT version, descricao FROM schema_migrations ORDER BY version"
                )
                relatorio["migrations_registradas"] = [
                    dict(row) for row in cursor.fetchall()
                ]

        # A aplicação precisa subir sobre o schema promovido.
        db = Database(dsn, auto_migrate=True)
        try:
            relatorio["aplicacao_reconhece_versao"] = db.obter_schema_version()
            relatorio["consultas_canonicas"] = {
                "apontamentos_por_op": len(db.listar_apontamentos_por_op("OPENS000001")),
                "listar_apontamentos_corte": len(
                    db.listar_apontamentos_operacionais("Corte")
                ),
                "codigos_recursos_totvs": len(db.listar_codigos_recursos_totvs()),
            }
        finally:
            db.close()
        relatorio["outbox"] = _exercitar_outbox(dsn)

        relatorio["aprovado"] = bool(
            relatorio["schema_apos_construcao"] == PARTIDA
            and relatorio["schema_apos_migrations"] == SCHEMA_VERSION
            and relatorio["dados_preservados"]
            and relatorio["aplicacao_reconhece_versao"] == SCHEMA_VERSION
            and not relatorio["integridade"]["constraints_nao_validadas"]
            and not relatorio["integridade"]["indices_invalidos"]
            and relatorio["integridade"]["linhas_incoerentes_marco_terminal"] == 0
            and relatorio["outbox"]["reservou"]
            and relatorio["outbox"]["estado_apos_falha_de_transporte"]
            == OutboxStatus.RETRY.value
        )
        print(json.dumps(relatorio, ensure_ascii=False, indent=2, default=str))
        return 0 if relatorio["aprovado"] else 1
    finally:
        if not args.manter_schema:
            with psycopg.connect(base.dsn, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                )


if __name__ == "__main__":
    raise SystemExit(main())
