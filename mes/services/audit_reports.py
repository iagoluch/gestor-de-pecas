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

TIPOS = {
    "01": {
        "id": "01",
        "titulo": "Eventos de status",
        "descricao": "Em que condição cada recurso esteve e por quanto tempo, produzindo ou parado.",
        "origem": "/auditoria/eventos-status",
        "filtros_comuns": list(FILTROS_COMUNS),
        "filtros_proprios": ["produto", "operacao", "evento_status", "evento_classe", "em_aberto"],
        "campos": [{"chave": key, "rotulo": label} for key, label in _CAMPOS_STATUS],
    },
    "02": {
        "id": "02",
        "titulo": "Eventos de produção",
        "descricao": "O que foi executado: OP, produto, operação, recurso e colaborador, com tempo real e quantidades.",
        "origem": "/auditoria/eventos-producao",
        "filtros_comuns": list(FILTROS_COMUNS),
        "filtros_proprios": ["produto", "operacao"],
        "campos": [{"chave": key, "rotulo": label} for key, label in _CAMPOS_PRODUCAO],
    },
}

#: Fontes de cada tipo: (método do banco, obrigatória?).
_FONTES = {
    "01": (("listar_estados_recurso_periodo", True), ("listar_recursos_pcfactory", False)),
    "02": (
        ("listar_fatos_operacionais_periodo", True),
        ("listar_eventos_quantidade_periodo", True),
        ("listar_estados_recurso_periodo", True),
        ("listar_apontamentos_corte", False),
    ),
}


def catalogo():
    return {"regra_periodo": REGRA_PERIODO, "tipos": [TIPOS[key] for key in sorted(TIPOS)]}


def as_of_for(filters, now=None) -> datetime:
    moment = (now or datetime.now()).replace(microsecond=0)
    return min(moment, filters.fim) if filters.fim else moment


def _fontes(db, tipo):
    return {name: ("ok" if callable(getattr(db, name, None)) else "indisponivel") for name, _ in _FONTES[tipo]}


def _avisos(tipo, filters, fontes):
    avisos = []
    if tipo == "01" and filters.produto:
        avisos.append("Produto filtra pelas OPs do produto no período: status sem OP (parada, sem demanda) não aparece.")
    if tipo == "02" and any((filters.op, filters.operacao, filters.produto)):
        avisos.append("Com filtro de OP, operação ou produto, as linhas do Corte (por tarefa e plano) não entram.")
    for name, required in _FONTES[tipo]:
        if not required and fontes[name] != "ok":
            avisos.append(f"Fonte complementar indisponível: {name}.")
    return avisos


def _estado(tipo, items, fontes):
    if any(fontes[name] != "ok" for name, required in _FONTES[tipo] if required):
        return "indisponivel"
    if not items:
        return "sem_registros"
    if tipo == "01":
        medida = sum(float(item.get("duracao_segundos") or 0) for item in items)
    else:
        medida = sum(
            float(item.get(field) or 0)
            for item in items
            for field in ("tempo_real_segundos", "quantidade_boa", "quantidade_refugo", "quantidade_retrabalho")
        )
    return "zero" if medida == 0 else "com_dados"


def run(facade, tipo: str, filters, *, now=None, status=None, classe=None, em_aberto=False):
    """Executa o tipo e devolve o envelope comum. ``tipo`` já validado pela rota."""

    fontes = _fontes(facade.db, tipo)
    if tipo == "01":
        payload = facade.eventos_status(filters, status=status, classe=classe, em_aberto=em_aberto)
    else:
        payload = facade.eventos_producao(filters)
    items = list(payload.get("items") or [])
    # Lido depois da consulta: a projeção recorta eventos abertos no relógio
    # do momento da leitura, então nenhum tempo contado passa da referência.
    as_of = as_of_for(filters, now)
    return {
        "tipo": tipo,
        "titulo": TIPOS[tipo]["titulo"],
        "as_of": as_of,
        "estado": _estado(tipo, items, fontes),
        "fontes": fontes,
        "avisos": _avisos(tipo, filters, fontes),
        "regra_periodo": REGRA_PERIODO,
        "campos": TIPOS[tipo]["campos"],
        "summary": payload.get("summary"),
        "opcoes": payload.get("opcoes"),
        "items": items,
    }
