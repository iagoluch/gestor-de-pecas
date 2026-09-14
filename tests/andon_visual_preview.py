"""Pré-visualização isolada do Andon, com a sessão já resolvida.

Reaproveita integralmente ``tests.web_preview_api``: os mesmos fixtures
visuais, o mesmo backend falso e nenhum banco operacional. A única diferença é
dispensar credenciais e permitir alternar entre o perfil de TV (``/andon``
dedicado) e o perfil gerencial pelo cookie ``preview_perfil``, que é o que
distingue as duas composições de layout.
"""

import os
import random

os.environ.setdefault("GESTOR_VISUAL_AUTOLOGIN", "1")

from fastapi import Request  # noqa: E402

from backend.api.dependencies.auth import get_current_user, require_csrf  # noqa: E402
from backend.api.dependencies.facade import get_frontend_facade  # noqa: E402
from backend.api.schemas.auth import SessionUser  # noqa: E402
from tests.web_preview_api import VisualFacade, app, visual_manager_id, visual_states  # noqa: E402

PREVIEW_ROLES = {"andon", "gestor"}

# Cenários de carga para a inspeção de layout. "maxima" é a capacidade normal de
# pico (cinco máquinas de Usinagem, várias estações de Solda); "leve" reproduz um
# turno com poucos apontamentos, que é onde o quadro precisa provar que encolhe
# em vez de guardar espaço vazio. Nenhum dos dois toca banco operacional.
PREVIEW_LIGHT_RESOURCES = {"LASER1", "PLASMA", "DOBRA3", "DOBRA2", "CNC-01", "SERRA1", "PINT.L", "Estação 1"}


class LightFacade(VisualFacade):
    """Mesma fonte de dados, recortada para um turno de baixa ocupação."""

    def andon(self, filters):
        snapshot = super().andon(filters)
        for sector in snapshot["sectors"]:
            for group in sector.get("groups") or ():
                group["resources"] = [item for item in group["resources"] if item["code"] in PREVIEW_LIGHT_RESOURCES]
            sector["groups"] = [group for group in (sector.get("groups") or ()) if group["resources"]]
            sector["resources"] = [item for item in sector["resources"] if item["code"] in PREVIEW_LIGHT_RESOURCES]
            sector["resource_count"] = len(sector["resources"])
        snapshot["resource_count"] = sum(sector["resource_count"] for sector in snapshot["sectors"])
        return snapshot


def preview_facade(request: Request):
    return LightFacade() if request.cookies.get("preview_carga") == "leve" else VisualFacade()


def preview_user(request: Request) -> SessionUser:
    role = request.cookies.get("preview_perfil", "andon")
    if role not in PREVIEW_ROLES:
        role = "andon"
    return SessionUser(
        id=visual_manager_id,
        name="Andon Visual" if role == "andon" else "Gestor Visual",
        role=role,
        management_access=role == "gestor",
        andon_access=True,
        operator_access=False,
    )


app.dependency_overrides[get_frontend_facade] = preview_facade
app.dependency_overrides[get_current_user] = preview_user
app.dependency_overrides[require_csrf] = lambda: None


# --- Demonstração de layout: transições de estado sob observação -------------
# Endpoint exclusivo desta pré-visualização isolada. Ele altera apenas o fixture
# em memória e publica a mesma invalidação que o backend real publicaria, para
# que a animação de entrada e de atualização possa ser observada ao vivo.
DEMO_RESOURCE = "Estação 1"

# Setup não existe em Pintura e Solda: a demonstração respeita a mesma regra de
# apontamento por setor que o fluxo do operador aplica.
DEMO_CATEGORIES = ("producao", "parada", "setup", "retrabalho", "atividade_sem_op")
DEMO_SECTORS_WITHOUT_SETUP = {"pintura", "solda"}
DEMO_REASONS = (
    "Aguardando material",
    "Troca de ferramenta",
    "Aguardando ponte rolante",
    "Manutenção corretiva",
    "Falta de operador",
)
_demo_removidos: list[dict] = []


def _demo_state(recurso=DEMO_RESOURCE):
    return next((item for item in visual_states if item["recurso"] == recurso), None)


def _demo_categorias(estado):
    setor = str(estado.get("tipo_setor") or "").casefold()
    proibido = {"setup"} if setor in DEMO_SECTORS_WITHOUT_SETUP else set()
    return [item for item in DEMO_CATEGORIES if item not in proibido]


def _demo_aplicar(estado, categoria, agora):
    estado["categoria"] = categoria
    estado["data_inicio"] = agora
    estado["motivo"] = random.choice(DEMO_REASONS) if categoria == "parada" else None


def _demo_aleatorio(agora):
    """Um passo de demonstração: entrada, saída ou troca de estado."""

    sorteio = random.random()
    if _demo_removidos and (sorteio < 0.35 or not visual_states):
        estado = _demo_removidos.pop(random.randrange(len(_demo_removidos)))
        _demo_aplicar(estado, random.choice(_demo_categorias(estado)), agora)
        visual_states.append(estado)
        return {"evento": "entrada", "recurso": estado["recurso"], "categoria": estado["categoria"]}
    if visual_states and sorteio > 0.82 and len(visual_states) > 6:
        estado = visual_states.pop(random.randrange(len(visual_states)))
        _demo_removidos.append(estado)
        return {"evento": "saida", "recurso": estado["recurso"]}
    if not visual_states:
        return {"evento": "sem_recurso"}
    estado = random.choice(visual_states)
    opcoes = [item for item in _demo_categorias(estado) if item != estado.get("categoria")]
    _demo_aplicar(estado, random.choice(opcoes), agora)
    return {"evento": "atualizacao", "recurso": estado["recurso"], "categoria": estado["categoria"]}


@app.post("/preview/andon/demo")
def preview_andon_demo(acao: str = "parada"):
    from datetime import datetime

    agora = datetime.now().replace(microsecond=0)
    if acao == "aleatorio":
        resultado = _demo_aleatorio(agora)
        app.state.realtime.publish("operator_action")
        return {"acao": acao, "ativos": len(visual_states), **resultado}

    estado = _demo_state()
    if acao == "sair":
        if estado is not None:
            visual_states.remove(estado)
            _demo_removidos.append(estado)
    elif acao == "entrar":
        if estado is None:
            recuperado = next((item for item in _demo_removidos if item["recurso"] == DEMO_RESOURCE), None)
            if recuperado is not None:
                _demo_removidos.remove(recuperado)
                _demo_aplicar(recuperado, "producao", agora)
                visual_states.append(recuperado)
    elif estado is not None:
        _demo_aplicar(estado, acao, agora)
    app.state.realtime.publish("operator_action")
    return {"acao": acao, "recurso": DEMO_RESOURCE, "ativos": len(visual_states)}


# A SPA está montada em "/" e captura qualquer caminho: a rota da demonstração
# precisa ser avaliada antes do mount.
app.router.routes.insert(0, app.router.routes.pop())
