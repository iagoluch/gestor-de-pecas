"""Inspeções dispensadas, expostas à gestão (somente leitura).

A dispensa é gravada pelo fluxo do operador (``QualityInspectionService``) em
``qualidade_inspecoes`` com ``status = 'DISPENSADA'``. Aqui ela só é traduzida
para o contrato público da gestão: quem autorizou, o motivo, o crachá e quando.
Nenhuma regra de dispensa vive neste módulo.
"""

from __future__ import annotations


def dispensa_publica(row: dict) -> dict:
    """Linha do repositório no contrato público de uma inspeção dispensada."""

    return {
        "inspecao_id": row.get("inspecao_id"),
        "dispensada": True,
        "op": row.get("codigo_op"),
        "operacao": row.get("numero_operacao"),
        "recurso": row.get("codigo_recurso"),
        "setor": row.get("setor_origem"),
        "produto": row.get("produto_codigo"),
        "descricao": row.get("produto_descricao"),
        "quantidade": row.get("quantidade_total"),
        "motivo": row.get("dispensa_motivo"),
        "autorizado_por": row.get("dispensa_autorizada_por"),
        "cracha": row.get("dispensa_cracha"),
        "dispensada_em": row.get("dispensada_em"),
        "registrada_por": row.get("operador"),
    }


class InspectionWaiverService:
    def __init__(self, db):
        self.db = db

    def _listar(self, **filtros) -> list[dict]:
        loader = getattr(self.db, "listar_dispensas_inspecao", None)
        if not callable(loader):
            return []
        return [dispensa_publica(row) for row in (loader(**filtros) or ())]

    def da_op(self, op: str) -> list[dict]:
        """Dispensas de uma OP (genealogia), da mais recente para a mais antiga."""

        return self._listar(op=op, op_exata=True)

    def no_periodo(self, filters) -> dict:
        """Dispensas do período, respeitando os filtros gerenciais."""

        items = self._listar(
            setor_origem=filters.setor,
            inicio=filters.inicio,
            fim=filters.fim,
            op=filters.op,
            operacao=filters.operacao,
            produto=filters.produto,
            recurso=filters.recurso,
        )
        return {
            "periodo": filters.to_dict(),
            "items": items,
            "count": len(items),
            "availability": "disponivel" if items else "sem_registros",
        }
