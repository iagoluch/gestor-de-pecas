"""Solda em três níveis: Setor -> Produto -> Subconjunto (fase 1, 11/11/2026).

Classifica cada operação da fila pelo código do item (exato, só sem espaços nas
pontas). Nunca há fallback silencioso: sem vínculo, vínculo ambíguo ou destino
inativo viram pendência. Classificar não inicia tempo nem altera apontamento.
"""

from __future__ import annotations

PRODUTO_SEM_VINCULO = "produto_sem_vinculo"
PRODUTO_AMBIGUO = "produto_ambiguo"
SUBCONJUNTO_SEM_VINCULO = "subconjunto_sem_vinculo"
SUBCONJUNTO_AMBIGUO = "subconjunto_ambiguo"
DESTINO_INATIVO = "destino_inativo"

MOTIVOS = {
    PRODUTO_SEM_VINCULO: "Produto sem vínculo",
    PRODUTO_AMBIGUO: "Produto ambíguo",
    SUBCONJUNTO_SEM_VINCULO: "Subconjunto sem vínculo",
    SUBCONJUNTO_AMBIGUO: "Subconjunto ambíguo",
    DESTINO_INATIVO: "Destino inativo",
}


def _codigo(valor):
    return str(valor or "").strip()


def classificar(codigo_item, mapa):
    """Devolve ``{"produto_id", "subconjunto_id", "motivo"}``.

    ``motivo`` é None quando a operação caiu num subconjunto ativo. Com
    ``subconjunto_sem_vinculo`` o produto é conhecido (pendência dentro dele).
    """

    codigo = _codigo(codigo_item)
    produtos = {p["id"]: p for p in mapa["produtos"]}
    subconjuntos = {s["id"]: s for s in mapa["subconjuntos"]}
    achados = [v for v in mapa["vinculos"] if codigo and _codigo(v["codigo_item"]) == codigo]
    if len({v["produto_id"] for v in achados}) > 1:
        return _resultado(None, None, PRODUTO_AMBIGUO)

    no_sub = [v for v in achados if v["subconjunto_id"] is not None]
    if no_sub:
        produto_id = no_sub[0]["produto_id"]
        if len({v["subconjunto_id"] for v in no_sub}) > 1:
            return _resultado(produto_id, None, SUBCONJUNTO_AMBIGUO)
        sub = subconjuntos.get(no_sub[0]["subconjunto_id"])
        if not sub or not sub["ativo"] or not produtos.get(produto_id, {}).get("ativo"):
            return _resultado(produto_id, None, DESTINO_INATIVO)
        return _resultado(produto_id, sub["id"], None)

    if achados:
        produto_id = achados[0]["produto_id"]
        if not produtos.get(produto_id, {}).get("ativo"):
            return _resultado(produto_id, None, DESTINO_INATIVO)
        return _resultado(produto_id, None, SUBCONJUNTO_SEM_VINCULO)
    return _resultado(None, None, PRODUTO_SEM_VINCULO)


def _resultado(produto_id, subconjunto_id, motivo):
    return {"produto_id": produto_id, "subconjunto_id": subconjunto_id, "motivo": motivo}


def fila_do_setor(service, setor, recursos):
    """Fila única do setor: une as estações e tira repetidos pela identidade da operação."""

    vistos, fila = set(), []
    for recurso in recursos:
        for card in service.listar_cartoes(setor, recurso)["queue"]:
            chave = card.get("catalogo_operacao_id") or (card.get("op"), card.get("operation"))
            if chave in vistos:
                continue
            vistos.add(chave)
            fila.append(card)
    return fila


def _contagem(cards):
    return {"operacoes": len(cards), "ops": len({c.get("op") for c in cards if c.get("op")})}


def _pendencia(card, motivo):
    return {
        "op": card.get("op"),
        "produto_codigo": _codigo(card.get("product")),
        "operacao": card.get("operation"),
        "motivo": motivo,
        "motivo_texto": MOTIVOS[motivo],
    }


def montar_mapa(mapa, fila):
    """Contagens por produto/subconjunto + pendências. Cada operação conta uma vez só."""

    por_produto, por_sub, pend_setor, pend_produto = {}, {}, [], {}
    for card in fila:
        r = classificar(card.get("product"), mapa)
        if r["motivo"] is None:
            por_sub.setdefault(r["subconjunto_id"], []).append(card)
            por_produto.setdefault(r["produto_id"], []).append(card)
        elif r["produto_id"] is not None and r["motivo"] != PRODUTO_AMBIGUO:
            pend_produto.setdefault(r["produto_id"], []).append(_pendencia(card, r["motivo"]))
            por_produto.setdefault(r["produto_id"], [])
        else:
            pend_setor.append(_pendencia(card, r["motivo"]))

    produtos = []
    for p in mapa["produtos"]:
        subs = [s for s in mapa["subconjuntos"] if s["produto_id"] == p["id"]]
        produtos.append({
            **p,
            **_contagem(por_produto.get(p["id"], [])),
            "pendencias": pend_produto.get(p["id"], []),
            "subconjuntos": [
                {
                    **s,
                    **_contagem(por_sub.get(s["id"], [])),
                    "codigos": [v for v in mapa["vinculos"] if v["subconjunto_id"] == s["id"]],
                }
                for s in subs
            ],
            "codigos": [
                v for v in mapa["vinculos"]
                if v["produto_id"] == p["id"] and v["subconjunto_id"] is None
            ],
        })
    total_pend = len(pend_setor) + sum(len(v) for v in pend_produto.values())
    return {
        "produtos": produtos,
        "pendencias": pend_setor,
        "totais": {**_contagem(fila), "pendencias": total_pend},
    }
