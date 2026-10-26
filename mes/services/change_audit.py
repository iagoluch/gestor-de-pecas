"""Cola entre as rotas de gestão e o log "quem mudou o quê" (migration 66).

Regra de ouro: auditar nunca derruba nem muda a resposta da operação. Toda
leitura do "antes" e toda gravação passam por aqui, com ``try/except`` e
``logging.exception``. A gravação acontece depois do commit da operação (o
``Database`` já confirmou) e usa a própria transação — nunca a da operação.
Quais campos entram no log é decisão do ``Database`` (allowlist por entidade).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from app.database.change_audit_repository import ENTIDADES_DE_CUSTO


def ler_estado(database, metodo, *args, **kwargs):
    """Chama um ``listar_*``/``obter_*`` existente; ``None`` se faltar ou falhar."""

    try:
        leitor = getattr(database, metodo, None)
        return leitor(*args, **kwargs) if callable(leitor) else None
    except Exception:
        logging.exception("Falha ao ler o estado anterior para auditoria (%s)", metodo)
        return None


def encontrar(linhas, campo, valor):
    """Primeira linha de ``linhas`` cujo ``campo`` casa com ``valor`` (comparado como texto)."""

    alvo = str(valor)
    for linha in linhas or ():
        if str(linha.get(campo)) == alvo:
            return linha
    return None


def auditar(database, user, entidade, chave, *, antes=None, depois=None):
    """Grava a alteração; a ação sai de antes/depois. Nunca levanta erro."""

    try:
        if antes is None and depois is None:
            return False
        acao = "criar" if antes is None else "excluir" if depois is None else "alterar"
        registrar = getattr(database, "registrar_auditoria", None)
        if not callable(registrar):
            return False
        return bool(
            registrar(
                entidade=entidade,
                chave=str(chave),
                acao=acao,
                usuario_id=getattr(user, "id", None),
                usuario_nome=getattr(user, "name", None),
                antes=antes,
                depois=depois,
            )
        )
    except Exception:
        logging.exception("Falha ao registrar auditoria (%s/%s)", entidade, chave)
        return False


def consultar(database, *, custos, entidade=None, chave=None, usuario=None,
              desde: date | None = None, ate: date | None = None, limite=100):
    """Lê o log. ``custos=True`` devolve só as entidades em R$; ``False`` nunca as devolve.

    ``desde``/``ate`` são dias inteiros (``ate`` inclusivo).
    """

    return database.listar_auditoria(
        entidade=entidade,
        chave=chave,
        usuario=usuario,
        desde=datetime.combine(desde, time.min) if desde else None,
        ate=datetime.combine(ate + timedelta(days=1), time.min) if ate else None,
        limite=limite,
        entidades=ENTIDADES_DE_CUSTO if custos else None,
        excluir_entidades=None if custos else ENTIDADES_DE_CUSTO,
    )
