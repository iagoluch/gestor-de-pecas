"""Auditoria Analítica: um catálogo de tipos de relatório sobre as fontes já existentes.

Cada tipo só **projeta** uma fonte canônica (aqui, ``event_log`` via fachada);
nenhuma regra é recalculada. O que este módulo acrescenta ao contrato:

* ``as_of``: o instante de referência da consulta. Evento em aberto conta até
  ele; nada depois dele conta. É o mesmo relógio que
  ``listar_estados_recurso_periodo`` usa para cortar estados abertos
  (``datetime.now()`` sem microssegundos), limitado ao fim do período.
* ``estado``: distingue ``com_dados``, ``zero`` (há registros, mas a medida
  principal do tipo soma zero), ``sem_registros`` e ``indisponivel`` (a fonte
  não existe nesta instalação). ``erro`` é devolvido pela rota quando a
  consulta falha.
* ``campos``: rótulo de cada campo do registro; a tela (detalhe) e a
  exportação usam a mesma lista, então nenhum campo se perde.

Regra de período (tipos 01 e 02) — ver ``REGRA_PERIODO``.
"""

from __future__ import annotations

from datetime import datetime

REGRA_PERIODO = (
    "Entra todo evento que toca o período, mesmo que tenha começado antes ou termine depois. "
    "O tempo contado é só a parte dentro do período: começa no maior entre o início do evento e o "
    "início do período e termina no menor entre o fim do evento, o fim do período e o instante de "
    "referência (as_of). Evento ainda aberto aparece sem fim e conta até o as_of. "
    "Início e fim mostrados são os do evento inteiro (no tipo 02, os da atividade dentro do período)."
)

#: Campos comuns da barra de filtros (nome do parâmetro da API).
FILTROS_COMUNS = ("setor", "recurso", "op", "operador")

_CAMPOS_STATUS = (
    ("id", "ID do evento"),
    ("op", "OP"),
    ("operacao", "Operação"),
    ("recurso", "Recurso (código)"),
    ("recurso_nome", "Recurso"),
    ("setor", "Setor"),
    ("codigo_status", "Código do status"),
    ("descricao", "Status"),
    ("categoria", "Categoria"),
    ("classificacao", "Classificação da parada"),
    ("classe", "Classificação"),
    ("inicio", "Início"),
    ("fim", "Fim"),
    ("em_aberto", "Em aberto"),
    ("duracao_segundos", "Duração no período (s)"),
    ("operador", "Colaborador"),
    ("motivo", "Motivo"),
    ("comentario", "Comentário"),
    ("origem", "Origem"),
)

_CAMPOS_PRODUCAO = (
    ("apontamento_id", "ID do apontamento"),
    ("op", "OP"),
    ("tarefa", "Tarefa (Corte)"),
    ("plano", "Plano (Corte)"),
    ("produto", "Produto"),
    ("produto_descricao", "Descrição do produto"),
    ("operacao", "Operação"),
    ("descricao_operacao", "Descrição da operação"),
    ("setor", "Setor"),
    ("recurso", "Recurso"),
    ("colaborador", "Colaborador"),
    ("atividade", "Atividade"),
    ("inicio", "Início"),
    ("fim", "Fim"),
    ("tempo_real_segundos", "Tempo real no período (s)"),
    ("tempo_padrao_segundos", "Tempo padrão (s)"),
    ("tempo_padrao_fonte", "Fonte do tempo padrão"),
    ("status_apontamento", "Situação do apontamento"),
    ("quantidade_boa", "Boas"),
    ("quantidade_refugo", "Refugo"),
    ("quantidade_retrabalho", "Retrabalho"),
    ("inconsistencia", "Inconsistência"),
)

#: Grupos do seletor de tipo, na ordem em que aparecem.
GRUPOS = ("Produção e rastreio", "Paradas e tempos", "Qualidade", "Indicadores", "Dados e sistema")

#: Quem vê cada nível de permissão: a mesma guarda do módulo de origem.
PERMISSOES = ("gestao", "qualidade", "admin")


def _tipo(tipo_id, grupo, titulo, descricao, origem, campos, *, permissao="gestao",
          filtros_comuns=FILTROS_COMUNS, filtros_proprios=(), medida=None, somente_consulta=False):
    return {
        "id": tipo_id,
        "grupo": grupo,
        "titulo": titulo,
        "descricao": descricao,
        "origem": origem,
        "permissao": permissao,
        "somente_consulta": somente_consulta,
        "filtros_comuns": list(filtros_comuns),
        "filtros_proprios": list(filtros_proprios),
        "campos": [{"chave": key, "rotulo": label} for key, label in campos],
        # Campos cuja soma define o estado "zero" (há registro, a medida soma 0).
        "medida": list(medida or ()),
    }


_PROD, _PARADAS, _QUAL, _IND, _SIS = GRUPOS
_OP_PROD = ("setor", "recurso", "op", "operador")

TIPOS = {
    "01": _tipo(
        "01", _PROD, "Eventos de status",
        "Em que condição cada recurso esteve e por quanto tempo, produzindo ou parado.",
        "/auditoria/eventos-status", _CAMPOS_STATUS,
        filtros_proprios=("produto", "operacao", "evento_status", "evento_classe", "em_aberto"),
        medida=("duracao_segundos",),
    ),
    "02": _tipo(
        "02", _PROD, "Eventos de produção",
        "O que foi executado: OP, produto, operação, recurso e colaborador, com tempo real e quantidades.",
        "/auditoria/eventos-producao", _CAMPOS_PRODUCAO,
        filtros_proprios=("produto", "operacao"),
        medida=("tempo_real_segundos", "quantidade_boa", "quantidade_refugo", "quantidade_retrabalho"),
    ),
    "03": _tipo(
        "03", _PROD, "OPs e operações",
        "Cada operação de OP no período: planejado, real, quantidades, saldo e quem iniciou e terminou.",
        "/auditoria/apontamentos",
        (("apontamento_id", "ID do apontamento"), ("op", "OP"), ("produto", "Produto"), ("descricao", "Descrição"),
         ("operacao_atual", "Operação"), ("descricao_operacao", "Descrição da operação"), ("setor", "Setor"),
         ("recurso_planejado", "Recurso planejado"), ("recurso_real", "Recurso real"),
         ("recurso_divergente", "Recurso divergente"), ("status", "Situação"), ("inicio_real", "Início"),
         ("fim_real", "Fim"), ("operador_inicio", "Iniciou"), ("operador_fim", "Terminou"),
         ("quantidade_planejada", "Planejada"), ("quantidade_boa", "Boas"), ("refugo", "Refugo"),
         ("retrabalho", "Retrabalho"), ("quantidade_atendida", "Atendida (boas + refugo)"),
         ("saldo_quantidade", "Saldo"), ("progresso_percentual", "Progresso (%)"),
         ("prazo_entrega", "Prazo de entrega"), ("proxima_operacao", "Próxima operação")),
        filtros_proprios=("produto", "operacao"),
        medida=("quantidade_boa", "refugo", "retrabalho"),
    ),
    "13": _tipo(
        "13", _PROD, "Linha do tempo da OP",
        "Tudo o que aconteceu com uma OP, em ordem: início e fim de operação, eventos e quantidades.",
        "/rastreabilidade",
        (("timestamp", "Quando"), ("type", "Evento"), ("operation", "Operação"), ("resource", "Recurso"),
         ("status", "Situação"), ("reason", "Motivo ou descrição"), ("operator", "Colaborador"),
         ("source", "Origem"), ("record_id", "ID do registro"), ("appointment_id", "ID do apontamento")),
        filtros_comuns=("op",),
    ),
    "14": _tipo(
        "14", _PROD, "Lote e nesting",
        "Cada nesting do Corte: chapa, repetições, tempo total e tempo dentro do período, aproveitamento.",
        "/rastreabilidade/nestings",
        (("tarefa", "Tarefa / lote"), ("programa", "Programa"), ("nesting", "Nesting"), ("maquina", "Máquina"),
         ("material", "Material"), ("espessura", "Espessura"), ("previsto_segundos", "Tempo previsto (s)"),
         ("real_segundos", "Tempo total (s)"), ("real_periodo_segundos", "Tempo no período (s)"),
         ("desvio_segundos", "Desvio (s)"), ("aproveitamento_percentual", "Aproveitamento (%)"),
         ("operador_inicio", "Operador"), ("ops_relacionadas", "OPs relacionadas"), ("status", "Situação")),
        filtros_comuns=("setor", "recurso", "operador"),
        medida=("real_periodo_segundos",),
    ),
    "04": _tipo(
        "04", _PARADAS, "Paradas",
        "Cada parada física: recurso, motivo, se era planejada, início e tempo dentro do período.",
        "/analises/paradas",
        (("recurso", "Recurso"), ("setor", "Setor"), ("motivo", "Motivo"), ("programada", "Planejada"),
         ("inicio", "Início"), ("segundos", "Tempo (s)"), ("op", "OP"), ("evento_id", "ID do evento"),
         ("estado_recurso_id", "ID do estado do recurso")),
        filtros_proprios=("produto", "operacao"),
        medida=("segundos",),
    ),
    "05": _tipo(
        "05", _PARADAS, "Setup",
        "Cada setup: recurso, tipo, motivo, início e tempo dentro do período (setup é produtivo).",
        "/analises/setup",
        (("recurso", "Recurso"), ("setor", "Setor"), ("tipo_setup", "Tipo de setup"), ("motivo", "Motivo"),
         ("inicio", "Início"), ("segundos", "Tempo (s)"), ("op", "OP"), ("evento_id", "ID do evento")),
        filtros_proprios=("produto", "operacao"),
        medida=("segundos",),
    ),
    "08": _tipo(
        "08", _PARADAS, "Tempo padrão × real",
        "Por OP e operação: tempo padrão estimado contra o tempo real, com o desvio.",
        "/analises/tempo-padrao",
        (("apontamento_id", "ID do apontamento"), ("op", "OP"), ("operacao", "Operação"), ("produto", "Produto"),
         ("recurso_real", "Recurso real"), ("quantidade_boa", "Peças boas"),
         ("tempo_padrao_estimado_segundos", "Padrão estimado (s)"),
         ("tempo_producao_real_segundos", "Tempo real (s)"), ("desvio_segundos", "Desvio (s)"),
         ("desvio_percentual", "Desvio (%)"), ("fonte_tempo_producao", "Fonte")),
        filtros_proprios=("produto", "operacao"),
        medida=("tempo_producao_real_segundos",),
    ),
    "09": _tipo(
        "09", _PARADAS, "Cronoanálise",
        "Tempo por peça medido, por produto, operação e recurso: amostra, média, mediana, mínimo, máximo e desvio.",
        "/analises/cronoanalise",
        (("produto", "Produto"), ("operacao", "Operação"), ("recurso", "Recurso"), ("amostras", "Amostras"),
         ("media_segundos_por_peca", "Média (s/peça)"), ("mediana_segundos_por_peca", "Mediana (s/peça)"),
         ("minimo_segundos_por_peca", "Mínimo (s/peça)"), ("maximo_segundos_por_peca", "Máximo (s/peça)"),
         ("desvio_padrao_segundos_por_peca", "Desvio padrão (s/peça)")),
        filtros_proprios=("produto", "operacao"),
        medida=("amostras",),
    ),
    "10": _tipo(
        "10", _PARADAS, "Capacidade",
        "Por recurso: tempo disponível no calendário, tempo ocupado, livre e utilização (oficial), com a fila.",
        "/analises/capacidade",
        (("codigo", "Recurso (código)"), ("nome", "Recurso"), ("tipo_setor", "Setor"),
         ("capacidade_segundos", "Tempo disponível (s)"), ("carga_segundos", "Tempo ocupado (s)"),
         ("capacidade_restante_segundos", "Livre (s)"), ("utilizacao_percentual", "Utilização (%)"),
         ("fila", "Fila (operações)"), ("fila_ops", "OPs na fila"), ("fila_horas_segundos", "Fila com padrão (s)"),
         ("fila_horas_estimadas_segundos", "Fila estimada (s)"), ("fila_sem_tempo_padrao", "Fila sem tempo padrão"),
         ("fila_excede_livre", "Fila maior que o livre"), ("calendario_reason", "Calendário")),
        filtros_comuns=("setor", "recurso"),
        medida=("carga_segundos",),
    ),
    "06": _tipo(
        "06", _QUAL, "Boas, refugo e retrabalho",
        "Quantidades por setor e produto, com o FTT do período e os motivos de refugo e retrabalho.",
        "/analises/qualidade",
        (("produto", "Produto"), ("setor", "Setor"), ("boa", "Boas"), ("refugo", "Refugo"),
         ("retrabalho", "Retrabalho")),
        filtros_proprios=("produto", "operacao"),
        medida=("boa", "refugo", "retrabalho"),
    ),
    "07": _tipo(
        "07", _QUAL, "Inspeções e medições",
        "Primeira peça de cada operação e as inspeções dispensadas, com quem fez e o resultado.",
        "/analises/qualidade",
        (("registro", "Registro"), ("quando", "Quando"), ("codigo_op", "OP"), ("numero_operacao", "Operação"),
         ("tipo_setor", "Setor"), ("produto_codigo", "Produto"), ("status", "Situação"),
         ("bloqueio_ativo", "Bloqueada"), ("inspecionada_por", "Inspecionou"), ("observacao", "Cotas medidas"),
         ("ocorrencia", "Ocorrência"), ("decisao", "Decisão"), ("cracha", "Crachá"),
         ("autorizado_por_nome", "Responsável"), ("motivo_recusa", "Motivo da recusa")),
        filtros_comuns=("setor", "op"),
    ),
    "21": _tipo(
        "21", _QUAL, "RNC",
        "Relatórios de não conformidade e a decisão vigente de cada um. Só consulta: decidir fica na tela Decisão de RNC.",
        "/qualidade/rnc",
        (("id", "ID"), ("codigo", "RNC"), ("criada_em", "Registrada em"), ("op", "OP"), ("produto", "Produto"),
         ("recurso", "Recurso"), ("numero_peca", "Peça"), ("motivo", "Motivo"), ("origem", "Origem"),
         ("resultado_peca", "Resultado da peça"), ("decisao_vigente_decisao", "Decisão vigente"),
         ("decisao_vigente_decidido_por_nome", "Decidido por"), ("decisao_vigente_quando", "Decidido em"),
         ("decisao_vigente_justificativa", "Justificativa"), ("aviso", "Aviso")),
        permissao="qualidade", filtros_comuns=("recurso", "op"), somente_consulta=True,
    ),
    "11": _tipo(
        "11", _IND, "OEE por recurso",
        "OEE e seus componentes (Disponibilidade, Performance, FTT) por recurso, da fonte única do OEE.",
        "/analises/oee",
        (("resource", "Recurso (código)"), ("resource_name", "Recurso"), ("sector", "Setor"), ("oee", "OEE (%)"),
         ("disponibilidade", "Disponibilidade (%)"), ("performance", "Performance (%)"), ("ftt", "FTT (%)"),
         ("producao_boa", "Boas"), ("refugo", "Refugo"), ("retrabalho", "Retrabalho"),
         ("tempo_producao_segundos", "Produção (s)"), ("tempo_setup_segundos", "Setup (s)"),
         ("tempo_parada_segundos", "Paradas (s)"), ("tempo_produtivo_segundos", "Produtivo (s)")),
        medida=("tempo_produtivo_segundos",),
    ),
    "12": _tipo(
        "12", _IND, "Falhas (MTBF e MTTR)",
        "Quebras de equipamento por recurso: quantidade, tempo parado e tempo médio de reparo.",
        "/analises/confiabilidade",
        (("recurso", "Recurso"), ("falhas", "Quebras"), ("tempo_reparo_segundos", "Tempo parado (s)"),
         ("mttr_segundos", "MTTR (s)")),
        medida=("falhas",),
    ),
    "15": _tipo(
        "15", _SIS, "Alertas e inconsistências",
        "Problemas achados nos registros do período, com a gravidade e onde corrigir.",
        "/auditoria/alertas",
        (("severity", "Gravidade"), ("type", "Tipo"), ("message", "Ocorrência"), ("op", "OP"),
         ("operation", "Operação"), ("sector", "Setor"), ("resource", "Recurso"), ("start", "Início"),
         ("end", "Fim"), ("seconds", "Duração (s)"), ("appointment_id", "ID do apontamento"),
         ("source", "Fonte")),
        filtros_proprios=("produto", "operacao"),
    ),
    "16": _tipo(
        "16", _SIS, "Confiabilidade dos dados",
        "Quantos registros foram analisados e quantos problemas há em cada gravidade.",
        "/auditoria/confiabilidade",
        (("severidade", "Gravidade"), ("quantidade", "Problemas")),
        filtros_proprios=("produto", "operacao"),
        medida=("quantidade",),
    ),
    "17": _tipo(
        "17", _SIS, "Alterações de cadastro",
        "Quem mudou o quê (usuários, níveis, turnos, pausas), com o antes e o depois.",
        "/iagodev/alteracoes",
        (("id", "ID"), ("quando", "Quando"), ("usuario_nome", "Quem"), ("entidade", "O quê"),
         ("chave", "Registro"), ("acao", "Ação"), ("antes", "Antes"), ("depois", "Depois")),
        permissao="admin", filtros_comuns=(),
    ),
    "18": _tipo(
        "18", _SIS, "Log do sistema",
        "Registro técnico do sistema: área, nível, rota e mensagem.",
        "/iagodev/log",
        (("id", "ID"), ("quando", "Quando"), ("area", "Área"), ("nivel", "Nível"), ("evento", "Evento"),
         ("mensagem", "Mensagem"), ("usuario", "Usuário"), ("metodo", "Método"), ("rota", "Rota"),
         ("status_http", "HTTP"), ("duracao_ms", "Duração (ms)"), ("request_id", "Requisição")),
        permissao="admin", filtros_comuns=(),
    ),
    "19": _tipo(
        "19", _SIS, "Envios ao Protheus",
        "Cada envio ao Protheus e a situação dele. Só consulta: reenviar e descartar ficam na tela Envios.",
        "/iagodev/envios-protheus",
        (("id", "ID"), ("event_type", "Tipo"), ("production_order", "OP"), ("operation_code", "Operação"),
         ("status", "Situação"), ("attempts", "Tentativas"), ("created_at", "Criado em"),
         ("updated_at", "Atualizado em"), ("sent_at", "Enviado em"), ("last_error_code", "Código do erro"),
         ("last_error_message", "Erro"), ("discarded_at", "Descartado em"), ("discarded_by", "Descartado por"),
         ("discard_reason", "Motivo do descarte")),
        permissao="admin", filtros_comuns=("op",), somente_consulta=True,
    ),
    "20": _tipo(
        "20", _SIS, "Chamadas",
        "Chamadas do operador e da gestão: quem chamou (com e-mail e crachá), quem foi chamado e o aviso.",
        "/inicio/chamadas",
        (("id", "ID"), ("criado_em", "Quando"), ("solicitante_nome", "Quem chamou"),
         ("solicitante_nivel", "Nível"), ("solicitante_email", "E-mail"), ("solicitante_cracha", "Crachá"),
         ("contato_nome", "Chamado"), ("contato_funcao", "Função"), ("prioridade", "Prioridade"),
         ("motivo", "Motivo"), ("comentario", "Comentário"), ("aviso", "Aviso"),
         ("telegram_erro", "Erro do aviso"), ("atendida_em", "Atendida em")),
        filtros_comuns=(),
    ),
}

#: Fontes de cada tipo: (método do banco, obrigatória?). Tipos sem entrada
#: leem pela fachada ou por serviço próprio, sem fonte opcional a declarar.
_FONTES = {
    "01": (("listar_estados_recurso_periodo", True), ("listar_recursos_pcfactory", False)),
    "02": (
        ("listar_fatos_operacionais_periodo", True),
        ("listar_eventos_quantidade_periodo", True),
        ("listar_estados_recurso_periodo", True),
        ("listar_apontamentos_corte", False),
    ),
}

#: Fontes sem filtro de período no banco: lemos os N mais recentes e
#: filtramos pelo período aqui.
LIMITE_RECENTES = 200


class ForaDoEscopo(Exception):
    """A OP pedida não passou por nenhum setor da conta (vira 403 na rota)."""


def catalogo(user=None):
    """Tipos que a conta pode abrir (sem ``user``: todos)."""

    tipos = [TIPOS[key] for key in sorted(TIPOS) if user is None or pode_ver(TIPOS[key], user)]
    return {"regra_periodo": REGRA_PERIODO, "grupos": list(GRUPOS), "tipos": tipos}


def pode_ver(tipo: dict, user) -> bool:
    """A mesma guarda do módulo de origem de cada tipo."""

    from app.core.permissions import can_manage_quality_templates, is_admin_level

    if tipo["permissao"] == "admin":
        return bool(is_admin_level(user.role))
    if tipo["permissao"] == "qualidade":
        return bool(can_manage_quality_templates(user.role))
    return bool(getattr(user, "management_access", False))


def as_of_for(filters, now=None) -> datetime:
    moment = (now or datetime.now()).replace(microsecond=0)
    return min(moment, filters.fim) if filters.fim else moment


def _fontes(db, tipo):
    return {name: ("ok" if callable(getattr(db, name, None)) else "indisponivel") for name, _ in _FONTES.get(tipo, ())}


# --- utilitários de linha --------------------------------------------------------

def _dt(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if isinstance(value, datetime):
        return value.astimezone().replace(tzinfo=None) if value.tzinfo else value
    return None


def _no_periodo(items, campo, filters):
    """Linhas cuja data ``campo`` cai dentro do período (sem data, fica fora)."""

    out = []
    for item in items:
        when = _dt(item.get(campo))
        if when is None:
            continue
        if filters.inicio and when < filters.inicio:
            continue
        if filters.fim and when > filters.fim:
            continue
        out.append(item)
    return out


def _contem(items, campo, valor):
    alvo = str(valor or "").strip().casefold()
    if not alvo:
        return items
    return [item for item in items if alvo in str(item.get(campo) or "").casefold()]


def _plano(item: dict) -> dict:
    """Sub-registro (dict) vira campos ``pai_filho``; nada se perde no CSV."""

    out = {}
    for key, value in item.items():
        if isinstance(value, dict):
            out.update({f"{key}_{sub}": inner for sub, inner in value.items()})
        else:
            out[key] = value
    return out


def _soma(items, campo):
    return sum(float(item.get(campo) or 0) for item in items)


def _aviso_limite(n):
    return f"Esta fonte não filtra por período no banco: mostra o que houver no período entre os {n} registros mais recentes."


# --- busca de cada tipo: (items, summary, avisos) ----------------------------------

def _t03(ctx):
    payload = ctx.facade.ordens_producao(ctx.filters)
    items = list(payload.get("items") or [])
    summary = {
        "operacoes": len(items),
        "quantidade_boa": _soma(items, "quantidade_boa"),
        "refugo": _soma(items, "refugo"),
        "retrabalho": _soma(items, "retrabalho"),
    }
    return items, summary, []


def _t13(ctx):
    op = str(ctx.filters.op or "").strip()
    if not op:
        return [], None, ["Informe a OP no filtro para ver a linha do tempo."]
    from app.core.areas import trace_in_scope

    trace = ctx.facade.rastreabilidade(op) or {}
    if not trace_in_scope(trace, getattr(ctx.user, "sector_scope", None)):
        raise ForaDoEscopo(op)
    items = list(trace.get("timeline") or [])
    summary = {"op": op, "operacoes": len(trace.get("operations") or [])}
    return items, summary, []


def _t14(ctx):
    payload = ctx.facade.nestings(ctx.filters)
    items = list(payload.get("items") or [])
    summary = {"nestings": len(items), "tempo_no_periodo_segundos": _soma(items, "real_periodo_segundos")}
    reason = (payload.get("time_policy") or {}).get("reason")
    return items, summary, [reason] if reason else []


_RESUMO_PARADAS = (
    "count", "total_seconds", "planned_downtime_seconds", "unplanned_downtime_seconds", "listed_seconds",
    "resource_count",
)


def _paradas(payload):
    items = list(payload.get("items") or [])
    summary = {key: payload.get(key) for key in _RESUMO_PARADAS if key in payload}
    avisos = []
    difference = payload.get("difference") or {}
    if difference.get("seconds") and difference.get("reason"):
        avisos.append(difference["reason"])
    return items, summary, avisos


def _t04(ctx):
    return _paradas(ctx.facade.paradas_tela(ctx.filters))


def _t05(ctx):
    return _paradas(ctx.facade.analise("setup", ctx.filters))


def _t08(ctx):
    payload = ctx.facade.analise("tempo_padrao_x_real", ctx.filters)
    items = list(payload.get("items") or [])
    comparaveis = [
        item for item in items
        if item.get("tempo_padrao_estimado_segundos") is not None and item.get("tempo_producao_real_segundos") is not None
    ]
    padrao = _soma(comparaveis, "tempo_padrao_estimado_segundos")
    real = _soma(comparaveis, "tempo_producao_real_segundos")
    summary = {
        "comparaveis": len(comparaveis),
        "sem_tempo_padrao": len(items) - len(comparaveis),
        "tempo_padrao_segundos": padrao,
        "tempo_real_segundos": real,
        "desvio_segundos": real - padrao if comparaveis else None,
        # Desvio só existe com padrão maior que zero (mesma regra da tela antiga).
        "desvio_percentual": ((real - padrao) / padrao * 100) if padrao > 0 else None,
    }
    return items, summary, []


def _t09(ctx):
    payload = ctx.facade.analise("cronoanalise", ctx.filters)
    items = list(payload.get("groups") or [])
    medidos = [
        item for item in items
        if item.get("media_segundos_por_peca") is not None and float(item.get("amostras") or 0) > 0
    ]
    amostras = _soma(medidos, "amostras")

    def _nome(item):
        return " · ".join(str(item.get(key)) for key in ("produto", "operacao", "recurso") if item.get(key)) if item else None

    lento = max(medidos, key=lambda item: float(item["media_segundos_por_peca"]), default=None)
    variaveis = [item for item in medidos if item.get("desvio_padrao_segundos_por_peca") is not None]
    variavel = max(variaveis, key=lambda item: float(item["desvio_padrao_segundos_por_peca"]), default=None)
    summary = {
        "grupos": len(items),
        "amostras": amostras,
        # Média ponderada pelas amostras: Σ(média × amostras) / Σ amostras.
        "media_ponderada_segundos_por_peca": (
            sum(float(item["media_segundos_por_peca"]) * float(item["amostras"]) for item in medidos) / amostras
            if amostras else None
        ),
        "mais_lento": _nome(lento),
        "mais_variavel": _nome(variavel),
    }
    return items, summary, []


_RESUMO_CAPACIDADE = (
    "total_capacity_seconds", "total_load_seconds", "total_remaining_seconds", "utilizacao_percentual",
    "bottleneck_resource", "recursos_com_calendario", "recursos_sem_calendario",
)


def _t10(ctx):
    payload = ctx.facade.analise("capacidade", ctx.filters)
    items = list(payload.get("items") or payload.get("recursos") or [])
    summary = {key: payload.get(key) for key in _RESUMO_CAPACIDADE if key in payload}
    return items, summary, []


def _t06(ctx):
    payload = ctx.facade.analise("qualidade", ctx.filters)
    items = list(payload.get("by_product") or [])
    ftt = payload.get("ftt") or {}
    summary = {**(payload.get("totals") or {}), "ftt": ftt.get("value")}
    avisos = [ftt["reason"]] if ftt.get("value") is None and ftt.get("reason") else []
    return items, summary, avisos


def _t07(ctx):
    from app.core.areas import scoped_sector

    setor = scoped_sector(ctx.filters.setor, getattr(ctx.user, "sector_scope", None))
    pecas = []
    for row in ctx.facade.db.listar_primeiras_pecas(tipo_setor=setor, limite=LIMITE_RECENTES) or []:
        item = {"registro": "Primeira peça", "quando": row.get("inspecionada_em") or row.get("setup_registrado_em")}
        item.update(row)
        pecas.append(item)
    dispensadas = []
    for row in (ctx.facade.inspecoes_dispensadas(ctx.filters) or {}).get("items") or []:
        item = {"registro": "Inspeção dispensada", "quando": row.get("data_hora")}
        item.update(row)
        dispensadas.append(item)
    items = _no_periodo(pecas, "quando", ctx.filters) + dispensadas
    items = _contem(items, "codigo_op", ctx.filters.op)
    items.sort(key=lambda item: _dt(item.get("quando")) or datetime.min, reverse=True)
    summary = {
        "primeiras_pecas": sum(1 for item in items if item["registro"] == "Primeira peça"),
        "bloqueadas": sum(1 for item in items if item.get("bloqueio_ativo")),
        "inspecoes_dispensadas": sum(1 for item in items if item["registro"] == "Inspeção dispensada"),
    }
    return items, summary, [_aviso_limite(LIMITE_RECENTES) + " (primeira peça)"]


def _t21(ctx):
    from mes.services.quality_rnc_decision import QualityRncDecisionService

    service = QualityRncDecisionService(ctx.facade.db, getattr(ctx.user, "id", None), getattr(ctx.user, "name", None))
    items = [_plano(row) for row in (service.listar_pendencias(limite=LIMITE_RECENTES) or {}).get("items") or []]
    items = _no_periodo(items, "criada_em", ctx.filters)
    items = _contem(_contem(items, "op", ctx.filters.op), "recurso", ctx.filters.recurso)
    summary = {"rncs": len(items), "sem_decisao": sum(1 for item in items if not item.get("decisao_vigente_decisao"))}
    return items, summary, [_aviso_limite(LIMITE_RECENTES)]


def _t11(ctx):
    # Fonte única do OEE: os KPIs por recurso que a tela Início já usa.
    payload = ctx.facade.inicio(ctx.filters, include_insights=False) or {}
    items = []
    for row in payload.get("resource_kpis") or []:
        metrics = row.get("metrics") or {}

        def _valor(key):
            metric = metrics.get(key)
            return metric.get("value") if isinstance(metric, dict) else metric

        item = {key: value for key, value in row.items() if key != "metrics"}
        item.update({
            "oee": _valor("oee"), "disponibilidade": _valor("availability"),
            "performance": _valor("performance"), "ftt": _valor("ftt"),
        })
        items.append(item)
    kpis = payload.get("kpis") or {}

    def _kpi(key):
        metric = kpis.get(key)
        return metric.get("value") if isinstance(metric, dict) else metric

    summary = {
        "oee": _kpi("oee"), "disponibilidade": _kpi("availability"),
        "performance": _kpi("performance"), "ftt": _kpi("ftt"),
    }
    return items, summary, []


_RESUMO_CONFIABILIDADE = (
    "mtbf_segundos", "mttr_segundos", "falhas", "reparos_concluidos", "tempo_operacional_segundos",
    "tempo_reparo_segundos",
)


def _t12(ctx):
    payload = ctx.facade.analise("confiabilidade", ctx.filters)
    items = list(payload.get("por_recurso") or [])
    summary = {key: payload.get(key) for key in _RESUMO_CONFIABILIDADE if key in payload}
    avisos = [payload["taxonomia"]] if payload.get("taxonomia") else []
    return items, summary, avisos


def _t15(ctx):
    payload = ctx.facade.auditoria(ctx.filters) or {}
    items = list(payload.get("issues") or [])
    summary = {"problemas": len(items), **(payload.get("by_severity") or {})}
    return items, summary, []


def _t16(ctx):
    payload = ctx.facade.auditoria(ctx.filters) or {}
    analisados = payload.get("records_analyzed") or 0
    items = (
        [{"severidade": key, "quantidade": value} for key, value in (payload.get("by_severity") or {}).items()]
        if analisados else []
    )
    summary = {
        key: payload.get(key)
        for key in (
            "reliability_percentage", "records_analyzed", "resource_states_analyzed", "rateio_sessions_analyzed",
        )
    }
    avisos = [payload["reliability_reason"]] if payload.get("reliability_reason") else []
    return items, summary, avisos


def _texto_json(value):
    import json

    return json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else value


def _t17(ctx):
    from mes.services.change_audit import consultar

    f = ctx.filters
    rows = consultar(
        ctx.facade.db, custos=False,
        desde=f.inicio.date() if f.inicio else None, ate=f.fim.date() if f.fim else None, limite=500,
    ) or []
    items = [{key: _texto_json(value) for key, value in row.items()} for row in rows]
    items = _no_periodo(items, "quando", f)
    return items, {"alteracoes": len(items)}, ["Mostra até 500 alterações; valores em R$ não entram aqui."]


def _t18(ctx):
    f = ctx.filters
    rows = ctx.facade.db.listar_log(desde=f.inicio, ate=f.fim, limite=1000) or []
    items = [{key: _texto_json(value) for key, value in row.items()} for row in rows]
    return items, {"registros": len(items)}, ["Mostra até 1000 registros, os mais recentes."]


def _t19(ctx):
    from mes.services.totvs_outbox_admin import TotvsOutboxAdminService

    chaves = [campo["chave"] for campo in TIPOS["19"]["campos"]]
    rows = TotvsOutboxAdminService(ctx.facade.db).list_items(limit=LIMITE_RECENTES) or []
    items = [{key: row.get(key) for key in chaves} for row in rows]
    items = _contem(_no_periodo(items, "created_at", ctx.filters), "production_order", ctx.filters.op)
    por_status = {}
    for item in items:
        por_status[str(item.get("status") or "—")] = por_status.get(str(item.get("status") or "—"), 0) + 1
    return items, {"envios": len(items), **por_status}, [_aviso_limite(LIMITE_RECENTES)]


#: Pendente há mais que isto vira "sem confirmação" (era regra da tela).
PENDENTE_SUSPEITO_SEGUNDOS = 5 * 60


def aviso_chamada(chamada: dict, as_of: datetime) -> str:
    """Estado do aviso da chamada no instante ``as_of``."""

    from app.database.chamada_repository import telegram_status

    status = telegram_status(chamada)
    if status == "so_sistema":
        return "atendida" if chamada.get("atendida_em") else "na_tela"
    if status != "pendente":
        return status
    criado = _dt(chamada.get("criado_em"))
    if criado is not None and (as_of - criado).total_seconds() > PENDENTE_SUSPEITO_SEGUNDOS:
        return "sem_confirmacao"
    return "enviando"


def _t20(ctx):
    rows = ctx.facade.db.listar_chamadas(limite=LIMITE_RECENTES) or []
    items = []
    for row in rows:
        item = {key: value for key, value in row.items() if key != "contato_telegram_chat_id"}
        item["aviso"] = aviso_chamada(item, ctx.as_of)
        items.append(item)
    items = _no_periodo(items, "criado_em", ctx.filters)
    summary = {
        "chamadas": len(items),
        "atendidas": sum(1 for item in items if item.get("atendida_em")),
        "falharam": sum(1 for item in items if item["aviso"] == "falhou"),
    }
    return items, summary, [_aviso_limite(LIMITE_RECENTES)]


_BUSCAS = {
    "03": _t03, "04": _t04, "05": _t05, "06": _t06, "07": _t07, "08": _t08, "09": _t09, "10": _t10,
    "11": _t11, "12": _t12, "13": _t13, "14": _t14, "15": _t15, "16": _t16, "17": _t17, "18": _t18,
    "19": _t19, "20": _t20, "21": _t21,
}


class _Ctx:
    def __init__(self, facade, filters, user, as_of):
        self.facade, self.filters, self.user, self.as_of = facade, filters, user, as_of


def _avisos(tipo, filters, fontes):
    avisos = []
    if tipo == "01" and filters.produto:
        avisos.append("Produto filtra pelas OPs do produto no período: status sem OP (parada, sem demanda) não aparece.")
    if tipo == "02" and any((filters.op, filters.operacao, filters.produto)):
        avisos.append("Com filtro de OP, operação ou produto, as linhas do Corte (por tarefa e plano) não entram.")
    for name, required in _FONTES.get(tipo, ()):
        if not required and fontes[name] != "ok":
            avisos.append(f"Fonte complementar indisponível: {name}.")
    return avisos


def _estado(tipo, items, fontes):
    if any(fontes[name] != "ok" for name, required in _FONTES.get(tipo, ()) if required):
        return "indisponivel"
    if not items:
        return "sem_registros"
    medida = TIPOS[tipo]["medida"]
    if not medida:
        return "com_dados"
    # Medida ausente (None) é "sem dado", nunca zero.
    valores = [float(item[field]) for item in items for field in medida if item.get(field) is not None]
    return "zero" if valores and sum(valores) == 0 else "com_dados"


def run(facade, tipo: str, filters, *, user=None, now=None, status=None, classe=None, em_aberto=False):
    """Executa o tipo e devolve o envelope comum. ``tipo`` e permissão já validados pela rota."""

    fontes = _fontes(facade.db, tipo)
    summary, opcoes, extras = None, None, []
    if tipo == "01":
        payload = facade.eventos_status(filters, status=status, classe=classe, em_aberto=em_aberto)
        items, summary, opcoes = list(payload.get("items") or []), payload.get("summary"), payload.get("opcoes")
    elif tipo == "02":
        payload = facade.eventos_producao(filters)
        items, summary = list(payload.get("items") or []), payload.get("summary")
    else:
        items, summary, extras = _BUSCAS[tipo](_Ctx(facade, filters, user, as_of_for(filters, now)))
    # Lido depois da consulta: a projeção recorta eventos abertos no relógio
    # do momento da leitura, então nenhum tempo contado passa da referência.
    as_of = as_of_for(filters, now)
    return {
        "tipo": tipo,
        "titulo": TIPOS[tipo]["titulo"],
        "as_of": as_of,
        "estado": _estado(tipo, items, fontes),
        "fontes": fontes,
        "avisos": _avisos(tipo, filters, fontes) + list(extras),
        "regra_periodo": REGRA_PERIODO,
        "campos": TIPOS[tipo]["campos"],
        "summary": summary,
        "opcoes": opcoes,
        "items": items,
    }
