# Paridade operacional Claude Code -> Codex

Verificado em 22/09/2026 com Claude Code 2.1.223 e Codex CLI 0.155.0-alpha.9.2.
Nenhum token, senha, cookie ou outro segredo foi migrado ou registrado aqui.

## Arquitetura Codex

- Instrucoes: `~/.codex/AGENTS.md` e `AGENTS.md` do projeto.
- Memoria: memoria nativa ativa e Brain compartilhado em `~/.claude/brain`.
- Skills: `~/.codex/skills` e `~/.agents/skills`.
- Hooks: `~/.codex/hooks.json` e `.codex/hooks.json`.
- MCP/plugins: `~/.codex/config.toml` e registros nativos do Codex.
- Delegacao: perfis nativos `fast`, `standard`, `hard` e `extreme`.

O diretorio `.claude/` foi preservado. Quando ambos os agentes usam a mesma
skill, o Codex a acessa por junction, sem manter uma segunda copia.

## Matriz de paridade

| Capacidade | Claude | Codex | Estado |
| --- | --- | --- | --- |
| Instrucoes | CLAUDE.md e regras locais | AGENTS global e do projeto | OK |
| Memoria | Brain | memoria nativa mais Brain | OK |
| Skills | 900 `SKILL.md` (68 individuais e 832 Composio) | 68 nativas/compartilhadas e catálogo Composio sob demanda | OK |
| Hooks globais | Task Observer | Brain e Task Observer | PARCIAL |
| Hooks de projeto | Graphify, TS, Headroom, Ponytail, Impeccable | mesmos comportamentos | OK |
| MCP | pg-aiguide, Headroom | pg_aiguide, Headroom, OmniRoute | PARCIAL |
| Plugins | Setup e pg-aiguide | Setup, documentos, browser, computador | OK |
| Agentes | perfis e agentes Impeccable | perfis e delegacao nativa | OK |
| Comandos | contexto, decidir, dia, fim, status | skills `source-command-*` | OK |
| Git/GitHub | Git e GH CLI | mesmos binarios | OK |

## Skills e comandos

O Claude tem 900 arquivos `SKILL.md`: 68 skills individuais e 832 automacoes
Composio. As 68 individuais permanecem acessiveis por skills compartilhadas,
plugins nativos de documentos ou junctions para a fonte Claude. `impeccable`
usa o detector de UI local; `task-observer` recebe gatilho global de sessao.

O catalogo e montado na abertura da conversa. As 832 automacoes Composio do
Claude foram espelhadas, sem perda, para
`~/.codex/skill-library/composio-skills`; a skill
`composio-automation-catalog` localiza e carrega somente a automacao pedida.
As 29 skills identicas em `~/.agents/skills` foram arquivadas fora da busca,
pois as copias nativas de `~/.codex/skills` permanecem ativas. Isso eliminou a
perda total de descricoes: o Codex ainda pode compacta-las, mas mantem todas as
skills visiveis e carregaveis.

`project_doc_max_bytes = 98304` em `~/.codex/config.toml` permite carregar o
`AGENTS.md` atual (72,5 KB) por inteiro. Para adicionar uma skill, preferir a
biblioteca nativa, evitar segredos e validar `SKILL.md` e seus scripts; para
alterar uma regra permanente, editar o `AGENTS.md` aplicavel e a documentacao
de estado correspondente, sem duplicar regra em skill.

## Hooks e memoria

O Brain permanece nos eventos globais SessionStart e UserPromptSubmit. O
Task Observer tem segundo SessionStart, por
`~/.codex/hooks/task-observer-activate.cmd`, que emite texto simples compativel
com Codex e aponta para o workspace compartilhado
`~/.claude/skill-observations`. Os hooks do projeto preservam guardas
Graphify, type-check TS, Headroom, Ponytail e Impeccable.

O Codex exige confianca explicita em hooks novos. Nao editar hashes de
confianca manualmente: aprovar pela interface `/hooks` em nova sessao.

## MCP, plugins e seguranca

Codex registra Headroom por stdio, pg_aiguide por HTTP, OmniRoute por
Streamable HTTP e runtimes nativos de browser/computador. O launcher do
Headroom estava orfao; ele foi restaurado offline a partir do cache local da
versao 0.37.0, incluindo o extra oficial `mcp`, e o registro passou a apontar
para o executavel do ambiente `uv`. O `initialize` MCP devolveu resposta valida
e uma chamada sintetica a `headroom_compress` executou o pipeline local. A
politica global de aprovacao impede essa chamada quando feita por um agente,
mas nao impede a inicializacao. O pg_aiguide foi validado por HTTP com
`initialize`, `tools/list` e `search_docs` somente-leitura. OmniRoute em
escuta local ainda nao prova provider nem chamada de ferramenta. Registrar
paridade MCP como OK somente apos operacao segura real para cada integracao.

Uma credencial preexistente foi encontrada em configuracao Codex. Ela nao foi
copiada nem exibida. Deve ser rotacionada e movida a secret store em manutencao
controlada. O projeto usa aprovacao automatica e sandbox irrestrito; hooks nao
substituem revisao de acoes destrutivas e das fronteiras TESTE/REAL.

Para incluir MCP, registrar a configuracao nativa em `~/.codex/config.toml`,
preferir variavel de ambiente para segredo, conferir `codex mcp list` e chamar
uma operacao somente-leitura antes de declarar a integracao pronta. Para testar
a configuracao geral, executar `codex --strict-config --help`, `codex features list`,
`codex doctor --summary` e um `codex exec --sandbox read-only` com um contrato
de instrucao ou skill conhecido.

## Validacao e pendencias

Foram verificados versoes, help, configuracoes, skills, hooks, agentes, MCPs,
plugins, GitHub CLI, JSON dos hooks, comandos de baixo risco e listeners locais.
O hook Task Observer permanece PARCIAL ate ser confiado pelo Codex em nova
sessao. MCP permanece PARCIAL somente por OmniRoute ainda nao possuir operacao
segura comprovada neste ciclo. As instrucoes completas e as skills migradas
foram verificadas em sessoes CLI limpas; a compactacao de descricoes de skills
e diagnostico de contexto, nao perda de descoberta.
