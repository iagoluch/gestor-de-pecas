"""Detector determinístico de defeitos (seções 20 e 41).

Cada verificação é uma consulta **somente leitura** que descreve um estado que
não deveria existir. Nada aqui altera o banco e nada aqui "conserta" nada: o
detector produz evidência.

Duas proteções contra falso positivo:

* **baseline.** O TESTE chega com WIP de execuções anteriores. Tudo o que já
  estava inconsistente antes do start é marcado ``pre_existente`` e sai do
  placar de defeitos introduzidos por esta execução.
* **impressão digital.** A mesma ocorrência não é recontada a cada ciclo; ela é
  registrada uma vez, com o instante em que apareceu.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from simulacao.dbobserver import DatabaseObserver
from simulacao.telemetry import (
    DATA_INCONSISTENCY,
    SEV_CRITICAL,
    SEV_ERROR,
    SEV_WARNING,
    Telemetry,
)


@dataclass(frozen=True)
class Verificacao:
    chave: str
    titulo: str
    severidade: str
    sql: str
    identidade: tuple[str, ...]


VERIFICACOES: tuple[Verificacao, ...] = (
    Verificacao(
        "operacao_finalizada_ainda_ativa",
        "Operação finalizada continua com apontamento ativo",
        SEV_ERROR,
        """
        SELECT ativo.id AS apontamento_id, ativo.op, ativo.numero_operacao,
               ativo.tipo_setor, ativo.maquina, ativo.status,
               final.id AS apontamento_finalizado
        FROM apontamentos_operacionais ativo
        JOIN apontamentos_operacionais final
          ON final.op = ativo.op
         AND final.catalogo_operacao_id IS NOT DISTINCT FROM ativo.catalogo_operacao_id
         AND final.status = 'Finalizado'
         AND final.id <> ativo.id
        WHERE ativo.status <> 'Finalizado'
        """,
        ("apontamento_id", "apontamento_finalizado"),
    ),
    Verificacao(
        "finalizado_sem_inicio",
        "Apontamento finalizado sem data de início",
        SEV_ERROR,
        """
        SELECT id AS apontamento_id, op, numero_operacao, tipo_setor, maquina,
               data_entrada, data_fim
        FROM apontamentos_operacionais
        WHERE status = 'Finalizado' AND data_inicio IS NULL
        """,
        ("apontamento_id",),
    ),
    Verificacao(
        "finalizado_sem_data_fim",
        "Apontamento finalizado sem data de fim",
        SEV_ERROR,
        """
        SELECT id AS apontamento_id, op, numero_operacao, tipo_setor, maquina
        FROM apontamentos_operacionais
        WHERE status = 'Finalizado' AND data_fim IS NULL
        """,
        ("apontamento_id",),
    ),
    Verificacao(
        "dupla_iniciacao",
        "Mesma operação da OP com dois apontamentos ativos",
        SEV_ERROR,
        """
        SELECT op, catalogo_operacao_id, numero_operacao,
               COUNT(*) AS ativos, MIN(id) AS primeiro, MAX(id) AS ultimo
        FROM apontamentos_operacionais
        WHERE status <> 'Finalizado'
        GROUP BY op, catalogo_operacao_id, numero_operacao
        HAVING COUNT(*) > 1
        """,
        ("op", "catalogo_operacao_id"),
    ),
    Verificacao(
        "recurso_com_duas_ops",
        "Recurso físico com duas execuções ativas simultâneas",
        SEV_ERROR,
        """
        SELECT tipo_setor, maquina, COUNT(*) AS ativos,
               STRING_AGG(DISTINCT op, ', ') AS ops
        FROM apontamentos_operacionais
        WHERE status IN ('Em processo', 'Parada', 'Setup', 'Retrabalho')
        GROUP BY tipo_setor, maquina
        HAVING COUNT(*) > 1
        """,
        ("tipo_setor", "maquina"),
    ),
    Verificacao(
        "estado_impossivel",
        "Apontamento em estado fora da máquina de estados canônica",
        SEV_CRITICAL,
        """
        SELECT id AS apontamento_id, op, status, tipo_setor, maquina
        FROM apontamentos_operacionais
        WHERE status NOT IN
              ('Aguardando', 'Em processo', 'Parada', 'Setup', 'Retrabalho', 'Finalizado')
        """,
        ("apontamento_id",),
    ),
    Verificacao(
        "saldo_excedido",
        "Atendido (boas + refugo) maior que o planejado da OP",
        SEV_ERROR,
        """
        SELECT id AS apontamento_id, op, numero_operacao, tipo_setor, maquina,
               quantidade, quantidade_boa, quantidade_refugo,
               (COALESCE(quantidade_boa,0) + COALESCE(quantidade_refugo,0)) AS atendido
        FROM apontamentos_operacionais
        WHERE COALESCE(quantidade,0) > 0
          AND (COALESCE(quantidade_boa,0) + COALESCE(quantidade_refugo,0)) > quantidade
        """,
        ("apontamento_id",),
    ),
    Verificacao(
        "quantidade_negativa",
        "Quantidade boa, refugo ou retrabalho negativa",
        SEV_ERROR,
        """
        SELECT id AS apontamento_id, op, quantidade_boa, quantidade_refugo,
               quantidade_retrabalho
        FROM apontamentos_operacionais
        WHERE COALESCE(quantidade_boa,0) < 0
           OR COALESCE(quantidade_refugo,0) < 0
           OR COALESCE(quantidade_retrabalho,0) < 0
        """,
        ("apontamento_id",),
    ),
    Verificacao(
        "retrabalho_consumiu_saldo",
        "Retrabalho pendente entrou no atendido da OP",
        SEV_ERROR,
        """
        SELECT a.id AS apontamento_id, a.op, a.quantidade, a.quantidade_boa,
               a.quantidade_refugo, a.quantidade_retrabalho,
               COALESCE(q.retrabalho, 0) AS eventos_retrabalho
        FROM apontamentos_operacionais a
        LEFT JOIN LATERAL (
            SELECT SUM(quantidade) AS retrabalho
            FROM eventos_quantidade_producao e
            WHERE e.op = a.op AND e.tipo = 'RETRABALHO'
              AND e.numero_operacao IS NOT DISTINCT FROM a.numero_operacao
        ) q ON TRUE
        WHERE COALESCE(a.quantidade,0) > 0
          AND COALESCE(q.retrabalho,0) > 0
          AND (COALESCE(a.quantidade_boa,0) + COALESCE(a.quantidade_refugo,0)
               + COALESCE(q.retrabalho,0)) <= a.quantidade
          AND (COALESCE(a.quantidade_boa,0) + COALESCE(a.quantidade_refugo,0)) > a.quantidade
        """,
        ("apontamento_id",),
    ),
    Verificacao(
        "participacao_aberta_apos_finalizacao",
        "Participação de operador aberta em apontamento já finalizado",
        SEV_ERROR,
        """
        SELECT p.id AS participacao_id, p.cracha, p.op, p.recurso, p.apontamento_id,
               a.status, a.data_fim
        FROM participacoes_operador p
        JOIN apontamentos_operacionais a ON a.id = p.apontamento_id
        WHERE p.data_fim IS NULL AND a.status = 'Finalizado'
        """,
        ("participacao_id",),
    ),
    Verificacao(
        "participacao_duplicada",
        "Mesmo crachá com duas participações abertas no mesmo apontamento",
        SEV_ERROR,
        """
        SELECT apontamento_id, cracha, COUNT(*) AS abertas,
               MIN(op) AS op, MIN(recurso) AS recurso
        FROM participacoes_operador
        WHERE data_fim IS NULL AND apontamento_id IS NOT NULL
        GROUP BY apontamento_id, cracha
        HAVING COUNT(*) > 1
        """,
        ("apontamento_id", "cracha"),
    ),
    Verificacao(
        "participacao_invertida",
        "Participação com fim anterior ao início",
        SEV_ERROR,
        """
        SELECT id AS participacao_id, cracha, op, recurso, data_inicio, data_fim
        FROM participacoes_operador
        WHERE data_fim IS NOT NULL AND data_fim < data_inicio
        """,
        ("participacao_id",),
    ),
    Verificacao(
        "lote_liberado_sem_aprovacao",
        "Primeira peça liberada sem inspeção conforme",
        SEV_CRITICAL,
        """
        SELECT id AS primeira_peca_id, codigo_op, numero_operacao, tipo_setor,
               status, resultado, inspecionada_em, liberada_em
        FROM qualidade_primeira_peca
        WHERE status = 'CONFORME'
          AND (inspecionada_em IS NULL OR resultado IS DISTINCT FROM 'CONFORME')
        """,
        ("primeira_peca_id",),
    ),
    Verificacao(
        "finalizacao_sem_primeira_peca",
        "Operação finalizada com a primeira peça não aprovada",
        SEV_CRITICAL,
        """
        SELECT a.id AS apontamento_id, a.op, a.numero_operacao, a.tipo_setor,
               a.maquina, f.status AS status_primeira_peca, f.bloqueio_ativo
        FROM apontamentos_operacionais a
        JOIN qualidade_primeira_peca f
          ON f.codigo_op = a.op
         AND f.catalogo_operacao_id IS NOT DISTINCT FROM a.catalogo_operacao_id
        WHERE a.status = 'Finalizado'
          AND a.tipo_setor IN ('Dobra', 'Usinagem', 'Serra', 'Solda', 'Pintura')
          AND f.status IS DISTINCT FROM 'CONFORME'
        """,
        ("apontamento_id",),
    ),
    Verificacao(
        "bloqueio_liberado_sem_autorizacao",
        "Bloqueio de primeira peça liberado sem registro de autorização",
        SEV_ERROR,
        """
        SELECT f.id AS primeira_peca_id, f.codigo_op, f.numero_operacao,
               f.liberada_em, f.liberada_por_cracha
        FROM qualidade_primeira_peca f
        WHERE f.liberada_em IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM qualidade_primeira_peca_autorizacoes a
              WHERE a.primeira_peca_id = f.id AND a.decisao = 'AUTORIZADA'
          )
        """,
        ("primeira_peca_id",),
    ),
    Verificacao(
        "peca_nao_conforme_sem_rnc",
        "Peça com cota não conforme registrada sem RNC ou como aprovada",
        SEV_CRITICAL,
        """
        SELECT p.id AS peca_id, p.inspecao_id, p.numero_peca, p.resultado,
               p.rnc_id, p.possui_nao_conformidade, s.codigo_op, s.tipo_setor
        FROM qualidade_pecas_inspecionadas p
        JOIN qualidade_inspecoes s ON s.id = p.inspecao_id
        WHERE EXISTS (
                  SELECT 1 FROM qualidade_resultados_cota c
                  WHERE c.peca_id = p.id AND c.status = 'NAO_CONFORME'
              )
          AND (p.rnc_id IS NULL OR p.resultado = 'APROVADA')
        """,
        ("peca_id",),
    ),
    Verificacao(
        "inspecao_concluida_incompleta",
        "Inspeção concluída com menos peças medidas do que a quantidade da OP",
        SEV_ERROR,
        """
        SELECT s.id AS inspecao_id, s.codigo_op, s.numero_operacao, s.tipo_setor,
               s.quantidade_total, COUNT(p.id) AS pecas_registradas
        FROM qualidade_inspecoes s
        LEFT JOIN qualidade_pecas_inspecionadas p ON p.inspecao_id = s.id
        WHERE s.status = 'CONCLUIDA'
        GROUP BY s.id, s.codigo_op, s.numero_operacao, s.tipo_setor, s.quantidade_total
        HAVING COUNT(p.id) < s.quantidade_total
        """,
        ("inspecao_id",),
    ),
    Verificacao(
        "inspecao_fora_da_caldeiraria",
        "Inspeção dimensional aberta por setor sem Qualidade habilitada",
        SEV_ERROR,
        """
        SELECT id AS inspecao_id, codigo_op, numero_operacao, tipo_setor,
               tipo_setor_origem, operador
        FROM qualidade_inspecoes
        WHERE COALESCE(NULLIF(TRIM(tipo_setor_origem), ''), 'Dobra')
              NOT IN ('Dobra', 'Usinagem', 'Serra')
        """,
        ("inspecao_id",),
    ),
    Verificacao(
        "evento_duplicado",
        "Evento de apontamento duplicado (mesmo estado e instante)",
        SEV_ERROR,
        """
        SELECT apontamento_id, estado, data_hora, COUNT(*) AS ocorrencias
        FROM eventos_apontamento_operador
        GROUP BY apontamento_id, estado, data_hora
        HAVING COUNT(*) > 1
        """,
        ("apontamento_id", "estado", "data_hora"),
    ),
    Verificacao(
        "evento_fora_de_ordem",
        "Evento de apontamento gravado antes do evento anterior",
        SEV_ERROR,
        """
        SELECT id AS evento_id, apontamento_id, estado, data_hora, anterior,
               origem_automatica, tipo_interrupcao, operador,
               ROUND(EXTRACT(EPOCH FROM (anterior - data_hora))/60.0, 1) AS atraso_minutos
        FROM (
            SELECT id, apontamento_id, estado, data_hora, operador,
                   origem_automatica, tipo_interrupcao,
                   LAG(data_hora) OVER (PARTITION BY apontamento_id ORDER BY id) AS anterior
            FROM eventos_apontamento_operador
        ) janela
        WHERE anterior IS NOT NULL AND data_hora < anterior
          -- O fechamento retroativo de turno (mes/services/shift_boundary.py)
          -- carimba o evento no instante em que o turno terminou, não no
          -- instante em que o sistema reconstruiu o limite perdido. Ficar
          -- "antes do anterior" é o comportamento correto dele, e só dele:
          -- qualquer outro evento fora de ordem continua sendo acusado.
          AND NOT (COALESCE(origem_automatica, FALSE) AND tipo_interrupcao = 'fim_turno')
        """,
        ("evento_id",),
    ),
    Verificacao(
        "estado_recurso_sobreposto",
        "Recurso com dois estados abertos ao mesmo tempo",
        SEV_ERROR,
        """
        SELECT recurso, tipo_setor, COUNT(*) AS abertos,
               STRING_AGG(DISTINCT categoria, ', ') AS categorias
        FROM eventos_estado_recurso
        WHERE data_fim IS NULL
        GROUP BY recurso, tipo_setor
        HAVING COUNT(*) > 1
        """,
        ("recurso", "tipo_setor"),
    ),
    Verificacao(
        "outbox_duplicada",
        "Outbox TOTVS com chave de idempotência repetida",
        SEV_ERROR,
        """
        SELECT idempotency_key, COUNT(*) AS ocorrencias,
               STRING_AGG(DISTINCT status, ', ') AS status
        FROM totvs_outbox
        WHERE idempotency_key IS NOT NULL
        GROUP BY idempotency_key
        HAVING COUNT(*) > 1
        """,
        ("idempotency_key",),
    ),
    Verificacao(
        "outbox_enviada",
        "Mensagem outbound marcada como enviada — o envio deveria estar bloqueado",
        SEV_CRITICAL,
        """
        SELECT id AS outbox_id, production_order, status, sent_at, last_http_status
        FROM totvs_outbox
        WHERE sent_at IS NOT NULL OR status = 'SENT'
        """,
        ("outbox_id",),
    ),
    Verificacao(
        "corte_finalizado_sem_inicio",
        "Nesting finalizado sem início registrado",
        SEV_ERROR,
        """
        SELECT id AS apontamento_id, plano_hash, maquina, status, data_inicio, data_fim
        FROM apontamentos_corte
        WHERE status = 'Finalizado' AND (data_inicio IS NULL OR data_fim IS NULL)
        """,
        ("apontamento_id",),
    ),
    Verificacao(
        "corte_duplo_ativo",
        "Máquina de Corte com dois nestings em processo",
        SEV_ERROR,
        """
        SELECT maquina, COUNT(*) AS ativos, STRING_AGG(plano_hash, ', ') AS planos
        FROM apontamentos_corte
        WHERE status = 'Em processo'
        GROUP BY maquina
        HAVING COUNT(*) > 1
        """,
        ("maquina",),
    ),
    Verificacao(
        "inconsistencia_registrada_pelo_gestor",
        "O próprio Gestor registrou uma inconsistência de dados",
        SEV_WARNING,
        """
        SELECT id AS inconsistencia_id, tipo, severidade, descricao, entidade,
               op, recurso, detectada_em
        FROM inconsistencias_dados
        WHERE resolvida IS NOT TRUE
        """,
        ("inconsistencia_id",),
    ),
)


@dataclass
class Detector:
    observer: DatabaseObserver
    telemetry: Telemetry
    baseline: dict[str, set[str]] = field(default_factory=dict)
    vistos: set[str] = field(default_factory=set)
    achados: list[dict] = field(default_factory=list)

    # ------------------------------------------------------------------
    def _fingerprint(self, verificacao: Verificacao, linha: dict) -> str:
        partes = [str(linha.get(chave, "")) for chave in verificacao.identidade]
        return f"{verificacao.chave}|" + "|".join(partes)

    def capturar_baseline(self) -> dict[str, int]:
        """Fotografa o que já estava inconsistente antes do primeiro evento."""

        resumo: dict[str, int] = {}
        for verificacao in VERIFICACOES:
            try:
                linhas = self.observer.consultar(verificacao.sql)
            except Exception as exc:  # verificação inválida é falha do simulador
                self.telemetry.registrar_evento(
                    action=f"baseline_{verificacao.chave}",
                    classification=DATA_INCONSISTENCY,
                    severity=SEV_WARNING,
                    result="consulta_indisponivel",
                    exception=f"{type(exc).__name__}: {exc}",
                )
                continue
            impressoes = {self._fingerprint(verificacao, linha) for linha in linhas}
            self.baseline[verificacao.chave] = impressoes
            self.vistos |= impressoes
            if impressoes:
                resumo[verificacao.chave] = len(impressoes)
        return resumo

    # ------------------------------------------------------------------
    def executar(self, *, fase: str = "") -> list[dict]:
        novos: list[dict] = []
        for verificacao in VERIFICACOES:
            try:
                linhas = self.observer.consultar(verificacao.sql)
            except Exception as exc:
                self.telemetry.registrar_evento(
                    action=f"detector_{verificacao.chave}",
                    classification=DATA_INCONSISTENCY,
                    severity=SEV_WARNING,
                    result="consulta_indisponivel",
                    exception=f"{type(exc).__name__}: {exc}",
                )
                continue
            for linha in linhas:
                impressao = self._fingerprint(verificacao, linha)
                if impressao in self.vistos:
                    continue
                self.vistos.add(impressao)
                achado = {
                    "verificacao": verificacao.chave,
                    "titulo": verificacao.titulo,
                    "severidade": verificacao.severidade,
                    "fase": fase,
                    "pre_existente": False,
                    "impressao": impressao,
                    "evidencia": linha,
                }
                self.achados.append(achado)
                novos.append(achado)
                self.telemetry.registrar_evento(
                    operator=str(linha.get("operador") or "") or None,
                    resource=str(linha.get("maquina") or linha.get("recurso") or "") or None,
                    sector=str(linha.get("tipo_setor") or "") or None,
                    op=str(linha.get("op") or linha.get("codigo_op") or "") or None,
                    action=f"detector:{verificacao.chave}",
                    classification=DATA_INCONSISTENCY,
                    severity=verificacao.severidade,
                    result=verificacao.titulo,
                    error_code=verificacao.chave,
                    details={"fase": fase, "evidencia": linha},
                )
        return novos

    # ------------------------------------------------------------------
    def resumo(self) -> dict:
        por_chave: dict[str, int] = {}
        for achado in self.achados:
            por_chave[achado["verificacao"]] = por_chave.get(achado["verificacao"], 0) + 1
        return {
            "achados_novos": len(self.achados),
            "por_verificacao": por_chave,
            "baseline": {chave: len(valor) for chave, valor in self.baseline.items() if valor},
            "verificacoes_executadas": [item.chave for item in VERIFICACOES],
        }

    def registrar_divergencia(
        self,
        *,
        tipo: str,
        titulo: str,
        severidade: str,
        evidencia: dict[str, Any],
        fase: str = "",
    ) -> dict:
        """Divergência API × UI × Andon × Gestão (seção 31)."""

        impressao = f"{tipo}|{evidencia.get('chave') or evidencia.get('recurso') or ''}|{fase}"
        achado = {
            "verificacao": tipo,
            "titulo": titulo,
            "severidade": severidade,
            "fase": fase,
            "pre_existente": False,
            "impressao": impressao,
            "evidencia": evidencia,
        }
        if impressao not in self.vistos:
            self.vistos.add(impressao)
            self.achados.append(achado)
        self.telemetry.registrar_consistencia(achado)
        self.telemetry.registrar_evento(
            action=f"consistencia:{tipo}",
            classification=DATA_INCONSISTENCY,
            severity=severidade,
            result=titulo,
            error_code=tipo,
            details=evidencia,
        )
        return achado
