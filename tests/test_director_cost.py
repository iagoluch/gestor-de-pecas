"""Fórmula do custo da aba Diretoria (16/10/2026): horas x (R$/h do recurso + R$/h das pessoas).

Sem banco: função pura sobre estruturas simples.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from mes.domain.director_cost import (
    CostRates,
    CostResult,
    StopSlice,
    stop_cost,
    work_cost,
)

T0 = datetime(2026, 10, 16, 8, 0, 0)


def _slice(recurso: str, horas: float, pessoas: tuple[str, ...], inicio: datetime = T0) -> StopSlice:
    return StopSlice(
        recurso=recurso,
        inicio=inicio,
        fim=inicio + timedelta(hours=horas),
        pessoas=pessoas,
    )


def test_parada_de_2h_recurso_100_duas_pessoas_50_custa_400() -> None:
    stops = [_slice("CORTE-1", 2, ("123", "456"))]
    rates = CostRates(
        recurso={"CORTE-1": Decimal("100")},
        pessoa={"123": Decimal("50"), "456": Decimal("50")},
    )

    result = stop_cost(stops, rates)

    assert result.horas == 2.0
    assert result.custo == Decimal("400.00")
    assert result.completo is True
    assert result.recursos_sem_custo == ()
    assert result.pessoas_sem_custo == ()


def test_recurso_sem_custo_marca_incompleto_e_lista_o_recurso() -> None:
    stops = [_slice("CORTE-1", 2, ("123", "456"))]
    rates = CostRates(
        recurso={},
        pessoa={"123": Decimal("50"), "456": Decimal("50")},
    )

    result = stop_cost(stops, rates)

    assert result.custo == Decimal("200.00")
    assert result.completo is False
    assert result.recursos_sem_custo == ("CORTE-1",)
    assert result.pessoas_sem_custo == ()


def test_pessoa_sem_custo_marca_incompleto_e_lista_a_pessoa() -> None:
    stops = [_slice("CORTE-1", 2, ("123", "999"))]
    rates = CostRates(
        recurso={"CORTE-1": Decimal("100")},
        pessoa={"123": Decimal("50")},
    )

    result = stop_cost(stops, rates)

    assert result.custo == Decimal("300.00")
    assert result.completo is False
    assert result.recursos_sem_custo == ()
    assert result.pessoas_sem_custo == ("999",)


def test_sem_paradas_devolve_zero_horas_zero_reais_completo() -> None:
    rates = CostRates(recurso={}, pessoa={})

    result = stop_cost([], rates)

    assert result == CostResult(0.0, Decimal("0.00"), True, (), ())


def test_mesma_pessoa_duas_vezes_no_mesmo_trecho_conta_uma_vez() -> None:
    stops = [_slice("CORTE-1", 2, ("123", "123"))]
    rates = CostRates(
        recurso={"CORTE-1": Decimal("100")},
        pessoa={"123": Decimal("50")},
    )

    result = stop_cost(stops, rates)

    assert result.custo == Decimal("300.00")
    assert result.completo is True


def test_cracha_e_recurso_sao_normalizados_com_strip_e_maiusculas() -> None:
    stops = [_slice("  corte-1 ", 1, (" 123 ",))]
    rates = CostRates(
        recurso={"CORTE-1": Decimal("100")},
        pessoa={"123": Decimal("50")},
    )

    result = stop_cost(stops, rates)

    assert result.custo == Decimal("150.00")
    assert result.completo is True


def test_duracao_negativa_ou_zero_conta_zero_horas() -> None:
    stops = [
        _slice("CORTE-1", -1, ("123",)),
        _slice("CORTE-1", 0, ("123",)),
    ]
    rates = CostRates(
        recurso={"CORTE-1": Decimal("100")},
        pessoa={"123": Decimal("50")},
    )

    result = stop_cost(stops, rates)

    assert result.horas == 0.0
    assert result.custo == Decimal("0.00")


def test_custo_arredonda_meio_para_cima_so_na_saida() -> None:
    stops = [_slice("CORTE-1", 1, ())]
    rates = CostRates(recurso={"CORTE-1": Decimal("0.125")}, pessoa={})

    result = stop_cost(stops, rates)

    assert result.custo == Decimal("0.13")


def test_listas_de_faltantes_sao_deduplicadas_e_ordenadas() -> None:
    stops = [
        _slice("ZETA", 1, ("999", "111")),
        _slice("ALFA", 1, ("999",), inicio=T0 + timedelta(hours=2)),
    ]
    rates = CostRates(recurso={}, pessoa={})

    result = stop_cost(stops, rates)

    assert result.recursos_sem_custo == ("ALFA", "ZETA")
    assert result.pessoas_sem_custo == ("111", "999")


def test_work_cost_usa_a_mesma_formula_de_stop_cost() -> None:
    stops = [_slice("CORTE-1", 2, ("123", "456"))]
    rates = CostRates(
        recurso={"CORTE-1": Decimal("100")},
        pessoa={"123": Decimal("50"), "456": Decimal("50")},
    )

    assert work_cost(stops, rates) == stop_cost(stops, rates)
