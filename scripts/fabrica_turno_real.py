#!/usr/bin/env python3
"""Simulador de turno REAL (tempo 1:1) para o Gestor de Peças.

Executar dentro da raiz do repositório, usando APENAS TEST_DATABASE_URL.
Usa OperatorFlowService: nenhum INSERT/UPDATE operacional direto, nenhum ERP.
NÃO sobe/reinicia servidor ou Andon. Corte/Destaque exigem fluxos próprios;
não são falsificados como apontamentos comuns.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
import logging
import math
import os
from pathlib import Path
import random
import re
import signal
import sys
import time
from urllib.parse import urlparse

# Execucao por caminho (python scripts\fabrica_turno_real.py) deixa apenas
# scripts/ no sys.path; os pacotes app/ e mes/ estao na raiz.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOG = logging.getLogger("fabrica")
APP_NAME = "SIMULADOR_TURNO_TESTE"
BAD_SOURCES = ("demo", "soak", "fixture", "seed", "fake", "visual", "simul")
BLOCKED_SECTORS = {"corte", "destaque"}  # requerem fluxo SigmaNEST próprio
ACTIVE_STATUSES = {"Em processo", "Parada", "Setup", "Retrabalho", "Aguardando"}


def instant() -> datetime:
    return datetime.now().replace(microsecond=0)


def proof_test_db(dsn: str, expected: str, prod_dsn: str) -> None:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    parsed = conninfo_to_dict(dsn)
    name = str(parsed.get("dbname") or "")
    if not expected or name.casefold() != expected.casefold() or "test" not in name.casefold():
        raise RuntimeError(f"Banco recusado: somente banco TESTE explícito ({expected})")
    if prod_dsn and conninfo_to_dict(prod_dsn) == parsed:
        raise RuntimeError("TEST_DATABASE_URL coincide com DATABASE_URL: abortado")
    with psycopg.connect(dsn) as c:
        live = c.execute("select current_database()").fetchone()[0]
        if str(live).casefold() != expected.casefold():
            raise RuntimeError("O banco conectado não corresponde ao esperado")
    LOG.info("Banco de TESTE validado: %s", expected)


@dataclass
class Posto:
    codigo: str
    setor: str
    estado: str = "ocioso"
    op: str = ""
    produto: str = ""
    operacao: dict = field(default_factory=dict)
    inicio: datetime | None = None
    fim_previsto: datetime | None = None
    proximo_evento: datetime | None = None
    retornar_em: datetime | None = None
    episodios: int = 0
    executou: bool = False
    falhas: int = 0
    bloqueio: str = ""
    primeira_peca: str = "pendente"
    pausado_segundos: float = 0
    pausa_inicio: datetime | None = None


class Simulador:
    def __init__(self, db, *, seed, hours, max_active, badge, tick, log_path, status_path):
        from mes.services.operator_flow import OperatorFlowService
        self.db = db
        self.service = OperatorFlowService(db, APP_NAME)
        from mes.services.first_piece import FirstPieceService
        self.first_piece = FirstPieceService(db, APP_NAME)
        self.rng = random.Random(seed)
        self.hours = hours
        self.max_active = max_active
        self.badge = badge
        self.tick = tick
        self.log_path = log_path
        self.status_path = status_path
        self.end_at = instant() + timedelta(hours=hours)
        self.stop = False
        self.postos: list[Posto] = []
        self.usadas_ops: set[tuple[str, str]] = set()
        self.total = {k: 0 for k in ("inicio", "setup", "parada", "retomada", "retornar", "finalizado", "bloqueio")}
        self.last_launch = datetime.min
        self.advisory = None

    def lock(self, dsn):
        import psycopg
        self.advisory = psycopg.connect(dsn, autocommit=True)
        acquired = self.advisory.execute(
            "SELECT pg_try_advisory_lock(hashtext(%s))", ("gestor:simulador-turno:v1",)
        ).fetchone()[0]
        if not acquired:
            raise RuntimeError("Outro simulador do turno já está ativo neste banco")

    def discover(self):
        # Somente o catálogo HABILITADO. O inventário do scheduler também
        # acrescenta certas estações sem cadastro (o que gerou a falsa Solda).
        from app.core.resource_mapping import resolve_resource_identity
        from app.core.operator_sectors import participa_da_timeline
        records = self.db.listar_recursos_pcfactory(somente_habilitados=True)
        seen = set()
        for row in records:
            setor = str(row.get("tipo_setor") or "").strip()
            raw = str(row.get("codigo") or "").strip()
            codigo = resolve_resource_identity(raw)
            if not codigo or not setor or not participa_da_timeline(raw, codigo):
                continue
            if codigo.casefold() in seen:
                continue
            seen.add(codigo.casefold())
            self.postos.append(Posto(codigo=codigo, setor=setor))
        self.rng.shuffle(self.postos)
        if not self.postos:
            raise RuntimeError("Nenhum recurso físico habilitado no cadastro TESTE")
        LOG.info("Inventário: %d recursos físicos de %d setores", len(self.postos), len({p.setor for p in self.postos}))
        return self.postos

    def _candidates(self, p):
        from app.core.resource_mapping import station_matches_route
        if p.setor.casefold() in BLOCKED_SECTORS:
            p.bloqueio = "Fluxo exclusivo (Corte/Destaque): precisa do nesting/tarefa original"
            return []
        rows = self.db.listar_proximas_operacoes_roteiro(p.setor)
        results = []
        for row in rows:
            op = str(row.get("codigo_op") or "").strip()
            fonte = str(row.get("fonte") or "").lower()
            product = str(row.get("produto_codigo") or "").strip()
            if not op or not product or any(flag in fonte for flag in BAD_SOURCES):
                continue
            # OP tem de vir do cadastro TOTVS, não de uma semente local.
            if not ("totvs" in fonte or "protheus" in fonte):
                continue
            rec = str(row.get("codigo_recurso") or "").strip()
            if not rec or not station_matches_route(p.setor, p.codigo, rec, resource_sector=row.get("recurso_tipo_setor")):
                continue
            if (op, str(row.get("id"))) in self.usadas_ops:
                continue
            if not row.get("tempo_medio_segundos") or int(row.get("quantidade") or 0) <= 0:
                continue
            # Serviço oficial resolve operação atual, pré-requisitos e elegibilidade.
            route = self.service.listar_operacoes(op, p.setor, p.codigo)
            available = next((x for x in route if x.get("id") == row.get("id") and x.get("selectable")
                              and x.get("visual_current")), None)
            if available:
                results.append((op, available))
        return results

    def _act(self, p, name, *, extras=None):
        kw = dict(op=p.op, setor=p.setor, recurso=p.codigo, operacao=p.operacao,
                  operadores_cracha=[self.badge] if self.badge else [], recurso_exclusivo=True)
        kw.update(extras or {})
        try:
            result = self.service.executar(name, **kw)
        except Exception as exc:
            LOG.exception("%s %s %s: erro", p.codigo, p.op, name)
            p.bloqueio = repr(exc)[:250]
            p.falhas += 1
            return False
        if not result.ok:
            LOG.warning("BLOQUEADO recurso=%s OP=%s acao=%s codigo=%s mensagem=%s",
                        p.codigo, p.op, name, result.code, result.message)
            p.bloqueio = str(result.code or result.message)
            p.falhas += 1
            self.total["bloqueio"] += 1
            return False
        self.total[{"Início": "inicio", "Setup": "setup", "Parada": "parada",
                    "Retomar": "retomada", "Retornar": "retornar", "Finalizado": "finalizado"}[name]] += 1
        LOG.info("EVENTO %s setor=%s recurso=%s OP=%s produto=%s",
                 name, p.setor, p.codigo, p.op, p.produto)
        p.bloqueio = ""
        return True

    def _reason(self, setor, planned):
        reasons = self.service.listar_motivos_parada(setor)
        selected = [r for r in reasons if ("NAO" not in str(r.get("classificacao") or "").upper()
                     and "NÃO" not in str(r.get("classificacao") or "").upper()) == planned]
        return self.rng.choice(selected or reasons) if (selected or reasons) else None

    def _active(self):
        return sum(p.estado in {"producao", "setup", "parada"} for p in self.postos)

    def start(self, p, now):
        if self.service.recurso_em_uso(p.setor, p.codigo):
            p.bloqueio = "Recurso já ocupado (preservado)"
            return False
        jobs = self._candidates(p)
        if not jobs:
            if not p.bloqueio:
                p.bloqueio = "Sem OP TOTVS elegível neste recurso/etapa"
            return False
        op, operacao = self.rng.choice(jobs)
        p.op = op
        p.operacao = operacao
        p.produto = str(operacao.get("produto_codigo") or operacao.get("produto") or "")
        if not self._act(p, "Início"):
            p.op, p.produto, p.operacao = "", "", {}
            return False
        planned = int(operacao.get("quantidade_planejada") or operacao.get("quantidade") or 1)
        already = int(operacao.get("quantidade_boa_registrada") or 0)
        seconds_each = max(1, float(operacao.get("tempo_medio_segundos") or 0))
        required = max(1, planned - already) * seconds_each
        # Respeita o tempo padrão: a produtividade variável (75-97%) amplia a duração.
        # Não encerra a OP se o tempo verdadeiro ultrapassar o fim do turno.
        segment_seconds = required / self.rng.uniform(0.75, 0.97)
        p.inicio = now
        p.primeira_peca = "pendente"
        p.pausado_segundos = 0
        p.pausa_inicio = None
        p.fim_previsto = now + timedelta(seconds=max(60, segment_seconds))
        p.proximo_evento = now + timedelta(minutes=self.rng.randint(4, 8))
        p.estado = "producao"
        p.executou = True
        self.usadas_ops.add((op, str(operacao.get("id"))))
        return True

    def _gate(self, p, now) -> bool:
        """Executa a primeira peça oficialmente, sem inventar cotas de produto."""
        from mes.domain.first_piece import sector_has_setup
        try:
            gate = self.first_piece.avaliar_finalizacao(op=p.op, setor=p.setor, operacao=p.operacao)
            if not gate.aplicavel or gate.liberado:
                p.primeira_peca = "liberada"
                return True
            if sector_has_setup(p.setor):
                if self._act(p, "Setup", extras={"tipo_setup": "Preparação da primeira peça (TESTE)"}):
                    p.estado, p.retornar_em = "setup", now + timedelta(minutes=self.rng.randint(8, 20))
                    p.pausa_inicio = now
                    p.primeira_peca = "checklist"
                    p.episodios += 1
                    return True
                p.primeira_peca = "bloqueada"
                return False
            produzido = self.first_piece.registrar_producao(
                op=p.op, setor=p.setor, recurso=p.codigo, operacao=p.operacao)
            if not produzido.ok:
                p.bloqueio = produzido.code
                p.primeira_peca = "bloqueada"
                return False
            inspecao = self.first_piece.inspecionar(
                op=p.op, setor=p.setor, recurso=p.codigo, operacao=p.operacao,
                resultado="CONFORME", observacao="Inspeção simulada apenas no banco TESTE")
            p.primeira_peca = "liberada" if inspecao.ok else "bloqueada"
            if not inspecao.ok:
                p.bloqueio = inspecao.code
            else:
                LOG.info("Primeira peça conforme: %s OP %s", p.codigo, p.op)
            return inspecao.ok
        except Exception:
            LOG.exception("Falha na primeira peça recurso=%s OP=%s", p.codigo, p.op)
            p.primeira_peca = "bloqueada"
            return False

    def _checklist(self, p) -> None:
        """Usa medidas nominais da ficha existente: sem template, não libera."""
        try:
            data = self.first_piece.checklist(setor=p.setor, operacao=p.operacao) or {}
            cotas = ((data.get("template") or {}).get("cotas") or [])
            measures = []
            for cota in cotas:
                padrao = str(cota.get("padrao") or "")
                match = re.search(r"[+-]?\d+(?:[.,]\d+)?", padrao)
                if not match:
                    p.bloqueio = "Cota nominal não numérica: checklist requer revisão"
                    p.primeira_peca = "bloqueada"
                    return
                measures.append({"sequencia": int(cota["sequencia"]),
                                 "medida": match.group().replace(",", ".")})
            if not measures:
                p.bloqueio = "Sem template de qualidade do produto: não inventar cotas"
                p.primeira_peca = "bloqueada"
                return
            result = self.first_piece.registrar_checklist(
                op=p.op, setor=p.setor, recurso=p.codigo, operacao=p.operacao,
                medidas=measures, observacao="Medição nominal simulada em ambiente TESTE")
            p.primeira_peca = "liberada" if result.ok else "bloqueada"
            if not result.ok:
                p.bloqueio = result.code
            else:
                LOG.info("Checklist da primeira peça aprovado: %s OP %s", p.codigo, p.op)
        except Exception:
            LOG.exception("Falha no checklist recurso=%s OP=%s", p.codigo, p.op)
            p.primeira_peca = "bloqueada"

    def interrupt(self, p, now, kind):
        if kind == "setup":
            from mes.domain.first_piece import sector_has_setup
            if not sector_has_setup(p.setor):
                return False
            if not self._act(p, "Setup", extras={"tipo_setup": "Ajuste de ferramental (simulacao TESTE)"}):
                return False
            p.estado, p.retornar_em = "setup", now + timedelta(minutes=self.rng.randint(7, 25))
        else:
            planned = kind == "parada_planejada"
            reason = self._reason(p.setor, planned)
            if reason is None:
                return False
            if not self._act(p, "Parada", extras={"motivo_codigo": reason["codigo"],
                        "comentario": "Simulação industrial no banco TESTE; sem ocorrência física."}):
                return False
            p.estado, p.retornar_em = "parada", now + timedelta(minutes=self.rng.randint(8, 32) if planned else self.rng.randint(18, 55))
        p.episodios += 1
        p.pausa_inicio = now
        return True

    def progress(self, p, now):
        if p.estado in ("setup", "parada"):
            if now >= p.retornar_em:
                if p.estado == "setup" and p.primeira_peca == "checklist":
                    self._checklist(p)
                verb = "Retornar" if p.estado == "setup" else "Retomar"
                if self._act(p, verb):
                    paused = (now - p.pausa_inicio).total_seconds() if p.pausa_inicio else 0
                    p.pausado_segundos += max(0, paused)
                    p.fim_previsto += timedelta(seconds=max(0, paused))
                    p.pausa_inicio = None
                    p.estado = "producao"
                    p.proximo_evento = now + timedelta(minutes=self.rng.randint(10, 22))
                    p.retornar_em = None
                else:
                    p.retornar_em = now + timedelta(minutes=5)
            return
        if p.estado != "producao":
            return
        # Primeira peça passa pelo gate oficial antes dos eventos aleatórios.
        if p.primeira_peca == "pendente" and now >= p.proximo_evento:
            self._gate(p, now)
            p.proximo_evento = now + timedelta(minutes=self.rng.randint(8, 18))
            return
        # Primeiro apontamento validado tem parada cedo, os demais variam organicamente.
        if now >= p.proximo_evento:
            options = ["parada_nao_planejada", "parada_planejada", "setup", "nenhum"]
            weights = [0.38, 0.14, 0.23, 0.25]
            # A primeira parada não planejada é garantida sem pular regras do MES.
            choice = "parada_nao_planejada" if self.total["parada"] == 0 else self.rng.choices(options, weights=weights)[0]
            if choice != "nenhum" and self.interrupt(p, now, choice):
                return
            p.proximo_evento = now + timedelta(minutes=self.rng.randint(8, 20))
        if now < p.fim_previsto:
            return
        # Fecha somente depois do tempo executado. Quantidade deriva do tempo padrão real.
        planned = int(p.operacao.get("quantidade_planejada") or p.operacao.get("quantidade") or 0)
        already = int(p.operacao.get("quantidade_boa_registrada") or 0)
        unit = float(p.operacao.get("tempo_medio_segundos") or 0)
        elapsed = max(0, (now - p.inicio).total_seconds() - p.pausado_segundos)
        qty = min(max(0, planned - already), int(elapsed / unit)) if unit > 0 else 0
        if qty < planned - already:
            p.fim_previsto = now + timedelta(minutes=10)
            return
        if qty < 1:
            p.fim_previsto = now + timedelta(minutes=10)
            return
        if self._act(p, "Finalizado", extras={"pecas_boas": qty}):
            p.estado = "ocioso"
            p.op, p.produto, p.operacao = "", "", {}
            p.inicio, p.fim_previsto, p.proximo_evento = None, None, None
            p.pausa_inicio, p.pausado_segundos = None, 0
            p.primeira_peca = "pendente"
        else:
            # Primeira peça/qualidade pode bloquear: NUNCA burlar o gate.
            p.fim_previsto = now + timedelta(minutes=15)

    def write_status(self):
        body = {"at": instant().isoformat(), "end_at": self.end_at.isoformat(),
                "resources": len(self.postos), "coverage": sum(p.executou for p in self.postos),
                "simultaneous": self._active(), "totals": self.total,
                "stations": [{"resource": p.codigo, "sector": p.setor, "state": p.estado,
                              "op": p.op or None, "product": p.produto or None,
                              "ever_started": p.executou, "first_piece": p.primeira_peca,
                              "reason": p.bloqueio or None,
                              "episodes": p.episodios} for p in self.postos]}
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.status_path.with_suffix(".tmp")
        temp.write_text(json.dumps(body, indent=2, ensure_ascii=False, default=str), encoding="utf8")
        temp.replace(self.status_path)

    def loop(self):
        self.discover()
        if self.max_active == 0:
            # Capacidade estimada para rodízio ao longo do turno (não liga todos juntos).
            self.max_active = min(len(self.postos), max(2, math.ceil(len(self.postos) * 150 / (self.hours * 60))))
        LOG.info("Começando turno de %.2f horas; concorrência %d; relógio 1:1", self.hours, self.max_active)
        while not self.stop and instant() < self.end_at:
            now = instant()
            for p in self.postos:
                if p.estado != "ocioso":
                    self.progress(p, now)
            # Prioridade: primeiro dar oportunidade a todos, depois rodízio normal.
            if self._active() < self.max_active and (now - self.last_launch).total_seconds() >= 25:
                candidates = [p for p in self.postos if p.estado == "ocioso"]
                candidates.sort(key=lambda p: (p.executou, p.falhas, self.rng.random()))
                for p in candidates:
                    if self.start(p, now):
                        self.last_launch = now
                        break
                else:
                    self.last_launch = now
            self.write_status()
            time.sleep(self.tick)
        self.write_status()
        LOG.info("Turno encerrado/interrompido: cobertura=%d/%d, eventos=%s",
                 sum(p.executou for p in self.postos), len(self.postos), self.total)


def main():
    ap = argparse.ArgumentParser(description="Fábrica simulada TESTE 1:1. Não inicia o Andon.")
    ap.add_argument("--hours", type=float, default=8)
    ap.add_argument("--max-active", type=int, default=0, help="0=automático, escalonado")
    ap.add_argument("--seed", type=int, default=20261009)
    ap.add_argument("--tick", type=float, default=5)
    ap.add_argument("--badge", default=os.getenv("SIM_TEST_BADGE", ""))
    ap.add_argument("--expected-db", default="gestor_pecas_test")
    ap.add_argument("--status", action="store_true", help="Mostra status do turno atual sem conexão")
    ap.add_argument("--run", action="store_true", help="Autoriza apontamentos SOMENTE no banco TESTE")
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    state_dir = root / "simulation_runs" / "fabrica_turno_real"
    path = state_dir / "status.json"
    if args.status:
        print(path.read_text(encoding="utf8") if path.exists() else "Nenhuma execução registrada")
        return 0
    if args.hours <= 0 or args.max_active < 0 or args.tick < 1:
        ap.error("hours deve ser positivo, max-active >= 0 e tick >= 1")
    state_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(state_dir / "eventos.log", encoding="utf8")])
    from dotenv import load_dotenv
    load_dotenv(root / ".env", override=False)
    dsn = os.getenv("TEST_DATABASE_URL", "")
    if not dsn:
        raise RuntimeError("TEST_DATABASE_URL não definida")
    proof_test_db(dsn, args.expected_db, os.getenv("DATABASE_URL", ""))
    if not args.run:
        LOG.info("Pré-checagem aprovada. Use --run para iniciar de fato.")
        return 0
    # Impede envio de fatos simulados ao Protheus mesmo quando .env herdou integrações.
    from app.database import Database
    from app.database.config import PostgresConfig
    from mes.integrations.totvs.outbound_enqueue import OutboundEnqueueConfig
    db = Database(config=PostgresConfig(dsn, max_pool_size=3), auto_migrate=False,
                  totvs_outbox_config=OutboundEnqueueConfig(enabled=False))
    sim = Simulador(db, seed=args.seed, hours=args.hours, max_active=args.max_active,
                    badge=args.badge, tick=args.tick, log_path=state_dir / "eventos.log", status_path=path)
    try:
        sim.lock(dsn)
        signal.signal(signal.SIGINT, lambda *_: setattr(sim, "stop", True))
        signal.signal(signal.SIGTERM, lambda *_: setattr(sim, "stop", True))
        sim.loop()
    finally:
        if sim.advisory is not None:
            sim.advisory.close()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
