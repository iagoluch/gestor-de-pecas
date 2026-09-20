# Referências Técnicas — Pesquisa Externa

Duas rodadas na mesma data (20/09/2026): levantamento amplo + rodada de decisão/execução sobre os achados. Curado — não é catálogo de todos os links avaliados, mas todos os **repositórios obrigatórios** pedidos pela rodada 2 aparecem aqui com decisão explícita, mesmo os rejeitados.

## Repositórios obrigatórios (rodada 2) — nenhum descartado silenciosamente

| Repo | Decisão | Motivo |
|---|---|---|
| `point85/mes-ai` | ESTUDAR | Stack quase idêntico (FastAPI+PostgreSQL+React); padrão de sidecar gRPC para SDKs proprietários é aplicável |
| `point85/OEE-Designer` | REFERÊNCIA ARQUITETURAL | Taxonomia de perdas de tempo (time-loss model) mais rica que a maioria; comparar com nossa modelagem de OEE |
| `Mes-Open/OpenMes` | ESTUDAR | Modelo de eventos de domínio e padrão snapshot+delta via WebSocket para Andon; AGPL-3.0, não copiar código |
| `SheetMetalConnect/eryxon-flow` | ESTUDAR (investigado a fundo) | Ver seção própria abaixo — comparação de cobertura de API |
| `FreeOpcUa/opcua-asyncio` | TESTAR (quando houver demanda real) | Biblioteca de referência para OPC UA em Python, mas reconexão automática não vem pronta |
| `mtconnect/cppagent` | ACOMPANHAR | Agente oficial MTConnect; relevante só se integrarmos CNCs que falem MTConnect nativamente |
| `anthropics/claude-code` | MANTER | É a própria ferramenta em uso (v2.1.223 confirmado nesta auditoria) |
| `anthropics/claude-plugins-official` | MANTER/ACOMPANHAR | Já configurado como marketplace neste ambiente; plugin `claude-code-setup` é a via recomendada para sugestões futuras de MCP/skill |
| `anthropics/skills` | MANTER | Já é a fonte das skills `anthropic-skills:*` (docx, pdf, pptx, xlsx, skill-creator etc.) já instaladas |
| `modelcontextprotocol/modelcontextprotocol` | REFERÊNCIA | Especificação do protocolo em si, sem ação — usado indiretamente por todo MCP já configurado |
| `modelcontextprotocol/inspector` | ACOMPANHAR | Ferramenta de debug de servidores MCP; útil só se formos desenvolver um MCP próprio (ex.: expor o domínio do Gestor via MCP, ver ideia do eryxon-flow abaixo) |
| `upstash/context7` | **REJEITADO em favor de `netresearch/context7-skill`** | Mesma função como skill sob demanda, fração do custo de contexto do MCP permanente — **instalado o substituto, não o MCP** |
| `microsoft/playwright` | **INSTALAR AGORA — feito** | `pytest-playwright` instalado, POC criada (ver `docs/CLAUDE_CODE_SETUP.md`) |
| `microsoft/playwright-mcp` | ACOMPANHAR (não adotado para CI) | ~4x mais tokens que a CLI em teste medido; reservado só para exploração visual pontual |
| `timescale/pg-aiguide` | **INSTALADO** (rodada 1, mantido) | Plugin Claude Code ativo, hospedado, Apache-2.0 |
| `gitleaks/gitleaks` | **INSTALADO no CI — feito** | Testado localmente, achou 4 falsos positivos, allowlist criada, agora bloqueante e limpo |
| `semgrep/semgrep` | ACOMPANHAR | `bandit` já cobre padrões de segurança Python; semgrep teria valor incremental cobrindo o frontend JS/TS (bandit não cobre) — não instalado agora para não empilhar 2 SAST de uma vez sem triagem, mas é o candidato natural para preencher essa lacuna depois |
| `snyk/agent-scan` | IGNORAR | Não é scanner de dependências (SCA) — é scanner de segurança para agentes de IA/MCP instalados na máquina; nome engana, não resolve o problema que buscávamos |

## Eryxon Flow — comparação de cobertura funcional (investigação aprofundada, rodada 2)

**Ficha técnica**: React 18+TS+Vite+shadcn/ui, backend Supabase (Postgres 17+Edge Functions+Realtime), MCP server próprio com ~99-113 tools. Licença **Business Source License 1.1** — self-host single-site é grátis, converte para GPLv2+ após 4 anos. **Implicação prática**: ler a API/MCP publicamente documentada para inspiração de padrões é seguro; copiar código-fonte literal exigiria avaliação de licenciamento (evitado).

| Capacidade do eryxon-flow | Existe no nosso domínio? | Vale considerar? |
|---|---|---|
| CRUD de Jobs/Parts | Existe (padrão, via OP/TOTVS) | Não |
| Operations com máquina de estados explícita (start/pause/resume/complete) | Parcial | Talvez — conferir se apontamento distingue pausa voluntária de parada Andon como estados separados |
| Substeps com templates de inspeção reutilizáveis | Parcial | **Sim** — template de checklist aplicável a operações é padrão limpo para Qualidade por etapa |
| Scrap reasons com Pareto/trend dedicado | Parcial | **Sim** — baixo esforço, alto valor prático pro chão de fábrica |
| Webhooks assinados de ciclo de vida (job/operação) | Não existe | **Sim** — padrão de integração reutilizável para desacoplar futuros consumidores do polling |
| Superfície MCP completa espelhando toda a API REST do domínio | Não existe | **Sim, é o achado mais estrutural** — se o time já usa MCP em outros contextos, expor OP/operação/apontamento/Andon como tools MCP nativas do próprio backend padronizaria automação |
| Envelope de resposta padronizado `{success, data, error}` | Parcial | Sim — convenção barata de aplicar, reduz inconsistência entre módulos |
| Locations & Placement (posição física da peça) | Não existe | Talvez — só se houver dor real de "onde está a peça fisicamente" |
| Activity/audit trail como tool MCP dedicada | Parcial | Não — Dev Observatory já resolve de forma equivalente ou superior |

Não virou backlog — é referência de padrões, não lista de tarefas.

## ADVPL/TLPP — skills oficiais e analisador (investigado a fundo, rodada 2)

### `totvs/engpro-advpl-tlpp-skills` — TESTAR no repositório ADVPL separado

Conteúdo real lido e verificado (não apenas o README): 20 skills específicas de ADVPL/TLPP (`advpl-to-tlpp-migration`, `code-review` com ~800-900 linhas de checklist real incluindo SQL injection em `DbSelectArea` e proibição de acesso direto a tabelas `SX*`, `mvc-generator`, `advpl-tlpp-sdd` com a regra real "todo arquivo gerado por IA é UTF-8, mas o compilador RDMake requer CP-1252 — conversão obrigatória antes de compilar", `context-map`) + 14 skills genéricas redundantes (ignorar, já cobertas por skills equivalentes já instaladas).

**Passo a passo para adoção** (no repositório ADVPL/TLPP separado, não neste):
1. Clonar `totvs/engpro-advpl-tlpp-skills` num diretório temporário.
2. Copiar só `skills/advpl-tlpp/*` (ignorar `superpowers/`) para `.claude/skills/` do repositório ADVPL separado.
3. Copiar `instructions/CLAUDE.md` (ou `AGENTS.md`) para a raiz desse repo.
4. Testar com uma tarefa real (ex.: revisão de um `.PRW` existente com a skill `code-review`) antes de adotar permanentemente.

### `totvsengpro/advpl-tlpp-code-analyzer` — PREPARAR ADOÇÃO FUTURA

Investigado: `docker run --rm -ti -v /path/to/files:/tmp totvsengpro/advpl-tlpp-code-analyzer`, config opcional via volume `/bin/conf` com `config.json` (`breakList`/`ignoreList`/`breakOnError`), saída em JSON (opção `printSonarFullOutput` para bruto), suporte a `.TLPP` documentado como opcional além de `.PRW`/`.PRX`. **Sem exemplo oficial de CI publicado** — precisaria ser escrito do zero. Imagem de 444MB, requer Docker Desktop (instalado nesta máquina, confirmado).

**Passo a passo para quando validar de verdade** (no repositório ADVPL separado):
1. `docker pull totvsengpro/advpl-tlpp-code-analyzer`.
2. Testar com 2-3 fontes `.PRW`/`.TLPP` reais + pasta `includes/`.
3. Validar profundidade real em `.TLPP`, tempo de execução, se o JSON é parseável para gate de CI.
4. Consultar `sonar-rules.engpro.totvs.com.br` para curar `breakList`/`ignoreList` **antes** de ativar `breakOnError: true` — sem essa curadoria vai quebrar build com falsos positivos.

## Resiliência de integração TOTVS — já resolvido internamente

Investigação no código confirmou: `mes/integrations/totvs/outbox.py` já implementa retry com backoff determinístico, classificação de falha por tipo, e limite de tentativas. **`backon`/`pybreaker` (retry/backoff): JÁ RESOLVIDO — não instalar.** Circuit breaker explícito (`pybreaker`): **PREPARAR ADOÇÃO FUTURA**, gatilho objetivo = evidência real de flapping/tempestade de retries degradando performance.

## PostgreSQL

- **`pg-aiguide`** — instalado e mantido (ver `CLAUDE_CODE_SETUP.md`).
- **`pg_partman`** — **PREPARAR ADOÇÃO FUTURA**. Sem dados de volume de tabela disponíveis nesta auditoria para justificar agora. Gatilho objetivo: tabela de eventos/apontamento/Andon ultrapassar volume que degrade performance de query perceptivelmente (medir antes de agir).
- **`pg_ivm`** — materialized views incrementais para dashboards de OEE quase em tempo real; checar se a hospedagem permite extensões custom antes de considerar.

## Frontend / Testes

- **Playwright CLI (`pytest-playwright`)** — **instalado nesta rodada**, POC em `tests/poc_playwright_smoke.py`. Recomendação confirmada: CLI > MCP para este caso de uso (~4x menos tokens medidos).
- **`react-window`** — **PREPARAR ADOÇÃO FUTURA**. O bug histórico de "despejar catálogo inteiro" já foi corrigido (memória do projeto). Gatilho objetivo: nova tela com lista/tabela de mais de ~500-1000 linhas sem paginação.
- **`schemathesis`** — ainda não testado na prática nesta rodada (ficou para a próxima iteração); continua classificado TESTAR, já com o caminho claro (FastAPI expõe OpenAPI automaticamente, rodar contra um endpoint não-crítico primeiro).
- **`testcontainers-python`** — ainda não testado na prática nesta rodada; continua classificado TESTAR.

## Segurança — CI (feito nesta rodada)

Ver detalhes de execução/teste em `docs/CLAUDE_CODE_SETUP.md`. Resumo:
- **gitleaks**: instalado no CI, testado, allowlist criada para 3 falsos positivos confirmados, bloqueante.
- **pip-audit**: instalado no CI, testado (0 vulnerabilidades hoje), bloqueante.
- **bandit**: instalado no CI, testado (44 avisos, maioria falso-positivo provável em SQL de coluna constante), **informativo** até triagem manual.
- **semgrep**: ver tabela de obrigatórios acima — ACOMPANHAR, candidato a preencher a lacuna de SAST no frontend JS/TS.
- GitHub Actions pinadas por SHA — feito.

## Claude Code — ecossistema

- **`netresearch/context7-skill`** — **instalado** nesta rodada (substitui o MCP `context7`).
- **`anthropics/claude-plugins-official`** (plugin `claude-code-setup`) — não executado nesta rodada; é a via recomendada para a próxima auditoria em vez de garimpar catálogos de terceiros.
- Catálogos "tudo em um" (`davila7/claude-code-templates` etc.) — mantido o alerta da rodada 1: usar só como índice, nunca instalar em massa via curl.

## Top descobertas (consolidado das duas rodadas, sem ranking)

1. **Superfície MCP completa do próprio domínio (ideia do eryxon-flow)** — se o Gestor já usa MCP em outros contextos, expor OP/operação/apontamento como tools MCP nativas do próprio backend é o achado mais estrutural desta rodada.
2. **OmniRoute removido com dados concretos** — 39 requisições, $0 de uso real, decisão de desabilitar baseada em evidência, não em achismo.
3. **Brain removido com evidência** — `decisions/` vazio após semanas rodando em toda mensagem confirma redundância real com a auto-memória nativa.
4. **GitHub Actions pinadas por SHA** — risco de supply-chain real corrigido, sem mudar comportamento (mesma versão major).
5. **gitleaks encontrou candidatos reais** (todos falsos positivos confirmados, não descartados sem checar) — validou que o processo de triagem funciona antes de confiar no gate.
6. **Retry/backoff já resolvido internamente** — evitou adicionar dependência (`backon`) para substituir código que já funciona bem.
7. **context7-skill substitui o MCP permanente** — mesmo ganho, fração do custo de contexto, consistente com a preferência CLI/skill > MCP.
8. **totvs/engpro-advpl-tlpp-skills** — qualidade real confirmada por leitura de 5 SKILL.md, mas correto identificar que pertence ao repositório errado (ADVPL separado), não instalado aqui por precisão de escopo.
9. **Playwright CLI configurado com POC real** — decisão de arquitetura de testes com caminho de adoção concreto, não só recomendação.
10. **pg_partman e react-window preparados para adoção futura com gatilho objetivo**, não instalados preventivamente sem evidência de necessidade — evita dependência sem propósito.
