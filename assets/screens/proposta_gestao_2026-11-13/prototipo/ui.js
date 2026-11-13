// Protótipo da proposta de gestão — helpers, ícones, contas e moldura (sidebar + topo).
const P = {
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M9.5 21v-6h5v6"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  clipboard: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1"/><path d="M9 11h6M9 15h4"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  shield: '<path d="M12 3 4 6v6c0 4.5 3.4 8 8 9 4.6-1 8-4.5 8-9V6z"/><path d="m9 12 2 2 4-4"/>',
  file: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
  pin: '<path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>',
  ruler: '<path d="M3 17 17 3l4 4L7 21z"/><path d="m7 13 2 2M10 10l2 2M13 7l2 2"/>',
  brief: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M3 13h18"/>',
  bulb: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"/>',
  factory: '<path d="M3 21V10l6 4V10l6 4V6l6 3v12z"/><path d="M7 17h2M12 17h2M17 17h2"/>',
  sliders: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  wrench: '<path d="M15 4a5 5 0 0 0-4.6 7L3 18.4 5.6 21l7.4-7.4A5 5 0 0 0 20 9l-3 1-3-3 1-3z"/>',
  bell: '<path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14"/><path d="M12 17.5h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5h.01"/>',
  warn: '<path d="M10.3 4 2.5 18a2 2 0 0 0 1.7 3h15.6a2 2 0 0 0 1.7-3L13.7 4a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
  err: '<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/>',
  ok: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  up: '<path d="m6 15 6-6 6 6"/>',
  down: '<path d="m6 9 6 6 6-6"/>',
  chev: '<path d="m9 6 6 6-6 6"/>',
  download: '<path d="M12 4v11M7 10l5 5 5-5M5 20h14"/>',
  filter: '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.9-3M4 4v4h4M4 13a8 8 0 0 0 14.9 3M20 20v-4h-4"/>',
  mega: '<path d="M3 10v4h4l6 4V6L7 10z"/><path d="M16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11"/>',
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
  users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M21.5 20a6.5 6.5 0 0 0-4-6"/>',
  idcard: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="11" r="2.2"/><path d="M5.8 16a3.4 3.4 0 0 1 6.4 0M14 10h4M14 13h3"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  send: '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4z"/>',
  server: '<rect x="3" y="4" width="18" height="7" rx="1.5"/><rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 7.5h.01M7 16.5h.01"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
  box: '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
  moon: '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
  gauge: '<path d="M12 14l4-4"/><path d="M3.3 17a9 9 0 1 1 17.4 0"/>',
  trend: '<path d="m3 17 6-6 4 4 8-8M15 7h6v6"/>',
  money: '<path d="M12 2v20M17 6.5C17 4.6 14.8 4 12 4s-5 .9-5 3 2 3 5 3.5 5 1.3 5 3.5-2.2 3-5 3-5-.6-5-2.5"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
  play: '<path d="M7 4v16l13-8z"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3.6-3.6a4 4 0 0 0-5.7-5.7L12 6.3"/><path d="M14 10a4 4 0 0 0-5.7 0l-3.6 3.6a4 4 0 0 0 5.7 5.7l1.6-1.6"/>',
};
const ic = (n, cls = "") => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${P[n] || ""}</svg>`;

// ---------- peças reutilizáveis ----------
const st = (kind, text) => `<span class="st ${kind}">${text}</span>`;
const STATE = {
  prod: () => st("ok", "Produzindo"),
  setup: () => st("setup", "Em setup"),
  stop: (m) => st("stop", m ? `Parado · ${m}` : "Parado"),
  wait: () => st("wait", "Sem OP"),
  off: () => st("off", "Fora do turno"),
  maint: () => st("maint", "Manutenção"),
  rework: () => st("rework", "Retrabalho"),
};

function kpi({ label, value, unit = "", cmp, cmpDir = "flat", say, bar, goal, tone = "", na = false, help = true }) {
  const arrow = cmpDir === "up" ? ic("up", "sm") : cmpDir === "down" ? ic("down", "sm") : "";
  return `<div class="kpi ${tone ? "st-" + tone : ""}">
    <div class="lbl">${label}${help ? `<span class="q" title="Como é calculado">${ic("help", "sm")}</span>` : ""}</div>
    <div class="val ${na ? "na" : ""}">${value}${unit ? `<small>${unit}</small>` : ""}</div>
    ${bar != null ? `<div class="bar"><i style="width:${bar}%;background:${tone === "bad" ? "var(--stop)" : tone === "warn" ? "var(--wait)" : tone === "ok" ? "var(--ok)" : "var(--primary)"}"></i>${goal != null ? `<span class="goal" style="left:${goal}%"></span>` : ""}</div>` : ""}
    ${cmp ? `<div class="cmp ${cmpDir === "up" ? "up" : cmpDir === "down" ? "down" : "flat"}">${arrow}${cmp}</div>` : ""}
    ${say ? `<div class="say">${say}</div>` : ""}
  </div>`;
}
const kpis = (n, items) => `<div class="kpis" style="--n:${n}">${items.join("")}</div>`;

function notice(kind, title, text, actions = "", code = "") {
  const icon = { info: "info", warn: "warn", err: "err", ok: "ok" }[kind];
  return `<div class="notice ${kind}" role="${kind === "err" ? "alert" : "status"}">${ic(icon)}<b>${title}</b>${actions ? `<div class="act">${actions}</div>` : ""}<p>${text}</p>${code ? `<div class="code">${code}</div>` : ""}</div>`;
}
const empty = (title, text, icon = "info") => `<div class="empty">${ic(icon)}<div><b>${title}</b><span>${text}</span></div></div>`;

function card(title, body, { sub = "", right = "", foot = "", flush = false, cls = "" } = {}) {
  return `<section class="card ${cls}"><div class="card-h"><h3>${title}</h3>${sub ? `<span class="sub">${sub}</span>` : ""}${right ? `<div class="r">${right}</div>` : ""}</div><div class="card-b ${flush ? "flush" : ""}">${body}</div>${foot ? `<div class="card-f">${foot}</div>` : ""}</section>`;
}

function table(cols, rows, { foot = "" } = {}) {
  const th = cols.map((c) => `<th class="${c.n ? "n" : ""}">${c.t}</th>`).join("");
  const tr = rows.map((r) => {
    const cls = r._cls || "";
    const cells = (r._cells || r).map((v, i) => `<td class="${cols[i] && cols[i].n ? "n" : ""} ${v === "—" ? "dim" : ""}">${v}</td>`).join("");
    return `<tr class="${cls}">${cells}</tr>`;
  }).join("");
  return `<table><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table>${foot ? `<div class="tfoot">${foot}</div>` : ""}`;
}
const flag = (cells) => ({ _cls: "flag", _cells: cells });
const warnRow = (cells) => ({ _cls: "warnrow", _cells: cells });

function brief(sentence, bullets = [], meta = "") {
  return `<div class="brief"><h2>${sentence}</h2>${meta ? `<div class="meta">${meta}</div>` : ""}${bullets.length ? `<ul>${bullets.map((b) => `<li>${b}</li>`).join("")}</ul>` : ""}</div>`;
}

function filters(opts = {}) {
  const { period = true, sector = true, chips = [], extra = "", search = "" } = opts;
  const per = period ? `<div class="seg">${["Hoje", "Ontem", "7 dias", "30 dias", "Este mês"].map((p, i) => `<button class="${i === (opts.on ?? 0) ? "on" : ""}">${p}</button>`).join("")}</div>` : "";
  const sec = sector ? `<span class="field">${ic("factory", "sm")}<small>Setor</small> ${opts.sectorValue || "Todos"} ${ic("down", "sm")}</span>` : "";
  const srch = search ? `<span class="field" style="min-width:260px">${ic("search", "sm")}<small>${search}</small></span>` : "";
  const ch = chips.map((c) => `<span class="chip">${c}${ic("x", "sm")}</span>`).join("");
  return `<div class="filters">${per}${sec}${srch}${extra}${ch}<span class="grow"></span><button class="btn">${ic("filter", "sm")}Mais filtros</button></div>`;
}

function gloss(items, n = 3) {
  return card("Entenda os números desta tela", `<dl class="gloss" style="--gn:${n}">${items.map(([t, d]) => `<div><dt>${t}</dt><dd>${d}</dd></div>`).join("")}</dl>`, { right: `<span class="sub">Explicação em palavras simples</span>` });
}

const hb = (label, pct, value, color = "var(--primary)") => `<div class="hb"><span>${label}</span><div class="t"><i style="width:${pct}%;background:${color}"></i></div><span class="v">${value}</span></div>`;

// ---------- seções do menu ----------
const SECTIONS = {
  home: { label: "Tela inicial", icon: "home", group: "Acompanhar", tabs: [["home-overview", "Visão Geral"], ["home-ai", "IA"], ["home-calls", "Chamadas da Gestão"]] },
  panels: { label: "Painéis Operacionais", icon: "grid", group: "Acompanhar", tabs: [["panels-andon", "Andon"], ["panels-map", "Mapa da fábrica"], ["panels-pauses", "Pausas"]] },
  operations: { label: "Consulta Operacional", icon: "search", group: "Acompanhar", tabs: [["ops-overview", "Visão Geral"], ["ops-resources", "Recursos"], ["ops-orders", "OPs em andamento"]] },
  production: { label: "Produção", icon: "clipboard", group: "Analisar", tabs: [["prod-orders", "Consulta de OP"], ["prod-exec", "Execução das OPs"], ["prod-done", "Produção realizada"], ["prod-plan", "Planejado × Realizado"]] },
  analytics: { label: "Análises", icon: "chart", group: "Analisar", tabs: [["an-hours", "Horas & Utilização"]] },
  audit: { label: "Auditoria", icon: "shield", group: "Analisar", tabs: [["audit", "Auditoria analítica"]] },
  reports: { label: "Relatórios", icon: "file", group: "Analisar", tabs: [["reports", "Relatórios"]] },
  trace: { label: "Rastreabilidade", icon: "pin", group: "Analisar", tabs: [["trace-op", "OP / Produto"], ["trace-nest", "Lote / Material / Nesting"]] },
  quality: { label: "Qualidade", icon: "ruler", group: "Minha área", tabs: [["q-cotas", "Cotas padrão"], ["q-spc", "SPC"], ["q-rnc", "Decisão de RNC"]] },
  director: { label: "Diretoria", icon: "brief", group: "Minha área", tabs: [["director", "Custo por produto"]] },
  improve: { label: "Melhoria Contínua", icon: "bulb", group: "Minha área", tabs: [["improve", "Oportunidades"]] },
  area: { label: "Serra", icon: "factory", group: "Minha área", tabs: [["area-serra", "Recursos"]] },
  maint: { label: "Manutenção", icon: "wrench", group: "Minha área", tabs: [["maint", "Chamados e sugestões"]] },
  dev: { label: "Admin", icon: "sliders", group: "Administração", tabs: [["dev-badges", "Crachás"], ["dev-users", "Cadastro"], ["dev-calls", "Chamadas do Admin"], ["dev-shifts", "Turnos"], ["dev-sector", "Apontamento por setor"], ["dev-changes", "Alterações"], ["dev-protheus", "Envios ao Protheus"], ["dev-system", "Sistema"]] },
};
const COMMON = ["home", "panels", "operations", "production", "analytics", "audit", "reports", "trace"];

const ACCOUNTS = {
  gestor: { name: "Gestor de exemplo", role: "Gestão", initials: "GE", sections: COMMON },
  gerente: { name: "Gerente de exemplo", role: "Gerente industrial", initials: "GI", sections: COMMON },
  lider: { name: "Líder de exemplo", role: "Líder · Serra", initials: "LS", sections: [...COMMON, "area"] },
  manufatura: { name: "Manufatura de exemplo", role: "Engenharia de manufatura", initials: "EM", sections: COMMON },
  qualidade: { name: "Qualidade de exemplo", role: "Qualidade", initials: "QA", sections: [...COMMON, "quality"] },
  diretoria: { name: "Diretoria de exemplo", role: "Diretoria", initials: "DI", sections: [...COMMON, "director"] },
  melhoria: { name: "Melhoria de exemplo", role: "Melhoria Contínua", initials: "MC", sections: [...COMMON, "improve"] },
  manutencao: { name: "Mantenedor de exemplo", role: "Manutenção", initials: "MT", sections: ["maint"] },
  admin: { name: "Admin de exemplo", role: "Administrador", initials: "AD", sections: [...COMMON, "quality", "director", "improve", "dev"] },
};

function sectionOf(screen) {
  return Object.entries(SECTIONS).find(([, s]) => s.tabs.some(([id]) => id === screen))?.[0];
}

function shell(accId, screen, content) {
  const acc = ACCOUNTS[accId];
  const secId = sectionOf(screen);
  const sec = SECTIONS[secId];
  let lastGroup = "";
  const nav = acc.sections.map((id) => {
    const s = SECTIONS[id];
    const g = s.group !== lastGroup ? `<div class="nav-group">${s.group}</div>` : "";
    lastGroup = s.group;
    const count = id === "home" && accId !== "manutencao" ? `<span class="count">3</span>` : "";
    return `${g}<a class="${id === secId ? "on" : ""}">${ic(s.icon)}${s.label}${count}</a>`;
  }).join("");
  const tabs = sec.tabs.map(([id, label]) => {
    const badge = id === "home-calls" ? `<span class="badge">2 novas</span>` : id === "q-rnc" ? `<span class="badge">4 aguardando</span>` : "";
    return `<a class="${id === screen ? "on" : ""}">${label}${badge}</a>`;
  }).join("");
  const tabLabel = sec.tabs.find(([id]) => id === screen)[1];
  return `<div class="app">
  <aside class="side">
    <div class="brand"><img src="../../../branding/logo_gestor_pecas.png" alt="Gestor de Peças"></div>
    <div class="profile"><div class="avatar">${acc.initials}</div><div><b>${acc.name}</b><small>${acc.role}</small></div><span class="bell">${ic("bell")}<span class="dot">3</span></span></div>
    <nav class="nav">${nav}</nav>
    <div class="side-foot">
      <div class="conn">
        <div><span class="led"></span>Protheus<span class="s">conectado</span></div>
        <div><span class="led"></span>SigmaNEST<span class="s">há 2 min</span></div>
        <div><span class="led"></span>Dados da fábrica<span class="s">ao vivo</span></div>
      </div>
      <div class="clock"><b>09:42</b><small>qui, 13/11/2026 · Turno único</small></div>
    </div>
  </aside>
  <main class="main">
    <div class="top">
      <div class="crumb">${sec.label}${ic("chev", "sm")}<b>${tabLabel}</b></div>
      <div class="top-right">
        <span class="live"><span class="led"></span>Atualizado às 09:42</span>
        <button class="iconbtn" title="Ajuda desta tela">${ic("help")}</button>
        <button class="btn call">${ic("mega", "sm")}Chamar</button>
      </div>
    </div>
    <nav class="tabs">${tabs}</nav>
    <div class="page">${content}</div>
  </main>
  <div class="watermark">Proposta visual · dados ilustrativos · 13/11/2026</div>
</div>`;
}

function head(title, desc, actions = "") {
  return `<div class="head"><div><h1>${title}</h1><p>${desc}</p></div>${actions ? `<div class="actions">${actions}</div>` : ""}</div>`;
}
