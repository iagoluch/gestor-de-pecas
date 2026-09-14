"""Homologação REAL da Etapa 6.2 — a executar quando a TI publicar o endpoint.

Diferente de `homologar_totvs_op_sob_demanda_etapa61.py`, que replica localmente
uma mensagem já capturada, este roteiro fala com o **Protheus de verdade**: o
endpoint `GESTORPECASPO` gera o `ProductionOrder` na hora, a partir da SC2.

Uso::

    .venv/Scripts/python.exe scripts/homologar_totvs_op_sob_demanda_etapa62.py \
        --endpoint https://<host>:1467/rest/gestorpecas/v1/production-order \
        --op <OP que existe no TOTVS TESTE e NÃO existe no Gestor TESTE>

Credenciais saem do `.env` (`GESTOR_TOTVS_OP_PULL_USERNAME`/`..._PASSWORD`) e
nunca são impressas. Recusa qualquer banco que não seja `gestor_pecas_test`.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
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


EXPECTED_DATABASE = "gestor_pecas_test"
OP_INEXISTENTE = "ZZ00000ZZ99"


def _guard(dsn: str) -> str:
    name = str(psycopg.conninfo.conninfo_to_dict(dsn).get("dbname") or "")
    if name != EXPECTED_DATABASE:
        raise SystemExit(f"RECUSADO: alvo {name!r}; só {EXPECTED_DATABASE}.")
    return name


def _build(db, endpoint, company, branch, timeout):
    resolver = TotvsResourceResolver(
        known_resource_codes=db.listar_codigos_recursos_totvs(),
        known_resource_sectors=db.listar_setores_recursos_totvs(),
    )
    gateway = ProtheusOnDemandRequestGateway(
        OnDemandGatewayConfig(
            endpoint=endpoint,
            delivery=DELIVERY_INLINE,
            timeout_seconds=timeout,
            username=os.environ.get("GESTOR_TOTVS_OP_PULL_USERNAME") or None,
            password=os.environ.get("GESTOR_TOTVS_OP_PULL_PASSWORD") or None,
            verify_tls=str(os.environ.get("GESTOR_TOTVS_OP_PULL_VERIFY_TLS") or "1")
            not in {"0", "false", "False", "no"},
        )
    )
    return ProductionOrderOnDemandSyncService(
        db,
        ingestion_service=TotvsProductionOrderIngestionService(
            db,
            enabled=True,
            parser=TotvsMessageParser(),
            mapper=TotvsProductionOrderMapper(resolver),
        ),
        gateway=gateway,
        company_id=company,
        branch_id=branch,
        timeout_seconds=timeout + 10,
        poll_interval_seconds=0.2,
        negative_ttl_seconds=30,
    )


def _rows(db, query, params=()):
    with db.connection() as connection, connection.cursor() as cursor:
        cursor.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--op", required=True)
    parser.add_argument("--company", default=os.environ.get("GESTOR_TOTVS_OP_PULL_COMPANY_ID", "01"))
    parser.add_argument("--branch", default=os.environ.get("GESTOR_TOTVS_OP_PULL_BRANCH_ID", "010004"))
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    op = str(args.op).strip().upper()
    dsn = os.environ["TEST_DATABASE_URL"]
    print(f"Banco alvo: {_guard(dsn)}")
    print(f"Endpoint  : {args.endpoint}")
    print(f"OP        : {op}  ({args.company}/{args.branch})")

    db = Database(dsn)
    try:
        service = _build(db, args.endpoint, args.company, args.branch, args.timeout)

        print("\n[1] consulta local antes")
        assert service.lookup_local(op) is None, "a OP não pode existir localmente antes"
        print("    MISS confirmado")

        print("[2] solicitação ao Protheus")
        outcome = service.sync_production_order_on_demand(op)
        print(f"    status={outcome.status} tempo={outcome.elapsed_seconds:.3f}s")
        if outcome.status != "sincronizada":
            print(f"    FALHOU: {outcome.detail}")
            return 1

        print("[3] mensagem recebida")
        inbox = _rows(
            db,
            """
            SELECT payload_raw, status, result_action, external_id
              FROM totvs_integration_messages
             WHERE external_id = %s ORDER BY id DESC LIMIT 1
            """,
            (f"{args.company}|{args.branch}|{op}",),
        )
        assert inbox, "a mensagem precisa estar na inbox canônica"
        raw = inbox[0]["payload_raw"]
        print(f"    inbox status={inbox[0]['status']} action={inbox[0]['result_action']}")
        for campo, esperado in (
            ("Transaction", "ProductionOrder"),
            ("SourceApplication", "SIGAPCP"),
            ("Type", "BusinessMessage"),
            ("CompanyId", args.company),
            ("BranchId", args.branch),
        ):
            achado = re.search(rf"<{campo}>(.*?)</{campo}>", raw)
            valor = achado.group(1) if achado else None
            marca = "OK " if valor == esperado else "!! "
            print(f"    {marca}{campo}: {valor} (esperado {esperado})")
            assert valor == esperado, f"{campo} divergente"
        assert 'version="2.004"' in raw, "versão da mensagem divergente"

        print("[4] OP canônica")
        header = _rows(db, "SELECT * FROM catalogo_pcp_ops WHERE codigo_op=%s", (op,))
        assert len(header) == 1
        h = header[0]
        print(f"    produto={h['produto_codigo']} '{h['produto_descricao']}' "
              f"qtd={h['quantidade']} unique_id={h['totvs_unique_id']}")
        assert h["totvs_unique_id"] == f"{args.company}|{args.branch}|{op}"

        print("[5] roteiro projetado")
        ops = _rows(
            db,
            """
            SELECT numero_operacao, descricao_operacao, codigo_recurso, tipo_setor,
                   marco_terminal, ativo, totvs_activity_id
              FROM catalogo_operacoes_op WHERE codigo_op=%s ORDER BY ordem, id
            """,
            (op,),
        )
        for row in ops:
            print(f"    {row['numero_operacao']:>3} {str(row['descricao_operacao'] or ''):<14}"
                  f" recurso={str(row['codigo_recurso'] or '-'):<8}"
                  f" setor={str(row['tipo_setor'] or '-'):<10}"
                  f" terminal={row['marco_terminal']} ativo={row['ativo']}"
                  f" activity_id={row['totvs_activity_id']}")
        assert ops, "o roteiro não pode ficar vazio"

        print("[6] marco terminal")
        terminal = [r for r in ops if r["marco_terminal"]]
        if terminal:
            for row in terminal:
                assert not row["ativo"], "o marco terminal não pode ficar ativo"
                assert row["tipo_setor"] is None, "o marco terminal não tem setor"
            print(f"    {len(terminal)} marco(s), inativo(s) e sem setor")
        else:
            print("    AVISO: esta OP não trouxe operação terminal; use uma OP com 99/ALMOX4")

        print("[7] operador vê apenas operações apontáveis")
        visiveis = db.listar_operacoes_para_op(op)
        print(f"    {len(visiveis)} operação(ões): "
              f"{[(r['numero_operacao'], r['codigo_recurso']) for r in visiveis]}")
        assert all(not r.get("marco_terminal") for r in visiveis)

        print("[8] ingestão não gerou outbound")
        outbox = _rows(db, "SELECT id FROM totvs_outbox WHERE production_order=%s", (op,))
        print(f"    itens de outbox = {len(outbox)}")
        assert not outbox

        print("[9] segunda busca")
        segunda = service.sync_production_order_on_demand(op)
        print(f"    status={segunda.status}")
        assert segunda.status == "local", "a segunda busca precisa ser local"

        print("[10] OP inexistente no Protheus")
        ausente = service.sync_production_order_on_demand(OP_INEXISTENTE)
        print(f"    status={ausente.status}")
        assert ausente.status == "nao_encontrada"
        assert not _rows(
            db, "SELECT codigo_op FROM catalogo_pcp_ops WHERE codigo_op=%s", (OP_INEXISTENTE,)
        )

        print("[11] concorrência real contra o Protheus")
        with db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM catalogo_operacoes_op WHERE codigo_op=%s", (op,))
            cursor.execute("DELETE FROM catalogo_pcp_ops WHERE codigo_op=%s", (op,))
            cursor.execute("DELETE FROM totvs_op_sync_requests WHERE codigo_op=%s", (op,))
        barrier = threading.Barrier(2)
        resultados = []

        def worker():
            local_db = Database(dsn, auto_migrate=False)
            try:
                svc = _build(local_db, args.endpoint, args.company, args.branch, args.timeout)
                barrier.wait(timeout=20)
                resultados.append(svc.sync_production_order_on_demand(op))
            finally:
                local_db.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)
        print(f"    resultados={[r.status for r in resultados]}")
        assert len(resultados) == 2 and all(r.status == "sincronizada" for r in resultados)
        assert len(_rows(db, "SELECT codigo_op FROM catalogo_pcp_ops WHERE codigo_op=%s", (op,))) == 1
        terminais = _rows(
            db,
            "SELECT id FROM catalogo_operacoes_op WHERE codigo_op=%s AND marco_terminal=TRUE",
            (op,),
        )
        print(f"    OPs=1 marcos_terminais={len(terminais)}")
        assert len(terminais) <= 1

        print("\nHOMOLOGAÇÃO ETAPA 6.2: OK")
        print("Confira no Protheus que a OP permanece inalterada "
              "(C2_QUJE, C2_DATRF, legenda, SH6/SD3).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
