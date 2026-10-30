"""Fábrica DEMO contínua que alimenta os fatos canônicos do Andon.

O módulo é deliberadamente restrito ao banco dedicado da demonstração. Ele
não chama HTTP, TOTVS, SigmaNEST, Telegram, OT nem qualquer outro transporte
externo. Os indicadores continuam sendo calculados por ``ManagementService``.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import os
import random
import time

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from app.core.resource_mapping import resolve_resource_identity
from app.database.config import PostgresConfig
from app.database.database import Database
from mes.domain import EventCategory
from mes.integrations.totvs.outbound_enqueue import OutboundEnqueueConfig
from mes.services.andon import ANDON_PANEL_BY_SECTOR
from mes.services.resource_state import ResourceStateService


LOGGER = logging.getLogger(__name__)
DEMO_DATABASE = "gestor_pecas_test_andon_demo"
# OPs sintéticas imitam o formato real (11 dígitos); o prefixo "99" não existe na
# série do Protheus e só é varrido no banco dedicado (guardas por dbname abaixo).
DEMO_OP_PREFIX = "99"
LEGACY_DEMO_OP_PREFIX = "DEMO-ANDON-"
DEMO_ORIGIN = "andon_demo"
DEMO_CUT_PREFIX = "demo-corte-"
MIN_VISIBLE_RESOURCES = 8
DEFAULT_VISIBLE_RESOURCES = 16
DEMO_INSTANCE_LOCK_NAME = "gestor_pecas:andon_demo:writer"
CYCLE_MINUTES = (20, 95)
PROFILE_MINUTES = (8, 22)
QUANTITY_TICK_SECONDS = (45, 150)
STOP_MINUTES_BY_PROFILE = {
    "NORMAL": (3, 12),
    "PICO": (3, 8),
    "BAIXA": (6, 18),
    "PERTURBACAO": (20, 45),
}

# Códigos e descrições no formato do catálogo real (nomes curtos e longos de propósito).
PRODUCTS_PARTS = (
    ("PPCX03001035", "CHAPA TRAVA MAIOR (9,5MM)"),
    ("PPCX04002359", "LATERAL INTERNA DIR."),
    ("PPCX03001052", "BASE INFERIOR CHASS  (9,5MM)"),
    ("PPCX05001072", "FLANGE TUBO SUPERIOR CHASSI"),
    ("IPM004001046", "PERFIL SUPERIOR LATERAL DIREITO  (4,5MM)"),
    ("IPM004001054", "REFORCO LATERAL CHASSI 4,5MM"),
    ("IPM011022108", "DOBRADICA INFERIOR 60"),
    ("IPM017001135", "REGUA CHAPA DE FECHAMENTO 1147"),
    ("PPM005001101", "MAO FRANCESA ESQUERDA PRODUTTIVA SS 16"),
    ("PPCX03001011", "BUCHA CHASSI"),
    ("PNT002003016", "TAMPA FRONTAL"),
    ("PPL001000020", "SUPORTE DO MOTOR"),
)
PRODUCTS_WELDED = (
    ("SPCX04001008", "CONJ.SOLD. CHASSI 40/41 PES RXS/FXS"),
    ("SPCX04001007", "CONJ.SOLD. CHASSI 45/46 PES RXS/FXS"),
    ("SPCX04014015", "CONJUNTO SOLDADO LATERAL INTERNA FX DIR."),
    ("SPMX20435001", "CONJUNTO SOLDADO TAMPA DO BANHO A OLEO"),
    ("SDT009001005", "CONJUNTO SOLDADO SUPORTE PE APOIO"),
    ("SSDC01000251", "SUB CONJUNTO SOLDADO REBOQUE DIREITO"),
    ("SSM014007071", "CONJUNTO SOLDADO SUPORTE DA RODA"),
    ("7000007289", "GIRADOR SOLD ARTICULADOR PLAINA 510"),
)
PRODUCT_DESCRIPTIONS = dict(PRODUCTS_PARTS + PRODUCTS_WELDED)
OPERATION_NAMES = (
    ("corte", "CORTE"), ("dobra", "DOBRA"), ("solda", "SOLDAGEM"), ("pintura", "PINTURA"),
    ("usinagem", "USINAGEM"), ("caldeiraria", "CALDEIRARIA"),
)

# Episódios que interrompem a produção. `planejado` só vale para "parada".
# Cada tipo aparece no mostrador com cor e rótulo próprios.
STOP_EPISODES = (
    ("parada", "Falta de material", False),
    ("parada", "Quebra de ferramenta", False),
    ("parada", "Manutenção corretiva", False),
    ("parada", "Aguardando inspeção da qualidade", False),
    ("parada", "Falta de operador", False),
    ("parada", "Manutenção preventiva", True),
    ("parada", "Diálogo diário de segurança", True),
    ("parada", "Limpeza e 5S", True),
    ("setup", "Troca de ferramental", None),
    ("setup", "Preparação de máquina", None),
    ("setup", "Ajuste de programa", None),
    ("retrabalho", "Correção dimensional", None),
    ("retrabalho", "Remoção de rebarba", None),
    ("fila", "Aguardando liberação da OP", None),
    ("sem_demanda", "Aguardando programação", None),
)
# Ordem de apresentação no warm start: garante uma amostra de cada estado na tela.
WARM_SCRIPT = (
    "producao", "parada_nao_prog", "producao", "setup", "producao", "sem_demanda",
    "retrabalho", "producao", "parada_plan", "producao", "fila", "producao",
)

LOAD_PROFILES = {
    "NORMAL": {"pace": (0.82, 0.98), "stop_chance": 0.10, "scrap": 0.025},
    "PICO": {"pace": (0.94, 1.08), "stop_chance": 0.05, "scrap": 0.015},
    "BAIXA": {"pace": (0.62, 0.82), "stop_chance": 0.13, "scrap": 0.035},
    "PERTURBACAO": {"pace": (0.48, 0.74), "stop_chance": 0.34, "scrap": 0.060},
}


def demo_dsns(environ=None) -> tuple[str, str, str]:
    """Retorna ``(fonte_teste, demo, manutencao)`` sem expor credenciais."""

    env = environ if environ is not None else os.environ
    source = str(env.get("TEST_DATABASE_URL") or "").strip()
    if not source:
        raise RuntimeError("TEST_DATABASE_URL não configurada; preparo DEMO recusado.")
    parsed = conninfo_to_dict(source)
    source_name = str(parsed.get("dbname") or "").strip().casefold()
    if "test" not in source_name or source_name == "gestor_pecas":
        raise RuntimeError("Fonte recusada: a DEMO exige um banco TESTE explícito.")
    demo = make_conninfo(source, dbname=DEMO_DATABASE, application_name="gestor_andon_demo")
    maintenance = make_conninfo(source, dbname="postgres", application_name="gestor_andon_demo_prepare")
    return source, demo, maintenance


def _database_name(dsn: str) -> str:
    return str(conninfo_to_dict(dsn).get("dbname") or "").strip()


def validate_demo_dsn(dsn: str) -> None:
    """Prova o alvo antes de qualquer migração ou escrita."""

    if _database_name(dsn).casefold() != DEMO_DATABASE.casefold():
        raise RuntimeError("Alvo recusado: somente o banco dedicado do Andon DEMO é aceito.")
    with psycopg.connect(dsn, autocommit=True) as connection:
        actual = connection.execute("SELECT current_database()").fetchone()[0]
    if str(actual).casefold() != DEMO_DATABASE.casefold():
        raise RuntimeError(f"Alvo efetivo inesperado: {actual!r}.")


def ensure_demo_database() -> tuple[str, str]:
    """Cria o banco dedicado se necessário e aplica as migrations atuais."""

    source_dsn, demo_dsn, maintenance_dsn = demo_dsns()
    with psycopg.connect(maintenance_dsn, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (DEMO_DATABASE,)
        ).fetchone()
        if not exists:
            if os.getenv("GESTOR_PERMITIR_BANCO_EXTRA") != "1":
                raise RuntimeError(
                    "Regra do notebook: um único banco (gestor_pecas_test). Criar outro banco "
                    "exige GESTOR_PERMITIR_BANCO_EXTRA=1 e aprovação do usuário."
                )
            connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DEMO_DATABASE)))
    validate_demo_dsn(demo_dsn)
    database = Database(
        config=PostgresConfig(demo_dsn, min_pool_size=1, max_pool_size=4),
        totvs_outbox_config=OutboundEnqueueConfig(enabled=False),
    )
    database.close()
    return source_dsn, demo_dsn


def _copy_rows(source, target, table: str, *, where: str = "TRUE", params=()) -> int:
    """Copia um cadastro entre bancos com a interseção real de colunas."""

    source_cols = {
        row["column_name"]
        for row in source.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s",
            (table,),
        ).fetchall()
    }
    target_cols = [
        row["column_name"]
        for row in target.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
            (table,),
        ).fetchall()
        if row["column_name"] in source_cols
    ]
    if not target_cols:
        return 0
    query = sql.SQL("SELECT {} FROM {} WHERE " + where).format(
        sql.SQL(", ").join(map(sql.Identifier, target_cols)), sql.Identifier(table)
    )
    rows = source.execute(query, params).fetchall()
    if not rows:
        return 0
    placeholders = sql.SQL(", ").join(sql.Placeholder() for _ in target_cols)
    updates = sql.SQL(", ").join(
        sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(column), sql.Identifier(column))
        for column in target_cols
        if column != target_cols[0]
    )
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {}").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, target_cols)),
        placeholders,
        sql.Identifier(target_cols[0]),
        updates,
    )
    with target.cursor() as cursor:
        cursor.executemany(statement, [tuple(row[column] for column in target_cols) for row in rows])
    return len(rows)


def seed_demo_catalogs(source_dsn: str, demo_dsn: str) -> dict:
    """Copia somente cadastros necessários; nenhum fato operacional é copiado."""

    validate_demo_dsn(demo_dsn)
    compatible = tuple(sorted(ANDON_PANEL_BY_SECTOR))
    with (
        psycopg.connect(
            make_conninfo(source_dsn, options="-c default_transaction_read_only=on"),
            row_factory=dict_row,
        ) as source,
        psycopg.connect(demo_dsn, row_factory=dict_row) as target,
    ):
        statuses = _copy_rows(source, target, "catalogo_status_recursos")
        users = _copy_rows(
            source,
            target,
            "usuarios",
            where="ativo IS TRUE AND LOWER(nome) IN ('andon', 'iagodev')",
        )
        resource_rows = source.execute(
            "SELECT * FROM catalogo_recursos_pcfactory WHERE habilitado IS TRUE"
        ).fetchall()
        selected_rows = [
            row for row in resource_rows
            if str(row.get("tipo_setor") or "").strip().casefold() in compatible
        ]
        if not selected_rows:
            raise RuntimeError("Nenhum recurso habilitado compatível com o Andon foi encontrado.")
        columns = list(selected_rows[0])
        statement = sql.SQL(
            "INSERT INTO catalogo_recursos_pcfactory ({}) VALUES ({}) "
            "ON CONFLICT (codigo) DO UPDATE SET {}"
        ).format(
            sql.SQL(", ").join(map(sql.Identifier, columns)),
            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
            sql.SQL(", ").join(
                sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(c), sql.Identifier(c))
                for c in columns if c != "codigo"
            ),
        )
        with target.cursor() as cursor:
            cursor.executemany(statement, [tuple(row[c] for c in columns) for row in selected_rows])
        target.execute(
            "INSERT INTO calendarios_produtivos (codigo, nome, ativo) "
            "VALUES ('DEMO_24X7', 'Andon DEMO 24x7', TRUE) "
            "ON CONFLICT (codigo) DO UPDATE SET nome=EXCLUDED.nome, ativo=TRUE"
        )
        for day in range(7):
            target.execute(
                "INSERT INTO turnos_produtivos "
                "(calendario_codigo,nome,dia_semana,hora_inicio,hora_fim,cruza_meia_noite,minutos_intervalo,ativo) "
                "VALUES ('DEMO_24X7','Demonstração',%s,'00:00','23:59:59',FALSE,0,TRUE) "
                "ON CONFLICT (calendario_codigo,nome,dia_semana,hora_inicio) DO UPDATE SET ativo=TRUE",
                (day,),
            )
        target.execute(
            "UPDATE catalogo_recursos_pcfactory SET calendario_codigo='DEMO_24X7'"
        )
    return {"statuses": statuses, "users": users, "resources": len(selected_rows)}


@dataclass
class ResourceRuntime:
    code: str
    name: str
    sector: str
    state: str
    appointment_id: int | None
    op: str | None
    operation: str | None
    product: str | None
    cycle_started: datetime
    cycle_ends: datetime
    next_quantity_at: datetime
    resume_at: datetime | None = None
    sequence: int = 0


class AndonDemo:
    """Mantém linhas temporais independentes até Ctrl+C."""

    def __init__(self, database: Database, *, seed: int | None = None, resource_count=DEFAULT_VISIBLE_RESOURCES):
        if str((database.safe_target or {}).get("dbname") or "").casefold() != DEMO_DATABASE.casefold():
            raise RuntimeError("AndonDemo recusou Database fora do alvo dedicado.")
        self.db = database
        self.rng = random.Random(seed)
        self.seed = seed
        self.resource_count = max(MIN_VISIBLE_RESOURCES, int(resource_count))
        self.profile = "NORMAL"
        self.next_profile_at = datetime.now()
        self.resources: list[ResourceRuntime] = []
        self._day = datetime.now().date()
        self._cut_sequence = 0
        self._slots: dict[str, int] = {}

    def discover_resources(self) -> tuple[list[dict], list[str]]:
        # O inventário do scheduler é a fonte canônica de recursos físicos:
        # exclui códigos apenas sincronizados (ex.: ALMOXS) e inclui postos de
        # Solda aprovados que ainda não possuem linha no catálogo corporativo.
        loader = getattr(self.db, "listar_recursos_ativos_scheduler", None)
        if not callable(loader):
            loader = self.db.listar_recursos_pcfactory
        rows = [dict(row) for row in loader()]
        by_sector = defaultdict(list)
        for row in rows:
            sector = str(row.get("tipo_setor") or "").strip()
            if sector.casefold() not in ANDON_PANEL_BY_SECTOR:
                continue
            identity = resolve_resource_identity(row.get("codigo") or row.get("nome"))
            row["identity"] = identity or row.get("codigo")
            by_sector[sector].append(row)
        selected, identities = [], set()
        for sector in sorted(by_sector, key=str.casefold):
            candidates = sorted(by_sector[sector], key=lambda item: str(item.get("codigo") or "").casefold())
            for row in candidates:
                identity = str(row["identity"]).casefold()
                if identity not in identities:
                    selected.append(row); identities.add(identity); break
        remaining = sorted(
            (row for bucket in by_sector.values() for row in bucket),
            key=lambda item: (str(item.get("tipo_setor") or "").casefold(), str(item.get("codigo") or "").casefold()),
        )
        for row in remaining:
            if len(selected) >= self.resource_count:
                break
            identity = str(row["identity"]).casefold()
            if identity not in identities:
                selected.append(row); identities.add(identity)
        missing = [
            sector for sector in sorted({value.title() for value in ANDON_PANEL_BY_SECTOR})
            if sector.casefold() not in {key.casefold() for key in by_sector}
        ]
        if len(selected) < MIN_VISIBLE_RESOURCES:
            raise RuntimeError(
                f"Catálogo oferece apenas {len(selected)} identidades compatíveis; mínimo é {MIN_VISIBLE_RESOURCES}."
            )
        return selected, missing

    def _cycle_minutes(self) -> int:
        return self.rng.randint(*CYCLE_MINUTES)

    def _stop_minutes(self) -> int:
        return self.rng.randint(*STOP_MINUTES_BY_PROFILE[self.profile])

    def prepare(self) -> dict:
        now = datetime.now().replace(microsecond=0)
        selected, missing = self.discover_resources()
        self.resources.clear()
        self._clear_previous_demo_facts()
        history_start = max(now.replace(hour=0, minute=0, second=0), now - timedelta(hours=4))
        for index, row in enumerate(selected):
            self._warm_resource(row, index=index, history_start=history_start, now=now)
        return {
            "seed": self.seed,
            "resource_count": len(self.resources),
            "sectors": sorted({item.sector for item in self.resources}, key=str.casefold),
            "resources": [item.code for item in self.resources],
            "compatible_sectors_without_resources": missing,
            "profile": self.profile,
        }

    def _clear_previous_demo_facts(self) -> None:
        if str((self.db.safe_target or {}).get("dbname") or "").casefold() != DEMO_DATABASE.casefold():
            raise RuntimeError("Limpeza DEMO recusada fora do banco dedicado.")
        with self.db.connection() as connection, connection.cursor() as cursor:
            # O scheduler pode ter materializado estados SYSTEM no banco vazio
            # antes do warm start. Neste banco exclusivamente sintético eles
            # também pertencem ao cenário anterior e bloqueariam a cronologia
            # retroativa do motor de estado.
            cursor.execute("DELETE FROM eventos_estado_recurso")
            cursor.execute("DELETE FROM eventos_quantidade_producao")
            cursor.execute("DELETE FROM apontamentos_corte WHERE plano_hash LIKE %s", (DEMO_CUT_PREFIX + "%",))
            cursor.execute("DELETE FROM catalogo_sigmanest_planos_corte WHERE plano_hash LIKE %s", (DEMO_CUT_PREFIX + "%",))
            for prefix in (DEMO_OP_PREFIX, LEGACY_DEMO_OP_PREFIX):
                cursor.execute("DELETE FROM apontamentos_operacionais WHERE op LIKE %s", (prefix + "%",))
                cursor.execute("DELETE FROM catalogo_operacoes_op WHERE codigo_op LIKE %s", (prefix + "%",))
                cursor.execute("DELETE FROM catalogo_pcp_ops WHERE codigo_op LIKE %s", (prefix + "%",))

    @contextmanager
    def instance_lock(self):
        """Mantém uma única instância escritora durante preparo e execução."""

        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_lock(hashtext(%s)) AS acquired",
                (DEMO_INSTANCE_LOCK_NAME,),
            )
            acquired = bool(cursor.fetchone()["acquired"])
            connection.commit()
            if not acquired:
                raise RuntimeError("Outra instância do Andon DEMO já está ativa neste banco.")
            try:
                yield
            finally:
                cursor.execute(
                    "SELECT pg_advisory_unlock(hashtext(%s))",
                    (DEMO_INSTANCE_LOCK_NAME,),
                )
                connection.commit()

    def _warm_resource(self, row: dict, *, index: int, history_start: datetime, now: datetime) -> None:
        code = str(row.get("identity") or row.get("codigo"))
        name = str(row.get("nome") or code)
        sector = str(row.get("tipo_setor") or "")
        elapsed = self.rng.randint(4, 50)
        total = self.rng.randint(max(20, elapsed + 2), 90)
        started = now - timedelta(minutes=elapsed)
        current = history_start + timedelta(seconds=index * 37)
        sequence = 0
        # Corte não recebe OP fictícia: sem nesting SigmaNEST real, a fonte
        # canônica é atividade sem OP e os KPIs sem base permanecem indisponíveis.
        if sector.casefold() == "corte":
            activity_start = max(history_start, now - timedelta(minutes=20 + index))
            self._activity_without_op(code, sector, activity_start)
            self._start_cut(name, activity_start)
            self.resources.append(ResourceRuntime(
                code, name, sector, "atividade_sem_op", None, None, None, None,
                activity_start, activity_start + timedelta(minutes=self._cycle_minutes()),
                now + timedelta(minutes=5), sequence=sequence,
            ))
            return
        while current + timedelta(minutes=20) <= started:
            duration = timedelta(minutes=self.rng.randint(20, 55))
            finish = min(started, current + duration)
            if finish - current < timedelta(minutes=20):
                break
            sequence += 1
            self._create_completed_cycle(code, sector, current, finish, sequence)
            current = finish + timedelta(minutes=self.rng.randint(1, 4))
        sequence += 1
        appointment_id, op, operation, product = self._create_active_cycle(
            code, sector, started, sequence, total
        )
        self._state(code, sector, "producao", started, op, operation, product)
        item = ResourceRuntime(
            code, name, sector, "producao", appointment_id, op, operation, product,
            started, started + timedelta(minutes=total),
            now + timedelta(seconds=self.rng.randint(*QUANTITY_TICK_SECONDS)), None, sequence,
        )
        scripted = WARM_SCRIPT[index % len(WARM_SCRIPT)]
        if scripted != "producao":
            self._begin_episode(item, now - timedelta(minutes=min(elapsed, 7)), scripted, resume_minutes=(6, 20))
        self.resources.append(item)

    def _begin_episode(self, item, moment, kind=None, *, resume_minutes=None):
        """Interrompe a produção com um episódio (parada, setup, retrabalho, fila...)."""

        if kind is None:
            episode = self.rng.choice(STOP_EPISODES)
        else:
            wanted = {
                "parada_nao_prog": ("parada", False), "parada_plan": ("parada", True),
            }.get(kind, (kind, None))
            pool = [e for e in STOP_EPISODES if e[0] == wanted[0] and (wanted[1] is None or e[2] == wanted[1])]
            episode = self.rng.choice(pool)
        category, motivo, planejado = episode
        without_op = category == "sem_demanda"
        item.state = category
        low, high = resume_minutes or STOP_MINUTES_BY_PROFILE[self.profile]
        item.resume_at = moment + timedelta(minutes=self.rng.randint(low, high))
        self._state(
            item.code, item.sector, "fila" if without_op else category, moment,
            None if without_op else item.op, None if without_op else item.operation,
            None if without_op else item.product, motivo=motivo, planejado=planejado,
        )

    def _cycle_identity(self, resource: str, sequence: int, sector: str = "") -> tuple[str, str, str]:
        slot = self._slots.setdefault(resource, len(self._slots) + 1)
        welded = any(key in sector.casefold() for key in ("solda", "pintura"))
        products = PRODUCTS_WELDED if welded else PRODUCTS_PARTS
        product = products[(slot * 5 + sequence) % len(products)][0]
        # 99 + nº do recurso (3) + ciclo (3) + item (3): 11 dígitos como as OPs reais.
        return (
            f"{DEMO_OP_PREFIX}{slot % 1000:03d}{sequence % 1000:03d}001",
            f"{sequence % 90 + 10:03d}",
            product,
        )

    @staticmethod
    def _operation_name(sector: str) -> str:
        lowered = sector.casefold()
        return next((name for key, name in OPERATION_NAMES if key in lowered), lowered.upper() or "OPERAÇÃO")

    def _insert_catalog_operation(
        self, connection, resource, sector, sequence, ideal_seconds, planned_quantity
    ):
        op, operation, product = self._cycle_identity(resource, sequence, sector)
        description = PRODUCT_DESCRIPTIONS[product]
        moment = datetime.now().replace(microsecond=0)
        connection.execute(
            "INSERT INTO catalogo_pcp_ops "
            "(codigo_op,produto_codigo,produto_descricao,quantidade,unidade,"
            "data_emissao,status_pcp,ativo,sincronizado_em) "
            "VALUES (%s,%s,%s,%s,'UN',%s,'DEMO',TRUE,%s) "
            "ON CONFLICT (codigo_op) DO UPDATE SET quantidade=EXCLUDED.quantidade",
            (
                op, product, description, planned_quantity,
                moment.date(), moment,
            ),
        )
        row = connection.execute(
            "INSERT INTO catalogo_operacoes_op "
            "(codigo_op,produto_codigo,produto_descricao,numero_operacao,codigo_recurso,descricao_operacao,"
            "tipo_setor,tempo_medio_segundos,ordem,fonte,ativo,sincronizado_em) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,%s,TRUE,%s) "
            "ON CONFLICT (codigo_op,numero_operacao,codigo_recurso) "
            "WHERE totvs_activity_id IS NULL DO UPDATE SET "
            "tempo_medio_segundos=EXCLUDED.tempo_medio_segundos RETURNING id",
            (op, product, description, operation, resource,
             self._operation_name(sector), sector, ideal_seconds, DEMO_ORIGIN, moment),
        ).fetchone()
        return op, operation, product, row["id"]

    def _create_completed_cycle(self, resource, sector, start, finish, sequence):
        ideal_seconds = self.rng.uniform(28.0, 65.0)
        stop_seconds = 0
        stop_start = stop_end = None
        if self.rng.random() < 0.35:
            stop_seconds = self.rng.randint(3, min(18, max(3, int((finish - start).total_seconds() // 180)))) * 60
            stop_start = start + (finish - start) * 0.45
            stop_end = min(finish, stop_start + timedelta(seconds=stop_seconds))
            stop_seconds = max(0, int((stop_end - stop_start).total_seconds()))
        productive_seconds = max(1, int((finish - start).total_seconds()) - stop_seconds)
        pace = self.rng.uniform(0.68, 1.02)
        good = max(1, int(productive_seconds * pace / ideal_seconds))
        scrap = 1 if self.rng.random() < 0.28 else 0
        planned_quantity = good + scrap
        finished = good >= planned_quantity
        with self.db.connection() as connection:
            op, operation, product, catalog_id = self._insert_catalog_operation(
                connection, resource, sector, sequence, ideal_seconds, planned_quantity
            )
            row = connection.execute(
                "INSERT INTO apontamentos_operacionais "
                "(op,peca,tipo_setor,maquina,status,quantidade,operador_fila,data_entrada,"
                "operador_inicio,data_inicio,operador_fim,data_fim,setor_destino,catalogo_operacao_id,"
                "numero_operacao,codigo_recurso,descricao_operacao,produto_codigo,produto_descricao,"
                "quantidade_boa,quantidade_refugo,quantidade_retrabalho) "
                "VALUES (%s,%s,%s,%s,%s,%s,'DEMO',%s,'DEMO',%s,%s,%s,'DEMO',%s,"
                "%s,%s,%s,%s,%s,%s,%s,0) RETURNING id",
                (
                    op, product, sector, resource,
                    "Finalizado" if finished else "Aguardando", planned_quantity,
                    start, start, "DEMO" if finished else None, finish, catalog_id, operation,
                    resource, self._operation_name(sector), product,
                    PRODUCT_DESCRIPTIONS[product], good, scrap,
                ),
            ).fetchone()
            appointment_id = row["id"]
            connection.execute(
                "INSERT INTO eventos_apontamento_operador "
                "(apontamento_id,estado,operador,data_hora,quantidade_boa,quantidade_refugo) "
                "VALUES (%s,'producao','DEMO',%s,0,0),(%s,%s,'DEMO',%s,%s,%s)",
                (
                    appointment_id, start, appointment_id,
                    "finalizado" if finished else "parcial", finish, good, scrap,
                ),
            )
            self.db.registrar_evento_quantidade(
                "boa", good, op, numero_operacao=operation, produto_codigo=product,
                recurso=resource, tipo_setor=sector, operador="DEMO", data_hora=finish,
                origem=DEMO_ORIGIN, referencia_origem=f"{op}:boa", connection=connection,
            )
            if scrap:
                self.db.registrar_evento_quantidade(
                    "refugo", scrap, op, numero_operacao=operation, produto_codigo=product,
                    recurso=resource, tipo_setor=sector, operador="DEMO", data_hora=finish,
                    origem=DEMO_ORIGIN, referencia_origem=f"{op}:refugo", connection=connection,
                )
        self._state(resource, sector, "producao", start, op, operation, product)
        if stop_start is not None and stop_end is not None:
            self._state(resource, sector, "parada", stop_start, op, operation, product)
            self._state(resource, sector, "producao", stop_end, op, operation, product)

    def _create_active_cycle(self, resource, sector, start, sequence, cycle_minutes):
        ideal_seconds = self.rng.uniform(28.0, 65.0)
        target_pace = self.rng.uniform(0.78, 0.96)
        planned_quantity = max(1, int(cycle_minutes * 60 * target_pace / ideal_seconds))
        with self.db.connection() as connection:
            op, operation, product, catalog_id = self._insert_catalog_operation(
                connection, resource, sector, sequence, ideal_seconds, planned_quantity
            )
            row = connection.execute(
                "INSERT INTO apontamentos_operacionais "
                "(op,peca,tipo_setor,maquina,status,quantidade,operador_fila,data_entrada,"
                "operador_inicio,data_inicio,catalogo_operacao_id,numero_operacao,codigo_recurso,"
                "descricao_operacao,produto_codigo,produto_descricao,quantidade_boa,"
                "quantidade_refugo,quantidade_retrabalho) "
                "VALUES (%s,%s,%s,%s,'Em processo',%s,'DEMO',%s,'DEMO',%s,%s,%s,%s,%s,%s,%s,0,0,0) RETURNING id",
                (
                    op, product, sector, resource, planned_quantity, start, start,
                    catalog_id, operation, resource, self._operation_name(sector),
                    product, PRODUCT_DESCRIPTIONS[product],
                ),
            ).fetchone()
            connection.execute(
                "INSERT INTO eventos_apontamento_operador "
                "(apontamento_id,estado,operador,data_hora,quantidade_boa,quantidade_refugo) "
                "VALUES (%s,'producao','DEMO',%s,0,0)", (row["id"], start),
            )
        return row["id"], op, operation, product

    def _state(self, resource, sector, state, moment, op, operation, product, *, motivo=None, planejado=None):
        service = ResourceStateService(self.db, "DEMO")
        if state == "parada":
            result = service.registrar_estado(
                resource, EventCategory.DOWNTIME.value, tipo_setor=sector,
                op=op, numero_operacao=operation, produto_codigo=product,
                motivo=motivo or "Falta de material",
                planejado=False if planejado is None else planejado,
                comentario="Fato sintético isolado no ambiente DEMO", data_hora=moment,
            )
        elif state in ("setup", "retrabalho", "fila"):
            result = service.registrar_estado(
                resource, EventCategory(state).value, tipo_setor=sector,
                op=op, numero_operacao=operation, produto_codigo=product,
                motivo=motivo or "Preparação de máquina", data_hora=moment,
            )
        else:
            result = service.registrar_estado(
                resource, EventCategory.PRODUCTION.value, tipo_setor=sector,
                op=op, numero_operacao=operation, produto_codigo=product,
                data_hora=moment,
            )
        # A origem permite limpeza idempotente sem tocar nenhum fato alheio.
        self._mark_state_origin(result)

    def _activity_without_op(self, resource, sector, moment):
        result = ResourceStateService(self.db, "DEMO").registrar_atividade_sem_op(
            resource,
            tipo_setor=sector,
            tipo_atividade="atividade_produtiva_demo",
            motivo="Atividade produtiva de demonstração sem nesting",
            data_hora=moment,
        )
        self._mark_state_origin(result)

    def _start_cut(self, machine: str, moment: datetime) -> None:
        """Corte em processo: tarefa, plano (programa) e nesting vêm de apontamentos_corte."""

        self._end_cut(machine, moment)
        self._cut_sequence += 1
        number = self._cut_sequence
        plan_hash = f"{DEMO_CUT_PREFIX}{number}"
        task = str(8400 + number)
        program = f"{self.rng.randint(1, 9)}0{number % 10}{self.rng.randint(10, 99)}"
        nesting = self.rng.randint(1, 4)
        sheet = self.rng.choice(("CH-3.00", "CH-4.75", "CH-6.35", "CH-8.00"))
        with self.db.connection() as connection:
            connection.execute(
                """
                INSERT INTO catalogo_sigmanest_planos_corte
                    (plano_hash, codigo_tarefa, programa, nome_chapa, sequencia_nesting,
                     quantidade_processo, maquina_sigmanest, sigmanest_repeat_id, sincronizado_em)
                VALUES (%s, %s, %s, %s, %s, 1, %s, %s, %s)
                """,
                (plan_hash, task, program, sheet, nesting, machine, nesting, moment),
            )
            connection.execute(
                """
                INSERT INTO apontamentos_corte
                    (plano_hash, codigo_tarefa, programa, nome_chapa, sequencia_nesting,
                     maquina, status, operador_inicio, data_inicio)
                VALUES (%s, %s, %s, %s, %s, %s, 'Em processo', 'Operador DEMO', %s)
                """,
                (plan_hash, task, program, sheet, nesting, machine, moment),
            )

    def _end_cut(self, machine: str, moment: datetime) -> None:
        with self.db.connection() as connection:
            connection.execute(
                """
                UPDATE apontamentos_corte
                   SET status = 'Finalizado', operador_fim = 'Operador DEMO', data_fim = %s
                 WHERE maquina = %s AND status = 'Em processo' AND plano_hash LIKE %s
                """,
                (moment, machine, DEMO_CUT_PREFIX + "%"),
            )

    def _mark_state_origin(self, result):
        event_id = (result or {}).get("id")
        if event_id is None:
            raise RuntimeError("Motor de estado não devolveu o fato persistido da DEMO.")
        with self.db.connection() as connection:
            connection.execute(
                "UPDATE eventos_estado_recurso SET origem=%s WHERE id=%s",
                (DEMO_ORIGIN, event_id),
            )

    def _increment_quantities(self, item: ResourceRuntime, now: datetime) -> None:
        if item.appointment_id is None or item.op is None:
            item.next_quantity_at = now + timedelta(minutes=5)
            return
        pace_min, pace_max = LOAD_PROFILES[self.profile]["pace"]
        qty = max(1, round(self.rng.randint(1, 4) * self.rng.uniform(pace_min, pace_max)))
        scrap = 1 if self.rng.random() < LOAD_PROFILES[self.profile]["scrap"] else 0
        with self.db.connection() as connection:
            row = connection.execute(
                "SELECT id,op,quantidade,quantidade_boa,quantidade_refugo FROM apontamentos_operacionais "
                "WHERE id=%s FOR UPDATE", (item.appointment_id,),
            ).fetchone()
            if not row or not str(row["op"]).startswith(DEMO_OP_PREFIX):
                raise RuntimeError("Writer DEMO recusou apontamento fora do seu namespace.")
            ref = f"{item.op}:tick:{now.isoformat()}"
            duplicate = connection.execute(
                "SELECT 1 FROM eventos_quantidade_producao WHERE origem=%s AND referencia_origem=%s LIMIT 1",
                (DEMO_ORIGIN, ref),
            ).fetchone()
            if duplicate:
                item.next_quantity_at = now + timedelta(seconds=self.rng.randint(*QUANTITY_TICK_SECONDS))
                return
            remaining = (
                int(row["quantidade"])
                - int(row["quantidade_boa"] or 0)
                - int(row["quantidade_refugo"] or 0)
            )
            if remaining <= 0:
                item.next_quantity_at = item.cycle_ends
                return
            scrap = min(scrap, remaining)
            qty = min(qty, remaining - scrap)
            connection.execute(
                "UPDATE apontamentos_operacionais SET quantidade_boa=quantidade_boa+%s, "
                "quantidade_refugo=quantidade_refugo+%s WHERE id=%s",
                (qty, scrap, item.appointment_id),
            )
            if qty:
                self.db.registrar_evento_quantidade(
                    "boa", qty, item.op, numero_operacao=item.operation,
                    produto_codigo=item.product, recurso=item.code, tipo_setor=item.sector,
                    operador="DEMO", data_hora=now, origem=DEMO_ORIGIN,
                    referencia_origem=ref, connection=connection,
                )
            if scrap:
                self.db.registrar_evento_quantidade(
                    "refugo", scrap, item.op, numero_operacao=item.operation,
                    produto_codigo=item.product, recurso=item.code, tipo_setor=item.sector,
                    operador="DEMO", motivo="Variação dimensional simulada", data_hora=now,
                    origem=DEMO_ORIGIN, referencia_origem=ref, connection=connection,
                )
        item.next_quantity_at = now + timedelta(seconds=self.rng.randint(*QUANTITY_TICK_SECONDS))

    def _finish_and_restart(self, item: ResourceRuntime, now: datetime) -> None:
        if item.appointment_id is not None:
            with self.db.connection() as connection:
                row = connection.execute(
                    "SELECT quantidade,quantidade_boa FROM apontamentos_operacionais "
                    "WHERE id=%s AND op LIKE %s FOR UPDATE",
                    (item.appointment_id, DEMO_OP_PREFIX + "%"),
                ).fetchone()
                if not row:
                    raise RuntimeError("Ciclo DEMO perdeu o apontamento ativo.")
                finished = int(row["quantidade_boa"] or 0) >= int(row["quantidade"] or 0)
                new_status = "Finalizado" if finished else "Aguardando"
                connection.execute(
                    "UPDATE apontamentos_operacionais SET status=%s,operador_fim=%s,"
                    "data_fim=%s,setor_destino='DEMO' WHERE id=%s",
                    (new_status, "DEMO" if finished else None, now, item.appointment_id),
                )
                connection.execute(
                    "INSERT INTO eventos_apontamento_operador "
                    "(apontamento_id,estado,operador,data_hora,quantidade_boa,quantidade_refugo) "
                    "VALUES (%s,%s,'DEMO',%s,0,0)",
                    (item.appointment_id, "finalizado" if finished else "parcial", now),
                )
        item.sequence += 1
        cycle_minutes = self._cycle_minutes()
        appointment_id, op, operation, product = self._create_active_cycle(
            item.code, item.sector, now, item.sequence, cycle_minutes
        )
        item.appointment_id, item.op, item.operation, item.product = appointment_id, op, operation, product
        item.cycle_started = now
        item.cycle_ends = now + timedelta(minutes=cycle_minutes)
        item.next_quantity_at = now + timedelta(seconds=self.rng.randint(*QUANTITY_TICK_SECONDS))
        item.state = "producao"
        item.resume_at = None
        self._state(item.code, item.sector, "producao", now, op, operation, product)

    def step(self, now: datetime | None = None) -> list[dict]:
        now = (now or datetime.now()).replace(microsecond=0)
        events = []
        if now.date() != self._day:
            # Um apontamento acumulado atravessando meia-noite faria o read
            # model recortar o tempo, mas usar todo o acumulado de boas.
            midnight = datetime.combine(now.date(), datetime.min.time())
            for item in self.resources:
                if item.sector.casefold() != "corte":
                    self._finish_and_restart(item, midnight)
            self._day = now.date()
            events.append({"event": "daily_rotation", "at": now.isoformat()})
        if now >= self.next_profile_at:
            names = [name for name in LOAD_PROFILES if name != self.profile]
            self.profile = self.rng.choices(names, weights=[4, 2, 2], k=1)[0]
            self.next_profile_at = now + timedelta(minutes=self.rng.randint(*PROFILE_MINUTES))
            events.append({"event": "profile", "profile": self.profile, "at": now.isoformat()})
        for item in self.resources:
            if item.sector.casefold() == "corte":
                if item.resume_at and now >= item.resume_at:
                    item.state = "atividade_sem_op"
                    item.resume_at = None
                    self._activity_without_op(item.code, item.sector, now)
                    self._start_cut(item.name, now)
                    events.append({"event": "resume_activity", "resource": item.code})
                if now >= item.cycle_ends:
                    should_stop = (
                        item.state == "atividade_sem_op"
                        and self.rng.random() < LOAD_PROFILES[self.profile]["stop_chance"]
                    )
                    if should_stop:
                        item.state = "parada"
                        item.resume_at = now + timedelta(minutes=self._stop_minutes())
                        self._end_cut(item.name, now)
                        self._state(item.code, item.sector, "parada", now, None, None, None)
                        events.append({"event": "stop", "resource": item.code})
                    else:
                        item.state = "atividade_sem_op"
                        self._activity_without_op(item.code, item.sector, now)
                        self._start_cut(item.name, now)
                        events.append({"event": "activity", "resource": item.code})
                    item.cycle_started = now
                    item.cycle_ends = now + timedelta(minutes=self._cycle_minutes())
                continue
            if item.resume_at and now >= item.resume_at:
                if item.state == "sem_demanda":
                    # Sem OP no estado: ao voltar, o recurso recebe a próxima OP.
                    self._finish_and_restart(item, now)
                    events.append({"event": "new_cycle", "resource": item.code})
                    continue
                item.state = "producao"; item.resume_at = None
                self._state(item.code, item.sector, "producao", now, item.op, item.operation, item.product)
                events.append({"event": "resume", "resource": item.code})
            if now >= item.cycle_ends:
                self._finish_and_restart(item, now)
                events.append({"event": "new_cycle", "resource": item.code})
                continue
            if item.state == "producao" and now >= item.next_quantity_at:
                self._increment_quantities(item, now)
                events.append({"event": "quantity", "resource": item.code})
                if self.rng.random() < LOAD_PROFILES[self.profile]["stop_chance"]:
                    self._begin_episode(item, now)
                    events.append({"event": "stop", "resource": item.code, "state": item.state})
        return events

    def run_forever(self, *, poll_seconds: float = 2.0) -> None:
        self.next_profile_at = datetime.now() + timedelta(minutes=self.rng.randint(8, 16))
        while True:
            for event in self.step():
                LOGGER.info("Andon DEMO: %s", event)
            time.sleep(max(0.2, float(poll_seconds)))


def open_demo_database() -> Database:
    _source, demo_dsn, _maintenance = demo_dsns()
    validate_demo_dsn(demo_dsn)
    return Database(
        config=PostgresConfig(demo_dsn, min_pool_size=1, max_pool_size=4),
        totvs_outbox_config=OutboundEnqueueConfig(enabled=False),
    )
