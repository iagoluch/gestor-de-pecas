# Setup do Claude Code — Gestor de Peças

Auditoria e configuração adotada em 20/09/2026. Este documento existe para que qualquer pessoa (ou sessão futura de Claude Code) entenda o que está ativo neste ambiente, por quê, e o que fica de fora de propósito.

## Escopo desta máquina

Tudo abaixo é local a esta máquina Windows (`iago.luchtenberg`), configurado em `~/.claude`. Não afeta sessões na nuvem nem outras máquinas. Uma descoberta relevante: o marketplace de plugins (`~/.claude/plugins/known_marketplaces.json`) tem `installLocation` apontando para `C:\Users\logistica.unidade4\...`, indicando que esta máquina já teve outro perfil de usuário Windows configurando Claude Code antes. Não foi investigado a fundo — não é bloqueante, mas explica achados como o sistema "Brain" abaixo.

## Achado importante: MCP servers da CLI ≠ MCP servers do app desktop

`claude mcp add --scope user` grava em `~/.claude.json` (usado quando você roda `claude` direto no terminal). **O app desktop (onde esta conversa roda) usa configuração própria separada** (`AppData\Roaming\Claude\config.json` e afins). Isso significa: `headroom`, `omniroute` e `pg-aiguide` (ver abaixo) estão registrados e conectados quando você roda `claude` pelo terminal, mas **não aparecem como ferramentas dentro de conversas no app desktop** como esta. Se quiser usá-los aqui, será preciso investigar a configuração própria do app desktop — não resolvido nesta auditoria.

## Componentes ativos

### MCP servers (escopo CLI/terminal, `~/.claude.json`)

| Servidor | O que faz | Status |
|---|---|---|
| `headroom` | Comprime tool outputs/logs antes de chegarem ao modelo | ✔ Conectado |
| `omniroute` | Gateway de roteamento para 350+ provedores de IA (incl. gratuitos) | ✔ Conectado, restrito a loopback, senha própria trocada |
| `plugin:pg:pg-aiguide` | Documentação/boas práticas PostgreSQL via busca semântica (TigerData/Timescale, hospedado) | ✔ Conectado — instalado nesta auditoria |

### Skills locais (`~/.claude/skills`)

- **~45 skills reais de engenharia** mantidas: `incremental-implementation`, `debugging-and-error-recovery`, `test-driven-development`, `code-review-and-quality`, `security-and-hardening`, `api-and-interface-design`, `frontend-ui-engineering`, etc. — motor do roteamento automático descrito no `CLAUDE.md` global do usuário.
- **Família `ponytail`** (lite/full/ultra + audit/debt/gain/help/review) — mantida, uso confirmado no histórico.
- **`graphify`** — grafo de conhecimento de código, ver seção própria abaixo.
- **832 skills `*-automation`** (pacote Composio: Slack, Notion, HubSpot etc.) **removidas** em 20/09/2026 — 0 uso registrado no histórico e nenhuma mapeia para o stack real do projeto (TOTVS/Protheus/SigmaNEST são sistemas proprietários fora do catálogo Composio). Pacote fonte continua intacto em `composio-skills/`, restaurável via `configure-skills.bat` se algum dia fizer sentido.

### Sistema "Brain" (`~/.claude/brain/`) — achado não documentado antes

Sistema de memória paralelo (Python, hooks em `SessionStart`, `UserPromptSubmit`, `PostToolUse:Edit|Write`, `Stop`, cada um com timeout de 10s) que mantém `projects/`, `decisions/`, `sessions/`, `state/` — sobreposição real com o sistema de auto-memória nativo do Claude Code (que já é usado nesta sessão, ver `memory/MEMORY.md` do projeto). Roda em **toda mensagem e toda edição**, em **todos os projetos** desta máquina.

**Classificação: INVESTIGAR / OTIMIZAR.** Não foi desabilitado nesta auditoria (é uma mudança de escopo global que afeta todos os projetos, não só este) — decisão do usuário. Se o objetivo é reduzir overhead por mensagem, os hooks em `~/.claude/settings.json` (`SessionStart`, `UserPromptSubmit`, `PostToolUse`, `Stop` → `brain.cmd`) são o ponto de remoção.

### Hooks do projeto (`.claude/settings.json`, escopo local)

Instalados por `graphify claude install` (ver abaixo): `PreToolUse` em `Bash|Grep` e `Read|Glob` chamando `graphify hook-guard` — injeta um lembrete não-bloqueante para consultar o grafo antes de grep bruto. Overhead: 1 processo Python curto por chamada dessas ferramentas (~10s de timeout máximo, raramente atingido).

### Graphify — grafo de conhecimento de código

Validado nesta sessão: **funcionando e útil**. Escopo atual: `mes/`, `backend/`, `app/`, `web/`, `tests/` (código, AST local, sem custo de LLM) → 6.634 nós, 14.145 arestas, 308 comunidades. `docs/` (1,6M palavras de relatórios históricos) e `assets/` (imagens) ficam **de fora por decisão de custo/valor**, não por limitação técnica.

Auto-atualiza via `.git/hooks/graphify-rebuild.sh` (dispara em background após qualquer commit que toque uma das 5 pastas de código). Comando manual de rebuild documentado no `CLAUDE.md` do projeto (a rota `graphify update .` padrão **não** se aplica aqui, pois o grafo foi construído por mesclagem de 5 extrações, não por extração de raiz única).

Não foi avaliado como redundante nenhuma outra ferramenta de code search/RAG — o Graphify já cobre essa necessidade.

### Limpeza automática de lixo do sistema de arquivos

`scripts/clean-junk.ps1` + tarefa agendada do Windows (`GestorPecas-LimpezaJunk`, diária às 08:00 e a cada login) — remove `desktop.ini` (OneDrive), `Thumbs.db`, `__pycache__`/`.pytest_cache`/`*.pyc`, arquivos de 0 bytes soltos na raiz (padrão observado: `fs.writeFileSync(__dirname`, indício de um comando shell mal escapado em algum lugar — causa raiz não identificada, vale investigar se reaparecer com frequência), e arquivos parados há +2 dias no staging do Google Drive (`.tmp.drivedownload`/`.tmp.driveupload` — nunca toca em arquivos recentes/ativos).

## Tabela: Componente | Antes | Ação | Depois

| Componente | Antes | Ação | Depois |
|---|---|---|---|
| Skills `*-automation` (Composio) | 832 instaladas, 0 uso | REMOVER (symlinks, fonte preservada) | Removidas |
| Skills de engenharia (~45) | Instaladas, uso implícito via router | MANTER | Mantidas |
| `ponytail` (família) | Instalada, uso confirmado | MANTER | Mantida |
| `graphify` | Não instalado | INSTALAR + configurar escopo + auto-update | Instalado, grafo completo, hook de rebuild ativo |
| `headroom` (MCP) | Não instalado | INSTALAR | Instalado, conectado (escopo CLI) |
| `omniroute` (MCP) | Não instalado | INSTALAR, corrigir exposição de `.env` do projeto, restringir a loopback | Instalado, conectado (escopo CLI), rodando de diretório neutro |
| `pg-aiguide` (plugin/MCP PostgreSQL) | Não instalado | INSTALAR (achado desta pesquisa, Apache-2.0, ativo) | Instalado, conectado (escopo CLI) |
| Sistema "Brain" (`~/.claude/brain`) | Ativo, hooks em toda mensagem | INVESTIGAR (redundante com auto-memória nativa) | Sem alteração — decisão pendente do usuário |
| Limpeza de lixo (desktop.ini, pycache, staging Drive) | Manual/inexistente | CRIAR script + tarefa agendada | Automatizado, roda sozinho |
| Config MCP CLI vs app desktop | Desconhecido | INVESTIGAR | Achado documentado, não resolvido — MCPs da CLI não aparecem no app desktop |

## Não instalado agora (recomendações para decisão futura)

Ver `docs/REFERENCIAS_TECNICAS.md` para a lista completa com justificativa. Resumo dos candidatos mais fortes a uma próxima rodada:
- **Segurança, baixíssimo custo**: `gitleaks` + `bandit` (ou Ruff com regras `S`, não ambos) + `pip-audit` + Dependabot + `npm audit` no CI.
- **Observabilidade, baixo custo**: `prometheus-fastapi-instrumentator` + `structlog`.
- **Contexto Claude Code**: preferir `netresearch/context7-skill` (skill sob demanda) a instalar o MCP permanente `context7` — mesma função, fração do custo de tokens.
