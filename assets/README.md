# assets/

Só entra aqui o que o frontend importa. Origem canônica: `web/src/config/assets.ts` (estilos em `web/src/styles/`).
Atualizado em 08/10/2026: 86 arquivos sem referência removidos (cópia em `backups/assets_orfaos_2026-10-08.zip`, local, e no histórico do git).

| Pasta | O que tem | Usado por |
| --- | --- | --- |
| `branding/` | logo e avatar do shell gerencial | `AppShell` |
| `web/navigation/` | ícones das seções gerenciais (png/svg) | navegação gerencial |
| `operator_mockup/` | logo, avatar e abas por setor do posto (`*_transparent.png`) | `OperatorShell` |
| `icons/` | ações, logos de setor, imagens de equipamentos e fallback de recursos | cards de recurso, posto, Andon |
| `screens/capturas_2026-10-08/` | 214 capturas reais do frontend (gestão e operadores), com `INDICE.md` e `capturas.json` | referência visual |

Fontes: sem `@font-face`; `tokens.css` usa a pilha do sistema e `ai.css` usa `Consolas`.
Novo asset: importe por `web/src/config/assets.ts`; asset sem import não fica aqui.
