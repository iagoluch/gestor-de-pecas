from datetime import datetime
from types import SimpleNamespace

import pytest

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

ADMIN = SimpleNamespace(id=1, name="Admin", role="admin", management_access=True, sector_scope=None)
GESTAO = SimpleNamespace(id=2, name="Gestão", role="supervisor", management_access=True, sector_scope=None)


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
    # Medida sem valor nenhum é falta de dado, não zero.
    sem_medida = audit_reports.run(Facade([{"duracao_segundos": None}]), "01", filtro(), now=AGORA)
    assert sem_medida["estado"] == "com_dados"


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

    payload, error = _run_report(Quebrada([]), "01", filtro(), ADMIN)
    assert payload is None and error.status_code == 500
    body = json.loads(error.body)
    assert body["estado"] == "erro" and body["as_of"] and "banco caiu" not in body["detail"]


# --- Etapa 3: tipos 03 a 21 ---------------------------------------------------------

class Fontes(Facade):
    """Fachada com as fontes dos tipos novos, cada uma devolvendo ``self.dados``."""

    def __init__(self, dados, db=None):
        super().__init__([], db=db)
        self.dados = dados

    def analise(self, kind, filters):
        return self.dados[kind]

    def rastreabilidade(self, op):
        return self.dados["trace"]


def test_catalogo_mostra_so_os_tipos_que_a_conta_abre():
    todos = {tipo["id"] for tipo in audit_reports.catalogo(ADMIN)["tipos"]}
    assert todos == {f"{n:02d}" for n in range(1, 22)}
    gestao = {tipo["id"] for tipo in audit_reports.catalogo(GESTAO)["tipos"]}
    assert not gestao & {"17", "18", "19", "21"}
    assert {"01", "11", "20"} <= gestao
    assert all(tipo["grupo"] in audit_reports.GRUPOS for tipo in audit_reports.TIPOS.values())
    assert audit_reports.TIPOS["19"]["somente_consulta"] and audit_reports.TIPOS["21"]["somente_consulta"]


def test_rota_recusa_tipo_fora_da_permissao():
    from backend.api.errors import AppError
    from backend.api.routers.audit import _run_report

    with pytest.raises(AppError) as erro:
        _run_report(Fontes({}), "17", filtro(), GESTAO)
    assert erro.value.status_code == 403


def test_tempo_padrao_desvio_percentual_calculado_no_servidor():
    linhas = [
        {"tempo_padrao_estimado_segundos": 100, "tempo_producao_real_segundos": 150},
        {"tempo_padrao_estimado_segundos": None, "tempo_producao_real_segundos": 999},
    ]
    resumo = audit_reports.run(Fontes({"tempo_padrao_x_real": {"items": linhas}}), "08", filtro(), now=AGORA)["summary"]
    assert resumo["comparaveis"] == 1 and resumo["sem_tempo_padrao"] == 1
    assert resumo["desvio_percentual"] == 50
    sem_padrao = [{"tempo_padrao_estimado_segundos": 0, "tempo_producao_real_segundos": 10}]
    resumo = audit_reports.run(Fontes({"tempo_padrao_x_real": {"items": sem_padrao}}), "08", filtro(), now=AGORA)["summary"]
    assert resumo["desvio_percentual"] is None


def test_cronoanalise_media_ponderada_pelas_amostras():
    grupos = [
        {"produto": "P1", "operacao": "010", "amostras": 1, "media_segundos_por_peca": 10, "desvio_padrao_segundos_por_peca": 5},
        {"produto": "P2", "operacao": "020", "amostras": 3, "media_segundos_por_peca": 20, "desvio_padrao_segundos_por_peca": 1},
        {"produto": "P3", "operacao": "030", "amostras": 0, "media_segundos_por_peca": None},
    ]
    resumo = audit_reports.run(Fontes({"cronoanalise": {"groups": grupos}}), "09", filtro(), now=AGORA)["summary"]
    assert resumo["media_ponderada_segundos_por_peca"] == 17.5
    assert resumo["mais_lento"] == "P2 · 020" and resumo["mais_variavel"] == "P1 · 010"


def test_linha_do_tempo_exige_op_e_respeita_escopo_do_setor():
    vazio = audit_reports.run(Fontes({}), "13", filtro(), now=AGORA, user=ADMIN)
    assert vazio["estado"] == "sem_registros" and "OP" in vazio["avisos"][0]
    trace = {"operations": [{"setor": "Solda"}], "timeline": [{"timestamp": AGORA, "type": "inicio"}]}
    ok = audit_reports.run(Fontes({"trace": trace}), "13", filtro(op="OP1"), now=AGORA, user=ADMIN)
    assert ok["estado"] == "com_dados" and len(ok["items"]) == 1
    corte = SimpleNamespace(**{**vars(GESTAO), "sector_scope": ["Corte"]})
    with pytest.raises(audit_reports.ForaDoEscopo):
        audit_reports.run(Fontes({"trace": trace}), "13", filtro(op="OP1"), now=AGORA, user=corte)


def test_chamadas_aviso_no_as_of_e_filtro_do_periodo():
    class DbChamadas(Db):
        def listar_chamadas(self, limite=100):
            return [
                {"id": 1, "criado_em": datetime(2026, 11, 10, 9, 0), "contato_telegram_chat_id": "x"},
                {"id": 2, "criado_em": datetime(2026, 11, 10, 9, 28)},
                {"id": 3, "criado_em": datetime(2026, 11, 10, 8, 0), "telegram_dispensado": True},
                {"id": 4, "criado_em": datetime(2026, 11, 9, 8, 0)},
            ]

    result = audit_reports.run(Fontes({}, db=DbChamadas()), "20", filtro(), now=AGORA, user=GESTAO)
    avisos = {item["id"]: item["aviso"] for item in result["items"]}
    assert avisos == {1: "sem_confirmacao", 2: "enviando", 3: "na_tela"}
    assert all("contato_telegram_chat_id" not in item for item in result["items"])


def test_tipos_sem_medida_e_com_medida_zero():
    result = audit_reports.run(Fontes({"confiabilidade": {"por_recurso": [{"recurso": "R1", "falhas": 0}]}}), "12", filtro(), now=AGORA)
    assert result["estado"] == "zero"
