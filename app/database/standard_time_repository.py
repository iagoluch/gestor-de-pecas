"""Persistência do tempo padrão estimado e leitura do manual guardado (migration 56).

Não decide regra: a prioridade da fonte e as validações vivem em
``mes/domain/standard_time.py`` e ``mes/services/standard_time.py``. Aqui ficam
as consultas e as garantias de banco (PK por chave normalizada).

Tempo manual (decisão do usuário, 04/11/2026): não há mais escrita. As tabelas
``tempo_padrao_manual*`` ficam no banco só como registro; nenhuma consulta de
padrão as usa. O histórico continua legível (``listar_historico_tempo_padrao_manual``).

A chave é ``(produto, operação, recurso)`` com produto/recurso em maiúsculas e
sem espaços nas pontas; o catálogo é por OP, então a lista agrupa as linhas
ativas, apontáveis e fora do Corte.
"""

from __future__ import annotations

from mes.domain.standard_time import _strip_key_part, normalize_key

# Fragmentos SQL constantes (nunca montados com input).
_KEY_EXPR = (
    "UPPER(BTRIM(c.produto_codigo)) AS produto_codigo,"
    " BTRIM(c.numero_operacao) AS numero_operacao,"
    " UPPER(BTRIM(c.codigo_recurso)) AS codigo_recurso"
)
_CATALOG_BASE = (
    "FROM catalogo_operacoes_op c"
    " WHERE c.ativo IS TRUE AND c.marco_terminal IS FALSE"
    " AND UPPER(BTRIM(c.tipo_setor)) <> 'CORTE'"
)

#: Regra única de "a linha do catálogo tem tempo do Protheus": tempo > 0. O mapper
#: grava NULL quando o Protheus manda 0,01 ("recurso sem tempo configurado").
#: É a regra da consulta de fatos (que alimenta o OEE, por linha ``c`` ligada ao
#: apontamento); a listagem usa a mesma expressão.
PROTHEUS_TIME_SQL = "c.tempo_medio_segundos > 0"

#: Agregação por chave sobre as linhas do catálogo (uma por OP). A chave só "tem
#: Protheus" quando TODAS as linhas têm: a consulta de fatos decide por linha, e
#: uma linha sem tempo fica sem padrão oficial ("n/a"). Em chave mista
#: ``tempo_protheus_segundos`` é NULL e ``linhas_com_protheus < linhas_total``;
#: com todas as linhas, vale o valor da mais recente.
PROTHEUS_KEY_AGG_SQL = (
    f" COUNT(*) FILTER (WHERE {PROTHEUS_TIME_SQL}) AS linhas_com_protheus,"
    " COUNT(*) AS linhas_total,"
    f" CASE WHEN COUNT(*) FILTER (WHERE {PROTHEUS_TIME_SQL}) = COUNT(*) THEN"
    "   (array_agg(c.tempo_medio_segundos ORDER BY c.sincronizado_em DESC, c.id DESC)"
    f"     FILTER (WHERE {PROTHEUS_TIME_SQL}))[1]"
    " END AS tempo_protheus_segundos"
)

LIMITE_PADRAO = 100
LIMITE_MAXIMO = 500


def _escape_like(term: str) -> str:
    """Escapa a barra invertida, ``%`` e ``_`` para ``LIKE ... ESCAPE`` com barra invertida."""

    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class StandardTimeRepositoryMixin:
    def listar_tempos_padrao(
        self, *, produto=None, setor=None, recurso=None, somente_sem_padrao=True,
        limite=LIMITE_PADRAO, deslocamento=0,
    ):
        """Operações (produto, operação, recurso) com Protheus e estimado lado a lado.

        ``somente_sem_padrao``: só chaves sem Protheus real (o estimado não conta
        como padrão oficial, mas aparece na linha). O manual guardado não entra.
        """

        limite = max(1, min(int(limite or LIMITE_PADRAO), LIMITE_MAXIMO))
        deslocamento = max(0, int(deslocamento or 0))
        filtros = ""
        params = []
        if produto:
            filtros += " AND UPPER(c.produto_codigo) LIKE %s ESCAPE '\\'"
            params.append(f"%{_escape_like(_strip_key_part(produto).upper())}%")
        if setor:
            filtros += " AND UPPER(BTRIM(c.tipo_setor)) = %s"
            params.append(_strip_key_part(setor).upper())
        if recurso:
            filtros += " AND UPPER(BTRIM(c.codigo_recurso)) = %s"
            params.append(_strip_key_part(recurso).upper())
        query = (
            "WITH chaves AS ("  # nosec B608 -- fragmentos constantes; valores via %s
            f" SELECT {_KEY_EXPR},"
            " MAX(c.tipo_setor) AS tipo_setor,"
            " MAX(c.produto_descricao) AS produto_descricao,"
            " MAX(c.descricao_operacao) AS descricao_operacao,"
            f"{PROTHEUS_KEY_AGG_SQL}"
            f" {_CATALOG_BASE} AND BTRIM(c.produto_codigo) <> ''{filtros}"
            " GROUP BY 1, 2, 3)"
            " SELECT k.*,"
            " te.segundos_por_peca AS tempo_estimado_segundos,"
            " te.amostras AS estimado_amostras,"
            " te.calculado_em AS estimado_calculado_em,"
            " te.vigente_desde AS estimado_vigente_desde,"
            " te.janela_inicio AS estimado_janela_inicio,"
            " te.janela_fim AS estimado_janela_fim,"
            " CASE WHEN k.tempo_protheus_segundos IS NOT NULL THEN 'protheus'"
            "      WHEN te.segundos_por_peca IS NOT NULL THEN 'estimado' END AS fonte_efetiva,"
            " COUNT(*) OVER () AS total"
            " FROM chaves k"
            " LEFT JOIN tempo_padrao_estimado te USING (produto_codigo, numero_operacao, codigo_recurso)"
            " WHERE (NOT %s OR k.tempo_protheus_segundos IS NULL)"
            " ORDER BY k.produto_codigo, k.numero_operacao, k.codigo_recurso"
            " LIMIT %s OFFSET %s"
        )
        params.extend((bool(somente_sem_padrao), limite, deslocamento))
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                "SELECT COUNT(*) AS n FROM ("  # nosec B608 -- fragmentos constantes
                f" SELECT DISTINCT BTRIM(c.numero_operacao), UPPER(BTRIM(c.codigo_recurso)) {_CATALOG_BASE}"
                " AND BTRIM(c.produto_codigo) = '') AS sem_produto"
            )
            sem_produto = int(cursor.fetchone()["n"])
        total = int(rows[0]["total"]) if rows else 0
        for row in rows:
            row.pop("total", None)
        return {"items": rows, "total": total, "sem_produto": sem_produto}

    def listar_historico_tempo_padrao_manual(self, produto, operacao, recurso, limite=50):
        chave = normalize_key(produto, operacao, recurso)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT acao, segundos_anterior, segundos_novo, observacao, usuario_nome,"
                " registrado_em, vigente_desde FROM tempo_padrao_manual_historico"
                " WHERE produto_codigo = %s AND numero_operacao = %s AND codigo_recurso = %s"
                " ORDER BY registrado_em DESC, id DESC LIMIT %s",
                (*chave, max(1, min(int(limite), 200))),
            )
            return [dict(row) for row in cursor.fetchall()]

    def substituir_tempos_padrao_estimados(self, registros, calculado_em):
        """Recalcula o conjunto de estimados de forma idempotente.

        Upsert de cada chave com ``calculado_em`` único e remoção das chaves
        que não foram reafirmadas (perderam amostras/ficaram sem elegíveis).
        Reexecutar com os mesmos registros não muda o resultado.

        ``vigente_desde`` (instante de ``calculado_em``) é gravado só na criação da
        chave e nunca reescrito pelo upsert: o estimado não alcança fatos
        anteriores a ele. Limitações assumidas (é rótulo "estimada", em campo
        separado da Performance oficial): o valor do P25 recalculado vale também
        para fatos entre ``vigente_desde`` e agora, e a chave que perde amostras e
        é removida aqui deixa de valer para todos os seus fatos.
        """
        vigente_desde = calculado_em

        with self.connection() as connection, connection.cursor() as cursor:
            for item in registros:
                cursor.execute(
                    "INSERT INTO tempo_padrao_estimado (produto_codigo, numero_operacao,"
                    " codigo_recurso, segundos_por_peca, amostras, calculado_em,"
                    " janela_inicio, janela_fim, vigente_desde)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                    " ON CONFLICT (produto_codigo, numero_operacao, codigo_recurso) DO UPDATE SET"
                    " segundos_por_peca = EXCLUDED.segundos_por_peca, amostras = EXCLUDED.amostras,"
                    " calculado_em = EXCLUDED.calculado_em, janela_inicio = EXCLUDED.janela_inicio,"
                    " janela_fim = EXCLUDED.janela_fim",
                    (
                        *normalize_key(item["produto"], item["operacao"], item["recurso"]),
                        item["segundos_por_peca"], item["amostras"], calculado_em,
                        item["janela_inicio"], item["janela_fim"], vigente_desde,
                    ),
                )
            cursor.execute(
                "DELETE FROM tempo_padrao_estimado WHERE calculado_em < %s", (calculado_em,)
            )
            return len(registros)
