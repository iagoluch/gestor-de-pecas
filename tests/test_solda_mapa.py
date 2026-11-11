"""Solda em três níveis: classificação por código exato e contagens do mapa."""

from mes.services import solda_mapa as sm


def _mapa(produtos=None, subconjuntos=None, vinculos=None):
    return {
        "produtos": produtos if produtos is not None else [
            {"id": 1, "nome": "Carreta", "codigo": "P1", "ativo": True},
            {"id": 2, "nome": "Plataforma", "codigo": "P2", "ativo": True},
        ],
        "subconjuntos": subconjuntos if subconjuntos is not None else [
            {"id": 10, "produto_id": 1, "nome": "Chassi", "codigo": "S1", "ativo": True},
            {"id": 11, "produto_id": 1, "nome": "Eixo", "codigo": "S2", "ativo": True},
        ],
        "vinculos": vinculos if vinculos is not None else [
            {"id": 100, "produto_id": 1, "subconjunto_id": 10, "codigo_item": "0001234"},
        ],
    }


def test_codigo_exato_cai_no_subconjunto():
    r = sm.classificar(" 0001234 ", _mapa())
    assert r == {"produto_id": 1, "subconjunto_id": 10, "motivo": None}


def test_zeros_a_esquerda_nao_somem():
    assert sm.classificar("1234", _mapa())["motivo"] == sm.PRODUTO_SEM_VINCULO


def test_sem_vinculo_e_vazio_viram_pendencia():
    assert sm.classificar("999", _mapa())["motivo"] == sm.PRODUTO_SEM_VINCULO
    assert sm.classificar(None, _mapa())["motivo"] == sm.PRODUTO_SEM_VINCULO


def test_codigo_em_dois_produtos_e_ambiguo():
    vinculos = [
        {"id": 1, "produto_id": 1, "subconjunto_id": None, "codigo_item": "X"},
        {"id": 2, "produto_id": 2, "subconjunto_id": None, "codigo_item": "X"},
    ]
    assert sm.classificar("X", _mapa(vinculos=vinculos))["motivo"] == sm.PRODUTO_AMBIGUO


def test_codigo_no_produto_a_e_no_subconjunto_de_b_e_ambiguo():
    vinculos = [
        {"id": 1, "produto_id": 2, "subconjunto_id": None, "codigo_item": "X"},
        {"id": 2, "produto_id": 1, "subconjunto_id": 10, "codigo_item": "X"},
    ]
    assert sm.classificar("X", _mapa(vinculos=vinculos))["motivo"] == sm.PRODUTO_AMBIGUO


def test_codigo_no_produto_e_no_subconjunto_dele_cai_no_subconjunto():
    vinculos = [
        {"id": 1, "produto_id": 1, "subconjunto_id": None, "codigo_item": "X"},
        {"id": 2, "produto_id": 1, "subconjunto_id": 10, "codigo_item": "X"},
    ]
    assert sm.classificar("X", _mapa(vinculos=vinculos))["subconjunto_id"] == 10


def test_codigo_em_dois_subconjuntos_e_ambiguo():
    vinculos = [
        {"id": 1, "produto_id": 1, "subconjunto_id": 10, "codigo_item": "X"},
        {"id": 2, "produto_id": 1, "subconjunto_id": 11, "codigo_item": "X"},
    ]
    r = sm.classificar("X", _mapa(vinculos=vinculos))
    assert r == {"produto_id": 1, "subconjunto_id": None, "motivo": sm.SUBCONJUNTO_AMBIGUO}


def test_so_no_produto_fica_pendente_dentro_dele():
    vinculos = [{"id": 1, "produto_id": 2, "subconjunto_id": None, "codigo_item": "X"}]
    r = sm.classificar("X", _mapa(vinculos=vinculos))
    assert r == {"produto_id": 2, "subconjunto_id": None, "motivo": sm.SUBCONJUNTO_SEM_VINCULO}


def test_destino_inativo_nao_tem_fallback():
    subs = [{"id": 10, "produto_id": 1, "nome": "Chassi", "codigo": "S1", "ativo": False}]
    assert sm.classificar("0001234", _mapa(subconjuntos=subs))["motivo"] == sm.DESTINO_INATIVO
    produtos = [{"id": 1, "nome": "Carreta", "codigo": "P1", "ativo": False}]
    assert sm.classificar("0001234", _mapa(produtos=produtos))["motivo"] == sm.DESTINO_INATIVO


class _Service:
    def __init__(self, filas):
        self.filas = filas

    def listar_cartoes(self, setor, recurso):
        return {"queue": self.filas[recurso], "production": []}


def test_fila_do_setor_nao_duplica_operacao_vista_em_varias_estacoes():
    card = {"catalogo_operacao_id": 7, "op": "OP1", "product": "0001234"}
    service = _Service({"E1": [card], "E2": [dict(card)]})
    assert len(sm.fila_do_setor(service, "Solda Aço", ["E1", "E2"])) == 1


def test_mapa_conta_cada_operacao_uma_vez_e_declara_pendencias():
    fila = [
        {"catalogo_operacao_id": 1, "op": "OP1", "product": "0001234"},
        {"catalogo_operacao_id": 2, "op": "OP1", "product": "0001234"},
        {"catalogo_operacao_id": 3, "op": "OP2", "product": "SOLTO"},
    ]
    resultado = sm.montar_mapa(_mapa(), fila)
    carreta = resultado["produtos"][0]
    assert (carreta["operacoes"], carreta["ops"]) == (2, 1)
    assert carreta["subconjuntos"][0]["operacoes"] == 2
    assert [p["motivo"] for p in resultado["pendencias"]] == [sm.PRODUTO_SEM_VINCULO]
    assert resultado["totais"] == {"operacoes": 3, "ops": 2, "pendencias": 1}
