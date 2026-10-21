"""std.*: explicação do tempo padrão (S1–S6), com banco e analytics falsos próprios."""

from __future__ import annotations

from datetime import datetime

import pytest

from mes.contracts import AnalyticsFilter
from mes.services.metric_explanation import UnknownMetricError
from mes.services.standard_time import ESTIMATE_EVENT_TYPE
from mes.services.standard_time_explanation import STD_TEXT, StandardTimeExplanationService

NOW = datetime(2026, 10, 20, 9, 0)
KEY = dict(produto="P1", operacao="10", recurso="LASER1")


def _row(**over):
    row = {
        "produto_codigo": "P1", "numero_operacao": "10", "codigo_recurso": "LASER1", "tipo_setor": "solda",
        "tempo_protheus_segundos": None, "linhas_com_protheus": 0, "linhas_total": 2,
        "tempo_manual_segundos": None, "manual_alterado_por": None, "manual_alterado_em": None,
        "manual_vigente_desde": None,
        "tempo_estimado_segundos": None, "estimado_janela_inicio": None, "estimado_janela_fim": None,
        "estimado_calculado_em": None, "fonte_efetiva": None,
    }
    row.update(over)
    return row


class FakeDb:
    def __init__(self, rows=(), history=(), event=None):
        self.rows, self.history, self.event = list(rows), list(history), event

    def listar_tempos_padrao(self, **kwargs):
        return {"items": self.rows, "total": len(self.rows), "sem_produto": 0}

    def listar_historico_tempo_padrao_manual(self, produto, operacao, recurso, limite=50):
        return self.history

    def ultimo_evento_sistema(self, tipos=None, origem=None):
        assert tipos == [ESTIMATE_EVENT_TYPE]
        return self.event


class FakeAnalytics:
    def __init__(self, items=(), samples=()):
        self.items, self.samples = list(items), list(samples)

    def standard_vs_actual(self, filters):
        return {"periodo": {}, "items": self.items}

    def standard_time_samples(self, filters):
        return [s for s in self.samples if filters.inicio <= s["inicio"] <= filters.fim]


def _service(db=None, analytics=None):
    return StandardTimeExplanationService(db or FakeDb(), analytics or FakeAnalytics(), now_func=lambda: NOW)


def _explain(service, metric, **filters):
    return service.explain(metric, AnalyticsFilter(inicio=datetime(2026, 9, 20), fim=NOW, **filters))


def _cmp(op, padrao, real, **over):
    row = {
        "op": op, "operacao": "10", "produto": "P1", "recurso_real": "LASER1", "quantidade_boa": 10,
        "tempo_padrao_unitario_segundos": padrao / 10 if padrao is not None else None,
        "tempo_padrao_fonte": "protheus" if padrao is not None else None,
        "tempo_padrao_estimado_segundos": padrao, "tempo_producao_real_segundos": real,
        "tempo_real_por_peca_segundos": real / 10 if real is not None else None,
    }
    row.update(over)
    return row


def test_unknown_metric():
    with pytest.raises(UnknownMetricError):
        _explain(_service(), "std.nada")


@pytest.mark.parametrize("metric", ["std.protheus", "std.manual", "std.estimado", "std.fonte"])
def test_line_without_key_or_row_has_no_value(metric):
    assert _explain(_service(), metric).value is None
    assert _explain(_service(FakeDb()), metric, **KEY).value is None


def test_protheus_value_and_manual_shadowed():
    db = FakeDb([_row(tempo_protheus_segundos=12.5, linhas_com_protheus=1, tempo_manual_segundos=9.0)])
    tree = _explain(_service(db), "std.protheus", **KEY)
    assert tree.value == 12.5 and tree.unit == "seconds"
    assert "1 de 2" in tree.reason
    assert tree.excluded[0]["value"] == "9,00 s"


def test_manual_history_lists_events_and_corte_note():
    db = FakeDb(
        [_row(tipo_setor="Corte", tempo_manual_segundos=8.0, manual_alterado_por="Ana",
              manual_alterado_em=datetime(2026, 10, 1, 8, 0), manual_vigente_desde=datetime(2026, 10, 2))],
        history=[{"acao": "definido", "segundos_anterior": 7.0, "segundos_novo": 8.0, "usuario_nome": "Ana",
                  "registrado_em": datetime(2026, 10, 1, 8, 0), "vigente_desde": datetime(2026, 10, 2), "observacao": "x"}],
    )
    tree = _explain(_service(db), "std.manual", **KEY)
    assert tree.value == 8.0 and len(tree.children) == 1
    assert tree.children[0].detail["anterior"] == "7,00 s"
    assert any("Corte" in n for n in tree.notes)


def test_fonte_shows_all_three_and_marks_the_one_in_use():
    db = FakeDb([_row(tempo_manual_segundos=8.0, tempo_estimado_segundos=7.0, fonte_efetiva="manual")])
    tree = _explain(_service(db), "std.fonte", **KEY)
    assert tree.value == "Manual"
    by = {c.label: c for c in tree.children}
    assert by["Manual"].detail == {"em_uso": "sim"}
    assert by["Protheus"].value == "Não cadastrado"


def test_fonte_without_any_standard():
    tree = _explain(_service(FakeDb([_row()])), "std.fonte", **KEY)
    assert tree.value == "Sem padrão"


def _estimate_setup(values):
    """Janela de 14 dias com as execuções `values` (P25 gravado = 1ª quartil dos mantidos)."""
    samples = [
        {"apontamento_id": i, "produto": "P1", "operacao": "10", "recurso": "LASER1",
         "segundos_por_peca": v, "inicio": datetime(2026, 10, 5, 8, i), "fim": datetime(2026, 10, 5, 9, i)}
        for i, v in enumerate(values, start=1)
    ]
    event = {"data_hora": NOW, "detalhes": {
        "calculado_em": NOW.isoformat(), "janela_inicio": "2026-09-22T00:00:00", "janela_fim": "2026-10-20T00:00:00",
        "execucoes_elegiveis": len(values), "chaves_avaliadas": 3, "chaves_estimadas": 1, "amostra_minima": 5,
    }}
    return samples, event


def test_estimado_reconciles_with_the_stored_p25_and_lists_the_executions():
    from mes.domain.standard_time import estimate_standard_seconds

    values = [10.0, 11.0, 12.0, 13.0, 14.0, 60.0]  # 60 é fora do padrão
    stored = estimate_standard_seconds(values, min_samples=5, pct=25.0).segundos_por_peca
    samples, event = _estimate_setup(values)
    row = _row(tempo_estimado_segundos=stored, estimado_janela_inicio=datetime(2026, 10, 5, 8, 1),
               estimado_janela_fim=datetime(2026, 10, 5, 9, 6), fonte_efetiva="estimado")
    tree = _explain(_service(FakeDb([row], event=event), FakeAnalytics(samples=samples)), "std.estimado", **KEY)
    assert tree.value == pytest.approx(stored)
    assert len(tree.children) == 5 and all(c.kind == "input" for c in tree.children)
    assert [e["value"] for e in tree.excluded] == ["60,00 s"]
    assert tree.reconciliation["ok"] is True


def test_estimado_mismatch_is_reported_not_hidden():
    values = [10.0, 11.0, 12.0, 13.0, 14.0]
    samples, event = _estimate_setup(values)
    row = _row(tempo_estimado_segundos=99.0, estimado_janela_inicio=datetime(2026, 10, 5, 8, 1),
               estimado_janela_fim=datetime(2026, 10, 5, 9, 5))
    tree = _explain(_service(FakeDb([row], event=event), FakeAnalytics(samples=samples)), "std.estimado", **KEY)
    assert tree.reconciliation["ok"] is False


def test_estimado_without_value():
    tree = _explain(_service(FakeDb([_row()])), "std.estimado", **KEY)
    assert tree.value is None and tree.children == []


def test_recalculo_from_json_string_and_legacy_event():
    event = {"data_hora": NOW, "detalhes": '{"execucoes_elegiveis": 40, "chaves_avaliadas": 8, "chaves_estimadas": 5, "amostra_minima": 5}'}
    tree = _explain(_service(FakeDb(event=event)), "std.recalculo")
    assert tree.value == 5.0 and tree.excluded[0]["value"] == "3"
    assert [c.value for c in tree.children] == [40.0, 8.0, 5.0]
    legacy = _explain(_service(FakeDb(event={"data_hora": NOW, "detalhes": None})), "std.recalculo")
    assert legacy.value == 0.0
    assert _explain(_service(FakeDb(event=None)), "std.recalculo").value is None


def test_comparacoes_groups_sum_to_total():
    items = [_cmp(1, 100.0, 120.0), _cmp(2, None, 50.0), _cmp(3, 80.0, None)]
    tree = _explain(_service(analytics=FakeAnalytics(items)), "std.comparacoes")
    assert tree.value == 3.0 and tree.reconciliation["ok"] is True
    assert [c.value for c in tree.children] == [1.0, 1.0, 1.0]


def test_acumulados_and_desvio_use_only_rows_with_both_sides():
    items = [_cmp(1, 3600.0, 4320.0), _cmp(2, 1800.0, 1800.0), _cmp(3, None, 999.0), _cmp(4, 500.0, None)]
    service = _service(analytics=FakeAnalytics(items))
    padrao = _explain(service, "std.padrao_acumulado")
    real = _explain(service, "std.real_acumulado")
    desvio = _explain(service, "std.desvio")
    assert padrao.value == pytest.approx(1.5) and real.value == pytest.approx(6120 / 3600)
    assert padrao.reconciliation["ok"] and real.reconciliation["ok"] and desvio.reconciliation["ok"]
    assert desvio.value == pytest.approx((6120 - 5400) / 5400 * 100)
    assert {e["value"] for e in padrao.excluded} == {"1"}  # 1 sem padrão e 1 sem real, um de cada


def test_desvio_without_base_is_none():
    assert _explain(_service(analytics=FakeAnalytics([_cmp(1, None, 10.0)])), "std.desvio").value is None
    assert _explain(_service(analytics=FakeAnalytics()), "std.desvio").value is None


def test_truncation_keeps_the_total():
    items = [_cmp(i, 100.0, 110.0) for i in range(1, 8)]
    tree = StandardTimeExplanationService(FakeDb(), FakeAnalytics(items), now_func=lambda: NOW).explain(
        "std.padrao_acumulado", AnalyticsFilter(inicio=datetime(2026, 9, 20), fim=NOW), max_leaves=3,
    )
    assert tree.truncated is True and tree.reconciliation["ok"] is True


class _Facade:
    def __init__(self, db, analytics):
        self.db, self.analytics = db, analytics


def _user(role):
    from backend.api.schemas.auth import SessionUser

    return SessionUser(id=1, name="x", role=role, management_access=True, andon_access=False, operator_access=False)


def _route(metric, role, facade=None, **filters):
    from backend.api.routers.explanation import explain_for_user

    return explain_for_user(facade or _Facade(FakeDb(), FakeAnalytics()), metric,
                            AnalyticsFilter(inicio=datetime(2026, 9, 20), fim=NOW, **filters), _user(role))


@pytest.mark.parametrize("metric", ["std.protheus", "std.manual", "std.estimado", "std.fonte", "std.recalculo"])
def test_line_metrics_denied_without_standard_time_access(metric):
    from backend.api.errors import AppError

    with pytest.raises(AppError) as exc:
        _route(metric, "operador")
    assert exc.value.status_code == 403


@pytest.mark.parametrize("metric", sorted(m for m in STD_TEXT))
@pytest.mark.parametrize("com_linha", [True, False])
def test_every_std_metric_passes_the_route_response_model(metric, com_linha):
    """Regressão do 500 em std.fonte: o dict do serviço tem de passar pelo response_model real da rota."""
    from pydantic import TypeAdapter

    from backend.api.schemas.explanation import ExplanationResponse, ValueExplanationResponse

    rows = [_row(tempo_manual_segundos=8.0, tempo_estimado_segundos=7.0, fonte_efetiva="manual")] if com_linha else []
    facade = _Facade(FakeDb(rows), FakeAnalytics())
    TypeAdapter(ExplanationResponse | ValueExplanationResponse).validate_python(
        _route(metric, "admin", facade, **(KEY if metric in ("std.protheus", "std.manual", "std.estimado", "std.fonte") else {}))
    )


def test_comparison_metrics_open_to_management_and_line_metrics_to_admin():
    assert _route("std.comparacoes", "operador")["metric"] == "std.comparacoes"
    assert _route("std.recalculo", "admin")["metric"] == "std.recalculo"


# --------------------------------------------------------------- adversariais (QA)


def test_estimado_stored_rounded_to_3_decimals_still_reconciles():
    """O recálculo grava ``round(p25, 3)`` (standard_time.py); a conta aberta tem de fechar com esse valor."""
    from mes.domain.standard_time import estimate_standard_seconds

    values = [10.1111, 11.2223, 12.3337, 13.4449, 14.5551]
    exact = estimate_standard_seconds(values, min_samples=5, pct=25.0).segundos_por_peca
    stored = round(exact, 3)
    assert abs(stored - exact) > 1e-6  # o cenário só vale se o arredondamento muda o número
    samples, event = _estimate_setup(values)
    row = _row(tempo_estimado_segundos=stored, estimado_janela_inicio=datetime(2026, 10, 5, 8, 1),
               estimado_janela_fim=datetime(2026, 10, 5, 9, 5), fonte_efetiva="estimado")
    tree = _explain(_service(FakeDb([row], event=event), FakeAnalytics(samples=samples)), "std.estimado", **KEY)
    assert tree.reconciliation["ok"] is True


def test_estimado_without_rebuildable_executions_does_not_claim_a_closed_conta():
    samples, event = _estimate_setup([10.0, 11.0, 12.0, 13.0, 14.0])
    row = _row(tempo_estimado_segundos=11.0, estimado_janela_inicio=datetime(2026, 10, 5, 8, 1),
               estimado_janela_fim=datetime(2026, 10, 5, 9, 5), fonte_efetiva="estimado")
    tree = _explain(_service(FakeDb([row], event=event), FakeAnalytics(samples=[])), "std.estimado", **KEY)
    assert tree.children == [] and tree.reconciliation["ok"] is False


def test_line_key_is_case_and_space_insensitive_and_garbage_rows_do_not_crash():
    garbage = _row(produto_codigo=None, numero_operacao=None, codigo_recurso=None)
    db = FakeDb([garbage, _row(tempo_protheus_segundos=5.0, linhas_com_protheus=2)])
    tree = _explain(_service(db), "std.protheus", produto="  p1 ", operacao=" 10 ", recurso="laser1")
    assert tree.value == 5.0
    for blank in ({"produto": "  "}, {"operacao": ""}, {"recurso": "\t"}):
        assert _explain(_service(db), "std.protheus", **{**KEY, **blank}).value is None


def test_manual_history_with_removal_and_empty_fields_does_not_crash():
    db = FakeDb([_row(tempo_manual_segundos=None, manual_alterado_em=datetime(2026, 10, 1))],
                history=[{"acao": None, "segundos_anterior": None, "segundos_novo": None, "usuario_nome": None,
                          "registrado_em": None, "vigente_desde": None, "observacao": None}])
    tree = _explain(_service(db), "std.manual", **KEY)
    assert tree.value is None and len(tree.children) == 1 and tree.children[0].value is None


def test_comparison_with_zero_standard_never_divides_by_zero():
    items = [_cmp(1, 0.0, 30.0), _cmp(2, 0.0, 0.0)]
    service = _service(analytics=FakeAnalytics(items))
    assert _explain(service, "std.desvio").value is None
    padrao = _explain(service, "std.padrao_acumulado")
    assert padrao.value == 0.0 and padrao.reconciliation["ok"] is True
    assert _explain(service, "std.real_acumulado").value == pytest.approx(30.0 / 3600)


def test_comparacoes_truncated_groups_still_sum_to_every_row():
    items = [_cmp(i, 100.0, 110.0) for i in range(1, 6)] + [_cmp(i, None, 5.0) for i in range(6, 10)]
    tree = StandardTimeExplanationService(FakeDb(), FakeAnalytics(items), now_func=lambda: NOW).explain(
        "std.comparacoes", AnalyticsFilter(inicio=datetime(2026, 9, 20), fim=NOW), max_leaves=2,
    )
    assert tree.value == 9.0 and tree.reconciliation["ok"] is True and tree.truncated is True
    assert sum(c.value for c in tree.children) == 9.0


def test_route_guard_ignores_case_whitespace_and_unknown_std_metric():
    from backend.api.errors import AppError

    with pytest.raises(AppError) as denied:
        _route("  std.protheus ", "operador")
    assert denied.value.status_code == 403
    with pytest.raises(AppError) as unknown:
        _route("std.nada", "manufatura")
    assert unknown.value.status_code == 422
