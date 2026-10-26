"""SPC (controle estatístico) das cotas medidas pela Qualidade. SOMENTE LEITURA.

Funções puras, sem I/O: recebem as medidas que o ``QualityInspectionService``
já gravou (``qualidade_resultados_cota``) e devolvem cartas de controle e Cpk.
Nada aqui grava, altera regra de conformidade ou muda o fluxo do operador.

Decisões de desenho (documentadas porque são escolhas, não fatos):

* **Série** = produto + cota (sequência + descrição) + ``padrao_snapshot``.
  Revisões diferentes do padrão NUNCA se misturam.
* **Subgrupo** = peças da MESMA inspeção (OP) para aquela cota, em ordem de
  registro. Inspeção com mais de 10 peças é cortada em blocos de 5 (sobra de 1
  peça é anexada ao bloco anterior), para caber nas constantes da carta X-barra/R.
* **Tipo de carta**: mediana do tamanho dos subgrupos >= 2 -> X-barra/R
  (subgrupos de 1 peça ficam fora e são contados); senão -> valor individual /
  amplitude móvel (I-AM), com cada medida como um ponto.
* **Amostra mínima**: 20 medidas e 5 subgrupos (pontos, na carta I-AM). Abaixo
  disso: ``suficiente = False``, sem limites de controle e sem Cpk.
* **Cpk** usa σ DENTRO do subgrupo (R-barra/d2 ou AM-barra/1,128). É o Cpk
  "dentro da OP/lote", NUNCA a capacidade da máquina — ver ``ROTULO_CPK``. Na carta
  de valor individual o escopo é outro (``ESCOPO_CPK_INDIVIDUAL``): a variação é
  entre peças consecutivas e pode cruzar OPs.
* **Variação zero** (σ = 0): a série segue "suficiente", mas sem limites e sem sinais
  (``motivo_sem_limites``); com limites colapsados todo ponto viraria alarme.
* **Regras de sinal**: ponto fora dos limites (X e dispersão) e 7 pontos
  seguidos do mesmo lado da linha central (carta X / I).

Peças reprovadas também entram: a Qualidade mede todas as peças da OP, e
excluir as ruins esconderia justamente a variação que o SPC deve mostrar.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from datetime import datetime
from statistics import median
from typing import Iterable, Mapping

from mes.contracts import MetricValue
from mes.domain import DataAvailability
from mes.domain.quality_measures import parse_decimal, parse_tolerance


MIN_MEDIDAS = 20
MIN_SUBGRUPOS = 5
TAMANHO_BLOCO = 5
TAMANHO_MAX_SUBGRUPO = 10
SEQUENCIA_MESMO_LADO = 7
LIMITE_PADRAO_LINHAS = 20_000

ESCOPO_CPK = "dentro_da_op_lote"
ROTULO_CPK = "Cpk dentro da OP/lote (variação curta); não é a capacidade da máquina."
# Carta de valor individual: a variação vem de peças consecutivas, que podem cruzar OPs.
ESCOPO_CPK_INDIVIDUAL = "curto_prazo_pecas_consecutivas"
ROTULO_CPK_INDIVIDUAL = (
    "Cpk de curto prazo entre peças consecutivas (pode cruzar OPs); "
    "não é a capacidade da máquina."
)

# Constantes de carta de controle (ASTM/Montgomery), por tamanho de subgrupo n.
_D2 = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534, 7: 2.704, 8: 2.847, 9: 2.970, 10: 3.078}
_A2 = {2: 1.880, 3: 1.023, 4: 0.729, 5: 0.577, 6: 0.483, 7: 0.419, 8: 0.373, 9: 0.337, 10: 0.308}
_D3 = {2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0, 6: 0.0, 7: 0.076, 8: 0.136, 9: 0.184, 10: 0.223}
_D4 = {2: 3.267, 3: 2.574, 4: 2.282, 5: 2.114, 6: 2.004, 7: 1.924, 8: 1.864, 9: 1.816, 10: 1.777}

# Valor individual / amplitude móvel (n = 2 para a amplitude móvel).
_IMR_D2 = 1.128
_IMR_E2 = 2.66  # 3 / d2
_IMR_D4 = 3.267

TIPO_XBAR_R = "xbar_r"
TIPO_I_MR = "i_mr"

REGRA_FORA_LIMITES = "fora_dos_limites"
REGRA_SETE_MESMO_LADO = "sete_do_mesmo_lado"


# ---------------------------------------------------------------------------
# Auxiliares numéricos
# ---------------------------------------------------------------------------
def _media(valores) -> float:
    return math.fsum(valores) / len(valores)


def _desvio_amostral(valores) -> float | None:
    if len(valores) < 2:
        return None
    media = _media(valores)
    return math.sqrt(math.fsum((v - media) ** 2 for v in valores) / (len(valores) - 1))


def dividir_em_blocos(valores: list) -> list[list]:
    """Subgrupo com mais de 10 peças vira blocos de 5; sobra de 1 se anexa ao anterior."""

    if len(valores) <= TAMANHO_MAX_SUBGRUPO:
        return [list(valores)]
    blocos = [list(valores[i : i + TAMANHO_BLOCO]) for i in range(0, len(valores), TAMANHO_BLOCO)]
    if len(blocos) > 1 and len(blocos[-1]) == 1:
        blocos[-2].extend(blocos.pop())
    return blocos


def indices_mesmo_lado(valores, centro, minimo=SEQUENCIA_MESMO_LADO) -> list[int]:
    """Índices de todos os pontos de sequências de ``minimo``+ do mesmo lado do centro.

    Ponto exatamente sobre o centro não pertence a lado nenhum e interrompe a sequência.
    """

    marcados: list[int] = []
    corrida: list[int] = []
    lado_atual = 0
    for indice, valor in enumerate(valores):
        lado = (valor > centro) - (valor < centro)
        if lado != 0 and lado == lado_atual:
            corrida.append(indice)
        else:
            if len(corrida) >= minimo:
                marcados.extend(corrida)
            corrida = [indice] if lado != 0 else []
            lado_atual = lado
    if len(corrida) >= minimo:
        marcados.extend(corrida)
    return marcados


# ---------------------------------------------------------------------------
# Preparação das medidas
# ---------------------------------------------------------------------------
def _chave_ordem(linha: Mapping):
    registrada = linha.get("registrada_em")
    return (registrada is None, registrada or datetime.min, linha.get("peca_id") or 0)


def _subgrupos(linhas: list[dict]) -> list[list[dict]]:
    """Agrupa por inspeção (OP), na ordem da primeira peça; corta os grandes em blocos."""

    por_inspecao: "OrderedDict[object, list[dict]]" = OrderedDict()
    for linha in sorted(linhas, key=_chave_ordem):
        por_inspecao.setdefault(linha.get("inspecao_id"), []).append(linha)
    resultado: list[list[dict]] = []
    for pecas in por_inspecao.values():
        resultado.extend(dividir_em_blocos(pecas))
    return resultado


def _especificacao(padrao) -> dict | None:
    tolerancia = parse_tolerance(padrao)
    if tolerancia is None:
        return None
    referencia, margem = tolerancia
    return {
        "nominal": float(referencia),
        "margem": float(margem),
        "lsl": float(referencia - margem),
        "usl": float(referencia + margem),
    }


def _cpk(media, sigma, especificacao) -> tuple[MetricValue, float | None, float | None]:
    if especificacao["usl"] == especificacao["lsl"]:
        return (
            MetricValue(None, DataAvailability.NOT_APPLICABLE, None, "Padrão sem tolerância (margem zero): Cpk não se aplica."),
            None,
            None,
        )
    if not sigma or sigma <= 0:
        return (
            MetricValue(None, DataAvailability.INSUFFICIENT_DATA, None, "Sem variação dentro dos subgrupos: Cpk indeterminado."),
            None,
            None,
        )
    cpu = (especificacao["usl"] - media) / (3 * sigma)
    cpl = (media - especificacao["lsl"]) / (3 * sigma)
    return MetricValue(min(cpu, cpl), DataAvailability.AVAILABLE, None, None), cpu, cpl


def _ponto_base(indice, subgrupo: list[dict], n: int, media: float, amplitude: float | None) -> dict:
    primeira, ultima = subgrupo[0], subgrupo[-1]
    return {
        "indice": indice,
        "inspecao_id": primeira.get("inspecao_id"),
        "codigo_op": primeira.get("codigo_op"),
        "inicio": primeira.get("registrada_em"),
        "fim": ultima.get("registrada_em"),
        "n": n,
        "media": media,
        "amplitude": amplitude,
        "limites_x": None,
        "limites_dispersao": None,
        "fora_de_controle": [],
    }


def _limites(centro, meia_largura):
    return {"lcl": centro - meia_largura, "centro": centro, "ucl": centro + meia_largura}


def _sinais(pontos: list[dict], centro: float) -> None:
    """Preenche ``fora_de_controle`` de cada ponto (limites já calculados)."""

    for ponto in pontos:
        sinais = ponto["fora_de_controle"]
        lx, ld = ponto["limites_x"], ponto["limites_dispersao"]
        if lx and not lx["lcl"] <= ponto["media"] <= lx["ucl"]:
            sinais.append({"grafico": "x", "regra": REGRA_FORA_LIMITES})
        amplitude = ponto["amplitude"]
        if ld and amplitude is not None and not ld["lcl"] <= amplitude <= ld["ucl"]:
            sinais.append({"grafico": "dispersao", "regra": REGRA_FORA_LIMITES})
    for indice in indices_mesmo_lado([p["media"] for p in pontos], centro):
        pontos[indice]["fora_de_controle"].append(
            {"grafico": "x", "regra": REGRA_SETE_MESMO_LADO}
        )


# ---------------------------------------------------------------------------
# Análise de UMA série (produto + cota + revisão do padrão)
# ---------------------------------------------------------------------------
def analisar_serie(linhas: list[dict], especificacao: dict) -> dict:
    """Carta de controle + Cpk de uma série já filtrada e com valor numérico.

    ``linhas`` precisa trazer ``valor`` (float), ``inspecao_id``, ``peca_id`` e
    ``registrada_em``. Devolve sempre um dicionário; sem amostra suficiente os
    limites ficam ``None`` e o Cpk vem com ``availability = dados_insuficientes``.
    """

    subgrupos = _subgrupos(linhas)
    tamanhos = [len(s) for s in subgrupos]
    tipo = TIPO_XBAR_R if tamanhos and median(tamanhos) >= 2 else TIPO_I_MR

    if tipo == TIPO_XBAR_R:
        usados = [s for s in subgrupos if len(s) >= 2]
        descartados = len(subgrupos) - len(usados)
        valores_por_ponto = [[l["valor"] for l in s] for s in usados]
        grupos_ponto = usados
    else:
        ordenadas = sorted(linhas, key=_chave_ordem)
        usados = [[linha] for linha in ordenadas]
        descartados = 0
        valores_por_ponto = [[l["valor"]] for l in ordenadas]
        grupos_ponto = usados

    todos = [v for grupo in valores_por_ponto for v in grupo]
    n_medidas = len(todos)
    n_pontos = len(grupos_ponto)
    media = _media(todos) if todos else None
    resultado = {
        "tipo_grafico": tipo,
        "n_medidas": n_medidas,
        "n_subgrupos": n_pontos,
        "subgrupos_unitarios_descartados": descartados,
        "media": media,
        "desvio_geral": _desvio_amostral(todos),
        "sigma_dentro": None,
        "sigma_fonte": None,
        "especificacao": especificacao,
        "suficiente": False,
        "motivo_insuficiente": None,
        "motivo_sem_limites": None,
        "limites_x": None,
        "limites_dispersao": None,
        "cpk": None,
        "cpu": None,
        "cpl": None,
        "escopo_cpk": ESCOPO_CPK if tipo == TIPO_XBAR_R else ESCOPO_CPK_INDIVIDUAL,
        "rotulo_cpk": ROTULO_CPK if tipo == TIPO_XBAR_R else ROTULO_CPK_INDIVIDUAL,
        "pontos": [],
    }

    # Pontos sem limites (servem de carta de tendência mesmo com amostra curta).
    if tipo == TIPO_XBAR_R:
        pontos = [
            _ponto_base(i, g, len(g), _media(v), max(v) - min(v))
            for i, (g, v) in enumerate(zip(grupos_ponto, valores_por_ponto))
        ]
    else:
        pontos = []
        anterior = None
        for i, (g, v) in enumerate(zip(grupos_ponto, valores_por_ponto)):
            amplitude = abs(v[0] - anterior) if anterior is not None else None
            pontos.append(_ponto_base(i, g, 1, v[0], amplitude))
            anterior = v[0]
    resultado["pontos"] = pontos

    if n_medidas < MIN_MEDIDAS or n_pontos < MIN_SUBGRUPOS:
        resultado["motivo_insuficiente"] = (
            f"Amostra insuficiente: {n_medidas} medidas em {n_pontos} subgrupos "
            f"(mínimo {MIN_MEDIDAS} medidas e {MIN_SUBGRUPOS} subgrupos)."
        )
        resultado["cpk"] = MetricValue(
            None, DataAvailability.INSUFFICIENT_DATA, None, resultado["motivo_insuficiente"]
        )
        return resultado

    resultado["suficiente"] = True
    if tipo == TIPO_XBAR_R:
        sigma = _media([p["amplitude"] / _D2[p["n"]] for p in pontos])
        resultado["sigma_fonte"] = "R-barra/d2 (dentro dos subgrupos)"
        if sigma > 0:
            for p in pontos:
                amplitude_esperada = _D2[p["n"]] * sigma
                p["limites_x"] = _limites(media, _A2[p["n"]] * amplitude_esperada)
                p["limites_dispersao"] = {
                    "lcl": _D3[p["n"]] * amplitude_esperada,
                    "centro": amplitude_esperada,
                    "ucl": _D4[p["n"]] * amplitude_esperada,
                }
            if len({p["n"] for p in pontos}) == 1:
                resultado["limites_x"] = pontos[0]["limites_x"]
                resultado["limites_dispersao"] = pontos[0]["limites_dispersao"]
    else:
        amplitudes = [p["amplitude"] for p in pontos if p["amplitude"] is not None]
        am_barra = _media(amplitudes)
        sigma = am_barra / _IMR_D2
        resultado["sigma_fonte"] = "amplitude móvel/1,128 (peças consecutivas)"
        if sigma > 0:
            limites_x = _limites(media, _IMR_E2 * am_barra)
            limites_am = {"lcl": 0.0, "centro": am_barra, "ucl": _IMR_D4 * am_barra}
            for p in pontos:
                p["limites_x"] = limites_x
                p["limites_dispersao"] = limites_am
            resultado["limites_x"] = limites_x
            resultado["limites_dispersao"] = limites_am

    resultado["sigma_dentro"] = sigma
    if sigma > 0:
        _sinais(pontos, media)
    else:
        # Instrumento/arredondamento sem resolução para ver variação curta: limites
        # colapsariam na média e marcariam TODO ponto. Sem limites, sem sinais.
        resultado["motivo_sem_limites"] = (
            "Sem variação dentro dos subgrupos (a resolução da medição não mostra "
            "diferença entre peças da mesma OP): limites de controle não calculados."
        )
    cpk, cpu, cpl = _cpk(media, sigma, especificacao)
    resultado["cpk"], resultado["cpu"], resultado["cpl"] = cpk, cpu, cpl
    return resultado


# ---------------------------------------------------------------------------
# Entrada: linhas do repositório -> séries
# ---------------------------------------------------------------------------
def analisar_medicoes(linhas: Iterable[Mapping]) -> dict:
    """Agrupa as medidas por produto + cota + padrão e analisa cada série.

    ``linhas``: dicionários de ``listar_medidas_spc`` (produto_codigo, sequencia,
    descricao_snapshot, padrao_snapshot, medida, inspecao_id, peca_id,
    registrada_em, codigo_op). Padrão ou medida não numéricos são ignorados e
    contados — nunca viram número inventado.
    """

    ignoradas = {"padrao_nao_numerico": 0, "medida_invalida": 0}
    grupos: "OrderedDict[tuple, dict]" = OrderedDict()
    for linha in sorted(linhas, key=lambda l: (str(l.get("produto_codigo") or ""),
                                              int(l.get("sequencia") or 0),
                                              str(l.get("padrao_snapshot") or ""),
                                              *_chave_ordem(l))):
        especificacao = _especificacao(linha.get("padrao_snapshot"))
        if especificacao is None:
            ignoradas["padrao_nao_numerico"] += 1
            continue
        valor = parse_decimal(linha.get("medida"))
        if valor is None:
            ignoradas["medida_invalida"] += 1
            continue
        chave = (
            linha.get("produto_codigo"),
            int(linha.get("sequencia") or 0),
            linha.get("descricao_snapshot") or "",
            linha.get("padrao_snapshot"),
        )
        grupo = grupos.setdefault(chave, {"especificacao": especificacao, "linhas": []})
        grupo["linhas"].append({**linha, "valor": float(valor)})

    series = []
    for (produto, sequencia, descricao, padrao), grupo in grupos.items():
        analise = analisar_serie(grupo["linhas"], grupo["especificacao"])
        analise["cpk"] = analise["cpk"].to_dict()
        series.append(
            {
                "produto": produto,
                "cota": {"sequencia": sequencia, "descricao": descricao or None, "unidade": "mm"},
                "padrao_snapshot": padrao,
                **analise,
            }
        )
    return {
        "escopo_cpk": ESCOPO_CPK,
        "rotulo_cpk": ROTULO_CPK,
        "amostra_minima": {"medidas": MIN_MEDIDAS, "subgrupos": MIN_SUBGRUPOS},
        "ignoradas": ignoradas,
        "series": series,
    }


__all__ = [
    "ESCOPO_CPK",
    "ESCOPO_CPK_INDIVIDUAL",
    "LIMITE_PADRAO_LINHAS",
    "MIN_MEDIDAS",
    "MIN_SUBGRUPOS",
    "ROTULO_CPK",
    "ROTULO_CPK_INDIVIDUAL",
    "analisar_medicoes",
    "analisar_serie",
    "dividir_em_blocos",
    "indices_mesmo_lado",
]
