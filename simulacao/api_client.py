"""Cliente HTTP instrumentado da simulação.

Cada posto simulado possui a própria sessão — cookie de sessão, cookie CSRF e
jar independentes — porque é assim que a fábrica real funciona: um terminal por
posto. Todo apontamento passa por aqui; o simulador não possui um segundo
caminho para escrever no Gestor.

Toda chamada é medida e classificada. A classificação distingue três coisas que
não podem ser confundidas (seções 19 e 46):

* **recusa esperada** — o simulador provocou de propósito (crachá inválido,
  etapa concluída, recurso ocupado) e o Gestor recusou como deveria;
* **recusa legítima não prevista** — o Gestor recusou por uma regra válida que o
  roteiro do simulador não antecipou; vira ``EXPECTED_VALIDATION`` e alimenta o
  detector, nunca é silenciada;
* **defeito** — 5xx, timeout, contrato quebrado, resposta incoerente.
"""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from statistics import median
import time
from typing import Any, Iterable
import uuid

import httpx

from simulacao.telemetry import (
    EXPECTED_BLOCK,
    EXPECTED_VALIDATION,
    OK,
    REAL_ERROR,
    SEV_ERROR,
    SEV_EXPECTED,
    SEV_INFO,
    SEV_WARNING,
    TECHNICAL_ERROR,
    Telemetry,
)


API_PREFIX = "/api/v1"


@dataclass
class ApiResponse:
    status: int
    data: Any
    latency_ms: float
    endpoint: str
    method: str
    code: str = ""
    message: str = ""
    exception: str = ""
    correlation_id: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def falhou_no_transporte(self) -> bool:
        return self.status == 0


@dataclass
class ApiMetrics:
    """Janela deslizante de latência/erros usada pelo observatório (seção 21)."""

    window: deque = field(default_factory=lambda: deque(maxlen=4000))
    status_counter: Counter = field(default_factory=Counter)
    endpoint_latencies: dict = field(default_factory=lambda: defaultdict(list))
    timeouts: int = 0
    retries: int = 0
    total: int = 0

    def record(self, response: ApiResponse) -> None:
        self.total += 1
        family = "erro_transporte" if response.status == 0 else f"{response.status // 100}xx"
        self.status_counter[family] += 1
        self.status_counter[str(response.status)] += 1
        self.window.append((time.monotonic(), response.latency_ms, response.status))
        bucket = self.endpoint_latencies[f"{response.method} {response.endpoint}"]
        bucket.append(response.latency_ms)
        if len(bucket) > 600:
            del bucket[: len(bucket) - 600]

    def snapshot(self, *, janela_segundos: float = 30.0) -> dict:
        agora = time.monotonic()
        recentes = [item for item in self.window if agora - item[0] <= janela_segundos]
        latencias = sorted(item[1] for item in recentes)
        def pct(p: float) -> float:
            if not latencias:
                return 0.0
            index = min(len(latencias) - 1, max(0, int(round(p * (len(latencias) - 1)))))
            return round(latencias[index], 1)
        lentos = sorted(
            (
                (nome, round(median(valores), 1), len(valores))
                for nome, valores in self.endpoint_latencies.items()
                if valores
            ),
            key=lambda item: item[1],
            reverse=True,
        )[:8]
        return {
            "requests_total": self.total,
            "rps": round(len(recentes) / janela_segundos, 2) if recentes else 0.0,
            "p50_ms": pct(0.50),
            "p95_ms": pct(0.95),
            "p99_ms": pct(0.99),
            "max_ms": round(latencias[-1], 1) if latencias else 0.0,
            "2xx": self.status_counter.get("2xx", 0),
            "4xx": self.status_counter.get("4xx", 0),
            "5xx": self.status_counter.get("5xx", 0),
            "erro_transporte": self.status_counter.get("erro_transporte", 0),
            "timeouts": self.timeouts,
            "retries": self.retries,
            "endpoints_lentos": [
                {"endpoint": nome, "mediana_ms": mediana, "amostras": amostras}
                for nome, mediana, amostras in lentos
            ],
        }


class ApiSession:
    """Uma sessão autenticada. Não guarda senha depois do login."""

    def __init__(
        self,
        *,
        base_url: str,
        identity: str,
        telemetry: Telemetry,
        metrics: ApiMetrics,
        thresholds: dict,
        sector: str | None = None,
        resource: str | None = None,
        operator_badge: str | None = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.identity = identity
        self.sector = sector
        self.resource = resource
        self.operator_badge = operator_badge
        self._telemetry = telemetry
        self._metrics = metrics
        self._thresholds = thresholds
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout, connect=10.0),
            follow_redirects=False,
            headers={"User-Agent": "GestorSimulacaoIndustrial/1.0"},
        )
        self.session_user: dict | None = None

    # ------------------------------------------------------------------
    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def cookies(self) -> dict[str, str]:
        return {name: value for name, value in self._client.cookies.items()}

    @property
    def csrf_token(self) -> str:
        return self._client.cookies.get("gestor_csrf") or ""

    # ------------------------------------------------------------------
    async def login(self, username: str, password: str) -> ApiResponse:
        response = await self.call(
            "POST",
            "/auth/login",
            json={"username": username, "password": password},
            action="login",
            expect=(),
            sensitive=True,
        )
        if response.ok and isinstance(response.data, dict):
            self.session_user = response.data
        return response

    # ------------------------------------------------------------------
    async def call(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        action: str = "",
        op: str | None = None,
        expect: Iterable[str] = (),
        state_before: str | None = None,
        state_after: str | None = None,
        sensitive: bool = False,
        retries: int = 1,
        registrar: bool = True,
        raw: bool = False,
    ) -> ApiResponse:
        """Executa uma chamada, mede, classifica e registra.

        ``expect`` lista os códigos de negócio que o simulador provocou de
        propósito nesta chamada. Só eles viram ``EXPECTED_BLOCK``.
        ``raw`` pede o caminho exato, fora do prefixo ``/api/v1`` — é como o
        pre-flight confere que o SPA TESTE está sendo servido pela própria API.
        """

        endpoint = path if path.startswith("/") else f"/{path}"
        url = endpoint if (raw or endpoint.startswith("/api/")) else f"{API_PREFIX}{endpoint}"
        headers = {"X-Request-ID": str(uuid.uuid4())}
        if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            token = self.csrf_token
            if token:
                headers["X-CSRF-Token"] = token

        tentativa = 0
        while True:
            tentativa += 1
            started = time.perf_counter()
            try:
                raw = await self._client.request(
                    method.upper(), url, json=json, params=params, headers=headers
                )
                latency = (time.perf_counter() - started) * 1000.0
                payload = self._parse(raw)
                code, message = self._business_error(payload)
                response = ApiResponse(
                    status=raw.status_code,
                    data=payload,
                    latency_ms=latency,
                    endpoint=endpoint,
                    method=method.upper(),
                    code=code,
                    message=message,
                    correlation_id=raw.headers.get("X-Request-ID", headers["X-Request-ID"]),
                )
                break
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                latency = (time.perf_counter() - started) * 1000.0
                if isinstance(exc, httpx.TimeoutException):
                    self._metrics.timeouts += 1
                if tentativa <= retries:
                    # Seção 37 — reexecução controlada de falha transitória.
                    self._metrics.retries += 1
                    await asyncio.sleep(0.4 * tentativa)
                    continue
                response = ApiResponse(
                    status=0,
                    data=None,
                    latency_ms=latency,
                    endpoint=endpoint,
                    method=method.upper(),
                    code="transporte_indisponivel",
                    message=str(exc)[:300],
                    exception=type(exc).__name__,
                    correlation_id=headers["X-Request-ID"],
                )
                break

        self._metrics.record(response)
        if registrar:
            classification, severity = self._classify(response, expect)
            self._telemetry.registrar_evento(
                operator=self.operator_badge or self.identity,
                resource=self.resource,
                sector=self.sector,
                op=op,
                action=action or f"{method.upper()} {endpoint}",
                endpoint=endpoint,
                http_status=response.status,
                latency_ms=response.latency_ms,
                result="ok" if response.ok else (response.code or "falha"),
                state_before=state_before,
                state_after=state_after,
                classification=classification,
                severity=severity,
                error_code=response.code or None,
                exception=response.exception or None,
                correlation_id=response.correlation_id,
                details=None if sensitive else self._detalhes(response),
            )
        return response

    # ------------------------------------------------------------------
    @staticmethod
    def _parse(raw: httpx.Response) -> Any:
        if raw.status_code == 204 or not raw.content:
            return None
        if "application/json" not in (raw.headers.get("content-type") or ""):
            return raw.text[:2000]
        try:
            return raw.json()
        except ValueError:
            return raw.text[:2000]

    @staticmethod
    def _corpo_do_erro(payload: Any) -> dict:
        """Localiza o objeto de erro em qualquer um dos formatos da API.

        ``backend/api/errors`` devolve o erro **plano**
        (``{"code", "message", "request_id", "details"}``); o endpoint do
        relógio de simulação usa ``HTTPException(detail={"error": {...}})``.
        Os dois precisam render o mesmo ``code``, senão o simulador não
        distingue uma recusa que ele provocou de uma que não previu.
        """

        atual: Any = payload
        for _ in range(4):
            if not isinstance(atual, dict):
                return {}
            if "code" in atual:
                return atual
            proximo = atual.get("error")
            if not isinstance(proximo, dict):
                proximo = atual.get("detail")
            if not isinstance(proximo, dict):
                return {}
            atual = proximo
        return {}

    @classmethod
    def _business_error(cls, payload: Any) -> tuple[str, str]:
        erro = cls._corpo_do_erro(payload)
        return str(erro.get("code") or ""), str(erro.get("message") or "")

    @staticmethod
    def _detalhes(response: ApiResponse) -> dict:
        if response.ok:
            data = response.data
            if isinstance(data, dict):
                resumo = {
                    key: data[key]
                    for key in ("ok", "message", "code")
                    if key in data
                }
                return resumo or {"tipo": "payload", "chaves": sorted(data)[:12]}
            return {}
        erro = ApiSession._corpo_do_erro(response.data)
        if erro:
            return {
                "code": erro.get("code"),
                "message": erro.get("message"),
                "details": erro.get("details"),
            }
        return {"body": response.data}

    def _classify(self, response: ApiResponse, expect: Iterable[str]) -> tuple[str, str]:
        esperados = {str(code).strip() for code in expect if str(code).strip()}
        if response.status == 0:
            return TECHNICAL_ERROR, SEV_ERROR
        if response.status >= 500:
            return TECHNICAL_ERROR, SEV_ERROR
        if response.ok:
            limite_erro = float(self._thresholds.get("latencia_error_ms", 3000))
            limite_aviso = float(self._thresholds.get("latencia_warning_ms", 1000))
            if response.latency_ms >= limite_erro:
                return OK, SEV_ERROR
            if response.latency_ms >= limite_aviso:
                return OK, SEV_WARNING
            return OK, SEV_INFO
        if response.status in {401, 403, 409, 422, 404, 400, 503}:
            if response.code and response.code in esperados:
                return EXPECTED_BLOCK, SEV_EXPECTED
            # Recusa legítima que o roteiro não previu: continua sendo uma
            # decisão do Gestor, e não um defeito — mas fica visível.
            return EXPECTED_VALIDATION, SEV_WARNING
        return REAL_ERROR, SEV_ERROR


class SessionFactory:
    """Cria e mantém as sessões, compartilhando métricas e telemetria."""

    def __init__(self, *, base_url: str, telemetry: Telemetry, thresholds: dict):
        self.base_url = base_url
        self.telemetry = telemetry
        self.thresholds = thresholds
        self.metrics = ApiMetrics()
        self._sessions: list[ApiSession] = []

    def build(self, **kwargs) -> ApiSession:
        session = ApiSession(
            base_url=self.base_url,
            telemetry=self.telemetry,
            metrics=self.metrics,
            thresholds=self.thresholds,
            **kwargs,
        )
        self._sessions.append(session)
        return session

    async def aclose(self) -> None:
        for session in self._sessions:
            try:
                await session.aclose()
            except Exception:  # pragma: no cover
                pass
        self._sessions.clear()
