"""Persistência do mapa Produto -> Subconjunto da Solda (migration 77).

Só cadastro. Quem decide para onde vai cada operação da fila é
``mes/services/solda_mapa.py``; nada aqui toca apontamento.
"""

from __future__ import annotations

from psycopg.errors import UniqueViolation


class SoldaMapaConflito(ValueError):
    """Código repetido no mesmo escopo (produto no setor, subconjunto no produto, vínculo)."""


_CAMPOS_PRODUTO = ("nome", "codigo", "ativo", "ordem")
_CAMPOS_SUBCONJUNTO = ("nome", "codigo", "ativo", "ordem")


class SoldaMapaRepositoryMixin:
    def listar_solda_mapa(self, setor):
        """Produtos do setor, seus subconjuntos e vínculos, na ordem de exibição."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, setor, nome, codigo, ativo, ordem FROM solda_produtos"
                " WHERE setor = %s ORDER BY ordem, nome, id",
                (setor,),
            )
            produtos = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                "SELECT s.id, s.produto_id, s.nome, s.codigo, s.ativo, s.ordem"
                " FROM solda_subconjuntos s JOIN solda_produtos p ON p.id = s.produto_id"
                " WHERE p.setor = %s ORDER BY s.ordem, s.nome, s.id",
                (setor,),
            )
            subconjuntos = [dict(row) for row in cursor.fetchall()]
            cursor.execute(
                "SELECT v.id, v.produto_id, v.subconjunto_id, v.codigo_item"
                " FROM solda_vinculos v JOIN solda_produtos p ON p.id = v.produto_id"
                " WHERE p.setor = %s ORDER BY v.codigo_item, v.id",
                (setor,),
            )
            vinculos = [dict(row) for row in cursor.fetchall()]
        return {"produtos": produtos, "subconjuntos": subconjuntos, "vinculos": vinculos}

    def _solda_executar(self, sql, params):
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return dict(row) if row else None
        except UniqueViolation as error:
            raise SoldaMapaConflito(str(error)) from error

    def obter_solda_produto(self, produto_id):
        return self._solda_executar(
            "SELECT id, setor, nome, codigo, ativo, ordem FROM solda_produtos WHERE id = %s",
            (produto_id,),
        )

    def obter_solda_subconjunto(self, subconjunto_id):
        return self._solda_executar(
            "SELECT s.id, s.produto_id, s.nome, s.codigo, s.ativo, s.ordem, p.setor"
            " FROM solda_subconjuntos s JOIN solda_produtos p ON p.id = s.produto_id"
            " WHERE s.id = %s",
            (subconjunto_id,),
        )

    def obter_solda_vinculo(self, vinculo_id):
        return self._solda_executar(
            "SELECT v.id, v.produto_id, v.subconjunto_id, v.codigo_item, p.setor"
            " FROM solda_vinculos v JOIN solda_produtos p ON p.id = v.produto_id"
            " WHERE v.id = %s",
            (vinculo_id,),
        )

    def criar_solda_produto(self, setor, nome, codigo, ordem, criado_por):
        return self._solda_executar(
            "INSERT INTO solda_produtos (setor, nome, codigo, ordem, criado_por)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING id, setor, nome, codigo, ativo, ordem",
            (setor, nome, codigo, ordem, criado_por),
        )

    def atualizar_solda_produto(self, produto_id, campos):
        campos = {k: v for k, v in campos.items() if k in _CAMPOS_PRODUTO}
        if not campos:
            return self.obter_solda_produto(produto_id)
        sets = ", ".join(f"{nome} = %s" for nome in campos)  # nomes vêm da lista fechada
        return self._solda_executar(
            f"UPDATE solda_produtos SET {sets} WHERE id = %s"  # nosec B608 -- nomes das colunas vêm de _CAMPOS_PRODUTO (lista fechada); valores vão por parâmetro
            " RETURNING id, setor, nome, codigo, ativo, ordem",
            (*campos.values(), produto_id),
        )

    def criar_solda_subconjunto(self, produto_id, nome, codigo, ordem, criado_por):
        return self._solda_executar(
            "INSERT INTO solda_subconjuntos (produto_id, nome, codigo, ordem, criado_por)"
            " VALUES (%s, %s, %s, %s, %s) RETURNING id, produto_id, nome, codigo, ativo, ordem",
            (produto_id, nome, codigo, ordem, criado_por),
        )

    def atualizar_solda_subconjunto(self, subconjunto_id, campos):
        campos = {k: v for k, v in campos.items() if k in _CAMPOS_SUBCONJUNTO}
        if not campos:
            return self.obter_solda_subconjunto(subconjunto_id)
        sets = ", ".join(f"{nome} = %s" for nome in campos)  # nomes vêm da lista fechada
        return self._solda_executar(
            f"UPDATE solda_subconjuntos SET {sets} WHERE id = %s"  # nosec B608 -- nomes das colunas vêm de _CAMPOS_SUBCONJUNTO (lista fechada); valores vão por parâmetro
            " RETURNING id, produto_id, nome, codigo, ativo, ordem",
            (*campos.values(), subconjunto_id),
        )

    def criar_solda_vinculo(self, produto_id, subconjunto_id, codigo_item, criado_por):
        return self._solda_executar(
            "INSERT INTO solda_vinculos (produto_id, subconjunto_id, codigo_item, criado_por)"
            " VALUES (%s, %s, %s, %s) RETURNING id, produto_id, subconjunto_id, codigo_item",
            (produto_id, subconjunto_id, codigo_item, criado_por),
        )

    def excluir_solda_vinculo(self, vinculo_id):
        return self._solda_executar(
            "DELETE FROM solda_vinculos WHERE id = %s"
            " RETURNING id, produto_id, subconjunto_id, codigo_item",
            (vinculo_id,),
        )
