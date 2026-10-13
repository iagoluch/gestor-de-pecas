"""Mantém uma fábrica TESTE operando em tempo real pela API canônica.

O processo adota WIP após reinício, nunca cria OP e nunca grava tabelas
operacionais.  Quando não há tempo padrão cadastrado, a decisão de agenda fica
explicitamente marcada como ``dados_insuficientes`` no log; os cálculos do MES
continuam sendo feitos pelos serviços normais.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import signal
import sys
import time
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.conninfo import conninfo_to_dict
from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA_DIR = ROOT / "dados" / "factory_realtime"
TARGET_DATABASE = "gestor_pecas_test"
API = f"http://127.0.0.1:{os.getenv('GESTOR_TEST_SIM_PORT', '8002')}/api/v1"  # 8001 é da API REAL
TEST_API_HEADER = "X-Gestor-Factory-Test"
PASSWORD_FILE = ROOT / "config" / "simulacao_industrial.json"
ADVISORY_LOCK_ID = 2_026_100_900_1


@dataclass(frozen=True)
class Station:
    sector: str
    resource: str
    username: str
    badge: str
    password: str | None = None


STATIONS = (
    Station("Dobra", "Gasparini", "sim_dobra", "SIM04"),
    Station("Dobra", "2204", "sim_dobra", "SIM05"),
    Station("Dobra", "1303", "sim_dobra", "SIM06"),
    Station("Pintura", "Jato", "sim_pintura", "SIM20"),
    Station("Pintura", "Preparação", "sim_pintura", "SIM21"),
    Station("Pintura", "Pintura", "sim_pintura", "SIM22"),
    Station("Pintura", "Inspeção Final", "sim_pintura", "SIM24"),
    Station("Protótipo", "SOLDA4", "sim_prototipo", "SIM15"),
    Station("Protótipo", "PREMTG", "sim_prototipo", "SIM16"),
    Station("Usinagem", "Romi D 1000", "sim_usinagem", "SIM07"),
    Station("Usinagem", "Eurostec", "sim_usinagem", "SIM08"),
    Station("Usinagem", "Fresadora FTV31", "sim_usinagem", "SIM09"),
    Station("Usinagem", "Romi GL 350M", "sim_usinagem", "SIM10"),
    Station("Serra", "S4220", "sim_serra", "SIM12"),
    Station("Serra", "SFHA-10", "sim_serra", "SIM13"),
    Station("Corte", "Laser Ensis 3015", "sim_corte", "SIM01"),
    Station("Corte", "Plasma TerraBlade 4", "sim_corte", "SIM02"),
    Station("Solda Robô", "Robô 1", "sim_solda_robo", "SIM30"),
)

MAX_ACTIVE_STATIONS = len(STATIONS)

FALLBACK_MINUTES = {
    "Dobra": (45, 120),
    "Pintura": (20, 75),
    "Protótipo": (60, 170),
    "Usinagem": (60, 150),
    "Serra": (35, 90),
}

STOP_REASONS = (
    ("0011", "Falha de máquina — manutenção corretiva"),
    ("0041", "Falta de componentes"),
    ("0015", "Peça não conforme"),
)

PINTURA_ROUTE_CODES = {
    "Jato": "JATO",
    "Preparação": "PREP",
    "Pintura": "PINT.L",
    "Inspeção Final": "INSPE2",
}


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def stable_int(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:12], 16)


class JsonLog:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path

    def write(self, event: str, **data: Any) -> None:
        payload = {"at": now().isoformat(), "event": event, **data}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
        print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)


class Runtime:
    def __init__(self, poll_seconds: float):
        self.poll_seconds = poll_seconds
        self.stop = asyncio.Event()
        self.log = JsonLog(DATA_DIR / "simulator.jsonl")
        self.state_path = DATA_DIR / "state.json"
        self.state = self._read_state()
        self.password = self._password()
        self.clients: dict[str, httpx.AsyncClient] = {}
        self._file_lock = None
        self._db_lock = None
        self._standard_time_db = None

    @staticmethod
    def _password() -> str:
        raw = json.loads(PASSWORD_FILE.read_text(encoding="utf-8"))
        password = str((raw.get("credenciais") or {}).get("senha_simulacao") or "")
        if not password:
            raise RuntimeError("Senha das contas de simulação não configurada.")
        return password

    def _read_state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            return {"appointments": {}, "stations": {}, "updated_at": None}

    def save_state(self, snapshots: dict[str, dict] | None = None) -> None:
        self.state["updated_at"] = now().isoformat()
        if snapshots is not None:
            self.state["stations"] = {
                name: {
                    "sector": item.get("sector"),
                    "category": (
                        ((item.get("cutting") or {}).get("resource_state") or {}).get("categoria")
                        if item.get("cutting") is not None
                        else ((item.get("workbench") or {}).get("resource_state") or {}).get("categoria")
                    ),
                    "production": [
                        card.get("op")
                        for card in ((item.get("workbench") or {}).get("production") or [])
                    ]
                    + [
                        (item.get("cutting") or {}).get("resource_state", {}).get("referencia_origem")
                    ] if item.get("cutting") is not None and (
                        item.get("cutting") or {}
                    ).get("resource_state", {}).get("categoria") in {"producao", "parada"} else [
                        card.get("op")
                        for card in ((item.get("workbench") or {}).get("production") or [])
                    ],
                    "queue_count": len(
                        ((item.get("cutting") or {}).get("items") or [])
                        if item.get("cutting") is not None
                        else ((item.get("workbench") or {}).get("queue") or [])
                    ),
                    "error": item.get("error"),
                }
                for name, item in snapshots.items()
            }
        temp = self.state_path.with_name(f".state.{os.getpid()}.tmp")
        temp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        for _ in range(20):
            try:
                os.replace(temp, self.state_path)
                return
            except PermissionError:
                time.sleep(0.05)
        self.log.write("state_write_deferred", temporary_path=temp.name)

    def acquire_singleton(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        lock_path = DATA_DIR / "simulator.lock"
        lock = lock_path.open("a+b")
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError("Outro runner da fábrica já está ativo.") from exc

        env = dotenv_values(ROOT / ".env")
        dsn = str(env.get("TEST_DATABASE_URL") or "")
        target = conninfo_to_dict(dsn).get("dbname")
        if target != TARGET_DATABASE:
            raise RuntimeError(f"Banco recusado: {target!r}; esperado {TARGET_DATABASE!r}.")
        operational = conninfo_to_dict(str(env.get("DATABASE_URL") or ""))
        test = conninfo_to_dict(dsn)
        if all(test.get(key) == operational.get(key) for key in ("host", "port", "dbname")):
            raise RuntimeError("Banco TESTE coincide com o banco operacional.")
        connection = psycopg.connect(dsn, autocommit=True, application_name="factory_realtime")
        actual = connection.execute("SELECT current_database()").fetchone()[0]
        locked = connection.execute(
            "SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_ID,)
        ).fetchone()[0]
        if actual != TARGET_DATABASE or not locked:
            connection.close()
            raise RuntimeError("Identidade do banco ou advisory lock recusado.")
        self._file_lock = lock
        self._db_lock = connection
        # Usa a própria consulta canônica do produto para preservar a prioridade
        # Protheus > manual > estimado também nas OPs liberadas depois do start.
        from app.database.database import Database

        self._standard_time_db = Database(dsn=dsn, auto_migrate=False)
        (DATA_DIR / "simulator.pid").write_text(str(os.getpid()), encoding="ascii")

    async def close(self) -> None:
        for client in self.clients.values():
            await client.aclose()
        self.clients.clear()
        if self._standard_time_db is not None:
            self._standard_time_db.close()
            self._standard_time_db = None
        if self._db_lock is not None:
            try:
                self._db_lock.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_ID,))
            finally:
                self._db_lock.close()
        if self._file_lock is not None:
            self._file_lock.seek(0)
            msvcrt.locking(self._file_lock.fileno(), msvcrt.LK_UNLCK, 1)
            self._file_lock.close()
        try:
            (DATA_DIR / "simulator.pid").unlink()
        except FileNotFoundError:
            pass

    async def client(self, station: Station) -> httpx.AsyncClient:
        client = self.clients.get(station.resource)
        if client is not None:
            return client
        client = httpx.AsyncClient(
            base_url=API,
            timeout=20,
            follow_redirects=False,
        )
        health = await client.get("/system/health")
        if (
            health.status_code != 200
            or health.headers.get(TEST_API_HEADER) != TARGET_DATABASE
        ):
            await client.aclose()
            raise RuntimeError(
                "API recusada: o processo na porta da simulação TESTE não confirmou o ambiente TESTE."
            )
        response = await client.post(
            "/auth/login",
            json={"username": station.username, "password": station.password or self.password},
        )
        if response.status_code != 200:
            await client.aclose()
            raise RuntimeError(f"Login recusado para {station.username}: HTTP {response.status_code}")
        self.clients[station.resource] = client
        return client

    def active_break(self, station: Station):
        """Lê a pausa configurada; não substitui a autoridade do scheduler."""

        if self._standard_time_db is None:
            return None
        try:
            from mes.services.shift_boundary import ShiftBoundaryService

            return ShiftBoundaryService(self._standard_time_db).active_break(
                {"tipo_setor": station.sector}, now()
            )
        except Exception as exc:
            self.log.write(
                "break_read_failed",
                resource=station.resource,
                sector=station.sector,
                error=f"{type(exc).__name__}: {exc}",
            )
            return None

    @staticmethod
    def csrf(client: httpx.AsyncClient) -> dict[str, str]:
        token = client.cookies.get("gestor_csrf") or ""
        return {"X-CSRF-Token": token} if token else {}

    async def workbench(self, station: Station) -> dict:
        client = await self.client(station)
        response = await client.get("/operator/workbench", params={"resource": station.resource})
        if response.status_code == 401:
            await client.aclose()
            self.clients.pop(station.resource, None)
            client = await self.client(station)
            response = await client.get("/operator/workbench", params={"resource": station.resource})
        response.raise_for_status()
        return response.json()

    def local_catalog_rows(self, station: Station) -> list[dict[str, Any]]:
        """Lista somente operações locais reais que este posto pode executar.

        A consulta é de descoberta; toda decisão de disponibilidade e toda
        escrita continuam passando pelo contrato HTTP do posto.
        """

        if self._standard_time_db is None:
            return []
        from app.core.resource_mapping import station_matches_route

        query = """
            SELECT
                operacao.id,
                operacao.codigo_op,
                operacao.numero_operacao,
                operacao.codigo_recurso,
                operacao.tipo_setor,
                recurso.tipo_setor AS recurso_tipo_setor,
                operacao.ordem
            FROM catalogo_operacoes_op operacao
            JOIN catalogo_pcp_ops pcp
              ON pcp.codigo_op = operacao.codigo_op
             AND pcp.ativo IS TRUE
            LEFT JOIN catalogo_recursos_pcfactory recurso
              ON recurso.codigo = operacao.codigo_recurso
            WHERE operacao.ativo IS TRUE
              AND operacao.fonte = 'totvs_production_order_v1'
              AND UPPER(operacao.tipo_setor) = UPPER(%s)
            ORDER BY operacao.codigo_op, operacao.ordem, operacao.id
        """
        with self._standard_time_db.connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(query, (station.sector,))
                rows = [dict(row) for row in cursor.fetchall()]
        rows = [
            row
            for row in rows
            if station_matches_route(
                station.sector,
                station.resource,
                row.get("codigo_recurso"),
                resource_sector=row.get("recurso_tipo_setor"),
            )
        ]
        expected_pintura_code = PINTURA_ROUTE_CODES.get(station.resource)
        if expected_pintura_code:
            rows = [
                row
                for row in rows
                if str(row.get("codigo_recurso") or "").strip().upper()
                == expected_pintura_code
            ]
        return rows

    async def local_catalog_candidates(self, station: Station) -> list[dict[str, Any]]:
        """Confirma no backend quais etapas locais estão selecionáveis.

        Não chama o endpoint de sync e, portanto, nunca consulta o ERP. Etapas
        futuras só entram quando o próprio domínio as publica como selecionáveis
        e conserva a confirmação de responsável exigida pelo fluxo canônico.
        """

        client = await self.client(station)
        candidates: list[dict[str, Any]] = []
        seen_ops: set[str] = set()
        for catalog in self.local_catalog_rows(station):
            op = str(catalog.get("codigo_op") or "").strip()
            if not op or op in seen_ops:
                continue
            seen_ops.add(op)
            response = await client.get(
                f"/operator/operations/{op}", params={"resource": station.resource}
            )
            if response.status_code != 200:
                self.log.write(
                    "catalog_read_failed",
                    resource=station.resource,
                    op=op,
                    http=response.status_code,
                )
                continue
            selected = next(
                (
                    row
                    for row in response.json().get("items") or []
                    if int(row.get("id") or row.get("catalogo_operacao_id") or 0)
                    == int(catalog.get("id") or 0)
                    and row.get("station_eligible")
                    and row.get("selectable")
                    and row.get("visual_status") != "done"
                ),
                None,
            )
            if selected is not None:
                candidates.append({**selected, "op": op})
        candidates.sort(
            key=lambda row: (
                row.get("visual_status") != "current",
                str(row.get("op") or ""),
                int(row.get("ordem") or 0),
            )
        )
        return candidates

    async def action(self, station: Station, card: dict, action: str, **extra: Any) -> tuple[int, dict]:
        client = await self.client(station)
        payload: dict[str, Any] = {
            "action": action,
            "resource": station.resource,
        }
        op = str(card.get("op") or "").strip()
        if op:
            payload["op"] = op
        operation_id = card.get("catalogo_operacao_id") or card.get("id_operacao")
        if operation_id:
            payload["operation_id"] = int(operation_id)
        operation_number = card.get("numero_operacao")
        if operation_number:
            payload["operation_number"] = str(operation_number)
        payload.update(extra)
        response = await client.post(
            "/operator/actions", json=payload, headers=self.csrf(client)
        )
        try:
            data = response.json()
        except ValueError:
            data = {"message": response.text[:300]}
        return response.status_code, data

    @staticmethod
    def error_code(data: Any) -> str:
        current = data
        for _ in range(4):
            if not isinstance(current, dict):
                return ""
            if current.get("code"):
                return str(current["code"])
            current = current.get("error") or current.get("detail")
        return ""

    def canonical_standard_time(self, card: dict) -> tuple[float | None, str | None]:
        if self._standard_time_db is None:
            return None, None
        product = str(card.get("produto_codigo") or card.get("product") or "").strip()
        operation = str(card.get("numero_operacao") or "").strip()
        resource = str(card.get("codigo_recurso") or "").strip()
        if not product or not operation or not resource:
            return None, None
        result = self._standard_time_db.listar_tempos_padrao(
            produto=product,
            recurso=resource,
            somente_sem_padrao=False,
            limite=500,
        )
        for item in result.get("items") or ():
            if (
                str(item.get("produto_codigo") or "").strip().upper() != product.upper()
                or str(item.get("numero_operacao") or "").strip() != operation
                or str(item.get("codigo_recurso") or "").strip().upper() != resource.upper()
            ):
                continue
            source = str(item.get("fonte_efetiva") or "")
            value = {
                "protheus": item.get("tempo_protheus_segundos"),
                "manual": item.get("tempo_manual_segundos"),
                "estimado": item.get("tempo_estimado_segundos"),
            }.get(source)
            if value is not None and float(value) > 0:
                return float(value), source
        return None, None

    def appointment(self, card: dict, station: Station) -> dict[str, Any]:
        key = str(card.get("id") or f"{card.get('op')}:{card.get('numero_operacao')}")
        saved = self.state["appointments"].setdefault(key, {})
        if "target_seconds" not in saved:
            standard, standard_source = self.canonical_standard_time(card)
            qty = max(1, int(card.get("qty") or card.get("quantidade") or 1))
            if standard and float(standard) > 0:
                target = max(60.0, float(standard) * qty)
                source = f"tempo_padrao_{standard_source}"
            else:
                low, high = FALLBACK_MINUTES.get(station.sector, (45, 120))
                seed = stable_int(f"{card.get('op')}:{card.get('numero_operacao')}")
                minutes = low + seed % (high - low + 1)
                target = float(min(high * 60, max(low * 60, minutes * 60 * qty)))
                source = "dados_insuficientes_sem_tempo_padrao"
            saved.update(
                {
                    "op": card.get("op"),
                    "operation": card.get("numero_operacao"),
                    "resource": station.resource,
                    "sector": station.sector,
                    "target_seconds": target,
                    "duration_source": source,
                    "created_at": now().isoformat(),
                }
            )
            self.log.write(
                "appointment_schedule",
                appointment_id=key,
                op=card.get("op"),
                resource=station.resource,
                target_minutes=round(target / 60, 1),
                duration_source=source,
            )
            self.save_state()
        return saved

    async def start_card(self, station: Station, card: dict) -> bool:
        status, data = await self.action(
            station, card, "Início", badges=[station.badge]
        )
        code = self.error_code(data)
        if status in {400, 403, 409, 422} and code in {
            "confirmacao_recurso_obrigatoria",
            "confirmacao_etapa_anterior_obrigatoria",
        }:
            extra = {
                "badges": [station.badge, "SIM99"],
                "confirm_resource_divergence": True,
            }
            if code == "confirmacao_etapa_anterior_obrigatoria":
                extra["confirm_previous_step"] = True
            status, data = await self.action(station, card, "Início", **extra)
            code = self.error_code(data)
        self.log.write(
            "start",
            resource=station.resource,
            sector=station.sector,
            op=card.get("op"),
            http=status,
            code=code,
        )
        return 200 <= status < 300

    async def setup_and_quality(
        self,
        station: Station,
        card: dict,
        saved: dict,
        resource_category: str,
    ) -> None:
        client = await self.client(station)
        params = {
            "op": card.get("op"),
            "resource": station.resource,
            "operation_id": card.get("catalogo_operacao_id"),
        }
        response = await client.get("/operator/first-piece", params=params)
        if response.status_code != 200:
            self.log.write("quality_read_failed", resource=station.resource, op=card.get("op"), http=response.status_code)
            return
        first_piece = response.json()
        if not first_piece.get("gate_estruturado"):
            saved["quality_done"] = "gate_nao_aplicavel"
            self.save_state()
            return
        if first_piece.get("liberado"):
            if resource_category == "setup":
                status, data = await self.action(station, card, "Retornar")
                self.log.write(
                    "quality_adopted_return",
                    resource=station.resource,
                    op=card.get("op"),
                    http=status,
                    code=self.error_code(data),
                )
                if not 200 <= status < 300:
                    saved.pop("quality_done", None)
                    self.save_state()
                    return
            saved["quality_done"] = now().isoformat()
            saved.pop("quality_blocked", None)
            self.save_state()
            return
        last_blocked = parse_datetime(saved.get("quality_blocked_at"))
        if last_blocked and (now() - last_blocked).total_seconds() < 600:
            return
        if not saved.get("setup_started_at"):
            status, data = await self.action(
                station,
                card,
                "Setup",
                setup_type="Simulação em tempo real — preparação da máquina",
            )
            if 200 <= status < 300:
                saved["setup_started_at"] = now().isoformat()
                self.log.write("setup", resource=station.resource, op=card.get("op"), http=status)
                self.save_state()
            else:
                self.log.write(
                    "setup_blocked",
                    resource=station.resource,
                    op=card.get("op"),
                    http=status,
                    code=self.error_code(data),
                )
            return
        started = parse_datetime(saved.get("setup_started_at"))
        if saved.get("quality_done") or not started or (now() - started).total_seconds() < 300:
            return
        cotas = (((first_piece.get("checklist") or {}).get("template") or {}).get("cotas") or [])
        if not cotas:
            saved["quality_blocked"] = "template_ausente"
            saved["quality_blocked_at"] = now().isoformat()
            self.log.write(
                "quality_data_insufficient",
                resource=station.resource,
                op=card.get("op"),
                reason="template_ausente",
            )
            self.save_state()
            return
        measures = []
        for index, item in enumerate(cotas):
            reference = item.get("referencia")
            if reference is None:
                saved["quality_blocked"] = "referencia_ausente"
                saved["quality_blocked_at"] = now().isoformat()
                self.log.write(
                    "quality_data_insufficient",
                    resource=station.resource,
                    op=card.get("op"),
                    reason="referencia_ausente",
                )
                self.save_state()
                return
            measures.append(
                {
                    "sequencia": int(item.get("sequencia") or index + 1),
                    "medida": str(reference),
                    "status": "CONFORME",
                }
            )
        payload = {
            "op": card.get("op"),
            "resource": station.resource,
            "operation_id": card.get("catalogo_operacao_id"),
            "operation_number": str(card.get("numero_operacao") or ""),
            "action": "checklist",
            "measures": measures,
            "note": "Simulação em tempo real — medidas conforme template existente.",
        }
        submitted = await client.post(
            "/operator/first-piece", json=payload, headers=self.csrf(client)
        )
        if submitted.status_code >= 300:
            self.log.write(
                "quality_blocked",
                resource=station.resource,
                op=card.get("op"),
                http=submitted.status_code,
                code=self.error_code(submitted.json()),
            )
            return
        status, data = await self.action(station, card, "Retornar")
        if 200 <= status < 300:
            saved["quality_done"] = now().isoformat()
            saved.pop("quality_blocked", None)
            saved.pop("quality_blocked_at", None)
            self.log.write("quality_approved", resource=station.resource, op=card.get("op"), measures=len(measures))
            self.save_state()
        else:
            self.log.write("quality_return_blocked", resource=station.resource, op=card.get("op"), http=status, code=self.error_code(data))

    async def finish(self, station: Station, card: dict, saved: dict) -> None:
        qty = max(1, int(card.get("qty") or card.get("quantidade") or 1))
        attended = int(card.get("good") or card.get("quantidade_boa") or 0) + int(
            card.get("scrap") or card.get("quantidade_refugo") or 0
        )
        balance = max(0, qty - attended)
        if balance <= 0:
            return
        scrap = 1 if balance >= 2 and stable_int(str(card.get("op"))) % 5 == 0 else 0
        good = balance - scrap
        extra: dict[str, Any] = {
            "badges": [station.badge],
            "good": good,
            "scrap": scrap,
            "lot": f"SIM-RT-{now():%Y%m%d}",
        }
        if scrap:
            extra.update(
                {
                    "badges": [station.badge, "SIM99"],
                    "scrap_reason": "Peça não conforme durante a simulação em tempo real.",
                    "root_cause": "Variação do processo observada na inspeção.",
                    "scrap_authorization_badge": "SIM99",
                }
            )
        status, data = await self.action(station, card, "Finalizado", **extra)
        code = self.error_code(data)
        self.log.write(
            "finish",
            resource=station.resource,
            sector=station.sector,
            op=card.get("op"),
            good=good,
            scrap=scrap,
            http=status,
            code=code,
        )
        if 200 <= status < 300:
            saved["finished_at"] = now().isoformat()
            self.save_state()

    async def manage_active(self, station: Station, workbench: dict) -> None:
        production = list(workbench.get("production") or [])
        if not production:
            return
        card = production[0]
        saved = self.appointment(card, station)
        resource_state = workbench.get("resource_state") or {}
        category = str(resource_state.get("categoria") or "")
        started = parse_datetime(card.get("data_inicio")) or parse_datetime(saved.get("created_at")) or now()
        paused_seconds = float(saved.get("paused_seconds") or 0.0)

        if category == "parada":
            stopped = parse_datetime(resource_state.get("data_inicio")) or now()
            if not saved.get("pause_started_at"):
                saved["pause_started_at"] = stopped.isoformat()
            if not saved.get("stop_requested_at"):
                saved["stop_requested_at"] = stopped.isoformat()
            self.save_state()
            stop_minutes = 5 + stable_int(f"stop:{card.get('op')}") % 16
            if (now() - stopped).total_seconds() >= stop_minutes * 60:
                status, data = await self.action(station, card, "Retomar")
                self.log.write(
                    "resume",
                    resource=station.resource,
                    op=card.get("op"),
                    stopped_minutes=stop_minutes,
                    http=status,
                    code=self.error_code(data),
                )
            return

        pause_started = parse_datetime(saved.get("pause_started_at"))
        if pause_started:
            paused_seconds += max(0.0, (now() - pause_started).total_seconds())
            saved["paused_seconds"] = paused_seconds
            saved.pop("pause_started_at", None)
            self.save_state()
        elapsed = max(0.0, (now() - started).total_seconds() - paused_seconds)

        setup_at = min(900.0, float(saved["target_seconds"]) * 0.25)
        if elapsed >= setup_at and (
            not saved.get("quality_done") or category == "setup"
        ):
            await self.setup_and_quality(station, card, saved, category)
            return

        should_stop = stable_int(f"event:{card.get('op')}") % 3 == 0
        stop_at = float(saved["target_seconds"]) * 0.35
        if should_stop and not saved.get("stop_requested_at") and elapsed >= stop_at:
            code, description = STOP_REASONS[stable_int(str(card.get("op"))) % len(STOP_REASONS)]
            status, data = await self.action(
                station,
                card,
                "Parada",
                stop_reason_code=code,
                comment=f"Simulação em tempo real — {description}.",
            )
            saved["stop_requested_at"] = now().isoformat()
            self.log.write(
                "stop",
                resource=station.resource,
                op=card.get("op"),
                reason_code=code,
                http=status,
                code=self.error_code(data),
            )
            self.save_state()
            return

        if elapsed >= float(saved["target_seconds"]):
            await self.finish(station, card, saved)

    @staticmethod
    def cutting_current(queue: dict) -> dict[str, Any] | None:
        for item in queue.get("items") or ():
            if str(item.get("status") or "").casefold() == "em processo":
                return item
        return None

    async def cutting_action(self, station: Station, payload: dict[str, Any]) -> tuple[int, dict]:
        client = await self.client(station)
        response = await client.post(
            "/cutting/actions", json=payload, headers=self.csrf(client)
        )
        try:
            data = response.json()
        except ValueError:
            data = {"message": response.text[:300]}
        return response.status_code, data

    async def manage_cutting(self, station: Station, queue: dict) -> None:
        resource_state = queue.get("resource_state") or {}
        current = self.cutting_current(queue)
        if current is None:
            if str(resource_state.get("categoria") or "") in {"parada", "producao"}:
                return
            candidate = next(
                (item for item in queue.get("items") or ()
                 if str(item.get("status") or "").casefold() == "aguardando"
                 and item.get("plano_hash")),
                None,
            )
            if candidate is None:
                return
            status, data = await self.cutting_action(
                station,
                {
                    "action": "Início",
                    "resource": station.resource,
                    "plan_hash": candidate["plano_hash"],
                },
            )
            self.log.write(
                "cut_start",
                resource=station.resource,
                plan_hash=candidate.get("plano_hash"),
                program=candidate.get("programa_atual") or candidate.get("programa"),
                http=status,
                code=self.error_code(data),
            )
            return

        key = str(current.get("plano_hash") or current.get("programa_atual") or station.resource)
        saved = self.state.setdefault("cutting", {}).setdefault(key, {})
        target = float(current.get("tempo_previsto_segundos") or 0)
        if target <= 0:
            target = 60.0
        saved.setdefault("target_seconds", target)
        saved.setdefault("started_at", current.get("data_inicio") or now().isoformat())
        category = str(resource_state.get("categoria") or "")
        if category == "parada":
            stopped = parse_datetime(resource_state.get("data_inicio")) or now()
            saved.setdefault("pause_started_at", stopped.isoformat())
            stop_minutes = 5 + stable_int(f"cut-stop:{key}") % 16
            if (now() - stopped).total_seconds() >= stop_minutes * 60:
                status, data = await self.cutting_action(
                    station,
                    {"action": "Retomada", "resource": station.resource},
                )
                self.log.write(
                    "cut_resume",
                    resource=station.resource,
                    plan_hash=key,
                    stopped_minutes=stop_minutes,
                    http=status,
                    code=self.error_code(data),
                )
            self.save_state()
            return

        pause_started = parse_datetime(saved.pop("pause_started_at", None))
        paused = float(saved.get("paused_seconds") or 0)
        if pause_started:
            stopped_seconds = max(0.0, (now() - pause_started).total_seconds())
            paused += stopped_seconds
            saved["paused_seconds"] = paused
            self.log.write(
                "cut_resume_observed",
                resource=station.resource,
                plan_hash=key,
                stopped_seconds=round(stopped_seconds, 1),
            )
        started = parse_datetime(saved.get("started_at")) or now()
        elapsed = max(0.0, (now() - started).total_seconds() - paused)
        if elapsed >= float(saved["target_seconds"]):
            appointment_ids = current.get("apontamento_ids_em_processo") or []
            appointment_id = appointment_ids[0] if appointment_ids else None
            if appointment_id is not None:
                status, data = await self.cutting_action(
                    station,
                    {
                        "action": "Finalizado",
                        "resource": station.resource,
                        "plan_hash": key,
                        "appointment_id": int(appointment_id),
                    },
                )
                self.log.write(
                    "cut_finish",
                    resource=station.resource,
                    plan_hash=key,
                    appointment_id=appointment_id,
                    http=status,
                    code=self.error_code(data),
                )
            return

        if elapsed >= float(saved["target_seconds"]) * 0.35 and not saved.get("stop_requested_at"):
            code, description = STOP_REASONS[stable_int(key) % len(STOP_REASONS)]
            status, data = await self.cutting_action(
                station,
                {
                    "action": "Parada",
                    "resource": station.resource,
                    "plan_hash": key,
                    "stop_reason_code": code,
                    "comment": f"Simulação em tempo real — {description}.",
                },
            )
            saved["stop_requested_at"] = now().isoformat()
            self.log.write(
                "cut_stop",
                resource=station.resource,
                plan_hash=key,
                reason_code=code,
                http=status,
                code=self.error_code(data),
            )
        self.save_state()

    async def snapshot(self, station: Station) -> tuple[str, dict]:
        try:
            if station.sector == "Corte":
                client = await self.client(station)
                response = await client.get(
                    "/cutting/queue", params={"resource": station.resource}
                )
                response.raise_for_status()
                return station.resource, {"sector": station.sector, "cutting": response.json()}
            return station.resource, {"sector": station.sector, "workbench": await self.workbench(station)}
        except Exception as exc:
            return station.resource, {"sector": station.sector, "error": f"{type(exc).__name__}: {exc}"}

    async def cycle(self) -> None:
        results = await asyncio.gather(*(self.snapshot(station) for station in STATIONS))
        snapshots = dict(results)
        occupied = {
            str(card.get("op"))
            for item in snapshots.values()
            for card in (((item.get("workbench") or {}).get("production") or []))
            if card.get("op")
        }
        active = 0
        catalog_eligible = 0
        for station in STATIONS:
            try:
                item = snapshots[station.resource]
                if station.sector == "Corte":
                    cutting = item.get("cutting")
                    if not isinstance(cutting, dict):
                        if item.get("error"):
                            self.log.write("station_error", resource=station.resource, error=item["error"])
                        continue
                    category = str((cutting.get("resource_state") or {}).get("categoria") or "")
                    if category in {"producao", "parada"}:
                        active += 1
                    await self.manage_cutting(station, cutting)
                    continue
                workbench = item.get("workbench")
                if not isinstance(workbench, dict):
                    if item.get("error"):
                        self.log.write("station_error", resource=station.resource, error=item["error"])
                    continue
                production = list(workbench.get("production") or [])
                if production:
                    active += 1
                    await self.manage_active(station, workbench)
                    continue
                resource_state = workbench.get("resource_state") or {}
                if resource_state.get("categoria") == "atividade_sem_op":
                    active += 1
                    continue
                if active >= MAX_ACTIVE_STATIONS:
                    continue
                configured_break = self.active_break(station)
                if configured_break:
                    self.log.write(
                        "intervalo_configurado_bloqueio_inicio",
                        resource=station.resource,
                        sector=station.sector,
                        nome=configured_break[1],
                    )
                    continue
                rejected = self.state.setdefault("start_rejections", {})
                queue = list(workbench.get("queue") or [])
                local = await self.local_catalog_candidates(station)
                catalog_eligible += len(local)
                candidates = queue + [
                    candidate
                    for candidate in local
                    if str(candidate.get("op") or "")
                    not in {str(item.get("op") or "") for item in queue}
                ]
                attempts = 0
                for candidate in candidates:
                    op = str(candidate.get("op") or "")
                    if not op or op in occupied or candidate.get("finished"):
                        continue
                    rejection_key = f"{station.resource}|{op}"
                    previous = parse_datetime((rejected.get(rejection_key) or {}).get("at"))
                    if previous and (now() - previous).total_seconds() < 300:
                        continue
                    if attempts >= 8:
                        break
                    attempts += 1
                    if await self.start_card(station, candidate):
                        rejected.pop(rejection_key, None)
                        occupied.add(op)
                        active += 1
                        break
                    rejected[rejection_key] = {"at": now().isoformat()}
                    self.save_state()
            except Exception as exc:
                self.log.write(
                    "station_cycle_error",
                    resource=station.resource,
                    error=f"{type(exc).__name__}: {exc}",
                )
        self.state["active_count"] = active
        self.state["eligible_queue_count"] = sum(
            len(((item.get("workbench") or {}).get("queue") or []))
            for item in snapshots.values()
        )
        self.state["eligible_catalog_count"] = catalog_eligible
        self.save_state(snapshots)

    async def run(self) -> None:
        self.acquire_singleton()
        self.log.write(
            "runner_started",
            pid=os.getpid(),
            database=TARGET_DATABASE,
            api=API,
            clock="real",
            totvs="disabled",
            station_count=len(STATIONS),
        )
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop.set)
            except (NotImplementedError, RuntimeError):
                pass
        try:
            while not self.stop.is_set():
                started = asyncio.get_running_loop().time()
                await self.cycle()
                remaining = max(0.5, self.poll_seconds - (asyncio.get_running_loop().time() - started))
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=remaining)
                except TimeoutError:
                    pass
        finally:
            self.log.write("runner_stopped", pid=os.getpid())
            await self.close()


def configure_environment() -> None:
    os.environ.update(
        {
            "DATABASE_URL": "",
            "GESTOR_EXPECTED_DATABASE": TARGET_DATABASE,
            "GESTOR_TEST_MODE": "1",
            "GESTOR_SIMULATION_MODE": "0",
            "GESTOR_SIMULATION_TIME_SCALE": "0",
            "GESTOR_TOTVS_ENABLED": "0",
            "GESTOR_TOTVS_SOAP_ENABLED": "0",
            "GESTOR_TOTVS_OUTBOX_ENABLED": "0",
            "GESTOR_TOTVS_OUTBOX_WORKER_ENABLED": "0",
            "GESTOR_SIGMANEST_SYNC_ENABLED": "0",
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    args = parser.parse_args()
    configure_environment()
    try:
        asyncio.run(Runtime(max(5.0, args.poll_seconds)).run())
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"factory realtime: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
