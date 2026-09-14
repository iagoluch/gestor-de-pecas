"""Conformidade dimensional calculada pelo backend.

A decisão "CONFORME / NÃO CONFORME" é aritmética, não é opinião do operador:

    limite_inferior = referencia - margem
    limite_superior = referencia + margem
    CONFORME  <=>  limite_inferior <= medicao <= limite_superior

Este módulo é a única autoridade sobre essa conta. O operador informa apenas a
medida; a interface só apresenta o resultado e os limites que vieram daqui.

A unidade de cota é fixa em ``mm`` desde a Wave 1, então a comparação é feita
sem conversão. A aritmética usa ``Decimal`` de propósito: com ``float``, um
padrão ``12,0 +/- 0,2`` recusaria a medida exatamente no limite ``12,2`` por
erro de representação binária. O limite pertence à faixa.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.quality import (
    QUALITY_MEASURE_CONFORMING,
    QUALITY_MEASURE_NON_CONFORMING,
    normalize_measure_status,
)


#: Unidade única das cotas (Wave 1). Não há conversão de unidade em lugar algum.
QUALITY_MEASURE_UNIT = "mm"

#: Separadores aceitos entre a referência e a margem do padrão cadastrado.
#: São formas de escrita da mesma informação — não é reconhecimento por
#: semelhança: qualquer outro texto simplesmente não é numérico.
_TOLERANCE_SEPARATORS = ("+/-", "+-", "±")

_NUMBER = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


def parse_decimal(value) -> Decimal | None:
    """Converte um número escrito com vírgula ou ponto. ``None`` se não for."""

    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    text = str(value if value is not None else "").strip()
    if not text or not _NUMBER.match(text):
        return None
    try:
        return Decimal(text.replace(",", "."))
    except InvalidOperation:  # pragma: no cover - _NUMBER já filtra
        return None


def parse_tolerance(padrao) -> tuple[Decimal, Decimal] | None:
    """Extrai ``(referencia, margem)`` do padrão cadastrado da cota.

    Aceita ``"1200,0 +/- 1,0"``, ``"12.0 ± 0.2"`` e o padrão sem margem
    (``"453"``), que significa margem zero. Um padrão que não seja numérico
    devolve ``None`` e o cálculo automático não se aplica àquela cota.
    """

    text = str(padrao or "").strip()
    if not text:
        return None
    for separator in _TOLERANCE_SEPARATORS:
        if separator in text:
            reference_text, _, margin_text = text.partition(separator)
            reference = parse_decimal(reference_text)
            margin = parse_decimal(margin_text)
            if reference is None or margin is None:
                return None
            return reference, abs(margin)
    reference = parse_decimal(text)
    return (reference, Decimal(0)) if reference is not None else None


@dataclass(frozen=True)
class MeasureEvaluation:
    """Resultado da avaliação de uma cota, com a conta exposta."""

    status: str
    calculado: bool
    referencia: Decimal | None = None
    margem: Decimal | None = None
    limite_inferior: Decimal | None = None
    limite_superior: Decimal | None = None
    medida: Decimal | None = None
    unidade: str = QUALITY_MEASURE_UNIT

    def as_public(self) -> dict:
        """Campos que a interface apresenta sem recalcular nada."""

        def number(value):
            return float(value) if value is not None else None

        return {
            "status": self.status,
            "conformidade_calculada": self.calculado,
            "referencia": number(self.referencia),
            "margem": number(self.margem),
            "limite_inferior": number(self.limite_inferior),
            "limite_superior": number(self.limite_superior),
            "medida_numerica": number(self.medida),
            "unidade": self.unidade,
        }


def evaluate_measure(medida, padrao) -> MeasureEvaluation:
    """Calcula a conformidade da medida contra o padrão da cota.

    ``calculado`` falso significa que a conta não se aplica — padrão ou medida
    não numéricos. Nesse caso o chamador decide o que fazer; este módulo não
    inventa um status.
    """

    tolerance = parse_tolerance(padrao)
    measured = parse_decimal(medida)
    if tolerance is None or measured is None:
        return MeasureEvaluation("", False, medida=measured)
    reference, margin = tolerance
    lower = reference - margin
    upper = reference + margin
    status = (
        QUALITY_MEASURE_CONFORMING
        if lower <= measured <= upper
        else QUALITY_MEASURE_NON_CONFORMING
    )
    return MeasureEvaluation(
        status,
        True,
        referencia=reference,
        margem=margin,
        limite_inferior=lower,
        limite_superior=upper,
        medida=measured,
    )


def cota_publica(cota) -> dict:
    """Cota do template com os limites já calculados pelo backend.

    A tela mostra a faixa; ela não a recalcula, e o operador não escolhe mais
    o status da cota — ele só informa a medida.
    """

    dados = dict(cota or {})
    tolerancia = parse_tolerance(dados.get("padrao"))
    referencia, margem = tolerancia if tolerancia else (None, None)
    return {
        "id": dados.get("id"),
        "sequencia": int(dados.get("sequencia") or 0),
        "descricao": dados.get("descricao"),
        "padrao": dados.get("padrao"),
        "unidade": QUALITY_MEASURE_UNIT,
        "referencia": float(referencia) if referencia is not None else None,
        "margem": float(margem) if margem is not None else None,
        "limite_inferior": float(referencia - margem) if tolerancia else None,
        "limite_superior": float(referencia + margem) if tolerancia else None,
        "conformidade_automatica": tolerancia is not None,
    }


def template_publico(template) -> dict | None:
    """Projeção estável do template para a UI, sem expor colunas internas."""

    if not template:
        return None
    return {
        "id": template.get("id"),
        "produto": template.get("produto_codigo"),
        "revisao": int(template.get("revisao") or 1),
        "atualizado_por": template.get("atualizado_por_nome")
        or template.get("criado_por_nome"),
        "atualizado_em": template.get("atualizado_em"),
        "cotas": [cota_publica(cota) for cota in (template.get("cotas") or ())],
    }


@dataclass(frozen=True)
class ChecklistError:
    """Recusa do checklist, com o código canônico e a frase do operador."""

    code: str
    message: str


def resolve_checklist_measures(
    cotas_template, medidas
) -> tuple[list[dict] | None, ChecklistError | None]:
    """Casa cada cota do template com a medida informada, sem curinga.

    Autoridade única da Wave 5.1 sobre "que medida pertence a que cota e qual é
    o status dela". A inspeção dimensional da Qualidade e o portão da primeira
    peça consomem esta mesma função — a conta não pode existir em duas versões.

    O status enviado pelo cliente só é considerado quando o padrão da cota não
    é numérico (templates legados em texto livre), porque aí não existe faixa
    para comparar.
    """

    informadas: dict[int, dict] = {}
    for item in medidas or ():
        dados = dict(item or {})
        try:
            sequencia = int(dados.get("sequencia"))
        except (TypeError, ValueError):
            return None, ChecklistError(
                "qualidade_medida_invalida",
                "A identificação da cota medida é inválida.",
            )
        informadas[sequencia] = dados
    resolvidas = []
    for cota in cotas_template or ():
        dados_cota = dict(cota or {})
        sequencia = int(dados_cota.get("sequencia") or 0)
        dados = informadas.pop(sequencia, None)
        if dados is None:
            return None, ChecklistError(
                "qualidade_medida_ausente",
                f"Informe a medida da Cota {sequencia}.",
            )
        medida = str(dados.get("medida") or "").strip()[:60]
        if not medida:
            return None, ChecklistError(
                "qualidade_medida_ausente",
                f"Informe a medida da Cota {sequencia}.",
            )
        avaliacao = evaluate_measure(medida, dados_cota.get("padrao"))
        if avaliacao.calculado:
            status = avaliacao.status
        else:
            status = normalize_measure_status(dados.get("status"))
            if not status:
                return None, ChecklistError(
                    "qualidade_status_cota_invalido",
                    f"Marque a Cota {sequencia} como Conforme ou Não conforme.",
                )
        resolvidas.append(
            {
                "cota_template_id": dados_cota.get("id"),
                "sequencia": sequencia,
                "descricao": dados_cota.get("descricao"),
                # O padrão vira snapshot: uma edição futura do template não
                # pode mudar o critério de uma inspeção já registrada.
                "padrao": dados_cota.get("padrao"),
                "unidade": QUALITY_MEASURE_UNIT,
                "medida": medida,
                "status": status,
                "avaliacao": avaliacao.as_public(),
            }
        )
    if informadas:
        desconhecidas = ", ".join(str(item) for item in sorted(informadas))
        return None, ChecklistError(
            "qualidade_cota_desconhecida",
            f"Cota fora do template do produto: {desconhecidas}.",
        )
    return resolvidas, None


__all__ = [
    "ChecklistError",
    "MeasureEvaluation",
    "QUALITY_MEASURE_UNIT",
    "cota_publica",
    "evaluate_measure",
    "parse_decimal",
    "parse_tolerance",
    "resolve_checklist_measures",
    "template_publico",
]
