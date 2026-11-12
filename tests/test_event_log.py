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


def test_sem_demanda_automatico_tem_sistema_como_autor_e_o_clique_como_causa():
    rows = [
        # Manufatura 12/11/2026: o banco guarda quem clicou, mas quem decide o
        # "Recurso sem demanda" é o sistema.
        {"id": 1, "recurso": "R1", "categoria": "fila", "data_inicio": dt(9), "data_fim": None,
         "operador": "Ana", "automatico": True, "motivo": "Recurso sem demanda",
         "origem": "apontamento_operador", "referencia_origem": "evento_apontamento:550"},
        {"id": 2, "recurso": "R2", "categoria": "fila", "data_inicio": dt(7), "data_fim": dt(8),
         "operador": "SISTEMA", "automatico": True, "motivo": "Recurso sem demanda",
         "origem": "retorno_turno_sem_demanda"},
        {"id": 3, "recurso": "R1", "categoria": "producao", "data_inicio": dt(8), "data_fim": dt(9),
         "operador": "Ana", "automatico": False, "origem": "apontamento_operador",
         "referencia_origem": "evento_apontamento:549"},
    ]
    gatilhos = {550: {"id": 550, "estado": "fila", "operador": "Ana", "op": "OP7", "numero_operacao": "20"}}
    items = {item["id"]: item for item in event_log.status_events(rows, gatilhos=gatilhos)["items"]}
    assert items[1]["autor"] == "Sistema"
    assert items[1]["causa"] == "Recurso ficou sem OP ativa depois que Ana interrompeu a OP OP7 (op. 20)"
    assert items[2]["autor"] == "Sistema"
    assert items[2]["causa"] == "Início do turno sem OP em andamento no recurso"
    assert items[3]["autor"] == "Ana" and items[3]["causa"] is None
    # O filtro de colaborador segue o autor: Ana não "fez" o sem demanda.
    assert [item["id"] for item in event_log.status_events(rows, operador="ana", gatilhos=gatilhos)["items"]] == [3]
    assert [item["id"] for item in event_log.status_events(rows, operador="sistema")["items"]] == [1, 2]


def test_interromper_op_vira_evento_de_producao_com_quem_e_quando():
    events = [
        {"id": 1, "apontamento_id": 1, "estado": "producao", "data_hora": dt(8), "operador": "Ana"},
        {"id": 2, "apontamento_id": 1, "estado": "fila", "data_hora": dt(9), "operador": "Bruno"},
    ]
    result = event_log.production_events([fact(1, end=None)], [], [qty("boa", 4, dt(8, 30))], operator_events=events)
    interrupts = [item for item in result["items"] if item["atividade"] == "interrupcao"]
    assert len(interrupts) == 1
    assert interrupts[0]["colaborador"] == "Bruno" and interrupts[0]["inicio"] == dt(9)
    assert interrupts[0]["quantidade_boa"] is None and interrupts[0]["tempo_real_segundos"] is None
    # A quantidade continua só na linha de trabalho, sem contar duas vezes.
    assert result["summary"]["quantidade_boa"] == 4


def test_interrupcao_fora_do_periodo_consultado_nao_aparece():
    events = [
        {"id": 1, "apontamento_id": 1, "estado": "fila", "data_hora": dt(7), "operador": "Ana"},
        {"id": 2, "apontamento_id": 1, "estado": "fila", "data_hora": dt(9), "operador": "Bruno"},
    ]
    result = event_log.production_events([fact(1, end=None)], [], [], operator_events=events, periodo=(dt(8), dt(12)))
    quem = [item["colaborador"] for item in result["items"] if item["atividade"] == "interrupcao"]
    assert quem == ["Bruno"]


def test_primeira_peca_aprovada_e_reprovada_viram_eventos_de_producao():
    inspecoes = [
        {"apontamento_id": 1, "resultado": "RETRABALHO", "operador": "Ana", "data_hora": dt(9)},
        {"apontamento_id": 1, "resultado": "CONFORME", "operador": "Bruno", "data_hora": dt(9, 30)},
    ]
    result = event_log.production_events([fact(1, end=None)], [], [qty("boa", 4, dt(10))], primeiras_pecas=inspecoes)
    linhas = sorted(
        (item["colaborador"], item["resultado_primeira_peca"], item["inicio"])
        for item in result["items"] if item["atividade"] == "primeira_peca"
    )
    assert linhas == [("Ana", "RETRABALHO", dt(9)), ("Bruno", "CONFORME", dt(9, 30))]
    assert result["summary"]["quantidade_boa"] == 4


def op_event(apontamento_id, estado, moment, id_=0):
    return {"id": id_, "apontamento_id": apontamento_id, "estado": estado, "data_hora": moment}


def physical(categoria, start, end, apontamento_id=1, recurso="DOBRA1"):
    return {**state(apontamento_id, categoria, start, end, (end - start).total_seconds()), "recurso": recurso}


def test_ops_simultaneas_cada_uma_com_o_tempo_inteiro_sem_o_intervalo():
    # Homologação 11/11/2026: a 1ª OP levava todo o tempo do posto e a 2ª ficava
    # zerada. Cada OP mostra o tempo em que esteve ativa; o intervalo não conta.
    facts = [fact(1, op="OPA", start=dt(8), end=dt(10)), fact(2, op="OPB", start=dt(9), end=dt(10))]
    states = [
        physical("producao", dt(8), dt(9, 30)),
        physical("intervalo", dt(9, 30), dt(9, 45), apontamento_id=None),
        physical("producao", dt(9, 45), dt(10)),
    ]
    events = [
        op_event(1, "producao", dt(8), 1), op_event(1, "finalizado", dt(10), 4),
        op_event(2, "producao", dt(9), 2), op_event(2, "finalizado", dt(10), 3),
    ]
    result = event_log.production_events(facts, states, [], operator_events=events)
    tempos = {item["op"]: item["tempo_real_segundos"] for item in result["items"]}
    assert tempos == {"OPA": 6300, "OPB": 2700}


def test_setup_de_uma_op_enquanto_outra_produz_aparece_com_seu_tempo():
    facts = [fact(1, op="OPA", start=dt(8), end=dt(10)), fact(2, op="OPB", start=dt(8), end=dt(10))]
    states = [physical("producao", dt(8), dt(10), apontamento_id=2)]
    events = [
        op_event(1, "setup", dt(8), 1), op_event(1, "producao", dt(8, 30), 3), op_event(1, "parcial", dt(9), 4),
        op_event(1, "producao", dt(9, 30), 5), op_event(1, "finalizado", dt(10), 6),
        op_event(2, "producao", dt(8), 2), op_event(2, "finalizado", dt(10), 5),
    ]
    result = event_log.production_events(facts, states, [], operator_events=events)
    linhas = {(item["op"], item["atividade"]): item["tempo_real_segundos"] for item in result["items"]}
    assert linhas == {("OPA", "setup"): 1800, ("OPA", "producao"): 3600, ("OPB", "producao"): 7200}
