"""Cenários C01–C20 da Metodologia de Tempos e Rateios V2 (Manufatura, 13/11/2026).

Cada teste reproduz a tabela do documento: HM e HH por OP, em minutos.
"""

import random
import unittest
from datetime import datetime, timedelta

from mes.analytics.rateio import (
    REASON_CONFLICT,
    REASON_PENDING,
    REASON_PROPOSED,
    allocate_by_badge,
    participation_rows,
)


def t(hhmm):
    hour, minute = hhmm.split(":")
    return datetime(2026, 11, 13, int(hour), int(minute))


def span(start, end):
    return (t(start), t(end))


def minutes(values):
    return {key: round(value / 60, 6) for key, value in values.items() if value}


def run(executions, participations):
    """executions: {op: (recurso, [(ini, fim), ...])}; participations: [(op, crachá, ini, fim)]."""

    return allocate_by_badge(
        [(op, resource, [span(*item) for item in spans]) for op, (resource, spans) in executions.items()],
        [(op, badge, t(start), t(end) if end else None) for op, badge, start, end in participations],
    )


class CenariosDoDocumento(unittest.TestCase):
    def check(self, result, hm, hh):
        self.assertEqual(minutes(result.hm), hm)
        self.assertEqual(minutes(result.hh), hh)
        # I01: o HH de cada crachá soma exatamente o tempo produtivo dele.
        self.assertAlmostEqual(
            sum(result.hh.values()),
            sum(sum(per_op.values()) for per_op in result.hh_by_badge.values()),
        )

    def test_c01_uma_op_um_colaborador(self):
        r = run({"A": ("X", [("08:00", "09:00")])}, [("A", "C1", "08:00", "09:00")])
        self.check(r, {"A": 60}, {"A": 60})

    def test_c02_dois_colaboradores_juntos(self):
        r = run({"A": ("X", [("08:00", "09:00")])},
                [("A", "C1", "08:00", "09:00"), ("A", "C2", "08:00", "09:00")])
        self.check(r, {"A": 60}, {"A": 120})

    def test_c03_entrada_tardia(self):
        r = run({"A": ("X", [("08:00", "10:00")])},
                [("A", "C1", "08:00", "10:00"), ("A", "C2", "08:25", "10:00")])
        self.check(r, {"A": 120}, {"A": 215})

    def test_c04_saida_antecipada(self):
        r = run({"A": ("X", [("08:00", "09:30")])},
                [("A", "C1", "08:00", "09:30"), ("A", "C2", "08:00", "08:40")])
        self.check(r, {"A": 90}, {"A": 130})

    def test_c05_duas_ops_um_cracha(self):
        r = run({"A": ("X", [("08:00", "09:00")]), "B": ("X", [("08:00", "09:00")])},
                [("A", "C1", "08:00", "09:00"), ("B", "C1", "08:00", "09:00")])
        self.check(r, {"A": 30, "B": 30}, {"A": 30, "B": 30})

    def test_c06_tres_ops_um_cracha(self):
        ops = {op: ("X", [("08:00", "09:00")]) for op in "ABC"}
        r = run(ops, [(op, "C1", "08:00", "09:00") for op in "ABC"])
        self.check(r, {"A": 20, "B": 20, "C": 20}, {"A": 20, "B": 20, "C": 20})

    def test_c07_duas_ops_crachas_exclusivos_mesmo_recurso(self):
        r = run({"A": ("X", [("08:00", "09:00")]), "B": ("X", [("08:00", "09:00")])},
                [("A", "C1", "08:00", "09:00"), ("B", "C2", "08:00", "09:00")])
        self.check(r, {"A": 60, "B": 60}, {"A": 60, "B": 60})
        # HM operacional 120 min; relógio do recurso 60 min — nomes diferentes.
        self.assertEqual(r.clock, {"X": 3600.0})

    def test_c08_tres_crachas_exclusivos(self):
        ops = {op: ("X", [("08:00", "09:00")]) for op in "ABC"}
        r = run(ops, [("A", "C1", "08:00", "09:00"), ("B", "C2", "08:00", "09:00"),
                      ("C", "C3", "08:00", "09:00")])
        self.check(r, {"A": 60, "B": 60, "C": 60}, {"A": 60, "B": 60, "C": 60})

    def test_c09_horarios_diferentes_crachas_exclusivos(self):
        r = run({"A": ("X", [("09:00", "10:00")]), "B": ("X", [("09:40", "10:40")])},
                [("A", "C1", "09:00", "10:00"), ("B", "C2", "09:40", "10:40")])
        self.check(r, {"A": 60, "B": 60}, {"A": 60, "B": 60})
        self.assertEqual(r.clock, {"X": 100 * 60.0})

    def test_c10_horarios_diferentes_mesmo_cracha(self):
        r = run({"A": ("X", [("09:00", "10:40")]), "B": ("X", [("09:40", "10:40")])},
                [("A", "C1", "09:00", "10:40"), ("B", "C1", "09:40", "10:40")])
        self.check(r, {"A": 70, "B": 30}, {"A": 70, "B": 30})

    def test_c11_tres_ops_uma_encerra_antes(self):
        r = run({"A": ("X", [("08:00", "08:30")]), "B": ("X", [("08:00", "09:00")]),
                 "C": ("X", [("08:00", "09:00")])},
                [("A", "C1", "08:00", "08:30"), ("B", "C1", "08:00", "09:00"),
                 ("C", "C1", "08:00", "09:00")])
        self.check(r, {"A": 10, "B": 25, "C": 25}, {"A": 10, "B": 25, "C": 25})

    def test_c12_um_exclusivo_outro_compartilhado(self):
        ops = {op: ("X", [("08:00", "09:00")]) for op in "ABC"}
        r = run(ops, [("A", "C1", "08:00", "09:00"), ("B", "C2", "08:00", "09:00"),
                      ("C", "C2", "08:00", "09:00")])
        self.check(r, {"A": 60, "B": 30, "C": 30}, {"A": 60, "B": 30, "C": 30})
        self.assertFalse(r.proposed)

    def test_c13_misto_regra_proposta(self):
        r = run({"A": ("X", [("08:00", "09:00")]), "B": ("X", [("08:00", "09:00")])},
                [("A", "C1", "08:00", "09:00"), ("A", "C2", "08:00", "09:00"),
                 ("B", "C2", "08:00", "09:00")])
        self.check(r, {"A": 60, "B": 30}, {"A": 90, "B": 30})
        self.assertEqual(r.proposed, {"A"})
        self.assertEqual(r.flag("A"), REASON_PROPOSED)
        self.assertIn(REASON_PROPOSED, {item.reason for item in r.trail if item.key == "A"})

    def test_c14_misto_tres_ops(self):
        ops = {op: ("X", [("08:00", "09:00")]) for op in "ABC"}
        r = run(ops, [("A", "C1", "08:00", "09:00"), ("B", "C2", "08:00", "09:00"),
                      ("B", "C3", "08:00", "09:00"), ("C", "C3", "08:00", "09:00")])
        self.check(r, {"A": 60, "B": 60, "C": 30}, {"A": 60, "B": 90, "C": 30})
        self.assertEqual(r.proposed, {"B"})

    def test_c15_troca_sequencial(self):
        r = run({"A": ("X", [("08:00", "08:30")]), "B": ("X", [("08:30", "09:00")])},
                [("A", "C1", "08:00", "08:30"), ("B", "C1", "08:30", "09:00")])
        self.check(r, {"A": 30, "B": 30}, {"A": 30, "B": 30})

    def test_c16_pausa_da_op(self):
        r = run({"A": ("X", [("08:00", "08:45"), ("09:00", "10:00")])},
                [("A", "C1", "08:00", "10:00")])
        self.check(r, {"A": 105}, {"A": 105})

    def test_c17_um_colaborador_pausa(self):
        r = run({"A": ("X", [("08:00", "09:00")])},
                [("A", "C1", "08:00", "09:00"), ("A", "C2", "08:00", "08:20"),
                 ("A", "C2", "08:35", "09:00")])
        self.check(r, {"A": 60}, {"A": 105})

    def test_c18_op_sem_cracha_fica_pendente(self):
        r = run({"A": ("X", [("08:00", "09:00")])}, [])
        self.assertEqual(minutes(r.hm), {})
        self.assertEqual(minutes(r.hh), {})
        self.assertEqual(minutes(r.pending), {"A": 60})
        self.assertEqual(r.flag("A"), REASON_PENDING)

    def test_c19_cracha_em_dois_recursos_e_conflito(self):
        r = run({"A": ("X", [("08:00", "09:00")]), "B": ("Y", [("08:00", "09:00")])},
                [("A", "C1", "08:00", "09:00"), ("B", "C1", "08:00", "09:00")])
        self.assertEqual(r.conflict, {"A", "B"})
        self.assertEqual(r.flag("B"), REASON_CONFLICT)
        # Nunca 2h de HH a partir de 1h física.
        self.assertEqual(round(sum(r.hh.values()) / 60), 60)

    def test_c20_duplicata_e_reprocessamento(self):
        dup = [("A", "C1", "08:00", "09:00"), ("A", "C1", "08:00", "09:00")]
        r = run({"A": ("X", [("08:00", "09:00")])}, dup)
        self.check(r, {"A": 60}, {"A": 60})
        again = run({"A": ("X", [("08:00", "09:00")])}, dup)
        self.assertEqual(r, again)


class PropriedadesDoMotor(unittest.TestCase):
    def test_resultado_nao_depende_da_ordem(self):
        executions = [
            ("A", "X", [span("08:00", "09:00")]), ("B", "X", [span("08:20", "09:30")]),
            ("C", "Y", [span("08:10", "08:50")]),
        ]
        participations = [
            ("A", "C1", t("08:00"), t("09:00")), ("B", "C1", t("08:20"), None),
            ("B", "C2", t("08:30"), t("09:10")), ("C", "C3", t("08:10"), t("08:50")),
        ]
        base = allocate_by_badge(executions, participations)
        rng = random.Random(7)
        for _ in range(20):
            rng.shuffle(executions)
            rng.shuffle(participations)
            self.assertEqual(allocate_by_badge(executions, participations), base)

    def test_vinculo_aberto_vale_ate_o_fim_da_producao(self):
        r = run({"A": ("X", [("08:00", "09:00")])}, [("A", "C1", "08:30", None)])
        self.assertEqual(minutes(r.hh), {"A": 30})
        self.assertEqual(minutes(r.pending), {"A": 30})

    def test_participacao_fora_da_producao_nao_conta(self):
        # Setup/parada não estão nos trechos de produção: o crachá ali não gera HH.
        r = run({"A": ("X", [("08:30", "09:00")])}, [("A", "C1", "08:00", "09:00")])
        self.assertEqual(minutes(r.hh), {"A": 30})

    def test_participation_rows_usa_cracha_resolvido(self):
        rows = [
            {"apontamento_id": 7, "cracha": "old", "cracha_resolvido": "C9",
             "data_inicio": t("08:00"), "data_fim": None},
            {"apontamento_id": None, "cracha": "C1", "data_inicio": t("08:00")},
            {"apontamento_id": 8, "cracha": " ", "data_inicio": t("08:00")},
        ]
        self.assertEqual(participation_rows(rows), [(7, "C9", t("08:00"), None)])

    def test_trilha_soma_o_resultado(self):
        r = run({"A": ("X", [("09:00", "10:40")]), "B": ("X", [("09:40", "10:40")])},
                [("A", "C1", "09:00", "10:40"), ("B", "C1", "09:40", "10:40")])
        for key in ("A", "B"):
            lines = [item for item in r.trail if item.key == key]
            self.assertAlmostEqual(sum(item.hm_seconds for item in lines), r.hm[key])
            self.assertAlmostEqual(sum(item.hh_seconds for item in lines), r.hh[key])
        self.assertEqual(len([item for item in r.trail if item.key == "A"]), 2)


if __name__ == "__main__":
    unittest.main()
