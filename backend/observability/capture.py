"""Ponte entre o ciclo HTTP e o gravador do Dev Observatory.

A captura não cria um caminho paralelo de tratamento de erro. Ela se pendura em
dois pontos que já existem e já são os únicos por onde tudo passa:

* ``backend.api.errors.register_error_handlers`` — funil único de ``AppError``,
  ``ReportError``, validação, ``DatabaseError``, ``HTTPException`` e do handler
  genérico de ``Exception``. É lá que se sabe o código de negócio e se o erro
  foi previsto;
* o middleware ``request_context`` de ``backend.api.main`` — onde o ``X-Request-ID``
  já é emitido. É lá que se mede a latência.

Observar nunca pode derrubar um request: toda falha aqui é engolida.
"""

from __future__ import annotations

import logging
import traceback as traceback_module

from starlette.requests import Request


STATE_KEY = "dev_observatory"
DEV_ROUTE_PREFIX = "/api/v1/dev-observatory"
MAX_TRACEBACK_CHARS = 6_000


def get_recorder(request: Request):
    return getattr(request.app.state, "dev_observatory", None)


def mark_error(
    request: Request,
    *,
    code: str | None,
    message: str | None,
    unhandled: bool = False,
    exception: BaseException | None = None,
) -> None:
    """Anota no request o que o funil de erros acabou de decidir."""

    try:
        payload = {
            "error_code": code,
            "error_message": message,
            "unhandled": bool(unhandled),
            "exception": type(exception).__name__ if exception is not None else None,
            "traceback": _format_traceback(exception) if unhandled and exception else None,
        }
        request.state.dev_observatory = payload
    except Exception:  # pragma: no cover - observar não pode falhar o request
        logging.debug("Dev Observatory: falha ao marcar erro", exc_info=True)


def record_response(request: Request, response, elapsed_ms: float) -> None:
    """Registra a requisição concluída, com o que o funil de erros marcou."""

    recorder = get_recorder(request)
    if recorder is None:
        return
    try:
        path = request.url.path
        if not path.startswith("/api/"):
            return
        route = _route_template(request, path)
        status = int(getattr(response, "status_code", 0) or 0)
        if route.startswith(DEV_ROUTE_PREFIX) and status < 400:
            # O próprio observatório faz polling; medir o observador como se
            # fosse tráfego de operador distorceria o retrato do turno.
            return
        marked = getattr(request.state, STATE_KEY, None) or {}
        claims = getattr(request.state, "session_claims", None)
        recorder.record_request(
            method=request.method,
            path=path,
            route=route,
            status=status,
            latency_ms=elapsed_ms,
            request_id=getattr(request.state, "request_id", None),
            user=getattr(claims, "username", None),
            role=None,
            error_code=marked.get("error_code"),
            error_message=marked.get("error_message"),
            unhandled=bool(marked.get("unhandled")),
            exception=marked.get("exception"),
            traceback_text=marked.get("traceback"),
        )
    except Exception:  # pragma: no cover - observar não pode falhar o request
        logging.debug("Dev Observatory: falha ao registrar requisição", exc_info=True)


def record_exception(request: Request, exception: BaseException, elapsed_ms: float) -> None:
    """Captura a exceção que escapou do roteador.

    O handler genérico de ``Exception`` do FastAPI vive no
    ``ServerErrorMiddleware``, que é a camada **mais externa** da aplicação —
    fora do middleware onde a latência é medida. Sem este gancho, justamente o
    caso mais importante (500 não previsto) passaria despercebido. O erro é
    apenas registrado; quem responde continua sendo o handler original.
    """

    recorder = get_recorder(request)
    if recorder is None:
        return
    try:
        path = request.url.path
        if not path.startswith("/api/"):
            return
        claims = getattr(request.state, "session_claims", None)
        recorder.record_request(
            method=request.method,
            path=path,
            route=_route_template(request, path),
            status=500,
            latency_ms=elapsed_ms,
            request_id=getattr(request.state, "request_id", None),
            user=getattr(claims, "username", None),
            error_code="internal_error",
            error_message=str(exception),
            unhandled=True,
            exception=type(exception).__name__,
            traceback_text=_format_traceback(exception),
        )
    except Exception:  # pragma: no cover - observar não pode falhar o request
        logging.debug("Dev Observatory: falha ao registrar exceção", exc_info=True)


def _route_template(request: Request, fallback: str) -> str:
    """Template da rota, com o prefixo real da aplicação.

    ``scope['route'].path`` traz o caminho como registrado no ``APIRouter``,
    sem o prefixo aplicado por ``include_router``. Sem a reconstrução, o
    agregado por rota apareceria como ``/management/...`` enquanto o caminho
    real é ``/api/v1/management/...``.
    """

    route = request.scope.get("route")
    template = str(getattr(route, "path", "") or "")
    if not template or template == "/":
        return fallback
    template_segments = template.strip("/").split("/")
    path_segments = fallback.strip("/").split("/")
    if len(path_segments) < len(template_segments):
        return template
    # Um parâmetro de rota nunca contém "/", então contar segmentos basta para
    # descobrir onde o template começa dentro do caminho real.
    prefix = "/".join(path_segments[: len(path_segments) - len(template_segments)])
    return f"/{prefix}{template}" if prefix else template


def _format_traceback(exception: BaseException) -> str:
    text = "".join(
        traceback_module.format_exception(type(exception), exception, exception.__traceback__)
    )
    if len(text) > MAX_TRACEBACK_CHARS:
        return text[-MAX_TRACEBACK_CHARS:]
    return text
