// Telas da proposta. Dados ILUSTRATIVOS (não vêm do banco).
const SCREENS = {};
const C = { ok: "var(--ok)", setup: "var(--setup)", stop: "var(--stop)", wait: "var(--wait)", off: "#c3ccd8", maint: "var(--maint)", rework: "var(--rework)", blue: "var(--primary)" };
const legendStates = `<div class="legend"><span><i style="background:${C.ok}"></i>Produzindo</span><span><i style="background:${C.setup}"></i>Em setup</span><span><i style="background:${C.stop}"></i>Parado</span><span><i style="background:${C.wait}"></i>Sem OP (sem demanda)</span><span><i style="background:${C.maint}"></i>Manutenção</span><span><i style="background:${C.off}"></i>Fora do turno</span></div>`;

/* ============ CAPA: princípios do redesenho ============ */
SCREENS.capa = () => `<div class="sheet">
  <div><h1>Gestão do Gestor de Peças — proposta de refatoração visual</h1>
  <p class="lead">Mesma identidade (menu azul-marinho, azul principal, mesmas telas e regras). O que muda é a leitura: cada tela responde primeiro <b>"como estamos?"</b> em uma frase, mostra os números com explicação ao lado, e todo aviso diz <b>o que aconteceu, o que significa e o que fazer</b>.</p></div>

  <div class="grid g3">
    ${card("1. Resumo em uma frase no topo", `<p style="margin:0 0 12px">Antes de qualquer número, uma frase em português comum.</p>${brief(`Hoje a fábrica aproveitou <em class="warn">61%</em> do tempo. A maior perda é <em class="bad">Serra parada há 2h10 (manutenção)</em>.`, [`${ic("ok", "sm")}22 recursos produzindo`, `${ic("warn", "sm")}5 parados`])}`)}
    ${card("2. Número sempre com explicação", `<div class="grid g2">${kpi({ label: "OEE", value: "61", unit: "%", bar: 61, goal: 75, cmp: "+3 p.p. vs ontem", cmpDir: "up", say: "De cada 10 h disponíveis, ~6 viraram peça boa. Meta: 75%.", tone: "warn" })}${kpi({ label: "Refugo", value: "1,8", unit: "%", cmp: "igual a ontem", say: "18 de cada 1.000 peças foram perdidas.", tone: "ok" })}</div>`)}
    ${card("3. Avisos com saída", `<div class="grid" style="gap:10px">${notice("info", "Período sem produção registrada", "Ainda não houve apontamento hoje. Os números aparecem quando o primeiro operador iniciar uma OP.")}${notice("warn", "SigmaNEST sem atualizar há 25 min", "Os planos de corte podem estar desatualizados.", `<button class="btn sm">Ver detalhes</button>`)}${notice("err", "Não foi possível carregar as OPs", "A conexão com o servidor caiu. Nada foi perdido.", `<button class="btn sm">${ic("refresh", "sm")}Tentar de novo</button>`, "Código para o suporte: OPS-503")}</div>`)}
  </div>

  <div class="grid g3">
    ${card("4. Uma cor = um estado, em todo o sistema", `${legendStates}<div class="row" style="margin-top:14px;flex-wrap:wrap;gap:8px">${STATE.prod()}${STATE.setup()}${STATE.stop("Falta de material")}${STATE.wait()}${STATE.maint()}${STATE.off()}</div><p class="muted" style="margin:12px 0 0">Sempre cor + palavra: quem não distingue cores lê o texto.</p>`)}
    ${card("5. Menos ruído nas tabelas", `<div class="ba"><div><b>Antes</b><p class="was">Não disponível · Não disponível · Não disponível · Sem registros</p></div><div><b>Depois</b><p>"—" claro e discreto, números alinhados à direita, linha com problema marcada em vermelho.</p></div></div>`)}
    ${card("6. Menu por intenção", `<p style="margin:0">O menu agrupa em <b>Acompanhar</b> (o agora), <b>Analisar</b> (o período), <b>Minha área</b> (o que só a sua conta vê) e <b>Administração</b>. O botão <b>Chamar</b> sai de cima do conteúdo e vai para o topo da tela. Filtros aplicam sozinhos e aparecem como etiquetas.</p>`)}
  </div>

  ${card("Como ler este pack", `<dl class="gloss" style="--gn:3">
    <div><dt>${ic("file", "sm")}01_comum_todas_as_contas</dt><dd>As 18 telas que toda conta de gestão vê (Gestor, Gerente, Líder, Manufatura, Qualidade, Diretoria, Melhoria e Admin).</dd></div>
    <div><dt>${ic("users", "sm")}02…10_conta_*</dt><dd>Para cada conta: a tela inicial com o menu daquela conta e as telas que só ela vê.</dd></div>
    <div><dt>${ic("info", "sm")}Dados ilustrativos</dt><dd>Nomes de recursos e setores são os reais; números e OPs são de exemplo, só para mostrar o desenho.</dd></div>
  </dl>`)}
</div><div class="watermark">Proposta visual · dados ilustrativos · 13/11/2026</div>`;

/* ============ TELA INICIAL ============ */
SCREENS["home-overview"] = (conta) => `
${head("Como está a fábrica hoje", "O resumo do turno: o que está produzindo, onde estamos perdendo tempo e o que precisa de ação primeiro.")}
${filters({ chips: [] })}
${brief(`Até agora a fábrica aproveitou <em class="warn">61% do tempo</em> (meta 75%). A maior perda do dia é <em class="bad">Serra parada há 2h10 por manutenção</em>.`,
  [`${ic("ok", "sm")}<span><b>22</b> recursos produzindo</span>`, `${ic("warn", "sm")}<span><b>5</b> parados</span>`, `${ic("clock", "sm")}<span><b>9</b> sem OP (sem demanda)</span>`, `${ic("box", "sm")}<span><b>1.284</b> peças boas · 23 refugadas</span>`],
  `Turno único · 08:00–17:30<br>${conta === "lider" ? "Sua área: Serra" : "Todos os setores"}`)}
${kpis(5, [
  kpi({ label: "Produção boa", value: "1.284", unit: "peças", cmp: "+8% vs ontem neste horário", cmpDir: "up", say: "Peças aprovadas apontadas no turno.", help: false }),
  kpi({ label: "OEE", value: "61", unit: "%", bar: 61, goal: 75, tone: "warn", cmp: "+3 p.p. vs ontem", cmpDir: "up", say: "De cada 10 h disponíveis, ~6 viraram peça boa." }),
  kpi({ label: "Disponibilidade", value: "78", unit: "%", bar: 78, goal: 90, tone: "warn", cmp: "−4 p.p. vs ontem", cmpDir: "down", say: "Tempo em que as máquinas não ficaram paradas." }),
  kpi({ label: "Performance", value: "83", unit: "%", bar: 83, goal: 90, cmp: "igual a ontem", say: "Velocidade real comparada ao tempo padrão." }),
  kpi({ label: "Qualidade (FTT)", value: "98,2", unit: "%", bar: 98, goal: 98, tone: "ok", cmp: "+0,4 p.p.", cmpDir: "up", say: "Peças boas de primeira, sem retrabalho." }),
])}
<div class="grid g21">
  ${card("O que precisa de ação agora", `<div class="grid" style="gap:10px">
    ${notice("err", "Serra · S-02 parada há 2h10 — manutenção corretiva", "É a maior perda do dia (34% das horas paradas). Chamado aberto às 07:32, mantenedor a caminho.", `<button class="btn sm">Ver recurso</button>`)}
    ${notice("warn", "Dobra · 2204 em setup há 48 min (padrão: 20 min)", "Setup acima do esperado atrasa a OP 012345 em cerca de 30 min.", `<button class="btn sm">Ver OP</button>`)}
    ${notice("warn", "3 apontamentos sem operador identificado", "Ficam fora dos relatórios por pessoa até alguém corrigir na Auditoria.", `<button class="btn sm">Corrigir</button>`)}
  </div>`, { right: `<span class="pill">3 itens</span>` })}
  ${card("Onde o tempo foi", `<div class="stack"><i style="width:58%;background:${C.ok}"></i><i style="width:7%;background:${C.setup}"></i><i style="width:11%;background:${C.stop}"></i><i style="width:3%;background:${C.rework}"></i><i style="width:21%;background:${C.wait}"></i></div>
    <div class="hbars" style="margin-top:16px">
      ${hb("Produzindo", 58, "112 h <small>58%</small>", C.ok)}
      ${hb("Setup", 7, "13 h <small>7%</small>", C.setup)}
      ${hb("Parado", 11, "21 h <small>11%</small>", C.stop)}
      ${hb("Retrabalho", 3, "6 h <small>3%</small>", C.rework)}
      ${hb("Sem OP", 21, "41 h <small>21%</small>", C.wait)}
    </div>`, { sub: "soma de 39 recursos no turno", foot: `${ic("info", "sm")}"Sem OP" não conta como perda no OEE: a máquina estava livre, sem demanda.` })}
</div>
<div class="grid g2">
  ${card("Setores — leitura rápida", table(
    [{ t: "Setor" }, { t: "Agora" }, { t: "Peças boas", n: 1 }, { t: "Refugo", n: 1 }, { t: "OEE", n: 1 }],
    [
      ["<b>Corte</b>", `${STATE.prod()}`, "412", "4", "72%"],
      ["<b>Dobra</b>", `${STATE.setup()}`, "268", "6", "58%"],
      flag(["<b>Serra</b>", `${STATE.stop("Manutenção")}`, "96", "2", "31%"]),
      ["<b>Solda Aço</b>", `${STATE.prod()}`, "88", "1", "66%"],
      ["<b>Pintura</b>", `${STATE.prod()}`, "301", "7", "69%"],
      ["<b>Usinagem</b>", `${STATE.wait()}`, "119", "3", "—"],
    ]), { flush: true, right: `<button class="btn ghost sm">Ver todos ${ic("chev", "sm")}</button>` })}
  ${card("Recursos que mais perderam tempo", `<div class="hbars">
      ${hb("S-02 · Serra", 92, "2h10 parada", C.stop)}
      ${hb("2204 · Dobra", 40, "48 min setup", C.setup)}
      ${hb("Laser ensis 3015", 26, "31 min parada", C.stop)}
      ${hb("Solda Robô", 19, "22 min parada", C.stop)}
      ${hb("Jateamento", 12, "14 min retrab.", C.rework)}
    </div>`, { sub: "paradas + setup acima do padrão" })}
</div>
${gloss([["OEE", "Quanto do tempo disponível virou peça boa. Junta três coisas: disponibilidade × performance × qualidade."], ["Sem OP", "Máquina ligada no turno, mas sem ordem para fazer. Não é culpa do posto; fica separado das perdas."], ["p.p. (pontos percentuais)", "Diferença direta entre porcentagens: de 58% para 61% são +3 p.p."]])}
`;

SCREENS["home-ai"] = () => `
${head("Pergunte à IA", "Faça perguntas sobre a produção em português. A IA só responde com dados do sistema e mostra de onde tirou cada número.")}
<div class="grid g21">
  ${card("Conversa", `<div class="chat">
      <div class="msg me">Por que o OEE da Dobra caiu ontem?</div>
      <div class="msg ai"><b>O OEE da Dobra foi de 52% ontem (média da semana: 64%).</b><br>A queda veio quase toda da <b>disponibilidade</b>: a 2204 ficou 1h35 em setup na troca de ferramenta da OP 012301 — o padrão é 20 min. A qualidade ficou normal (98%).
        <div class="src">${ic("link", "sm")}Fonte: Análises › Horas & Utilização · Dobra · 12/11/2026</div></div>
      <div class="msg me">E hoje, está melhor?</div>
      <div class="msg ai">Até 09:42, a Dobra está em <b>58%</b>. A 2204 está em setup de novo há 48 min.
        <div class="src">${ic("link", "sm")}Fonte: Consulta Operacional › Recursos · agora</div></div>
    </div>`, { flush: false, foot: `<div class="composer" style="border:0;padding:0;width:100%"><span class="field">Escreva sua pergunta…</span><button class="btn primary">${ic("send", "sm")}Enviar</button></div>` })}
  <div class="grid" style="align-content:start">
    ${card("Sugestões de pergunta", `<div class="grid" style="gap:8px">${["Qual recurso mais parou esta semana?", "Quanto refugo tivemos na Pintura hoje?", "Quais OPs estão atrasadas?", "Compare o OEE do Corte e da Dobra no mês"].map((s) => `<button class="btn" style="justify-content:flex-start;height:auto;padding:9px 12px;font-weight:500">${ic("spark", "sm")}${s}</button>`).join("")}</div>`)}
    ${notice("info", "A IA pode errar", "Confira o número na tela indicada em \"Fonte\" antes de tomar uma decisão.")}
  </div>
</div>`;

SCREENS["home-calls"] = () => `
${head("Chamadas da Gestão", "Pedidos de ajuda feitos pelo botão Chamar nos postos e nas telas. Cada chamada mostra quem pediu, para quem foi e se já foi atendida.")}
${filters({ sector: true, on: 2 })}
${kpis(4, [
  kpi({ label: "Abertas agora", value: "2", tone: "bad", say: "Ainda sem resposta de quem foi chamado.", help: false }),
  kpi({ label: "Atendidas hoje", value: "11", say: "Fechadas por quem recebeu.", help: false }),
  kpi({ label: "Tempo médio até atender", value: "6", unit: "min", cmp: "−2 min vs semana passada", cmpDir: "up", say: "Da chamada até alguém marcar \"a caminho\"." }),
  kpi({ label: "Mais chamado", value: "Qualidade", say: "5 de 11 chamadas foram para a Qualidade.", help: false }),
])}
${card("Histórico", table(
  [{ t: "Quando" }, { t: "Quem chamou" }, { t: "Para" }, { t: "Motivo" }, { t: "Situação" }, { t: "Esperou", n: 1 }],
  [
    flag(["09:31", "<b>Posto 1303</b><span class=\"sub\">Dobra</span>", "Qualidade", "Medida fora da faixa na 1ª peça", st("stop", "Aberta"), "11 min"]),
    flag(["09:18", "<b>S-02</b><span class=\"sub\">Serra</span>", "Manutenção", "Lâmina travando", st("stop", "Aberta"), "24 min"]),
    ["08:52", "<b>Pintura</b><span class=\"sub\">Pintura</span>", "PCP", "Falta de material (tinta RAL 5010)", st("ok", "Atendida"), "4 min"],
    ["08:10", "<b>Laser ensis 3015</b><span class=\"sub\">Corte</span>", "Manutenção", "Alarme de gás", st("ok", "Atendida"), "7 min"],
    ["07:44", "<b>Solda Robô</b><span class=\"sub\">Solda</span>", "Qualidade", "Liberação de primeira peça", st("ok", "Atendida"), "3 min"],
  ], { foot: `Mostrando 5 de 13 <div class="r"><button class="btn sm">${ic("download", "sm")}Excel</button></div>` }), { flush: true })}`;

/* ============ PAINÉIS ============ */
const RES = [
  ["Laser ensis 3015", "Corte", "prod", "OP 012340", "Ana P.", "1h12"],
  ["Plasma terrablade 4", "Corte", "prod", "OP 012338", "Carlos M.", "38 min"],
  ["Destaque", "Destaque", "wait", "—", "—", "1h40"],
  ["Gasparini", "Dobra", "prod", "OP 012329", "Rafael S.", "22 min"],
  ["2204", "Dobra", "setup", "OP 012345", "Júlio T.", "48 min"],
  ["1303", "Dobra", "stop", "OP 012331", "Marcos L.", "11 min", "Qualidade"],
  ["S-02", "Serra", "maint", "OP 012300", "—", "2h10"],
  ["S-01", "Serra", "prod", "OP 012317", "Paulo R.", "55 min"],
  ["Solda Robô", "Solda Robô", "prod", "OP 012322", "Diego F.", "1h05"],
  ["Solda MIG 03", "Solda Aço", "prod", "OP 012318", "Elias N.", "40 min"],
  ["Solda TIG 01", "Solda Alumínio", "wait", "—", "—", "1h20"],
  ["Jateamento", "Pintura", "rework", "OP 012290", "Lucas B.", "14 min"],
  ["Preparação", "Pintura", "prod", "OP 012295", "Renan C.", "33 min"],
  ["Pintura", "Pintura", "prod", "OP 012295", "Vitor A.", "26 min"],
  ["Secagem pintura", "Pintura", "prod", "OP 012288", "—", "1h50"],
  ["Inspeção final", "Pintura", "prod", "OP 012280", "Sílvia M.", "12 min"],
  ["Centro ROMI D800", "Usinagem", "wait", "—", "—", "2h05"],
  ["Torno CNC 02", "Usinagem", "prod", "OP 012311", "Igor P.", "1h30"],
  ["Ferramentaria", "Proj. Ferramentaria", "off", "—", "—", "—"],
  ["Protótipo", "Protótipo", "wait", "—", "—", "45 min"],
];
const stateOf = (k, m) => k === "prod" ? STATE.prod() : k === "setup" ? STATE.setup() : k === "stop" ? STATE.stop(m) : k === "maint" ? STATE.maint() : k === "rework" ? STATE.rework() : k === "off" ? STATE.off() : STATE.wait();

SCREENS["panels-andon"] = () => `
${head("Andon", "Todos os recursos e o estado de cada um agora. Vermelho e roxo primeiro: são os que precisam de alguém.", `<button class="btn">${ic("eye", "sm")}Abrir modo TV</button>`)}
<div class="filters"><div class="seg"><button class="on">Todos (39)</button><button>Precisam de ação (3)</button><button>Produzindo (22)</button><button>Sem OP (9)</button></div><span class="field">${ic("factory", "sm")}<small>Setor</small> Todos ${ic("down", "sm")}</span><span class="grow"></span>${legendStates}</div>
<div class="res-grid" style="--rc:5">${RES.map(([n, s, k, op, who, t, m]) => `<div class="res ${k === "stop" || k === "maint" ? "stop" : ""}">
  <div class="nm">${n}<span class="sec">${s}</span></div>${stateOf(k, m)}
  <div class="ln"><span>OP</span><span>${op}</span></div>
  <div class="ln"><span>Operador</span><span>${who}</span></div>
  <div class="ln"><span>Neste estado há</span><b>${t}</b></div></div>`).join("")}</div>`;

SCREENS["panels-map"] = () => {
  const z = (x, y, w, h, name, states) => `<div class="zone" style="left:${x}%;top:${y}%;width:${w}%;height:${h}%"><b>${name}</b><div class="dots">${states.map((s) => `<i style="background:${C[s]}" title="${s}"></i>`).join("")}</div></div>`;
  return `
${head("Mapa da fábrica", "A planta vista de cima. Cada quadrado é um recurso, na cor do estado atual. Passe o mouse para ver o detalhe.")}
<div class="filters">${legendStates}<span class="grow"></span><span class="live"><span class="led"></span>Atualiza sozinho a cada 30 s</span></div>
${card("Planta baixa — Filial 4", `<div class="map">
  ${z(2, 4, 26, 40, "Corte", ["ok", "ok", "wait", "ok"])}
  ${z(30, 4, 22, 40, "Dobra", ["ok", "setup", "stop"])}
  ${z(54, 4, 18, 40, "Serra", ["maint", "ok"])}
  ${z(74, 4, 24, 40, "Usinagem", ["wait", "ok", "ok"])}
  ${z(2, 50, 30, 44, "Solda", ["ok", "ok", "wait", "ok", "ok"])}
  ${z(34, 50, 34, 44, "Pintura", ["rework", "ok", "ok", "ok", "ok"])}
  ${z(70, 50, 13, 44, "Rebarbação · Robô", ["ok"])}
  ${z(85, 50, 13, 21, "Expedição (Almox)", [])}
  ${z(85, 73, 13, 21, "Projetos · Ferramentaria", ["off"])}
  <div class="res" style="position:absolute;left:56%;top:22%;width:250px;box-shadow:var(--shadow-pop)"><div class="nm">S-02<span class="sec">Serra</span></div>${STATE.maint()}<div class="ln"><span>Desde</span><span>07:32 (2h10)</span></div><div class="ln"><span>Chamado</span><span>Lâmina travando</span></div></div>
</div>`, { flush: false })}`;
};

SCREENS["panels-pauses"] = () => `
${head("Pausas programadas", "Intervalos fixos do turno (café, almoço, ginástica). Nesses horários a máquina parada não conta como perda.", `<button class="btn primary">${ic("plus", "sm")}Nova pausa</button>`)}
${notice("info", "Como as pausas afetam os números", "Durante uma pausa programada, o tempo sai do \"tempo disponível\" do OEE. Uma pausa cadastrada errada deixa o OEE maior ou menor do que a realidade.")}
${card("Pausas cadastradas", table(
  [{ t: "Nome" }, { t: "Horário" }, { t: "Duração", n: 1 }, { t: "Dias" }, { t: "Vale para" }, { t: "" }],
  [
    ["<b>Café da manhã</b>", "08:30 – 08:40", "10 min", "Seg a Sex", "Todos os setores", `<button class="btn ghost sm">${ic("edit", "sm")}Editar</button>`],
    ["<b>Almoço</b>", "11:30 – 12:30", "60 min", "Seg a Sex", "Todos os setores", `<button class="btn ghost sm">${ic("edit", "sm")}Editar</button>`],
    ["<b>Ginástica laboral</b>", "14:00 – 14:10", "10 min", "Ter e Qui", "Solda, Pintura", `<button class="btn ghost sm">${ic("edit", "sm")}Editar</button>`],
    ["<b>Café da tarde</b>", "15:00 – 15:10", "10 min", "Seg a Sex", "Todos os setores", `<button class="btn ghost sm">${ic("edit", "sm")}Editar</button>`],
  ], { foot: `Total por dia: 1h30 em pausas · o turno tem 9h30` }), { flush: true })}
${card("Linha do dia — Turno único", `<div class="tl">
  <span>Turno único</span><div class="lane" style="background:var(--ok-soft)">${[[5.3, 1.8], [36.8, 10.5], [63.2, 1.8], [73.7, 1.8]].map(([l, w]) => `<i style="left:${l}%;width:${w}%;background:var(--off)"></i>`).join("")}</div>
  <div class="axis"><span>08:00</span><span>10:00</span><span>12:00</span><span>14:00</span><span>16:00</span><span>17:30</span></div></div>
  <div class="legend" style="margin-top:12px"><span><i style="background:var(--ok-soft);border:1px solid #b5e2c4"></i>Tempo de trabalho</span><span><i style="background:var(--off)"></i>Pausa programada</span></div>`)}`;

/* ============ CONSULTA OPERACIONAL ============ */
SCREENS["ops-overview"] = () => `
${head("Consulta Operacional", "Como cada setor está neste momento: quantos recursos produzem, quantos estão parados e por quê.")}
${filters({ period: false })}
${brief(`<em>22 de 39</em> recursos estão produzindo. <em class="bad">5 parados</em> — o motivo mais comum agora é <em>manutenção</em>.`, [], "Situação de agora · atualiza a cada 30 s")}
${kpis(4, [
  kpi({ label: "Produzindo", value: "22", unit: "de 39", tone: "ok", say: "Com OP aberta e operador apontando.", help: false }),
  kpi({ label: "Parados", value: "5", tone: "bad", say: "Com OP, mas parados por algum motivo.", help: false }),
  kpi({ label: "Sem OP", value: "9", tone: "warn", say: "Livres: não há ordem para fazer.", help: false }),
  kpi({ label: "Maior parada aberta", value: "2h10", say: "S-02 (Serra), manutenção.", tone: "bad", help: false }),
])}
${card("Por setor", table(
  [{ t: "Setor" }, { t: "Recursos", n: 1 }, { t: "Produzindo", n: 1 }, { t: "Em setup", n: 1 }, { t: "Parados", n: 1 }, { t: "Sem OP", n: 1 }, { t: "Motivo principal da parada" }],
  [
    ["<b>Corte</b>", "4", "3", "0", "0", "1", "—"],
    ["<b>Dobra</b>", "3", "1", "1", "1", "0", "Aguardando Qualidade"],
    flag(["<b>Serra</b>", "2", "1", "0", "1", "0", "Manutenção corretiva"]),
    ["<b>Solda</b>", "8", "6", "0", "0", "2", "—"],
    ["<b>Pintura</b>", "6", "4", "0", "1", "1", "Retrabalho"],
    ["<b>Usinagem</b>", "5", "2", "0", "1", "2", "Falta de material"],
    ["<b>Outros</b>", "11", "5", "0", "1", "3", "Falta de material"],
  ]), { flush: true })}`;

SCREENS["ops-resources"] = () => `
${head("Recursos", "Cada máquina ou posto: o que está fazendo agora, com qual OP, quem está operando e há quanto tempo.")}
${filters({ period: false, chips: [], search: "Buscar recurso, OP ou operador" })}
${kpis(4, [
  kpi({ label: "Recursos no filtro", value: "39", help: false, say: "Só os que recebem apontamento." }),
  kpi({ label: "Produzindo agora", value: "22", tone: "ok", help: false }),
  kpi({ label: "Parados", value: "5", tone: "bad", help: false, say: "3 com motivo informado, 2 sem motivo." }),
  kpi({ label: "Maior parada aberta", value: "2h10", tone: "bad", help: false, say: "S-02 · Serra · manutenção" }),
])}
${card("Recursos", table(
  [{ t: "Recurso" }, { t: "Estado agora" }, { t: "OP" }, { t: "Produto" }, { t: "Operador" }, { t: "Desde" }, { t: "Há", n: 1 }],
  RES.slice(0, 14).map(([n, s, k, op, who, t, m]) => {
    const row = [`<b>${n}</b><span class="sub">${s}</span>`, stateOf(k, m), op, op === "—" ? "—" : "Suporte lateral SL-220", who, "08:00", t];
    return k === "stop" || k === "maint" ? flag(row) : row;
  }), { foot: `Mostrando 14 de 39 · "—" = sem OP ou sem operador no momento <div class="r"><button class="btn sm">${ic("download", "sm")}Excel</button></div>` }), { flush: true, right: legendStates })}`;

SCREENS["ops-orders"] = () => `
${head("OPs em andamento", "Ordens de produção que já começaram e ainda não terminaram: em qual etapa estão e quanto falta.")}
${filters({ period: false, search: "Buscar OP ou produto" })}
${kpis(4, [
  kpi({ label: "OPs em andamento", value: "27", help: false }),
  kpi({ label: "Paradas agora", value: "3", tone: "bad", help: false, say: "Têm etapa parada neste momento." }),
  kpi({ label: "Acima do tempo padrão", value: "6", tone: "warn", say: "Já gastaram mais que o previsto." }),
  kpi({ label: "Concluídas hoje", value: "14", tone: "ok", help: false }),
])}
${card("OPs", table(
  [{ t: "OP" }, { t: "Produto" }, { t: "Etapa atual" }, { t: "Estado" }, { t: "Progresso" }, { t: "Tempo gasto / padrão", n: 1 }],
  [
    ["<b>012345</b>", "Suporte lateral SL-220", "Dobra · 2204", STATE.setup(), `<div class="bar" style="width:140px"><i style="width:40%"></i></div><span class="sub">40 de 100 peças</span>`, "1h52 / 2h30"],
    flag(["<b>012300</b>", "Eixo traseiro ET-90", "Serra · S-02", STATE.maint(), `<div class="bar" style="width:140px"><i style="width:65%"></i></div><span class="sub">13 de 20 peças</span>`, `<span class="down">3h40 / 2h00</span>`]),
    ["<b>012340</b>", "Chapa base CB-12", "Corte · Laser", STATE.prod(), `<div class="bar" style="width:140px"><i style="width:80%"></i></div><span class="sub">plano 4 de 5</span>`, "0h58 / 1h20"],
    warnRow(["<b>012331</b>", "Tampa TP-40", "Dobra · 1303", STATE.stop("Qualidade"), `<div class="bar" style="width:140px"><i style="width:10%"></i></div><span class="sub">1ª peça em análise</span>`, "0h25 / 1h10"]),
    ["<b>012295</b>", "Carenagem CR-7", "Pintura · Preparação", STATE.prod(), `<div class="bar" style="width:140px"><i style="width:55%"></i></div><span class="sub">22 de 40 peças</span>`, "2h10 / 4h00"],
  ], { foot: "Mostrando 5 de 27" }), { flush: true })}`;

/* ============ PRODUÇÃO ============ */
SCREENS["prod-orders"] = () => `
${head("Consulta de OP", "Digite o número da OP para ver o roteiro completo: por onde ela já passou, onde está e o que falta.")}
<div class="filters"><span class="field grow">${ic("search", "sm")}012300</span><button class="btn primary">Buscar OP</button></div>
<div class="grid g12">
  ${card("OP 012300", `<dl class="kv"><dt>Produto</dt><dd>Eixo traseiro ET-90</dd><dt>Quantidade</dt><dd>20 peças</dd><dt>Situação</dt><dd>${STATE.maint()}</dd><dt>Entrega prevista</dt><dd>14/11/2026</dd><dt>Origem</dt><dd>Protheus · sincronizada 09:40</dd></dl>`)}
  ${card("Roteiro", `<ol class="steps">
    <li class="done"><b>10 · Corte (Laser)</b><span>20 de 20 peças · terminou 12/11 15:20</span></li>
    <li class="done"><b>20 · Dobra (Gasparini)</b><span>20 de 20 peças · terminou 13/11 07:10</span></li>
    <li class="now"><b>30 · Serra (S-02)</b><span>13 de 20 peças · parada desde 07:32 — manutenção</span></li>
    <li><b>40 · Solda Aço</b><span>aguardando a etapa anterior</span></li>
    <li><b>50 · Pintura</b><span>aguardando</span></li>
  </ol>`, { right: `<button class="btn sm">${ic("plus", "sm")}Adicionar etapa</button>`, foot: `${ic("info", "sm")}Etapas em cinza ainda não começaram. Etapa "só no Protheus" aparece com essa etiqueta quando o MES ainda não registrou nada.` })}
</div>
${notice("warn", "Esta OP está 1h40 acima do tempo padrão na Serra", "O padrão da etapa 30 é 2h00 para 20 peças; já foram 3h40 por causa da parada. A entrega de 14/11 continua possível se a Serra voltar até as 13:00.")}`;

SCREENS["prod-exec"] = () => `
${head("Execução das OPs", "Quanto de cada OP já foi feito e quanto ainda falta (saldo). Ordenado pelas que estão mais atrasadas.")}
${filters({ search: "Buscar OP ou produto", on: 1, chips: ["Situação: em aberto"] })}
${kpis(4, [
  kpi({ label: "OPs no filtro", value: "142", help: false }),
  kpi({ label: "Planejado", value: "8.420", unit: "peças", help: false }),
  kpi({ label: "Peças boas feitas", value: "5.913", unit: "peças", bar: 70, tone: "ok", say: "70% do planejado já está pronto." }),
  kpi({ label: "Saldo a produzir", value: "2.507", unit: "peças", say: "O que ainda falta para fechar essas OPs.", help: false }),
])}
${card("OPs", table(
  [{ t: "OP" }, { t: "Produto" }, { t: "Recurso" }, { t: "Situação" }, { t: "Planejado", n: 1 }, { t: "Boas", n: 1 }, { t: "Refugo", n: 1 }, { t: "Saldo", n: 1 }, { t: "Atendido" }],
  [
    flag(["<b>012300</b>", "Eixo traseiro ET-90", "S-02", STATE.maint(), "20", "13", "0", "7", `<div class="bar" style="width:110px"><i style="width:65%"></i></div>`]),
    ["<b>012345</b>", "Suporte lateral SL-220", "2204", STATE.setup(), "100", "40", "2", "60", `<div class="bar" style="width:110px"><i style="width:40%"></i></div>`],
    ["<b>012340</b>", "Chapa base CB-12", "Laser ensis 3015", STATE.prod(), "250", "200", "1", "50", `<div class="bar" style="width:110px"><i style="width:80%"></i></div>`],
    ["<b>012295</b>", "Carenagem CR-7", "Preparação", STATE.prod(), "40", "22", "0", "18", `<div class="bar" style="width:110px"><i style="width:55%"></i></div>`],
    ["<b>012280</b>", "Painel PN-3", "Inspeção final", STATE.prod(), "60", "58", "2", "0", `<div class="bar" style="width:110px"><i style="width:100%"></i></div>`],
  ], { foot: `Mostrando 5 de 142 <div class="r"><button class="btn sm">${ic("download", "sm")}Excel</button></div>` }), { flush: true })}`;

SCREENS["prod-done"] = () => `
${head("Produção realizada", "O que foi produzido no período: peças boas, refugo e retrabalho, por setor.")}
${filters({ on: 0 })}
${kpis(5, [
  kpi({ label: "Peças boas", value: "6.842", cmp: "+5% vs semana passada", cmpDir: "up", help: false }),
  kpi({ label: "Refugo", value: "124", unit: "peças", tone: "warn", cmp: "+18 vs semana passada", cmpDir: "down", help: false }),
  kpi({ label: "Retrabalho", value: "57", unit: "peças", help: false }),
  kpi({ label: "Taxa de refugo", value: "1,8", unit: "%", bar: 18, goal: 20, say: "Limite aceitável: 2%.", tone: "ok" }),
  kpi({ label: "OPs atendidas", value: "61", help: false }),
])}
<div class="grid g2">
  ${card("Peças boas por setor", `<div class="hbars">${hb("Corte", 100, "2.210", C.blue)}${hb("Pintura", 74, "1.640", C.blue)}${hb("Dobra", 62, "1.372", C.blue)}${hb("Solda", 41, "905", C.blue)}${hb("Usinagem", 22, "488", C.blue)}${hb("Serra", 10, "227", C.blue)}</div>`)}
  ${card("Perdas por setor", table([{ t: "Setor" }, { t: "Refugo", n: 1 }, { t: "Retrabalho", n: 1 }, { t: "Taxa", n: 1 }], [
    ["Corte", "18", "6", "0,8%"], warnRow(["Dobra", "41", "12", "3,0%"]), ["Pintura", "29", "25", "1,8%"], ["Solda", "16", "9", "1,8%"], ["Usinagem", "14", "4", "2,8%"], ["Serra", "6", "1", "2,6%"],
  ]), { flush: true, foot: `${ic("warn", "sm")}Dobra passou do limite de 2% — 26 das 41 peças foram da OP 012329 (medida de dobra).` })}
</div>`;

SCREENS["prod-plan"] = () => `
${head("Planejado × Realizado", "Compara o que o PCP planejou no Protheus com o que a fábrica fez: quantidade, máquina e data.")}
${filters({ on: 0 })}
${kpis(4, [
  kpi({ label: "Planejado", value: "7.300", unit: "peças", help: false }),
  kpi({ label: "Realizado (boas)", value: "6.842", unit: "peças", help: false }),
  kpi({ label: "Atendimento", value: "94", unit: "%", bar: 94, goal: 95, tone: "warn", say: "Faltou 1 p.p. para a meta de 95%." }),
  kpi({ label: "Feito em outra máquina", value: "11", unit: "OPs", say: "Planejadas para um recurso, feitas em outro.", help: false }),
])}
${card("Plano × real por OP", table(
  [{ t: "OP" }, { t: "Operação" }, { t: "Recurso planejado → real" }, { t: "Planejado", n: 1 }, { t: "Real", n: 1 }, { t: "Data planejada → real" }],
  [
    ["<b>012340</b>", "10 · Corte", "Laser ensis 3015", "250", "200", "13/11 → em andamento"],
    warnRow(["<b>012329</b>", "20 · Dobra", `2204 → <b>Gasparini</b>`, "120", "94", `12/11 → <span class="down">13/11 (+1 dia)</span>`]),
    ["<b>012318</b>", "40 · Solda", "Solda MIG 03", "30", "30", "12/11 → 12/11"],
    flag(["<b>012300</b>", "30 · Serra", "S-02", "20", "13", `13/11 → <span class="down">atrasada</span>`]),
  ]), { flush: true })}
${notice("info", "Planejado indisponível para 3 OPs", "Essas OPs não trazem data planejada do Protheus. Elas aparecem com \"—\" e não entram no atendimento.")}`;

/* ============ ANÁLISES / AUDITORIA / RELATÓRIOS ============ */
SCREENS["an-hours"] = () => `
${head("Horas & Utilização", "Quantas horas cada máquina e cada pessoa trabalhou no período, e quanto disso foi produção.")}
<div class="filters"><div class="seg"><button class="on">Máquinas</button><button>Funcionários</button></div>${filters({ chips: [] }).replace(/^<div class="filters">|<\/div>$/g, "")}</div>
${kpis(4, [
  kpi({ label: "Horas no turno", value: "1.716", unit: "h", say: "Soma das horas disponíveis de todos os recursos.", help: false }),
  kpi({ label: "Horas produzindo", value: "1.046", unit: "h", help: false }),
  kpi({ label: "Utilização", value: "61", unit: "%", bar: 61, goal: 75, tone: "warn", say: "Parte do turno em que a máquina estava fazendo peça." }),
  kpi({ label: "Horas paradas", value: "205", unit: "h", tone: "bad", say: "41% delas por manutenção.", help: false }),
])}
${card("Utilização por recurso", table(
  [{ t: "Recurso" }, { t: "Uso do turno" }, { t: "Produzindo", n: 1 }, { t: "Setup", n: 1 }, { t: "Parado", n: 1 }, { t: "Sem OP", n: 1 }],
  [
    ["<b>Laser ensis 3015</b><span class=\"sub\">Corte</span>", `<div class="stack" style="width:220px"><i style="width:78%;background:${C.ok}"></i><i style="width:6%;background:${C.setup}"></i><i style="width:6%;background:${C.stop}"></i><i style="width:10%;background:${C.wait}"></i></div>`, "34h", "2h40", "2h40", "4h20"],
    ["<b>Gasparini</b><span class=\"sub\">Dobra</span>", `<div class="stack" style="width:220px"><i style="width:64%;background:${C.ok}"></i><i style="width:14%;background:${C.setup}"></i><i style="width:8%;background:${C.stop}"></i><i style="width:14%;background:${C.wait}"></i></div>`, "28h", "6h10", "3h30", "6h10"],
    flag(["<b>S-02</b><span class=\"sub\">Serra</span>", `<div class="stack" style="width:220px"><i style="width:38%;background:${C.ok}"></i><i style="width:4%;background:${C.setup}"></i><i style="width:48%;background:${C.stop}"></i><i style="width:10%;background:${C.wait}"></i></div>`, "16h40", "1h45", "21h", "4h20"]),
    ["<b>Solda Robô</b><span class=\"sub\">Solda</span>", `<div class="stack" style="width:220px"><i style="width:70%;background:${C.ok}"></i><i style="width:5%;background:${C.setup}"></i><i style="width:5%;background:${C.stop}"></i><i style="width:20%;background:${C.wait}"></i></div>`, "30h40", "2h10", "2h10", "8h45"],
  ], { foot: legendStates }), { flush: true })}
${gloss([["Utilização", "Horas produzindo ÷ horas do turno. Pausas programadas não entram na conta."], ["Hora-homem", "Na aba Funcionários: horas em que a pessoa esteve apontando, somadas por pessoa."]], 2)}`;

SCREENS["audit"] = () => `
${head("Auditoria analítica", "Lista de eventos que merecem conferência: apontamentos sem operador, paradas sem motivo, números que não fecham.")}
<div class="filters"><span class="field">${ic("layers", "sm")}<small>Tipo</small> Paradas ${ic("down", "sm")}</span><div class="seg"><button>Todos</button><button class="on">Só em aberto</button></div><span class="field">${ic("calendar", "sm")}<small>Período</small> Esta semana ${ic("down", "sm")}</span><span class="grow"></span><button class="btn">${ic("download", "sm")}Exportar Excel</button></div>
${kpis(3, [
  kpi({ label: "Em aberto", value: "17", tone: "warn", say: "Precisam de alguém para conferir ou corrigir.", help: false }),
  kpi({ label: "Resolvidos na semana", value: "42", tone: "ok", help: false }),
  kpi({ label: "Mais comum", value: "Parada sem motivo", say: "9 dos 17 em aberto.", help: false }),
])}
${card("Eventos em aberto", table(
  [{ t: "Quando" }, { t: "Recurso" }, { t: "O que aconteceu" }, { t: "Por que importa" }, { t: "" }],
  [
    ["13/11 08:14", "<b>1303</b><span class=\"sub\">Dobra</span>", "Parada de 18 min sem motivo", "Fica como \"a esclarecer\" e reduz o OEE sem explicação", `<button class="btn sm">Informar motivo</button>`],
    ["13/11 07:02", "<b>Solda MIG 03</b><span class=\"sub\">Solda</span>", "Apontamento sem operador", "Não aparece nas horas por pessoa", `<button class="btn sm">Corrigir</button>`],
    ["12/11 16:40", "<b>Jateamento</b><span class=\"sub\">Pintura</span>", "OP aberta há 26 h sem fechar", "Infla o tempo gasto da OP", `<button class="btn sm">Ver OP</button>`],
  ]), { flush: true })}
${empty("Nenhuma inconsistência de produção nesta semana", "Quando um apontamento tiver quantidade maior que o planejado ou refugo sem motivo, ele aparece aqui.", "ok")}`;

SCREENS["reports"] = () => `
${head("Relatórios", "Escolha o relatório, o período e baixe em Excel. A prévia abaixo mostra exatamente o que vai no arquivo.")}
<div class="filters"><div class="seg"><button class="on">Gerencial</button><button>Perdas</button><button>Indicadores</button><button>Dados analíticos</button></div><span class="field">${ic("calendar", "sm")}<small>Período</small> Outubro/2026 ${ic("down", "sm")}</span><span class="grow"></span><button class="btn primary">${ic("download", "sm")}Baixar em Excel (.xlsx)</button></div>
${kpis(5, [
  kpi({ label: "Produção boa", value: "28.410", unit: "peças", help: false }),
  kpi({ label: "OEE", value: "63", unit: "%", bar: 63, goal: 75, tone: "warn", help: false }),
  kpi({ label: "FTT", value: "97,9", unit: "%", tone: "ok", help: false }),
  kpi({ label: "MTBF", value: "18", unit: "h", say: "Tempo médio entre uma quebra e outra.", help: false }),
  kpi({ label: "MTTR", value: "1h12", say: "Tempo médio para consertar.", help: false }),
])}
${card("Prévia do relatório gerencial", table(
  [{ t: "Setor" }, { t: "Peças boas", n: 1 }, { t: "Refugo", n: 1 }, { t: "OEE", n: 1 }, { t: "Tempo parado", n: 1 }, { t: "Utilização", n: 1 }],
  [["Corte", "9.820", "141", "71%", "38h", "74%"], ["Dobra", "6.210", "188", "58%", "61h", "63%"], ["Pintura", "6.050", "120", "66%", "42h", "68%"], ["Solda", "3.880", "61", "64%", "35h", "66%"], ["Usinagem", "1.640", "44", "55%", "29h", "52%"], ["Serra", "810", "21", "49%", "48h", "47%"]],
  { foot: "6 setores · o arquivo também traz uma aba por recurso" }), { flush: true })}
${gloss([["MTBF", "Média de horas que a máquina funciona entre duas quebras. Quanto maior, melhor."], ["MTTR", "Média de tempo para a máquina voltar depois de quebrar. Quanto menor, melhor."], ["FTT", "Peças boas de primeira, sem precisar de retrabalho."]])}`;

/* ============ RASTREABILIDADE ============ */
SCREENS["trace-op"] = () => `
${head("Rastreabilidade · OP / Produto", "A história completa de uma OP: quem fez, em qual máquina, quando, e o que foi inspecionado.")}
<div class="filters"><span class="field grow">${ic("search", "sm")}012280</span><button class="btn primary">Buscar OP</button></div>
${kpis(4, [
  kpi({ label: "Situação", value: "Em inspeção", help: false, say: "Etapa 60 · Inspeção final" }),
  kpi({ label: "Peças boas", value: "58", unit: "de 60", tone: "ok", help: false }),
  kpi({ label: "Perdas", value: "2", unit: "refugo", tone: "warn", help: false, say: "Pintura com escorrimento." }),
  kpi({ label: "Eventos registrados", value: "47", help: false }),
])}
<div class="grid g21">
  ${card("Linha do tempo", `<ol class="steps">
    <li class="done"><b>10 · Corte</b><span>Laser ensis 3015 · Ana P. · 10/11 08:12–09:40 · plano P-4471</span></li>
    <li class="done"><b>20 · Dobra</b><span>Gasparini · Rafael S. · 10/11 13:05–15:30</span></li>
    <li class="done"><b>40 · Solda Aço</b><span>Solda MIG 03 · Elias N. · 11/11 08:00–14:22</span></li>
    <li class="done"><b>50 · Pintura</b><span>Pintura · Vitor A. · 12/11 · <b>2 refugadas</b> (escorrimento)</span></li>
    <li class="now"><b>60 · Inspeção final</b><span>Sílvia M. · em andamento</span></li>
  </ol>`)}
  ${card("Peças inspecionadas", empty("Nenhuma peça inspecionada ainda", "A Inspeção final começou às 09:30. As medições aparecem aqui assim que a primeira peça for registrada.", "ruler"))}
</div>`;

SCREENS["trace-nest"] = () => `
${head("Rastreabilidade · Lote / Material / Nesting", "Para cada chapa cortada: qual material, quanto da chapa virou peça (aproveitamento) e o tempo previsto × real.")}
<div class="filters"><span class="field grow">${ic("search", "sm")}Buscar tarefa, material ou nesting</span>${`<span class="field">${ic("calendar", "sm")}<small>Período</small> Esta semana ${ic("down", "sm")}</span>`}</div>
${kpis(4, [
  kpi({ label: "Nestings no período", value: "86", help: false }),
  kpi({ label: "Aproveitamento médio", value: "78", unit: "%", bar: 78, goal: 80, tone: "warn", say: "De cada chapa, 78% virou peça; o resto é sobra." }),
  kpi({ label: "Com dado", value: "81", help: false }),
  kpi({ label: "Sem dado", value: "5", say: "Não entram na média: o SigmaNEST não mandou o aproveitamento.", help: false }),
])}
${card("Nestings", table(
  [{ t: "Tarefa" }, { t: "Plano" }, { t: "Material" }, { t: "Chapas", n: 1 }, { t: "Aproveitamento", n: 1 }, { t: "Tempo previsto → real", n: 1 }],
  [
    ["<b>T-2291</b>", "P-4471", "Aço SAE 1020 · 3,0 mm", "4", "84%", "1h20 → 1h12"],
    ["<b>T-2290</b>", "P-4468", "Aço SAE 1020 · 6,3 mm", "2", "79%", "0h50 → 0h58"],
    warnRow(["<b>T-2288</b>", "P-4460", "Inox 304 · 2,0 mm", "1", "61%", `0h35 → <span class="down">0h52</span>`]),
    ["<b>T-2287</b>", "P-4459", "Alumínio 5052 · 3,0 mm", "3", "—", "1h05 → 1h01"],
  ], { foot: `"—" = sem aproveitamento informado pelo SigmaNEST` }), { flush: true })}`;

/* ============ QUALIDADE ============ */
SCREENS["q-cotas"] = () => `
${head("Cotas padrão", "Medidas de referência de cada produto. O operador mede a primeira peça contra essas cotas.", `<button class="btn primary">${ic("plus", "sm")}Cadastrar produto</button>`)}
<div class="filters"><span class="field grow">${ic("search", "sm")}Código do produto</span><span class="chip">Somente ativos ${ic("x", "sm")}</span></div>
${card("Produtos com cotas padrão", table(
  [{ t: "Produto" }, { t: "Revisão" }, { t: "Cotas", n: 1 }, { t: "Última alteração" }, { t: "Situação" }, { t: "" }],
  [
    ["<b>SL-220</b><span class=\"sub\">Suporte lateral</span>", "C", "6", "02/11 · Sandro", st("ok", "Ativo"), `<button class="btn ghost sm">${ic("edit", "sm")}Editar</button>`],
    ["<b>TP-40</b><span class=\"sub\">Tampa</span>", "A", "4", "28/10 · Sandro", st("ok", "Ativo"), `<button class="btn ghost sm">${ic("edit", "sm")}Editar</button>`],
    ["<b>ET-90</b><span class=\"sub\">Eixo traseiro</span>", "B", "9", "15/10 · operador (1ª vez)", st("info", "Revisar"), `<button class="btn ghost sm">${ic("edit", "sm")}Editar</button>`],
    ["<b>CB-12</b><span class=\"sub\">Chapa base</span>", "A", "3", "01/09 · Sandro", st("off", "Inativo"), `<button class="btn ghost sm">${ic("edit", "sm")}Editar</button>`],
  ], { foot: "Mostrando 4 de 318" }), { flush: true })}
${notice("info", "\"Revisar\" = cadastrado pelo operador na primeira vez", "A cota vale desde já, mas a Qualidade ainda não conferiu. Confira e salve para tirar a etiqueta.")}`;

SCREENS["q-spc"] = () => {
  const pts = [10.02, 10.05, 9.98, 10.01, 10.07, 10.03, 9.99, 10.04, 10.11, 10.06, 10.02, 10.0, 9.97, 10.03, 10.08, 10.13, 10.05, 10.01];
  const y = (v) => 190 - (v - 9.9) * 700;
  const path = pts.map((v, i) => `${i ? "L" : "M"}${30 + i * 40},${y(v).toFixed(1)}`).join(" ");
  return `
${head("SPC — controle estatístico", "Mostra se uma medida está estável ao longo do tempo. Ponto fora das linhas vermelhas = algo mudou no processo.")}
<div class="filters"><span class="field">${ic("box", "sm")}<small>Produto</small> SL-220 ${ic("down", "sm")}</span><span class="field">${ic("ruler", "sm")}<small>Cota</small> Altura da aba (10,00 mm) ${ic("down", "sm")}</span><span class="field">${ic("calendar", "sm")}<small>Período</small> Últimos 30 dias ${ic("down", "sm")}</span></div>
${kpis(4, [
  kpi({ label: "Cpk", value: "1,12", tone: "warn", bar: 75, goal: 89, say: "Abaixo de 1,33: o processo cabe na tolerância, mas com pouca folga." }),
  kpi({ label: "Média", value: "10,04", unit: "mm", say: "Nominal 10,00 · deslocada 0,04 para cima.", help: false }),
  kpi({ label: "Medições", value: "18", help: false }),
  kpi({ label: "Fora de controle", value: "1", tone: "bad", say: "Ponto 16 acima do limite superior.", help: false }),
])}
${card("Carta de controle — Altura da aba", `<svg viewBox="0 0 740 220" style="width:100%;height:auto">
  <line x1="20" x2="730" y1="${y(10.12)}" y2="${y(10.12)}" stroke="var(--stop)" stroke-dasharray="5 4"/><text x="732" y="${y(10.12) + 4}" font-size="11" fill="var(--stop)" text-anchor="end" dy="-6">LSC 10,12</text>
  <line x1="20" x2="730" y1="${y(10.04)}" y2="${y(10.04)}" stroke="var(--muted)"/><text x="732" y="${y(10.04) - 6}" font-size="11" fill="var(--muted)" text-anchor="end">Média 10,04</text>
  <line x1="20" x2="730" y1="${y(9.96)}" y2="${y(9.96)}" stroke="var(--stop)" stroke-dasharray="5 4"/><text x="732" y="${y(9.96) + 14}" font-size="11" fill="var(--stop)" text-anchor="end">LIC 9,96</text>
  <path d="${path}" fill="none" stroke="var(--primary)" stroke-width="2"/>
  ${pts.map((v, i) => `<circle cx="${30 + i * 40}" cy="${y(v).toFixed(1)}" r="${v > 10.12 ? 6 : 3.5}" fill="${v > 10.12 ? "var(--stop)" : "var(--primary)"}"/>`).join("")}
</svg>`, { foot: `${ic("warn", "sm")}Ponto 16 (12/11, Gasparini, Rafael S.) passou do limite superior. Verifique ferramenta de dobra antes do próximo lote.` })}
${gloss([["LSC / LIC", "Limites de controle, calculados das próprias medições. Diferentes da tolerância do desenho."], ["Cpk", "Quanto o processo cabe na tolerância. 1,33 ou mais = confortável; abaixo de 1 = vai gerar peça ruim."]], 2)}`;
};

SCREENS["q-rnc"] = () => `
${head("Decisão de RNC", "Peças não conformes aguardando decisão da Qualidade: usar como está, retrabalhar ou refugar.")}
<div class="filters"><div class="seg"><button class="on">Aguardando decisão (4)</button><button>Decididas</button><button>Todas</button></div></div>
<div class="grid g12">
  ${card("Aguardando", table([{ t: "RNC" }, { t: "Peça" }, { t: "Há" }], [
    flag(["<b>RNC 0412</b>", "TP-40 · 3 pç", "2 dias"]), ["<b>RNC 0415</b>", "SL-220 · 1 pç", "6 h"], ["<b>RNC 0416</b>", "ET-90 · 2 pç", "3 h"], ["<b>RNC 0417</b>", "CR-7 · 5 pç", "40 min"],
  ]), { flush: true })}
  ${card("RNC 0412 · Tampa TP-40", `<dl class="kv"><dt>Problema</dt><dd>Furo deslocado 1,5 mm (tolerância ±0,5)</dd><dt>Onde</dt><dd>Dobra · 1303 · OP 012331</dd><dt>Aberta por</dt><dd>Marcos L. · 11/11 14:20</dd><dt>Armazém</dt><dd>07 (cartão laranja)</dd></dl>
    <div class="form" style="margin-top:16px">
      <label>Decisão<span class="seg" style="margin-top:6px"><button>Usar como está</button><button class="on">Retrabalhar</button><button>Refugar</button></span></label>
      <label class="err">Justificativa<span class="field" style="height:64px;align-items:flex-start;padding-top:8px">—</span><small>${ic("err", "sm")}Escreva o motivo da decisão. Ela fica no histórico da peça.</small></label>
    </div>`, { foot: `<span class="grow"></span><button class="btn primary">Registrar decisão</button>` })}
</div>
${notice("warn", "RNC 0412 aguarda decisão há 2 dias", "As 3 peças estão paradas no Armazém 07 e seguram a OP 012331.")}`;

/* ============ DIRETORIA / MELHORIA / ÁREA / MANUTENÇÃO ============ */
SCREENS["director"] = () => `
${head("Diretoria", "Quanto produzimos, onde perdemos tempo e quanto isso custou.")}
${filters({ chips: [], period: true })}
${brief(`Em outubro as paradas custaram <em class="bad">R$ 84,2 mil</em>, 12% menos que setembro. <em>Serra</em> foi o setor que mais perdeu; <em class="ok">Corte</em> o que melhor aproveitou o tempo.`, [], "Outubro/2026 · custo/hora cadastrado por recurso")}
${kpis(4, [
  kpi({ label: "Custo das paradas", value: "R$ 84,2", unit: "mil", cmp: "−12% vs setembro", cmpDir: "up", tone: "warn", say: "Horas paradas × custo/hora de cada recurso." }),
  kpi({ label: "Horas trabalhadas", value: "6.910", unit: "h", help: false }),
  kpi({ label: "Melhor setor", value: "Corte", unit: "74%", tone: "ok", say: "Maior utilização do mês.", help: false }),
  kpi({ label: "Pior setor", value: "Serra", unit: "47%", tone: "bad", say: "48 h paradas, 61% manutenção.", help: false }),
])}
<div class="grid g2">
  ${card("Onde mais perdemos (R$)", `<div class="hbars">${hb("Manutenção corretiva", 100, "R$ 31,4 mil", C.stop)}${hb("Setup acima do padrão", 58, "R$ 18,2 mil", C.setup)}${hb("Falta de material", 45, "R$ 14,1 mil", C.stop)}${hb("Aguardando Qualidade", 33, "R$ 10,3 mil", C.stop)}${hb("Retrabalho", 26, "R$ 8,1 mil", C.rework)}</div>`)}
  ${card("Por setor", table([{ t: "Setor" }, { t: "Trabalhou", n: 1 }, { t: "Parado", n: 1 }, { t: "Custo do trabalho", n: 1 }, { t: "Custo das paradas", n: 1 }], [
    ["Corte", "1.720 h", "38 h", "R$ 206 mil", "R$ 9,1 mil"], ["Dobra", "1.210 h", "61 h", "R$ 133 mil", "R$ 13,4 mil"], ["Pintura", "1.480 h", "42 h", "R$ 118 mil", "R$ 6,7 mil"], flag(["Serra", "420 h", "48 h", "R$ 38 mil", "R$ 21,6 mil"]),
  ]), { flush: true })}
</div>
${notice("info", "Custo calculado com o custo/hora cadastrado", "3 recursos não têm custo/hora e ficam de fora do total. Cadastre em \"Custos por recurso\" no fim desta tela.")}`;

SCREENS["improve"] = () => `
${head("Melhoria Contínua", "Onde estão as maiores oportunidades: as causas de parada que mais tomam tempo e as operações que mais passam do tempo padrão.")}
${filters({ chips: [] })}
<div class="grid g2">
  ${card("Maiores causas de parada", table([{ t: "Causa" }, { t: "Vezes", n: 1 }, { t: "Tempo total", n: 1 }, { t: "% das paradas", n: 1 }], [
    ["Manutenção corretiva", "14", "31h20", "34%"], ["Setup acima do padrão", "38", "18h10", "20%"], ["Falta de material", "21", "14h05", "15%"], ["Aguardando Qualidade", "17", "10h15", "11%"], ["Sem motivo informado", "9", "4h40", "5%"],
  ]), { flush: true, sub: "últimos 30 dias" })}
  ${card("Operações acima do tempo padrão", table([{ t: "Produto · operação" }, { t: "Padrão", n: 1 }, { t: "Real (média)", n: 1 }, { t: "Diferença", n: 1 }], [
    ["SL-220 · 20 Dobra", "1h30", "2h05", `<span class="down">+39%</span>`], ["ET-90 · 30 Serra", "2h00", "2h40", `<span class="down">+33%</span>`], ["CR-7 · 50 Pintura", "3h20", "4h00", `<span class="down">+20%</span>`], ["TP-40 · 10 Corte", "0h40", "0h46", `<span class="down">+15%</span>`],
  ]), { flush: true, sub: "mínimo de 5 execuções" })}
</div>
${notice("info", "Como usar esta tela", "Comece pela primeira linha de cada lista: ela é a que mais devolve tempo se for resolvida. \"Sem motivo informado\" se resolve na Auditoria.")}`;

SCREENS["area-serra"] = () => `
${head("Minha área · Serra", "Os recursos da Serra agora e a fila de prioridades que o líder organiza para os operadores.")}
${kpis(3, [
  kpi({ label: "Produzindo agora", value: "1", unit: "de 2", help: false }),
  kpi({ label: "Parados", value: "1", tone: "bad", say: "S-02 em manutenção há 2h10.", help: false }),
  kpi({ label: "OPs na fila", value: "6", help: false }),
])}
<div class="grid g21">
  ${card("Recursos da Serra", table([{ t: "Recurso" }, { t: "Estado" }, { t: "OP" }, { t: "Operador" }, { t: "Há", n: 1 }], [
    flag(["<b>S-02</b>", STATE.maint(), "012300", "—", "2h10"]), ["<b>S-01</b>", STATE.prod(), "012317", "Paulo R.", "55 min"],
  ]), { flush: true })}
  ${card("Fila de prioridades", `<ol class="steps queue">
    <li class="now"><b>1 · OP 012317</b><span>Tubo TB-30 · 40 pç · ${ic("pin", "sm")}fixada pelo líder</span></li>
    <li><b>2 · OP 012300</b><span>Eixo ET-90 · 7 pç restantes · volta quando S-02 liberar</span></li>
    <li><b>3 · OP 012352</b><span>Barra BR-12 · 120 pç</span></li>
    <li><b>4 · OP 012355</b><span>Perfil PF-8 · 60 pç</span></li>
  </ol>`, { right: `<button class="btn sm">${ic("plus", "sm")}Adicionar</button>`, foot: `${ic("info", "sm")}Arraste para mudar a ordem. O operador vê esta fila na tela dele.` })}
</div>`;

SCREENS["maint"] = () => `
${head("Sugestões de manutenção", "Recursos que o sistema sugere revisar por causa de paradas repetidas ou longas. Aceite para planejar a manutenção, ou descarte com uma nota.")}
<div class="filters"><div class="seg"><button class="on">Sugeridas (3)</button><button>Aceitas (8)</button><button>Descartadas (5)</button></div></div>
${kpis(3, [
  kpi({ label: "Sugeridas", value: "3", tone: "warn", say: "Aguardando sua decisão.", help: false }),
  kpi({ label: "Aceitas no mês", value: "8", help: false }),
  kpi({ label: "Descartadas no mês", value: "5", help: false }),
])}
${card("Aguardando decisão", table([{ t: "Recurso" }, { t: "Por que foi sugerido" }, { t: "Última OP" }, { t: "" }], [
  flag(["<b>S-02</b><span class=\"sub\">Serra</span>", "4 paradas por \"lâmina travando\" em 7 dias (5h50 no total)", "012300", `<div class="row" style="gap:6px"><button class="btn primary sm">Aceitar</button><button class="btn sm">Descartar</button></div>`]),
  ["<b>Laser ensis 3015</b><span class=\"sub\">Corte</span>", "Alarme de gás 3 vezes esta semana", "012340", `<div class="row" style="gap:6px"><button class="btn primary sm">Aceitar</button><button class="btn sm">Descartar</button></div>`],
  ["<b>Solda Robô</b><span class=\"sub\">Solda</span>", "Parada de 1h40 por falha de alimentação de arame", "012322", `<div class="row" style="gap:6px"><button class="btn primary sm">Aceitar</button><button class="btn sm">Descartar</button></div>`],
]), { flush: true })}
${notice("info", "Esta conta vê só esta tela", "A conta Manutenção não acessa a gestão. Ao descartar, escreva uma nota curta: ela evita que a mesma sugestão volte sem motivo.")}`;

/* ============ ADMINISTRAÇÃO ============ */
const editBtn = `<button class="btn ghost sm">${ic("edit", "sm")}Editar</button>`;
SCREENS["dev-badges"] = () => `
${head("Crachás", "Crachás dos operadores e quem pode liberar OP bloqueada (responsáveis autorizados).", `<button class="btn primary">${ic("plus", "sm")}Novo crachá</button>`)}
${kpis(4, [kpi({ label: "Ativos", value: "184", help: false }), kpi({ label: "Responsáveis autorizados", value: "12", help: false }), kpi({ label: "Sem responsável", value: "2", unit: "setores", tone: "warn", say: "Nesses setores, OP bloqueada não tem quem libere.", help: false }), kpi({ label: "Inativos", value: "23", help: false })])}
${notice("warn", "Pintura e Protótipo estão sem responsável autorizado", "Se uma OP bloquear nesses setores, nenhum crachá consegue liberar. Marque ao menos uma pessoa como responsável.", `<button class="btn sm">Definir responsável</button>`)}
${card("Crachás cadastrados", table([{ t: "Crachá" }, { t: "Nome" }, { t: "Setor" }, { t: "Responsável" }, { t: "Situação" }, { t: "" }], [
  ["<span class=\"mono\">004512</span>", "Ana P.", "Corte", st("ok", "Sim"), st("ok", "Ativo"), editBtn],
  ["<span class=\"mono\">004530</span>", "Rafael S.", "Dobra", "—", st("ok", "Ativo"), editBtn],
  ["<span class=\"mono\">004611</span>", "Elias N.", "Solda", st("ok", "Sim"), st("ok", "Ativo"), editBtn],
  ["<span class=\"mono\">003980</span>", "Jorge K.", "Serra", "—", st("off", "Inativo"), editBtn],
], { foot: "Mostrando 4 de 207" }), { flush: true })}`;

SCREENS["dev-users"] = () => `
${head("Cadastro de usuários", "Contas que entram no sistema e o nível de acesso de cada uma. O nível decide quais telas a pessoa vê.", `<button class="btn">${ic("plus", "sm")}Novo nível de acesso</button><button class="btn primary">${ic("plus", "sm")}Novo usuário</button>`)}
${kpis(4, [kpi({ label: "Usuários ativos", value: "64", help: false }), kpi({ label: "Contas admin", value: "3", help: false }), kpi({ label: "Inativos", value: "9", help: false }), kpi({ label: "Níveis personalizados", value: "18", help: false })])}
${card("Usuários", table([{ t: "Nome" }, { t: "Login" }, { t: "Nível" }, { t: "O que vê" }, { t: "Último acesso" }, { t: "" }], [
  ["Gestor de exemplo", "<span class=\"mono\">gestor.ex</span>", "Gestor", "Gestão completa, sem Admin", "hoje 09:12", editBtn],
  ["Líder da Serra", "<span class=\"mono\">lider.serra</span>", "Líder · Serra", "Gestão + área Serra", "hoje 07:40", editBtn],
  ["Qualidade de exemplo", "<span class=\"mono\">qualidade.ex</span>", "Qualidade", "Gestão + Qualidade", "ontem", editBtn],
  ["Manutenção de exemplo", "<span class=\"mono\">manut.ex</span>", "Manutenção", "Só Sugestões de manutenção", "12/11", editBtn],
]), { flush: true })}
${notice("info", "Ao excluir um usuário", "A conta deixa de entrar, mas tudo o que ela registrou continua no histórico com o nome dela.")}`;

SCREENS["dev-calls"] = () => `
${head("Chamadas do Admin", "Quem recebe cada chamada feita pelo botão Chamar, e por onde (Telegram).", `<button class="btn primary">${ic("plus", "sm")}Novo contato</button>`)}
${kpis(3, [kpi({ label: "Contatos ativos", value: "9", help: false }), kpi({ label: "Setores sem contato", value: "1", tone: "warn", say: "Protótipo: o botão Chamar abre vazio lá.", help: false }), kpi({ label: "Falhas de envio (7 dias)", value: "2", tone: "warn", help: false })])}
${card("Contatos", table([{ t: "Nome" }, { t: "Função" }, { t: "Conta do sistema" }, { t: "Telegram" }, { t: "Setores" }, { t: "" }], [
  ["Qualidade de exemplo", "Qualidade", "qualidade.ex", st("ok", "Ligado"), "Todos", editBtn],
  ["Manutenção de exemplo", "Manutenção", "manut.ex", st("ok", "Ligado"), "Todos", editBtn],
  warnRow(["PCP de exemplo", "PCP", "pcp.ex", st("stop", "Falhou 2×"), "Corte, Dobra", editBtn]),
]), { flush: true })}
${notice("err", "2 chamadas não chegaram ao PCP de exemplo", "O Telegram recusou o envio (conversa bloqueada). As chamadas ficaram registradas no sistema. Peça à pessoa para abrir o bot de novo.", "", "Código para o suporte: TG-403")}`;

SCREENS["dev-shifts"] = () => `
${head("Turnos", "Horário oficial de trabalho, horas extras e faixas fora do turno. Os números de OEE e utilização usam esta tabela.", `<button class="btn primary">${ic("plus", "sm")}Novo turno</button>`)}
${kpis(4, [kpi({ label: "Janela oficial", value: "08:00–17:30", help: false, say: "H1 08:00–12:00 · H2 13:00–17:30" }), kpi({ label: "Horas extras ativas", value: "2", help: false }), kpi({ label: "Faixas fora de turno", value: "3", help: false }), kpi({ label: "Apontamentos fora do turno", value: "5", unit: "esta semana", tone: "warn", help: false })])}
${card("Turnos cadastrados", table([{ t: "Nome" }, { t: "Tipo" }, { t: "Início" }, { t: "Fim" }, { t: "Ativo" }, { t: "" }], [
  ["<b>Turno único</b>", "Oficial", "08:00", "17:30", st("ok", "Sim"), editBtn],
  ["<b>Hora extra sábado</b>", "Hora extra", "07:00", "12:00", st("ok", "Sim"), editBtn],
  ["<b>Hora extra noite Corte</b>", "Hora extra", "17:30", "21:00", st("ok", "Sim"), editBtn],
  ["<b>Turno 2 (antigo)</b>", "Oficial", "17:30", "02:00", st("off", "Não"), editBtn],
]), { flush: true })}
${notice("warn", "Mudar um turno muda números do passado", "O OEE de dias anteriores é recalculado com o turno novo. Se o horário mudou só daqui para frente, crie um turno novo com data de início.")}`;

SCREENS["dev-sector"] = () => `
${head("Apontamento por setor", "Abre a tela do operador de um setor, para apontar em nome dele quando o posto estiver sem computador.")}
<div class="res-grid" style="--rc:3">${[["Solda", "16 estações · Aço, Alumínio, Robô"], ["Projetos", "Ferramentaria · 2 recursos"], ["Protótipo", "1 recurso"]].map(([n, d]) => `<div class="res"><div class="nm">${n}<span class="sec">${d}</span></div><button class="btn primary sm" style="margin-top:12px">${ic("play", "sm")}Abrir tela do operador</button></div>`).join("")}</div>
${empty("Outros setores apontam no próprio posto", "Corte, Dobra, Serra, Usinagem e Pintura têm computador no posto e não aparecem aqui.", "info")}`;

SCREENS["dev-changes"] = () => `
${head("Alterações", "Tudo o que foi mudado nos cadastros: quem mudou, quando e o valor antes e depois. Algumas mudanças podem ser desfeitas.")}
<div class="filters"><span class="field">${ic("layers", "sm")}<small>O quê</small> Todos ${ic("down", "sm")}</span><span class="field">${ic("users", "sm")}<small>Quem</small> Todos ${ic("down", "sm")}</span><span class="field">${ic("calendar", "sm")}<small>Até</small> hoje ${ic("down", "sm")}</span></div>
${card("Histórico", table([{ t: "Quando" }, { t: "Quem" }, { t: "O quê" }, { t: "Mudança" }, { t: "" }], [
  ["13/11 09:05", "Admin de exemplo", "Turno · Hora extra sábado", `Fim: <s class="dim">11:00</s> → <b>12:00</b>`, `<button class="btn ghost sm">Desfazer</button>`],
  ["12/11 17:22", "Qualidade de exemplo", "Cota · SL-220 altura da aba", `Tolerância: <s class="dim">±0,10</s> → <b>±0,15</b>`, `<button class="btn ghost sm">Desfazer</button>`],
  ["12/11 10:40", "Admin de exemplo", "Usuário · lider.serra", `Nível: <s class="dim">Líder</s> → <b>Líder · Serra</b>`, ""],
]), { flush: true })}`;

SCREENS["dev-protheus"] = () => `
${head("Envios ao Protheus", "Apontamentos que o sistema enviou ao Protheus. Os que deram erro ficam aqui até alguém reenviar ou descartar.")}
<div class="filters"><div class="seg"><button class="on">Com erro (2)</button><button>Descartados</button><button>Todos</button></div><span class="grow"></span><span class="live"><span class="led"></span>Protheus TEST conectado</span></div>
${card("Com erro", table([{ t: "Quando" }, { t: "OP · operação" }, { t: "O que o Protheus respondeu" }, { t: "O que fazer" }, { t: "" }], [
  flag(["13/11 08:44", "<b>012329</b> · 20", "Saldo insuficiente no armazém 01", "Confirmar o saldo com o almoxarifado e reenviar", `<div class="row" style="gap:6px"><button class="btn primary sm">Reenviar</button><button class="btn sm">Descartar</button></div>`]),
  flag(["12/11 16:10", "<b>012288</b> · 50", "OP já encerrada no Protheus", "Descartar: o apontamento chegou depois do encerramento", `<div class="row" style="gap:6px"><button class="btn sm">Reenviar</button><button class="btn danger sm">Descartar</button></div>`]),
]), { flush: true })}
${notice("info", "Reenviar é seguro", "O sistema confere se o apontamento já entrou no Protheus antes de reenviar; não duplica.")}`;

SCREENS["dev-system"] = () => `
${head("Sistema", "Ações de manutenção do servidor. Use só quando o suporte pedir.")}
<div class="grid g2">
  ${card("Atualizar a tela da gestão", `<p style="margin:0 0 14px">Gera de novo os arquivos das telas (build). Leva cerca de 1 minuto; quem estiver usando precisa recarregar a página depois.</p><button class="btn primary">${ic("refresh", "sm")}Gerar build do frontend</button>`)}
  ${card("Conexões", `<dl class="kv"><dt>Protheus</dt><dd>${st("ok", "Conectado")} TEST · 09:40</dd><dt>SigmaNEST</dt><dd>${st("setup", "Atrasado")} última leitura há 25 min</dd><dt>Banco</dt><dd>${st("ok", "OK")}</dd></dl>`)}
</div>
${notice("err", "O último build falhou", "A tela continua funcionando com a versão anterior. Veja as últimas linhas do log abaixo e envie ao suporte.", `<button class="btn sm">Copiar log</button>`, "Código para o suporte: BUILD-1")}
${card("Log do último build", `<pre class="mono" style="margin:0;white-space:pre-wrap;font-size:12px;color:var(--muted)">13/11 08:02 › npm run build
error TS2339: Property 'turno' does not exist on type 'Resumo'.
  src/pages/Inicio.tsx:212
Build terminou com erro (código 2).</pre>`)}`;
