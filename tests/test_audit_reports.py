from datetime import datetime

from mes.contracts import AnalyticsFilter
from mes.services import audit_reports


def filtro(**extra):
    return AnalyticsFilter(inicio=datetime(2026, 11, 10, 0, 0), fim=datetime(2026, 11, 10, 23, 59, 59), **extra)


class Db:
    def listar_estados_recurso_periodo(self, *args, **kwargs):
        return []

    def listar_recursos_pcfactory(self):
        return []

    def listar_fatos_operacionais_periodo(self, *args, **kwargs):
        return []

    def listar_eventos_quantidade_periodo(self, *args, **kwargs):
        return []


class Facade:
    def __init__(self, items, db=None, summary=None):
        self.db = db or Db()
        self.items = items
        self.summary = summary or {}
        self.calls = []

    def eventos_status(self, filters, **table):
        self.calls.append(("01", table))
        return {"items": self.items, "summary": self.summary, "opcoes": {"status": []}}

    def eventos_producao(self, filters):
        self.calls.append(("02", {}))
        return {"items": self.items, "summary": self.summary}


AGORA = datetime(2026, 11, 10, 9, 30, 15, 123456)


def test_as_of_e_o_instante_da_consulta_limitado_ao_fim_do_periodo():
    assert audit_reports.as_of_for(filtro(), AGORA) == datetime(2026, 11, 10, 9, 30, 15)
    assert audit_reports.as_of_for(filtro(), datetime(2026, 11, 12, 8, 0)) == datetime(2026, 11, 10, 23, 59, 59)


def test_estados_distinguem_sem_registros_zero_e_com_dados():
    vazio = audit_reports.run(Facade([]), "01", filtro(), now=AGORA)
    assert vazio["estado"] == "sem_registros" and vazio["as_of"] == datetime(2026, 11, 10, 9, 30, 15)
    zero = audit_reports.run(Facade([{"duracao_segundos": 0}]), "01", filtro(), now=AGORA)
    assert zero["estado"] == "zero"
    cheio = audit_reports.run(Facade([{"duracao_segundos": 60}]), "01", filtro(), now=AGORA)
    assert cheio["estado"] == "com_dados"
    producao_zero = audit_reports.run(
        Facade([{"tempo_real_segundos": None, "quantidade_boa": 0, "quantidade_refugo": None}]), "02", filtro(), now=AGORA,
    )
    assert producao_zero["estado"] == "zero"


def test_fonte_obrigatoria_ausente_e_indisponivel_nao_zero():
    class SemQuantidade(Db):
        listar_eventos_quantidade_periodo = None

    result = audit_reports.run(Facade([], db=SemQuantidade()), "02", filtro(), now=AGORA)
    assert result["estado"] == "indisponivel"
    assert result["fontes"]["listar_eventos_quantidade_periodo"] == "indisponivel"
    # A fonte do Corte é complementar: ausente, vira aviso, não indisponível.
    assert any("listar_apontamentos_corte" in aviso for aviso in result["avisos"])


def test_tipo_01_repassa_filtros_proprios_e_tipo_02_avisa_corte_fora_com_op():
    facade = Facade([])
    audit_reports.run(facade, "01", filtro(), now=AGORA, status="Setup", classe="setup", em_aberto=True)
    assert facade.calls[-1] == ("01", {"status": "Setup", "classe": "setup", "em_aberto": True})
    result = audit_reports.run(Facade([]), "02", filtro(op="OP1"), now=AGORA)
    assert any("Corte" in aviso for aviso in result["avisos"])


def test_campos_do_catalogo_cobrem_todo_campo_das_fontes():
    from mes.services import event_log

    status = event_log.status_events([{"id": 1, "recurso": "LASER1", "categoria": "producao", "data_inicio": AGORA}])
    producao = event_log.production_events(
        [{"id": 1, "op": "OP1", "numero_operacao": "010", "data_inicio": AGORA}], [], [],
        [{"codigo_tarefa": "T1", "maquina": "LASER1", "data_inicio": AGORA}],
    )
    for tipo, items in (("01", status["items"]), ("02", producao["items"])):
        chaves = {campo["chave"] for campo in audit_reports.TIPOS[tipo]["campos"]}
        for item in items:
            assert set(item) <= chaves, (tipo, set(item) - chaves)


def test_falha_da_consulta_vira_estado_erro_com_500():
    import json

    from backend.api.routers.audit import _run_report

    class Quebrada(Facade):
        def eventos_status(self, filters, **table):
            raise RuntimeError("banco caiu")

    payload, error = _run_report(Quebrada([]), "01", filtro())
    assert payload is None and error.status_code == 500
    body = json.loads(error.body)
    assert body["estado"] == "erro" and body["as_of"] and "banco caiu" not in body["detail"]
