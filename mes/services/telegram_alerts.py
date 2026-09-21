"""Chat mestre de alerta: botão de chamada e parada de recurso.

O chat mestre é ``chamada_telegram_chat_id`` — o mesmo destino que o botão de
chamada já usa quando o contato não tem Telegram próprio. A parada de recurso
entra aqui por decisão do usuário (21/09/2026): o supervisor precisa saber na
hora, no mesmo lugar onde já recebe as chamadas, sem depender de alguém abrir
o Andon.

Nada neste módulo pode derrubar o fluxo produtivo: quando ele roda, o fato
industrial já está persistido. Indisponibilidade do canal vira log e ``False``,
nunca exceção — mesma regra já adotada pelo aviso de Corte e pela outbox TOTVS.

O envio sai **depois** da resposta HTTP, via ``BackgroundTasks``: o posto
confirma a parada ou a chamada na hora e o Telegram (que pode levar até
``DEFAULT_TIMEOUT_SECONDS``) acontece por trás. O ``Database`` da API é um
singleton com pool próprio, não um recurso por request, então continua válido
quando a tarefa roda.
"""

from __future__ import annotations

from datetime import datetime
import logging

from mes.integrations.notifications.telegram import send_telegram_message
from mes.services.telegram_presenter import TelegramPresenter


LOGGER = logging.getLogger(__name__)


def master_chat(settings) -> tuple[str, str]:
    """``(bot_token, chat_id)`` do chat mestre; strings vazias quando faltar."""

    token = str(getattr(settings, "telegram_bot_token", "") or "").strip()
    chat_id = str(getattr(settings, "chamada_telegram_chat_id", "") or "").strip()
    return token, chat_id


def station_context(database, *, setor, recurso) -> dict:
    """OP/peça em andamento no posto, para dar contexto ao aviso da chamada.

    A tela do operador não precisa (nem deve) informar OP e peça no corpo da
    chamada: o apontamento ativo do posto é a fonte da verdade. Sem nada ativo,
    devolve apenas máquina e setor — o aviso sai sem as linhas de OP.
    """

    contexto = {"maquina": str(recurso or "").strip(), "setor": str(setor or "").strip()}
    loader = getattr(database, "listar_apontamentos_operacionais", None)
    if not contexto["maquina"] or not contexto["setor"] or not callable(loader):
        return contexto
    try:
        # A consulta já ordena "Em processo" primeiro; a primeira linha é o que
        # o posto está executando agora.
        ativo = next(iter(loader(contexto["setor"], contexto["maquina"]) or ()), None)
    except Exception:  # pragma: no cover - contexto extra nunca bloqueia a chamada
        LOGGER.exception("Falha ao buscar o apontamento ativo de %s.", contexto["maquina"])
        return contexto
    if not ativo:
        return contexto
    for campo in ("op", "numero_operacao", "produto_codigo", "produto_descricao", "peca"):
        valor = ativo.get(campo)
        if valor is not None and str(valor).strip():
            contexto[campo] = valor
    return contexto


def _send(settings, text_builder, *, erro: str) -> bool:
    token, chat_id = master_chat(settings)
    if not token or not chat_id:
        return False
    try:
        return send_telegram_message(
            bot_token=token, chat_id=chat_id, text=text_builder(), parse_mode="HTML"
        )
    except Exception:  # pragma: no cover - canal indisponível não é erro do posto
        LOGGER.exception(erro)
        return False


def alert_resource_stop(settings, dados: dict, *, ocorrido_em=None) -> bool:
    """Avisa o chat mestre que um recurso acabou de parar.

    ``dados`` é a linha que o próprio fluxo já devolveu — apontamento
    operacional, estado físico do recurso ou fila do Corte. O apresentador lê
    os apelidos equivalentes; nenhuma tela precisa montar um formato próprio.
    """

    dados = dict(dados or {})
    # O Corte devolve o estado físico aninhado na linha da fila; achatar aqui
    # evita que cada tela monte o dicionário do aviso do seu jeito.
    estado = dados.pop("estado_recurso", None)
    if isinstance(estado, dict):
        dados.update({chave: valor for chave, valor in estado.items() if valor is not None})
    # ``data_inicio`` da linha não serve de carimbo: no apontamento com OP ela
    # é o início da operação, não o instante da parada. O aviso sai logo depois
    # do fato, então o relógio de agora é o horário correto em todos os fluxos.
    momento = ocorrido_em if isinstance(ocorrido_em, datetime) else datetime.now()
    return _send(
        settings,
        lambda: TelegramPresenter().resource_stop(dados, now=momento),
        erro="Falha ao avisar a parada de recurso no Telegram.",
    )


def schedule_resource_stop_alert(background, settings, dados: dict, *, ocorrido_em=None) -> bool:
    """Agenda o aviso de parada para depois da resposta ao posto.

    Devolve se houve o que agendar: sem chat mestre configurado nada é
    enfileirado, e o horário é congelado agora para o carimbo não escorregar
    até a tarefa rodar.
    """

    token, chat_id = master_chat(settings)
    if not token or not chat_id or background is None:
        return False
    background.add_task(
        alert_resource_stop,
        settings,
        dict(dados or {}),
        ocorrido_em=ocorrido_em if isinstance(ocorrido_em, datetime) else datetime.now(),
    )
    return True


def deliver_chamada(database, chamada_id, *, bot_token: str, chat_id: str, texto: str) -> bool:
    """Entrega a chamada e registra o desfecho na própria linha da chamada.

    Roda fora do request: quem chamou já recebeu a confirmação. O resultado
    real do envio fica em ``chamadas.telegram_enviado``/``telegram_erro``, que
    é o que a tela de histórico mostra.
    """

    enviado = False
    try:
        enviado = send_telegram_message(
            bot_token=bot_token, chat_id=chat_id, text=texto, parse_mode="HTML"
        )
    except Exception:  # pragma: no cover - canal indisponível não é erro do posto
        LOGGER.exception("Falha ao enviar a chamada %s no Telegram.", chamada_id)
    try:
        database.marcar_chamada_telegram(
            chamada_id,
            enviado=enviado,
            erro=None if enviado else "Falha ao enviar o aviso pelo Telegram.",
        )
    except Exception:  # pragma: no cover - a chamada já está registrada
        LOGGER.exception("Falha ao registrar o desfecho do Telegram da chamada %s.", chamada_id)
    return enviado


__all__ = [
    "alert_resource_stop",
    "deliver_chamada",
    "master_chat",
    "schedule_resource_stop_alert",
    "station_context",
]
