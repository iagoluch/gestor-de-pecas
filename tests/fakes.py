"""Dublês em memória dos serviços e da API; nenhum backend SQL é acessado."""

from collections import Counter
from datetime import date, datetime, time, timedelta

from app.core.normalization import limpa_codigo, normalizar_data_db
from app.core.resource_mapping import resource_display_name
from app.database.schema import SCHEMA_VERSION
from app.database.welding_repository import WELDING_MANAGEMENT_SECTORS
from mes.domain import (
    ManufacturingRules,
    OperatorState,
    SIGMANEST_LASER_MACHINE,
    can_transition,
    operator_state_from_status,
    operator_status_for_state,
    return_state_for_transition,
)


#: Espelho do filtro de setor usado pela leitura gerencial da Solda no SQL.
_SETORES_SOLDA = {nome.upper() for nome in WELDING_MANAGEMENT_SECTORS}


class FakeDatabase:
    def __init__(self):
        self.tasks = []
        self.ops = []
        self.history = []
        self.users = []
        self.events = []
        self.appointments = []
        self.cut_plans = []
        self.cut_appointments = []
        # Linhas de peça do SigmaNEST (tarefa + programa + OP + peça) e o
        # catálogo de OPs do TOTVS, espelhando `catalogo_sigmanest_ops` e
        # `catalogo_pcp_ops`. É daqui que sai a hierarquia plano -> OP -> produto.
        self.sigmanest_ops = []
        self.pcp_ops = []
        self.catalog_operations = []
        self.operator_events = []
        self.quantity_events = []
        self.participations = []
        self.operator_badges = [
            {
                "id": 1,
                "cracha": "1",
                "nome": "Iago",
                "ativo": True,
                "fonte": "teste_ficticio",
                # Wave 5: designação do responsável pelo retrabalho da primeira
                # peça. O crachá padrão do fake é responsável para que os testes
                # já existentes continuem exercitando o fluxo completo.
                "autorizador_retrabalho": True,
            }
        ]
        # Wave 5 — portão da primeira peça, auditoria da autorização e alertas
        # internos. O fake precisa modelar as três tabelas: sem elas o serviço
        # degradaria em silêncio e os testes deixariam de provar a regra.
        self.first_pieces = []
        self.first_piece_authorizations = []
        self.internal_alerts = []
        self.highlight_events = []
        self.ai_conversations = []
        self.ai_messages = []
        self.ai_knowledge = []
        self.generated_reports = []
        self.report_schedules = []
        self.messaging_destinations = []
        self.report_deliveries = []
        self.quality_templates = []
        self.quality_dimensions = []
        self.quality_inspections = []
        self.quality_pieces = []
        self.quality_measures = []
        self.quality_rnc = []
        self.quality_drawings = []
        self.resource_states = {}
        # Pausas automáticas configuráveis (Wave 3): a semente reproduz o que a
        # migração 23 grava no banco — almoço e café para todos os setores.
        self.automatic_pauses = [
            {
                "id": indice,
                "tipo_setor": setor,
                "nome": nome,
                "hora_inicio": inicio,
                "hora_fim": fim,
                "ativo": True,
                "ordem": ordem,
                "atualizado_por": None,
                "atualizado_em": None,
            }
            for indice, (setor, nome, inicio, fim, ordem) in enumerate(
                (
                    (setor, nome, inicio, fim, ordem)
                    for setor in (
                        "Corte", "Dobra", "Usinagem", "Serra", "Caldeiraria",
                        "Solda", "Pintura", "Montagem", "Destaque",
                    )
                    for nome, inicio, fim, ordem in (
                        ("Almoço", time(12, 10), time(12, 52), 1),
                        ("Café", time(15, 30), time(15, 45), 2),
                    )
                ),
                start=1,
            )
        ]
        self.status_resources = [
            {
                "codigo": "0015", "nome": "Peça não conforme",
                "grupo_codigo": "0004", "grupo_nome": "PARADAS DA FABRICA",
                "habilitado": True, "oculto": False, "setup": False,
                "retrabalho": False, "requer_comentario": True,
            },
            {
                "codigo": "0029", "nome": "Aguardando ponte",
                "grupo_codigo": "0004", "grupo_nome": "PARADAS DA FABRICA",
                "habilitado": True, "oculto": False, "setup": False,
                "retrabalho": False, "requer_comentario": False,
            },
            {
                "codigo": "1005", "nome": "Set-Up",
                "grupo_codigo": "0001", "grupo_nome": "PRODUÇÃO",
                "habilitado": True, "oculto": False, "setup": True,
                "retrabalho": False, "requer_comentario": False,
            },
            {
                "codigo": "0040", "nome": "Aguardando retrabalho produção",
                "grupo_codigo": "0004", "grupo_nome": "PARADAS DA FABRICA",
                "habilitado": True, "oculto": False, "setup": False,
                "retrabalho": True, "requer_comentario": False,
            },
        ]
        self.closed = False
        self._ids = Counter()

    def _id(self, name):
        self._ids[name] += 1
        return self._ids[name]

    def close(self):
        self.closed = True

    def obter_schema_version(self):
        return SCHEMA_VERSION

    def diagnostico_integridade(self):
        return {"ok": True, "schema_version": SCHEMA_VERSION, "tabelas": {}}

    def criar_usuario(self, nome, senha, nivel="operador_destaque"):
        if self.usuario_existe(nome):
            return None
        user = {
            "id": self._id("users"), "nome": nome, "senha": senha, "nivel": nivel,
            "ativo": True, "data_criacao": datetime.now().replace(microsecond=0),
        }
        self.users.append(user)
        return user["id"]

    def autenticar_usuario(self, nome, senha):
        user = next((item for item in self.users if item["nome"] == nome and item["ativo"]), None)
        if not user or user["senha"] != senha:
            return None
        return {key: user[key] for key in ("id", "nome", "nivel")}

    def usuario_existe(self, nome):
        return any(item["nome"] == nome for item in self.users)

    def obter_nivel_usuario_por_nome(self, nome):
        user = next((item for item in self.users if item["nome"] == nome), None)
        return user["nivel"] if user else None

    def listar_usuarios(self):
        return [{key: item[key] for key in ("id", "nome", "nivel", "ativo", "data_criacao")} for item in self.users]

    def obter_usuario_por_id(self, user_id):
        user = next((item for item in self.users if item["id"] == user_id), None)
        return dict(user) if user else None

    def atualizar_nivel_usuario(self, user_id, level):
        user = self.obter_usuario_por_id(user_id)
        if not user:
            return False
        next(item for item in self.users if item["id"] == user_id)["nivel"] = level
        return True

    def resetar_senha_usuario(self, user_id, password):
        user = next((item for item in self.users if item["id"] == user_id), None)
        if not user:
            return False
        user["senha"] = password
        return True

    def ativar_desativar_usuario(self, user_id, active):
        user = next((item for item in self.users if item["id"] == user_id), None)
        if not user:
            return False
        user["ativo"] = bool(active)
        return True

    def criar_conversa_ia(self, user_id, title):
        now = datetime.now().replace(microsecond=0)
        item = {
            "id": self._id("ai_conversations"),
            "user_id": int(user_id),
            "title": str(title),
            "created_at": now,
            "updated_at": now,
        }
        self.ai_conversations.append(item)
        return dict(item)

    def listar_conversas_ia(self, user_id, *, limit=100):
        items = [item for item in self.ai_conversations if item["user_id"] == int(user_id)]
        items.sort(key=lambda item: (item["updated_at"], item["id"]), reverse=True)
        return [dict(item) for item in items[:limit]]

    def obter_conversa_ia(self, conversation_id, user_id, *, message_limit=None):
        item = next(
            (
                item for item in self.ai_conversations
                if item["id"] == int(conversation_id) and item["user_id"] == int(user_id)
            ),
            None,
        )
        if item is None:
            return None
        messages = [
            dict(message) for message in self.ai_messages
            if message["conversation_id"] == int(conversation_id)
        ]
        messages.sort(key=lambda message: (message["created_at"], message["id"]))
        if message_limit is not None:
            messages = messages[-int(message_limit):]
        return {**dict(item), "messages": messages}

    def atualizar_titulo_conversa_ia(self, conversation_id, user_id, title):
        item = next(
            (
                item for item in self.ai_conversations
                if item["id"] == int(conversation_id) and item["user_id"] == int(user_id)
            ),
            None,
        )
        if item is None:
            return None
        item["title"] = str(title)
        item["updated_at"] = datetime.now().replace(microsecond=0)
        return dict(item)

    def excluir_conversa_ia(self, conversation_id, user_id):
        item = next(
            (
                item for item in self.ai_conversations
                if item["id"] == int(conversation_id) and item["user_id"] == int(user_id)
            ),
            None,
        )
        if item is None:
            return False
        self.ai_conversations.remove(item)
        self.ai_messages = [
            message for message in self.ai_messages
            if message["conversation_id"] != int(conversation_id)
        ]
        return True

    def adicionar_mensagem_ia(
        self,
        conversation_id,
        user_id,
        role,
        content,
        *,
        model=None,
        metadata=None,
    ):
        conversation = next(
            (
                item for item in self.ai_conversations
                if item["id"] == int(conversation_id) and item["user_id"] == int(user_id)
            ),
            None,
        )
        if conversation is None:
            return None
        now = datetime.now().replace(microsecond=0)
        item = {
            "id": self._id("ai_messages"),
            "conversation_id": int(conversation_id),
            "role": str(role),
            "content": str(content),
            "model": model,
            "created_at": now,
            "metadata": dict(metadata or {}),
        }
        self.ai_messages.append(item)
        conversation["updated_at"] = now
        return dict(item)

    def listar_conhecimento_ia_validado(self, *, limit=100):
        return [
            dict(item) for item in self.ai_knowledge
            if item.get("status_validacao") == "validado"
        ][:limit]

    def registrar_relatorio_gerado(self, **values):
        item = {
            "id": str(values["report_id"]),
            **{key: values.get(key) for key in (
                "created_by", "report_type", "period_start", "period_end", "filters",
                "filename", "storage_path", "status", "source", "size_bytes",
                "worksheet_count", "row_count", "generation_ms", "created_at",
                "expires_at", "idempotency_key", "generation_metadata",
            )},
            "download_count": 0,
            "last_downloaded_at": None,
        }
        duplicate = self.obter_relatorio_por_idempotencia(
            item["created_by"], item.get("idempotency_key")
        ) if item.get("idempotency_key") else None
        if duplicate:
            return duplicate
        self.generated_reports.append(item)
        return dict(item)

    def reservar_relatorio_gerado(self, **values):
        """Espelha o UPSERT do PostgreSQL: só um dono por chave de idempotência."""

        chave = values.get("idempotency_key")
        existente = self.obter_relatorio_por_idempotencia(
            values["created_by"], chave
        ) if chave else None
        criado_em = values.get("created_at")
        if existente is not None:
            expirado = (
                existente.get("expires_at") is not None
                and criado_em is not None
                and existente["expires_at"] <= criado_em
            )
            if existente.get("status") not in ("falhou", "expirado") and not expirado:
                return None
            alvo = next(item for item in self.generated_reports if item["id"] == existente["id"])
            alvo.update({
                "id": str(values["report_id"]),
                "report_type": values.get("report_type"),
                "period_start": values.get("period_start"),
                "period_end": values.get("period_end"),
                "filters": dict(values.get("filters") or {}),
                "filename": values.get("filename"),
                "storage_path": values.get("storage_path"),
                "status": "gerando",
                "source": values.get("source"),
                "size_bytes": 0,
                "worksheet_count": 0,
                "row_count": 0,
                "generation_ms": 0,
                "created_at": criado_em,
                "expires_at": values.get("expires_at"),
                "generation_metadata": dict(values.get("generation_metadata") or {}),
            })
            return dict(alvo)

        item = {
            "id": str(values["report_id"]),
            "created_by": int(values["created_by"]),
            "report_type": values.get("report_type"),
            "period_start": values.get("period_start"),
            "period_end": values.get("period_end"),
            "filters": dict(values.get("filters") or {}),
            "filename": values.get("filename"),
            "storage_path": values.get("storage_path"),
            "status": "gerando",
            "source": values.get("source"),
            "size_bytes": 0,
            "worksheet_count": 0,
            "row_count": 0,
            "generation_ms": 0,
            "generation_metadata": dict(values.get("generation_metadata") or {}),
            "idempotency_key": chave,
            "created_at": criado_em,
            "expires_at": values.get("expires_at"),
            "download_count": 0,
            "last_downloaded_at": None,
        }
        self.generated_reports.append(item)
        return dict(item)

    def concluir_relatorio_gerado(self, report_id, **values):
        item = next((i for i in self.generated_reports if i["id"] == str(report_id)), None)
        if item is None:
            return None
        item.update({
            "status": "pronto",
            "size_bytes": values.get("size_bytes"),
            "worksheet_count": values.get("worksheet_count"),
            "row_count": values.get("row_count"),
            "generation_ms": values.get("generation_ms"),
            "generation_metadata": dict(values.get("generation_metadata") or {}),
        })
        return dict(item)

    def falhar_relatorio_gerado(self, report_id):
        item = next((i for i in self.generated_reports if i["id"] == str(report_id)), None)
        if item is None:
            return None
        item["status"] = "falhou"
        return dict(item)

    def obter_relatorio_gerado(self, report_id, user_id):
        item = next((
            item for item in self.generated_reports
            if item["id"] == str(report_id) and item["created_by"] == int(user_id)
        ), None)
        return dict(item) if item else None

    def obter_relatorio_por_idempotencia(self, user_id, idempotency_key):
        if not idempotency_key:
            return None
        item = next((
            item for item in self.generated_reports
            if item["created_by"] == int(user_id)
            and item.get("idempotency_key") == str(idempotency_key)
        ), None)
        return dict(item) if item else None

    def registrar_download_relatorio(self, report_id, user_id, downloaded_at):
        item = next((
            item for item in self.generated_reports
            if item["id"] == str(report_id) and item["created_by"] == int(user_id)
        ), None)
        if item is None:
            return None
        item["download_count"] += 1
        item["last_downloaded_at"] = downloaded_at
        return dict(item)

    def criar_agendamento_relatorio(self, **values):
        item = {
            "id": self._id("report_schedules"),
            **values,
            "filters": dict(values.get("filters") or {}),
            "updated_at": values.get("created_at"),
        }
        self.report_schedules.append(item)
        return dict(item)

    def listar_agendamentos_relatorio(self, user_id=None, *, enabled_only=False):
        items = self.report_schedules
        if user_id is not None:
            items = [item for item in items if item["created_by"] == int(user_id)]
        if enabled_only:
            items = [item for item in items if item.get("enabled")]
        return [dict(item) for item in items]

    def excluir_agendamento_relatorio(self, schedule_id, user_id):
        item = next((
            item for item in self.report_schedules
            if item["id"] == int(schedule_id) and item["created_by"] == int(user_id)
        ), None)
        if item is None:
            return False
        self.report_schedules.remove(item)
        return True

    def listar_destinos_mensagem(self, user_id, *, provider="telegram"):
        return [
            dict(item) for item in self.messaging_destinations
            if item["user_id"] == int(user_id)
            and item["provider"] == provider
            and item.get("enabled", True)
        ]

    def obter_destino_mensagem(self, destination_id, user_id, *, provider="telegram"):
        item = next((
            item for item in self.messaging_destinations
            if item["id"] == int(destination_id)
            and item["user_id"] == int(user_id)
            and item["provider"] == provider
            and item.get("enabled", True)
        ), None)
        return dict(item) if item else None

    def registrar_entrega_relatorio(self, **values):
        item = next((
            item for item in self.report_deliveries
            if item["idempotency_key"] == values["idempotency_key"]
        ), None)
        if item is None:
            item = {"id": self._id("report_deliveries"), **values}
            self.report_deliveries.append(item)
        else:
            item.update(values)
        return dict(item)

    def obter_entrega_relatorio_por_idempotencia(self, idempotency_key):
        item = next((
            item for item in self.report_deliveries
            if item["idempotency_key"] == str(idempotency_key)
        ), None)
        return dict(item) if item else None

    def inserir_tarefa(self, codigo_tarefa, material=None, espessura=None):
        codigo = limpa_codigo(codigo_tarefa)
        task = next((item for item in self.tasks if item["codigo_tarefa"] == codigo), None)
        if task:
            if material is not None:
                task["material"] = material
            if espessura is not None:
                task["espessura"] = float(espessura)
            return task["id"]
        task = {
            "id": self._id("tasks"), "codigo_tarefa": codigo, "material": material,
            "espessura": float(espessura) if espessura is not None else None, "status": None,
            "data_inicio_destaque": None, "data_finalizacao": None, "data_despacho": None,
            "observacoes": None,
        }
        self.tasks.append(task)
        return task["id"]

    def buscar_tarefa_por_codigo(self, codigo):
        task = next((item for item in self.tasks if item["codigo_tarefa"] == limpa_codigo(codigo)), None)
        return dict(task) if task else None

    def buscar_tarefa_por_id(self, task_id):
        task = next((item for item in self.tasks if item["id"] == task_id), None)
        return dict(task) if task else None

    def listar_tarefas(self):
        return [dict(item) for item in self.tasks]

    def get_tasks(self, status_filter=None, search=None):
        rows = self.listar_tarefas()
        if status_filter and status_filter != "Todos":
            rows = [row for row in rows if (row["status"] or "Aguardando registro") == status_filter]
        if search:
            text = search.upper()
            rows = [row for row in rows if text in row["codigo_tarefa"] or text in (row["material"] or "").upper()]
        return rows

    def atualizar_tarefa_status(self, task_id, status):
        task = next((item for item in self.tasks if item["id"] == task_id), None)
        if not task:
            return False
        task["status"] = status
        field = {"Destacando": "data_inicio_destaque", "Finalizado": "data_finalizacao", "Despachado": "data_despacho"}.get(status)
        if field:
            task[field] = datetime.now().replace(microsecond=0)
        return True

    def registrar_transicao_tarefa(
        self, tarefa_id, status_esperado, novo_status, operador, setor, motivo
    ):
        task = next((item for item in self.tasks if item["id"] == tarefa_id), None)
        if not task or task.get("status") != status_esperado:
            return False
        self.atualizar_tarefa_status(tarefa_id, novo_status)
        self.inserir_historico(
            task["codigo_tarefa"], "Movimentação", setor, motivo, 0, operador, "", tarefa_id
        )
        return True

    def obter_estado_destaque(self, tarefa_id, plano_hash=None):
        task = next((item for item in self.tasks if item["id"] == tarefa_id), None)
        if not task:
            return None
        event = next(
            (
                item for item in reversed(self.highlight_events)
                if item["tarefa_id"] == tarefa_id
                and item.get("plano_hash") == plano_hash
            ),
            None,
        )
        if event:
            state = event.get("estado")
        elif plano_hash:
            state = "aguardando"
        else:
            state = {
                "Destacando": "inicio",
                "Finalizado": "fim",
                "Despachado": "fim",
            }.get(task.get("status"), "aguardando")
        return {
            "tarefa_id": tarefa_id,
            "codigo_tarefa": task["codigo_tarefa"],
            "status_tarefa": task.get("status"),
            "estado": state,
            "evento": dict(event) if event else None,
        }

    def transicionar_destaque_tarefa(
        self, tarefa_id, acao, operador, *, codigo_status_recurso=None,
        motivo=None, comentario=None, data_hora=None, plano_hash=None,
    ):
        task = next((item for item in self.tasks if item["id"] == tarefa_id), None)
        if not task or task.get("status") in {"Finalizado", "Despachado"}:
            return None
        grupo = next(
            (item for item in self.listar_fila_destaque(limite=10000) if item["tarefa_id"] == tarefa_id),
            None,
        )
        if plano_hash:
            plan = next(
                (item for item in (grupo or {}).get("planos", []) if item["plano_hash"] == plano_hash),
                None,
            )
            if not plan or plan.get("status_corte") != "Finalizado":
                return None
        elif not grupo or grupo.get("situacao") != "COMPLETA":
            return None
        current = self.obter_estado_destaque(tarefa_id, plano_hash)["estado"]
        now = normalizar_data_db(data_hora) or datetime.now().replace(microsecond=0)
        if plano_hash:
            # Escopo de chapa: os mesmos estados, sem mexer no status da tarefa.
            if acao == "inicio" and current in {"aguardando", "parada"}:
                event_state = "retomada" if current == "parada" else "inicio"
                if not task.get("status"):
                    task["status"] = "Destacando"
                    task["data_inicio_destaque"] = task.get("data_inicio_destaque") or now
            elif acao == "parada" and current in {"inicio", "retomada"}:
                event_state = "parada"
            elif acao == "fim" and current in {"inicio", "retomada"}:
                event_state = "fim"
            else:
                return None
        elif acao == "inicio" and current == "aguardando" and not task.get("status"):
            event_state = "inicio"
            task["status"] = "Destacando"
            task["data_inicio_destaque"] = task.get("data_inicio_destaque") or now
        elif acao == "inicio" and current == "parada" and task.get("status") == "Destacando":
            event_state = "retomada"
        elif acao == "parada" and current in {"inicio", "retomada"} and task.get("status") == "Destacando":
            event_state = "parada"
        elif acao == "fim" and current in {"inicio", "retomada"} and task.get("status") == "Destacando":
            event_state = "fim"
            task["status"] = "Finalizado"
            task["data_finalizacao"] = now
            for plan in grupo.get("planos", []):
                latest = next(
                    (
                        item for item in reversed(self.highlight_events)
                        if item.get("tarefa_id") == tarefa_id
                        and item.get("plano_hash") == plan.get("plano_hash")
                    ),
                    None,
                )
                if (latest or {}).get("estado") == "fim":
                    continue
                self.highlight_events.append({
                    "id": self._id("highlight_events"),
                    "tarefa_id": tarefa_id,
                    "estado": "fim",
                    "codigo_status_recurso": None,
                    "motivo": None,
                    "comentario": None,
                    "operador": operador,
                    "data_hora": now,
                    "plano_hash": plan.get("plano_hash"),
                })
        else:
            return None
        event = {
            "id": self._id("highlight_events"),
            "tarefa_id": tarefa_id,
            "estado": event_state,
            "codigo_status_recurso": codigo_status_recurso,
            "motivo": motivo,
            "comentario": comentario,
            "operador": operador,
            "data_hora": now,
            "plano_hash": plano_hash,
        }
        self.highlight_events.append(event)
        self.inserir_historico(
            task["codigo_tarefa"], "Apontamento Destaque", "Destaque",
            event_state, 0, operador, "", tarefa_id,
        )
        result = dict(task)
        result["estado_destaque"] = event_state
        result["evento_destaque_id"] = event["id"]
        return result

    def listar_fila_destaque(self, *, limite=60):
        """Fila do Destaque agrupada por tarefa, como o repositório real."""

        grupos = {}
        for plano in self.cut_plans:
            machine = str(plano.get("maquina_sigmanest") or "").strip().upper()
            if machine and machine != SIGMANEST_LASER_MACHINE:
                continue
            if not plano.get("ativo", True):
                continue
            tarefa = next(
                (
                    item for item in self.tasks
                    if str(item.get("codigo_tarefa") or "") == str(plano.get("codigo_tarefa") or "")
                ),
                None,
            )
            if tarefa is None:
                continue
            apontamento = next(
                (
                    item for item in self.cut_appointments
                    if item.get("plano_hash") == plano.get("plano_hash")
                ),
                None,
            )
            evento = next(
                (
                    item for item in reversed(self.highlight_events)
                    if item.get("tarefa_id") == tarefa["id"]
                    and item.get("plano_hash") == plano.get("plano_hash")
                ),
                None,
            )
            grupo = grupos.setdefault(tarefa["id"], {
                "tarefa_id": tarefa["id"],
                "codigo_tarefa": tarefa.get("codigo_tarefa"),
                "status_tarefa": tarefa.get("status"),
                "material": tarefa.get("material"),
                "espessura": tarefa.get("espessura"),
                "planos": [],
            })
            grupo["planos"].append({
                "plano_hash": plano.get("plano_hash"),
                "programa": plano.get("programa"),
                "nome_chapa": plano.get("nome_chapa"),
                "sequencia": plano.get("sequencia_nesting"),
                "repeticao": plano.get("sigmanest_repeat_id"),
                "maquina": plano.get("maquina_sigmanest"),
                "quantidade_processo": plano.get("quantidade_processo"),
                "status_corte": (apontamento or {}).get("status") or "Aguardando",
                "cortada_em": (apontamento or {}).get("data_fim"),
                "estado_destaque": (evento or {}).get("estado") or "aguardando",
                "destaque_em": (evento or {}).get("data_hora"),
                "destaque_operador": (evento or {}).get("operador"),
            })

        resultado = []
        for grupo in grupos.values():
            planos = grupo["planos"]
            cortadas = [item for item in planos if item["status_corte"] == "Finalizado"]
            if not cortadas:
                continue
            destacadas = [item for item in cortadas if item["estado_destaque"] == "fim"]
            grupo.update({
                "chapas_total": len(planos),
                "chapas_cortadas": len(cortadas),
                "chapas_destacadas": len(destacadas),
                "chapas_disponiveis": len(cortadas) - len(destacadas),
                "situacao": "COMPLETA" if len(cortadas) == len(planos) else "PARCIAL",
                "progresso_corte": f"{len(cortadas)} de {len(planos)} planos cortados",
            })
            resultado.append(grupo)
        return resultado[:max(1, int(limite))]

    def listar_ops_catalogo_tarefa(self, codigo_tarefa):
        """Espelha o LEFT JOIN real com o catálogo de OPs do TOTVS."""

        codigo = limpa_codigo(codigo_tarefa)
        produtos = {
            limpa_codigo(item.get("codigo_op")): item
            for item in self.pcp_ops
            if item.get("ativo", True)
        }
        linhas = [
            item for item in self.sigmanest_ops
            if limpa_codigo(item.get("codigo_tarefa")) == codigo
            and item.get("ativo", True)
        ]
        linhas.sort(key=lambda item: (
            str(item.get("programa") or ""),
            limpa_codigo(item.get("codigo_op")),
            str(item.get("linha_hash") or ""),
        ))
        resultado = []
        for item in linhas:
            produto = produtos.get(limpa_codigo(item.get("codigo_op"))) or {}
            resultado.append({
                **item,
                "produto_codigo": produto.get("produto_codigo"),
                "produto_descricao": produto.get("produto_descricao"),
                "quantidade_op": produto.get("quantidade"),
                "unidade_op": produto.get("unidade"),
            })
        return resultado

    def listar_eventos_destaque(self, tarefa_id):
        return [
            dict(item) for item in self.highlight_events
            if item["tarefa_id"] == tarefa_id
        ]

    def listar_cortes_ativos_andon(self):
        """Espelha o LEFT JOIN real: a repetição vem do catálogo de planos.

        O apontamento não guarda ``sigmanest_repeat_id``; lê-lo do próprio
        apontamento foi o que deixou o fake verde enquanto o PostgreSQL
        levantava ``UndefinedColumn``.
        """

        planos = {
            plano.get("plano_hash"): plano
            for plano in self.cut_plans
            if plano.get("plano_hash")
        }
        return [
            {
                "apontamento_id": item.get("id"),
                "maquina": item.get("maquina"),
                "codigo_tarefa": item.get("codigo_tarefa"),
                "programa": item.get("programa"),
                "nome_chapa": item.get("nome_chapa"),
                "sequencia_nesting": item.get("sequencia_nesting"),
                "repeticao": (
                    planos.get(item.get("plano_hash")) or {}
                ).get("sigmanest_repeat_id"),
                "operador_inicio": item.get("operador_inicio"),
                "data_inicio": item.get("data_inicio"),
            }
            for item in self.cut_appointments
            if item.get("status") == "Em processo"
        ]

    def inserir_op_na_tarefa(self, task_id, codigo_op, peca, setor, quantidade):
        codigo = limpa_codigo(codigo_op)
        item = next((row for row in self.ops if row["tarefa_id"] == task_id and row["codigo_op"] == codigo), None)
        if item:
            if not item["editado"]:
                item.update(id_peca=peca, setor_destino_original=setor, setor_destino_atual=setor,
                            quantidade_original=int(quantidade), quantidade_atual=int(quantidade))
            return item["id"]
        item = {
            "id": self._id("ops"), "tarefa_id": task_id, "codigo_op": codigo, "id_peca": peca,
            "setor_destino_original": setor, "setor_destino_atual": setor,
            "quantidade_original": int(quantidade), "quantidade_atual": int(quantidade), "editado": False,
        }
        self.ops.append(item)
        return item["id"]

    def listar_ops_por_tarefa(self, task_id):
        return [dict(item) for item in self.ops if item["tarefa_id"] == task_id]

    def get_ops_for_task(self, task_id):
        return self.listar_ops_por_tarefa(task_id)

    def get_op_counts_by_task(self, task_ids=None):
        allowed = None if task_ids is None else set(task_ids)
        counts = Counter(item["tarefa_id"] for item in self.ops if allowed is None or item["tarefa_id"] in allowed)
        return dict(counts)

    def get_first_op_codes_by_task(self, task_ids):
        first = {}
        allowed = set(task_ids)
        for item in sorted(self.ops, key=lambda row: row["id"]):
            if item["tarefa_id"] in allowed:
                first.setdefault(item["tarefa_id"], item["codigo_op"])
        return first

    def buscar_op_por_codigo(self, codigo):
        normalized = limpa_codigo(codigo)
        item = next((row for row in self.ops if row["codigo_op"] == normalized), None)
        if not item:
            item = next((row for row in self.ops if row["codigo_op"].lstrip("0") == normalized.lstrip("0")), None)
        return dict(item) if item else None

    def listar_operacoes_para_op(self, codigo_op, tipo_setor=None):
        code = limpa_codigo(codigo_op)
        # Espelha o filtro `ativo = TRUE` do PostgreSQL: marco terminal e
        # operação de inspeção da Qualidade não pertencem ao roteiro do posto.
        rows = [
            row for row in self.catalog_operations
            if row["codigo_op"] == code and row.get("ativo", True)
        ]
        if tipo_setor:
            rows = [
                row for row in rows
                if row["tipo_setor"].casefold() == str(tipo_setor).casefold()
            ]
        return [dict(row) for row in rows]

    def listar_roteiro_completo_op(self, codigo_op):
        code = limpa_codigo(codigo_op)
        return [
            dict(row)
            for row in sorted(
                (row for row in self.catalog_operations if row["codigo_op"] == code),
                key=lambda row: (int(row.get("ordem") or 0), int(row.get("id") or 0)),
            )
        ]

    def listar_proximas_operacoes_roteiro(self, tipo_setor=None):
        """Espelho em memória da projeção PostgreSQL da próxima etapa."""

        result = []
        codes = sorted({row["codigo_op"] for row in self.catalog_operations})
        active_states = {"Aguardando", "Em processo", "Parada", "Setup", "Retrabalho"}
        for code in codes:
            route = sorted(
                (
                    dict(row) for row in self.catalog_operations
                    if row["codigo_op"] == code and row.get("ativo", True)
                ),
                key=lambda row: (int(row.get("ordem") or 0), int(row.get("id") or 0)),
            )
            link = next((row for row in self.ops if row["codigo_op"] == code), None)
            task = next(
                (row for row in self.tasks if link and row["id"] == link["tarefa_id"]),
                None,
            )
            override_keys = []
            for appointment in self.appointments:
                if (
                    appointment.get("op") != code
                    or appointment.get("status") != "Finalizado"
                    or not appointment.get("etapa_anterior_pendente_confirmada")
                ):
                    continue
                operation = next(
                    (
                        item for item in route
                        if item.get("id") == appointment.get("catalogo_operacao_id")
                    ),
                    None,
                )
                if operation:
                    override_keys.append((int(operation.get("ordem") or 0), int(operation.get("id") or 0)))
            override_boundary = max(override_keys, default=(-1, -1))
            for operation in route:
                operation_key = (int(operation.get("ordem") or 0), int(operation.get("id") or 0))
                operation_id = operation.get("id")
                appointments = [
                    row for row in self.appointments
                    if row.get("catalogo_operacao_id") == operation_id
                ]
                if any(row.get("status") == "Finalizado" for row in appointments):
                    continue
                if operation_key < override_boundary:
                    continue
                if str(operation.get("tipo_setor") or "").casefold() == "corte":
                    plans = [
                        row for row in self.cut_plans
                        if task
                        and row.get("codigo_tarefa") == task.get("codigo_tarefa")
                        and row.get("ativo", True)
                    ]
                    completed = {
                        row.get("plano_hash") for row in self.cut_appointments
                        if row.get("status") == "Finalizado"
                    }
                    if (
                        task
                        and task.get("status") == "Finalizado"
                        and plans
                        and all(row.get("plano_hash") in completed for row in plans)
                    ):
                        continue
                    break
                if any(row.get("status") in active_states for row in appointments):
                    break
                if (
                    tipo_setor
                    and str(operation.get("tipo_setor") or "").casefold()
                    != str(tipo_setor).casefold()
                ):
                    break
                quantity = next(
                    (
                        row.get("quantidade_atual") or row.get("quantidade_original")
                        for row in self.ops if row["codigo_op"] == code
                    ),
                    operation.get("quantidade") or 1,
                )
                result.append({**operation, "quantidade": quantity})
                break
        return result

    def listar_status_recursos(
        self,
        *,
        somente_habilitados=True,
        incluir_ocultos=False,
        somente_paradas=False,
        setup=None,
        retrabalho=None,
    ):
        rows = list(self.status_resources)
        if somente_habilitados:
            rows = [row for row in rows if row.get("habilitado")]
        if not incluir_ocultos:
            rows = [row for row in rows if not row.get("oculto")]
        if somente_paradas:
            rows = [
                row for row in rows
                if row.get("grupo_codigo") != "0001"
                and not row.get("setup")
                and not row.get("retrabalho")
            ]
        if setup is not None:
            rows = [row for row in rows if bool(row.get("setup")) is bool(setup)]
        if retrabalho is not None:
            rows = [row for row in rows if bool(row.get("retrabalho")) is bool(retrabalho)]
        return [dict(row) for row in rows]

    def buscar_status_recurso(self, codigo):
        row = next(
            (
                item for item in self.status_resources
                if item["codigo"] == str(codigo or "").strip()
            ),
            None,
        )
        return dict(row) if row else None

    def transicionar_estado_recurso(self, recurso, categoria, **kwargs):
        state = {
            "recurso": str(recurso or "").strip(),
            "categoria": categoria,
            **dict(kwargs),
            "data_inicio": kwargs.get("data_hora") or datetime.now().replace(microsecond=0),
        }
        self.resource_states[state["recurso"]] = state
        return dict(state)

    def buscar_estado_recurso_atual(self, recurso):
        state = self.resource_states.get(str(recurso or "").strip())
        return dict(state) if state else None

    def cadastrar_operador_apontamento(
        self, cracha, nome, *, ativo=True, fonte="cadastro", autorizador_retrabalho=None
    ):
        badge = str(cracha or "").strip()
        current = next((row for row in self.operator_badges if row["cracha"] == badge), None)
        if current is None:
            current = {
                "id": len(self.operator_badges) + 1,
                "cracha": badge,
                "nome": str(nome or "").strip(),
                "ativo": bool(ativo),
                "fonte": fonte,
                "autorizador_retrabalho": bool(autorizador_retrabalho),
            }
            self.operator_badges.append(current)
        else:
            current.update(nome=str(nome or "").strip(), ativo=bool(ativo), fonte=fonte)
            if autorizador_retrabalho is not None:
                current["autorizador_retrabalho"] = bool(autorizador_retrabalho)
        return dict(current)

    def buscar_operador_apontamento_detalhado(self, cracha):
        badge = str(cracha or "").strip()
        row = next((item for item in self.operator_badges if item["cracha"] == badge), None)
        return dict(row) if row else None

    def listar_autorizadores_retrabalho(self):
        return [
            dict(row)
            for row in self.operator_badges
            if row.get("autorizador_retrabalho") and row.get("ativo")
        ]

    def definir_autorizador_retrabalho(self, cracha, autorizado):
        badge = str(cracha or "").strip()
        row = next((item for item in self.operator_badges if item["cracha"] == badge), None)
        if row is None:
            return None
        row["autorizador_retrabalho"] = bool(autorizado)
        return dict(row)

    # ------------------------------------------------------------------
    # Wave 5 — primeira peça
    # ------------------------------------------------------------------
    def garantir_primeira_peca(self, **valores):
        codigo = limpa_codigo(valores.get("codigo_op"))
        operacao_id = valores.get("catalogo_operacao_id")
        existente = self._primeira_peca(codigo, operacao_id)
        if existente is not None:
            return dict(existente)
        agora = valores.get("criada_em") or datetime.now().replace(microsecond=0)
        linha = {
            "id": self._id("first_piece"),
            "codigo_op": codigo,
            "catalogo_operacao_id": operacao_id,
            "numero_operacao": str(valores.get("numero_operacao") or "").strip(),
            "apontamento_id": valores.get("apontamento_id"),
            "produto_codigo": valores.get("produto_codigo"),
            "produto_descricao": valores.get("produto_descricao"),
            "tipo_setor": str(valores.get("tipo_setor") or "").strip(),
            "codigo_recurso": valores.get("codigo_recurso"),
            "recurso_apontado": valores.get("recurso_apontado"),
            "quantidade_planejada": max(1, int(valores.get("quantidade_planejada") or 1)),
            "status": "PENDENTE",
            "peca_produzida_em": None,
            "peca_produzida_por": None,
            "setup_obrigatorio": bool(valores.get("setup_obrigatorio")),
            "setup_registrado_em": None,
            "inspecionada_em": None,
            "inspecionada_por": None,
            "resultado": None,
            "observacao": None,
            "bloqueio_ativo": False,
            "bloqueio_ocorrencia": None,
            "bloqueio_em": None,
            "liberada_em": None,
            "liberada_por_cracha": None,
            "liberada_por_nome": None,
            "tentativas": 0,
            "criada_em": agora,
            "atualizada_em": agora,
        }
        self.first_pieces.append(linha)
        return dict(linha)

    def _primeira_peca(self, codigo_op, catalogo_operacao_id=None):
        codigo = limpa_codigo(codigo_op)
        candidatas = [
            row for row in self.first_pieces
            if limpa_codigo(row["codigo_op"]) == codigo
            and (
                catalogo_operacao_id is None
                or row.get("catalogo_operacao_id") == catalogo_operacao_id
            )
        ]
        return candidatas[-1] if candidatas else None

    def buscar_primeira_peca(self, codigo_op, catalogo_operacao_id=None):
        linha = self._primeira_peca(codigo_op, catalogo_operacao_id)
        return dict(linha) if linha else None

    def buscar_primeira_peca_por_id(self, primeira_peca_id):
        linha = next(
            (row for row in self.first_pieces if row["id"] == int(primeira_peca_id)), None
        )
        return dict(linha) if linha else None

    def listar_primeiras_pecas_da_op(self, codigo_op):
        codigo = limpa_codigo(codigo_op)
        return [
            dict(row) for row in self.first_pieces
            if limpa_codigo(row["codigo_op"]) == codigo
        ]

    def registrar_primeira_peca_produzida(
        self, primeira_peca_id, *, operador, apontamento_id=None, instante=None
    ):
        linha = next(
            (row for row in self.first_pieces if row["id"] == int(primeira_peca_id)), None
        )
        if linha is None or linha["status"] not in {"PENDENTE", "PRODUZIDA", "REFUGO"}:
            return None
        momento = instante or datetime.now().replace(microsecond=0)
        linha["status"] = "PRODUZIDA"
        linha["peca_produzida_em"] = linha["peca_produzida_em"] or momento
        linha["peca_produzida_por"] = linha["peca_produzida_por"] or operador
        linha["apontamento_id"] = apontamento_id or linha["apontamento_id"]
        linha["tentativas"] = int(linha["tentativas"]) + 1
        linha["atualizada_em"] = momento
        return dict(linha)

    def registrar_setup_primeira_peca(
        self, codigo_op, catalogo_operacao_id=None, *, instante=None
    ):
        linha = self._primeira_peca(codigo_op, catalogo_operacao_id)
        if linha is None:
            return None
        momento = instante or datetime.now().replace(microsecond=0)
        linha["setup_registrado_em"] = linha["setup_registrado_em"] or momento
        linha["atualizada_em"] = momento
        return dict(linha)

    def registrar_inspecao_primeira_peca(
        self,
        primeira_peca_id,
        *,
        resultado,
        operador,
        observacao=None,
        instante=None,
        bloquear=False,
        ocorrencia=None,
    ):
        linha = next(
            (row for row in self.first_pieces if row["id"] == int(primeira_peca_id)), None
        )
        if linha is None or linha["bloqueio_ativo"]:
            return None
        momento = instante or datetime.now().replace(microsecond=0)
        linha.update(
            status=str(resultado).strip().upper(),
            resultado=str(resultado).strip().upper(),
            inspecionada_em=momento,
            inspecionada_por=operador,
            observacao=observacao,
            bloqueio_ativo=bool(bloquear),
            bloqueio_ocorrencia=ocorrencia if bloquear else None,
            bloqueio_em=momento if bloquear else None,
            atualizada_em=momento,
        )
        return dict(linha)

    def liberar_primeira_peca_bloqueada(
        self, primeira_peca_id, *, cracha, nome, instante=None
    ):
        linha = next(
            (row for row in self.first_pieces if row["id"] == int(primeira_peca_id)), None
        )
        if linha is None or not linha["bloqueio_ativo"]:
            return None
        momento = instante or datetime.now().replace(microsecond=0)
        linha.update(
            bloqueio_ativo=False,
            status="PRODUZIDA",
            resultado=None,
            liberada_em=momento,
            liberada_por_cracha=cracha,
            liberada_por_nome=nome,
            atualizada_em=momento,
        )
        return dict(linha)

    def listar_primeiras_pecas(
        self, *, tipo_setor=None, status=None, somente_bloqueadas=False, limite=200
    ):
        rows = list(self.first_pieces)
        if tipo_setor:
            rows = [row for row in rows if str(row["tipo_setor"]).casefold() == str(tipo_setor).casefold()]
        if status:
            rows = [row for row in rows if row["status"] == str(status).upper()]
        if somente_bloqueadas:
            rows = [row for row in rows if row["bloqueio_ativo"]]
        return [dict(row) for row in rows[: int(limite)]]

    def resumo_primeira_peca(self):
        contagem = Counter(row["status"] for row in self.first_pieces)
        return [
            {
                "status": status,
                "total": total,
                "bloqueadas": sum(
                    1 for row in self.first_pieces
                    if row["status"] == status and row["bloqueio_ativo"]
                ),
            }
            for status, total in sorted(contagem.items())
        ]

    def registrar_autorizacao_primeira_peca(self, **valores):
        linha = {
            "id": self._id("first_piece_auth"),
            **{
                chave: valores.get(chave)
                for chave in (
                    "primeira_peca_id", "codigo_op", "catalogo_operacao_id",
                    "numero_operacao", "tipo_setor", "codigo_recurso",
                    "recurso_apontado", "operador", "ocorrencia", "cracha",
                    "autorizado_por_nome", "decisao", "motivo_recusa",
                    "estado_antes", "estado_depois",
                )
            },
            "data_hora": valores.get("data_hora") or datetime.now().replace(microsecond=0),
        }
        self.first_piece_authorizations.append(linha)
        return dict(linha)

    def listar_autorizacoes_primeira_peca(self, *, codigo_op=None, limite=200):
        rows = list(reversed(self.first_piece_authorizations))
        if codigo_op:
            alvo = limpa_codigo(codigo_op)
            rows = [row for row in rows if limpa_codigo(row.get("codigo_op")) == alvo]
        return [dict(row) for row in rows[: int(limite)]]

    # ------------------------------------------------------------------
    # Wave 5 — alertas internos
    # ------------------------------------------------------------------
    def registrar_alerta_interno(self, **valores):
        linha = {
            "id": self._id("internal_alert"),
            **{
                chave: valores.get(chave)
                for chave in (
                    "tipo", "severidade", "destinatario", "canal_previsto",
                    "status_notificacao", "codigo_op", "catalogo_operacao_id",
                    "numero_operacao", "tipo_setor", "codigo_recurso",
                    "produto_codigo", "titulo", "mensagem", "quantidade",
                    "detalhes", "origem", "criado_por",
                )
            },
            "criado_em": valores.get("criado_em") or datetime.now().replace(microsecond=0),
            "notificado_em": None,
            "resolvido_em": None,
        }
        self.internal_alerts.append(linha)
        return dict(linha)

    def listar_alertas_internos(
        self, *, destinatario=None, tipo=None, codigo_op=None,
        somente_pendentes=False, limite=200,
    ):
        rows = list(reversed(self.internal_alerts))
        if destinatario:
            rows = [row for row in rows if row.get("destinatario") == str(destinatario).upper()]
        if tipo:
            rows = [row for row in rows if row.get("tipo") == str(tipo).upper()]
        if codigo_op:
            alvo = limpa_codigo(codigo_op)
            rows = [row for row in rows if limpa_codigo(row.get("codigo_op")) == alvo]
        if somente_pendentes:
            rows = [row for row in rows if row.get("status_notificacao") == "PENDENTE"]
        return [dict(row) for row in rows[: int(limite)]]

    def resumo_alertas_internos(self):
        contagem = Counter(
            (row.get("tipo"), row.get("destinatario"), row.get("severidade"), row.get("status_notificacao"))
            for row in self.internal_alerts
        )
        return [
            {
                "tipo": tipo,
                "destinatario": destinatario,
                "severidade": severidade,
                "status_notificacao": status,
                "total": total,
                "quantidade_total": sum(
                    int(row.get("quantidade") or 0)
                    for row in self.internal_alerts
                    if row.get("tipo") == tipo and row.get("destinatario") == destinatario
                ),
            }
            for (tipo, destinatario, severidade, status), total in sorted(
                contagem.items(), key=lambda item: (str(item[0][0]), str(item[0][1]))
            )
        ]

    def listar_operadores_apontamento(self, somente_ativos=True):
        rows = self.operator_badges
        if somente_ativos:
            rows = [row for row in rows if row.get("ativo")]
        return [dict(row) for row in rows]

    def buscar_operadores_apontamento(self, crachas):
        wanted = [str(cracha or "").strip() for cracha in (crachas or ())]
        return [
            dict(row) for badge in wanted for row in self.operator_badges
            if row["cracha"] == badge and row.get("ativo")
        ]

    def atualizar_op(self, op_id, setor, quantidade):
        item = next((row for row in self.ops if row["id"] == op_id), None)
        if not item:
            return False
        item.update(setor_destino_atual=setor, quantidade_atual=int(quantidade), editado=True)
        return True

    def corrigir_op_com_historico(
        self, op_id, codigo_op, setor_esperado, quantidade_esperada,
        novo_setor, nova_quantidade, operador, tarefa_id,
    ):
        item = next((row for row in self.ops if row["id"] == op_id), None)
        if not item:
            return False
        setor_atual = item["setor_destino_atual"] or item["setor_destino_original"]
        quantidade_atual = item["quantidade_atual"] or item["quantidade_original"]
        if setor_atual != setor_esperado or int(quantidade_atual) != int(quantidade_esperada):
            return False
        self.atualizar_op(op_id, novo_setor, nova_quantidade)
        self.inserir_historico(
            codigo_op, "Correção", novo_setor,
            f"Ajuste: {setor_esperado}->{novo_setor}, qtd {quantidade_esperada}->{nova_quantidade}",
            int(nova_quantidade) - int(quantidade_esperada), operador, "", tarefa_id,
        )
        return True

    def inserir_historico(self, op, tipo, setor, motivo, quantidade, operador, peca="", tarefa_id=None, data_hora=None):
        row = {
            "id": self._id("history"), "op": limpa_codigo(op), "tipo": tipo, "setor": setor,
            "motivo": motivo, "quantidade": int(quantidade), "operador": operador,
            "data_hora": normalizar_data_db(data_hora) or datetime.now().replace(microsecond=0),
            "peca": peca, "tarefa_id": tarefa_id,
        }
        self.history.append(row)
        return row["id"]

    def registrar_evento_sistema(self, tipo, origem, mensagem, operador=None, referencia=None, detalhes=None, data_hora=None):
        row = {"id": self._id("events"), "tipo": tipo, "origem": origem, "mensagem": mensagem,
               "operador": operador, "referencia": referencia, "detalhes": detalhes,
               "data_hora": normalizar_data_db(data_hora) or datetime.now().replace(microsecond=0)}
        self.events.append(row)
        return row["id"]

    def ultimo_status_sincronizacao(self):
        """Espelha o stub real: nenhuma integração de BI participa do produto."""

        return {
            "status": "Pendente TI",
            "mensagem": "Integração Protheus/TOTVS ainda não configurada.",
            "data_hora": "",
            "referencia": "TOTVS",
        }

    def listar_fila_corte(self, data_minima, maquina_sigmanest=None, agora=None):
        cutoff = normalizar_data_db(data_minima).date()
        pointed = {row["plano_hash"] for row in self.cut_appointments}
        waiting = []
        for plan in self.cut_plans:
            program_date = plan.get("data_programa")
            if isinstance(program_date, datetime):
                program_date = program_date.date()
            if not plan.get("ativo", True) or not program_date or program_date < cutoff:
                continue
            if plan["plano_hash"] in pointed:
                continue
            # Espelha a regra canônica: nesting já concluído no SigmaNEST sai
            # da fila ativa, mas continua persistido para auditoria.
            if plan.get("sigmanest_comp_date") is not None:
                continue
            if maquina_sigmanest and str(plan.get("maquina_sigmanest", "")).upper() != str(maquina_sigmanest).upper():
                continue
            task = next(
                (item for item in self.tasks if item["codigo_tarefa"] == plan["codigo_tarefa"]),
                {},
            )
            waiting.append({
                **plan,
                "id": None,
                "material": plan.get("material", task.get("material")),
                "espessura": plan.get("espessura", task.get("espessura")),
                "status": "Aguardando",
                "operador_inicio": None,
                "data_inicio": None,
                "operador_fim": None,
                "data_fim": None,
                "tempo_real_segundos": None,
            })
        active = []
        for row in self.cut_appointments:
            if row["status"] != "Em processo":
                continue
            if maquina_sigmanest and str(row.get("maquina_sigmanest", "")).upper() != str(maquina_sigmanest).upper():
                continue
            # Espelha a consulta canônica: o instante de referência vem do
            # chamador (relógio da aplicação, virtual ou não) e só cai para o
            # relógio local quando não é informado.
            referencia = normalizar_data_db(agora) or datetime.now()
            elapsed = (referencia - row["data_inicio"]).total_seconds()
            active.append({**row, "tempo_real_segundos": elapsed})
        incomplete_keys = {
            (row.get("codigo_tarefa"), str(row.get("maquina_sigmanest") or "").upper())
            for row in active + waiting
        }
        completed = []
        for row in self.cut_appointments:
            key = (
                row.get("codigo_tarefa"),
                str(row.get("maquina_sigmanest") or "").upper(),
            )
            if row["status"] != "Finalizado" or key not in incomplete_keys:
                continue
            if maquina_sigmanest and key[1] != str(maquina_sigmanest).upper():
                continue
            completed.append({
                **row,
                "tempo_real_segundos": (
                    row["data_fim"] - row["data_inicio"]
                ).total_seconds(),
            })
        rows = active + waiting + completed
        rows.sort(key=lambda item: (
            item.get("codigo_tarefa") or "",
            item.get("programa") or "",
        ))
        rows.sort(
            key=lambda item: item.get("data_programa") or date.min,
            reverse=True,
        )
        rows.sort(key=lambda item: {
            "Em processo": 0,
            "Aguardando": 1,
            "Finalizado": 2,
        }.get(item["status"], 3))
        return rows

    def iniciar_apontamento_corte(self, plano_hash, maquina, operador, data_minima, data_inicio=None):
        if any(row["plano_hash"] == plano_hash for row in self.cut_appointments):
            return None
        plan = next(
            (row for row in self.listar_fila_corte(data_minima) if row["plano_hash"] == plano_hash),
            None,
        )
        if not plan:
            return None
        row = {
            **plan,
            "id": self._id("cut_appointments"),
            "maquina": maquina,
            "status": "Em processo",
            "operador_inicio": operador,
            "data_inicio": normalizar_data_db(data_inicio) or datetime.now().replace(microsecond=0),
            "operador_fim": None,
            "data_fim": None,
        }
        self.cut_appointments.append(row)
        return dict(row)

    def finalizar_apontamento_corte(self, apontamento_id, operador, data_fim=None):
        row = next(
            (
                item for item in self.cut_appointments
                if item["id"] == apontamento_id and item["status"] == "Em processo"
            ),
            None,
        )
        if not row:
            return None
        end = normalizar_data_db(data_fim) or datetime.now().replace(microsecond=0)
        row["status"] = "Finalizado"
        row["operador_fim"] = operador
        row["data_fim"] = end
        row["tempo_real_segundos"] = (row["data_fim"] - row["data_inicio"]).total_seconds()
        return dict(row)

    def avancar_nesting_corte(
        self, apontamento_id, proximo_plano_hash, operador, data_minima, momento=None
    ):
        current = next(
            (
                item for item in self.cut_appointments
                if item["id"] == apontamento_id and item["status"] == "Em processo"
            ),
            None,
        )
        if not current:
            return None
        next_plan = next(
            (
                item for item in self.listar_fila_corte(data_minima)
                if item["plano_hash"] == proximo_plano_hash
                and item["codigo_tarefa"] == current["codigo_tarefa"]
                and item["maquina_sigmanest"] == current["maquina_sigmanest"]
            ),
            None,
        )
        if not next_plan:
            return None
        transition = normalizar_data_db(momento) or datetime.now().replace(microsecond=0)
        current["status"] = "Finalizado"
        current["operador_fim"] = operador
        current["data_fim"] = transition
        current["tempo_real_segundos"] = (
            current["data_fim"] - current["data_inicio"]
        ).total_seconds()
        started = {
            **next_plan,
            "id": self._id("cut_appointments"),
            "maquina": current["maquina"],
            "status": "Em processo",
            "operador_inicio": operador,
            "data_inicio": transition,
            "operador_fim": None,
            "data_fim": None,
        }
        self.cut_appointments.append(started)
        return {"finalizado": dict(current), "iniciado": dict(started)}

    def listar_apontamentos_corte(
        self, inicio=None, fim=None, maquina=None, status=None, search=None, agora=None
    ):
        rows = list(self.cut_appointments)
        if inicio:
            rows = [row for row in rows if row["data_inicio"] >= normalizar_data_db(inicio)]
        if fim:
            rows = [row for row in rows if row["data_inicio"] <= normalizar_data_db(fim)]
        if maquina:
            rows = [row for row in rows if row.get("maquina", "").upper() == maquina.upper()]
        if status and status != "Todos":
            rows = [row for row in rows if row["status"] == status]
        if search:
            needle = search.casefold()
            rows = [
                row for row in rows
                if any(
                    needle in str(row.get(key) or "").casefold()
                    for key in ("codigo_tarefa", "programa", "material")
                )
            ]
        result = []
        # Mesma referência temporal da consulta canônica: o instante vem do
        # chamador e só cai para o relógio local quando não é informado.
        referencia = normalizar_data_db(agora) or datetime.now()
        for row in rows:
            end = row.get("data_fim") or referencia
            result.append({**row, "tempo_real_segundos": (end - row["data_inicio"]).total_seconds()})
        return sorted(result, key=lambda item: (item["data_inicio"], item["id"]), reverse=True)

    def get_op_timeline(self, op):
        normalized = limpa_codigo(op).lstrip("0")
        return [dict(row) for row in sorted(self.history, key=lambda item: (item["data_hora"], item["id"]))
                if row["op"].lstrip("0") == normalized]

    def obter_historico_completo(self, periodo_inicio=None, periodo_fim=None, setor=None, operador=None, tipo=None, search=None):
        rows = list(self.history)
        if periodo_inicio:
            rows = [row for row in rows if row["data_hora"] >= normalizar_data_db(periodo_inicio)]
        if periodo_fim:
            rows = [row for row in rows if row["data_hora"] <= normalizar_data_db(periodo_fim)]
        if setor:
            rows = [row for row in rows if row["setor"] == setor]
        if operador:
            rows = [row for row in rows if row["operador"] == operador]
        if tipo:
            rows = [row for row in rows if row["tipo"] == tipo]
        if search:
            text = search.lower()
            rows = [row for row in rows if any(text in str(row.get(key) or "").lower() for key in ("op", "peca", "motivo"))]
        return [dict(row) for row in sorted(rows, key=lambda item: (item["data_hora"], item["id"]), reverse=True)]

    def buscar_movimentacoes_periodo(self, inicio, fim):
        return [row for row in self.obter_historico_completo(inicio, fim, tipo="Movimentação") if not row["op"].startswith("T")]

    def _latest(self):
        latest = {}
        for row in sorted(self.history, key=lambda item: (item["data_hora"], item["id"])):
            if row["tipo"] == "Movimentação" and not row["op"].startswith("T"):
                latest[row["op"]] = row
        return list(latest.values())

    def get_current_ops(
        self, setor_filter=None, search=None, maquinas_dobra=None, maquinas_usinagem=None, maquinas_serra=None
    ):
        rows = self._latest()
        if setor_filter:
            mapping = {
                "ALMOX": ["Almoxarifado"], "ALMOXARIFADO": ["Almoxarifado"],
                "AGUARDANDO_DOBRA": ["Aguardando Dobra"], "MAQUINAS_DOBRA": maquinas_dobra or [],
                "AGUARDANDO_USINAGEM": ["Aguardando Usinagem"], "MAQUINAS_USINAGEM": maquinas_usinagem or [],
                "AGUARDANDO_SERRA": ["Aguardando Serra"], "MAQUINAS_SERRA": maquinas_serra or [],
            }
            allowed = mapping.get(setor_filter.upper(), [setor_filter])
            rows = [row for row in rows if row["setor"] in allowed]
        if search:
            text = search.upper()
            rows = [row for row in rows if text in row["op"].upper() or text in (row["peca"] or "").upper()]
        return [dict(row) for row in sorted(rows, key=lambda item: item["data_hora"], reverse=True)]

    def buscar_movimentos_setores(self, setores):
        return [dict(row) for row in self._latest() if row["setor"] in setores]

    def despachar_tarefa(
        self, task_id, operador, maquinas_dobra=None, maquinas_usinagem=None, maquinas_serra=None
    ):
        task = next((item for item in self.tasks if item["id"] == task_id), None)
        if not task or task["status"] != "Finalizado":
            return False
        now = datetime.now().replace(microsecond=0)
        for op in self.listar_ops_por_tarefa(task_id):
            setor = op["setor_destino_atual"] or op["setor_destino_original"]
            if setor.upper() in ("DOBRA", "AGUARDANDO DOBRA"):
                setor = "Aguardando Dobra"
            elif setor.upper() in ("USINAGEM", "AGUARDANDO USINAGEM"):
                setor = "Aguardando Usinagem"
            elif setor.upper() in ("SERRA", "AGUARDANDO SERRA"):
                setor = "Aguardando Serra"
            self.inserir_historico(op["codigo_op"], "Movimentação", setor, "", op["quantidade_atual"] or op["quantidade_original"], operador, op["id_peca"], task_id, now)
        task.update(status="Despachado", data_despacho=now)
        return True

    def ultimas_ops_despachadas(self, periodo_inicio=None, periodo_fim=None, limite=5):
        dispatched = {item["id"]: item for item in self.tasks if item["status"] == "Despachado"}
        rows = [row for row in self.history if row["tarefa_id"] in dispatched and row["data_hora"] == dispatched[row["tarefa_id"]]["data_despacho"]]
        return [dict(row) for row in sorted(rows, key=lambda item: item["id"], reverse=True)[:limite]]

    def enfileirar_apontamento_operacional(
        self, op, peca, tarefa_id, tipo_setor, maquina, operador,
        quantidade=1, data_entrada=None, operacao=None,
        etapa_anterior_pendente_confirmada=False,
    ):
        normalized = limpa_codigo(op)
        if any(
            item["op"] == normalized
            and item["tipo_setor"].upper() == tipo_setor.upper()
            and item["status"] in ("Aguardando", "Em processo", "Parada", "Setup", "Retrabalho")
            for item in self.appointments
        ):
            return None
        operation = dict(operacao or {})
        row = {"id": self._id("appointments"), "op": normalized, "peca": peca, "tarefa_id": tarefa_id,
               "tipo_setor": tipo_setor, "maquina": maquina, "status": "Aguardando", "quantidade": int(quantidade),
               "operador_fila": operador, "data_entrada": normalizar_data_db(data_entrada) or datetime.now().replace(microsecond=0),
               "operador_inicio": None, "data_inicio": None, "operador_fim": None, "data_fim": None, "setor_destino": None,
               "catalogo_operacao_id": operation.get("id"),
               "numero_operacao": operation.get("numero_operacao") or operation.get("codigo"),
               "codigo_recurso": operation.get("codigo_recurso"),
               "descricao_operacao": operation.get("descricao_operacao") or operation.get("nome"),
               "produto_codigo": operation.get("produto_codigo") or operation.get("produto"),
               "produto_descricao": operation.get("produto_descricao") or operation.get("descricao"),
               "quantidade_boa": 0, "quantidade_refugo": 0, "quantidade_retrabalho": 0,
               "lote": None, "motivo_refugo": None, "causa_raiz": None, "tipo_setup": None,
               "motivo_parada": None, "comentario": None,
               "codigo_status_recurso": None, "estado_retorno": None,
               "etapa_anterior_pendente_confirmada": bool(etapa_anterior_pendente_confirmada),
               "retorno_retrabalho_qualidade": False,
               "origem_retrabalho_inspecao_id": None}
        self.appointments.append(row)
        self.operator_events.append(
            {
                "id": self._id("operator_events"),
                "apontamento_id": row["id"], "estado": "fila", "operador": operador,
                "data_hora": row["data_entrada"],
            }
        )
        return dict(row)

    def buscar_apontamento_operacional(self, item_id):
        row = next((item for item in self.appointments if item["id"] == item_id), None)
        return dict(row) if row else None

    def listar_apontamentos_operacionais(self, tipo_setor, maquina=None, somente_ativos=True):
        rows = [item for item in self.appointments if item["tipo_setor"].upper() == tipo_setor.upper()]
        if maquina:
            rows = [item for item in rows if item["maquina"].upper() == maquina.upper()]
        if somente_ativos:
            rows = [
                item for item in rows
                if item["status"] in ("Aguardando", "Em processo", "Parada", "Setup", "Retrabalho")
            ]
        return [dict(item) for item in rows]

    def listar_apontamentos_por_op(self, op):
        normalized = limpa_codigo(op)
        return [dict(item) for item in self.appointments if item["op"] == normalized]

    def listar_apontamentos_operacionais_periodo(self, tipo_setor, inicio, fim):
        return [dict(item) for item in self.appointments if item["tipo_setor"].upper() == tipo_setor.upper() and item["data_inicio"]]

    def listar_ops_solda_gerencial(self, *, limite=300):
        """Espelho em memória da leitura gerencial das OPs de Solda (Wave 6D).

        Reproduz as mesmas junções do PostgreSQL: roteiro ativo de Solda, OP
        ativa do catálogo, execução da própria operação e o primeiro apontamento
        da OP inteira (base da regra de atraso).
        """

        ativos = ("Aguardando", "Em processo", "Parada", "Setup", "Retrabalho")
        pcp_por_op = {
            row["codigo_op"]: row
            for row in self.pcp_ops
            if row.get("ativo", True)
        }
        resultado = []
        operacoes = sorted(
            (
                row for row in self.catalog_operations
                if row.get("ativo", True)
                and str(row.get("tipo_setor") or "").upper() in _SETORES_SOLDA
                and row["codigo_op"] in pcp_por_op
            ),
            key=lambda row: (row["codigo_op"], int(row.get("ordem") or 0), int(row.get("id") or 0)),
        )
        for operacao in operacoes:
            pcp = pcp_por_op[operacao["codigo_op"]]
            candidatos = [
                item for item in self.appointments
                if item["op"] == operacao["codigo_op"]
                and str(item["tipo_setor"]).upper() in _SETORES_SOLDA
                and (
                    item.get("catalogo_operacao_id") == operacao.get("id")
                    or (
                        item.get("catalogo_operacao_id") is None
                        and str(item.get("numero_operacao") or "")
                        == str(operacao.get("numero_operacao") or "")
                    )
                )
            ]
            execucao = next(
                iter(sorted(
                    candidatos,
                    key=lambda item: (
                        0 if item["status"] in ativos else 1,
                        -(item.get("data_fim") or item.get("data_inicio") or item["data_entrada"]).timestamp(),
                        -int(item["id"]),
                    ),
                )),
                None,
            )
            instantes = [
                item.get("data_inicio") or item.get("data_entrada")
                for item in self.appointments
                if item["op"] == operacao["codigo_op"]
            ]
            instantes = [valor for valor in instantes if valor is not None]
            resultado.append({
                "codigo_op": operacao["codigo_op"],
                "numero_operacao": operacao.get("numero_operacao"),
                "ordem": operacao.get("ordem"),
                "codigo_recurso": operacao.get("codigo_recurso"),
                "descricao_operacao": operacao.get("descricao_operacao"),
                "recurso_nome": operacao.get("recurso_nome"),
                "produto_codigo": pcp.get("produto_codigo"),
                "produto_descricao": pcp.get("produto_descricao"),
                "produto_modelo": pcp.get("produto_modelo"),
                "quantidade": pcp.get("quantidade"),
                "data_emissao": pcp.get("data_emissao"),
                "prazo_entrega": pcp.get("prazo_entrega"),
                "inicio_planejado": pcp.get("inicio_planejado"),
                "fim_planejado": pcp.get("fim_planejado"),
                "data_geracao": pcp.get("totvs_generated_on"),
                "estacao_observada": (execucao or {}).get("maquina"),
                "status_apontamento": (execucao or {}).get("status"),
                "apontamento_inicio": (execucao or {}).get("data_inicio"),
                "apontamento_fim": (execucao or {}).get("data_fim"),
                "operador_inicio": (execucao or {}).get("operador_inicio"),
                "operador_fim": (execucao or {}).get("operador_fim"),
                "primeiro_apontamento": min(instantes) if instantes else None,
                "total_apontamentos": len(instantes),
            })
        return resultado[:int(limite)]

    def transicionar_apontamento_operador(
        self, apontamento_id, estado, operador, *, motivo=None, comentario=None,
        codigo_status_recurso=None, quantidade_boa=0, quantidade_refugo=0,
        quantidade_retrabalho=0, lote=None, motivo_refugo=None, causa_raiz=None,
        tipo_setup=None, operadores_cracha=None,
        recurso_roteiro_codigo=None, recurso_roteiro_nome=None,
        recurso_apontado=None, recurso_divergente=False,
        setor_roteiro=None, setor_divergente=False,
        recurso_exclusivo=False,
        setor_destino="Almoxarifado", data_hora=None,
    ):
        row = next((item for item in self.appointments if item["id"] == apontamento_id), None)
        if not row:
            return None
        try:
            destination = OperatorState(estado)
        except ValueError:
            return None
        source = operator_state_from_status(row.get("status"))
        if source is None or not can_transition(source, destination):
            return None
        target = operator_status_for_state(destination)
        return_state = return_state_for_transition(
            source,
            destination,
            row.get("estado_retorno"),
        )
        return_state_value = return_state.value if return_state else None
        if recurso_exclusivo and destination in {
            OperatorState.PRODUCTION,
            OperatorState.SETUP,
            OperatorState.REWORK,
        } and row["status"] == "Aguardando":
            occupied = next(
                (
                    item for item in self.appointments
                    if item["id"] != apontamento_id
                    and item.get("maquina") == row.get("maquina")
                    and item.get("status") in {"Em processo", "Parada", "Setup", "Retrabalho"}
                ),
                None,
            )
            if occupied:
                return {
                    "exclusive_resource_conflict": True,
                    "resource": row.get("maquina"),
                    "operator": occupied.get("operador_inicio")
                    or occupied.get("operador_fila")
                    or "outro operador",
                }
        now = normalizar_data_db(data_hora) or datetime.now().replace(microsecond=0)
        if str(setor_roteiro or "").strip():
            row["setor_roteiro"] = row.get("setor_roteiro") or str(setor_roteiro).strip()
            row["setor_divergente"] = bool(row.get("setor_divergente")) or bool(setor_divergente)
        partial = False
        next_good = int(row.get("quantidade_boa") or 0)
        next_scrap = int(row.get("quantidade_refugo") or 0)
        if target == "Finalizado":
            next_good += int(quantidade_boa or 0)
            next_scrap += int(quantidade_refugo or 0)
            attended = ManufacturingRules.attended_quantity(next_good, next_scrap)
            if attended > int(row["quantidade"]):
                raise ValueError("A soma de peças boas e refugo excede a quantidade prevista restante.")
            partial = attended < int(row["quantidade"])
        row.update(
            status="Aguardando" if partial else target,
            motivo_parada=motivo if target != "Em processo" else None,
            comentario=comentario or row.get("comentario"),
            codigo_status_recurso=(codigo_status_recurso if target != "Em processo" else None),
            lote=lote or row.get("lote"),
            motivo_refugo=motivo_refugo or row.get("motivo_refugo"),
            causa_raiz=causa_raiz or row.get("causa_raiz"),
            tipo_setup=(tipo_setup or row.get("tipo_setup")) if target == "Setup" else row.get("tipo_setup"),
            estado_retorno=(None if partial else return_state_value),
        )
        if target == "Retrabalho":
            row["quantidade_retrabalho"] = int(row.get("quantidade_retrabalho") or 0) + int(quantidade_retrabalho or 0)
        if destination in {
            OperatorState.PRODUCTION,
            OperatorState.STOPPED,
            OperatorState.SETUP,
            OperatorState.REWORK,
        }:
            row["operador_inicio"] = row.get("operador_inicio") or operador
            row["data_inicio"] = row.get("data_inicio") or now
        if target == "Finalizado":
            row.update(quantidade_boa=next_good, quantidade_refugo=next_scrap)
            row["quantidade_retrabalho"] = (
                int(row.get("quantidade_retrabalho") or 0)
                + int(quantidade_retrabalho or 0)
            )
            if not partial:
                row.update(
                    operador_fim=operador,
                    data_fim=now,
                    setor_destino=setor_destino,
                )
            else:
                row["data_entrada"] = now
                row["motivo_parada"] = None
                row["codigo_status_recurso"] = None
        self.operator_events.append(
            {
                "id": self._id("operator_events"),
                "apontamento_id": apontamento_id,
                "estado": "parcial" if partial else estado,
                "operador": operador,
                "data_hora": now,
                "motivo": motivo,
                "comentario": comentario,
                "codigo_status_recurso": codigo_status_recurso,
                "recurso_roteiro_codigo": recurso_roteiro_codigo,
                "recurso_roteiro_nome": recurso_roteiro_nome,
                "recurso_apontado": recurso_apontado,
                "recurso_divergente": bool(recurso_divergente),
                "setor_roteiro": row.get("setor_roteiro"),
                "setor_divergente": bool(row.get("setor_divergente")),
                "estado_retorno": return_state_value,
                "operadores": [
                    row for row in self.buscar_operadores_apontamento(operadores_cracha or ())
                ],
            }
        )
        for kind, qty, reason in (
            ("boa", int(quantidade_boa or 0), None),
            ("refugo", int(quantidade_refugo or 0), motivo_refugo or motivo),
            ("retrabalho", int(quantidade_retrabalho or 0), motivo),
        ):
            if qty > 0:
                self.quantity_events.append({
                    "id": self._id("quantity_events"), "tipo": kind, "quantidade": qty,
                    "op": row.get("op"), "numero_operacao": row.get("numero_operacao"),
                    "produto_codigo": row.get("produto_codigo"), "recurso": row.get("maquina"),
                    "tipo_setor": row.get("tipo_setor"), "operador": operador, "lote": lote,
                    "motivo": reason, "causa_raiz": causa_raiz, "comentario": comentario,
                    "data_hora": now,
                })
        result = dict(row)
        if target == "Finalizado":
            result["finalizacao_parcial"] = partial
            result["saldo_restante"] = ManufacturingRules.quantity_remaining(
                row["quantidade"], next_good, next_scrap
            )
        return result

    def listar_apontamentos_abertos_no_limite_turno(self, data_limite):
        limite = normalizar_data_db(data_limite)
        rows = []
        for row in self.appointments:
            if row.get("status") not in {"Em processo", "Parada", "Setup", "Retrabalho"}:
                continue
            started = row.get("data_inicio")
            if not started or started > limite:
                continue
            exists = any(
                event.get("apontamento_id") == row.get("id")
                and event.get("tipo_interrupcao") == "fim_turno"
                and event.get("data_hora") == limite
                for event in self.operator_events
            )
            if not exists:
                rows.append(dict(row))
        return rows

    def interromper_apontamento_fim_turno(
        self, apontamento_id, *, data_hora, operador="SISTEMA",
        motivo="Fim de turno — interrupção programada automática",
        tipo_interrupcao="fim_turno",
    ):
        limite = normalizar_data_db(data_hora)
        row = next((item for item in self.appointments if item.get("id") == apontamento_id), None)
        if not row:
            return None
        if row.get("status") not in {"Em processo", "Parada", "Setup", "Retrabalho"}:
            return None
        if not row.get("data_inicio") or row.get("data_inicio") > limite:
            return None

        if any(
            event.get("apontamento_id") == apontamento_id
            and event.get("tipo_interrupcao") == tipo_interrupcao
            and event.get("data_hora") == limite
            for event in self.operator_events
        ):
            result = dict(row)
            result["interrupcao_registrada"] = False
            return result

        later_state_event = any(
            event.get("apontamento_id") == apontamento_id
            and event.get("data_hora") > limite
            and event.get("estado") != "parcial"
            for event in self.operator_events
        )
        if not later_state_event and row.get("status") in {"Em processo", "Setup", "Retrabalho"}:
            source = operator_state_from_status(row.get("status"))
            return_state = return_state_for_transition(
                source,
                OperatorState.STOPPED,
                row.get("estado_retorno"),
            )
            row["status"] = "Parada"
            row["motivo_parada"] = motivo
            row["codigo_status_recurso"] = None
            row["estado_retorno"] = return_state.value if return_state else None

        event = {
            "id": self._id("operator_events"),
            "apontamento_id": apontamento_id,
            "estado": "fora_turno",
            "operador": operador,
            "data_hora": limite,
            "motivo": motivo,
            "comentario": None,
            "quantidade_boa": 0,
            "quantidade_refugo": 0,
            "codigo_status_recurso": None,
            "interrupcao_programada": True,
            "origem_automatica": True,
            "tipo_interrupcao": tipo_interrupcao,
            "estado_retorno": row.get("estado_retorno"),
            "operadores": [],
        }
        self.operator_events.append(event)
        self.history.append({
            "id": self._id("history"),
            "op": row.get("op"),
            "tipo": "Apontamento Operador",
            "setor": row.get("maquina"),
            "motivo": motivo,
            "quantidade": 0,
            "operador": operador,
            "data_hora": limite,
            "peca": row.get("peca") or "",
            "tarefa_id": row.get("tarefa_id"),
        })
        result = dict(row)
        result.update({
            "interrupcao_registrada": True,
            "evento_id": event["id"],
            "interrupcao_programada": True,
            "origem_automatica": True,
            "tipo_interrupcao": tipo_interrupcao,
        })
        return result

    def listar_historico_operador(
        self,
        tipo_setor,
        maquina=None,
        data_referencia=None,
        *,
        limite=None,
        deslocamento=0,
    ):
        rows = [
            item for item in self.appointments
            if item["tipo_setor"].casefold() == str(tipo_setor).casefold()
        ]
        if maquina:
            rows = [
                item for item in rows
                if item["maquina"].casefold() == str(maquina).casefold()
            ]
        start = max(0, int(deslocamento or 0))
        end = None if limite is None else start + max(1, int(limite))
        return [dict(item) for item in rows[start:end]]

    def listar_eventos_apontamento_operador(self, apontamento_id):
        return [
            dict(item) for item in self.operator_events
            if item.get("apontamento_id") == apontamento_id
        ]

    def listar_eventos_quantidade_periodo(
        self, inicio, fim, *, setor=None, recurso=None, op=None, operacao=None, produto=None,
        operador=None,
    ):
        start = normalizar_data_db(inicio)
        end = normalizar_data_db(fim)
        rows = []
        for raw in self.quantity_events:
            item = dict(raw)
            if not (start <= item["data_hora"] <= end):
                continue
            if setor and str(item.get("tipo_setor") or "").casefold() != str(setor).casefold():
                continue
            if recurso and str(item.get("recurso") or "").casefold() != str(recurso).casefold():
                continue
            if op and str(item.get("op") or "").casefold() != limpa_codigo(op).casefold():
                continue
            if operacao and str(item.get("numero_operacao") or "") != str(operacao):
                continue
            if produto and str(item.get("produto_codigo") or "").casefold() != str(produto).casefold():
                continue
            if operador and str(operador).casefold() not in str(item.get("operador") or "").casefold():
                continue
            rows.append(item)
        return rows

    def listar_fatos_operacionais_periodo(
        self, inicio, fim, *, setor=None, recurso=None, op=None, operacao=None, produto=None,
        operador=None,
    ):
        start = normalizar_data_db(inicio)
        end = normalizar_data_db(fim)
        result = []
        for raw in self.appointments:
            item = dict(raw)
            item_start = item.get("data_inicio")
            item_end = item.get("data_fim") or datetime.now().replace(microsecond=0)
            if not item_start or item_start > end or item_end < start:
                continue
            if setor and item.get("tipo_setor", "").casefold() != str(setor).casefold():
                continue
            if recurso and item.get("maquina", "").casefold() != str(recurso).casefold():
                continue
            if op and item.get("op", "").casefold() != limpa_codigo(op).casefold():
                continue
            if operacao and str(item.get("numero_operacao") or "") != str(operacao):
                continue
            if produto and str(item.get("produto_codigo") or "").casefold() != str(produto).casefold():
                continue
            if operador:
                needle_operator = str(operador).casefold()
                names = " ".join(str(item.get(key) or "") for key in ("operador_fila", "operador_inicio", "operador_fim")).casefold()
                events_for_operator = self.listar_eventos_apontamento_operador(item["id"])
                if needle_operator not in names and not any(
                    needle_operator in str(event.get("operador") or "").casefold()
                    for event in events_for_operator
                ):
                    continue
            item["eventos"] = self.listar_eventos_apontamento_operador(item["id"])
            operation = next(
                (row for row in self.catalog_operations if row.get("id") == item.get("catalogo_operacao_id")),
                None,
            )
            item["tempo_medio_segundos"] = operation.get("tempo_medio_segundos") if operation else None
            result.append(item)
        return result

    def listar_tempos_nesting_corte(self, inicio=None, fim=None, maquina=None, search=None):
        rows = self.listar_apontamentos_corte(inicio=inicio, fim=fim, maquina=maquina, search=search)
        result = []
        for row in rows:
            planned = float(row.get("tempo_previsto_segundos") or 0) or None
            real = float(row.get("tempo_real_segundos") or 0) if row.get("tempo_real_segundos") is not None else None
            deviation = real - planned if real is not None and planned is not None else None
            period_start = normalizar_data_db(inicio) if inicio else None
            period_end = normalizar_data_db(fim) if fim else None
            execution_start = row.get("data_inicio")
            execution_end = row.get("data_fim") or datetime.now().replace(microsecond=0)
            clipped_start = max(execution_start, period_start) if execution_start and period_start else execution_start
            clipped_end = min(execution_end, period_end) if execution_end and period_end else execution_end
            real_period = (
                max(0.0, (clipped_end - clipped_start).total_seconds())
                if clipped_start and clipped_end else 0.0
            )
            result.append({
                "apontamento_id": row.get("id"), "plano_hash": row.get("plano_hash"),
                "tarefa": row.get("codigo_tarefa"), "programa": row.get("programa"),
                "nesting": row.get("sequencia_nesting"), "maquina": row.get("maquina"),
                "material": row.get("material"), "espessura": row.get("espessura"),
                "inicio": row.get("data_inicio"), "fim": row.get("data_fim"),
                "previsto_segundos": planned, "real_segundos": real,
                "real_periodo_segundos": real_period, "desvio_segundos": deviation,
                "desvio_percentual": (deviation / planned * 100) if deviation is not None and planned else None,
                "status": row.get("status"), "operador_inicio": row.get("operador_inicio"),
                "operador_fim": row.get("operador_fim"),
            })
        return result

    # ------------------------------------------------------------------
    # Tempo-pessoa (Wave 5.1)
    # ------------------------------------------------------------------
    def iniciar_participacao_operador(
        self, recurso, *, operador_id=None, cracha=None, nome=None, tipo_setor=None,
        op=None, numero_operacao=None, data_inicio=None, origem="gestor_pecas",
        referencia_origem=None, apontamento_id=None, tipo_participacao=None,
        operador_principal=False,
    ):
        aberta = next(
            (
                item for item in self.participations
                if item["apontamento_id"] == apontamento_id
                and str(item.get("cracha") or "").casefold()
                == str(cracha or "").casefold()
                and item.get("data_fim") is None
            ),
            None,
        )
        if aberta is not None:
            return dict(aberta)
        row = {
            "id": self._id("participations"),
            "operador_id": operador_id,
            "cracha": cracha,
            "nome": nome,
            "recurso": str(recurso or "").strip(),
            "tipo_setor": tipo_setor,
            "op": limpa_codigo(op) if op else None,
            "numero_operacao": numero_operacao,
            "data_inicio": normalizar_data_db(data_inicio) or datetime.now().replace(microsecond=0),
            "data_fim": None,
            "origem": origem,
            "referencia_origem": referencia_origem,
            "apontamento_id": apontamento_id,
            "tipo_participacao": tipo_participacao,
            "operador_principal": bool(operador_principal),
        }
        self.participations.append(row)
        return dict(row)

    def listar_participacoes_apontamento(self, apontamento_id, *, somente_abertas=False):
        rows = [
            dict(item) for item in self.participations
            if item["apontamento_id"] == apontamento_id
            and (not somente_abertas or item.get("data_fim") is None)
        ]
        rows.sort(key=lambda item: (item["data_inicio"], item["id"]))
        return rows

    def finalizar_participacoes_apontamento(self, apontamento_id, *, data_fim=None, crachas=None):
        fim = normalizar_data_db(data_fim) or datetime.now().replace(microsecond=0)
        alvo = None
        if crachas is not None:
            alvo = {str(item or "").strip().casefold() for item in crachas if str(item or "").strip()}
            if not alvo:
                return []
        fechadas = []
        for item in self.participations:
            if item["apontamento_id"] != apontamento_id or item.get("data_fim") is not None:
                continue
            if alvo is not None and str(item.get("cracha") or "").casefold() not in alvo:
                continue
            item["data_fim"] = fim
            fechadas.append(dict(item))
        return fechadas

    def listar_participacoes_operador_periodo(
        self, inicio, fim, *, recurso=None, setor=None, op=None, operacao=None, cracha=None,
    ):
        start = normalizar_data_db(inicio)
        end = normalizar_data_db(fim)
        rows = []
        for item in self.participations:
            if start and end:
                if item["data_inicio"] >= end:
                    continue
                if (item.get("data_fim") or end) <= start:
                    continue
            if op and str(item.get("op") or "").upper() != limpa_codigo(op).upper():
                continue
            if recurso and str(item.get("recurso") or "").upper() != str(recurso).upper():
                continue
            if setor and str(item.get("tipo_setor") or "").upper() != str(setor).upper():
                continue
            rows.append(dict(item))
        rows.sort(key=lambda item: (item["data_inicio"], item["id"]))
        return rows

    def listar_producao_corte_periodo(self, inicio, fim, maquina=None):
        """Espelha a projeção canônica: tarefa 100% cortada gera produção."""

        period_start = normalizar_data_db(inicio) if inicio else None
        period_end = normalizar_data_db(fim) if fim else None
        rows = []
        for task in self.tasks:
            codigo_tarefa = task["codigo_tarefa"]
            planos = [
                plan for plan in self.cut_plans
                if plan.get("codigo_tarefa") == codigo_tarefa and plan.get("ativo", True)
            ]
            if not planos:
                continue
            apontamentos = [
                row for row in self.cut_appointments
                if row.get("codigo_tarefa") == codigo_tarefa
            ]
            if len(apontamentos) != len(planos):
                continue
            if any(row.get("status") != "Finalizado" for row in apontamentos):
                continue
            ultimo = max(apontamentos, key=lambda row: row.get("data_fim"))
            concluido_em = ultimo.get("data_fim")
            if period_start and concluido_em < period_start:
                continue
            if period_end and concluido_em > period_end:
                continue
            if maquina and str(ultimo.get("maquina") or "").upper() != str(maquina).upper():
                continue
            for vinculo in self.ops:
                if vinculo["tarefa_id"] != task["id"]:
                    continue
                quantidade = int(
                    vinculo.get("quantidade_atual")
                    if vinculo.get("quantidade_atual") is not None
                    else vinculo.get("quantidade_original") or 0
                )
                if quantidade <= 0:
                    continue
                rows.append({
                    "codigo_tarefa": codigo_tarefa,
                    "concluido_em": concluido_em,
                    "maquina": ultimo.get("maquina"),
                    "codigo_op": vinculo["codigo_op"],
                    "quantidade": quantidade,
                })
        rows.sort(key=lambda row: (row["concluido_em"], row["codigo_op"]))
        return rows

    def possui_calendario_produtivo(self, setor=None, recurso=None):
        return False

    def movimentos_por_setor(self):
        return list(Counter(row["setor"] or "" for row in self._latest()).items())

    def movimentos_por_dia(self, dias=7):
        today = datetime.now().date()
        counter = Counter(row["data_hora"].date() for row in self.history if row["tipo"] == "Movimentação" and not row["op"].startswith("T"))
        return [((today - timedelta(days=offset)).strftime("%d/%m/%Y"), counter[today - timedelta(days=offset)]) for offset in range(dias - 1, -1, -1)]

    def ops_por_status(self, maquinas_dobra=None, maquinas_usinagem=None, maquinas_serra=None):
        mapa = dict(self.movimentos_por_setor())
        dobra = mapa.get("Aguardando Dobra", 0) + sum(mapa.get(item, 0) for item in (maquinas_dobra or []))
        usinagem = mapa.get("Aguardando Usinagem", 0) + sum(mapa.get(item, 0) for item in (maquinas_usinagem or []))
        serra = mapa.get("Aguardando Serra", 0) + sum(mapa.get(item, 0) for item in (maquinas_serra or []))
        known = set(
            (maquinas_dobra or []) + (maquinas_usinagem or []) + (maquinas_serra or [])
            + ["Aguardando Dobra", "Aguardando Usinagem", "Aguardando Serra", "Almoxarifado"]
        )
        return {
            "Dobra": dobra,
            "Usinagem": usinagem,
            "Serra": serra,
            "Almoxarifado": mapa.get("Almoxarifado", 0),
            "Outros": sum(value for key, value in mapa.items() if key not in known),
        }

    def counts_overview(self, maquinas_dobra=None, maquinas_usinagem=None, maquinas_serra=None):
        status = self.ops_por_status(maquinas_dobra, maquinas_usinagem, maquinas_serra)
        sync = self.ultimo_status_sincronizacao()
        return {"ops_ativas": len(self._latest()), "tarefas_abertas": sum(item["status"] != "Despachado" for item in self.tasks),
                "ops_em_dobra": status["Dobra"], "ops_em_usinagem": status["Usinagem"],
                "ops_em_serra": status["Serra"],
                "ops_almoxarifado": status["Almoxarifado"], "movimentacoes_hoje": 0,
                "sincronizacao_status": sync["status"], "sincronizacao_mensagem": sync["mensagem"],
                "sincronizacao_data": sync["data_hora"], "sincronizacao_referencia": sync["referencia"],
                "por_setor": dict(self.movimentos_por_setor())}

    # ------------------------------------------------------------------
    # Qualidade — espelho em memória do QualityRepositoryMixin
    # ------------------------------------------------------------------
    def buscar_operacao_inspecao(self, codigo_op):
        code = limpa_codigo(codigo_op)
        rows = sorted(
            (
                dict(row) for row in self.catalog_operations
                if row["codigo_op"] == code and row.get("inspecao_qualidade")
            ),
            key=lambda row: (int(row.get("ordem") or 0), int(row.get("id") or 0)),
        )
        if not rows:
            return None
        operation = rows[0]
        link = next((row for row in self.ops if row["codigo_op"] == code), None)
        if not operation.get("quantidade"):
            operation["quantidade"] = (
                (link or {}).get("quantidade_atual")
                or (link or {}).get("quantidade_original")
                or 1
            )
        return operation

    def buscar_operacao_produtiva_anterior(self, codigo_op, ordem_inspecao):
        code = limpa_codigo(codigo_op)
        rows = sorted(
            (
                dict(row) for row in self.catalog_operations
                if row["codigo_op"] == code
                and row.get("ativo", True)
                and not row.get("marco_terminal")
                and not row.get("inspecao_qualidade")
                and int(row.get("ordem") or 0) < int(ordem_inspecao)
            ),
            key=lambda row: (int(row.get("ordem") or 0), int(row.get("id") or 0)),
            reverse=True,
        )
        return rows[0] if rows else None

    def buscar_op_planejada(self, codigo_op):
        code = limpa_codigo(codigo_op)
        row = next((item for item in self.ops if item["codigo_op"] == code), None)
        if row is None and any(
            item["codigo_op"] == code for item in self.catalog_operations
        ):
            row = {"codigo_op": code}
        return dict(row) if row else None

    def buscar_ultima_inspecao(self, codigo_op):
        code = limpa_codigo(codigo_op)
        row = next(
            (
                item for item in reversed(self.quality_inspections)
                if limpa_codigo(item["codigo_op"]) == code
            ),
            None,
        )
        return dict(row) if row else None

    def dispensar_inspecao_qualidade(self, **valores):
        """Sessão em estado terminal DISPENSADA: a inspeção NÃO aconteceu."""

        registro = {
            "id": self._id("quality_inspections"),
            "codigo_op": limpa_codigo(valores.get("codigo_op")),
            "catalogo_operacao_id": valores.get("catalogo_operacao_id"),
            "apontamento_id": None,
            "numero_operacao": str(valores.get("numero_operacao") or "").strip(),
            "produto_codigo": str(valores.get("produto_codigo") or "").strip(),
            "produto_descricao": valores.get("produto_descricao"),
            "tipo_setor": str(valores.get("tipo_setor") or "").strip(),
            "tipo_setor_origem": str(valores.get("tipo_setor_origem") or "").strip()
            or None,
            "codigo_recurso": str(valores.get("codigo_recurso") or "").strip(),
            "quantidade_total": max(1, int(valores.get("quantidade_total") or 1)),
            "template_id": None,
            "template_revisao": None,
            "status": "DISPENSADA",
            "operador": str(valores.get("operador") or "Operador").strip(),
            "iniciada_em": valores.get("dispensada_em"),
            "finalizada_em": valores.get("dispensada_em"),
            "dispensa_motivo": valores.get("motivo"),
            "dispensa_autorizada_por": valores.get("autorizada_por"),
            "dispensa_cracha": valores.get("cracha"),
        }
        self.quality_inspections.append(registro)
        return dict(registro)

    def buscar_dispensa_inspecao(self, codigo_op, numero_operacao=None):
        code = limpa_codigo(codigo_op)
        return next(
            (
                dict(row) for row in reversed(self.quality_inspections)
                if limpa_codigo(row.get("codigo_op")) == code
                and row.get("status") == "DISPENSADA"
                and (
                    not numero_operacao
                    or str(row.get("numero_operacao") or "") == str(numero_operacao)
                )
            ),
            None,
        )

    def listar_pausas_automaticas(self, *, tipo_setor=None, somente_ativas=True):
        linhas = [dict(row) for row in self.automatic_pauses]
        if somente_ativas:
            linhas = [row for row in linhas if row.get("ativo")]
        if tipo_setor:
            alvo = str(tipo_setor).strip().casefold()
            linhas = [
                row for row in linhas
                if str(row.get("tipo_setor") or "").strip().casefold() == alvo
            ]
        return sorted(
            linhas,
            key=lambda row: (
                str(row.get("tipo_setor") or ""),
                int(row.get("ordem") or 0),
                str(row.get("hora_inicio")),
                int(row.get("id") or 0),
            ),
        )

    def salvar_pausa_automatica(
        self, *, tipo_setor, nome, hora_inicio, hora_fim,
        ativo=True, ordem=1, pausa_id=None, operador=None,
    ):
        setor = str(tipo_setor or "").strip()
        rotulo = str(nome or "").strip()
        if not setor or not rotulo:
            raise ValueError("Setor e nome da pausa são obrigatórios.")
        if hora_inicio == hora_fim:
            raise ValueError("A pausa precisa de horário inicial e final distintos.")
        registro = None
        if pausa_id is not None:
            registro = next(
                (row for row in self.automatic_pauses if row["id"] == pausa_id), None
            )
            if registro is None:
                return None
        else:
            registro = next(
                (
                    row for row in self.automatic_pauses
                    if str(row["tipo_setor"]).casefold() == setor.casefold()
                    and row["nome"] == rotulo
                    and row["hora_inicio"] == hora_inicio
                ),
                None,
            )
        if registro is None:
            registro = {"id": max((row["id"] for row in self.automatic_pauses), default=0) + 1}
            self.automatic_pauses.append(registro)
        registro.update({
            "tipo_setor": setor, "nome": rotulo, "hora_inicio": hora_inicio,
            "hora_fim": hora_fim, "ativo": bool(ativo), "ordem": int(ordem or 1),
            "atualizado_por": operador, "atualizado_em": datetime.now(),
        })
        return dict(registro)

    def remover_pausa_automatica(self, pausa_id):
        antes = len(self.automatic_pauses)
        self.automatic_pauses = [
            row for row in self.automatic_pauses if row["id"] != pausa_id
        ]
        return len(self.automatic_pauses) < antes

    def listar_ops_elegiveis_inspecao(self, *, limite=200):
        result = []
        for code in sorted({row["codigo_op"] for row in self.catalog_operations}):
            inspection = self.buscar_operacao_inspecao(code)
            if inspection is None:
                continue
            # Inspeção dispensada sai da fila sem nunca ter sido executada.
            if self.buscar_dispensa_inspecao(code):
                continue
            anteriores = [
                row for row in self.catalog_operations
                if row["codigo_op"] == code
                and row.get("ativo", True)
                and not row.get("marco_terminal")
                and int(row.get("ordem") or 0) < int(inspection.get("ordem") or 0)
            ]
            concluidas = sum(
                1 for row in anteriores
                if any(
                    item.get("catalogo_operacao_id") == row.get("id")
                    and item.get("status") == "Finalizado"
                    for item in self.appointments
                )
            )
            if concluidas != len(anteriores):
                continue
            execucao = next(
                (
                    row for row in reversed(self.appointments)
                    if row.get("catalogo_operacao_id") == inspection.get("id")
                ),
                None,
            )
            if (execucao or {}).get("status") == "Finalizado":
                continue
            if any(
                row.get("op") == code
                and row.get("retorno_retrabalho_qualidade")
                and row.get("status")
                in {"Aguardando", "Em processo", "Parada", "Setup", "Retrabalho"}
                for row in self.appointments
            ):
                continue
            planejada = int(inspection.get("quantidade") or 0)
            aprovada = int((execucao or {}).get("quantidade_boa") or 0)
            saldo = max(planejada - aprovada, 0)
            if saldo <= 0:
                continue
            sessao = next(
                (
                    row for row in reversed(self.quality_inspections)
                    if limpa_codigo(row["codigo_op"]) == code
                    and row["numero_operacao"] == inspection.get("numero_operacao")
                    and row["status"] == "EM_INSPECAO"
                ),
                None,
            )
            registradas = sum(
                1 for row in self.quality_pieces
                if sessao and row["inspecao_id"] == sessao["id"]
            )
            # Mesma regra do repositório real: o setor dono da inspeção é o da
            # última etapa apontável antes dela.
            origem = next(
                (
                    row for row in sorted(
                        anteriores,
                        key=lambda item: (int(item.get("ordem") or 0), int(item.get("id") or 0)),
                        reverse=True,
                    )
                    if str(row.get("tipo_setor") or "").strip()
                    and not row.get("inspecao_qualidade")
                ),
                None,
            )
            result.append({
                "catalogo_operacao_id": inspection.get("id"),
                "tipo_setor_origem": (origem or {}).get("tipo_setor"),
                "codigo_recurso_origem": (origem or {}).get("codigo_recurso"),
                "codigo_op": code,
                "numero_operacao": inspection.get("numero_operacao"),
                "codigo_recurso": inspection.get("codigo_recurso"),
                "descricao_operacao": inspection.get("descricao_operacao"),
                "produto_codigo": inspection.get("produto_codigo"),
                "produto_descricao": inspection.get("produto_descricao"),
                "quantidade": saldo,
                "quantidade_planejada": planejada,
                "quantidade_aprovada": aprovada,
                "status_apontamento": (execucao or {}).get("status"),
                "data_liberacao": inspection.get("data_liberacao"),
                "inicio_planejado": inspection.get("inicio_planejado"),
                "recurso_nome": inspection.get("recurso_nome"),
                "inspecao_id": (sessao or {}).get("id"),
                "inspecao_status": (sessao or {}).get("status"),
                "pecas_registradas": registradas,
            })
        return result[:limite]

    def buscar_template_qualidade(self, produto_codigo, *, somente_ativas=True):
        produto = str(produto_codigo or "").strip()
        template = next(
            (row for row in self.quality_templates if row["produto_codigo"] == produto),
            None,
        )
        if template is None:
            return None
        item = dict(template)
        cotas = [
            dict(row) for row in self.quality_dimensions
            if row["template_id"] == template["id"]
            and (row.get("ativo", True) or not somente_ativas)
        ]
        item["cotas"] = sorted(
            cotas, key=lambda row: (row.get("ordem") or 0, row["sequencia"])
        )
        return item

    def salvar_template_qualidade(
        self, produto_codigo, cotas, *, produto_descricao=None, usuario_id=None,
        usuario_nome="", agora=None, nova_revisao=False,
    ):
        produto = str(produto_codigo or "").strip()
        instante = agora or datetime.now().replace(microsecond=0)
        template = next(
            (row for row in self.quality_templates if row["produto_codigo"] == produto),
            None,
        )
        if template is None:
            template = {
                "id": self._id("quality_template"),
                "produto_codigo": produto,
                "produto_descricao": produto_descricao,
                "revisao": 1,
                "ativo": True,
                "criado_por": usuario_id,
                "criado_por_nome": usuario_nome or "Operador",
                "atualizado_por": usuario_id,
                "atualizado_por_nome": usuario_nome or "Operador",
                "criado_em": instante,
                "atualizado_em": instante,
            }
            self.quality_templates.append(template)
        else:
            template["revisao"] += 1 if nova_revisao else 0
            template["atualizado_por"] = usuario_id
            template["atualizado_por_nome"] = usuario_nome or "Operador"
            template["atualizado_em"] = instante
        informadas = set()
        for ordem, cota in enumerate(cotas or (), start=1):
            sequencia = int(cota.get("sequencia") or ordem)
            informadas.add(sequencia)
            existente = next(
                (
                    row for row in self.quality_dimensions
                    if row["template_id"] == template["id"]
                    and row["sequencia"] == sequencia
                ),
                None,
            )
            valores = {
                "descricao": cota.get("descricao"),
                "padrao": str(cota.get("padrao") or "").strip(),
                "unidade": cota.get("unidade"),
                "ordem": ordem,
                "ativo": True,
                "atualizado_em": instante,
            }
            if existente is None:
                self.quality_dimensions.append({
                    "id": self._id("quality_dimension"),
                    "template_id": template["id"],
                    "sequencia": sequencia,
                    "criado_em": instante,
                    **valores,
                })
            else:
                existente.update(valores)
        for row in self.quality_dimensions:
            if row["template_id"] == template["id"] and row["sequencia"] not in informadas:
                row["ativo"] = False
        return self.buscar_template_qualidade(produto)

    def abrir_inspecao_qualidade(self, **valores):
        codigo = limpa_codigo(valores.get("codigo_op"))
        numero = str(valores.get("numero_operacao") or "").strip()
        if any(
            limpa_codigo(row["codigo_op"]) == codigo
            and row["numero_operacao"] == numero
            and row["status"] == "EM_INSPECAO"
            for row in self.quality_inspections
        ):
            return None
        row = {
            "id": self._id("quality_inspection"),
            "codigo_op": codigo,
            "catalogo_operacao_id": valores.get("catalogo_operacao_id"),
            "apontamento_id": valores.get("apontamento_id"),
            "numero_operacao": numero,
            "produto_codigo": str(valores.get("produto_codigo") or "").strip(),
            "produto_descricao": valores.get("produto_descricao"),
            "tipo_setor": str(valores.get("tipo_setor") or "").strip(),
            "tipo_setor_origem": str(valores.get("tipo_setor_origem") or "").strip()
            or None,
            "codigo_recurso": str(valores.get("codigo_recurso") or "").strip(),
            "quantidade_total": int(valores.get("quantidade_total") or 1),
            "template_id": valores.get("template_id"),
            "template_revisao": valores.get("template_revisao"),
            "status": "EM_INSPECAO",
            "operador": str(valores.get("operador") or "Operador").strip(),
            "iniciada_em": valores.get("iniciada_em")
            or datetime.now().replace(microsecond=0),
            "finalizada_em": None,
        }
        self.quality_inspections.append(row)
        return dict(row)

    def _quality_session(self, inspecao_id):
        return next(
            (row for row in self.quality_inspections if row["id"] == int(inspecao_id)),
            None,
        )

    def buscar_inspecao_qualidade(self, inspecao_id):
        row = self._quality_session(inspecao_id)
        return dict(row) if row else None

    def buscar_inspecao_aberta(self, codigo_op, numero_operacao):
        codigo = limpa_codigo(codigo_op)
        numero = str(numero_operacao or "").strip()
        row = next(
            (
                item for item in reversed(self.quality_inspections)
                if limpa_codigo(item["codigo_op"]) == codigo
                and item["numero_operacao"] == numero
                and item["status"] == "EM_INSPECAO"
            ),
            None,
        )
        return dict(row) if row else None

    def concluir_inspecao_qualidade(self, inspecao_id, *, finalizada_em=None):
        row = self._quality_session(inspecao_id)
        if row is None or row["status"] != "EM_INSPECAO":
            return None
        row["status"] = "CONCLUIDA"
        row["finalizada_em"] = finalizada_em or datetime.now().replace(microsecond=0)
        return dict(row)

    def vincular_apontamento_inspecao(self, inspecao_id, apontamento_id):
        row = self._quality_session(inspecao_id)
        if row is None:
            return None
        row["apontamento_id"] = apontamento_id
        return dict(row)

    def listar_pecas_inspecionadas(self, inspecao_id):
        rows = [
            dict(row) for row in self.quality_pieces
            if row["inspecao_id"] == int(inspecao_id)
        ]
        for row in rows:
            rnc = next(
                (item for item in self.quality_rnc if item["id"] == row.get("rnc_id")),
                None,
            )
            row["rnc_codigo"] = (rnc or {}).get("codigo")
        return sorted(rows, key=lambda row: row["numero_peca"])

    def registrar_peca_inspecionada(
        self, inspecao_id, *, numero_peca, resultado, possui_nao_conformidade,
        operador, cotas, rnc=None, operacao_retrabalho=None, registrada_em=None,
    ):
        sessao = self._quality_session(inspecao_id)
        if sessao is None or sessao["status"] != "EM_INSPECAO":
            return None
        if any(
            row["inspecao_id"] == int(inspecao_id)
            and row["numero_peca"] == int(numero_peca)
            for row in self.quality_pieces
        ):
            return None
        instante = registrada_em or datetime.now().replace(microsecond=0)
        rnc_row = None
        if rnc:
            rnc_row = {
                "id": self._id("quality_rnc"),
                "codigo": rnc.get("codigo"),
                "inspecao_id": int(inspecao_id),
                "numero_peca": int(numero_peca),
                "codigo_op": sessao["codigo_op"],
                "produto_codigo": sessao["produto_codigo"],
                "tipo_setor": sessao["tipo_setor"],
                "codigo_recurso": sessao["codigo_recurso"],
                "operador": operador,
                "motivo": rnc.get("motivo"),
                "observacao": rnc.get("observacao"),
                "registrada_em": instante,
            }
            self.quality_rnc.append(rnc_row)
        peca = {
            "id": self._id("quality_piece"),
            "inspecao_id": int(inspecao_id),
            "numero_peca": int(numero_peca),
            "resultado": str(resultado or "").strip().upper(),
            "possui_nao_conformidade": bool(possui_nao_conformidade),
            "rnc_id": (rnc_row or {}).get("id"),
            "operador": operador,
            "registrada_em": instante,
        }
        self.quality_pieces.append(peca)
        for cota in cotas or ():
            self.quality_measures.append({
                "id": self._id("quality_measure"),
                "peca_id": peca["id"],
                "cota_template_id": cota.get("cota_template_id"),
                "sequencia": int(cota.get("sequencia") or 0),
                "descricao_snapshot": cota.get("descricao"),
                "padrao_snapshot": cota.get("padrao"),
                "unidade_snapshot": cota.get("unidade"),
                "medida": cota.get("medida"),
                "status": cota.get("status"),
            })
        if peca["resultado"] == "RETRABALHO":
            anterior = dict(operacao_retrabalho or {})
            if not anterior:
                self.quality_pieces.remove(peca)
                return None
            retorno = next(
                (
                    row for row in self.appointments
                    if row.get("origem_retrabalho_inspecao_id") == int(inspecao_id)
                    and row.get("catalogo_operacao_id") == anterior.get("id")
                    and row.get("retorno_retrabalho_qualidade")
                    and row.get("status")
                    in {"Aguardando", "Em processo", "Parada", "Setup", "Retrabalho"}
                ),
                None,
            )
            if retorno is None:
                machine = resource_display_name(
                    anterior.get("codigo_recurso"), anterior.get("recurso_nome")
                )
                retorno = self.enfileirar_apontamento_operacional(
                    sessao["codigo_op"],
                    sessao.get("produto_codigo") or "",
                    None,
                    anterior.get("tipo_setor"),
                    machine,
                    operador,
                    quantidade=1,
                    data_entrada=instante,
                    operacao=anterior,
                )
                retorno = next(
                    row for row in self.appointments if row["id"] == retorno["id"]
                )
                retorno["retorno_retrabalho_qualidade"] = True
                retorno["origem_retrabalho_inspecao_id"] = int(inspecao_id)
            else:
                retorno["quantidade"] += 1
            peca["retrabalho_apontamento_id"] = retorno["id"]
        return {**peca, "rnc": rnc_row}

    def listar_resultados_cota(self, peca_id):
        return sorted(
            (
                dict(row) for row in self.quality_measures
                if row["peca_id"] == int(peca_id)
            ),
            key=lambda row: row["sequencia"],
        )

    def _setor_origem_inspecao(self, sessao):
        """Setor que produziu a peça de uma inspeção já aberta."""

        gravado = str((sessao or {}).get("tipo_setor_origem") or "").strip()
        if gravado:
            return gravado
        inspecao = next(
            (
                row for row in self.catalog_operations
                if row.get("id") == (sessao or {}).get("catalogo_operacao_id")
            ),
            None,
        )
        if inspecao is None:
            return None
        anteriores = [
            row for row in self.catalog_operations
            if row.get("codigo_op") == inspecao.get("codigo_op")
            and row.get("ativo", True)
            and not row.get("marco_terminal")
            and not row.get("inspecao_qualidade")
            and int(row.get("ordem") or 0) < int(inspecao.get("ordem") or 0)
            and str(row.get("tipo_setor") or "").strip()
        ]
        anteriores.sort(key=lambda item: (int(item.get("ordem") or 0), int(item.get("id") or 0)))
        return (anteriores[-1].get("tipo_setor") if anteriores else None)

    def resumo_qualidade(self, *, setor=None, setor_origem=None):
        pecas = list(self.quality_pieces)
        if setor:
            alvo = {
                row["id"] for row in self.quality_inspections
                if row["tipo_setor"].casefold() == str(setor).casefold()
            }
            pecas = [row for row in pecas if row["inspecao_id"] in alvo]
        if setor_origem:
            permitido = {
                row["id"] for row in self.quality_inspections
                if (self._setor_origem_inspecao(row) or "").casefold()
                in {"", str(setor_origem).casefold()}
            }
            pecas = [row for row in pecas if row["inspecao_id"] in permitido]
        return {
            "aguardando": 0,
            "aprovadas": sum(1 for row in pecas if row["resultado"] == "APROVADA"),
            "retrabalho": sum(1 for row in pecas if row["resultado"] == "RETRABALHO"),
            "refugo": sum(1 for row in pecas if row["resultado"] == "REFUGO"),
        }

    def contar_pendentes_inspecao(self):
        return sum(
            max(
                int(row.get("quantidade") or 0) - int(row.get("pecas_registradas") or 0),
                0,
            )
            for row in self.listar_ops_elegiveis_inspecao(limite=1000)
        )

    def listar_historico_qualidade(
        self, *, setor=None, setor_origem=None, inicio=None, fim=None, op=None,
        produto=None, recurso=None, resultado=None, limite=200, deslocamento=0,
    ):
        rows = []
        for peca in self.quality_pieces:
            sessao = self._quality_session(peca["inspecao_id"])
            if sessao is None:
                continue
            if setor and sessao["tipo_setor"].casefold() != str(setor).casefold():
                continue
            origem = self._setor_origem_inspecao(sessao)
            if setor_origem and origem and origem.casefold() != str(setor_origem).casefold():
                continue
            if op and not sessao["codigo_op"].upper().startswith(str(op).upper()):
                continue
            if produto and not sessao["produto_codigo"].upper().startswith(
                str(produto).upper()
            ):
                continue
            if recurso and sessao["codigo_recurso"].casefold() != str(recurso).casefold():
                continue
            if resultado and peca["resultado"] != str(resultado).upper():
                continue
            if inicio and peca["registrada_em"] < inicio:
                continue
            if fim and peca["registrada_em"] > fim:
                continue
            rnc = next(
                (item for item in self.quality_rnc if item["id"] == peca.get("rnc_id")),
                None,
            )
            rows.append({
                "peca_id": peca["id"],
                "numero_peca": peca["numero_peca"],
                "resultado": peca["resultado"],
                "registrada_em": peca["registrada_em"],
                "operador": peca["operador"],
                "possui_nao_conformidade": peca["possui_nao_conformidade"],
                "rnc_codigo": (rnc or {}).get("codigo"),
                "rnc_motivo": (rnc or {}).get("motivo"),
                "inspecao_id": sessao["id"],
                "codigo_op": sessao["codigo_op"],
                "numero_operacao": sessao["numero_operacao"],
                "produto_codigo": sessao["produto_codigo"],
                "produto_descricao": sessao["produto_descricao"],
                "codigo_recurso": sessao["codigo_recurso"],
                "tipo_setor": sessao["tipo_setor"],
                "quantidade_total": sessao["quantidade_total"],
            })
        rows.sort(key=lambda row: (row["registrada_em"], row["peca_id"]), reverse=True)
        return rows[deslocamento:deslocamento + limite]

    def buscar_desenho_produto(self, produto_codigo):
        produto = str(produto_codigo or "").strip()
        rows = [
            dict(row) for row in self.quality_drawings
            if row["produto_codigo"] == produto and row.get("ativo", True)
        ]
        if not rows:
            return None
        return max(rows, key=lambda row: (row["versao"], row["id"]))

    def registrar_desenho_produto(self, **valores):
        produto = str(valores.get("produto_codigo") or "").strip()
        versao = max(
            (
                row["versao"] for row in self.quality_drawings
                if row["produto_codigo"] == produto
            ),
            default=0,
        ) + 1
        row = {
            "id": self._id("quality_drawing"),
            "produto_codigo": produto,
            "versao": versao,
            "filename": valores.get("filename"),
            "storage_path": valores.get("storage_path"),
            "content_type": valores.get("content_type") or "application/pdf",
            "size_bytes": int(valores.get("size_bytes") or 0),
            "paginas": valores.get("paginas"),
            "enviado_por": valores.get("enviado_por"),
            "enviado_por_nome": valores.get("enviado_por_nome") or "Sistema",
            "enviado_em": valores.get("enviado_em")
            or datetime.now().replace(microsecond=0),
            "ativo": True,
        }
        self.quality_drawings.append(row)
        return dict(row)
