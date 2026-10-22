"""Persistência da fila manual por recurso (migration 62).

Não decide regra de negócio (quem pode puxar, qual operação é a próxima): isso
vive em ``mes/services/manual_queue.py``. Aqui ficam a leitura das entradas
vivas e as escritas serializadas por recurso.

Uma entrada só vale enquanto a operação não foi finalizada, a OP e a operação
seguem ativas e nenhuma linha ativa da operação está em OUTRO recurso. Isso é
filtrado na leitura (sem tocar a máquina de estados do apontamento); as mortas
são marcadas ``removida_em`` na próxima escrita do recurso.
"""

from __future__ import annotations

from app.core.normalization import limpa_codigo
from app.core.resource_mapping import resolve_resource_identity

_ESTADOS_ATIVOS_SQL = "('Aguardando', 'Em processo', 'Parada', 'Setup', 'Retrabalho')"

# Constante do módulo, sem input; os valores entram sempre via %s.
_ENTRADAS_SQL = f"""
    SELECT
        f.id, f.catalogo_operacao_id, f.codigo_op, f.setor, f.recurso,
        f.posicao, f.puxada, f.criado_por, f.criado_em,
        (
            o.ativo IS TRUE
            AND p.ativo IS TRUE
            AND NOT EXISTS (
                SELECT 1 FROM apontamentos_operacionais a
                WHERE a.catalogo_operacao_id = f.catalogo_operacao_id
                  AND a.status = 'Finalizado'
            )
        ) AS viva_no_banco,
        ARRAY(
            SELECT a.maquina FROM apontamentos_operacionais a
            WHERE a.catalogo_operacao_id = f.catalogo_operacao_id
              AND a.status IN {_ESTADOS_ATIVOS_SQL}
        ) AS maquinas_ativas
    FROM fila_manual_recurso f
    LEFT JOIN catalogo_operacoes_op o ON o.id = f.catalogo_operacao_id
    LEFT JOIN catalogo_pcp_ops p ON p.codigo_op = o.codigo_op
    WHERE f.removida_em IS NULL
"""  # nosec B608 -- só constantes do módulo


def _identidade(valor):
    return str(resolve_resource_identity(valor) or "").strip().casefold()


def _viva(entrada):
    if not entrada["viva_no_banco"]:
        return False
    recurso = _identidade(entrada["recurso"])
    return all(_identidade(maquina) == recurso for maquina in entrada["maquinas_ativas"])


def _como_entrada(row):
    entrada = dict(row)
    entrada.pop("viva_no_banco", None)
    entrada.pop("maquinas_ativas", None)
    return entrada


class ManualQueueRepositoryMixin:
    def _entradas_fila_manual_tx(self, cursor, operacao_id=None):
        query, params = _ENTRADAS_SQL, []
        if operacao_id is not None:
            query += " AND f.catalogo_operacao_id = %s"
            params.append(int(operacao_id))
        cursor.execute(query + " ORDER BY UPPER(f.recurso), f.posicao, f.id", params)
        return [dict(row) for row in cursor.fetchall()]

    def listar_fila_manual_ativa(self, operacao_id=None):
        """Entradas vivas, de todos os recursos, na ordem do recurso."""

        with self.connection() as connection, connection.cursor() as cursor:
            return [
                _como_entrada(entrada)
                for entrada in self._entradas_fila_manual_tx(cursor, operacao_id)
                if _viva(entrada)
            ]

    def _preparar_recurso_fila_manual_tx(self, cursor, recurso, operacao_ids=()):
        """Trava o recurso e baixa as entradas mortas dele (e das operações dadas).

        Devolve as entradas vivas do recurso, na ordem. O lock de transação
        serializa escritas concorrentes mesmo quando o recurso ainda não tem
        linha alguma para ``FOR UPDATE``.
        """

        identidade = _identidade(recurso)
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))", (f"fila-manual:{identidade}",)
        )
        operacoes = {int(item) for item in operacao_ids}
        vivas, mortas = [], []
        for entrada in self._entradas_fila_manual_tx(cursor):
            if _identidade(entrada["recurso"]) != identidade and (
                entrada["catalogo_operacao_id"] not in operacoes
            ):
                continue
            (vivas if _viva(entrada) else mortas).append(entrada)
        if mortas:
            cursor.execute(
                """
                UPDATE fila_manual_recurso
                SET removida_em = %s, removida_por = 'sistema'
                WHERE id = ANY(%s) AND removida_em IS NULL
                """,
                (self._now(), [entrada["id"] for entrada in mortas]),
            )
        do_recurso = [e for e in vivas if _identidade(e["recurso"]) == identidade]
        # Sem buracos: quem saiu da fila (finalizada, inativa...) não deixa
        # posição vazia para trás.
        for posicao, entrada in enumerate(do_recurso, start=1):
            if entrada["posicao"] != posicao:
                cursor.execute(
                    "UPDATE fila_manual_recurso SET posicao = %s WHERE id = %s",
                    (posicao, entrada["id"]),
                )
                entrada["posicao"] = posicao
        return do_recurso

    def _fixar_fila_manual_tx(
        self, cursor, operacao_id, codigo_op, setor, recurso, posicao, usuario, puxada=False
    ):
        """Upsert por (operação, recurso). ``puxada`` nunca volta de TRUE para FALSE."""

        cursor.execute(
            """
            INSERT INTO fila_manual_recurso (
                catalogo_operacao_id, codigo_op, setor, recurso, posicao,
                puxada, criado_por, criado_em
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (catalogo_operacao_id, recurso) WHERE removida_em IS NULL DO UPDATE SET
                posicao = EXCLUDED.posicao,
                setor = EXCLUDED.setor,
                puxada = fila_manual_recurso.puxada OR EXCLUDED.puxada,
                atualizado_por = EXCLUDED.criado_por,
                atualizado_em = EXCLUDED.criado_em
            RETURNING id, catalogo_operacao_id, recurso, posicao
            """,
            (
                int(operacao_id), limpa_codigo(codigo_op), str(setor), str(recurso),
                int(posicao), bool(puxada), usuario, self._now(),
            ),
        )
        return dict(cursor.fetchone())

    def adicionar_fila_manual(self, operacao_id, codigo_op, setor, recurso, usuario):
        """Puxa a operação para o recurso: fim das fixadas, marcada ``puxada``.

        Se ela já está fixada neste mesmo recurso, mantém a posição. A puxada
        anterior em outro recurso é baixada (a OP só some de UM lugar).
        """

        with self.connection() as connection, connection.cursor() as cursor:
            vivas = self._preparar_recurso_fila_manual_tx(cursor, recurso, [operacao_id])
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"fila-manual-op:{int(operacao_id)}",),
            )
            cursor.execute(
                """
                UPDATE fila_manual_recurso
                SET removida_em = %s, removida_por = %s
                WHERE catalogo_operacao_id = %s AND puxada
                  AND removida_em IS NULL AND recurso <> %s
                """,
                (self._now(), usuario, int(operacao_id), str(recurso)),
            )
            atual = next(
                (e for e in vivas if e["catalogo_operacao_id"] == int(operacao_id)), None
            )
            posicao = (
                atual["posicao"] if atual
                else max((e["posicao"] for e in vivas), default=0) + 1
            )
            return self._fixar_fila_manual_tx(
                cursor, operacao_id, codigo_op, setor, recurso, posicao, usuario, puxada=True
            )

    def reordenar_fila_manual(self, setor, recurso, operacoes, usuario):
        """Grava a ordem dada (``[(operacao_id, codigo_op), ...]``) a partir da posição 1.

        As entradas vivas do recurso que ficaram fora da lista seguem depois,
        na ordem em que estavam.
        """

        with self.connection() as connection, connection.cursor() as cursor:
            vivas = self._preparar_recurso_fila_manual_tx(
                cursor, recurso, [operacao_id for operacao_id, _ in operacoes]
            )
            dadas = {int(operacao_id) for operacao_id, _ in operacoes}
            resto = [
                (e["catalogo_operacao_id"], e["codigo_op"])
                for e in vivas
                if e["catalogo_operacao_id"] not in dadas
            ]
            for posicao, (operacao_id, codigo_op) in enumerate(
                [*operacoes, *resto], start=1
            ):
                self._fixar_fila_manual_tx(
                    cursor, operacao_id, codigo_op, setor, recurso, posicao, usuario
                )

    def remover_fila_manual(self, entrada_id, recurso, usuario):
        """Baixa a entrada do recurso. ``False`` se não existe (ou é de outro recurso)."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"fila-manual:{_identidade(recurso)}",),
            )
            cursor.execute(
                """
                UPDATE fila_manual_recurso
                SET removida_em = %s, removida_por = %s
                WHERE id = %s AND removida_em IS NULL AND UPPER(recurso) = UPPER(%s)
                """,
                (self._now(), usuario, int(entrada_id), str(recurso)),
            )
            return cursor.rowcount == 1

    def buscar_op_pcp_ativa(self, codigo_op):
        """``{'codigo_op', 'ativo'}`` da OP no catálogo, ou ``None`` se não existe."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT codigo_op, ativo FROM catalogo_pcp_ops WHERE codigo_op = %s",
                (limpa_codigo(codigo_op),),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
