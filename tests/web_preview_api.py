"""API isolada para QA visual local; nunca usa o banco operacional."""

from datetime import date, datetime, time, timedelta
import os

from backend.api.config import WebSettings
from backend.api.dependencies.auth import get_current_user, require_csrf
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.main import create_app
from backend.api.schemas.auth import SessionUser
from mes.contracts.ai import AIProviderResponse
from mes.services.operator_flow import OperatorFlowService
from tests.test_web_api import ApiFakeDatabase


class VisualAIProvider:
    """Resposta determinística para validar a interface sem consumir a Groq."""

    configured = True

    async def complete(self, _messages, *, tools, tool_choice="auto", request_id=None):
        return AIProviderResponse(content="Nenhuma consulta adicional é necessária.")

    async def stream(self, _messages, *, tools=None, tool_choice="none", request_id=None):
        yield "**A fábrica está disponível para consulta.**\n\n"
        yield "- Esta resposta é uma simulação visual isolada.\n"
        yield "- Nenhuma alteração produtiva foi executada."


database = ApiFakeDatabase()
visual_manager_id = database.criar_usuario("Gestor Visual", "visual-local", "gestor")
database.criar_usuario("Operador Dobra Visual", "visual-operador", "operador_dobra")
database.criar_usuario("Operador Corte Visual", "visual-corte", "operador_corte")
database.criar_usuario("Operador Destaque Visual", "visual-destaque", "operador_destaque")
database.criar_usuario("Operador Solda Visual", "visual-solda", "estacao1aco")

visual_now = datetime.now().replace(microsecond=0)
# A pré-visualização usa exatamente os códigos e nomes do cadastro oficial
# (``app/core/resource_mapping.RESOURCE_FRIENDLY_NAMES``): nenhum recurso é
# inventado aqui. A carga representa a capacidade máxima normal do Andon, com as
# cinco máquinas de Usinagem apontando ao mesmo tempo.
visual_resources = [
    {"codigo": "LASER1", "nome": "Laser Ensis 3015", "tipo_setor": "Corte", "habilitado": True},
    {"codigo": "PLASMA", "nome": "Plasma TerraBlade 4", "tipo_setor": "Corte", "habilitado": True},
    {"codigo": "DOBRA1", "nome": "Gasparini", "tipo_setor": "Dobra", "habilitado": True},
    {"codigo": "DOBRA2", "nome": "2204", "tipo_setor": "Dobra", "habilitado": True},
    {"codigo": "DOBRA3", "nome": "1303", "tipo_setor": "Dobra", "habilitado": True},
    {"codigo": "CNC-01", "nome": "Romi D 1000", "tipo_setor": "Usinagem", "habilitado": True},
    {"codigo": "CNC-02", "nome": "Eurostec", "tipo_setor": "Usinagem", "habilitado": True},
    {"codigo": "FRESA1", "nome": "Fresadora FTV31", "tipo_setor": "Usinagem", "habilitado": True},
    {"codigo": "TCNC-1", "nome": "Romi GL 350M", "tipo_setor": "Usinagem", "habilitado": True},
    {"codigo": "TORNOC", "nome": "Torno Mecânico", "tipo_setor": "Usinagem", "habilitado": True},
    {"codigo": "SERRA1", "nome": "S4220", "tipo_setor": "Serra", "habilitado": True},
    {"codigo": "SERRA2", "nome": "SFHA-10", "tipo_setor": "Serra", "habilitado": True},
    {"codigo": "SERRA3", "nome": "SFG-330", "tipo_setor": "Serra", "habilitado": True},
    {"codigo": "SOLDA4", "nome": "Solda", "tipo_setor": "Solda Aço", "habilitado": True},
    {"codigo": "PINT.L", "nome": "Pintura", "tipo_setor": "Pintura", "habilitado": True},
]
visual_states = [
    {"id": 801, "recurso": "DOBRA3", "setor": "Dobra", "tipo_setor": "Dobra", "categoria": "producao", "data_inicio": visual_now - timedelta(minutes=47), "op": "10735703001", "numero_operacao": "10", "produto_codigo": "IPCX04014283"},
    {"id": 802, "recurso": "DOBRA2", "setor": "Dobra", "tipo_setor": "Dobra", "categoria": "parada", "data_inicio": visual_now - timedelta(minutes=18), "motivo": "Aguardando material"},
    {"id": 803, "recurso": "DOBRA1", "setor": "Dobra", "tipo_setor": "Dobra", "categoria": "producao", "data_inicio": visual_now - timedelta(minutes=27), "op": "10735901012", "numero_operacao": "10", "produto_codigo": "PPCX12001012"},
    {"id": 804, "recurso": "CNC-01", "setor": "Usinagem", "tipo_setor": "Usinagem", "categoria": "setup", "data_inicio": visual_now - timedelta(minutes=12)},
    {"id": 805, "recurso": "CNC-02", "setor": "Usinagem", "tipo_setor": "Usinagem", "categoria": "retrabalho", "data_inicio": visual_now - timedelta(minutes=9)},
    {"id": 806, "recurso": "FRESA1", "setor": "Usinagem", "tipo_setor": "Usinagem", "categoria": "producao", "data_inicio": visual_now - timedelta(minutes=63), "op": "00652704001", "numero_operacao": "20", "produto_codigo": "PPCX04002312"},
    {"id": 807, "recurso": "TCNC-1", "setor": "Usinagem", "tipo_setor": "Usinagem", "categoria": "producao", "data_inicio": visual_now - timedelta(minutes=41), "op": "PCML9501001", "numero_operacao": "30", "produto_codigo": "PNT002002032"},
    {"id": 808, "recurso": "TORNOC", "setor": "Usinagem", "tipo_setor": "Usinagem", "categoria": "parada", "data_inicio": visual_now - timedelta(minutes=7), "motivo": "Troca de ferramenta"},
    {"id": 809, "recurso": "SERRA1", "setor": "Serra", "tipo_setor": "Serra", "categoria": "producao", "data_inicio": visual_now - timedelta(minutes=31), "op": "PCMKXF01001", "numero_operacao": "40", "produto_codigo": "PPCX04002371"},
    {"id": 810, "recurso": "SERRA2", "setor": "Serra", "tipo_setor": "Serra", "categoria": "setup", "data_inicio": visual_now - timedelta(minutes=5)},
    {"id": 811, "recurso": "SERRA3", "setor": "Serra", "tipo_setor": "Serra", "categoria": "producao", "data_inicio": visual_now - timedelta(minutes=22), "op": "00652706001", "numero_operacao": "10", "produto_codigo": "PSM002005049"},
    # A Solda aponta por estação: o posto escolhido pelo operador é o recurso do
    # evento de estado, e é assim que ele chega ao Andon (recurso fora do
    # catálogo, com pertencimento canônico ao setor). Setup não existe em Solda.
    {"id": 8121, "recurso": "Estação 1", "setor": "Solda Aço", "tipo_setor": "Solda Aço", "categoria": "producao", "data_inicio": visual_now - timedelta(minutes=44), "op": "00652801001", "numero_operacao": "10", "produto_codigo": "SRF004001001"},
    {"id": 8122, "recurso": "Estação 2", "setor": "Solda Aço", "tipo_setor": "Solda Aço", "categoria": "parada", "data_inicio": visual_now - timedelta(minutes=14), "motivo": "Aguardando ponte rolante"},
    {"id": 8123, "recurso": "Estação 3", "setor": "Solda Aço", "tipo_setor": "Solda Aço", "categoria": "atividade_sem_op", "data_inicio": visual_now - timedelta(hours=1, minutes=6), "motivo": "Apoio à montagem"},
    {"id": 8124, "recurso": "Estação 4", "setor": "Solda Aço", "tipo_setor": "Solda Aço", "categoria": "producao", "data_inicio": visual_now - timedelta(minutes=58), "op": "00652802001", "numero_operacao": "20", "produto_codigo": "PNT002001136"},
    {"id": 8125, "recurso": "Estação 5", "setor": "Solda Aço", "tipo_setor": "Solda Aço", "categoria": "retrabalho", "data_inicio": visual_now - timedelta(minutes=11), "op": "00652803001", "numero_operacao": "10", "produto_codigo": "PCGX08001006"},
    {"id": 813, "recurso": "PINT.L", "setor": "Pintura", "tipo_setor": "Pintura", "categoria": "producao", "data_inicio": visual_now - timedelta(minutes=52), "op": "10735801001", "produto_codigo": "PNT002003016"},
    {"id": 814, "recurso": "LASER1", "setor": "Corte", "tipo_setor": "Corte", "categoria": "producao", "data_inicio": visual_now - timedelta(minutes=38), "op": "10735701001", "produto_codigo": "PNT002003016"},
    {"id": 815, "recurso": "PLASMA", "setor": "Corte", "tipo_setor": "Corte", "categoria": "producao", "data_inicio": visual_now - timedelta(minutes=26), "op": "10735702001", "produto_codigo": "PPL001000020"},
]

# O Destaque é um posto operacional de Corte: sem este evento o grupo não
# aparece na pré-visualização e o Corte ficaria com dois grupos apenas.
visual_highlights = [{
    "estado": "inicio",
    "data_hora": visual_now - timedelta(minutes=21),
    "operador": "Operador Destaque Visual",
    "codigo_tarefa": "T3419",
    "programa": "8461",
    "nome_chapa": "S194",
    "motivo": None,
    "codigo_status_recurso": None,
    "ops": [
        {"codigo_op": "10735701001", "produto_codigo": "PNT002003016", "produto_descricao": "CHAPA EXTERNA RODADO"},
        {"codigo_op": "10735703001", "produto_codigo": "IPCX04014283", "produto_descricao": "LATERAL 6 FX DIR."},
    ],
}]
visual_facts = [{
    "id": 901,
    "op": "10735703001",
    "tipo_setor": "Dobra",
    "maquina": "DOBRA3",
    "status": "Em processo",
    "data_inicio": visual_now - timedelta(minutes=47),
    "data_fim": None,
    "operador_inicio": "Operador Dobra Visual",
    "quantidade": 12,
    "quantidade_planejada_pcp": 12,
    "quantidade_boa": 5,
    "quantidade_refugo": 1,
    "quantidade_retrabalho": 0,
    "produto_codigo": "IPCX04014283",
    "produto_descricao": "LATERAL 6 FX DIR.",
    "numero_operacao": "10",
    "descricao_operacao": "DOBRAR SUPORTE",
    "eventos": [],
}]
database.listar_recursos_pcfactory = lambda *_args, **_kwargs: visual_resources
database.listar_estados_recurso_atuais = lambda **_kwargs: visual_states
database.listar_estados_recurso_periodo = lambda *_args, **_kwargs: visual_states
database.listar_destaques_ativos_andon = lambda: visual_highlights
database.listar_fatos_operacionais_periodo = lambda *_args, **_kwargs: visual_facts
# O sininho do menu e a tela de Chamadas leem isto; a prévia não tem chamadas.
database.contar_chamadas_nao_vistas = lambda _usuario_id: 0
database.marcar_chamadas_vistas = lambda _usuario_id: None
database.listar_chamadas = lambda **_kwargs: []
database.listar_chamada_contatos = lambda **_kwargs: []
database.buscar_contato_padrao_gestao = lambda: None

task_id = database.inserir_tarefa("T-VISUAL-101", material="AÇO 304", espessura=3)
database.inserir_op_na_tarefa(task_id, "OP-VISUAL-101", "SUPORTE-101", "Dobra", 12)
database.catalog_operations.extend([
    {
        "id": 501,
        "codigo_op": "OP-VISUAL-101",
        "numero_operacao": "10",
        "codigo_recurso": "DOBRA3",
        "descricao_operacao": "DOBRAR SUPORTE",
        "tipo_setor": "Dobra",
        "produto_codigo": "SUPORTE-101",
        "produto_descricao": "Suporte estrutural",
        "quantidade": 12,
        "ordem": 1,
        "ativo": True,
    },
    {
        # Segunda etapa do próprio posto: torna inspecionável a confirmação de
        # operação fora da etapa atual (Wave 2) sem liberar outro setor.
        "id": 503,
        "codigo_op": "OP-VISUAL-101",
        "numero_operacao": "20",
        "codigo_recurso": "DOBRA3",
        "descricao_operacao": "DOBRA ESPECIAL",
        "tipo_setor": "Dobra",
        "produto_codigo": "SUPORTE-101",
        "produto_descricao": "Suporte estrutural",
        "quantidade": 12,
        "ordem": 2,
        "ativo": True,
    },
    {
        "id": 502,
        "codigo_op": "OP-VISUAL-101",
        "numero_operacao": "30",
        "codigo_recurso": "PINT.L",
        "descricao_operacao": "PINTURA",
        "tipo_setor": "Pintura",
        "produto_codigo": "SUPORTE-101",
        "produto_descricao": "Suporte estrutural",
        "quantidade": 12,
        "ordem": 3,
        "ativo": True,
    },
])

highlight_task_id = database.inserir_tarefa("T-DESTAQUE-202", material="AÇO CARBONO", espessura=6)
database.inserir_op_na_tarefa(highlight_task_id, "OP-DEST-201", "CHAPA-201", "Dobra", 8)
database.inserir_op_na_tarefa(highlight_task_id, "OP-DEST-202", "CHAPA-202", "Solda", 4)

# Hierarquia real do Corte (Wave 6C): a tarefa T3419 tem DOIS planos.
# O programa 8461 tem quatro chapas físicas do mesmo programa (repetição 1..4, duas
# já cortadas) e o 8462 tem três ainda aguardando. Nada é presumido como
# "1 nesting = 1 chapa": a contagem e a repetição vêm do planejamento.
for programa, chapas, quantidade in (("8461", 4, 20), ("8462", 3, 6)):
    for sequence in range(1, chapas + 1):
        database.cut_plans.append({
            "plano_hash": f"hash-visual-{programa}-{sequence}",
            "codigo_tarefa": "T3419",
            "programa": programa,
            "nome_chapa": "S194" if programa == "8461" else "S201",
            "sequencia_nesting": sequence,
            "sigmanest_repeat_id": sequence,
            "material": "ASTM A36",
            "espessura": 6.35,
            "maquina_sigmanest": "Amada_ensis",
            "quantidade_processo": quantidade,
            "tempo_previsto_segundos": 1220 if programa == "8461" else 760,
            "data_programa": date.today(),
            "area_usada": 1_250_000,
            "fracao_sucata": 0.12,
            "ativo": True,
        })

# Linhas de peça do SigmaNEST: a OP pertence ao produto, e o produto foi
# aninhado em um programa específico. É este vínculo que a tela de Corte usa
# para mostrar as OPs dentro do plano correto.
database.sigmanest_ops.extend([
    {
        "linha_hash": f"T3419|{programa}|{codigo_op}|{peca}",
        "codigo_tarefa": "T3419",
        "programa": programa,
        "codigo_op": codigo_op,
        "id_peca": peca,
        "setor_destino": setor,
        "quantidade": quantidade,
        "ativo": True,
    }
    for programa, codigo_op, peca, setor, quantidade in (
        ("8461", "10735701001", "PNT002003016", "Aguardando Dobra", 12),
        ("8461", "10735703001", "IPCX04014283", "Aguardando Usinagem", 8),
        ("8462", "10735704001", "PPL001000020", "Almoxarifado", 6),
    )
])
database.pcp_ops.extend([
    {
        "codigo_op": codigo_op, "produto_codigo": produto,
        "produto_descricao": descricao, "quantidade": quantidade,
        "unidade": "UN", "ativo": True,
    }
    for codigo_op, produto, descricao, quantidade in (
        ("10735701001", "PNT002003016", "CHAPA EXTERNA RODADO", 12),
        ("10735703001", "IPCX04014283", "LATERAL 6 FX DIR.", 8),
        ("10735704001", "PPL001000020", "CHAPA DIANTEIRA DE FIX.TUBO DO ENGATE", 6),
        ("10735702001", "PPL001000020", "CHAPA DIANTEIRA DE FIX.TUBO DO ENGATE", 6),
        ("10735901012", "PPCX12001012", "CHAPA SUPORTE CANOS", 3),
        ("00652704001", "PPCX04002312", "ENCOSTO INFERIOR MASCARA", 10),
        ("PCML9501001", "PNT002002032", "ARTICULACAO CILINDRO", 6),
        ("PCMKXF01001", "PPCX04002371", "TUBO ESCORA ACOPLADOR ESQ.", 10),
        ("00652706001", "PSM002005049", "REFORCO CHASSI", 4),
        ("00652801001", "SRF004001001", "CONJUNTO SOLDADO CHASSI CENTRAL", 2),
        ("00652802001", "PNT002001136", "SUPORTE PARAFUSADO", 8),
        ("00652803001", "PCGX08001006", "SUPORTE ESQUERDA PARACHQOUE", 4),
    )
])

# A tarefa do Destaque precisa existir no fluxo de tarefas para agrupar as OPs.
corte_task_id = database.inserir_tarefa("T3419", material="ASTM A36", espessura=6.35)
database.inserir_op_na_tarefa(corte_task_id, "10735701001", "PNT002003016", "Dobra", 12)
database.inserir_op_na_tarefa(corte_task_id, "10735703001", "IPCX04014283", "Usinagem", 8)
for sequence in (1, 2):
    iniciado = database.iniciar_apontamento_corte(
        f"hash-visual-8461-{sequence}",
        "Laser Ensis 3015",
        "Operador Corte Visual",
        "2026-01-01",
        data_inicio=visual_now - timedelta(hours=3, minutes=sequence * 20),
    )
    if iniciado:
        database.finalizar_apontamento_corte(
            iniciado["id"],
            "Operador Corte Visual",
            data_fim=visual_now - timedelta(hours=2, minutes=sequence * 20),
        )

# Uma OP que já chegou na etapa de inspeção: é o que alimenta a fila da
# Qualidade e a regra transitória "seguir sem inspeção" da Wave 3.
database.cadastrar_operador_apontamento("77", "Inspetor Visual")
quality_task_id = database.inserir_tarefa("T-QUALIDADE-401", material="AÇO 304", espessura=3)
database.inserir_op_na_tarefa(quality_task_id, "OP-VISUAL-401", "FLANGE-401", "Dobra", 6)
database.catalog_operations.extend([
    {
        "id": 701,
        "codigo_op": "OP-VISUAL-401",
        "numero_operacao": "10",
        "codigo_recurso": "DOBRA3",
        "descricao_operacao": "DOBRAR FLANGE",
        "tipo_setor": "Dobra",
        "produto_codigo": "FLANGE-401",
        "produto_descricao": "Flange dobrado",
        "quantidade": 6,
        "ordem": 1,
        "ativo": True,
    },
    {
        # A etapa de inspeção vive no roteiro do Protheus como CALDER/INSPEC e
        # entra inativa: ela não bloqueia o avanço, apenas alimenta a fila.
        "id": 702,
        "codigo_op": "OP-VISUAL-401",
        "numero_operacao": "20",
        "codigo_recurso": "INSPEC",
        "descricao_operacao": "INSPECAO",
        "tipo_setor": None,
        "produto_codigo": "FLANGE-401",
        "produto_descricao": "Flange dobrado",
        "quantidade": 6,
        "ordem": 2,
        "ativo": False,
        "marco_terminal": False,
        "inspecao_qualidade": True,
    },
])
_visual_flow = OperatorFlowService(database, "OPERADOR DOBRA VISUAL")
_visual_operacao = database.listar_operacoes_para_op("OP-VISUAL-401", "Dobra")[0]
_visual_flow.executar("Início", op="OP-VISUAL-401", setor="Dobra", recurso="1303", operacao=_visual_operacao)
_visual_flow.executar(
    "Finalizado", op="OP-VISUAL-401", setor="Dobra", recurso="1303",
    operacao=_visual_operacao, pecas_boas=6, operadores_cracha=["77"],
)

# Wave 6E — variedade mínima para conferir visualmente os filtros das telas de
# cadastro: crachá ativo/inativo, com e sem designação de responsável, e mais de
# uma origem. Vale apenas nesta pré-visualização isolada.
for _cracha, _nome, _ativo, _fonte, _responsavel in (
    ("77", "Marina Alves", True, "cadastro", True),
    ("102", "Rafael Nogueira", True, "cadastro", False),
    ("118", "Helena Prado", True, "gestao", True),
    ("205", "Tiago Moreira", False, "gestao", False),
    ("310", "Sofia Camargo", True, "cadastro", False),
):
    database.cadastrar_operador_apontamento(
        _cracha, _nome, ativo=_ativo, fonte=_fonte, autorizador_retrabalho=_responsavel,
    )
# Pausa com descrição livre: mostra a coluna de tipo da tela de Pausas.
database.salvar_pausa_automatica(
    tipo_setor="Corte", nome="Pausa para ginástica", hora_inicio=time(9, 40),
    hora_fim=time(9, 50), ativo=True, ordem=3, operador="Pré-visualização",
)

settings = WebSettings(
    environment="test",
    session_secret="visual-preview-only-secret-with-more-than-thirty-two-bytes",
    allowed_hosts=("127.0.0.1", "localhost", *filter(None, os.getenv("GESTOR_VISUAL_EXTRA_HOSTS", "").split(","))),
    allowed_origins=("http://127.0.0.1:5173",),
    ai_enabled=os.getenv("GESTOR_VISUAL_AI") == "1",
    ai_api_key=os.getenv("GESTOR_VISUAL_AI_KEY", ""),
)

app = create_app(settings=settings, database_factory=lambda: database)


class VisualFacade:
    """Complementa somente a pré-visualização isolada com KPIs determinísticos."""

    def __init__(self):
        from mes.services.frontend_facade import FrontendBackendFacade

        self._facade = FrontendBackendFacade(database)

    def __getattr__(self, name):
        # Só o Andon recebe KPIs determinísticos; o resto da pré-visualização
        # usa a fachada canônica, para conferir as telas gerenciais como são.
        return getattr(self._facade, name)

    def andon(self, filters):
        snapshot = self._facade.andon(filters)
        for index, resource in enumerate(
            (item for sector in snapshot["sectors"] for item in sector["resources"]),
            1,
        ):
            base = 68 + (index * 3) % 24
            resource["metrics"] = {
                "oee": {"value": float(base), "availability": "disponivel", "unit": "%", "reason": None},
                "availability": {"value": float(min(99, base + 5)), "availability": "disponivel", "unit": "%", "reason": None},
                "performance": {"value": float(min(99, base + 8)), "availability": "disponivel", "unit": "%", "reason": None},
                "ftt": {"value": float(min(99, base + 12)), "availability": "disponivel", "unit": "%", "reason": None},
            }
        # O Corte real publica tarefa/plano (apontamentos_corte), não OP/produto.
        cuts = {"LASER1": ("8478", "50412", "CH-6.35", 2), "PLASMA": ("8481", "60307", "CH-4.75", 1)}
        for sector in snapshot["sectors"]:
            for resource in sector["resources"]:
                if resource["code"] in cuts:
                    task, plan, sheet, nesting = cuts[resource["code"]]
                    resource["operation"] = None
                    resource["cut"] = {"task": task, "plan": plan, "sheet": sheet, "nesting": nesting}
        return snapshot


app.dependency_overrides[get_frontend_facade] = lambda: VisualFacade()
if settings.ai_enabled and settings.ai_configured:
    app.state.ai_provider = VisualAIProvider()
    database.criar_conversa_ia(visual_manager_id, "Como está a fábrica agora?")
    if os.getenv("GESTOR_VISUAL_AI_COOLDOWN") == "1":
        app.state.ai_rate_limit.activate({"retry_after": "90"})
_autologin = os.getenv("GESTOR_VISUAL_AUTOLOGIN")
_PERFIS = {"operador": ("Operador Dobra Visual", "operador_dobra"), "destaque": ("Operador Destaque Visual", "operador_destaque"),
           "corte": ("Operador Corte Visual", "operador_corte"), "solda": ("Operador Solda Visual", "estacao1aco"),
           "andon": ("Andon TV Visual", "andon")}
if _autologin == "1" or _autologin in _PERFIS:
    # "operador" = Dobra, "destaque" = Destaque; "1" = gestor com Andon.
    _as_operator = _autologin not in ("1", "andon")
    visual_manager = SessionUser(
        id=visual_manager_id,
        name=_PERFIS.get(_autologin, ("Gestor Visual", ""))[0],
        role=_PERFIS.get(_autologin, ("", "gestor"))[1],
        management_access=_autologin == "1",
        andon_access=not _as_operator,
        operator_access=_as_operator,
    )
    app.dependency_overrides[get_current_user] = lambda: visual_manager
    app.dependency_overrides[require_csrf] = lambda: None
