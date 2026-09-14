"""Captura visual seletiva e caça a defeitos de interface (seções 29 e 30).

Um único Chrome headless fica vivo durante a execução e abre uma aba por
captura. A captura acontece **em evento relevante**, nunca em laço contínuo —
a seção 29 pede evidência, não filme, e a seção 42 proíbe o simulador virar o
gargalo.

Cada captura também executa uma auditoria de DOM na própria página do
operador. A auditoria procura apenas o que é observável e objetivo (texto
cortado, overflow, loading preso, tela em branco, erro técnico visível, modal
sem saída). Preferência estética não vira defeito.
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

import websockets


CHROME_CANDIDATOS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)

AUDITORIA_JS = r"""
(() => {
  const corpo = document.body;
  const texto = corpo ? (corpo.innerText || "") : "";
  const problemas = [];
  const limpo = texto.trim();
  if (/Carregando dados|Preparando o posto|Carregando fila|Verificando sess/i.test(texto)) {
    problemas.push("loading_visivel");
  }
  if (limpo.length < 40) problemas.push("conteudo_em_branco");
  if (/Traceback|TypeError|is not a function|NetworkError|Failed to fetch|500 Internal|Unexpected token/i.test(texto)) {
    problemas.push("erro_tecnico_visivel");
  }
  if (document.documentElement.scrollWidth > window.innerWidth + 4) {
    problemas.push("overflow_horizontal");
  }
  let foraDaTela = 0, cortados = 0, botoesInvisiveis = 0;
  const alvos = Array.prototype.slice.call(
    document.querySelectorAll("button, a, h1, h2, h3, td, th, label, .pill, .card, span"), 0, 800);
  for (const elemento of alvos) {
    const caixa = elemento.getBoundingClientRect();
    if (caixa.width === 0 && caixa.height === 0) continue;
    if (caixa.right > window.innerWidth + 6 || caixa.left < -6) foraDaTela += 1;
    const estilo = getComputedStyle(elemento);
    if (elemento.scrollWidth > elemento.clientWidth + 3 &&
        (estilo.overflow === "hidden" || estilo.overflowX === "hidden") &&
        estilo.textOverflow !== "ellipsis") {
      cortados += 1;
    }
    if (elemento.tagName === "BUTTON" && caixa.height > 0 &&
        (estilo.visibility === "hidden" || parseFloat(estilo.opacity || "1") < 0.15)) {
      botoesInvisiveis += 1;
    }
  }
  if (foraDaTela > 0) problemas.push("elemento_fora_da_tela");
  if (cortados > 0) problemas.push("texto_cortado");
  if (botoesInvisiveis > 0) problemas.push("botao_inacessivel");
  const modais = Array.prototype.slice.call(
    document.querySelectorAll('[role="dialog"], dialog[open], .modal, .dialog'));
  const semSaida = modais.filter(m => m.querySelectorAll("button").length === 0).length;
  if (semSaida > 0) problemas.push("modal_sem_fechamento");
  return {
    titulo: document.title,
    url: location.href,
    problemas: problemas,
    fora_da_tela: foraDaTela,
    textos_cortados: cortados,
    botoes_invisiveis: botoesInvisiveis,
    modais: modais.length,
    modais_sem_saida: semSaida,
    tamanho_texto: limpo.length,
    amostra: limpo.slice(0, 700)
  };
})()
"""


@dataclass
class ResultadoCaptura:
    arquivo: str | None
    auditoria: dict
    erro: str | None = None


@dataclass
class ChromeCDP:
    """Cliente CDP mínimo: o bastante para navegar, auditar e capturar."""

    largura: int = 1500
    altura: int = 940
    _processo: subprocess.Popen | None = None
    _perfil: str | None = None
    _ws: Any = None
    _tarefa: asyncio.Task | None = None
    _pendentes: dict = field(default_factory=dict)
    _sequencia: int = 0
    disponivel: bool = False
    motivo_indisponivel: str = ""

    # ------------------------------------------------------------------
    def _executavel(self) -> str | None:
        for caminho in CHROME_CANDIDATOS:
            if Path(caminho).is_file():
                return caminho
        return shutil.which("chrome") or shutil.which("msedge")

    async def iniciar(self) -> bool:
        executavel = self._executavel()
        if not executavel:
            self.motivo_indisponivel = "Chrome/Edge headless não encontrado nesta estação."
            return False
        self._perfil = tempfile.mkdtemp(prefix="gestor-simulacao-captura-")
        self._processo = subprocess.Popen(
            [
                executavel,
                "--headless=new",
                "--disable-gpu",
                "--hide-scrollbars",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                "--disable-background-timer-throttling",
                "--remote-debugging-port=0",
                f"--user-data-dir={self._perfil}",
                f"--window-size={self.largura},{self.altura}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        porta = await self._porta_devtools()
        if porta is None:
            self.motivo_indisponivel = "Chrome não publicou a porta de depuração."
            await self.encerrar()
            return False
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as cliente:
                versao = (await cliente.get(f"http://127.0.0.1:{porta}/json/version")).json()
            self._ws = await websockets.connect(
                versao["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024, ping_interval=None
            )
        except Exception as exc:
            self.motivo_indisponivel = f"Falha ao conectar no CDP: {type(exc).__name__}"
            await self.encerrar()
            return False
        self._tarefa = asyncio.create_task(self._ouvir(), name="cdp-listener")
        self.disponivel = True
        return True

    async def _porta_devtools(self) -> int | None:
        arquivo = Path(self._perfil or "") / "DevToolsActivePort"
        for _ in range(120):
            if arquivo.is_file():
                try:
                    conteudo = arquivo.read_text(encoding="utf-8").splitlines()
                    if conteudo and conteudo[0].strip().isdigit():
                        return int(conteudo[0].strip())
                except OSError:
                    pass
            await asyncio.sleep(0.1)
        return None

    async def _ouvir(self) -> None:
        try:
            async for bruto in self._ws:
                mensagem = json.loads(bruto)
                identificador = mensagem.get("id")
                if identificador is None:
                    continue
                futuro = self._pendentes.pop(identificador, None)
                if futuro is None or futuro.done():
                    continue
                if "error" in mensagem:
                    futuro.set_exception(RuntimeError(str(mensagem["error"])))
                else:
                    futuro.set_result(mensagem.get("result") or {})
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def _enviar(self, metodo: str, parametros: dict | None = None,
                      sessao: str | None = None, timeout: float = 25.0) -> dict:
        self._sequencia += 1
        identificador = self._sequencia
        futuro: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pendentes[identificador] = futuro
        pacote = {"id": identificador, "method": metodo, "params": parametros or {}}
        if sessao:
            pacote["sessionId"] = sessao
        await self._ws.send(json.dumps(pacote))
        return await asyncio.wait_for(futuro, timeout=timeout)

    # ------------------------------------------------------------------
    async def capturar(
        self, url: str, destino: Path, *, espera_ms: int = 2600
    ) -> ResultadoCaptura:
        if not self.disponivel:
            return ResultadoCaptura(None, {}, self.motivo_indisponivel or "captura indisponível")
        alvo = None
        try:
            alvo = (await self._enviar("Target.createTarget", {"url": "about:blank"}))["targetId"]
            sessao = (
                await self._enviar(
                    "Target.attachToTarget", {"targetId": alvo, "flatten": True}
                )
            )["sessionId"]
            await self._enviar("Page.enable", sessao=sessao)
            await self._enviar("Runtime.enable", sessao=sessao)
            await self._enviar(
                "Emulation.setDeviceMetricsOverride",
                {"width": self.largura, "height": self.altura,
                 "deviceScaleFactor": 1, "mobile": False},
                sessao=sessao,
            )
            await self._enviar("Page.navigate", {"url": url}, sessao=sessao)
            await asyncio.sleep(espera_ms / 1000.0)
            avaliacao = await self._enviar(
                "Runtime.evaluate",
                {"expression": AUDITORIA_JS, "returnByValue": True, "awaitPromise": False},
                sessao=sessao,
            )
            auditoria = (avaliacao.get("result") or {}).get("value") or {}
            imagem = await self._enviar(
                "Page.captureScreenshot",
                {"format": "png", "fromSurface": True, "captureBeyondViewport": False},
                sessao=sessao,
            )
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(base64.b64decode(imagem["data"]))
            return ResultadoCaptura(str(destino), auditoria)
        except Exception as exc:
            return ResultadoCaptura(None, {}, f"{type(exc).__name__}: {exc}")
        finally:
            if alvo:
                try:
                    await self._enviar("Target.closeTarget", {"targetId": alvo}, timeout=8)
                except Exception:
                    pass

    async def encerrar(self) -> None:
        self.disponivel = False
        if self._tarefa is not None:
            self._tarefa.cancel()
            try:
                await self._tarefa
            except (asyncio.CancelledError, Exception):
                pass
            self._tarefa = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._processo is not None and self._processo.poll() is None:
            self._processo.terminate()
            try:
                self._processo.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self._processo.kill()
        self._processo = None
        if self._perfil:
            shutil.rmtree(self._perfil, ignore_errors=True)
            self._perfil = None
