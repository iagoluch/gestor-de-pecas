"""Contexto compacto da explicação de uma métrica para a IA do painel.

A IA do painel responde somente com a árvore que o servidor recalculou. Este
módulo transforma essa árvore em texto curto (setor -> recurso -> trecho) dentro
de um limite de tokens, agrupando o excedente em "outros N" e avisando quando
algo foi cortado, para a IA nunca tratar uma lista parcial como completa.
"""

from __future__ import annotations

from typing import Any

from mes.ai.context_budget import estimate_tokens

EXPLANATION_INSTRUCTION = """\
MODO EXPLICAÇÃO DE MÉTRICA. O usuário abriu o painel "de onde vem este número" e pergunta sobre ele.
Regras deste modo, que valem acima de qualquer outra orientação:
- Responda SOMENTE com os dados da explicação abaixo. Não consulte nem cite nenhuma outra fonte; nesta conversa não há ferramentas.
- Cite as horas e os trechos (horário inicial e final) que sustentam a resposta. Não recalcule o total nem invente causa, meta ou responsável.
- Se a pergunta fugir do que está na explicação (outra métrica, outra OP, motivo de negócio, dado não listado), diga "não sei" e oriente o usuário a abrir a tela Rastreabilidade da OP ou o painel da métrica correspondente.
- Se a explicação estiver marcada como TRUNCATED ou CONTEXTO REDUZIDO, avise o usuário explicitamente, na resposta, que nem todos os itens aparecem e que a conclusão vale só para o que foi listado.
- Escreva em português do Brasil, em frases curtas, com durações como "2h 30min"."""

_MAX_EXCLUDED = 10
_MAX_NOTES = 5
_NOTE_CHARS = 300
# Do mais rico ao mais enxuto: (profundidade, máximo de filhos por nível).
_SHAPES: tuple[tuple[int, int | None], ...] = (
    (3, None), (3, 20), (3, 10), (3, 5), (3, 3),
    (2, None), (2, 20), (2, 10), (2, 5), (2, 3),
    (1, None), (1, 10), (1, 5), (1, 3), (1, 1),
)


def hms(seconds: Any) -> str:
    try:
        total = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return "0min"
    hours, rest = divmod(total, 3600)
    minutes = rest // 60
    if hours and minutes:
        return f"{hours}h {minutes:02d}min"
    if hours:
        return f"{hours}h"
    if minutes:
        return f"{minutes}min"
    return f"{total}s" if total else "0min"


def _has_truncated(nodes: list[dict]) -> bool:
    return any(node.get("truncated") or _has_truncated(node.get("children") or []) for node in nodes)


def _stretch_line(node: dict) -> str:
    detail = node.get("detail") or {}
    extras = [str(item) for item in (detail.get("motivo"), detail.get("who")) if item]
    suffix = f" ({'; '.join(extras)})" if extras else ""
    return f"{node.get('label')}: {hms(node.get('seconds'))}{suffix}"


def _pick(nodes: list[dict], limit: int | None) -> tuple[list[dict], list[dict]]:
    if limit is None or len(nodes) <= limit:
        return nodes, []
    keep = sorted(range(len(nodes)), key=lambda i: -float(nodes[i].get("seconds") or 0))[:limit]
    kept = [nodes[i] for i in sorted(keep)]
    dropped = [node for i, node in enumerate(nodes) if i not in set(keep)]
    return kept, dropped


def _render_nodes(nodes: list[dict], level: int, depth: int, limit: int | None, lines: list[str]) -> bool:
    """Acrescenta as linhas e devolve True se algo foi agrupado em "outros N"."""
    if level > depth:
        return bool(nodes)
    grouped = False
    kept, dropped = _pick(nodes, limit)
    indent = "  " * (level - 1)
    for node in kept:
        if node.get("kind") == "stretch":
            lines.append(f"{indent}- {_stretch_line(node)}")
            continue
        lines.append(f"{indent}- {node.get('label')}: {hms(node.get('seconds'))}")
        grouped |= _render_nodes(node.get("children") or [], level + 1, depth, limit, lines)
    if dropped:
        grouped = True
        total = sum(float(node.get("seconds") or 0) for node in dropped)
        lines.append(f"{indent}- outros {len(dropped)}: {hms(total)}")
    return grouped


def _header(tree: dict) -> list[str]:
    lines = [f"Métrica: {tree.get('label')}", f"Total: {hms(tree.get('total_seconds'))}"]
    resources = int(tree.get("resource_count") or 0)
    average = tree.get("average_seconds")
    if average is not None and resources > 0:
        days = int(tree.get("day_count") or 0)
        scope = f"{resources} recursos" + (f", {days} dias" if days > 1 else "")
        lines.append(f"Média: {hms(average)} por recurso ({scope})")
    elif resources > 0:
        lines.append(f"Recursos: {resources}")
    if tree.get("reason"):
        lines.append(f"Significado: {tree['reason']}")
    if tree.get("rule"):
        lines.append(f"Regra: {tree['rule']}")
    return lines


def _footer(tree: dict) -> list[str]:
    lines: list[str] = []
    excluded = list(tree.get("excluded") or [])
    if excluded:
        lines.append("Itens que ficaram de fora desta métrica (e por quê):")
        for item in excluded[:_MAX_EXCLUDED]:
            lines.append(f"- {item.get('label')}: {hms(item.get('seconds'))}. {item.get('reason')}")
        if len(excluded) > _MAX_EXCLUDED:
            lines.append(f"- outros {len(excluded) - _MAX_EXCLUDED} itens excluídos não listados")
    notes = [str(note)[:_NOTE_CHARS] for note in (tree.get("notes") or [])][:_MAX_NOTES]
    if notes:
        lines.append("Observações:")
        lines.extend(f"- {note}" for note in notes)
    return lines


def build_explanation_context(tree: dict, *, max_tokens: int) -> str:
    """Texto de contexto (instrução + dados) com no máximo ``max_tokens`` estimados.

    Reduz a composição (menos níveis, menos itens por nível, "outros N") até caber;
    o cabeçalho, a regra, os excluídos e as observações sempre entram.
    """
    children = list(tree.get("children") or [])
    tree_truncated = bool(tree.get("truncated")) or _has_truncated(children)
    head, foot = _header(tree), _footer(tree)

    def assemble(body: list[str], *, reduced: bool) -> str:
        parts = [EXPLANATION_INSTRUCTION, ""]
        if tree_truncated:
            parts.append(
                "TRUNCATED: a explicação do painel foi cortada por tamanho; "
                "o total está certo, mas nem todos os itens aparecem."
            )
        if reduced:
            parts.append(
                "CONTEXTO REDUZIDO: para caber no limite da IA, itens foram agrupados "
                'em "outros N" ou omitidos.'
            )
        parts.extend(head)
        if body:
            parts.append("Composição (setor > recurso > trecho):")
            parts.extend(body)
        parts.extend(foot)
        return "\n".join(parts)

    for depth, limit in _SHAPES:
        body: list[str] = []
        grouped = _render_nodes(children, 1, depth, limit, body)
        text = assemble(body, reduced=grouped)
        if estimate_tokens(text) <= max_tokens:
            return text
    return assemble([], reduced=bool(children))
