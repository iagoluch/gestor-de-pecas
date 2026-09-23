"""Adaptador SQL Server SOMENTE LEITURA do planejamento SigmaNEST.

Este é o único arquivo do produto autorizado a conhecer tabelas e colunas do
SigmaNEST. Ele implementa :class:`SigmaNestPlanningGateway` e devolve DTOs
neutros.

Auditoria de origem (27/08/2026, `SVR-DBLANTEK\\SIGMANEST` / `SNDBase2026`):

```text
ProgArchive  PK=AutoID     TaskName, ProgramName, SheetName, MachineName,
                           PostDateTime, CompDate, TransType, ArchivePacketID
STPIPArc     PK=AutoID     ProgramName, SheetName, PartName, WONumber,
                           QtyInProcess, MasterPartQty, TransType
Part         PK=(WONumber, PartName)   FK Part.WONumber -> Wo.WONumber
Wo           PK=WONumber
```

Garantias de segurança:

- conexão aberta com ``readonly=True`` e ``ApplicationIntent=ReadOnly``;
- somente ``SELECT`` com ``WITH (NOLOCK)``;
- nenhuma instrução de escrita ou DDL existe neste módulo;
- a senha nunca é registrada em log.
"""

from __future__ import annotations

from contextlib import closing
from datetime import datetime
import logging
import os
import re
from typing import Iterable

from mes.integrations.sigmanest.models import (
    SigmaNestCutPlan,
    SigmaNestPartLine,
    SigmaNestPlanningSnapshot,
    SigmaNestTask,
)


LOGGER = logging.getLogger(__name__)

DEFAULT_ODBC_DRIVER = "ODBC Driver 18 for SQL Server"


class SigmaNestConfigurationError(RuntimeError):
    """Configuração ausente ou insegura para o acesso ao SigmaNEST."""


def build_sigmanest_dsn(environ=None) -> str:
    """Monta o DSN a partir do ambiente, sem inventar servidor ou credencial."""

    env = environ if environ is not None else os.environ
    direto = str(env.get("SIGMANEST_ODBC_DSN") or "").strip()
    if direto:
        return direto
    servidor = str(env.get("SIGMANEST_SERVER") or "").strip()
    banco = str(env.get("SIGMANEST_DATABASE") or "").strip()
    if not servidor or not banco:
        raise SigmaNestConfigurationError(
            "SigmaNEST não configurado. Defina SIGMANEST_ODBC_DSN ou "
            "SIGMANEST_SERVER/SIGMANEST_DATABASE."
        )
    driver = str(env.get("SIGMANEST_ODBC_DRIVER") or DEFAULT_ODBC_DRIVER).strip()
    usuario = str(env.get("SIGMANEST_USER") or "").strip()
    partes = [
        f"DRIVER={{{driver}}}",
        f"SERVER={servidor}",
        f"DATABASE={banco}",
        "TrustServerCertificate=yes",
        "ApplicationIntent=ReadOnly",
        f"Connect Timeout={str(env.get('SIGMANEST_CONNECT_TIMEOUT') or '10').strip()}",
    ]
    if usuario:
        partes.append(f"UID={usuario}")
        partes.append(f"PWD={env.get('SIGMANEST_PASSWORD') or ''}")
    else:
        partes.append("Trusted_Connection=yes")
    return ";".join(partes)


def mask_dsn(dsn: str) -> str:
    """Versão segura para log: nunca expõe a senha."""

    return re.sub(r"(PWD|PASSWORD)=[^;]*", r"\1=***", str(dsn or ""), flags=re.I)


# Consultas fixas e auditáveis. Nenhuma é montada por concatenação de dados.
_SQL_PLANOS = """
SELECT
    p.TaskName, p.ProgramName, p.SheetName, p.MachineName, p.RepeatID,
    p.ArchivePacketID, p.UsedArea, p.ScrapFraction, p.CuttingTime,
    p.PostDateTime, p.CompDate, p.TransType
FROM ProgArchive p WITH (NOLOCK)
WHERE p.TaskName IS NOT NULL
  AND (? IS NULL OR p.PostDateTime >= ?)
ORDER BY p.TaskName, p.ProgramName, p.SheetName, p.ArchivePacketID
"""

# STPIPArc é arquivo de eventos: cada (programa, chapa, peça, WO) aparece ~4x,
# uma linha por ArchivePacketID/TransType, com MasterPartQty constante. A
# agregação abaixo desduplica a composição real do nesting.
_SQL_PECAS = """
SELECT
    s.ProgramName, s.SheetName, s.PartName, s.WONumber,
    MAX(s.QtyInProcess)    AS QtyInProcess,
    MAX(s.MasterPartQty)   AS MasterPartQty,
    MAX(s.CuttingTime)     AS CuttingTime,
    MAX(s.TrueArea)        AS TrueArea,
    MAX(s.TransType)       AS TransType,
    MAX(pt.Material)       AS Material,
    MAX(pt.Thickness)      AS Thickness,
    MAX(pt.Data3)          AS Dobra,
    MAX(pt.Data4)          AS Usinagem,
    MAX(pt.Data5)          AS Solda,
    MAX(pt.Data6)          AS Chanfro
FROM STPIPArc s WITH (NOLOCK)
LEFT JOIN Part pt WITH (NOLOCK)
  ON pt.WONumber = s.WONumber AND pt.PartName = s.PartName
WHERE s.WONumber IS NOT NULL
  AND s.ProgramName IN (
      SELECT DISTINCT ProgramName FROM ProgArchive WITH (NOLOCK)
      WHERE TaskName IS NOT NULL AND (? IS NULL OR PostDateTime >= ?)
  )
GROUP BY s.ProgramName, s.SheetName, s.PartName, s.WONumber
"""


class SigmaNestSqlServerGateway:
    """Implementação ODBC do :class:`SigmaNestPlanningGateway`."""

    def __init__(self, dsn: str | None = None, *, connect=None, environ=None):
        self.dsn = dsn or build_sigmanest_dsn(environ)
        self._connect = connect

    def _abrir(self):
        if self._connect is not None:
            return self._connect(self.dsn)
        import pyodbc  # importado sob demanda: o produto não exige o driver

        conexao = pyodbc.connect(self.dsn, readonly=True, autocommit=True)
        # Sem isso, uma consulta presa (lock, servidor sobrecarregado) no SQL
        # Server do SigmaNEST fica bloqueada indefinidamente — o timeout de
        # conexão do DSN não cobre a execução da query, só o handshake inicial.
        try:
            conexao.timeout = int(
                str(os.environ.get("SIGMANEST_QUERY_TIMEOUT") or "30").strip()
            )
        except (AttributeError, ValueError) as exc:
            LOGGER.warning(
                "Timeout de consulta do SigmaNEST não aplicado (SIGMANEST_QUERY_TIMEOUT): %s; "
                "consultas ficam sem limite de execução.",
                exc,
            )
        return conexao

    @staticmethod
    def _linhas(cursor) -> list[dict]:
        colunas = [coluna[0] for coluna in cursor.description]
        return [dict(zip(colunas, linha)) for linha in cursor.fetchall()]

    def ler_planejamento(
        self,
        *,
        desde=None,
        tarefas: Iterable[str] | None = None,
    ) -> SigmaNestPlanningSnapshot:
        filtro_tarefas = {
            str(codigo).strip().upper()
            for codigo in (tarefas or ())
            if str(codigo or "").strip()
        }
        # ``with`` de uma conexão pyodbc só faz commit/rollback, não fecha:
        # ``closing`` devolve a conexão ao SQL Server também em caso de erro.
        with closing(self._abrir()) as conexao:
            cursor = conexao.cursor()
            cursor.execute(_SQL_PLANOS, desde, desde)
            planos = self._linhas(cursor)
            cursor.execute(_SQL_PECAS, desde, desde)
            pecas = self._linhas(cursor)
        return self.montar_snapshot(planos, pecas, filtro_tarefas=filtro_tarefas)

    @staticmethod
    def montar_snapshot(
        planos: list[dict],
        pecas: list[dict],
        *,
        filtro_tarefas: set[str] | None = None,
        read_at: datetime | None = None,
    ) -> SigmaNestPlanningSnapshot:
        """Converte linhas cruas em DTOs. Determinístico e testável sem banco."""

        pecas_por_nesting: dict[tuple[str, str], list[SigmaNestPartLine]] = {}
        for linha in pecas:
            chave = (
                str(linha.get("ProgramName") or "").strip(),
                str(linha.get("SheetName") or "").strip(),
            )
            pecas_por_nesting.setdefault(chave, []).append(
                SigmaNestPartLine(
                    program_name=chave[0],
                    sheet_name=chave[1],
                    part_name=str(linha.get("PartName") or "").strip(),
                    wo_number=str(linha.get("WONumber") or "").strip(),
                    qty_in_process=int(linha.get("QtyInProcess") or 0),
                    master_part_qty=int(linha.get("MasterPartQty") or 0),
                    cutting_time_seconds=linha.get("CuttingTime"),
                    true_area=linha.get("TrueArea"),
                    trans_type=str(linha.get("TransType") or "").strip(),
                    material=str(linha.get("Material") or "").strip(),
                    thickness=linha.get("Thickness"),
                    dobra=str(linha.get("Dobra") or "").strip(),
                    usinagem=str(linha.get("Usinagem") or "").strip(),
                    solda=str(linha.get("Solda") or "").strip(),
                    chanfro=str(linha.get("Chanfro") or "").strip(),
                )
            )

        # Um mesmo programa/chapa aparece várias vezes no arquivo (um registro
        # por TransType/pacote). Preserva-se o registro mais recente por
        # ArchivePacketID, mantendo a conclusão quando ela existir.
        #
        # `RepeatID` participa da chave porque o nesting **é a chapa física**:
        # `ProgramName + SheetName + RepeatID` (auditoria de 27/08/2026,
        # `docs/INTEGRACAO_CORTE_SIGMANEST.md`). Colapsar as repetições
        # transformaria N chapas em uma só e perderia a quantidade real —
        # exatamente a suposição "1 nesting = 1 chapa" que não deve existir.
        # `_plano_hash` do repositório já usava `repeat_id`; só o snapshot
        # deixava as repetições de fora.
        melhor_plano: dict[tuple[str, str, str, int], dict] = {}
        for linha in planos:
            tarefa = str(linha.get("TaskName") or "").strip()
            programa = str(linha.get("ProgramName") or "").strip()
            chapa = str(linha.get("SheetName") or "").strip()
            if not tarefa or not programa:
                continue
            if filtro_tarefas and tarefa.upper() not in filtro_tarefas:
                continue
            repeticao = linha.get("RepeatID")
            chave = (
                tarefa,
                programa,
                chapa,
                int(repeticao) if repeticao is not None else 1,
            )
            atual = melhor_plano.get(chave)
            if atual is None:
                melhor_plano[chave] = dict(linha)
                continue
            pacote_novo = linha.get("ArchivePacketID") or 0
            pacote_atual = atual.get("ArchivePacketID") or 0
            if pacote_novo > pacote_atual:
                conclusao = atual.get("CompDate") or linha.get("CompDate")
                melhor_plano[chave] = {**dict(linha), "CompDate": conclusao}
            elif atual.get("CompDate") is None and linha.get("CompDate") is not None:
                melhor_plano[chave] = {**atual, "CompDate": linha.get("CompDate")}

        planos_por_tarefa: dict[str, list[SigmaNestCutPlan]] = {}
        for (tarefa, programa, chapa, _repeticao), linha in sorted(melhor_plano.items()):
            planos_por_tarefa.setdefault(tarefa, []).append(
                SigmaNestCutPlan(
                    task_name=tarefa,
                    program_name=programa,
                    sheet_name=chapa,
                    machine_name=str(linha.get("MachineName") or "").strip(),
                    repeat_id=linha.get("RepeatID"),
                    archive_packet_id=linha.get("ArchivePacketID"),
                    used_area=linha.get("UsedArea"),
                    scrap_fraction=linha.get("ScrapFraction"),
                    cutting_time_seconds=linha.get("CuttingTime"),
                    posted_at=linha.get("PostDateTime"),
                    completed_at=linha.get("CompDate"),
                    trans_type=str(linha.get("TransType") or "").strip(),
                    parts=tuple(pecas_por_nesting.get((programa, chapa), ())),
                )
            )

        def _material_da_tarefa(planos_da_tarefa):
            for plano in planos_da_tarefa:
                for peca in plano.parts:
                    if peca.material:
                        return peca.material, peca.thickness
            return "", None

        return SigmaNestPlanningSnapshot(
            tasks=tuple(
                SigmaNestTask(
                    task_name=tarefa,
                    material=_material_da_tarefa(planos_da_tarefa)[0],
                    thickness=_material_da_tarefa(planos_da_tarefa)[1],
                    plans=tuple(planos_da_tarefa),
                )
                for tarefa, planos_da_tarefa in sorted(planos_por_tarefa.items())
            ),
            read_at=read_at,
            source="sigmanest_sqlserver",
        )
