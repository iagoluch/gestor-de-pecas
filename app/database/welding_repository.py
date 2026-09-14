"""Leitura das OPs de conjunto soldado para a visão gerencial da Solda.

Este repositório é somente leitura. Ele não classifica prazo, não decide
estação e não grava nada: a regra vive em ``mes/domain/welding.py`` e a
composição em ``mes/services/welding.py``.

Fontes, todas já canônicas no Gestor:

* ``catalogo_pcp_ops`` — a OP e o produto/conjunto planejado;
* ``catalogo_operacoes_op`` — a operação de Solda do roteiro e a máquina dela;
* ``catalogo_recursos_pcfactory`` — o nome público da máquina;
* ``apontamentos_operacionais`` — a execução real, de onde sai a **estação**
  observada e a conclusão.

A identidade da OP é a canônica do catálogo (``codigo_op``). Nenhum
identificador novo é criado e a OP não é duplicada: a granularidade da linha é
``(OP, operação de Solda do roteiro)``, que é o que a PCP acompanha.
"""

from __future__ import annotations

from app.core.operator_sectors import WELDING_SECTOR_NAMES


#: Estados do apontamento que representam execução viva no posto.
ACTIVE_APPOINTMENT_STATUSES = ("Aguardando", "Em processo", "Parada", "Setup", "Retrabalho")

#: Setores que a tela gerencial da Solda acompanha.
#:
#: Wave 6F — o setor único "Solda" virou cinco. ``"Solda"`` continua na lista
#: porque os roteiros e apontamentos já gravados mantêm esse ``tipo_setor``: a
#: reclassificação vale para o catálogo de recursos e só alcança as operações na
#: próxima sincronização da OP. Retirá-lo esvaziaria o histórico da tela.
WELDING_MANAGEMENT_SECTORS = ("Solda", *WELDING_SECTOR_NAMES)


class WeldingRepositoryMixin:
    def listar_ops_solda_gerencial(self, *, limite=300):
        """Uma linha por operação de Solda do roteiro, com execução observada.

        A consulta é única de propósito: a tela é gerencial e roda em ciclo de
        TV, portanto não pode abrir uma consulta por OP nem por estação.
        """

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    operacao.codigo_op,
                    operacao.numero_operacao,
                    operacao.ordem,
                    operacao.codigo_recurso,
                    operacao.descricao_operacao,
                    recurso.nome AS recurso_nome,
                    pcp.produto_codigo,
                    pcp.produto_descricao,
                    -- Modelo da máquina do produto. A coluna existe e continua
                    -- anulável: a carga automática dela é trabalho de outra
                    -- etapa, e a ausência é mostrada como texto, nunca inventada.
                    pcp.produto_modelo,
                    pcp.quantidade,
                    pcp.data_emissao,
                    pcp.prazo_entrega,
                    pcp.inicio_planejado,
                    pcp.fim_planejado,
                    pcp.totvs_generated_on AS data_geracao,
                    execucao.maquina AS estacao_observada,
                    execucao.status AS status_apontamento,
                    execucao.data_inicio AS apontamento_inicio,
                    execucao.data_fim AS apontamento_fim,
                    execucao.operador_inicio,
                    execucao.operador_fim,
                    historico.primeiro_apontamento,
                    historico.total_apontamentos
                FROM catalogo_operacoes_op operacao
                JOIN catalogo_pcp_ops pcp
                  ON pcp.codigo_op = operacao.codigo_op AND pcp.ativo IS TRUE
                LEFT JOIN catalogo_recursos_pcfactory recurso
                  ON recurso.codigo = operacao.codigo_recurso
                -- Execução da própria operação de Solda. O vínculo preferido é
                -- o identificador da operação do roteiro; quando o apontamento
                -- é anterior a esse vínculo, o par OP + número da operação
                -- mantém a leitura. Nunca se atribui a execução de outra etapa.
                LEFT JOIN LATERAL (
                    SELECT ap.maquina, ap.status, ap.data_inicio, ap.data_fim,
                           ap.operador_inicio, ap.operador_fim
                    FROM apontamentos_operacionais ap
                    WHERE UPPER(ap.tipo_setor) = ANY(%(setores)s)
                      AND ap.op = operacao.codigo_op
                      AND (
                        ap.catalogo_operacao_id = operacao.id
                        OR (
                          ap.catalogo_operacao_id IS NULL
                          AND COALESCE(ap.numero_operacao, '') = operacao.numero_operacao
                        )
                      )
                    ORDER BY
                        CASE WHEN ap.status = ANY(%(ativos)s) THEN 0 ELSE 1 END,
                        COALESCE(ap.data_fim, ap.data_inicio, ap.data_entrada) DESC,
                        ap.id DESC
                    LIMIT 1
                ) execucao ON TRUE
                -- Histórico da OP inteira: a regra de atraso pergunta se a OP
                -- recebeu algum apontamento na semana em que foi criada, e isso
                -- não se limita à Solda.
                LEFT JOIN LATERAL (
                    SELECT
                        MIN(COALESCE(ap.data_inicio, ap.data_entrada)) AS primeiro_apontamento,
                        COUNT(*) AS total_apontamentos
                    FROM apontamentos_operacionais ap
                    WHERE ap.op = operacao.codigo_op
                ) historico ON TRUE
                WHERE operacao.ativo IS TRUE
                  AND UPPER(operacao.tipo_setor) = ANY(%(setores)s)
                ORDER BY operacao.codigo_op, operacao.ordem, operacao.id
                LIMIT %(limite)s
                """,
                {
                    "setores": [name.upper() for name in WELDING_MANAGEMENT_SECTORS],
                    "ativos": list(ACTIVE_APPOINTMENT_STATUSES),
                    "limite": int(limite),
                },
            )
            return [dict(row) for row in cursor.fetchall()]
