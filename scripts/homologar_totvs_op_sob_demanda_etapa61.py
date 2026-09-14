"""Homologação da Etapa 6.1 — busca de OP sob demanda, no banco TESTE real.

O que este roteiro prova, ponta a ponta, contra `gestor_pecas_test`:

1. consulta local MISS de uma OP real que existe no Protheus e não no Gestor;
2. solicitação HTTP real (não dublê em memória) pela porta de solicitação;
3. a mensagem devolvida é o `ProductionOrder` **real gerado pelo Protheus**
   (`Product name="MATA650" version="12.1.2510"`, `SourceApplication=SIGAPCP`),
   capturada do PCPA111 — nenhum campo é fabricado aqui;
4. a mensagem entra pelo MESMO pipeline canônico do push;
5. OP, roteiro, ActivityCode/ActivityID/MachineCode e marco terminal aparecem;
6. a segunda consulta é local e não gera nova comunicação;
7. OP inexistente, indisponibilidade e concorrência se comportam como exigido.

**Limite honesto e deliberado**: o Protheus deste ambiente NÃO possui mecanismo
suportado para o Gestor solicitar uma OP (ver
`docs/INTEGRACAO_TOTVS_OP_SOB_DEMANDA_ETAPA61.md`). O responder local abaixo
ocupa exatamente o lugar da rotina que a TI/TOTVS precisa publicar, com o mesmo
contrato HTTP; ele **reproduz** uma mensagem real do ERP, não inventa uma.

Segurança: recusa qualquer alvo que não seja `gestor_pecas_test`.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import sys
import threading

import psycopg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app.database.database import Database  # noqa: E402
from mes.integrations.totvs.mapper import TotvsProductionOrderMapper  # noqa: E402
from mes.integrations.totvs.on_demand import (  # noqa: E402
    DELIVERY_INLINE,
    ProductionOrderOnDemandSyncService,
)
from mes.integrations.totvs.on_demand_gateway import (  # noqa: E402
    OnDemandGatewayConfig,
    ProtheusOnDemandRequestGateway,
)
from mes.integrations.totvs.parser import TotvsMessageParser  # noqa: E402
from mes.integrations.totvs.resource_mapping import TotvsResourceResolver  # noqa: E402
from mes.integrations.totvs.service import TotvsProductionOrderIngestionService  # noqa: E402


REAL_MESSAGE = (
    ROOT
    / "integracao_totvs_referencia"
    / "mensagens_teste"
    / "ok_productionorder_20260821103018_1079689c001 1.xml"
)
OP = "1079689C001"
OP_INEXISTENTE = "ZZ00000ZZ99"
EXPECTED_DATABASE = "gestor_pecas_test"


def _guard(dsn: str) -> str:
    info = psycopg.conninfo.conninfo_to_dict(dsn)
    name = str(info.get("dbname") or "")
    if name != EXPECTED_DATABASE:
        raise SystemExit(f"RECUSADO: alvo {name!r}; esta homologação só roda em {EXPECTED_DATABASE}.")
    return name


class _ProtheusStandIn(BaseHTTPRequestHandler):
    """Ocupa o lugar da rotina Protheus. Só replica; não monta ProductionOrder."""

    payload_xml = ""
    known = {OP}
    mode = "ok"
    calls: list[str] = []

    def do_POST(self):  # noqa: N802 - assinatura da stdlib
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        number = str(body.get("number") or "")
        type(self).calls.append(number)
        if type(self).mode == "offline":
            self.close_connection = True
            return
        if number not in type(self).known:
            data = json.dumps({"status": "notFound"}).encode("utf-8")
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        data = type(self).payload_xml.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # silencia o log da stdlib
        return


def _build(db, endpoint):
    resolver = TotvsResourceResolver(
        known_resource_codes=db.listar_codigos_recursos_totvs(),
        known_resource_sectors=db.listar_setores_recursos_totvs(),
    )
    ingestion = TotvsProductionOrderIngestionService(
        db,
        enabled=True,
        parser=TotvsMessageParser(),
        mapper=TotvsProductionOrderMapper(resolver),
    )
    gateway = ProtheusOnDemandRequestGateway(
        OnDemandGatewayConfig(endpoint=endpoint, delivery=DELIVERY_INLINE, timeout_seconds=15)
    )
    return ProductionOrderOnDemandSyncService(
        db,
        ingestion_service=ingestion,
        gateway=gateway,
        company_id="01",
        branch_id="010004",
        timeout_seconds=20,
        poll_interval_seconds=0.2,
        negative_ttl_seconds=30,
    )


def _rows(db, query, params=()):
    with db.connection() as connection, connection.cursor() as cursor:
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def main() -> int:
    dsn = os.environ["TEST_DATABASE_URL"]
    print(f"Banco alvo: {_guard(dsn)}")

    _ProtheusStandIn.payload_xml = REAL_MESSAGE.read_text(encoding="utf-8")
    server = HTTPServer(("127.0.0.1", 0), _ProtheusStandIn)
    endpoint = f"http://127.0.0.1:{server.server_address[1]}/op"
    threading.Thread(target=server.serve_forever, daemon=True).start()

    db = Database(dsn)
    try:
        service = _build(db, endpoint)

        print("\n[1] consulta local antes")
        antes = service.lookup_local(OP)
        print(f"    {OP} local = {antes}")
        assert antes is None, "a OP não pode existir localmente antes do teste"

        print("[2] solicitação sob demanda")
        outcome = service.sync_production_order_on_demand(OP)
        print(f"    status={outcome.status} requested={outcome.requested} "
              f"tempo={outcome.elapsed_seconds:.3f}s")
        assert outcome.status == "sincronizada", outcome

        print("[3] OP canônica")
        header = _rows(db, "SELECT * FROM catalogo_pcp_ops WHERE codigo_op=%s", (OP,))
        assert len(header) == 1
        h = header[0]
        print(f"    codigo_op={h['codigo_op']} produto={h['produto_codigo']} "
              f"qtd={h['quantidade']} unique_id={h['totvs_unique_id']}")

        print("[4] roteiro projetado")
        ops = _rows(
            db,
            """
            SELECT numero_operacao, descricao_operacao, codigo_recurso, tipo_setor,
                   marco_terminal, ativo, totvs_activity_id
              FROM catalogo_operacoes_op WHERE codigo_op=%s ORDER BY ordem, id
            """,
            (OP,),
        )
        for row in ops:
            print(
                f"    {row['numero_operacao']:>3} {str(row['descricao_operacao'] or ''):<14}"
                f" recurso={str(row['codigo_recurso'] or '-'):<8} setor={str(row['tipo_setor'] or '-'):<10}"
                f" terminal={row['marco_terminal']} ativo={row['ativo']}"
                f" activity_id={row['totvs_activity_id']}"
            )
        terminais = [row for row in ops if row["marco_terminal"]]
        assert terminais, "o marco terminal precisa existir"
        assert all(not row["ativo"] for row in terminais), "o marco terminal não pode ficar ativo"

        print("[5] ingestão não gera outbound")
        outbox = _rows(db, "SELECT id FROM totvs_outbox WHERE production_order=%s", (OP,))
        print(f"    itens de outbox = {len(outbox)}")
        assert not outbox

        print("[6] segunda busca")
        chamadas = len(_ProtheusStandIn.calls)
        segunda = service.sync_production_order_on_demand(OP)
        print(f"    status={segunda.status} novas_chamadas={len(_ProtheusStandIn.calls) - chamadas}")
        assert segunda.status == "local"
        assert len(_ProtheusStandIn.calls) == chamadas, "a segunda busca não pode chamar o ERP"

        print("[7] OP inexistente")
        ausente = service.sync_production_order_on_demand(OP_INEXISTENTE)
        print(f"    status={ausente.status}")
        assert ausente.status == "nao_encontrada"
        assert not _rows(db, "SELECT codigo_op FROM catalogo_pcp_ops WHERE codigo_op=%s", (OP_INEXISTENTE,))
        assert not _rows(db, "SELECT id FROM catalogo_operacoes_op WHERE codigo_op=%s", (OP_INEXISTENTE,))

        print("[8] cache negativo curto")
        chamadas = len(_ProtheusStandIn.calls)
        service.sync_production_order_on_demand(OP_INEXISTENTE)
        print(f"    novas chamadas ao ERP = {len(_ProtheusStandIn.calls) - chamadas}")
        assert len(_ProtheusStandIn.calls) == chamadas

        print("[9] mecanismo indisponível")
        _ProtheusStandIn.mode = "offline"
        offline_op = "1079689C002"
        indisponivel = service.sync_production_order_on_demand(offline_op)
        print(f"    status={indisponivel.status} detalhe={indisponivel.detail}")
        assert indisponivel.status == "indisponivel"
        assert not _rows(db, "SELECT codigo_op FROM catalogo_pcp_ops WHERE codigo_op=%s", (offline_op,))
        assert not _rows(db, "SELECT id FROM catalogo_operacoes_op WHERE codigo_op=%s", (offline_op,))
        _ProtheusStandIn.mode = "ok"

        print("[10] concorrência")
        with db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM catalogo_operacoes_op WHERE codigo_op=%s", (OP,))
            cursor.execute("DELETE FROM catalogo_pcp_ops WHERE codigo_op=%s", (OP,))
            cursor.execute("DELETE FROM totvs_op_sync_requests WHERE codigo_op=%s", (OP,))
            cursor.execute("DELETE FROM totvs_integration_messages")
        _ProtheusStandIn.calls.clear()
        barrier = threading.Barrier(2)
        resultados = []

        def worker():
            local_db = Database(dsn, auto_migrate=False)
            try:
                svc = _build(local_db, endpoint)
                barrier.wait(timeout=15)
                resultados.append(svc.sync_production_order_on_demand(OP))
            finally:
                local_db.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        print(f"    resultados={[r.status for r in resultados]} chamadas_ao_erp={len(_ProtheusStandIn.calls)}")
        assert len(resultados) == 2
        assert all(r.status == "sincronizada" for r in resultados)
        assert len(_ProtheusStandIn.calls) == 1, "só uma sincronização lógica é permitida"
        assert len(_rows(db, "SELECT codigo_op FROM catalogo_pcp_ops WHERE codigo_op=%s", (OP,))) == 1
        terminais = _rows(
            db,
            "SELECT id FROM catalogo_operacoes_op WHERE codigo_op=%s AND marco_terminal=TRUE",
            (OP,),
        )
        print(f"    OPs={1} marcos_terminais={len(terminais)}")
        assert len(terminais) == 1

        print("\nHOMOLOGAÇÃO ETAPA 6.1: OK")
        return 0
    finally:
        db.close()
        server.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
