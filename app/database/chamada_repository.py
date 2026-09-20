"""Botão de chamada: contatos geridos pela gestão e o histórico de chamadas."""


#: Colunas seguras para o dropdown de busca (operador e gestão comum): nunca
#: inclui ``telegram_chat_id`` — é dado de contato pessoal, só o admin vê.
_COLUNAS_CONTATO_BUSCA = "id, nome, funcao, ativo, padrao_gestao"


class ChamadaRepositoryMixin:
    def listar_chamada_contatos(self, *, somente_ativos=True, busca=None, completo=False, setor=None):
        """Lista de contatos.

        ``completo=False`` (padrão) é o dropdown de busca do operador e da
        gestão comum — nunca traz o Telegram do contato. ``completo=True`` é
        exclusivo da tela de Cadastro/Contatos, que só o admin acessa.

        ``setor``, quando informado, restringe aos contatos configurados para
        aquele setor — contato sem setor configurado (lista vazia) continua
        aparecendo em qualquer setor.
        """

        colunas = "*" if completo else _COLUNAS_CONTATO_BUSCA
        query = f"SELECT {colunas} FROM chamada_contatos"  # nosec B608 -- colunas vem só de "*" ou constante do módulo, nunca de input do usuário
        condicoes = []
        parametros = []
        if somente_ativos:
            condicoes.append("ativo = TRUE")
        termo = str(busca or "").strip()
        if termo:
            condicoes.append("(nome ILIKE %s OR funcao ILIKE %s)")
            parametros.extend([f"%{termo}%", f"%{termo}%"])
        setor = str(setor or "").strip()
        if setor:
            condicoes.append("(setores = '{}' OR %s = ANY(setores))")
            parametros.append(setor)
        if condicoes:
            query += " WHERE " + " AND ".join(condicoes)
        query += " ORDER BY nome, funcao"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, parametros)
            return [dict(row) for row in cursor.fetchall()]

    def salvar_chamada_contato(
        self,
        *,
        contato_id=None,
        nome,
        funcao,
        ativo=True,
        padrao_gestao=False,
        telegram_chat_id=None,
        setores=None,
    ):
        """Cria ou atualiza um contato. Tela de gestão, nunca o Dev Observatory.

        ``padrao_gestao`` é quem o botão de chamada da tela de gestão
        pré-seleciona. Só existe um por vez: marcar um novo desmarca o
        anterior, na mesma transação. ``telegram_chat_id`` é opcional: quando
        preenchido, a chamada para este contato avisa direto esse chat, em
        vez do chat geral do ambiente. ``setores`` vazio/None mantém o
        contato visível em todos os setores.
        """

        nome = str(nome or "").strip()
        funcao = str(funcao or "").strip()
        if not nome or not funcao:
            raise ValueError("Nome e função do contato são obrigatórios.")
        telegram_chat_id = str(telegram_chat_id or "").strip() or None
        setores = [str(item).strip() for item in (setores or []) if str(item).strip()]
        with self.connection() as connection, connection.cursor() as cursor:
            if padrao_gestao:
                cursor.execute("UPDATE chamada_contatos SET padrao_gestao = FALSE")
            if contato_id is None:
                cursor.execute(
                    """
                    INSERT INTO chamada_contatos (nome, funcao, ativo, padrao_gestao, telegram_chat_id, setores)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (LOWER(nome), LOWER(funcao)) DO UPDATE SET
                        ativo = EXCLUDED.ativo,
                        padrao_gestao = EXCLUDED.padrao_gestao,
                        telegram_chat_id = EXCLUDED.telegram_chat_id,
                        setores = EXCLUDED.setores,
                        atualizado_em = CURRENT_TIMESTAMP
                    RETURNING *
                    """,
                    (nome, funcao, bool(ativo), bool(padrao_gestao), telegram_chat_id, setores),
                )
            else:
                cursor.execute(
                    """
                    UPDATE chamada_contatos
                    SET nome = %s, funcao = %s, ativo = %s, padrao_gestao = %s,
                        telegram_chat_id = %s, setores = %s, atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING *
                    """,
                    (nome, funcao, bool(ativo), bool(padrao_gestao), telegram_chat_id, setores, int(contato_id)),
                )
            row = cursor.fetchone()
            if row is None:
                raise ValueError("Contato de chamada não encontrado.")
            return dict(row)

    def buscar_contato_padrao_gestao(self):
        """Contato pré-selecionado no botão de chamada da tela de gestão."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT {_COLUNAS_CONTATO_BUSCA} FROM chamada_contatos "  # nosec B608 -- lista de colunas é constante do módulo
                "WHERE padrao_gestao = TRUE AND ativo = TRUE LIMIT 1"
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def remover_chamada_contato(self, contato_id):
        """Remove o contato do dropdown; chamadas antigas preservam nome/função."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM chamada_contatos WHERE id = %s RETURNING id",
                (int(contato_id),),
            )
            return cursor.fetchone() is not None

    def registrar_chamada(
        self,
        *,
        contato_id,
        motivo,
        comentario,
        solicitante_nome,
        solicitante_nivel,
        solicitante_cracha=None,
        solicitante_email=None,
    ):
        """Grava a chamada com o retrato do contato no momento da chamada.

        ``solicitante_cracha``/``solicitante_email`` identificam quem de fato
        chamou quando o login é compartilhado (posto do operador, conta
        genérica da gestão) — a obrigatoriedade por perfil é decidida no
        endpoint, não aqui.
        """

        motivo = str(motivo or "").strip()
        comentario = str(comentario or "").strip()
        if not motivo or not comentario:
            raise ValueError("Motivo e comentário da chamada são obrigatórios.")
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT nome, funcao, telegram_chat_id FROM chamada_contatos "
                "WHERE id = %s AND ativo = TRUE",
                (int(contato_id),),
            )
            contato = cursor.fetchone()
            if contato is None:
                raise ValueError("Contato selecionado não existe ou não está mais ativo.")
            cursor.execute(
                """
                INSERT INTO chamadas (
                    contato_id, contato_nome, contato_funcao, motivo, comentario,
                    solicitante_nome, solicitante_nivel, solicitante_cracha, solicitante_email
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    int(contato_id),
                    contato["nome"],
                    contato["funcao"],
                    motivo,
                    comentario,
                    str(solicitante_nome or "").strip(),
                    str(solicitante_nivel or "").strip(),
                    str(solicitante_cracha or "").strip() or None,
                    str(solicitante_email or "").strip() or None,
                ),
            )
            resultado = dict(cursor.fetchone())
            # Não é coluna de ``chamadas`` — é só o roteamento do envio deste
            # disparo. Quem for ler o histórico depois usa contato_id/nome.
            resultado["contato_telegram_chat_id"] = contato["telegram_chat_id"]
            return resultado

    def marcar_chamada_telegram(self, chamada_id, *, enviado, erro=None):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE chamadas
                SET telegram_enviado = %s, telegram_erro = %s
                WHERE id = %s
                RETURNING *
                """,
                (bool(enviado), str(erro or "").strip() or None, int(chamada_id)),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def listar_chamadas(self, *, limite=100):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM chamadas ORDER BY criado_em DESC LIMIT %s",
                (int(limite),),
            )
            return [dict(row) for row in cursor.fetchall()]

    def contar_chamadas_nao_vistas(self, usuario_id):
        """Sininho pessoal: quantas chamadas têm id maior que a última vista.

        Compara por id (monotônico), não por timestamp: duas chamadas no
        mesmo segundo do relógio nunca empatam. Sem linha em
        ``chamada_visualizacoes``, a conta nunca viu nada ainda — toda
        chamada existente conta, em vez de começar "zerada" e esconder
        histórico anterior ao primeiro acesso.
        """

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS total
                FROM chamadas
                WHERE id > COALESCE(
                    (SELECT ultima_chamada_vista_id FROM chamada_visualizacoes WHERE usuario_id = %s),
                    0
                )
                """,
                (int(usuario_id),),
            )
            return int(cursor.fetchone()["total"])

    def marcar_chamadas_vistas(self, usuario_id):
        """Ancora o sininho no maior id de chamada existente agora."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO chamada_visualizacoes (usuario_id, ultima_chamada_vista_id)
                VALUES (%s, COALESCE((SELECT MAX(id) FROM chamadas), 0))
                ON CONFLICT (usuario_id) DO UPDATE SET
                    ultima_chamada_vista_id = EXCLUDED.ultima_chamada_vista_id
                RETURNING ultima_chamada_vista_id
                """,
                (int(usuario_id),),
            )
            return int(cursor.fetchone()["ultima_chamada_vista_id"])
