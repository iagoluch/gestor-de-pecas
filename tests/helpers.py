"""Apoio dos testes ao portão da primeira peça (Wave 5).

Desde a Wave 5 nenhuma operação produtiva é finalizada sem que a primeira peça
tenha sido produzida, o Setup tenha sido apontado onde ele existe e a inspeção
do próprio operador tenha dado ``CONFORME``.

Os testes anteriores à Wave 5 finalizavam direto. Em vez de afrouxar a regra
para eles continuarem passando — o que esconderia justamente o comportamento
novo —, eles passam a executar o mesmo ciclo que o operador executa no posto.
Este módulo é esse ciclo, em uma chamada.
"""

from __future__ import annotations

from mes.services.first_piece import FirstPieceService


def liberar_primeira_peca(
    db,
    operador="OPERADOR",
    *,
    op,
    setor,
    recurso,
    operacao,
    now_func=None,
    resultado="CONFORME",
):
    """Produz, aponta o Setup quando aplicável e inspeciona a primeira peça.

    Devolve o resultado da inspeção. Quando a operação está fora do portão
    (Corte, Destaque, Qualidade, INSPECAO ou marco terminal), devolve ``None``
    porque não há nada a liberar.
    """

    servico = FirstPieceService(db, operador, now_func=now_func)
    linha = servico.garantir(op=op, setor=setor, recurso=recurso, operacao=operacao)
    if linha is None:
        return None
    producao = servico.registrar_producao(
        op=op, setor=setor, recurso=recurso, operacao=operacao
    )
    if not producao.ok and producao.code != "primeira_peca_ja_aprovada":
        return producao
    if linha.get("setup_obrigatorio"):
        servico.marcar_setup(op=op, operacao=operacao)
    return servico.inspecionar(
        op=op,
        setor=setor,
        recurso=recurso,
        operacao=operacao,
        resultado=resultado,
    )


__all__ = ["liberar_primeira_peca"]
