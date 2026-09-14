"""Observatório da simulação e viewports reais dos operadores (seções 25-28).

O viewport **não é mock**: cada operador ganha um proxy de leitura na própria
porta, e esse proxy serve a aplicação TESTE inteira — mesmo SPA, mesmas rotas,
mesmos componentes, mesma API — injetando do lado servidor o cookie da sessão
daquele operador. O navegador nunca recebe cookie de sessão, e por isso é
possível ver 24 postos diferentes ao mesmo tempo, o que um único cookie
``gestor_session`` jamais permitiria.

Duas garantias estruturais:

* **observação é passiva (seção 27).** O proxy só encaminha ``GET``/``HEAD``;
  qualquer método que escreva é recusado com 405 antes de sair do observatório.
  Olhar um posto não pode apontar nada nem travar a fábrica.
* **sem alterar o backend.** ``X-Frame-Options``/``frame-ancestors`` são
  reescritos apenas na resposta que passa pelo proxy, para o iframe funcionar.
  A API TESTE continua com a política original dela.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
from typing import Callable

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route


HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-encoding",
    "content-length",
}


# ---------------------------------------------------------------------------
# Viewport: um proxy somente leitura por operador
# ---------------------------------------------------------------------------
@dataclass
class ViewportAlvo:
    posto_id: str
    nome: str
    porta: int
    cookies: dict[str, str]
    recurso: str = ""


#: Único ponto em que o proxy toca o corpo da resposta.
#:
#: A tela do operador escolhe o posto por estado local do React — não existe
#: parâmetro de rota para isso. Sem o ajuste, o observador veria eternamente a
#: grade "Selecione o recurso" em vez da bancada que o operador simulado está
#: usando. A resposta continua sendo a do Gestor: apenas a lista de recursos do
#: setor é restringida ao posto observado, e o backend continua validando o
#: recurso por conta própria (``validate_resource``) em toda chamada.
CONTEXTO_DO_OPERADOR = "/api/v1/operator/context"


def montar_viewport(alvo: ViewportAlvo, api_base: str, observatorio_origem: str) -> Starlette:
    cliente = httpx.AsyncClient(
        base_url=api_base.rstrip("/"),
        timeout=httpx.Timeout(60.0, connect=10.0, read=None),
        follow_redirects=False,
    )

    async def encaminhar(request: Request) -> Response:
        if request.method.upper() not in {"GET", "HEAD"}:
            return JSONResponse(
                {
                    "error": {
                        "code": "viewport_somente_leitura",
                        "message": (
                            "Este viewport é uma janela de observação. "
                            "Apontamentos só acontecem pelos operadores simulados."
                        ),
                    }
                },
                status_code=405,
            )
        caminho = request.url.path
        # ``accept-encoding`` é removido de propósito: sem compressão upstream o
        # corpo atravessa o proxy byte a byte, sem risco de o navegador receber
        # bytes comprimidos sem o cabeçalho que os descreve. Em loopback a
        # compressão não compra nada.
        cabecalhos = {
            nome: valor
            for nome, valor in request.headers.items()
            if nome.lower()
            not in HOP_BY_HOP | {"host", "cookie", "origin", "referer", "accept-encoding"}
        }
        cabecalhos["accept-encoding"] = "identity"
        cabecalhos["cookie"] = "; ".join(
            f"{nome}={valor}" for nome, valor in alvo.cookies.items()
        )
        pedido = cliente.build_request(
            request.method,
            caminho,
            params=dict(request.query_params),
            headers=cabecalhos,
        )
        try:
            resposta = await cliente.send(pedido, stream=True)
        except httpx.HTTPError as exc:
            return PlainTextResponse(
                f"Viewport indisponível: {type(exc).__name__}", status_code=502
            )

        saida = {
            nome: valor
            for nome, valor in resposta.headers.items()
            if nome.lower() not in HOP_BY_HOP | {"set-cookie", "x-frame-options"}
        }
        # O iframe do observatório precisa de permissão explícita de moldura.
        saida["content-security-policy"] = f"frame-ancestors {observatorio_origem}"
        saida["x-simulacao-viewport"] = alvo.posto_id
        # O bundle do Vite chega com ``immutable`` de um ano. Como a porta do
        # viewport é reaproveitada entre execuções, uma resposta ruim de uma
        # execução anterior ficaria grudada no navegador por um ano inteiro —
        # e apareceria como "tela em branco" que não existe no servidor. Janela
        # de observação não guarda cache.
        saida["cache-control"] = "no-store"
        saida.pop("etag", None)
        saida.pop("last-modified", None)

        if caminho == CONTEXTO_DO_OPERADOR and alvo.recurso:
            try:
                corpo_bruto = await resposta.aread()
            finally:
                await resposta.aclose()
            try:
                contexto = json.loads(corpo_bruto)
            except (ValueError, UnicodeDecodeError):
                return Response(
                    corpo_bruto, status_code=resposta.status_code, headers=saida,
                    media_type=resposta.headers.get("content-type"),
                )
            if isinstance(contexto, dict) and alvo.recurso in (contexto.get("resources") or []):
                contexto["resources"] = [alvo.recurso]
                contexto["fixed_resource"] = True
                contexto["observacao_simulacao"] = alvo.posto_id
            return JSONResponse(contexto, status_code=resposta.status_code, headers=saida)

        async def corpo():
            # ``aiter_bytes`` entrega o corpo já decodificado; como
            # ``content-encoding``/``content-length`` saíram dos cabeçalhos, a
            # resposta vai em chunked e o navegador lê exatamente o que a API
            # produziu — inclusive nos fluxos SSE, que não terminam.
            try:
                async for pedaco in resposta.aiter_bytes():
                    yield pedaco
            finally:
                await resposta.aclose()

        return StreamingResponse(
            corpo(),
            status_code=resposta.status_code,
            headers=saida,
            media_type=resposta.headers.get("content-type"),
        )

    @asynccontextmanager
    async def ciclo_de_vida(_app: Starlette):
        try:
            yield
        finally:
            await cliente.aclose()

    app = Starlette(
        routes=[Route("/{caminho:path}", encaminhar, methods=["GET", "HEAD", "POST", "DELETE"])],
        lifespan=ciclo_de_vida,
    )
    app.state.alvo = alvo
    return app


# ---------------------------------------------------------------------------
# Observatório
# ---------------------------------------------------------------------------
def montar_observatorio(provedor_estado: Callable[[], dict], pagina: Callable[[], str]) -> Starlette:
    async def raiz(_request: Request) -> Response:
        return RedirectResponse("/simulation-observatory")

    async def observatorio(_request: Request) -> Response:
        return HTMLResponse(pagina())

    async def estado(_request: Request) -> Response:
        return JSONResponse(json.loads(json.dumps(provedor_estado(), default=str)))

    return Starlette(
        routes=[
            Route("/", raiz),
            Route("/simulation-observatory", observatorio),
            Route("/api/state", estado),
        ]
    )


class ServidorObservatorio:
    """Sobe o observatório e todos os viewports em um único event loop."""

    def __init__(
        self,
        *,
        observatory_port: int,
        api_base: str,
        provedor_estado: Callable[[], dict],
        pagina: Callable[[], str],
    ):
        self.observatory_port = observatory_port
        self.api_base = api_base
        self.provedor_estado = provedor_estado
        self.pagina = pagina
        self._servidores: list[uvicorn.Server] = []
        self._tarefas: list[asyncio.Task] = []
        self.viewports: list[ViewportAlvo] = []

    @property
    def origem(self) -> str:
        return f"http://127.0.0.1:{self.observatory_port}"

    def registrar_viewport(self, alvo: ViewportAlvo) -> None:
        self.viewports.append(alvo)

    async def iniciar(self) -> None:
        principal = montar_observatorio(self.provedor_estado, self.pagina)
        self._subir(principal, self.observatory_port)
        for alvo in self.viewports:
            self._subir(montar_viewport(alvo, self.api_base, self.origem), alvo.porta)
        # Dá tempo dos sockets abrirem antes do primeiro acesso.
        await asyncio.sleep(0.8)

    def _subir(self, app: Starlette, porta: int) -> None:
        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=porta,
            log_level="warning",
            access_log=False,
            lifespan="on",
        )
        servidor = uvicorn.Server(config)
        servidor.install_signal_handlers = lambda: None  # type: ignore[assignment]
        self._servidores.append(servidor)
        self._tarefas.append(asyncio.create_task(servidor.serve(), name=f"observatorio-{porta}"))

    async def encerrar(self) -> None:
        for servidor in self._servidores:
            servidor.should_exit = True
        for tarefa in self._tarefas:
            try:
                await asyncio.wait_for(tarefa, timeout=8)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                tarefa.cancel()
            except Exception:
                pass
        self._servidores.clear()
        self._tarefas.clear()


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------
PAGINA = """<!doctype html>
<html lang="pt-BR"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Observatório da Simulação Industrial</title>
<style>
  :root{
    --fundo:#0d1117; --painel:#161b22; --borda:#30363d; --texto:#e6edf3;
    --suave:#8b949e; --ok:#3fb950; --aviso:#d29922; --erro:#f85149; --critico:#ff7b72;
    --acento:#58a6ff; --parada:#d29922; --producao:#3fb950; --ocioso:#484f58;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--fundo);color:var(--texto);
       font:13px/1.45 "Segoe UI",system-ui,sans-serif}
  header{position:sticky;top:0;z-index:20;background:#0d1117f2;backdrop-filter:blur(6px);
         border-bottom:1px solid var(--borda);padding:10px 16px}
  .relogios{display:flex;gap:22px;flex-wrap:wrap;align-items:baseline}
  .relogios b{font-size:22px;font-variant-numeric:tabular-nums}
  .rotulo{color:var(--suave);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
  .barra{height:6px;background:#21262d;border-radius:3px;margin-top:8px;overflow:hidden}
  .barra span{display:block;height:100%;background:linear-gradient(90deg,#1f6feb,#58a6ff)}
  main{padding:16px;display:grid;gap:16px}
  .grade{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
  .painel{background:var(--painel);border:1px solid var(--borda);border-radius:8px;padding:12px}
  .painel h2{margin:0 0 8px;font-size:12px;text-transform:uppercase;letter-spacing:.07em;
             color:var(--suave);font-weight:600}
  .numeros{display:grid;grid-template-columns:repeat(auto-fit,minmax(88px,1fr));gap:8px}
  .numero{background:#0d1117;border:1px solid var(--borda);border-radius:6px;padding:8px}
  .numero b{display:block;font-size:19px;font-variant-numeric:tabular-nums}
  .numero span{color:var(--suave);font-size:10.5px;text-transform:uppercase}
  table{width:100%;border-collapse:collapse;font-size:12px}
  th,td{text-align:left;padding:4px 6px;border-bottom:1px solid #21262d}
  th{color:var(--suave);font-weight:600;font-size:10.5px;text-transform:uppercase}
  .postos{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(330px,1fr))}
  .posto{background:var(--painel);border:1px solid var(--borda);border-radius:8px;overflow:hidden;
         display:flex;flex-direction:column}
  .posto.ampliado{grid-column:1/-1}
  .posto header{position:static;background:none;border:0;border-bottom:1px solid var(--borda);
                padding:8px 10px;cursor:pointer;display:flex;justify-content:space-between;gap:8px}
  .posto h3{margin:0;font-size:12.5px}
  .posto .meta{color:var(--suave);font-size:11px;margin-top:2px}
  .pill{border-radius:999px;padding:2px 8px;font-size:10.5px;white-space:nowrap;align-self:flex-start}
  .p-producao{background:#12341f;color:var(--producao)}
  .p-parada{background:#3a2c06;color:var(--parada)}
  .p-setup{background:#1c2b4a;color:var(--acento)}
  .p-inspecao{background:#132f33;color:#56d4dd}
  .p-retrabalho{background:#3d1f0a;color:#ffa657}
  .p-bloqueado{background:#42161a;color:var(--erro)}
  .p-ocioso,.p-sem_op,.p-fora_do_turno,.p-abrindo,.p-encerrado{background:#21262d;color:var(--suave)}
  .moldura{position:relative;background:#010409;border-top:1px solid var(--borda)}
  .moldura iframe{width:100%;height:320px;border:0;display:block;background:#fff}
  .posto.ampliado .moldura iframe{height:720px}
  .vazio{height:320px;display:flex;align-items:center;justify-content:center;color:var(--suave);
         font-size:12px;text-align:center;padding:14px}
  .aviso-viewport{position:absolute;right:8px;top:8px;background:#0d1117cc;border:1px solid var(--borda);
                  border-radius:4px;padding:2px 7px;font-size:10px;color:var(--suave)}
  .lista{max-height:260px;overflow:auto}
  .sev-INFO{color:var(--suave)} .sev-WARNING{color:var(--aviso)}
  .sev-ERROR{color:var(--erro)} .sev-CRITICAL{color:var(--critico);font-weight:600}
  .sev-EXPECTED_BLOCK{color:var(--acento)}
  .acoes{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  button{background:#21262d;color:var(--texto);border:1px solid var(--borda);border-radius:6px;
         padding:5px 10px;cursor:pointer;font-size:12px}
  button:hover{border-color:var(--acento)}
  code{background:#0d1117;padding:1px 4px;border-radius:3px;font-size:11px}
</style></head><body>
<header>
  <div class="relogios">
    <div><span class="rotulo">Tempo real</span><br><b id="real">--:--:--</b></div>
    <div><span class="rotulo">Tempo virtual (fábrica)</span><br><b id="virtual">--:--:--</b></div>
    <div><span class="rotulo">Velocidade</span><br><b id="escala">--</b></div>
    <div><span class="rotulo">Seed</span><br><b id="seed">--</b></div>
    <div><span class="rotulo">Fase</span><br><b id="fase">--</b></div>
    <div><span class="rotulo">Estado</span><br><b id="estado">--</b></div>
    <div><span class="rotulo">Restante</span><br><b id="restante">--</b></div>
    <div class="acoes">
      <button id="alternar">Pausar viewports</button>
      <button id="recolher">Recolher todos</button>
    </div>
  </div>
  <div class="barra"><span id="progresso" style="width:0%"></span></div>
</header>
<main>
  <section class="grade">
    <div class="painel"><h2>Fábrica</h2><div class="numeros" id="fabrica"></div></div>
    <div class="painel"><h2>Performance da API</h2><div class="numeros" id="performance"></div></div>
    <div class="painel"><h2>PostgreSQL</h2><div class="numeros" id="banco"></div></div>
    <div class="painel"><h2>Processos</h2><div class="numeros" id="processos"></div></div>
  </section>

  <section class="painel"><h2>Setores</h2>
    <table><thead><tr><th>Setor</th><th>Postos</th><th>Produzindo</th><th>Parados</th>
    <th>Ociosos</th><th>Finalizados</th><th>Parciais</th><th>Retrab.</th><th>Refugo</th>
    <th>Bloqueios esperados</th></tr></thead><tbody id="setores"></tbody></table>
  </section>

  <section>
    <h2 style="font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:#8b949e">
      Operadores — telas reais (clique no cabeçalho para ampliar)</h2>
    <div class="postos" id="postos"></div>
  </section>

  <section class="grade">
    <div class="painel"><h2>Eventos recentes</h2><div class="lista"><table id="eventos"></table></div></div>
    <div class="painel"><h2>Bloqueios esperados</h2><div class="lista"><table id="bloqueios"></table></div></div>
    <div class="painel"><h2>Erros e inconsistências</h2><div class="lista"><table id="erros"></table></div></div>
    <div class="painel"><h2>Alertas</h2><div class="lista"><table id="alertas"></table></div></div>
  </section>
</main>
<script>
const montados = new Set();
const ampliados = new Set();
let viewportsAtivos = true;

function texto(valor, padrao='—'){ return (valor===null||valor===undefined||valor==='')?padrao:valor; }
function hora(iso){ return iso ? String(iso).slice(11,19) : '--:--:--'; }
function numero(rotulo, valor){
  return `<div class="numero"><b>${texto(valor,'0')}</b><span>${rotulo}</span></div>`;
}

function desenharPostos(postos){
  const container = document.getElementById('postos');
  for(const posto of postos){
    let card = document.getElementById('posto-'+posto.id);
    if(!card){
      card = document.createElement('article');
      card.className = 'posto';
      card.id = 'posto-'+posto.id;
      card.innerHTML = `
        <header data-id="${posto.id}">
          <div><h3>${posto.nome}</h3>
            <div class="meta" id="meta-${posto.id}"></div></div>
          <span class="pill" id="pill-${posto.id}"></span>
        </header>
        <div class="moldura" id="moldura-${posto.id}">
          <div class="vazio">Viewport pausado — a fábrica continua rodando.</div>
        </div>`;
      card.querySelector('header').addEventListener('click', () => {
        if(ampliados.has(posto.id)){ ampliados.delete(posto.id); card.classList.remove('ampliado'); }
        else { ampliados.add(posto.id); card.classList.add('ampliado'); }
      });
      container.appendChild(card);
    }
    document.getElementById('meta-'+posto.id).innerHTML =
      `${posto.setor} · ${posto.recurso} · crachá <code>${posto.cracha}</code><br>` +
      `OP ${texto(posto.op)} · ${texto(posto.produto)} · ${texto(posto.operacao)}<br>` +
      `${texto(posto.acao_atual)} · há ${texto(posto.tempo_no_estado,'00:00:00')}` +
      (posto.proxima_acao ? ` · a seguir: ${posto.proxima_acao}` : '');
    const pill = document.getElementById('pill-'+posto.id);
    pill.textContent = posto.estado;
    pill.className = 'pill p-'+posto.estado;

    const moldura = document.getElementById('moldura-'+posto.id);
    if(viewportsAtivos && posto.viewport_port && !montados.has(posto.id)){
      montados.add(posto.id);
      moldura.innerHTML =
        `<span class="aviso-viewport">tela real · somente leitura</span>
         <iframe loading="lazy" title="${posto.nome}"
                 src="http://127.0.0.1:${posto.viewport_port}/operador"></iframe>`;
    }
    if(!viewportsAtivos && montados.has(posto.id)){
      montados.delete(posto.id);
      moldura.innerHTML = '<div class="vazio">Viewport pausado — a fábrica continua rodando.</div>';
    }
  }
}

function linhas(alvo, dados, colunas){
  const tabela = document.getElementById(alvo);
  tabela.innerHTML = dados.map(item =>
    `<tr class="sev-${texto(item.severity||item.severidade,'INFO')}">` +
    colunas.map(coluna => `<td>${texto(item[coluna])}</td>`).join('') + '</tr>'
  ).join('') || '<tr><td>sem registros</td></tr>';
}

async function atualizar(){
  let estado;
  try { estado = await (await fetch('/api/state', {cache:'no-store'})).json(); }
  catch(erro){ document.getElementById('estado').textContent = 'observatório sem dados'; return; }

  document.getElementById('real').textContent = hora(estado.relogio.real);
  document.getElementById('virtual').textContent =
    String(estado.relogio.virtual||'').replace('T',' ').slice(0,19);
  document.getElementById('escala').textContent = estado.relogio.escala + '×';
  document.getElementById('seed').textContent = estado.config.seed;
  document.getElementById('fase').textContent = estado.fase;
  document.getElementById('estado').textContent = estado.estado;
  document.getElementById('restante').textContent = estado.relogio.restante_real;
  document.getElementById('progresso').style.width = (estado.relogio.progresso*100).toFixed(1)+'%';

  const f = estado.fabrica;
  document.getElementById('fabrica').innerHTML =
    numero('postos', f.postos) + numero('produzindo', f.produzindo) + numero('parados', f.parados) +
    numero('setup', f.setup) + numero('inspeção', f.inspecao) +
    numero('retrabalho', f.retrabalho) + numero('ociosos', f.ociosos) +
    numero('OPs ativas', f.ops_ativas) + numero('OPs finalizadas', f.ops_finalizadas) +
    numero('fila', f.fila) + numero('parciais (WIP)', f.parciais) +
    numero('refugo', f.refugos) + numero('bloqueios', f.bloqueios_esperados);

  const p = estado.performance || {};
  document.getElementById('performance').innerHTML =
    numero('requests', p.requests_total) + numero('rps', p.rps) + numero('p50 ms', p.p50_ms) +
    numero('p95 ms', p.p95_ms) + numero('p99 ms', p.p99_ms) + numero('2xx', p['2xx']) +
    numero('4xx', p['4xx']) + numero('5xx', p['5xx']) + numero('timeouts', p.timeouts) +
    numero('retries', p.retries);

  const b = estado.banco || {};
  const c = b.conexoes || {}; const e = b.estatisticas || {}; const l = b.locks || {};
  document.getElementById('banco').innerHTML =
    numero('conexões', c.conexoes) + numero('ativas', c.ativas) + numero('idle', c.idle) +
    numero('idle in tx', c.idle_in_transaction) + numero('locks', l.total) +
    numero('locks retidos', l.nao_concedidos) + numero('deadlocks', e.deadlocks) +
    numero('rollbacks', e.xact_rollback) +
    numero('cache hit', b.cache_hit_ratio ? (b.cache_hit_ratio*100).toFixed(1)+'%' : '—') +
    numero('queries lentas', (b.queries_lentas||[]).length);

  const pr = estado.processos || {};
  document.getElementById('processos').innerHTML =
    numero('API RSS MB', (pr.api||{}).rss_mb) + numero('API threads', (pr.api||{}).threads) +
    numero('API conexões', (pr.api||{}).conexoes) +
    numero('Sim RSS MB', (pr.simulador||{}).rss_mb) +
    numero('Sim threads', (pr.simulador||{}).threads) +
    numero('deriva relógio s', estado.relogio.deriva_segundos);

  document.getElementById('setores').innerHTML = estado.setores.map(s =>
    `<tr><td>${s.setor}</td><td>${s.postos}</td><td>${s.produzindo}</td><td>${s.parados}</td>
     <td>${s.ociosos}</td><td>${s.finalizados}</td><td>${s.parciais}</td><td>${s.retrabalhos}</td>
     <td>${s.refugos}</td><td>${s.bloqueios}</td></tr>`).join('');

  desenharPostos(estado.postos);
  linhas('eventos', estado.eventos, ['simulation_timestamp','operator','resource','action','http_status','result']);
  linhas('bloqueios', estado.bloqueios, ['simulation_timestamp','operator','action','error_code','result']);
  linhas('erros', estado.erros, ['simulation_timestamp','operator','action','error_code','result']);
  linhas('alertas', estado.alertas, ['severidade','titulo']);
}

document.getElementById('alternar').addEventListener('click', (evento) => {
  viewportsAtivos = !viewportsAtivos;
  evento.target.textContent = viewportsAtivos ? 'Pausar viewports' : 'Retomar viewports';
});
document.getElementById('recolher').addEventListener('click', () => {
  ampliados.clear();
  document.querySelectorAll('.posto.ampliado').forEach(no => no.classList.remove('ampliado'));
});
atualizar();
setInterval(atualizar, 2000);
</script></body></html>
"""


def pagina_observatorio() -> str:
    return PAGINA
