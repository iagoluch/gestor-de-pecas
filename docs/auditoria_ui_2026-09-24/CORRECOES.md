# Correções da auditoria de UI/UX — 24/09/2026

Baseline: [RELATORIO.md](RELATORIO.md). Evidências: `docs/evidencias/correcoes_ui_2026-09-24/<onda>/`.
Scripts reexecutáveis (somente leitura, credenciais de fixture de `tests/web_preview_api.py`):
`docs/evidencias/correcoes_ui_2026-09-24/scripts/`.

Restrição respeitada: nenhum arquivo/regra específico da OEE (`.oee-*`, `Oee*`) foi alterado; o
codemod pulou toda linha com `oee`. `app/database/database.py` e `mes/services/shift_boundary.py`
(sessão paralela) ficaram fora dos commits.

## Onda 1 — Fundação

### Primitives (fonte única — usar estes, não recriar)

| Primitive | Arquivo | Quando usar |
|---|---|---|
| Tokens de estado | `web/src/styles/tokens.css` | `--state-producing/stopped/waiting/neutral`, `--success`, `--error` seguem o tema. `--fill-producing/stopped/setup/waiting/rework/neutral` + `--fill-ink`/`--fill-ink-dark` são preenchimentos com texto **medidos AA (≥4,5:1)** e iguais nos dois temas (HMI/Andon). `--setup-ink` para texto de setup. |
| Escalas | `tokens.css` | Tipo `--text-2xs…2xl` (piso de leitura 11px), raio `--radius-sm/control/md/card/panel/pill`, z-index `--z-raised…--z-popover`, breakpoints documentados no comentário (480·580·650·900·1180·1400·1680·2500). |
| `ConfirmDialog` / `useConfirm` | `web/src/components/ConfirmDialog.tsx` | Toda confirmação. `const [confirm, dialog] = useConfirm(); if (await confirm({title, message, confirmLabel, tone}))`. Rótulo é o verbo ("Remover pausa"), nunca "OK". `tone:"danger"` para desativar/remover/reiniciar. Substitui `window.confirm`. |
| `AsyncButton` | `web/src/components/AsyncButton.tsx` | Todo botão que chama o servidor. Trava por ref (o 2º clique no mesmo quadro já é ignorado), `disabled` + `aria-busy`, `pendingLabel` opcional. |
| `Notice` | `web/src/components/Notice.tsx` | Único canal de resultado em linha: `tone="info|success|error|stale"`. Erro = `role="alert"`, resto = `role="status"`. Carregamento de dados continua no `DataState`. |
| `useDialogFocus` | `web/src/hooks/useDialogFocus.ts` | Já usado por todo `OperatorDialog`: guarda quem abriu **no render** (antes do `autoFocus` roubar o foco), respeita campo com `autoFocus` e devolve o foco ao fechar. |

### ID → status

| ID | Antes | Depois | Evidência |
|---|---|---|---|
| TE-01 | CSP bloqueava o script inline de tema (erro de console, tema piscando) | **CORRIGIDO** — script externo `web/public/theme-init.js`; CSP `script-src 'self'` intacta | `check.py`: 148/148 páginas com `data-theme` = tema pedido e sem erro de CSP; `dist/theme-init.js` no build |
| TE-02 | 40 tamanhos de fonte, 20 raios, z-index soltos, `!important` | **CORRIGIDO (fundação)** — 291 literais → tokens em `global.css`/`welding.css`/`ai.css`; z-index em escala; `!important` só em reduced-motion e `.visually-hidden` (legítimos) + `.andon-card__quantity` (Onda 2). `andon.css` e a região do Andon em `global.css` ficam para a Onda 2 | `check.py`: 0 texto < 11px, 0 overflow horizontal, 0 texto cortado em 37 rotas × claro/escuro × 1366/320 |
| AX-02 | Foco caía no `body` ao fechar diálogo | **CORRIGIDO** na raiz (`useDialogFocus`, vale para todos os diálogos) | `primitives.test.tsx` (autoFocus + Escape); `confirm_dialog.py`: `focusReturnedToOpener: true` |
| AX-05 | FAB acima do scrim do menu mobile; foco fora da gaveta | **PARCIAL** — FAB agora abaixo do scrim (`--z-fab` < `--z-scrim`). Trap/Escape da gaveta: Onda 3 | escala z-index em `tokens.css` |
| Drift `operator-notice--danger` | classe sem CSS (erro aparecia como aviso neutro) | **CORRIGIDO** — mapeado para `Notice tone="error"` | `primitives.test.tsx` |
| Diálogos em 320px | `96vw` + padding 26px estourava a largura útil | **CORRIGIDO** no `OperatorDialog` (largura/altura = área útil, respiro `clamp`) | `confirm_dialog.py`: `dialogInViewport: true` em 1366 e 320; `onda1/confirm_dialog_*.png` |
| GE-01 (Pausas) | `window.confirm` nativo | **CORRIGIDO em Pausas** (Ativar/Desativar/Remover). Demais telas: Onda 2 | `pauses.test.tsx` |

### Validação

- `vitest` nos arquivos afetados: primitives, pauses, operator, quality, ai, badges, chamada-button, shifts,
  management, cutting-hierarchy, system-state → **169/169**. `pauses.test.tsx` passou a clicar no diálogo
  (não há mais `window.confirm`); `operator.test.tsx` ganhou `timeout: 4000` num `findByRole` que dependia de
  sync→refetch e estourava 1s só sob carga (passa isolado; não é regressão).
- `tsc --noEmit` limpo; `npm run build` ok (aviso de chunk > 500 kB é anterior).
- Inspeção real (Playwright, preview 8010): `onda1/metrics.json` + capturas claro/escuro.

### Achados fora do escopo (registrados, não alterados)

- Preview: `GET /api/v1/chamadas/nao-vistas` → 500 (`ApiFakeDatabase` sem `contar_chamadas_nao_vistas`). Lacuna da fixture, não do produto.
- Gestor sem perfil admin recebe 403 em Crachás/Turnos/Cadastro (esperado); a apresentação do 403 é item da Onda 3.

## Onda 2 — P1 / HMI

### ID → status

| ID | Antes | Depois | Evidência |
|---|---|---|---|
| AN-01 | Andon em TV: nome 13px, estado 10px, cronômetro 11px (1920) | **CORRIGIDO** — tipografia em `cqi` (escala com a largura do card): 1920 → nome 13,4–18,4 / estado 10–13,7 / cronômetro 14,7–20,2px; 2560 → 18–24,3 / 13,3–18 / 19,7–26,6px. Altura de card por faixa de viewport (`--andon-card-height`) | `andon.py`: `onda2/andon_{antes,depois}.json` + `andon_*_{1920,2560,1366}.png` |
| AN-02 | Motivo da parada truncado (8 textos cortados a 1920, 3 a 2560) | **CORRIGIDO** — motivo em linha própria com quebra (`white-space: normal`), sem `ellipsis`: **0 cortes** e 0 overflow a 1920 e 2560 | idem |
| AN-03 | Parada só com borda/ponto; mesma massa visual de "produzindo" | **CORRIGIDO** — cabeçalho inteiro com fundo sólido `--fill-stopped` (rgb 200,30,44) + borda esquerda 6px; parada **planejada** (classificação do backend) em âmbar `--fill-waiting` | `stopHeaderBg` em `andon_depois.json`; `andon.test.tsx` 15/15 |
| OP-01 | "Iniciar" 1,87:1; "Parada" 3,66:1; desabilitado = cor original desbotada | **CORRIGIDO por token** — `.operator-action--*` usam `--fill-*`/`--fill-ink*`: produzindo 5,02 · parada 5,71 · finalizar 8,08 (tinta escura) · setup 5,36 · retrabalho 9,40; desabilitado = `--fill-neutral` 5,48 + ícone em escala de cinza | `onda2/operador_depois_{1366,1024}.png`; cálculo WCAG dos pares |
| OP-02 | Estado do posto só num badge pequeno | **CORRIGIDO** — `StationStateBanner` (novo, `role=status`) no topo de Dobra/Corte/Destaque: rótulo + OP + motivo + "desde hh:mm", cor do estado. Só rotula `resource_state.categoria` do backend (não infere estado) | `operator.test.tsx` (asserção do banner); `operador_depois_1366.png` |
| OP-03 | "Iniciar" habilitado com outro apontamento ativo; 409 na barra neutra | **CORRIGIDO** — Iniciar desabilitado com motivo "Recurso em uso pela OP …" (mesma regra do 409 `operator_resource_occupied`, `operator_flow.py:953-960`); erros agora em `Notice tone="error"` | `operator.test.tsx` (teste ajustado para provar o bloqueio) |
| OP-04 | Duplo clique em "Confirmar finalização" → 2 POST | **CORRIGIDO** — todos os botões de confirmação do operador (Workbench/Corte/Destaque) viraram `AsyncButton pendingLabel="Enviando…"`, travados de forma síncrona até a promessa resolver | `primitives.test.tsx` (AsyncButton), `operator.test.tsx` |
| GE-01 | Desativar/Remover/Reiniciar build executavam direto; 3 padrões | **CORRIGIDO** — `useConfirm` único em Usuários, Crachás, Chamadas (remover responsável/contato) e Sistema (Reiniciar build), além de Pausas (Onda 1) | `users.test.tsx` e `chamadas.test.tsx` (novos), `badges.test.tsx`; Sistema: `confirms.py` abre o diálogo "Reiniciar build" e cancela → 0 escritas (`onda2/confirms.json`, `confirm_sistema.png`) |
| GE-02 | Admin se desativava e ficava trancado | **CORRIGIDO** — guarda no backend (409 `user_self_lockout` ao desativar/rebaixar a própria conta) + botão bloqueado na própria linha no front. "Último admin" coberto por consequência: quem salva é sempre admin ativo. **JUSTIFICADO (não alterado):** o login continua com "Usuário ou senha inválidos." para conta inativa — distinguir "inativo" permitiria enumerar usuários | `tests/test_user_management.py` 9/9; `users.test.tsx` |
| AX-01 | FAB 2,76 · badge 4,02/2,75 · escopo 2,98 · créditos 4,21 · pílulas 4,39–4,44 | **CORRIGIDO por token** — FAB: `--fill-ink-dark` sobre o laranja da marca (6,29); badge: `--fill-stopped` + `--fill-ink` (5,71); escopo: `--success-ink` (4,92 claro / 7,89 escuro); `--sidebar-text-faint` #6582a6→#7a93b8 (5,32, vale para créditos da gestão e do operador); novo `--info-ink` (claro = `--primary` 4,65; escuro #7aa8ff 5,42) em `.status-badge--info` e hovers do date-picker | `contrast.py`: `onda2/contrast_{antes,depois}.json` — depois: **0 falhas** em claro e escuro |

### Justificativas (não alterado de propósito)

- **AN-03, escalonamento por tempo** (parada "longa" piscando/mais forte): não implementado — exigiria inventar um limiar que não existe no MES. A saliência vem só do estado e da classificação que o backend já envia.
- **AN-01, rodízio por setor**: decisão de produto, fora do escopo de UI.
- **AN-04 (1366×768)**: ainda há `overflowY` 10px / 1 card cortado — igual à linha de base; é o AN-04 (P2) e fica na Onda 3.
- **Preview do operador mostra "Sem apontamento"**: a fixture `tests/web_preview_api.py` não envia `resource_state`; o backend real envia (`backend/api/routers/operator.py:260`). Os tons da faixa estão provados em vitest.

### Limpeza

- `.andon-card__quantity` (3 regras, incluindo o `!important` restante da Onda 1) removido de `global.css`: sem nenhum uso em TSX. `.andon-page--embedded` também está órfão → Onda 4.

### Validação

- `vitest` (operator, cutting-hierarchy, quality, andon, users, badges, pauses, primitives, chamada-button, system-state, management, chamadas) → **140/140**; `tsc --noEmit` limpo; `npm run build` ok.
- `python -m unittest tests.test_user_management` → 9/9.
- Regressão da gestão (`check.py onda2`): 148 combinações (37 rotas × claro/escuro × 1366/320) — 0 overflow horizontal, 0 texto cortado, 0 texto < 11px; os 12 erros de console são os mesmos 403 do gestor já registrados na Onda 1 (idêntico a `onda1/metrics.json`).
- OEE: nenhuma linha com `oee` no diff de estilos; `.oee-*` e `.andon-card__oee` intactos.

## Onda 3 — P2

Três commits: parte 1 (a739155 — TV, exportação, 403, teclado), parte 2 (ee95754 — operador) e o restante (gestão + Dev Observatory, este commit).

### Primitives novos (fonte única)

- `RowActions` — ação primária visível + menu "⋯" (popover nativo: fecha ao clicar fora/Escape, foco no 1º item, destrutivas separadas no fim). Nomes acessíveis com contexto: "Editar: Almoço · Caldeiraria", "Mais ações: …".
- `ValidatedForm` / `validarFormulario` / `Obrigatorio` — validação inline pt-BR ("Preencha Descrição."), foco no 1º campo inválido, `aria-invalid`, `*` de obrigatório `aria-hidden`.
- `useDraft` — estado sujo: fechar/Escape com alteração abre "Descartar alterações?" (via `useConfirm`).
- `useDialogFocus` com pilha: só o diálogo do topo trata Escape e o Tab trap.
- `OperatorDialog` via portal no `body` + título por `useId`.

### ID → status

| ID | Antes | Depois | Evidência |
|---|---|---|---|
| AN-04 | Solda/Andon com rolagem a 1280/1366 | **CORRIGIDO** (parte 1) | 0px de rolagem a 1280 e 1366 |
| AN-05 | TV em branco ao cair a rede no rodízio | **CORRIGIDO** (parte 1) — último quadro + "dados de hh:mm" | `keepLastSnapshot` |
| GE-03 | Exportar navegava para JSON de erro | **CORRIGIDO** (parte 1) — `api.download` + erro inline pt-BR | |
| GE-04 | Salvar sem motivo; validação nativa em inglês | **CORRIGIDO** — `ValidatedForm` em Pausas, Crachás, Chamadas, Turnos, Usuários e Login | teste "explica em pt-BR o campo obrigatório vazio" (foco + `aria-invalid` + nenhum POST); visto no 8010 |
| GE-05 | Editar → Escape perdia a edição | **CORRIGIDO** — `useDraft` nos 5 cadastros | visto no 8010 com teclado real: Escape → "Descartar alterações?" por cima |
| GE-06 | 22:00–21:00 aceito sem explicação | **CORRIGIDO na UI** — o servidor aceita fim < início (turno que vira o dia); a tabela mostra "21:00 (dia seguinte)". Nenhuma regra nova inventada no front | `shifts.test.tsx` |
| GE-07 | 403 genérico para gestor | **CORRIGIDO** (parte 1) — `RequireAdmin` → "Acesso restrito" | |
| GE-08 | Destrutivo ao lado do seguro em cada linha | **CORRIGIDO** — `RowActions` em Pausas, Crachás, Chamadas e Turnos (Remover turno agora pede confirmação) | menu "⋯" com foco em "Desativar", "Remover" separado |
| GE-09 | 14 colunas, status cortado, sem ordenação | **CORRIGIDO** — `DataTable` com colunas fixas (OP, Status sticky), ordenação com `aria-sort` e status sem corte | 8010: "Em Processo" inteiro; `aria-sort` → ascending; 0 overflow |
| GE-10 | 41,7% (KPI) × 50% (tabela) sem base | **CORRIGIDO** — cada percentual rotula a base | |
| GE-11 | 17 campos, placeholder cortado | **CORRIGIDO** — dica do ID do Telegram vira texto de ajuda ligado por `aria-describedby`, placeholder curto, setores em largura total | `chamadas.test.tsx` |
| DO-01 | 361 de 548 textos < 12px, caixa alta | **CORRIGIDO** — escala `--text-*`/`--radius-*` espelhada de `web/src/styles/tokens.css`; sem caixa alta; borda lateral colorida (side-tab) removida | harness: 0 de 110 textos < 12px |
| DO-02 | Falha de um bloco apagava painéis sem motivo | **CORRIGIDO** — falha dentro do painel ("Indisponível agora: … Mostrando a última leitura, das hh:mm:ss."), valores anteriores esmaecidos; toast só para ações do usuário | harness com métricas 500: só PostgreSQL/Processo/Rotas lentas mostram a falha |
| DO-03 | Overflow de 116px a 320px | **CORRIGIDO** — grades `minmax(min(N, 100%), 1fr)` | `scrollWidth` 320 a 320px |
| OP-05 / OP-06 | Mensagem de sucesso genérica, igual para toda ação | **CORRIGIDO** (ee95754) — mensagem por intenção no backend (`operator_flow._mensagem_sucesso`) e rótulo por intenção no botão | `WorkbenchPage.tsx` |
| OP-07 | Setup em curso reapontava o Setup | **CORRIGIDO** (ee95754) — só reabre o checklist, com `aria-pressed` | |
| OP-08 | Setup liberado sem produção iniciada, sem explicação | **CORRIGIDO** (ee95754) — dica "Inicie a produção e depois aponte o Setup" quando o Setup não está disponível | |
| OP-09 | Inspeção bloqueava sem dizer o motivo | **CORRIGIDO** (ee95754) — motivo do bloqueio, medida inválida explicada e foco no passo | `QualityInspectionPage.tsx` |
| OP-10 | Campos de medida sem rótulo visível | **CORRIGIDO** (ee95754) — "Padrão (mm)" e "Tolerância (± mm)", teclado decimal, salvar desabilitado com motivo | |
| OP-11 | Botão travado sem motivo; passar do saldo bloqueava | **CORRIGIDO** (ee95754) — motivo no botão; passar do saldo só avisa (regra existente preservada) | |
| OP-12 | OP inexistente mostrava referência técnica crua | **CORRIGIDO** (ee95754) — mensagem clara e referência dentro de "Detalhes técnicos" (`DataState`) | fluxo `http500` da Onda 5 |
| OP-13 | Alvos de toque pequenos | **CORRIGIDO** (ee95754) — 44px nos botões do posto, 24px nos alvos isolados | matriz: `tiny` 579→120 |
| OP-14 | Topbar do posto rolava de lado a 320px | **CORRIGIDO** (ee95754) | matriz: `hOverflow` dos postos 110→80 |
| OP-15 | "Parada" ambígua sem OP ativa | **CORRIGIDO** (ee95754) — "Parada do posto" quando não há OP | |
| AX-01 (Chamar) | FAB "Chamar" com contraste 2,76:1 | **CORRIGIDO** (ee95754) | fluxo `contrast`: 0 falhas |
| AX-03 | "Ver análise" sem anel de foco | **CORRIGIDO** (a739155) | |
| AX-04 | Sem skip link | **CORRIGIDO** (a739155) — "Pular para o conteúdo" é a 1ª parada do Tab | fluxo `keyboard`: `skiplink has=true` |
| AX-05 | Menu móvel perdia o foco ao fechar; FAB por cima do scrim | **CORRIGIDO** (a739155) — foco vai para o "×" ao abrir e volta ao botão ao fechar | fluxo `keyboard` |
| AX-06 | FAB "Chamar" cobria conteúdo | **CORRIGIDO** (a739155) — faixa reservada no fim da página | |

### Bugs achados na inspeção visual (corrigidos)

- **Diálogo de confirmação atrás do de edição**: os backdrops dividem `z-index: 100` e o "Descartar alterações?" vinha antes no DOM → ficava por baixo do "Editar pausa". O jsdom não pinta, então os testes passavam. Correção na camada compartilhada: `OperatorDialog` renderiza em portal no `body` (o último aberto fica no topo). Um teste do operador que buscava o diálogo no `container` passou a buscá-lo no `document`.
- **`*` de obrigatório numa linha própria** (labels em grid): `label:has(> .required-mark)` vira flex com o campo em 100%.
- **Ids de título duplicados** entre diálogos: `useId` no `OperatorDialog`.

### Pendências / observações

- Crachás, Chamadas e Turnos não foram vistos no navegador (a fixture de gestor não é admin); cobertos por teste.
- Foco inicial do "Descartar alterações?" vai para o "×"; aceitável, sem mudança.
- `app.js` do Dev Observatory ainda aplica `c-<classe>` nos postos, que agora não tem estilo (inofensivo) → Onda 4 (órfãos).
- Nenhuma nova falha no teste de refugo do operador nesta rodada (32/32).

### Validação

- `vitest`: pauses 14, badges 10, chamadas 1, shifts 4, users 2, operator 32, primitives 4, management 17 → **84/84**; `tsc --noEmit` limpo; `npm run build` ok.
- `python -m unittest tests.test_dev_observatory` → 20/20.
- 8010 (gestor, 1366×900): Ordens, Pausas (menu, validação, diálogo empilhado); Dev Observatory via harness same-origin (CSP intacta; arquivos de harness removidos do `dist`).
- OEE: nenhum arquivo nem regra `.oee-*`/`.andon-card__oee` tocados.

## Onda 4 — P3 / polish

### ID → status

| ID | Antes | Depois | Evidência |
|---|---|---|---|
| OP-16 | Botão do desenho: estado só na cor, `aria-label` ≠ texto visível | **CORRIGIDO** — o texto visível é o nome acessível ("PDF ↗" / "Sem PDF"); indisponível ganha borda tracejada | 8010 operador Dobra 1303: "Sem PDF", `border-style: dashed` |
| OP-17 | Cabeçalho do posto em caixa alta 8px, sem h1; campo da OP centralizado | **CORRIGIDO** — h1 oculto "Máquina Dobra - 1303", rótulo da máquina em `--text-sm`, crédito em `--sidebar-text-muted`, campo da OP alinhado à esquerda | 8010: `h1` = "Máquina Dobra - 1303" |
| OP-18 | Filtro de motivo sem resultado deixava uma faixa vazia | **CORRIGIDO** — a mensagem "Nenhum motivo corresponde…" (`role=status`) substitui o listbox; `aria-selected` já existia | `operator.test.tsx` |
| OP-19 | "Ver OPs" repetido com o mesmo nome para dois nestings do mesmo programa | **CORRIGIDO** — `aria-label` "Ver OPs: Nesting N do plano X" (reusa `rotuloPlano`) | `operator.test.tsx` |
| GE-12 | Preset de período sem estado ativo; abas com `role=tablist` sem setas | **CORRIGIDO** — `aria-pressed` compara o período aplicado com o do atalho; abas viram `<nav>` de links com `aria-current` (NavLink) | 8010: "Hoje:true" → clique em "7 dias" → "7 dias:true"; 0 `[role=tablist]` |
| GE-13 | Setores: vazio duplicado + destaques zerados sem setor | **CORRIGIDO E PROVADO** (Fechamento) — vazio só na tabela (`emptyTitle`), destaques somem sem setores | `management.test.tsx` "Setores sem registro": 1 vazio, 0 `.metric-card` |
| GE-13 (Performance 36,6% sem meta) | — | **CORRIGIDO E PROVADO** (Fechamento) — ver seção Fechamento | `management.test.tsx` GE-13 |
| GE-13 (11 filtros) | — | **SEM MUDANÇA** — os campos avançados já ficam atrás de "Mais filtros" | |
| IA-02 | Aba "IA" visível com a função desligada | **CORRIGIDO** — o `PageFrame` consulta `/ai/status` na Tela inicial e esconde a aba só quando o backend diz `enabled=false` (falha/carregando mantém a aba; na própria rota da IA não consulta de novo) | `ai.test.tsx` (novo teste, liga/desliga); 8010: abas "Visão Geral, Setores, Alertas" |
| AX-07 | Alto contraste: item ativo, barras e presets sem distinção | **CORRIGIDO** — bloco `@media (forced-colors: active)` com Highlight/HighlightText/CanvasText e `forced-color-adjust: none` só onde o fundo carrega informação. A "pílula cortada" da evidência é a rolagem horizontal da tabela, que acontece também fora do alto contraste — não é defeito de forced-colors | CSS; emulação completa fica para a Onda 5 |
| AN-06 | TV sem atalho de tela cheia | **ACEITO POR DECISÃO DE PRODUTO** (Fechamento; antes: não aplicado) ("não coloque botão em tv", 25/09/2026). Implementado e retirado: o botão fixo cobria a contagem do setor no Andon e "Estações com OP" na Solda (a TV alterna `/andon` ↔ `/welding-management`). Tela cheia/quiosque é configuração do navegador da TV | medição de sobreposição no 8011 a 1366×768 |
| DO-04 | Login do observatório com validação nativa em inglês, sem foco no erro | **CORRIGIDO** — `novalidate`, "Preencha Usuário."/"Preencha Senha." com foco e `aria-invalid`; 401 limpa e foca a senha; `#erro role=alert`; rótulos `<label for>` em Ambiente/Atualização | Playwright com o código atual: vazio → ("Preencha Usuário.", foco em username, `aria-invalid`); 401 → ("Usuário ou senha inválidos.", foco em password, valor vazio) — `docs/evidencias/…/onda4/do04_login_*.png` |
| DO (órfão da Onda 3) | `app.js` aplicava `c-<classe>` sem estilo | **CORRIGIDO** — removido `CATEGORIA_CLASSE`; a pílula mostra o rótulo pt-BR (`CATEGORIA_ROTULO`: Produção, Parada, Setup…) | `tests.test_dev_observatory` |
| TE-03 | `QualityPage` parecia código morto | **DOCUMENTADO** — órfã de propósito desde a Wave 6B, coberta por `quality.test.tsx` (JSDoc) | |

### Pendências / observações

- `.andon-page--embedded` e `.andon-fullscreen` (global.css): **removidos no Fechamento** (ver seção Fechamento).
- O `describe` "tela IagoDev" de `shifts.test.tsx` está correto: o título da tela é literalmente "IagoDev — Turnos". Sem mudança.
- A 8001 (servidor do Dev Observatory aberto fora da sessão) roda o código antigo; o DO-04 foi validado num servidor temporário com o código atual.
- As pílulas "Produção" do observatório não foram vistas renderizadas: o banco falso do teste não implementa `fetchall` nos eventos (limitação do ambiente de teste).

### Validação

- `vitest`: management, andon, operator, shifts, ai, primitives → **86/86**; andon + welding-management após retirar o AN-06 → **41/41**; `tsc --noEmit` limpo; `npm run build` ok.
- `python -m unittest tests.test_dev_observatory` → 20/20.
- 8010 (gestor e operador) e 8011 (Andon/Solda TV) inspecionados após o build.
- OEE: nenhum arquivo nem regra `.oee-*`/`.andon-card__oee` tocados.

## Onda 5 — Regressão

Mesma bateria da auditoria (matriz de layout, fluxos, emulações, contraste, rede, Web Vitals e detector), rodada contra o código atual numa instância limpa (`tests/web_preview_api.py` na 8013, `web/dist` recém-buildado). Chromium apenas: Firefox/WebKit não foram testados, por decisão do usuário.

### Matriz (430 pares: 39 rotas de gestão + Dobra/Corte/Destaque/Solda × 1024, 1280, 1366, 1440, 1600, 1920, 2560, 853×480, 640×360, 320×256)

Os tamanhos 853×480, 640×360 e 320×256 equivalem ao zoom de 150/200/400% e ao reflow de 320px.

| Métrica | Antes | Depois |
|---|---|---|
| rolagem horizontal da página | 110 | 80 |
| texto < 12px | 11057 | 10403 |
| texto cortado | 194 | 82 |
| alvo < 24px | 579 | 120 |
| fora da tela | 3105 | 3013 |
| erros de console | 1270 | 860 |
| sem nome acessível / sem label / img sem alt | 0 / 0 / 0 | 0 / 0 / 0 |

Das 26 células que pioraram, nenhuma é regressão de layout:
- **`clipped` 0→1 nos postos:** é o `h1.visually-hidden` do OP-17, oculto de propósito. O comparador desconta.
- **Ordens, `small` 27→38 e `offscreen`:** vêm dos ícones ↕ de ordenação do GE-09 e das colunas dentro da rolagem da tabela, que é intencional com OP/Status fixos. O ícone tinha 9px e `opacity .7`; → **corrigido** para `--text-xs` e `--muted`, com a cor do texto quando a coluna está ativa.
- **Solda e Andon em 640×360 e 320×256, `offscreen`:** a tabela macro da Solda agora tem conteúdo, dentro da própria rolagem. Nenhuma das duas é tamanho de TV.
- **`errors` +1 em 7 células:** é o 500 do fixture em `/calls/unseen-count` (`contar_chamadas_nao_vistas` não existe no `ApiFakeDatabase`), que chega em momentos diferentes a cada rodada. É limitação do ambiente de teste, não do produto.

### Achados novos da regressão (corrigidos)

| Achado | Causa | Correção |
|---|---|---|
| Clicar no cabeçalho da coluna fora do texto não ordenava | `.data-table__sort` era `inline-flex`, com 27px dentro de um `th` de 112px | O botão ocupa a célula inteira (`display: flex; width: 100%`). No 8010, clicar no centro da célula → `aria-sort=ascending` |
| Dark: texto `--primary` sobre `--primary-soft` com 4,39:1 (item ativo, "Aguardando", paginação) | Token `--primary-soft` do tema escuro claro demais | `#15325a` → `#12294a` (≈5:1). A cor da marca não mudou |

### Fluxos, emulações e rede (Chromium, Playwright)

| Fluxo | Antes | Depois |
|---|---|---|
| 1ª parada do Tab | "Recolher menu" | "Pular para o conteúdo" (AX-04) |
| Menu móvel aberto | foco ficava no botão de abrir | foco no "×" (AX-05) |
| Preset de período | nenhum `aria-pressed` | "7 dias" pressionado (GE-12) |
| Abas de seção | `tablist` sem setas | `<nav>` com links, 0 `tablist` (GE-12) |
| Erro 500 | "Referência: abc123" solto | "Detalhes técnicos" recolhido (OP-12) |
| Offline / API lenta (3s) | — | sem mudança em relação à auditoria; nenhum crash |
| Dark / forced-colors / reduced-motion | — | sem crash; regras AX-07 aplicadas (forced-colors emulado pelo Chromium) |
| Contraste (12 telas: light, dark, operador) | 3 a 5 falhas por tela | **0 falhas** em todas |
| Violações de CSP `script-src 'self'` no console (todos os fluxos) | 5 | 0 (CSP intacta) |

### Web Vitals (fixture local)

| Rota | LCP antes → depois (ms) | Outros |
|---|---|---|
| Visão Geral | 400 → 380 | CLS 0 |
| Ordens | 468 → 432 | CLS 0 |
| OEE | 404 → 392 | CLS 0 |
| Gerencial | 340 → 316 | CLS 0 |
| Operador (workbench) | 208 → 228 | INP 112 → 48; tarefas longas 3 → 1 |
| Andon 1920 | 560 → 116 | tarefas longas 1 → 0 |

### Detector Impeccable

12 achados, os mesmos da linha de base e nenhum novo: side-tab/border-accent dos acentos de estado do Andon, pré-existentes.

### IA-01 (arquitetura de informação)

| ID | Antes | Depois |
|---|---|---|
| IA-01 | Títulos misturavam "Management View", "Crachás" e "Usuários" sem seção | **CORRIGIDO E PROVADO** no Fechamento (antes: PARCIAL) — todas as telas seguem "Seção — Aba" ("Tela inicial — Visão Geral/Setores/Alertas", "IagoDev — Crachás e responsáveis", "IagoDev — Cadastro de usuários"). Fica pendente, por decisão do usuário, renomear a seção "IagoDev" (nome e estrutura definidos pelo usuário em 17/09/2026). Breadcrumb não foi adicionado: o h1 e a aba ativa já localizam a tela |

### Pendências registradas

Todas fechadas na seção **Fechamento**, exceto Firefox/WebKit (fora do escopo).

### Validação

- `tsc --noEmit` limpo; vitest management, operator, users e badges **61/61**; `npm run build` ok.
- Matriz, fluxos, contraste e vitals: `docs/evidencias/auditoria_ui_2026-09-24/onda5/` (gitignorado, com screenshots e JSON).
- 8010: Ordens reinspecionada após o build (clique no cabeçalho, cor do ícone ativo).
- OEE: nenhum arquivo nem regra `.oee-*` ou `.andon-card__oee` tocados em nenhuma onda.

## Fechamento — pontos soltos

Escopo: só as pendências da Onda 5, sem nova auditoria ampla e sem redesign. Backend não foi tocado; a única mudança Python é a fixture `tests/web_preview_api.py`. Somente TEST.

| Item | Status final | Causa → correção | Evidência |
|---|---|---|---|
| **GE-13** Performance sem meta | **CORRIGIDO E PROVADO** | O backend já emite `kpi_targets_not_configured` em `insights.limitations` quando não há fonte de metas, mas o card mostrava o percentual solto. Agora os 4 KPIs da Visão Geral dizem "Sem meta definida". O motivo de dado insuficiente tem prioridade. Com meta configurada, o desvio aparece como exceção do backend. Nenhuma meta foi inventada, e o cálculo da OEE não mudou | `management.test.tsx` › GE-13 (3 testes, incluindo o estado vazio de Setores) |
| **GE-13** Setores (vazio) | **CORRIGIDO E PROVADO** | A fixture sempre devolve setores; o estado vazio foi provado por teste | teste "Setores sem registro": 1 mensagem de vazio, nenhum destaque zerado |
| **IA-01** nomes | **CORRIGIDO E PROVADO** | Causa: cada página passava um `title` literal, que divergia do menu. Agora o `PageFrame` monta o h1 como "Seção — Aba" a partir de `navigation.ts`, a mesma fonte do menu e das abas. O hook novo `useDocumentTitle` aplica esse nome ao `document.title` ("… · Gestor de Peças"). Andon: "Painéis Operacionais — Andon". Solda (fora das abas): "Acompanhamento da Solda". A seção "IagoDev" segue como nome oficial, sem prefixo "DEV —". A aba ativa continua com `aria-current` (NavLink). Postos do operador (`OperatorShell`): o `document.title` ficava "Gestor de Peças", diferente do h1 em 20 células da matriz. Agora usa o mesmo nome do h1 ("Posto do operador · Dobra", "Máquina Dobra - 1303") | `management.test.tsx` › IA-01: `it.each` em **todas** as `managementRoutes`, que passa um título local divergente e confere h1 + `document.title` + reset no unmount; 8011: título da aba do navegador conferido no Andon e na Solda; 8010: título = h1 conferido no posto Dobra, antes e depois de escolher a máquina |
| **AN-06** tela cheia na TV | **ACEITO POR DECISÃO DE PRODUTO** | Sem controle em TV ("não coloque botão em tv"). O navegador da TV faz tela cheia/quiosque | 8011, perfil TV, viewport emulado (equivale ao F11/quiosque, sem barra do navegador): **1920×1080 e 2560×1440**, Andon (20 cards) e Solda → rolagem horizontal 0, rolagem vertical 0, 0 cards sobrepostos, 0 cards fora da tela, 0 controles fora dos cards |
| **CSS órfão** | **CORRIGIDO E PROVADO** | Removidas 33 linhas de `.andon-page--embedded …` e `.andon-fullscreen …` do `global.css`, incluindo as de dentro de media queries. Nenhum `.tsx` atribui essas classes. As 4 regras `.andon-page--embedded .andon-card__oee` nunca casavam porque o pai não existe. O anel real da OEE fica em `andon.css:376-415` e está intacto. O teste do Andon, que conta `.andon-card__oee`, continua verde | build sem os seletores; 8011 sem `cssRule` para eles; `andon.test.tsx` verde |
| **Detector Impeccable** | **CORRIGIDO E PROVADO** | 12 alertas triados. **1 corrigido:** `border-top: 5px` do `.andon-card` em `global.css` era declaração morta, porque o shorthand `border` do `andon.css` (carregado depois) sobrescrevia. **11 intencionais**, suprimidos um a um com `impeccable-disable-next-line <regra> -- motivo`: faixas de estado HMI em que a cor muda com o estado e o texto do estado está no card (Andon, Corte, Destaque, Inspeção), faixa engrossada da TV, faixa por KPI (identidade da série, igual à legenda) e o triângulo de canto do dia selecionado. Nenhuma supressão genérica: `.impeccable/config.json` não foi alterado | `impeccable detect web/src` → **0**; `--no-inline-ignores` → **11** (as 11 suprimidas, nenhuma nova) |
| **Fixture 500** | **CORRIGIDO E PROVADO** | O `ApiFakeDatabase` da prévia não tinha os métodos de chamadas. O sininho (`/api/v1/chamadas/nao-vistas`) dava 500 em toda página. A tela Chamadas (`/chamadas/admin/historico`, contatos) também dava 500: eram 11 respostas 500 no log da regressão. Stubs vazios só na fixture, sem mexer no backend | ver regressão abaixo |

### Regressão final (Fechamento)

Tudo em TEST, nos servidores de prévia 8010 (Gestão/postos), 8011 (Andon/Solda em perfil TV) e 8012, servindo o `web/dist` recém-construído. Evidências em `docs/evidencias/auditoria_ui_2026-09-24/final/` (gitignored): `matrix/*.json` + capturas, e `flows/flows2_keyboard_filters_resilience_emulations_contrast.json` + capturas.

**Matriz de telas × tamanhos.** Gestão (todas as rotas), postos Dobra/Corte/Destaque/Solda e Andon/TV, em **1024, 1366, 1920, 2560 e 320 px (reflow)**. Foram 215 pares comparados com a Onda 5 e nenhum ficou sem par.

| Métrica (total da matriz) | Onda 5 | Fechamento | Leitura |
|---|---|---|---|
| Erros de console/rede | 433 | **16** | Os 500 da fixture sumiram. Os 16 restantes são o `401` esperado de `/auth/me` antes do login (1 por perfil) e ruído de SSE da prévia |
| Rolagem horizontal | 80 | 80 | inalterado (tabelas largas em 320 px rolam dentro do próprio contêiner) |
| Texto < 12 px | 5143 | 5148 | +5: o detalhe "Sem meta definida" (GE-13) no slot `--text-xs` que já existia em `.metric-card__detail`, a mesma escala do detalhe anterior. Não é regressão |
| Cortado / minúsculo | 45 / 60 | 45 / 60 | inalterado |
| Sem nome acessível / sem rótulo / img sem alt | 0 | 0 | — |
| Fora da tela | 1699 | 1686 | −13 |

**Fluxos.**
- **Teclado/foco:** o skip link é a 1ª parada do Tab e todas as paradas têm contorno de 2 px. No menu móvel, o foco vai para o "×" e o Esc fecha o menu e devolve o foco.
- **Filtros:** o botão "7 dias" usa `aria-pressed`. A ordenação de tabela funciona.
- **Offline:** aparece o alerta "Não foi possível acessar o servidor".
- **Erro 500:** aparece o estado de erro com "Detalhes técnicos".
- **API lenta (3 s):** não há crash. Menu e abas aparecem na hora; o conteúdo entra quando a API responde. Na 1ª carga a área fica vazia, sem indicador de carregamento (`res_3_lento_visao.png`). É o mesmo comportamento que a auditoria marcou como ✅, sem ID aberto; está registrado aqui como observação.

**Temas e emulações:**
- **Escuro:** o fundo fica em `rgb(10,19,34)`.
- **Contraste:** 0 falhas em 12 telas, nos temas claro e escuro.
- **`prefers-reduced-motion`:** 0 animações ativas.
- **`forced-colors`:** capturas feitas, com os controles visíveis.

**AN-06 (TV):** Andon e Solda sem rolagem, sobreposição nem controles, em 1920×1080 e 2560×1440 (ver tabela acima).

**Chamadas (observação, não regressão):** na prévia, `/chamadas/nao-vistas` e `/admin/historico` são recarregados a cada ~1 s. A causa é o `live_tick` do SSE (`subscribeRealtime` em `useApiQuery`), que recarrega toda consulta ativa. É comportamento pré-existente de atualização ao vivo, e nenhum desses arquivos mudou.

**Validação:**
- `npx tsc -b` → 0.
- `npm run build` → OK.
- vitest direcionado (`management`, `andon`, `welding-management`, `operator`) → **4 arquivos, 132/132**.
- `impeccable detect web/src` → **0**.
- `git diff --check` → limpo.
- Firefox/WebKit: fora do escopo.


### Pendências reais

- **Firefox/WebKit:** fora do escopo, por decisão do usuário.
- Nenhuma outra pendência aberta da auditoria de frontend.
