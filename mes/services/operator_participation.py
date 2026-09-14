"""Tempo-pessoa na mesma OP.

Duas grandezas diferentes convivem aqui, e confundi-las é o erro que este
serviço existe para impedir:

* **Tempo da OP** — quanto tempo a execução ficou aberta no recurso. É um só,
  vem de ``apontamentos_operacionais``/``sessoes_recurso`` e **não é dividido**
  entre as pessoas.
* **Tempo-pessoa** — quanto tempo cada pessoa esteve naquela execução. Com A e
  B juntos por 60 minutos, o tempo da OP é 60 e o tempo-pessoa é 120. Não é
  duplicidade: é outra pergunta.

A fonte canônica do tempo-pessoa é ``participacoes_operador``, uma linha por
pessoa por execução. O operador que abriu o apontamento continua registrado em
``apontamentos_operacionais.operador_inicio`` e nunca é substituído: ele apenas
passa a ser uma das participações, marcada como principal.
"""

from __future__ import annotations

import logging

from mes.domain import OperatorState


#: Estados em que existe alguém trabalhando na OP. Parada não conta tempo-pessoa
#: de produção: a pessoa está no recurso, mas a execução está interrompida — o
#: estado físico do recurso já é registrado por ``eventos_estado_recurso``.
PARTICIPATION_STATES = (
    OperatorState.PRODUCTION,
    OperatorState.SETUP,
    OperatorState.REWORK,
)


class OperatorParticipationService:
    """Mantém as participações abertas de um apontamento em dia."""

    def __init__(self, db, *, now_func=None):
        self.db = db
        self._now = now_func

    # ------------------------------------------------------------------
    def _instante(self, apontamento):
        if callable(self._now):
            return self._now()
        return (apontamento or {}).get("data_fim") or (apontamento or {}).get("data_inicio")

    def _resolver_pessoas(self, crachas):
        """Traduz crachás em pessoas cadastradas, sem inventar identidade."""

        codigos = [str(item or "").strip() for item in (crachas or ()) if str(item or "").strip()]
        if not codigos:
            return []
        finder = getattr(self.db, "buscar_operadores_apontamento", None)
        registrados = list(finder(codigos) or []) if callable(finder) else []
        por_cracha = {
            str(item.get("cracha") or "").strip(): item for item in registrados
        }
        pessoas = []
        vistos = set()
        for codigo in codigos:
            chave = codigo.casefold()
            if chave in vistos:
                # A mesma pessoa informada duas vezes na mesma ação é uma só
                # participação — e isso não é erro do operador, é digitação.
                continue
            vistos.add(chave)
            registro = por_cracha.get(codigo) or {}
            pessoas.append({
                "cracha": codigo,
                "operador_id": registro.get("id"),
                "nome": registro.get("nome") or codigo,
            })
        return pessoas

    # ------------------------------------------------------------------
    def sincronizar(self, *, apontamento, setor, recurso, op, operacao, target, crachas):
        """Aplica a uma execução aceita o conjunto de pessoas informado.

        * entra quem ainda não estava (início, setup, retrabalho, retomada);
        * sai quem deixou de ser informado (troca de operador);
        * na finalização todo mundo sai.

        Nada aqui pode recusar um apontamento já aceito.
        """

        opener = getattr(self.db, "iniciar_participacao_operador", None)
        closer = getattr(self.db, "finalizar_participacoes_apontamento", None)
        lister = getattr(self.db, "listar_participacoes_apontamento", None)
        apontamento_id = (apontamento or {}).get("id")
        if apontamento_id is None or not callable(opener) or not callable(closer):
            return []
        instante = self._instante(apontamento)

        if target == OperatorState.FINISHED:
            closer(apontamento_id, data_fim=instante)
            return list(lister(apontamento_id) or []) if callable(lister) else []
        if target not in PARTICIPATION_STATES:
            # Parada mantém as participações abertas de propósito: a pessoa não
            # deixou a OP, a execução é que está interrompida.
            return list(lister(apontamento_id) or []) if callable(lister) else []

        pessoas = self._resolver_pessoas(crachas)
        if not pessoas:
            # Ação sem crachá não apaga quem já estava: a equipe informada
            # continua valendo até alguém informar outra.
            return list(lister(apontamento_id) or []) if callable(lister) else []

        abertas = (
            list(lister(apontamento_id, somente_abertas=True) or [])
            if callable(lister)
            else []
        )
        atuais = {str(row.get("cracha") or "").strip().casefold() for row in abertas}
        informados = {pessoa["cracha"].casefold() for pessoa in pessoas}
        saindo = [
            str(row.get("cracha") or "").strip()
            for row in abertas
            if str(row.get("cracha") or "").strip().casefold() not in informados
        ]
        if saindo:
            closer(apontamento_id, data_fim=instante, crachas=saindo)

        principal_definido = any(row.get("operador_principal") for row in abertas)
        for pessoa in pessoas:
            if pessoa["cracha"].casefold() in atuais:
                continue
            opener(
                recurso,
                operador_id=pessoa["operador_id"],
                cracha=pessoa["cracha"],
                nome=pessoa["nome"],
                tipo_setor=setor,
                op=op,
                numero_operacao=(operacao or {}).get("numero_operacao"),
                data_inicio=instante,
                apontamento_id=apontamento_id,
                tipo_participacao=getattr(target, "value", str(target)),
                operador_principal=not principal_definido,
                referencia_origem=f"apontamento:{apontamento_id}",
            )
            principal_definido = True
        return list(lister(apontamento_id) or []) if callable(lister) else []

    # ------------------------------------------------------------------
    def resumo(self, apontamento_id, *, agora=None):
        """Tempo-pessoa consolidado de uma execução.

        ``tempo_op_segundos`` não é a soma: é a duração da execução. A soma das
        pessoas fica em ``tempo_pessoa_segundos`` e é maior quando há mais de
        uma pessoa — por definição.
        """

        lister = getattr(self.db, "listar_participacoes_apontamento", None)
        if not callable(lister):
            return {"pessoas": [], "tempo_pessoa_segundos": 0.0, "total_pessoas": 0}
        referencia = agora or (self._now() if callable(self._now) else None)
        pessoas = []
        total = 0.0
        for row in lister(apontamento_id) or ():
            inicio = row.get("data_inicio")
            fim = row.get("data_fim") or referencia
            segundos = (
                max(0.0, (fim - inicio).total_seconds())
                if inicio is not None and fim is not None
                else 0.0
            )
            total += segundos
            pessoas.append({
                "cracha": row.get("cracha"),
                "nome": row.get("nome"),
                "principal": bool(row.get("operador_principal")),
                "tipo_participacao": row.get("tipo_participacao"),
                "data_inicio": inicio,
                "data_fim": row.get("data_fim"),
                "segundos": segundos,
            })
        return {
            "pessoas": pessoas,
            "total_pessoas": len({item["cracha"] for item in pessoas if item["cracha"]}),
            "tempo_pessoa_segundos": total,
            "fonte": "participacoes_operador",
            "politica": (
                "O tempo da OP não é dividido entre as pessoas; o tempo-pessoa "
                "é a soma das participações."
            ),
        }


def sincronizar_participacoes(service, **kwargs):
    """Efeito colateral protegido: participação nunca derruba um apontamento."""

    try:
        return service.sincronizar(**kwargs)
    except Exception:  # pragma: no cover - efeito colateral não bloqueia
        logging.exception(
            "Falha ao sincronizar o tempo-pessoa do apontamento %s.",
            (kwargs.get("apontamento") or {}).get("id"),
        )
        return []


__all__ = [
    "OperatorParticipationService",
    "PARTICIPATION_STATES",
    "sincronizar_participacoes",
]
