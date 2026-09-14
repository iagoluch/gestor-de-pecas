"""Endpoint somente leitura do acompanhamento gerencial da Solda.

A mesma projeção serve a tela de gestão e o ciclo da TV, por isso a autorização
é a do Andon: perfil de TV e perfil gerencial leem a mesma verdade. Nenhuma ação
é exposta aqui — a visão é de acompanhamento.
"""

from fastapi import APIRouter, Depends

from backend.api.dependencies.auth import require_andon_user
from backend.api.dependencies.facade import get_frontend_facade
from backend.api.schemas.auth import SessionUser


router = APIRouter(prefix="/welding", tags=["Solda"])


@router.get("")
def acompanhamento(
    _user: SessionUser = Depends(require_andon_user),
    facade=Depends(get_frontend_facade),
):
    return facade.solda_gerencial()
