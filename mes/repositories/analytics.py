"""Protocolos estruturais usados pelos serviços gerenciais.

O ``Database`` atual satisfaz este contrato por duck typing. Uma futura API Web
ou adapter para banco corporativo pode implementar o mesmo protocolo sem mudar
as regras do MES.
"""

from typing import Protocol


class AnalyticsRepository(Protocol):
    def listar_fatos_operacionais_periodo(
        self, inicio, fim, *, setor=None, recurso=None, op=None, operacao=None, produto=None,
        operador=None,
    ): ...

    def listar_tempos_nesting_corte(self, inicio=None, fim=None, maquina=None, search=None): ...

    def listar_nestings_corte_por_op(self, op): ...

    def listar_eventos_quantidade_periodo(
        self, inicio, fim, *, setor=None, recurso=None, op=None, operacao=None, produto=None,
        operador=None,
    ): ...

    def listar_rateios_tempo_periodo(
        self, inicio, fim, *, setor=None, recurso=None, op=None, operacao=None,
    ): ...

    def listar_estados_recurso_periodo(
        self, inicio, fim, *, setor=None, recurso=None, categoria=None, op=None, operacao=None,
    ): ...

    def listar_estados_recurso_atuais(self, *, setor=None, recurso=None): ...

    def listar_intervalos_turno(self, turno_id): ...

    def listar_excecoes_calendario_periodo(self, calendario_codigo, inicio, fim): ...

    def possui_calendario_produtivo(self, setor=None, recurso=None): ...

    def listar_configuracao_capacidade_recursos(self, *, setor=None, recurso=None): ...

    def listar_inconsistencias_dados(self, *, somente_abertas=True, severidade=None): ...


class KpiTargetRepository(Protocol):
    """Extensão opcional; a ausência dela proíbe alertas baseados em meta."""

    def listar_metas_indicadores(
        self, *, inicio, fim, setor=None, recurso=None, turno=None,
    ): ...
