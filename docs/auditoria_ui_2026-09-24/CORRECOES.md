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
