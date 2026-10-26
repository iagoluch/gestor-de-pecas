"""Parada NÃO planejada do grupo de manutenção vira ordem de manutenção SUGERIDA.

O mantenedor só aceita ou descarta. Esta camada é um REGISTRO interno: não cria
ordem no Protheus, não escreve no outbox, não altera apontamento nem parada e
não pede nada ao operador. A classificação NÃO é reimplementada aqui:

* a parada vem do serviço canônico de paradas (``IndustrialAnalyticsService.downtimes``);
* "é manutenção corretiva" é ``ManufacturingRules.stop_reason_is_equipment_failure``
  (grupo ``0003`` do catálogo, a mesma taxonomia do MTBF/MTTR);
* "é NÃO planejada" é ``ManufacturingRules.classify_stop``.

A geração é lazy (a cada leitura) e idempotente por ``(recurso, parada_inicio)``.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from mes.contracts import AnalyticsFilter
from mes.domain import EventCategory, ManufacturingRules, StopClassification
from mes.services.industrial_analytics import IndustrialAnalyticsService

#: Parada mais curta que isto não gera sugestão (ruído de apontamento).
MIN_PARADA_SEGUNDOS = 600
#: Janela das paradas consideradas, contada a partir da meia-noite de ``hoje - N``
#: (início estável durante o dia: a chave de idempotência usa o início da parada).
JANELA_DIAS = 7
LIMITE_LISTA = 200
NOTA_MAX = 500

STATUS_SUGERIDA = "sugerida"
STATUS_ACEITA = "aceita"
STATUS_DESCARTADA = "descartada"
STATUS = (STATUS_SUGERIDA, STATUS_ACEITA, STATUS_DESCARTADA)


class MaintenanceSuggestionError(Exception):
    """Erro de regra (o transporte devolve ``status_code`` com ``code``/``message``)."""

    def __init__(self, code, message, *, status_code=409, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def sugestao_publica(row):
    """Projeção da linha para a API (contrato estável, sem R$)."""

    return {
        "id": row["id"],
        "recurso": row["recurso"],
        "setor": row["setor"],
        "parada_inicio": row["parada_inicio"],
        "parada_fim": row["parada_fim"],
        "parada_segundos": row["parada_segundos"],
        "motivo": row["motivo"],
        "op": row["op"],
        "status": row["status"],
        "criada_em": row["criada_em"],
        "decidido_por_id": row["decidido_por_id"],
        "decidido_por_nome": row["decidido_por_nome"],
        "decidido_em": row["decidido_em"],
        "nota": row["nota"],
    }


class MaintenanceSuggestionService:
    def __init__(self, db, usuario_id, usuario_nome, *, now_func=None):
        self.db = db
        self.usuario_id = usuario_id
        self.usuario_nome = str(usuario_nome or "Manutenção").strip() or "Manutenção"
        self._now = now_func or (lambda: datetime.now().replace(microsecond=0))

    # ------------------------------------------------------------------ geração
    def gerar(self):
        """Grava as sugestões que faltam; devolve quantas paradas elegíveis existem."""

        paradas = self._paradas_elegiveis()
        self.db.gravar_sugestoes_manutencao(paradas)
        return len(paradas)

    def _paradas_elegiveis(self):
        agora = self._now()
        inicio = datetime.combine((agora - timedelta(days=JANELA_DIAS)).date(), time.min)
        catalogo = self._catalogo()
        if not catalogo:
            return []
        analytics = IndustrialAnalyticsService(self.db, now_func=lambda: agora)
        itens = analytics.downtimes(AnalyticsFilter(inicio=inicio, fim=agora)).get("items") or []
        paradas = {}
        for item in itens:
            parada = self._como_sugestao(item, catalogo)
            # Início recortado na borda da janela: o pedaço já gerou sugestão quando
            # a parada começou; sem este corte a chave (recurso, início) não repetiria.
            if parada is not None and parada["parada_inicio"] <= inicio:
                continue
            if parada is not None:
                # Mesma chave do banco: repetição no mesmo recurso/instante vale uma vez.
                paradas.setdefault((parada["recurso"], parada["parada_inicio"]), parada)
        return list(paradas.values())

    def _catalogo(self):
        loader = getattr(self.db, "listar_status_recursos", None)
        rows = list(loader(incluir_ocultos=True) or []) if callable(loader) else []
        return {
            str(row.get("codigo") or "").strip(): dict(row)
            for row in rows
            if str(row.get("codigo") or "").strip()
        }

    @staticmethod
    def _como_sugestao(item, catalogo):
        status_row = catalogo.get(str(item.get("codigo_status") or "").strip())
        if status_row is None:
            return None  # sem catálogo não há grupo: não se infere manutenção pelo texto
        if not ManufacturingRules.stop_reason_is_equipment_failure(status_row):
            return None
        # Parada marcada como programada não é falha (igual a ``reliability``).
        if item.get("programada"):
            return None
        classificacao = ManufacturingRules.classify_stop(
            category=EventCategory.DOWNTIME,
            status_row=status_row,
            reason=item.get("motivo"),
            planned=item.get("programada"),
        )
        if classificacao is not StopClassification.UNPLANNED:
            return None
        inicio = item.get("inicio")
        segundos = int(float(item.get("segundos") or 0.0))
        recurso = str(item.get("recurso") or "").strip()
        if not isinstance(inicio, datetime) or not recurso or segundos < MIN_PARADA_SEGUNDOS:
            return None
        return {
            "recurso": recurso,
            "setor": item.get("setor"),
            "parada_inicio": inicio,
            # Parada ainda em curso: sem fim; a duração é atualizada nas próximas leituras.
            "parada_fim": None if item.get("em_andamento") else item.get("fim"),
            "parada_segundos": segundos,
            "motivo": str(item.get("motivo") or status_row.get("nome") or "Manutenção"),
            "op": str(item.get("op") or "").strip() or None,
        }

    # ------------------------------------------------------------------ leitura
    def listar(self, status=STATUS_SUGERIDA):
        """Gera (lazy) e lista, mais recentes primeiro (até ``LIMITE_LISTA``)."""

        if status not in STATUS:
            raise MaintenanceSuggestionError(
                "maintenance_status_invalid",
                "Status inválido. Use: " + ", ".join(STATUS) + ".",
                status_code=422,
            )
        self.gerar()
        return [
            sugestao_publica(row)
            for row in self.db.listar_sugestoes_manutencao(status, LIMITE_LISTA)
        ]

    # ------------------------------------------------------------------ decisão
    def aceitar(self, sugestao_id, nota=None):
        return self._decidir(sugestao_id, STATUS_ACEITA, nota)

    def descartar(self, sugestao_id, nota=None):
        return self._decidir(sugestao_id, STATUS_DESCARTADA, nota)

    def _decidir(self, sugestao_id, status, nota):
        nota = str(nota or "").strip() or None
        if nota is not None and len(nota) > NOTA_MAX:
            raise MaintenanceSuggestionError(
                "maintenance_note_too_long",
                f"A nota pode ter no máximo {NOTA_MAX} caracteres.",
                status_code=422,
            )
        row = self.db.decidir_sugestao_manutencao(
            sugestao_id,
            status=status,
            usuario_id=self.usuario_id,
            usuario_nome=self.usuario_nome,
            nota=nota,
            quando=self._now(),
        )
        if row is not None:
            return sugestao_publica(row)
        atual = self.db.buscar_sugestao_manutencao(sugestao_id)
        if atual is None:
            raise MaintenanceSuggestionError(
                "maintenance_suggestion_not_found",
                "Sugestão de manutenção não encontrada.",
                status_code=404,
            )
        raise MaintenanceSuggestionError(
            "maintenance_suggestion_already_decided",
            "Esta sugestão já foi decidida.",
            details={
                "status": atual["status"],
                "decidido_por_nome": atual["decidido_por_nome"],
                "decidido_em": atual["decidido_em"],
            },
        )
