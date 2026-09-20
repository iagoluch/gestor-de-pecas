# Setup do Claude Code — Gestor de Peças

Auditoria em 20/09/2026, quatro rodadas na mesma data: (1) levantamento inicial, (2) decisão/execução, (3) fechamento com validação prática de cada item (CI real, bandit 100% triado, benchmark do headroom, Playwright/Schemathesis testados de verdade), (4) limpeza de dependências dev/runtime, registro do bug do Schemathesis, inspeção real de código dos MES externos e do repositório ADVPL/TLPP. Este documento existe para que qualquer pessoa (ou sessão futura de Claude Code) entenda o que está ativo neste ambiente, por quê, e o que fica de fora de propósito.

## Escopo desta máquina

Tudo abaixo é local a esta máquina Windows (`iago.luchtenberg`), configurado em `~/.claude`. Não afeta sessões na nuvem nem outras máquinas. Achado não resolvido: o marketplace de plugins (`~/.claude/plugins/known_marketplaces.json`) tem `installLocation` apontando para `C:\Users\logistica.unidade4\...`, indicando que esta máquina já teve outro perfil de usuário Windows configurando Claude Code antes.

## Achado importante, ainda sem solução: MCP servers da CLI ≠ MCP servers do app desktop

`claude mcp add --scope user` grava em `~/.claude.json` (usado quando você roda `claude` direto no terminal). **O app desktop (onde esta conversa roda) usa configuração própria separada.** Investigado nesta rodada até onde dava para ir sem risco: não há um arquivo de config de MCP do app desktop documentado publicamente nem localizado com segurança nesta auditoria para editar diretamente sem risco de corromper o app. Decisão: não replicar manualmente — os únicos MCPs realmente mantidos (`headroom`, `pg-aiguide`) continuam disponíveis via terminal; nenhum deles é crítico o suficiente para justificar mexer em configuração não documentada do app desktop. Se precisar de um deles dentro de uma conversa como esta, a via seguro é usar a CLI/skill equivalente em vez do MCP (ex.: skill `context7` em vez do MCP, `pg` via CLI do plugin quando aplicável).

## Componentes ativos

### MCP servers (escopo CLI/terminal, `~/.claude.json`)

| Servidor | O que faz | Rodada 1 | Rodada 2 |
|---|---|---|---|
| `headroom` | Comprime tool outputs/logs antes de chegarem ao modelo | Instalado | MANTIDO — sem evidência de problema, baixo overhead, benefício claro (compressão de contexto) |
| `omniroute` | Gateway de roteamento para 350+ provedores de IA | Instalado, depois removido, depois **restaurado** | MANTER EM AVALIAÇÃO — ver seção própria abaixo |
| `plugin:pg:pg-aiguide` | Documentação/boas práticas PostgreSQL via busca semântica (TigerData, hospedado) | Instalado | MANTIDO — hospedado (sem processo local), Apache-2.0, uso justificado |

### OmniRoute — reavaliado e restaurado (rodada 3)

A decisão de remover na rodada 2 foi precipitada: "39 requisições / $0" media 1-2 dias de instalação, não uma janela real de avaliação. Corrigido — classificação passa a ser **MANTER EM AVALIAÇÃO** (nem removido, nem obrigatório).

**Segurança reconfirmada nesta rodada:**
- Escuta só em `127.0.0.1:20128` (confirmado via `netstat`) — nenhuma interface exposta à rede.
- Rodando a partir de `~/.omniroute-run` (diretório neutro), não do diretório do projeto — sem risco de recarregar o `.env` do Gestor.
- Senha do dashboard já trocada da padrão (`CHANGEME`).
- **Pendente de reverificação manual**: o toggle "Cloud OmniRoute" (relay para a nuvem do fabricante) — não encontrei endpoint de API para checar o estado programaticamente sem gastar mais tempo; confirme em `http://localhost:20128` → Endpoints → "Cloud OmniRoute" que está desativado, se ainda não confirmou.

**Como ativar:**
```bash
# 1. Subir o servidor (de um diretório NEUTRO, nunca da raiz do projeto):
cd ~/.omniroute-run && OMNIROUTE_SERVER_HOST=127.0.0.1 omniroute serve
# 2. Registrar o MCP (uma vez, escopo CLI):
claude mcp add --transport http --scope user omniroute http://localhost:20128/api/mcp/stream \
  --header "Authorization: Bearer <chave-de-gerenciamento-do-dashboard>"
```

**Como desativar:**
```bash
claude mcp remove omniroute --scope user
# e finalizar o processo node do omniroute (verificar com: netstat -ano | grep 20128)
```

**Critério real de decisão daqui para frente** (não mais "quantas requisições teve"): usar por pelo menos algumas tarefas reais e então avaliar — permite modelos/provedores que agregam algo? reduz custo? melhora alguma tarefa? adiciona latência/instabilidade perceptível? é mais útil que Claude Code direto? Só depois disso decidir entre MANTER, USO SOB DEMANDA ou REMOVER — não antes.

### OmniRoute — decisão original de desabilitar (rodada 2, revertida na rodada 3)

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
- **bandit** — 44 avisos encontrados, **todos triados individualmente e suprimidos com `#nosec` documentado** (ver seção "Bandit — os 44 achados, 100% triados" abaixo). Bloqueante desde a rodada 3, sem `|| true`.

Não instalado: Ruff (o projeto não usa nenhum linter hoje; introduzir Ruff seria uma decisão maior que "segurança", fora do escopo desta auditoria — bandit é a ferramenta cirúrgica certa aqui, sem se comprometer com um linter completo).

### `netresearch/context7-skill` (rodada 2 — instalado)

Avaliado e instalado em `~/.claude/skills/context7/`. Licença `(MIT AND CC-BY-SA-4.0)`, sem chave de API (usa a API REST pública do Context7 via `curl`+`jq`), ativa sob demanda (skill, não MCP permanente). Substitui a necessidade do MCP `context7` permanente pela mesma função com fração do custo de contexto — confirma a preferência CLI/skill > MCP permanente já adotada no projeto.

### Playwright (ADOTADO desde a rodada 3 — não é mais POC)

**Adotado desde a rodada 3** (não é mais POC) — ver seção "Playwright — decisão firme: ADOTADO" abaixo. `tests/test_e2e_smoke.py` (sem skip), `requirements-dev.txt`, workflow `e2e.yml` próprio.

**Testado e validado de ponta a ponta**: Chromium baixado (191.8 MB, precisou de 3 tentativas por disputa de lock de arquivo `__dirlock` durante download concorrente — resolvido), teste rodado com `python -m pytest tests/test_e2e_smoke.py -v` contra o preview real (`gestor-preview-visual`, porta 8010) → **1 passed em 2.10s** (rodado 2x). Estado atual: sem `@pytest.mark.skip`, roda sob demanda via `.github/workflows/e2e.yml` (`workflow_dispatch`) — não faz parte do CI principal (`ci.yml`) nem bloqueia o deploy.

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

## Rodada 3 — fechamento com validação prática

### CI como gate real do deploy
`deploy.yml` agora chama `ci.yml` via `workflow_call` (job `validate`) antes de `build-frontend`/`deploy`. `ci.yml` passou a ignorar pushes de tag no seu próprio trigger (`tags-ignore: ["v*"]`) para não rodar em duplicidade no mesmo commit. Validado: `python3 -c "import yaml; ..."` confirma sintaxe válida nos dois arquivos.

### Least privilege do GITHUB_TOKEN
`permissions: contents: read` no topo de `ci.yml` e `deploy.yml` (nenhum job precisa de mais que isso — não há criação de release/tag/comentário).

### Supply chain — hardening final
- gitleaks pinado por **digest** (`@sha256:c00b6bd0...`), não só tag.
- bandit/pip-audit movidos para `requirements.txt` com versão exata (`bandit==1.9.4`, `pip-audit==2.10.1`) — rastreáveis pelo Dependabot.
- `.github/dependabot.yml` criado: `github-actions`, `pip` (raiz), `npm` (`/web`), `docker` (raiz, cobre `compose.yaml`). Limitação documentada: o Dependabot não rastreia a imagem do gitleaks (é `docker run` inline num workflow, não um Dockerfile/compose) — atualização dela continua manual.

### Segurança do frontend
`npm audit --audit-level=high` adicionado ao job `frontend` do CI (roda sempre, mesmo se build/teste falhar antes, via `if: always()`).

### Bandit — os 44 achados, 100% triados (não em massa)
Todos os 44 revisados individualmente lendo o código real (não presumido): 32× B608 (SQL via f-string — em **todos os casos**, os nomes de coluna/tabela vêm de constantes do módulo ou de allowlist por dict, valores reais sempre via `%s`/`%(...)s`), 3× B105 (nomes de variável/chave contendo "password", nenhum valor hardcoded), 2× B110 (`except: pass` de limpeza best-effort após falha já logada), 2× B404/B603 (subprocess com lista fixa de args, sem shell, path resolvido via `shutil.which`), 3× B405/B406 (XML de entrada usa `defusedxml`; os imports de `xml.etree`/`xml.sax.saxutils` flagados são só para tipo de exceção ou construção/escape de XML de saída, nunca parse de XML não confiável). Todos suprimidos com `# nosec BXXX -- <motivo>` localizado na linha exata (para strings multi-linha, na linha de fechamento do `"""`, único lugar onde o bandit realmente lê o comentário — validado empiricamente antes de aplicar em massa). CI confirmado rodando limpo: `bandit -r backend mes app -ll` → **exit code 0, "No issues identified", 44 disabled**. `|| true` removido — agora é bloqueante de verdade.

### Graphify — portabilidade corrigida
`.claude/settings.json`: caminho absoluto (`C:/Users/iago.luchtenberg/.local/bin/graphify.EXE`) trocado por `graphify` bare (resolve via PATH em qualquer máquina que tenha o `uv tool install graphifyy` feito). Testado: `echo '...' | graphify hook-guard search` funciona via PATH.

O hook de rebuild deixou de viver só em `.git/hooks/` (não versionado): movido para `scripts/graphify-rebuild.sh` (rastreado no git), com `scripts/setup-dev-hooks.sh` — instalador pequeno e idempotente que qualquer clone novo roda uma vez (`sh scripts/setup-dev-hooks.sh`) para religar o gatilho de post-commit sem sobrescrever o auto-push já existente. Testado duas vezes: idempotência (rodar de novo diz "já estava instalado, nada a fazer") e simulação de clone novo (sem hook prévio) em `$HOME/hook_test_repo` temporário, removido depois.

### Playwright — decisão firme: ADOTADO (não é mais POC)
- `requirements-dev.txt` criado (`playwright==1.62.0`, `pytest-playwright==0.9.0`), separado do `requirements.txt` de propósito (pesado, só quem roda E2E precisa).
- Teste renomeado de `poc_playwright_smoke.py` para `tests/test_e2e_smoke.py` (sem `@pytest.mark.skip` — não é mais POC), confirmado que `unittest discover` do CI principal não tenta rodá-lo (é estilo pytest com fixture, `unittest` não encontra `TestCase` nenhuma ali — testado, "Ran 0 tests... NO TESTS RAN", zero risco de quebrar o CI principal).
- `.github/workflows/e2e.yml` criado: `workflow_dispatch` (sob demanda, não bloqueia CI/deploy), instala `requirements-dev.txt`, `playwright install --with-deps chromium`, sobe o preview visual, roda o teste.
- **Validado de ponta a ponta duas vezes nesta rodada**, com o gotcha real documentado: no Windows, usar o Python do `.venv` do projeto (`./.venv/Scripts/python.exe`), não um `python3` solto no PATH que pode não ter as libs do projeto instaladas.

### Schemathesis — testado de verdade, achou bug real
Instalado (`schemathesis==4.27.5`), rodado contra `http://127.0.0.1:8010/api/openapi.json` (preview visual, self-contained, sem banco real) com `--max-examples=20`: **106 operações testadas, 496 casos gerados**.

**Achado real e concreto**: `GET /api/v1/audit/appointments?fim=0263-10-17T17:14:48Z` retorna **500 Internal Server Error** em vez de 422 — o parâmetro de data `fim` não valida limites plausíveis antes de processar, e uma data extrema (ano 0263, gerada pelo fuzzing) derruba a rotina em vez de ser rejeitada como entrada inválida. **Não corrigido nesta rodada** (regra de negócio, fora do escopo desta auditoria de infraestrutura) — reportado para correção futura.

Outros achados: 102 operações só retornaram 401 (autenticação não configurada no teste — esperado), 2× 503 em `/PcfIntegService` ("Receptor SOAP TOTVS desabilitado por configuração" — comportamento esperado no ambiente de preview, não é bug), 130 "undocumented status code" e 43 "unsupported methods" são majoritariamente ruído de schema (OpenAPI não documenta todo código de erro possível) e fuzzing de métodos HTTP fora da superfície real da API.

**Decisão**: valor real comprovado (achou 1 bug genuíno). Adicionado a `requirements-dev.txt` junto com Playwright, comando documentado. **Não incorporado ao CI ainda** — precisaria de curadoria da lista de status codes esperados por endpoint antes de virar gate (senão o 503 esperado do SOAP desligado e os 401 de autenticação quebrariam o build por ruído, não por bug real).

### Testcontainers — rejeitado com evidência
Confirmado por grep: o projeto já tem uma convenção madura e documentada (`TEST_DATABASE_URL`, citada no README, usada em toda a suíte de testes de integração) apontando para Postgres real — via `services.postgres` no CI e `compose.yaml` (porta 15432) localmente. `testcontainers-python` resolveria o mesmo problema de forma paralela e redundante, sem nenhuma lacuna real identificada. **REJEITADO — infraestrutura de CI/dev já cobre o problema.**

### Headroom — benchmark real (biblioteca Python, não CLI)
Usando `headroom.compress()` diretamente (ambiente isolado do `uv tool`, `~/AppData/Roaming/uv/tools/headroom-ai/`) contra dados reais deste projeto:

| Cenário | Tokens antes | Tokens depois | Redução | Latência | Fidelidade |
|---|---|---|---|---|---|
| JSON estruturado grande (saída do bandit, 63KB) | 24.175 | 1.411 | **94,2%** | 2,3s | Preservada (verificado sem o erro de metodologia da 1ª tentativa) |
| Leitura de arquivo de código (`database.py`, 256KB) | 52.998 | 52.998 | **0%** | 0,9s | N/A |

**Achado importante não óbvio**: para `tool_result` de leitura de código-fonte (`Read`), o headroom aplica `router:excluded:tool` — **exclui esse tipo de conteúdo da compressão por padrão**, presumivelmente para nunca arriscar alterar código que o agente vai usar. Isso significa que o ganho real de tokens numa sessão típica de desenvolvimento (onde grande parte do volume é leitura de arquivos de código, não saída de comandos/JSON) é bem menor do que a redução de 94% sugere isoladamente — o benefício concentra-se em saídas de ferramentas tipo Bash/grep/logs/JSON, não em leitura de arquivos.

**Decisão**: MANTER — ganho real e mensurável existe (para o tipo certo de conteúdo), sem perda de fidelidade detectada, latência aceitável (segundos, não dezenas de segundos). Ressalva documentada acima sobre onde o ganho realmente se aplica.

### Context7 skill — smoke test real
Skill descoberta pelo Claude Code (`Skill(context7)` funcionou). Executado o fluxo real: `context7.sh search "fastapi"` → `context7.sh docs "/websites/fastapi_tiangolo" "dependency injection with default values" "code"` → retornou documentação atual e citável (exemplos de `Depends()`, `Query()` com link para `fastapi.tiangolo.com`), sem precisar de `CONTEXT7_API_KEY`.

**Achado real durante o teste**: a skill declara depender de `curl` e `jq`, mas **`jq` não estava instalado nesta máquina** — a skill falhava silenciosamente sem isso. Corrigido: `jq` baixado direto do release oficial (`jqlang/jq`) para `~/.local/bin/jq.exe`, sem precisar de admin (chocolatey também travou por falta de permissão, mesmo problema do gitleaks/graphify anteriores).

## Tabela: Componente | Antes | Ação | Depois | Motivo

| Componente | Antes | Ação | Depois | Motivo |
|---|---|---|---|---|
| Skills `*-automation` (Composio) | 832 instaladas, 0 uso | REMOVER (rodada 1) | Removidas | 0 uso real, stack proprietário fora do catálogo |
| `graphify` | — | INSTALAR (rodada 1) | Mantido, validado funcionando (rodada 2) | Grafo de código funcional, sem redundância |
| `headroom` (MCP) | — | INSTALAR (rodada 1) | Mantido (rodada 2) | Benefício claro, baixo overhead |
| `omniroute` (MCP) | — | INSTALAR (rodada 1) → REMOVIDO (rodada 2, precipitado) → **RESTAURADO** (rodada 3) | MANTER EM AVALIAÇÃO | Remoção na rodada 2 media só 1-2 dias de instalação, não uso real; segurança reconfirmada (loopback, dir neutro), critério de decisão futura documentado |
| `pg-aiguide` (plugin) | — | INSTALAR (rodada 1) | Mantido (rodada 2) | Hospedado, Apache-2.0, uso justificado |
| `context7` (skill) | — | — | **INSTALADO** (rodada 2) | Substitui MCP permanente por fração do custo de contexto |
| Sistema "Brain" (hooks) | Ativo em toda mensagem | INVESTIGAR (rodada 1) | **Hooks removidos** (rodada 2) | `decisions/` vazio após semanas de uso — redundante com auto-memória nativa, confirmado com evidência |
| GitHub Actions (tags) | `@v4`/`@v5` mutáveis | AUDITAR (rodada 1) | **Pinadas por SHA** (rodada 2) | Risco de supply-chain real e documentado, correção segura sem mudar versão |
| Segurança no CI | Inexistente | AVALIAR ferramentas → triar bandit (rodada 3) | **gitleaks + pip-audit + bandit, os 3 bloqueantes**, 44 achados do bandit 100% triados e suprimidos com `#nosec` | Cobertura de alto retorno/baixo custo, validada antes de commitar |
| Playwright | Não instalado | AVALIAR CLI vs MCP → **ADOTAR** (rodada 3) | Dependência reproduzível (`requirements-dev.txt`), teste renomeado (não é mais POC), workflow `e2e.yml` dedicado, validado 2x de ponta a ponta | CLI vence MCP em custo de contexto (~4x), confirmado por medição |
| Schemathesis | Não instalado | TESTAR (rodada 2) → **TESTADO de verdade** (rodada 3) | Achou bug real (500 em data extrema); em `requirements-dev.txt`, não incorporado ao CI ainda (precisa curar status codes esperados) | Valor comprovado, não hipotético |
| testcontainers-python | — | AVALIAR com ceticismo (rodada 3) | **REJEITADO** com evidência (`TEST_DATABASE_URL` já é convenção madura) | CI/dev já cobrem o problema |
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
