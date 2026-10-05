"""Testes unitários de casos de borda para parse_decimal, parse_tolerance e evaluate_measure.

Estes testes complementam test_wave5_1.py cobrindo casos não exercidos lá.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

from mes.domain.quality_measures import (
    evaluate_measure,
    parse_decimal,
    parse_tolerance,
)


def parametrize(nomes, casos):
    """Equivalente mínimo de pytest.mark.parametrize usando subTest (o CI roda unittest)."""
    chaves = [n.strip() for n in nomes.split(",")]

    def decorador(teste):
        def executar(self):
            for caso in casos:
                with self.subTest(caso=caso):
                    teste(self, *(caso if len(chaves) > 1 else (caso,)))

        executar.__name__ = teste.__name__
        return executar

    return decorador


class TestParseDecimalEdgeCases(unittest.TestCase):
    """Casos de borda de parse_decimal não cobertos em test_wave5_1.py."""

    @parametrize(
        "entrada, esperado",
        [
            ("+12,5", Decimal("12.5")),
            ("+12.5", Decimal("12.5")),
            ("+453", Decimal("453")),
        ],
    )
    def test_numero_com_sinal_positivo_explicito(self, entrada, esperado):
        assert parse_decimal(entrada) == esperado

    @parametrize(
        "entrada",
        [
            "12,3,4",
            "12..5",
            ",5",
            "5.",
            "  ,  ",
            "1e5",
            "1E5",
            "1,2e3",
            "inf",
            "-inf",
            "nan",
            "NaN",
        ],
    )
    def test_textos_nao_numericos_variados_retornam_none(self, entrada):
        assert parse_decimal(entrada) is None

    def test_decimal_ja_e_decimal_retorna_o_mesmo_objeto(self):
        valor = Decimal("12.5")
        assert parse_decimal(valor) is valor

    def test_int_retorna_decimal_equivalente(self):
        assert parse_decimal(42) == Decimal(42)


class TestParseToleranceEdgeCases(unittest.TestCase):
    """Casos de borda de parse_tolerance não cobertos em test_wave5_1.py."""

    @parametrize(
        "padrao, ref_esperada, margem_esperada",
        [
            ("12,0 +/- 0,2", Decimal("12.0"), Decimal("0.2")),
            ("12,0 +- 0,2", Decimal("12.0"), Decimal("0.2")),
            ("12,0 ± 0,2", Decimal("12.0"), Decimal("0.2")),
            ("12.0 +/- 0.2", Decimal("12.0"), Decimal("0.2")),
            ("12.0 +- 0.2", Decimal("12.0"), Decimal("0.2")),
            ("12.0 ± 0.2", Decimal("12.0"), Decimal("0.2")),
        ],
    )
    def test_todos_os_separadores_suportados(self, padrao, ref_esperada, margem_esperada):
        ref, margem = parse_tolerance(padrao)
        assert ref == ref_esperada
        assert margem == margem_esperada

    def test_padrao_sem_margem_margem_zero(self):
        ref, margem = parse_tolerance("453")
        assert ref == Decimal("453")
        assert margem == Decimal("0")

        ref, margem = parse_tolerance("453.0")
        assert ref == Decimal("453.0")
        assert margem == Decimal("0")

    @parametrize(
        "padrao",
        [
            "12,0 +/- -0,2",
            "12,0 +- -0,2",
            "12,0 ± -0,2",
        ],
    )
    def test_margem_negativa_vira_absoluto_com_todos_separadores(self, padrao):
        ref, margem = parse_tolerance(padrao)
        assert ref == Decimal("12.0")
        assert margem == Decimal("0.2")

    @parametrize(
        "padrao",
        [
            "",
            "   ",
            None,
        ],
    )
    def test_padrao_vazio_none_espacos_retorna_none(self, padrao):
        assert parse_tolerance(padrao) is None

    @parametrize(
        "padrao",
        [
            "12,0 +/- abc",
            "abc +/- 0,2",
            "12,0 +/- ",
            " +/- 0,2",
            "12,0 +/- 0,2 extra",
        ],
    )
    def test_padrao_com_parte_invalida_retorna_none(self, padrao):
        assert parse_tolerance(padrao) is None

    def test_referencia_negativa_com_margem(self):
        ref, margem = parse_tolerance("-5,0 +/- 0,5")
        assert ref == Decimal("-5.0")
        assert margem == Decimal("0.5")


class TestEvaluateMeasureEdgeCases(unittest.TestCase):
    """Casos de borda de evaluate_measure não cobertos em test_wave5_1.py.

    O limite pertence à faixa: limite_inferior <= medida <= limite_superior.
    """

    PADRAO = "12,0 +/- 0,2"  # faixa 11,8 .. 12,2

    @parametrize(
        "medida, status_esperado",
        [
            ("11,8", "CONFORME"),   # exatamente no limite inferior
            ("12,2", "CONFORME"),   # exatamente no limite superior
            ("11,79", "NAO_CONFORME"),
            ("12,21", "NAO_CONFORME"),
        ],
    )
    def test_limites_pertencem_a_faixa(self, medida, status_esperado):
        avaliacao = evaluate_measure(medida, self.PADRAO)
        assert avaliacao.calculado is True
        assert avaliacao.status == status_esperado
        assert avaliacao.limite_inferior == Decimal("11.8")
        assert avaliacao.limite_superior == Decimal("12.2")

    def test_padrao_sem_margem_exige_exatidao(self):
        avaliacao = evaluate_measure("453", "453")
        assert avaliacao.calculado is True
        assert avaliacao.status == "CONFORME"
        assert avaliacao.margem == Decimal("0")
        assert avaliacao.limite_inferior == Decimal("453")
        assert avaliacao.limite_superior == Decimal("453")

        avaliacao = evaluate_measure("453,1", "453")
        assert avaliacao.calculado is True
        assert avaliacao.status == "NAO_CONFORME"

    def test_referencia_negativa_com_limites(self):
        # padrão -5,0 +/- 0,5 -> faixa -5,5 .. -4,5
        avaliacao = evaluate_measure("-5,5", "-5,0 +/- 0,5")
        assert avaliacao.calculado is True
        assert avaliacao.status == "CONFORME"
        assert avaliacao.limite_inferior == Decimal("-5.5")
        assert avaliacao.limite_superior == Decimal("-4.5")

        avaliacao = evaluate_measure("-4,5", "-5,0 +/- 0,5")
        assert avaliacao.calculado is True
        assert avaliacao.status == "CONFORME"

        avaliacao = evaluate_measure("-5,6", "-5,0 +/- 0,5")
        assert avaliacao.calculado is True
        assert avaliacao.status == "NAO_CONFORME"

        avaliacao = evaluate_measure("-4,4", "-5,0 +/- 0,5")
        assert avaliacao.calculado is True
        assert avaliacao.status == "NAO_CONFORME"

    def test_medida_ou_padrao_nao_numerico_calculado_falso(self):
        avaliacao = evaluate_measure("12,1", "conforme gabarito")
        assert avaliacao.calculado is False
        assert avaliacao.status == ""

        avaliacao = evaluate_measure("abc", self.PADRAO)
        assert avaliacao.calculado is False

        avaliacao = evaluate_measure(None, self.PADRAO)
        assert avaliacao.calculado is False

    def test_medida_com_ponto_e_virgula_produzem_mesmo_resultado(self):
        a1 = evaluate_measure("12.1", "12.0 ± 0.2")
        a2 = evaluate_measure("12,1", "12,0 +/- 0,2")
        assert a1.status == a2.status
        assert a1.limite_inferior == a2.limite_inferior
        assert a1.limite_superior == a2.limite_superior

    def test_avaliacao_expõe_campos_corretos(self):
        avaliacao = evaluate_measure("12,1", "12,0 +/- 0,2")
        assert avaliacao.referencia == Decimal("12.0")
        assert avaliacao.margem == Decimal("0.2")
        assert avaliacao.limite_inferior == Decimal("11.8")
        assert avaliacao.limite_superior == Decimal("12.2")
        assert avaliacao.medida == Decimal("12.1")
        assert avaliacao.unidade == "mm"

    def test_as_public_converte_para_float(self):
        avaliacao = evaluate_measure("12,1", "12,0 +/- 0,2")
        public = avaliacao.as_public()
        assert public["referencia"] == 12.0
        assert public["margem"] == 0.2
        assert public["limite_inferior"] == 11.8
        assert public["limite_superior"] == 12.2
        assert public["medida_numerica"] == 12.1
        assert public["unidade"] == "mm"
        assert public["conformidade_calculada"] is True