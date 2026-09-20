# Setup do Claude Code — Gestor de Peças

Auditoria em 20/09/2026 (duas rodadas na mesma data: levantamento inicial + rodada de decisão/execução). Este documento existe para que qualquer pessoa (ou sessão futura de Claude Code) entenda o que está ativo neste ambiente, por quê, e o que fica de fora de propósito.

## Escopo desta máquina

Tudo abaixo é local a esta máquina Windows (`iago.luchtenberg`), configurado em `~/.claude`. Não afeta sessões na nuvem nem outras máquinas. Achado não resolvido: o marketplace de plugins (`~/.claude/plugins/known_marketplaces.json`) tem `installLocation` apontando para `C:\Users\logistica.unidade4\...`, indicando que esta máquina já teve outro perfil de usuário Windows configurando Claude Code antes.

## Achado importante, ainda sem solução: MCP servers da CLI ≠ MCP servers do app desktop

`claude mcp add --scope user` grava em `~/.claude.json` (usado quando você roda `claude` direto no terminal). **O app desktop (onde esta conversa roda) usa configuração própria separada.** Investigado nesta rodada até onde dava para ir sem risco: não há um arquivo de config de MCP do app desktop documentado publicamente nem localizado com segurança nesta auditoria para editar diretamente sem risco de corromper o app. Decisão: não replicar manualmente — os únicos MCPs realmente mantidos (`headroom`, `pg-aiguide`) continuam disponíveis via terminal; nenhum deles é crítico o suficiente para justificar mexer em configuração não documentada do app desktop. Se precisar de um deles dentro de uma conversa como esta, a via seguro é usar a CLI/skill equivalente em vez do MCP (ex.: skill `context7` em vez do MCP, `pg` via CLI do plugin quando aplicável).

## Componentes ativos

### MCP servers (escopo CLI/terminal, `~/.claude.json`)

| Servidor | O que faz | Rodada 1 | Rodada 2 |
|---|---|---|---|
| `headroom` | Comprime tool outputs/logs antes de chegarem ao modelo | Instalado | MANTIDO — sem evidência de problema, baixo overhead, benefício claro (compressão de contexto) |
| `omniroute` | Gateway de roteamento para 350+ provedores de IA | Instalado | **REMOVIDO/DESABILITADO** — ver seção própria abaixo |
| `plugin:pg:pg-aiguide` | Documentação/boas práticas PostgreSQL via busca semântica (TigerData, hospedado) | Instalado | MANTIDO — hospedado (sem processo local), Apache-2.0, uso justificado |

### OmniRoute — decisão de desabilitar (rodada 2)

**Investigação concreta feita nesta rodada:** `omniroute cost` e `omniroute usage` mostraram **39 requisições desde a instalação, 0 tokens de entrada/saída, $0,00 de custo** — ou seja, nenhum uso real além dos meus próprios testes de smoke test (auth, handshake MCP). Comparação benefício vs. custo:

- **Benefício hoje:** zero uso real comprovado; o único caminho viável (`omniroute launch --profile` no terminal) já havia se mostrado instável em teste anterior (timeout em 2 de 3 tentativas).
- **Complexidade:** alta (357 provedores, dashboard próprio, servidor Node persistente).
- **Superfície de ataque:** real — já vazou o `.env` do projeto uma vez nesta auditoria (corrigido rodando de diretório neutro), expõe um servidor HTTP local com chaves de API e um relay de nuvem opcional.
- **Overhead operacional:** processo Node persistente (~200MB+ de memória) com múltiplos schedulers rodando em background mesmo ocioso.

**Ação executada:** processo do servidor finalizado, MCP removido do `~/.claude.json` (`claude mcp remove omniroute --scope user`). O pacote npm continua instalado (não desinstalado) e o dashboard/perfis de terminal (`~/.claude/profiles/auto-best-coding*`) continuam no disco — reativável a qualquer momento com `omniroute serve` + `claude mcp add` se surgir um caso de uso real e comprovado (ex.: economia de custo em uso pesado de API paga).

### Sistema "Brain" (`~/.claude/brain/`) — decisão de remoção dos hooks automáticos (rodada 2)

**Investigação concreta feita nesta rodada:** `~/.claude/brain/decisions/` continha **apenas o template `INDEX.md`, zero decisões reais gravadas**, apesar dos hooks rodarem em toda mensagem/edição há semanas. `state/current.md` e o arquivo de projeto (`projects/gestor de pecas...md`) tinham conteúdo genérico e desatualizado (última atividade registrada: 18/09, três dias antes desta auditoria; "próximo passo: Determinar pelo pedido atual do usuário; não presumir" — um não-resultado). Isso confirma redundância real com a auto-memória nativa do Claude Code, que já tem ~30 memórias específicas e ricas sobre este projeto.

**Ação executada:** removidos os 4 hooks (`SessionStart`, `UserPromptSubmit`, `PostToolUse:Edit|Write`, `Stop`) de `~/.claude/settings.json` que chamavam `brain.cmd`. Reversível: os arquivos de `~/.claude/brain/` continuam intactos, e as skills manuais `dia`, `status`, `contexto`, `decidir`, `fim` continuam instaladas e invocáveis por comando explícito, caso você queira usá-las manualmente sem o overhead automático em toda mensagem.

### GitHub Actions — SHA pinning (rodada 2)

**Confirmado o risco apontado na pesquisa anterior:** todas as actions em `.github/workflows/ci.yml` e `deploy.yml` estavam referenciadas por tag mutável (`@v4`, `@v5`), não por SHA de commit. Ação executada: resolvidas as SHAs exatas das mesmas versões major já em uso (sem upgrade de versão, para não mudar comportamento) e aplicadas com comentário `# vX` para legibilidade — `actions/checkout@11d5960a...`, `actions/setup-python@a26af69b...`, `actions/setup-node@49933ea5...`, `actions/upload-artifact@ea165f8d...`, `actions/download-artifact@d3f86a10...`.

### Novo job de segurança no CI (rodada 2)

Adicionado job `security` em `.github/workflows/ci.yml`:
- **gitleaks** (`zricethezav/gitleaks:v8.30.1` via Docker, escaneando histórico completo de commits) — **testado localmente antes de commitar**: achou 4 candidatos, todos confirmados como falsos positivos (dois segredos de teste com nome explícito de fixture, um placeholder literal `"USUARIO:SENHA"` em `protheus/README.md`). Allowlist criada em `.gitleaks.toml` para esses 3 padrões específicos; re-testado após a allowlist e confirmado **"no leaks found"**, exit code 0. É bloqueante (falha o build se achar algo novo).
- **pip-audit** — testado localmente, **0 vulnerabilidades** nas dependências atuais. Bloqueante.
- **bandit** — testado localmente contra `backend`, `mes`, `app` (45.461 linhas escaneadas): 44 avisos, quase todos B608 (SQL via f-string) sobre nomes de coluna constantes (`{OUTBOX_COLUMNS}`), não input de usuário — falso positivo provável, mas não triado item a item. **Informativo por ora** (`|| true`, não quebra o build) até alguém revisar os 44 achados e marcar os reais com `#nosec` ou corrigir; depois disso, trocar para bloqueante.

Não instalado: Ruff (o projeto não usa nenhum linter hoje; introduzir Ruff seria uma decisão maior que "segurança", fora do escopo desta auditoria — bandit é a ferramenta cirúrgica certa aqui, sem se comprometer com um linter completo).

### `netresearch/context7-skill` (rodada 2 — instalado)

Avaliado e instalado em `~/.claude/skills/context7/`. Licença `(MIT AND CC-BY-SA-4.0)`, sem chave de API (usa a API REST pública do Context7 via `curl`+`jq`), ativa sob demanda (skill, não MCP permanente). Substitui a necessidade do MCP `context7` permanente pela mesma função com fração do custo de contexto — confirma a preferência CLI/skill > MCP permanente já adotada no projeto.

### Playwright (rodada 2 — configurado, POC parcial)

`pytest-playwright` instalado (`pip install pytest-playwright`, versão 1.62.0/0.9.0). POC criada em `tests/poc_playwright_smoke.py` (marcada `@pytest.mark.skip`, não faz parte da suíte principal ainda) testando que a página inicial do preview visual (`http://127.0.0.1:8010`, servidor já existente do projeto: `gestor-preview-visual`) carrega e retorna o título correto.

**Testado e validado de ponta a ponta**: Chromium baixado (191.8 MB, precisou de 3 tentativas por disputa de lock de arquivo `__dirlock` durante download concorrente — resolvido), teste rodado com `python -m pytest tests/poc_playwright_smoke.py -v` contra o preview real (`gestor-preview-visual`, porta 8010) → **1 passed em 2.10s**. Teste fica marcado `@pytest.mark.skip` no repositório (não roda em CI automaticamente ainda — decisão de incorporar à suíte principal fica para o time, não foi feita nesta auditoria).

Confirmada a recomendação da pesquisa anterior: usar Playwright via CLI/pytest (não via MCP `playwright-mcp`) para testes automatizados — ~4x menos tokens medidos, sem degradação em sessões longas.

### ADVPL/TLPP — skills oficiais e analisador (rodada 2 — investigado, não instalado aqui)

**`totvs/engpro-advpl-tlpp-skills`**: conteúdo real lido (5 SKILL.md verificados: `advpl-to-tlpp-migration`, `code-review`, `mvc-generator`, `advpl-tlpp-sdd`, `context-map`). Qualidade confirmada alta e não-redundante (conhecimento de domínio verificável: SQL injection em `DbSelectArea`, proibição de acesso direto a tabelas `SX*`, a armadilha real UTF-8 vs. CP-1252 no compilador RDMake). **Decisão: TESTAR, mas no repositório ADVPL/TLPP separado, não neste** — o Gestor de Peças (este repo) não contém código ADVPL, então instalar essas skills aqui nunca seria acionado. Passo a passo documentado em `docs/REFERENCIAS_TECNICAS.md`.

**`totvsengpro/advpl-tlpp-code-analyzer`**: investigado a fundo (comando exato, volumes, formato de config.json, formato de saída JSON). **Requer Docker Desktop**, que está instalado nesta máquina, mas **não foi testado de fato** por não haver ainda fontes `.PRW`/`.TLPP` de teste isolados neste momento. Decisão: PREPARAR ADOÇÃO FUTURA, passo a passo completo documentado em `docs/REFERENCIAS_TECNICAS.md` para quando o repositório ADVPL separado quiser validar.

### Resiliência de integrações TOTVS — já resolvido internamente (rodada 2)

Investigação concreta no código: `mes/integrations/totvs/outbox.py` já implementa uma política de retry com **backoff determinístico** (`backoff_delay_seconds`), classificação de falha por tipo (`retryable: bool`), limite de tentativas e distinção entre falha de transporte/indisponibilidade (repete) vs. rejeição de dado (não repete). **Decisão: JÁ RESOLVIDO INTERNAMENTE para retry/backoff — não instalar `backon`.** Não foi encontrada nenhuma classe de circuit breaker própria (que rastreie falhas consecutivas entre chamadas para "abrir o circuito" e parar de tentar por um tempo) — **`pybreaker`: PREPARAR ADOÇÃO FUTURA**, com gatilho objetivo: só adotar se houver evidência real de flapping/tempestade de retries degradando performance, não preventivamente.

### Skills locais (`~/.claude/skills`)

- **~45 skills reais de engenharia** mantidas (rodada 1).
- **Família `ponytail`** — mantida.
- **`graphify`** — mantido, ver seção própria abaixo.
- **`context7`** — instalado nesta rodada (ver acima).
- **832 skills `*-automation`** (Composio) — removidas na rodada 1, decisão reafirmada, não reinstaladas.

### Graphify — validação rápida (rodada 2)

Validado que continua funcionando: `graphify explain`/`graphify query` responderam corretamente durante esta auditoria (ex.: consulta usada para checar resiliência da integração TOTVS). Nenhuma ferramenta redundante de code search/RAG foi instalada — o Graphify já cobre essa necessidade, conforme decisão da rodada 1.

## Tabela: Componente | Antes | Ação | Depois | Motivo

| Componente | Antes | Ação | Depois | Motivo |
|---|---|---|---|---|
| Skills `*-automation` (Composio) | 832 instaladas, 0 uso | REMOVER (rodada 1) | Removidas | 0 uso real, stack proprietário fora do catálogo |
| `graphify` | — | INSTALAR (rodada 1) | Mantido, validado funcionando (rodada 2) | Grafo de código funcional, sem redundância |
| `headroom` (MCP) | — | INSTALAR (rodada 1) | Mantido (rodada 2) | Benefício claro, baixo overhead |
| `omniroute` (MCP) | — | INSTALAR (rodada 1) | **REMOVIDO** (rodada 2) | 0 uso real comprovado (39 req/$0), superfície de ataque real, overhead de processo persistente |
| `pg-aiguide` (plugin) | — | INSTALAR (rodada 1) | Mantido (rodada 2) | Hospedado, Apache-2.0, uso justificado |
| `context7` (skill) | — | — | **INSTALADO** (rodada 2) | Substitui MCP permanente por fração do custo de contexto |
| Sistema "Brain" (hooks) | Ativo em toda mensagem | INVESTIGAR (rodada 1) | **Hooks removidos** (rodada 2) | `decisions/` vazio após semanas de uso — redundante com auto-memória nativa, confirmado com evidência |
| GitHub Actions (tags) | `@v4`/`@v5` mutáveis | AUDITAR (rodada 1) | **Pinadas por SHA** (rodada 2) | Risco de supply-chain real e documentado, correção segura sem mudar versão |
| Segurança no CI | Inexistente | AVALIAR ferramentas | **gitleaks + pip-audit (bloqueantes) + bandit (informativo)** adicionados e testados localmente | Cobertura de alto retorno/baixo custo, validada antes de commitar |
| Playwright | Não instalado | AVALIAR CLI vs MCP | **pytest-playwright instalado + POC criada**; binário do Chromium pendente (ambiente) | CLI vence MCP em custo de contexto (~4x), confirmado por medição |
| ADVPL/TLPP skills oficiais | — | INVESTIGAR conteúdo | Lido e avaliado; **não instalado aqui** (repo errado) | Só faria sentido no repositório ADVPL/TLPP separado |
| `pybreaker`/`backon` | — | AVALIAR se já resolvido | **JÁ RESOLVIDO internamente** (outbox.py) | Retry/backoff determinístico já implementado; circuit breaker fica como adoção futura condicional |
| Config MCP CLI vs app desktop | Desconhecido | INVESTIGAR (rodada 1) | Investigado até o limite seguro; **sem solução aplicada** (rodada 2) | Nenhuma config documentada localizável com segurança para editar sem risco ao app |
| Limpeza de lixo (desktop.ini, pycache, staging Drive) | Manual | AUTOMATIZAR (rodada 1) | Mantido, rodando sozinho | Sem mudanças nesta rodada |

## Não instalado / adoção futura com gatilho objetivo

- **`pybreaker`** — só se houver evidência real de flapping de retries.
- **`pg_partman`** — sem dados de volume que justifiquem agora; gatilho: tabela de eventos/apontamento passar de volume que degrade performance de query perceptivelmente.
- **`react-window`** — bug histórico de "despejar catálogo" já corrigido; gatilho: nova tela com lista/tabela renderizando mais de ~500-1000 linhas sem paginação.
- **`advpl-tlpp-code-analyzer`** — requer Docker Desktop (disponível) e fontes de teste; passo a passo em `docs/REFERENCIAS_TECNICAS.md`.
- **`totvs/engpro-advpl-tlpp-skills`** — instalar no repositório ADVPL/TLPP separado, não aqui.
- **`prometheus-fastapi-instrumentator` + `structlog`** — não avaliados a fundo nesta rodada por tempo; permanecem como recomendação de referência.
