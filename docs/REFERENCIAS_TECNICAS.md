# Referências Técnicas — Pesquisa Externa (20/09/2026)

Levantamento amplo em GitHub/web para o Gestor de Peças. Curado: só o que passou o filtro de "realmente vale acompanhar". Pesquisa completa (todos os itens avaliados, incluindo IGNORAR) fica registrada no histórico da sessão que gerou este documento.

## MES / Manufatura

- **[SheetMetalConnect/eryxon-flow](https://github.com/SheetMetalConnect/eryxon-flow)** (BSL 1.1, ativo) — MES para job shop de chapa metálica/usinagem, o mais próximo do nosso domínio real. Servidor MCP com 113 ferramentas é um checklist valioso de cobertura de API contra a nossa.
- **[point85/OEE-Designer](https://github.com/point85/OEE-Designer)** (MIT, maduro) — taxonomia de perdas de tempo (time-loss model) mais rica que a maioria; vale comparar com nossa modelagem de OEE.
- **[crbnos/carbon](https://github.com/crbnos/carbon)** (AGPL-3.0, muito ativo, 2.6k★) — grafo de dependência de operações e módulo de qualidade com CAPA mais maduro que a média; referência se a Qualidade evoluir.
- **[united-manufacturing-hub](https://github.com/united-manufacturing-hub/united-manufacturing-hub)** (Apache 2.0) — templates de dashboard OEE/Andon em Grafana, bons como referência de layout (gauge + timeline + Pareto de paradas).
- **[factorysemantics/factorysemantics-mes](https://github.com/factorysemantics/factorysemantics-mes)** (Apache-2.0, pré-alpha) — princípio "never invent production" (nunca inferir produção de estado incerto) é regra de integridade valiosa para qualquer ingestão futura de contadores/sensores.

## APIs / Integração / Filas

- **[danielfm/pybreaker](https://github.com/danielfm/pybreaker)** (BSD) + **backon** — circuit breaker + retry/backoff leves para proteger as chamadas TOTVS contra flapping, sem reescrever a integração existente.
- **[taskiq-python](https://github.com/taskiq-python/taskiq)** (MIT) — fila async-first, encaixa melhor que Celery no worker de outbox se ele crescer.
- **[kvesteri/postgresql-audit](https://github.com/kvesteri/postgresql-audit)** (BSD) — padrão de schema de auditoria genérica via trigger, referência para consolidar auditoria sem duplicar lógica por módulo.
- **[svix/svix-webhooks](https://github.com/svix/svix-webhooks)** — não para instalar agora, mas é a referência de ouro de "como fazer webhook direito" (HMAC, retry, idempotência) se o Gestor precisar notificar terceiros no futuro.

## Protheus / ADVPL / TLPP

- **[totvs/engpro-advpl-tlpp-skills](https://github.com/totvs/engpro-advpl-tlpp-skills)** (MIT, 133★, oficial) — skills oficiais da TOTVS para IA fazer ADVPL/TLPP; comparar convenções com o repositório ADVPL separado.
- **[totvsengpro/advpl-tlpp-code-analyzer](https://hub.docker.com/r/totvsengpro/advpl-tlpp-code-analyzer)** (oficial, Docker) — lint estático estilo SonarQube para `.PRW`/`.PRX`, cobre uma lacuna real (nenhuma ferramenta genérica faz isso).
- **[totvs/advpl-vscode](https://github.com/totvs/advpl-vscode)** + **TOTVS Developer Studio for VSCode** — ferramentas oficiais de edição, preferíveis a extensões de terceiros.
- Nota honesta: o ecossistema é pobre em repositórios GitHub de qualidade — a maioria dos exemplos de terceiros tem 0-30★ e está abandonada desde 2018-2019. O conhecimento de boas práticas (aliases, work areas, SQL embutido) vive em blogs técnicos brasileiros (Terminal de Informação, ProtheusAdvpl.com.br), não em código aberto.

## PostgreSQL

- **[timescale/pg-aiguide](https://github.com/timescale/pg-aiguide)** (Apache-2.0) — **já instalado** nesta auditoria como plugin Claude Code (`pg@aiguide`). Documentação/boas práticas Postgres sob demanda.
- **[pgpartman/pg_partman](https://github.com/pgpartman/pg_partman)** (PostgreSQL License) — particionamento automático por tempo/retenção; direto para tabelas de eventos Andon/apontamento que crescem indefinidamente.
- **[sraoss/pg_ivm](https://github.com/sraoss/pg_ivm)** — materialized views com atualização incremental; útil para dashboards de OEE quase em tempo real sem recomputar tudo (checar se a hospedagem permite extensões custom antes de adotar).

## Frontend Industrial / Testes

- **Playwright CLI vs MCP (comparação direta feita nesta pesquisa)**: CLI (`pytest-playwright`) consome ~4x menos tokens que o MCP em teste prático (27k vs 114k) e não degrada em sessões longas. **Recomendação: usar Playwright CLI no CI, reservar o MCP só para exploração visual pontual.**
- **[bvaughn/react-window](https://github.com/bvaughn/react-window)** (MIT) — correção direta e barata para o padrão de bug já conhecido no projeto (telas que despejam catálogo inteiro / travam com muita linha).
- **[schemathesis](https://github.com/schemathesis/schemathesis)** (MIT) + **[testcontainers-python](https://github.com/testcontainers/testcontainers-python)** — testes de contrato de API a partir do OpenAPI do FastAPI + testes de integração contra Postgres real em vez de mocks/SQLite.
- **WCAG 2.3.2 (Three Flashes)** — regra dura contra piscar mais de 3x/segundo. Vale auditar os alertas do Andon/Solda: usar pulso lento ou mudança de cor+ícone, nunca strobe.

## OPC UA / MTConnect / IIoT (referência futura, sem integração real hoje)

- **[AndreasHeine/i3x2ua](https://github.com/AndreasHeine/i3x2ua)** (AGPL-3.0/comercial) — transforma OPC UA em REST+MCP, stack idêntica à nossa (FastAPI/Python); candidato a gateway sidecar se um dia integrarmos máquinas OPC UA reais.
- **[FreeOpcUa/opcua-asyncio](https://github.com/FreeOpcUa/opcua-asyncio)** (LGPL-3.0) — biblioteca de referência, mas **reconexão automática não vem pronta** — precisaria ser implementada por nós.
- **[thingsboard/thingsboard-gateway](https://github.com/thingsboard/thingsboard-gateway)** (Apache 2.0) — gateway multiprotocolo Python maduro; padrão "connector + converter" plugável é bom blueprint mesmo sem adotar a plataforma.

## Observabilidade

- **`prometheus-fastapi-instrumentator`** — métricas Prometheus direto nas rotas de OP/apontamento, baixo custo de adoção.
- **`hynek/structlog`** (MIT) — logging estruturado com contextvars, encaixa bem no FastAPI async; ganho de observabilidade incremental (introduzir primeiro no worker de outbox e no client TOTVS).

## Segurança

Combo gratuito de baixo overhead que cobre a maior parte do risco real:
- **gitleaks** (secret scanning) + **bandit** ou **Ruff regras `S`** (escolher um, não os dois) + **pip-audit** + Dependabot + `npm audit`.
- Achado de maior risco prático: **GitHub Actions não pinadas por SHA** no CI/self-hosted runner — correção barata e direta, relevante porque o projeto já teve um caso real de exposição (SOAP TOTVS via túnel Cloudflare, corrigido na auditoria de 14/09/2026).
- `snyk/agent-scan` **não é** scanner de dependências (é scanner de segurança para agentes de IA/MCP instalados na máquina) — não confundir com SCA.
- CodeQL/SonarQube: avaliados como pesados/caros demais para o porte atual — não recomendado agora.

## Claude Code — ecossistema

- **[netresearch/context7-skill](https://github.com/netresearch/context7-skill)** — mesma função do MCP permanente `context7` (docs atualizadas de biblioteca), mas como skill sob demanda, fração do custo de contexto. **Preferir esta a instalar o MCP.**
- Benchmark confirmado na pesquisa: um MCP genérico pode consumir de 1,3x a 80x mais tokens que o CLI equivalente (ex: GitHub MCP vs `gh`) — reforça manter a preferência CLI/skill sob demanda antes de MCP permanente.
- `anthropics/claude-plugins-official` tem um plugin **"claude-code-setup"** que analisa o próprio repo e sugere MCPs/skills sob medida — mais direto que garimpar catálogos "awesome-*" de terceiros.
- Catálogos "tudo em um" (`davila7/claude-code-templates` etc.) — útil só como índice; **não instalar em massa via curl**, um deles teve reporte de RCE no modo `--studio`.

## Top descobertas (sem ranking, 12 itens que merecem acompanhamento real)

1. **eryxon-flow** — MES do mesmo nicho (chapa metálica/usinagem), catálogo de API mais completo que o nosso hoje.
2. **pg-aiguide** — já instalado; ganho imediato de esforço zero para modelagem Postgres.
3. **Playwright CLI > MCP** para este projeto — decisão de arquitetura de testes com dado concreto (4x menos tokens).
4. **pybreaker + backon** — resiliência barata ao redor da integração TOTVS existente, sem reescrevê-la.
5. **totvs/engpro-advpl-tlpp-skills** — convenções oficiais para comparar com o repositório ADVPL separado.
6. **pg_partman** — resposta direta ao crescimento das tabelas de eventos/apontamento.
7. **react-window** — conserto barato para o bug já conhecido de telas que travam com muita linha.
8. **gitleaks + bandit/Ruff-S + pip-audit** — cobertura de segurança de alto retorno e custo quase zero.
9. **context7-skill** (não o MCP) — mesmo ganho, fração do custo de contexto.
10. **i3x2ua** — se algum dia integrarmos OPC UA real, é o atalho mais direto (stack idêntica à nossa).
11. **schemathesis** — testes de contrato de API gerados a partir do OpenAPI que o FastAPI já expõe, sem esforço de escrita manual.
12. **WCAG 2.3.2 (three flashes)** — checagem de acessibilidade concreta e acionável para o Andon/Solda.
