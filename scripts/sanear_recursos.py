"""Saneamento do cadastro de recursos (Etapa 4C).

Classifica todo o catálogo de recursos, corrige apenas o que é **comprovável**
pelos próprios dados e imprime a matriz `RECURSO → SETOR → POSTO → ELEGÍVEL`.

Regras de segurança:

* só opera no banco de TESTE (`Database` já recusa alvo sem "test" no nome);
* nunca apaga linha e nunca toca em apontamento, evento ou histórico;
* consolidação de duplicidade exige prova: mesmo código ignorando caixa,
  **mesmo nome** e **zero uso** nas duas variantes;
* `tipo_setor` ausente não é preenchido por semelhança de nome — sem evidência,
  permanece ausente e vai para a lista de decisão humana.

Uso:

```
python scripts/sanear_recursos.py --dry-run     # só relata
python scripts/sanear_recursos.py               # aplica o comprovável
python scripts/sanear_recursos.py --matriz      # só a matriz de elegibilidade
```
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env", override=False)

from app.core.operator_sectors import OPERATOR_SECTORS  # noqa: E402
from app.core.resource_mapping import (  # noqa: E402
    OFFICIAL_RESOURCE_ALIASES,
    SECTOR_OWNED_RESOURCE_SECTORS,
    canonical_resource_code,
    station_matches_route,
)
from app.database import Database  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Fontes que representam massa de teste, não cadastro real da fábrica.
FIXTURE_SOURCES = {"planilha_teste_roteiro", "planilha_teste", "carga_teste_apontamento"}
REPORT_PATH = PROJECT_ROOT / "tests" / "etapa4c_recursos" / "saneamento_recursos.json"


def rows(db, sql, params=None):
    with db.connection() as connection, connection.cursor() as cursor:
        if params is None:
            cursor.execute(sql)
        else:
            cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def carregar_inventario(db):
    return rows(
        db,
        """
        SELECT r.codigo, r.nome, r.tipo_setor, r.habilitado, r.fonte, r.sincronizado_em,
               (SELECT COUNT(*) FROM catalogo_operacoes_op o
                 WHERE o.codigo_recurso = r.codigo) AS operacoes,
               (SELECT COUNT(DISTINCT o.codigo_op) FROM catalogo_operacoes_op o
                 WHERE o.codigo_recurso = r.codigo) AS ops,
               (SELECT COUNT(*) FROM apontamentos_operacionais a
                 WHERE a.codigo_recurso = r.codigo) AS apontamentos,
               (SELECT COUNT(*) FROM eventos_estado_recurso e
                 WHERE UPPER(e.recurso) = UPPER(r.codigo)) AS estados,
               EXISTS (SELECT 1 FROM catalogo_operacoes_op o
                        JOIN catalogo_pcp_ops p ON p.codigo_op = o.codigo_op
                       WHERE o.codigo_recurso = r.codigo
                         AND p.totvs_unique_id IS NOT NULL) AS usado_por_totvs
        FROM catalogo_recursos_pcfactory r
        ORDER BY r.codigo
        """,
    )


def classificar(inventario):
    """Cada recurso recebe todas as etiquetas que couberem."""

    por_caixa = defaultdict(list)
    por_nome = defaultdict(list)
    for item in inventario:
        por_caixa[str(item["codigo"]).strip().upper()].append(item)
        por_nome[str(item["nome"]).strip().upper()].append(item)

    postos_por_setor = {
        sector.name.casefold(): tuple(sector.resources) for sector in OPERATOR_SECTORS
    }

    classificado = []
    for item in inventario:
        etiquetas = []
        codigo = str(item["codigo"]).strip()
        variantes = por_caixa[codigo.upper()]
        if len(variantes) > 1:
            etiquetas.append("diferenca_apenas_de_capitalizacao")
        if str(item["fonte"] or "") in FIXTURE_SOURCES:
            etiquetas.append("ficticio_de_teste")
        if not str(item["tipo_setor"] or "").strip():
            etiquetas.append("sem_setor")
        if item["usado_por_totvs"]:
            etiquetas.append("usado_em_roteiro_totvs")
        usado = bool(item["operacoes"] or item["apontamentos"] or item["estados"])
        if not usado:
            etiquetas.append("sem_uso_identificado")

        setor = str(item["tipo_setor"] or "").strip()
        postos = postos_por_setor.get(setor.casefold(), ())
        elegiveis = [
            posto
            for posto in postos
            if station_matches_route(setor, posto, codigo, resource_sector=setor)
        ]
        if setor and not elegiveis:
            etiquetas.append("sem_posto_correspondente")
        if elegiveis and not etiquetas:
            etiquetas.append("canonico")
        elif elegiveis:
            etiquetas.append("com_posto")

        classificado.append(
            {
                **item,
                "sincronizado_em": str(item["sincronizado_em"]),
                "postos_elegiveis": elegiveis,
                "etiquetas": etiquetas,
            }
        )
    return classificado


def duplicidades_comprovadas(classificado):
    """Variantes que só diferem por caixa, com o mesmo nome e sem uso algum."""

    por_caixa = defaultdict(list)
    for item in classificado:
        por_caixa[str(item["codigo"]).strip().upper()].append(item)

    consolidar = []
    for chave, variantes in sorted(por_caixa.items()):
        if len(variantes) < 2:
            continue
        nomes = {str(item["nome"]).strip().upper() for item in variantes}
        usadas = [
            item for item in variantes
            if item["operacoes"] or item["apontamentos"] or item["estados"]
        ]
        if len(nomes) > 1 or usadas:
            # Nome diferente ou uso real: são recursos distintos ou existe
            # história atrelada. Vira decisão humana, não consolidação.
            consolidar.append({"chave": chave, "acao": "decisao_humana", "variantes": variantes})
            continue
        # A variante canônica é a mais recente do PC Factory; as demais são
        # resíduo de exportação antiga e ficam desativadas, nunca apagadas.
        ordenadas = sorted(variantes, key=lambda item: str(item["sincronizado_em"]), reverse=True)
        consolidar.append(
            {
                "chave": chave,
                "acao": "desativar_variante_antiga",
                "manter": ordenadas[0]["codigo"],
                "desativar": [item["codigo"] for item in ordenadas[1:]],
                "nome": ordenadas[0]["nome"],
            }
        )
    return consolidar


def aplicar(db, plano, *, dry_run):
    desativados = []
    for entrada in plano:
        if entrada["acao"] != "desativar_variante_antiga":
            continue
        for codigo in entrada["desativar"]:
            desativados.append(codigo)
            if dry_run:
                continue
            with db.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE catalogo_recursos_pcfactory
                    SET habilitado = FALSE
                    WHERE codigo = %s AND habilitado IS TRUE
                    """,
                    (codigo,),
                )
    return desativados


def matriz_elegibilidade(db):
    """RECURSO → SETOR → POSTO → ELEGÍVEL, com o setor vindo do cadastro."""

    catalogo = rows(
        db,
        """
        SELECT codigo, nome, tipo_setor, habilitado FROM catalogo_recursos_pcfactory
        WHERE COALESCE(TRIM(tipo_setor), '') <> '' ORDER BY tipo_setor, codigo
        """,
    )
    linhas = []
    for sector in OPERATOR_SECTORS:
        setor = sector.name
        recursos = [
            item for item in catalogo
            if str(item["tipo_setor"] or "").casefold() == setor.casefold()
        ]
        for item in recursos:
            codigo = str(item["codigo"]).strip()
            elegiveis = [
                posto
                for posto in sector.resources
                if station_matches_route(setor, posto, codigo, resource_sector=setor)
            ]
            vazamento = []
            for outro in OPERATOR_SECTORS:
                if outro.name.casefold() == setor.casefold():
                    continue
                vazamento.extend(
                    f"{outro.name}/{posto}"
                    for posto in outro.resources
                    if station_matches_route(
                        outro.name, posto, codigo, resource_sector=setor
                    )
                )
            linhas.append(
                {
                    "recurso": codigo,
                    "nome": item["nome"],
                    "setor": setor,
                    "postos": elegiveis,
                    "elegivel": bool(elegiveis),
                    "habilitado": bool(item["habilitado"]),
                    "identidade_canonica": canonical_resource_code(codigo),
                    "vazamento_para_outro_setor": vazamento,
                }
            )
    return linhas


def imprimir_matriz(linhas):
    print(f"\n{'RECURSO':12s} {'SETOR':10s} {'ELEG':5s} POSTO(S)")
    print("-" * 78)
    for linha in linhas:
        marca = "SIM" if linha["elegivel"] else "NAO"
        postos = ", ".join(linha["postos"]) if linha["postos"] else "—"
        alerta = "  << VAZAMENTO" if linha["vazamento_para_outro_setor"] else ""
        estado = "" if linha["habilitado"] else "  (desativado)"
        print(f"{linha['recurso']:12s} {linha['setor']:10s} {marca:5s} {postos}{estado}{alerta}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="relata sem gravar")
    parser.add_argument("--matriz", action="store_true", help="somente a matriz")
    args = parser.parse_args()

    db = Database()
    alvo = str((db.safe_target or {}).get("dbname") or "")
    print(f"banco: {alvo}")
    try:
        if args.matriz:
            imprimir_matriz(matriz_elegibilidade(db))
            return 0

        inventario = carregar_inventario(db)
        classificado = classificar(inventario)
        contagem = defaultdict(int)
        for item in classificado:
            for etiqueta in item["etiquetas"]:
                contagem[etiqueta] += 1
        print(f"\nrecursos no catálogo: {len(inventario)}")
        for etiqueta, total in sorted(contagem.items(), key=lambda par: -par[1]):
            print(f"  {etiqueta:38s} {total}")

        plano = duplicidades_comprovadas(classificado)
        desativados = aplicar(db, plano, dry_run=args.dry_run)
        prefixo = "[dry-run] " if args.dry_run else ""
        for entrada in plano:
            if entrada["acao"] == "desativar_variante_antiga":
                print(
                    f"{prefixo}consolidar {entrada['chave']}: mantém "
                    f"{entrada['manter']!r}, desativa {entrada['desativar']} "
                    f"({entrada['nome']})"
                )
            else:
                print(f"decisão humana em {entrada['chave']}: variantes com uso ou nome distinto")
        print(f"{prefixo}variantes desativadas: {len(desativados)}")

        sem_setor = [item for item in classificado if "sem_setor" in item["etiquetas"]]
        sem_uso = [item for item in sem_setor if "sem_uso_identificado" in item["etiquetas"]]
        print(
            f"\nsem tipo_setor: {len(sem_setor)} "
            f"(destes, {len(sem_uso)} sem qualquer uso — sem evidência para classificar)"
        )
        com_uso_sem_setor = [item for item in sem_setor if item not in sem_uso]
        for item in com_uso_sem_setor:
            print(f"  PRECISA DE SETOR: {item['codigo']} — {item['nome']}")

        linhas = matriz_elegibilidade(db)
        imprimir_matriz(linhas)

        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(
            json.dumps(
                {
                    "banco": alvo,
                    "dry_run": bool(args.dry_run),
                    "total_recursos": len(inventario),
                    "contagem_por_etiqueta": dict(contagem),
                    "plano_duplicidades": plano,
                    "desativados": desativados,
                    "aliases_oficiais": OFFICIAL_RESOURCE_ALIASES,
                    "setores_donos_do_recurso": sorted(SECTOR_OWNED_RESOURCE_SECTORS),
                    "matriz": linhas,
                    "sem_setor_sem_uso": [item["codigo"] for item in sem_uso],
                    "sem_setor_com_uso": [item["codigo"] for item in com_uso_sem_setor],
                    "inventario": classificado,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        print(f"\nrelatório: {REPORT_PATH}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
