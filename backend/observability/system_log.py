"""Log do sistema: um registro por evento relevante, separado por área.

Duas fontes alimentam o mesmo funil:

* **requisições HTTP** — toda ação que muda estado (``POST``/``PUT``/``PATCH``/
  ``DELETE``), todo erro (status >= 400) e toda resposta lenta. ``GET`` de
  polling que deu certo (Andon, timeline) não entra: seria milhares de linhas
  por minuto sem informação nova. O corpo da requisição nunca é gravado.
* **logging do Python** — avisos e erros de qualquer parte do sistema
  (Protheus, SigmaNEST, Telegram, IA, turnos, banco), classificados pela origem.

A gravação é em fila + thread própria, em lote: observar nunca atrasa nem
derruba a requisição, e se o banco estiver fora o lote é descartado.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
import logging
import threading
from typing import Any, Callable

from backend.api.request_context import REQUEST_ID
from backend.observability.classification import sanitize

#: slug -> rótulo exibido. A ordem é a dos filtros na tela.
AREAS: dict[str, str] = {
    "acesso": "Acesso e contas",
    "operador": "Operador",
    "corte": "Corte",
    "qualidade": "Qualidade",
    "manutencao": "Manutenção",
    "gestao": "Gestão",
    "diretoria": "Diretoria",
    "andon": "Andon",
    "protheus": "Protheus",
    "sigmanest": "SigmaNEST",
    "telegram": "Telegram",
    "ia": "IA",
    "relatorios": "Relatórios",
    "banco": "Banco de dados",
    "sistema": "Sistema",
}

# Prefixo do caminho (depois de /api/v1/) -> área.
_AREA_POR_ROTA = (
    ("auth", "acesso"),
    ("operator", "operador"),
    ("operations", "operador"),
    ("areas", "operador"),
    ("highlight", "operador"),
    ("cutting", "corte"),
    ("quality", "qualidade"),
    ("traceability", "qualidade"),
    ("maintenance", "manutencao"),
    ("management", "gestao"),
    ("chamadas", "gestao"),
    ("analytics", "gestao"),
    ("audit", "gestao"),
    ("director", "diretoria"),
    ("andon", "andon"),
    ("admin/totvs-outbox", "protheus"),
    ("order-consultation", "protheus"),
    ("orders", "protheus"),
    ("ai", "ia"),
    ("reports", "relatorios"),
    ("system", "sistema"),
)

# Prefixo do logger (módulo Python) e, na falta, palavra na mensagem -> área.
_AREA_POR_LOGGER = (
    ("mes.integrations.totvs", "protheus"),
    ("mes.services.totvs", "protheus"),
    ("app.database.totvs", "protheus"),
    ("backend.integrations.totvs", "protheus"),
    ("mes.integrations.sigmanest", "sigmanest"),
    ("mes.services.sigmanest", "sigmanest"),
    ("app.database.sigmanest", "sigmanest"),
    ("mes.services.telegram", "telegram"),
    ("mes.services.internal_alert", "telegram"),
    ("mes.integrations.notifications", "telegram"),
    ("backend.messaging", "telegram"),
    ("backend.ai", "ia"),
    ("mes.ai", "ia"),
    ("mes.services.ai_tools", "ia"),
    ("mes.services.report", "relatorios"),
    ("mes.services.industrial_reports", "relatorios"),
    ("app.database", "banco"),
)
_AREA_POR_PALAVRA = (
    ("protheus", "protheus"), ("totvs", "protheus"),
    ("sigmanest", "sigmanest"),
    ("telegram", "telegram"),
    ("groq", "ia"), ("ia industrial", "ia"),
    ("turno", "gestao"), ("pausa", "gestao"),
    ("postgres", "banco"), ("banco", "banco"), ("pool", "banco"),
)

# Loggers de bibliotecas barulhentas; só erros delas interessam.
_RUIDOSOS = ("uvicorn.access", "httpx", "httpcore", "asyncio", "psycopg", "urllib3", "multipart")
_PROPRIO = "backend.observability.system_log"
_THREAD = "system-log-writer"

SLOW_MS = 3000.0
RETENCAO_DIAS = 30
MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def area_da_rota(path: str) -> str:
    resto = path.split("/api/v1/", 1)[-1].strip("/")
    for prefixo, area in _AREA_POR_ROTA:
        if resto == prefixo or resto.startswith(prefixo + "/"):
            return area
    return "sistema"


def area_do_logger(nome: str, mensagem: str = "") -> str:
    for prefixo, area in _AREA_POR_LOGGER:
        if nome.startswith(prefixo):
            return area
    texto = mensagem.lower()
    for palavra, area in _AREA_POR_PALAVRA:
        if palavra in texto:
            return area
    return "sistema"


def nivel_do_status(status: int) -> str:
    return "erro" if status >= 500 else "aviso" if status >= 400 else "info"


class SystemLog:
    def __init__(self, database_provider: Callable[[], Any], *, now: Callable[[], datetime] = datetime.now,
                 retention_days: int = RETENCAO_DIAS, max_queue: int = 5000, batch: int = 200):
        self._database_provider = database_provider
        self._now = now
        self._retention = timedelta(days=retention_days)
        self._queue: deque = deque(maxlen=max_queue)
        self._batch = batch
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_purge: datetime | None = None
        self._handler: logging.Handler | None = None

    # -- ciclo de vida -------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=_THREAD, daemon=True)
        self._thread.start()
        self._handler = _Handler(self)
        logging.getLogger().addHandler(self._handler)
        self.record("sistema", "info", "api_iniciada", "API iniciada.")

    def stop(self) -> None:
        if self._handler is not None:
            logging.getLogger().removeHandler(self._handler)
            self._handler = None
        if self._thread is None:
            return
        self.record("sistema", "info", "api_encerrada", "API encerrada.")
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=5)
        self._thread = None

    # -- entrada -------------------------------------------------------
    def record(self, area: str, nivel: str, evento: str, mensagem: str, *, usuario: str | None = None,
               request_id: str | None = None, metodo: str | None = None, rota: str | None = None,
               status_http: int | None = None, duracao_ms: float | None = None,
               detalhe: dict | None = None) -> None:
        try:
            self._queue.append({
                "quando": self._now(), "area": area if area in AREAS else "sistema",
                "nivel": nivel, "evento": evento[:80], "mensagem": mensagem[:2000],
                "usuario": usuario, "request_id": request_id, "metodo": metodo, "rota": rota,
                "status_http": status_http,
                "duracao_ms": None if duracao_ms is None else round(float(duracao_ms), 1),
                "detalhe": sanitize(detalhe) if detalhe else None,
            })
            self._wake.set()
        except Exception:  # observar nunca derruba quem é observado
            pass

    def record_http(self, request, status: int, elapsed_ms: float, marked: dict | None = None) -> None:
        path = request.url.path
        if not path.startswith("/api/") or "/dev-observatory" in path:
            return
        method = request.method
        if status < 400 and method not in MUTATING and elapsed_ms < SLOW_MS:
            return
        if status == 401 and method == "GET":
            return  # sessão vencida no polling: ruído, não evento
        claims = getattr(request.state, "session_claims", None)
        route = request.scope.get("route")
        template = str(getattr(route, "path", "") or path)
        marked = marked or {}
        area = area_da_rota(path)
        evento = f"http_{method.lower()}"
        if area == "acesso" and path.endswith("/login"):
            evento = "login" if status < 400 else "login_recusado"
        elif area == "acesso" and path.endswith("/logout"):
            evento = "logout"
        nivel = nivel_do_status(status)
        if nivel == "info" and elapsed_ms >= SLOW_MS and method not in MUTATING:
            nivel, evento = "aviso", "resposta_lenta"
        texto = f"{method} {path} → {status} ({elapsed_ms:.0f} ms)"
        if marked.get("error_message"):
            texto += f" — {marked['error_message']}"
        self.record(
            area, nivel, evento, texto,
            usuario=getattr(claims, "username", None),
            request_id=getattr(request.state, "request_id", None),
            metodo=method, rota=template, status_http=status, duracao_ms=elapsed_ms,
            detalhe={k: marked.get(k) for k in ("error_code", "exception") if marked.get(k)} or None,
        )

    # -- gravação ------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=2.0)
            self._wake.clear()
            self.flush()
        self.flush()

    def flush(self) -> int:
        lote = []
        while self._queue and len(lote) < self._batch:
            try:
                lote.append(self._queue.popleft())
            except IndexError:
                break
        if not lote:
            return 0
        try:
            database = self._database_provider()
            gravadas = database.gravar_log_lote(lote)
            self._purge_if_due(database)
            if self._queue:
                self._wake.set()
            return gravadas
        except Exception:
            logging.getLogger(_PROPRIO).debug("Log do sistema: lote descartado", exc_info=True)
            return 0

    def _purge_if_due(self, database) -> None:
        agora = self._now()
        if self._last_purge is not None and agora - self._last_purge < timedelta(hours=6):
            return
        self._last_purge = agora
        database.limpar_log(antes_de=agora - self._retention)


class _Handler(logging.Handler):
    """Leva avisos/erros do ``logging`` (de qualquer módulo) para o log do sistema."""

    def __init__(self, target: SystemLog):
        super().__init__(level=logging.INFO)
        self._target = target

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.name.startswith(_PROPRIO) or threading.current_thread().name == _THREAD:
                return
            if record.name.startswith(_RUIDOSOS) and record.levelno < logging.ERROR:
                return
            mensagem = record.getMessage()
            area = area_do_logger(record.name, mensagem)
            # INFO só das integrações e serviços em segundo plano; o resto do
            # INFO é conversa interna, não evento.
            if record.levelno < logging.WARNING and area in ("sistema", "banco", "gestao"):
                return
            detalhe = {"logger": record.name}
            if record.exc_info and record.exc_info[0] is not None:
                detalhe["exception"] = record.exc_info[0].__name__
            nivel = "info" if record.levelno < logging.WARNING else (
                "aviso" if record.levelno < logging.ERROR else "erro"
            )
            self._target.record(
                area, nivel, "log_aplicacao", mensagem,
                request_id=REQUEST_ID.get(), detalhe=detalhe,
            )
        except Exception:
            pass
