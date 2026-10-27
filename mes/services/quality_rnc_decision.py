"""Decisão sobre uma RNC já existente (disposição da peça não conforme).

Esta camada é um REGISTRO: grava quem decidiu o quê e por quê. Ela nunca cria
evento de quantidade (FTT/OEE derivam deles), nunca altera o resultado da peça
nem a RNC e não fala com TOTVS. Contradição com o resultado registrado da peça
NÃO bloqueia: devolve apenas um ``aviso`` para a tela mostrar.
"""

from __future__ import annotations

from datetime import datetime

from mes.services.quality import QualityResult

DECISAO_USAR_COMO_ESTA = "usar_como_esta"
DECISAO_RETRABALHAR = "retrabalhar"
DECISAO_SUCATEAR = "sucatear"
DECISAO_QUARENTENA = "quarentena"
DECISOES = (
    DECISAO_USAR_COMO_ESTA,
    DECISAO_RETRABALHAR,
    DECISAO_SUCATEAR,
    DECISAO_QUARENTENA,
)

JUSTIFICATIVA_MIN = 3
JUSTIFICATIVA_MAX = 500

# (resultado registrado da peça, decisão) -> aviso. É a ÚNICA fonte da regra:
# uma decisão que desfaz a classificação já registrada pelo inspetor. Qualquer
# outra combinação (inclusive sucatear/quarentena) é coerente e fica sem aviso.
_CONTRADICOES = {
    ("REFUGO", DECISAO_USAR_COMO_ESTA): (
        "A peça foi registrada como REFUGO na inspeção, mas a decisão é usar como está."
        " A decisão foi gravada; confirme se é isso mesmo."
    ),
    ("REFUGO", DECISAO_RETRABALHAR): (
        "A peça foi registrada como REFUGO na inspeção, mas a decisão é retrabalhar."
        " A decisão foi gravada; confirme se é isso mesmo."
    ),
    ("RETRABALHO", DECISAO_USAR_COMO_ESTA): (
        "A peça foi registrada para RETRABALHO na inspeção, mas a decisão é usar como está."
        " A decisão foi gravada; confirme se é isso mesmo."
    ),
}


def aviso_de_contradicao(resultado_peca, decisao):
    """Texto de aviso (pt-BR) se a decisão contradiz o resultado da peça; senão ``None``.

    Função pura. Resultado ausente ou desconhecido nunca gera aviso.
    """

    chave = (str(resultado_peca or "").strip().upper(), str(decisao or "").strip())
    return _CONTRADICOES.get(chave)


def decisao_publica(row, *, resultado_peca=None, vigente=False):
    """Projeção da linha para a API, com o aviso recalculado a partir do resultado."""

    return {
        "id": row["id"],
        "rnc_id": row["rnc_id"],
        "decisao": row["decisao"],
        "justificativa": row["justificativa"],
        "decidido_por_id": row["decidido_por_id"],
        "decidido_por_nome": row["decidido_por_nome"],
        "quando": row["quando"],
        "vigente": bool(vigente),
        "aviso": aviso_de_contradicao(resultado_peca, row["decisao"]),
    }


class QualityRncDecisionService:
    """Caso de uso fino: valida, grava a linha e calcula o aviso."""

    def __init__(self, db, usuario_id, usuario_nome, *, now_func=None):
        self.db = db
        self.usuario_id = usuario_id
        self.usuario_nome = str(usuario_nome or "Qualidade").strip() or "Qualidade"
        self._now = now_func or (lambda: datetime.now().replace(microsecond=0))

    def registrar(self, rnc_id, decisao, justificativa):
        """``None`` se a RNC não existe; senão um ``QualityResult`` (``data`` com o aviso)."""

        rnc = self.db.buscar_rnc_com_resultado(rnc_id)
        if rnc is None:
            return None
        decisao = str(decisao or "").strip()
        justificativa = str(justificativa or "").strip()
        if decisao not in DECISOES:
            return QualityResult(
                False,
                "Decisão inválida. Use: " + ", ".join(DECISOES) + ".",
                "qualidade_rnc_decisao_invalida",
            )
        if not JUSTIFICATIVA_MIN <= len(justificativa) <= JUSTIFICATIVA_MAX:
            return QualityResult(
                False,
                f"A justificativa precisa ter de {JUSTIFICATIVA_MIN} a {JUSTIFICATIVA_MAX} caracteres.",
                "qualidade_rnc_justificativa_invalida",
            )
        linha = self.db.registrar_decisao_rnc(
            rnc["id"],
            decisao=decisao,
            justificativa=justificativa,
            usuario_id=self.usuario_id,
            usuario_nome=self.usuario_nome,
            quando=self._now(),
        )
        item = decisao_publica(linha, resultado_peca=rnc.get("resultado_peca"), vigente=True)
        return QualityResult(
            True,
            "Decisão registrada.",
            "qualidade_rnc_decisao_registrada",
            {"rnc": rnc, "decisao": item, "aviso": item["aviso"]},
        )

    def listar(self, rnc_id):
        """``None`` se a RNC não existe; senão ``{"rnc", "vigente", "items"}``."""

        rnc = self.db.buscar_rnc_com_resultado(rnc_id)
        if rnc is None:
            return None
        itens = [
            decisao_publica(linha, resultado_peca=rnc.get("resultado_peca"), vigente=indice == 0)
            for indice, linha in enumerate(self.db.listar_decisoes_rnc(rnc["id"]))
        ]
        return {"rnc": rnc, "vigente": itens[0] if itens else None, "items": itens}

    def listar_pendencias(self, *, limite=100, somente_sem_decisao=False):
        """RNCs recentes com a decisão vigente e o ``aviso`` de contradição (ou ``None``)."""

        itens = []
        for linha in self.db.listar_rncs_para_decisao(
            limite=limite, somente_sem_decisao=somente_sem_decisao
        ):
            vigente = linha.get("decisao_vigente")
            itens.append(
                {
                    **linha,
                    "aviso": (
                        aviso_de_contradicao(linha.get("resultado_peca"), vigente["decisao"])
                        if vigente
                        else None
                    ),
                }
            )
        return {"items": itens, "count": len(itens)}
