/* Dev Observatory — cliente da página.
 *
 * Não calcula indicador e não reimplementa regra: só desenha o que a API
 * devolve (o semáforo abaixo é apresentação sobre números já calculados).
 * Todo POST carrega o mesmo cabeçalho CSRF que o SPA usa. Todo dado dinâmico
 * entra no HTML por escapar(); eventos por delegação (CSP: script-src 'self').
 */
"use strict";

const BASE = "/api/v1/dev-observatory";

// ---------------------------------------------------------------------------
// Constantes de comportamento
// ---------------------------------------------------------------------------
const PREF_PREFIXO = "devobs.";
const INTERVALOS_MS = [0, 5000, 10000, 30000];
const EVENTOS_LIMITE = 300;
const IA_TIMEOUT_MS = 90000;
const IA_PERGUNTA_MAX = 500;
const TOAST_MS = { ok: 4000, info: 5000, erro: 9000 };
const CLASSES_DEFEITO = ["REAL_ERROR", "TECHNICAL_ERROR", "PERFORMANCE_ERROR"];
const CLASSES_FILTRO = [
  ["REAL_ERROR", "Erro real"],
  ["TECHNICAL_ERROR", "Técnico"],
  ["PERFORMANCE_ERROR", "Lentidão"],
  ["EXPECTED_BLOCK", "Bloqueio esperado"],
  ["EXPECTED_VALIDATION", "Validação"],
  ["OK", "OK / ações"],
];
const ABAS = [
  { id: "geral", rotulo: "Visão geral" },
  { id: "erros", rotulo: "Erros" },
  { id: "trafego", rotulo: "Tráfego" },
  { id: "banco", rotulo: "Banco" },
  { id: "postos", rotulo: "Postos" },
  { id: "relatorios", rotulo: "Relatórios" },
  { id: "chat", rotulo: "Chat" },
];
const ABAS_COM_ATALHO = 6; // teclas 1–6; o Chat abre pela aba, pela paleta ou por "Perguntar à IA"
const CHAT_PREF = "chat";
const CHAT_FALAS_PERSISTIDAS = 40;
const CHAT_FALAS_ENVIADAS = 10; // o servidor só usa as últimas 10
const CHAT_CONTEUDO_MAX = 4000;
const CHAT_ANEXOS_MAX = 3;
const CHAT_ALTURA_CAMPO_MAX = 160;
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

// Limiares do semáforo: [atenção, crítico], valor >= limiar. Só apresentação:
// ajuste aqui se o piso de cada indicador mudar.
const LATENCIA_PADRAO = { aviso: 1000, erro: 3000 }; // ms; o servidor manda os reais em summary.thresholds
const LIMIARES = {
  defeitos: [1, 5],
  conexoes: [40, 80], // max_connections padrão do PostgreSQL = 100
  esperandoLock: [1, 3],
  idleEmTransacao: [1, 3],
  queryAtivaS: [5, 30],
  rssMb: [1024, 2048],
  cpuProcesso: [70, 90], // %
};
const CACHE_HIT = [0.99, 0.95]; // [bom a partir de, crítico abaixo de]

// Peso de gravidade em "Precisa de atenção agora" (maior aparece primeiro).
const PESO = { REAL_ERROR: 100, TECHNICAL_ERROR: 90, bloqueio: 80, idle: 70, idleLongo: 75, PERFORMANCE_ERROR: 60, rotaErro: 65, rotaAviso: 50 };
const IDLE_LONGO_S = 60;

// Linhas de traceback do projeto (em cor de acento); site-packages fica esmaecido.
const PROJETO_RE = /(?:^|[\s"'/\\])(?:backend|mes|app)[\\/]/;
const BIBLIOTECA_RE = /site-packages|dist-packages/;

const ESQUELETO = '<div class="esqueleto"></div><div class="esqueleto"></div><div class="esqueleto"></div>';

// ---------------------------------------------------------------------------
// Estado
// ---------------------------------------------------------------------------
const estado = {
  ambiente: "test",
  intervalo: 10000,
  timer: null,
  aba: "geral",
  atualizando: false,
  repetir: false,
  status: null,
  resumoEventos: null,
  eventos: [],
  traffic: [],
  metricas: null,
  viewports: null,
  turnos: null,
  relatorios: null,
  relatoriosCarregado: false,
  filtros: { classes: [], busca: "", agrupar: false },
  trafegoFiltro: { metodo: "", status: "" },
  postosFiltro: { busca: "", categoria: "" },
  listaErros: [],
  selecionado: null,
  detalhe: null,
  vistos: new Set(),
  vistoAte: 0,
  vistoInicio: null,
  relatorioAberto: null,
  relatorioTexto: "",
  ia: { cache: new Map(), pendentes: new Set(), erros: new Map() },
  chat: { mensagens: [], anexos: [], incluirSnapshot: true, pendente: false, controle: null, motivoAbort: "", rodada: 0 },
  encerrar: null,
  paleta: { todos: [], itens: [], ativo: 0 },
  ultimaLeitura: {},
};

// ---------------------------------------------------------------------------
// Utilitários
// ---------------------------------------------------------------------------
function $(id) {
  return document.getElementById(id);
}

function texto(valor, padrao) {
  if (valor === null || valor === undefined || valor === "") return padrao === undefined ? "—" : padrao;
  return String(valor);
}

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };

// Escapa sem trocar vazio por "—" (linhas de traceback podem ser vazias).
function escaparLinha(valor) {
  return String(valor).replace(/[&<>"']/g, (caractere) => ESCAPES[caractere]);
}

function escapar(valor) {
  return escaparLinha(texto(valor));
}

function normalizar(valor) {
  return String(valor === null || valor === undefined ? "" : valor)
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "");
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

function lista(valor) {
  return Array.isArray(valor) ? valor : [];
}

function ehNumero(valor) {
  return valor !== null && valor !== undefined && valor !== "" && !Number.isNaN(Number(valor));
}

/** Preferências leves: storage pode lançar, estar vazio ou bloqueado — a página funciona sem ele. */
function lerPref(chave, padrao) {
  try {
    const bruto = window.localStorage.getItem(PREF_PREFIXO + chave);
    return bruto === null ? padrao : JSON.parse(bruto);
  } catch (_) {
    return padrao;
  }
}

function gravarPref(chave, valor) {
  try {
    window.localStorage.setItem(PREF_PREFIXO + chave, JSON.stringify(valor));
  } catch (_) {
    /* sem storage: segue sem persistir */
  }
}

function aplicarLarguras(raiz) {
  // Largura via CSSOM (não via atributo style=, que o CSP poderia barrar).
  raiz.querySelectorAll("[data-w]").forEach((el) => {
    el.style.width = `${el.dataset.w}%`;
  });
}

/** innerHTML só quando o HTML mudou: evita piscar e perder foco a cada polling. */
function definirHtml(el, html) {
  if (!el || el._html === html) return false;
  el._html = html;
  el.innerHTML = html;
  aplicarLarguras(el);
  return true;
}

function ehCampo(alvo) {
  return Boolean(alvo && (/^(INPUT|TEXTAREA|SELECT)$/.test(alvo.tagName) || alvo.isContentEditable));
}

function telaEstreita() {
  return window.matchMedia("(max-width: 900px)").matches;
}

function abrirDialogo(dialogo) {
  if (typeof dialogo.showModal === "function") dialogo.showModal();
  else dialogo.setAttribute("open", "");
}

// ---------------------------------------------------------------------------
// Toasts e área de transferência
// ---------------------------------------------------------------------------
function avisar(mensagem, tipo) {
  if (!mensagem) return;
  const caixa = $("toasts");
  const item = document.createElement("div");
  const nivel = tipo || "info";
  item.className = `toast ${nivel}`;
  item.textContent = mensagem;
  item.addEventListener("click", () => item.remove());
  caixa.append(item);
  while (caixa.children.length > 4) caixa.firstChild.remove();
  window.setTimeout(() => item.remove(), TOAST_MS[nivel] || TOAST_MS.info);
}

function copiarLegado(conteudo) {
  const area = document.createElement("textarea");
  area.value = conteudo;
  area.setAttribute("readonly", "");
  area.className = "copia-oculta";
  document.body.append(area);
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  if (!ok) throw new Error("copy");
}

async function copiar(conteudo, descricao) {
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(conteudo);
    else copiarLegado(conteudo);
    avisar(`${descricao} copiado.`, "ok");
  } catch (_) {
    try {
      copiarLegado(conteudo);
      avisar(`${descricao} copiado.`, "ok");
    } catch (__) {
      avisar("Não foi possível copiar: o navegador bloqueou o acesso à área de transferência.", "erro");
    }
  }
}

// ---------------------------------------------------------------------------
// Rede
// ---------------------------------------------------------------------------
async function pedir(caminho, opcoes) {
  const config = Object.assign({ credentials: "include", headers: {} }, opcoes || {});
  const metodo = (config.method || "GET").toUpperCase();
  if (metodo !== "GET") {
    config.headers["Content-Type"] = "application/json";
    const csrf = cookie("gestor_devobs_csrf");
    if (csrf) config.headers["X-CSRF-Token"] = csrf;
  }
  const resposta = await fetch(BASE + caminho, config);
  const tipo = resposta.headers.get("content-type") || "";
  if (!resposta.ok) {
    let mensagem = resposta.status === 401
      ? "Sessão expirada; recarregue a página para entrar de novo"
      : `${resposta.status} em ${caminho}`;
    let codigo;
    if (tipo.includes("application/json")) {
      const corpo = await resposta.json().catch(() => null);
      if (corpo && corpo.message) mensagem = corpo.message;
      else if (corpo && typeof corpo.detail === "string") mensagem = corpo.detail;
      if (corpo && corpo.code) codigo = corpo.code;
    }
    const erro = new Error(mensagem);
    erro.status = resposta.status;
    erro.code = codigo;
    throw erro;
  }
  if (tipo.includes("application/json")) return resposta.json();
  return resposta.text();
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
    const alvo = $(id);
    const painel = alvo && alvo.closest(".painel, section");
    if (!painel) return;
    let faixa = painel.querySelector(`:scope > .falha[data-bloco="${bloco}"]`);
    if (!erro) {
      if (faixa) faixa.remove();
      return;
    }
    if (!faixa) {
      faixa = document.createElement("p");
      faixa.className = "falha";
      faixa.dataset.bloco = bloco;
      faixa.setAttribute("role", "status");
      const titulo = painel.querySelector(":scope > h2");
      if (titulo) titulo.after(faixa);
      else painel.prepend(faixa);
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

// ---------------------------------------------------------------------------
// Peças de HTML
// ---------------------------------------------------------------------------
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

function semaforo(valor, [atencao, critico]) {
  if (!ehNumero(valor)) return "";
  const v = Number(valor);
  if (v >= critico) return "ruim";
  return v >= atencao ? "alerta" : "bom";
}

function semaforoCache(razao) {
  if (!ehNumero(razao)) return "";
  const v = Number(razao);
  if (v >= CACHE_HIT[0]) return "bom";
  return v >= CACHE_HIT[1] ? "alerta" : "ruim";
}

function limitesLatencia() {
  const lim = ((estado.status || {}).summary || {}).thresholds || (estado.resumoEventos || {}).thresholds || {};
  return {
    aviso: Number(lim.latency_warning_ms) || LATENCIA_PADRAO.aviso,
    erro: Number(lim.latency_error_ms) || LATENCIA_PADRAO.erro,
  };
}

function nivelLatencia(ms) {
  const lim = limitesLatencia();
  const v = Number(ms);
  if (!ehNumero(ms)) return "";
  if (v >= lim.erro) return "lento-erro";
  return v >= lim.aviso ? "lento-aviso" : "";
}

function resumoAtual() {
  return (estado.status && estado.status.summary) || estado.resumoEventos || {};
}

function pg() {
  return (estado.metricas && estado.metricas.postgres) || {};
}

function iaDisponivel() {
  return Boolean(estado.status && estado.status.ai && estado.status.ai.available);
}

function podeEncerrar() {
  const acoes = (estado.status && estado.status.quick_actions) || {};
  return acoes.terminate_backend === true && estado.ambiente === "test";
}

function inicioApi() {
  return (resumoAtual().started_at) || "";
}

// ---------------------------------------------------------------------------
// Ambiente e status
// ---------------------------------------------------------------------------
function aplicarAmbiente() {
  document.body.dataset.ambiente = estado.ambiente;
  document.querySelectorAll('[data-acao="ambiente"]').forEach((botao) => {
    botao.setAttribute("aria-pressed", String(botao.dataset.ambiente === estado.ambiente));
  });
  $("faixa-real").hidden = estado.ambiente !== "real";
  atualizarTitulo();
}

function definirAmbiente(ambiente) {
  if ((ambiente !== "test" && ambiente !== "real") || ambiente === estado.ambiente) return;
  estado.ambiente = ambiente;
  estado.metricas = null; // não mostrar dado do outro banco enquanto o novo carrega
  estado.viewports = null;
  aplicarAmbiente();
  desenharBanco();
  desenharPostos();
  desenharGeral();
  desenharContadores();
  avisar(ambiente === "real" ? "Observando o REAL — somente leitura." : "Observando o TESTE.", ambiente === "real" ? "info" : "ok");
  atualizar();
}

function atualizarTitulo() {
  const pendentes = contarNaoVistos();
  document.title = `${estado.ambiente === "real" ? "[REAL] " : ""}${pendentes ? `(${pendentes}) ` : ""}Dev Observatory — Gestor de Peças`;
}

function desenharStatus(dados) {
  estado.status = dados;
  $("relogio").textContent = hora(dados.generated_at);
  $("turno").textContent = dados.current_shift ? dados.current_shift.label : "fora de turno";

  const ia = dados.ai || {};
  const chip = $("chip-ia");
  chip.className = `chip-ia${ia.available ? " ok" : ""}`;
  chip.textContent = ia.available ? `IA: ${texto(ia.model, "modelo")}` : "IA indisponível";
  chip.title = (ia.available ? `Provedor: ${texto(ia.provider)}. ` : "IA não configurada. ") + "Clique para trocar chave e modelo";

  const real = (dados.environments || {}).real || {};
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
  definirHtml($("num-api"), [
    numero("requisições", resumo.requests || 0),
    numero("defeitos", defeitos, defeitos ? "ruim" : "bom"),
    numero("erros reais", classificacoes.REAL_ERROR || 0, classificacoes.REAL_ERROR ? "ruim" : ""),
    numero("técnicos", classificacoes.TECHNICAL_ERROR || 0, classificacoes.TECHNICAL_ERROR ? "ruim" : ""),
    numero("bloqueios esperados", resumo.expected_blocks || 0),
    numero("validações", classificacoes.EXPECTED_VALIDATION || 0),
  ].join(""));

  desenharGeral();
  desenharTrafego();
  desenharContadores();
  desenharIAs();
  desenharChat();
  desenharBanco();
}

// ---------------------------------------------------------------------------
// Visão geral: KPIs e "precisa de atenção agora"
// ---------------------------------------------------------------------------
const NOME_NIVEL = { bom: "normal", alerta: "atenção", ruim: "crítico", "": "sem leitura" };

function kpi(rotulo, valor, nivel, destino) {
  return `<button type="button" class="kpi ${nivel}" data-acao="ir" data-aba="${escapar(destino)}" ` +
    `aria-label="${escapar(rotulo)}: ${escapar(valor)}, ${NOME_NIVEL[nivel]}. Abrir ${escapar(destino)}">` +
    `<span class="kpi-rotulo">${escapar(rotulo)}</span><b>${escapar(valor)}</b>` +
    `<span class="kpi-nivel">${NOME_NIVEL[nivel]}</span></button>`;
}

function desenharKpis() {
  const resumo = resumoAtual();
  const banco = pg();
  const conexoes = banco.connections || {};
  const locks = banco.locks || {};
  const processo = (estado.metricas && estado.metricas.process) || {};
  const lentas = lista(resumo.slowest_routes);
  const p95 = lentas.length ? lentas[0].p95_ms : null;
  const lim = limitesLatencia();
  const temBanco = Boolean(estado.metricas);
  const defeitos = Number(resumo.defects || 0);
  const esperando = conexoes.esperando_lock !== undefined ? conexoes.esperando_lock : locks.nao_concedidos;
  const idle = conexoes.idle_in_transaction;

  const nivelP95 = !ehNumero(p95) ? "" : semaforo(p95, [lim.aviso, lim.erro]);
  const cartoes = [
    kpi("Requisições", resumo.requests || 0, "", "trafego"),
    kpi("Defeitos", defeitos, semaforo(defeitos, LIMIARES.defeitos), "erros"),
    kpi("p95 pior rota", ehNumero(p95) ? `${Math.round(Number(p95))} ms` : "—", nivelP95, "trafego"),
    kpi("Conexões", temBanco ? texto(conexoes.conexoes, "0") : "—", temBanco ? semaforo(conexoes.conexoes, LIMIARES.conexoes) : "", "banco"),
    kpi("Esperando lock", temBanco ? texto(esperando, "0") : "—", temBanco ? semaforo(esperando, LIMIARES.esperandoLock) : "", "banco"),
    kpi("Cache hit", ehNumero(banco.cache_hit_ratio) ? `${(banco.cache_hit_ratio * 100).toFixed(1)}%` : "—", semaforoCache(banco.cache_hit_ratio), "banco"),
    kpi("Idle in tx", temBanco ? texto(idle, "0") : "—", temBanco ? semaforo(idle, LIMIARES.idleEmTransacao) : "", "banco"),
    kpi("Memória (RSS)", processo.available ? `${processo.rss_mb} MB` : "—", processo.available ? semaforo(processo.rss_mb, LIMIARES.rssMb) : "", "geral"),
    kpi("CPU do processo", processo.available ? `${Number(processo.cpu_percent || 0).toFixed(0)}%` : "—", processo.available ? semaforo(processo.cpu_percent, LIMIARES.cpuProcesso) : "", "geral"),
  ];
  definirHtml($("kpis"), cartoes.join(""));
}

function itensAtencao() {
  const itens = [];
  const defeitosRecentes = estado.eventos.filter((e) => e.classification === "REAL_ERROR" || e.classification === "TECHNICAL_ERROR");
  defeitosRecentes.slice(0, 5).forEach((e) => itens.push({
    peso: PESO[e.classification],
    nivel: "ruim",
    selo: e.classification,
    titulo: `${texto(e.method, "")} ${texto(e.route)} → ${texto(e.status)}`.trim(),
    detalhe: `${hora(e.timestamp)} · ${texto(e.error_code, "")} ${texto(e.error_message || e.exception, "")}`.trim(),
    aba: "erros",
    sequence: e.sequence,
  }));
  estado.eventos.filter((e) => e.classification === "PERFORMANCE_ERROR").slice(0, 3).forEach((e) => itens.push({
    peso: PESO.PERFORMANCE_ERROR,
    nivel: "alerta",
    selo: "lentidão",
    titulo: `${texto(e.method, "")} ${texto(e.route)} levou ${texto(e.latency_ms)} ms`,
    detalhe: hora(e.timestamp),
    aba: "erros",
    sequence: e.sequence,
  }));
  lista(pg().blocked).forEach((b) => itens.push({
    peso: PESO.bloqueio,
    nivel: "ruim",
    selo: "bloqueio",
    titulo: `Sessão ${texto(b.bloqueado)} bloqueada pela sessão ${texto(b.bloqueador)}`,
    detalhe: texto(b.query_bloqueada, ""),
    aba: "banco",
  }));
  lista(pg().idle_in_transaction).forEach((s) => {
    const longo = Number(s.duracao_s || 0) >= IDLE_LONGO_S;
    itens.push({
      peso: longo ? PESO.idleLongo : PESO.idle,
      nivel: longo ? "ruim" : "alerta",
      selo: "idle in tx",
      titulo: `Sessão ${texto(s.pid)} parada em transação há ${duracao(s.duracao_s)}`,
      detalhe: `${texto(s.application_name, "")} ${texto(s.query, "")}`.trim(),
      aba: "banco",
    });
  });
  const lim = limitesLatencia();
  lista(resumoAtual().slowest_routes).slice(0, 3).forEach((r) => {
    const p95 = Number(r.p95_ms);
    if (!(p95 >= lim.aviso)) return;
    itens.push({
      peso: p95 >= lim.erro ? PESO.rotaErro : PESO.rotaAviso,
      nivel: p95 >= lim.erro ? "ruim" : "alerta",
      selo: "rota lenta",
      titulo: `${texto(r.method, "")} ${texto(r.route)} — p95 ${Math.round(p95)} ms`,
      detalhe: `${texto(r.count, "0")} chamadas · máx ${texto(r.max_ms)} ms`,
      aba: "trafego",
    });
  });
  return itens.sort((a, b) => b.peso - a.peso).slice(0, 12);
}

function desenharAtencao() {
  const semDados = !estado.status && !estado.metricas && !estado.eventos.length;
  if (semDados) {
    definirHtml($("atencao"), ESQUELETO);
    definirHtml($("atencao-n"), "");
    return;
  }
  const itens = itensAtencao();
  $("atencao-n").textContent = itens.length ? `${itens.length} ${itens.length === 1 ? "item" : "itens"}` : "";
  if (!itens.length) {
    definirHtml($("atencao"), '<div class="calmo"><b>Tudo calmo.</b><span>Sem erro real ou técnico, bloqueio, sessão parada em transação nem rota lenta agora.</span></div>');
    return;
  }
  const html = itens.map((item) =>
    `<li><button type="button" data-acao="ir" data-aba="${escapar(item.aba)}"` +
    `${item.sequence ? ` data-sequence="${escapar(item.sequence)}"` : ""}>` +
    `<span class="nivel ${item.nivel}">${escapar(item.selo)}</span>` +
    `<span class="at-titulo">${escapar(item.titulo)}</span>` +
    `<span class="at-ir">abrir ›</span>` +
    `${item.detalhe ? `<span class="at-detalhe">${escapar(item.detalhe)}</span>` : ""}</button></li>`
  ).join("");
  definirHtml($("atencao"), `<ul class="atencao">${html}</ul>`);
}

function desenharGeral() {
  desenharKpis();
  desenharAtencao();
}

// ---------------------------------------------------------------------------
// Contadores das abas
// ---------------------------------------------------------------------------
function contarNaoVistos() {
  return estado.eventos.filter(
    (e) => CLASSES_DEFEITO.includes(e.classification) && !(e.sequence <= estado.vistoAte) && !estado.vistos.has(e.sequence)
  ).length;
}

function definirContador(id, quantidade, descricao) {
  const el = $(id);
  if (!el) return;
  el.hidden = quantidade <= 0;
  definirHtml(el, quantidade > 0 ? `${quantidade}<span class="sr"> ${escapar(descricao)}</span>` : "");
}

function desenharContadores() {
  definirContador("contador-erros", contarNaoVistos(), "erros não vistos");
  const banco = pg();
  definirContador("contador-banco", lista(banco.idle_in_transaction).length + lista(banco.blocked).length, "sessões com problema");
  atualizarTitulo();
}

// ---------------------------------------------------------------------------
// Métricas: banco e processo
// ---------------------------------------------------------------------------
function receberMetricas(dados) {
  estado.metricas = dados;
  desenharBanco();
  desenharProcesso();
  desenharGeral();
  desenharContadores();
}

function desenharProcesso() {
  const processo = (estado.metricas && estado.metricas.process) || {};
  const sistema = processo.system || {};
  definirHtml($("num-processo"), !estado.metricas ? ESQUELETO : processo.available
    ? [
        numero("RSS", `${processo.rss_mb} MB`, semaforo(processo.rss_mb, LIMIARES.rssMb)),
        numero("threads", processo.threads),
        numero("CPU proc.", `${Number(processo.cpu_percent || 0).toFixed(0)}%`, semaforo(processo.cpu_percent, LIMIARES.cpuProcesso)),
        numero("conexões TCP", texto(processo.connections)),
        numero("mem. livre", `${Number(sistema.memory_available_mb || 0).toFixed(0)} MB`),
        numero("CPU sistema", `${Number(sistema.cpu_percent || 0).toFixed(0)}%`),
      ].join("")
    : `<div class="vazio">${escapar(processo.reason || "Indisponível")}</div>`);
}

function botoesSessao(pid, query, rotuloEncerrar) {
  const copiarQuery = query
    ? `<button type="button" class="mini" data-acao="copiar-query" data-copiar="${escapar(query)}">Copiar query</button>`
    : "";
  const encerrar = podeEncerrar()
    ? `<button type="button" class="mini perigo" data-acao="encerrar-sessao" data-pid="${escapar(pid)}" ` +
      `aria-label="${escapar(rotuloEncerrar)} (pid ${escapar(pid)})">${escapar(rotuloEncerrar)}</button>`
    : "";
  return `<td class="acoes-celula">${copiarQuery}${encerrar}</td>`;
}

function notaBanco() {
  if (estado.ambiente === "real") return "REAL é somente leitura: nenhuma ação de escrita (encerrar sessão) é oferecida aqui.";
  const acoes = (estado.status && estado.status.quick_actions) || {};
  if (estado.status && acoes.terminate_backend !== true) return "Encerrar sessão está desabilitado nesta instância (ambiente de produção).";
  return "";
}

function desenharBanco() {
  const dados = estado.metricas;
  if (!dados) {
    definirHtml($("num-banco"), ESQUELETO);
    ["tab-idle", "tab-bloqueios", "tab-queries"].forEach((id) => definirHtml($(id), tabela([], [], "Carregando…")));
    return;
  }
  const banco = pg();
  const conexoes = banco.connections || {};
  const estatisticas = banco.statistics || {};
  const locks = banco.locks || {};
  const esperando = conexoes.esperando_lock !== undefined ? conexoes.esperando_lock : locks.nao_concedidos;
  $("banco-alvo").textContent = `${texto((banco.target || {}).dbname)} · ${dados.environment === "real" ? "somente leitura" : "pool da API"}`;
  $("banco-nota").textContent = notaBanco();

  definirHtml($("num-banco"), [
    numero("conexões", conexoes.conexoes || 0, semaforo(conexoes.conexoes, LIMIARES.conexoes)),
    numero("ativas", conexoes.ativas || 0),
    numero("idle in tx", conexoes.idle_in_transaction || 0, semaforo(conexoes.idle_in_transaction, LIMIARES.idleEmTransacao)),
    numero("deadlocks", estatisticas.deadlocks || 0, Number(estatisticas.deadlocks || 0) > 0 ? "ruim" : ""),
    numero("locks aguardando", locks.nao_concedidos || esperando || 0, semaforo(locks.nao_concedidos || esperando, LIMIARES.esperandoLock)),
    numero("cache hit", ehNumero(banco.cache_hit_ratio) ? `${(banco.cache_hit_ratio * 100).toFixed(1)}%` : "—", semaforoCache(banco.cache_hit_ratio)),
    numero("query ativa + longa", `${Number(conexoes.query_ativa_mais_longa_s || 0).toFixed(1)}s`, semaforo(conexoes.query_ativa_mais_longa_s, LIMIARES.queryAtivaS)),
    numero("tamanho", `${(Number(estatisticas.tamanho_bytes || 0) / (1024 * 1024)).toFixed(0)} MB`),
  ].join(""));

  const idle = lista(banco.idle_in_transaction).map((s) =>
    `<tr><td class="num">${escapar(s.pid)}</td><td>${escapar(s.application_name)}</td>` +
    `<td class="num-lat">${escapar(duracao(s.duracao_s))}</td>` +
    `<td class="consulta"><code>${escapar(s.query)}</code></td>${botoesSessao(s.pid, s.query, "Encerrar sessão")}</tr>`
  );
  definirHtml($("tab-idle"), tabela(["pid", "aplicação", "em transação", "última query", "ações"], idle, "Nenhuma sessão parada em transação."));

  const bloqueios = lista(banco.blocked).map((b) =>
    `<tr><td class="num">${escapar(b.bloqueado)}</td><td class="num">${escapar(b.bloqueador)}</td>` +
    `<td class="consulta"><code>${escapar(b.query_bloqueada)}</code></td>` +
    `<td>${escapar([b.wait_event_type, b.wait_event].filter(Boolean).join(" / ") || "—")}</td>` +
    `${botoesSessao(b.bloqueador, b.query_bloqueada, "Encerrar bloqueador")}</tr>`
  );
  definirHtml($("tab-bloqueios"), tabela(["bloqueada (pid)", "bloqueador (pid)", "consulta bloqueada", "espera", "ações"], bloqueios, "Nenhum bloqueio de lock agora."));

  const queries = lista(banco.slow_queries).map((q) =>
    `<tr><td class="num">${escapar(q.pid)}</td><td class="num-lat">${Number(q.duracao_s || 0).toFixed(1)}s</td>` +
    `<td class="consulta"><code>${escapar(q.query)}</code><div class="rotulo">${escapar(q.application_name)}</div></td>` +
    `<td>${escapar(q.wait_event || "—")}</td>${botoesSessao(q.pid, q.query, "Encerrar sessão")}</tr>`
  );
  definirHtml($("tab-queries"), tabela(["pid", "duração", "consulta", "espera", "ações"], queries, "Nenhuma consulta longa no momento."));
}

// ---------------------------------------------------------------------------
// Encerrar sessão (TESTE apenas, com confirmação)
// ---------------------------------------------------------------------------
function descreverSessao(pid) {
  const banco = pg();
  const lenta = lista(banco.slow_queries).find((s) => Number(s.pid) === pid);
  if (lenta) return { estadoSessao: "active (consulta lenta)", query: lenta.query, app: lenta.application_name };
  const parada = lista(banco.idle_in_transaction).find((s) => Number(s.pid) === pid);
  if (parada) return { estadoSessao: "idle in transaction", query: parada.query, app: parada.application_name };
  const bloqueio = lista(banco.blocked).find((b) => Number(b.bloqueador) === pid);
  if (bloqueio) {
    return { estadoSessao: `bloqueando a sessão ${bloqueio.bloqueado}`, query: `(consulta que ela bloqueia) ${texto(bloqueio.query_bloqueada, "")}`, app: "" };
  }
  return { estadoSessao: "desconhecido", query: "", app: "" };
}

function abrirEncerrar(pid) {
  if (!podeEncerrar() || !Number.isInteger(pid)) return;
  const sessao = descreverSessao(pid);
  estado.encerrar = { pid };
  definirHtml($("encerrar-corpo"),
    `<h2 id="encerrar-titulo">Encerrar sessão ${escapar(pid)}?</h2>` +
    `<p class="nota">Isto roda pg_terminate_backend no banco de TESTE. A transação aberta dessa sessão é desfeita.</p>` +
    `<dl class="sessao-info"><dt>pid</dt><dd>${escapar(pid)}</dd>` +
    `<dt>estado</dt><dd>${escapar(sessao.estadoSessao)}</dd>` +
    `<dt>aplicação</dt><dd>${escapar(sessao.app)}</dd>` +
    `<dt>consulta</dt><dd><code>${escapar(sessao.query)}</code></dd></dl>` +
    `<div class="dialogo-acoes">` +
    `<button type="button" data-acao="fechar-dialogo" data-dialogo="dialogo-encerrar" autofocus>Cancelar</button>` +
    `<button type="button" class="perigo" id="encerrar-confirmar" data-acao="confirmar-encerrar">Encerrar sessão</button></div>`);
  abrirDialogo($("dialogo-encerrar"));
}

async function confirmarEncerrar() {
  if (!podeEncerrar() || !estado.encerrar) return;
  const { pid } = estado.encerrar;
  const botao = $("encerrar-confirmar");
  if (botao) botao.disabled = true;
  try {
    const r = await pedir("/actions/terminate-backend", { method: "POST", body: JSON.stringify({ pid }) });
    if (r.terminated) avisar(`Sessão ${pid} encerrada.`, "ok");
    else if (r.found) avisar(`Sessão ${pid} encontrada, mas o PostgreSQL não a encerrou.`, "erro");
    else avisar(`Sessão ${pid} não existe mais.`, "info");
  } catch (erro) {
    avisar(erro.message, "erro");
  } finally {
    estado.encerrar = null;
    $("dialogo-encerrar").close();
    buscarMetricas().catch((erro) => situacaoBloco("metricas", ["num-banco"], erro));
  }
}

// ---------------------------------------------------------------------------
// Postos
// ---------------------------------------------------------------------------
function receberPostos(dados) {
  estado.viewports = dados;
  desenharPostos();
}

function textoPosto(item) {
  const op = lista(item.ops_ativas)[0] || {};
  return normalizar([
    item.recurso, item.setor, item.op_estado, op.op, op.produto, op.descricao_produto, item.operador_estado,
    op.operador_inicio, item.descricao_atividade, item.motivo, CATEGORIA_ROTULO[item.categoria], item.categoria,
  ].join(" "));
}

function desenharPostos() {
  const dados = estado.viewports;
  const alvo = $("postos");
  if (!dados) {
    definirHtml($("postos-chips"), "");
    definirHtml(alvo, ESQUELETO);
    return;
  }
  $("viewports-fonte").textContent = `${texto(dados.database)} · ${texto(dados.source)}`;
  const itens = lista(dados.items);

  const contagem = {};
  itens.forEach((item) => {
    const cat = String(item.categoria || "desconhecido");
    contagem[cat] = (contagem[cat] || 0) + 1;
  });
  definirHtml($("postos-chips"), Object.keys(contagem).map((cat) =>
    `<button type="button" class="chip" data-acao="chip-posto" data-categoria="${escapar(cat)}" ` +
    `aria-pressed="${estado.postosFiltro.categoria === cat}">${escapar(CATEGORIA_ROTULO[cat] || cat)}` +
    `<span class="chip-n">${contagem[cat]}</span></button>`
  ).join(""));

  const termo = normalizar(estado.postosFiltro.busca);
  const visiveis = itens.filter((item) =>
    (!estado.postosFiltro.categoria || String(item.categoria || "desconhecido") === estado.postosFiltro.categoria) &&
    (!termo || textoPosto(item).includes(termo))
  );
  if (!itens.length) {
    definirHtml(alvo, '<div class="vazio">Nenhum posto com estado canônico registrado agora.</div>');
    return;
  }
  if (!visiveis.length) {
    definirHtml(alvo, '<div class="vazio">Nenhum posto combina com a busca/filtro. Use “Limpar filtros” na paleta (Ctrl+K).</div>');
    return;
  }
  definirHtml(alvo, visiveis.map((item) => {
    const categoria = String(item.categoria || "desconhecido");
    const op = lista(item.ops_ativas)[0] || {};
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
  }).join(""));
}

// ---------------------------------------------------------------------------
// Eventos: lista (mestre)
// ---------------------------------------------------------------------------
function receberEventos(dados) {
  estado.eventos = lista(dados.items);
  estado.traffic = lista(dados.traffic);
  estado.resumoEventos = dados.summary || null;
  restaurarVistos();
  if (estado.detalhe) {
    const atual = estado.eventos.find((e) => e.sequence === estado.detalhe.sequence);
    if (atual) estado.detalhe = atual;
  }
  desenharErros();
  desenharTrafego();
  desenharGeral();
  desenharContadores();
}

/** "Visto até" persiste por execução da API: sequence recomeça do zero quando ela reinicia. */
function restaurarVistos() {
  const inicio = inicioApi();
  if (estado.vistoInicio === inicio) return;
  estado.vistoInicio = inicio;
  const salvo = lerPref("vistoAte", null);
  estado.vistoAte = salvo && salvo.inicio === inicio ? Number(salvo.sequence) || 0 : 0;
  estado.vistos.clear();
}

function marcarVistos() {
  const maior = estado.eventos.reduce((m, e) => Math.max(m, Number(e.sequence) || 0), 0);
  estado.vistoAte = maior;
  gravarPref("vistoAte", { inicio: inicioApi(), sequence: maior });
  desenharErros();
  desenharContadores();
  desenharGeral();
}

function textoBuscaEvento(e) {
  return normalizar([e.method, e.path, e.route, e.error_code, e.error_message, e.exception, e.classification, e.status].join(" "));
}

function eventosFiltrados() {
  const { classes, busca } = estado.filtros;
  const termo = normalizar(busca);
  return estado.eventos.filter((e) =>
    (!classes.length || classes.includes(e.classification)) && (!termo || textoBuscaEvento(e).includes(termo))
  );
}

function agruparEventos(eventos) {
  if (!estado.filtros.agrupar) return eventos.map((e) => ({ evento: e, total: 1, sequences: [e.sequence] }));
  const grupos = new Map();
  eventos.forEach((e) => {
    const chave = [e.route, e.error_code, e.status].join("|");
    const grupo = grupos.get(chave);
    if (grupo) {
      grupo.total += 1;
      grupo.sequences.push(e.sequence);
    } else {
      grupos.set(chave, { evento: e, total: 1, sequences: [e.sequence] }); // lista vem do mais novo: o primeiro é o representante
    }
  });
  return [...grupos.values()];
}

function ehNovo(e) {
  return CLASSES_DEFEITO.includes(e.classification) && !(e.sequence <= estado.vistoAte) && !estado.vistos.has(e.sequence);
}

function filtrosAtivos() {
  return estado.filtros.classes.length > 0 || estado.filtros.busca.trim() !== "";
}

function desenharErros() {
  const contagem = {};
  estado.eventos.forEach((e) => {
    contagem[e.classification] = (contagem[e.classification] || 0) + 1;
  });
  definirHtml($("erros-chips"), CLASSES_FILTRO.map(([classe, rotulo]) =>
    `<button type="button" class="chip" data-acao="chip-classe" data-classe="${classe}" ` +
    `aria-pressed="${estado.filtros.classes.includes(classe)}">${escapar(rotulo)}` +
    `<span class="chip-n">${contagem[classe] || 0}</span></button>`
  ).join(""));

  const filtrados = eventosFiltrados();
  const grupos = agruparEventos(filtrados);
  estado.listaErros = grupos;
  $("erros-resumo").textContent = estado.eventos.length
    ? `${filtrados.length} de ${estado.eventos.length} eventos${estado.filtros.agrupar ? ` · ${grupos.length} grupos` : ""}`
    : "";

  const caixa = $("erros-lista");
  const focado = document.activeElement;
  const sequenceFocada = focado && caixa.contains(focado) ? focado.dataset.sequence : null;
  const rolagem = caixa.scrollTop;
  let html;
  if (!estado.eventos.length) {
    html = '<li class="vazio">Nenhum evento capturado desde o start da API.</li>';
  } else if (!grupos.length) {
    html = '<li class="vazio">Nenhum evento com esses filtros. <button type="button" class="link" data-acao="limpar-filtros">Limpar filtros</button></li>';
  } else {
    html = grupos.map(({ evento: e, total }) => {
      const selecionado = e.sequence === estado.selecionado;
      return `<li><button type="button" class="item-evento${selecionado ? " sel" : ""}${ehNovo(e) ? " novo" : ""}" ` +
        `data-acao="selecionar-evento" data-sequence="${escapar(e.sequence)}" aria-current="${selecionado}">` +
        `<span class="ie-linha"><span class="ie-hora">${hora(e.timestamp)}</span>` +
        `<span class="cls cls-${escapar(e.classification)}">${escapar(e.classification)}</span>` +
        `<span class="ie-status">${escapar(e.status)}</span>${total > 1 ? `<span class="ie-n">×${total}</span>` : ""}</span>` +
        `<code class="ie-rota">${escapar(e.method)} ${escapar(e.route)}</code>` +
        `<span class="ie-msg">${escapar([e.error_code, e.error_message || e.exception].filter(Boolean).join(" · ") || "—")}</span></button></li>`;
    }).join("");
  }
  if (definirHtml(caixa, html)) {
    caixa.scrollTop = rolagem;
    if (sequenceFocada) {
      const botao = caixa.querySelector(`[data-sequence="${sequenceFocada}"]`);
      if (botao) botao.focus({ preventScroll: true });
    }
  }
}

function selecionarEvento(sequence, aposSelecao) {
  const evento = estado.eventos.find((e) => e.sequence === Number(sequence));
  if (!evento) return;
  estado.selecionado = evento.sequence;
  estado.detalhe = evento;
  estado.vistos.add(evento.sequence);
  desenharErros();
  desenharDetalhe();
  desenharContadores();
  desenharGeral();
  if (aposSelecao === "rolar") {
    const botao = $("erros-lista").querySelector(`[data-sequence="${evento.sequence}"]`);
    if (botao) botao.scrollIntoView({ block: "nearest" });
  }
  if (telaEstreita()) $("erros-detalhe").focus();
}

function fecharDetalhe() {
  if (!estado.selecionado) return;
  const sequence = estado.selecionado;
  estado.selecionado = null;
  estado.detalhe = null;
  desenharErros();
  desenharDetalhe();
  const botao = $("erros-lista").querySelector(`[data-sequence="${sequence}"]`);
  if (botao) botao.focus({ preventScroll: true });
}

function moverSelecao(delta) {
  const grupos = estado.listaErros;
  if (!grupos.length) return;
  const atual = grupos.findIndex((g) => g.sequences.includes(estado.selecionado));
  const proximo = atual === -1 ? (delta > 0 ? 0 : grupos.length - 1) : Math.min(grupos.length - 1, Math.max(0, atual + delta));
  selecionarEvento(grupos[proximo].evento.sequence, "rolar");
}

// ---------------------------------------------------------------------------
// Evento: detalhe
// ---------------------------------------------------------------------------
function jsonLegivel(valor) {
  try {
    return JSON.stringify(valor, null, 2);
  } catch (_) {
    return String(valor);
  }
}

function htmlTraceback(traceback) {
  let projeto = false;
  const linhas = String(traceback).split("\n").map((linha) => {
    let classe = "tb-lib";
    if (/^\s+File /.test(linha)) {
      projeto = PROJETO_RE.test(linha) && !BIBLIOTECA_RE.test(linha);
      classe = projeto ? "tb-proj" : "tb-lib";
    } else if (/^\S/.test(linha) && !/^Traceback/.test(linha)) {
      classe = "tb-exc"; // linha final: Tipo: mensagem
      projeto = false;
    } else if (projeto) {
      classe = "tb-proj"; // trecho de código do frame do projeto
    }
    return `<span class="${classe}">${escaparLinha(linha)}</span>`;
  });
  return `<pre class="traceback">${linhas.join("\n")}</pre>`;
}

function htmlDetalhe(e, grupo) {
  const linhasMeta = [
    ["Método", e.method], ["Caminho", e.path], ["Rota", e.route], ["Status", e.status],
    ["Latência", ehNumero(e.latency_ms) ? `${e.latency_ms} ms` : "—"],
    ["Classificação", e.classification], ["Gravidade", e.severity], ["error_code", e.error_code],
    ["request_id", e.request_id], ["Quando", e.timestamp], ["sequence", e.sequence],
  ].map(([rotulo, valor]) => `<dt>${escapar(rotulo)}</dt><dd>${escapar(valor)}</dd>`).join("");
  return `
    <div class="det-cab">
      <div><span class="cls cls-${escapar(e.classification)}">${escapar(e.classification)}</span>
        <h3><code>${escapar(e.method)} ${escapar(e.route)}</code> → ${escapar(e.status)}</h3></div>
      <button type="button" class="fechar-detalhe" data-acao="fechar-detalhe" aria-label="Fechar detalhe">Fechar ✕</button>
    </div>
    ${grupo && grupo.total > 1 ? `<p class="det-grupo">×${grupo.total} ocorrências iguais (rota + código + status); mostrando a mais recente.</p>` : ""}
    ${e.error_message ? `<p class="det-msg">${escapar(e.error_message)}</p>` : ""}
    <div class="det-acoes">
      <button type="button" class="principal" data-acao="copiar-pacote">Copiar pacote p/ Claude</button>
      <button type="button" data-acao="copiar-traceback"${e.traceback ? "" : " disabled"}>Copiar traceback</button>
      <button type="button" data-acao="copiar-rota">Copiar rota</button>
      <button type="button" data-acao="perguntar-ia">Perguntar à IA</button>
    </div>
    <div id="ia-evento"></div>
    <dl class="det-meta">${linhasMeta}</dl>
    ${e.exception ? `<h4>Exceção</h4><pre class="bloco-codigo">${escapar(e.exception)}</pre>` : ""}
    ${e.traceback ? `<h4>Traceback</h4>${htmlTraceback(e.traceback)}` : ""}
    ${e.details ? `<h4>Details</h4><pre class="bloco-codigo">${escapar(jsonLegivel(e.details))}</pre>` : ""}`;
}

function desenharDetalhe() {
  const caixa = $("erros-detalhe");
  const evento = estado.detalhe;
  caixa.classList.toggle("aberto", Boolean(evento));
  if (!evento) {
    definirHtml(caixa, '<div class="vazio">Selecione um evento para ver requisição, exceção e traceback. Use <kbd>j</kbd>/<kbd>k</kbd> para navegar.</div>');
    return;
  }
  const grupo = estado.listaErros.find((g) => g.sequences.includes(evento.sequence));
  definirHtml(caixa, htmlDetalhe(evento, grupo));
  desenharIAs();
}

function pacoteClaude(e) {
  const ambiente = estado.ambiente === "real" ? "REAL (somente leitura)" : "TESTE";
  const bloco = (titulo, conteudo, linguagem) => (conteudo ? `\n## ${titulo}\n\`\`\`${linguagem || "text"}\n${conteudo}\n\`\`\`\n` : "");
  return [
    `# Erro no Gestor de Peças: ${texto(e.method, "")} ${texto(e.route)} → ${texto(e.status)} (${texto(e.classification)})`,
    "",
    `- Ambiente observado no painel: ${ambiente}`,
    `- Capturado pela API em: ${texto(e.timestamp)}`,
    `- request_id: ${texto(e.request_id)}`,
    `- Requisição: \`${texto(e.method, "")} ${texto(e.path || e.route)}\` (rota ${texto(e.route)})`,
    `- Status / latência: ${texto(e.status)} / ${ehNumero(e.latency_ms) ? `${e.latency_ms} ms` : "—"}`,
    `- Código: ${texto(e.error_code)}`,
    `- Mensagem: ${texto(e.error_message)}`,
    bloco("Exceção", e.exception),
    bloco("Traceback", e.traceback),
    bloco("Details", e.details ? jsonLegivel(e.details) : "", "json"),
    "## Pedido",
    "Investigue a causa raiz e proponha a correção mínima.",
    "",
  ].join("\n");
}

function copiarDoDetalhe(tipo) {
  const e = estado.detalhe;
  if (!e) return;
  if (tipo === "pacote") copiar(pacoteClaude(e), "Pacote para o Claude");
  else if (tipo === "traceback") copiar(texto(e.traceback, ""), "Traceback");
  else copiar(`${texto(e.method, "")} ${texto(e.path || e.route)}`.trim(), "Rota");
}

function ultimoErro() {
  return estado.eventos.find((e) => CLASSES_DEFEITO.includes(e.classification));
}

// ---------------------------------------------------------------------------
// Diagnóstico por IA (evento e relatório)
// ---------------------------------------------------------------------------
const IA_ROTULOS = {
  evento: { primeiro: "Diagnosticar com IA", refazer: "Refazer diagnóstico" },
  relatorio: { primeiro: "Resumir com IA", refazer: "Refazer resumo" },
};

function chaveIA(tipo) {
  if (tipo === "evento") return estado.selecionado ? `${inicioApi()}|evento|${estado.selecionado}` : null;
  return estado.relatorioAberto ? `relatorio|${estado.relatorioAberto}` : null;
}

function corpoIA(tipo) {
  if (tipo === "evento") return estado.selecionado ? { sequence: Number(estado.selecionado) } : null;
  return estado.relatorioAberto ? { report: estado.relatorioAberto } : null;
}

function htmlIA(tipo, chave) {
  const disponivel = iaDisponivel();
  const trocas = estado.ia.cache.get(chave) || [];
  const pendente = estado.ia.pendentes.has(chave);
  const falha = estado.ia.erros.get(chave);
  const rotulos = IA_ROTULOS[tipo];
  const modelo = ((estado.status || {}).ai || {}).model;
  const botao = `<button type="button" class="principal" data-acao="ia-diagnosticar" data-alvo="${tipo}"` +
    `${pendente || !disponivel ? " disabled" : ""}>${pendente ? "Analisando…" : trocas.length ? rotulos.refazer : rotulos.primeiro}</button>`;
  const respostas = trocas.map((t, indice) =>
    `<div class="ia-troca">${t.pergunta ? `<div class="ia-pergunta">Pergunta: ${escapar(t.pergunta)}</div>` : ""}` +
    `<div class="ia-resposta">${escapar(t.resposta || "(resposta vazia)")}</div>` +
    `<div class="ia-meta"><span>${escapar(t.modelo)} · contexto de ${escapar(t.contexto)} caracteres</span>` +
    `<button type="button" class="mini" data-acao="ia-copiar" data-alvo="${tipo}" data-indice="${indice}">Copiar resposta</button></div></div>`
  ).join("");
  const acompanhamento = trocas.length && disponivel
    ? `<form class="ia-form" data-ia-form="${tipo}"><label class="sr" for="ia-pergunta-${tipo}">Pergunta de acompanhamento</label>` +
      `<input type="text" id="ia-pergunta-${tipo}" maxlength="${IA_PERGUNTA_MAX}" autocomplete="off" ` +
      `placeholder="Pergunta de acompanhamento (opcional, até ${IA_PERGUNTA_MAX} caracteres)"${pendente ? " disabled" : ""}>` +
      `<button type="submit"${pendente ? " disabled" : ""}>Perguntar</button></form>`
    : "";
  return `<div class="ia"><div class="ia-cab"><b>Análise por IA${modelo ? ` · ${escapar(modelo)}` : ""}</b>${botao}</div>` +
    `<p class="ia-aviso">O contexto é sanitizado no servidor e a IA só lê: não executa nada.</p>` +
    `${disponivel ? "" : '<p class="ia-erro">IA não habilitada nesta instância.</p>'}` +
    `${pendente ? '<p class="ia-analisando" role="status">Analisando… pode levar até 90 s.</p>' : ""}` +
    `${falha ? `<p class="ia-erro" role="alert">${escapar(falha)}</p>` : ""}${respostas}${acompanhamento}</div>`;
}

function desenharIAs() {
  ["evento", "relatorio"].forEach((tipo) => {
    const el = $(`ia-${tipo}`);
    if (!el) return;
    const chave = chaveIA(tipo);
    definirHtml(el, chave ? htmlIA(tipo, chave) : "");
  });
}

function mensagemIA(erro) {
  if (erro && erro.name === "AbortError") return `A IA não respondeu em ${IA_TIMEOUT_MS / 1000} s. Tente de novo.`;
  if (erro && erro.status === 409 && erro.code === "dev_observatory_ai_unavailable") return "IA não habilitada nesta instância.";
  if (erro && erro.status === 502) return erro.message; // dev_observatory_ai_failed: o servidor já devolve texto legível
  return (erro && erro.message) || "Falha ao consultar a IA.";
}

async function diagnosticar(tipo, pergunta) {
  const chave = chaveIA(tipo);
  const corpo = corpoIA(tipo);
  if (!chave || !corpo || estado.ia.pendentes.has(chave)) return;
  const textoPergunta = String(pergunta || "").trim().slice(0, IA_PERGUNTA_MAX);
  if (textoPergunta) corpo.question = textoPergunta;

  const controle = new AbortController();
  const limite = window.setTimeout(() => controle.abort(), IA_TIMEOUT_MS);
  estado.ia.pendentes.add(chave);
  estado.ia.erros.delete(chave);
  desenharIAs();
  try {
    const resposta = await pedir("/ai/diagnose", { method: "POST", body: JSON.stringify(corpo), signal: controle.signal });
    // Sem pergunta = análise nova (substitui o histórico); com pergunta = acompanhamento.
    const anteriores = textoPergunta ? estado.ia.cache.get(chave) || [] : [];
    estado.ia.cache.set(chave, anteriores.concat({
      pergunta: textoPergunta,
      resposta: resposta.answer,
      modelo: resposta.model,
      contexto: resposta.context_chars,
    }));
  } catch (erro) {
    estado.ia.erros.set(chave, mensagemIA(erro));
  } finally {
    window.clearTimeout(limite);
    estado.ia.pendentes.delete(chave);
    desenharIAs();
  }
}

function diagnosticarUltimoErro() {
  const evento = ultimoErro();
  if (!evento) {
    avisar("Nenhum erro capturado para diagnosticar.", "info");
    return;
  }
  irParaAba("erros");
  selecionarEvento(evento.sequence, "rolar");
  if (!iaDisponivel()) {
    avisar("IA não habilitada nesta instância.", "erro");
    return;
  }
  const chave = chaveIA("evento");
  if (estado.ia.cache.has(chave)) return; // já analisado: só reabre
  diagnosticar("evento");
}

// ---------------------------------------------------------------------------
// Chat com a IA
//
// O servidor não guarda estado: o cliente reenvia o histórico a cada pergunta.
// As bolhas são acrescentadas ao DOM uma a uma (sem reescrever a lista), para o
// leitor de tela anunciar só a fala nova. O texto entra sempre escapado.
// ---------------------------------------------------------------------------
function rotuloEvento(e) {
  return `#${e.sequence} ${texto(e.method, "")} ${texto(e.route)} ${texto(e.status)}`.replace(/\s+/g, " ").trim();
}

/** Texto escapado; blocos ``` viram <pre> simples. Sem biblioteca de markdown. */
function htmlTextoChat(conteudo) {
  return String(conteudo).split("```").map((parte, indice) => {
    if (indice % 2 === 1) {
      const codigo = parte.replace(/^[\w+#.-]{0,20}\n/, "").replace(/\n+$/, ""); // tira o nome da linguagem
      return `<pre class="bloco-codigo">${escaparLinha(codigo)}</pre>`;
    }
    const corrido = parte.replace(/^\n+|\n+$/g, "");
    return corrido ? `<div class="chat-par">${escaparLinha(corrido)}</div>` : "";
  }).join("");
}

function htmlBolha(msg, indice) {
  const ehIa = msg.papel === "assistant";
  const ehErro = msg.papel === "erro";
  const classe = ehErro ? "erro" : ehIa ? "ia" : "usuario";
  const autor = ehErro ? "Aviso" : ehIa ? `IA${msg.modelo ? ` · ${msg.modelo}` : ""}` : "Você";
  const evidencias = lista(msg.anexos).concat(msg.snapshot ? ["estado atual do observatório"] : []);
  let rodape = "";
  if (ehIa) {
    rodape = `<div class="chat-meta"><span>${ehNumero(msg.contexto) ? `contexto de ${escapar(msg.contexto)} caracteres` : ""}</span>` +
      `<button type="button" class="mini" data-acao="chat-copiar" data-indice="${indice}">Copiar</button></div>`;
  } else if (evidencias.length) {
    rodape = `<div class="chat-meta"><span>Evidências: ${escapar(evidencias.join(" · "))}</span></div>`;
  }
  return `<div class="chat-msg chat-msg-${classe}"><div class="chat-msg-cab">${escapar(autor)}</div>` +
    `${htmlTextoChat(msg.texto)}${rodape}</div>`;
}

function rolarChatAoFim() {
  const caixa = $("chat-lista");
  caixa.scrollTop = caixa.scrollHeight;
}

function ajustarAlturaCampoChat() {
  const campo = $("chat-texto");
  campo.style.height = "auto";
  if (!campo.scrollHeight) { // aba oculta: sem layout, não há como medir
    campo.style.height = "";
    return;
  }
  campo.style.height = `${Math.min(campo.scrollHeight + 2, CHAT_ALTURA_CAMPO_MAX)}px`;
}

function persistirChat() {
  const falas = estado.chat.mensagens
    .filter((m) => m.papel === "user" || m.papel === "assistant")
    .slice(-CHAT_FALAS_PERSISTIDAS)
    .map((m) => ({ papel: m.papel, texto: m.texto, modelo: m.modelo, contexto: m.contexto })); // anexos não persistem
  gravarPref(CHAT_PREF, falas);
}

function atualizarVazioChat() {
  $("chat-vazio").hidden = estado.chat.mensagens.length > 0;
}

function adicionarMensagemChat(msg) {
  const c = estado.chat;
  c.mensagens.push(msg);
  const molde = document.createElement("div");
  molde.innerHTML = htmlBolha(msg, c.mensagens.length - 1);
  $("chat-lista").append(molde.firstElementChild);
  atualizarVazioChat();
  rolarChatAoFim();
  if (msg.papel !== "erro") persistirChat(); // balão de erro é só da sessão
}

function restaurarChat() {
  const salvas = lerPref(CHAT_PREF, []);
  if (!Array.isArray(salvas)) return;
  salvas.slice(-CHAT_FALAS_PERSISTIDAS).forEach((fala) => {
    if (!fala || (fala.papel !== "user" && fala.papel !== "assistant") || typeof fala.texto !== "string" || !fala.texto) return;
    const c = estado.chat;
    const msg = { papel: fala.papel, texto: fala.texto, modelo: fala.modelo, contexto: fala.contexto };
    c.mensagens.push(msg);
    const molde = document.createElement("div");
    molde.innerHTML = htmlBolha(msg, c.mensagens.length - 1);
    $("chat-lista").append(molde.firstElementChild);
  });
  atualizarVazioChat();
}

function desenharAnexosChat() {
  definirHtml($("chat-anexos"), estado.chat.anexos.map((a) =>
    `<span class="chat-anexo"><span>${escapar(a.rotulo)}</span>` +
    `<button type="button" class="mini" data-acao="chat-remover-anexo" data-sequence="${escapar(a.sequence)}" ` +
    `aria-label="Remover anexo ${escapar(a.rotulo)}">✕</button></span>`
  ).join(""));
}

/** Estado dos controles do chat: IA disponível, requisição em curso, anexos. */
function desenharChat() {
  const c = estado.chat;
  const disponivel = iaDisponivel();
  const verificando = !estado.status;
  const aviso = $("chat-aviso-ia");
  aviso.hidden = disponivel;
  aviso.classList.toggle("ia-erro", !disponivel && !verificando);
  aviso.textContent = verificando
    ? "Verificando se a IA está disponível…"
    : "IA desligada ou sem chave nesta instância: o chat fica indisponível. Habilite a IA e reinicie a API.";

  const modelo = ((estado.status || {}).ai || {}).model;
  $("chat-modelo").hidden = !(disponivel && modelo);
  $("chat-modelo").textContent = modelo || "";

  $("chat-texto").disabled = !disponivel;
  $("chat-enviar").disabled = !disponivel || c.pendente;
  $("chat-cancelar").hidden = !c.pendente;
  $("chat-pensando").hidden = !c.pendente;
  $("chat-snapshot").disabled = !disponivel;
  $("chat-anexar-ultimo").disabled = !disponivel || c.anexos.length >= CHAT_ANEXOS_MAX;
  document.querySelectorAll('[data-acao="chat-sugestao"]').forEach((botao) => {
    botao.disabled = !disponivel;
  });
  desenharAnexosChat();
}

function entrarNoChat() {
  desenharChat();
  rolarChatAoFim();
  ajustarAlturaCampoChat();
}

function focarCampoChat() {
  const campo = $("chat-texto");
  if (!campo.disabled) campo.focus();
}

function abrirChat() {
  irParaAba("chat");
  focarCampoChat();
}

function preencherChat(sugestao) {
  const campo = $("chat-texto");
  if (campo.disabled) return;
  campo.value = sugestao || "";
  ajustarAlturaCampoChat();
  campo.focus();
  campo.setSelectionRange(campo.value.length, campo.value.length);
}

function anexarEventoChat(evento) {
  const c = estado.chat;
  const sequence = Number(evento.sequence);
  if (c.anexos.some((a) => a.sequence === sequence)) return true;
  if (c.anexos.length >= CHAT_ANEXOS_MAX) {
    avisar(`No máximo ${CHAT_ANEXOS_MAX} eventos anexados: remova um antes de anexar outro.`, "info");
    return false;
  }
  c.anexos.push({ sequence, rotulo: rotuloEvento(evento) });
  desenharChat();
  return true;
}

function anexarUltimoErro() {
  const evento = ultimoErro();
  if (!evento) {
    avisar("Nenhum erro capturado para anexar.", "info");
    return;
  }
  if (anexarEventoChat(evento)) focarCampoChat();
}

function perguntarSobreEventoAberto() {
  if (!estado.detalhe) return;
  anexarEventoChat(estado.detalhe);
  abrirChat(); // não envia nada: o usuário escreve a pergunta
}

function removerAnexoChat(sequence) {
  estado.chat.anexos = estado.chat.anexos.filter((a) => a.sequence !== sequence);
  desenharChat();
  focarCampoChat();
}

function cancelarChat() {
  const c = estado.chat;
  if (!c.pendente || !c.controle) return;
  c.motivoAbort = "usuario";
  c.controle.abort();
}

function limparChat() {
  const c = estado.chat;
  if (c.mensagens.length && !window.confirm("Limpar toda a conversa? Isso não pode ser desfeito.")) return;
  c.rodada += 1; // resposta que ainda chegar para a conversa antiga é descartada
  if (c.controle) c.controle.abort();
  c.controle = null;
  c.pendente = false;
  c.mensagens = [];
  $("chat-lista").replaceChildren();
  atualizarVazioChat();
  persistirChat();
  desenharChat();
  focarCampoChat();
}

function historicoParaEnvio() {
  return estado.chat.mensagens
    .filter((m) => (m.papel === "user" || m.papel === "assistant") && m.texto.trim())
    .slice(-CHAT_FALAS_ENVIADAS)
    .map((m) => ({ role: m.papel, content: m.texto.slice(0, CHAT_CONTEUDO_MAX) })); // limite do contrato: 4000 por fala
}

function mensagemErroChat(erro, motivo) {
  if (erro && erro.name === "AbortError") {
    return motivo === "usuario" ? "Pergunta cancelada." : `A IA não respondeu em ${IA_TIMEOUT_MS / 1000} s. Tente de novo.`;
  }
  if (erro && erro.status === 409 && erro.code === "dev_observatory_ai_unavailable") {
    return "IA desligada ou sem chave nesta instância. Habilite a IA e reinicie a API.";
  }
  if (erro && erro.status === 403) return "Pedido recusado pela proteção CSRF. Recarregue a página e tente de novo.";
  return (erro && erro.message) || "Falha ao consultar a IA.";
}

/** 404 event_not_found: tira dos anexos o que saiu da memória do recorder. */
function descartarAnexosPerdidos() {
  const c = estado.chat;
  const perdidos = c.anexos.filter((a) => !estado.eventos.some((e) => e.sequence === a.sequence));
  const remover = perdidos.length ? perdidos : c.anexos.slice(); // sem como saber qual foi: tira todos
  c.anexos = c.anexos.filter((a) => !remover.includes(a));
  return remover.map((a) => `#${a.sequence}`).join(", ");
}

async function enviarChat() {
  const c = estado.chat;
  const campo = $("chat-texto");
  if (c.pendente || !iaDisponivel()) return;
  const conteudo = campo.value.trim();
  if (!conteudo) {
    campo.focus();
    return;
  }

  const anexos = c.anexos.slice();
  adicionarMensagemChat({ papel: "user", texto: conteudo, anexos: anexos.map((a) => a.rotulo), snapshot: c.incluirSnapshot });
  campo.value = "";
  ajustarAlturaCampoChat();
  const corpo = {
    messages: historicoParaEnvio(),
    sequences: anexos.map((a) => a.sequence),
    include_snapshot: c.incluirSnapshot,
  };

  const rodada = c.rodada + 1;
  c.rodada = rodada;
  const controle = new AbortController();
  c.controle = controle;
  c.motivoAbort = "";
  const limite = window.setTimeout(() => {
    c.motivoAbort = "tempo";
    controle.abort();
  }, IA_TIMEOUT_MS);
  c.pendente = true;
  desenharChat();
  try {
    const resposta = await pedir("/ai/chat", { method: "POST", body: JSON.stringify(corpo), signal: controle.signal });
    if (rodada !== c.rodada) return;
    adicionarMensagemChat({
      papel: "assistant",
      texto: texto(resposta.answer, "(resposta vazia)"),
      modelo: resposta.model,
      contexto: resposta.context_chars,
    });
  } catch (erro) {
    if (rodada !== c.rodada) return;
    if (erro && erro.status === 404) {
      const perdidos = descartarAnexosPerdidos();
      adicionarMensagemChat({
        papel: "erro",
        texto: `Evento ${perdidos || "anexado"} saiu da memória do recorder e foi removido dos anexos. Envie a pergunta de novo.`,
      });
      avisar("Evento anexado não existe mais; anexo removido.", "info");
    } else {
      adicionarMensagemChat({ papel: "erro", texto: mensagemErroChat(erro, c.motivoAbort) });
    }
  } finally {
    window.clearTimeout(limite);
    if (rodada === c.rodada) {
      c.pendente = false;
      c.controle = null;
      desenharChat();
    }
  }
}

function registrarEventosChat() {
  const campo = $("chat-texto");
  $("chat-form").addEventListener("submit", (evento) => {
    evento.preventDefault();
    enviarChat();
  });
  campo.addEventListener("keydown", (evento) => {
    if (evento.key === "Enter" && !evento.shiftKey && !evento.isComposing) {
      evento.preventDefault();
      enviarChat();
    }
  });
  campo.addEventListener("input", ajustarAlturaCampoChat);
  $("chat-snapshot").addEventListener("change", (evento) => {
    estado.chat.incluirSnapshot = evento.target.checked;
  });
}

// ---------------------------------------------------------------------------
// Tráfego
// ---------------------------------------------------------------------------
function passaStatus(item, filtro) {
  const codigo = Number(item.status);
  switch (filtro) {
    case "2xx": return codigo >= 200 && codigo < 300;
    case "3xx": return codigo >= 300 && codigo < 400;
    case "4xx": return codigo >= 400 && codigo < 500;
    case "5xx": return codigo >= 500;
    case "lentas": return Number(item.latency_ms) >= limitesLatencia().aviso;
    default: return true;
  }
}

function desenharTrafego() {
  const lim = limitesLatencia();
  $("limites-latencia").textContent = `aviso ≥ ${lim.aviso} ms · erro ≥ ${lim.erro} ms`;
  const lentas = lista(resumoAtual().slowest_routes).map((r) => {
    const nivel = nivelLatencia(r.p95_ms);
    return `<tr><td><code>${escapar(r.method)} ${escapar(r.route)}</code></td>` +
      `<td class="num">${escapar(r.count)}</td>` +
      `<td class="num lat ${nivel}">${escapar(r.p95_ms)}</td>` +
      `<td class="num ${nivelLatencia(r.max_ms)}">${escapar(r.max_ms)}</td></tr>`;
  });
  definirHtml($("tab-lentas"), tabela(["Rota", "Chamadas", "p95 ms", "máx ms"], lentas, "Sem rota com tráfego no minuto corrente."));

  const { metodo, status } = estado.trafegoFiltro;
  const itens = estado.traffic.filter((t) =>
    (!metodo || String(t.method).toUpperCase() === metodo) && passaStatus(t, status)
  );
  const maior = Math.max(lim.erro, ...itens.map((t) => Number(t.latency_ms) || 0));
  const linhas = itens.map((t) => {
    const ms = Number(t.latency_ms) || 0;
    const nivel = nivelLatencia(ms);
    const largura = Math.max(2, Math.min(100, Math.round((ms / maior) * 100)));
    const aviso = nivel ? `<span class="sr"> acima do limite de ${nivel === "lento-erro" ? "erro" : "aviso"}</span>` : "";
    return `<tr class="${nivel}"><td>${hora(t.timestamp)}</td>` +
      `<td><code>${escapar(t.method)} ${escapar(t.route)}</code></td>` +
      `<td class="num">${escapar(t.status)}</td>` +
      `<td class="num-lat lat ${nivel}">${escapar(ehNumero(t.latency_ms) ? Math.round(ms) : "—")} ms${aviso}` +
      `<span class="barra" aria-hidden="true"><i class="b-${escapar(t.classification)}" data-w="${largura}"></i></span></td>` +
      `<td><span class="cls cls-${escapar(t.classification)}">${escapar(t.classification)}</span></td></tr>`;
  });
  const vazio = estado.traffic.length ? "Nenhuma requisição com esses filtros." : "Sem tráfego registrado ainda.";
  definirHtml($("stream"), tabela(["Hora", "Rota", "Status", "Latência", "Classe"], linhas, vazio));
}

// ---------------------------------------------------------------------------
// Turnos e relatórios
// ---------------------------------------------------------------------------
async function desenharTurnos() {
  const dados = await pedir("/shifts");
  estado.turnos = dados;
  definirHtml($("turnos"), lista(dados.windows).map((janela) => {
    const rotulo = janela.report ? "Regerar relatório" : "Gerar relatório";
    return `
        <div class="turno ${janela.current ? "atual" : ""}">
          <b>${escapar(janela.label)}</b>
          <small>${escapar(String(janela.start).slice(11, 16))} → ${escapar(String(janela.end).slice(11, 16))} ·
            ${janela.closed ? "encerrado" : janela.current ? "em curso" : "ainda não começou"} ·
            ${janela.report ? "relatório gravado" : "sem relatório"}</small>
          <button type="button" data-acao="gerar-relatorio" data-turno="${escapar(janela.key)}" data-dia="${escapar(dados.day)}"
                  data-force="${janela.report ? "1" : "0"}">${rotulo}</button>
        </div>`;
  }).join(""));
}

function desenharListaRelatorios() {
  const dados = estado.relatorios;
  if (!dados) return;
  const linhas = lista(dados.items).map((item) => {
    const resumo = item.summary || {};
    const atual = item.name === estado.relatorioAberto;
    return (
      `<tr class="${atual ? "atual" : ""}"><td><button type="button" class="link" data-acao="abrir-relatorio" ` +
      `data-relatorio="${escapar(item.name)}"${atual ? ' aria-current="true"' : ""}>${escapar(item.name)}</button>` +
      `<div class="rotulo">${escapar(item.generated_at)}</div></td>` +
      `<td class="num">${escapar(resumo.defects === undefined ? "—" : resumo.defects)}</td>` +
      `<td class="num">${escapar(resumo.expected_blocks === undefined ? "—" : resumo.expected_blocks)}</td></tr>`
    );
  });
  definirHtml($("relatorios"), tabela(["Relatório", "Defeitos", "Bloqueios"], linhas, `Nenhum relatório em ${texto(dados.directory)}.`));
}

async function desenharRelatorios() {
  estado.relatorios = await pedir("/reports");
  desenharListaRelatorios();
}

async function carregarRelatorios() {
  estado.relatoriosCarregado = true;
  await blocoMonitorado("relatorios", ["relatorios"], Promise.all([desenharTurnos(), desenharRelatorios()]));
}

async function abrirRelatorio(nome) {
  try {
    const conteudo = await pedir(`/reports/${encodeURIComponent(nome)}`);
    estado.relatorioAberto = nome;
    estado.relatorioTexto = String(conteudo);
    $("relatorio-conteudo").textContent = estado.relatorioTexto;
    $("relatorio-copiar").disabled = false;
    desenharListaRelatorios();
    desenharIAs();
  } catch (erro) {
    avisar(erro.message, "erro");
  }
}

async function gerarRelatorioDe(parametros, botao) {
  const rotuloOriginal = botao ? botao.textContent : "";
  if (botao) {
    botao.disabled = true;
    botao.textContent = "Gerando…";
  }
  try {
    const resposta = await pedir("/reports", { method: "POST", body: JSON.stringify(parametros) });
    await Promise.all([desenharTurnos(), desenharRelatorios()]);
    await abrirRelatorio(resposta.name);
    avisar("Relatório gerado.", "ok");
    return true;
  } catch (erro) {
    avisar(erro.message, "erro");
    if (botao) {
      botao.disabled = false;
      botao.textContent = rotuloOriginal;
    }
    return false;
  }
}

async function gerarRelatorioAtual() {
  if (!estado.turnos) await desenharTurnos().catch((erro) => avisar(erro.message, "erro"));
  const janela = estado.turnos && lista(estado.turnos.windows).find((j) => j.current);
  if (!janela) {
    avisar("Fora de turno: não há turno corrente para gerar.", "info");
    return;
  }
  irParaAba("relatorios");
  await gerarRelatorioDe({ day: estado.turnos.day, shift: janela.key, force: Boolean(janela.report) });
}

// ---------------------------------------------------------------------------
// Ciclo de atualização
// ---------------------------------------------------------------------------
function buscarMetricas() {
  const ambiente = estado.ambiente;
  return pedir(`/metrics?env=${encodeURIComponent(ambiente)}`).then((dados) => {
    if (ambiente === estado.ambiente) receberMetricas(dados); // resposta de outro ambiente é descartada
  });
}

async function atualizar() {
  if (estado.atualizando) {
    estado.repetir = true;
    return;
  }
  estado.atualizando = true;
  const ambiente = estado.ambiente;
  const consulta = `?env=${encodeURIComponent(ambiente)}`;
  try {
    await Promise.all([
      blocoMonitorado("status", ["num-api", "kpis", "tab-lentas"], pedir("/status").then(desenharStatus)),
      blocoMonitorado("metricas", ["num-banco", "num-processo", "tab-idle", "tab-bloqueios", "tab-queries"], buscarMetricas()),
      blocoMonitorado("postos", ["postos"], pedir(`/viewports${consulta}`).then((dados) => {
        if (ambiente === estado.ambiente) receberPostos(dados);
      })),
      blocoMonitorado("eventos", ["erros-lista", "stream", "atencao"], pedir(`/events?limit=${EVENTOS_LIMITE}`).then(receberEventos)),
    ]);
  } finally {
    estado.atualizando = false;
    if (estado.repetir) {
      estado.repetir = false;
      atualizar();
    }
  }
}

function reprogramar() {
  window.clearInterval(estado.timer);
  if (estado.intervalo > 0) {
    estado.timer = window.setInterval(atualizar, estado.intervalo);
  }
}

function definirIntervalo(ms) {
  if (!INTERVALOS_MS.includes(ms)) return;
  estado.intervalo = ms;
  $("intervalo").value = String(ms);
  gravarPref("intervalo", ms);
  reprogramar();
}

// ---------------------------------------------------------------------------
// Abas
// ---------------------------------------------------------------------------
function irParaAba(id, sequence) {
  const aba = ABAS.some((a) => a.id === id) ? id : "geral";
  estado.aba = aba;
  gravarPref("aba", aba);
  document.querySelectorAll('[role="tab"]').forEach((botao) => {
    const ativa = botao.dataset.aba === aba;
    botao.setAttribute("aria-selected", String(ativa));
    botao.tabIndex = ativa ? 0 : -1;
  });
  document.querySelectorAll("[data-painel]").forEach((painel) => {
    painel.hidden = painel.dataset.painel !== aba;
  });
  if (window.location.hash !== `#${aba}`) window.location.hash = aba;
  if (aba === "relatorios" && estado.relatoriosCarregado) carregarRelatorios();
  if (aba === "chat") entrarNoChat();
  if (sequence) selecionarEvento(sequence, "rolar");
}

function abaDoHash() {
  const id = window.location.hash.replace(/^#/, "");
  return ABAS.some((a) => a.id === id) ? id : null;
}

function focarBusca() {
  if (estado.aba !== "postos") irParaAba("erros");
  const campo = $(estado.aba === "postos" ? "busca-postos" : "busca-erros");
  campo.focus();
  campo.select();
}

// ---------------------------------------------------------------------------
// Filtros
// ---------------------------------------------------------------------------
function alternarClasse(classe) {
  const atuais = estado.filtros.classes;
  estado.filtros.classes = atuais.includes(classe) ? atuais.filter((c) => c !== classe) : atuais.concat(classe);
  gravarPref("classes", estado.filtros.classes);
  desenharErros();
}

function limparFiltros() {
  estado.filtros.classes = [];
  estado.filtros.busca = "";
  estado.trafegoFiltro = { metodo: "", status: "" };
  estado.postosFiltro = { busca: "", categoria: "" };
  gravarPref("classes", []);
  $("busca-erros").value = "";
  $("busca-postos").value = "";
  $("filtro-metodo").value = "";
  $("filtro-status").value = "";
  desenharErros();
  desenharTrafego();
  desenharPostos();
  avisar("Filtros limpos.", "ok");
}

// ---------------------------------------------------------------------------
// Paleta de comandos
// ---------------------------------------------------------------------------
function comandos() {
  const itens = ABAS.map((aba, indice) => ({
    rotulo: `Ir para ${aba.rotulo}`,
    dica: indice < ABAS_COM_ATALHO ? String(indice + 1) : "",
    exec: () => irParaAba(aba.id),
  }));
  const outroAmbiente = estado.ambiente === "test" ? "real" : "test";
  itens.push({ rotulo: `Alternar ambiente para ${outroAmbiente === "real" ? "REAL (somente leitura)" : "TESTE"}`, exec: () => definirAmbiente(outroAmbiente) });
  itens.push({ rotulo: "Atualizar agora", exec: atualizar });
  INTERVALOS_MS.forEach((ms) => itens.push({
    rotulo: `Intervalo de atualização: ${ms ? `${ms / 1000} s` : "manual"}`,
    exec: () => definirIntervalo(ms),
  }));
  itens.push({ rotulo: "Gerar relatório do turno atual", exec: gerarRelatorioAtual });
  itens.push({
    rotulo: "Copiar pacote do último erro (p/ Claude)",
    exec: () => {
      const evento = ultimoErro();
      if (evento) copiar(pacoteClaude(evento), "Pacote para o Claude");
      else avisar("Nenhum erro capturado.", "info");
    },
  });
  itens.push({ rotulo: "Diagnosticar último erro com IA", exec: diagnosticarUltimoErro });
  itens.push({ rotulo: "Abrir chat", exec: abrirChat });
  itens.push({ rotulo: "Limpar filtros", exec: limparFiltros });
  itens.push({ rotulo: "Marcar erros como vistos", exec: marcarVistos });
  itens.push({ rotulo: "Mostrar atalhos de teclado", dica: "?", exec: () => abrirDialogo($("atalhos")) });
  return itens;
}

function desenharPaleta() {
  const { itens, ativo } = estado.paleta;
  $("paleta-lista").innerHTML = itens.length
    ? itens.map((c, i) =>
        `<li role="option" id="cmd-${i}" class="${i === ativo ? "ativo" : ""}" aria-selected="${i === ativo}" ` +
        `data-acao="executar-comando" data-indice="${i}"><span>${escapar(c.rotulo)}</span>${c.dica ? `<kbd>${escapar(c.dica)}</kbd>` : ""}</li>`
      ).join("")
    : '<li class="vazio" role="presentation">Nenhum comando encontrado.</li>';
  $("paleta-busca").setAttribute("aria-activedescendant", itens.length ? `cmd-${ativo}` : "");
  const atual = $(`cmd-${ativo}`);
  if (atual) atual.scrollIntoView({ block: "nearest" });
}

function filtrarPaleta() {
  const termo = normalizar($("paleta-busca").value);
  estado.paleta.itens = estado.paleta.todos.filter((c) => normalizar(c.rotulo).includes(termo));
  estado.paleta.ativo = 0;
  desenharPaleta();
}

function abrirPaleta() {
  const dialogo = $("paleta");
  if (dialogo.open) {
    dialogo.close();
    return;
  }
  $("paleta-busca").value = "";
  estado.paleta.todos = comandos();
  filtrarPaleta();
  abrirDialogo(dialogo);
  $("paleta-busca").focus();
}

function executarComando(indice) {
  const comando = estado.paleta.itens[indice];
  $("paleta").close();
  if (comando) comando.exec();
}

function teclaPaleta(evento) {
  const total = estado.paleta.itens.length;
  if (evento.key === "ArrowDown" || evento.key === "ArrowUp") {
    evento.preventDefault();
    if (!total) return;
    estado.paleta.ativo = (estado.paleta.ativo + (evento.key === "ArrowDown" ? 1 : -1) + total) % total;
    desenharPaleta();
  } else if (evento.key === "Enter") {
    evento.preventDefault();
    if (total) executarComando(estado.paleta.ativo);
  }
}

// ---------------------------------------------------------------------------
// Eventos de interface (delegação)
// ---------------------------------------------------------------------------
function preencherModelosIa() {
  const ia = (estado.status || {}).ai || {};
  const provedor = $("ia-config-provedor").value;
  $("ia-config-modelos").innerHTML = ((ia.suggestions || {})[provedor] || [])
    .map((m) => `<option value="${escapar(m)}"></option>`).join("");
}

function abrirConfigIa() {
  const ia = (estado.status || {}).ai || {};
  $("ia-config-provedor").value = ia.configured_provider || "nvidia";
  $("ia-config-modelo").value = ia.model || "";
  $("ia-config-chave").value = "";
  $("ia-config-erro").textContent = "";
  $("ia-config-estado").textContent = ia.key_set
    ? `Chave ${ia.from_screen ? "salva pela tela" : "do .env"} em uso.`
    : "Nenhuma chave configurada.";
  preencherModelosIa();
  abrirDialogo($("dialogo-ia"));
}

async function salvarConfigIa(evento) {
  evento.preventDefault();
  const botao = $("ia-config-salvar");
  botao.disabled = true;
  $("ia-config-erro").textContent = "";
  try {
    await pedir("/ai/config", {
      method: "PUT",
      body: JSON.stringify({
        provider: $("ia-config-provedor").value,
        model: $("ia-config-modelo").value,
        api_key: $("ia-config-chave").value,
      }),
    });
    $("ia-config-chave").value = "";
    $("dialogo-ia").close();
    avisar("IA atualizada.", "ok");
    atualizar();
  } catch (erro) {
    $("ia-config-erro").textContent = erro.message;
  } finally {
    botao.disabled = false;
  }
}

async function voltarIaParaEnv() {
  try {
    await pedir("/ai/config", { method: "DELETE" });
    $("dialogo-ia").close();
    avisar("IA voltou à configuração do .env.", "ok");
    atualizar();
  } catch (erro) {
    $("ia-config-erro").textContent = erro.message;
  }
}

const ACOES = {
  "ia-config": () => abrirConfigIa(),
  "ia-config-reset": () => voltarIaParaEnv(),
  ir: (el) => irParaAba(el.dataset.aba, el.dataset.sequence),
  ambiente: (el) => definirAmbiente(el.dataset.ambiente),
  atualizar: () => atualizar(),
  paleta: () => abrirPaleta(),
  "executar-comando": (el) => executarComando(Number(el.dataset.indice)),
  "fechar-dialogo": (el) => $(el.dataset.dialogo).close(),
  "selecionar-evento": (el) => selecionarEvento(el.dataset.sequence),
  "fechar-detalhe": () => fecharDetalhe(),
  "chip-classe": (el) => alternarClasse(el.dataset.classe),
  "chip-posto": (el) => {
    estado.postosFiltro.categoria = estado.postosFiltro.categoria === el.dataset.categoria ? "" : el.dataset.categoria;
    desenharPostos();
  },
  "limpar-filtros": () => limparFiltros(),
  "marcar-vistos": () => marcarVistos(),
  "copiar-pacote": () => copiarDoDetalhe("pacote"),
  "copiar-traceback": () => copiarDoDetalhe("traceback"),
  "copiar-rota": () => copiarDoDetalhe("rota"),
  "copiar-query": (el) => copiar(el.dataset.copiar, "Query"),
  "encerrar-sessao": (el) => abrirEncerrar(Number(el.dataset.pid)),
  "confirmar-encerrar": () => confirmarEncerrar(),
  "ia-diagnosticar": (el) => diagnosticar(el.dataset.alvo),
  "ia-copiar": (el) => {
    const trocas = estado.ia.cache.get(chaveIA(el.dataset.alvo)) || [];
    const troca = trocas[Number(el.dataset.indice)];
    if (troca) copiar(troca.resposta || "", "Resposta da IA");
  },
  "perguntar-ia": () => perguntarSobreEventoAberto(),
  "chat-limpar": () => limparChat(),
  "chat-cancelar": () => cancelarChat(),
  "chat-copiar": (el) => {
    const msg = estado.chat.mensagens[Number(el.dataset.indice)];
    if (msg) copiar(msg.texto, "Resposta da IA");
  },
  "chat-sugestao": (el) => preencherChat(el.dataset.texto),
  "chat-anexar-ultimo": () => anexarUltimoErro(),
  "chat-remover-anexo": (el) => removerAnexoChat(Number(el.dataset.sequence)),
  "abrir-relatorio": (el) => abrirRelatorio(el.dataset.relatorio),
  "gerar-relatorio": (el) => gerarRelatorioDe(
    { day: el.dataset.dia, shift: el.dataset.turno, force: el.dataset.force === "1" },
    el,
  ),
  "gerar-relatorio-atual": () => gerarRelatorioAtual(),
  "copiar-relatorio": () => copiar(estado.relatorioTexto, "Markdown do relatório"),
};

function aoClicar(evento) {
  if (evento.target instanceof HTMLDialogElement) {
    evento.target.close(); // clique no fundo escurecido
    return;
  }
  const el = evento.target.closest("[data-acao]");
  if (!el || el.disabled) return;
  const acao = ACOES[el.dataset.acao];
  if (acao) acao(el, evento);
}

function aoPressionar(evento) {
  const comModificador = evento.ctrlKey || evento.metaKey;
  if (comModificador && String(evento.key).toLowerCase() === "k") {
    evento.preventDefault();
    abrirPaleta();
    return;
  }
  if (evento.target && evento.target.getAttribute && evento.target.getAttribute("role") === "tab") {
    if (teclaAbas(evento)) return;
  }
  if (document.querySelector("dialog[open]")) return; // o diálogo cuida do Esc e do foco
  const campo = ehCampo(evento.target);
  if (evento.key === "Escape") {
    if (campo && evento.target.type === "search" && evento.target.value) {
      evento.target.value = "";
      evento.target.dispatchEvent(new Event("input", { bubbles: true }));
    } else if (campo) {
      evento.target.blur();
    } else if (estado.aba === "erros") {
      fecharDetalhe();
    }
    return;
  }
  if (campo || comModificador || evento.altKey) return;
  const tecla = evento.key;
  if (tecla === "/") {
    evento.preventDefault();
    focarBusca();
  } else if (tecla === "?") {
    abrirDialogo($("atalhos"));
  } else if (/^[1-6]$/.test(tecla)) {
    irParaAba(ABAS[Number(tecla) - 1].id);
  } else if (estado.aba === "erros" && (tecla === "j" || tecla === "ArrowDown")) {
    evento.preventDefault();
    moverSelecao(1);
  } else if (estado.aba === "erros" && (tecla === "k" || tecla === "ArrowUp")) {
    evento.preventDefault();
    moverSelecao(-1);
  }
}

/** Setas/Home/End entre as abas (padrão WAI-ARIA tabs). */
function teclaAbas(evento) {
  const abas = [...document.querySelectorAll('[role="tab"]')];
  const atual = abas.indexOf(evento.target);
  let destino = -1;
  if (evento.key === "ArrowRight") destino = (atual + 1) % abas.length;
  else if (evento.key === "ArrowLeft") destino = (atual - 1 + abas.length) % abas.length;
  else if (evento.key === "Home") destino = 0;
  else if (evento.key === "End") destino = abas.length - 1;
  if (destino === -1) return false;
  evento.preventDefault();
  abas[destino].focus();
  irParaAba(abas[destino].dataset.aba);
  return true;
}

function registrarEventos() {
  document.addEventListener("click", aoClicar);
  $("ia-config-form").addEventListener("submit", salvarConfigIa);
  $("ia-config-provedor").addEventListener("change", preencherModelosIa);
  document.addEventListener("keydown", aoPressionar);
  document.addEventListener("submit", (evento) => {
    const tipo = evento.target.dataset && evento.target.dataset.iaForm;
    if (!tipo) return;
    evento.preventDefault();
    const campo = evento.target.querySelector("input");
    diagnosticar(tipo, campo ? campo.value : "");
  });
  window.addEventListener("hashchange", () => {
    const aba = abaDoHash();
    if (aba && aba !== estado.aba) irParaAba(aba);
  });

  $("intervalo").addEventListener("change", (evento) => definirIntervalo(Number(evento.target.value)));
  $("busca-erros").addEventListener("input", (evento) => {
    estado.filtros.busca = evento.target.value;
    desenharErros();
  });
  $("busca-postos").addEventListener("input", (evento) => {
    estado.postosFiltro.busca = evento.target.value;
    desenharPostos();
  });
  $("agrupar").addEventListener("change", (evento) => {
    estado.filtros.agrupar = evento.target.checked;
    gravarPref("agrupar", estado.filtros.agrupar);
    desenharErros();
  });
  $("filtro-metodo").addEventListener("change", (evento) => {
    estado.trafegoFiltro.metodo = evento.target.value;
    desenharTrafego();
  });
  $("filtro-status").addEventListener("change", (evento) => {
    estado.trafegoFiltro.status = evento.target.value;
    desenharTrafego();
  });
  $("paleta-busca").addEventListener("input", filtrarPaleta);
  $("paleta-busca").addEventListener("keydown", teclaPaleta);
}

// ---------------------------------------------------------------------------
// Início
// ---------------------------------------------------------------------------
function carregarPreferencias() {
  const intervalo = Number(lerPref("intervalo", estado.intervalo));
  if (INTERVALOS_MS.includes(intervalo)) estado.intervalo = intervalo;
  $("intervalo").value = String(estado.intervalo);

  const classes = lerPref("classes", []);
  const validas = CLASSES_FILTRO.map(([classe]) => classe);
  estado.filtros.classes = Array.isArray(classes) ? classes.filter((c) => validas.includes(c)) : [];
  estado.filtros.agrupar = lerPref("agrupar", false) === true;
  $("agrupar").checked = estado.filtros.agrupar;
}

function iniciar() {
  carregarPreferencias();
  aplicarAmbiente();
  registrarEventos();
  desenharBanco();
  desenharPostos();
  desenharErros();
  desenharDetalhe();
  desenharTrafego();
  desenharGeral();
  registrarEventosChat();
  restaurarChat();
  desenharChat();
  const prefAba = lerPref("aba", "geral");
  irParaAba(abaDoHash() || (ABAS.some((a) => a.id === prefAba) ? prefAba : "geral"));
  atualizar();
  carregarRelatorios();
  reprogramar();
}

document.addEventListener("DOMContentLoaded", iniciar);
