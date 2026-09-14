"""Cenário de planejamento para inspeção visual da interface (banco TESTE).

O que este script cria — e só isso:

* **3 tarefas** de Corte com **5 planos (nestings)** cada, distribuídos entre o
  **Laser** (``AMADA_ENSIS``) e o **Plasma** (``MESSER_XPR_300``), e **5 OPs**
  por tarefa na granularidade canônica ``(tarefa, OP, peça)``;
* **5 OPs separadas**, sem etapa de Corte, para que Serra, Dobra, Usinagem,
  Solda e Pintura tenham fila imediata;
* **roteiro completo** por OP, atravessando os setores até a inspeção da
  Qualidade e o marco terminal, no mesmo formato que a ingestão real do TOTVS
  grava (``fonte='totvs_production_order_v1'``, ``totvs_*`` preenchidos,
  ``INSPECAO`` e ``FINALIZADA`` inativas por contrato);
* templates de cota da Qualidade para parte dos produtos, para exercitar tanto
  a inspeção com cotas cadastradas quanto o cadastro na hora.

O que este script **não** cria: apontamento, evento de estado, produção,
parada, refugo ou qualquer movimento de execução. Execução é o que você vai
gerar usando as telas — é justamente isso que se quer observar. Nenhum número
de indicador é fabricado aqui.

Segurança:

* grava exclusivamente em ``TEST_DATABASE_URL``, via ``load_postgres_config``,
  que recusa banco cujo nome não contenha ``test``, recusa DSN igual ao
  ``DATABASE_URL`` e respeita ``GESTOR_EXPECTED_DATABASE``;
* tudo em uma transação, sob *advisory lock*, e **idempotente**: rodar de novo
  atualiza as mesmas linhas em vez de duplicar;
* todo identificador criado carrega o prefixo ``ZZ``/``zz-gui:``, o que permite
  ao ``scripts/limpar_cenario_gui.py`` remover exatamente este cenário.

Uso::

    .venv/Scripts/python.exe scripts/seed_cenario_gui.py --dry-run
    .venv/Scripts/python.exe scripts/seed_cenario_gui.py
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database.config import load_postgres_config  # noqa: E402
from app.database.database import Database  # noqa: E402


# ---------------------------------------------------------------- identidade
# Prefixo único do cenário. Nenhuma OP, tarefa ou programa real começa com ZZ,
# então a limpeza consegue ser cirúrgica sem heurística.
PREFIXO = "ZZ"
PREFIXO_PLANO = "zz-gui:"
TAG_CENARIO = "cenario_gui_wave2"
# Assinatura gravada nos templates da Qualidade criados aqui. É por ela que a
# limpeza distingue o que é do cenário do que foi cadastrado por um operador.
AUTOR_CENARIO = "CENARIO_GUI"
LOCK_ID = 874_210_309

# Identidade corporativa observada nas OPs reais já ingeridas no TESTE.
FILIAL = "010004"
EMPRESA = "01"
ROTEIRO = "40"
APLICACAO_ORIGEM = "SIGAPCP"
FONTE_ROTEIRO = "totvs_production_order_v1"
FONTE_CATALOGO = "cenario_gui_teste"


# ------------------------------------------------------------------ recursos
# Só códigos que já existem em catalogo_recursos_pcfactory com tipo_setor
# canônico e que o app/core/resource_mapping.py reconhece como posto real.
POSTOS = {
    "Corte": ("LASER1", "PLASMA"),
    "Serra": ("SERRA1", "SERRA2", "SERRA3"),
    "Dobra": ("DOBRA1", "DOBRA2", "DOBRA3"),
    "Usinagem": ("CNC-01", "CNC-02", "FRESA1", "TCNC-1", "TORNOC"),
    "Solda": ("SOLDA4",),
    "Pintura": ("PINT.L",),
}

# Centro de trabalho por setor, no idioma do ProductionOrder. Caldeiraria
# (CALDER) agrupa os postos de bancada/máquina, como no roteiro real.
CENTRO_TRABALHO = {
    "Corte": "CORTE",
    "Serra": "CALDER",
    "Dobra": "CALDER",
    "Usinagem": "CALDER",
    "Solda": "SOLDA",
    "Pintura": "PINTU",
}

# Tempo padrão unitário por setor, em segundos. Existe para que "Tempo padrão ×
# real" e a Cronoanálise tenham base de comparação assim que houver execução.
TEMPO_PADRAO_SEGUNDOS = {
    "Corte": 150.0,
    "Serra": 95.0,
    "Dobra": 180.0,
    "Usinagem": 420.0,
    "Solda": 600.0,
    "Pintura": 240.0,
}

MAQUINA_SIGMANEST = {"LASER1": "AMADA_ENSIS", "PLASMA": "MESSER_XPR_300"}


# ------------------------------------------------------------------ produtos
# Códigos e descrições no estilo dos produtos reais do Protheus (IPCX/PPCX/IPM/
# PNT/PSM). Nenhum deles existe no cadastro real; são deste cenário.
PRODUTOS = (
    ("IPCX04014041P", "CHAPA FECHAMENTO LATERAL 8MM"),
    ("PPCX05001035", "APOIO LATERAL MOLINETE"),
    ("IPM011022108", "DOBRADICA INFERIOR 60"),
    ("PPCX03001010", "TUBO SUPERIOR LATERAL CHASSI"),
    ("IPM010001005T", "COMPLEMENTO RASPADOR PRODUTTIVA 5550"),
    ("PNT002002003", "BRACO ARTICULACAO"),
    ("PSM014003121", "SUPORTE MANCAL DIANTEIRO"),
    ("IPCX04016022", "CHAPA REFORCO TRASEIRO"),
    ("PPCX05001120", "TUBO INFERIOR LATERAL CHASSI 35"),
    ("IPM011024300", "MANCAL EIXO TRANSPORTADOR"),
    ("PNT002004017", "TRAVESSA CENTRAL ELEVADOR"),
    ("PSM014003400", "FLANGE ACOPLAMENTO 120"),
    ("IPCX04018005", "CHAPA GUIA CORREIA"),
    ("PPCX03001044", "TUBO DIAGONAL TORRE"),
    ("IPM010001220", "EIXO ACIONAMENTO PRODUTTIVA"),
    ("PNT002006012", "SUPORTE MOTOR REDUTOR"),
    ("PSM014005090", "CHAPA BASE MOTOR"),
    ("IPCX04019110", "CHAPA TAMPA INSPECAO"),
    ("PPCX05001210", "PERFIL LATERAL ESTEIRA"),
    ("IPM011026044", "BUCHA GUIA ROLETE"),
)


# ------------------------------------------------------------------ tarefas
@dataclass(frozen=True)
class TarefaCorte:
    codigo: str
    material: str
    espessura: float
    chapa: str
    # Máquina de cada um dos 5 planos, na ordem do nesting.
    maquinas: tuple[str, ...]


TAREFAS = (
    TarefaCorte(
        codigo=f"{PREFIXO}T4501",
        material="AÇO ASTM A36",
        espessura=6.35,
        chapa="CHAPA 3000 x 1500",
        # Tarefa mista: o mesmo lote passa pelo Laser e pelo Plasma.
        maquinas=("LASER1", "LASER1", "PLASMA", "LASER1", "PLASMA"),
    ),
    TarefaCorte(
        codigo=f"{PREFIXO}T4502",
        material="AÇO INOX 304",
        espessura=3.00,
        chapa="CHAPA 2000 x 1000",
        maquinas=("LASER1",) * 5,
    ),
    TarefaCorte(
        codigo=f"{PREFIXO}T4503",
        material="AÇO CARBONO SAE 1020",
        espessura=12.70,
        chapa="CHAPA 6000 x 2000",
        maquinas=("PLASMA",) * 5,
    ),
)


# ------------------------------------------------------------------- roteiros
# Cada roteiro é a sequência de setores produtivos. INSPECAO e FINALIZADA são
# acrescentadas automaticamente, como no ProductionOrder real.
ROTEIROS_CORTE = (
    ("Corte", "Serra", "Dobra", "Usinagem", "Solda", "Pintura"),
    ("Corte", "Dobra", "Usinagem", "Solda", "Pintura"),
    ("Corte", "Dobra", "Solda"),
    ("Corte", "Serra", "Dobra", "Usinagem", "Solda", "Pintura"),
    ("Corte", "Usinagem", "Pintura"),
)

ROTEIROS_SEPARADOS = (
    ("Serra", "Usinagem", "Solda", "Pintura"),
    ("Dobra", "Usinagem", "Solda", "Pintura"),
    ("Usinagem", "Dobra", "Solda"),
    ("Dobra", "Solda", "Pintura"),
    ("Serra", "Dobra", "Usinagem", "Solda", "Pintura"),
)


@dataclass(frozen=True)
class Etapa:
    numero_operacao: str
    ordem: int
    codigo_recurso: str
    descricao_operacao: str
    tipo_setor: str | None
    centro_trabalho: str
    codigo_maquina: str
    tempo_medio_segundos: float | None
    ativo: bool
    marco_terminal: bool
    inspecao_qualidade: bool
    totvs_activity_id: str


@dataclass(frozen=True)
class OrdemProducao:
    codigo: str
    produto_codigo: str
    produto_descricao: str
    quantidade: int
    prioridade: int
    inicio_planejado: datetime
    fim_planejado: datetime
    prazo_entrega: datetime
    etapas: tuple[Etapa, ...]
    codigo_tarefa: str | None = None
    setor_destino: str = "Almoxarifado"


@dataclass
class Cenario:
    ordens: list[OrdemProducao] = field(default_factory=list)
    tarefas: list[TarefaCorte] = field(default_factory=list)
    planos: list[dict] = field(default_factory=list)
    linhas_sigmanest: list[dict] = field(default_factory=list)
    programas: list[dict] = field(default_factory=list)
    templates_qualidade: list[dict] = field(default_factory=list)


class RodizioDePostos:
    """Distribui as etapas entre TODOS os postos reais de cada setor.

    Sem isto, um setor com cinco máquinas receberia carga só nas primeiras, e
    os demais postos abririam a tela sem nada para apontar.
    """

    def __init__(self):
        self._contadores = {setor: 0 for setor in POSTOS}

    def proximo(self, setor: str) -> str:
        opcoes = POSTOS[setor]
        escolhido = opcoes[self._contadores[setor] % len(opcoes)]
        self._contadores[setor] += 1
        return escolhido


def _montar_etapas(setores, *, rodizio: RodizioDePostos, base_activity: int) -> tuple[Etapa, ...]:
    """Projeta o roteiro no formato exato que a ingestão TOTVS grava.

    ``ordem`` começa em 2 e ``INSPECAO``/``FINALIZADA`` entram inativas com os
    marcadores canônicos — a mesma forma observada nas OPs reais já ingeridas.
    """

    etapas: list[Etapa] = []
    ordem = 2
    for posicao, setor in enumerate(setores):
        recurso = rodizio.proximo(setor)
        etapas.append(
            Etapa(
                numero_operacao=str((posicao + 1) * 10),
                ordem=ordem,
                codigo_recurso=recurso,
                descricao_operacao=setor.upper(),
                tipo_setor=setor,
                centro_trabalho=CENTRO_TRABALHO[setor],
                codigo_maquina=recurso,
                tempo_medio_segundos=TEMPO_PADRAO_SEGUNDOS[setor],
                ativo=True,
                marco_terminal=False,
                inspecao_qualidade=False,
                totvs_activity_id=str(base_activity + ordem),
            )
        )
        ordem += 1

    # Assinatura exata reconhecida por app/core/quality.py:
    # (ActivityDescription, WorkCenterCode, MachineCode) = (INSPECAO, CALDER, INSPEC).
    etapas.append(
        Etapa(
            numero_operacao=str((len(setores) + 1) * 10),
            ordem=ordem,
            codigo_recurso="INSPEC",
            descricao_operacao="INSPECAO",
            tipo_setor=None,
            centro_trabalho="CALDER",
            codigo_maquina="INSPEC",
            tempo_medio_segundos=None,
            ativo=False,
            marco_terminal=False,
            inspecao_qualidade=True,
            totvs_activity_id=str(base_activity + ordem),
        )
    )
    ordem += 1
    etapas.append(
        Etapa(
            numero_operacao="99",
            ordem=ordem,
            codigo_recurso="ALMOX4",
            descricao_operacao="FINALIZADA",
            tipo_setor=None,
            centro_trabalho="ALMOX4",
            codigo_maquina="ALMOX4",
            tempo_medio_segundos=None,
            ativo=False,
            marco_terminal=True,
            inspecao_qualidade=False,
            totvs_activity_id=str(base_activity + ordem),
        )
    )
    return tuple(etapas)


def _destino_apos_corte(etapas) -> str:
    """Primeiro setor produtivo depois do Corte, para o Destaque."""

    achou_corte = False
    for etapa in etapas:
        if etapa.tipo_setor == "Corte":
            achou_corte = True
            continue
        if achou_corte and etapa.tipo_setor:
            return etapa.tipo_setor
    return "Almoxarifado"


def construir_cenario(hoje: date) -> Cenario:
    """Monta o cenário inteiro em memória, sem tocar no banco."""

    cenario = Cenario(tarefas=list(TAREFAS))
    produto_seq = 0
    activity_seq = 900_000
    rodizio = RodizioDePostos()

    # ------------------------------------------------------ OPs com Corte
    for indice_tarefa, tarefa in enumerate(TAREFAS):
        ops_da_tarefa: list[OrdemProducao] = []
        for n in range(5):
            produto_codigo, produto_descricao = PRODUTOS[produto_seq % len(PRODUTOS)]
            produto_seq += 1
            activity_seq += 100
            indice_global = indice_tarefa * 5 + n
            etapas = _montar_etapas(
                ROTEIROS_CORTE[n],
                rodizio=rodizio,
                base_activity=activity_seq,
            )
            inicio = datetime.combine(hoje, datetime.min.time()) + timedelta(
                days=indice_tarefa, hours=7
            )
            ordem = OrdemProducao(
                codigo=f"{PREFIXO}2609C{indice_tarefa + 1}{n + 1:02d}",
                produto_codigo=produto_codigo,
                produto_descricao=produto_descricao,
                quantidade=(n + 1) * 4 + indice_tarefa * 2,
                prioridade=(indice_global % 5) + 1,
                inicio_planejado=inicio,
                fim_planejado=inicio + timedelta(hours=9),
                prazo_entrega=inicio + timedelta(days=5),
                etapas=etapas,
                codigo_tarefa=tarefa.codigo,
                setor_destino=_destino_apos_corte(etapas),
            )
            ops_da_tarefa.append(ordem)
            cenario.ordens.append(ordem)

        # ---------------------------------------------- 5 planos por tarefa
        for sequencia, recurso in enumerate(tarefa.maquinas, start=1):
            programa = f"{PREFIXO}9{indice_tarefa + 1}{sequencia:02d}"
            # data_programa precisa ser >= o cutoff da fila de Corte; usa-se a
            # janela recente para o plano aparecer como trabalho pendente.
            data_programa = hoje - timedelta(days=(sequencia - 1) % 3)
            cenario.programas.append(
                {"codigo_tarefa": tarefa.codigo, "programa": programa}
            )
            cenario.planos.append(
                {
                    "plano_hash": f"{PREFIXO_PLANO}{tarefa.codigo}:{programa}:{sequencia}",
                    "codigo_tarefa": tarefa.codigo,
                    "programa": programa,
                    "nome_chapa": tarefa.chapa,
                    "sequencia_nesting": sequencia,
                    "area_usada": round(1.85 + sequencia * 0.12, 2),
                    "fracao_sucata": round(0.08 + sequencia * 0.01, 2),
                    # Cada nesting processa as peças de várias OPs da tarefa.
                    "quantidade_processo": sum(
                        item.quantidade for item in ops_da_tarefa
                    ) // 5 + sequencia,
                    "maquina_sigmanest": MAQUINA_SIGMANEST[recurso],
                    "tempo_previsto_segundos": 480 + sequencia * 120,
                    "data_programa": data_programa,
                }
            )

        # ------------------------------- correlação (tarefa, OP, peça)
        for ordem in ops_da_tarefa:
            setores = {etapa.tipo_setor for etapa in ordem.etapas}
            cenario.linhas_sigmanest.append(
                {
                    "linha_hash": f"{PREFIXO_PLANO}{tarefa.codigo}:{ordem.codigo}",
                    "codigo_tarefa": tarefa.codigo,
                    "codigo_op": ordem.codigo,
                    "id_peca": ordem.produto_codigo,
                    "setor_destino": ordem.setor_destino,
                    "quantidade": ordem.quantidade,
                    "dobra": "Sim" if "Dobra" in setores else None,
                    "usinagem": "Sim" if "Usinagem" in setores else None,
                    "solda": "Sim" if "Solda" in setores else None,
                    "chanfro": None,
                }
            )

    # ------------------------------------------------- 5 OPs separadas
    for n, setores in enumerate(ROTEIROS_SEPARADOS):
        produto_codigo, produto_descricao = PRODUTOS[produto_seq % len(PRODUTOS)]
        produto_seq += 1
        activity_seq += 100
        etapas = _montar_etapas(setores, rodizio=rodizio, base_activity=activity_seq)
        inicio = datetime.combine(hoje, datetime.min.time()) + timedelta(hours=7 + n)
        cenario.ordens.append(
            OrdemProducao(
                codigo=f"{PREFIXO}2609S{n + 1:02d}",
                produto_codigo=produto_codigo,
                produto_descricao=produto_descricao,
                quantidade=(n + 2) * 5,
                prioridade=(n % 5) + 1,
                inicio_planejado=inicio,
                fim_planejado=inicio + timedelta(hours=6),
                prazo_entrega=inicio + timedelta(days=3),
                etapas=etapas,
            )
        )

    # ------------------------------------------- templates da Qualidade
    # Só parte dos produtos recebe template: assim dá para testar tanto a
    # inspeção com cotas prontas quanto o cadastro na hora.
    for ordem in cenario.ordens[:4]:
        cenario.templates_qualidade.append(
            {
                "produto_codigo": ordem.produto_codigo,
                "produto_descricao": ordem.produto_descricao,
                "cotas": (
                    ("Comprimento total", "1200,0 +/- 1,0"),
                    ("Largura útil", "480,0 +/- 0,5"),
                    ("Furo de fixação", "12,0 +/- 0,2"),
                ),
            }
        )
    return cenario


# ------------------------------------------------------------------- gravação
def aplicar(cenario: Cenario, *, agora: datetime) -> dict:
    config = load_postgres_config(testing=True)
    alvo = config.safe_target
    nome_banco = str(alvo.get("dbname") or "").casefold()
    if "test" not in nome_banco:
        raise RuntimeError(
            "Carga recusada: TEST_DATABASE_URL deve apontar para um banco de teste."
        )

    db = Database(config=config)
    try:
        with db.connection() as conexao, conexao.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
            _gravar_ordens(cursor, cenario, agora)
            tarefa_ids = _gravar_tarefas(cursor, cenario, agora)
            _gravar_corte(cursor, cenario, tarefa_ids, agora)
            templates_ignorados = _gravar_templates_qualidade(cursor, cenario, agora)
            cursor.execute(
                """
                INSERT INTO eventos_sistema (
                    tipo, origem, referencia, mensagem, operador, detalhes, data_hora
                ) VALUES (%s, 'scripts/seed_cenario_gui.py', %s,
                          'Cenário de planejamento para inspeção visual aplicado.',
                          'SEED', %s, %s)
                """,
                (
                    TAG_CENARIO,
                    TAG_CENARIO,
                    json.dumps(
                        {
                            "ops": len(cenario.ordens),
                            "tarefas": len(cenario.tarefas),
                            "planos": len(cenario.planos),
                        }
                    ),
                    agora,
                ),
            )
            conferencia = _conferir(cursor)
        return {
            "alvo": alvo,
            "conferencia": conferencia,
            "templates_preservados": templates_ignorados,
        }
    finally:
        db.close()


def _gravar_ordens(cursor, cenario: Cenario, agora: datetime) -> None:
    for ordem in cenario.ordens:
        cursor.execute(
            """
            INSERT INTO catalogo_pcp_ops (
                codigo_op, produto_codigo, produto_descricao, quantidade, unidade,
                data_emissao, status_pcp, filial, local_estoque, roteiro, recurso,
                ativo, sincronizado_em, data_liberacao, inicio_planejado,
                fim_planejado, prazo_entrega, prioridade, totvs_unique_id,
                totvs_company_id, totvs_branch_id, totvs_generated_on,
                totvs_source_application
            ) VALUES (%s, %s, %s, %s, 'UN', %s, '1', %s, 'TESTE', %s, %s, TRUE, %s,
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (codigo_op) DO UPDATE SET
                produto_codigo = EXCLUDED.produto_codigo,
                produto_descricao = EXCLUDED.produto_descricao,
                quantidade = EXCLUDED.quantidade,
                unidade = EXCLUDED.unidade,
                data_emissao = EXCLUDED.data_emissao,
                status_pcp = EXCLUDED.status_pcp,
                filial = EXCLUDED.filial,
                roteiro = EXCLUDED.roteiro,
                recurso = EXCLUDED.recurso,
                ativo = TRUE,
                sincronizado_em = EXCLUDED.sincronizado_em,
                data_liberacao = EXCLUDED.data_liberacao,
                inicio_planejado = EXCLUDED.inicio_planejado,
                fim_planejado = EXCLUDED.fim_planejado,
                prazo_entrega = EXCLUDED.prazo_entrega,
                prioridade = EXCLUDED.prioridade,
                totvs_unique_id = EXCLUDED.totvs_unique_id,
                totvs_company_id = EXCLUDED.totvs_company_id,
                totvs_branch_id = EXCLUDED.totvs_branch_id,
                totvs_generated_on = EXCLUDED.totvs_generated_on,
                totvs_source_application = EXCLUDED.totvs_source_application
            """,
            (
                ordem.codigo, ordem.produto_codigo, ordem.produto_descricao,
                ordem.quantidade, agora.date(), FILIAL, ROTEIRO,
                ordem.etapas[0].codigo_recurso, agora, agora,
                ordem.inicio_planejado, ordem.fim_planejado, ordem.prazo_entrega,
                ordem.prioridade, f"{EMPRESA}|{FILIAL}|{ordem.codigo}",
                EMPRESA, FILIAL, agora, APLICACAO_ORIGEM,
            ),
        )
        for etapa in ordem.etapas:
            cursor.execute(
                """
                INSERT INTO catalogo_operacoes_op (
                    codigo_op, produto_codigo, produto_descricao, numero_operacao,
                    codigo_recurso, descricao_operacao, tipo_setor, filial, tipo,
                    roteiro, tempo_medio_segundos, ordem, fonte, ativo,
                    sincronizado_em, totvs_activity_id, totvs_work_center_code,
                    totvs_machine_code, marco_terminal, inspecao_qualidade
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '1', %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s)
                ON CONFLICT (codigo_op, totvs_activity_id)
                    WHERE totvs_activity_id IS NOT NULL
                DO UPDATE SET
                    produto_codigo = EXCLUDED.produto_codigo,
                    produto_descricao = EXCLUDED.produto_descricao,
                    numero_operacao = EXCLUDED.numero_operacao,
                    codigo_recurso = EXCLUDED.codigo_recurso,
                    descricao_operacao = EXCLUDED.descricao_operacao,
                    tipo_setor = EXCLUDED.tipo_setor,
                    tempo_medio_segundos = EXCLUDED.tempo_medio_segundos,
                    ordem = EXCLUDED.ordem,
                    ativo = EXCLUDED.ativo,
                    sincronizado_em = EXCLUDED.sincronizado_em,
                    totvs_work_center_code = EXCLUDED.totvs_work_center_code,
                    totvs_machine_code = EXCLUDED.totvs_machine_code,
                    marco_terminal = EXCLUDED.marco_terminal,
                    inspecao_qualidade = EXCLUDED.inspecao_qualidade
                """,
                (
                    ordem.codigo, ordem.produto_codigo, ordem.produto_descricao,
                    etapa.numero_operacao, etapa.codigo_recurso,
                    etapa.descricao_operacao, etapa.tipo_setor, FILIAL, ROTEIRO,
                    etapa.tempo_medio_segundos, etapa.ordem, FONTE_ROTEIRO,
                    etapa.ativo, agora, etapa.totvs_activity_id,
                    etapa.centro_trabalho, etapa.codigo_maquina,
                    etapa.marco_terminal, etapa.inspecao_qualidade,
                ),
            )


def _gravar_tarefas(cursor, cenario: Cenario, agora: datetime) -> dict[str, int]:
    tarefa_ids: dict[str, int] = {}
    for tarefa in cenario.tarefas:
        cursor.execute(
            """
            INSERT INTO tarefas (
                codigo_tarefa, material, espessura, status, data_inicio_destaque,
                data_finalizacao, data_despacho, observacoes
            ) VALUES (%s, %s, %s, NULL, NULL, NULL, NULL, %s)
            ON CONFLICT (codigo_tarefa) DO UPDATE SET
                material = EXCLUDED.material,
                espessura = EXCLUDED.espessura,
                status = NULL,
                data_inicio_destaque = NULL,
                data_finalizacao = NULL,
                data_despacho = NULL,
                observacoes = EXCLUDED.observacoes
            RETURNING id
            """,
            (
                tarefa.codigo, tarefa.material, tarefa.espessura,
                "Cenário de teste da interface; não é planejamento real.",
            ),
        )
        tarefa_ids[tarefa.codigo] = int(cursor.fetchone()["id"])
        cursor.execute(
            """
            INSERT INTO catalogo_sigmanest_tarefas (
                codigo_tarefa, material, espessura, ativo, sincronizado_em
            ) VALUES (%s, %s, %s, TRUE, %s)
            ON CONFLICT (codigo_tarefa) DO UPDATE SET
                material = EXCLUDED.material,
                espessura = EXCLUDED.espessura,
                ativo = TRUE,
                sincronizado_em = EXCLUDED.sincronizado_em
            """,
            (tarefa.codigo, tarefa.material, tarefa.espessura, agora),
        )

    for ordem in cenario.ordens:
        if not ordem.codigo_tarefa:
            continue
        cursor.execute(
            """
            INSERT INTO op_por_tarefa (
                tarefa_id, codigo_op, id_peca, setor_destino_original,
                setor_destino_atual, quantidade_original, quantidade_atual, editado
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
            ON CONFLICT (tarefa_id, codigo_op) DO UPDATE SET
                id_peca = EXCLUDED.id_peca,
                setor_destino_original = EXCLUDED.setor_destino_original,
                setor_destino_atual = EXCLUDED.setor_destino_atual,
                quantidade_original = EXCLUDED.quantidade_original,
                quantidade_atual = EXCLUDED.quantidade_atual,
                editado = FALSE
            """,
            (
                tarefa_ids[ordem.codigo_tarefa], ordem.codigo, ordem.produto_codigo,
                ordem.setor_destino, ordem.setor_destino,
                ordem.quantidade, ordem.quantidade,
            ),
        )
    return tarefa_ids


def _gravar_corte(cursor, cenario: Cenario, tarefa_ids, agora: datetime) -> None:
    for programa in cenario.programas:
        cursor.execute(
            """
            INSERT INTO catalogo_sigmanest_programas (
                codigo_tarefa, programa, ativo, sincronizado_em
            ) VALUES (%s, %s, TRUE, %s)
            ON CONFLICT (codigo_tarefa, programa) DO UPDATE SET
                ativo = TRUE, sincronizado_em = EXCLUDED.sincronizado_em
            """,
            (programa["codigo_tarefa"], programa["programa"], agora),
        )
    for plano in cenario.planos:
        segundos = int(plano["tempo_previsto_segundos"])
        cursor.execute(
            """
            INSERT INTO catalogo_sigmanest_planos_corte (
                plano_hash, codigo_tarefa, programa, nome_chapa, sequencia_nesting,
                area_usada, fracao_sucata, quantidade_processo, maquina_sigmanest,
                tempo_previsto_segundos, tempo_previsto_formatado, data_programa,
                status_programa, ativo, sincronizado_em, sigmanest_comp_date
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                      'LIBERADO', TRUE, %s, NULL)
            ON CONFLICT (plano_hash) DO UPDATE SET
                codigo_tarefa = EXCLUDED.codigo_tarefa,
                programa = EXCLUDED.programa,
                nome_chapa = EXCLUDED.nome_chapa,
                sequencia_nesting = EXCLUDED.sequencia_nesting,
                area_usada = EXCLUDED.area_usada,
                fracao_sucata = EXCLUDED.fracao_sucata,
                quantidade_processo = EXCLUDED.quantidade_processo,
                maquina_sigmanest = EXCLUDED.maquina_sigmanest,
                tempo_previsto_segundos = EXCLUDED.tempo_previsto_segundos,
                tempo_previsto_formatado = EXCLUDED.tempo_previsto_formatado,
                data_programa = EXCLUDED.data_programa,
                status_programa = EXCLUDED.status_programa,
                ativo = TRUE,
                sincronizado_em = EXCLUDED.sincronizado_em,
                -- Nesting concluído na origem sai da fila. O cenário nasce
                -- pendente para o operador poder executá-lo.
                sigmanest_comp_date = NULL
            """,
            (
                plano["plano_hash"], plano["codigo_tarefa"], plano["programa"],
                plano["nome_chapa"], plano["sequencia_nesting"], plano["area_usada"],
                plano["fracao_sucata"], plano["quantidade_processo"],
                plano["maquina_sigmanest"], segundos,
                f"{segundos // 3600}h {segundos % 3600 // 60:02d}min",
                plano["data_programa"], agora,
            ),
        )
    for linha in cenario.linhas_sigmanest:
        cursor.execute(
            """
            INSERT INTO catalogo_sigmanest_ops (
                linha_hash, codigo_tarefa, codigo_op, id_peca, setor_destino,
                quantidade, dobra, usinagem, solda, chanfro, ativo, sincronizado_em
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (linha_hash) DO UPDATE SET
                codigo_tarefa = EXCLUDED.codigo_tarefa,
                codigo_op = EXCLUDED.codigo_op,
                id_peca = EXCLUDED.id_peca,
                setor_destino = EXCLUDED.setor_destino,
                quantidade = EXCLUDED.quantidade,
                dobra = EXCLUDED.dobra,
                usinagem = EXCLUDED.usinagem,
                solda = EXCLUDED.solda,
                ativo = TRUE,
                sincronizado_em = EXCLUDED.sincronizado_em
            """,
            (
                linha["linha_hash"], linha["codigo_tarefa"], linha["codigo_op"],
                linha["id_peca"], linha["setor_destino"], linha["quantidade"],
                linha["dobra"], linha["usinagem"], linha["solda"], linha["chanfro"],
                agora,
            ),
        )


def _gravar_templates_qualidade(cursor, cenario: Cenario, agora: datetime) -> list[str]:
    """Cria template de cota só onde o produto ainda não tem um.

    Um produto pode ser compartilhado com OPs reais do banco de teste. Se já
    existe template cadastrado por alguém, ele é preservado intacto — o cenário
    não sobrescreve trabalho de outra pessoa nem se apropria da linha.
    """

    ignorados: list[str] = []
    for template in cenario.templates_qualidade:
        cursor.execute(
            "SELECT id, criado_por_nome FROM qualidade_templates_produto WHERE produto_codigo = %s",
            (template["produto_codigo"],),
        )
        existente = cursor.fetchone()
        if existente and str(existente["criado_por_nome"] or "") != AUTOR_CENARIO:
            ignorados.append(template["produto_codigo"])
            continue
        cursor.execute(
            """
            INSERT INTO qualidade_templates_produto (
                produto_codigo, produto_descricao, revisao, ativo,
                criado_por_nome, atualizado_por_nome, criado_em, atualizado_em
            ) VALUES (%s, %s, 1, TRUE, %s, %s, %s, %s)
            ON CONFLICT (produto_codigo) DO UPDATE SET
                produto_descricao = EXCLUDED.produto_descricao,
                ativo = TRUE,
                atualizado_por_nome = EXCLUDED.atualizado_por_nome,
                atualizado_em = EXCLUDED.atualizado_em
            RETURNING id
            """,
            (
                template["produto_codigo"], template["produto_descricao"],
                AUTOR_CENARIO, AUTOR_CENARIO, agora, agora,
            ),
        )
        template_id = int(cursor.fetchone()["id"])
        # Recria as cotas do template para manter a sequência determinística
        # entre execuções, sem deixar cota órfã de uma carga anterior.
        cursor.execute(
            "DELETE FROM qualidade_cotas_template WHERE template_id = %s",
            (template_id,),
        )
        for sequencia, (descricao, padrao) in enumerate(template["cotas"], start=1):
            cursor.execute(
                """
                INSERT INTO qualidade_cotas_template (
                    template_id, sequencia, descricao, padrao, unidade, ordem,
                    ativo, criado_em, atualizado_em
                ) VALUES (%s, %s, %s, %s, 'mm', %s, TRUE, %s, %s)
                """,
                (template_id, sequencia, descricao, padrao, sequencia, agora, agora),
            )
    return ignorados


def _conferir(cursor) -> dict:
    cursor.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM catalogo_pcp_ops WHERE codigo_op LIKE %(op)s) AS ops,
            (SELECT COUNT(*) FROM catalogo_operacoes_op WHERE codigo_op LIKE %(op)s) AS etapas_roteiro,
            (SELECT COUNT(*) FROM catalogo_operacoes_op
              WHERE codigo_op LIKE %(op)s AND ativo IS TRUE) AS etapas_apontaveis,
            (SELECT COUNT(*) FROM tarefas WHERE codigo_tarefa LIKE %(tar)s) AS tarefas,
            (SELECT COUNT(*) FROM op_por_tarefa WHERE codigo_op LIKE %(op)s) AS ops_por_tarefa,
            (SELECT COUNT(*) FROM catalogo_sigmanest_planos_corte
              WHERE plano_hash LIKE %(plano)s) AS planos,
            (SELECT COUNT(*) FROM catalogo_sigmanest_planos_corte
              WHERE plano_hash LIKE %(plano)s AND maquina_sigmanest = 'AMADA_ENSIS') AS planos_laser,
            (SELECT COUNT(*) FROM catalogo_sigmanest_planos_corte
              WHERE plano_hash LIKE %(plano)s AND maquina_sigmanest = 'MESSER_XPR_300') AS planos_plasma,
            (SELECT COUNT(*) FROM catalogo_sigmanest_ops WHERE codigo_op LIKE %(op)s) AS linhas_peca,
            (SELECT COUNT(*) FROM qualidade_templates_produto
              WHERE criado_por_nome = %(autor)s) AS templates_qualidade
        """,
        {
            "op": f"{PREFIXO}%",
            "tar": f"{PREFIXO}%",
            "plano": f"{PREFIXO_PLANO}%",
            "autor": AUTOR_CENARIO,
        },
    )
    return dict(cursor.fetchone())


def resumo_para_teste(cenario: Cenario) -> dict:
    """Resumo legível: o que existe e onde olhar na interface."""

    por_setor: dict[str, set[str]] = {}
    for ordem in cenario.ordens:
        for etapa in ordem.etapas:
            if etapa.tipo_setor:
                por_setor.setdefault(etapa.tipo_setor, set()).add(etapa.codigo_recurso)
    fila_imediata: dict[str, list[str]] = {}
    for ordem in cenario.ordens:
        if ordem.codigo_tarefa:
            continue  # OP de Corte só libera o próximo setor após o Destaque
        primeira = ordem.etapas[0]
        fila_imediata.setdefault(
            f"{primeira.tipo_setor} / {primeira.codigo_recurso}", []
        ).append(ordem.codigo)
    return {
        "ops": len(cenario.ordens),
        "ops_com_corte": sum(1 for item in cenario.ordens if item.codigo_tarefa),
        "ops_separadas": sum(1 for item in cenario.ordens if not item.codigo_tarefa),
        "tarefas": [item.codigo for item in cenario.tarefas],
        "planos": len(cenario.planos),
        "planos_laser": sum(
            1 for item in cenario.planos if item["maquina_sigmanest"] == "AMADA_ENSIS"
        ),
        "planos_plasma": sum(
            1 for item in cenario.planos if item["maquina_sigmanest"] == "MESSER_XPR_300"
        ),
        "linhas_peca": len(cenario.linhas_sigmanest),
        "recursos_por_setor": {
            setor: sorted(recursos) for setor, recursos in sorted(por_setor.items())
        },
        "fila_imediata_por_posto": {
            posto: sorted(ops) for posto, ops in sorted(fila_imediata.items())
        },
        "templates_qualidade": [
            item["produto_codigo"] for item in cenario.templates_qualidade
        ],
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o cenário que seria gravado, sem tocar no banco.",
    )
    parser.add_argument(
        "--data-base",
        help="Data de referência YYYY-MM-DD (padrão: hoje).",
    )
    parser.add_argument("--json", action="store_true", help="Somente JSON na saída.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    hoje = date.fromisoformat(args.data_base) if args.data_base else date.today()
    agora = datetime.now().replace(microsecond=0)
    cenario = construir_cenario(hoje)
    resultado = {"modo": "dry-run", "cenario": resumo_para_teste(cenario)}
    if not args.dry_run:
        resultado.update(aplicar(cenario, agora=agora))
        resultado["modo"] = "aplicado"

    if args.json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))
        return 0

    resumo = resultado["cenario"]
    print(f"Modo: {resultado['modo']}")
    if "alvo" in resultado:
        print(f"Banco: {resultado['alvo']}")
    print(
        f"OPs: {resumo['ops']} "
        f"({resumo['ops_com_corte']} com Corte, {resumo['ops_separadas']} separadas)"
    )
    print(f"Tarefas: {', '.join(resumo['tarefas'])}")
    print(
        f"Planos/nestings: {resumo['planos']} "
        f"(Laser {resumo['planos_laser']} · Plasma {resumo['planos_plasma']})"
    )
    print(f"Linhas de peça (tarefa/OP/peça): {resumo['linhas_peca']}")
    print("\nPostos com etapa no roteiro:")
    for setor, recursos in resumo["recursos_por_setor"].items():
        print(f"  {setor:<9} {', '.join(recursos)}")
    print("\nFila imediata (OPs sem Corte, já apontáveis):")
    for posto, ops in resumo["fila_imediata_por_posto"].items():
        print(f"  {posto:<22} {', '.join(ops)}")
    print(
        "\nOPs com Corte só liberam o setor seguinte depois de finalizar todos os "
        "nestings e o Destaque da tarefa — é a regra canônica, não um defeito."
    )
    if resultado.get("templates_preservados"):
        print(
            "\nTemplates de Qualidade preservados (já existiam para o produto): "
            + ", ".join(resultado["templates_preservados"])
        )
    if "conferencia" in resultado:
        print("\nConferência no banco:")
        for chave, valor in resultado["conferencia"].items():
            print(f"  {chave:<20} {valor}")
    print(
        "\nPara remover tudo isto: "
        ".venv/Scripts/python.exe scripts/limpar_cenario_gui.py"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
