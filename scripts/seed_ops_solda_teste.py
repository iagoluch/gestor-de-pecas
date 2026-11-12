"""Cria recursos de teste da frente de Solda e 10 OPs para cada um (banco TESTE).

Solda Aço (9 estações) e Solda Alumínio (4) não têm recurso no cadastro
corporativo; aqui nascem recursos de teste SOLDAA1..9 e SOLDAL1..4 (prefixo
``ZZ``-free, fonte 'seed_ops_solda_teste'). ROBO P/ROBO S já existem.
OPs: ``ZZSOL<recurso><nn>``, idempotente (reexecutar atualiza, não duplica).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import seed_cenario_gui as s  # noqa: E402
from app.database.config import load_postgres_config  # noqa: E402
from app.database.database import Database  # noqa: E402

RECURSOS = (
    [(f"SOLDAA{n}", f"SOLDA ACO ESTACAO {n} (TESTE)", "Solda Aço") for n in range(1, 10)]
    + [(f"SOLDAL{n}", f"SOLDA ALUMINIO ESTACAO {n} (TESTE)", "Solda Alumínio") for n in range(1, 5)]
    + [("ROBO P", None, "Solda Robô"), ("ROBO S", None, "Solda Robô")]
)
POR_RECURSO = 10


def montar(agora: datetime) -> list[s.OrdemProducao]:
    ordens, seq = [], 0
    for i, (codigo, _nome, setor) in enumerate(RECURSOS):
        sufixo = codigo.replace(" ", "")
        for n in range(1, POR_RECURSO + 1):
            pc, pd = s.PRODUTOS[seq % len(s.PRODUTOS)]
            seq += 1
            ini = agora.replace(minute=0, second=0, microsecond=0) + timedelta(hours=n)
            etapa = s.Etapa(
                numero_operacao="10", ordem=2, codigo_recurso=codigo,
                descricao_operacao="SOLDA", tipo_setor=setor, centro_trabalho="SOLDA",
                codigo_maquina=codigo, tempo_medio_segundos=600.0, ativo=True,
                marco_terminal=False, inspecao_qualidade=False,
                totvs_activity_id=str(950_000 + i * 100 + n * 10 + 2),
            )
            fim = [
                s.Etapa("20", 3, "INSPEC", "INSPECAO", None, "CALDER", "INSPEC", None,
                        False, False, True, str(950_000 + i * 100 + n * 10 + 3)),
                s.Etapa("99", 4, "ALMOX4", "FINALIZADA", None, "ALMOX4", "ALMOX4", None,
                        False, True, False, str(950_000 + i * 100 + n * 10 + 4)),
            ]
            ordens.append(s.OrdemProducao(
                codigo=f"ZZSOL{sufixo}{n:02d}", produto_codigo=pc, produto_descricao=pd,
                quantidade=n * 2, prioridade=(n % 5) + 1, inicio_planejado=ini,
                fim_planejado=ini + timedelta(hours=6), prazo_entrega=ini + timedelta(days=3),
                etapas=(etapa, *fim),
            ))
    return ordens


def main() -> int:
    agora = datetime.now().replace(microsecond=0)
    config = load_postgres_config(testing=True)
    if "test" not in str(config.safe_target.get("dbname", "")).casefold():
        raise RuntimeError("Recusado: não é banco de teste.")
    db = Database(config=config)
    try:
        with db.connection() as con, con.cursor() as cur:
            for codigo, nome, setor in RECURSOS:
                if nome is None:
                    continue
                cur.execute(
                    """INSERT INTO catalogo_recursos_pcfactory
                       (codigo, nome, tipo_setor, habilitado, fonte, sincronizado_em)
                       VALUES (%s,%s,%s,TRUE,'seed_ops_solda_teste',%s)
                       ON CONFLICT (codigo) DO UPDATE SET nome=EXCLUDED.nome,
                       tipo_setor=EXCLUDED.tipo_setor, habilitado=TRUE""",
                    (codigo, nome, setor, agora),
                )
            ordens = montar(agora)
            s._gravar_ordens(cur, s.Cenario(ordens=ordens), agora)
            cur.execute(
                "SELECT count(*) FROM catalogo_pcp_ops WHERE codigo_op LIKE 'ZZSOL%'"
            )
            print("OPs ZZSOL no banco:", cur.fetchone())
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
