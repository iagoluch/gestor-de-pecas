"""Contrato de estados do novo apontamento por setor.

Este módulo não contém cadastros de OP, operação, produto ou motivo. Ele apenas
define a ordem válida do fluxo que será persistido após a importação dos dados
operacionais para o PostgreSQL.
"""

from dataclasses import dataclass
from datetime import datetime
import logging

from app.core.resource_mapping import (
    RESOURCE_CONFIRMATION_EXEMPT_SECTORS,
    resource_display_name,
    station_matches_route,
)
from app.core.normalization import limpa_codigo
from app.core.operator_sectors import sector_display_label
from app.core.quality import inspection_step_auto_skipped, sector_has_quality
from mes.domain import (
    EventCategory,
    ManufacturingRules,
    OperatorAction,
    OperatorState,
    explain_invalid_transition,
    operator_state_from_status,
    resolve_operator_action,
    validate_transition,
)
from mes.domain.manufacturing_rules import LOW_PRIORITY_STOP_REASONS
from mes.services.operator_participation import (
    OperatorParticipationService,
    sincronizar_participacoes,
)
from mes.domain.first_piece import (
    FIRST_PIECE_CONFORMING,
    PRODUCTION_SCRAP_OCCURRENCE,
    evaluate_first_piece_gate,
    first_piece_applies,
    first_piece_gate_is_structured,
    sector_has_setup,
)
from mes.services.first_piece import FirstPieceService
from mes.services.internal_alerts import InternalAlertService
from mes.services.resource_state import ResourceStateService

# OP-05/OP-06 (auditoria de UI 24/09/2026): a resposta fala a intenção do
# operador, não o código da ação ("Retornar registrado com sucesso.").
_MENSAGEM_POR_ACAO = {
    "Início": "Produção iniciada.",
    "Retomar": "Produção retomada.",
    "Retornar": "Setup encerrado. Produção retomada.",
}
_MENSAGEM_POR_ESTADO = {
    OperatorState.STOPPED: "Parada registrada.",
    OperatorState.SETUP: "Setup iniciado.",
    OperatorState.REWORK: "Retrabalho iniciado.",
}


def _mensagem_sucesso(action, target, codigo, boas, refugos):
    if target == OperatorState.FINISHED:
        return f"OP {codigo} finalizada: {boas} peça(s) boa(s), {refugos} refugo(s)."
    return (
        _MENSAGEM_POR_ESTADO.get(target)
        or _MENSAGEM_POR_ACAO.get(str(getattr(action, "value", action)))
        or f"{action} registrado."
    )


@dataclass(frozen=True)
class OperatorFlowResult:
    ok: bool
    message: str
    code: str = ""
    data: dict | None = None


class OperatorFlowService:
    """Orquestra o posto do operador sem acoplar regra ao frontend Web."""

    def __init__(self, db, operador, now_func=None):
        self.db = db
        self.operador = str(operador or "Operador").strip() or "Operador"
        self._now = now_func or datetime.now
        # Wave 5: o portão da primeira peça é regra de negócio e vive no seu
        # próprio caso de uso. Aqui ele é apenas consultado — nenhuma cópia da
        # regra é escrita neste arquivo nem no React.
        self._first_piece = FirstPieceService(db, self.operador, now_func=self._now)
        self._alertas = InternalAlertService(db, self.operador, now_func=self._now)
        # Wave 5.1: tempo-pessoa. Grandeza distinta do tempo da OP e do tempo
        # físico do recurso; por isso um serviço próprio sobre a fonte canônica
        # `participacoes_operador`.
        self._participacoes = OperatorParticipationService(db, now_func=self._now)

    def listar_operacoes(self, op, setor, recurso=None):
        codigo = limpa_codigo(op)
        complete_loader = getattr(self.db, "listar_roteiro_completo_op", None)
        source_rows = (
            complete_loader(codigo)
            if callable(complete_loader)
            else self.db.listar_operacoes_para_op(codigo)
        )
        rows = [dict(row) for row in source_rows]
        if not rows:
            return []

        progress_loader = getattr(self.db, "listar_apontamentos_por_op", None)
        progress = list(progress_loader(codigo) or []) if callable(progress_loader) else []
        finalized_ids = {
            row.get("catalogo_operacao_id")
            for row in progress
            if row.get("status") == "Finalizado" and row.get("catalogo_operacao_id") is not None
        }
        finalized_ids.update(
            row.get("id")
            for row in rows
            if row.get("corte_concluido") and row.get("id") is not None
        )

        # Setor produtivo que antecede cada etapa. Precisa vir antes de
        # ``finalized_ids``: é ele que decide (a) quem executa a INSPECAO
        # herdada quando o setor não possui Qualidade implantada, e (b) se a
        # etapa INSPECAO da Caldeiraria é concluída sozinha pelo Gestor (ver
        # abaixo) — nos dois casos o critério é o setor de quem trabalhou na
        # operação real anterior, não o setor (vazio) da própria INSPECAO.
        setor_anterior = {}
        recurso_anterior = {}
        ultimo_setor = None
        ultimo_recurso = None
        for index, row in enumerate(rows):
            setor_anterior[index] = ultimo_setor
            recurso_anterior[index] = ultimo_recurso
            if row.get("tipo_setor") and not row.get("marco_terminal"):
                ultimo_setor = row.get("tipo_setor")
                ultimo_recurso = row.get("codigo_recurso") or row.get("recurso")

        # A etapa "INSPECAO"/"INSPECAO QUALIDADE" do roteiro da Caldeiraria
        # não é mais um processo real da fábrica (substituída pela
        # conferência da primeira peça — decisão do usuário, 16/09/2026): o
        # Gestor a trata como sempre concluída, sem apontamento nenhum e sem
        # produção fictícia, para não travar o avanço da OP. Solda e Pintura
        # ficam de fora — o processo delas continua diferente (apontada pelo
        # posto anterior só para contar o tempo, `inspecao_sem_checklist`
        # abaixo), e nada muda na Qualidade real (cotas, RNC, primeira peça,
        # fila do inspetor) para nenhum setor.
        finalized_ids.update(
            row.get("id")
            for index, row in enumerate(rows)
            if row.get("inspecao_qualidade")
            and row.get("id") is not None
            and inspection_step_auto_skipped(setor_anterior.get(index))
        )
        active_ids = {
            row.get("catalogo_operacao_id")
            for row in progress
            if row.get("status")
            in {"Aguardando", "Em processo", "Parada", "Setup", "Retrabalho"}
            and row.get("catalogo_operacao_id") is not None
        }
        route_index_by_id = {
            row.get("id"): index
            for index, row in enumerate(rows)
            if row.get("id") is not None
        }
        override_indices = [
            route_index_by_id[row.get("catalogo_operacao_id")]
            for row in progress
            if row.get("status") == "Finalizado"
            and row.get("etapa_anterior_pendente_confirmada")
            and row.get("catalogo_operacao_id") in route_index_by_id
        ]
        override_boundary = max(override_indices, default=-1)
        current_index = next(
            (
                index for index, row in enumerate(rows)
                if row.get("id") in active_ids
            ),
            None,
        )
        if current_index is None:
            current_index = next(
                (
                    index for index, row in enumerate(rows)
                    if index > override_boundary
                    if row.get("id") not in finalized_ids
                    and not row.get("marco_terminal")
                ),
                None,
            )
        # O marco terminal (99 - FINALIZADA) não é etapa de trabalho: ele nasce
        # com ``ativo = FALSE``, não tem recurso apontável e fica fora de toda
        # consulta canônica do roteiro (``marco_terminal IS FALSE``), que deriva
        # o marco da **última operação produtiva**. Por isso ele nunca vira
        # etapa atual: concluída a última etapa real, a OP já alcançou o marco,
        # e ele fica no roteiro apenas como leitura. Sem isso o posto era
        # empurrado para uma etapa em que nenhum apontamento pode existir e o
        # Finalizar não tinha saída.
        roteiro_concluido = all(
            row.get("id") in finalized_ids
            for row in rows
            if not row.get("marco_terminal")
        )

        # Wave 5 — portão da primeira peça. Uma única leitura por OP: projetar
        # o portão etapa a etapa com consulta individual transformaria abrir
        # uma OP em N consultas ao banco.
        first_piece_loader = getattr(self.db, "listar_primeiras_pecas_da_op", None)
        first_piece_rows = (
            list(first_piece_loader(codigo) or ())
            if callable(first_piece_loader)
            else []
        )
        first_piece_by_operation = {
            row.get("catalogo_operacao_id"): dict(row)
            for row in first_piece_rows
            if row.get("catalogo_operacao_id") is not None
        }
        setup_disponivel = sector_has_setup(setor)

        for index, row in enumerate(rows):
            operation_progress = next(
                (
                    item
                    for item in reversed(progress)
                    if self._corresponde_operacao(item, row)
                ),
                None,
            )
            planned = int(
                (operation_progress or {}).get("quantidade")
                or row.get("quantidade")
                or 0
            )
            registered_good = int(
                (operation_progress or {}).get("quantidade_boa") or 0
            )
            registered_scrap = int(
                (operation_progress or {}).get("quantidade_refugo") or 0
            )
            row["quantidade_planejada"] = planned
            row["quantidade_boa_registrada"] = registered_good
            row["quantidade_refugo_registrada"] = registered_scrap
            row["quantidade_atendida"] = ManufacturingRules.attended_quantity(
                registered_good,
                registered_scrap,
            )
            balance = ManufacturingRules.quantity_remaining(
                planned,
                registered_good,
                registered_scrap,
            )
            row["saldo_quantidade"] = balance
            # Nome legado preservado no contrato durante a transição da UI.
            row["saldo_quantidade_boa"] = balance
            row["etapa_anterior_pendente_confirmada"] = bool(
                (operation_progress or {}).get("etapa_anterior_pendente_confirmada")
            )
            row["operational_status"] = (operation_progress or {}).get("status")
            if current_index is not None and index == current_index:
                row["visual_status"] = "current"
            elif row.get("id") in finalized_ids or (
                row.get("marco_terminal") and roteiro_concluido
            ):
                row["visual_status"] = "done"
            else:
                row["visual_status"] = "pending"
            row["visual_current"] = current_index is not None and index == current_index
            # Regra transitória do fluxo oficial: Solda e Pintura ainda não
            # possuem inspeção de qualidade própria. Quando o roteiro chega na
            # INSPECAO desses setores, o posto que executou a etapa anterior
            # aponta a etapa só para contar o tempo e seguir com a OP — sem
            # checklist dimensional da Caldeiraria e sem sessão de inspeção.
            setor_herdado = setor_anterior.get(index)
            inspecao_sem_qualidade = bool(
                row.get("inspecao_qualidade")
                and setor_herdado
                and not sector_has_quality(setor_herdado)
            )
            setor_efetivo = setor_herdado if inspecao_sem_qualidade else row.get("tipo_setor")
            recurso_efetivo = (
                recurso_anterior.get(index)
                if inspecao_sem_qualidade
                else (row.get("codigo_recurso") or row.get("recurso"))
            )
            # O pertencimento do recurso precisa vir da mesma linha do recurso:
            # quando a INSPECAO é herdada, ``recurso_efetivo`` é o recurso da
            # etapa anterior, e usar o ``recurso_tipo_setor`` da linha da
            # INSPECAO (``INSPEC``, sem setor) tornava o posto inelegível para a
            # própria etapa que ele acabou de executar.
            recurso_setor_efetivo = (
                setor_herdado if inspecao_sem_qualidade else row.get("recurso_tipo_setor")
            )
            row["inspecao_sem_checklist"] = inspecao_sem_qualidade
            # Decisão do usuário, 21/09/2026: a etapa INSPECAO da Caldeiraria
            # (Dobra/Usinagem/Serra) continua concluída sozinha no backend —
            # nada muda no roteiro real — mas deixa de aparecer no roteiro
            # visual do operador, que só mostrava um item morto (sempre
            # "Concluída", nunca selecionável). Solda/Pintura continuam
            # aparecendo: lá a INSPECAO é apontada de verdade pelo posto
            # anterior (`inspecao_sem_checklist`).
            row["inspecao_auto_concluida"] = bool(
                row.get("inspecao_qualidade")
                and setor_herdado
                and inspection_step_auto_skipped(setor_herdado)
            )
            row["setor_efetivo"] = setor_efetivo
            row["recurso_efetivo"] = recurso_efetivo
            pointable = bool(
                row.get("ativo", True) or inspecao_sem_qualidade
            ) and not row.get("marco_terminal") and (
                not row.get("inspecao_qualidade") or inspecao_sem_qualidade
            )
            sector_compatible = (
                str(setor_efetivo or "").casefold() == str(setor or "").casefold()
            )
            resource_compatible = bool(
                recurso
                and pointable
                and station_matches_route(
                    setor,
                    recurso,
                    recurso_efetivo,
                    resource_sector=recurso_setor_efetivo,
                )
            )
            row["pointable"] = pointable
            row["sector_compatible"] = sector_compatible
            row["resource_compatible"] = resource_compatible
            # Elegibilidade do posto: o recurso/setor pode executar a operação.
            # É a barreira dura do domínio — nenhuma confirmação a dispensa.
            station_eligible = bool(
                pointable and sector_compatible and resource_compatible
            )
            row["station_eligible"] = station_eligible
            # No Workbench normal, o roteiro completo permite selecionar toda
            # etapa ainda não concluída, inclusive INSPECAO ou uma etapa
            # pertencente a outro recurso. A seleção fora da atual continua
            # sujeita à confirmação canônica e ao crachá autorizado quando
            # houver divergência. Corte e Destaque mantêm seus fluxos
            # especializados e continuam limitados à elegibilidade do posto.
            #
            # O marco terminal fica fora dessa abertura: ele não é apontável
            # (``pointable`` já é falso) e oferecê-lo no seletor só produzia um
            # beco sem saída — era a única linha com ``pode_finalizar`` quando o
            # portão da primeira peça segurava a etapa real, e o operador
            # acabava "finalizando" a OP por ele, sem apontamento nenhum.
            normal_workbench = str(setor or "").casefold() not in {
                "corte",
                "destaque",
            }
            row["selectable"] = bool(
                row["visual_status"] != "done"
                and not row.get("marco_terminal")
                and (normal_workbench or station_eligible)
            )
            # Etapa fora da atual reabre a regra canônica de exceção
            # (crachá autorizado) já existente no projeto; ela não é liberada
            # silenciosamente nem bloqueada de forma absoluta.
            row["requires_confirmation"] = bool(
                row["selectable"] and not row["visual_current"]
            )
            row["actionable"] = bool(station_eligible and row["visual_current"])
            # O botão Finalizar do posto não pode inventar a própria regra: ele
            # lê `pode_finalizar`, que o backend calcula com o mesmo domínio
            # usado para recusar a finalização prematura.
            registro_primeira_peca = first_piece_by_operation.get(row.get("id"))
            aplicavel_primeira_peca = first_piece_applies(setor_efetivo, row)
            gate = evaluate_first_piece_gate(
                aplicavel=aplicavel_primeira_peca,
                status=(registro_primeira_peca or {}).get("status") or "PENDENTE",
                peca_produzida=bool(
                    (registro_primeira_peca or {}).get("peca_produzida_em")
                ),
                setup_obrigatorio=bool(
                    (registro_primeira_peca or {}).get("setup_obrigatorio")
                    if registro_primeira_peca
                    else (aplicavel_primeira_peca and setup_disponivel)
                ),
                setup_registrado=bool(
                    (registro_primeira_peca or {}).get("setup_registrado_em")
                ),
                bloqueio_ativo=bool(
                    (registro_primeira_peca or {}).get("bloqueio_ativo")
                ),
                # Wave 6B — a tela usa este sinal para saber que o Finalizar
                # desta etapa passa pelo popup Setup/Qualidade. Ele é derivado
                # do setor, não é um estado novo e não é decidido no React.
                gate_estruturado=first_piece_gate_is_structured(setor_efetivo, row),
            )
            row["primeira_peca"] = gate.como_dicionario()
            row["primeira_peca_id"] = (registro_primeira_peca or {}).get("id")
            row["pode_finalizar"] = bool(row["selectable"] and gate.liberado)
            # O Finalizar desta etapa ainda passa pela conferência da primeira
            # peça: o posto sabe de antemão que o botão abrirá o popup (ou
            # pedirá o Setup) em vez de encerrar a operação direto.
            row["exige_gate_primeira_peca"] = bool(
                gate.gate_estruturado and not gate.liberado
            )
        return rows

    def listar_motivos_parada(self, setor=None):
        """Catálogo PCFactory de motivos de parada com a classificação central.

        Os nomes e grupos continuam sendo os do cadastro corporativo. O Gestor
        apenas acrescenta ``classificacao`` e ``cor``, para que nenhuma tela
        reconstrua o mapeamento planejado/não planejado por grupo ou por texto.
        Paradas que o sistema já lança sozinho (ex.: fim de turno) e paradas
        específicas de outro setor ficam de fora — ver
        ``ManufacturingRules.stop_reason_selectable_by_operator``.
        """

        loader = getattr(self.db, "listar_status_recursos", None)
        if not callable(loader):
            return []
        rows = []
        for raw in loader(somente_paradas=True) or []:
            row = dict(raw)
            if not ManufacturingRules.stop_reason_selectable_by_operator(
                row.get("codigo"), setor
            ):
                continue
            classification = ManufacturingRules.classify_stop(status_row=row)
            row["classificacao"] = classification.value
            row["cor"] = ManufacturingRules.stop_classification_ui_token(classification)
            rows.append(row)
        rows.sort(key=lambda r: r.get("codigo") in LOW_PRIORITY_STOP_REASONS)
        return rows

    def listar_operadores(self):
        loader = getattr(self.db, "listar_operadores_apontamento", None)
        if not callable(loader):
            return []
        return list(loader(somente_ativos=True) or [])

    def _status_recurso(self, codigo):
        finder = getattr(self.db, "buscar_status_recurso", None)
        if not callable(finder):
            return None
        row = finder(str(codigo or "").strip())
        if not row or not row.get("habilitado") or row.get("oculto"):
            return None
        return dict(row)

    def _status_especial(self, action):
        loader = getattr(self.db, "listar_status_recursos", None)
        if not callable(loader):
            return None
        filters = {"setup": True} if action == "Setup" else {"retrabalho": True}
        rows = list(loader(**filters) or [])
        return dict(rows[0]) if rows else None

    def estado_recurso(self, recurso):
        """Estado físico atual do recurso, como a tela do Corte já expõe."""

        state = ResourceStateService(self.db, self.operador).atual(recurso)
        return dict(state) if state else None

    def registrar_parada_recurso(self, *, setor, recurso, motivo_codigo, comentario=None):
        """Registra parada física manual sem exigir OP, tarefa ou nesting ativo."""

        status = self._status_recurso(motivo_codigo)
        if (
            status is None
            or status.get("setup")
            or status.get("retrabalho")
            or status.get("grupo_codigo") == "0001"
            or status.get("retorno_automatico")
            or not ManufacturingRules.stop_reason_selectable_by_operator(
                status.get("codigo"), setor
            )
        ):
            return OperatorFlowResult(
                False,
                "Selecione um motivo de parada válido do catálogo.",
                "motivo_parada_invalido",
            )
        if status.get("requer_comentario") and not str(comentario or "").strip():
            return OperatorFlowResult(
                False,
                "O motivo selecionado exige comentário.",
                "comentario_obrigatorio",
            )
        state_service = ResourceStateService(self.db, self.operador)
        current = state_service.atual(recurso)
        if current and str(current.get("categoria") or "") == EventCategory.DOWNTIME.value:
            return OperatorFlowResult(
                False,
                "O recurso já está parado.",
                "recurso_ja_parado",
                dict(current),
            )
        code = str(status.get("codigo") or "").strip()
        reason = " - ".join(
            value
            for value in (code, str(status.get("nome") or "").strip())
            if value
        )
        row = state_service.registrar_estado(
            recurso,
            EventCategory.DOWNTIME.value,
            tipo_setor=setor,
            codigo_status_recurso=code,
            motivo=reason,
            causa_raiz=status.get("causa_raiz"),
            comentario=str(comentario or "").strip() or None,
            planejado=False,
            automatico=False,
            tipo_interrupcao="manual",
            data_hora=self._now(),
        )
        if not row:
            return OperatorFlowResult(
                False,
                "Não foi possível registrar a parada do recurso.",
                "estado_recurso_alterado",
            )
        return OperatorFlowResult(
            True,
            "Parada registrada com sucesso.",
            "parada_recurso_sem_op",
            dict(row),
        )

    def retomar_recurso_sem_op(self, *, setor, recurso):
        """Encerra a parada sem OP e devolve o recurso ao estado sem demanda.

        Simétrico de ``registrar_parada_recurso``: sem OP não existe apontamento
        para retomar, então a retomada é do próprio recurso. O destino é
        A persistência continua usando ``fila`` por compatibilidade de schema;
        a regra central projeta toda fila sem OP como recurso sem demanda.
        """

        state_service = ResourceStateService(self.db, self.operador)
        current = state_service.atual(recurso)
        category = str((current or {}).get("categoria") or "")
        if category != EventCategory.DOWNTIME.value:
            return OperatorFlowResult(
                False,
                "O recurso não está parado.",
                "recurso_nao_parado",
                dict(current) if current else None,
            )
        if str(current.get("op") or "").strip():
            return OperatorFlowResult(
                False,
                "Esta parada pertence a uma OP. Carregue a OP e retome o apontamento.",
                "parada_vinculada_op",
                dict(current),
            )
        row = state_service.registrar_estado(
            recurso,
            EventCategory.QUEUE.value,
            tipo_setor=setor,
            motivo="Retomada após parada sem OP",
            automatico=False,
            data_hora=self._now(),
        )
        if not row:
            return OperatorFlowResult(
                False,
                "Não foi possível retomar o recurso.",
                "estado_recurso_alterado",
            )
        return OperatorFlowResult(
            True,
            "Recurso retomado com sucesso.",
            "retomada_recurso_sem_op",
            dict(row),
        )

    def iniciar_atividade_sem_op(self, *, setor, recurso):
        """Abre atividade sem OP: trabalho real do posto fora de qualquer OP.

        É produtivo (``ManufacturingRules.is_productive``) e pertence ao
        recurso, não a um apontamento: por isso não exige OP, tarefa nem
        nesting. O tipo da atividade é decidido pelo setor, nunca pelo
        operador.
        """

        state_service = ResourceStateService(self.db, self.operador)
        current = state_service.atual(recurso)
        category = str((current or {}).get("categoria") or "")
        if category == EventCategory.ACTIVITY_WITHOUT_OP.value:
            return OperatorFlowResult(
                False,
                "Já existe uma atividade sem OP em andamento neste recurso.",
                "atividade_sem_op_em_andamento",
                dict(current),
            )
        if category == EventCategory.DOWNTIME.value:
            return OperatorFlowResult(
                False,
                "O recurso está parado. Retome antes de iniciar a atividade.",
                "recurso_parado",
                dict(current),
            )
        if category in {
            EventCategory.PRODUCTION.value,
            EventCategory.SETUP.value,
            EventCategory.REWORK.value,
        }:
            return OperatorFlowResult(
                False,
                "O recurso está executando uma OP. Finalize o apontamento antes de iniciar a atividade.",
                "recurso_em_execucao",
                dict(current),
            )
        activity_kind = ManufacturingRules.activity_kind_for_sector(setor)
        row = state_service.registrar_atividade_sem_op(
            recurso,
            tipo_setor=setor,
            tipo_atividade=activity_kind,
            motivo=ManufacturingRules.activity_display_label(activity_kind),
            data_hora=self._now(),
        )
        if not row:
            return OperatorFlowResult(
                False,
                "Não foi possível iniciar a atividade sem OP.",
                "estado_recurso_alterado",
            )
        return OperatorFlowResult(
            True,
            "Atividade sem OP iniciada com sucesso.",
            "inicio_atividade_sem_op",
            dict(row),
        )

    def finalizar_atividade_sem_op(self, *, setor, recurso):
        """Encerra a atividade sem OP e devolve o recurso ao estado sem demanda.

        Simétrico de ``retomar_recurso_sem_op``: o destino persistido é ``fila``
        e a regra central projeta toda fila sem OP como recurso sem demanda.
        """

        state_service = ResourceStateService(self.db, self.operador)
        current = state_service.atual(recurso)
        category = str((current or {}).get("categoria") or "")
        if category != EventCategory.ACTIVITY_WITHOUT_OP.value:
            return OperatorFlowResult(
                False,
                "Não existe atividade sem OP em andamento neste recurso.",
                "atividade_sem_op_inexistente",
                dict(current) if current else None,
            )
        row = state_service.registrar_estado(
            recurso,
            EventCategory.QUEUE.value,
            tipo_setor=setor,
            motivo="Fim da atividade sem OP",
            automatico=False,
            data_hora=self._now(),
        )
        if not row:
            return OperatorFlowResult(
                False,
                "Não foi possível finalizar a atividade sem OP.",
                "estado_recurso_alterado",
            )
        return OperatorFlowResult(
            True,
            "Atividade sem OP finalizada com sucesso.",
            "fim_atividade_sem_op",
            dict(row),
        )

    @staticmethod
    def _corresponde_operacao(row, operacao):
        """Confirma a identidade da operação sem tratar campo nulo como curinga."""

        operacao = dict(operacao or {})
        operation_id = operacao.get("id") or operacao.get("catalogo_operacao_id")
        row_operation_id = row.get("catalogo_operacao_id")
        if operation_id is not None and row_operation_id is not None:
            return row_operation_id == operation_id

        numero = str(
            operacao.get("numero_operacao") or operacao.get("codigo") or ""
        ).strip()
        row_numero = str(row.get("numero_operacao") or "").strip()
        return bool(numero and row_numero and numero == row_numero)

    def _buscar_ativo(self, op, setor, recurso, operacao=None):
        codigo = limpa_codigo(op)
        for row in self.db.listar_apontamentos_operacionais(
            setor,
            maquina=recurso,
            somente_ativos=True,
        ):
            if limpa_codigo(row.get("op")) != codigo:
                continue
            if self._corresponde_operacao(row, operacao):
                return row
        return None

    def _buscar_conflito_ativo(self, op, setor, recurso, operacao=None):
        """Localiza uma execução da OP que não pertence ao contexto selecionado."""

        codigo = limpa_codigo(op)
        for row in self.db.listar_apontamentos_operacionais(setor, somente_ativos=True):
            if limpa_codigo(row.get("op")) != codigo:
                continue
            same_resource = str(row.get("maquina") or "").casefold() == str(
                recurso or ""
            ).casefold()
            if same_resource and self._corresponde_operacao(row, operacao):
                continue
            return row
        return None

    def _operacao_finalizada(self, op, operacao):
        """Impede reabertura de etapa que já alcançou o estado terminal."""

        loader = getattr(self.db, "listar_apontamentos_por_op", None)
        if not callable(loader):
            return None
        for row in loader(limpa_codigo(op)) or ():
            if row.get("status") != "Finalizado":
                continue
            if self._corresponde_operacao(row, operacao):
                return dict(row)
        return None

    @staticmethod
    def _operation_key(row):
        row = dict(row or {})
        operation_id = row.get("id") or row.get("catalogo_operacao_id")
        if operation_id is not None:
            return ("id", operation_id)
        number = str(row.get("numero_operacao") or row.get("codigo") or "").strip()
        return ("numero", number) if number else ("", "")

    def _etapa_anterior_pendente(self, op, operacao):
        """Retorna a primeira etapa que ainda bloqueia a operação selecionada.

        A projeção de próximas operações da persistência é a fonte preferida,
        pois ela já conhece as regras especiais de Corte/Nesting. O fallback
        usa o progresso do roteiro apenas para manter compatibilidade com
        implementações de banco mais simples.
        """

        route_loader = getattr(self.db, "listar_operacoes_para_op", None)
        if not callable(route_loader):
            return None
        codigo = limpa_codigo(op)
        route = [dict(row) for row in (route_loader(codigo) or [])]
        selected_key = self._operation_key(operacao)
        selected_index = next(
            (
                index
                for index, row in enumerate(route)
                if self._operation_key(row) == selected_key
            ),
            None,
        )
        if selected_index in (None, 0):
            return None

        projected_loader = getattr(self.db, "listar_proximas_operacoes_roteiro", None)
        if callable(projected_loader):
            projected = [
                dict(row)
                for row in (projected_loader() or [])
                if limpa_codigo(row.get("codigo_op")) == codigo
            ]
            if any(self._operation_key(row) == selected_key for row in projected):
                return None
            if projected:
                projected_key = self._operation_key(projected[0])
                projected_index = next(
                    (
                        index
                        for index, row in enumerate(route)
                        if self._operation_key(row) == projected_key
                    ),
                    None,
                )
                if projected_index is not None and projected_index < selected_index:
                    return projected[0]

        progress_loader = getattr(self.db, "listar_apontamentos_por_op", None)
        progress = list(progress_loader(codigo) or []) if callable(progress_loader) else []
        finalized = {
            row.get("catalogo_operacao_id")
            for row in progress
            if row.get("status") == "Finalizado"
            and row.get("catalogo_operacao_id") is not None
        }
        for previous in route[:selected_index]:
            operation_id = previous.get("id") or previous.get("catalogo_operacao_id")
            if operation_id is not None and operation_id in finalized:
                continue
            return previous
        return None

    def recurso_em_uso(self, setor, recurso):
        """Retorna a execução que ocupa fisicamente um recurso, se houver."""

        rows = self.db.listar_apontamentos_operacionais(
            setor,
            maquina=recurso,
            somente_ativos=True,
        )
        return next(
            (
                dict(row)
                for row in rows
                if row.get("status") in {
                    "Em processo", "Parada", "Setup", "Retrabalho"
                }
            ),
            None,
        )

    def executar(
        self,
        action,
        *,
        op,
        setor,
        recurso,
        operacao,
        motivo=None,
        motivo_codigo=None,
        comentario=None,
        pecas_boas=0,
        refugo=0,
        retrabalho_quantidade=0,
        lote=None,
        motivo_refugo=None,
        causa_raiz=None,
        tipo_setup=None,
        operador_id=None,
        operadores_cracha=None,
        confirmar_recurso_divergente=False,
        confirmar_etapa_anterior_pendente=False,
        recurso_exclusivo=False,
        cracha_refugo=None,
    ):
        try:
            requested_action = OperatorAction(action)
        except (TypeError, ValueError):
            return OperatorFlowResult(False, "Ação de apontamento inválida.", "acao_invalida")
        # A lista de setores sem Setup vive em ``mes.domain.first_piece``; este
        # gate repetia os nomes à mão e por isso ficava para trás sempre que a
        # fábrica ganhava um setor (a Wave 6F quintuplicou a frente de Solda).
        if action == "Setup" and not sector_has_setup(setor):
            return OperatorFlowResult(
                False,
                f"Setup não está disponível para {setor}.",
                "setup_indisponivel_setor",
            )
        codigo = limpa_codigo(op)
        if not codigo or not operacao:
            return OperatorFlowResult(
                False,
                "Informe a OP e selecione uma operação antes de apontar.",
                "dados_incompletos",
            )
        etapa_atual_nome = ""
        if str(setor or "").casefold() != "qualidade":
            route = self.listar_operacoes(codigo, setor, recurso)
            selected_key = self._operation_key(operacao)
            selected_route = next(
                (row for row in route if self._operation_key(row) == selected_key),
                None,
            )
            current = next((row for row in route if row.get("visual_current")), None)
            etapa_atual_nome = " - ".join(
                value
                for value in (
                    str((current or {}).get("numero_operacao") or "").strip(),
                    str((current or {}).get("descricao_operacao") or "").strip(),
                )
                if value
            )
            # Wave 2: a etapa fora da atual voltou a ser apontável, porém só
            # quando o posto realmente executa aquela operação e mediante a
            # confirmação canônica de exceção. A elegibilidade de
            # recurso/setor continua sendo um bloqueio absoluto.
            if selected_route is not None and not selected_route.get("selectable"):
                current_name = etapa_atual_nome or "não identificada"
                if selected_route.get("visual_status") == "done":
                    return OperatorFlowResult(
                        False,
                        "Esta etapa já foi concluída e não pode ser apontada novamente.",
                        "operacao_finalizada",
                        dict(selected_route),
                    )
                return OperatorFlowResult(
                    False,
                    f"Etapa atual: {current_name}. Esta operação não está disponível para {setor} neste posto.",
                    "operacao_nao_apontavel",
                    {"etapa_atual": current_name},
                )

        crachas = operadores_cracha
        if crachas is None:
            crachas = operador_id if isinstance(operador_id, (list, tuple, set)) else [operador_id]
        crachas = list(
            dict.fromkeys(
                str(cracha or "").strip()
                for cracha in (crachas or ())
                if str(cracha or "").strip()
            )
        )
        # Inspeção sem checklist herda o recurso da etapa produtiva anterior:
        # quem aponta é o posto que acabou de executar, e o roteiro registra
        # INSPEC apenas como identidade da etapa.
        route_code = str(
            operacao.get("recurso_efetivo")
            if operacao.get("inspecao_sem_checklist")
            else (operacao.get("codigo_recurso") or operacao.get("recurso") or "")
        ).strip()
        route_name = resource_display_name(route_code, operacao.get("recurso_nome"))
        divergent_resource = bool(
            route_code
            and not station_matches_route(
                setor,
                recurso,
                route_code,
                resource_sector=operacao.get("recurso_tipo_setor"),
            )
        )
        # Wave 5.1 — o setor de origem do roteiro é preservado ao lado do setor
        # onde a OP foi realmente apontada. O evento histórico não é reescrito:
        # a exibição passa a ser "Atual (Original)".
        route_sector = str(
            operacao.get("tipo_setor") or operacao.get("recurso_tipo_setor") or ""
        ).strip()
        divergent_sector = bool(
            route_sector
            and str(setor or "").strip().casefold() != route_sector.casefold()
        )

        status_recurso = None
        if requested_action == OperatorAction.STOP:
            status_recurso = self._status_recurso(motivo_codigo)
            if (
                status_recurso is None
                or status_recurso.get("setup")
                or status_recurso.get("retrabalho")
                or status_recurso.get("grupo_codigo") == "0001"
                or status_recurso.get("retorno_automatico")
            ):
                return OperatorFlowResult(
                    False,
                    "Selecione um motivo de parada válido do catálogo.",
                    "motivo_parada_invalido",
                )
        elif requested_action in {OperatorAction.SETUP, OperatorAction.REWORK}:
            status_recurso = self._status_especial(action)
            if status_recurso is None:
                return OperatorFlowResult(
                    False,
                    f"Status de {action.lower()} não disponível no catálogo.",
                    "status_especial_indisponivel",
                )
        if status_recurso is not None:
            motivo_codigo = str(status_recurso.get("codigo") or "").strip()
            motivo = " - ".join(
                value
                for value in (
                    motivo_codigo,
                    str(status_recurso.get("nome") or "").strip(),
                )
                if value
            )
            if status_recurso.get("requer_comentario") and not str(comentario or "").strip():
                return OperatorFlowResult(
                    False,
                    "O motivo selecionado exige comentário.",
                    "comentario_obrigatorio",
                )

        atual = self._buscar_ativo(codigo, setor, recurso, operacao)
        ocupacao = self.recurso_em_uso(setor, recurso)
        if atual is None and ocupacao is not None:
            return OperatorFlowResult(
                False,
                "Este recurso já possui um apontamento ativo. Finalize ou altere o estado atual antes de iniciar outro.",
                "operator_resource_occupied",
                dict(ocupacao),
            )
        conflito = self._buscar_conflito_ativo(codigo, setor, recurso, operacao)
        if atual is None and conflito is not None:
            operacao_ativa = " - ".join(
                value
                for value in (
                    str(conflito.get("numero_operacao") or "").strip(),
                    str(conflito.get("descricao_operacao") or "").strip(),
                )
                if value
            ) or "não identificada"
            recurso_ativo = str(conflito.get("maquina") or "").strip() or "outro recurso"
            return OperatorFlowResult(
                False,
                (
                    f"A OP já possui a operação {operacao_ativa} em execução "
                    f"no recurso {recurso_ativo}. Selecione essa operação para continuar."
                ),
                "operacao_ativa_diferente",
                dict(conflito),
            )
        if atual is None and requested_action == OperatorAction.SETUP:
            return OperatorFlowResult(
                False,
                "Inicie a OP antes de apontar o Setup.",
                "setup_exige_inicio",
                {"op": codigo, "estado_atual": OperatorState.QUEUED.value},
            )
        target = resolve_operator_action(requested_action, OperatorState.QUEUED)
        if atual is None and target in {
            OperatorState.PRODUCTION,
            OperatorState.STOPPED,
            OperatorState.SETUP,
            OperatorState.REWORK,
        }:
            finalizada = self._operacao_finalizada(codigo, operacao)
            if finalizada is not None:
                return OperatorFlowResult(
                    False,
                    "Esta etapa já foi concluída e não pode ser apontada novamente.",
                    "operacao_finalizada",
                    finalizada,
                )
            etapa_pendente = self._etapa_anterior_pendente(codigo, operacao)
            if etapa_pendente is not None and not confirmar_etapa_anterior_pendente:
                pending_number = str(
                    etapa_pendente.get("numero_operacao")
                    or etapa_pendente.get("codigo")
                    or ""
                ).strip()
                pending_name = str(
                    etapa_pendente.get("descricao_operacao")
                    or etapa_pendente.get("nome")
                    or ""
                ).strip()
                selected_number = str(
                    operacao.get("numero_operacao") or operacao.get("codigo") or ""
                ).strip()
                selected_name = str(
                    operacao.get("descricao_operacao") or operacao.get("nome") or ""
                ).strip()
                return OperatorFlowResult(
                    False,
                    "A etapa anterior do roteiro ainda não foi concluída. Confirme a exceção com um crachá autorizado.",
                    "confirmacao_etapa_anterior_obrigatoria",
                    {
                        "motivo_confirmacao": "etapa_anterior_pendente",
                        "op": codigo,
                        "etapa_atual": etapa_atual_nome or "Não identificada",
                        "etapa_pendente_operacao": " - ".join(
                            value for value in (pending_number, pending_name) if value
                        ) or "Não identificada",
                        "etapa_pendente_setor": str(
                            etapa_pendente.get("tipo_setor") or ""
                        ).strip() or "Não identificado",
                        "etapa_pendente_recurso": str(
                            etapa_pendente.get("codigo_recurso")
                            or etapa_pendente.get("recurso")
                            or ""
                        ).strip() or "Não identificado",
                        "operacao_selecionada": " - ".join(
                            value for value in (selected_number, selected_name) if value
                        ) or "Não identificada",
                        # A autorização da etapa anterior também pode cobrir
                        # o recurso divergente da próxima etapa, evitando dois
                        # pop-ups para a mesma exceção operacional.
                        "confirmar_recurso_divergente": divergent_resource,
                        "operacao": dict(operacao),
                    },
                )
            sector_exempt_from_resource_confirmation = (
                str(setor or "").strip().casefold() in RESOURCE_CONFIRMATION_EXEMPT_SECTORS
            )
            if (
                divergent_resource
                and not confirmar_recurso_divergente
                and not sector_exempt_from_resource_confirmation
            ):
                return OperatorFlowResult(
                    False,
                    (
                        f"O roteiro exige {route_code} ({route_name}), mas o posto aberto é "
                        f"{recurso}. Confirme a exceção com um crachá autorizado."
                    ),
                    "confirmacao_recurso_obrigatoria",
                    {
                        "op": codigo,
                        "etapa_atual": etapa_atual_nome or "Não identificada",
                        "recurso_roteiro_codigo": route_code,
                        "recurso_roteiro_nome": route_name,
                        "recurso_apontado": str(recurso or "").strip(),
                        "operacao": dict(operacao),
                    },
                )
            requires_authorization = bool(
                (
                    divergent_resource
                    and confirmar_recurso_divergente
                    and not sector_exempt_from_resource_confirmation
                )
                or (etapa_pendente is not None and confirmar_etapa_anterior_pendente)
            )
            if requires_authorization:
                if not crachas:
                    return OperatorFlowResult(
                        False,
                        "Informe um crachá para autorizar esta exceção operacional.",
                        "cracha_autorizacao_obrigatorio",
                    )
                finder = getattr(self.db, "buscar_operador_apontamento_detalhado", None)
                if not callable(finder):
                    return OperatorFlowResult(
                        False,
                        "Não foi possível validar o responsável pela exceção operacional.",
                        "autorizacao_indisponivel",
                    )
                operadores = [(cracha, finder(cracha)) for cracha in crachas]
                ausentes = [
                    cracha
                    for cracha, operador in operadores
                    if not operador or not operador.get("ativo")
                ]
                if ausentes:
                    return OperatorFlowResult(
                        False,
                        f"Crachá não cadastrado ou inativo: {', '.join(ausentes)}.",
                        "cracha_invalido",
                    )
                autorizado = next(
                    (
                        (cracha, operador)
                        for cracha, operador in operadores
                        if operador.get("autorizador_retrabalho")
                    ),
                    None,
                )
                if autorizado is None:
                    return OperatorFlowResult(
                        False,
                        "A exceção operacional exige o crachá de um responsável autorizado.",
                        "cracha_autorizacao_nao_autorizado",
                    )
            # Wave 6B — o portão é avaliado antes de enfileirar: um Iniciar
            # recusado pelo popup não pode deixar apontamento algum para trás.
            recusa_gate = self._recusa_primeira_peca(
                target, codigo, setor, operacao, etapa_atual_nome
            )
            if recusa_gate is not None:
                return recusa_gate
            quantidade_planejada = operacao.get("quantidade")
            try:
                quantidade_planejada = int(quantidade_planejada)
            except (TypeError, ValueError):
                quantidade_planejada = 0
            if quantidade_planejada <= 0:
                return OperatorFlowResult(
                    False,
                    "A quantidade planejada desta OP não está disponível. Atualize o planejamento antes de iniciar.",
                    "quantidade_planejada_indisponivel",
                )
            contexto = self.db.buscar_op_por_codigo(codigo)
            atual = self.db.enfileirar_apontamento_operacional(
                codigo,
                operacao.get("produto_codigo") or operacao.get("produto_descricao") or "",
                contexto.get("tarefa_id") if contexto else None,
                setor,
                recurso,
                self.operador,
                quantidade=quantidade_planejada,
                operacao=operacao,
                data_entrada=self._now(),
                etapa_anterior_pendente_confirmada=bool(
                    etapa_pendente is not None
                    and confirmar_etapa_anterior_pendente
                ),
            )
            if atual is None:
                atual = self._buscar_ativo(codigo, setor, recurso, operacao)
        if atual is None:
            return OperatorFlowResult(
                False,
                "A OP não possui apontamento ativo neste posto. Inicie a produção primeiro.",
                "apontamento_inexistente",
            )

        current = operator_state_from_status(atual.get("status"))
        target = resolve_operator_action(
            requested_action,
            current,
            atual.get("estado_retorno"),
        )
        if target is None:
            recusa = explain_invalid_transition(
                requested_action, current, atual.get("estado_retorno")
            )
            return OperatorFlowResult(
                False,
                recusa.message,
                recusa.code,
                {
                    "op": codigo,
                    "etapa_atual": etapa_atual_nome or "Não identificada",
                    **recusa.as_details(),
                },
            )

        # ------------------------------------------------------------------
        # Wave 5 — portão da primeira peça.
        #
        # Enquanto a primeira peça não estiver validada, a operação não volta a
        # produzir nem é finalizada. Setup, Parada e Retrabalho continuam
        # liberados de propósito: é com eles que o operador corrige a peça. A
        # regra vive em `mes/domain/first_piece.py`; aqui ela é consultada.
        # ------------------------------------------------------------------
        recusa_gate = self._recusa_primeira_peca(
            target, codigo, setor, operacao, etapa_atual_nome
        )
        if recusa_gate is not None:
            return recusa_gate

        try:
            boas = int(pecas_boas or 0)
            refugos = int(refugo or 0)
            retrabalhos = int(retrabalho_quantidade or 0)
        except (TypeError, ValueError):
            return OperatorFlowResult(
                False, "Peças boas e refugo devem ser números inteiros.", "quantidade_invalida"
            )
        if boas < 0 or refugos < 0 or retrabalhos < 0:
            return OperatorFlowResult(
                False, "Peças boas, refugo e retrabalho não podem ser negativos.", "quantidade_invalida"
            )
        # A INSPECAO herdada sem checklist (Solda/Pintura hoje — ver
        # `inspecao_sem_checklist` acima) é apontada pelo posto só para contar
        # o tempo e seguir a OP; ela não produz peça própria, quem produziu
        # foi a operação real anterior. Aceitar uma quantidade aqui duplicaria
        # a peça em qualquer totalizador que some por OP/recurso (o operador
        # tende a repetir o mesmo número já registrado na etapa anterior — o
        # cenário que soma 25+25 para um lote de 25 peças). A inspeção real
        # (setor com Qualidade, fila própria) não passa por aqui com esta
        # marca e continua registrando a quantidade normalmente.
        inspecao_marcador = bool((operacao or {}).get("inspecao_sem_checklist"))
        if inspecao_marcador:
            boas = 0
            refugos = 0
        if target == OperatorState.FINISHED:
            if not crachas:
                return OperatorFlowResult(
                    False,
                    "Informe ao menos um crachá de operador.",
                    "cracha_obrigatorio",
                )
            # O tempo bruto do Gestor é sempre gravado normalmente, mesmo
            # abaixo do mínimo: esta checagem só existe quando a integração
            # ativa exige uma duração mínima de segmento (atributo genérico
            # do banco; este serviço não sabe qual integração é nem por quê).
            minimo = getattr(self.db, "minimum_appointment_duration_seconds", None)
            if minimo:
                inicio_segmento = self.db.inicio_segmento_producao_apontamento(
                    atual["id"]
                )
                if inicio_segmento is not None:
                    decorrido = (self._now() - inicio_segmento).total_seconds()
                    if 0 <= decorrido < minimo:
                        faltam = max(1, int(minimo) - int(decorrido))
                        return OperatorFlowResult(
                            False,
                            f"Aguarde mais {faltam}s antes de finalizar: esta "
                            "operação ainda não atingiu a duração mínima "
                            "exigida.",
                            "duracao_minima_nao_atingida",
                            {"segundos_restantes": faltam},
                        )
            total_lote = boas + refugos
            boas_anteriores = int(atual.get("quantidade_boa") or 0)
            refugos_anteriores = int(atual.get("quantidade_refugo") or 0)
            previsto = int(atual.get("quantidade") or 0)
            quality_rework_only = bool(
                str(setor or "").casefold() == "qualidade"
                and retrabalhos > 0
            )
            atendimento_previo = ManufacturingRules.attended_quantity(
                boas_anteriores, refugos_anteriores
            )
            finalizacao_de_saldo_esgotado = atendimento_previo >= previsto
            if (
                total_lote <= 0
                and not quality_rework_only
                and not inspecao_marcador
                and not finalizacao_de_saldo_esgotado
            ):
                return OperatorFlowResult(
                    False,
                    "Informe ao menos uma peça boa ou um refugo.",
                    "quantidade_invalida",
                )
            quantidade_atendida = ManufacturingRules.attended_quantity(
                boas_anteriores + boas,
                refugos_anteriores + refugos,
            )
            if quantidade_atendida > previsto:
                return OperatorFlowResult(
                    False,
                    "A soma de peças boas e refugo excede o saldo previsto da OP.",
                    "quantidade_inconsistente",
                )
            finder = getattr(self.db, "buscar_operadores_apontamento", None)
            if callable(finder) and crachas:
                operadores = list(finder(crachas) or [])
                encontrados = {str(item.get("cracha") or "").strip() for item in operadores}
                ausentes = [cracha for cracha in crachas if cracha not in encontrados]
                if ausentes:
                    return OperatorFlowResult(
                        False,
                        f"Crachá não cadastrado ou inativo: {', '.join(ausentes)}.",
                        "cracha_invalido",
                    )
            if refugos > 0:
                recusa_refugo = self._autorizar_refugo(
                    op=codigo,
                    setor=setor,
                    recurso=recurso,
                    operacao=operacao,
                    quantidade=refugos,
                    cracha=cracha_refugo,
                    crachas_informados=crachas,
                )
                if recusa_refugo is not None:
                    return recusa_refugo

        payload = {
            "op": codigo,
            "operacao": operacao.get("numero_operacao") or operacao.get("codigo"),
            "recurso": recurso,
            "motivo_parada": motivo,
            "pecas_boas": boas,
            "refugo": refugos,
            "operador_id": operador_id,
            "operadores_cracha": crachas,
        }
        validation = validate_transition(current, target, payload)
        if not validation.ok:
            return OperatorFlowResult(
                False,
                validation.message,
                "transicao_invalida",
                {"campos_ausentes": validation.missing_fields},
            )
        try:
            row = self.db.transicionar_apontamento_operador(
                atual["id"],
                target.value,
                self.operador,
                motivo=motivo,
                comentario=comentario,
                codigo_status_recurso=motivo_codigo,
                quantidade_boa=boas,
                quantidade_refugo=refugos,
                quantidade_retrabalho=retrabalhos,
                lote=lote,
                motivo_refugo=motivo_refugo,
                causa_raiz=causa_raiz,
                tipo_setup=tipo_setup,
                operadores_cracha=crachas,
                recurso_roteiro_codigo=route_code or None,
                recurso_roteiro_nome=route_name or None,
                recurso_apontado=str(recurso or "").strip() or None,
                recurso_divergente=divergent_resource,
                setor_roteiro=route_sector or None,
                setor_divergente=divergent_sector,
                recurso_exclusivo=bool(recurso_exclusivo),
                data_hora=self._now(),
            )
        except ValueError as exc:
            return OperatorFlowResult(False, str(exc), "quantidade_invalida")
        if row is None:
            return OperatorFlowResult(
                False,
                "O estado da OP mudou. Atualize o posto e tente novamente.",
                "concorrencia",
            )
        if row.get("exclusive_resource_conflict"):
            return OperatorFlowResult(
                False,
                "Este recurso já possui um apontamento ativo. Finalize ou altere o estado atual antes de iniciar outro.",
                "operator_resource_occupied",
                row,
            )
        # Wave 5.1 — tempo-pessoa. O tempo da OP é o do apontamento e não é
        # dividido; cada crachá informado ganha a própria participação.
        sincronizar_participacoes(
            self._participacoes,
            apontamento=row,
            setor=setor,
            recurso=recurso,
            op=codigo,
            operacao=operacao,
            target=target,
            crachas=crachas,
        )
        self._efeitos_wave5(
            target=target,
            op=codigo,
            setor=setor,
            recurso=recurso,
            operacao=operacao,
            apontamento=row,
            boas=boas,
            refugos=refugos,
            retrabalhos=retrabalhos,
        )
        if target == OperatorState.FINISHED and row.get("finalizacao_parcial"):
            saldo = int(row.get("saldo_restante") or 0)
            return OperatorFlowResult(
                True,
                f"Apontamento parcial registrado. A OP permanece aberta com saldo de {saldo} peça(s).",
                "finalizacao_parcial",
                row,
            )
        return OperatorFlowResult(
            True, _mensagem_sucesso(action, target, codigo, boas, refugos), data=row
        )

    def _autorizar_refugo(
        self, *, op, setor, recurso, operacao, quantidade, cracha, crachas_informados
    ):
        """Refugo apontado exige o crachá do responsável designado.

        Descartar peça é decisão de responsável, não do posto — a mesma regra do
        retrabalho da primeira peça, com o mesmo cadastro de crachás
        (``autorizador_retrabalho``) e a mesma auditoria. Quando um dos crachás
        já informados na finalização pertence a um responsável autorizado, ele
        vale como a autorização e o operador não digita nada duas vezes.

        Devolve a recusa quando não houver autorização, ou ``None`` quando o
        refugo estiver autorizado (e já auditado).
        """

        finder = getattr(self.db, "buscar_operador_apontamento_detalhado", None)
        if not callable(finder):  # pragma: no cover - cadastro indisponível
            return None
        candidatos = [
            str(item or "").strip()
            for item in (str(cracha or "").strip(), *crachas_informados)
            if str(item or "").strip()
        ]
        autorizado = None
        for codigo_cracha in dict.fromkeys(candidatos):
            operador = finder(codigo_cracha)
            if (
                operador
                and operador.get("ativo")
                and operador.get("autorizador_retrabalho")
            ):
                autorizado = (codigo_cracha, operador)
                break
        contexto = dict(operacao or {})
        registrar = getattr(self.db, "registrar_autorizacao_primeira_peca", None)
        if callable(registrar):
            try:
                registrar(
                    primeira_peca_id=None,
                    codigo_op=op,
                    catalogo_operacao_id=contexto.get("id")
                    or contexto.get("catalogo_operacao_id"),
                    numero_operacao=contexto.get("numero_operacao")
                    or contexto.get("codigo"),
                    tipo_setor=setor,
                    codigo_recurso=contexto.get("codigo_recurso"),
                    recurso_apontado=recurso,
                    operador=self.operador,
                    ocorrencia=PRODUCTION_SCRAP_OCCURRENCE,
                    cracha=autorizado[0] if autorizado else str(cracha or "").strip(),
                    autorizado_por_nome=autorizado[1].get("nome") if autorizado else None,
                    decisao="AUTORIZADA" if autorizado else "RECUSADA",
                    motivo_recusa=None
                    if autorizado
                    else "Refugo sem crachá de responsável autorizado.",
                    estado_antes={"refugo": int(quantidade)},
                    estado_depois=None,
                    data_hora=self._now(),
                )
            except Exception:  # pragma: no cover - auditoria não bloqueia
                logging.exception("Falha ao auditar a autorização do refugo da OP %s.", op)
        if autorizado is not None:
            return None
        return OperatorFlowResult(
            False,
            "O refugo precisa do crachá de um responsável autorizado para ser "
            "registrado.",
            "refugo_autorizacao_obrigatoria",
            {"op": op, "refugo": int(quantidade)},
        )

    def _recusa_primeira_peca(self, target, codigo, setor, operacao, etapa_atual_nome):
        """Portão da primeira peça aplicado às transições que ele governa.

        O portão é do **Finalizar**: a operação não fecha antes de a primeira
        peça ser conferida e aprovada. Produzir nunca foi — e voltou a não ser —
        bloqueado por ele: em Dobra, Usinagem e Serra o operador dá Início,
        produz, aponta o Setup e só encontra o portão quando tenta finalizar.

        A única coisa que ainda impede voltar a produzir é o **bloqueio** do
        retrabalho da primeira peça (Wave 5), que espera o crachá do
        responsável. Setup, Parada e Retrabalho continuam liberados de
        propósito: é com eles que o operador prepara a máquina e corrige a peça.

        Nos setores com checklist estruturado, o código da recusa diz ao posto o
        que fazer: ``primeira_peca_setup_pendente`` pede o botão Setup e
        ``primeira_peca_gate_obrigatorio`` abre o popup Setup/Qualidade. Quem
        decide isso é o domínio, não a tela.
        """

        if target not in {OperatorState.PRODUCTION, OperatorState.FINISHED}:
            return None
        gate = self._first_piece.avaliar_finalizacao(
            op=codigo, setor=setor, operacao=operacao
        )
        if not gate.aplicavel:
            return None
        detalhes = {
            "op": codigo,
            "etapa_atual": etapa_atual_nome or "Não identificada",
            "primeira_peca": gate.como_dicionario(),
        }
        if gate.bloqueio_ativo:
            return OperatorFlowResult(False, gate.message, gate.code, detalhes)
        if target == OperatorState.FINISHED and not gate.liberado:
            return OperatorFlowResult(False, gate.message, gate.code, detalhes)
        return None

    # ------------------------------------------------------------------
    # Wave 5 — efeitos posteriores ao apontamento aceito
    # ------------------------------------------------------------------
    def _efeitos_wave5(
        self,
        *,
        target,
        op,
        setor,
        recurso,
        operacao,
        apontamento,
        boas,
        refugos,
        retrabalhos,
    ):
        """Abre a primeira peça, anota o Setup e registra os alertas internos.

        Nada aqui pode recusar um apontamento já aceito: o evento produtivo é
        canônico e não depende do aviso. Falha de alerta vira log, não erro do
        operador.
        """

        if not first_piece_applies(setor, operacao):
            return
        try:
            self._first_piece.garantir(
                op=op,
                setor=setor,
                recurso=recurso,
                operacao=operacao,
                apontamento_id=(apontamento or {}).get("id"),
            )
            if target == OperatorState.SETUP:
                self._first_piece.marcar_setup(op=op, operacao=operacao)
        except Exception:  # pragma: no cover - efeito colateral não bloqueia
            logging.exception("Falha ao manter a primeira peça da OP %s.", op)
        if target == OperatorState.REWORK:
            # Retrabalho depois da primeira peça aprovada é o caso do §8: o
            # fluxo continua e o que a Wave 5 exige é o evento com destinatário.
            self._alertar_retrabalho_posterior(
                op=op, setor=setor, recurso=recurso, operacao=operacao
            )
            return
        if target != OperatorState.FINISHED:
            return
        try:
            self._alertar_finalizacao(
                op=op,
                setor=setor,
                recurso=recurso,
                operacao=operacao,
                apontamento=apontamento,
                refugos=refugos,
                retrabalhos=retrabalhos,
            )
        except Exception:  # pragma: no cover - alerta não bloqueia produção
            logging.exception("Falha ao registrar alertas internos da OP %s.", op)

    def _alertar_retrabalho_posterior(self, *, op, setor, recurso, operacao):
        """Só alerta quando a primeira peça já estava aprovada.

        Retrabalho **da** primeira peça tem alerta próprio, com destinatário
        diferente e bloqueio da OP. Confundir os dois esconderia justamente a
        distinção que a Wave 5 pediu para comparar no relatório.
        """

        try:
            estado = self._first_piece.estado(
                op=op, setor=setor, recurso=recurso, operacao=operacao
            )
        except Exception:  # pragma: no cover
            logging.exception("Falha ao ler a primeira peça da OP %s.", op)
            return
        if str(estado.get("status") or "") != FIRST_PIECE_CONFORMING:
            return
        dados = dict(operacao or {})
        self._alertas.retrabalho_peca_posterior(
            {
                "codigo_op": op,
                "catalogo_operacao_id": dados.get("id")
                or dados.get("catalogo_operacao_id"),
                "numero_operacao": dados.get("numero_operacao") or dados.get("codigo"),
                "tipo_setor": setor,
                "codigo_recurso": dados.get("codigo_recurso") or dados.get("recurso"),
                "produto_codigo": dados.get("produto_codigo"),
            },
            quantidade=1,
        )

    def _alertar_finalizacao(
        self, *, op, setor, recurso, operacao, apontamento, refugos, retrabalhos
    ):
        """Refugo, reposição, nova OP e retrabalho posterior viram alerta interno."""

        dados = dict(operacao or {})
        contexto = {
            "codigo_op": op,
            "catalogo_operacao_id": dados.get("id") or dados.get("catalogo_operacao_id"),
            "numero_operacao": dados.get("numero_operacao") or dados.get("codigo"),
            "tipo_setor": setor,
            "codigo_recurso": dados.get("codigo_recurso") or dados.get("recurso"),
            "recurso_apontado": recurso,
            "produto_codigo": dados.get("produto_codigo"),
        }
        linha = dict(apontamento or {})
        planejado = int(linha.get("quantidade") or 0)
        boas_totais = int(linha.get("quantidade_boa") or 0)
        refugos_totais = int(linha.get("quantidade_refugo") or 0)
        saldo = ManufacturingRules.quantity_remaining(
            planejado, boas_totais, refugos_totais
        )

        if retrabalhos > 0:
            self._alertas.retrabalho_peca_posterior(contexto, quantidade=retrabalhos)
        if refugos > 0:
            self._alertas.refugo_registrado(contexto, quantidade=refugos)
        # "Aguardando reposição" é exatamente o estado em que o saldo fechou
        # mas o planejado não foi atendido com peça boa. A necessidade de nova
        # OP é o total de refugo dessa operação — e nenhuma OP é criada aqui.
        if saldo == 0 and refugos_totais > 0 and boas_totais < planejado:
            faltante = max(0, planejado - boas_totais)
            self._alertas.reposicao_necessaria(contexto, quantidade=faltante)
            self._alertas.nova_op_necessaria(contexto, quantidade=faltante)

    def listar_cartoes(self, setor, recurso):
        rows = self.db.listar_apontamentos_operacionais(
            setor, maquina=recurso, somente_ativos=True
        )
        queue = [self._card(row) for row in rows if row.get("status") == "Aguardando"]
        production = [self._card(row) for row in rows if row.get("status") != "Aguardando"]
        route_loader = getattr(self.db, "listar_proximas_operacoes_roteiro", None)
        if callable(route_loader):
            projected = list(route_loader(setor) or [])
            active_operations = {
                row.get("catalogo_operacao_id")
                for row in rows
                if row.get("catalogo_operacao_id") is not None
            }
            for operation in projected:
                operation_id = operation.get("id") or operation.get("catalogo_operacao_id")
                if operation_id in active_operations:
                    continue
                route_code = operation.get("codigo_recurso") or operation.get("recurso")
                if not station_matches_route(
                    setor,
                    recurso,
                    route_code,
                    resource_sector=operation.get("recurso_tipo_setor"),
                ):
                    continue
                virtual = {
                    **dict(operation),
                    "catalogo_operacao_id": operation_id,
                    "op": operation.get("codigo_op"),
                    "peca": operation.get("produto_codigo") or "",
                    "maquina": recurso,
                    "status": "Aguardando",
                    "virtual_queue": True,
                    "quantidade_boa": 0,
                    "quantidade_refugo": 0,
                }
                queue.append(self._card(virtual))
        queue.sort(
            key=lambda row: (
                str(row.get("op") or ""),
                str(row.get("numero_operacao") or row.get("operation") or ""),
            )
        )
        return {"queue": queue, "production": production}

    def listar_historico(
        self,
        setor,
        recurso,
        data_referencia=None,
        *,
        limite=None,
        deslocamento=0,
    ):
        return [
            self._card(row)
            for row in self.db.listar_historico_operador(
                setor,
                recurso,
                data_referencia,
                limite=limite,
                deslocamento=deslocamento,
            )
        ]

    def _card(self, row):
        row = dict(row or {})
        planned_quantity = int(row.get("quantidade") or row.get("qty") or 0)
        registered_good = int(
            row.get("quantidade_boa")
            if row.get("quantidade_boa") is not None
            else row.get("good") or 0
        )
        registered_scrap = int(
            row.get("quantidade_refugo")
            if row.get("quantidade_refugo") is not None
            else row.get("scrap") or 0
        )
        code = str(row.get("numero_operacao") or row.get("operation") or "").strip()
        description = str(row.get("descricao_operacao") or "").strip()
        operation = " - ".join(part for part in (code, description) if part)
        elapsed = row.get("elapsed")
        if not elapsed and row.get("data_inicio"):
            started = row.get("data_inicio")
            ended = row.get("data_fim") or self._now().replace(microsecond=0)
            if isinstance(started, datetime) and isinstance(ended, datetime):
                total = max(0, int((ended - started).total_seconds()))
                hours, remainder = divmod(total, 3600)
                minutes, seconds = divmod(remainder, 60)
                elapsed = (
                    f"{hours}h {minutes:02d}min {seconds:02d}s"
                    if hours
                    else f"{minutes}min {seconds:02d}s"
                )

        status_elapsed = ""
        stopped_since = None
        if row.get("status") == "Parada" and row.get("id") is not None:
            event_loader = getattr(self.db, "listar_eventos_apontamento_operador", None)
            if callable(event_loader):
                try:
                    events = list(event_loader(row.get("id")) or [])
                except Exception:
                    events = []
                last_stop = next(
                    (event for event in reversed(events) if str(event.get("estado") or "").casefold() == "parada"),
                    None,
                )
                started_stop = last_stop.get("data_hora") if last_stop else None
                if isinstance(started_stop, datetime):
                    stopped_since = started_stop
                    seconds_total = max(0, int((self._now().replace(microsecond=0) - started_stop).total_seconds()))
                    hours, remainder = divmod(seconds_total, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    status_elapsed = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        card = {
            **row,
            "operation": operation,
            "product": row.get("produto_codigo") or row.get("product") or row.get("peca") or "",
            "description": row.get("produto_descricao") or row.get("description") or row.get("peca") or "",
            "qty": row.get("quantidade") or row.get("qty") or 0,
            "good": row.get("quantidade_boa") if row.get("quantidade_boa") is not None else row.get("good"),
            "scrap": row.get("quantidade_refugo") if row.get("quantidade_refugo") is not None else row.get("scrap"),
            "attended": ManufacturingRules.attended_quantity(
                registered_good,
                registered_scrap,
            ),
            "balance": ManufacturingRules.quantity_remaining(
                planned_quantity,
                registered_good,
                registered_scrap,
            ),
            "last_updated_at": (
                row.get("data_fim")
                or row.get("data_inicio")
                or row.get("data_entrada")
            ),
            "elapsed": elapsed or "",
            # Wave 5.1 — apontamento em setor incorreto continua visível como
            # "Atual (Original)". O card não recalcula nada: recebe pronto.
            "setor_roteiro": row.get("setor_roteiro") or "",
            "setor_divergente": bool(row.get("setor_divergente")),
            "setor_exibicao": sector_display_label(
                row.get("tipo_setor"), row.get("setor_roteiro")
            ),
            "motivo_parada": row.get("motivo_parada") or row.get("motivo") or "",
            "status_elapsed": status_elapsed,
            "stopped_since": stopped_since,
            "finished": row.get("status") == "Finalizado",
        }
        if row.get("retorno_retrabalho_qualidade") and row.get("status") == "Aguardando":
            card["status"] = "Retrabalho"
            card["rework_return"] = True
        return card
