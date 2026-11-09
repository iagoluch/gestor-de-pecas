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
    nivel_inspecao=None,
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
    if nivel_inspecao is not None:
        definir_nivel_inspecao(
            db, linha.get("produto_codigo"), linha.get("numero_operacao"), nivel_inspecao
        )
    inspecao = servico.inspecionar(
        op=op,
        setor=setor,
        recurso=recurso,
        operacao=operacao,
        resultado=resultado,
    )
    if inspecao.ok:
        medir_pecas_restantes(db, (inspecao.data or {}).get("registro"), operador)
    return inspecao


def definir_nivel_inspecao(db, produto, operacao, nivel):
    """Nível da inspeção progressiva do produto + operação (começa em 5).

    Nível 1 = só a 1ª peça: os testes de quantidade usam para que a inspeção
    some exatamente 1 peça boa ao total.
    """

    chave = (str(produto or "").strip(), str(operacao or "").strip())
    if hasattr(db, "progressive_levels"):
        db.progressive_levels[chave] = int(nivel)
        return
    with db.connection() as conexao, conexao.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO qualidade_inspecao_progressiva_nivel (produto_codigo, numero_operacao, nivel)
            VALUES (%s, %s, %s)
            ON CONFLICT (produto_codigo, numero_operacao) DO UPDATE SET nivel = EXCLUDED.nivel
            """,
            (*chave, int(nivel)),
        )


def medir_pecas_restantes(db, primeira_peca, operador="OPERADOR"):
    """Grava as peças conformes que faltam da inspeção progressiva.

    Patch 09/11/2026: na Caldeiraria (Dobra/Usinagem/Serra) a aprovação da
    1ª peça fixa N e o lote só libera com as N medições, que o checklist grava
    peça a peça (regras em ``tests/test_inspecao_progressiva.py``). Os testes
    que só precisam do lote liberado gravam aqui as que faltam. Setor sem
    inspeção progressiva (N vazio) não grava nada.
    """

    dados = dict(primeira_peca or {})
    if dados.get("inspecao_pecas_exigidas") is None:
        return
    for _ in range(int(dados["inspecao_pecas_exigidas"])):
        gravada = db.registrar_peca_inspecao_progressiva(
            dados["id"], conforme=True, medidas=[], operador=operador
        )
        if gravada is None:
            return


__all__ = ["definir_nivel_inspecao", "liberar_primeira_peca", "medir_pecas_restantes"]
