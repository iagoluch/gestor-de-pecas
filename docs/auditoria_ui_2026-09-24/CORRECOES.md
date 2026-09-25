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
| OP-05..15, AX-01 (Chamar) | ver ee95754 | **CORRIGIDO** (parte 2) | |
| AX-03..06 | ver a739155 | **CORRIGIDO** (parte 1) | |

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
