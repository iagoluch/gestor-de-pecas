/* Dev Observatory — cliente da página.
 *
 * Não calcula indicador e não reimplementa regra: só desenha o que a API
 * devolve. Todo POST carrega o mesmo cabeçalho CSRF que o SPA usa.
 */
"use strict";

const BASE = "/api/v1/dev-observatory";

const estado = {
  ambiente: "test",
  intervalo: 10000,
  timer: null,
  relatorioAberto: null,
  ultimaLeitura: {},
};

function $(id) {
  return document.getElementById(id);
}

function texto(valor, padrao) {
  if (valor === null || valor === undefined || valor === "") return padrao === undefined ? "—" : padrao;
  return String(valor);
}

function escapar(valor) {
  return texto(valor).replace(/[&<>"]/g, (caractere) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  })[caractere]);
}

function hora(iso) {
  return iso ? String(iso).slice(11, 19) : "--:--:--";
}

function duracao(segundos) {
  if (segundos === null || segundos === undefined) return "—";
  const total = Math.max(0, Math.round(Number(segundos)));
  const h = String(Math.floor(total / 3600)).padStart(2, "0");
  const m = String(Math.floor((total % 3600) / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function cookie(nome) {
  const item = document.cookie
    .split(";")
    .map((parte) => parte.trim())
    .find((parte) => parte.startsWith(`${nome}=`));
  return item ? decodeURIComponent(item.slice(nome.length + 1)) : undefined;
}

function avisar(mensagem) {
  const caixa = $("aviso");
  if (!mensagem) {
    caixa.hidden = true;
    return;
  }
  caixa.textContent = mensagem;
  caixa.hidden = false;
  window.clearTimeout(avisar._timer);
  avisar._timer = window.setTimeout(() => {
    caixa.hidden = true;
  }, 8000);
}

/**
 * Mostra (ou limpa) a falha de um bloco dentro dos painéis que ele alimenta,
 * mantendo os últimos valores na tela, esmaecidos (DO-02). O toast `avisar`
 * fica só para o retorno de ações disparadas pelo usuário.
 */
function situacaoBloco(bloco, ids, erro) {
  if (!erro) estado.ultimaLeitura[bloco] = new Date().toLocaleTimeString("pt-BR");
  const ultima = estado.ultimaLeitura[bloco];
  ids.forEach((id) => {
    const painel = $(id).closest(".painel, section");
    let faixa = painel.querySelector(":scope > .falha");
    if (!erro) {
      if (faixa) faixa.remove();
      return;
    }
    if (!faixa) {
      faixa = document.createElement("p");
      faixa.className = "falha";
      faixa.setAttribute("role", "status");
      painel.querySelector("h2").after(faixa);
    }
    faixa.textContent = `Indisponível agora: ${erro.message.replace(/\.$/, "")}. ` +
      (ultima ? `Mostrando a última leitura, das ${ultima}.` : "Ainda sem leitura nesta sessão.");
  });
}

function blocoMonitorado(bloco, ids, promessa) {
  return promessa.then(
    () => situacaoBloco(bloco, ids, null),
    (erro) => situacaoBloco(bloco, ids, erro),
  );
}

async function pedir(caminho, opcoes) {
  const config = Object.assign({ credentials: "include", headers: {} }, opcoes || {});
  const metodo = (config.method || "GET").toUpperCase();
  if (metodo !== "GET") {
    config.headers["Content-Type"] = "application/json";
    const csrf = cookie("gestor_csrf");
    if (csrf) config.headers["X-CSRF-Token"] = csrf;
  }
  const resposta = await fetch(BASE + caminho, config);
  const tipo = resposta.headers.get("content-type") || "";
  if (!resposta.ok) {
    let mensagem = `${resposta.status} em ${caminho}`;
    if (tipo.includes("application/json")) {
      const corpo = await resposta.json().catch(() => null);
      if (corpo && corpo.message) mensagem = corpo.message;
    }
    throw new Error(mensagem);
  }
  if (tipo.includes("application/json")) return resposta.json();
  return resposta.text();
}

function numero(rotulo, valor, classe) {
  return `<div class="numero ${classe || ""}"><b>${escapar(valor)}</b><span>${escapar(rotulo)}</span></div>`;
}

function tabela(colunas, linhas, vazio) {
  if (!linhas.length) {
    return `<tbody><tr><td class="vazio">${escapar(vazio)}</td></tr></tbody>`;
  }
  const cabecalho = colunas.map((coluna) => `<th>${escapar(coluna)}</th>`).join("");
  return `<thead><tr>${cabecalho}</tr></thead><tbody>${linhas.join("")}</tbody>`;
}

// ---------------------------------------------------------------------------
// Status e faixa de segurança
// ---------------------------------------------------------------------------
function desenharStatus(dados) {
  $("relogio").textContent = hora(dados.generated_at);
  $("turno").textContent = dados.current_shift ? dados.current_shift.label : "fora de turno";

  const real = dados.environments.real || {};
  const faixa = $("faixa-seguranca");
  if (!real.configured) {
    faixa.className = "faixa";
    faixa.textContent = `REAL não configurado — ${texto(real.reason)}`;
  } else if (!real.available) {
    faixa.className = "faixa erro";
    faixa.textContent = `REAL indisponível — ${texto(real.reason)}`;
  } else {
    const prova = real.read_only || {};
    faixa.className = "faixa ok";
    faixa.textContent =
      `REAL '${texto(prova.database)}' aberto como ${texto(prova.user)} · ` +
      `transaction_read_only=${texto(prova.transaction_read_only)} · ` +
      `gravação ${texto(prova.write_probe)} · ` +
      `o observatório não escreve em banco algum (persistência só em disco).`;
  }

  const resumo = dados.summary || {};
  const classificacoes = resumo.classifications || {};
  const defeitos = Number(resumo.defects || 0);
  $("num-api").innerHTML = [
    numero("requisições", resumo.requests || 0),
    numero("defeitos", defeitos, defeitos ? "ruim" : "bom"),
    numero("erros reais", classificacoes.REAL_ERROR || 0, classificacoes.REAL_ERROR ? "ruim" : ""),
    numero("técnicos", classificacoes.TECHNICAL_ERROR || 0, classificacoes.TECHNICAL_ERROR ? "ruim" : ""),
    numero("bloqueios esperados", resumo.expected_blocks || 0),
    numero("validações", classificacoes.EXPECTED_VALIDATION || 0),
  ].join("");
}

// ---------------------------------------------------------------------------
// Métricas
// ---------------------------------------------------------------------------
function desenharMetricas(dados) {
  const pg = dados.postgres || {};
  const conexoes = pg.connections || {};
  const estatisticas = pg.statistics || {};
  const locks = pg.locks || {};
  $("banco-alvo").textContent = `${texto((pg.target || {}).dbname)} · ${dados.environment === "real" ? "somente leitura" : "pool da API"}`;
  $("num-banco").innerHTML = [
    numero("conexões", conexoes.conexoes || 0),
    numero("ativas", conexoes.ativas || 0),
    numero("idle in tx", conexoes.idle_in_transaction || 0, Number(conexoes.idle_in_transaction || 0) >= 2 ? "alerta" : ""),
    numero("deadlocks", estatisticas.deadlocks || 0, Number(estatisticas.deadlocks || 0) > 0 ? "ruim" : ""),
    numero("locks aguardando", locks.nao_concedidos || 0, Number(locks.nao_concedidos || 0) > 0 ? "alerta" : ""),
    numero("cache hit", pg.cache_hit_ratio === null || pg.cache_hit_ratio === undefined ? "—" : `${(pg.cache_hit_ratio * 100).toFixed(1)}%`),
    numero("query ativa + longa", `${Number(conexoes.query_ativa_mais_longa_s || 0).toFixed(1)}s`,
      Number(conexoes.query_ativa_mais_longa_s || 0) > 5 ? "alerta" : ""),
    numero("tamanho", `${(Number(estatisticas.tamanho_bytes || 0) / (1024 * 1024)).toFixed(0)} MB`),
  ].join("");

  const processo = dados.process || {};
  const sistema = processo.system || {};
  $("num-processo").innerHTML = processo.available
    ? [
        numero("RSS", `${processo.rss_mb} MB`),
        numero("threads", processo.threads),
        numero("CPU proc.", `${Number(processo.cpu_percent || 0).toFixed(0)}%`),
        numero("conexões TCP", texto(processo.connections)),
        numero("mem. livre", `${Number(sistema.memory_available_mb || 0).toFixed(0)} MB`),
        numero("CPU sistema", `${Number(sistema.cpu_percent || 0).toFixed(0)}%`),
      ].join("")
    : `<div class="vazio">${escapar(processo.reason || "Indisponível")}</div>`;

  const lentas = (dados.api && dados.api.slowest_routes) || [];
  const linhasLentas = lentas.map(
    (linha) =>
      `<tr><td><code>${escapar(linha.method)} ${escapar(linha.route)}</code></td>` +
      `<td class="num">${escapar(linha.count)}</td>` +
      `<td class="num">${escapar(linha.p95_ms)}</td>` +
      `<td class="num">${escapar(linha.max_ms)}</td></tr>`
  );
  const queries = (pg.slow_queries || []).map(
    (linha) =>
      `<tr><td colspan="2"><code>${escapar(linha.query)}</code><div class="meta">pid ${escapar(linha.pid)} · ${escapar(linha.application_name)}</div></td>` +
      `<td class="num">${Number(linha.duracao_s || 0).toFixed(1)}s</td><td class="num">${escapar(linha.wait_event || "—")}</td></tr>`
  );
  $("lentidao").innerHTML = tabela(
    ["Rota / consulta", "Chamadas", "p95 ms / duração", "máx ms / espera"],
    linhasLentas.concat(queries),
    "Sem rota lenta e sem consulta longa no minuto corrente."
  );
}

// ---------------------------------------------------------------------------
// Viewports dos postos
// ---------------------------------------------------------------------------
const CATEGORIA_ROTULO = {
  producao: "Produção",
  parada: "Parada",
  setup: "Setup",
  retrabalho: "Retrabalho",
  fila: "Fila",
  fora_turno: "Fora do turno",
  atividade_sem_op: "Atividade sem OP",
  desconhecido: "Desconhecido",
};

function desenharPostos(dados) {
  $("viewports-fonte").textContent = `${texto(dados.database)} · ${texto(dados.source)}`;
  const alvo = $("postos");
  const itens = dados.items || [];
  if (!itens.length) {
    alvo.innerHTML = '<div class="vazio">Nenhum posto com estado canônico registrado agora.</div>';
    return;
  }
  alvo.innerHTML = itens
    .map((item) => {
      const categoria = String(item.categoria || "desconhecido");
      const ops = item.ops_ativas || [];
      const op = ops[0] || {};
      const codigoOp = item.op_estado || op.op;
      return `
        <article class="posto">
          <div class="cabeca">
            <div>
              <h3>${escapar(item.recurso)}</h3>
              <div class="meta">${escapar(item.setor)} · desde ${hora(item.inicio)} (${duracao(item.duracao_segundos)})</div>
            </div>
            <span class="pill p-${escapar(categoria)}">${escapar(CATEGORIA_ROTULO[categoria] || categoria)}</span>
          </div>
          <dl>
            <dt>OP</dt><dd>${escapar(codigoOp)}${op.operacao ? ` · op ${escapar(op.operacao)}` : ""}</dd>
            <dt>Produto</dt><dd>${escapar(op.produto || item.produto_estado)}${op.descricao_produto ? ` — ${escapar(op.descricao_produto)}` : ""}</dd>
            <dt>Ação</dt><dd>${escapar(item.descricao_atividade || item.motivo || op.status || "—")}</dd>
            <dt>Operador</dt><dd>${escapar(item.operador_estado || op.operador_inicio)}</dd>
            <dt>Quantidades</dt><dd>boas ${escapar(op.quantidade_boa || 0)} · refugo ${escapar(op.refugo || 0)} · retrab. ${escapar(op.retrabalho || 0)} · plan. ${escapar(op.quantidade_planejada || "—")}</dd>
            <dt>OPs ativas</dt><dd>${escapar(item.quantidade_ops_ativas || 0)}</dd>
          </dl>
        </article>`;
    })
    .join("");
}

// ---------------------------------------------------------------------------
// Eventos
// ---------------------------------------------------------------------------
const CLASSES_DEFEITO = ["REAL_ERROR", "TECHNICAL_ERROR", "PERFORMANCE_ERROR"];

function linhaEvento(evento, comDetalhe) {
  const detalhe = comDetalhe
    ? `<div class="meta">${escapar(evento.error_message || evento.exception || "")}</div>` +
      (evento.traceback ? `<details><summary>stack trace</summary><pre class="markdown">${escapar(evento.traceback)}</pre></details>` : "")
    : "";
  return (
    `<tr><td>${hora(evento.timestamp)}</td>` +
    `<td><span class="cls cls-${escapar(evento.classification)}">${escapar(evento.classification)}</span></td>` +
    `<td><code>${escapar(evento.method)} ${escapar(evento.route)}</code>${detalhe}</td>` +
    `<td class="num">${escapar(evento.status)}</td>` +
    `<td>${escapar(evento.error_code)}</td></tr>`
  );
}

function desenharEventos(dados) {
  const itens = dados.items || [];
  const erros = itens.filter((item) => CLASSES_DEFEITO.includes(item.classification));
  const bloqueios = itens.filter((item) => item.classification === "EXPECTED_BLOCK");
  const resto = itens.filter(
    (item) => !CLASSES_DEFEITO.includes(item.classification) && item.classification !== "EXPECTED_BLOCK"
  );

  $("erros").innerHTML = tabela(
    ["Hora", "Classe", "Rota", "Status", "Código"],
    erros.map((item) => linhaEvento(item, true)),
    "Nenhum erro capturado desde o start da API."
  );
  $("bloqueios").innerHTML = tabela(
    ["Hora", "Classe", "Rota", "Status", "Código"],
    bloqueios.map((item) => linhaEvento(item, true)),
    "Nenhuma recusa de negócio capturada."
  );
  $("eventos").innerHTML = tabela(
    ["Hora", "Classe", "Rota", "Status", "Código"],
    resto.map((item) => linhaEvento(item, false)),
    "Nenhuma ação de escrita registrada ainda."
  );
}

// ---------------------------------------------------------------------------
// Turnos e relatórios
// ---------------------------------------------------------------------------
async function desenharTurnos() {
  const dados = await pedir("/shifts");
  $("turnos").innerHTML = dados.windows
    .map((janela) => {
      const rotulo = janela.report ? "Regerar relatório" : "Gerar relatório";
      return `
        <div class="turno ${janela.current ? "atual" : ""}">
          <b>${escapar(janela.label)}</b>
          <small>${escapar(janela.start.slice(11, 16))} → ${escapar(janela.end.slice(11, 16))} ·
            ${janela.closed ? "encerrado" : janela.current ? "em curso" : "ainda não começou"} ·
            ${janela.report ? "relatório gravado" : "sem relatório"}</small>
          <button type="button" data-turno="${escapar(janela.key)}" data-dia="${escapar(dados.day)}"
                  data-force="${janela.report ? "1" : "0"}">${rotulo}</button>
        </div>`;
    })
    .join("");
  for (const botao of $("turnos").querySelectorAll("button")) {
    botao.addEventListener("click", () => gerarRelatorio(botao));
  }
}

async function gerarRelatorio(botao) {
  botao.disabled = true;
  const rotuloOriginal = botao.textContent;
  botao.textContent = "Gerando…";
  try {
    const resposta = await pedir("/reports", {
      method: "POST",
      body: JSON.stringify({
        day: botao.dataset.dia,
        shift: botao.dataset.turno,
        force: botao.dataset.force === "1",
      }),
    });
    await desenharTurnos();
    await desenharRelatorios();
    await abrirRelatorio(resposta.name);
  } catch (erro) {
    avisar(erro.message);
    botao.disabled = false;
    botao.textContent = rotuloOriginal;
  }
}

async function desenharRelatorios() {
  const dados = await pedir("/reports");
  const linhas = dados.items.map((item) => {
    const resumo = item.summary || {};
    return (
      `<tr><td><a href="#" data-relatorio="${escapar(item.name)}">${escapar(item.name)}</a>` +
      `<div class="meta">${escapar(item.generated_at)}</div></td>` +
      `<td class="num">${escapar(resumo.defects === undefined ? "—" : resumo.defects)}</td>` +
      `<td class="num">${escapar(resumo.expected_blocks === undefined ? "—" : resumo.expected_blocks)}</td></tr>`
    );
  });
  $("relatorios").innerHTML = tabela(
    ["Relatório", "Defeitos", "Bloqueios"],
    linhas,
    `Nenhum relatório em ${escapar(dados.directory)}.`
  );
  for (const link of $("relatorios").querySelectorAll("a[data-relatorio]")) {
    link.addEventListener("click", (evento) => {
      evento.preventDefault();
      abrirRelatorio(link.dataset.relatorio);
    });
  }
}

async function abrirRelatorio(nome) {
  try {
    const conteudo = await pedir(`/reports/${encodeURIComponent(nome)}`);
    estado.relatorioAberto = nome;
    $("relatorio-conteudo").textContent = conteudo;
  } catch (erro) {
    avisar(erro.message);
  }
}

// ---------------------------------------------------------------------------
// Ciclo
// ---------------------------------------------------------------------------
async function atualizar() {
  const ambiente = `?env=${encodeURIComponent(estado.ambiente)}`;
  let status = true;
  await blocoMonitorado("status", ["num-api"], pedir("/status").then(desenharStatus, (erro) => {
    status = false;
    throw erro;
  }));
  if (!status) return;
  await Promise.all([
    blocoMonitorado("metricas", ["num-banco", "num-processo", "lentidao"], pedir(`/metrics${ambiente}`).then(desenharMetricas)),
    blocoMonitorado("postos", ["postos"], pedir(`/viewports${ambiente}`).then(desenharPostos)),
    blocoMonitorado("eventos", ["erros", "bloqueios", "eventos"], pedir("/events?limit=200").then(desenharEventos)),
  ]);
}

function reprogramar() {
  window.clearInterval(estado.timer);
  if (estado.intervalo > 0) {
    estado.timer = window.setInterval(atualizar, estado.intervalo);
  }
}

function iniciar() {
  $("ambiente").addEventListener("change", (evento) => {
    estado.ambiente = evento.target.value;
    atualizar();
  });
  $("intervalo").addEventListener("change", (evento) => {
    estado.intervalo = Number(evento.target.value);
    reprogramar();
  });
  $("atualizar").addEventListener("click", atualizar);
  atualizar();
  // Turnos e relatórios dividem o mesmo painel: uma falha só, para um não apagar o aviso do outro.
  blocoMonitorado("relatorios", ["relatorios"], Promise.all([desenharTurnos(), desenharRelatorios()]));
  reprogramar();
}

document.addEventListener("DOMContentLoaded", iniciar);
