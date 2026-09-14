"""Cria e popula o banco isolado da homologação extrema.

O script nunca grava no banco operacional nem no banco de teste comum. O alvo
precisa conter simultaneamente ``test`` e ``homolog`` no nome. A carga é
determinística, idempotente e preserva no destino uma cópia dos usuários do
banco normal, sem expor hashes ou credenciais.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
import sys

from dotenv import dotenv_values
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.config import PostgresConfig  # noqa: E402
from app.database.database import Database  # noqa: E402
from app.database.schema import SCHEMA_VERSION  # noqa: E402


# Sem default: o banco dedicado da homologação precisa ser informado em
# HOMOLOG_DATABASE_NAME. Nunca aponte para o banco de TESTE oficial.
TARGET_DATABASE = os.getenv("HOMOLOG_DATABASE_NAME", "").strip()
START = datetime(2026, 8, 11, 6, 0, 0)
END = datetime(2026, 8, 20, 21, 30, 0)
SEED_TAG = "homologacao_extrema_v1"
EXPECTED_PATH = Path(__file__).with_name("expected_results.json")
ACTUAL_PATH = Path(__file__).with_name("seed_result.json")


SECTOR_RESOURCES = {
    "Corte": ("Laser Ensis 3015", "Plasma TerraBlade 4"),
    "Dobra": ("1303", "2204", "Gasparini"),
    "Usinagem": (
        "Eurostec",
        "Fresadora FTV31",
        "Romi D 1000",
        "Romi GL 350M",
        "Torno Mecânico",
    ),
    "Serra": ("SFG-330", "S4220", "SFHA-10"),
    "Solda": tuple(f"Estação {number}" for number in range(1, 11)),
    "Pintura": ("Pintura",),
    "Destaque": ("Destaque 1", "Destaque 2"),
}

SPECIAL_RESOURCES = {
    "DOBRA-SIM-01": "Dobra",
    "CNC-CONFLITO": "Usinagem",
    "TURNO-RES-01": "Usinagem",
    "SERRA-ZERO": "Serra",
}

STATUS_ROWS = (
    ("H-PROD", "Produção", "producao", True, False, False, False, False, False),
    ("H-STOP-MAN", "Parada manual — causa mecânica", "parada", False, False, True, True, False, True),
    ("H-STOP-AUTO", "Interrupção automática de fim de turno", "fora_turno", False, True, True, False, False, False),
    ("H-SETUP", "Setup produtivo", "setup", True, True, False, False, False, False),
    ("H-REWORK", "Retrabalho controlado", "retrabalho", True, False, False, False, True, False),
    ("H-NOOP", "Atividade produtiva sem OP", "atividade_sem_op", True, False, False, False, False, False),
    ("H-UNKNOWN", "Estado incompatível — desconhecido", "desconhecido", None, None, None, False, False, False),
)


def _load_dsns() -> tuple[str, str, str, str]:
    values = dotenv_values(PROJECT_ROOT / ".env")
    common_test = str(os.getenv("TEST_DATABASE_URL") or values.get("TEST_DATABASE_URL") or "").strip()
    if not common_test:
        raise RuntimeError("TEST_DATABASE_URL precisa estar configurada.")

    test_values = conninfo_to_dict(common_test)
    if "test" not in str(test_values.get("dbname") or "").casefold():
        raise RuntimeError("Barreira de segurança: a fonte de usuários deve ser um banco de teste.")
    if "test" not in TARGET_DATABASE.casefold() or "homolog" not in TARGET_DATABASE.casefold():
        raise RuntimeError("O banco-alvo precisa conter 'test' e 'homolog' no nome.")
    if TARGET_DATABASE.casefold() in {
        str(test_values.get("dbname") or "").casefold(),
        "postgres",
    }:
        raise RuntimeError("Barreira de segurança: o alvo não é exclusivo da homologação.")

    target = make_conninfo(
        common_test,
        dbname=TARGET_DATABASE,
        connect_timeout="8",
        application_name="gestor_homologacao_extrema",
    )
    maintenance = make_conninfo(
        common_test,
        dbname="postgres",
        connect_timeout="8",
        application_name="gestor_homologacao_extrema_setup",
    )
    return common_test, common_test, target, maintenance


def _safe_target(dsn: str) -> dict:
    values = conninfo_to_dict(dsn)
    return {
        "host": values.get("host") or "local socket",
        "port": values.get("port") or "5432",
        "dbname": values.get("dbname") or "",
        "user": values.get("user") or "",
    }


def _ensure_target_database(maintenance_dsn: str) -> bool:
    with psycopg.connect(maintenance_dsn, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname = %s)",
            (TARGET_DATABASE,),
        ).fetchone()[0]
        if exists:
            return False
        connection.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(
                sql.Identifier(TARGET_DATABASE)
            )
        )
    return True


def _truncate_dedicated_target(connection) -> None:
    database = connection.execute("SELECT current_database() AS database_name").fetchone()["database_name"]
    if database.casefold() != TARGET_DATABASE.casefold():
        raise RuntimeError(f"Limpeza recusada no banco inesperado: {database}")
    tables = [
        row["tablename"]
        for row in connection.execute(
            """
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public' AND tablename <> 'schema_migrations'
            ORDER BY tablename
            """
        ).fetchall()
    ]
    if tables:
        connection.execute(
            sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(sql.Identifier(name) for name in tables)
            )
        )


def _copy_test_users(source_test_dsn: str, cursor) -> int:
    with psycopg.connect(source_test_dsn, row_factory=dict_row) as source:
        source.execute("SET TRANSACTION READ ONLY")
        users = source.execute(
            "SELECT nome, senha_hash, nivel, ativo, data_criacao FROM usuarios ORDER BY id"
        ).fetchall()
    cursor.executemany(
        """
        INSERT INTO usuarios (nome, senha_hash, nivel, ativo, data_criacao)
        VALUES (%(nome)s, %(senha_hash)s, %(nivel)s, %(ativo)s, %(data_criacao)s)
        ON CONFLICT (nome) DO UPDATE SET
            senha_hash = EXCLUDED.senha_hash,
            nivel = EXCLUDED.nivel,
            ativo = EXCLUDED.ativo,
            data_criacao = EXCLUDED.data_criacao
        """,
        users,
    )
    return len(users)


def _insert_configuration(cursor) -> None:
    cursor.execute(
        """
        INSERT INTO calendarios_produtivos (codigo, nome, timezone, ativo, criado_em)
        VALUES ('FABRICA-HOM', 'Fábrica — homologação extrema', 'America/Sao_Paulo', TRUE, %s)
        """,
        (START,),
    )
    shifts = (
        ("1º turno", time(6), time(14), False),
        ("2º turno", time(14), time(22), False),
        ("3º turno", time(22), time(6), True),
    )
    for weekday in range(7):
        for name, shift_start, shift_end, overnight in shifts:
            shift_id = cursor.execute(
                """
                INSERT INTO turnos_produtivos (
                    calendario_codigo, nome, dia_semana, hora_inicio, hora_fim,
                    cruza_meia_noite, minutos_intervalo, ativo
                ) VALUES ('FABRICA-HOM', %s, %s, %s, %s, %s, 45, TRUE)
                RETURNING id
                """,
                (name, weekday, shift_start, shift_end, overnight),
            ).fetchone()["id"]
            if not overnight:
                interval_start = (datetime.combine(date.min, shift_start) + timedelta(hours=4)).time()
                interval_end = (datetime.combine(date.min, interval_start) + timedelta(minutes=45)).time()
                cursor.execute(
                    """
                    INSERT INTO intervalos_turno_produtivo (
                        turno_id, nome, hora_inicio, hora_fim, desconta_tempo, ativo
                    ) VALUES (%s, 'Intervalo', %s, %s, TRUE, TRUE)
                    """,
                    (shift_id, interval_start, interval_end),
                )
    cursor.executemany(
        """
        INSERT INTO excecoes_calendario_produtivo (
            calendario_codigo, data, tipo, hora_inicio, hora_fim, motivo, ativo
        ) VALUES ('FABRICA-HOM', %s, %s, %s, %s, %s, TRUE)
        """,
        (
            (date(2026, 8, 15), "indisponivel", None, None, "Feriado fictício de homologação"),
            (date(2026, 8, 16), "disponivel_extra", time(6), time(12), "Turno extra fictício"),
        ),
    )

    for code, name, category, productive, planned, affects_availability, setup, rework, root in STATUS_ROWS:
        cursor.execute(
            """
            INSERT INTO catalogo_status_recursos (
                codigo, nome, grupo_codigo, grupo_nome, habilitado, classificacao,
                setup, retrabalho, retorno_automatico, parada_geral, oculto,
                requer_detalhe, requer_comentario, acao_padrao, fonte,
                sincronizado_em, categoria_gerencial, produtivo, planejado,
                afeta_disponibilidade, afeta_performance, afeta_qualidade,
                atividade_sem_op, requer_causa_raiz
            ) VALUES (
                %s, %s, 'HOM', 'Homologação', TRUE, 1,
                %s, %s, FALSE, FALSE, FALSE, TRUE, FALSE, NULL, %s, %s,
                %s, %s, %s, %s, FALSE, FALSE, %s, %s
            )
            """,
            (
                code,
                name,
                setup,
                rework,
                SEED_TAG,
                START,
                category,
                productive,
                planned,
                affects_availability,
                category == "atividade_sem_op",
                root,
            ),
        )

    resources = [
        (resource, sector)
        for sector, sector_resources in SECTOR_RESOURCES.items()
        for resource in sector_resources
    ] + list(SPECIAL_RESOURCES.items())
    for sequence, (resource, sector) in enumerate(resources, start=1):
        cursor.execute(
            """
            INSERT INTO catalogo_recursos_pcfactory (
                codigo, nome, tipo_setor, habilitado, fonte, sincronizado_em,
                calendario_codigo, capacidade_valor, capacidade_unidade
            ) VALUES (%s, %s, %s, TRUE, %s, %s, 'FABRICA-HOM', %s, 'horas/dia')
            """,
            (resource, resource, sector, SEED_TAG, START, 16 + sequence % 3),
        )

    cursor.executemany(
        """
        INSERT INTO operadores_apontamento (cracha, nome, ativo, fonte, criado_em)
        VALUES (%s, %s, TRUE, %s, %s)
        """,
        [
            (f"H{number:03d}", f"Operador Homologação {number:02d}", SEED_TAG, START)
            for number in range(1, 13)
        ],
    )


def _appointment_status(index: int) -> str:
    group = index % 10
    if group <= 5:
        return "Finalizado"
    return {
        6: "Em processo",
        7: "Aguardando",
        8: "Parada",
        9: "Setup" if (index // 10) % 2 else "Retrabalho",
    }[group]


def _insert_orders(cursor) -> dict:
    totals = Counter()
    sectors = ("Corte", "Dobra", "Usinagem", "Serra", "Solda", "Pintura")
    operator_ids = [row["id"] for row in cursor.execute("SELECT id FROM operadores_apontamento ORDER BY id")]
    simultaneous_ops = []

    for index in range(1, 121):
        op = f"HOMEXT{index:05d}"
        product = f"PÇ-HOM-{(index - 1) % 24 + 1:03d}"
        description = (
            "Conjunto de proteção — aço inoxidável, operação crítica com descrição longa "
            "para validar acentuação, truncamento e responsividade"
            if index == 1
            else f"Peça fictícia de homologação {index:03d}"
        )
        sector = sectors[(index - 1) % len(sectors)]
        resource = SECTOR_RESOURCES[sector][(index - 1) % len(SECTOR_RESOURCES[sector])]
        operation_number = str(((index - 1) % 5 + 1) * 10)
        planned = 40 + (index % 5) * 10
        status = _appointment_status(index)
        group = index % 10
        good = planned if group <= 5 else (0 if group == 7 else planned // (2 if group == 6 else 3))
        scrap = 2 + index % 3 if index % 5 == 0 else 0
        rework = 1 + index % 2 if index % 7 == 0 else 0
        day_offset = (index - 1) // 12
        slot = (index - 1) % 12
        started = START + timedelta(days=day_offset, minutes=slot * 75)
        setup_end = started + timedelta(minutes=10)
        production_end = setup_end + timedelta(minutes=45 + (index % 4) * 15)
        finished = production_end + (timedelta(minutes=10) if index % 4 == 0 else timedelta())
        is_done = status == "Finalizado"
        planned_start = started - timedelta(minutes=20)
        planned_end = planned_start + timedelta(minutes=75)
        deadline = planned_end + timedelta(hours=4 + index % 8)

        cursor.execute(
            """
            INSERT INTO catalogo_pcp_ops (
                codigo_op, produto_codigo, produto_descricao, quantidade, unidade,
                data_emissao, status_pcp, filial, local_estoque, roteiro, recurso,
                ativo, sincronizado_em, data_liberacao, inicio_planejado,
                fim_planejado, prazo_entrega, prioridade
            ) VALUES (%s, %s, %s, %s, 'PC', %s, %s, '04', '01', %s, %s,
                      TRUE, %s, %s, %s, %s, %s, %s)
            """,
            (
                op,
                product,
                description,
                planned,
                started.date() - timedelta(days=1),
                "ENCERRADA" if is_done else "ABERTA",
                f"ROT-{(index - 1) % 8 + 1:02d}",
                resource,
                START,
                started - timedelta(days=1),
                planned_start,
                planned_end,
                deadline,
                1 + index % 5,
            ),
        )
        operation_id = cursor.execute(
            """
            INSERT INTO catalogo_operacoes_op (
                codigo_op, produto_codigo, produto_descricao, numero_operacao,
                codigo_recurso, descricao_operacao, tipo_setor, filial, tipo,
                roteiro, tempo_medio_segundos, ordem, fonte, ativo, sincronizado_em
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, '04', 'P', %s, %s, 1, %s, TRUE, %s)
            RETURNING id
            """,
            (
                op,
                product,
                description,
                operation_number,
                resource,
                f"{sector} — operação homologada",
                sector,
                f"ROT-{(index - 1) % 8 + 1:02d}",
                45 + index % 20,
                SEED_TAG,
                START,
            ),
        ).fetchone()["id"]
        appointment_id = cursor.execute(
            """
            INSERT INTO apontamentos_operacionais (
                op, peca, tarefa_id, tipo_setor, maquina, status, quantidade,
                operador_fila, data_entrada, operador_inicio, data_inicio,
                operador_fim, data_fim, setor_destino, catalogo_operacao_id,
                numero_operacao, codigo_recurso, descricao_operacao,
                produto_codigo, produto_descricao, quantidade_boa,
                quantidade_refugo, motivo_parada, comentario,
                codigo_status_recurso, quantidade_retrabalho, lote,
                motivo_refugo, causa_raiz, tipo_setup
            ) VALUES (
                %s, %s, NULL, %s, %s, %s, %s, 'SEED-HOM', %s,
                %s, %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) RETURNING id
            """,
            (
                op,
                product,
                sector,
                resource,
                status,
                planned,
                started - timedelta(minutes=15),
                "Operador Homologação 01" if status != "Aguardando" else None,
                started if status != "Aguardando" else None,
                "Operador Homologação 02" if is_done else None,
                finished if is_done else None,
                operation_id,
                operation_number,
                resource,
                f"{sector} — operação homologada",
                product,
                description,
                good,
                scrap,
                "Falha mecânica" if status == "Parada" else None,
                "Carga determinística da homologação extrema.",
                {
                    "Parada": "H-STOP-MAN",
                    "Setup": "H-SETUP",
                    "Retrabalho": "H-REWORK",
                }.get(status),
                rework,
                f"L-HOM-{index:04d}",
                "Dimensão fora da tolerância" if scrap else None,
                None if index % 15 == 0 else ("Desgaste de ferramenta" if scrap else None),
                "Inicial" if status == "Setup" else None,
            ),
        ).fetchone()["id"]

        events = [("fila", started - timedelta(minutes=15), 0, 0, None)]
        if status != "Aguardando":
            events.extend(
                [
                    ("setup", started, 0, 0, "H-SETUP"),
                    ("producao", setup_end, 0, 0, "H-PROD"),
                ]
            )
            if index % 4 == 0:
                events.append(("parada", production_end, 0, 0, "H-STOP-MAN"))
            if is_done:
                events.append(("finalizado", finished, good, scrap, "H-PROD"))
            elif good or scrap:
                events.append(("parcial", finished, good, scrap, "H-PROD"))
        last_event_id = None
        for state, at, event_good, event_scrap, status_code in events:
            last_event_id = cursor.execute(
                """
                INSERT INTO eventos_apontamento_operador (
                    apontamento_id, estado, motivo, comentario, quantidade_boa,
                    quantidade_refugo, operador, data_hora, codigo_status_recurso,
                    recurso_roteiro_codigo, recurso_roteiro_nome, recurso_apontado,
                    recurso_divergente, interrupcao_programada, origem_automatica,
                    tipo_interrupcao
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, FALSE, FALSE, NULL) RETURNING id
                """,
                (
                    appointment_id,
                    state,
                    "Falha mecânica" if state == "parada" else None,
                    "Evento sintético auditável.",
                    event_good,
                    event_scrap,
                    f"Operador Homologação {(index - 1) % 12 + 1:02d}",
                    at,
                    status_code,
                    resource,
                    resource,
                    ("CNC-CONFLITO" if index == 11 else resource),
                    index == 11,
                ),
            ).fetchone()["id"]
        if last_event_id and status != "Aguardando":
            cursor.execute(
                "INSERT INTO operadores_evento_apontamento (evento_id, operador_id) VALUES (%s, %s)",
                (last_event_id, operator_ids[(index - 1) % len(operator_ids)]),
            )

        if good:
            cursor.execute(
                """
                INSERT INTO eventos_quantidade_producao (
                    tipo, quantidade, op, numero_operacao, produto_codigo,
                    recurso, tipo_setor, operador, lote, motivo, causa_raiz,
                    comentario, data_hora, origem, referencia_origem
                ) VALUES ('boa', %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL,
                          'Peças boas somente.', %s, %s, %s)
                """,
                (
                    good,
                    op,
                    operation_number,
                    product,
                    resource,
                    sector,
                    f"Operador Homologação {(index - 1) % 12 + 1:02d}",
                    f"L-HOM-{index:04d}",
                    finished,
                    SEED_TAG,
                    f"op:{op}:boa",
                ),
            )
        if scrap:
            cursor.execute(
                """
                INSERT INTO eventos_quantidade_producao (
                    tipo, quantidade, op, numero_operacao, produto_codigo,
                    recurso, tipo_setor, operador, lote, motivo, causa_raiz,
                    comentario, data_hora, origem, referencia_origem
                ) VALUES ('refugo', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          'Refugo não completa a OP.', %s, %s, %s)
                """,
                (
                    scrap,
                    op,
                    operation_number,
                    product,
                    resource,
                    sector,
                    f"Operador Homologação {(index - 1) % 12 + 1:02d}",
                    f"L-HOM-{index:04d}",
                    "Dimensão fora da tolerância",
                    None if index % 15 == 0 else "Desgaste de ferramenta",
                    finished,
                    SEED_TAG,
                    f"op:{op}:refugo",
                ),
            )
        if rework:
            cursor.execute(
                """
                INSERT INTO eventos_quantidade_producao (
                    tipo, quantidade, op, numero_operacao, produto_codigo,
                    recurso, tipo_setor, operador, lote, motivo, causa_raiz,
                    comentario, data_hora, origem, referencia_origem
                ) VALUES ('retrabalho', %s, %s, %s, %s, %s, %s, %s, %s,
                          'Correção dimensional', 'Programa desatualizado',
                          'Retrabalho separado de boas e refugo.', %s, %s, %s)
                """,
                (
                    rework,
                    op,
                    operation_number,
                    product,
                    resource,
                    sector,
                    f"Operador Homologação {(index - 1) % 12 + 1:02d}",
                    f"L-HOM-{index:04d}",
                    finished,
                    SEED_TAG,
                    f"op:{op}:retrabalho",
                ),
            )

        if status != "Aguardando":
            cursor.executemany(
                """
                INSERT INTO eventos_estado_recurso (
                    recurso, tipo_setor, categoria, codigo_status_recurso, op,
                    numero_operacao, produto_codigo, operador, motivo, causa_raiz,
                    comentario, data_inicio, data_fim, origem, referencia_origem,
                    planejado, automatico, tipo_interrupcao, apontamento_id,
                    evento_apontamento_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, FALSE, NULL, %s, NULL)
                """,
                [
                    (
                        resource,
                        sector,
                        "setup",
                        "H-SETUP",
                        op,
                        operation_number,
                        product,
                        "Operador Homologação 01",
                        "Setup inicial produtivo",
                        None,
                        "Setup não reduz disponibilidade nem performance.",
                        started,
                        setup_end,
                        SEED_TAG,
                        f"op:{op}:estado:setup",
                        True,
                        appointment_id,
                    ),
                    (
                        resource,
                        sector,
                        "producao",
                        "H-PROD",
                        op,
                        operation_number,
                        product,
                        "Operador Homologação 01",
                        None,
                        None,
                        "Produção física canônica.",
                        setup_end,
                        production_end,
                        SEED_TAG,
                        f"op:{op}:estado:producao",
                        False,
                        appointment_id,
                    ),
                ],
            )
            if index % 4 == 0:
                cursor.execute(
                    """
                    INSERT INTO eventos_estado_recurso (
                        recurso, tipo_setor, categoria, codigo_status_recurso, op,
                        numero_operacao, produto_codigo, operador, motivo, causa_raiz,
                        comentario, data_inicio, data_fim, origem, referencia_origem,
                        planejado, automatico, tipo_interrupcao, apontamento_id
                    ) VALUES (%s, %s, 'parada', 'H-STOP-MAN', %s, %s, %s,
                              'Operador Homologação 01', 'Falha mecânica',
                              'Desgaste de rolamento', 'Parada manual não programada.',
                              %s, %s, %s, %s, FALSE, FALSE, NULL, %s)
                    """,
                    (
                        resource,
                        sector,
                        op,
                        operation_number,
                        product,
                        production_end,
                        finished,
                        SEED_TAG,
                        f"op:{op}:estado:parada",
                        appointment_id,
                    ),
                )

        participation_end = finished if status != "Aguardando" else started
        cursor.execute(
            """
            INSERT INTO participacoes_operador (
                operador_id, cracha, nome, recurso, tipo_setor, op,
                numero_operacao, data_inicio, data_fim, origem, referencia_origem
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                operator_ids[(index - 1) % len(operator_ids)],
                f"H{(index - 1) % 12 + 1:03d}",
                f"Operador Homologação {(index - 1) % 12 + 1:02d}",
                resource,
                sector,
                op,
                operation_number,
                started,
                participation_end,
                SEED_TAG,
                f"op:{op}:participacao",
            ),
        )
        cursor.execute(
            """
            INSERT INTO historico (op, tipo, setor, motivo, quantidade, operador,
                                   data_hora, peca, tarefa_id)
            VALUES (%s, %s, %s, %s, %s, 'SEED-HOM', %s, %s, NULL)
            """,
            (op, status, sector, "Homologação extrema", good, finished, product),
        )

        totals["planned"] += planned
        totals["good"] += good
        totals["scrap"] += scrap
        totals["rework"] += rework
        totals["appointments"] += 1
        totals["quantity_events"] += int(bool(good)) + int(bool(scrap)) + int(bool(rework))
        totals[f"status:{status}"] += 1
        if index in (1, 2):
            simultaneous_ops.append((op, operation_number))

    return {**totals, "simultaneous_ops": simultaneous_ops}


def _insert_factory_edge_cases(cursor, simultaneous_ops) -> dict:
    # Sessão física compartilhada por duas OPs: 7200 s físicos = 3600 + 3600 s rateados.
    session_start = datetime(2026, 8, 16, 14, 0)
    session_end = datetime(2026, 8, 16, 16, 0)
    session_id = cursor.execute(
        """
        INSERT INTO sessoes_recurso (
            recurso, tipo_setor, data_inicio, data_fim, segundos_fisicos,
            origem, referencia_origem
        ) VALUES ('DOBRA-SIM-01', 'Dobra', %s, %s, 7200, %s, 'sessao:simultanea')
        RETURNING id
        """,
        (session_start, session_end, SEED_TAG),
    ).fetchone()["id"]
    cursor.execute(
        """
        INSERT INTO eventos_estado_recurso (
            recurso, tipo_setor, categoria, codigo_status_recurso, op,
            numero_operacao, operador, comentario, data_inicio, data_fim,
            origem, referencia_origem, planejado, automatico
        ) VALUES ('DOBRA-SIM-01', 'Dobra', 'producao', 'H-PROD', NULL, NULL,
                  'Equipe simultânea', 'Tempo físico único; OPs recebem rateio.',
                  %s, %s, %s, 'estado:simultaneo', FALSE, FALSE)
        """,
        (session_start, session_end, SEED_TAG),
    )
    for op, operation in simultaneous_ops:
        cursor.execute(
            """
            INSERT INTO rateios_tempo_op (
                sessao_recurso_id, op, numero_operacao, estrategia, peso,
                segundos_atribuidos, criado_em
            ) VALUES (%s, %s, %s, 'igualitario', 0.5, 3600, %s)
            """,
            (session_id, op, operation, START),
        )

    # Conflito explícito: o intervalo de 30 min deve permanecer desconhecido.
    cursor.executemany(
        """
        INSERT INTO eventos_estado_recurso (
            recurso, tipo_setor, categoria, codigo_status_recurso, op,
            numero_operacao, operador, motivo, comentario, data_inicio, data_fim,
            origem, referencia_origem, planejado, automatico
        ) VALUES ('CNC-CONFLITO', 'Usinagem', %s, %s, %s, '30',
                  'Operador Homologação 03', %s, %s, %s, %s, %s, %s, %s, FALSE)
        """,
        (
            (
                "producao",
                "H-PROD",
                "HOMEXT00011",
                None,
                "Estado produtivo sobreposto intencional.",
                datetime(2026, 8, 17, 16, 0),
                datetime(2026, 8, 17, 18, 0),
                SEED_TAG,
                "conflito:producao",
                False,
            ),
            (
                "parada",
                "H-STOP-MAN",
                "HOMEXT00011",
                "Leitura incompatível",
                "Conflito intencional — não eleger vencedor.",
                datetime(2026, 8, 17, 16, 30),
                datetime(2026, 8, 17, 17, 0),
                SEED_TAG,
                "conflito:parada",
                False,
            ),
        ),
    )

    for day_offset in range(10):
        day = START.date() + timedelta(days=day_offset)
        # Parada sem OP, manual e não programada.
        stop_start = datetime.combine(day, time(12, 20))
        cursor.execute(
            """
            INSERT INTO eventos_estado_recurso (
                recurso, tipo_setor, categoria, codigo_status_recurso, op,
                operador, motivo, causa_raiz, comentario, data_inicio, data_fim,
                origem, referencia_origem, planejado, automatico
            ) VALUES ('TURNO-RES-01', 'Usinagem', 'parada', 'H-STOP-MAN', NULL,
                      'Operador Homologação 04', 'Ajuste mecânico sem OP',
                      'Folga no conjunto', 'Parada permitida sem OP ativa.',
                      %s, %s, %s, %s, FALSE, FALSE)
            """,
            (
                stop_start,
                stop_start + timedelta(minutes=12),
                SEED_TAG,
                f"sem-op:parada:{day.isoformat()}",
            ),
        )
        activity_start = datetime.combine(day, time(13, 0))
        cursor.execute(
            """
            INSERT INTO eventos_estado_recurso (
                recurso, tipo_setor, categoria, codigo_status_recurso, op,
                operador, motivo, comentario, data_inicio, data_fim, origem,
                referencia_origem, planejado, automatico
            ) VALUES ('TURNO-RES-01', 'Usinagem', 'atividade_sem_op', 'H-NOOP', NULL,
                      'Operador Homologação 05', 'Limpeza técnica produtiva',
                      'Atividade produtiva sem OP.', %s, %s, %s, %s, FALSE, FALSE)
            """,
            (
                activity_start,
                activity_start + timedelta(minutes=18),
                SEED_TAG,
                f"sem-op:atividade:{day.isoformat()}",
            ),
        )

    # Limites oficiais: duas interrupções automáticas por dia, quantidade zero.
    cutoff_rows = []
    for day_offset in range(9):
        day = START.date() + timedelta(days=day_offset)
        for cutoff in (time(17, 30), time(21, 30)):
            at = datetime.combine(day, cutoff)
            cutoff_rows.append(
                (
                    "TURNO-RES-01",
                    "Usinagem",
                    "fora_turno",
                    "H-STOP-AUTO",
                    "Interrupção automática de fim de turno",
                    at,
                    at + timedelta(minutes=1),
                    SEED_TAG,
                    f"fim-turno:{at.isoformat()}",
                    True,
                    True,
                    "fim_turno",
                )
            )
    cursor.executemany(
        """
        INSERT INTO eventos_estado_recurso (
            recurso, tipo_setor, categoria, codigo_status_recurso, motivo,
            data_inicio, data_fim, origem, referencia_origem, planejado,
            automatico, tipo_interrupcao
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        cutoff_rows,
    )

    # Evento de duração zero válido e explicitamente auditável.
    cursor.execute(
        """
        INSERT INTO eventos_estado_recurso (
            recurso, tipo_setor, categoria, codigo_status_recurso, motivo,
            comentario, data_inicio, data_fim, origem, referencia_origem,
            planejado, automatico
        ) VALUES ('SERRA-ZERO', 'Serra', 'parada', 'H-STOP-MAN',
                  'Evento com duração zero', 'Não deve gerar tempo negativo.',
                  %s, %s, %s, 'duracao-zero', FALSE, FALSE)
        """,
        (datetime(2026, 8, 18, 10), datetime(2026, 8, 18, 10), SEED_TAG),
    )

    issues = (
        ("causa_raiz_ausente", "aviso", "Refugo sem causa raiz confirmada", "quantidade"),
        ("estado_conflitante", "critico", "Produção e parada simultâneas", "recurso"),
        ("duracao_zero", "info", "Evento com duração zero", "recurso"),
        ("recurso_divergente", "erro", "Recurso apontado diverge do roteiro", "evento"),
    )
    for index in range(12):
        issue = issues[index % len(issues)]
        cursor.execute(
            """
            INSERT INTO inconsistencias_dados (
                tipo, severidade, descricao, entidade, entidade_id, op,
                numero_operacao, recurso, operador, detectada_em, resolvida,
                observacao
            ) VALUES (%s, %s, %s, %s, %s, %s, '10', %s,
                      'AUDITOR-HOM', %s, FALSE, %s)
            """,
            (
                issue[0],
                issue[1],
                issue[2],
                issue[3],
                f"HOM-{index + 1:03d}",
                f"HOMEXT{index + 1:05d}",
                "CNC-CONFLITO" if issue[0] == "estado_conflitante" else "TURNO-RES-01",
                START + timedelta(days=index % 10, hours=index),
                "Evidência fictícia para o drill-down de qualidade.",
            ),
        )
    return {
        "rateio_session_seconds": 7200,
        "rateio_allocated_seconds": 7200,
        "conflicting_state_seconds": 1800,
        "manual_no_op_stops": 10,
        "productive_no_op_activities": 10,
        "automatic_shift_interruptions": len(cutoff_rows),
        "zero_duration_events": 1,
        "issues": 12,
    }


def _insert_cutting_and_highlight(cursor) -> dict:
    plans = actuals = completed_actuals = highlight_events = 0
    predicted_seconds = actual_seconds = 0
    for task_index in range(1, 25):
        task_code = f"T-HOM-{task_index:03d}"
        status = "Finalizado" if task_index <= 14 else ("Destacando" if task_index <= 20 else "Aguardando")
        task_start = START + timedelta(days=(task_index - 1) % 10, hours=1)
        task_end = task_start + timedelta(minutes=25 + task_index) if status == "Finalizado" else None
        task_id = cursor.execute(
            """
            INSERT INTO tarefas (
                codigo_tarefa, material, espessura, status,
                data_inicio_destaque, data_finalizacao, data_despacho, observacoes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (
                task_code,
                "AÇO INOX 304" if task_index % 2 else "AÇO CARBONO A36",
                2 + task_index % 8,
                status,
                task_start if status != "Aguardando" else None,
                task_end,
                task_end + timedelta(minutes=5) if task_end else None,
                "Observação de homologação com acentuação: peça, produção, operação e máquina.",
            ),
        ).fetchone()["id"]
        op_index = ((task_index - 1) * 5) + 1
        op = f"HOMEXT{op_index:05d}"
        product = f"PÇ-HOM-{(op_index - 1) % 24 + 1:03d}"
        cursor.execute(
            """
            INSERT INTO op_por_tarefa (
                tarefa_id, codigo_op, id_peca, setor_destino_original,
                setor_destino_atual, quantidade_original, quantidade_atual, editado
            ) VALUES (%s, %s, %s, 'Dobra', 'Dobra', 50, 50, FALSE)
            """,
            (task_id, op, product),
        )
        line_hash = f"hom:linha:{task_index:03d}"
        cursor.execute(
            """
            INSERT INTO catalogo_sigmanest_tarefas (
                codigo_tarefa, material, espessura, ativo, sincronizado_em
            ) VALUES (%s, %s, %s, TRUE, %s)
            """,
            (task_code, "AÇO INOX 304", 2 + task_index % 8, START),
        )
        cursor.execute(
            """
            INSERT INTO catalogo_sigmanest_programas (
                codigo_tarefa, programa, ativo, sincronizado_em
            ) VALUES (%s, %s, TRUE, %s)
            """,
            (task_code, f"PRG-HOM-{task_index:03d}", START),
        )
        cursor.execute(
            """
            INSERT INTO catalogo_sigmanest_ops (
                linha_hash, codigo_tarefa, codigo_op, id_peca, setor_destino,
                quantidade, dobra, usinagem, solda, chanfro, ativo,
                sincronizado_em
            ) VALUES (%s, %s, %s, %s, 'Dobra', 50, 'Sim', NULL, NULL, NULL, TRUE, %s)
            """,
            (line_hash, task_code, op, product, START),
        )

        if status != "Aguardando":
            cursor.execute(
                """
                INSERT INTO eventos_destaque_tarefa (
                    tarefa_id, estado, codigo_status_recurso, motivo, comentario,
                    operador, data_hora
                ) VALUES (%s, 'inicio', 'H-PROD', NULL,
                          'Início do destaque.', 'Operador Homologação 06', %s)
                """,
                (task_id, task_start),
            )
            highlight_events += 1
            if task_index % 4 == 0:
                cursor.executemany(
                    """
                    INSERT INTO eventos_destaque_tarefa (
                        tarefa_id, estado, codigo_status_recurso, motivo,
                        comentario, operador, data_hora
                    ) VALUES (%s, %s, %s, %s, %s,
                              'Operador Homologação 06', %s)
                    """,
                    (
                        (task_id, "parada", "H-STOP-MAN", "Ajuste de desenho", "Parada manual.", task_start + timedelta(minutes=8)),
                        (task_id, "retomada", "H-PROD", None, "Retomada manual.", task_start + timedelta(minutes=12)),
                    ),
                )
                highlight_events += 2
            if task_end:
                cursor.execute(
                    """
                    INSERT INTO eventos_destaque_tarefa (
                        tarefa_id, estado, codigo_status_recurso, motivo, comentario,
                        operador, data_hora
                    ) VALUES (%s, 'fim', 'H-PROD', NULL, 'Destaque finalizado.',
                              'Operador Homologação 06', %s)
                    """,
                    (task_id, task_end),
                )
                highlight_events += 1

        for nesting in (1, 2):
            plan_hash = f"hom:plano:{task_index:03d}:{nesting}"
            machine_sigmanest = "AMADA_ENSIS" if (task_index + nesting) % 2 else "MESSER_XPR_300"
            machine = "Laser Ensis 3015" if machine_sigmanest == "AMADA_ENSIS" else "Plasma TerraBlade 4"
            predicted = 900 + task_index * 20 + nesting * 60
            predicted_seconds += predicted
            plan_date = START.date() + timedelta(days=(task_index - 1) % 10)
            cursor.execute(
                """
                INSERT INTO catalogo_sigmanest_planos_corte (
                    plano_hash, codigo_tarefa, programa, nome_chapa,
                    sequencia_nesting, area_usada, fracao_sucata,
                    quantidade_processo, maquina_sigmanest, tempo_previsto_segundos,
                    tempo_previsto_formatado, data_programa, status_programa,
                    ativo, sincronizado_em
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, 'LIBERADO', TRUE, %s)
                """,
                (
                    plan_hash,
                    task_code,
                    f"PRG-HOM-{task_index:03d}",
                    f"CHAPA {3000 + task_index} × {1500 + nesting}",
                    nesting,
                    1_000_000 + task_index * 1_000 + nesting * 100,
                    round(0.05 + ((task_index + nesting) % 10) / 100, 2),
                    20 + task_index,
                    machine_sigmanest,
                    predicted,
                    f"{predicted // 60} min",
                    plan_date,
                    START,
                ),
            )
            plans += 1
            if plans <= 30:
                actual_start = datetime.combine(plan_date, time(8)) + timedelta(minutes=nesting * 20)
                duration = predicted + ((task_index % 5) - 2) * 90
                is_finished = plans <= 20
                actual_end = actual_start + timedelta(seconds=duration) if is_finished else None
                cursor.execute(
                    """
                    INSERT INTO apontamentos_corte (
                        plano_hash, codigo_tarefa, programa, nome_chapa,
                        sequencia_nesting, material, espessura, maquina,
                        maquina_sigmanest, quantidade_processo, tempo_previsto_segundos,
                        data_programa, area_usada, fracao_sucata, status,
                        operador_inicio, data_inicio, operador_fim, data_fim
                    ) VALUES (%s, %s, %s, %s, %s, 'AÇO INOX 304', %s, %s, %s,
                              %s, %s, %s, %s, %s, %s,
                              'Operador Homologação 07', %s, %s, %s)
                    """,
                    (
                        plan_hash,
                        task_code,
                        f"PRG-HOM-{task_index:03d}",
                        f"CHAPA {3000 + task_index} × {1500 + nesting}",
                        nesting,
                        2 + task_index % 8,
                        machine,
                        machine_sigmanest,
                        20 + task_index,
                        predicted,
                        plan_date,
                        1_000_000 + task_index * 1_000 + nesting * 100,
                        round(0.05 + ((task_index + nesting) % 10) / 100, 2),
                        "Finalizado" if is_finished else "Em processo",
                        actual_start,
                        "Operador Homologação 08" if is_finished else None,
                        actual_end,
                    ),
                )
                actuals += 1
                if is_finished:
                    completed_actuals += 1
                    actual_seconds += duration

    return {
        "tasks": 24,
        "plans": plans,
        "actual_cuttings": actuals,
        "completed_cuttings": completed_actuals,
        "predicted_cutting_seconds": predicted_seconds,
        "completed_actual_cutting_seconds": actual_seconds,
        "highlight_events": highlight_events,
    }


def _finalize(cursor, users_copied: int, expected: dict) -> None:
    cursor.execute(
        """
        INSERT INTO eventos_sistema (
            tipo, origem, referencia, mensagem, operador, detalhes, data_hora
        ) VALUES ('homologacao_extrema_seed', %s, %s,
                  'Dataset ouro da homologação extrema aplicado.', 'SEED-HOM',
                  %s, %s)
        """,
        (
            "tests/homologacao_extrema/seed_homologacao_extrema.py",
            SEED_TAG,
            json.dumps({"users_copied": users_copied, "expected": expected}, ensure_ascii=False),
            END,
        ),
    )


def seed() -> dict:
    user_source_test_dsn, common_test_dsn, target_dsn, maintenance_dsn = _load_dsns()
    created = _ensure_target_database(maintenance_dsn)
    os.environ["TEST_DATABASE_URL"] = target_dsn
    os.environ["GESTOR_EXPECTED_DATABASE"] = TARGET_DATABASE
    config = PostgresConfig(dsn=target_dsn, min_pool_size=1, max_pool_size=6, pool_timeout=8)
    db = Database(config=config)
    try:
        with db.connection() as connection:
            _truncate_dedicated_target(connection)
            with connection.cursor() as cursor:
                users_copied = _copy_test_users(user_source_test_dsn, cursor)
                _insert_configuration(cursor)
                order_totals = _insert_orders(cursor)
                edge_totals = _insert_factory_edge_cases(
                    cursor,
                    order_totals.pop("simultaneous_ops"),
                )
                cut_totals = _insert_cutting_and_highlight(cursor)
                expected = {
                    "dataset": SEED_TAG,
                    "period": {"start": START.isoformat(), "end": END.isoformat()},
                    "schema_version": SCHEMA_VERSION,
                    "users_copied": users_copied,
                    "counts": {
                        "orders": 120,
                        "operations": 120,
                        "appointments": order_totals["appointments"],
                        "quantity_events": order_totals["quantity_events"],
                        "tasks": cut_totals["tasks"],
                        "cut_plans": cut_totals["plans"],
                        "cut_appointments": cut_totals["actual_cuttings"],
                        "highlight_events": cut_totals["highlight_events"],
                        "operator_badges": 12,
                        "data_issues": edge_totals["issues"],
                    },
                    "quantities": {
                        "planned": order_totals["planned"],
                        "good": order_totals["good"],
                        "scrap": order_totals["scrap"],
                        "rework": order_totals["rework"],
                    },
                    "statuses": {
                        key.removeprefix("status:"): value
                        for key, value in order_totals.items()
                        if key.startswith("status:")
                    },
                    "edge_cases": edge_totals,
                    "cutting": cut_totals,
                    "rules": {
                        "good_only_completes_order": True,
                        "scrap_does_not_complete_order": True,
                        "setup_is_productive": True,
                        "manual_stop_is_unplanned": True,
                        "automatic_interruption_is_planned": True,
                        "official_cutoffs": ["17:30:00", "21:30:00"],
                        "simultaneous_orders_do_not_multiply_physical_time": True,
                        "conflicts_are_unknown": True,
                        "management_correction_tab": False,
                    },
                }
                _finalize(cursor, users_copied, expected)
        EXPECTED_PATH.write_text(
            json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        result = {
            "created": created,
            "user_source_test": _safe_target(user_source_test_dsn),
            "common_test": _safe_target(common_test_dsn),
            "target": _safe_target(target_dsn),
            "expected_path": str(EXPECTED_PATH),
            "expected": expected,
        }
        ACTUAL_PATH.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result
    finally:
        db.close()


if __name__ == "__main__":
    payload = seed()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
