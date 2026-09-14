"""Persistência técnica da IA, isolada das tabelas e eventos produtivos."""

from __future__ import annotations

from psycopg.types.json import Jsonb


def _conversation(row, messages=None):
    if not row:
        return None
    item = dict(row)
    if messages is not None:
        item["messages"] = [dict(message) for message in messages]
    return item


class AIRepositoryMixin:
    """Operações restritas às três tabelas técnicas da IA Industrial."""

    def criar_conversa_ia(self, user_id: int, title: str):
        clean_title = " ".join(str(title or "").split())[:160]
        if not clean_title:
            raise ValueError("O título da conversa é obrigatório.")
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO ai_conversations (user_id, title)
                VALUES (%s, %s)
                RETURNING id, user_id, title, created_at, updated_at
                """,
                (int(user_id), clean_title),
            )
            return _conversation(cursor.fetchone())

    def listar_conversas_ia(self, user_id: int, *, limit: int = 100):
        safe_limit = max(1, min(100, int(limit)))
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, user_id, title, created_at, updated_at
                FROM ai_conversations
                WHERE user_id = %s
                ORDER BY updated_at DESC, id DESC
                LIMIT %s
                """,
                (int(user_id), safe_limit),
            )
            return [_conversation(row) for row in cursor.fetchall()]

    def obter_conversa_ia(
        self,
        conversation_id: int,
        user_id: int,
        *,
        message_limit: int | None = None,
    ):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, user_id, title, created_at, updated_at
                FROM ai_conversations
                WHERE id = %s AND user_id = %s
                """,
                (int(conversation_id), int(user_id)),
            )
            conversation = cursor.fetchone()
            if not conversation:
                return None
            if message_limit is None:
                cursor.execute(
                    """
                    SELECT id, conversation_id, role, content, model, created_at, metadata
                    FROM ai_messages
                    WHERE conversation_id = %s
                    ORDER BY created_at, id
                    """,
                    (int(conversation_id),),
                )
            else:
                safe_limit = max(1, min(100, int(message_limit)))
                cursor.execute(
                    """
                    SELECT * FROM (
                        SELECT id, conversation_id, role, content, model, created_at, metadata
                        FROM ai_messages
                        WHERE conversation_id = %s
                        ORDER BY created_at DESC, id DESC
                        LIMIT %s
                    ) AS recent_messages
                    ORDER BY created_at, id
                    """,
                    (int(conversation_id), safe_limit),
                )
            return _conversation(conversation, cursor.fetchall())

    def atualizar_titulo_conversa_ia(self, conversation_id: int, user_id: int, title: str):
        clean_title = " ".join(str(title or "").split())[:160]
        if not clean_title:
            raise ValueError("O título da conversa é obrigatório.")
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE ai_conversations
                SET title = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND user_id = %s
                RETURNING id, user_id, title, created_at, updated_at
                """,
                (clean_title, int(conversation_id), int(user_id)),
            )
            return _conversation(cursor.fetchone())

    def excluir_conversa_ia(self, conversation_id: int, user_id: int) -> bool:
        """Exclui somente a conversa técnica pertencente ao usuário informado."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                DELETE FROM ai_conversations
                WHERE id = %s AND user_id = %s
                RETURNING id
                """,
                (int(conversation_id), int(user_id)),
            )
            return cursor.fetchone() is not None

    def adicionar_mensagem_ia(
        self,
        conversation_id: int,
        user_id: int,
        role: str,
        content: str,
        *,
        model: str | None = None,
        metadata: dict | None = None,
    ):
        clean_role = str(role or "").strip().casefold()
        clean_content = str(content or "").strip()
        if clean_role not in {"user", "assistant"}:
            raise ValueError("Papel de mensagem da IA inválido.")
        if not clean_content:
            raise ValueError("A mensagem da IA não pode ficar vazia.")
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM ai_conversations
                WHERE id = %s AND user_id = %s
                FOR UPDATE
                """,
                (int(conversation_id), int(user_id)),
            )
            if not cursor.fetchone():
                return None
            cursor.execute(
                """
                INSERT INTO ai_messages (
                    conversation_id, role, content, model, metadata
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING id, conversation_id, role, content, model, created_at, metadata
                """,
                (
                    int(conversation_id),
                    clean_role,
                    clean_content,
                    str(model).strip() if model else None,
                    Jsonb(dict(metadata or {})),
                ),
            )
            message = dict(cursor.fetchone())
            cursor.execute(
                """
                UPDATE ai_conversations
                SET updated_at = %s
                WHERE id = %s
                """,
                (message["created_at"], int(conversation_id)),
            )
            return message

    def listar_conhecimento_ia_validado(self, *, limit: int = 100):
        safe_limit = max(1, min(100, int(limit)))
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, tipo, conteudo, origem, status_validacao, created_at, updated_at
                FROM ai_knowledge
                WHERE status_validacao = 'validado'
                ORDER BY updated_at DESC, id DESC
                LIMIT %s
                """,
                (safe_limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
