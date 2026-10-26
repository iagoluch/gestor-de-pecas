"""Persistência do "quem mudou o quê" das telas de gestão (migration 66).

A gravação nunca derruba a operação auditada: ``registrar_auditoria`` captura
qualquer erro, loga e devolve ``False``. Só entram os campos listados em
``CAMPOS_AUDITAVEIS`` por entidade — senha, hash, token e ``session_version``
ficam fora por construção, não por filtro de nome.
"""

from __future__ import annotations

import json
import logging
import re

from psycopg.types.json import Jsonb

ACOES = ("criar", "alterar", "excluir")

CAMPOS_AUDITAVEIS = {
    "usuario": ("nome", "nivel_atribuido", "unidade", "ativo"),
    "nivel": ("nome", "rotulo", "nivel_base"),
    "turno": ("nome", "tipo", "hora_inicio", "hora_fim", "ativo", "ordem"),
    "pausa": ("tipo_setor", "nome", "hora_inicio", "hora_fim", "ativo", "ordem"),
    "custo_recurso": ("recurso", "valor_hora"),
    "custo_pessoa": ("operador_id", "valor_hora"),
    # Decisão sobre RNC (Qualidade): sem dado pessoal além do que já está na RNC.
    "rnc_decisao": ("rnc_id", "rnc_codigo", "decisao", "justificativa"),
}

# Entidades em R$: só a aba Diretoria as expõe (``/diretoria/custos/auditoria``).
ENTIDADES_DE_CUSTO = ("custo_recurso", "custo_pessoa")

LIMITE_PADRAO = 100
LIMITE_MAXIMO = 500


def _json_seguro(valor):
    return json.loads(json.dumps(valor, ensure_ascii=False, default=str))


def sanitizar_auditoria(entidade, dados):
    """Reduz ``dados`` aos campos permitidos da entidade (``None`` se não há)."""

    campos = CAMPOS_AUDITAVEIS.get(entidade)
    if campos is None or not dados:
        return None
    return {campo: dados[campo] for campo in campos if campo in dados}


class ChangeAuditRepositoryMixin:
    def registrar_auditoria(self, *, entidade, chave, acao, usuario_id=None, usuario_nome=None,
                            antes=None, depois=None):
        """Grava uma alteração; nunca levanta erro. Devolve se gravou."""

        try:
            if entidade not in CAMPOS_AUDITAVEIS or acao not in ACOES:
                raise ValueError(f"Auditoria recusada: entidade={entidade!r} acao={acao!r}.")
            antes_limpo = sanitizar_auditoria(entidade, antes)
            depois_limpo = sanitizar_auditoria(entidade, depois)
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO auditoria_alteracoes
                        (quando, usuario_id, usuario_nome, entidade, chave, acao, antes, depois)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self._now(),
                        usuario_id,
                        usuario_nome,
                        entidade,
                        str(chave),
                        acao,
                        None if antes_limpo is None else Jsonb(_json_seguro(antes_limpo)),
                        None if depois_limpo is None else Jsonb(_json_seguro(depois_limpo)),
                    ),
                )
            return True
        except Exception:
            logging.exception("Falha ao gravar auditoria de alteração (%s/%s)", entidade, chave)
            return False

    def listar_auditoria(self, *, entidade=None, chave=None, usuario=None, desde=None, ate=None,
                         limite=LIMITE_PADRAO, entidades=None, excluir_entidades=None):
        """Mais recentes primeiro. ``usuario`` casa por id (número) ou parte do nome;
        ``desde`` inclusivo e ``ate`` exclusivo (datetimes)."""

        limite = max(1, min(int(limite or LIMITE_PADRAO), LIMITE_MAXIMO))
        query = (
            "SELECT id, quando, usuario_id, usuario_nome, entidade, chave, acao, antes, depois"
            " FROM auditoria_alteracoes WHERE TRUE"
        )
        params = []
        if entidade:
            query += " AND entidade = %s"
            params.append(entidade)
        if entidades:
            query += " AND entidade = ANY(%s)"
            params.append(list(entidades))
        if excluir_entidades:
            query += " AND entidade <> ALL(%s)"
            params.append(list(excluir_entidades))
        if chave:
            query += " AND chave = %s"
            params.append(str(chave))
        if usuario:
            texto = str(usuario).strip()
            # Só 0-9 e até 18 dígitos cabem no id; "²" ou número gigante viram busca por nome.
            if re.fullmatch(r"[0-9]{1,18}", texto):
                query += " AND usuario_id = %s"
                params.append(int(texto))
            else:
                query += " AND usuario_nome ILIKE %s"
                params.append("%" + texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
        if desde:
            query += " AND quando >= %s"
            params.append(desde)
        if ate:
            query += " AND quando < %s"
            params.append(ate)
        query += " ORDER BY quando DESC, id DESC LIMIT %s"
        params.append(limite)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]


__all__ = [
    "ACOES",
    "CAMPOS_AUDITAVEIS",
    "ENTIDADES_DE_CUSTO",
    "ChangeAuditRepositoryMixin",
    "sanitizar_auditoria",
]
