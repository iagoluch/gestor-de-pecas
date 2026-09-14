"""Cria uma história operacional determinística de três meses em banco isolado.

O script reutiliza apenas as barreiras de conexão/migração da homologação
extrema. Toda a massa desta simulação é nova e o banco operacional é aberto
somente para copiar usuários existentes.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Sem default: o banco dedicado da simulação precisa ser informado em
# SIMULACAO_DATABASE_NAME. Nunca aponte para o banco de TESTE oficial.
TARGET_DATABASE = os.getenv("SIMULACAO_DATABASE_NAME", "").strip()
os.environ["HOMOLOG_DATABASE_NAME"] = TARGET_DATABASE

from app.database.config import PostgresConfig  # noqa: E402
from app.database.database import Database  # noqa: E402
from app.database.schema import SCHEMA_VERSION  # noqa: E402
from tests.homologacao_extrema import seed_homologacao_extrema as isolation  # noqa: E402


START = datetime(2026, 6, 1, 6, 0, 0)
SIMULATED_NOW = datetime(2026, 8, 24, 8, 32, 0)
SEED_TAG = "simulacao_historica_3_meses_v1"
RANDOM_SEED = 20260824
OUTPUT_DIR = Path(__file__).resolve().parent
EXPECTED_PATH = OUTPUT_DIR / "expected_results.json"
RESULT_PATH = OUTPUT_DIR / "seed_result.json"

RESOURCES = {
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
}
RESOURCE_ROWS = tuple(
    (resource, sector)
    for sector, sector_resources in RESOURCES.items()
    for resource in sector_resources
)

PROFILE_BY_RESOURCE = {
    "Laser Ensis 3015": "excelente",
    "Plasma TerraBlade 4": "muito_bom",
    "1303": "bom",
    "2204": "medio",
    "Gasparini": "muito_bom",
    "Eurostec": "excelente",
    "Fresadora FTV31": "muito_bom",
    "Romi D 1000": "critico_pontual",
    "Romi GL 350M": "bom",
    "Torno Mecânico": "medio",
    "SFG-330": "bom",
    "S4220": "muito_bom",
    "SFHA-10": "medio",
    "Estação 1": "excelente",
    "Estação 2": "muito_bom",
    "Estação 3": "bom",
    "Estação 4": "bom",
    "Estação 5": "muito_bom",
    "Estação 6": "bom",
    "Estação 7": "medio",
    "Estação 8": "bom",
    "Estação 9": "ruim",
    "Estação 10": "ocioso",
    "Pintura": "muito_bom",
}

PROFILE_AVAILABILITY_OFFSET = {
    "excelente": 0.018,
    "muito_bom": 0.010,
    "bom": 0.0,
    "medio": -0.025,
    "ruim": -0.060,
    "critico_pontual": -0.085,
    "ocioso": -0.040,
}

MONTH_MODEL = {
    6: {
        "availability": 0.895,
        "setup_ratio": 0.035,
        "rework_time_ratio": 0.006,
        "no_op_ratio": 0.004,
        "quality_loss_ratio": 0.026,
        "actual_standard_ratio": 1.080,
    },
    7: {
        "availability": 0.925,
        "setup_ratio": 0.025,
        "rework_time_ratio": 0.005,
        "no_op_ratio": 0.003,
        "quality_loss_ratio": 0.014,
        "actual_standard_ratio": 1.045,
    },
    8: {
        "availability": 0.935,
        "setup_ratio": 0.020,
        "rework_time_ratio": 0.004,
        "no_op_ratio": 0.003,
        "quality_loss_ratio": 0.008,
        "actual_standard_ratio": 1.025,
    },
}

STATUS_ROWS = (
    ("SIM-PROD", "Produção", "producao", True, False, False, False, False, False),
    ("SIM-STOP-MAN", "Parada manual não programada", "parada", False, False, True, False, False, True),
    ("SIM-STOP-AUTO", "Interrupção automática de fim de turno", "fora_turno", False, True, False, False, False, False),
    ("SIM-SETUP", "Setup produtivo", "setup", True, True, False, True, False, False),
    ("SIM-REWORK", "Retrabalho controlado", "retrabalho", True, False, False, False, True, False),
    ("SIM-NOOP", "Atividade produtiva sem OP", "atividade_sem_op", True, False, False, False, False, False),
    ("SIM-QUEUE", "Sem demanda / fila", "fila", False, True, False, False, False, False),
    ("SIM-UNKNOWN", "Estado incompatível — desconhecido", "desconhecido", None, None, None, False, False, False),
)

STOP_REASONS = (
    ("Manutenção corretiva", "Desgaste de componente"),
    ("Falta de material", "Abastecimento atrasado"),
    ("Ajuste de processo", "Parâmetro fora da faixa"),
    ("Reunião operacional", "Alinhamento de segurança"),
    ("Pausa técnica", "Inspeção preventiva"),
)
SCRAP_REASONS = (
    ("Dimensão fora da tolerância", "Desgaste de ferramenta"),
    ("Rebarba excessiva", "Parâmetro de corte inadequado"),
    ("Defeito superficial", "Contaminação do material"),
    ("Furo deslocado", "Referenciamento incorreto"),
)

PRODUCT_BASE_QUANTITY = {
    "Corte": 720,
    "Dobra": 560,
    "Usinagem": 420,
    "Serra": 680,
    "Solda": 300,
    "Pintura": 840,
}

BREAKS = (
    (time(10, 0), time(10, 30)),
    (time(15, 30), time(15, 45)),
    (time(19, 15), time(19, 30)),
)


def _history_days() -> list[date]:
    result = []
    current = START.date()
    last = date(2026, 8, 22)
    while current <= last:
        if current.weekday() < 6:
            result.append(current)
        current += timedelta(days=1)
    if len(result) != 72:
        raise RuntimeError(f"Calendário histórico inesperado: {len(result)} dias produtivos.")
    return result


def _safe_dsns():
    user_source_test, common_test, target, maintenance = isolation._load_dsns()
    safe = {
        "user_source_test": isolation._safe_target(user_source_test),
        "common_test": isolation._safe_target(common_test),
        "target": isolation._safe_target(target),
    }
    if safe["target"]["dbname"] != TARGET_DATABASE:
        raise RuntimeError("Barreira de segurança: nome do banco de simulação inesperado.")
    return user_source_test, common_test, target, maintenance, safe


def _insert_configuration(cursor) -> None:
    cursor.execute(
        """
        INSERT INTO calendarios_produtivos (codigo, nome, timezone, ativo, criado_em)
        VALUES ('FABRICA-SIM-3M', 'Fábrica — simulação histórica de 3 meses',
                'America/Sao_Paulo', TRUE, %s)
        """,
        (START,),
    )
    shifts = (
        ("1º turno", time(6), time(14), 30, time(10), time(10, 30)),
        ("2º turno", time(14), time(17, 30), 15, time(15, 30), time(15, 45)),
        ("3º turno", time(17, 30), time(21, 30), 15, time(19, 15), time(19, 30)),
    )
    for weekday in range(6):
        for name, shift_start, shift_end, break_minutes, break_start, break_end in shifts:
            shift_id = cursor.execute(
                """
                INSERT INTO turnos_produtivos (
                    calendario_codigo, nome, dia_semana, hora_inicio, hora_fim,
                    cruza_meia_noite, minutos_intervalo, ativo
                ) VALUES ('FABRICA-SIM-3M', %s, %s, %s, %s, FALSE, %s, TRUE)
                RETURNING id
                """,
                (name, weekday, shift_start, shift_end, break_minutes),
            ).fetchone()["id"]
            cursor.execute(
                """
                INSERT INTO intervalos_turno_produtivo (
                    turno_id, nome, hora_inicio, hora_fim, desconta_tempo, ativo
                ) VALUES (%s, 'Intervalo', %s, %s, TRUE, TRUE)
                """,
                (shift_id, break_start, break_end),
            )

    cursor.executemany(
        """
        INSERT INTO excecoes_calendario_produtivo (
            calendario_codigo, data, tipo, hora_inicio, hora_fim, motivo, ativo
        ) VALUES ('FABRICA-SIM-3M', %s, %s, %s, %s, %s, TRUE)
        """,
        (
            (date(2026, 6, 12), "indisponivel", time(6), time(10), "Manutenção elétrica programada"),
            (date(2026, 7, 9), "indisponivel", time(14), time(17, 30), "Treinamento fabril programado"),
            (date(2026, 8, 15), "indisponivel", None, None, "Feriado da simulação"),
            (date(2026, 8, 16), "disponivel_extra", time(6), time(12), "Turno extra de recuperação"),
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
                %s, %s, 'SIM3M', 'Simulação 3 meses', TRUE, 1,
                %s, %s, FALSE, FALSE, FALSE, TRUE, FALSE, NULL, %s, %s,
                %s, %s, %s, %s, FALSE, FALSE, %s, %s
            )
            """,
            (
                code, name, setup, rework, SEED_TAG, START, category,
                productive, planned, affects_availability,
                category == "atividade_sem_op", root,
            ),
        )

    for sequence, (resource, sector) in enumerate(RESOURCE_ROWS, start=1):
        cursor.execute(
            """
            INSERT INTO catalogo_recursos_pcfactory (
                codigo, nome, tipo_setor, habilitado, fonte, sincronizado_em,
                calendario_codigo, capacidade_valor, capacidade_unidade
            ) VALUES (%s, %s, %s, TRUE, %s, %s, 'FABRICA-SIM-3M', %s, 'horas/dia')
            """,
            (resource, resource, sector, SEED_TAG, START, 14.5),
        )

    cursor.executemany(
        """
        INSERT INTO operadores_apontamento (cracha, nome, ativo, fonte, criado_em)
        VALUES (%s, %s, TRUE, %s, %s)
        """,
        [
            (f"S{number:03d}", f"Operador Simulação {number:02d}", SEED_TAG, START)
            for number in range(1, 37)
        ],
    )


def _available_segments(day: date) -> list[tuple[datetime, datetime]]:
    points = [
        (time(6), time(10)),
        (time(10, 30), time(15, 30)),
        (time(15, 45), time(19, 15)),
        (time(19, 30), time(21, 30)),
    ]
    return [(datetime.combine(day, start), datetime.combine(day, end)) for start, end in points]


def _allocate_categories(day: date, durations: list[tuple[str, int]]) -> list[tuple[str, datetime, datetime]]:
    result = []
    segments = _available_segments(day)
    segment_index = 0
    cursor_at = segments[0][0]
    for category, seconds in durations:
        remaining = max(0, int(seconds))
        while remaining > 0:
            if segment_index >= len(segments):
                raise RuntimeError("A composição temporal excedeu o calendário disponível.")
            segment_start, segment_end = segments[segment_index]
            cursor_at = max(cursor_at, segment_start)
            available = int((segment_end - cursor_at).total_seconds())
            if available <= 0:
                segment_index += 1
                if segment_index < len(segments):
                    cursor_at = segments[segment_index][0]
                continue
            used = min(available, remaining)
            end_at = cursor_at + timedelta(seconds=used)
            result.append((category, cursor_at, end_at))
            cursor_at = end_at
            remaining -= used
    return result


def _duration_model(day: date, resource: str, sequence: int) -> dict[str, int]:
    model = MONTH_MODEL[day.month]
    profile = PROFILE_BY_RESOURCE[resource]
    weekly_shock = -0.035 if day.isocalendar().week % 5 == 0 and day.weekday() == 2 else 0.0
    daily_wave = ((sequence % 7) - 3) * 0.0025
    availability = max(
        0.72,
        min(0.975, model["availability"] + PROFILE_AVAILABILITY_OFFSET[profile] + weekly_shock + daily_wave),
    )
    if profile == "ocioso":
        availability = min(availability, 0.83)
    available_seconds = 52_200
    worked = round(available_seconds * availability)
    setup_ratio = model["setup_ratio"] * {
        "excelente": 0.78,
        "muito_bom": 0.88,
        "bom": 1.0,
        "medio": 1.18,
        "ruim": 1.42,
        "critico_pontual": 1.58,
        "ocioso": 0.85,
    }[profile]
    setup = round(available_seconds * setup_ratio)
    rework = round(available_seconds * model["rework_time_ratio"])
    no_op = round(available_seconds * model["no_op_ratio"])
    production = max(0, worked - setup - rework - no_op)
    unproductive = available_seconds - worked
    downtime_share = 0.68 if profile != "ocioso" else 0.18
    downtime = round(unproductive * downtime_share)
    queue = unproductive - downtime
    return {
        "available": available_seconds,
        "worked": worked,
        "production": production,
        "setup": setup,
        "rework": rework,
        "no_op": no_op,
        "downtime": downtime,
        "queue": queue,
    }


def _category_sequence(model: dict[str, int]) -> list[tuple[str, int]]:
    production = model["production"]
    downtime = model["downtime"]
    return [
        ("setup", model["setup"]),
        ("producao", round(production * 0.36)),
        ("parada", round(downtime * 0.42)),
        ("producao", round(production * 0.34)),
        ("retrabalho", model["rework"]),
        ("parada", downtime - round(downtime * 0.42)),
        ("producao", production - round(production * 0.36) - round(production * 0.34)),
        ("atividade_sem_op", model["no_op"]),
        ("fila", model["queue"]),
    ]


def _attainment(month: int, sequence: int) -> float:
    if sequence % 17 == 0:
        return {6: 0.90, 7: 0.94, 8: 0.96}[month]
    if sequence % 11 == 0:
        return {6: 1.035, 7: 1.045, 8: 1.055}[month]
    if sequence % 7 == 0:
        return {6: 0.975, 7: 0.988, 8: 0.995}[month]
    return {6: 1.000, 7: 1.010, 8: 1.018}[month]


def _build_orders() -> tuple[list[dict], dict]:
    rows = []
    monthly = defaultdict(Counter)
    sequence = 0
    for day in _history_days():
        for resource, sector in RESOURCE_ROWS:
            sequence += 1
            op = f"SIM3M{sequence:06d}"
            product_number = (sequence - 1) % 72 + 1
            product = f"PÇ-SIM-{product_number:03d}"
            description = (
                "Conjunto estrutural de proteção — aço inoxidável, montagem crítica com descrição longa para validar acentuação, pesquisa e responsividade"
                if sequence % 137 == 1
                else f"Peça histórica simulada {product_number:03d} — {sector}"
            )
            model = _duration_model(day, resource, sequence)
            schedule = _allocate_categories(day, _category_sequence(model))
            planned = PRODUCT_BASE_QUANTITY[sector] + ((sequence % 9) - 4) * 20
            good = max(1, round(planned * _attainment(day.month, sequence)))
            loss_rate = MONTH_MODEL[day.month]["quality_loss_ratio"]
            profile = PROFILE_BY_RESOURCE[resource]
            if profile in {"ruim", "critico_pontual"}:
                loss_rate *= 1.55
            elif profile in {"excelente", "muito_bom"}:
                loss_rate *= 0.72
            total_loss = max(1, round(good * loss_rate / max(0.001, 1.0 - loss_rate)))
            scrap = max(1, round(total_loss * 0.78))
            rework_qty = max(0, total_loss - scrap)
            # Toda OP desta faixa pertence ao histórico fechado e possui data de
            # término. Variação abaixo/acima do plano permanece na quantidade,
            # sem transformar uma execução encerrada em sessão ativa antiga.
            status = "Finalizado"
            actual_per_piece = model["production"] / good
            standard_per_piece = round(
                actual_per_piece / MONTH_MODEL[day.month]["actual_standard_ratio"],
                6,
            )
            started = datetime.combine(day, time(6))
            finished = datetime.combine(day, time(21, 30))
            planned_start = started - timedelta(minutes=15)
            planned_end = finished - timedelta(minutes=20 if day.month == 6 else 35 if day.month == 7 else 45)
            deadline = planned_end + timedelta(hours=(sequence % 5) - 2)
            rows.append({
                "sequence": sequence,
                "op": op,
                "product": product,
                "description": description,
                "sector": sector,
                "resource": resource,
                "operation": str(((sequence - 1) % 5 + 1) * 10),
                "planned": planned,
                "good": good,
                "scrap": scrap,
                "rework_qty": rework_qty,
                "status": status,
                "started": started,
                "finished": finished,
                "planned_start": planned_start,
                "planned_end": planned_end,
                "deadline": deadline,
                "priority": 1 + sequence % 5,
                "standard_per_piece": standard_per_piece,
                "schedule": schedule,
                "duration_model": model,
                "operator_number": (sequence - 1) % 36 + 1,
                "lot": f"L-SIM-{day:%Y%m}-{sequence:06d}",
                "stop_reason": STOP_REASONS[sequence % len(STOP_REASONS)],
                "scrap_reason": SCRAP_REASONS[sequence % len(SCRAP_REASONS)],
                "current": False,
            })
            bucket = monthly[day.month]
            bucket["orders"] += 1
            bucket["planned"] += planned
            bucket["good"] += good
            bucket["scrap"] += scrap
            bucket["rework"] += rework_qty
            bucket["seconds:standard_run"] += standard_per_piece * good
            for key in ("available", "worked", "production", "setup", "rework", "no_op", "downtime", "queue"):
                bucket[f"seconds:{key}"] += model[key]

    current_states = {
        "Laser Ensis 3015": "producao",
        "1303": "producao",
        "2204": "setup",
        "Eurostec": "producao",
        "Fresadora FTV31": "producao",
        "Romi D 1000": "parada",
        "S4220": "producao",
        "Estação 1": "producao",
        "Estação 2": "producao",
        "Estação 4": "producao",
        "Estação 5": "producao",
        "Pintura": "producao",
    }
    day = SIMULATED_NOW.date()
    for resource, sector in RESOURCE_ROWS:
        sequence += 1
        category = current_states.get(resource)
        op = f"SIM3M{sequence:06d}"
        product_number = (sequence - 1) % 72 + 1
        product = f"PÇ-SIM-{product_number:03d}"
        planned = PRODUCT_BASE_QUANTITY[sector]
        started = datetime.combine(day, time(6, 5)) + timedelta(minutes=sequence % 20)
        if category == "setup":
            started = datetime.combine(day, time(7, 48))
        elif category == "parada":
            started = datetime.combine(day, time(8, 3))
        standard_per_piece = 75.0 + sequence % 20
        current_seconds = max(0, round((SIMULATED_NOW - started).total_seconds()))
        if category == "producao":
            demand_limited_good = round(planned * (0.18 + (sequence % 5) * 0.035))
            # Mantém o snapshot demonstrativo fisicamente coerente: a quantidade
            # boa atual não pode exigir mais tempo-padrão que o tempo transcorrido.
            # A fórmula canônica de Performance/OEE permanece intocada.
            feasible_good = int(current_seconds * (0.86 + (sequence % 7) * 0.015) / standard_per_piece)
            good = min(demand_limited_good, max(0, feasible_good))
        else:
            good = 0
        scrap = 1 if category == "producao" and sequence % 4 == 0 else 0
        rework_qty = 1 if category == "producao" and sequence % 7 == 0 else 0
        status = {
            "producao": "Em processo",
            "setup": "Setup",
            "parada": "Parada",
        }.get(category, "Aguardando")
        rows.append({
            "sequence": sequence,
            "op": op,
            "product": product,
            "description": f"Ordem atual simulada — {sector} / {resource}",
            "sector": sector,
            "resource": resource,
            "operation": str(((sequence - 1) % 5 + 1) * 10),
            "planned": planned,
            "good": good,
            "scrap": scrap,
            "rework_qty": rework_qty,
            "status": status,
            "started": started if category else None,
            "finished": None,
            "planned_start": datetime.combine(day, time(6)),
            "planned_end": SIMULATED_NOW,
            "deadline": SIMULATED_NOW,
            "priority": 1 + sequence % 5,
            "standard_per_piece": standard_per_piece,
            "schedule": [],
            "duration_model": None,
            "operator_number": (sequence - 1) % 36 + 1,
            "lot": f"L-SIM-ATUAL-{sequence:06d}",
            "stop_reason": STOP_REASONS[sequence % len(STOP_REASONS)],
            "scrap_reason": SCRAP_REASONS[sequence % len(SCRAP_REASONS)],
            "current": True,
            "current_category": category,
        })
        bucket = monthly[8]
        bucket["orders"] += 1
        bucket["planned"] += planned
        bucket["good"] += good
        bucket["scrap"] += scrap
        bucket["rework"] += rework_qty
        if category:
            bucket["seconds:available"] += current_seconds
            if category in {"producao", "setup", "retrabalho", "atividade_sem_op"}:
                bucket["seconds:worked"] += current_seconds
            category_key = {
                "producao": "production",
                "parada": "downtime",
                "setup": "setup",
                "retrabalho": "rework",
                "atividade_sem_op": "no_op",
                "fila": "queue",
            }[category]
            bucket[f"seconds:{category_key}"] += current_seconds
            if category == "producao":
                bucket["seconds:standard_run"] += standard_per_piece * good

    # Os conflitos deliberados substituem o estado original pelo estado
    # desconhecido durante quinze minutos na consolidação física.
    for month, conflict_day in ((6, 23), (7, 21), (8, 18)):
        conflict_at = datetime(2026, month, conflict_day, 11, 0)
        original = next(
            row
            for row in rows
            if not row["current"]
            and row["resource"] == "Romi D 1000"
            and row["started"].date() == conflict_at.date()
        )
        bucket = monthly[month]
        conflict_end = conflict_at + timedelta(minutes=15)
        conflicting_seconds = 0
        covered_seconds = 0
        for original_category, start_at, end_at in original["schedule"]:
            overlap = max(
                0,
                round((min(end_at, conflict_end) - max(start_at, conflict_at)).total_seconds()),
            )
            if not overlap:
                continue
            covered_seconds += overlap
            # Parada sobre parada é compatível; apenas categorias diferentes
            # viram desconhecido na consolidação física.
            if original_category == "parada":
                continue
            source_key = {
                "producao": "production",
                "parada": "downtime",
                "setup": "setup",
                "retrabalho": "rework",
                "atividade_sem_op": "no_op",
                "fila": "queue",
            }[original_category]
            bucket[f"seconds:{source_key}"] -= overlap
            if original_category in {"producao", "setup", "retrabalho", "atividade_sem_op"}:
                bucket["seconds:worked"] -= overlap
            conflicting_seconds += overlap
        if covered_seconds != 900:
            raise RuntimeError(
                f"Conflito histórico não cobriu 900 segundos em {conflict_at}: {covered_seconds}."
            )
        bucket["seconds:unknown"] += conflicting_seconds

    return rows, {str(month): dict(values) for month, values in sorted(monthly.items())}


def _insert_order_catalogs(cursor, orders: list[dict]) -> dict[str, int]:
    cursor.executemany(
        """
        INSERT INTO catalogo_pcp_ops (
            codigo_op, produto_codigo, produto_descricao, quantidade, unidade,
            data_emissao, status_pcp, filial, local_estoque, roteiro, recurso,
            ativo, sincronizado_em, data_liberacao, inicio_planejado,
            fim_planejado, prazo_entrega, prioridade
        ) VALUES (%s, %s, %s, %s, 'PC', %s, %s, '04', '01', %s, %s,
                  TRUE, %s, %s, %s, %s, %s, %s)
        """,
        [
            (
                row["op"], row["product"], row["description"], row["planned"],
                (row["started"] or row["planned_start"]).date() - timedelta(days=2),
                "ENCERRADA" if row["status"] == "Finalizado" else "ABERTA",
                f"ROT-{(row['sequence'] - 1) % 12 + 1:02d}", row["resource"], START,
                row["planned_start"] - timedelta(days=2), row["planned_start"],
                row["planned_end"], row["deadline"], row["priority"],
            )
            for row in orders
        ],
    )
    cursor.executemany(
        """
        INSERT INTO catalogo_operacoes_op (
            codigo_op, produto_codigo, produto_descricao, numero_operacao,
            codigo_recurso, descricao_operacao, tipo_setor, filial, tipo,
            roteiro, tempo_medio_segundos, ordem, fonte, ativo, sincronizado_em
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, '04', 'P', %s, %s, 1, %s, TRUE, %s)
        """,
        [
            (
                row["op"], row["product"], row["description"], row["operation"],
                row["resource"], f"{row['sector']} — operação histórica simulada",
                row["sector"], f"ROT-{(row['sequence'] - 1) % 12 + 1:02d}",
                row["standard_per_piece"], SEED_TAG, START,
            )
            for row in orders
        ],
    )
    return {
        row["codigo_op"]: row["id"]
        for row in cursor.execute(
            "SELECT id, codigo_op FROM catalogo_operacoes_op ORDER BY id"
        ).fetchall()
    }


def _insert_appointments(cursor, orders: list[dict], operation_ids: dict[str, int]) -> dict[str, int]:
    cursor.executemany(
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
            %s, %s, NULL, %s, %s, %s, %s, 'SEED-SIM', %s,
            %s, %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        """,
        [
            (
                row["op"], row["product"], row["sector"], row["resource"],
                row["status"], max(row["planned"], row["good"]), row["planned_start"] - timedelta(minutes=15),
                f"Operador Simulação {row['operator_number']:02d}" if row["started"] else None,
                row["started"],
                f"Operador Simulação {(row['operator_number'] % 36) + 1:02d}" if row["finished"] else None,
                row["finished"], operation_ids[row["op"]], row["operation"],
                row["resource"], f"{row['sector']} — operação histórica simulada",
                row["product"], row["description"], row["good"], row["scrap"],
                row["stop_reason"][0] if row["status"] == "Parada" else None,
                "História operacional sintética, determinística e auditável.",
                {
                    "Parada": "SIM-STOP-MAN",
                    "Setup": "SIM-SETUP",
                    "Retrabalho": "SIM-REWORK",
                }.get(row["status"]),
                row["rework_qty"], row["lot"],
                row["scrap_reason"][0] if row["scrap"] else None,
                row["scrap_reason"][1] if row["scrap"] else None,
                "Inicial" if row["status"] == "Setup" else None,
            )
            for row in orders
        ],
    )
    return {
        row["op"]: row["id"]
        for row in cursor.execute(
            "SELECT id, op FROM apontamentos_operacionais ORDER BY id"
        ).fetchall()
    }


def _status_code(category: str) -> str:
    return {
        "producao": "SIM-PROD",
        "parada": "SIM-STOP-MAN",
        "setup": "SIM-SETUP",
        "retrabalho": "SIM-REWORK",
        "atividade_sem_op": "SIM-NOOP",
        "fila": "SIM-QUEUE",
        "fora_turno": "SIM-STOP-AUTO",
        "desconhecido": "SIM-UNKNOWN",
    }[category]


def _insert_order_events(cursor, orders: list[dict], appointment_ids: dict[str, int]) -> dict:
    operator_ids = {
        row["cracha"]: row["id"]
        for row in cursor.execute("SELECT id, cracha FROM operadores_apontamento").fetchall()
    }
    quantity_rows = []
    state_rows = []
    operator_event_rows = []
    participation_rows = []
    history_rows = []
    cutoff_count = 0

    for row in orders:
        appointment_id = appointment_ids[row["op"]]
        operator_name = f"Operador Simulação {row['operator_number']:02d}"
        operator_badge = f"S{row['operator_number']:03d}"
        event_time = row["finished"] or SIMULATED_NOW
        if row["good"]:
            quantity_rows.append((
                "boa", row["good"], row["op"], row["operation"], row["product"],
                row["resource"], row["sector"], operator_name, row["lot"], None, None,
                "Peças boas realizadas na simulação histórica.", event_time, SEED_TAG,
                f"sim3m:{row['op']}:boa",
            ))
        if row["scrap"]:
            quantity_rows.append((
                "refugo", row["scrap"], row["op"], row["operation"], row["product"],
                row["resource"], row["sector"], operator_name, row["lot"],
                row["scrap_reason"][0], row["scrap_reason"][1],
                "Refugo separado da quantidade boa.", event_time, SEED_TAG,
                f"sim3m:{row['op']}:refugo",
            ))
        if row["rework_qty"]:
            quantity_rows.append((
                "retrabalho", row["rework_qty"], row["op"], row["operation"], row["product"],
                row["resource"], row["sector"], operator_name, row["lot"],
                "Correção dimensional", "Variação de processo",
                "Retrabalho separado de boas e refugo.", event_time, SEED_TAG,
                f"sim3m:{row['op']}:retrabalho",
            ))

        if row["current"]:
            category = row.get("current_category")
            if category:
                reason, root = row["stop_reason"] if category == "parada" else (None, None)
                state_rows.append((
                    row["resource"], row["sector"], category, _status_code(category), row["op"],
                    row["operation"], row["product"], operator_name, reason, root,
                    "Estado atual em 24/08/2026 08:32.", row["started"], None, SEED_TAG,
                    f"sim3m:{row['op']}:estado-atual", category in {"setup", "fila"}, False,
                    None, appointment_id,
                ))
                operator_event_rows.append((
                    appointment_id, category, reason, "Estado atual da simulação.", 0, 0,
                    operator_name, row["started"], _status_code(category), row["resource"],
                    row["resource"], row["resource"], False, False, False, None,
                ))
            if row["started"]:
                participation_rows.append((
                    operator_ids[operator_badge], operator_badge, operator_name, row["resource"],
                    row["sector"], row["op"], row["operation"], row["started"], None,
                    SEED_TAG, f"sim3m:{row['op']}:participacao-atual",
                ))
            history_rows.append((
                row["op"], row["status"], row["sector"], "Estado atual simulado",
                row["good"], operator_name, SIMULATED_NOW, row["product"],
            ))
            continue

        for category, start_at, end_at in row["schedule"]:
            has_op = category not in {"atividade_sem_op", "fila"}
            reason = None
            root = None
            if category == "parada":
                reason, root = row["stop_reason"]
            elif category == "fila":
                reason = "Sem demanda" if PROFILE_BY_RESOURCE[row["resource"]] == "ocioso" else "Aguardando programação"
            elif category == "setup":
                reason = "Preparação inicial"
            elif category == "atividade_sem_op":
                reason = "Limpeza e inspeção produtiva"
            state_rows.append((
                row["resource"], row["sector"], category, _status_code(category),
                row["op"] if has_op else None, row["operation"] if has_op else None,
                row["product"] if has_op else None, operator_name, reason, root,
                "Composição física da simulação histórica.", start_at, end_at, SEED_TAG,
                f"sim3m:{row['op']}:estado:{category}:{start_at:%H%M%S}",
                category in {"setup", "fila"}, False, None, appointment_id if has_op else None,
            ))
            if has_op:
                operator_event_rows.append((
                    appointment_id, category, reason, "Evento operacional histórico simulado.",
                    0, 0, operator_name, start_at, _status_code(category), row["resource"],
                    row["resource"], row["resource"], False, False, False, None,
                ))

        for break_start, break_end in BREAKS:
            at = datetime.combine(row["started"].date(), break_start)
            end_at = datetime.combine(row["started"].date(), break_end)
            state_rows.append((
                row["resource"], row["sector"], "fora_turno", "SIM-STOP-AUTO", row["op"],
                row["operation"], row["product"], operator_name, "Intervalo programado", None,
                "Parada programada do calendário.", at, end_at, SEED_TAG,
                f"sim3m:{row['op']}:intervalo:{at:%H%M}", True, True, "intervalo", appointment_id,
            ))
            operator_event_rows.append((
                appointment_id, "fora_turno", "Intervalo programado", "Quantidade zero.",
                0, 0, operator_name, at, "SIM-STOP-AUTO", row["resource"], row["resource"],
                row["resource"], False, True, True, "intervalo",
            ))

        for cutoff in (time(17, 30), time(21, 30)):
            at = datetime.combine(row["started"].date(), cutoff)
            state_rows.append((
                row["resource"], row["sector"], "fora_turno", "SIM-STOP-AUTO", row["op"],
                row["operation"], row["product"], operator_name,
                "Interrupção automática de fim de turno", None,
                "Evento de duração zero; OP permanece aberta até retomada manual.",
                at, at, SEED_TAG, f"sim3m:{row['op']}:fim-turno:{at:%H%M}",
                True, True, "fim_turno", appointment_id,
            ))
            operator_event_rows.append((
                appointment_id, "fora_turno", "Interrupção automática de fim de turno",
                "Quantidade zero; retomada posterior é manual.", 0, 0, operator_name, at,
                "SIM-STOP-AUTO", row["resource"], row["resource"], row["resource"],
                False, True, True, "fim_turno",
            ))
            cutoff_count += 1

        operator_event_rows.append((
            appointment_id, "finalizado" if row["status"] == "Finalizado" else "parcial",
            None, "Fechamento da sessão histórica.", row["good"], row["scrap"], operator_name,
            row["finished"], "SIM-PROD", row["resource"], row["resource"], row["resource"],
            False, False, False, None,
        ))
        participation_rows.append((
            operator_ids[operator_badge], operator_badge, operator_name, row["resource"],
            row["sector"], row["op"], row["operation"], row["started"], row["finished"],
            SEED_TAG, f"sim3m:{row['op']}:participacao",
        ))
        history_rows.append((
            row["op"], row["status"], row["sector"], "Simulação histórica",
            row["good"], operator_name, row["finished"], row["product"],
        ))

    cursor.executemany(
        """
        INSERT INTO eventos_quantidade_producao (
            tipo, quantidade, op, numero_operacao, produto_codigo, recurso,
            tipo_setor, operador, lote, motivo, causa_raiz, comentario,
            data_hora, origem, referencia_origem
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        quantity_rows,
    )
    cursor.executemany(
        """
        INSERT INTO eventos_estado_recurso (
            recurso, tipo_setor, categoria, codigo_status_recurso, op,
            numero_operacao, produto_codigo, operador, motivo, causa_raiz,
            comentario, data_inicio, data_fim, origem, referencia_origem,
            planejado, automatico, tipo_interrupcao, apontamento_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s)
        """,
        state_rows,
    )
    cursor.executemany(
        """
        INSERT INTO eventos_apontamento_operador (
            apontamento_id, estado, motivo, comentario, quantidade_boa,
            quantidade_refugo, operador, data_hora, codigo_status_recurso,
            recurso_roteiro_codigo, recurso_roteiro_nome, recurso_apontado,
            recurso_divergente, interrupcao_programada, origem_automatica,
            tipo_interrupcao
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        operator_event_rows,
    )
    cursor.executemany(
        """
        INSERT INTO participacoes_operador (
            operador_id, cracha, nome, recurso, tipo_setor, op,
            numero_operacao, data_inicio, data_fim, origem, referencia_origem
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        participation_rows,
    )
    cursor.executemany(
        """
        INSERT INTO historico (
            op, tipo, setor, motivo, quantidade, operador, data_hora, peca, tarefa_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL)
        """,
        history_rows,
    )
    return {
        "quantity_events": len(quantity_rows),
        "resource_state_events": len(state_rows),
        "operator_events": len(operator_event_rows),
        "participations": len(participation_rows),
        "history_events": len(history_rows),
        "automatic_shift_interruptions": cutoff_count,
    }


def _insert_rateios_and_issues(cursor, orders: list[dict]) -> dict:
    sessions = 0
    allocated_seconds = 0
    physical_seconds = 0
    for month, day in ((6, 18), (7, 16), (8, 12)):
        month_orders = [row for row in orders if (row["started"] or row["planned_start"]).month == month]
        for case in range(4):
            first = month_orders[case * 2]
            second = month_orders[case * 2 + 1]
            start_at = datetime(2026, month, day + case, 22, 0)
            end_at = start_at + timedelta(hours=1)
            session_id = cursor.execute(
                """
                INSERT INTO sessoes_recurso (
                    recurso, tipo_setor, data_inicio, data_fim, segundos_fisicos,
                    origem, referencia_origem
                ) VALUES (%s, %s, %s, %s, 3600, %s, %s) RETURNING id
                """,
                (
                    first["resource"], first["sector"], start_at, end_at, SEED_TAG,
                    f"sim3m:rateio:{month}:{case}",
                ),
            ).fetchone()["id"]
            cursor.executemany(
                """
                INSERT INTO rateios_tempo_op (
                    sessao_recurso_id, op, numero_operacao, estrategia, peso,
                    segundos_atribuidos, criado_em
                ) VALUES (%s, %s, %s, 'igualitario', 0.5, 1800, %s)
                """,
                (
                    (session_id, first["op"], first["operation"], START),
                    (session_id, second["op"], second["operation"], START),
                ),
            )
            sessions += 1
            physical_seconds += 3600
            allocated_seconds += 3600

    issue_templates = (
        ("causa_raiz_ausente", "aviso", "Causa raiz de perda ainda não confirmada", "quantidade"),
        ("estado_conflitante", "critico", "Produção e parada incompatíveis no mesmo recurso", "recurso"),
        ("duracao_zero", "info", "Evento técnico com duração zero", "recurso"),
        ("recurso_divergente", "erro", "Recurso apontado diverge do roteiro", "evento"),
    )
    for index in range(36):
        template = issue_templates[index % len(issue_templates)]
        order = orders[index * 17]
        cursor.execute(
            """
            INSERT INTO inconsistencias_dados (
                tipo, severidade, descricao, entidade, entidade_id, op,
                numero_operacao, recurso, operador, detectada_em, resolvida,
                observacao
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                      'AUDITOR-SIM', %s, FALSE, %s)
            """,
            (
                template[0], template[1], template[2], template[3],
                f"SIM-ISSUE-{index + 1:03d}", order["op"], order["operation"],
                order["resource"], order["started"] or order["planned_start"],
                "Inconsistência deliberada; não corrigir automaticamente.",
            ),
        )

    conflict_seconds = 0
    for month, day in ((6, 23), (7, 21), (8, 18)):
        start_at = datetime(2026, month, day, 11, 0)
        end_at = start_at + timedelta(minutes=15)
        sample = next(row for row in orders if (row["started"] or row["planned_start"]).month == month)
        cursor.execute(
            """
            INSERT INTO eventos_estado_recurso (
                recurso, tipo_setor, categoria, codigo_status_recurso, op,
                numero_operacao, operador, motivo, comentario, data_inicio,
                data_fim, origem, referencia_origem, planejado, automatico
            ) VALUES ('Romi D 1000', 'Usinagem', 'parada', 'SIM-STOP-MAN', %s,
                      %s, 'Operador Simulação 08', 'Leitura conflitante',
                      'Conflito deliberado; não eleger vencedor.', %s, %s,
                      %s, %s, FALSE, FALSE)
            """,
            (sample["op"], sample["operation"], start_at, end_at, SEED_TAG, f"sim3m:conflito:{month}"),
        )
        conflict_seconds += 900

    return {
        "rateio_sessions": sessions,
        "rateio_physical_seconds": physical_seconds,
        "rateio_allocated_seconds": allocated_seconds,
        "issues": 36,
        "conflicting_state_seconds": conflict_seconds,
    }


def _insert_cutting_and_highlight(cursor, orders: list[dict]) -> dict:
    cutting_orders = [row for row in orders if row["sector"] == "Corte" and not row["current"]]
    tasks = cutting_orders[:150]
    plan_count = actual_count = completed_count = highlight_count = 0
    predicted_seconds = actual_seconds = 0
    for task_index, order in enumerate(tasks, start=1):
        task_code = f"T-SIM-{task_index:04d}"
        current_task = task_index > max(0, len(tasks) - 6)
        status = "Destacando" if current_task else "Finalizado"
        task_start = order["started"] + timedelta(minutes=20)
        task_duration = timedelta(minutes=18 + task_index % 55)
        task_end = None if current_task else task_start + task_duration
        task_id = cursor.execute(
            """
            INSERT INTO tarefas (
                codigo_tarefa, material, espessura, status,
                data_inicio_destaque, data_finalizacao, data_despacho, observacoes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """,
            (
                task_code,
                "AÇO INOX 304" if task_index % 3 else "AÇO CARBONO A36",
                1.5 + (task_index % 12), status, task_start, task_end,
                task_end + timedelta(minutes=8) if task_end else None,
                "Histórico de Destaque com parada, retomada e acentuação preservada.",
            ),
        ).fetchone()["id"]
        cursor.execute(
            """
            INSERT INTO op_por_tarefa (
                tarefa_id, codigo_op, id_peca, setor_destino_original,
                setor_destino_atual, quantidade_original, quantidade_atual, editado
            ) VALUES (%s, %s, %s, 'Dobra', 'Dobra', %s, %s, FALSE)
            """,
            (task_id, order["op"], order["product"], order["planned"], order["planned"]),
        )
        cursor.execute(
            """
            INSERT INTO catalogo_sigmanest_tarefas (
                codigo_tarefa, material, espessura, ativo, sincronizado_em
            ) VALUES (%s, %s, %s, TRUE, %s)
            """,
            (task_code, "AÇO INOX 304", 1.5 + task_index % 12, START),
        )
        cursor.execute(
            """
            INSERT INTO catalogo_sigmanest_programas (
                codigo_tarefa, programa, ativo, sincronizado_em
            ) VALUES (%s, %s, TRUE, %s)
            """,
            (task_code, f"PRG-SIM-{task_index:04d}", START),
        )
        cursor.execute(
            """
            INSERT INTO catalogo_sigmanest_ops (
                linha_hash, codigo_tarefa, codigo_op, id_peca, setor_destino,
                quantidade, dobra, usinagem, solda, chanfro, ativo, sincronizado_em
            ) VALUES (%s, %s, %s, %s, 'Dobra', %s, 'Sim', NULL, NULL, NULL, TRUE, %s)
            """,
            (f"sim3m:linha:{task_index:04d}", task_code, order["op"], order["product"], order["planned"], START),
        )

        cursor.execute(
            """
            INSERT INTO eventos_destaque_tarefa (
                tarefa_id, estado, codigo_status_recurso, motivo, comentario,
                operador, data_hora
            ) VALUES (%s, 'inicio', 'SIM-PROD', NULL, 'Início do Destaque.', %s, %s)
            """,
            (task_id, f"Operador Simulação {(task_index % 36) + 1:02d}", task_start),
        )
        highlight_count += 1
        if task_index % 5 == 0:
            cursor.executemany(
                """
                INSERT INTO eventos_destaque_tarefa (
                    tarefa_id, estado, codigo_status_recurso, motivo, comentario,
                    operador, data_hora
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    (task_id, "parada", "SIM-STOP-MAN", "Ajuste de desenho", "Parada controlada.", f"Operador Simulação {(task_index % 36) + 1:02d}", task_start + timedelta(minutes=6)),
                    (task_id, "retomada", "SIM-PROD", None, "Retomada manual.", f"Operador Simulação {(task_index % 36) + 1:02d}", task_start + timedelta(minutes=10)),
                ),
            )
            highlight_count += 2
        if task_end:
            cursor.execute(
                """
                INSERT INTO eventos_destaque_tarefa (
                    tarefa_id, estado, codigo_status_recurso, motivo, comentario,
                    operador, data_hora
                ) VALUES (%s, 'fim', 'SIM-PROD', NULL, 'Destaque finalizado.', %s, %s)
                """,
                (task_id, f"Operador Simulação {(task_index % 36) + 1:02d}", task_end),
            )
            highlight_count += 1

        for nesting in (1, 2):
            plan_hash = f"sim3m:plano:{task_index:04d}:{nesting}"
            machine_sigmanest = "AMADA_ENSIS" if (task_index + nesting) % 2 else "MESSER_XPR_300"
            machine = "Laser Ensis 3015" if machine_sigmanest == "AMADA_ENSIS" else "Plasma TerraBlade 4"
            predicted = 900 + (task_index % 24) * 35 + nesting * 75
            predicted_seconds += predicted
            program_date = order["started"].date()
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
                    plan_hash, task_code, f"PRG-SIM-{task_index:04d}",
                    f"CHAPA {3000 + task_index} × {1500 + nesting}", nesting,
                    1_100_000 + task_index * 1_200 + nesting * 100,
                    round(0.035 + ((task_index + nesting) % 9) / 100, 3),
                    25 + task_index % 70, machine_sigmanest, predicted,
                    f"{predicted // 60} min", program_date, START,
                ),
            )
            plan_count += 1

            actual_start = datetime.combine(program_date, time(7, 0)) + timedelta(minutes=nesting * 50)
            finished = not current_task
            variation = {6: 1.08, 7: 1.01, 8: 0.96}[program_date.month]
            variation += ((task_index % 7) - 3) * 0.018
            duration = max(300, round(predicted * variation))
            actual_end = actual_start + timedelta(seconds=duration) if finished else None
            if task_index in {50, 100} and nesting == 2:
                actual_start = (
                    datetime(2026, 6, 30, 23, 10)
                    if task_index == 50
                    else datetime(2026, 7, 31, 23, 10)
                )
                actual_end = actual_start + timedelta(hours=3)
                duration = 10_800
            cursor.execute(
                """
                INSERT INTO apontamentos_corte (
                    plano_hash, codigo_tarefa, programa, nome_chapa,
                    sequencia_nesting, material, espessura, maquina,
                    maquina_sigmanest, quantidade_processo, tempo_previsto_segundos,
                    data_programa, area_usada, fracao_sucata, status,
                    operador_inicio, data_inicio, operador_fim, data_fim
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    plan_hash, task_code, f"PRG-SIM-{task_index:04d}",
                    f"CHAPA {3000 + task_index} × {1500 + nesting}", nesting,
                    "AÇO INOX 304" if task_index % 3 else "AÇO CARBONO A36",
                    1.5 + task_index % 12, machine, machine_sigmanest,
                    25 + task_index % 70, predicted, program_date,
                    1_100_000 + task_index * 1_200 + nesting * 100,
                    round(0.035 + ((task_index + nesting) % 9) / 100, 3),
                    "Finalizado" if finished else "Em processo",
                    f"Operador Simulação {(task_index % 36) + 1:02d}", actual_start,
                    f"Operador Simulação {((task_index + 1) % 36) + 1:02d}" if finished else None,
                    actual_end,
                ),
            )
            actual_count += 1
            if finished:
                completed_count += 1
                actual_seconds += duration

    return {
        "tasks": len(tasks),
        "plans": plan_count,
        "cut_appointments": actual_count,
        "completed_cuttings": completed_count,
        "highlight_events": highlight_count,
        "predicted_cutting_seconds": predicted_seconds,
        "completed_actual_cutting_seconds": actual_seconds,
    }


def _expected_months(monthly: dict[str, dict]) -> dict[str, dict]:
    result = {}
    for month, raw in monthly.items():
        values = dict(raw)
        available = values.get("seconds:available", 0)
        worked = values.get("seconds:worked", 0)
        production = values.get("seconds:production", 0)
        operational = max(0, available - values.get("seconds:queue", 0))
        total_quality = values.get("good", 0) + values.get("scrap", 0) + values.get("rework", 0)
        ftt = values.get("good", 0) / total_quality if total_quality else 0.0
        supporting_productive = (
            values.get("seconds:setup", 0)
            + values.get("seconds:rework", 0)
            + values.get("seconds:no_op", 0)
        )
        net = values.get("seconds:standard_run", 0) + supporting_productive
        availability = worked / available if available else 0.0
        performance = net / worked if worked else 0.0
        result[month] = {
            **values,
            "kpis": {
                "availability": availability * 100.0,
                "performance": performance * 100.0,
                "ftt": ftt * 100.0,
                "oee": availability * performance * ftt * 100.0,
                "utilization": worked / operational * 100.0 if operational else 0.0,
                "productivity": production / operational * 100.0 if operational else 0.0,
                "ae": net / available * 100.0 if available else 0.0,
            },
        }
    return result


def seed() -> dict:
    user_source_test_dsn, common_test_dsn, target_dsn, maintenance_dsn, safe = _safe_dsns()
    created = isolation._ensure_target_database(maintenance_dsn)
    os.environ["TEST_DATABASE_URL"] = target_dsn
    os.environ["GESTOR_EXPECTED_DATABASE"] = TARGET_DATABASE
    config = PostgresConfig(dsn=target_dsn, min_pool_size=1, max_pool_size=8, pool_timeout=15)
    db = Database(config=config)
    try:
        orders, monthly_raw = _build_orders()
        with db.connection() as connection:
            isolation._truncate_dedicated_target(connection)
            with connection.cursor() as cursor:
                users_copied = isolation._copy_test_users(user_source_test_dsn, cursor)
                _insert_configuration(cursor)
                operation_ids = _insert_order_catalogs(cursor, orders)
                appointment_ids = _insert_appointments(cursor, orders, operation_ids)
                event_totals = _insert_order_events(cursor, orders, appointment_ids)
                edge_totals = _insert_rateios_and_issues(cursor, orders)
                cutting_totals = _insert_cutting_and_highlight(cursor, orders)
                expected = {
                    "dataset": SEED_TAG,
                    "random_seed": RANDOM_SEED,
                    "period": {"start": START.isoformat(), "end": SIMULATED_NOW.isoformat()},
                    "schema_version": SCHEMA_VERSION,
                    "users_copied": users_copied,
                    "counts": {
                        "orders": len(orders),
                        "operations": len(orders),
                        "appointments": len(orders),
                        "operator_badges": 36,
                        **event_totals,
                        **cutting_totals,
                        "resource_state_events": event_totals["resource_state_events"] + 3,
                        "data_issues": edge_totals["issues"],
                    },
                    "months": _expected_months(monthly_raw),
                    "edge_cases": edge_totals,
                    "current": {
                        "reference_time": SIMULATED_NOW.isoformat(),
                        "active_resources": sum(bool(row.get("current_category")) for row in orders if row["current"]),
                        "queued_or_free_resources": sum(not bool(row.get("current_category")) for row in orders if row["current"]),
                    },
                    "rules": {
                        "simulation_only": True,
                        "good_only_completes_order": True,
                        "setup_is_productive": True,
                        "official_cutoffs": ["17:30:00", "21:30:00"],
                        "no_future_data": True,
                        "rateio_conserves_physical_time": True,
                    },
                }
                cursor.execute(
                    """
                    INSERT INTO eventos_sistema (
                        tipo, origem, referencia, mensagem, operador, detalhes, data_hora
                    ) VALUES ('simulacao_historica_seed', %s, %s,
                              'História operacional de três meses aplicada.', 'SEED-SIM', %s, %s)
                    """,
                    (
                        "tests/simulacao_historica_3_meses/seed_simulacao_historica.py",
                        SEED_TAG,
                        json.dumps({"users_copied": users_copied, "expected": expected}, ensure_ascii=False),
                        SIMULATED_NOW,
                    ),
                )
        EXPECTED_PATH.write_text(
            json.dumps(expected, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        result = {
            "created": created,
            **safe,
            "expected_path": str(EXPECTED_PATH),
            "expected": expected,
        }
        RESULT_PATH.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return result
    finally:
        db.close()


if __name__ == "__main__":
    print(json.dumps(seed(), ensure_ascii=False, indent=2))
