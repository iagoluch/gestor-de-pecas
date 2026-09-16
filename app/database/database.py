"""Facade de persistência PostgreSQL consumida pelo backend Web."""

import csv
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
import hashlib
import hmac
import logging
import os

from psycopg.errors import UniqueViolation

from app.core.constants import FMT_DB
from app.core.normalization import limpa_codigo, normalizar_data_db
from app.core.operator_sectors import WELDING_STEEL_SECTOR
from app.database.config import PostgresConfig, load_postgres_config
from app.database.ai_repository import AIRepositoryMixin
from app.database.chamada_repository import ChamadaRepositoryMixin
from app.database.first_piece_repository import FirstPieceRepositoryMixin
from app.database.quality_repository import QualityRepositoryMixin
from app.database.report_repository import ReportRepositoryMixin
from app.database.sigmanest_repository import SigmaNestRepositoryMixin
from app.database.totvs_repository import TotvsRepositoryMixin
from app.database.totvs_outbound_repository import TotvsOutboundRepositoryMixin
from app.database.totvs_outbox_repository import TotvsOutboxRepositoryMixin
from app.database.totvs_op_sync_repository import TotvsOpSyncRepositoryMixin
from app.database.welding_repository import WeldingRepositoryMixin
from app.database.connection import PostgresPoolManager
from app.database.diagnostics import run_database_diagnostic
from app.database.errors import DatabaseConfigurationError, DatabaseIntegrityError
from app.database.migrations import apply_migrations
from app.database.schema import SCHEMA_VERSION
from mes.integrations.totvs.outbound_enqueue import (
    load_outbound_enqueue_config,
    plan_execution_event,
    plan_terminal_milestone,
)
from mes.domain import (
    EXECUTING_APPOINTMENT_STATUSES,
    ManufacturingRules,
    PHYSICAL_STATE_VALUES,
    SIGMANEST_LASER_MACHINE,
    OperatorState,
    can_transition,
    operator_state_from_status,
    operator_status_for_state,
    return_state_for_transition,
)


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
LEGACY_PASSWORD_ITERATIONS = 100_000
CATALOG_SYNC_LOCK_ID = 874_210_307

#: Setor cujo cadastro só é publicado em tela depois de comprovar uso real.
#:
#: Wave 6F — a Solda Aço herdou do PC Factory 41 recursos que são etapas de
#: solda históricas, sem posto físico e sem aparecer no roteiro de nenhuma OP.
#: Eles continuam no catálogo (rastreabilidade e sincronização com o TOTVS), mas
#: ficam fora das listagens até uma OP real referenciá-los. A regra é desse
#: setor e só dele: não existe filtro geral de "esconder recurso sem uso".
CATALOG_ONLY_RESOURCE_SECTOR = WELDING_STEEL_SECTOR


def agora_db():
    """Return the current local timestamp normalized for persistence."""
    return datetime.now().replace(microsecond=0)


def _as_dict(row):
    return dict(row) if row else None


def _task_dict(row):
    item = _as_dict(row)
    if item and item.get("espessura") is not None:
        item["espessura"] = float(item["espessura"])
    return item


def _period_value(value):
    return normalizar_data_db(value) if value is not None else None


__all__ = ["Database", "FMT_DB", "SCHEMA_VERSION", "agora_db", "limpa_codigo", "normalizar_data_db"]


class Database(
    SigmaNestRepositoryMixin,
    TotvsRepositoryMixin,
    TotvsOutboundRepositoryMixin,
    TotvsOutboxRepositoryMixin,
    TotvsOpSyncRepositoryMixin,
    ChamadaRepositoryMixin,
    QualityRepositoryMixin,
    WeldingRepositoryMixin,
    FirstPieceRepositoryMixin,
    ReportRepositoryMixin,
    AIRepositoryMixin,
):
    """Stable facade backed exclusively by PostgreSQL."""

    schema_version = SCHEMA_VERSION

    def __init__(
        self,
        dsn=None,
        *,
        config=None,
        pool_manager=None,
        auto_migrate=True,
        now_func=None,
        totvs_outbox_config=None,
    ):
        if pool_manager is None:
            if config is None:
                config = PostgresConfig(str(dsn)) if dsn else load_postgres_config(testing=True)
            target_name = str(config.safe_target.get("dbname") or "").strip()
            if "test" not in target_name.casefold():
                raise DatabaseConfigurationError(
                    "O Gestor de Peças está bloqueado para bancos de teste; "
                    "o nome do banco deve conter 'test'."
                )
            pool_manager = PostgresPoolManager(config)
        self._pool = pool_manager
        self._now = lambda: (now_func() if now_func is not None else agora_db()).replace(
            microsecond=0
        )
        self._closed = False
        # Configuração da outbox TOTVS por ambiente. Nasce desabilitada e nunca
        # depende do nome do banco: o mesmo código serve TESTE e piloto REAL.
        self.totvs_outbox_config = (
            totvs_outbox_config
            if totvs_outbox_config is not None
            else load_outbound_enqueue_config()
        )
        self.safe_target = getattr(getattr(pool_manager, "config", None), "safe_target", {})
        if auto_migrate:
            with self.connection() as connection:
                apply_migrations(connection)

    def connection(self):
        return self._pool.connection()

    @contextmanager
    def catalog_sync_lock(self):
        """Hold one cross-process catalog synchronization lease."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s) AS acquired", (CATALOG_SYNC_LOCK_ID,))
            acquired = bool(cursor.fetchone()["acquired"])
            try:
                yield acquired
            finally:
                if acquired:
                    cursor.execute("SELECT pg_advisory_unlock(%s)", (CATALOG_SYNC_LOCK_ID,))

    def connect(self):
        """Compatibility lease; prefer ``with db.connection()`` in new code."""
        return self._pool.get_connection()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._pool.close()

    def create_tables(self):
        with self.connection() as connection:
            return apply_migrations(connection)

    def ensure_indices(self):
        return self.create_tables()

    def ensure_schema_version(self):
        return self.create_tables()

    def obter_schema_version(self):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations")
            return int(cursor.fetchone()["version"])

    def _hash_senha(self, senha, salt=None):
        salt_bytes = os.urandom(32) if salt is None else bytes.fromhex(salt)
        hash_obj = hashlib.pbkdf2_hmac(
            "sha256", senha.encode("utf-8"), salt_bytes, PASSWORD_ITERATIONS
        )
        return f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}${salt_bytes.hex()}${hash_obj.hex()}"

    def _verificar_senha(self, senha, hash_senha):
        try:
            if str(hash_senha).startswith(f"{PASSWORD_SCHEME}$"):
                scheme, iterations_text, salt_hex, hash_hex = str(hash_senha).split("$", 3)
                if scheme != PASSWORD_SCHEME:
                    return False
                iterations = int(iterations_text)
                if iterations <= 0:
                    return False
            else:
                salt_hex, hash_hex = str(hash_senha).split(":", 1)
                iterations = LEGACY_PASSWORD_ITERATIONS
            hash_calc = hashlib.pbkdf2_hmac(
                "sha256", senha.encode("utf-8"), bytes.fromhex(salt_hex), iterations
            )
            return hmac.compare_digest(hash_calc, bytes.fromhex(hash_hex))
        except (AttributeError, TypeError, ValueError):
            return False

    @staticmethod
    def _senha_precisa_rehash(hash_senha):
        return not str(hash_senha or "").startswith(
            f"{PASSWORD_SCHEME}${PASSWORD_ITERATIONS}$"
        )

    def criar_usuario(self, nome, senha, nivel="operador_destaque"):
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO usuarios (nome, senha_hash, nivel, ativo, data_criacao)
                    VALUES (%s, %s, %s, TRUE, %s)
                    RETURNING id
                    """,
                    (nome, self._hash_senha(senha), nivel, agora_db()),
                )
                return int(cursor.fetchone()["id"])
        except UniqueViolation as exc:
            if exc.diag.constraint_name == "uq_usuarios_nome":
                return None
            raise

    def autenticar_usuario(self, nome, senha):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, nome, senha_hash, nivel FROM usuarios WHERE nome = %s AND ativo IS TRUE",
                (nome,),
            )
            row = cursor.fetchone()
            if not row or not self._verificar_senha(senha, row["senha_hash"]):
                return None
            if self._senha_precisa_rehash(row["senha_hash"]):
                cursor.execute(
                    "UPDATE usuarios SET senha_hash = %s WHERE id = %s",
                    (self._hash_senha(senha), row["id"]),
                )
            return dict(row)

    def usuario_existe(self, nome):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT EXISTS(SELECT 1 FROM usuarios WHERE nome = %s) AS existe", (nome,))
            return bool(cursor.fetchone()["existe"])

    def obter_nivel_usuario_por_nome(self, nome):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT nivel FROM usuarios WHERE nome = %s", (nome,))
            row = cursor.fetchone()
            return row["nivel"] if row else None

    def listar_usuarios(self):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id, nome, nivel, ativo, data_criacao FROM usuarios ORDER BY nome")
            return [dict(row) for row in cursor.fetchall()]


    def inserir_historico(
        self, op, tipo, setor, motivo, quantidade, operador, peca="", tarefa_id=None, data_hora=None
    ):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO historico (op, tipo, setor, motivo, quantidade, operador, data_hora, peca, tarefa_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (op, tipo, setor, motivo, int(quantidade), operador, _period_value(data_hora) or agora_db(), peca, tarefa_id),
            )
            return int(cursor.fetchone()["id"])

    def registrar_evento_sistema(
        self, tipo, origem, mensagem, operador=None, referencia=None, detalhes=None, data_hora=None
    ):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO eventos_sistema
                    (tipo, origem, referencia, mensagem, operador, detalhes, data_hora)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (tipo, origem, referencia, mensagem, operador, detalhes, _period_value(data_hora) or agora_db()),
            )
            return int(cursor.fetchone()["id"])

    def ultimo_evento_sistema(self, tipos=None, origem=None):
        query = "SELECT * FROM eventos_sistema WHERE TRUE"
        params = []
        if tipos:
            query += " AND tipo = ANY(%s)"
            params.append(list(tipos))
        if origem:
            query += " AND origem = %s"
            params.append(origem)
        query += " ORDER BY data_hora DESC, id DESC LIMIT 1"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return _as_dict(cursor.fetchone())

    def ultimo_status_sincronizacao(self):
        """Compatibilidade: não consulta rede e informa a integração pendente."""

        return {
            "status": "Pendente TI",
            "mensagem": "Integração Protheus/TOTVS ainda não configurada.",
            "data_hora": "",
            "referencia": "TOTVS",
        }

    def obter_ultimo_estado_sincronizacao(self):
        """Nome explicito para novos consumidores, mantendo a API anterior."""

        return self.ultimo_status_sincronizacao()

    def diagnostico_integridade(self):
        try:
            return run_database_diagnostic(self)
        except Exception as exc:
            logging.exception("Falha ao executar diagnóstico PostgreSQL")
            return {
                "ok": False,
                "mensagem": str(exc),
                "target": self.safe_target,
                "schema_version": None,
                "missing_tables": [],
                "tabelas": {},
            }

    def buscar_tarefa_por_codigo(self, codigo_tarefa):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM tarefas WHERE codigo_tarefa = %s", (limpa_codigo(codigo_tarefa),))
            return _task_dict(cursor.fetchone())

    def buscar_tarefa_por_id(self, tarefa_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM tarefas WHERE id = %s", (tarefa_id,))
            return _task_dict(cursor.fetchone())

    def listar_tarefas(self):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM tarefas ORDER BY data_inicio_destaque DESC NULLS LAST, id DESC")
            return [_task_dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _upsert_tarefa_cursor(cursor, codigo, material=None, espessura=None):
        cursor.execute(
            """
            INSERT INTO tarefas (codigo_tarefa, material, espessura)
            VALUES (%s, %s, %s)
            ON CONFLICT (codigo_tarefa) DO UPDATE
            SET material = COALESCE(EXCLUDED.material, tarefas.material),
                espessura = COALESCE(EXCLUDED.espessura, tarefas.espessura)
            RETURNING id
            """,
            (codigo, material, espessura),
        )
        return int(cursor.fetchone()["id"])

    def inserir_tarefa(self, codigo_tarefa, material=None, espessura=None):
        codigo = limpa_codigo(codigo_tarefa)
        with self.connection() as connection, connection.cursor() as cursor:
            return self._upsert_tarefa_cursor(cursor, codigo, material, espessura)

    def listar_ops_por_tarefa(self, tarefa_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM op_por_tarefa WHERE tarefa_id = %s ORDER BY id", (tarefa_id,))
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def _upsert_op_cursor(cursor, tarefa_id, codigo, id_peca, setor_destino, quantidade):
        qtd = int(quantidade)
        cursor.execute(
            """
            INSERT INTO op_por_tarefa (
                tarefa_id, codigo_op, id_peca, setor_destino_original,
                setor_destino_atual, quantidade_original, quantidade_atual, editado
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT (tarefa_id, codigo_op) DO UPDATE
            SET id_peca = EXCLUDED.id_peca,
                setor_destino_original = EXCLUDED.setor_destino_original,
                setor_destino_atual = EXCLUDED.setor_destino_atual,
                quantidade_original = EXCLUDED.quantidade_original,
                quantidade_atual = EXCLUDED.quantidade_atual
            WHERE op_por_tarefa.editado IS FALSE
            RETURNING id
            """,
            (tarefa_id, codigo, id_peca, setor_destino, setor_destino, qtd, qtd),
        )
        row = cursor.fetchone()
        if row:
            return int(row["id"])
        cursor.execute(
            "SELECT id FROM op_por_tarefa WHERE tarefa_id = %s AND codigo_op = %s",
            (tarefa_id, codigo),
        )
        return int(cursor.fetchone()["id"])

    def inserir_op_na_tarefa(self, tarefa_id, codigo_op, id_peca, setor_destino, quantidade):
        codigo = limpa_codigo(codigo_op)
        with self.connection() as connection, connection.cursor() as cursor:
            return self._upsert_op_cursor(
                cursor, tarefa_id, codigo, id_peca, setor_destino, quantidade
            )

    def publicar_catalogo_pcp(self, registros, sincronizado_em=None):
        """Publish one validated PCP snapshot without touching operational rows."""

        sincronizado_em = normalizar_data_db(sincronizado_em) or agora_db()
        normalizados = []
        codigos = set()
        for item in registros:
            codigo = limpa_codigo(item.get("codigo_op"))
            if not codigo or codigo in codigos:
                raise ValueError(f"Catálogo PCP possui OP vazia ou duplicada: {codigo or '<vazia>'}")
            codigos.add(codigo)
            quantidade = int(item.get("quantidade") or 0)
            if quantidade <= 0:
                raise ValueError(f"Quantidade PCP inválida para {codigo}: {quantidade}")
            emissao = normalizar_data_db(item.get("data_emissao"))
            if emissao is None:
                raise ValueError(f"Data de emissão PCP ausente para {codigo}")
            produto = limpa_codigo(item.get("produto_codigo"))
            descricao = str(item.get("produto_descricao") or "").strip()
            if not produto or not descricao:
                raise ValueError(f"Produto/descrição PCP ausente para {codigo}")
            normalizados.append((
                codigo,
                produto,
                descricao,
                quantidade,
                str(item.get("unidade") or "").strip(),
                emissao.date(),
                str(item.get("status_pcp") or "").strip(),
                str(item.get("filial") or "").strip(),
                str(item.get("local_estoque") or "").strip(),
                str(item.get("roteiro") or "").strip(),
                str(item.get("recurso") or "").strip(),
                sincronizado_em,
            ))
        if not normalizados:
            raise ValueError("Snapshot PCP vazio; catálogo anterior foi preservado.")

        columns = (
            "codigo_op, produto_codigo, produto_descricao, quantidade, unidade, "
            "data_emissao, status_pcp, filial, local_estoque, roteiro, recurso, "
            "ativo, sincronizado_em"
        )
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "CREATE TEMP TABLE tmp_catalogo_pcp_ops "
                "(LIKE catalogo_pcp_ops INCLUDING DEFAULTS) ON COMMIT DROP"
            )
            cursor.executemany(
                """
                INSERT INTO tmp_catalogo_pcp_ops (
                    codigo_op, produto_codigo, produto_descricao, quantidade, unidade,
                    data_emissao, status_pcp, filial, local_estoque, roteiro, recurso,
                    ativo, sincronizado_em
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                """,
                normalizados,
            )
            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE atual.codigo_op IS NULL) AS inseridos,
                    COUNT(*) FILTER (WHERE atual.codigo_op IS NOT NULL) AS atualizados
                FROM tmp_catalogo_pcp_ops novo
                LEFT JOIN catalogo_pcp_ops atual USING (codigo_op)
                """
            )
            counts = cursor.fetchone()
            cursor.execute(
                f"""
                INSERT INTO catalogo_pcp_ops ({columns})
                SELECT {columns} FROM tmp_catalogo_pcp_ops
                ON CONFLICT (codigo_op) DO UPDATE SET
                    produto_codigo = EXCLUDED.produto_codigo,
                    produto_descricao = EXCLUDED.produto_descricao,
                    quantidade = EXCLUDED.quantidade,
                    unidade = EXCLUDED.unidade,
                    data_emissao = EXCLUDED.data_emissao,
                    status_pcp = EXCLUDED.status_pcp,
                    filial = EXCLUDED.filial,
                    local_estoque = EXCLUDED.local_estoque,
                    roteiro = EXCLUDED.roteiro,
                    recurso = EXCLUDED.recurso,
                    ativo = TRUE,
                    sincronizado_em = EXCLUDED.sincronizado_em
                """
            )
            cursor.execute(
                """
                UPDATE catalogo_pcp_ops atual
                SET ativo = FALSE, sincronizado_em = %s
                WHERE atual.ativo IS TRUE
                  AND NOT EXISTS (
                      SELECT 1 FROM tmp_catalogo_pcp_ops novo
                      WHERE novo.codigo_op = atual.codigo_op
                  )
                """,
                (sincronizado_em,),
            )
            inativados = cursor.rowcount
        return {
            "lidos": len(normalizados),
            "inseridos": int(counts["inseridos"]),
            "atualizados": int(counts["atualizados"]),
            "inativados": int(inativados),
        }

    def publicar_catalogo_sigmanest(
        self, tarefas, programas, ops, sincronizado_em=None, planos_corte=None
    ):
        """Publish task, program, and task/OP snapshots in one transaction."""

        sincronizado_em = normalizar_data_db(sincronizado_em) or agora_db()
        tarefas_rows = []
        tarefas_ids = set()
        for item in tarefas:
            codigo = limpa_codigo(item.get("codigo_tarefa"))
            if not codigo or codigo in tarefas_ids:
                raise ValueError(f"Tarefa SIGMANEST vazia ou duplicada: {codigo or '<vazia>'}")
            tarefas_ids.add(codigo)
            espessura = item.get("espessura")
            tarefas_rows.append((
                codigo,
                str(item.get("material") or "").strip() or None,
                float(espessura) if espessura not in (None, "") else None,
                sincronizado_em,
            ))
        if not tarefas_rows:
            raise ValueError("Snapshot SIGMANEST vazio; catálogo anterior foi preservado.")

        programas_rows = []
        programas_ids = set()
        for item in programas:
            key = (limpa_codigo(item.get("codigo_tarefa")), str(item.get("programa") or "").strip())
            if not key[0] or not key[1] or key in programas_ids:
                continue
            programas_ids.add(key)
            programas_rows.append((*key, sincronizado_em))

        ops_rows = []
        linhas = set()
        for item in ops:
            linha_hash = str(item.get("linha_hash") or "").strip()
            tarefa = limpa_codigo(item.get("codigo_tarefa"))
            op = limpa_codigo(item.get("codigo_op"))
            if not linha_hash or not tarefa or not op or linha_hash in linhas:
                continue
            if tarefa not in tarefas_ids:
                continue
            linhas.add(linha_hash)
            ops_rows.append((
                linha_hash,
                tarefa,
                # Programa em que a peça foi aninhada. Anulável: publicações
                # antigas não o informam e continuam válidas.
                str(item.get("programa") or "").strip() or None,
                op,
                str(item.get("id_peca") or "").strip(),
                str(item.get("setor_destino") or "Almoxarifado").strip(),
                max(0, int(item.get("quantidade") or 0)),
                str(item.get("dobra") or "").strip() or None,
                str(item.get("usinagem") or "").strip() or None,
                str(item.get("solda") or "").strip() or None,
                str(item.get("chanfro") or "").strip() or None,
                sincronizado_em,
            ))

        planos_rows = None
        if planos_corte is not None:
            planos_rows = []
            planos_ids = set()
            for item in planos_corte:
                plano_hash = str(item.get("plano_hash") or "").strip()
                tarefa = limpa_codigo(item.get("codigo_tarefa"))
                programa = str(item.get("programa") or "").strip()
                maquina = str(item.get("maquina_sigmanest") or "").strip()
                data_programa = normalizar_data_db(item.get("data_programa"))
                if (
                    not plano_hash
                    or plano_hash in planos_ids
                    or tarefa not in tarefas_ids
                    or not programa
                    or not maquina
                    or data_programa is None
                ):
                    continue
                planos_ids.add(plano_hash)
                planos_rows.append((
                    plano_hash,
                    tarefa,
                    programa,
                    str(item.get("nome_chapa") or "").strip() or None,
                    max(1, int(item.get("sequencia_nesting") or 1)),
                    float(item.get("area_usada") or 0),
                    float(item.get("fracao_sucata") or 0),
                    max(1, int(item.get("quantidade_processo") or 1)),
                    maquina,
                    float(item.get("tempo_previsto_segundos") or 0),
                    str(item.get("tempo_previsto_formatado") or "").strip() or None,
                    data_programa.date(),
                    str(item.get("status_programa") or "").strip() or None,
                    sincronizado_em,
                ))
            if not planos_rows:
                raise ValueError(
                    "Snapshot de planos de Corte vazio; catálogo anterior foi preservado."
                )

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "CREATE TEMP TABLE tmp_catalogo_sig_tarefas "
                "(LIKE catalogo_sigmanest_tarefas INCLUDING DEFAULTS) ON COMMIT DROP"
            )
            cursor.execute(
                "CREATE TEMP TABLE tmp_catalogo_sig_programas "
                "(LIKE catalogo_sigmanest_programas INCLUDING DEFAULTS) ON COMMIT DROP"
            )
            cursor.execute(
                "CREATE TEMP TABLE tmp_catalogo_sig_ops "
                "(LIKE catalogo_sigmanest_ops INCLUDING DEFAULTS) ON COMMIT DROP"
            )
            if planos_rows is not None:
                cursor.execute(
                    "CREATE TEMP TABLE tmp_catalogo_sig_planos_corte "
                    "(LIKE catalogo_sigmanest_planos_corte INCLUDING DEFAULTS) ON COMMIT DROP"
                )
            cursor.executemany(
                """
                INSERT INTO tmp_catalogo_sig_tarefas
                    (codigo_tarefa, material, espessura, ativo, sincronizado_em)
                VALUES (%s, %s, %s, TRUE, %s)
                """,
                tarefas_rows,
            )
            if programas_rows:
                cursor.executemany(
                    """
                    INSERT INTO tmp_catalogo_sig_programas
                        (codigo_tarefa, programa, ativo, sincronizado_em)
                    VALUES (%s, %s, TRUE, %s)
                    """,
                    programas_rows,
                )
            if ops_rows:
                cursor.executemany(
                    """
                    INSERT INTO tmp_catalogo_sig_ops
                        (linha_hash, codigo_tarefa, programa, codigo_op, id_peca,
                         setor_destino, quantidade, dobra, usinagem, solda, chanfro,
                         ativo, sincronizado_em)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                    """,
                    ops_rows,
                )
            if planos_rows is not None:
                cursor.executemany(
                    """
                    INSERT INTO tmp_catalogo_sig_planos_corte (
                        plano_hash, codigo_tarefa, programa, nome_chapa, sequencia_nesting,
                        area_usada, fracao_sucata, quantidade_processo, maquina_sigmanest,
                        tempo_previsto_segundos, tempo_previsto_formatado, data_programa,
                        status_programa, ativo, sincronizado_em
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s
                    )
                    """,
                    planos_rows,
                )

            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE atual.codigo_tarefa IS NULL) AS inseridos,
                    COUNT(*) FILTER (WHERE atual.codigo_tarefa IS NOT NULL) AS atualizados
                FROM tmp_catalogo_sig_tarefas novo
                LEFT JOIN catalogo_sigmanest_tarefas atual USING (codigo_tarefa)
                """
            )
            task_counts = cursor.fetchone()
            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE atual.codigo_tarefa IS NULL) AS inseridos,
                    COUNT(*) FILTER (WHERE atual.codigo_tarefa IS NOT NULL) AS atualizados
                FROM tmp_catalogo_sig_programas novo
                LEFT JOIN catalogo_sigmanest_programas atual
                  ON atual.codigo_tarefa = novo.codigo_tarefa
                 AND atual.programa = novo.programa
                """
            )
            program_counts = cursor.fetchone()
            cursor.execute(
                """
                SELECT
                    COUNT(*) FILTER (WHERE atual.linha_hash IS NULL) AS inseridos,
                    COUNT(*) FILTER (WHERE atual.linha_hash IS NOT NULL) AS atualizados
                FROM tmp_catalogo_sig_ops novo
                LEFT JOIN catalogo_sigmanest_ops atual USING (linha_hash)
                """
            )
            op_counts = cursor.fetchone()
            plan_counts = {"inseridos": 0, "atualizados": 0}
            if planos_rows is not None:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) FILTER (WHERE atual.plano_hash IS NULL) AS inseridos,
                        COUNT(*) FILTER (WHERE atual.plano_hash IS NOT NULL) AS atualizados
                    FROM tmp_catalogo_sig_planos_corte novo
                    LEFT JOIN catalogo_sigmanest_planos_corte atual USING (plano_hash)
                    """
                )
                plan_counts = cursor.fetchone()

            cursor.execute(
                """
                INSERT INTO catalogo_sigmanest_tarefas
                    (codigo_tarefa, material, espessura, ativo, sincronizado_em)
                SELECT codigo_tarefa, material, espessura, ativo, sincronizado_em
                FROM tmp_catalogo_sig_tarefas
                ON CONFLICT (codigo_tarefa) DO UPDATE SET
                    material = EXCLUDED.material,
                    espessura = EXCLUDED.espessura,
                    ativo = TRUE,
                    sincronizado_em = EXCLUDED.sincronizado_em
                """
            )
            cursor.execute(
                """
                UPDATE catalogo_sigmanest_tarefas atual
                SET ativo = FALSE, sincronizado_em = %s
                WHERE atual.ativo IS TRUE
                  AND NOT EXISTS (
                      SELECT 1 FROM tmp_catalogo_sig_tarefas novo
                      WHERE novo.codigo_tarefa = atual.codigo_tarefa
                  )
                """,
                (sincronizado_em,),
            )
            tarefas_inativas = cursor.rowcount

            cursor.execute(
                """
                INSERT INTO catalogo_sigmanest_programas
                    (codigo_tarefa, programa, ativo, sincronizado_em)
                SELECT codigo_tarefa, programa, ativo, sincronizado_em
                FROM tmp_catalogo_sig_programas
                ON CONFLICT (codigo_tarefa, programa) DO UPDATE SET
                    ativo = TRUE,
                    sincronizado_em = EXCLUDED.sincronizado_em
                """
            )
            cursor.execute(
                """
                UPDATE catalogo_sigmanest_programas atual
                SET ativo = FALSE, sincronizado_em = %s
                WHERE atual.ativo IS TRUE
                  AND NOT EXISTS (
                      SELECT 1 FROM tmp_catalogo_sig_programas novo
                      WHERE novo.codigo_tarefa = atual.codigo_tarefa
                        AND novo.programa = atual.programa
                  )
                """,
                (sincronizado_em,),
            )
            programas_inativos = cursor.rowcount

            cursor.execute(
                """
                INSERT INTO catalogo_sigmanest_ops
                    (linha_hash, codigo_tarefa, programa, codigo_op, id_peca,
                     setor_destino, quantidade, dobra, usinagem, solda, chanfro,
                     ativo, sincronizado_em)
                SELECT linha_hash, codigo_tarefa, programa, codigo_op, id_peca,
                       setor_destino, quantidade, dobra, usinagem, solda, chanfro,
                       ativo, sincronizado_em
                FROM tmp_catalogo_sig_ops
                ON CONFLICT (linha_hash) DO UPDATE SET
                    codigo_tarefa = EXCLUDED.codigo_tarefa,
                    programa = EXCLUDED.programa,
                    codigo_op = EXCLUDED.codigo_op,
                    id_peca = EXCLUDED.id_peca,
                    setor_destino = EXCLUDED.setor_destino,
                    quantidade = EXCLUDED.quantidade,
                    dobra = EXCLUDED.dobra,
                    usinagem = EXCLUDED.usinagem,
                    solda = EXCLUDED.solda,
                    chanfro = EXCLUDED.chanfro,
                    ativo = TRUE,
                    sincronizado_em = EXCLUDED.sincronizado_em
                """
            )
            cursor.execute(
                """
                UPDATE catalogo_sigmanest_ops atual
                SET ativo = FALSE, sincronizado_em = %s
                WHERE atual.ativo IS TRUE
                  AND NOT EXISTS (
                      SELECT 1 FROM tmp_catalogo_sig_ops novo
                      WHERE novo.linha_hash = atual.linha_hash
                  )
                """,
                (sincronizado_em,),
            )
            ops_inativas = cursor.rowcount

            planos_inativos = 0
            if planos_rows is not None:
                cursor.execute(
                    """
                    INSERT INTO catalogo_sigmanest_planos_corte (
                        plano_hash, codigo_tarefa, programa, nome_chapa, sequencia_nesting,
                        area_usada, fracao_sucata, quantidade_processo, maquina_sigmanest,
                        tempo_previsto_segundos, tempo_previsto_formatado, data_programa,
                        status_programa, ativo, sincronizado_em
                    )
                    SELECT
                        plano_hash, codigo_tarefa, programa, nome_chapa, sequencia_nesting,
                        area_usada, fracao_sucata, quantidade_processo, maquina_sigmanest,
                        tempo_previsto_segundos, tempo_previsto_formatado, data_programa,
                        status_programa, ativo, sincronizado_em
                    FROM tmp_catalogo_sig_planos_corte
                    ON CONFLICT (plano_hash) DO UPDATE SET
                        codigo_tarefa = EXCLUDED.codigo_tarefa,
                        programa = EXCLUDED.programa,
                        nome_chapa = EXCLUDED.nome_chapa,
                        sequencia_nesting = EXCLUDED.sequencia_nesting,
                        area_usada = EXCLUDED.area_usada,
                        fracao_sucata = EXCLUDED.fracao_sucata,
                        quantidade_processo = EXCLUDED.quantidade_processo,
                        maquina_sigmanest = EXCLUDED.maquina_sigmanest,
                        tempo_previsto_segundos = EXCLUDED.tempo_previsto_segundos,
                        tempo_previsto_formatado = EXCLUDED.tempo_previsto_formatado,
                        data_programa = EXCLUDED.data_programa,
                        status_programa = EXCLUDED.status_programa,
                        ativo = TRUE,
                        sincronizado_em = EXCLUDED.sincronizado_em
                    """
                )
                cursor.execute(
                    """
                    UPDATE catalogo_sigmanest_planos_corte atual
                    SET ativo = FALSE, sincronizado_em = %s
                    WHERE atual.ativo IS TRUE
                      AND NOT EXISTS (
                          SELECT 1 FROM tmp_catalogo_sig_planos_corte novo
                          WHERE novo.plano_hash = atual.plano_hash
                      )
                    """,
                    (sincronizado_em,),
                )
                planos_inativos = cursor.rowcount

        return {
            "lidos": len(tarefas_rows) + len(programas_rows) + len(ops_rows) + len(planos_rows or []),
            "inseridos": sum(int(item["inseridos"]) for item in (task_counts, program_counts, op_counts, plan_counts)),
            "atualizados": sum(int(item["atualizados"]) for item in (task_counts, program_counts, op_counts, plan_counts)),
            "tarefas": len(tarefas_rows),
            "programas": len(programas_rows),
            "ops": len(ops_rows),
            "planos_corte": len(planos_rows or []),
            "inativados": tarefas_inativas + programas_inativos + ops_inativas + planos_inativos,
        }

    def buscar_op_catalogo(self, codigo_op):
        codigo = limpa_codigo(codigo_op)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM catalogo_pcp_ops
                WHERE ativo IS TRUE
                  AND (codigo_op = %s OR LTRIM(codigo_op, '0') = LTRIM(%s, '0'))
                ORDER BY CASE WHEN codigo_op = %s THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (codigo, codigo, codigo),
            )
            return _as_dict(cursor.fetchone())

    def buscar_tarefa_catalogo(self, codigo_tarefa):
        codigo = limpa_codigo(codigo_tarefa)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM catalogo_sigmanest_tarefas WHERE codigo_tarefa = %s AND ativo IS TRUE",
                (codigo,),
            )
            return _task_dict(cursor.fetchone())

    def listar_ops_catalogo_tarefa(self, codigo_tarefa):
        """Linhas de peça da tarefa, já com o produto projetado localmente.

        O produto vem de ``catalogo_pcp_ops`` (catálogo alimentado pelo TOTVS)
        por LEFT JOIN: uma OP ainda não recebida empobrece o rótulo, nunca
        esconde a linha. A leitura é uma só por tarefa — quem agrupa a fila de
        Corte não precisa consultar OP por OP.
        """

        codigo = limpa_codigo(codigo_tarefa)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    sig.*,
                    pcp.produto_codigo,
                    pcp.produto_descricao,
                    pcp.quantidade AS quantidade_op,
                    pcp.unidade AS unidade_op
                FROM catalogo_sigmanest_ops sig
                LEFT JOIN catalogo_pcp_ops pcp
                  ON pcp.codigo_op = sig.codigo_op AND pcp.ativo IS TRUE
                WHERE sig.codigo_tarefa = %s AND sig.ativo IS TRUE
                ORDER BY sig.programa NULLS FIRST, sig.codigo_op, sig.linha_hash
                """,
                (codigo,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def materializar_tarefa_catalogo(self, codigo_tarefa):
        """Atomically create operational task/OP rows from the local catalog."""

        codigo = limpa_codigo(codigo_tarefa)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM catalogo_sigmanest_tarefas
                WHERE codigo_tarefa = %s AND ativo IS TRUE
                FOR SHARE
                """,
                (codigo,),
            )
            tarefa_catalogo = cursor.fetchone()
            if not tarefa_catalogo:
                return None
            cursor.execute(
                """
                -- A granularidade do catálogo é (tarefa, programa, OP, peça):
                -- a mesma peça aninhada em dois programas da tarefa gera duas
                -- linhas. A OP operacional, porém, é uma só; consolidar aqui
                -- preserva a quantidade por peça (a maior observada) e mantém
                -- a materialização determinística.
                SELECT
                    codigo_op,
                    id_peca,
                    MAX(quantidade) AS quantidade,
                    MIN(setor_destino) AS setor_destino
                FROM catalogo_sigmanest_ops
                WHERE codigo_tarefa = %s AND ativo IS TRUE
                GROUP BY codigo_op, id_peca
                ORDER BY codigo_op, id_peca
                """,
                (codigo,),
            )
            ops = cursor.fetchall()
            if not ops:
                return None
            tarefa_id = self._upsert_tarefa_cursor(
                cursor,
                codigo,
                tarefa_catalogo.get("material"),
                tarefa_catalogo.get("espessura"),
            )
            op_ids = []
            for op in ops:
                op_ids.append(self._upsert_op_cursor(
                    cursor,
                    tarefa_id,
                    limpa_codigo(op["codigo_op"]),
                    op.get("id_peca"),
                    op.get("setor_destino") or "Almoxarifado",
                    op.get("quantidade") or 0,
                ))
            cursor.execute("SELECT * FROM tarefas WHERE id = %s", (tarefa_id,))
            tarefa = _task_dict(cursor.fetchone())
            tarefa["op_ids"] = op_ids
            return tarefa

    def listar_fila_corte(self, data_minima, maquina_sigmanest=None, agora=None):
        """Return virtual waiting rows plus persisted in-process cut rows.

        Um nesting com ``sigmanest_comp_date`` preenchido já foi concluído no
        SigmaNEST e não representa trabalho pendente: ele sai da fila ativa,
        mas continua persistido e auditável. Nenhum apontamento é criado, o
        ``apontamentos_corte`` não é marcado como finalizado e o roteiro da OP
        não avança por causa disso — a conclusão operacional continua sendo
        exclusivamente do fluxo canônico do Gestor.
        """

        cutoff = normalizar_data_db(data_minima)
        if cutoff is None:
            raise ValueError("Data inicial da fila de Corte é obrigatória.")
        machine_clause = ""
        machine_params = []
        if maquina_sigmanest:
            machine_clause = " AND UPPER(p.maquina_sigmanest) = UPPER(%s)"
            machine_params.append(str(maquina_sigmanest).strip())
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    NULL::BIGINT AS id,
                    p.plano_hash,
                    p.codigo_tarefa,
                    p.programa,
                    p.nome_chapa,
                    p.sequencia_nesting,
                    -- Repetição da chapa no programa: é ela que diferencia
                    -- duas chapas físicas do mesmo nesting.
                    p.sigmanest_repeat_id,
                    t.material,
                    t.espessura,
                    p.maquina_sigmanest,
                    p.quantidade_processo,
                    p.tempo_previsto_segundos,
                    p.tempo_previsto_formatado,
                    p.data_programa,
                    p.area_usada,
                    p.fracao_sucata,
                    p.status_programa,
                    'Aguardando'::TEXT AS status,
                    NULL::TEXT AS operador_inicio,
                    NULL::TIMESTAMP AS data_inicio,
                    NULL::TEXT AS operador_fim,
                    NULL::TIMESTAMP AS data_fim,
                    NULL::NUMERIC AS tempo_real_segundos
                FROM catalogo_sigmanest_planos_corte p
                JOIN catalogo_sigmanest_tarefas t
                  ON t.codigo_tarefa = p.codigo_tarefa AND t.ativo IS TRUE
                LEFT JOIN apontamentos_corte a ON a.plano_hash = p.plano_hash
                WHERE p.ativo IS TRUE
                  AND p.data_programa >= %s
                  AND a.id IS NULL
                  -- Nesting já concluído no SigmaNEST não é trabalho pendente
                  -- do operador. A linha permanece persistida para histórico e
                  -- auditoria; apenas sai da fila ativa.
                  AND p.sigmanest_comp_date IS NULL
                  {machine_clause}
                """,
                [cutoff.date(), *machine_params],
            )
            waiting = [dict(row) for row in cursor.fetchall()]

            active_query = """
                SELECT
                    a.*,
                    NULL::TEXT AS tempo_previsto_formatado,
                    NULL::TEXT AS status_programa,
                    EXTRACT(EPOCH FROM (%s - a.data_inicio)) AS tempo_real_segundos
                FROM apontamentos_corte a
                WHERE a.status = 'Em processo'
            """
            active_params = [_period_value(agora) or self._now()]
            if maquina_sigmanest:
                active_query += " AND UPPER(a.maquina_sigmanest) = UPPER(%s)"
                active_params.append(str(maquina_sigmanest).strip())
            cursor.execute(active_query, active_params)
            active = [dict(row) for row in cursor.fetchall()]

            completed_query = """
                SELECT
                    a.*,
                    NULL::TEXT AS tempo_previsto_formatado,
                    NULL::TEXT AS status_programa,
                    EXTRACT(EPOCH FROM (a.data_fim - a.data_inicio)) AS tempo_real_segundos
                FROM apontamentos_corte a
                WHERE a.status = 'Finalizado'
                  AND EXISTS (
                      SELECT 1
                      FROM catalogo_sigmanest_planos_corte p
                      LEFT JOIN apontamentos_corte pendente
                        ON pendente.plano_hash = p.plano_hash
                      WHERE p.codigo_tarefa = a.codigo_tarefa
                        AND UPPER(p.maquina_sigmanest) = UPPER(a.maquina_sigmanest)
                        AND p.ativo IS TRUE
                        AND p.data_programa >= %s
                        AND p.sigmanest_comp_date IS NULL
                        AND (pendente.id IS NULL OR pendente.status = 'Em processo')
                  )
            """
            completed_params = [cutoff.date()]
            if maquina_sigmanest:
                completed_query += " AND UPPER(a.maquina_sigmanest) = UPPER(%s)"
                completed_params.append(str(maquina_sigmanest).strip())
            cursor.execute(completed_query, completed_params)
            completed = [dict(row) for row in cursor.fetchall()]
        rows = active + waiting + completed
        rows.sort(key=lambda item: (
            item.get("codigo_tarefa") or "",
            item.get("programa") or "",
            int(item.get("sequencia_nesting") or 1),
        ))
        rows.sort(
            key=lambda item: item.get("data_programa") or date.min,
            reverse=True,
        )
        rows.sort(key=lambda item: {
            "Em processo": 0,
            "Aguardando": 1,
            "Finalizado": 2,
        }.get(item.get("status"), 3))
        return rows

    def iniciar_apontamento_corte(
        self, plano_hash, maquina, operador, data_minima, data_inicio=None
    ):
        inicio = _period_value(data_inicio) or agora_db()
        cutoff = normalizar_data_db(data_minima)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT p.*, t.material, t.espessura
                FROM catalogo_sigmanest_planos_corte p
                JOIN catalogo_sigmanest_tarefas t
                  ON t.codigo_tarefa = p.codigo_tarefa AND t.ativo IS TRUE
                WHERE p.plano_hash = %s
                  AND p.ativo IS TRUE
                  AND p.data_programa >= %s
                FOR SHARE
                """,
                (str(plano_hash).strip(), cutoff.date()),
            )
            plan = cursor.fetchone()
            if not plan:
                return None
            cursor.execute(
                """
                INSERT INTO apontamentos_corte (
                    plano_hash, codigo_tarefa, programa, nome_chapa, sequencia_nesting,
                    material, espessura, maquina, maquina_sigmanest, quantidade_processo,
                    tempo_previsto_segundos, data_programa, area_usada, fracao_sucata,
                    status, operador_inicio, data_inicio
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'Em processo', %s, %s
                )
                ON CONFLICT (plano_hash) DO NOTHING
                RETURNING *
                """,
                (
                    plan["plano_hash"], plan["codigo_tarefa"], plan["programa"],
                    plan.get("nome_chapa"), plan["sequencia_nesting"], plan.get("material"),
                    plan.get("espessura"), str(maquina).strip(), plan["maquina_sigmanest"],
                    plan["quantidade_processo"], plan.get("tempo_previsto_segundos"),
                    plan.get("data_programa"), plan.get("area_usada"),
                    plan.get("fracao_sucata"), operador, inicio,
                ),
            )
            started = cursor.fetchone()
            if not started:
                return None
            self._transicionar_estado_recurso_tx(
                cursor,
                started.get("maquina"),
                "producao",
                tipo_setor="Corte",
                operador=operador,
                motivo=f"Nesting {started.get('sequencia_nesting') or ''}".strip(),
                data_hora=inicio,
                origem="corte_nesting",
                referencia_origem=f"nesting:{started.get('id')}",
                planejado=None,
                automatico=False,
            )
            return dict(started)

    def finalizar_apontamento_corte(self, apontamento_id, operador, data_fim=None):
        fim = _period_value(data_fim) or agora_db()
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE apontamentos_corte
                SET status = 'Finalizado', operador_fim = %s, data_fim = %s
                WHERE id = %s AND status = 'Em processo'
                RETURNING *, EXTRACT(EPOCH FROM (%s - data_inicio)) AS tempo_real_segundos
                """,
                (operador, fim, apontamento_id, fim),
            )
            finished = cursor.fetchone()
            if not finished:
                return None
            self._encerrar_estado_recurso_tx(
                cursor,
                finished.get("maquina"),
                fim,
                somente_origem="corte_nesting",
            )
            return dict(finished)

    def avancar_nesting_corte(
        self, apontamento_id, proximo_plano_hash, operador, data_minima, momento=None
    ):
        """Finish one nesting and start the next at the same instant atomically."""

        transicao = _period_value(momento) or agora_db()
        cutoff = normalizar_data_db(data_minima)
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT * FROM apontamentos_corte
                    WHERE id = %s AND status = 'Em processo'
                    FOR UPDATE
                    """,
                    (apontamento_id,),
                )
                current = cursor.fetchone()
                if not current:
                    return None
                cursor.execute(
                    """
                    SELECT p.*, t.material, t.espessura
                    FROM catalogo_sigmanest_planos_corte p
                    JOIN catalogo_sigmanest_tarefas t
                      ON t.codigo_tarefa = p.codigo_tarefa AND t.ativo IS TRUE
                    WHERE p.plano_hash = %s
                      AND p.codigo_tarefa = %s
                      AND UPPER(p.maquina_sigmanest) = UPPER(%s)
                      AND p.ativo IS TRUE
                      AND p.data_programa >= %s
                    FOR SHARE
                    """,
                    (
                        str(proximo_plano_hash).strip(),
                        current["codigo_tarefa"],
                        current["maquina_sigmanest"],
                        cutoff.date(),
                    ),
                )
                next_plan = cursor.fetchone()
                if not next_plan:
                    return None

                cursor.execute(
                    """
                    UPDATE apontamentos_corte
                    SET status = 'Finalizado', operador_fim = %s, data_fim = %s
                    WHERE id = %s AND status = 'Em processo'
                    RETURNING *, EXTRACT(EPOCH FROM (%s - data_inicio)) AS tempo_real_segundos
                    """,
                    (operador, transicao, apontamento_id, transicao),
                )
                finished = cursor.fetchone()
                if not finished:
                    return None
                cursor.execute(
                    """
                    INSERT INTO apontamentos_corte (
                        plano_hash, codigo_tarefa, programa, nome_chapa, sequencia_nesting,
                        material, espessura, maquina, maquina_sigmanest, quantidade_processo,
                        tempo_previsto_segundos, data_programa, area_usada, fracao_sucata,
                        status, operador_inicio, data_inicio
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        'Em processo', %s, %s
                    )
                    RETURNING *
                    """,
                    (
                        next_plan["plano_hash"], next_plan["codigo_tarefa"],
                        next_plan["programa"], next_plan.get("nome_chapa"),
                        next_plan["sequencia_nesting"], next_plan.get("material"),
                        next_plan.get("espessura"), current["maquina"],
                        next_plan["maquina_sigmanest"], next_plan["quantidade_processo"],
                        next_plan.get("tempo_previsto_segundos"),
                        next_plan.get("data_programa"), next_plan.get("area_usada"),
                        next_plan.get("fracao_sucata"), operador, transicao,
                    ),
                )
                started = cursor.fetchone()
                self._transicionar_estado_recurso_tx(
                    cursor,
                    current.get("maquina"),
                    "producao",
                    tipo_setor="Corte",
                    operador=operador,
                    motivo=f"Nesting {started.get('sequencia_nesting') or ''}".strip(),
                    data_hora=transicao,
                    origem="corte_nesting",
                    referencia_origem=f"nesting:{started.get('id')}",
                    automatico=False,
                )
                return {
                    "finalizado": dict(finished),
                    "iniciado": dict(started),
                }
        except UniqueViolation:
            return None

    def listar_apontamentos_corte(
        self, inicio=None, fim=None, maquina=None, status=None, search=None, agora=None
    ):
        query = """
            SELECT *,
                   EXTRACT(EPOCH FROM (COALESCE(data_fim, %s) - data_inicio))
                       AS tempo_real_segundos
            FROM apontamentos_corte
            WHERE TRUE
        """
        params = [_period_value(agora) or self._now()]
        if inicio:
            query += " AND data_inicio >= %s"
            params.append(_period_value(inicio))
        if fim:
            query += " AND data_inicio <= %s"
            params.append(_period_value(fim))
        if maquina:
            query += " AND UPPER(maquina) = UPPER(%s)"
            params.append(str(maquina).strip())
        if status and str(status).casefold() != "todos":
            query += " AND status = %s"
            params.append(str(status).strip())
        if search:
            pattern = f"%{str(search).strip()}%"
            query += " AND (codigo_tarefa ILIKE %s OR programa ILIKE %s OR material ILIKE %s)"
            params.extend((pattern, pattern, pattern))
        query += " ORDER BY data_inicio DESC, id DESC"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def atualizar_op(self, op_id, novo_setor, nova_quantidade):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE op_por_tarefa
                SET setor_destino_atual = %s, quantidade_atual = %s, editado = TRUE
                WHERE id = %s
                """,
                (novo_setor, int(nova_quantidade), op_id),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _after_op_correction(_connection, _op):
        """Test seam executed before correction history is written."""

    def corrigir_op_com_historico(
        self,
        op_id,
        codigo_op,
        setor_esperado,
        quantidade_esperada,
        novo_setor,
        nova_quantidade,
        operador,
        tarefa_id,
    ):
        """Atomically persist an OP correction and its audit history."""
        now = agora_db()
        quantidade_esperada = int(quantidade_esperada)
        nova_quantidade = int(nova_quantidade)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE op_por_tarefa
                SET setor_destino_atual = %s, quantidade_atual = %s, editado = TRUE
                WHERE id = %s
                  AND COALESCE(setor_destino_atual, setor_destino_original) IS NOT DISTINCT FROM %s
                  AND COALESCE(quantidade_atual, quantidade_original) = %s
                RETURNING id, codigo_op
                """,
                (novo_setor, nova_quantidade, op_id, setor_esperado, quantidade_esperada),
            )
            op = cursor.fetchone()
            if not op:
                return False
            self._after_op_correction(connection, op)
            cursor.execute(
                """
                INSERT INTO historico
                    (op, tipo, setor, motivo, quantidade, operador, data_hora, peca, tarefa_id)
                VALUES (%s, 'Correção', %s, %s, %s, %s, %s, '', %s)
                """,
                (
                    limpa_codigo(codigo_op),
                    novo_setor,
                    f"Ajuste: {setor_esperado}->{novo_setor}, qtd {quantidade_esperada}->{nova_quantidade}",
                    nova_quantidade - quantidade_esperada,
                    operador,
                    now,
                    tarefa_id,
                ),
            )
            return True

    def buscar_op_por_codigo(self, codigo_op):
        codigo = limpa_codigo(codigo_op)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM op_por_tarefa WHERE codigo_op = %s ORDER BY id LIMIT 1", (codigo,))
            row = cursor.fetchone()
            if not row and codigo:
                cursor.execute(
                    "SELECT * FROM op_por_tarefa WHERE LTRIM(codigo_op, '0') = LTRIM(%s, '0') ORDER BY id LIMIT 1",
                    (codigo,),
                )
                row = cursor.fetchone()
            return _as_dict(row)

    def listar_operacoes_para_op(self, codigo_op, tipo_setor=None):
        """Retorna o roteiro importado da OP, opcionalmente limitado ao setor."""

        query = """
            SELECT
                operacao.*,
                pcp.quantidade,
                operacao.numero_operacao AS codigo,
                operacao.descricao_operacao AS nome,
                operacao.produto_codigo AS produto,
                operacao.produto_descricao AS descricao,
                recurso.nome AS recurso_nome,
                recurso.tipo_setor AS recurso_tipo_setor
            FROM catalogo_operacoes_op operacao
            JOIN catalogo_pcp_ops pcp ON pcp.codigo_op = operacao.codigo_op
            LEFT JOIN catalogo_recursos_pcfactory recurso
              ON recurso.codigo = operacao.codigo_recurso
            WHERE operacao.codigo_op = %s
              AND operacao.ativo = TRUE
        """
        params = [limpa_codigo(codigo_op)]
        if tipo_setor:
            query += " AND UPPER(operacao.tipo_setor) = UPPER(%s)"
            params.append(str(tipo_setor).strip())
        query += " ORDER BY operacao.ordem, operacao.id"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def listar_roteiro_completo_op(self, codigo_op):
        """Retorna o snapshot vigente inteiro do roteiro, inclusive marcos.

        O sincronizador inativa o snapshot anterior antes de gravar o novo.
        INSPECAO e FINALIZADA também são inativas por contrato, portanto um
        simples ``ativo = TRUE`` omite contexto real e um simples "sem filtro"
        ressuscita versões antigas. O timestamp do último snapshot TOTVS separa
        esses dois casos sem mudar a semântica de apontamento.
        """

        codigo = limpa_codigo(codigo_op)
        query = """
            SELECT
                operacao.*,
                pcp.quantidade,
                operacao.numero_operacao AS codigo,
                operacao.descricao_operacao AS nome,
                operacao.produto_codigo AS produto,
                operacao.produto_descricao AS descricao,
                recurso.nome AS recurso_nome,
                recurso.tipo_setor AS recurso_tipo_setor,
                CASE
                    WHEN UPPER(operacao.tipo_setor) = 'CORTE' THEN
                        tarefa.status = 'Finalizado'
                        AND EXISTS (
                            SELECT 1
                            FROM catalogo_sigmanest_planos_corte plano
                            WHERE plano.codigo_tarefa = tarefa.codigo_tarefa
                              AND plano.ativo = TRUE
                        )
                        AND NOT EXISTS (
                            SELECT 1
                            FROM catalogo_sigmanest_planos_corte plano
                            WHERE plano.codigo_tarefa = tarefa.codigo_tarefa
                              AND plano.ativo = TRUE
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM apontamentos_corte corte
                                  WHERE corte.plano_hash = plano.plano_hash
                                    AND corte.status = 'Finalizado'
                              )
                        )
                    ELSE FALSE
                END AS corte_concluido
            FROM catalogo_operacoes_op operacao
            JOIN catalogo_pcp_ops pcp ON pcp.codigo_op = operacao.codigo_op
            LEFT JOIN catalogo_recursos_pcfactory recurso
              ON recurso.codigo = operacao.codigo_recurso
            LEFT JOIN LATERAL (
                SELECT item.tarefa_id
                FROM op_por_tarefa item
                WHERE item.codigo_op = operacao.codigo_op
                ORDER BY item.id
                LIMIT 1
            ) vinculo ON TRUE
            LEFT JOIN tarefas tarefa ON tarefa.id = vinculo.tarefa_id
            WHERE operacao.codigo_op = %s
              AND (
                    operacao.ativo IS TRUE
                    OR (
                        operacao.fonte = 'totvs_production_order_v1'
                        AND operacao.sincronizado_em = (
                            SELECT MAX(atual.sincronizado_em)
                            FROM catalogo_operacoes_op atual
                            WHERE atual.codigo_op = operacao.codigo_op
                              AND atual.fonte = 'totvs_production_order_v1'
                        )
                    )
              )
            ORDER BY operacao.ordem, operacao.id
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, (codigo,))
            return [dict(row) for row in cursor.fetchall()]

    def listar_proximas_operacoes_roteiro(self, tipo_setor=None):
        """Projeta a próxima operação liberada de cada OP sem criar apontamento.

        O roteiro continua sendo a fonte de verdade. Uma etapa anterior de
        Corte só é considerada concluída quando todos os nestings ativos foram
        finalizados e a tarefa passou pelo fim do Destaque.
        """

        query = """
            SELECT
                operacao.*,
                pcp.quantidade,
                operacao.numero_operacao AS codigo,
                operacao.descricao_operacao AS nome,
                operacao.produto_codigo AS produto,
                operacao.produto_descricao AS descricao,
                recurso.nome AS recurso_nome,
                recurso.tipo_setor AS recurso_tipo_setor,
                vinculo.tarefa_id,
                tarefa.status AS tarefa_status
            FROM catalogo_operacoes_op operacao
            JOIN catalogo_pcp_ops pcp
              ON pcp.codigo_op = operacao.codigo_op
             AND pcp.ativo = TRUE
            LEFT JOIN catalogo_recursos_pcfactory recurso
              ON recurso.codigo = operacao.codigo_recurso
            LEFT JOIN LATERAL (
                SELECT item.tarefa_id
                FROM op_por_tarefa item
                WHERE item.codigo_op = operacao.codigo_op
                ORDER BY item.id
                LIMIT 1
            ) vinculo ON TRUE
            LEFT JOIN tarefas tarefa ON tarefa.id = vinculo.tarefa_id
            WHERE operacao.ativo = TRUE
              AND UPPER(operacao.tipo_setor) <> 'CORTE'
              AND NOT EXISTS (
                  SELECT 1
                  FROM apontamentos_operacionais atual
                  WHERE atual.catalogo_operacao_id = operacao.id
                    AND atual.status IN (
                        'Aguardando', 'Em processo', 'Parada', 'Setup',
                        'Retrabalho', 'Finalizado'
                    )
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM catalogo_operacoes_op anterior
                  WHERE anterior.codigo_op = operacao.codigo_op
                    AND anterior.ativo = TRUE
                    AND (
                        anterior.ordem < operacao.ordem
                        OR (anterior.ordem = operacao.ordem AND anterior.id < operacao.id)
                    )
                    -- Uma finalização adiantada autorizada cria uma fronteira
                    -- auditável no roteiro. Etapas anteriores a essa
                    -- fronteira deixam de bloquear somente o avanço seguinte;
                    -- elas não são reescritas nem fingidas como concluídas.
                    AND NOT EXISTS (
                        SELECT 1
                        FROM catalogo_operacoes_op autorizada
                        JOIN apontamentos_operacionais apontamento_autorizado
                          ON apontamento_autorizado.catalogo_operacao_id = autorizada.id
                         AND apontamento_autorizado.status = 'Finalizado'
                         AND apontamento_autorizado.etapa_anterior_pendente_confirmada IS TRUE
                        WHERE autorizada.codigo_op = operacao.codigo_op
                          AND (
                              autorizada.ordem > anterior.ordem
                              OR (
                                  autorizada.ordem = anterior.ordem
                                  AND autorizada.id > anterior.id
                              )
                          )
                          AND (
                              autorizada.ordem < operacao.ordem
                              OR (
                                  autorizada.ordem = operacao.ordem
                                  AND autorizada.id < operacao.id
                              )
                          )
                    )
                    AND (
                        (
                            UPPER(anterior.tipo_setor) = 'CORTE'
                            AND NOT (
                                tarefa.status = 'Finalizado'
                                AND EXISTS (
                                    SELECT 1
                                    FROM catalogo_sigmanest_planos_corte plano
                                    WHERE plano.codigo_tarefa = tarefa.codigo_tarefa
                                      AND plano.ativo = TRUE
                                )
                                AND NOT EXISTS (
                                    SELECT 1
                                    FROM catalogo_sigmanest_planos_corte plano
                                    WHERE plano.codigo_tarefa = tarefa.codigo_tarefa
                                      AND plano.ativo = TRUE
                                      AND NOT EXISTS (
                                          SELECT 1
                                          FROM apontamentos_corte corte
                                          WHERE corte.plano_hash = plano.plano_hash
                                            AND corte.status = 'Finalizado'
                                      )
                                )
                            )
                        )
                        OR (
                            UPPER(anterior.tipo_setor) <> 'CORTE'
                            AND NOT EXISTS (
                                SELECT 1
                                FROM apontamentos_operacionais concluido
                                WHERE concluido.catalogo_operacao_id = anterior.id
                                  AND concluido.status = 'Finalizado'
                            )
                        )
                    )
              )
        """
        params = []
        if tipo_setor:
            query += " AND UPPER(operacao.tipo_setor) = UPPER(%s)"
            params.append(str(tipo_setor).strip())
        query += " ORDER BY operacao.codigo_op, operacao.ordem, operacao.id"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def listar_recursos_pcfactory(self, tipo_setor=None, somente_habilitados=True):
        query = "SELECT * FROM catalogo_recursos_pcfactory WHERE TRUE"
        params = []
        if tipo_setor:
            query += " AND UPPER(tipo_setor) = UPPER(%s)"
            params.append(str(tipo_setor).strip())
        if somente_habilitados:
            query += " AND habilitado = TRUE"
        query += " ORDER BY codigo"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def publicar_recursos_pcfactory(self, recursos, *, fonte="PC Factory D0021"):
        """Atualiza o catálogo por código exato, sem classificar por prefixo."""

        rows = []
        for raw in recursos or ():
            item = dict(raw or {})
            code = str(item.get("codigo") or "").strip()
            name = str(item.get("nome") or "").strip()
            if not code or not name:
                continue
            rows.append(
                (
                    code,
                    name,
                    str(item.get("tipo_setor") or "").strip() or None,
                    bool(item.get("habilitado", True)),
                    str(item.get("fonte") or fonte).strip() or fonte,
                    agora_db(),
                )
            )
        if not rows:
            return 0
        with self.connection() as connection, connection.cursor() as cursor:
            # O mesmo recurso já chegou do PC Factory com capitalização
            # diferente em exportações distintas, criando duas linhas para uma
            # única máquina. `codigo` é a identidade e continua preservado como
            # veio na primeira vez: a importação reaproveita a linha existente
            # em vez de criar uma variante só por caixa.
            cursor.execute(
                """
                SELECT codigo FROM catalogo_recursos_pcfactory
                ORDER BY habilitado DESC, sincronizado_em DESC, codigo
                """
            )
            canonical_by_fold = {}
            for existing in cursor.fetchall():
                code = str(existing["codigo"]).strip()
                canonical_by_fold.setdefault(code.upper(), code)
            rows = [
                (canonical_by_fold.get(row[0].upper(), row[0]), *row[1:])
                for row in rows
            ]
            cursor.executemany(
                """
                INSERT INTO catalogo_recursos_pcfactory (
                    codigo, nome, tipo_setor, habilitado, fonte, sincronizado_em
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (codigo) DO UPDATE SET
                    nome = EXCLUDED.nome,
                    tipo_setor = COALESCE(
                        EXCLUDED.tipo_setor,
                        catalogo_recursos_pcfactory.tipo_setor
                    ),
                    habilitado = EXCLUDED.habilitado,
                    fonte = EXCLUDED.fonte,
                    sincronizado_em = EXCLUDED.sincronizado_em
                """,
                rows,
            )
        return len(rows)

    def listar_status_recursos(
        self,
        *,
        somente_habilitados=True,
        incluir_ocultos=False,
        somente_paradas=False,
        setup=None,
        retrabalho=None,
    ):
        query = "SELECT * FROM catalogo_status_recursos WHERE TRUE"
        params = []
        if somente_habilitados:
            query += " AND habilitado = TRUE"
        if not incluir_ocultos:
            query += " AND oculto = FALSE"
        if somente_paradas:
            query += (
                " AND COALESCE(grupo_codigo, '') <> '0001'"
                " AND setup = FALSE AND retrabalho = FALSE"
            )
        if setup is not None:
            query += " AND setup = %s"
            params.append(bool(setup))
        if retrabalho is not None:
            query += " AND retrabalho = %s"
            params.append(bool(retrabalho))
        query += " ORDER BY grupo_codigo, codigo"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def buscar_status_recurso(self, codigo):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM catalogo_status_recursos WHERE codigo = %s",
                (str(codigo or "").strip(),),
            )
            return _as_dict(cursor.fetchone())

    def enfileirar_apontamento_operacional(
        self,
        op,
        peca,
        tarefa_id,
        tipo_setor,
        maquina,
        operador,
        quantidade=1,
        data_entrada=None,
        operacao=None,
        etapa_anterior_pendente_confirmada=False,
    ):
        operacao = dict(operacao or {})
        entrada = _period_value(data_entrada) or agora_db()
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO apontamentos_operacionais (
                        op, peca, tarefa_id, tipo_setor, maquina, status, quantidade,
                        operador_fila, data_entrada, catalogo_operacao_id, numero_operacao,
                        codigo_recurso, descricao_operacao, produto_codigo, produto_descricao,
                        etapa_anterior_pendente_confirmada
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'Aguardando', %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING *
                    """,
                    (
                        limpa_codigo(op), peca or "", tarefa_id, str(tipo_setor or "").strip(),
                        str(maquina or "").strip(), max(1, int(quantidade or 1)), operador,
                        entrada,
                        operacao.get("id") or operacao.get("catalogo_operacao_id"),
                        operacao.get("numero_operacao") or operacao.get("codigo"),
                        operacao.get("codigo_recurso") or operacao.get("recurso"),
                        operacao.get("descricao_operacao") or operacao.get("nome"),
                        operacao.get("produto_codigo") or operacao.get("produto"),
                        operacao.get("produto_descricao") or operacao.get("descricao"),
                        bool(etapa_anterior_pendente_confirmada),
                    ),
                )
                row = cursor.fetchone()
                cursor.execute(
                    """
                    INSERT INTO eventos_apontamento_operador (
                        apontamento_id, estado, operador, data_hora
                    ) VALUES (%s, 'fila', %s, %s)
                    """,
                    (row["id"], operador, entrada),
                )
                return dict(row)
        except UniqueViolation as exc:
            if exc.diag.constraint_name == "idx_apontamento_ativo_op_setor":
                return None
            raise

    def listar_apontamentos_operacionais(self, tipo_setor, maquina=None, somente_ativos=True):
        query = "SELECT * FROM apontamentos_operacionais WHERE UPPER(tipo_setor) = UPPER(%s)"
        params = [str(tipo_setor or "").strip()]
        if maquina:
            query += " AND UPPER(maquina) = UPPER(%s)"
            params.append(str(maquina).strip())
        if somente_ativos:
            query += " AND status IN ('Aguardando', 'Em processo', 'Parada', 'Setup', 'Retrabalho')"
        query += """
            ORDER BY CASE status
                WHEN 'Em processo' THEN 0
                WHEN 'Parada' THEN 1
                WHEN 'Setup' THEN 2
                WHEN 'Retrabalho' THEN 3
                ELSE 4
            END, data_entrada, id
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def listar_apontamentos_por_op(self, op):
        """Retorna o progresso persistido usado para colorir o roteiro completo."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM apontamentos_operacionais
                WHERE UPPER(op) = UPPER(%s)
                ORDER BY data_entrada, id
                """,
                (limpa_codigo(op),),
            )
            return [dict(row) for row in cursor.fetchall()]

    def buscar_apontamento_operacional(self, apontamento_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM apontamentos_operacionais WHERE id = %s", (apontamento_id,))
            return _as_dict(cursor.fetchone())

    def listar_apontamentos_operacionais_periodo(self, tipo_setor, inicio, fim):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM apontamentos_operacionais
                WHERE UPPER(tipo_setor) = UPPER(%s)
                  AND data_inicio IS NOT NULL
                  AND data_inicio <= %s
                  AND (data_fim IS NULL OR data_fim >= %s)
                ORDER BY data_inicio, id
                """,
                (str(tipo_setor or "").strip(), _period_value(fim), _period_value(inicio)),
            )
            return [dict(row) for row in cursor.fetchall()]

    def _after_appointment_transition(self, connection, action, row):
        """Test seam executed inside the transaction before history is inserted."""

    def _enfileirar_outbound_totvs_tx(
        self, cursor, *, evento_id, codigo_op, execucao_concluida
    ):
        """Cria os itens da outbox TOTVS na MESMA transação do fato canônico.

        Esta é a fronteira ENQUEUE. Nada aqui fala com o WSPCP: o caminho
        crítico do operador termina no COMMIT local, e a entrega é problema do
        worker. A distinção que sustenta a Etapa 6 é esta:

        * **ERP indisponível** — WSPCP fora, timeout, rede caída. Isso *não*
          acontece nesta função. O item é gravado, o COMMIT ocorre, o operador
          é liberado e o worker tenta depois. Correto.
        * **Obrigação de integração não pôde ser registrada** — o ``INSERT`` na
          ``totvs_outbox`` falhou, ou o fato canônico não pôde ser lido para
          decidir se há obrigação. Aqui a exceção **propaga** e derruba a
          transação inteira. Um apontamento commitado sem a sua obrigação
          outbound seria uma perda definitiva: nenhum worker, retry ou
          reprocessamento consegue recuperar uma linha que nunca existiu.

        Por isso não existe ``SAVEPOINT`` nesta função. Engolir a falha aqui
        seria exatamente o cenário proibido.

        Falta de parâmetro homologado (``WasteCode``/``StopReasonCode``) e
        divergência de recurso **não** são falhas de persistência: o planner as
        converte em item ``ERROR`` bloqueado, com o fato canônico preservado em
        ``payload_context``. A obrigação continua registrada, auditável e
        reprocessável — o COMMIT segue normalmente.
        """

        config = getattr(self, "totvs_outbox_config", None)
        if config is None or not getattr(config, "enabled", False):
            # Sem outbox habilitada não existe obrigação de integração a
            # registrar, então também não existe nada que possa se perder.
            return []
        requests = []
        evento = self.buscar_evento_canonico_outbound_totvs(evento_id, cursor=cursor)
        if evento is not None:
            requests.extend(plan_execution_event(evento, config=config))
        if execucao_concluida and codigo_op:
            marco = self.buscar_marco_terminal_outbound_totvs(
                str(codigo_op), cursor=cursor
            )
            if marco is not None:
                requests.extend(plan_terminal_milestone(marco, config=config))
        criados = []
        for request in requests:
            item = self.enfileirar_outbound_totvs_tx(cursor, request)
            if item is None:
                # ``ON CONFLICT DO NOTHING``: a mesma mensagem lógica já está
                # registrada. Confirmamos que ela realmente existe antes de
                # seguir, para que "duplicata" nunca vire "obrigação ausente".
                item = self.buscar_item_outbound_totvs_por_chave(
                    request.idempotency_key, cursor=cursor
                )
                if item is None:
                    raise DatabaseIntegrityError(
                        "A obrigação de integração TOTVS não pôde ser registrada "
                        f"para o evento {evento_id}; a transação será revertida."
                    )
            criados.append(item)
        return criados

    def transicionar_apontamento_operador(
        self,
        apontamento_id,
        estado,
        operador,
        *,
        motivo=None,
        comentario=None,
        codigo_status_recurso=None,
        quantidade_boa=0,
        quantidade_refugo=0,
        quantidade_retrabalho=0,
        lote=None,
        motivo_refugo=None,
        causa_raiz=None,
        tipo_setup=None,
        operadores_cracha=None,
        recurso_roteiro_codigo=None,
        recurso_roteiro_nome=None,
        recurso_apontado=None,
        recurso_divergente=False,
        setor_roteiro=None,
        setor_divergente=False,
        recurso_exclusivo=False,
        setor_destino="Almoxarifado",
        data_hora=None,
    ):
        """Executa uma transição e registra lote, evento e participantes atomicamente."""

        destino_estado = str(estado or "").strip().lower()
        try:
            destino = OperatorState(destino_estado)
        except ValueError:
            raise ValueError(f"Estado de apontamento inválido: {estado}")
        if destino == OperatorState.QUEUED:
            raise ValueError(f"Estado de apontamento inválido: {estado}")
        instante = _period_value(data_hora) or agora_db()
        boas = max(0, int(quantidade_boa or 0))
        refugos = max(0, int(quantidade_refugo or 0))
        retrabalhos = max(0, int(quantidade_retrabalho or 0))
        crachas = list(
            dict.fromkeys(
                str(cracha or "").strip()
                for cracha in (operadores_cracha or ())
                if str(cracha or "").strip()
            )
        )

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM apontamentos_operacionais WHERE id = %s FOR UPDATE",
                (apontamento_id,),
            )
            atual = cursor.fetchone()
            if not atual:
                return None
            origem = atual["status"]
            origem_estado = operator_state_from_status(origem)
            if origem_estado is None or not can_transition(origem_estado, destino):
                return None
            estado_retorno = return_state_for_transition(
                origem_estado,
                destino,
                atual.get("estado_retorno"),
            )
            estado_retorno_db = estado_retorno.value if estado_retorno else None

            if (
                recurso_exclusivo
                and destino in {
                    OperatorState.PRODUCTION,
                    OperatorState.SETUP,
                    OperatorState.REWORK,
                }
                and origem == "Aguardando"
            ):
                resource = str(atual.get("maquina") or "").strip()
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(UPPER(%s)))",
                    (resource,),
                )
                cursor.execute(
                    """
                    SELECT id, operador_inicio, operador_fila
                    FROM apontamentos_operacionais
                    WHERE UPPER(maquina) = UPPER(%s)
                      AND id <> %s
                      AND status IN ('Em processo', 'Parada', 'Setup', 'Retrabalho')
                    ORDER BY id
                    LIMIT 1
                    """,
                    (resource, apontamento_id),
                )
                occupied = cursor.fetchone()
                if occupied:
                    return {
                        "exclusive_resource_conflict": True,
                        "resource": resource,
                        "operator": occupied.get("operador_inicio")
                        or occupied.get("operador_fila")
                        or "outro operador",
                    }

            operadores = []
            finalizacao_parcial = False
            total_boas = int(atual.get("quantidade_boa") or 0)
            total_refugos = int(atual.get("quantidade_refugo") or 0)
            total_retrabalhos = int(atual.get("quantidade_retrabalho") or 0)
            if crachas:
                cursor.execute(
                    """
                    SELECT id, cracha, nome FROM operadores_apontamento
                    WHERE cracha = ANY(%s) AND ativo = TRUE
                    ORDER BY array_position(%s::TEXT[], cracha)
                    """,
                    (crachas, crachas),
                )
                operadores = [dict(item) for item in cursor.fetchall()]
                encontrados = {item["cracha"] for item in operadores}
                ausentes = [cracha for cracha in crachas if cracha not in encontrados]
                if ausentes:
                    raise ValueError(
                        f"Crachá não cadastrado ou inativo: {', '.join(ausentes)}."
                    )
            if destino == OperatorState.FINISHED:
                quality_rework_only = bool(
                    str(atual.get("tipo_setor") or "").casefold() == "qualidade"
                    and retrabalhos > 0
                )
                if boas + refugos <= 0 and not quality_rework_only:
                    raise ValueError("Informe ao menos uma peça boa ou um refugo.")
                total_boas += boas
                total_refugos += refugos
                total_atendido = ManufacturingRules.attended_quantity(
                    total_boas,
                    total_refugos,
                )
                if total_atendido > int(atual["quantidade"]):
                    raise ValueError(
                        "A soma de peças boas e refugo excede a quantidade prevista restante."
                    )
                finalizacao_parcial = total_atendido < int(atual["quantidade"])

            if destino == OperatorState.PRODUCTION:
                cursor.execute(
                    """
                    UPDATE apontamentos_operacionais
                    SET status = 'Em processo',
                        operador_inicio = COALESCE(operador_inicio, %s),
                        data_inicio = COALESCE(data_inicio, %s),
                        motivo_parada = NULL,
                        codigo_status_recurso = NULL,
                        estado_retorno = NULL,
                        comentario = COALESCE(%s, comentario)
                    WHERE id = %s
                    RETURNING *
                    """,
                    (operador, instante, comentario, apontamento_id),
                )
            elif destino == OperatorState.FINISHED and finalizacao_parcial:
                cursor.execute(
                    """
                    UPDATE apontamentos_operacionais
                    SET status = 'Aguardando',
                        quantidade_boa = %s, quantidade_refugo = %s,
                        quantidade_retrabalho = %s,
                        data_entrada = %s,
                        codigo_status_recurso = NULL,
                        motivo_parada = NULL,
                        estado_retorno = NULL,
                        lote = COALESCE(%s, lote),
                        motivo_refugo = COALESCE(%s, motivo_refugo),
                        causa_raiz = COALESCE(%s, causa_raiz),
                        comentario = COALESCE(%s, comentario)
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        total_boas, total_refugos, total_retrabalhos + retrabalhos,
                        instante,
                        lote, motivo_refugo, causa_raiz, comentario, apontamento_id,
                    ),
                )
            elif destino == OperatorState.FINISHED:
                cursor.execute(
                    """
                    UPDATE apontamentos_operacionais
                    SET status = 'Finalizado', operador_fim = %s, data_fim = %s,
                        setor_destino = %s, quantidade_boa = %s, quantidade_refugo = %s,
                        quantidade_retrabalho = %s, lote = COALESCE(%s, lote),
                        motivo_refugo = COALESCE(%s, motivo_refugo),
                        causa_raiz = COALESCE(%s, causa_raiz),
                        codigo_status_recurso = COALESCE(%s, codigo_status_recurso),
                        motivo_parada = COALESCE(%s, motivo_parada),
                        estado_retorno = NULL,
                        comentario = COALESCE(%s, comentario)
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        operador, instante, str(setor_destino or "Almoxarifado").strip(),
                        total_boas, total_refugos, total_retrabalhos + retrabalhos,
                        lote, motivo_refugo, causa_raiz, codigo_status_recurso, motivo,
                        comentario, apontamento_id,
                    ),
                )
            else:
                cursor.execute(
                    """
                    UPDATE apontamentos_operacionais
                    SET status = %s, codigo_status_recurso = %s,
                        operador_inicio = COALESCE(operador_inicio, %s),
                        data_inicio = COALESCE(data_inicio, %s),
                        motivo_parada = %s, comentario = %s,
                        estado_retorno = %s,
                        quantidade_retrabalho = quantidade_retrabalho + %s,
                        causa_raiz = COALESCE(%s, causa_raiz),
                        tipo_setup = CASE WHEN %s = 'setup' THEN COALESCE(%s, tipo_setup) ELSE tipo_setup END
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        operator_status_for_state(destino), codigo_status_recurso,
                        operador, instante, motivo, comentario, estado_retorno_db,
                        retrabalhos if destino == OperatorState.REWORK else 0,
                        causa_raiz, destino_estado, tipo_setup, apontamento_id,
                    ),
                )
            row = cursor.fetchone()
            # Setor de origem do roteiro: gravado uma única vez, na primeira
            # transição que o conhece. `COALESCE` impede que uma ação posterior
            # reescreva a origem — o histórico do apontamento incorreto precisa
            # continuar mostrando de onde a OP veio.
            if str(setor_roteiro or "").strip():
                cursor.execute(
                    """
                    UPDATE apontamentos_operacionais
                    SET setor_roteiro = COALESCE(setor_roteiro, %s),
                        setor_divergente = (
                            setor_divergente OR %s
                        )
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        str(setor_roteiro).strip(),
                        bool(setor_divergente),
                        apontamento_id,
                    ),
                )
                atualizado = cursor.fetchone()
                if atualizado is not None:
                    row = atualizado
            self._after_appointment_transition(connection, destino_estado, row)
            evento_estado = "parcial" if finalizacao_parcial else destino.value
            cursor.execute(
                """
                INSERT INTO eventos_apontamento_operador (
                    apontamento_id, estado, motivo, comentario, quantidade_boa,
                    quantidade_refugo, operador, data_hora, codigo_status_recurso,
                    recurso_roteiro_codigo, recurso_roteiro_nome,
                    recurso_apontado, recurso_divergente, estado_retorno,
                    setor_roteiro, setor_divergente
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id
                """,
                (
                    apontamento_id, evento_estado, motivo, comentario,
                    boas, refugos, operador, instante, codigo_status_recurso,
                    str(recurso_roteiro_codigo or "").strip() or None,
                    str(recurso_roteiro_nome or "").strip() or None,
                    str(recurso_apontado or "").strip() or None,
                    bool(recurso_divergente),
                    estado_retorno_db,
                    str(setor_roteiro or "").strip() or None,
                    bool(setor_divergente),
                ),
            )
            evento_id = cursor.fetchone()["id"]
            for participante in operadores:
                cursor.execute(
                    """
                    INSERT INTO operadores_evento_apontamento (evento_id, operador_id)
                    VALUES (%s, %s)
                    """,
                    (evento_id, participante["id"]),
                )

            source_ref = f"evento_apontamento:{evento_id}"
            self._reconciliar_estado_recurso_apontamentos_tx(
                cursor,
                row.get("maquina"),
                instante,
                operador=operador,
                origem="apontamento_operador",
                referencia_origem=source_ref,
                evento_apontamento_id=evento_id,
            )
            quantity_common = {
                "numero_operacao": row.get("numero_operacao"),
                "produto_codigo": row.get("produto_codigo"),
                "recurso": row.get("maquina"),
                "tipo_setor": row.get("tipo_setor"),
                "operador": operador,
                "lote": lote,
                "causa_raiz": causa_raiz,
                "comentario": comentario,
                "data_hora": instante,
                "origem": "apontamento_operador",
                "referencia_origem": source_ref,
                "connection": connection,
            }
            if boas:
                self.registrar_evento_quantidade("boa", boas, row["op"], **quantity_common)
            if refugos:
                self.registrar_evento_quantidade(
                    "refugo", refugos, row["op"],
                    motivo=motivo_refugo or motivo, **quantity_common
                )
            if retrabalhos:
                self.registrar_evento_quantidade(
                    "retrabalho", retrabalhos, row["op"], motivo=motivo, **quantity_common
                )

            # Outbox TOTVS: gravada depois das quantidades canônicas, porque o
            # read model outbound as lê, e antes do COMMIT, porque é ele que
            # torna o outbound durável junto com o fato do operador.
            self._enfileirar_outbound_totvs_tx(
                cursor,
                evento_id=evento_id,
                codigo_op=row.get("op"),
                execucao_concluida=(
                    destino == OperatorState.FINISHED and not finalizacao_parcial
                ),
            )

            cursor.execute(
                """
                INSERT INTO historico (
                    op, tipo, setor, motivo, quantidade, operador, data_hora, peca, tarefa_id
                ) VALUES (%s, 'Apontamento Operador', %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    row["op"], row["maquina"],
                    motivo or (
                        "Finalização parcial; OP permanece aberta"
                        if finalizacao_parcial
                        else f"Estado: {operator_status_for_state(destino)}"
                    ),
                    boas if destino == OperatorState.FINISHED else row["quantidade"],
                    operador, instante, row["peca"] or "", row["tarefa_id"],
                ),
            )
            # A localização corrente da OP continua sendo derivada dos eventos
            # de movimentação. A máquina de estados é a única responsável por
            # criá-los no início e na conclusão, sem converter a quantidade
            # planejada em quantidade boa.
            setor_movimentacao = None
            quantidade_movimentada = 0
            if origem_estado == OperatorState.QUEUED:
                setor_movimentacao = row.get("maquina")
                quantidade_movimentada = int(row.get("quantidade") or 0)
            elif destino == OperatorState.FINISHED and not finalizacao_parcial:
                setor_movimentacao = row.get("setor_destino")
                quantidade_movimentada = int(row.get("quantidade_boa") or 0)
            if setor_movimentacao:
                cursor.execute(
                    """
                    INSERT INTO historico (
                        op, tipo, setor, motivo, quantidade, operador, data_hora, peca, tarefa_id
                    ) VALUES (%s, 'Movimentação', %s, '', %s, %s, %s, %s, %s)
                    """,
                    (
                        row["op"], setor_movimentacao, quantidade_movimentada,
                        operador, instante, row["peca"] or "", row["tarefa_id"],
                    ),
                )
            result = dict(row)
            if destino == OperatorState.FINISHED:
                result["finalizacao_parcial"] = finalizacao_parcial
                result["saldo_restante"] = max(
                    0,
                    ManufacturingRules.quantity_remaining(
                        row["quantidade"],
                        row.get("quantidade_boa"),
                        row.get("quantidade_refugo"),
                    ),
                )
                result["operadores"] = operadores
            return result

    def listar_apontamentos_abertos_no_limite_turno(self, data_limite):
        """Lista apontamentos iniciados que precisam receber corte de fim de turno.

        Inclui Parada porque uma parada manual iniciada antes do limite precisa
        terminar temporalmente no fim do turno; do contrário, o período fora de
        turno seria contado como downtime até a retomada do dia seguinte.
        """

        limite = _period_value(data_limite)
        if limite is None:
            raise ValueError("data_limite é obrigatória.")
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT a.*
                FROM apontamentos_operacionais a
                WHERE a.status IN ('Em processo', 'Parada', 'Setup', 'Retrabalho')
                  AND a.data_inicio IS NOT NULL
                  AND a.data_inicio <= %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM eventos_apontamento_operador e
                      WHERE e.apontamento_id = a.id
                        AND e.tipo_interrupcao = 'fim_turno'
                        AND e.data_hora = %s
                  )
                ORDER BY a.id
                """,
                (limite, limite),
            )
            return [dict(row) for row in cursor.fetchall()]

    def listar_cortes_abertos_no_limite_turno(self, data_limite):
        """Lista nestings ativos que atravessam um limite oficial de turno."""

        limite = _period_value(data_limite)
        if limite is None:
            raise ValueError("data_limite é obrigatória.")
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT a.*
                FROM apontamentos_corte a
                WHERE a.status = 'Em processo'
                  AND a.data_inicio IS NOT NULL
                  AND a.data_inicio <= %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM eventos_estado_recurso e
                      WHERE UPPER(e.recurso) = UPPER(a.maquina)
                        AND e.tipo_interrupcao = 'fim_turno'
                        AND e.data_inicio = %s
                  )
                ORDER BY a.id
                """,
                (limite, limite),
            )
            return [dict(row) for row in cursor.fetchall()]

    def interromper_corte_fim_turno(
        self,
        apontamento_id,
        *,
        data_hora,
        operador="SISTEMA",
        motivo="Fim de turno — interrupção programada automática",
        tipo_interrupcao="fim_turno",
    ):
        """Interrompe fisicamente o Corte sem finalizar ou alterar seu nesting."""

        instante = _period_value(data_hora)
        if instante is None:
            raise ValueError("data_hora é obrigatória para o fim de turno.")
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM apontamentos_corte WHERE id = %s FOR UPDATE",
                (apontamento_id,),
            )
            row = cursor.fetchone()
            if (
                not row
                or row.get("status") != "Em processo"
                or row.get("data_inicio") is None
                or row.get("data_inicio") > instante
            ):
                return None
            cursor.execute(
                """
                SELECT id FROM eventos_estado_recurso
                WHERE UPPER(recurso) = UPPER(%s)
                  AND tipo_interrupcao = %s
                  AND data_inicio = %s
                LIMIT 1
                """,
                (row.get("maquina"), tipo_interrupcao, instante),
            )
            if cursor.fetchone():
                result = dict(row)
                result["interrupcao_registrada"] = False
                return result
            state = self._transicionar_estado_recurso_tx(
                cursor,
                row.get("maquina"),
                "fora_turno",
                tipo_setor="Corte",
                operador=str(operador or "SISTEMA").strip() or "SISTEMA",
                motivo=str(motivo or "").strip(),
                data_hora=instante,
                origem="fim_turno_automatico_corte",
                referencia_origem=f"nesting:{row.get('id')}",
                planejado=True,
                automatico=True,
                tipo_interrupcao=tipo_interrupcao,
            )
            result = dict(row)
            result["interrupcao_registrada"] = bool(state)
            result["estado_recurso_id"] = state.get("id") if state else None
            result["tipo_interrupcao"] = tipo_interrupcao
            return result

    def listar_pausas_automaticas(self, *, tipo_setor=None, somente_ativas=True):
        """Configuração gerencial das pausas automáticas, por setor.

        Substitui a lista fixa que vivia no domínio. O documento oficial de
        fluxo prevê horários diferentes por setor e mais de uma pausa por dia,
        então o horário deixou de ser regra de código.
        """

        query = "SELECT * FROM pausas_automaticas_setor WHERE TRUE"
        params = []
        if somente_ativas:
            query += " AND ativo IS TRUE"
        if tipo_setor:
            query += " AND UPPER(tipo_setor) = UPPER(%s)"
            params.append(str(tipo_setor).strip())
        query += " ORDER BY tipo_setor, ordem, hora_inicio, id"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def salvar_pausa_automatica(
        self,
        *,
        tipo_setor,
        nome,
        hora_inicio,
        hora_fim,
        ativo=True,
        ordem=1,
        pausa_id=None,
        operador=None,
    ):
        """Cria ou atualiza uma pausa. A janela precisa existir de fato."""

        setor = str(tipo_setor or "").strip()
        rotulo = str(nome or "").strip()
        if not setor or not rotulo:
            raise ValueError("Setor e nome da pausa são obrigatórios.")
        if hora_inicio == hora_fim:
            raise ValueError("A pausa precisa de horário inicial e final distintos.")
        with self.connection() as connection, connection.cursor() as cursor:
            if pausa_id is not None:
                cursor.execute(
                    """
                    UPDATE pausas_automaticas_setor
                    SET tipo_setor = %s, nome = %s, hora_inicio = %s, hora_fim = %s,
                        ativo = %s, ordem = %s, atualizado_por = %s,
                        atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING *
                    """,
                    (setor, rotulo, hora_inicio, hora_fim, bool(ativo), int(ordem),
                     operador, int(pausa_id)),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO pausas_automaticas_setor (
                        tipo_setor, nome, hora_inicio, hora_fim, ativo, ordem,
                        atualizado_por
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (UPPER(tipo_setor), nome, hora_inicio) DO UPDATE SET
                        hora_fim = EXCLUDED.hora_fim,
                        ativo = EXCLUDED.ativo,
                        ordem = EXCLUDED.ordem,
                        atualizado_por = EXCLUDED.atualizado_por,
                        atualizado_em = CURRENT_TIMESTAMP
                    RETURNING *
                    """,
                    (setor, rotulo, hora_inicio, hora_fim, bool(ativo), int(ordem),
                     operador),
                )
            row = cursor.fetchone()
            return dict(row) if row else None

    def remover_pausa_automatica(self, pausa_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM pausas_automaticas_setor WHERE id = %s", (int(pausa_id),)
            )
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Turnos automáticos (H1/expediente/H2 e futuros) — tela IagoDev.
    #
    # Substitui as constantes fixas que viviam em
    # ``mes/domain/manufacturing_rules.py`` (SHIFT_END_BOUNDARIES,
    # OFFICIAL_WORK_WINDOW). ``ShiftBoundaryService`` lê esta tabela a cada
    # ciclo pelo carregador em ``mes/services/shift_parameters.py``.
    # ------------------------------------------------------------------
    def listar_parametros_turno(self, *, somente_ativos=False):
        query = "SELECT * FROM parametros_turno WHERE TRUE"
        if somente_ativos:
            query += " AND ativo IS TRUE"
        query += " ORDER BY ordem, hora_inicio, id"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    def salvar_parametro_turno(
        self,
        *,
        nome,
        tipo,
        hora_inicio,
        hora_fim,
        ativo=True,
        ordem=1,
        parametro_id=None,
    ):
        """Cria ou atualiza um turno. A janela precisa existir de fato."""

        rotulo = str(nome or "").strip()
        tipo_normalizado = str(tipo or "").strip().casefold()
        if not rotulo:
            raise ValueError("Nome do turno é obrigatório.")
        if tipo_normalizado not in {"expediente", "hora_extra"}:
            raise ValueError("Tipo do turno deve ser 'expediente' ou 'hora_extra'.")
        if hora_inicio == hora_fim:
            raise ValueError("O turno precisa de horário inicial e final distintos.")
        with self.connection() as connection, connection.cursor() as cursor:
            if parametro_id is not None:
                cursor.execute(
                    """
                    UPDATE parametros_turno
                    SET nome = %s, tipo = %s, hora_inicio = %s, hora_fim = %s,
                        ativo = %s, ordem = %s, atualizado_em = CURRENT_TIMESTAMP
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        rotulo, tipo_normalizado, hora_inicio, hora_fim,
                        bool(ativo), int(ordem), int(parametro_id),
                    ),
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO parametros_turno (
                        nome, tipo, hora_inicio, hora_fim, ativo, ordem
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (nome) DO UPDATE SET
                        tipo = EXCLUDED.tipo,
                        hora_inicio = EXCLUDED.hora_inicio,
                        hora_fim = EXCLUDED.hora_fim,
                        ativo = EXCLUDED.ativo,
                        ordem = EXCLUDED.ordem,
                        atualizado_em = CURRENT_TIMESTAMP
                    RETURNING *
                    """,
                    (rotulo, tipo_normalizado, hora_inicio, hora_fim, bool(ativo), int(ordem)),
                )
            row = cursor.fetchone()
            return dict(row) if row else None

    def remover_parametro_turno(self, parametro_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM parametros_turno WHERE id = %s", (int(parametro_id),)
            )
            return cursor.rowcount > 0

    def listar_recursos_ativos_no_instante(self, data_hora):
        """Recursos com execução operacional ou Corte aberta no instante."""

        instante = _period_value(data_hora)
        if instante is None:
            raise ValueError("data_hora é obrigatória.")
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT recurso, MIN(tipo_setor) AS tipo_setor
                FROM (
                    SELECT maquina AS recurso, tipo_setor
                    FROM apontamentos_operacionais
                    WHERE status IN ('Em processo', 'Setup', 'Retrabalho')
                      AND data_inicio IS NOT NULL AND data_inicio <= %s
                      AND (data_fim IS NULL OR data_fim > %s)
                    UNION ALL
                    SELECT maquina AS recurso, 'Corte'::TEXT AS tipo_setor
                    FROM apontamentos_corte
                    WHERE status = 'Em processo'
                      AND data_inicio IS NOT NULL AND data_inicio <= %s
                      AND (data_fim IS NULL OR data_fim > %s)
                ) ativos
                WHERE COALESCE(BTRIM(recurso), '') <> ''
                GROUP BY recurso
                ORDER BY recurso
                """,
                (instante, instante, instante, instante),
            )
            return [dict(row) for row in cursor.fetchall()]

    def iniciar_intervalo_automatico(
        self, data_hora, nome, *, operador="SISTEMA", tipo_setor=None
    ):
        """Classifica como parada programada os recursos ativos no intervalo.

        ``tipo_setor`` restringe a pausa ao setor configurado. Sem ele, a pausa
        vale para toda a fábrica — comportamento anterior, preservado para
        configurações que não declaram setor.
        """

        instante = _period_value(data_hora)
        motivo = f"Intervalo automático — {str(nome or 'programado').strip()}"
        alvo = str(tipo_setor or "").strip().casefold()
        changed = []
        # A idempotência é resolvida em uma única leitura: antes esta checagem
        # rodava por recurso, tomando uma conexão do pool a cada volta do laço.
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT UPPER(recurso) AS recurso
                FROM eventos_estado_recurso
                WHERE tipo_interrupcao = 'intervalo_programado'
                  AND data_inicio = %s
                """,
                (instante,),
            )
            ja_aplicados = {row["recurso"] for row in cursor.fetchall()}
        for row in self.listar_recursos_ativos_no_instante(instante):
            if alvo and str(row.get("tipo_setor") or "").strip().casefold() != alvo:
                continue
            if str(row["recurso"] or "").upper() in ja_aplicados:
                continue
            state = self.transicionar_estado_recurso(
                row["recurso"],
                "parada",
                tipo_setor=row.get("tipo_setor"),
                operador=operador,
                motivo=motivo,
                data_hora=instante,
                origem="intervalo_programado_inicio",
                referencia_origem=instante.isoformat(),
                planejado=True,
                automatico=True,
                tipo_interrupcao="intervalo_programado",
            )
            if state:
                changed.append(dict(state))
        return changed

    def finalizar_intervalo_automatico(
        self, data_hora, nome, *, operador="SISTEMA", tipo_setor=None
    ):
        """Retoma automaticamente somente recursos ainda parados pelo intervalo."""

        instante = _period_value(data_hora)
        reason = f"Retomada automática — {str(nome or 'intervalo programado').strip()}"
        alvo = str(tipo_setor or "").strip().casefold()
        resumed = []
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM eventos_estado_recurso
                WHERE data_fim IS NULL
                  AND tipo_interrupcao = 'intervalo_programado'
                  AND automatico IS TRUE
                ORDER BY recurso, id
                FOR UPDATE
                """
            )
            states = [dict(row) for row in cursor.fetchall()]
            for current in states:
                if alvo and str(current.get("tipo_setor") or "").strip().casefold() != alvo:
                    continue
                resource = current["recurso"]
                cursor.execute(
                    """
                    SELECT status, tipo_setor
                    FROM apontamentos_operacionais
                    WHERE UPPER(maquina) = UPPER(%s)
                      AND status IN ('Em processo', 'Setup', 'Retrabalho')
                      AND data_inicio IS NOT NULL AND data_inicio <= %s
                      AND (data_fim IS NULL OR data_fim > %s)
                    ORDER BY id
                    """,
                    (resource, instante, instante),
                )
                appointments = [dict(row) for row in cursor.fetchall()]
                cursor.execute(
                    """
                    SELECT 1 FROM apontamentos_corte
                    WHERE UPPER(maquina) = UPPER(%s)
                      AND status = 'Em processo'
                      AND data_inicio IS NOT NULL AND data_inicio <= %s
                      AND (data_fim IS NULL OR data_fim > %s)
                    LIMIT 1
                    """,
                    (resource, instante, instante),
                )
                has_cut = cursor.fetchone() is not None
                category_by_status = {
                    "Em processo": "producao",
                    "Setup": "setup",
                    "Retrabalho": "retrabalho",
                }
                categories = {
                    category_by_status[row.get("status")]
                    for row in appointments
                    if row.get("status") in category_by_status
                }
                if has_cut:
                    categories.add("producao")
                if not categories:
                    closed = self._encerrar_estado_recurso_tx(cursor, resource, instante)
                    if closed:
                        resumed.append(dict(closed))
                    continue
                category = next(iter(categories)) if len(categories) == 1 else "desconhecido"
                sector_values = {
                    str(row.get("tipo_setor") or "").strip()
                    for row in appointments
                    if str(row.get("tipo_setor") or "").strip()
                }
                if has_cut:
                    sector_values.add("Corte")
                state = self._transicionar_estado_recurso_tx(
                    cursor,
                    resource,
                    category,
                    tipo_setor=(next(iter(sector_values)) if len(sector_values) == 1 else None),
                    operador=operador,
                    motivo=reason,
                    data_hora=instante,
                    origem="intervalo_programado_fim",
                    referencia_origem=current.get("referencia_origem"),
                    planejado=None,
                    automatico=True,
                    tipo_interrupcao="retomada_intervalo_programado",
                )
                if state:
                    resumed.append(dict(state))
        return resumed

    def interromper_recursos_ociosos_fim_turno(
        self,
        data_hora,
        *,
        operador="SISTEMA",
        motivo="Fim de turno — interrupção programada automática",
        tipo_interrupcao="fim_turno",
    ):
        """Fecha o dia dos recursos que já estavam ociosos no limite de turno.

        ``interromper_apontamento_fim_turno`` só cobre o recurso que tinha uma
        OP aberta no instante do limite. Na prática a maioria dos recursos já
        havia encerrado a última OP horas antes e ficou ocioso sem nenhum
        apontamento aberto para "carregar" a interrupção — sem esta rotina,
        o estado físico desses recursos não muda: ``eventos_estado_recurso``
        fica sem linha aberta (ou com uma categoria antiga) e o recurso
        simplesmente some do Andon em vez de aparecer como "Sem demanda".

        Só entram recursos com histórico físico prévio (``eventos_estado_recurso``);
        cadastro nunca usado não vira card por conta desta rotina. Recurso com
        apontamento ou corte em execução no instante fica de fora — quem
        cobre esse caso é a interrupção específica da OP/nesting, que
        preserva os dados coletados em vez de fabricar um segundo evento.
        """

        instante = _period_value(data_hora)
        if instante is None:
            raise ValueError("data_hora é obrigatória para o fim de turno.")
        operador = str(operador or "SISTEMA").strip() or "SISTEMA"
        motivo = str(motivo or "Fim de turno — interrupção programada automática").strip()
        tipo_interrupcao = str(tipo_interrupcao or "fim_turno").strip() or "fim_turno"
        executando = sorted(EXECUTING_APPOINTMENT_STATUSES)
        changed = []
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT ON (UPPER(e.recurso)) e.recurso, e.tipo_setor
                FROM eventos_estado_recurso e
                WHERE e.recurso IS NOT NULL AND e.recurso <> ''
                  AND e.data_inicio <= %s
                  AND NOT EXISTS (
                      SELECT 1 FROM eventos_estado_recurso e2
                      WHERE UPPER(e2.recurso) = UPPER(e.recurso)
                        AND e2.tipo_interrupcao = %s
                        AND e2.data_inicio = %s
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM apontamentos_operacionais a
                      WHERE UPPER(a.maquina) = UPPER(e.recurso)
                        AND a.status = ANY(%s)
                        AND a.data_inicio IS NOT NULL AND a.data_inicio <= %s
                        AND (a.data_fim IS NULL OR a.data_fim > %s)
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM apontamentos_corte c
                      WHERE UPPER(c.maquina) = UPPER(e.recurso)
                        AND c.status = 'Em processo'
                        AND c.data_inicio IS NOT NULL AND c.data_inicio <= %s
                        AND (c.data_fim IS NULL OR c.data_fim > %s)
                  )
                ORDER BY UPPER(e.recurso), e.id DESC
                """,
                (
                    instante, tipo_interrupcao, instante, executando,
                    instante, instante, instante, instante,
                ),
            )
            candidatos = [dict(row) for row in cursor.fetchall()]
            for candidato in candidatos:
                state = self._transicionar_estado_recurso_tx(
                    cursor,
                    candidato["recurso"],
                    "fora_turno",
                    tipo_setor=candidato.get("tipo_setor"),
                    operador=operador,
                    motivo=motivo,
                    data_hora=instante,
                    origem="fim_turno_automatico_ocioso",
                    referencia_origem=None,
                    planejado=True,
                    automatico=True,
                    tipo_interrupcao=tipo_interrupcao,
                )
                if state and not state.get("retroativo_ignorado"):
                    changed.append(dict(state))
        return changed

    def finalizar_fora_turno_automatico(
        self,
        data_hora,
        *,
        operador="SISTEMA",
        motivo="Retorno do turno — recurso sem demanda",
        tipo_interrupcao="retorno_turno_sem_demanda",
    ):
        """Encerra o fora de turno e publica ausência de demanda às 08:00.

        A OP interrompida permanece em ``Parada`` e exige retomada manual. A
        fila criada aqui não carrega OP nem estado produtivo: ela registra
        apenas que o recurso voltou à janela oficial sem demanda em execução.

        Recurso com execução em curso fica de fora: o Corte é interrompido no
        fim do turno sem encerrar o nesting, então o estado físico pode dizer
        ``fora_turno`` enquanto a máquina continua cortando. Publicar ausência
        de demanda por cima disso apagaria produção real da linha do tempo e
        do Andon.
        """

        instante = _period_value(data_hora)
        if instante is None:
            raise ValueError("data_hora é obrigatória para o retorno do turno.")
        executando = sorted(EXECUTING_APPOINTMENT_STATUSES)
        changed = []
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT e.*
                FROM eventos_estado_recurso e
                WHERE e.data_fim IS NULL
                  AND e.categoria = 'fora_turno'
                  AND e.automatico IS TRUE
                  AND e.tipo_interrupcao = 'fim_turno'
                  AND e.data_inicio < %s
                  AND NOT EXISTS (
                      SELECT 1
                      FROM apontamentos_operacionais a
                      WHERE UPPER(a.maquina) = UPPER(e.recurso)
                        AND a.status = ANY(%s)
                        AND a.data_inicio IS NOT NULL
                        AND a.data_inicio <= %s
                        AND (a.data_fim IS NULL OR a.data_fim > %s)
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM apontamentos_corte c
                      WHERE UPPER(c.maquina) = UPPER(e.recurso)
                        AND c.status = 'Em processo'
                        AND c.data_inicio IS NOT NULL
                        AND c.data_inicio <= %s
                        AND (c.data_fim IS NULL OR c.data_fim > %s)
                  )
                ORDER BY e.recurso, e.id
                FOR UPDATE
                """,
                (
                    instante, executando, instante, instante,
                    instante, instante,
                ),
            )
            for current in [dict(row) for row in cursor.fetchall()]:
                state = self._transicionar_estado_recurso_tx(
                    cursor,
                    current["recurso"],
                    "fila",
                    tipo_setor=current.get("tipo_setor"),
                    operador=str(operador or "SISTEMA").strip() or "SISTEMA",
                    motivo=str(motivo or "").strip(),
                    data_hora=instante,
                    origem="retorno_turno_sem_demanda",
                    referencia_origem=f"evento_estado:{current.get('id')}",
                    planejado=None,
                    automatico=True,
                    tipo_interrupcao=tipo_interrupcao,
                )
                if state and not state.get("retroativo_ignorado"):
                    changed.append(dict(state))
        return changed

    def interromper_apontamento_fim_turno(
        self,
        apontamento_id,
        *,
        data_hora,
        operador="SISTEMA",
        motivo="Fim de turno — interrupção programada automática",
        tipo_interrupcao="fim_turno",
    ):
        """Registra o corte temporal de fim de turno sem lançar quantidade.

        A OP não é finalizada. Se não houve outro evento depois do limite, seu
        estado corrente passa a ``Parada`` para exigir retomada manual. Caso a
        aplicação esteja apenas reconstruindo um limite perdido e já existam
        eventos posteriores, a linha do tempo é corrigida retroativamente sem
        sobrescrever o estado atual.
        """

        instante = _period_value(data_hora)
        if instante is None:
            raise ValueError("data_hora é obrigatória para o fim de turno.")
        operador = str(operador or "SISTEMA").strip() or "SISTEMA"
        motivo = str(motivo or "Fim de turno — interrupção programada automática").strip()
        tipo_interrupcao = str(tipo_interrupcao or "fim_turno").strip() or "fim_turno"

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM apontamentos_operacionais WHERE id = %s FOR UPDATE",
                (apontamento_id,),
            )
            atual = cursor.fetchone()
            if not atual:
                return None
            if atual.get("status") not in {"Em processo", "Parada", "Setup", "Retrabalho"}:
                return None
            if atual.get("data_inicio") is None or atual.get("data_inicio") > instante:
                return None

            cursor.execute(
                """
                SELECT id
                FROM eventos_apontamento_operador
                WHERE apontamento_id = %s
                  AND tipo_interrupcao = %s
                  AND data_hora = %s
                LIMIT 1
                """,
                (apontamento_id, tipo_interrupcao, instante),
            )
            if cursor.fetchone():
                result = dict(atual)
                result["interrupcao_registrada"] = False
                return result

            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM eventos_apontamento_operador
                    WHERE apontamento_id = %s
                      AND data_hora > %s
                      AND estado <> 'parcial'
                ) AS existe
                """,
                (apontamento_id, instante),
            )
            tem_evento_posterior = bool(cursor.fetchone()["existe"])

            row = atual
            if not tem_evento_posterior and atual.get("status") in {
                "Em processo", "Setup", "Retrabalho"
            }:
                origem_estado = operator_state_from_status(atual.get("status"))
                estado_retorno = return_state_for_transition(
                    origem_estado,
                    OperatorState.STOPPED,
                    atual.get("estado_retorno"),
                )
                cursor.execute(
                    """
                    UPDATE apontamentos_operacionais
                    SET status = 'Parada',
                        codigo_status_recurso = NULL,
                        motivo_parada = %s,
                        estado_retorno = %s
                    WHERE id = %s
                    RETURNING *
                    """,
                    (
                        motivo,
                        estado_retorno.value if estado_retorno else None,
                        apontamento_id,
                    ),
                )
                row = cursor.fetchone()

            cursor.execute(
                """
                INSERT INTO eventos_apontamento_operador (
                    apontamento_id, estado, motivo, comentario,
                    quantidade_boa, quantidade_refugo, operador, data_hora,
                    codigo_status_recurso, interrupcao_programada,
                    origem_automatica, tipo_interrupcao, estado_retorno
                ) VALUES (
                    %s, 'fora_turno', %s, NULL, 0, 0, %s, %s,
                    NULL, TRUE, TRUE, %s, %s
                )
                ON CONFLICT DO NOTHING
                RETURNING id
                """,
                (
                    apontamento_id,
                    motivo,
                    operador,
                    instante,
                    tipo_interrupcao,
                    row.get("estado_retorno"),
                ),
            )
            event = cursor.fetchone()
            if not event:
                result = dict(row)
                result["interrupcao_registrada"] = False
                return result

            # Fim de turno é estado físico próprio e programado. Mesmo que
            # várias OPs estejam simultâneas no recurso, a transição é
            # idempotente e cria um único intervalo físico fora de turno.
            self._transicionar_estado_recurso_tx(
                cursor,
                row.get("maquina"),
                "fora_turno",
                tipo_setor=row.get("tipo_setor"),
                operador=operador,
                motivo=motivo,
                data_hora=instante,
                origem="fim_turno_automatico",
                referencia_origem=f"evento_apontamento:{event['id']}",
                planejado=True,
                automatico=True,
                tipo_interrupcao=tipo_interrupcao,
                apontamento_id=row.get("id"),
                evento_apontamento_id=event["id"],
            )

            # Histórico apenas como trilha de auditoria. Quantidade zero é
            # deliberada: fim de turno nunca registra produção.
            cursor.execute(
                """
                INSERT INTO historico (
                    op, tipo, setor, motivo, quantidade, operador, data_hora, peca, tarefa_id
                ) VALUES (%s, 'Apontamento Operador', %s, %s, 0, %s, %s, %s, %s)
                """,
                (
                    row["op"], row["maquina"], motivo, operador, instante,
                    row.get("peca") or "", row.get("tarefa_id"),
                ),
            )

            result = dict(row)
            result["interrupcao_registrada"] = True
            result["evento_id"] = event["id"]
            result["tipo_interrupcao"] = tipo_interrupcao
            result["interrupcao_programada"] = True
            result["origem_automatica"] = True
            return result

    def listar_fatos_operacionais_periodo(
        self, inicio, fim, *, setor=None, recurso=None, op=None, operacao=None, produto=None,
        operador=None,
    ):
        """Carrega fatos operacionais com eventos em uma única consulta.

        É a fonte preferencial dos serviços gerenciais; evita N+1 e mantém a UI
        desacoplada das tabelas físicas.
        """

        start = _period_value(inicio)
        end = _period_value(fim)
        query = """
            SELECT
                a.*,
                MAX(p.quantidade) AS quantidade_planejada_pcp,
                c.tempo_medio_segundos,
                c.ordem AS ordem_operacao,
                p.data_liberacao,
                p.inicio_planejado,
                p.fim_planejado,
                p.prazo_entrega,
                p.prioridade,
                COALESCE(
                    json_agg(
                        json_build_object(
                            'id', e.id,
                            'estado', e.estado,
                            'motivo', e.motivo,
                            'comentario', e.comentario,
                            'quantidade_boa', e.quantidade_boa,
                            'quantidade_refugo', e.quantidade_refugo,
                            'operador', e.operador,
                            'data_hora', e.data_hora,
                            'codigo_status_recurso', e.codigo_status_recurso,
                            'recurso_roteiro_codigo', e.recurso_roteiro_codigo,
                            'recurso_roteiro_nome', e.recurso_roteiro_nome,
                            'recurso_apontado', e.recurso_apontado,
                            'recurso_divergente', e.recurso_divergente,
                            'interrupcao_programada', e.interrupcao_programada,
                            'origem_automatica', e.origem_automatica,
                            'tipo_interrupcao', e.tipo_interrupcao
                        ) ORDER BY e.data_hora, e.id
                    ) FILTER (WHERE e.id IS NOT NULL),
                    '[]'::json
                ) AS eventos
            FROM apontamentos_operacionais a
            LEFT JOIN catalogo_operacoes_op c ON c.id = a.catalogo_operacao_id
            LEFT JOIN catalogo_pcp_ops p ON p.codigo_op = a.op
            LEFT JOIN eventos_apontamento_operador e ON e.apontamento_id = a.id
            WHERE COALESCE(a.data_inicio, a.data_entrada) <= %s
              AND COALESCE(a.data_fim, %s) >= %s
        """
        params = [end, end, start]
        if setor:
            query += " AND UPPER(a.tipo_setor) = UPPER(%s)"
            params.append(str(setor).strip())
        if recurso:
            query += " AND UPPER(a.maquina) = UPPER(%s)"
            params.append(str(recurso).strip())
        if op:
            query += " AND UPPER(a.op) = UPPER(%s)"
            params.append(limpa_codigo(op))
        if operacao:
            query += " AND a.numero_operacao = %s"
            params.append(str(operacao).strip())
        if produto:
            query += " AND UPPER(COALESCE(a.produto_codigo, '')) = UPPER(%s)"
            params.append(str(produto).strip())
        if operador:
            pattern = f"%{str(operador).strip()}%"
            query += """
                AND (
                    COALESCE(a.operador_fila, '') ILIKE %s
                    OR COALESCE(a.operador_inicio, '') ILIKE %s
                    OR COALESCE(a.operador_fim, '') ILIKE %s
                    OR EXISTS (
                        SELECT 1 FROM eventos_apontamento_operador eo
                        WHERE eo.apontamento_id = a.id
                          AND COALESCE(eo.operador, '') ILIKE %s
                    )
                )
            """
            params.extend((pattern, pattern, pattern, pattern))
        query += """
            GROUP BY a.id, c.tempo_medio_segundos, c.ordem,
                     p.data_liberacao, p.inicio_planejado, p.fim_planejado,
                     p.prazo_entrega, p.prioridade
            ORDER BY a.data_inicio, a.id
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def listar_tempos_nesting_corte(self, inicio=None, fim=None, maquina=None, search=None):
        """Retorna uma linha por nesting, preservando o tempo físico individual."""

        # Recortar uma execução aberta no fim da janela é correto, mas a janela
        # pode terminar no futuro: a tela envia `fim` como 23:59:59 do dia. Sem
        # limitar pelo agora, um nesting iniciado há um minuto apareceria com
        # horas de corte. Tempo que ainda não passou não é tempo produzido.
        agora = self._now()
        solicitado = _period_value(fim)
        as_of = min(solicitado, agora) if solicitado else agora
        query = """
            SELECT
                id AS apontamento_id,
                plano_hash,
                codigo_tarefa AS tarefa,
                programa,
                sequencia_nesting AS nesting,
                maquina,
                material,
                espessura,
                data_inicio AS inicio,
                data_fim AS fim,
                tempo_previsto_segundos AS previsto_segundos,
                EXTRACT(EPOCH FROM (COALESCE(data_fim, %s) - data_inicio))
                    AS real_segundos,
                status,
                operador_inicio,
                operador_fim
            FROM apontamentos_corte
            WHERE data_inicio IS NOT NULL
        """
        params = [as_of]
        if inicio:
            query += " AND COALESCE(data_fim, %s) >= %s"
            params.extend((as_of, _period_value(inicio)))
        if fim:
            query += " AND data_inicio <= %s"
            params.append(_period_value(fim))
        if maquina:
            query += " AND UPPER(maquina) = UPPER(%s)"
            params.append(str(maquina).strip())
        if search:
            pattern = f"%{str(search).strip()}%"
            query += " AND (codigo_tarefa ILIKE %s OR programa ILIKE %s OR COALESCE(material, '') ILIKE %s)"
            params.extend((pattern, pattern, pattern))
        query += " ORDER BY data_inicio DESC, id DESC"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = []
            for raw in cursor.fetchall():
                row = dict(raw)
                planned = float(row.get("previsto_segundos") or 0) or None
                real = float(row.get("real_segundos") or 0) if row.get("real_segundos") is not None else None
                deviation = (real - planned) if real is not None and planned is not None else None
                row["desvio_segundos"] = deviation
                row["desvio_percentual"] = (
                    (deviation / planned) * 100.0
                    if deviation is not None and planned
                    else None
                )
                period_start = _period_value(inicio) if inicio else None
                period_end = _period_value(fim) if fim else None
                execution_start = _period_value(row.get("inicio"))
                execution_end = _period_value(row.get("fim")) or as_of
                clipped_start = max(execution_start, period_start) if execution_start and period_start else execution_start
                clipped_end = min(execution_end, period_end) if execution_end and period_end else execution_end
                row["real_periodo_segundos"] = (
                    max(0.0, (clipped_end - clipped_start).total_seconds())
                    if clipped_start and clipped_end and clipped_end >= clipped_start
                    else 0.0
                )
                rows.append(row)
            return rows

    def listar_producao_corte_periodo(self, inicio, fim, maquina=None):
        """Produção do Corte por OP, a partir da execução real dos nestings.

        O Corte não escreve em ``apontamentos_operacionais`` nem em
        ``eventos_quantidade_producao``: a execução dele vive em
        ``apontamentos_corte``, e a quantidade por OP vive no vínculo
        SigmaNEST ``catalogo_sigmanest_ops``. Sem esta projeção o rollup
        gerencial de setor mostrava o Corte com ``boa = 0`` e ``ops = 0``
        mesmo com nestings concluídos.

        Uma tarefa só conta quando **todos** os planos ativos dela foram
        finalizados — é o mesmo critério que ``listar_roteiro_completo_op``
        usa para dizer que o Corte da OP terminou. O instante atribuído é o
        do último nesting concluído, e o recurso é a máquina desse nesting.
        Nenhuma quantidade é estimada: ela vem inteira do vínculo OP×tarefa.
        """

        query = """
            WITH tarefa_concluida AS (
                SELECT
                    plano.codigo_tarefa,
                    MAX(corte.data_fim) AS concluido_em,
                    (ARRAY_AGG(corte.maquina ORDER BY corte.data_fim DESC))[1]
                        AS maquina
                FROM catalogo_sigmanest_planos_corte plano
                JOIN apontamentos_corte corte
                  ON corte.plano_hash = plano.plano_hash
                WHERE plano.ativo = TRUE
                GROUP BY plano.codigo_tarefa
                HAVING COUNT(*) FILTER (WHERE corte.status = 'Finalizado') = COUNT(*)
                   AND COUNT(*) = (
                        SELECT COUNT(*)
                        FROM catalogo_sigmanest_planos_corte pendente
                        WHERE pendente.codigo_tarefa = plano.codigo_tarefa
                          AND pendente.ativo = TRUE
                   )
            )
            SELECT
                tarefa.codigo_tarefa,
                tarefa.concluido_em,
                tarefa.maquina,
                vinculo.codigo_op,
                SUM(vinculo.quantidade)::INTEGER AS quantidade
            FROM tarefa_concluida tarefa
            JOIN catalogo_sigmanest_ops vinculo
              ON vinculo.codigo_tarefa = tarefa.codigo_tarefa
             AND vinculo.ativo = TRUE
            WHERE tarefa.concluido_em IS NOT NULL
              AND tarefa.concluido_em >= %s
              AND tarefa.concluido_em <= %s
        """
        params = [_period_value(inicio), _period_value(fim)]
        if maquina:
            query += " AND UPPER(tarefa.maquina) = UPPER(%s)"
            params.append(str(maquina).strip())
        query += """
            GROUP BY
                tarefa.codigo_tarefa, tarefa.concluido_em,
                tarefa.maquina, vinculo.codigo_op
            HAVING SUM(vinculo.quantidade) > 0
            ORDER BY tarefa.concluido_em, vinculo.codigo_op
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def listar_nestings_corte_por_op(self, op):
        """Relaciona uma OP aos nestings de Corte sem depender da UI."""

        codigo = limpa_codigo(op)
        if not codigo:
            return []
        query = """
            SELECT
                ac.id AS apontamento_id, ac.plano_hash, ac.codigo_tarefa AS tarefa,
                ac.programa, ac.sequencia_nesting AS nesting, ac.maquina,
                ac.material, ac.espessura, ac.data_inicio AS inicio, ac.data_fim AS fim,
                ac.tempo_previsto_segundos AS previsto_segundos,
                EXTRACT(EPOCH FROM (COALESCE(ac.data_fim, %s) - ac.data_inicio))
                    AS real_segundos,
                ac.status, ac.operador_inicio, ac.operador_fim
            FROM apontamentos_corte ac
            WHERE ac.data_inicio IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM catalogo_sigmanest_ops so
                  WHERE so.codigo_tarefa = ac.codigo_tarefa
                    AND (
                        UPPER(so.codigo_op) = UPPER(%s)
                        OR LTRIM(so.codigo_op, '0') = LTRIM(%s, '0')
                    )
              )
            ORDER BY ac.data_inicio, ac.id
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, (self._now(), codigo, codigo))
            rows = []
            for raw in cursor.fetchall():
                row = dict(raw)
                planned = float(row.get("previsto_segundos") or 0) or None
                real = float(row.get("real_segundos") or 0) if row.get("real_segundos") is not None else None
                deviation = real - planned if real is not None and planned is not None else None
                row["desvio_segundos"] = deviation
                row["desvio_percentual"] = (deviation / planned * 100.0) if deviation is not None and planned else None
                rows.append(row)
            return rows

    @staticmethod
    def _categoria_estado_apontamento(status):
        return {
            "Em processo": "producao",
            "Parada": "parada",
            "Setup": "setup",
            "Retrabalho": "retrabalho",
        }.get(str(status or "").strip())

    def _estado_recurso_aberto_tx(self, cursor, recurso):
        cursor.execute(
            """
            SELECT *
            FROM eventos_estado_recurso
            WHERE UPPER(recurso) = UPPER(%s) AND data_fim IS NULL
            FOR UPDATE
            """,
            (str(recurso or "").strip(),),
        )
        return cursor.fetchone()

    def _encerrar_estado_recurso_tx(self, cursor, recurso, instante, *, somente_origem=None):
        resource = str(recurso or "").strip()
        if not resource:
            return None
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(UPPER(%s)))",
            (resource,),
        )
        current = self._estado_recurso_aberto_tx(cursor, resource)
        if not current:
            return None
        if somente_origem and str(current.get("origem") or "") != str(somente_origem):
            return dict(current)
        if current.get("data_inicio") and current["data_inicio"] > instante:
            # Não reescreve uma timeline posterior quando um scheduler recupera
            # retroativamente um evento antigo. A inconsistência fica auditável.
            result = dict(current)
            result["retroativo_ignorado"] = True
            return result
        cursor.execute(
            """
            UPDATE eventos_estado_recurso
            SET data_fim = %s
            WHERE id = %s AND data_fim IS NULL
            RETURNING *
            """,
            (instante, current["id"]),
        )
        return _as_dict(cursor.fetchone())

    def _transicionar_estado_recurso_tx(
        self, cursor, recurso, categoria, *, tipo_setor=None, operador=None,
        codigo_status_recurso=None, op=None, numero_operacao=None,
        produto_codigo=None, motivo=None, causa_raiz=None, comentario=None,
        data_hora=None, origem="gestor_pecas", referencia_origem=None,
        planejado=None, automatico=False, tipo_interrupcao=None,
        apontamento_id=None, evento_apontamento_id=None,
    ):
        instante = _period_value(data_hora) or agora_db()
        resource = str(recurso or "").strip()
        if not resource:
            raise ValueError("Recurso é obrigatório para registrar estado.")
        category = str(categoria or "").strip().lower()
        if category not in PHYSICAL_STATE_VALUES:
            raise ValueError(f"Categoria de estado inválida: {categoria}")

        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(UPPER(%s)))",
            (resource,),
        )
        current = self._estado_recurso_aberto_tx(cursor, resource)
        if current and current.get("data_inicio") and current["data_inicio"] > instante:
            result = dict(current)
            result["retroativo_ignorado"] = True
            return result

        # Várias OPs simultâneas em produção não devem fragmentar a timeline
        # física. Se o estado físico continua semanticamente igual, mantemos o
        # mesmo intervalo aberto; OPs/rateio ficam em estruturas próprias.
        if current:
            same_state = (
                str(current.get("categoria") or "") == category
                and str(current.get("codigo_status_recurso") or "") == str(codigo_status_recurso or "")
                and str(current.get("motivo") or "") == str(motivo or "")
                and str(current.get("causa_raiz") or "") == str(causa_raiz or "")
                and bool(current.get("automatico")) == bool(automatico)
                and str(current.get("tipo_interrupcao") or "") == str(tipo_interrupcao or "")
            )
            if same_state:
                return dict(current)
            cursor.execute(
                "UPDATE eventos_estado_recurso SET data_fim = %s WHERE id = %s AND data_fim IS NULL",
                (instante, current["id"]),
            )

        cursor.execute(
            """
            INSERT INTO eventos_estado_recurso (
                recurso, tipo_setor, categoria, codigo_status_recurso, op,
                numero_operacao, produto_codigo, operador, motivo, causa_raiz,
                comentario, data_inicio, origem, referencia_origem, planejado,
                automatico, tipo_interrupcao, apontamento_id, evento_apontamento_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            RETURNING *
            """,
            (
                resource, tipo_setor, category, codigo_status_recurso,
                limpa_codigo(op) if op else None, numero_operacao, produto_codigo,
                operador, motivo, causa_raiz, comentario, instante,
                str(origem or "gestor_pecas"), referencia_origem, planejado,
                bool(automatico), tipo_interrupcao, apontamento_id,
                evento_apontamento_id,
            ),
        )
        return dict(cursor.fetchone())

    def _reconciliar_estado_recurso_apontamentos_tx(
        self, cursor, recurso, instante, *, operador=None, origem="apontamento_operador",
        referencia_origem=None, evento_apontamento_id=None,
    ):
        """Deriva um único estado físico a partir das OPs ativas do recurso.

        Simultaneidade com o mesmo estado é válida. Estados distintos no mesmo
        instante viram ``desconhecido``; escolher um vencedor corromperia a
        verdade física e os indicadores.
        """

        resource = str(recurso or "").strip()
        if not resource:
            return None
        cursor.execute(
            """
            SELECT *
            FROM apontamentos_operacionais
            WHERE UPPER(COALESCE(maquina, '')) = UPPER(%s)
              AND status IN ('Em processo', 'Parada', 'Setup', 'Retrabalho')
              AND data_inicio IS NOT NULL
              AND data_inicio <= %s
              AND (data_fim IS NULL OR data_fim > %s)
            ORDER BY id
            """,
            (resource, instante, instante),
        )
        active = [dict(row) for row in cursor.fetchall()]
        if not active:
            return self._encerrar_estado_recurso_tx(cursor, resource, instante)

        categories = {
            self._categoria_estado_apontamento(row.get("status"))
            for row in active
        }
        categories.discard(None)
        sector_values = {
            str(row.get("tipo_setor") or "").strip()
            for row in active if str(row.get("tipo_setor") or "").strip()
        }
        sector = next(iter(sector_values)) if len(sector_values) == 1 else None

        reason_values = {
            str(row.get("motivo_parada") or "").strip()
            for row in active if str(row.get("motivo_parada") or "").strip()
        }
        status_codes = {
            str(row.get("codigo_status_recurso") or "").strip()
            for row in active if str(row.get("codigo_status_recurso") or "").strip()
        }

        conflict = len(categories) != 1
        if categories == {"parada"} and (len(reason_values) > 1 or len(status_codes) > 1):
            conflict = True

        if conflict:
            category = "desconhecido"
            status_code = None
            reason = "Estados simultâneos incompatíveis no mesmo recurso"
            planned = None
        else:
            category = next(iter(categories))
            status_code = next(iter(status_codes)) if len(status_codes) == 1 else None
            reason = next(iter(reason_values)) if len(reason_values) == 1 else None
            # Parada manual é sempre não programada pela regra da Manufatura.
            planned = False if category == "parada" else None

        single = active[0] if len(active) == 1 else None
        return self._transicionar_estado_recurso_tx(
            cursor,
            resource,
            category,
            tipo_setor=sector,
            operador=operador,
            codigo_status_recurso=status_code,
            op=single.get("op") if single else None,
            numero_operacao=single.get("numero_operacao") if single else None,
            produto_codigo=single.get("produto_codigo") if single else None,
            motivo=reason,
            data_hora=instante,
            origem=origem,
            referencia_origem=referencia_origem,
            planejado=planned,
            automatico=False,
            apontamento_id=single.get("id") if single else None,
            evento_apontamento_id=evento_apontamento_id,
        )

    def possui_calendario_produtivo(self, setor=None, recurso=None):
        query = """
            SELECT EXISTS (
                SELECT 1
                FROM catalogo_recursos_pcfactory r
                JOIN calendarios_produtivos c
                  ON c.codigo = r.calendario_codigo AND c.ativo IS TRUE
                JOIN turnos_produtivos t
                  ON t.calendario_codigo = c.codigo AND t.ativo IS TRUE
                WHERE r.habilitado IS TRUE
        """
        params = []
        if recurso:
            query += " AND (UPPER(r.nome) = UPPER(%s) OR UPPER(r.codigo) = UPPER(%s))"
            resource = str(recurso).strip()
            params.extend((resource, resource))
        elif setor:
            query += " AND UPPER(COALESCE(r.tipo_setor, '')) = UPPER(%s)"
            params.append(str(setor).strip())
        query += ") AS existe"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()
            return bool(row and row["existe"])

    def transicionar_estado_recurso(
        self, recurso, categoria, *, tipo_setor=None, operador=None,
        codigo_status_recurso=None, op=None, numero_operacao=None,
        produto_codigo=None, motivo=None, causa_raiz=None, comentario=None,
        data_hora=None, origem="gestor_pecas", referencia_origem=None,
        planejado=None, automatico=False, tipo_interrupcao=None,
        apontamento_id=None, evento_apontamento_id=None,
    ):
        """Transiciona o estado físico canônico do recurso.

        O método é idempotente para o mesmo estado físico. OPs simultâneas não
        criam minutos adicionais; associação OP↔tempo permanece em rateio e
        fatos operacionais.
        """

        instante = _period_value(data_hora) or agora_db()
        with self.connection() as connection, connection.cursor() as cursor:
            return self._transicionar_estado_recurso_tx(
                cursor,
                recurso,
                categoria,
                tipo_setor=tipo_setor,
                operador=operador,
                codigo_status_recurso=codigo_status_recurso,
                op=op,
                numero_operacao=numero_operacao,
                produto_codigo=produto_codigo,
                motivo=motivo,
                causa_raiz=causa_raiz,
                comentario=comentario,
                data_hora=instante,
                origem=origem,
                referencia_origem=referencia_origem,
                planejado=planejado,
                automatico=automatico,
                tipo_interrupcao=tipo_interrupcao,
                apontamento_id=apontamento_id,
                evento_apontamento_id=evento_apontamento_id,
            )

    def encerrar_estado_recurso(self, recurso, *, data_hora=None, somente_origem=None):
        instante = _period_value(data_hora) or agora_db()
        with self.connection() as connection, connection.cursor() as cursor:
            return self._encerrar_estado_recurso_tx(
                cursor, recurso, instante, somente_origem=somente_origem
            )

    def buscar_estado_recurso_atual(self, recurso):
        resource = str(recurso or "").strip()
        if not resource:
            return None
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM eventos_estado_recurso
                WHERE UPPER(recurso) = UPPER(%s) AND data_fim IS NULL
                ORDER BY data_inicio DESC, id DESC
                LIMIT 1
                """,
                (resource,),
            )
            return _as_dict(cursor.fetchone())

    def listar_estados_recurso_atuais(
        self,
        *,
        setor=None,
        recurso=None,
        reference_time=None,
    ):
        query = """
            SELECT *
            FROM eventos_estado_recurso
            WHERE data_fim IS NULL
        """
        params = []
        reference = _period_value(reference_time)
        if reference is not None:
            query += " AND data_inicio <= %s"
            params.append(reference)
        if setor:
            query += " AND UPPER(COALESCE(tipo_setor, '')) = UPPER(%s)"
            params.append(str(setor).strip())
        if recurso:
            query += " AND UPPER(recurso) = UPPER(%s)"
            params.append(str(recurso).strip())
        query += " ORDER BY COALESCE(tipo_setor, ''), recurso, data_inicio"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def listar_estados_recurso_periodo(
        self, inicio, fim, *, setor=None, recurso=None, categoria=None,
        op=None, operacao=None,
    ):
        start = _period_value(inicio)
        end = _period_value(fim)
        if start is None or end is None or end <= start:
            return []
        # O grupo/taxonomia do catálogo PCFactory viaja junto com o estado para
        # que a classificação PLANEJADA/NÃO_PLANEJADA seja decidida uma única vez
        # no domínio, sem uma consulta por parada.
        query = """
            SELECT e.*,
                   s.nome AS status_nome,
                   s.grupo_codigo AS status_grupo_codigo,
                   s.grupo_nome AS status_grupo_nome,
                   s.planejado AS status_planejado
            FROM eventos_estado_recurso e
            LEFT JOIN catalogo_status_recursos s
                   ON s.codigo = e.codigo_status_recurso
            WHERE e.data_inicio < %s
              AND COALESCE(e.data_fim, %s) > %s
        """
        params = [end, end, start]
        if setor:
            query += " AND UPPER(COALESCE(e.tipo_setor, '')) = UPPER(%s)"
            params.append(str(setor).strip())
        if recurso:
            query += " AND UPPER(e.recurso) = UPPER(%s)"
            params.append(str(recurso).strip())
        if categoria:
            query += " AND e.categoria = %s"
            params.append(str(categoria).strip().lower())
        if op:
            query += " AND UPPER(COALESCE(e.op, '')) = UPPER(%s)"
            params.append(limpa_codigo(op))
        if operacao is not None:
            query += " AND COALESCE(e.numero_operacao, '') = %s"
            params.append(str(operacao))
        query += " ORDER BY e.recurso, e.data_inicio, e.id"

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            result = []
            for raw in cursor.fetchall():
                row = dict(raw)
                state_start = _period_value(row.get("data_inicio"))
                state_end = _period_value(row.get("data_fim")) or end
                row["inicio_periodo"] = max(state_start, start)
                row["fim_periodo"] = min(state_end, end)
                row["segundos_periodo"] = max(
                    0.0,
                    (row["fim_periodo"] - row["inicio_periodo"]).total_seconds(),
                )
                result.append(row)
            return result

    def listar_intervalos_turno(self, turno_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM intervalos_turno_produtivo
                WHERE turno_id = %s AND ativo IS TRUE
                ORDER BY hora_inicio, id
                """,
                (turno_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def listar_excecoes_calendario_periodo(self, calendario_codigo, inicio, fim):
        start = _period_value(inicio)
        end = _period_value(fim)
        if start is None or end is None or end <= start:
            return []
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT *
                FROM excecoes_calendario_produtivo
                WHERE calendario_codigo = %s
                  AND ativo IS TRUE
                  AND data BETWEEN %s AND %s
                ORDER BY data, hora_inicio NULLS FIRST, id
                """,
                (str(calendario_codigo), start.date(), end.date()),
            )
            return [dict(row) for row in cursor.fetchall()]

    def registrar_evento_quantidade(
        self, tipo, quantidade, op, *, numero_operacao=None, produto_codigo=None,
        recurso=None, tipo_setor=None, operador=None, lote=None, motivo=None,
        causa_raiz=None, comentario=None, data_hora=None, origem="gestor_pecas",
        referencia_origem=None, connection=None,
    ):
        kind = str(tipo or "").strip().lower()
        if kind not in {"boa", "refugo", "retrabalho"}:
            raise ValueError(f"Tipo de quantidade inválido: {tipo}")
        qty = int(quantidade or 0)
        if qty <= 0:
            return None
        instante = _period_value(data_hora) or agora_db()

        def _insert(conn):
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO eventos_quantidade_producao (
                        tipo, quantidade, op, numero_operacao, produto_codigo,
                        recurso, tipo_setor, operador, lote, motivo, causa_raiz,
                        comentario, data_hora, origem, referencia_origem
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        kind, qty, limpa_codigo(op), numero_operacao, produto_codigo,
                        recurso, tipo_setor, operador, lote, motivo, causa_raiz,
                        comentario, instante, str(origem or "gestor_pecas"),
                        referencia_origem,
                    ),
                )
                return dict(cursor.fetchone())

        if connection is not None:
            return _insert(connection)
        with self.connection() as conn:
            return _insert(conn)

    def listar_eventos_quantidade_periodo(
        self, inicio, fim, *, setor=None, recurso=None, op=None, operacao=None, produto=None,
        operador=None,
    ):
        query = """
            SELECT * FROM eventos_quantidade_producao
            WHERE data_hora >= %s AND data_hora <= %s
        """
        params = [_period_value(inicio), _period_value(fim)]
        if setor:
            query += " AND UPPER(COALESCE(tipo_setor, '')) = UPPER(%s)"
            params.append(str(setor).strip())
        if recurso:
            query += " AND UPPER(COALESCE(recurso, '')) = UPPER(%s)"
            params.append(str(recurso).strip())
        if op:
            query += " AND UPPER(op) = UPPER(%s)"
            params.append(limpa_codigo(op))
        if operacao:
            query += " AND numero_operacao = %s"
            params.append(str(operacao).strip())
        if produto:
            query += " AND UPPER(COALESCE(produto_codigo, '')) = UPPER(%s)"
            params.append(str(produto).strip())
        if operador:
            query += " AND COALESCE(operador, '') ILIKE %s"
            params.append(f"%{str(operador).strip()}%")
        query += " ORDER BY data_hora, id"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def salvar_calendario_produtivo(self, codigo, nome, *, timezone="America/Sao_Paulo", ativo=True):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO calendarios_produtivos (codigo, nome, timezone, ativo)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (codigo) DO UPDATE SET
                    nome = EXCLUDED.nome,
                    timezone = EXCLUDED.timezone,
                    ativo = EXCLUDED.ativo
                RETURNING *
                """,
                (str(codigo).strip(), str(nome).strip(), str(timezone).strip(), bool(ativo)),
            )
            return dict(cursor.fetchone())

    def salvar_turno_produtivo(
        self, calendario_codigo, nome, dia_semana, hora_inicio, hora_fim, *,
        cruza_meia_noite=False, minutos_intervalo=0, ativo=True,
    ):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO turnos_produtivos (
                    calendario_codigo, nome, dia_semana, hora_inicio, hora_fim,
                    cruza_meia_noite, minutos_intervalo, ativo
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (calendario_codigo, nome, dia_semana, hora_inicio)
                DO UPDATE SET
                    hora_fim = EXCLUDED.hora_fim,
                    cruza_meia_noite = EXCLUDED.cruza_meia_noite,
                    minutos_intervalo = EXCLUDED.minutos_intervalo,
                    ativo = EXCLUDED.ativo
                RETURNING *
                """,
                (
                    str(calendario_codigo).strip(), str(nome).strip(), int(dia_semana),
                    hora_inicio, hora_fim, bool(cruza_meia_noite),
                    max(0, int(minutos_intervalo or 0)), bool(ativo),
                ),
            )
            return dict(cursor.fetchone())

    def salvar_intervalo_turno_produtivo(
        self, turno_id, nome, hora_inicio, hora_fim, *, desconta_tempo=True, ativo=True,
    ):
        """Persiste um intervalo exato sem inferir sua posição no turno."""

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO intervalos_turno_produtivo (
                    turno_id, nome, hora_inicio, hora_fim, desconta_tempo, ativo
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (turno_id, hora_inicio, hora_fim)
                DO UPDATE SET
                    nome = EXCLUDED.nome,
                    desconta_tempo = EXCLUDED.desconta_tempo,
                    ativo = EXCLUDED.ativo
                RETURNING *
                """,
                (
                    int(turno_id), str(nome or "Intervalo").strip(),
                    hora_inicio, hora_fim, bool(desconta_tempo), bool(ativo),
                ),
            )
            return dict(cursor.fetchone())

    def vincular_calendario_recurso(
        self, recurso_codigo, calendario_codigo, *, capacidade_valor=None, capacidade_unidade=None
    ):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE catalogo_recursos_pcfactory
                SET calendario_codigo = %s,
                    capacidade_valor = %s,
                    capacidade_unidade = %s
                WHERE codigo = %s
                RETURNING *
                """,
                (
                    calendario_codigo,
                    capacidade_valor,
                    capacidade_unidade,
                    str(recurso_codigo).strip(),
                ),
            )
            return _as_dict(cursor.fetchone())

    def listar_turnos_recurso(self, recurso_codigo):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.*, c.timezone, c.nome AS calendario_nome
                FROM catalogo_recursos_pcfactory r
                JOIN calendarios_produtivos c
                  ON c.codigo = r.calendario_codigo AND c.ativo IS TRUE
                JOIN turnos_produtivos t
                  ON t.calendario_codigo = c.codigo AND t.ativo IS TRUE
                WHERE r.codigo = %s AND r.habilitado IS TRUE
                ORDER BY t.dia_semana, t.hora_inicio, t.id
                """,
                (str(recurso_codigo).strip(),),
            )
            return [dict(row) for row in cursor.fetchall()]

    def listar_configuracao_capacidade_recursos(self, *, setor=None, recurso=None):
        """Expõe configuração, sem calcular capacidade restante por conta própria.

        Wave 6F — o cadastro da Solda Aço herdou 41 recursos do PC Factory que
        descrevem etapas de solda antigas e nunca aparecem no roteiro de uma OP.
        Eles continuam no catálogo (rastreabilidade e sincronização com o TOTVS
        dependem disso), mas não são posto de trabalho nem linha de capacidade:
        exibi-los enchia a tela de Capacidade de recursos inexistentes na
        prática. A regra é reativa e vale só para esse setor: o recurso de Solda
        Aço volta a aparecer sozinho no dia em que uma OP real o referenciar em
        ``catalogo_operacoes_op``. Nenhum outro setor é filtrado.
        """

        query = """
            SELECT
                r.codigo, r.nome, r.tipo_setor, r.capacidade_valor,
                r.capacidade_unidade, r.calendario_codigo,
                c.nome AS calendario_nome, c.timezone
            FROM catalogo_recursos_pcfactory r
            LEFT JOIN calendarios_produtivos c ON c.codigo = r.calendario_codigo
            WHERE r.habilitado IS TRUE
              AND (
                UPPER(COALESCE(r.tipo_setor, '')) <> UPPER(%s)
                OR EXISTS (
                    SELECT 1 FROM catalogo_operacoes_op o
                    WHERE UPPER(BTRIM(o.codigo_recurso)) = UPPER(BTRIM(r.codigo))
                )
              )
        """
        params = [CATALOG_ONLY_RESOURCE_SECTOR]
        if setor:
            query += " AND UPPER(COALESCE(r.tipo_setor, '')) = UPPER(%s)"
            params.append(str(setor).strip())
        if recurso:
            query += " AND (UPPER(r.codigo) = UPPER(%s) OR UPPER(r.nome) = UPPER(%s))"
            resource = str(recurso).strip()
            params.extend((resource, resource))
        query += " ORDER BY COALESCE(r.tipo_setor, ''), r.nome, r.codigo"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def registrar_rateio_recurso(
        self, recurso, inicio, fim, allocations, *, tipo_setor=None,
        origem="gestor_pecas", referencia_origem=None,
    ):
        """Persiste uma sessão física e seus tempos atribuídos atomicamente."""

        start = _period_value(inicio)
        end = _period_value(fim)
        if start is None or end is None or end < start:
            raise ValueError("Período inválido para sessão de recurso.")
        physical = max(0.0, (end - start).total_seconds())
        allocation_rows = [dict(item) for item in allocations or ()]
        if not allocation_rows and physical > 0:
            raise ValueError("Sessão com tempo físico positivo exige ao menos uma OP para rateio.")
        if any(not limpa_codigo(item.get("op")) for item in allocation_rows):
            raise ValueError("Todos os itens do rateio devem possuir OP.")
        allocated = sum(float(item.get("segundos_atribuidos") or 0) for item in allocation_rows)
        if abs(allocated - physical) > 0.01:
            raise ValueError(
                "A soma dos tempos atribuídos deve ser igual ao tempo físico da sessão."
            )
        with self.connection() as connection, connection.cursor() as cursor:
            # Serializa sessões do mesmo recurso e recusa sobreposição física.
            # Assim duas requisições Web simultâneas não conseguem
            # transformar 60 minutos reais em duas sessões concorrentes.
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(UPPER(%s)))",
                (str(recurso or "").strip(),),
            )
            cursor.execute(
                """
                SELECT id FROM sessoes_recurso
                WHERE UPPER(recurso) = UPPER(%s)
                  AND data_inicio < %s
                  AND COALESCE(data_fim, 'infinity'::timestamp) > %s
                LIMIT 1
                """,
                (str(recurso or "").strip(), end, start),
            )
            if cursor.fetchone():
                raise ValueError("Já existe uma sessão física sobreposta para este recurso.")
            cursor.execute(
                """
                INSERT INTO sessoes_recurso (
                    recurso, tipo_setor, data_inicio, data_fim, segundos_fisicos,
                    origem, referencia_origem
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    str(recurso or "").strip(), tipo_setor, start, end, physical,
                    str(origem or "gestor_pecas"), referencia_origem,
                ),
            )
            session = dict(cursor.fetchone())
            rows = []
            for item in allocation_rows:
                cursor.execute(
                    """
                    INSERT INTO rateios_tempo_op (
                        sessao_recurso_id, op, numero_operacao, estrategia,
                        peso, segundos_atribuidos
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        session["id"], limpa_codigo(item.get("op")),
                        item.get("numero_operacao"), item.get("estrategia"),
                        item.get("peso"), float(item.get("segundos_atribuidos") or 0),
                    ),
                )
                rows.append(dict(cursor.fetchone()))
            session["rateios"] = rows
            return session

    def listar_rateios_tempo_periodo(
        self, inicio, fim, *, setor=None, recurso=None, op=None, operacao=None,
    ):
        """Lista sessões físicas e rateios recortados ao período solicitado.

        O tempo físico da sessão nunca é multiplicado pela quantidade de OPs.
        Quando o filtro corta parcialmente uma sessão, o tempo atribuído é
        recortado na mesma proporção temporal da sessão, pois o rateio é definido
        para todo o intervalo físico persistido.
        """

        start = _period_value(inicio)
        end = _period_value(fim)
        if start is None or end is None or end <= start:
            return []

        join_filters = []
        join_params = []
        if op:
            join_filters.append("UPPER(r.op) = UPPER(%s)")
            join_params.append(limpa_codigo(op))
        if operacao is not None:
            join_filters.append("COALESCE(r.numero_operacao, '') = %s")
            join_params.append(str(operacao))

        join_clause = ""
        if join_filters:
            join_clause = " AND " + " AND ".join(join_filters)

        query = f"""
            SELECT
                s.id AS sessao_id, s.recurso, s.tipo_setor, s.data_inicio,
                s.data_fim, s.segundos_fisicos, s.origem, s.referencia_origem,
                r.id AS rateio_id, r.op, r.numero_operacao, r.estrategia,
                r.peso, r.segundos_atribuidos
            FROM sessoes_recurso s
            LEFT JOIN rateios_tempo_op r
              ON r.sessao_recurso_id = s.id{join_clause}
            WHERE s.data_inicio < %s
              AND COALESCE(s.data_fim, %s) > %s
        """
        params = list(join_params) + [end, end, start]
        if setor:
            query += " AND UPPER(COALESCE(s.tipo_setor, '')) = UPPER(%s)"
            params.append(str(setor).strip())
        if recurso:
            query += " AND UPPER(s.recurso) = UPPER(%s)"
            params.append(str(recurso).strip())
        if join_filters:
            query += " AND r.id IS NOT NULL"
        query += " ORDER BY s.data_inicio, s.id, r.id"

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = [dict(row) for row in cursor.fetchall()]

        sessions = {}
        for row in rows:
            session_id = row["sessao_id"]
            session = sessions.get(session_id)
            if session is None:
                session_start = _period_value(row.get("data_inicio"))
                session_end = _period_value(row.get("data_fim")) or end
                clip_start = max(session_start, start)
                clip_end = min(session_end, end)
                period_seconds = max(0.0, (clip_end - clip_start).total_seconds())
                full_seconds = float(row.get("segundos_fisicos") or 0)
                if full_seconds <= 0 and session_end > session_start:
                    full_seconds = (session_end - session_start).total_seconds()
                session = {
                    "id": session_id,
                    "recurso": row.get("recurso"),
                    "tipo_setor": row.get("tipo_setor"),
                    "data_inicio": session_start,
                    "data_fim": _period_value(row.get("data_fim")),
                    "segundos_fisicos": float(row.get("segundos_fisicos") or full_seconds or 0),
                    "inicio_periodo": clip_start,
                    "fim_periodo": clip_end,
                    "segundos_fisicos_periodo": period_seconds,
                    "origem": row.get("origem"),
                    "referencia_origem": row.get("referencia_origem"),
                    "rateios": [],
                }
                sessions[session_id] = session

            if row.get("rateio_id") is not None:
                full_seconds = float(session.get("segundos_fisicos") or 0)
                ratio = (
                    float(session["segundos_fisicos_periodo"]) / full_seconds
                    if full_seconds > 0 else 0.0
                )
                attributed = float(row.get("segundos_atribuidos") or 0)
                session["rateios"].append({
                    "id": row.get("rateio_id"),
                    "op": row.get("op"),
                    "numero_operacao": row.get("numero_operacao"),
                    "estrategia": row.get("estrategia"),
                    "peso": row.get("peso"),
                    "segundos_atribuidos": attributed,
                    "segundos_atribuidos_periodo": attributed * ratio,
                })

        return list(sessions.values())

    def iniciar_participacao_operador(
        self, recurso, *, operador_id=None, cracha=None, nome=None, tipo_setor=None,
        op=None, numero_operacao=None, data_inicio=None, origem="gestor_pecas",
        referencia_origem=None, apontamento_id=None, tipo_participacao=None,
        operador_principal=False,
    ):
        """Abre o tempo-pessoa de alguém nesta execução da OP.

        O índice parcial ``uq_participacao_aberta_apontamento`` garante uma
        única participação aberta por pessoa no mesmo apontamento: a mesma
        pessoa não entra duas vezes em silêncio. Reentrar devolve a
        participação que já estava aberta em vez de criar uma segunda.
        """

        inicio = _period_value(data_inicio) or agora_db()
        with self.connection() as connection, connection.cursor() as cursor:
            if apontamento_id is not None:
                cursor.execute(
                    """
                    SELECT * FROM participacoes_operador
                    WHERE apontamento_id = %s
                      AND UPPER(COALESCE(cracha, '')) = UPPER(COALESCE(%s, ''))
                      AND data_fim IS NULL
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (apontamento_id, cracha),
                )
                aberta = _as_dict(cursor.fetchone())
                if aberta is not None:
                    return aberta
            try:
                cursor.execute(
                    """
                    INSERT INTO participacoes_operador (
                        operador_id, cracha, nome, recurso, tipo_setor, op,
                        numero_operacao, data_inicio, origem, referencia_origem,
                        apontamento_id, tipo_participacao, operador_principal
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        operador_id, cracha, nome, str(recurso or "").strip(),
                        tipo_setor, limpa_codigo(op) if op else None, numero_operacao,
                        inicio, str(origem or "gestor_pecas"), referencia_origem,
                        apontamento_id, tipo_participacao, bool(operador_principal),
                    ),
                )
            except UniqueViolation:
                # Corrida entre dois postos/abas registrando a mesma pessoa: o
                # índice é a autoridade e a participação já existente vale.
                connection.rollback()
                with connection.cursor() as retry:
                    retry.execute(
                        """
                        SELECT * FROM participacoes_operador
                        WHERE apontamento_id = %s
                          AND UPPER(COALESCE(cracha, '')) = UPPER(COALESCE(%s, ''))
                          AND data_fim IS NULL
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (apontamento_id, cracha),
                    )
                    return _as_dict(retry.fetchone())
            return _as_dict(cursor.fetchone())

    def listar_participacoes_apontamento(self, apontamento_id, *, somente_abertas=False):
        """Participações de uma execução, base do tempo-pessoa da OP."""

        query = """
            SELECT * FROM participacoes_operador
            WHERE apontamento_id = %s
        """
        params = [apontamento_id]
        if somente_abertas:
            query += " AND data_fim IS NULL"
        query += " ORDER BY data_inicio, id"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def finalizar_participacoes_apontamento(
        self, apontamento_id, *, data_fim=None, crachas=None
    ):
        """Fecha participações abertas do apontamento.

        Sem ``crachas`` fecha todas (fim da execução). Com ``crachas`` fecha só
        aquelas pessoas — é a troca de operador, que não interrompe o tempo de
        quem continuou.
        """

        fim = _period_value(data_fim) or agora_db()
        query = """
            UPDATE participacoes_operador
            SET data_fim = %s
            WHERE apontamento_id = %s
              AND data_fim IS NULL
              AND data_inicio <= %s
        """
        params = [fim, apontamento_id, fim]
        alvo = [str(item or "").strip() for item in (crachas or ()) if str(item or "").strip()]
        if crachas is not None:
            if not alvo:
                return []
            query += " AND UPPER(COALESCE(cracha, '')) = ANY(%s)"
            params.append([item.upper() for item in alvo])
        query += " RETURNING *"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def listar_participacoes_operador_periodo(
        self, inicio, fim, *, recurso=None, setor=None, op=None, operacao=None,
        cracha=None,
    ):
        start = _period_value(inicio)
        end = _period_value(fim)
        if start is None or end is None or end <= start:
            return []
        query = """
            SELECT *
            FROM participacoes_operador
            WHERE data_inicio < %s
              AND COALESCE(data_fim, %s) > %s
        """
        params = [end, end, start]
        if recurso:
            query += " AND UPPER(recurso) = UPPER(%s)"
            params.append(str(recurso).strip())
        if setor:
            query += " AND UPPER(COALESCE(tipo_setor, '')) = UPPER(%s)"
            params.append(str(setor).strip())
        if op:
            query += " AND UPPER(COALESCE(op, '')) = UPPER(%s)"
            params.append(limpa_codigo(op))
        if operacao is not None:
            query += " AND COALESCE(numero_operacao, '') = %s"
            params.append(str(operacao))
        if cracha:
            query += " AND UPPER(COALESCE(cracha, '')) = UPPER(%s)"
            params.append(str(cracha).strip())
        query += " ORDER BY data_inicio, id"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def finalizar_participacao_operador(self, participacao_id, data_fim=None):
        fim = _period_value(data_fim) or agora_db()
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE participacoes_operador
                SET data_fim = %s
                WHERE id = %s AND data_fim IS NULL AND data_inicio <= %s
                RETURNING *
                """,
                (fim, participacao_id, fim),
            )
            return _as_dict(cursor.fetchone())

    def registrar_inconsistencia_dados(
        self, tipo, severidade, descricao, *, entidade=None, entidade_id=None,
        op=None, numero_operacao=None, recurso=None, operador=None,
    ):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO inconsistencias_dados (
                    tipo, severidade, descricao, entidade, entidade_id, op,
                    numero_operacao, recurso, operador
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    str(tipo), str(severidade), str(descricao), entidade,
                    str(entidade_id) if entidade_id is not None else None,
                    limpa_codigo(op) if op else None, numero_operacao, recurso, operador,
                ),
            )
            return dict(cursor.fetchone())

    def listar_inconsistencias_dados(self, *, somente_abertas=True, severidade=None):
        query = "SELECT * FROM inconsistencias_dados WHERE TRUE"
        params = []
        if somente_abertas:
            query += " AND resolvida IS FALSE"
        if severidade:
            query += " AND severidade = %s"
            params.append(str(severidade))
        query += " ORDER BY detectada_em DESC, id DESC"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def listar_eventos_apontamento_operador(self, apontamento_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    evento.*,
                    COALESCE(
                        (
                            SELECT jsonb_agg(
                                jsonb_build_object(
                                    'cracha', operador.cracha,
                                    'nome', operador.nome
                                ) ORDER BY operador.cracha
                            )
                            FROM operadores_evento_apontamento vinculo
                            JOIN operadores_apontamento operador
                              ON operador.id = vinculo.operador_id
                            WHERE vinculo.evento_id = evento.id
                        ),
                        '[]'::jsonb
                    ) AS operadores
                FROM eventos_apontamento_operador evento
                WHERE evento.apontamento_id = %s
                ORDER BY evento.data_hora, evento.id
                """,
                (apontamento_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def definir_tempo_padrao_operacao(
        self, codigo_op, segundos_por_peca, *, origem, somente_ausente=True
    ):
        """Preenche o tempo padrão/ciclo de uma OP quando ele não existe.

        O ``ProductionOrder`` do TOTVS chega sem tempo padrão confiável e a
        ingestão grava ``NULL`` de propósito — estimar ali seria inventar dado
        corporativo. Mas sem tempo padrão a Performance do OEE fica em zero, e
        um turno simulado inteiro perde significado.

        Por isso esta função existe: ela preenche o tempo **somente** quando
        ele está ausente e registra a origem em ``eventos_sistema``, para que
        qualquer leitura posterior saiba que aquele valor é sintético. Ela não
        sobrescreve tempo real e não toca em apontamento.
        """

        codigo = limpa_codigo(codigo_op)
        segundos = max(0.0, float(segundos_por_peca or 0.0))
        if not codigo or segundos <= 0:
            return 0
        condicao = (
            " AND (tempo_medio_segundos IS NULL OR tempo_medio_segundos <= 0)"
            if somente_ausente
            else ""
        )
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE catalogo_operacoes_op SET tempo_medio_segundos = %s"
                " WHERE codigo_op = %s AND marco_terminal IS FALSE" + condicao,
                (segundos, codigo),
            )
            atualizadas = cursor.rowcount or 0
        if atualizadas:
            self.registrar_evento_sistema(
                tipo="tempo_padrao_sintetico",
                origem=str(origem or "SIMULAÇÃO"),
                referencia=codigo,
                mensagem=(
                    f"Tempo padrão sintético de {segundos:.1f}s por peça aplicado a "
                    f"{atualizadas} operação(ões) sem tempo real."
                ),
                operador=str(origem or "SIMULAÇÃO"),
            )
        return atualizadas

    def cadastrar_operador_apontamento(
        self,
        cracha,
        nome,
        *,
        ativo=True,
        fonte="cadastro",
        autorizador_retrabalho=None,
    ):
        """Cadastra/atualiza um crachá do chão de fábrica.

        ``autorizador_retrabalho`` designa o responsável habilitado a liberar o
        retrabalho da primeira peça (Wave 5). ``None`` preserva a designação
        atual: um cadastro de rotina não pode revogar silenciosamente quem a
        gestão nomeou.
        """

        cracha = str(cracha or "").strip()
        nome = str(nome or "").strip()
        if not cracha or not nome:
            raise ValueError("Crachá e nome do operador são obrigatórios.")
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO operadores_apontamento (
                    cracha, nome, ativo, fonte, autorizador_retrabalho
                )
                VALUES (%s, %s, %s, %s, COALESCE(%s, FALSE))
                ON CONFLICT (cracha) DO UPDATE SET
                    nome = EXCLUDED.nome,
                    ativo = EXCLUDED.ativo,
                    fonte = EXCLUDED.fonte,
                    autorizador_retrabalho = COALESCE(
                        %s, operadores_apontamento.autorizador_retrabalho
                    )
                RETURNING *
                """,
                (
                    cracha,
                    nome,
                    bool(ativo),
                    str(fonte or "cadastro").strip(),
                    None if autorizador_retrabalho is None else bool(autorizador_retrabalho),
                    None if autorizador_retrabalho is None else bool(autorizador_retrabalho),
                ),
            )
            return dict(cursor.fetchone())

    def listar_operadores_apontamento(self, somente_ativos=True):
        query = "SELECT * FROM operadores_apontamento"
        if somente_ativos:
            query += " WHERE ativo = TRUE"
        query += " ORDER BY cracha, nome"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    def buscar_operadores_apontamento(self, crachas):
        valores = list(
            dict.fromkeys(
                str(cracha or "").strip()
                for cracha in (crachas or ())
                if str(cracha or "").strip()
            )
        )
        if not valores:
            return []
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM operadores_apontamento
                WHERE cracha = ANY(%s) AND ativo = TRUE
                ORDER BY array_position(%s::TEXT[], cracha)
                """,
                (valores, valores),
            )
            return [dict(row) for row in cursor.fetchall()]

    def listar_historico_operador(
        self,
        tipo_setor,
        maquina=None,
        data_referencia=None,
        *,
        limite=None,
        deslocamento=0,
    ):
        query = """
            SELECT
                apontamento.*,
                COALESCE(apontamento.numero_operacao, '') AS operation,
                COALESCE(apontamento.produto_codigo, apontamento.peca, '') AS product,
                COALESCE(apontamento.produto_descricao, apontamento.peca, '') AS description,
                apontamento.quantidade AS qty,
                apontamento.quantidade_boa AS good,
                apontamento.quantidade_refugo AS scrap,
                GREATEST(
                    0,
                    EXTRACT(EPOCH FROM (
                        COALESCE(apontamento.data_fim, %s) - apontamento.data_inicio
                    ))
                )::BIGINT AS elapsed_seconds
            FROM apontamentos_operacionais apontamento
            WHERE UPPER(apontamento.tipo_setor) = UPPER(%s)
        """
        params = [self._now(), str(tipo_setor or "").strip()]
        if maquina:
            query += " AND UPPER(apontamento.maquina) = UPPER(%s)"
            params.append(str(maquina).strip())
        if data_referencia:
            query += " AND DATE(COALESCE(apontamento.data_fim, apontamento.data_entrada)) = %s"
            params.append(_period_value(data_referencia).date())
        query += " ORDER BY COALESCE(apontamento.data_fim, apontamento.data_entrada) DESC, apontamento.id DESC"
        if limite is not None:
            query += " LIMIT %s OFFSET %s"
            params.extend((max(1, int(limite)), max(0, int(deslocamento or 0))))
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            rows = []
            for raw in cursor.fetchall():
                row = dict(raw)
                seconds = row.pop("elapsed_seconds", 0) or 0
                row["elapsed"] = self._formatar_duracao_segundos(seconds)
                rows.append(row)
            return rows

    @staticmethod
    def _formatar_duracao_segundos(valor):
        total = max(0, int(valor or 0))
        horas, resto = divmod(total, 3600)
        minutos, segundos = divmod(resto, 60)
        if horas:
            return f"{horas}h {minutos:02d}min {segundos:02d}s"
        return f"{minutos}min {segundos:02d}s"

    def atualizar_tarefa_status(self, tarefa_id, status):
        fields = {
            "Destacando": "data_inicio_destaque",
            "Finalizado": "data_finalizacao",
            "Despachado": "data_despacho",
        }
        timestamp_field = fields.get(status)
        with self.connection() as connection, connection.cursor() as cursor:
            if timestamp_field:
                query = f"UPDATE tarefas SET status = %s, {timestamp_field} = %s WHERE id = %s"
                cursor.execute(query, (status, agora_db(), tarefa_id))
            else:
                cursor.execute("UPDATE tarefas SET status = %s WHERE id = %s", (status, tarefa_id))
            return cursor.rowcount == 1

    @staticmethod
    def _after_task_transition(_connection, _status, _task):
        """Test seam executed before the history row is written."""

    def registrar_transicao_tarefa(
        self, tarefa_id, status_esperado, novo_status, operador, setor, motivo
    ):
        """Atomically change a task status and append its production history."""
        timestamp_fields = {
            "Destacando": "data_inicio_destaque",
            "Finalizado": "data_finalizacao",
            "Despachado": "data_despacho",
        }
        timestamp_field = timestamp_fields.get(novo_status)
        if not timestamp_field:
            raise ValueError(f"Transição de tarefa inválida: {novo_status}")

        now = agora_db()
        params = [novo_status, now, tarefa_id]
        if status_esperado is None:
            status_clause = "(status IS NULL OR BTRIM(status) = '')"
        else:
            status_clause = "status = %s"
            params.append(status_esperado)

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE tarefas
                SET status = %s, {timestamp_field} = %s
                WHERE id = %s AND {status_clause}
                RETURNING id, codigo_tarefa, status
                """,
                params,
            )
            tarefa = cursor.fetchone()
            if not tarefa:
                return False
            self._after_task_transition(connection, novo_status, tarefa)
            cursor.execute(
                """
                INSERT INTO historico
                    (op, tipo, setor, motivo, quantidade, operador, data_hora, peca, tarefa_id)
                VALUES (%s, 'Movimentação', %s, %s, 0, %s, %s, '', %s)
                """,
                (tarefa["codigo_tarefa"], setor, motivo, operador, now, tarefa_id),
            )
            return True

    def listar_fila_destaque(self, *, limite=60):
        """Tarefas com Corte já concluído em pelo menos uma chapa.

        Regra do fluxo oficial (Wave 3): **a chapa cortada libera o Destaque na
        hora**, sem esperar a tarefa inteira. A tarefa continua sendo o pai
        obrigatório — nenhum plano aparece solto — e o backend entrega a
        contagem de chapas já pronta, vinda do SigmaNEST.
        """

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                WITH chapa AS (
                    SELECT
                        plano.plano_hash,
                        plano.codigo_tarefa,
                        plano.programa,
                        plano.nome_chapa,
                        plano.sequencia_nesting,
                        plano.sigmanest_repeat_id,
                        plano.maquina_sigmanest,
                        plano.quantidade_processo,
                        corte.status AS status_corte,
                        corte.data_fim AS cortada_em,
                        corte.maquina AS maquina_corte
                    FROM catalogo_sigmanest_planos_corte plano
                    LEFT JOIN apontamentos_corte corte
                      ON corte.plano_hash = plano.plano_hash
                    WHERE plano.ativo IS TRUE
                      AND UPPER(COALESCE(plano.maquina_sigmanest, '')) = %s
                ),
                destaque AS (
                    SELECT DISTINCT ON (tarefa_id, plano_hash)
                        tarefa_id, plano_hash, estado, data_hora, operador
                    FROM eventos_destaque_tarefa
                    WHERE plano_hash IS NOT NULL
                    ORDER BY tarefa_id, plano_hash, data_hora DESC, id DESC
                )
                SELECT
                    tarefa.id AS tarefa_id,
                    tarefa.codigo_tarefa,
                    tarefa.status AS status_tarefa,
                    tarefa.material,
                    tarefa.espessura,
                    chapa.plano_hash,
                    chapa.programa,
                    chapa.nome_chapa,
                    chapa.sequencia_nesting,
                    chapa.sigmanest_repeat_id,
                    COALESCE(chapa.maquina_corte, chapa.maquina_sigmanest) AS maquina,
                    chapa.quantidade_processo,
                    COALESCE(chapa.status_corte, 'Aguardando') AS status_corte,
                    chapa.cortada_em,
                    COALESCE(destaque.estado, 'aguardando') AS estado_destaque,
                    destaque.data_hora AS destaque_em,
                    destaque.operador AS destaque_operador
                FROM tarefas tarefa
                JOIN chapa ON chapa.codigo_tarefa = tarefa.codigo_tarefa
                LEFT JOIN destaque
                  ON destaque.tarefa_id = tarefa.id
                 AND destaque.plano_hash = chapa.plano_hash
                WHERE COALESCE(tarefa.status, '') <> 'Despachado'
                  AND EXISTS (
                      SELECT 1 FROM chapa cortada
                      WHERE cortada.codigo_tarefa = tarefa.codigo_tarefa
                        AND cortada.status_corte = 'Finalizado'
                  )
                ORDER BY tarefa.codigo_tarefa,
                         chapa.programa,
                         chapa.sequencia_nesting,
                         chapa.plano_hash
                """,
                (SIGMANEST_LASER_MACHINE,),
            )
            linhas = [dict(row) for row in cursor.fetchall()]

        tarefas = {}
        for linha in linhas:
            chave = linha["tarefa_id"]
            grupo = tarefas.setdefault(chave, {
                "tarefa_id": chave,
                "codigo_tarefa": linha["codigo_tarefa"],
                "status_tarefa": linha["status_tarefa"],
                "material": linha["material"],
                "espessura": linha["espessura"],
                "planos": [],
            })
            grupo["planos"].append({
                "plano_hash": linha["plano_hash"],
                "programa": linha["programa"],
                "nome_chapa": linha["nome_chapa"],
                "sequencia": linha["sequencia_nesting"],
                "repeticao": linha["sigmanest_repeat_id"],
                "maquina": linha["maquina"],
                "quantidade_processo": linha["quantidade_processo"],
                "status_corte": linha["status_corte"],
                "cortada_em": linha["cortada_em"],
                "estado_destaque": linha["estado_destaque"],
                "destaque_em": linha["destaque_em"],
                "destaque_operador": linha["destaque_operador"],
            })

        resultado = []
        for grupo in tarefas.values():
            planos = grupo["planos"]
            cortadas = [item for item in planos if item["status_corte"] == "Finalizado"]
            destacadas = [item for item in cortadas if item["estado_destaque"] == "fim"]
            disponiveis = [
                item for item in cortadas if item["estado_destaque"] != "fim"
            ]
            grupo.update({
                # A quantidade de chapas vem do SigmaNEST: cada plano projetado
                # é uma chapa física (programa + chapa + repetição).
                "chapas_total": len(planos),
                "chapas_cortadas": len(cortadas),
                "chapas_destacadas": len(destacadas),
                "chapas_disponiveis": len(disponiveis),
                "situacao": "COMPLETA" if len(cortadas) == len(planos) else "PARCIAL",
                "progresso_corte": f"{len(cortadas)} de {len(planos)} planos cortados",
            })
            resultado.append(grupo)
        return resultado[:max(1, int(limite))]

    def listar_destaques_ativos_andon(self):
        """Retorna somente execuções atuais do Destaque para gestão à vista.

        A identidade física apresentada no Andon é o posto ``Destaque``. Os
        eventos continuam separados por tarefa/plano e são consolidados pelo
        serviço do Andon sem criar uma segunda máquina de estados.
        """

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                WITH atual AS (
                    SELECT DISTINCT ON (evento.tarefa_id, evento.plano_hash)
                        evento.*
                    FROM eventos_destaque_tarefa evento
                    ORDER BY evento.tarefa_id, evento.plano_hash,
                             evento.data_hora DESC, evento.id DESC
                )
                SELECT
                    atual.tarefa_id,
                    tarefa.codigo_tarefa,
                    atual.plano_hash,
                    atual.estado,
                    atual.codigo_status_recurso,
                    atual.motivo,
                    atual.comentario,
                    atual.operador,
                    atual.data_hora,
                    plano.programa,
                    plano.nome_chapa,
                    COALESCE((
                        SELECT jsonb_agg(to_jsonb(op_linha) ORDER BY op_linha.codigo_op)
                        FROM (
                            SELECT DISTINCT
                                sig_op.codigo_op,
                                pcp.produto_codigo,
                                pcp.produto_descricao
                            FROM catalogo_sigmanest_ops sig_op
                            LEFT JOIN catalogo_pcp_ops pcp
                              ON pcp.codigo_op = sig_op.codigo_op
                            WHERE sig_op.codigo_tarefa = tarefa.codigo_tarefa
                              AND sig_op.ativo IS TRUE
                        ) op_linha
                    ), '[]'::jsonb) AS ops
                FROM atual
                JOIN tarefas tarefa ON tarefa.id = atual.tarefa_id
                LEFT JOIN catalogo_sigmanest_planos_corte plano
                  ON plano.plano_hash = atual.plano_hash
                WHERE atual.estado IN ('inicio', 'retomada', 'parada')
                ORDER BY atual.data_hora DESC, atual.id DESC
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def listar_cortes_ativos_andon(self):
        """Contexto operacional atual do Corte para o card físico do Andon.

        Quem determina "está cortando agora" é ``apontamentos_corte``. A
        repetição da chapa é dado de planejamento e vive só no catálogo, por
        isso entra por LEFT JOIN: uma lacuna de catálogo empobrece o rótulo,
        nunca apaga o card de um recurso em processo.

        O contrato de saída usa vocabulário neutro (``repeticao``), igual ao
        de ``listar_fila_destaque``. A procedência corporativa termina aqui,
        na camada de persistência; o Andon consome apenas execução.
        """

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    corte.id AS apontamento_id,
                    corte.maquina,
                    corte.codigo_tarefa,
                    corte.programa,
                    corte.nome_chapa,
                    corte.sequencia_nesting,
                    plano.sigmanest_repeat_id AS repeticao,
                    corte.operador_inicio,
                    corte.data_inicio
                FROM apontamentos_corte corte
                LEFT JOIN catalogo_sigmanest_planos_corte plano
                  ON plano.plano_hash = corte.plano_hash
                WHERE corte.status = 'Em processo'
                ORDER BY corte.maquina, corte.data_inicio, corte.id
                """
            )
            return [dict(row) for row in cursor.fetchall()]

    def obter_estado_destaque(self, tarefa_id, plano_hash=None):
        """Retorna o estado corrente do destaque sem confundir parada com nova tarefa.

        ``plano_hash`` seleciona o escopo: nulo é a tarefa inteira, preenchido
        é uma chapa específica já cortada.
        """

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, codigo_tarefa, status FROM tarefas WHERE id = %s",
                (tarefa_id,),
            )
            tarefa = cursor.fetchone()
            if not tarefa:
                return None
            cursor.execute(
                """
                SELECT * FROM eventos_destaque_tarefa
                WHERE tarefa_id = %s
                  AND plano_hash IS NOT DISTINCT FROM %s
                ORDER BY data_hora DESC, id DESC
                LIMIT 1
                """,
                (tarefa_id, plano_hash),
            )
            evento = cursor.fetchone()
            estado = evento["estado"] if evento else None
            if estado is None:
                estado = (
                    "aguardando"
                    if plano_hash
                    else {
                        "Destacando": "inicio",
                        "Finalizado": "fim",
                        "Despachado": "fim",
                    }.get(tarefa["status"], "aguardando")
                )
            return {
                "tarefa_id": tarefa["id"],
                "codigo_tarefa": tarefa["codigo_tarefa"],
                "status_tarefa": tarefa["status"],
                "estado": estado,
                "evento": dict(evento) if evento else None,
            }

    def transicionar_destaque_tarefa(
        self,
        tarefa_id,
        acao,
        operador,
        *,
        codigo_status_recurso=None,
        motivo=None,
        comentario=None,
        data_hora=None,
        plano_hash=None,
    ):
        """Registra início/retomada, parada ou fim do mesmo destaque.

        ``plano_hash`` define o escopo. Nulo = tarefa inteira (comportamento
        original). Preenchido = uma chapa já cortada, que pode ser destacada
        antes de a tarefa terminar. Só o escopo da tarefa muda
        ``tarefas.status``; o escopo do plano registra o evento e nada mais,
        porque quem fecha a tarefa é o serviço, ao ver todas as chapas prontas.
        """

        destino = str(acao or "").strip().lower()
        if destino not in {"inicio", "parada", "fim"}:
            raise ValueError(f"Ação de destaque inválida: {acao}")
        instante = _period_value(data_hora) or agora_db()
        operador = str(operador or "").strip()
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM tarefas WHERE id = %s FOR UPDATE",
                (tarefa_id,),
            )
            tarefa = cursor.fetchone()
            if not tarefa:
                return None
            if tarefa.get("status") in {"Finalizado", "Despachado"}:
                return None

            if plano_hash:
                cursor.execute(
                    """
                    SELECT plano.plano_hash
                    FROM catalogo_sigmanest_planos_corte plano
                    JOIN apontamentos_corte corte
                      ON corte.plano_hash = plano.plano_hash
                     AND corte.status = 'Finalizado'
                    WHERE plano.plano_hash = %s
                      AND plano.codigo_tarefa = %s
                      AND plano.ativo IS TRUE
                      AND UPPER(COALESCE(plano.maquina_sigmanest, '')) = %s
                    """,
                    (
                        str(plano_hash).strip(),
                        tarefa["codigo_tarefa"],
                        SIGMANEST_LASER_MACHINE,
                    ),
                )
                if cursor.fetchone() is None:
                    return None
            else:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE corte.status = 'Finalizado') AS concluidos
                    FROM catalogo_sigmanest_planos_corte plano
                    LEFT JOIN apontamentos_corte corte
                      ON corte.plano_hash = plano.plano_hash
                    WHERE plano.codigo_tarefa = %s
                      AND plano.ativo IS TRUE
                      AND UPPER(COALESCE(plano.maquina_sigmanest, '')) = %s
                    """,
                    (tarefa["codigo_tarefa"], SIGMANEST_LASER_MACHINE),
                )
                progresso = cursor.fetchone()
                if (
                    not progresso
                    or int(progresso.get("total") or 0) <= 0
                    or int(progresso.get("concluidos") or 0)
                    != int(progresso.get("total") or 0)
                ):
                    return None
            cursor.execute(
                """
                SELECT * FROM eventos_destaque_tarefa
                WHERE tarefa_id = %s
                  AND plano_hash IS NOT DISTINCT FROM %s
                ORDER BY data_hora DESC, id DESC
                LIMIT 1
                """,
                (tarefa_id, plano_hash),
            )
            ultimo = cursor.fetchone()
            estado_atual = ultimo["estado"] if ultimo else None
            if estado_atual is None:
                estado_atual = (
                    "aguardando"
                    if plano_hash
                    else {
                        "Destacando": "inicio",
                        "Finalizado": "fim",
                        "Despachado": "fim",
                    }.get(tarefa["status"], "aguardando")
                )

            if plano_hash:
                # Escopo de chapa: os estados são os mesmos, mas o status da
                # tarefa é decidido pelo conjunto, não por uma chapa isolada.
                if destino == "inicio":
                    if estado_atual not in {"aguardando", "parada"}:
                        return None
                    estado_evento = "retomada" if estado_atual == "parada" else "inicio"
                    historico_motivo = (
                        "Retomada do destaque do plano" if estado_atual == "parada"
                        else "Início do destaque do plano"
                    )
                    # A primeira chapa destacada já coloca a tarefa em
                    # Destacando: o Destaque dela começou de fato, mesmo que
                    # os demais planos ainda estejam no Corte.
                    if not str(tarefa["status"] or "").strip():
                        cursor.execute(
                            """
                            UPDATE tarefas
                            SET status = 'Destacando',
                                data_inicio_destaque = COALESCE(data_inicio_destaque, %s)
                            WHERE id = %s AND (status IS NULL OR BTRIM(status) = '')
                            RETURNING *
                            """,
                            (instante, tarefa_id),
                        )
                        tarefa_atualizada = cursor.fetchone()
                        if not tarefa_atualizada:
                            return None
                        tarefa = tarefa_atualizada
                        self._after_task_transition(connection, "Destacando", tarefa)
                elif destino == "parada":
                    if estado_atual not in {"inicio", "retomada"}:
                        return None
                    estado_evento = "parada"
                    historico_motivo = "Parada do destaque do plano"
                    if motivo:
                        historico_motivo += f": {motivo}"
                else:
                    if estado_atual not in {"inicio", "retomada"}:
                        return None
                    estado_evento = "fim"
                    historico_motivo = "Fim do destaque do plano"
            elif destino == "inicio":
                if estado_atual == "aguardando" and not tarefa["status"]:
                    estado_evento = "inicio"
                    cursor.execute(
                        """
                        UPDATE tarefas
                        SET status = 'Destacando',
                            data_inicio_destaque = COALESCE(data_inicio_destaque, %s)
                        WHERE id = %s AND (status IS NULL OR BTRIM(status) = '')
                        RETURNING *
                        """,
                        (instante, tarefa_id),
                    )
                    tarefa_atualizada = cursor.fetchone()
                    if not tarefa_atualizada:
                        return None
                    tarefa = tarefa_atualizada
                    self._after_task_transition(connection, "Destacando", tarefa)
                    historico_motivo = "Início do destaque"
                elif estado_atual == "parada" and tarefa["status"] == "Destacando":
                    estado_evento = "retomada"
                    historico_motivo = "Retomada do destaque"
                else:
                    return None
            elif destino == "parada":
                if tarefa["status"] != "Destacando" or estado_atual not in {"inicio", "retomada"}:
                    return None
                estado_evento = "parada"
                historico_motivo = "Parada do destaque"
                if motivo:
                    historico_motivo += f": {motivo}"
            else:
                if tarefa["status"] != "Destacando" or estado_atual not in {"inicio", "retomada"}:  # noqa: E501
                    return None
                estado_evento = "fim"
                cursor.execute(
                    """
                    UPDATE tarefas
                    SET status = 'Finalizado', data_finalizacao = %s
                    WHERE id = %s AND status = 'Destacando'
                    RETURNING *
                    """,
                    (instante, tarefa_id),
                )
                tarefa_atualizada = cursor.fetchone()
                if not tarefa_atualizada:
                    return None
                tarefa = tarefa_atualizada
                self._after_task_transition(connection, "Finalizado", tarefa)
                historico_motivo = "Fim do destaque"

                # Uma conclusão no escopo da tarefa atende apenas os planos
                # ainda pendentes. Planos já apontados individualmente não
                # recebem evento duplicado; todos os demais ganham evidência
                # explícita e tornam chamadas posteriores idempotentes.
                cursor.execute(
                    """
                    INSERT INTO eventos_destaque_tarefa (
                        tarefa_id, estado, operador, data_hora, plano_hash
                    )
                    SELECT %s, 'fim', %s, %s, plano.plano_hash
                    FROM catalogo_sigmanest_planos_corte plano
                    JOIN apontamentos_corte corte
                      ON corte.plano_hash = plano.plano_hash
                     AND corte.status = 'Finalizado'
                    LEFT JOIN LATERAL (
                        SELECT evento.estado
                        FROM eventos_destaque_tarefa evento
                        WHERE evento.tarefa_id = %s
                          AND evento.plano_hash = plano.plano_hash
                        ORDER BY evento.data_hora DESC, evento.id DESC
                        LIMIT 1
                    ) atual ON TRUE
                    WHERE plano.codigo_tarefa = %s
                      AND plano.ativo IS TRUE
                      AND UPPER(COALESCE(plano.maquina_sigmanest, '')) = %s
                      AND COALESCE(atual.estado, 'aguardando') <> 'fim'
                    """,
                    (
                        tarefa_id,
                        operador,
                        instante,
                        tarefa_id,
                        tarefa["codigo_tarefa"],
                        SIGMANEST_LASER_MACHINE,
                    ),
                )

            cursor.execute(
                """
                INSERT INTO eventos_destaque_tarefa (
                    tarefa_id, estado, codigo_status_recurso, motivo,
                    comentario, operador, data_hora, plano_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    tarefa_id,
                    estado_evento,
                    codigo_status_recurso,
                    motivo,
                    comentario,
                    operador,
                    instante,
                    plano_hash,
                ),
            )
            evento = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO historico (
                    op, tipo, setor, motivo, quantidade, operador,
                    data_hora, peca, tarefa_id
                ) VALUES (%s, 'Apontamento Destaque', 'Destaque', %s, 0, %s, %s, '', %s)
                """,
                (
                    tarefa["codigo_tarefa"],
                    historico_motivo,
                    operador,
                    instante,
                    tarefa_id,
                ),
            )
            resultado = dict(tarefa)
            resultado["estado_destaque"] = estado_evento
            resultado["evento_destaque_id"] = evento["id"]
            resultado["plano_hash"] = plano_hash
            return resultado

    def listar_eventos_destaque(self, tarefa_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM eventos_destaque_tarefa
                WHERE tarefa_id = %s
                ORDER BY data_hora, id
                """,
                (tarefa_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def despachar_tarefa(
        self, tarefa_id, operador, maquinas_dobra=None, maquinas_usinagem=None, maquinas_serra=None
    ):
        now = agora_db()
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id, status FROM tarefas WHERE id = %s FOR UPDATE", (tarefa_id,))
            tarefa = cursor.fetchone()
            if not tarefa or tarefa["status"] != "Finalizado":
                return False
            cursor.execute("SELECT * FROM op_por_tarefa WHERE tarefa_id = %s ORDER BY id", (tarefa_id,))
            for op in cursor.fetchall():
                setor = op["setor_destino_atual"] or op["setor_destino_original"]
                quantidade = op["quantidade_atual"] or op["quantidade_original"]
                setor_upper = str(setor or "").strip().upper()
                if setor_upper in ("DOBRA", "AGUARDANDO DOBRA"):
                    setor = "Aguardando Dobra"
                elif setor_upper in ("USINAGEM", "AGUARDANDO USINAGEM"):
                    setor = "Aguardando Usinagem"
                elif setor_upper in ("SERRA", "AGUARDANDO SERRA"):
                    setor = "Aguardando Serra"
                cursor.execute(
                    """
                    INSERT INTO historico (op, tipo, setor, motivo, quantidade, operador, data_hora, peca, tarefa_id)
                    VALUES (%s, 'Movimentação', %s, '', %s, %s, %s, %s, %s)
                    """,
                    (op["codigo_op"], setor, quantidade, operador, now, op["id_peca"], tarefa_id),
                )
            cursor.execute(
                "UPDATE tarefas SET status = 'Despachado', data_despacho = %s WHERE id = %s",
                (now, tarefa_id),
            )
            return True

    @staticmethod
    def _latest_movements_cte():
        return """
            WITH latest AS (
                SELECT DISTINCT ON (op) *
                FROM historico
                WHERE tipo = 'Movimentação' AND op NOT LIKE 'T%%'
                ORDER BY op, data_hora DESC, id DESC
            )
        """

    def get_current_ops(
        self, setor_filter=None, search=None, maquinas_dobra=None, maquinas_usinagem=None, maquinas_serra=None
    ):
        query = self._latest_movements_cte() + " SELECT * FROM latest h"
        where, params = [], []
        if setor_filter:
            normalized = setor_filter.upper()
            if normalized in ("ALMOXARIFADO", "ALMOX"):
                where.append("UPPER(h.setor) = 'ALMOXARIFADO'")
            elif normalized == "AGUARDANDO_DOBRA":
                where.append("UPPER(h.setor) = 'AGUARDANDO DOBRA'")
            elif normalized == "MAQUINAS_DOBRA" and maquinas_dobra:
                where.append("UPPER(h.setor) = ANY(%s)")
                params.append([item.upper() for item in maquinas_dobra])
            elif normalized == "AGUARDANDO_USINAGEM":
                where.append("UPPER(h.setor) = 'AGUARDANDO USINAGEM'")
            elif normalized == "MAQUINAS_USINAGEM" and maquinas_usinagem:
                where.append("UPPER(h.setor) = ANY(%s)")
                params.append([item.upper() for item in maquinas_usinagem])
            elif normalized == "AGUARDANDO_SERRA":
                where.append("UPPER(h.setor) = 'AGUARDANDO SERRA'")
            elif normalized == "MAQUINAS_SERRA" and maquinas_serra:
                where.append("UPPER(h.setor) = ANY(%s)")
                params.append([item.upper() for item in maquinas_serra])
            else:
                where.append("h.setor = %s")
                params.append(setor_filter)
        if search:
            pattern = f"%{search.strip()}%"
            where.append(
                "(h.op ILIKE %s OR h.peca ILIKE %s OR EXISTS "
                "(SELECT 1 FROM tarefas t WHERE t.id = h.tarefa_id AND t.codigo_tarefa ILIKE %s))"
            )
            params.extend([pattern, pattern, pattern])
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY h.data_hora DESC, h.id DESC"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def buscar_movimentos_setores(self, setores):
        if not setores:
            return []
        query = self._latest_movements_cte() + """
            SELECT op, peca, setor, data_hora, tarefa_id
            FROM latest
            WHERE setor = ANY(%s)
            ORDER BY data_hora DESC, id DESC
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, (list(setores),))
            return [dict(row) for row in cursor.fetchall()]

    def get_op_timeline(self, op):
        codigo = limpa_codigo(op)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM historico WHERE op = %s ORDER BY data_hora, id", (codigo,))
            rows = cursor.fetchall()
            if not rows and codigo:
                cursor.execute(
                    "SELECT * FROM historico WHERE LTRIM(op, '0') = LTRIM(%s, '0') ORDER BY data_hora, id",
                    (codigo,),
                )
                rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_tasks(self, status_filter=None, search=None):
        query = "SELECT * FROM tarefas"
        where, params = [], []
        if status_filter and status_filter.upper() != "TODOS":
            if status_filter == "Aguardando registro":
                where.append("(status IS NULL OR BTRIM(status) = '' OR status = %s)")
            else:
                where.append("status = %s")
            params.append(status_filter)
        if search:
            pattern = f"%{search.strip()}%"
            where.append("(codigo_tarefa ILIKE %s OR material ILIKE %s)")
            params.extend([pattern, pattern])
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY data_inicio_destaque DESC NULLS LAST, id DESC"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [_task_dict(row) for row in cursor.fetchall()]

    def get_ops_for_task(self, tarefa_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT * FROM op_por_tarefa WHERE tarefa_id = %s ORDER BY codigo_op", (tarefa_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_op_counts_by_task(self, tarefa_ids=None):
        query = "SELECT tarefa_id, COUNT(*) AS quantidade FROM op_por_tarefa"
        params = []
        if tarefa_ids is not None:
            ids = [int(item) for item in tarefa_ids if item is not None]
            if not ids:
                return {}
            query += " WHERE tarefa_id = ANY(%s)"
            params.append(ids)
        query += " GROUP BY tarefa_id"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return {int(row["tarefa_id"]): int(row["quantidade"]) for row in cursor.fetchall()}

    def get_first_op_codes_by_task(self, tarefa_ids):
        ids = [int(item) for item in tarefa_ids if item is not None]
        if not ids:
            return {}
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT DISTINCT ON (tarefa_id) tarefa_id, codigo_op
                FROM op_por_tarefa
                WHERE tarefa_id = ANY(%s)
                ORDER BY tarefa_id, id
                """,
                (ids,),
            )
            return {
                int(row["tarefa_id"]): str(row["codigo_op"] or "")
                for row in cursor.fetchall()
            }

    def ultimas_ops_despachadas(self, periodo_inicio=None, periodo_fim=None, limite=5):
        query = """
            SELECT h.* FROM historico h
            INNER JOIN tarefas t ON t.id = h.tarefa_id
            WHERE h.tipo = 'Movimentação' AND h.op NOT LIKE 'T%%'
              AND t.status = 'Despachado' AND h.data_hora = t.data_despacho
        """
        params = []
        if periodo_inicio:
            query += " AND h.data_hora >= %s"
            params.append(_period_value(periodo_inicio))
        if periodo_fim:
            query += " AND h.data_hora <= %s"
            params.append(_period_value(periodo_fim))
        query += " ORDER BY h.data_hora DESC, h.id DESC LIMIT %s"
        params.append(int(limite or 5))
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def obter_historico_completo(
        self, periodo_inicio=None, periodo_fim=None, setor=None, operador=None, tipo=None, search=None
    ):
        query = "SELECT * FROM historico WHERE TRUE"
        params = []
        for clause, value in (
            ("data_hora >= %s", _period_value(periodo_inicio) if periodo_inicio else None),
            ("data_hora <= %s", _period_value(periodo_fim) if periodo_fim else None),
            ("setor = %s", setor), ("operador = %s", operador), ("tipo = %s", tipo),
        ):
            if value is not None and value != "":
                query += " AND " + clause
                params.append(value)
        if search:
            pattern = f"%{search.strip()}%"
            query += " AND (op ILIKE %s OR peca ILIKE %s OR motivo ILIKE %s)"
            params.extend([pattern, pattern, pattern])
        query += " ORDER BY data_hora DESC, id DESC"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def buscar_movimentacoes_periodo(self, inicio, fim):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM historico
                WHERE tipo = 'Movimentação' AND op NOT LIKE 'T%%'
                  AND data_hora >= %s AND data_hora <= %s
                ORDER BY data_hora DESC, id DESC
                """,
                (_period_value(inicio), _period_value(fim)),
            )
            return [dict(row) for row in cursor.fetchall()]

    def counts_overview(self, maquinas_dobra=None, maquinas_usinagem=None, maquinas_serra=None):
        inicio = datetime.combine(datetime.now().date(), time.min)
        fim = inicio + timedelta(days=1)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*) AS total FROM historico
                WHERE tipo = 'Movimentação' AND op NOT LIKE 'T%%'
                  AND data_hora >= %s AND data_hora < %s
                """,
                (inicio, fim),
            )
            movimentos_hoje = int(cursor.fetchone()["total"])
            cursor.execute("SELECT COUNT(*) AS total FROM tarefas WHERE status IS NULL OR status <> 'Despachado'")
            tarefas_abertas = int(cursor.fetchone()["total"])
            cursor.execute(
                self._latest_movements_cte()
                + "SELECT setor, COUNT(*) AS qtd FROM latest GROUP BY setor"
            )
            mapa = {row["setor"] or "": int(row["qtd"]) for row in cursor.fetchall()}
        dobra = mapa.get("Aguardando Dobra", 0) + sum(mapa.get(item, 0) for item in (maquinas_dobra or []))
        usinagem = mapa.get("Aguardando Usinagem", 0) + sum(mapa.get(item, 0) for item in (maquinas_usinagem or []))
        serra = mapa.get("Aguardando Serra", 0) + sum(mapa.get(item, 0) for item in (maquinas_serra or []))
        return {
            "ops_ativas": sum(mapa.values()), "tarefas_abertas": tarefas_abertas,
            "ops_em_dobra": dobra, "ops_em_usinagem": usinagem, "ops_em_serra": serra,
            "ops_almoxarifado": mapa.get("Almoxarifado", 0), "movimentacoes_hoje": movimentos_hoje,
            "integracao_status": "Pendente TI",
            "integracao_mensagem": "Mecanismo Protheus/TOTVS ainda não definido.",
            "por_setor": mapa,
        }

    def movimentos_por_dia(self, dias=7):
        dias = int(dias)
        if dias <= 0:
            return []
        hoje = datetime.now().date()
        primeiro_dia = hoje - timedelta(days=dias - 1)
        inicio = datetime.combine(primeiro_dia, time.min)
        fim = datetime.combine(hoje + timedelta(days=1), time.min)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT data_hora::date AS dia, COUNT(*) AS total
                FROM historico
                WHERE tipo = 'Movimentação' AND op NOT LIKE 'T%%'
                  AND data_hora >= %s AND data_hora < %s
                GROUP BY data_hora::date
                """,
                (inicio, fim),
            )
            totais = {row["dia"]: int(row["total"]) for row in cursor.fetchall()}
        return [
            (dia.strftime("%d/%m/%Y"), totais.get(dia, 0))
            for dia in (primeiro_dia + timedelta(days=offset) for offset in range(dias))
        ]

    def movimentos_por_setor(self):
        query = self._latest_movements_cte() + """
            SELECT COALESCE(setor, '') AS setor, COUNT(*) AS qtd
            FROM latest GROUP BY COALESCE(setor, '') ORDER BY qtd DESC
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(query)
            return [(row["setor"], int(row["qtd"])) for row in cursor.fetchall()]

    def ops_por_status(self, maquinas_dobra=None, maquinas_usinagem=None, maquinas_serra=None):
        mapa = dict(self.movimentos_por_setor())
        grupos = set((maquinas_dobra or []) + (maquinas_usinagem or []) + (maquinas_serra or []))
        grupos.update(("Aguardando Dobra", "Aguardando Usinagem", "Aguardando Serra", "Almoxarifado"))
        return {
            "Dobra": mapa.get("Aguardando Dobra", 0) + sum(mapa.get(item, 0) for item in (maquinas_dobra or [])),
            "Usinagem": mapa.get("Aguardando Usinagem", 0) + sum(mapa.get(item, 0) for item in (maquinas_usinagem or [])),
            "Serra": mapa.get("Aguardando Serra", 0) + sum(mapa.get(item, 0) for item in (maquinas_serra or [])),
            "Almoxarifado": mapa.get("Almoxarifado", 0),
            "Outros": sum(value for key, value in mapa.items() if key not in grupos),
        }

    def importar_tarefas_csv(self, arquivo_tarefas, arquivo_ops):
        tarefas = ops = 0
        erros = []
        with open(arquivo_tarefas, "r", encoding="utf-8-sig", newline="") as arquivo:
            reader = csv.DictReader(arquivo, delimiter=";")
            faltando = {"codigo_tarefa"} - set(reader.fieldnames or [])
            if faltando:
                raise ValueError(f"Arquivo de tarefas sem coluna(s): {', '.join(sorted(faltando))}")
            for linha, row in enumerate(reader, start=2):
                try:
                    codigo = limpa_codigo(row.get("codigo_tarefa", ""))
                    if not codigo:
                        raise ValueError("codigo_tarefa vazio")
                    texto = row.get("espessura", "").strip().replace(",", ".")
                    self.inserir_tarefa(codigo, row.get("material", "").strip(), float(texto) if texto else None)
                    tarefas += 1
                except Exception as exc:
                    erros.append(f"Tarefas linha {linha}: {exc}")
        with open(arquivo_ops, "r", encoding="utf-8-sig", newline="") as arquivo:
            reader = csv.DictReader(arquivo, delimiter=";")
            obrigatorios = {"codigo_tarefa", "codigo_op", "id_peca", "setor_destino", "quantidade"}
            faltando = obrigatorios - set(reader.fieldnames or [])
            if faltando:
                raise ValueError(f"Arquivo de OPs sem coluna(s): {', '.join(sorted(faltando))}")
            for linha, row in enumerate(reader, start=2):
                try:
                    tarefa_codigo = limpa_codigo(row.get("codigo_tarefa", ""))
                    op_codigo = limpa_codigo(row.get("codigo_op", ""))
                    setor = row.get("setor_destino", "").strip()
                    quantidade = int(row.get("quantidade", "").strip())
                    if not tarefa_codigo or not op_codigo or not setor:
                        raise ValueError("codigo_tarefa, codigo_op e setor_destino são obrigatórios")
                    if quantidade <= 0:
                        raise ValueError("quantidade deve ser maior que zero")
                    tarefa = self.buscar_tarefa_por_codigo(tarefa_codigo)
                    if not tarefa:
                        raise ValueError(f"tarefa {tarefa_codigo} não encontrada")
                    self.inserir_op_na_tarefa(
                        tarefa["id"], op_codigo, row.get("id_peca", "").strip(), setor, quantidade
                    )
                    ops += 1
                except Exception as exc:
                    erros.append(f"OPs linha {linha}: {exc}")
        if erros:
            resumo = "\n".join(erros[:10])
            if len(erros) > 10:
                resumo += f"\n... e mais {len(erros) - 10} erro(s)."
            raise ValueError(resumo)
        return f"Importação concluída: {tarefas} tarefa(s) processada(s), {ops} OP(s) processada(s)."

    def obter_usuario_por_id(self, usuario_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id, nome, nivel, ativo FROM usuarios WHERE id = %s", (usuario_id,))
            return _as_dict(cursor.fetchone())

    def atualizar_nivel_usuario(self, usuario_id, novo_nivel):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE usuarios SET nivel = %s WHERE id = %s", (novo_nivel, usuario_id))
            return cursor.rowcount == 1

    def resetar_senha_usuario(self, usuario_id, nova_senha):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE usuarios SET senha_hash = %s WHERE id = %s",
                (self._hash_senha(nova_senha), usuario_id),
            )
            return cursor.rowcount == 1

    def ativar_desativar_usuario(self, usuario_id, ativo):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE usuarios SET ativo = %s WHERE id = %s", (bool(ativo), usuario_id))
            return cursor.rowcount == 1
