"""A leitura em lote (``_JanelaPrefetch``) não pode mover o OEE de um dia.

Sintoma reproduzido em 15/10/2026: para o mesmo filtro de um dia, o resumo
direto (``get_overview``) e a aba OEE da fachada (``analise("oee")``, que usa
``_janela_prefetch(filters, periodos=[(inicio, fim), *bounds])``) divergiam.

Duas causas, ambas na fatia em memória, não na fórmula:

1. com janela de um dia, ``bounds`` repete o próprio período e cada linha era
   anexada duas vezes ao mesmo bucket (contagem dupla de peças e de tempo);
2. estado de recurso ainda aberto era estendido até o fim do bucket
   (23:59:59), contando o futuro, enquanto o SQL recorta em ``agora``.

O repositório falso abaixo reproduz o predicado e o recorte das consultas
reais de ``app/database/database.py``.
"""

import unittest
from datetime import datetime
from unittest import mock

from mes.contracts import AnalyticsFilter
from mes.services import management as management_module
from mes.services.frontend_facade import FrontendBackendFacade
from mes.services.management import ManagementService, _JanelaPrefetch
from tests.test_backend_canonical_v11 import _CanonicalRepo

AGORA = datetime(2026, 10, 15, 14, 0)
INICIO = datetime(2026, 10, 15, 0, 0, 0)
FIM = datetime(2026, 10, 15, 23, 59, 59)

FATOS = [
    {
        "id": 1, "op": "OP1", "tipo_setor": "Dobra", "maquina": "DOBRA1",
        "status": "Finalizado", "operador_inicio": "A", "produto_codigo": "P1",
        "numero_operacao": "20", "quantidade": 20, "quantidade_boa": 20,
        "quantidade_refugo": 0, "quantidade_retrabalho": 0,
        "tempo_medio_segundos": 300,
        "data_inicio": datetime(2026, 10, 15, 8, 0),
        "data_fim": datetime(2026, 10, 15, 10, 0),
        "eventos": [
            {"id": 1, "estado": "producao", "data_hora": datetime(2026, 10, 15, 8, 0)},
            {"id": 2, "estado": "finalizado", "data_hora": datetime(2026, 10, 15, 10, 0)},
        ],
    },
    {
        "id": 2, "op": "OP2", "tipo_setor": "Dobra", "maquina": "DOBRA1",
        "status": "Em produção", "operador_inicio": "A", "produto_codigo": "P2",
        "numero_operacao": "20", "quantidade": 30, "quantidade_boa": 5,
        "quantidade_refugo": 0, "quantidade_retrabalho": 0,
        "tempo_medio_segundos": 300,
        "data_inicio": datetime(2026, 10, 15, 12, 0),
        "data_fim": None,
        "eventos": [
            {"id": 3, "estado": "producao", "data_hora": datetime(2026, 10, 15, 12, 0)},
        ],
    },
]

ESTADOS = [
    {
        "id": 10, "recurso": "DOBRA1", "tipo_setor": "Dobra", "categoria": "producao",
        "origem": "apontamento_operador",
        "data_inicio": datetime(2026, 10, 15, 8, 0),
        "data_fim": datetime(2026, 10, 15, 10, 0),
    },
    {
        "id": 11, "recurso": "DOBRA1", "tipo_setor": "Dobra", "categoria": "parada",
        "origem": "apontamento_operador",
        "data_inicio": datetime(2026, 10, 15, 10, 0),
        "data_fim": datetime(2026, 10, 15, 11, 0),
    },
    {
        # Estado ABERTO: começou às 12:00 e ainda está em produção às 14:00.
        "id": 12, "recurso": "DOBRA1", "tipo_setor": "Dobra", "categoria": "producao",
        "origem": "apontamento_operador",
        "data_inicio": datetime(2026, 10, 15, 12, 0),
        "data_fim": None,
    },
]

QUANTIDADES = [
    {"tipo": "boa", "quantidade": 10, "tipo_setor": "Dobra", "produto_codigo": "P1",
     "data_hora": datetime(2026, 10, 15, 9, 0)},
    {"tipo": "boa", "quantidade": 10, "tipo_setor": "Dobra", "produto_codigo": "P1",
     "data_hora": datetime(2026, 10, 15, 10, 0)},
    {"tipo": "boa", "quantidade": 5, "tipo_setor": "Dobra", "produto_codigo": "P2",
     "data_hora": datetime(2026, 10, 15, 13, 0)},
]


def _estados_como_sql(estados, inicio, fim, categoria=None):
    """``listar_estados_recurso_periodo`` do PostgreSQL, em memória.

    Predicado: data_inicio < fim AND COALESCE(data_fim, fim) > inicio (o
    ``&& tsrange`` da consulta real é implicado por ele). Nenhum estado, aberto
    ou fechado, conta além de min(fim, agora); períodos não positivos devolvem
    vazio.
    """

    if fim <= inicio:
        return []
    open_end = min(fim, AGORA)
    rows = []
    for raw in estados:
        if categoria and raw["categoria"] != categoria:
            continue
        if not (raw["data_inicio"] < fim and (raw["data_fim"] or fim) > inicio):
            continue
        row = dict(raw)
        row["inicio_periodo"] = max(raw["data_inicio"], inicio)
        row["fim_periodo"] = min(raw["data_fim"] or open_end, open_end)
        row["segundos_periodo"] = max(
            0.0, (row["fim_periodo"] - row["inicio_periodo"]).total_seconds()
        )
        rows.append(row)
    return rows


class _RepoDiaComEstadoAberto(_CanonicalRepo):
    """Espelha os predicados e o recorte das consultas reais do PostgreSQL."""

    def listar_fatos_operacionais_periodo(self, inicio, fim, **_kwargs):
        # COALESCE(data_inicio, data_entrada) <= fim
        # AND COALESCE(data_fim, CURRENT_TIMESTAMP) >= inicio
        return [
            dict(row) for row in FATOS
            if row["data_inicio"] <= fim and (row["data_fim"] or AGORA) >= inicio
        ]

    def listar_estados_recurso_periodo(self, inicio, fim, categoria=None, **_kwargs):
        return _estados_como_sql(ESTADOS, inicio, fim, categoria)

    def listar_eventos_quantidade_periodo(self, inicio, fim, **_kwargs):
        return [dict(row) for row in QUANTIDADES if inicio <= row["data_hora"] <= fim]


class _PrefetchAgoraFixo(_JanelaPrefetch):
    """Mesmo ``agora`` do repositório falso (no banco real: CURRENT_TIMESTAMP nos fatos, ``agora_db()`` nos estados)."""

    def __init__(self, **kwargs):
        kwargs["agora"] = AGORA
        super().__init__(**kwargs)


def _kpis(overview):
    return {
        chave: overview["kpis"][chave]["value"]
        for chave in ("oee", "availability", "performance", "ftt")
    }


class PrefetchJanelaDeUmDiaTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(management_module, "_JanelaPrefetch", _PrefetchAgoraFixo)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.filters = AnalyticsFilter(inicio=INICIO, fim=FIM)

    def _servico(self):
        return ManagementService(_RepoDiaComEstadoAberto(), now_func=lambda: AGORA)

    def _direto(self):
        return self._servico().get_overview(self.filters)

    def test_resumo_com_prefetch_da_aba_oee_bate_com_o_resumo_direto(self):
        direto = self._direto()
        servico = self._servico()
        bounds = servico._bucket_bounds(self.filters)
        # Janela de um dia: o único bucket é o próprio período (chave repetida).
        self.assertEqual(bounds, [(INICIO, FIM)])
        with servico._janela_prefetch(self.filters, periodos=[(INICIO, FIM), *bounds]):
            em_lote = servico.get_overview(self.filters)

        self.assertIsNotNone(direto["kpis"]["oee"]["value"])
        self.assertEqual(_kpis(em_lote), _kpis(direto))
        self.assertEqual(em_lote["production"], direto["production"])
        self.assertEqual(em_lote["hours"], direto["hours"])

    def test_aba_oee_da_fachada_bate_com_o_resumo_direto(self):
        direto = self._direto()
        facade = FrontendBackendFacade(_RepoDiaComEstadoAberto(), now_func=lambda: AGORA)
        aba = facade.analise("oee", self.filters)

        self.assertEqual(aba["value"], direto["kpis"]["oee"]["value"])
        ponto = aba["evolution"]["points"][0]
        for chave in ("oee", "availability", "performance"):
            self.assertEqual(
                ponto["components"][chave]["value"], direto["kpis"][chave]["value"], chave
            )

    def test_indice_nao_repete_linha_quando_o_periodo_aparece_duas_vezes(self):
        servico = self._servico()
        with servico._janela_prefetch(self.filters, periodos=[(INICIO, FIM), (INICIO, FIM)]):
            prefetch = servico._prefetch
            _, quantidades = prefetch.quantity_events(INICIO, FIM)
            _, estados = prefetch.state_rows(INICIO, FIM)
            fatos = prefetch.facts(INICIO, FIM)
        self.assertEqual(len(quantidades), len(QUANTIDADES))
        self.assertEqual(len(estados), len(ESTADOS))
        self.assertEqual(len(fatos), len(FATOS))

    def test_estado_aberto_recortado_em_agora_nos_dois_caminhos_da_fatia(self):
        repo = _RepoDiaComEstadoAberto()
        esperado = {
            row["id"]: (row["fim_periodo"], row["segundos_periodo"])
            for row in repo.listar_estados_recurso_periodo(INICIO, FIM)
        }
        # Estado aberto vale até agora (14:00), não até 23:59:59.
        self.assertEqual(esperado[12], (AGORA, 7200.0))

        # Janela carregada para um período maior que o bucket pedido.
        janela_inicio = datetime(2026, 10, 14, 0, 0)
        estados_janela = repo.listar_estados_recurso_periodo(janela_inicio, FIM)

        nao_indexado = _JanelaPrefetch(
            facts=[], quantity_available=True, quantity_events=[],
            state_available=True, state_rows=estados_janela, agora=AGORA,
        )
        _, linhas = nao_indexado.state_rows(INICIO, FIM)
        self.assertEqual(
            {row["id"]: (row["fim_periodo"], row["segundos_periodo"]) for row in linhas},
            esperado,
        )

        indexado = _JanelaPrefetch(
            facts=[], quantity_available=True, quantity_events=[],
            state_available=True, state_rows=estados_janela, agora=AGORA,
        )
        indexado.indexar([(janela_inicio, datetime(2026, 10, 14, 23, 59, 59)), (INICIO, FIM)])
        _, linhas = indexado.state_rows(INICIO, FIM)
        self.assertEqual(
            {row["id"]: (row["fim_periodo"], row["segundos_periodo"]) for row in linhas},
            esperado,
        )

    def test_estado_aberto_antigo_entra_em_todos_os_buckets_seguintes(self):
        """SQL: COALESCE(data_fim, fim) > inicio inclui o estado aberto em cada
        bucket posterior ao início; o índice não pode restringi-lo ao bucket
        em que ele começou."""

        aberto = {
            "id": 99, "recurso": "DOBRA1", "tipo_setor": "Dobra", "categoria": "producao",
            "data_inicio": datetime(2026, 10, 10, 8, 0), "data_fim": None,
            "inicio_periodo": datetime(2026, 10, 10, 8, 0), "fim_periodo": AGORA,
            "segundos_periodo": 0.0,
        }
        dias = [
            (datetime(2026, 10, d, 0, 0), datetime(2026, 10, d, 23, 59, 59))
            for d in range(10, 16)
        ]
        prefetch = _JanelaPrefetch(
            facts=[], quantity_available=True, quantity_events=[],
            state_available=True, state_rows=[aberto], agora=AGORA,
        )
        prefetch.indexar(dias)
        for inicio, fim in dias:
            with self.subTest(dia=inicio.date()):
                _, linhas = prefetch.state_rows(inicio, fim)
                self.assertEqual([row["id"] for row in linhas], [99])
                self.assertEqual(linhas[0]["fim_periodo"], min(fim, AGORA))


def _dia(dia, h0=0, m0=0, s0=0, h1=23, m1=59, s1=59):
    return (
        datetime(2026, 10, dia, h0, m0, s0),
        datetime(2026, 10, dia, h1, m1, s1),
    )


def _estado(id_, inicio, fim=None, **extra):
    return {
        "id": id_, "recurso": "DOBRA1", "tipo_setor": "Dobra",
        "categoria": "producao", "origem": "apontamento_operador",
        "data_inicio": inicio, "data_fim": fim, **extra,
    }


ESTADOS_BORDA = [
    _estado(1, datetime(2026, 10, 10, 8, 0)),                                  # aberto antigo
    _estado(2, datetime(2026, 10, 15, 12, 0)),                                 # aberto hoje
    _estado(3, datetime(2026, 10, 15, 16, 0)),                                 # aberto "no futuro"
    _estado(4, datetime(2026, 10, 11, 20, 0), datetime(2026, 10, 13, 6, 0)),   # fechado multi-dia
    _estado(5, datetime(2026, 10, 12, 0, 0), datetime(2026, 10, 12, 12, 0)),   # termina no meio
    _estado(6, datetime(2026, 10, 13, 0, 0), datetime(2026, 10, 13, 23, 59, 59)),
    _estado(7, datetime(2026, 10, 14, 23, 59, 59)),                            # aberto começa no fim do dia 14
    _estado(8, datetime(2026, 10, 15, 8, 0), datetime(2026, 10, 15, 17, 30)),  # fechado com fim depois de agora
]

# Arranjos de sub-períodos: uniforme (inclui dias depois de agora), largura não
# uniforme (passo None), mesma chave repetida, mesmo início com fins distintos
# e fatias horárias em torno de agora.
LAYOUTS = {
    "diario_com_futuro": [_dia(d) for d in range(10, 18)],
    "largura_nao_uniforme": [
        _dia(10), (datetime(2026, 10, 11), datetime(2026, 10, 12, 23, 59, 59)),
        _dia(13), _dia(15),
    ],
    "chave_repetida": [_dia(11), _dia(12), _dia(12), _dia(13)],
    "chave_repetida_so_microssegundos": [
        (datetime(2026, 10, 15), datetime(2026, 10, 15, 23, 59, 59)),
        (datetime(2026, 10, 15), datetime(2026, 10, 15, 23, 59, 59, 999999)),
    ],
    "mesmo_inicio_fins_diferentes": [
        (datetime(2026, 10, 14), datetime(2026, 10, 14, 12, 0)),
        (datetime(2026, 10, 14), datetime(2026, 10, 14, 23, 59, 59)),
        _dia(15),
    ],
    "horario_em_torno_de_agora": [
        (datetime(2026, 10, 15, h), datetime(2026, 10, 15, h, 59, 59)) for h in range(10, 20)
    ],
}


def _chave(row):
    return row["id"], row["inicio_periodo"], row["fim_periodo"], row["segundos_periodo"]


class FatiaDeEstadosIgualAoSqlTests(unittest.TestCase):
    """Cada bucket da fatia tem de devolver exatamente o que o SQL devolveria."""

    def _prefetch(self, estados, periodos, *, indexar, derivados=True, agora=AGORA):
        todos = [dict(row) for row in estados]
        inicio_janela = min(i for i, _ in periodos)
        fim_janela = max(f for _, f in periodos)
        if derivados:
            linhas = _estados_como_sql(todos, inicio_janela, fim_janela)
        else:
            linhas = [
                row for row in todos
                if row["data_inicio"] < fim_janela
                and (row["data_fim"] or fim_janela) > inicio_janela
            ]
        prefetch = _JanelaPrefetch(
            facts=[], quantity_available=True, quantity_events=[],
            state_available=True, state_rows=linhas, agora=agora,
        )
        if indexar:
            prefetch.indexar(periodos)
        return prefetch

    def test_todo_bucket_bate_com_o_sql_nos_dois_caminhos(self):
        for nome, periodos in LAYOUTS.items():
            for indexar in (True, False):
                prefetch = self._prefetch(ESTADOS_BORDA, periodos, indexar=indexar)
                for inicio, fim in periodos:
                    with self.subTest(layout=nome, indexar=indexar, bucket=(inicio, fim)):
                        _, linhas = prefetch.state_rows(inicio, fim)
                        esperado = _estados_como_sql(
                            ESTADOS_BORDA, _JanelaPrefetch._limite(inicio),
                            _JanelaPrefetch._limite(fim),
                        )
                        self.assertEqual(
                            sorted(map(_chave, linhas)), sorted(map(_chave, esperado))
                        )

    def test_estado_fechado_com_fim_no_futuro_conta_so_ate_agora(self):
        # Fim de turno gravado antecipado (17:30) não pode virar 9h30 às 14h.
        fechado = _estado(1, datetime(2026, 10, 15, 8, 0), datetime(2026, 10, 15, 17, 30))
        for indexar in (True, False):
            with self.subTest(indexar=indexar):
                _, linhas = self._prefetch(
                    [fechado], [_dia(15)], indexar=indexar
                ).state_rows(*_dia(15))
                self.assertEqual(linhas[0]["fim_periodo"], AGORA)
                self.assertEqual(
                    linhas[0]["segundos_periodo"],
                    (AGORA - datetime(2026, 10, 15, 8, 0)).total_seconds(),
                )

    def test_bucket_inteiramente_depois_de_agora_inclui_estado_aberto_com_zero_segundos(self):
        futuro = _dia(16)
        prefetch = self._prefetch(
            [_estado(1, datetime(2026, 10, 10, 8, 0))], [_dia(15), futuro], indexar=True
        )
        _, linhas = prefetch.state_rows(*futuro)
        self.assertEqual([row["id"] for row in linhas], [1])
        self.assertEqual(linhas[0]["segundos_periodo"], 0.0)
        self.assertEqual(linhas[0]["inicio_periodo"], futuro[0])

    def test_bucket_inteiramente_antes_de_agora_conta_o_bucket_inteiro(self):
        passado = _dia(12)
        prefetch = self._prefetch(
            [_estado(1, datetime(2026, 10, 10, 8, 0))], [passado, _dia(15)], indexar=True
        )
        _, linhas = prefetch.state_rows(*passado)
        self.assertEqual(linhas[0]["fim_periodo"], passado[1])
        self.assertEqual(linhas[0]["segundos_periodo"], 86399.0)

    def test_sem_agora_o_estado_aberto_vai_ate_o_fim_do_bucket(self):
        for indexar in (True, False):
            with self.subTest(indexar=indexar):
                prefetch = self._prefetch(
                    [_estado(1, datetime(2026, 10, 15, 12, 0))], [_dia(15)],
                    indexar=indexar, agora=None,
                )
                _, linhas = prefetch.state_rows(*_dia(15))
                self.assertEqual(linhas[0]["fim_periodo"], FIM)

    def test_repositorio_sem_campos_derivados_mantem_o_formato_original(self):
        periodos = LAYOUTS["diario_com_futuro"]
        for indexar in (True, False):
            prefetch = self._prefetch(
                ESTADOS_BORDA, periodos, indexar=indexar, derivados=False
            )
            for inicio, fim in periodos:
                with self.subTest(indexar=indexar, bucket=(inicio, fim)):
                    _, linhas = prefetch.state_rows(inicio, fim)
                    esperado = sorted(
                        row["id"] for row in ESTADOS_BORDA
                        if row["data_inicio"] < fim and (row["data_fim"] or fim) > inicio
                    )
                    self.assertEqual(sorted(row["id"] for row in linhas), esperado)
                    for row in linhas:
                        self.assertNotIn("inicio_periodo", row)
                        self.assertNotIn("fim_periodo", row)
                        self.assertNotIn("segundos_periodo", row)


if __name__ == "__main__":
    unittest.main()
