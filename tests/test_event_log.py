from datetime import datetime

from mes.services import event_log


def dt(hour, minute=0):
    return datetime(2026, 11, 10, hour, minute)


def fact(id_, op="OP1", oper="010", start=dt(8), end=dt(10), recurso="DOBRA1", **extra):
    return {"id": id_, "op": op, "numero_operacao": oper, "data_inicio": start, "data_fim": end,
            "maquina": recurso, "codigo_recurso": recurso, "tipo_setor": "DOBRA", **extra}


def state(apontamento_id, categoria, start, end, seconds):
    return {"apontamento_id": apontamento_id, "categoria": categoria, "inicio_periodo": start,
            "fim_periodo": end, "data_fim": end, "segundos_periodo": seconds}


def qty(tipo, quantidade, moment, op="OP1", oper="010", recurso="DOBRA1"):
    return {"tipo": tipo, "quantidade": quantidade, "data_hora": moment, "op": op,
            "numero_operacao": oper, "recurso": recurso}


def test_quantidade_vai_para_um_unico_apontamento():
    facts = [fact(1, start=dt(8), end=dt(9)), fact(2, start=dt(9), end=dt(11), recurso="DOBRA2")]
    result = event_log.production_events(facts, [], [qty("boa", 5, dt(10), recurso="DOBRA2")])
    boas = {item["apontamento_id"]: item["quantidade_boa"] for item in result["items"]}
    assert boas == {1: 0, 2: 5}
    assert result["summary"]["quantidade_boa"] == 5


def test_quantidade_sem_apontamento_fica_visivel_como_orfa():
    result = event_log.production_events([fact(1)], [], [qty("refugo", 2, dt(9), op="OP9")])
    orphans = [item for item in result["items"] if item["inconsistencia"] == "quantidade_sem_evento"]
    assert len(orphans) == 1 and orphans[0]["quantidade_refugo"] == 2
    assert result["summary"]["quantidade_sem_evento"] == 1
    assert result["summary"]["quantidade_refugo"] == 2


def test_quantidade_antes_do_inicio_do_apontamento_fica_orfa():
    result = event_log.production_events([fact(1, start=dt(10), end=dt(11))], [], [qty("boa", 3, dt(9))])
    assert result["summary"]["quantidade_sem_evento"] == 1
    assert [item["quantidade_boa"] for item in result["items"] if item["apontamento_id"] == 1] == [0]


def test_setup_e_producao_viram_linhas_e_quantidade_so_na_producao():
    states = [state(1, "setup", dt(8), dt(8, 30), 1800), state(1, "producao", dt(8, 30), dt(10), 5400)]
    result = event_log.production_events([fact(1)], states, [qty("boa", 10, dt(9))])
    rows = {item["atividade"]: item for item in result["items"]}
    assert rows["setup"]["tempo_real_segundos"] == 1800
    assert rows["setup"]["quantidade_boa"] is None
    assert rows["producao"]["tempo_real_segundos"] == 5400
    assert rows["producao"]["quantidade_boa"] == 10
    assert result["summary"]["quantidade_boa"] == 10


def test_sem_estado_usa_retrabalho_quando_retorno_da_qualidade():
    result = event_log.production_events([fact(1, retorno_retrabalho_qualidade=True)], [], [])
    assert result["items"][0]["atividade"] == "retrabalho"
    assert result["items"][0]["tempo_real_segundos"] is None


def test_corte_identificado_por_tarefa_e_plano_sem_quantidade():
    cut = {"codigo_tarefa": "T1", "programa": "PL1", "maquina": "LASER1", "data_inicio": dt(7),
           "data_fim": dt(8), "tempo_real_segundos": 3600, "tempo_previsto_segundos": 3000}
    item = event_log.production_events([], [], [], [cut])["items"][0]
    assert (item["tarefa"], item["plano"], item["op"]) == ("T1", "PL1", None)
    assert item["quantidade_boa"] is None
    assert item["tempo_padrao_fonte"] == "sigmanest"


def test_status_events_filtros_da_tabela_e_opcoes_do_periodo_inteiro():
    rows = [
        {"id": 1, "recurso": "R1", "categoria": "producao", "status_nome": "Produzindo", "op": "OP-100",
         "data_inicio": dt(8), "data_fim": None},
        {"id": 2, "recurso": "R2", "categoria": "producao", "status_nome": "Produzindo", "op": "OP-200",
         "data_inicio": dt(9), "data_fim": dt(10)},
        {"id": 3, "recurso": "R2", "categoria": "setup", "status_nome": "Setup", "op": "OP-200",
         "data_inicio": dt(7), "data_fim": dt(8)},
    ]
    result = event_log.status_events(rows, recurso="r2", status="produzindo")
    assert [item["id"] for item in result["items"]] == [2]
    assert result["summary"]["eventos"] == 1
    assert result["opcoes"] == {
        "recursos": [{"codigo": "R1", "nome": "R1"}, {"codigo": "R2", "nome": "R2"}],
        "status": ["Produzindo", "Setup"], "classes": ["producao", "setup"],
    }
    assert [item["id"] for item in event_log.status_events(rows, classe="setup")["items"]] == [3]
    assert [item["id"] for item in event_log.status_events(rows, op="100")["items"]] == [1]
    assert [item["id"] for item in event_log.status_events(rows, em_aberto=True)["items"]] == [1]


def test_status_events_filtra_operador_e_conta_em_aberto():
    rows = [
        {"id": 1, "recurso": "R1", "categoria": "producao", "data_inicio": dt(8), "data_fim": None,
         "segundos_periodo": 60, "operador": "Ana"},
        {"id": 2, "recurso": "R2", "categoria": "producao", "data_inicio": dt(9), "data_fim": dt(10),
         "segundos_periodo": 60, "operador": "Bruno"},
    ]
    result = event_log.status_events(rows, operador="ana")
    assert [item["id"] for item in result["items"]] == [1]
    assert result["summary"]["em_aberto"] == 1


def test_status_events_mostra_nome_liquido_do_recurso_e_filtra_pelo_codigo():
    rows = [
        {"id": 1, "recurso": "DOBRA1", "categoria": "producao", "data_inicio": dt(8), "data_fim": dt(9)},
        {"id": 2, "recurso": "Jato", "categoria": "producao", "data_inicio": dt(9), "data_fim": dt(10)},
        {"id": 3, "recurso": "JATO", "categoria": "producao", "data_inicio": dt(10), "data_fim": dt(11)},
    ]
    nomes = {"dobra1": "GASPARINI", "jato": "JATEAMENTO"}
    result = event_log.status_events(rows, nomes=nomes)
    assert {item["id"]: item["recurso_nome"] for item in result["items"]} == {1: "Gasparini", 2: "JATEAMENTO", 3: "JATEAMENTO"}
    assert result["opcoes"]["recursos"] == [{"codigo": "DOBRA1", "nome": "Gasparini"}, {"codigo": "Jato", "nome": "JATEAMENTO"}]
    assert [item["id"] for item in event_log.status_events(rows, nomes=nomes, recurso="Jato")["items"]] == [3, 2]
