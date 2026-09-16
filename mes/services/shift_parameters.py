"""Carrega os turnos configuráveis (H1/expediente/H2 e futuros) do banco.

Até esta rotina existir, os horários de fim de turno e a janela oficial
viviam como constantes fixas em ``mes/domain/manufacturing_rules.py``
(``SHIFT_END_BOUNDARIES``, ``OFFICIAL_WORK_WINDOW``). A tabela
``parametros_turno`` (migration 37, tela IagoDev) é agora a fonte: este
módulo só traduz as linhas em uma ``ManufacturingRules`` equivalente, sem
duplicar a regra de negócio em nenhum outro lugar.

Sem registro configurado (banco não migrado, tabela vazia, configuração
inconsistente), cai nos valores homologados de ``ManufacturingRules()`` — o
comportamento de hoje nunca fica sem uma janela oficial.
"""

from __future__ import annotations

from mes.domain.manufacturing_rules import ManufacturingRules


def load_manufacturing_rules(db) -> ManufacturingRules:
    """Monta a ``ManufacturingRules`` vigente a partir de ``parametros_turno``.

    Regra de derivação (generaliza H1/Oficial/H2 para N turnos futuros):

    * a linha ``tipo='expediente'`` define a janela oficial
      (``official_work_window``);
    * toda linha ``tipo='hora_extra'`` cadastrada entra em
      ``overtime_windows``, na ordem configurada;
    * ``shift_end_boundaries`` é o fim do expediente encadeado com o fim de
      cada hora extra que começa exatamente onde a anterior termina (H2 hoje;
      H3, H4... amanhã, se a fábrica precisar) — janelas de hora extra
      **antes** do expediente (H1) não geram limite próprio: quem já está
      trabalhando ali é protegido pela regra de execução ativa, não por um
      corte automático.
    """

    loader = getattr(db, "listar_parametros_turno", None)
    rows = list(loader(somente_ativos=True) or []) if callable(loader) else []
    expediente_rows = [row for row in rows if str(row.get("tipo") or "") == "expediente"]
    if len(expediente_rows) != 1:
        # Sem configuração (ou configuração ambígua/quebrada): mantém o
        # comportamento homologado em vez de arriscar uma janela oficial vazia.
        return ManufacturingRules()

    expediente = expediente_rows[0]
    official_work_window = (expediente["hora_inicio"], expediente["hora_fim"])

    overtime_rows = sorted(
        (row for row in rows if str(row.get("tipo") or "") == "hora_extra"),
        key=lambda row: row["hora_inicio"],
    )
    overtime_windows = tuple((row["hora_inicio"], row["hora_fim"]) for row in overtime_rows)

    boundaries = [official_work_window[1]]
    cursor = official_work_window[1]
    changed = True
    remaining = list(overtime_rows)
    while changed:
        changed = False
        for row in list(remaining):
            if row["hora_inicio"] == cursor:
                boundaries.append(row["hora_fim"])
                cursor = row["hora_fim"]
                remaining.remove(row)
                changed = True
                break

    return ManufacturingRules(
        shift_end_boundaries=tuple(dict.fromkeys(boundaries)),
        official_work_window=official_work_window,
        overtime_windows=overtime_windows,
    )


__all__ = ["load_manufacturing_rules"]
