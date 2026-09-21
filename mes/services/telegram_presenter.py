"""Apresentação HTML única da interface Telegram do Gestor de Peças."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape


FRONTS = {
    "corte": ("✂️", "Corte"),
    "solda": ("👨‍🏭", "Solda"),
    "pintura": ("🫟", "Pintura"),
    "caldeiraria": ("🔨", "Caldeiraria"),
}


@dataclass(frozen=True)
class TelegramView:
    text: str
    reply_markup: dict | None = None


def html(value) -> str:
    return escape(str(value if value is not None else ""), quote=True)


def format_duration(seconds) -> str:
    total = max(0, int(float(seconds or 0)))
    hours, remainder = divmod(total, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes}min" if minutes else f"{hours}h"
    return f"{minutes}min" if minutes else "menos de 1min"


def format_number(value) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:,}".replace(",", ".")


def format_percent(metric) -> str | None:
    value = (metric or {}).get("value")
    if value is None:
        return None
    number = float(value)
    rendered = f"{number:.1f}" if not number.is_integer() else f"{number:.0f}"
    return rendered.replace(".", ",") + "%"


def button(text: str, callback_data: str, style: str | None = None) -> dict:
    result = {"text": text, "callback_data": callback_data}
    if style:
        result["style"] = style
    return result


def keyboard(*rows: list[dict]) -> dict:
    return {"inline_keyboard": list(rows)}


def _header(icon: str, title: str) -> list[str]:
    return [f"{icon} <b>{html(title)}</b>", ""]


def _op_lines(item: dict, *, operator: str | None = None) -> list[str]:
    """Render the common OP context without inventing absent fields."""
    op = item.get("op") or item.get("production_order") or item.get("production_order_number")
    if not op:
        return []
    lines = [f"🧾 OP: <b>{html(op)}</b>"]
    fields = (
        ("Setor", item.get("setor") or item.get("tipo_setor") or item.get("sector")),
        ("Peça", item.get("peca") or item.get("produto_codigo") or item.get("product") or item.get("item_code")),
        ("Descrição", item.get("descricao") or item.get("produto_descricao") or item.get("product_description") or item.get("item_description")),
        ("Etapa roteiro", item.get("etapa_roteiro") or item.get("descricao_operacao") or item.get("operation_description") or item.get("operation") or item.get("terminal_operation")),
        ("Quantidade", item.get("quantidade") or item.get("quantity") or item.get("planned_quantity") or item.get("good_quantity")),
    )
    for label, value in fields:
        if value is not None and str(value).strip():
            lines.append(f"{label}: {html(value)}")
    operator_value = operator or item.get("operador") or item.get("operator")
    resource = item.get("recurso") or item.get("resource") or item.get("resource_code")
    if operator_value or resource:
        parts = []
        if operator_value:
            parts.append(html(operator_value))
        if resource:
            parts.append(html(resource))
        lines.extend(["", " • ".join(parts)])
    return lines


def _footer(label: str, now: datetime) -> str:
    return f"🕐 <b>{label} {now:%H:%M}</b>"


def _first(item: dict, *keys):
    """Primeiro valor preenchido entre apelidos equivalentes do mesmo campo."""

    for key in keys:
        value = (item or {}).get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _station_lines(item: dict) -> list[str]:
    """Identifica o posto do fato: máquina, OP e peça, sem inventar ausentes.

    Os apelidos cobrem as três origens que alimentam estes avisos sem
    normalização intermediária: apontamento operacional, estado físico do
    recurso (``eventos_estado_recurso``) e fila do Corte.
    """

    fields = (
        ("Máquina", _first(item, "maquina", "recurso", "resource", "codigo_recurso")),
        ("Setor", _first(item, "setor", "tipo_setor", "sector")),
        ("OP", _first(item, "op", "codigo_op", "production_order")),
        # No Corte a identidade do trabalho é a tarefa, não a OP.
        ("Tarefa", _first(item, "codigo_tarefa")),
        ("Operação", _first(item, "numero_operacao", "operation")),
        ("Peça", _first(item, "produto_codigo", "peca", "product")),
        ("Descrição", _first(item, "produto_descricao", "descricao", "description")),
    )
    return [f"{label}: <b>{html(value)}</b>" for label, value in fields if value]


def _timestamp_lines(now: datetime) -> list[str]:
    """Data e hora explícitas: quem recebe o aviso no celular precisa das duas."""

    return [f"📅 Data: <b>{now:%d/%m/%Y}</b>", f"🕐 Hora: <b>{now:%H:%M}</b>"]


def _chamada_solicitante(item: dict) -> str:
    """Quem apertou o botão: o login do posto é compartilhado, o crachá não."""

    nome = _first(item, "solicitante_nome") or "Não identificado"
    nivel = _first(item, "solicitante_nivel")
    partes = [f"{nome} ({nivel})" if nivel else nome]
    cracha = _first(item, "solicitante_cracha")
    if cracha:
        partes.append(f"crachá {cracha}")
    email = _first(item, "solicitante_email")
    if email:
        partes.append(email)
    return " — ".join(partes)


def _home_button() -> dict:
    return button("🏠 Menu", "gp:home", "primary")


def _front_buttons(prefix: str) -> list[list[dict]]:
    return [
        [
            button("✂️ Corte", f"gp:{prefix}:corte", "primary"),
            button("👨‍🏭 Solda", f"gp:{prefix}:solda", "primary"),
        ],
        [
            button("🫟 Pintura", f"gp:{prefix}:pintura", "primary"),
            button("🔨 Caldeiraria", f"gp:{prefix}:caldeiraria", "primary"),
        ],
    ]


class TelegramPresenter:
    def cut_plan_event(
        self, *, item: dict, event: str, now: datetime
    ) -> str | None:
        """Apresenta o apontamento físico do Corte sem inventar sua hierarquia."""

        task = str(item.get("codigo_tarefa") or "").strip()
        program = str(item.get("programa_atual") or item.get("programa") or "").strip()
        machine = str(item.get("maquina") or "").strip()
        if not task or not program or not machine:
            return None

        titles = {
            "corte_iniciado": ("🟢", "Corte iniciado"),
            "corte_nesting_concluido": ("🟢", "Próximo nesting iniciado"),
            "corte_finalizado": ("✅", "Plano concluído"),
        }
        icon, title = titles.get(event, ("🔵", "Atualização do Corte"))
        lines = [f"{icon} <b>{title}</b>", "", f"Tarefa: <b>{html(task)}</b>", f"Plano: <b>{html(program)}</b>"]

        same_program = [
            nesting for nesting in (item.get("nestings") or [])
            if str(nesting.get("programa") or "").strip() == program
        ]
        if len(same_program) > 1:
            current = next(
                (nesting for nesting in same_program if nesting.get("status") == "Em processo"),
                None,
            )
            if current is None:
                current = max(
                    same_program,
                    key=lambda nesting: int(nesting.get("sequencia") or 0),
                )
            nesting_id = current.get("repeticao")
            if nesting_id is None or not str(nesting_id).strip():
                nesting_id = current.get("sequencia")
            if nesting_id is not None and str(nesting_id).strip():
                lines.append(f"Nesting: <b>{html(nesting_id)}</b>")

        sector = item.get("setor") or item.get("tipo_setor") or item.get("sector") or "Corte"
        lines.append(f"Setor: <b>{html(sector)}</b>")
        operator = item.get("operador_fim") or item.get("operador_inicio")
        if operator or machine:
            context = []
            if operator:
                context.append(html(operator))
            if machine:
                context.append(html(machine))
            lines.extend([
                "",
                " • ".join(context),
            ])
        lines.extend(["", _footer("Ocorrido às", now)])
        return "\n".join(lines)

    def menu(self, *, name, linked: bool, summary: dict, good, now: datetime) -> TelegramView:
        lines = _header("🏠", "Menu principal")
        if name:
            lines.append(f"Olá, {html(name)}.")
            lines.append("")
        downtime = summary.get("downtime")
        production = summary.get("production")
        if downtime is not None:
            icon = "🔴" if downtime else "🟢"
            label = f"{downtime} parada{'s' if downtime != 1 else ''} ativa{'s' if downtime != 1 else ''}"
            lines.append(f"{icon} <b>{label}</b>")
        if production is not None:
            lines.append(f"🟢 <b>{production} recursos produzindo</b>")
        if good is not None:
            lines.append(f"📦 <b>{format_number(good)} peças hoje</b>")
        lines.extend(["", "O que você deseja consultar?", "", _footer("Atualizado às", now)])
        stop_style = "danger" if downtime else "success"
        stop_text = f"🔴 Paradas • {downtime}" if downtime else "🟢 Sem paradas"
        personal = (
            button("👤 Meu status", "gp:me", "primary")
            if linked
            else button("🔗 Vincular crachá", "gp:link", "primary")
        )
        return TelegramView("\n".join(lines), keyboard(
            [button("🏭 Fábrica", "gp:factory", "primary"), button("📊 Produção", "gp:production", "primary")],
            [button(stop_text, "gp:stops", stop_style), button("🧭 Frentes", "gp:fronts", "primary")],
            [personal, button("❓ Ajuda", "gp:help", "primary")],
        ))

    def factory(self, *, summary: dict, stopped: list[dict], now: datetime) -> TelegramView:
        lines = _header("🏭", "Status da fábrica")
        entries = (
            ("🟢", "production", "produzindo"),
            ("🔴", "downtime", "parados"),
            ("🟡", "setup", "em setup"),
            ("🟡", "rework", "em retrabalho"),
        )
        for icon, key, label in entries:
            if summary.get(key) is not None:
                lines.append(f"{icon} <b>{summary[key]} {label}</b>")
        if stopped:
            lines.extend(["", "<b>🔴 Parados agora</b>", ""])
            for item in stopped[:12]:
                lines.append(f"⚙️ <b>{html(item.get('name') or 'Recurso não informado')}</b>")
                label = html(item.get("reason") or "Motivo não informado")
                duration = format_duration(item.get("duration_seconds"))
                lines.append(f"{label} • <b>{duration}</b>")
                lines.append("")
        elif summary.get("downtime") == 0:
            lines.extend(["", "🟢 <b>Nenhuma parada ativa.</b>", ""])
        lines.append(_footer("Atualizado às", now))
        stop_count = summary.get("downtime")
        stop_label = f"🔴 Ver paradas • {stop_count}" if stop_count else "🟢 Sem paradas"
        return TelegramView("\n".join(lines), keyboard(
            [button(stop_label, "gp:stops", "danger" if stop_count else "success"), button("📊 Produção", "gp:production", "primary")],
            [button("🧭 Frentes", "gp:fronts", "primary")],
            [button("🔄 Atualizar", "gp:factory", "primary"), _home_button()],
        ))

    def production(self, *, front: str | None, data: dict, now: datetime) -> TelegramView:
        icon, label = FRONTS.get(front, ("📊", "Produção"))
        title = f"Produção · {label}" if front else "Produção"
        lines = _header(icon, title)
        lines.extend([
            f"📈 Peças boas: <b>{format_number(data.get('good'))}</b>",
            f"📦 Refugo: <b>{format_number(data.get('scrap'))}</b>",
            f"📦 Retrabalho: <b>{format_number(data.get('rework'))}</b>",
        ])
        for title_label, key in (("OEE", "oee"), ("Disponibilidade", "availability"), ("Performance", "performance"), ("FTT", "ftt")):
            value = format_percent((data.get("kpis") or {}).get(key))
            if value is not None:
                lines.append(f"{title_label}: <b>{value}</b>")
        lines.extend(["", _footer("Atualizado às", now)])
        rows = [[button("🏭 Geral", "gp:production", "primary")], *_front_buttons("prod")]
        rows.append([button("🔄 Atualizar", f"gp:prod:{front}" if front else "gp:production", "primary"), _home_button()])
        return TelegramView("\n".join(lines), keyboard(*rows))

    def stops(self, *, front: str | None, active: list[dict], total_seconds, counts: dict, now: datetime) -> TelegramView:
        icon, label = FRONTS.get(front, ("⏱️", "Paradas"))
        title = f"Paradas · {label}" if front else "Paradas"
        lines = _header(icon, title)
        count = len(active)
        status_icon = "🔴" if count else "🟢"
        lines.append(f"{status_icon} <b>{count} recurso{'s' if count != 1 else ''} parado{'s' if count != 1 else ''}</b>")
        if total_seconds is not None:
            lines.append(f"⏱️ Tempo acumulado hoje: <b>{format_duration(total_seconds)}</b>")
        if active:
            lines.extend(["", "<b>Paradas em andamento</b>", ""])
            for item in active[:12]:
                lines.append(f"🔴 <b>{html(item.get('name') or 'Recurso não informado')}</b>")
                lines.append(f"🔧 {html(item.get('reason') or 'Motivo não informado')}")
                lines.append(f"⏱️ <b>{format_duration(item.get('duration_seconds'))}</b>")
                lines.append("")
        lines.append(_footer("Atualizado às", now))

        def stop_button(front_key: str | None, text: str) -> dict:
            value = counts.get(front_key or "all")
            suffix = f" • {value}" if value is not None else ""
            style = "danger" if value else "success" if value == 0 else None
            callback = "gp:stops" if front_key is None else f"gp:stops:{front_key}"
            return button(text + suffix, callback, style)

        rows = [
            [stop_button(None, "🏭 Todas")],
            [stop_button("corte", "Corte"), stop_button("solda", "Solda")],
            [stop_button("pintura", "Pintura"), stop_button("caldeiraria", "Caldeiraria")],
            [button("🔄 Atualizar", f"gp:stops:{front}" if front else "gp:stops", "primary"), _home_button()],
        ]
        return TelegramView("\n".join(lines), keyboard(*rows))

    def fronts(self) -> TelegramView:
        lines = _header("🧭", "Frentes")
        lines.append("Escolha uma frente para consultar.")
        return TelegramView("\n".join(lines), keyboard(*_front_buttons("front"), [_home_button()]))

    def front(self, *, front: str, summary: dict, good, now: datetime) -> TelegramView:
        icon, label = FRONTS[front]
        lines = _header(icon, label)
        lines.append(f"🟢 <b>{summary.get('production', 0)} produzindo</b>")
        lines.append(f"🔴 <b>{summary.get('downtime', 0)} parados</b>")
        if good is not None:
            lines.extend(["", f"📦 Produção: <b>{format_number(good)} peças</b>"])
        lines.extend(["", "O que deseja consultar?", "", _footer("Atualizado às", now)])
        return TelegramView("\n".join(lines), keyboard(
            [button("📊 Produção", f"gp:prod:{front}", "primary"), button("⏱️ Paradas", f"gp:stops:{front}", "danger" if summary.get("downtime") else "success")],
            [button("🔄 Atualizar", f"gp:front:{front}", "primary")],
            [button("⬅️ Frentes", "gp:fronts", "primary"), _home_button()],
        ))

    def my_status(self, *, operator: dict | None, participations: list[dict], now: datetime) -> TelegramView:
        if operator is None:
            return self.link_badge(now=now)
        lines = _header("👤", "Meu status")
        lines.append(f"👤 Operador: <b>{html(operator.get('nome') or 'Não informado')}</b>")
        lines.append(f"🪪 Crachá: <b>{html(operator.get('cracha'))}</b>")
        if not participations:
            lines.extend(["", "⚪ Nenhuma operação em aberto agora."])
        else:
            lines.append("")
            for item in participations:
                lines.extend(_op_lines(item, operator=operator.get("nome")))
                if item.get("numero_operacao") is not None:
                    lines.append(f"Operação: <b>{html(item.get('numero_operacao'))}</b>")
                started_at = item.get("data_inicio")
                if started_at:
                    lines.append(f"⏱️ Em andamento há <b>{format_duration((now - started_at).total_seconds())}</b>")
                lines.append("")
        lines.append(_footer("Atualizado às", now))
        return TelegramView("\n".join(lines), keyboard([button("🔄 Atualizar", "gp:me", "primary"), _home_button()]))

    def link_badge(self, *, now: datetime, message: str | None = None, success: bool = False) -> TelegramView:
        lines = _header("🔗", "Vincular crachá")
        if message:
            lines.append(("✅" if success else "❌") + f" {html(message)}")
        else:
            lines.extend(["Envie:", "", "<code>/vincular SEU_CRACHÁ</code>", "", "Use o mesmo crachá do posto."])
        lines.extend(["", _footer("Consulta realizada às", now)])
        return TelegramView("\n".join(lines), keyboard([_home_button()]))

    def help(self) -> TelegramView:
        lines = _header("❓", "Ajuda")
        lines.extend([
            "Você pode usar o menu ou simplesmente perguntar.", "",
            "Exemplos:", "• Como está a fábrica?", "• Tem alguma parada no Corte?", "• Produção da Solda", "• Meu status", "",
            "Comandos disponíveis:", "/fabrica", "/producao", "/paradas", "/meustatus", "/vincular", "/menu", "/ajuda",
        ])
        return TelegramView("\n".join(lines), keyboard([_home_button()]))

    def unavailable(self, *, retry_callback: str, now: datetime) -> TelegramView:
        lines = _header("⚪", "Dados indisponíveis no momento")
        lines.extend(["Não existem informações suficientes para esta consulta.", "", _footer("Consulta realizada às", now)])
        return TelegramView("\n".join(lines), keyboard([
            button("🔄 Tentar novamente", retry_callback, "primary"), _home_button()
        ]))

    def chamada(self, item: dict, *, now: datetime) -> str:
        """Botão de chamada do posto, no mesmo formato dos avisos automáticos."""

        lines = _header("📣", "Chamada do posto")
        station = _station_lines(item)
        if station:
            lines.extend([*station, ""])
        contato = _first(item, "contato_nome")
        if contato:
            funcao = _first(item, "contato_funcao")
            lines.append(
                f"Para: <b>{html(contato)}</b>"
                + (f" ({html(funcao)})" if funcao else "")
            )
        lines.append(
            f"Motivo: <b>{html(_first(item, 'motivo') or 'Não informado')}</b>"
        )
        comentario = _first(item, "comentario")
        if comentario:
            lines.append(f"Comentário: {html(comentario)}")
        lines.append(f"Solicitado por: {html(_chamada_solicitante(item))}")
        lines.extend(["", *_timestamp_lines(now)])
        return "\n".join(lines)

    def resource_stop(self, item: dict, *, now: datetime) -> str:
        """Parada de recurso registrada no posto, avisada no chat mestre."""

        lines = _header("🔴", "Parada registrada")
        station = _station_lines(item)
        if station:
            lines.extend([*station, ""])
        lines.append(
            f"🔧 Motivo: <b>{html(_first(item, 'motivo', 'motivo_parada') or 'Não informado')}</b>"
        )
        comentario = _first(item, "comentario", "comment")
        if comentario:
            lines.append(f"Comentário: {html(comentario)}")
        operador = _first(item, "operador", "operador_inicio", "operator")
        if operador:
            lines.append(f"Operador: {html(operador)}")
        lines.extend(["", *_timestamp_lines(now)])
        return "\n".join(lines)

    def totvs_outbox_error(self, item: dict) -> str:
        context = item.get("payload_context") or {}
        delivery_class = item.get("delivery_class") or item.get("last_delivery_class")
        error_code = item.get("error_code") or item.get("last_error_code")
        functional = (
            str(delivery_class or "").casefold() == "functional"
            or str(error_code or "").casefold() == "ack_funcional_error"
        )
        now = item.get("last_attempt_at") or item.get("updated_at") or datetime.now()
        if not isinstance(now, datetime):
            now = datetime.now()
        op_context = {
            **context,
            "production_order": item.get("production_order"),
            "resource": item.get("resource") or item.get("resource_code") or context.get("resource_code"),
        }
        reason = html(
            str(item.get("error_message") or item.get("last_error_message") or "").strip()
            or "Retorno não informado."
        )
        if functional:
            lines = _header("⚠️", "Apontamento rejeitado pelo TOTVS")
            lines.extend([
                *_op_lines(op_context), "",
                "🔴 <b>Rejeição funcional</b>", "",
                "O TOTVS recebeu a solicitação, mas não aceitou o apontamento.", "",
                "<b>Retorno</b>", reason, "", _footer("Ocorrido às", now),
            ])
        else:
            lines = _header("🔴", "TOTVS indisponível")
            lines.extend([
                *_op_lines(op_context), "",
                "🔗 Não foi possível concluir a comunicação com o Protheus.",
                "🟡 As tentativas automáticas se esgotaram; o evento permanece registrado para tratamento.",
                "", _footer("Última tentativa às", now),
            ])
        return "\n".join(lines)


__all__ = [
    "FRONTS", "TelegramPresenter", "TelegramView", "button", "format_duration",
    "format_number", "format_percent", "html", "keyboard",
]
