"""Visão gerencial de acompanhamento da Solda (Wave 6D).

Leitura para PCP, Liderança, Supervisão e Diretoria. Não é tela de posto: aqui
não existe comando, seleção de estação nem login por estação. O serviço compõe
o que já é canônico no Gestor e delega a classificação de prazo ao domínio.

Três decisões estruturais desta visão:

* **A OP mantém a identidade canônica do catálogo.** Nenhum código novo é
  criado e a OP não é duplicada. A linha é ``(OP, operação de Solda)``, que é a
  unidade que a PCP acompanha quando o roteiro tem mais de uma solda.
* **A estação é observada, não derivada.** O posto pega a OP e escolhe a
  estação ao executar; não existe mapeamento determinístico de produto ou
  máquina para estação. A estação exibida é a do apontamento real, e a OP sem
  execução fica no agrupamento sem estação — que a tela explica em texto.
* **Estado técnico continua no contrato.** Modelo ausente, estação ausente e
  prazo desconhecido saem daqui como estado (``nao_configurado``,
  ``sem_registros``, ``dados_insuficientes``). Quem traduz para texto humano é
  a camada de apresentação.

Atraso é acompanhamento: nada neste serviço é consultado por iniciar, parar,
retomar ou finalizar. Uma OP atrasada continua integralmente executável.
"""

from __future__ import annotations

from datetime import date, datetime

from app.core.resource_mapping import resource_display_name
from mes.domain import DataAvailability
from mes.domain.welding import (
    WELDING_SECTOR,
    WELDING_STATUS_DONE,
    WELDING_STATUS_DUE,
    WELDING_STATUS_LATE,
    classify_welding_status,
    resolve_creation_basis,
    resolve_deadline_basis,
)


def _text(value):
    return str(value or "").strip()


def _moment(value):
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None


def _basis(temporal):
    return {
        "value": _moment(temporal.value),
        "label": temporal.label,
        "availability": temporal.availability,
    }


class WeldingManagementService:
    """Projeta as OPs de conjunto soldado por estação observada."""

    def __init__(self, db, now_func=None, simulation_mode=False):
        self.db = db
        self._now = now_func or datetime.now
        self.simulation_mode = bool(simulation_mode)

    # ------------------------------------------------------------------
    def acompanhamento(self, *, limite=300):
        agora = self._now()
        linhas = [
            self._linha(row, agora)
            for row in self.db.listar_ops_solda_gerencial(limite=limite)
        ]
        estacoes = self._agrupar_por_estacao(linhas)
        return {
            "setor": WELDING_SECTOR,
            "generated_at": _moment(agora),
            "availability": (
                DataAvailability.AVAILABLE.value
                if linhas
                else DataAvailability.NO_RECORDS.value
            ),
            "resumo": self._resumo(linhas),
            "macros": self._agrupar_por_macro(linhas),
            "estacoes": estacoes,
            "simulation_only": self.simulation_mode,
        }

    # ------------------------------------------------------------------
    def _linha(self, row, agora):
        # A regra temporal recebe chaves neutras: o serviço é quem conhece a
        # persistência, o domínio conhece apenas "criação" e "prazo".
        pedido = {
            "data_emissao": row.get("data_emissao"),
            "data_geracao": row.get("data_geracao"),
            "prazo_entrega": row.get("prazo_entrega"),
            "fim_planejado": row.get("fim_planejado"),
        }
        status = classify_welding_status(
            pedido,
            appointment_status=row.get("status_apontamento"),
            first_appointment=row.get("primeiro_apontamento"),
            now=agora,
        )
        estacao = _text(row.get("estacao_observada"))
        modelo = _text(row.get("produto_modelo"))
        return {
            # Identidade canônica da OP, exatamente como o catálogo a guarda.
            "op": _text(row.get("codigo_op")),
            "operacao": _text(row.get("numero_operacao")) or None,
            "produto": {
                "codigo": _text(row.get("produto_codigo")) or None,
                "descricao": _text(row.get("produto_descricao")) or None,
                "quantidade": row.get("quantidade"),
            },
            "maquina": {
                "codigo": _text(row.get("codigo_recurso")) or None,
                "nome": resource_display_name(
                    row.get("codigo_recurso"), row.get("recurso_nome")
                ) or None,
                "operacao": _text(row.get("descricao_operacao")) or None,
            },
            "modelo": {
                "value": modelo or None,
                "availability": (
                    DataAvailability.AVAILABLE.value
                    if modelo
                    else DataAvailability.NOT_CONFIGURED.value
                ),
            },
            "estacao": {
                "value": estacao or None,
                "availability": (
                    DataAvailability.AVAILABLE.value
                    if estacao
                    else DataAvailability.NO_RECORDS.value
                ),
            },
            "datas": {
                "emissao": _moment(row.get("data_emissao")),
                "prazo": _moment(row.get("prazo_entrega")),
                "inicio_planejado": _moment(row.get("inicio_planejado")),
                "fim_planejado": _moment(row.get("fim_planejado")),
                "inicio_real": _moment(row.get("apontamento_inicio")),
                "fim_real": _moment(row.get("apontamento_fim")),
                "criacao": _basis(resolve_creation_basis(pedido)),
                "referencia_prazo": _basis(resolve_deadline_basis(pedido)),
            },
            "status": {
                "value": status.value,
                "availability": status.availability,
                "reason": status.reason,
            },
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _agrupar_por_estacao(linhas):
        """Agrupa por estação observada, com um grupo final sem estação.

        O grupo sem estação existe porque a OP pode estar planejada e ainda não
        ter passado por nenhum posto. Ele nunca recebe uma estação escolhida por
        inferência.
        """

        grupos = {}
        for linha in linhas:
            chave = linha["estacao"]["value"]
            grupo = grupos.setdefault(
                chave,
                {
                    "nome": chave,
                    "availability": linha["estacao"]["availability"],
                    "ops": [],
                },
            )
            grupo["ops"].append(linha)
        identificadas = sorted(
            (grupo for chave, grupo in grupos.items() if chave),
            key=lambda grupo: _station_order(grupo["nome"]),
        )
        sem_estacao = [grupo for chave, grupo in grupos.items() if not chave]
        for grupo in identificadas + sem_estacao:
            grupo["ops"].sort(key=_row_order)
            grupo["op_count"] = len(grupo["ops"])
        return identificadas + sem_estacao

    @staticmethod
    def _agrupar_por_macro(linhas):
        """Pivô MACRO × situação de prazo, com o mesmo estado já classificado.

        MACRO é o produto/conjunto planejado da OP — a mesma identidade que a
        linha já carrega em ``produto``. Nada é reclassificado aqui: a contagem
        usa ``status.value``, que veio do domínio. A OP sem produto cadastrado
        fica em um grupo próprio e declarado, nunca distribuída por semelhança.
        """

        grupos = {}
        for linha in linhas:
            produto = linha["produto"]
            nome = produto["descricao"] or produto["codigo"]
            grupo = grupos.setdefault(str(nome or ""), {
                "nome": nome,
                "codigo": produto["codigo"],
                "availability": (
                    DataAvailability.AVAILABLE.value
                    if nome
                    else DataAvailability.NOT_CONFIGURED.value
                ),
                "a_vencer": 0,
                "atrasadas": 0,
                "finalizadas": 0,
                "sem_prazo": 0,
                "total": 0,
            })
            chave = {
                WELDING_STATUS_DUE: "a_vencer",
                WELDING_STATUS_LATE: "atrasadas",
                WELDING_STATUS_DONE: "finalizadas",
            }.get(linha["status"]["value"], "sem_prazo")
            grupo[chave] += 1
            grupo["total"] += 1
        # O que está atrasado aparece primeiro: a tela existe para mostrar risco.
        return sorted(
            grupos.values(),
            key=lambda grupo: (
                -grupo["atrasadas"], -grupo["total"], str(grupo["nome"] or "").casefold(),
            ),
        )

    @staticmethod
    def _resumo(linhas):
        estados = [linha["status"]["value"] for linha in linhas]
        return {
            "ops": len({linha["op"] for linha in linhas}),
            "linhas": len(linhas),
            "estacoes": len({
                linha["estacao"]["value"] for linha in linhas if linha["estacao"]["value"]
            }),
            "a_vencer": estados.count(WELDING_STATUS_DUE),
            "atrasadas": estados.count(WELDING_STATUS_LATE),
            "finalizadas": estados.count(WELDING_STATUS_DONE),
            "sem_prazo": estados.count(None),
            "sem_modelo": sum(1 for linha in linhas if not linha["modelo"]["value"]),
            "sem_estacao": sum(1 for linha in linhas if not linha["estacao"]["value"]),
        }


def _station_order(nome):
    """Ordena "Estação 2" antes de "Estação 10" sem depender de cadastro novo."""

    texto = _text(nome)
    digitos = "".join(character for character in texto if character.isdigit())
    return (0, int(digitos), texto) if digitos else (1, 0, texto.casefold())


def _row_order(linha):
    """Atrasada primeiro, depois a vencer, depois o que já terminou."""

    prioridade = {
        WELDING_STATUS_LATE: 0,
        WELDING_STATUS_DUE: 1,
        None: 2,
        WELDING_STATUS_DONE: 3,
    }
    referencia = linha["datas"]["referencia_prazo"]["value"] or ""
    return (prioridade.get(linha["status"]["value"], 2), referencia, linha["op"])
