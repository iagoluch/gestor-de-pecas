"""Auditoria READ-ONLY do banco SigmaNEST — Etapa 3.1, Fase A.

Este script é ferramenta de engenharia reversa. Ele **não** faz integração,
não escreve no SigmaNEST e não escreve no PostgreSQL do Gestor.

Segurança:

- a conexão é aberta com ``readonly=True``;
- toda instrução passa por uma allowlist que aceita apenas consultas;
- qualquer verbo de escrita (INSERT/UPDATE/DELETE/MERGE/DDL) aborta o script;
- a senha nunca é impressa nem gravada em arquivo de saída.

Configuração esperada no ``.env`` (nenhum valor é inventado pelo script):

```
SIGMANEST_ODBC_DSN=DRIVER={ODBC Driver 18 for SQL Server};SERVER=...;DATABASE=...;UID=...;PWD=...;TrustServerCertificate=yes
```

ou, alternativamente:

```
SIGMANEST_SERVER=192.168.0.218,55035
SIGMANEST_DATABASE=SNDBase2026
SIGMANEST_USER=ti_consulta
SIGMANEST_PASSWORD=...
```

Uso:

```
python scripts/auditar_sigmanest.py                 # auditoria completa
python scripts/auditar_sigmanest.py --wo PCMDO701001
```
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


# Estruturas apontadas pela investigação inicial. A lista é ponto de partida
# da auditoria; o script confirma existência e tipos no banco real.
ESTRUTURAS_DE_INTERESSE = (
    "Wo",
    "Part",
    "STPIPArc",
    "ProgArchive",
    "STOCK",
    "PartWithQtyInProcess",
    "DashboardProgramData",
)

_ESCRITA = re.compile(
    r"\b(insert|update|delete|merge|drop|create|alter|truncate|grant|revoke|"
    r"exec\s+sp_(?!help)|xp_cmdshell|into\s+\w+\s*\(|backup|restore)\b",
    re.I,
)


class SomenteLeituraViolada(RuntimeError):
    """Disparada quando uma consulta não passa na allowlist."""


def _garantir_somente_leitura(sql: str) -> str:
    texto = " ".join(sql.split())
    if _ESCRITA.search(texto):
        raise SomenteLeituraViolada(f"Instrução bloqueada (não é leitura): {texto[:120]}")
    primeiro = texto.lstrip("(").split(" ", 1)[0].casefold()
    if primeiro not in {"select", "with", "sp_help", "sp_helptext"}:
        raise SomenteLeituraViolada(f"Instrução bloqueada (verbo inesperado): {texto[:120]}")
    return sql


def _dsn() -> str:
    direto = str(os.getenv("SIGMANEST_ODBC_DSN") or "").strip()
    if direto:
        return direto
    servidor = str(os.getenv("SIGMANEST_SERVER") or "").strip()
    banco = str(os.getenv("SIGMANEST_DATABASE") or "").strip()
    usuario = str(os.getenv("SIGMANEST_USER") or "").strip()
    senha = os.getenv("SIGMANEST_PASSWORD")
    driver = str(
        os.getenv("SIGMANEST_ODBC_DRIVER") or "ODBC Driver 18 for SQL Server"
    ).strip()
    if not servidor or not banco:
        raise SystemExit(
            "SigmaNEST não configurado. Defina SIGMANEST_ODBC_DSN ou "
            "SIGMANEST_SERVER/SIGMANEST_DATABASE (e credencial) no .env."
        )
    partes = [
        f"DRIVER={{{driver}}}",
        f"SERVER={servidor}",
        f"DATABASE={banco}",
        "TrustServerCertificate=yes",
        "Connect Timeout=10",
        "ApplicationIntent=ReadOnly",
    ]
    if usuario:
        partes.append(f"UID={usuario}")
        partes.append(f"PWD={senha or ''}")
    else:
        partes.append("Trusted_Connection=yes")
    return ";".join(partes)


def _dsn_seguro(dsn: str) -> str:
    return re.sub(r"(PWD|PASSWORD)=[^;]*", r"\1=***", dsn, flags=re.I)


class AuditorSigmaNest:
    def __init__(self, conexao):
        self.conexao = conexao

    def consultar(self, sql: str, parametros=()) -> list[dict]:
        cursor = self.conexao.cursor()
        cursor.execute(_garantir_somente_leitura(sql), *parametros)
        colunas = [coluna[0] for coluna in cursor.description]
        return [dict(zip(colunas, linha)) for linha in cursor.fetchall()]

    def escalar(self, sql: str, parametros=()):
        linhas = self.consultar(sql, parametros)
        return next(iter(linhas[0].values())) if linhas else None

    # -- Passo 1 ------------------------------------------------------
    def identidade(self) -> dict:
        return self.consultar(
            """
            SELECT
                CAST(@@SERVERNAME AS NVARCHAR(200)) AS servidor,
                CAST(DB_NAME() AS NVARCHAR(200))    AS banco,
                CAST(SUSER_SNAME() AS NVARCHAR(200)) AS login,
                CAST(SERVERPROPERTY('ProductVersion') AS NVARCHAR(50)) AS versao,
                CAST(SERVERPROPERTY('Edition') AS NVARCHAR(100)) AS edicao
            """
        )[0]

    def permissoes(self) -> list[dict]:
        return self.consultar(
            """
            SELECT DISTINCT permission_name AS permissao, state_desc AS estado
            FROM fn_my_permissions(NULL, 'DATABASE')
            ORDER BY permission_name
            """
        )

    # -- Passo 2 ------------------------------------------------------
    def objetos(self) -> list[dict]:
        return self.consultar(
            """
            SELECT s.name AS esquema, o.name AS objeto, o.type_desc AS tipo
            FROM sys.objects o
            JOIN sys.schemas s ON s.schema_id = o.schema_id
            WHERE o.type IN ('U', 'V')
            ORDER BY o.type_desc, s.name, o.name
            """
        )

    def colunas(self, objeto: str) -> list[dict]:
        return self.consultar(
            """
            SELECT
                c.name AS coluna,
                t.name AS tipo,
                c.max_length AS tamanho,
                c.precision AS precisao,
                c.scale AS escala,
                c.is_nullable AS aceita_nulo,
                c.column_id AS ordem
            FROM sys.columns c
            JOIN sys.types t ON t.user_type_id = c.user_type_id
            WHERE c.object_id = OBJECT_ID(?)
            ORDER BY c.column_id
            """,
            (objeto,),
        )

    def chaves_primarias(self, objeto: str) -> list[dict]:
        return self.consultar(
            """
            SELECT i.name AS indice, c.name AS coluna, ic.key_ordinal AS posicao
            FROM sys.indexes i
            JOIN sys.index_columns ic
              ON ic.object_id = i.object_id AND ic.index_id = i.index_id
            JOIN sys.columns c
              ON c.object_id = ic.object_id AND c.column_id = ic.column_id
            WHERE i.object_id = OBJECT_ID(?) AND i.is_primary_key = 1
            ORDER BY ic.key_ordinal
            """,
            (objeto,),
        )

    def indices(self, objeto: str) -> list[dict]:
        return self.consultar(
            """
            SELECT
                i.name AS indice,
                i.is_unique AS unico,
                i.type_desc AS tipo,
                c.name AS coluna,
                ic.key_ordinal AS posicao,
                ic.is_included_column AS incluida
            FROM sys.indexes i
            JOIN sys.index_columns ic
              ON ic.object_id = i.object_id AND ic.index_id = i.index_id
            JOIN sys.columns c
              ON c.object_id = ic.object_id AND c.column_id = ic.column_id
            WHERE i.object_id = OBJECT_ID(?) AND i.is_primary_key = 0
            ORDER BY i.name, ic.is_included_column, ic.key_ordinal
            """,
            (objeto,),
        )

    def chaves_estrangeiras(self) -> list[dict]:
        return self.consultar(
            """
            SELECT
                fk.name AS constraint_fk,
                OBJECT_NAME(fk.parent_object_id) AS tabela_origem,
                co.name AS coluna_origem,
                OBJECT_NAME(fk.referenced_object_id) AS tabela_destino,
                cd.name AS coluna_destino
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc
              ON fkc.constraint_object_id = fk.object_id
            JOIN sys.columns co
              ON co.object_id = fkc.parent_object_id
             AND co.column_id = fkc.parent_column_id
            JOIN sys.columns cd
              ON cd.object_id = fkc.referenced_object_id
             AND cd.column_id = fkc.referenced_column_id
            ORDER BY tabela_origem, constraint_fk, fkc.constraint_column_id
            """
        )

    def contagem(self, objeto: str):
        return self.escalar(f"SELECT COUNT(*) AS total FROM [{objeto}] WITH (NOLOCK)")

    def definicao_view(self, objeto: str):
        return self.escalar(
            "SELECT CAST(OBJECT_DEFINITION(OBJECT_ID(?)) AS NVARCHAR(MAX)) AS definicao",
            (objeto,),
        )


def _existe(auditor: AuditorSigmaNest, objeto: str) -> bool:
    return bool(auditor.escalar("SELECT OBJECT_ID(?) AS id", (objeto,)))


def executar(args) -> dict:
    import pyodbc

    dsn = _dsn()
    print(f"Conectando (read-only): {_dsn_seguro(dsn)}")
    relatorio: dict = {}
    with pyodbc.connect(dsn, readonly=True, autocommit=True) as conexao:
        auditor = AuditorSigmaNest(conexao)

        relatorio["identidade"] = auditor.identidade()
        print("\n== IDENTIDADE ==")
        for chave, valor in relatorio["identidade"].items():
            print(f"  {chave:10s} {valor}")

        try:
            relatorio["permissoes"] = [p["permissao"] for p in auditor.permissoes()]
            escrita = sorted(
                p for p in relatorio["permissoes"]
                if p in {"INSERT", "UPDATE", "DELETE", "ALTER", "CONTROL"}
            )
            print(f"\n== PERMISSOES ==\n  total={len(relatorio['permissoes'])}")
            print(f"  permissoes de escrita concedidas: {escrita or 'nenhuma'}")
        except Exception as erro:  # pragma: no cover - depende do servidor
            print(f"\n== PERMISSOES ==\n  indisponivel: {str(erro)[:120]}")

        print("\n== ESTRUTURAS DE INTERESSE ==")
        estruturas = {}
        for nome in ESTRUTURAS_DE_INTERESSE:
            if not _existe(auditor, nome):
                print(f"  {nome:24s} AUSENTE")
                estruturas[nome] = {"existe": False}
                continue
            colunas = auditor.colunas(nome)
            pk = auditor.chaves_primarias(nome)
            try:
                total = auditor.contagem(nome)
            except Exception as erro:
                total = f"erro: {str(erro)[:80]}"
            estruturas[nome] = {
                "existe": True,
                "linhas": total,
                "chave_primaria": [c["coluna"] for c in pk],
                "colunas": colunas,
                "indices": auditor.indices(nome),
            }
            pk_txt = ", ".join(c["coluna"] for c in pk) or "sem PK declarada"
            print(f"  {nome:24s} linhas={total!s:>10}  PK=({pk_txt})  colunas={len(colunas)}")
        relatorio["estruturas"] = estruturas

        print("\n== CHAVES ESTRANGEIRAS DECLARADAS ==")
        fks = auditor.chaves_estrangeiras()
        relevantes = [
            fk for fk in fks
            if fk["tabela_origem"] in ESTRUTURAS_DE_INTERESSE
            or fk["tabela_destino"] in ESTRUTURAS_DE_INTERESSE
        ]
        relatorio["chaves_estrangeiras"] = relevantes
        for fk in relevantes:
            print(
                f"  {fk['tabela_origem']}.{fk['coluna_origem']}"
                f" -> {fk['tabela_destino']}.{fk['coluna_destino']}  ({fk['constraint_fk']})"
            )
        if not relevantes:
            print("  nenhuma FK declarada envolvendo as estruturas de interesse")

        relatorio.update(_provas_de_cardinalidade(auditor, args))
        relatorio.update(_analise_transtype(auditor))
        relatorio.update(_formato_wonumber(auditor))

        if _existe(auditor, "DashboardProgramData"):
            definicao = auditor.definicao_view("DashboardProgramData")
            relatorio["dashboard_program_data"] = definicao
            print("\n== DashboardProgramData ==")
            print(f"  definicao capturada: {len(definicao or '')} caracteres")

    return relatorio


def _provas_de_cardinalidade(auditor: AuditorSigmaNest, args) -> dict:
    print("\n== CARDINALIDADES (dados reais) ==")
    resultado = {}
    if _existe(auditor, "ProgArchive"):
        linha = auditor.consultar(
            """
            SELECT
                COUNT(*) AS linhas,
                COUNT(DISTINCT ProgramName) AS programas,
                COUNT(DISTINCT TaskName) AS tarefas,
                COUNT(DISTINCT MachineName) AS maquinas,
                COUNT(DISTINCT SheetName) AS chapas
            FROM ProgArchive WITH (NOLOCK)
            """
        )[0]
        resultado["prog_archive"] = linha
        print(f"  ProgArchive: {linha}")
        multiplos = auditor.consultar(
            """
            SELECT TOP 5 TaskName, COUNT(DISTINCT ProgramName) AS programas
            FROM ProgArchive WITH (NOLOCK)
            WHERE TaskName IS NOT NULL
            GROUP BY TaskName
            HAVING COUNT(DISTINCT ProgramName) > 1
            ORDER BY COUNT(DISTINCT ProgramName) DESC
            """
        )
        resultado["tarefa_com_varios_programas"] = multiplos
        print(f"  1 tarefa -> N programas (top 5): {multiplos}")
    if _existe(auditor, "STPIPArc"):
        varias_wos = auditor.consultar(
            """
            SELECT TOP 5
                ProgramName,
                COUNT(DISTINCT WONumber) AS wos,
                COUNT(DISTINCT PartName) AS pecas
            FROM STPIPArc WITH (NOLOCK)
            GROUP BY ProgramName
            HAVING COUNT(DISTINCT WONumber) > 1
            ORDER BY COUNT(DISTINCT WONumber) DESC
            """
        )
        resultado["programa_com_varias_wos"] = varias_wos
        print(f"  1 programa -> N WOs/pecas (top 5): {varias_wos}")
    if args.wo and _existe(auditor, "STPIPArc"):
        cadeia = auditor.consultar(
            """
            SELECT TOP 50
                s.WONumber, s.PartName, s.ProgramName, s.SheetName,
                s.QtyInProcess, s.TransType,
                p.TaskName, p.MachineName, p.PostDateTime, p.CompDate
            FROM STPIPArc s WITH (NOLOCK)
            LEFT JOIN ProgArchive p WITH (NOLOCK)
              ON p.ProgramName = s.ProgramName AND p.SheetName = s.SheetName
            WHERE s.WONumber = ?
            ORDER BY s.ProgramName
            """,
            (args.wo,),
        )
        resultado["cadeia_da_wo"] = cadeia
        print(f"\n  Cadeia Wo->Part->STPIPArc->ProgArchive para {args.wo}:")
        for linha in cadeia[:10]:
            print(f"    {linha}")
    return resultado


def _analise_transtype(auditor: AuditorSigmaNest) -> dict:
    print("\n== TransType (sem inventar semantica) ==")
    resultado = {}
    for tabela in ("ProgArchive", "STPIPArc"):
        if not _existe(auditor, tabela):
            continue
        try:
            linhas = auditor.consultar(
                f"""
                SELECT
                    TransType,
                    COUNT(*) AS ocorrencias,
                    SUM(CASE WHEN CompDate IS NULL THEN 0 ELSE 1 END) AS com_compdate
                FROM [{tabela}] WITH (NOLOCK)
                GROUP BY TransType
                ORDER BY COUNT(*) DESC
                """
            )
        except Exception as erro:
            print(f"  {tabela}: indisponivel ({str(erro)[:90]})")
            continue
        resultado[f"transtype_{tabela.casefold()}"] = linhas
        for linha in linhas:
            print(f"  {tabela}: {linha}")
    return resultado


def _formato_wonumber(auditor: AuditorSigmaNest) -> dict:
    print("\n== FORMATO DE WONumber (para a correlacao com a OP TOTVS) ==")
    if not _existe(auditor, "Part"):
        return {}
    amostra = auditor.consultar(
        """
        SELECT TOP 200 WONumber, PartName
        FROM Part WITH (NOLOCK)
        WHERE WONumber IS NOT NULL
        ORDER BY WONumber DESC
        """
    )
    tamanhos = Counter(len(str(linha["WONumber"])) for linha in amostra)
    espacos = sum(
        1 for linha in amostra if str(linha["WONumber"]) != str(linha["WONumber"]).strip()
    )
    zeros = sum(1 for linha in amostra if str(linha["WONumber"]).strip().startswith("0"))
    print(f"  amostra={len(amostra)} tamanhos={dict(tamanhos)}")
    print(f"  com espaco nas bordas={espacos}  iniciando com zero={zeros}")
    print(f"  exemplos: {[l['WONumber'] for l in amostra[:8]]}")
    return {
        "wonumber_amostra": amostra[:50],
        "wonumber_tamanhos": dict(tamanhos),
        "wonumber_com_espaco": espacos,
        "wonumber_com_zero_a_esquerda": zeros,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wo", help="WONumber real para provar a cadeia completa")
    parser.add_argument("--json", help="caminho para gravar o relatorio bruto")
    args = parser.parse_args()

    relatorio = executar(args)
    if args.json:
        destino = Path(args.json)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(relatorio, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        print(f"\nRelatorio bruto gravado em {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
