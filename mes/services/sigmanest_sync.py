"""Sincronização SigmaNEST → catálogo canônico de Corte do Gestor.

Fronteira: este serviço lê planejamento por um gateway somente leitura e o
projeta nas tabelas que a fila de Corte **já consome**. Ele não cria OP, não
cria apontamento e não conhece SQL do SigmaNEST.

```text
SigmaNestPlanningGateway (read-only)
        ↓ snapshot de DTOs
SigmaNestSyncService
        ↓ projeção incremental e idempotente
catalogo_sigmanest_tarefas / _programas / _planos_corte / _ops
        ↓ serviços canônicos já existentes
Database.listar_fila_corte → CutService → Tela do Operador
```
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import logging

from app.core.normalization import limpa_codigo
from mes.integrations.sigmanest.gateway import SigmaNestPlanningService


DEFAULT_OVERLAP_DAYS = 7


def _linha_hash(codigo_tarefa: str, programa: str, codigo_op: str, id_peca: str) -> str:
    """Identidade estável da linha de peça dentro do programa da tarefa.

    A composição (tarefa, programa, OP, peça) é a granularidade real de
    ``catalogo_sigmanest_ops``: a mesma OP pode ser aninhada em programas
    diferentes da mesma tarefa, e colapsar isso apagava exatamente o vínculo
    plano -> OP que a fila de Corte precisa exibir. Usá-la mantém a projeção
    idempotente sem depender de identificadores voláteis do arquivo de eventos.
    """

    bruto = "|".join(
        (
            str(codigo_tarefa or "").strip().upper(),
            str(programa or "").strip().upper(),
            str(codigo_op or "").strip().upper(),
            str(id_peca or "").strip().upper(),
        )
    )
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def _assinatura_projecao(planos) -> str:
    """Resume o conjunto de nestings projetado, incluindo o estado de origem.

    Serve só para decidir se algo mudou entre dois ciclos automáticos. Não é
    identidade de negócio e nunca substitui a chave real do plano.
    """

    partes = sorted(
        "|".join(
            (
                str(plano.get("codigo_tarefa") or ""),
                str(plano.get("programa") or ""),
                str(plano.get("nome_chapa") or ""),
                str(plano.get("sequencia_nesting") or ""),
                str(plano.get("sigmanest_repeat_id") or ""),
                str(plano.get("sigmanest_comp_date") or ""),
            )
        )
        for plano in planos or ()
    )
    return hashlib.sha256("\n".join(partes).encode("utf-8")).hexdigest()


@dataclass
class SigmaNestSyncResult:
    """Resultado auditável de uma sincronização."""

    lido_desde: datetime | None = None
    tarefas: int = 0
    programas: int = 0
    nestings: int = 0
    linhas_de_peca: int = 0
    ordens_no_sigmanest: int = 0
    ordens_correlacionadas: int = 0
    ordens_sem_op_no_gestor: tuple[str, ...] = field(default_factory=tuple)
    nestings_concluidos_na_origem: int = 0
    projetado: dict = field(default_factory=dict)
    # Diagnóstico da janela efetivamente consultada (Wave 3). Serve para
    # auditar a leitura incremental sem expor nada disso ao operador.
    watermark: datetime | None = None
    overlap_dias: int = DEFAULT_OVERLAP_DAYS
    janela_inicio: datetime | None = None
    janela_fim: datetime | None = None
    iniciado_em: datetime | None = None
    concluido_em: datetime | None = None
    duracao_segundos: float = 0.0
    tarefas_novas: int = 0
    tarefas_atualizadas: int = 0
    nestings_novos: int = 0
    nestings_atualizados: int = 0
    # Identidade do conjunto projetado nesta janela. Como a projeção é
    # idempotente, duas leituras da mesma realidade produzem a mesma
    # assinatura: é o sinal barato de "nada novo" para quem agenda o ciclo.
    assinatura: str = ""

    def resumo(self) -> str:
        return (
            f"tarefas={self.tarefas} (novas={self.tarefas_novas}) "
            f"programas={self.programas} "
            f"nestings={self.nestings} (novos={self.nestings_novos}) "
            f"pecas={self.linhas_de_peca} "
            f"OPs={self.ordens_no_sigmanest} correlacionadas={self.ordens_correlacionadas} "
            f"sem_op_no_gestor={len(self.ordens_sem_op_no_gestor)} "
            f"janela={self.janela_inicio}..{self.janela_fim} "
            f"duracao={self.duracao_segundos:.2f}s"
        )

    @property
    def houve_novidade(self) -> bool:
        """Alguma tarefa ou chapa entrou/mudou nesta janela."""

        return bool(self.tarefas_novas or self.nestings_novos)

    def as_dict(self) -> dict:
        """Payload de diagnóstico, pronto para log e endpoint administrativo."""

        return {
            "origem": "sigmanest",
            "watermark": self.watermark,
            "overlap_dias": self.overlap_dias,
            "janela_inicio": self.janela_inicio,
            "janela_fim": self.janela_fim,
            "iniciado_em": self.iniciado_em,
            "concluido_em": self.concluido_em,
            "duracao_segundos": round(self.duracao_segundos, 3),
            "tarefas": self.tarefas,
            "tarefas_novas": self.tarefas_novas,
            "tarefas_atualizadas": self.tarefas_atualizadas,
            "programas": self.programas,
            "nestings": self.nestings,
            "nestings_novos": self.nestings_novos,
            "nestings_atualizados": self.nestings_atualizados,
            "linhas_de_peca": self.linhas_de_peca,
            "ordens_no_sigmanest": self.ordens_no_sigmanest,
            "ordens_correlacionadas": self.ordens_correlacionadas,
            "ordens_sem_op_no_gestor": len(self.ordens_sem_op_no_gestor),
            "nestings_concluidos_na_origem": self.nestings_concluidos_na_origem,
            "assinatura": self.assinatura,
        }


class SigmaNestSyncService:
    """Caso de uso de sincronização incremental do planejamento de Corte."""

    def __init__(self, db, gateway, *, now_func=None):
        self.db = db
        self.gateway = gateway
        self.planning = SigmaNestPlanningService(gateway)
        self._now = now_func or datetime.now

    # ------------------------------------------------------------------
    def marca_dagua(self, *, overlap_days: int = DEFAULT_OVERLAP_DAYS):
        """Data a partir da qual reler o SigmaNEST.

        Usa a maior ``data_programa`` já projetada, recuada por uma janela de
        sobreposição. A releitura sobreposta é segura porque a projeção é
        idempotente, e protege contra programas lançados com data retroativa.
        """

        leitor = getattr(self.db, "ultima_sincronizacao_sigmanest", None)
        if not callable(leitor):
            return None
        estado = leitor() or {}
        ultima = estado.get("ultima_data_programa")
        if ultima is None:
            return None
        if isinstance(ultima, datetime):
            base = ultima
        else:
            base = datetime(ultima.year, ultima.month, ultima.day)
        return base - timedelta(days=max(0, int(overlap_days)))

    def _identidades_projetadas(self) -> tuple[set[str], set[str]]:
        """Tarefas e chapas já presentes localmente, antes desta janela.

        Comparar contra elas é o que permite dizer ao operador quantas tarefas
        são realmente **novas** e quantas foram apenas reconfirmadas.
        """

        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT codigo_tarefa FROM catalogo_sigmanest_tarefas")
            tarefas = {
                str(linha["codigo_tarefa"] or "").strip().upper()
                for linha in cursor.fetchall()
            }
            cursor.execute(
                "SELECT codigo_tarefa, programa, nome_chapa, sigmanest_repeat_id"
                " FROM catalogo_sigmanest_planos_corte"
            )
            planos = {
                self._chave_plano(
                    linha["codigo_tarefa"],
                    linha["programa"],
                    linha["nome_chapa"],
                    linha["sigmanest_repeat_id"],
                )
                for linha in cursor.fetchall()
            }
        return tarefas, planos

    @staticmethod
    def _chave_plano(codigo_tarefa, programa, nome_chapa, repeat_id) -> str:
        return "|".join(
            (
                str(codigo_tarefa or "").strip().upper(),
                str(programa or "").strip().upper(),
                str(nome_chapa or "").strip().upper(),
                str(int(repeat_id) if repeat_id is not None else 1),
            )
        )

    def _ordens_conhecidas(self) -> set[str]:
        """OPs que já existem no catálogo canônico alimentado pelo TOTVS."""

        with self.db.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT codigo_op FROM catalogo_pcp_ops")
            return {
                limpa_codigo(linha["codigo_op"])
                for linha in cursor.fetchall()
                if limpa_codigo(linha["codigo_op"])
            }

    # ------------------------------------------------------------------
    def sincronizar(
        self,
        *,
        desde=None,
        overlap_days: int = DEFAULT_OVERLAP_DAYS,
        tarefas=None,
    ) -> SigmaNestSyncResult:
        iniciado_em = self._now()
        watermark = self.marca_dagua(overlap_days=overlap_days)
        inicio = desde if desde is not None else watermark
        snapshot = self.planning.snapshot(desde=inicio, tarefas=tarefas)
        conhecidas = self._ordens_conhecidas()
        try:
            tarefas_antes, planos_antes = self._identidades_projetadas()
        except Exception:  # pragma: no cover - repositório sem as tabelas
            tarefas_antes, planos_antes = set(), set()
        correlacoes, desconhecidas = SigmaNestPlanningService.correlacionar(
            snapshot, conhecidas
        )

        tarefas_projetadas = []
        programas_projetados = []
        planos_projetados = []
        ops_projetadas: dict[str, dict] = {}
        concluidos = 0

        for tarefa in snapshot.tasks:
            tarefas_projetadas.append(
                {
                    "codigo_tarefa": tarefa.codigo_tarefa,
                    "material": tarefa.material,
                    "espessura": tarefa.thickness,
                }
            )
            for ordinal, plano in enumerate(tarefa.plans, start=1):
                programas_projetados.append(
                    {
                        "codigo_tarefa": tarefa.codigo_tarefa,
                        "programa": plano.program_name,
                    }
                )
                if plano.completed_at is not None:
                    concluidos += 1
                planos_projetados.append(
                    {
                        "codigo_tarefa": tarefa.codigo_tarefa,
                        "programa": plano.program_name,
                        "nome_chapa": plano.sheet_name,
                        "sequencia_nesting": ordinal,
                        "area_usada": plano.used_area,
                        "fracao_sucata": plano.scrap_fraction,
                        "quantidade_processo": max(
                            1, sum(peca.quantidade for peca in plano.parts) or 1
                        ),
                        # A máquina do SigmaNEST é preservada exatamente como
                        # veio; o Gestor já resolve o rótulo do posto por ela.
                        "maquina_sigmanest": plano.machine_name,
                        "tempo_previsto_segundos": plano.cutting_time_seconds,
                        "data_programa": plano.posted_at,
                        "status_programa": None,
                        # Dados brutos de procedência, sem regra de negócio.
                        "sigmanest_repeat_id": plano.repeat_id,
                        "sigmanest_archive_packet_id": plano.archive_packet_id,
                        "sigmanest_comp_date": plano.completed_at,
                        "sigmanest_trans_type": plano.trans_type,
                    }
                )
                for peca in plano.parts:
                    if not peca.codigo_op:
                        continue
                    chave = _linha_hash(
                        tarefa.codigo_tarefa,
                        plano.program_name,
                        peca.codigo_op,
                        peca.produto_codigo,
                    )
                    atual = ops_projetadas.get(chave)
                    quantidade = peca.quantidade
                    if atual is not None:
                        # A mesma peça/OP pode aparecer em várias chapas do
                        # mesmo programa; preserva-se a maior quantidade
                        # observada, como antes. O que deixou de ser colapsado
                        # foi o programa, não a repetição de chapa.
                        quantidade = max(quantidade, int(atual["quantidade"]))
                    ops_projetadas[chave] = {
                        "linha_hash": chave,
                        "codigo_tarefa": tarefa.codigo_tarefa,
                        "programa": plano.program_name,
                        "codigo_op": peca.codigo_op,
                        "id_peca": peca.produto_codigo,
                        "setor_destino": peca.setor_destino,
                        "quantidade": quantidade,
                        "dobra": peca.dobra,
                        "usinagem": peca.usinagem,
                        "solda": peca.solda,
                        "chanfro": peca.chanfro,
                    }

        projetado = self.db.sincronizar_catalogo_sigmanest(
            tarefas=tarefas_projetadas,
            programas=programas_projetados,
            ops=list(ops_projetadas.values()),
            planos_corte=planos_projetados,
            sincronizado_em=self._now().replace(microsecond=0),
        )

        concluido_em = self._now()
        chaves_projetadas = {
            self._chave_plano(
                plano["codigo_tarefa"], plano["programa"],
                plano.get("nome_chapa"), plano.get("sigmanest_repeat_id"),
            )
            for plano in planos_projetados
        }
        codigos_tarefa = {
            str(item["codigo_tarefa"] or "").strip().upper()
            for item in tarefas_projetadas
        }
        resultado = SigmaNestSyncResult(
            assinatura=_assinatura_projecao(planos_projetados),
            watermark=watermark,
            overlap_dias=int(overlap_days),
            janela_inicio=inicio,
            janela_fim=snapshot.read_at or concluido_em,
            iniciado_em=iniciado_em,
            concluido_em=concluido_em,
            duracao_segundos=max(0.0, (concluido_em - iniciado_em).total_seconds()),
            tarefas_novas=len(codigos_tarefa - tarefas_antes),
            tarefas_atualizadas=len(codigos_tarefa & tarefas_antes),
            nestings_novos=len(chaves_projetadas - planos_antes),
            nestings_atualizados=len(chaves_projetadas & planos_antes),
            lido_desde=inicio,
            tarefas=len(tarefas_projetadas),
            programas=len({(p["codigo_tarefa"], p["programa"]) for p in programas_projetados}),
            nestings=len(planos_projetados),
            linhas_de_peca=len(ops_projetadas),
            ordens_no_sigmanest=len(snapshot.ordens_de_producao),
            ordens_correlacionadas=len(correlacoes),
            ordens_sem_op_no_gestor=desconhecidas,
            nestings_concluidos_na_origem=concluidos,
            projetado=projetado,
        )
        logging.info("Sincronização SigmaNEST concluída: %s", resultado.resumo())
        return resultado
