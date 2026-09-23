"""`mes/domain/welding.py` e `mes/services/welding.py` (acompanhamento
gerencial da Solda, Wave 6D/6F) não tinham nenhum teste dedicado, apesar de
serem regra de produção real para a divisão em 5 setores (Aço/Alumínio/
Robô/Ferramentaria/Protótipo). O que mais importa cobrir:

* `classify_welding_status` decide entre A VENCER / ATRASADA / FINALIZADA
  seguindo uma ordem de precedência estrita (apontamento > semana de criação
  fechada sem apontamento > janela de prazo > sem base temporal). Um erro de
  ordem aqui muda o status mostrado para PCP/Liderança sem gerar exceção.
* `resolve_creation_basis` / `resolve_deadline_basis` escolhem a primeira
  data preenchida de uma precedência (emissão > geração; prazo_entrega >
  fim_planejado) e declaram se o resultado é "disponível" (base preferida)
  ou "parcial" (fallback) — um bug aqui produz "parcial" quando deveria ser
  "disponível" (ou vice-versa) sem quebrar nada visivelmente.
* `week_bounds` / `week_is_closed` / `appointed_in_creation_week` são a base
  de cálculo do atraso "sem apontamento na semana de criação"; bordas de
  semana (segunda 00:00, domingo 23:59:59) são onde off-by-one se escondem.
* `WeldingManagementService._agrupar_por_estacao` / `_agrupar_por_macro` /
  `_resumo` fazem agregação e ordenação (atrasada primeiro, "Estação 2" antes
  de "Estação 10", grupo sem estação/sem modelo isolado) que é fácil de
  quebrar silenciosamente numa refatoração futura.

Fakes em vez de mocks: `_FakeDB` simula `listar_ops_solda_gerencial` com
dicionários crus, como a camada real de banco entregaria.
"""

from __future__ import annotations

from datetime import datetime
import unittest

from mes.domain.industrial import DataAvailability
from mes.domain.welding import (
    CREATION_BASIS_GENERATED,
    CREATION_BASIS_ISSUE,
    DEADLINE_BASIS_DELIVERY,
    DEADLINE_BASIS_PLANNED_END,
    FINISHED_APPOINTMENT_STATUS,
    WELDING_STATUS_DONE,
    WELDING_STATUS_DUE,
    WELDING_STATUS_LATE,
    appointed_in_creation_week,
    classify_welding_status,
    resolve_creation_basis,
    resolve_deadline_basis,
    week_bounds,
    week_is_closed,
)
from mes.services.welding import WeldingManagementService


# ----------------------------------------------------------------------
# resolve_creation_basis / resolve_deadline_basis
# ----------------------------------------------------------------------
class ResolveCreationBasisTests(unittest.TestCase):
    def test_usa_emissao_quando_preenchida_e_marca_disponivel(self):
        basis = resolve_creation_basis(
            {"data_emissao": datetime(2026, 9, 1), "data_geracao": datetime(2026, 9, 2)}
        )
        self.assertEqual(basis.value, datetime(2026, 9, 1))
        self.assertEqual(basis.basis, CREATION_BASIS_ISSUE)
        self.assertEqual(basis.availability, DataAvailability.AVAILABLE.value)

    def test_cai_para_geracao_quando_emissao_ausente_e_marca_parcial(self):
        basis = resolve_creation_basis({"data_geracao": datetime(2026, 9, 2)})
        self.assertEqual(basis.value, datetime(2026, 9, 2))
        self.assertEqual(basis.basis, CREATION_BASIS_GENERATED)
        self.assertEqual(basis.availability, DataAvailability.PARTIAL.value)

    def test_sem_nenhuma_data_fica_insuficiente(self):
        basis = resolve_creation_basis({})
        self.assertIsNone(basis.value)
        self.assertIsNone(basis.basis)
        self.assertEqual(basis.availability, DataAvailability.INSUFFICIENT_DATA.value)
        self.assertIsNone(basis.label)


class ResolveDeadlineBasisTests(unittest.TestCase):
    def test_usa_prazo_entrega_quando_preenchido(self):
        basis = resolve_deadline_basis(
            {"prazo_entrega": datetime(2026, 9, 10), "fim_planejado": datetime(2026, 9, 5)}
        )
        self.assertEqual(basis.basis, DEADLINE_BASIS_DELIVERY)
        self.assertEqual(basis.availability, DataAvailability.AVAILABLE.value)

    def test_cai_para_fim_planejado_e_marca_parcial(self):
        basis = resolve_deadline_basis({"fim_planejado": datetime(2026, 9, 5)})
        self.assertEqual(basis.basis, DEADLINE_BASIS_PLANNED_END)
        self.assertEqual(basis.availability, DataAvailability.PARTIAL.value)

    def test_aceita_date_pura_alem_de_datetime(self):
        from datetime import date

        basis = resolve_deadline_basis({"prazo_entrega": date(2026, 9, 10)})
        self.assertEqual(basis.value, datetime(2026, 9, 10, 0, 0))


# ----------------------------------------------------------------------
# Semana de criação
# ----------------------------------------------------------------------
class WeekBoundsTests(unittest.TestCase):
    def test_semana_comeca_na_segunda_00h_e_termina_domingo_23_59_59(self):
        # 2026-09-23 é uma quarta-feira.
        start, end = week_bounds(datetime(2026, 9, 23, 15, 30))
        self.assertEqual(start, datetime(2026, 9, 21, 0, 0, 0))  # segunda
        self.assertEqual(end, datetime(2026, 9, 27, 23, 59, 59))  # domingo

    def test_referencia_none_retorna_none(self):
        self.assertIsNone(week_bounds(None))


class WeekIsClosedTests(unittest.TestCase):
    def test_semana_ainda_em_curso_nao_esta_fechada(self):
        criacao = datetime(2026, 9, 21, 8, 0)  # segunda
        agora = datetime(2026, 9, 25, 10, 0)  # sexta, mesma semana
        self.assertFalse(week_is_closed(criacao, agora))

    def test_exatamente_no_limite_domingo_23_59_59_ainda_nao_fechou(self):
        criacao = datetime(2026, 9, 21, 8, 0)
        limite = datetime(2026, 9, 27, 23, 59, 59)
        self.assertFalse(week_is_closed(criacao, limite))

    def test_um_segundo_apos_o_limite_ja_fechou(self):
        criacao = datetime(2026, 9, 21, 8, 0)
        depois = datetime(2026, 9, 28, 0, 0, 0)
        self.assertTrue(week_is_closed(criacao, depois))

    def test_sem_referencia_ou_sem_agora_nunca_fecha(self):
        self.assertFalse(week_is_closed(None, datetime(2026, 9, 28)))
        self.assertFalse(week_is_closed(datetime(2026, 9, 21), None))


class AppointedInCreationWeekTests(unittest.TestCase):
    def test_apontamento_dentro_da_semana_de_criacao(self):
        criacao = datetime(2026, 9, 21, 8, 0)
        primeiro = datetime(2026, 9, 23, 9, 0)
        self.assertTrue(appointed_in_creation_week(criacao, primeiro))

    def test_apontamento_na_semana_seguinte_nao_conta(self):
        criacao = datetime(2026, 9, 21, 8, 0)
        primeiro = datetime(2026, 9, 28, 0, 0, 1)
        self.assertFalse(appointed_in_creation_week(criacao, primeiro))

    def test_sem_apontamento_retorna_false(self):
        self.assertFalse(appointed_in_creation_week(datetime(2026, 9, 21), None))


# ----------------------------------------------------------------------
# classify_welding_status — a regra central
# ----------------------------------------------------------------------
class ClassifyWeldingStatusTests(unittest.TestCase):
    def test_apontamento_finalizado_vence_qualquer_outra_condicao(self):
        # Mesmo com prazo já vencido, apontamento concluído manda.
        order = {"prazo_entrega": datetime(2026, 1, 1)}
        status = classify_welding_status(
            order,
            appointment_status=FINISHED_APPOINTMENT_STATUS,
            now=datetime(2026, 9, 23),
        )
        self.assertEqual(status.value, WELDING_STATUS_DONE)
        self.assertTrue(status.finished)
        self.assertEqual(status.availability, DataAvailability.AVAILABLE.value)

    def test_apontamento_status_e_comparado_com_strip_mas_case_sensitive(self):
        order = {"prazo_entrega": datetime(2026, 12, 1)}
        status = classify_welding_status(
            order,
            appointment_status=f"  {FINISHED_APPOINTMENT_STATUS}  ",
            now=datetime(2026, 9, 23),
        )
        self.assertTrue(status.finished)

    def test_semana_de_criacao_fechada_sem_apontamento_fica_atrasada(self):
        order = {"data_emissao": datetime(2026, 9, 7)}  # semana 07-13/09, já fechada
        status = classify_welding_status(
            order,
            appointment_status=None,
            first_appointment=None,
            now=datetime(2026, 9, 23),
        )
        self.assertEqual(status.value, WELDING_STATUS_LATE)
        self.assertFalse(status.finished)
        self.assertIn("apontamento na semana", status.reason)

    def test_semana_de_criacao_fechada_mas_com_apontamento_na_semana_nao_atrasa(self):
        order = {"data_emissao": datetime(2026, 9, 7), "prazo_entrega": datetime(2026, 12, 1)}
        status = classify_welding_status(
            order,
            appointment_status=None,
            first_appointment=datetime(2026, 9, 9),  # dentro da mesma semana
            now=datetime(2026, 9, 23),
        )
        # Passou pela regra da semana sem acusar atraso; cai para a janela de prazo.
        self.assertEqual(status.value, WELDING_STATUS_DUE)

    def test_semana_de_criacao_ainda_em_curso_nao_atrasa_por_semana(self):
        agora = datetime(2026, 9, 23)  # quarta, semana em curso
        order = {"data_emissao": agora, "prazo_entrega": datetime(2026, 12, 1)}
        status = classify_welding_status(
            order, appointment_status=None, first_appointment=None, now=agora
        )
        self.assertEqual(status.value, WELDING_STATUS_DUE)

    def test_prazo_vencido_sem_apontamento_fica_atrasada(self):
        order = {"prazo_entrega": datetime(2026, 9, 1)}
        status = classify_welding_status(
            order, appointment_status=None, now=datetime(2026, 9, 23)
        )
        self.assertEqual(status.value, WELDING_STATUS_LATE)
        self.assertIn("janela de prazo", status.reason)

    def test_dentro_da_janela_de_prazo_fica_a_vencer(self):
        order = {"prazo_entrega": datetime(2026, 12, 1)}
        status = classify_welding_status(
            order, appointment_status=None, now=datetime(2026, 9, 23)
        )
        self.assertEqual(status.value, WELDING_STATUS_DUE)

    def test_exatamente_no_prazo_ainda_nao_esta_atrasada(self):
        limite = datetime(2026, 9, 23, 12, 0, 0)
        order = {"prazo_entrega": limite}
        status = classify_welding_status(order, appointment_status=None, now=limite)
        self.assertEqual(status.value, WELDING_STATUS_DUE)

    def test_sem_nenhuma_base_temporal_fica_indisponivel(self):
        status = classify_welding_status({}, appointment_status=None, now=datetime(2026, 9, 23))
        self.assertIsNone(status.value)
        self.assertFalse(status.late)
        self.assertFalse(status.finished)
        self.assertEqual(status.availability, DataAvailability.INSUFFICIENT_DATA.value)


# ----------------------------------------------------------------------
# WeldingManagementService
# ----------------------------------------------------------------------
class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def listar_ops_solda_gerencial(self, *, limite=300):
        return list(self._rows[:limite])


def _row(**overrides):
    base = {
        "codigo_op": "OP1",
        "numero_operacao": "10",
        "produto_codigo": "PROD1",
        "produto_descricao": "Conjunto A",
        "quantidade": 5,
        "codigo_recurso": "R1",
        "recurso_nome": "Robo 1",
        "descricao_operacao": "Solda robô",
        "produto_modelo": "Modelo X",
        "estacao_observada": "Estação 2",
        # Segunda-feira da semana corrente do "agora" padrão dos testes
        # (2026-09-23, quarta). Semana ainda em curso: não deve disparar a
        # regra de atraso por "semana de criação fechada sem apontamento" a
        # menos que o teste queira isso explicitamente.
        "data_emissao": datetime(2026, 9, 21),
        "data_geracao": None,
        "prazo_entrega": datetime(2026, 12, 1),
        "fim_planejado": None,
        "inicio_planejado": None,
        "apontamento_inicio": None,
        "apontamento_fim": None,
        "status_apontamento": None,
        "primeiro_apontamento": None,
    }
    base.update(overrides)
    return base


class WeldingManagementServiceTests(unittest.TestCase):
    def _service(self, rows, now=datetime(2026, 9, 23)):
        return WeldingManagementService(_FakeDB(rows), now_func=lambda: now)

    def test_acompanhamento_sem_linhas_fica_no_records(self):
        resultado = self._service([]).acompanhamento()
        self.assertEqual(resultado["availability"], DataAvailability.NO_RECORDS.value)
        self.assertEqual(resultado["estacoes"], [])
        self.assertEqual(resultado["resumo"]["linhas"], 0)

    def test_resumo_conta_status_e_ops_unicas(self):
        rows = [
            _row(codigo_op="OP1", numero_operacao="10", prazo_entrega=datetime(2026, 12, 1)),
            _row(codigo_op="OP1", numero_operacao="20", prazo_entrega=datetime(2026, 1, 1)),
            _row(
                codigo_op="OP2",
                status_apontamento=FINISHED_APPOINTMENT_STATUS,
                estacao_observada="",
                produto_modelo="",
            ),
        ]
        resumo = self._service(rows).acompanhamento()["resumo"]
        self.assertEqual(resumo["ops"], 2)
        self.assertEqual(resumo["linhas"], 3)
        self.assertEqual(resumo["a_vencer"], 1)
        self.assertEqual(resumo["atrasadas"], 1)
        self.assertEqual(resumo["finalizadas"], 1)
        self.assertEqual(resumo["sem_modelo"], 1)
        self.assertEqual(resumo["sem_estacao"], 1)

    def test_agrupamento_por_estacao_ordena_numericamente_e_isola_sem_estacao(self):
        rows = [
            _row(codigo_op="OP1", estacao_observada="Estação 10"),
            _row(codigo_op="OP2", estacao_observada="Estação 2"),
            _row(codigo_op="OP3", estacao_observada=""),
        ]
        estacoes = self._service(rows).acompanhamento()["estacoes"]
        nomes = [grupo["nome"] for grupo in estacoes]
        # "Estação 2" deve vir antes de "Estação 10" (ordem numérica, não
        # lexicográfica). Estação vazia vira None (ver `_text(...) or None`
        # na linha), não string vazia.
        self.assertEqual(nomes, ["Estação 2", "Estação 10", None])
        self.assertEqual(estacoes[-1]["availability"], DataAvailability.NO_RECORDS.value)
        for grupo in estacoes:
            self.assertEqual(grupo["op_count"], len(grupo["ops"]))

    def test_linhas_dentro_da_estacao_ordenam_atrasada_antes_de_a_vencer_antes_de_finalizada(self):
        rows = [
            _row(codigo_op="DONE", status_apontamento=FINISHED_APPOINTMENT_STATUS),
            _row(codigo_op="LATE", prazo_entrega=datetime(2026, 1, 1)),
            _row(codigo_op="DUE", prazo_entrega=datetime(2026, 12, 1)),
        ]
        estacao = self._service(rows).acompanhamento()["estacoes"][0]
        ordem = [linha["op"] for linha in estacao["ops"]]
        self.assertEqual(ordem, ["LATE", "DUE", "DONE"])

    def test_agrupamento_por_macro_usa_descricao_e_prioriza_mais_atrasadas(self):
        rows = [
            _row(codigo_op="OP1", produto_descricao="Conjunto A", prazo_entrega=datetime(2026, 1, 1)),
            _row(codigo_op="OP2", produto_descricao="Conjunto A", prazo_entrega=datetime(2026, 1, 1)),
            _row(codigo_op="OP3", produto_descricao="Conjunto B", prazo_entrega=datetime(2026, 12, 1)),
            _row(codigo_op="OP4", produto_descricao="", produto_codigo=""),
        ]
        macros = self._service(rows).acompanhamento()["macros"]
        self.assertEqual(macros[0]["nome"], "Conjunto A")
        self.assertEqual(macros[0]["atrasadas"], 2)
        sem_produto = next(m for m in macros if not m["nome"])
        self.assertEqual(sem_produto["availability"], DataAvailability.NOT_CONFIGURED.value)

    def test_linha_projeta_bases_temporais_com_label_e_availability(self):
        rows = [_row(data_emissao=datetime(2026, 9, 21), data_geracao=None)]
        linha = self._service(rows).acompanhamento()["estacoes"][0]["ops"][0]
        self.assertEqual(linha["datas"]["criacao"]["availability"], DataAvailability.AVAILABLE.value)
        self.assertEqual(linha["datas"]["criacao"]["label"], "Emissão da OP")
        self.assertEqual(linha["status"]["value"], WELDING_STATUS_DUE)

    def test_simulation_mode_e_repassado_no_resultado(self):
        service = WeldingManagementService(
            _FakeDB([]), now_func=lambda: datetime(2026, 9, 23), simulation_mode=True
        )
        self.assertTrue(service.acompanhamento()["simulation_only"])


if __name__ == "__main__":
    unittest.main()
