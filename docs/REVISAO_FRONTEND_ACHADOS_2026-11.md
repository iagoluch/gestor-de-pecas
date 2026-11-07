# Revisão do frontend — achados (06/11/2026)

Escopo: todo `web/src` (páginas, componentes, hooks, `api/`, `config/navigation.ts`, `App.tsx`, estilos, testes).
Mesmo formato de `docs/REVISAO_BACKEND_ACHADOS_2026-11.md`.
Gravidade: crítico · alto · médio · baixo. Status: aberto · corrigido · descartado · decisão do usuário.

Ponto de partida: `npx tsc --noEmit` sem erro; vitest 527 de 528 (1 falha, F1).

## O que foi conferido e está certo

- **Contrato com a API:** todos os endereços que o frontend chama existem no backend (comparado com `/api/openapi.json`, 170 rotas). Nenhum endereço órfão.
- **Permissões:** as travas de rota (`RequireAdmin`, `RequireStandardTimeAccess`, `RequireQualityTemplateAccess`, `RequireDiretoriaAccess`…) batem com `app/core/permissions.py`. A Consulta de OP usa `permissions.can_add_step` vindo do servidor.
- **CSRF:** `api/client.ts` manda `X-CSRF-Token` (cookie `gestor_csrf`) em todo método que grava.
- **Erros da API:** `failure()` trata o formato cru `{detail:{code,message}}` do FastAPI; downloads só viram arquivo com resposta 2xx.
- **Memória do navegador:** todo uso de `localStorage`/`sessionStorage` está em try/catch (`AndonSidebarNav`, `usePersistentFilters`, `useTheme`, `AppShell`).
- **Links externos:** `target="_blank"` com `rel` correto.
- **Andon TV:** não foi alterado (Chrome 79, sem botões).

## Achados

**F1 — médio — corrigido**
Teste quebrado: `src/test/management.test.tsx` ("mantém as telas gerenciais e inclui as sub-abas do Andon") espera 45 telas, mas são 46 desde a tela "Envios ao Protheus" (990eed2). O que se vê: a suíte do frontend fica vermelha e esconde falhas novas.
Como conferir: `npx vitest run src/test/management.test.tsx`.

**F2 — médio — corrigido**
Consulta de OP mostra a data de emissão com **um dia a menos**. `data_emissao` é coluna DATE (`catalogo_pcp_ops`), chega como `"2026-11-05"`; `formatDateTime` (`web/src/utils/format.ts:81`) faz `new Date("2026-11-05")`, que o navegador lê como meia-noite UTC, e no Brasil isso vira `04/11/2026 21:00`. Tela: `OrderConsultationPage.tsx:223` ("Emissão").
Como conferir: no console do navegador, `new Date("2026-11-05").toLocaleString("pt-BR")` → `04/11/2026, 21:00:00`. Depois da correção, a data pura aparece só como dia (`05/11/2026`).
Observação: no TEST nenhuma OP tem `data_emissao` preenchida hoje, por isso ninguém viu na tela.

**F3 — médio — corrigido**
Sessão expirada no meio do uso: a API responde 401 "Entre para continuar.", mas o frontend não volta para o login. Cada quadro da tela mostra o erro separado e o usuário fica preso (`web/src/auth/AuthContext.tsx`; `api/client.ts` não avisa ninguém do 401). Afeta principalmente o chão de fábrica (Workbench, Destaque), que fica aberto o dia inteiro.
Como conferir: logado, apague o cookie de sessão no DevTools e espere a próxima atualização: a tela deve ir para o login.

**F4 — médio — corrigido**
Destaque: se a fila (`/api/v1/highlight/queue`) falhar ou ainda estiver carregando, aparece "Nenhuma tarefa liberada pelo Corte" — um vazio falso — e o aviso de posto parado some, porque vem da mesma resposta (`web/src/pages/operator/HighlightPage.tsx:153,288-302`). O Corte já faz certo (`CuttingPage.tsx:301`: carregando → erro com "Tentar de novo" → aviso de dado desatualizado).
Como conferir: no DevTools, bloquear `highlight/queue` e recarregar a tela do Destaque.

**F5 — médio — corrigido**
Workbench do operador: se o histórico falhar, o quadro mostra "Sem apontamentos recentes" — vazio falso (`web/src/pages/operator/WorkbenchPage.tsx:163,828`).
Como conferir: bloquear `operator/history` no DevTools.

**F6 — médio — corrigido**
Auditoria → Alertas: se `/api/v1/management/internal-alerts` falhar, aparece "Nenhum alerta interno registrado" — vazio falso (`web/src/pages/audit/AuditPages.tsx:118,160-178`).
Como conferir: bloquear `internal-alerts` no DevTools.

**F7 — médio — corrigido**
Qualidade → histórico de inspeção → detalhe: se as cotas falharem, a tabela aparece vazia, sem aviso (`web/src/pages/operator/QualityPage.tsx:278,344`).
Como conferir: abrir o detalhe de uma inspeção com `cotas` bloqueado no DevTools.

**F8 — baixo — aberto**
Consultas secundárias sem estado de erro (o quadro some ou fica vazio, sem dado falso de número): `DirectorSheet.tsx:28` (catálogo do filtro), `ChamadasContatosPage.tsx:41` (setores), `OperatorPortalPage.tsx:16` (postos), `ChamadaSino.tsx:11`, `WorkbenchPage.tsx:166,170` (postos e desenho). O `trendQuery` da Visão geral (`ManagementOverviewPage.tsx:216`) falha em silêncio de propósito (é opcional).

**F9 — baixo — resolvido**
Tela Metas: a rota `inicio/metas` continuava no `App.tsx`, mas o item do menu estava comentado desde 01/10 (aba oculta). Decisão do usuário (06/11/2026): remover. Saíram a rota, a página `GoalsPage.tsx` e o item comentado do menu. A página não chamava nenhum endereço da API; o backend não foi alterado. O card "Metas e atingimento" da Visão geral é outra coisa e continua.
Como conferir: `/inicio/metas` não abre mais a tela; `npx vitest run src/test/management.test.tsx src/test/andon.test.tsx` (95 testes verdes).

**F10 — baixo — aberto**
`OrderConsultationPage.tsx:233` usa `.at(-1)`, que o Chrome 79 não tem. Hoje só a gestão (navegador moderno) usa essa tela, então não quebra; se um dia abrir em navegador antigo, quebra.

**F11 — baixo — aberto**
Duplicação: `cookie()` existe em `api/client.ts` e em `api/ai.ts`. `download()` revoga o endereço do arquivo logo após o clique (funciona nos navegadores atuais; risco teórico em navegador lento).

**F12 — baixo — aberto**
`AuthContext.logout` não trata falha de rede: se o POST de saída falhar, a tela continua logada sem aviso. `useApiQuery` não zera `updatedAt` quando o endereço muda (o "atualizado às" pode mostrar a hora da consulta anterior por um instante).

## Limites desta revisão

Acessibilidade e responsividade foram vistas por leitura de código, sem varredura automática (axe) nem teste em celular real. Andon TV não foi testado na TV física.

## Provas (06/11/2026, API 8001 com o build novo)

- F3: falha 401 simulada no navegador → a tela foi para o login. Teste: `src/test/sessionExpired.test.ts` (login com senha errada não dispara).
- F4: falha simulada da fila no Destaque (conta de teste `claude.destaque`) → aviso "Atualização temporariamente indisponível" e a tarefa continua na tela. Teste novo em `src/test/operator.test.tsx` para a falha já na primeira carga.
- F5: falha simulada do histórico no Workbench (conta `claude.dobra`, posto 1303) → "Não foi possível carregar o histórico".
- F6: falha simulada dos alertas internos → quadro de erro com "Tentar novamente".
- F2: teste `src/test/formatDateTime.test.ts`; sem prova na tela porque nenhuma OP do TEST tem data de emissão.
- F7: mesmo padrão de F6; sem prova na tela (precisaria de inspeção com cotas no histórico).
- Validação: `tsc` sem erro, vitest 54 arquivos / 534 testes, todos verdes; `npm run build` ok.

Observação F3 no Andon TV: se a sessão da TV expirar, a TV agora vai para a tela de login em vez de ficar com erro em cada quadro. Nos dois casos alguém precisa entrar de novo; o fluxo normal da TV não mudou.

## Plano de etapas

1. **Etapa A (feito):** F1 (teste), F2 (datas), F3 (sessão expirada).
2. **Etapa B (feito):** F4–F7 (vazios falsos), seguindo o padrão do Corte: carregando → erro com "Tentar de novo".
3. **Guardado (baixo):** F8, F10, F11, F12 — corrigir junto com a próxima mudança em cada tela.
4. **Feito (06/11):** F9 — tela Metas removida por decisão do usuário.

Nenhum achado de segurança aberto: este documento pode ser commitado.
