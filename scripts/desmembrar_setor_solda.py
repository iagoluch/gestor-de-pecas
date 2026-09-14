"""Desmembramento do setor Solda em cinco setores reais (Wave 6F).

Decisão do usuário em 14/09/2026: o setor único "Solda", com dez estações
genéricas, passa a ser cinco setores distintos, cada um com ``tipo_setor``
próprio, elegibilidade própria e contas próprias:

* **Solda Aço** — sucessor direto da Solda de hoje, dez estações;
* **Solda Alumínio** — seis estações, ainda sem recurso classificado no catálogo;
* **Solda Robô** — ``ROBO P`` e ``ROBO S``;
* **Proj. Ferramentaria** — ``DISPEX``, ``DISPG``, ``SERVGE`` e ``DISPOS``;
* **Protótipo** — ``PREMTG`` e ``SOLDA4``.

O que o script faz, tudo idempotente:

1. reclassifica ``catalogo_recursos_pcfactory.tipo_setor`` pelos códigos acima
   e move o restante da antiga Solda para "Solda Aço";
2. realinha o ``tipo_setor`` do roteiro (``catalogo_operacoes_op``) ao setor do
   recurso — é a mesma derivação que a ingestão do TOTVS faz, e sem ela a
   operação continuaria apontando para um setor que não existe mais;
3. renomeia "Solda" para "Solda Aço" nas tabelas operacionais e de qualidade.
   Não é reatribuição: o setor foi renomeado, e quem executou aquelas
   operações foi o posto que hoje se chama Solda Aço;
4. garante uma conta por estação (login = nível), com a senha informada.

Regras de segurança: opera somente no banco de TESTE (``Database`` recusa alvo
sem "test" no nome) e nunca apaga linha.

Uso:

```
python scripts/desmembrar_setor_solda.py --dry-run
python scripts/desmembrar_setor_solda.py --senha 1234
```

TODO(lançamento em produção): a senha aplicada aqui é de ambiente de TESTE. As
senhas reais das contas criadas — ``estacao1aco``..``estacao10aco``,
``estacao1alu``..``estacao6alu``, ``robo1``, ``projetos`` e ``prototipo`` —
precisam ser definidas manualmente no lançamento. O Dev Observatory não possui
hoje um mecanismo de pendência/card onde registrar esse lembrete.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env", override=False)

from app.core.operator_sectors import (  # noqa: E402
    WELDING_OPERATOR_PROFILES,
    WELDING_STEEL_SECTOR,
)
from app.database import Database  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


LEGACY_SECTOR = "Solda"

#: Recursos que saem da antiga Solda (ou de ``tipo_setor`` nulo) para um setor
#: novo. Lista fechada com o usuário; o restante da antiga Solda vira Solda Aço.
RECLASSIFICACAO = {
    "Solda Robô": ("ROBO P", "ROBO S"),
    "Proj. Ferramentaria": ("DISPEX", "DISPG", "SERVGE", "DISPOS"),
    "Protótipo": ("PREMTG", "SOLDA4"),
}

#: Tabelas onde o nome do setor foi gravado junto do registro operacional.
SECTOR_COLUMNS = (
    ("alertas_internos", "tipo_setor"),
    ("apontamentos_operacionais", "tipo_setor"),
    ("apontamentos_operacionais", "setor_roteiro"),
    ("eventos_apontamento_operador", "setor_roteiro"),
    ("eventos_estado_recurso", "tipo_setor"),
    ("eventos_quantidade_producao", "tipo_setor"),
    ("participacoes_operador", "tipo_setor"),
    ("pausas_automaticas_setor", "tipo_setor"),
    ("qualidade_inspecoes", "tipo_setor"),
    ("qualidade_primeira_peca", "tipo_setor"),
    ("qualidade_primeira_peca_autorizacoes", "tipo_setor"),
    ("qualidade_rnc", "tipo_setor"),
    ("sessoes_recurso", "tipo_setor"),
)


def reclassificar_catalogo(cursor, *, dry_run):
    """Move os códigos acordados e leva o resto da antiga Solda para Solda Aço."""

    resultado = {}
    for setor, codigos in RECLASSIFICACAO.items():
        alvo = [codigo.upper() for codigo in codigos]
        cursor.execute(
            "SELECT codigo FROM catalogo_recursos_pcfactory "
            "WHERE UPPER(BTRIM(codigo)) = ANY(%s) AND COALESCE(tipo_setor, '') <> %s",
            (alvo, setor),
        )
        pendentes = [row["codigo"] for row in cursor.fetchall()]
        resultado[setor] = pendentes
        if pendentes and not dry_run:
            cursor.execute(
                "UPDATE catalogo_recursos_pcfactory SET tipo_setor = %s "
                "WHERE UPPER(BTRIM(codigo)) = ANY(%s)",
                (setor, alvo),
            )
    cursor.execute(
        "SELECT codigo FROM catalogo_recursos_pcfactory WHERE tipo_setor = %s",
        (LEGACY_SECTOR,),
    )
    remanescentes = [row["codigo"] for row in cursor.fetchall()]
    resultado[WELDING_STEEL_SECTOR] = remanescentes
    if remanescentes and not dry_run:
        cursor.execute(
            "UPDATE catalogo_recursos_pcfactory SET tipo_setor = %s WHERE tipo_setor = %s",
            (WELDING_STEEL_SECTOR, LEGACY_SECTOR),
        )
    return resultado


def realinhar_roteiro(cursor, *, dry_run):
    """O setor da operação do roteiro é o setor do recurso — nada é inventado."""

    sql_select = """
        SELECT o.id
        FROM catalogo_operacoes_op o
        JOIN catalogo_recursos_pcfactory r
          ON UPPER(BTRIM(r.codigo)) = UPPER(BTRIM(o.codigo_recurso))
        WHERE o.tipo_setor = %s
          AND NULLIF(BTRIM(r.tipo_setor), '') IS NOT NULL
          AND r.tipo_setor <> o.tipo_setor
    """
    cursor.execute(sql_select, (LEGACY_SECTOR,))
    pendentes = len(cursor.fetchall())
    if pendentes and not dry_run:
        cursor.execute(
            """
            UPDATE catalogo_operacoes_op o
            SET tipo_setor = r.tipo_setor
            FROM catalogo_recursos_pcfactory r
            WHERE UPPER(BTRIM(r.codigo)) = UPPER(BTRIM(o.codigo_recurso))
              AND o.tipo_setor = %s
              AND NULLIF(BTRIM(r.tipo_setor), '') IS NOT NULL
              AND r.tipo_setor <> o.tipo_setor
            """,
            (LEGACY_SECTOR,),
        )
    return pendentes


def renomear_historico(cursor, *, dry_run):
    """"Solda" era o nome do setor que hoje se chama "Solda Aço"."""

    totais = {}
    for tabela, coluna in SECTOR_COLUMNS:
        cursor.execute(
            f"SELECT count(*) AS total FROM {tabela} WHERE {coluna} = %s",
            (LEGACY_SECTOR,),
        )
        pendentes = int(cursor.fetchone()["total"])
        if not pendentes:
            continue
        totais[f"{tabela}.{coluna}"] = pendentes
        if not dry_run:
            cursor.execute(
                f"UPDATE {tabela} SET {coluna} = %s WHERE {coluna} = %s",
                (WELDING_STEEL_SECTOR, LEGACY_SECTOR),
            )
    return totais


def garantir_contas(db, senha, *, dry_run):
    """Uma conta por estação: o posto vem do login, não de uma escolha na tela."""

    criadas = []
    for profile in WELDING_OPERATOR_PROFILES:
        if db.usuario_existe(profile.level):
            continue
        criadas.append(profile.level)
        if not dry_run:
            db.criar_usuario(profile.level, senha, profile.level)
    return criadas


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Desmembra o setor Solda (Wave 6F).")
    parser.add_argument("--dry-run", action="store_true", help="relata sem gravar")
    parser.add_argument(
        "--senha",
        default="1234",
        help="senha das contas novas no ambiente de TESTE (padrão: 1234)",
    )
    args = parser.parse_args(argv)

    db = Database()
    alvo = str((db.safe_target or {}).get("dbname") or "")
    prefixo = "[dry-run] " if args.dry_run else ""
    print(f"banco: {alvo}")
    try:
        with db.connection() as connection, connection.cursor() as cursor:
            catalogo = reclassificar_catalogo(cursor, dry_run=args.dry_run)
            roteiro = realinhar_roteiro(cursor, dry_run=args.dry_run)
            historico = renomear_historico(cursor, dry_run=args.dry_run)
        for setor, codigos in catalogo.items():
            print(f"{prefixo}catálogo → {setor}: {len(codigos)} recurso(s) {sorted(codigos)}")
        print(f"{prefixo}roteiro realinhado ao setor do recurso: {roteiro} operação(ões)")
        for chave, total in sorted(historico.items()):
            print(f"{prefixo}renomeado {LEGACY_SECTOR} → {WELDING_STEEL_SECTOR} em {chave}: {total}")
        criadas = garantir_contas(db, args.senha, dry_run=args.dry_run)
        print(f"{prefixo}contas criadas: {len(criadas)} {criadas}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
