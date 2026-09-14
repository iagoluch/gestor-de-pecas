# Relatório de implementação — IA Industrial com Groq

> **HISTÓRICO.** Este relatório registra a implementação da IA em 25/08/2026. Menções a bancos de simulação/residência não definem o ambiente atual; em 27/08/2026 o TESTE oficial foi consolidado em `gestor_pecas_test`. Consulte `ROADMAP.md`.

**Projeto:** Gestor de Peças  
**Data da consolidação:** 25/08/2026  
**Ambiente:** checkout de testes, PostgreSQL local em Docker  
**Situação:** implementação concluída e validada sem chamada real à Groq

## 1. Resumo executivo

Foi implementada uma V1 da IA Industrial do Gestor de Peças para usuários gerenciais. A funcionalidade permite consultar e explicar informações do MES por meio da Groq, sem conceder ao modelo acesso direto ao banco e sem permitir qualquer alteração produtiva.

A integração reutiliza os contratos e serviços canônicos já existentes. O modelo pode solicitar somente ferramentas explicitamente autorizadas, que chamam a `FrontendBackendFacade`. A interface Web foi adicionada como sub-aba de **Tela inicial**, preservando a identidade visual oficial do sistema.

Também foram concluídos:

- migration PostgreSQL 14 para conversas, mensagens e conhecimento validado;
- streaming dedicado de respostas por SSE;
- isolamento de conversas por usuário;
- proteção CSRF nos endpoints de escrita técnica;
- limites de histórico, ferramentas, período e volume de dados;
- tratamento seguro de falhas e cancelamento;
- testes Python, PostgreSQL e React;
- build Web de produção;
- validação visual em quatro resoluções;
- otimizações de memória, consultas e robustez de migrations;
- normalização e validação do banco residencial em loopback.

## 2. Escopo e limites

### 2.1 Escopo implementado

- Consultas gerenciais sobre fábrica, setores, recursos, OPs, produção, paradas, qualidade, setup, nestings, auditoria e KPIs.
- Explicações baseadas exclusivamente nos resultados canônicos do backend.
- Conversas persistentes e isoladas por gestor.
- Resposta progressiva no navegador.
- Conhecimento adicional somente quando estiver marcado como validado.
- Estado controlado quando a IA estiver desabilitada ou sem chave.

### 2.2 Ações proibidas para a IA

A IA não possui ferramentas para:

- executar SQL;
- iniciar, interromper, retomar ou finalizar produção;
- alterar quantidade boa, refugo ou retrabalho;
- alterar OP, operação, estado físico ou cadastro;
- controlar máquinas, PLC, OPC ou Modbus;
- modificar planejamento;
- escrever em tabelas produtivas.

As únicas escritas técnicas autorizadas são nas tabelas `ai_conversations` e `ai_messages`. A tabela `ai_knowledge` foi preparada para governança futura, sem endpoint público de escrita nesta versão.

## 3. Arquitetura implementada

```text
React /inicio/ia
        │
        ▼
FastAPI /api/v1/ai
        │
        ├── AIService ───────────────► GroqProvider ─► Groq API
        │
        ├── AIToolRegistry
        │         │
        │         ▼
        │   FrontendBackendFacade
        │         │
        │         ▼
        │   Serviços MES canônicos ─► PostgreSQL
        │
        └── AIRepository ────────────► ai_conversations
                                       ai_messages
                                       ai_knowledge
```

### 3.1 Separação de responsabilidades

- `backend/ai/groq_provider.py`: adaptação assíncrona da API Groq.
- `mes/services/ai_service.py`: orquestra histórico, tool calling, resposta e persistência.
- `mes/services/ai_tools.py`: whitelist e validação das consultas permitidas.
- `mes/ai/prompts/system_prompt.py`: regras industriais e de segurança do modelo.
- `mes/contracts/ai.py`: contratos neutros, sem dependência de FastAPI ou Groq.
- `app/database/ai_repository.py`: persistência técnica da IA.
- `backend/api/routers/ai.py`: contrato HTTP e streaming SSE.
- `web/src/pages/AIPage.tsx`: interface gerencial.

O fluxo preserva a dependência esperada do projeto:

```text
UI/Web → contratos/serviços → domínio/analytics → repositórios → infraestrutura
```

## 4. Integração com a Groq

Foi adicionada a dependência:

```text
groq>=1.6,<2
```

O provider usa `AsyncGroq`, timeout limitado, retry limitado e os parâmetros:

- modelo padrão `openai/gpt-oss-120b`;
- `reasoning_effort` configurável entre `low`, `medium` e `high`;
- `reasoning_format="hidden"`;
- temperatura configurável;
- limite de tokens configurável;
- tool calling local;
- streaming com `stream=True`.

O SDK é carregado de maneira que a ausência da dependência ou da chave não impeça a inicialização do restante do Gestor.

Documentação oficial usada como referência:

- [Groq — GPT OSS 120B](https://console.groq.com/docs/model/openai/gpt-oss-120b)
- [Groq — Local Tool Calling](https://console.groq.com/docs/tool-use/local-tool-calling)
- [Groq — Text Streaming](https://console.groq.com/docs/text-chat)
- [Groq — API Reference](https://console.groq.com/docs/api-reference)

## 5. Configuração por ambiente

As seguintes variáveis foram adicionadas ao contrato de configuração:

```dotenv
GROQ_API_KEY=
GESTOR_AI_ENABLED=false
GESTOR_AI_MODEL=openai/gpt-oss-120b
GESTOR_AI_REASONING_EFFORT=medium
GESTOR_AI_TEMPERATURE=0.2
GESTOR_AI_MAX_COMPLETION_TOKENS=768
GESTOR_AI_MAX_TOOL_ROUNDS=6
GESTOR_AI_MAX_HISTORY_MESSAGES=20
GESTOR_AI_TIMEOUT_SECONDS=60
GESTOR_AI_REAL_TEST=false
```

A chave:

- permanece somente no `.env` local do servidor;
- não é incluída no `.env.example` com valor;
- não é enviada ao React;
- não aparece em `/status`;
- é ocultada do `repr` das configurações;
- não é registrada em logs.

## 6. Banco de dados e migration 14

O schema foi atualizado da versão 13 para a versão 14.

### 6.1 `ai_conversations`

Armazena:

- `id`;
- `user_id`, com FK para `usuarios` e exclusão em cascata;
- `title`, limitado a 160 caracteres úteis;
- `created_at`;
- `updated_at`.

Índice principal:

```text
idx_ai_conversations_user_updated
```

### 6.2 `ai_messages`

Armazena:

- conversa proprietária;
- papel `user` ou `assistant`;
- conteúdo;
- modelo usado;
- data de criação;
- metadados JSONB, como `request_id`, tools, rodadas e uso.

Mensagens são removidas em cascata quando a conversa é excluída.

Índice principal:

```text
idx_ai_messages_conversation_created
```

### 6.3 `ai_knowledge`

Armazena:

- tipo;
- conteúdo;
- origem;
- estado de validação;
- datas de criação e atualização.

Estados permitidos:

```text
rascunho
validado
revogado
```

Somente registros `validado` podem ser incorporados ao system prompt.

Índice principal:

```text
idx_ai_knowledge_validation
```

### 6.4 Segurança da migration

- Migration aditiva.
- Nenhum backfill produtivo.
- Nenhum evento histórico reescrito.
- Nenhuma tabela produtiva limpa ou truncada.
- Foreign keys, constraints e índices validados no PostgreSQL real de teste.
- Esperas de lock e statement continuam limitadas.
- O migrador passou a identificar e reparar versões individualmente ausentes, em vez de considerar apenas `MAX(version)`.

### 6.5 Ambiente residencial validado

```text
Container: gestor-de-pecas-postgres-1
Imagem: postgres:17-alpine
Host: 127.0.0.1
Porta publicada: 15432
Banco de teste: gestor_pecas_test_simulacao_residencia_20260824
Schema: 14
```

O uso de loopback evita depender do IP recebido em cada rede Wi-Fi. Credenciais e dados existentes foram preservados.

## 7. Endpoints HTTP

Todos os endpoints exigem usuário com acesso gerencial.

| Método | Endpoint | Finalidade |
|---|---|---|
| `GET` | `/api/v1/ai/status` | Informa se a IA está habilitada e configurada, sem expor segredo |
| `GET` | `/api/v1/ai/conversations` | Lista as conversas do usuário atual |
| `POST` | `/api/v1/ai/conversations` | Cria uma conversa; exige CSRF |
| `GET` | `/api/v1/ai/conversations/{id}` | Reabre conversa com validação de propriedade |
| `POST` | `/api/v1/ai/conversations/{id}/messages` | Envia pergunta e recebe eventos SSE; exige CSRF |

Eventos SSE utilizados:

```text
status
delta
done
error
```

O streaming da IA é independente do `RealtimeBroker`, que permanece responsável apenas pelas atualizações e invalidações de telas operacionais.

## 8. Ferramentas permitidas

| Tool | Método canônico |
|---|---|
| `get_factory_status` | `FrontendBackendFacade.andon` |
| `get_management_overview` | `FrontendBackendFacade.inicio` |
| `get_management_insights` | `FrontendBackendFacade.insights` |
| `explain_kpi` | `FrontendBackendFacade.explain_kpi` |
| `get_resource_status` | `FrontendBackendFacade.consulta_operacional`, filtrado por recurso |
| `get_sector_status` | `FrontendBackendFacade.consulta_operacional`, filtrado por setor |
| `get_production_orders` | `FrontendBackendFacade.ordens_producao` |
| `get_production` | `FrontendBackendFacade.producao_realizada` |
| `get_downtimes` | `FrontendBackendFacade.analise("paradas")` |
| `get_quality` | `FrontendBackendFacade.analise("qualidade")` |
| `get_setups` | `FrontendBackendFacade.analise("setup")` |
| `trace_work_order` | `FrontendBackendFacade.rastreabilidade` |
| `get_nestings` | `FrontendBackendFacade.nestings` |
| `get_audit_issues` | `FrontendBackendFacade.auditoria` |

Não existe resolução dinâmica com `getattr`. Nome, argumentos, campos, enumerações, datas e permissões são validados contra a whitelist.

### 8.1 Limitação de ocorrências

`get_occurrences` não foi implementada porque não foi encontrada uma fonte canônica independente de ocorrências no sistema atual. Existem apenas referências agregadas em relatórios. Criar uma tool a partir dessas referências transformaria uma inferência em regra oficial.

**Estado:** `[A DEFINIR]` até existir contrato canônico de ocorrências.

## 9. Regras industriais incorporadas

O system prompt preserva, entre outras, as seguintes regras:

- Quantidade Produzida significa somente peças boas.
- Refugo e retrabalho permanecem grandezas separadas.
- Refugo não completa a quantidade planejada da OP.
- Setup é produtivo e não reduz Disponibilidade nem Performance.
- Atividade sem OP é produtiva.
- Tempo físico do recurso não pode ser multiplicado por OPs simultâneas.
- Estados físicos incompatíveis permanecem `desconhecido`.
- Indicadores não são recalculados pelo modelo.
- Dados insuficientes permanecem explicitamente insuficientes.
- Motivo registrado não é tratado automaticamente como causa raiz.
- Prazo, meta, responsável e causa não são inventados.

Textos vindos do usuário ou do banco são tratados como dados não confiáveis e não podem substituir o system prompt ou ampliar permissões.

## 10. Histórico, memória e conhecimento

- Histórico padrão limitado às 20 mensagens mais recentes.
- Consulta preliminar busca apenas a última mensagem necessária para determinar retry e título.
- A pergunta é persistida antes da chamada ao provider.
- A resposta do assistente só é persistida após streaming completo.
- Cancelamento ou falha não grava resposta incompleta.
- Retry reutiliza a pergunta pendente sem duplicar a mensagem `user`.
- Conhecimento validado limitado a 20 registros e 12.000 caracteres no prompt.
- Cada item de conhecimento é limitado individualmente.
- Não foram adicionados embeddings, banco vetorial ou RAG nesta V1.

## 11. Segurança implementada

- Autorização gerencial em todas as rotas.
- CSRF em todos os POSTs.
- Isolamento por `user_id` em leitura, título e inserção de mensagens.
- Conversa de outro usuário retorna não encontrada.
- Chave Groq restrita ao backend.
- Tool whitelist explícita.
- Ausência de SQL e tools produtivas.
- Período máximo de 366 dias por consulta.
- Máximo padrão de seis rodadas de tools.
- Timeout de provider configurável e limitado.
- Retry do SDK limitado.
- Cancelamento assíncrono preservado.
- Saída de listas limitada a 100 itens.
- Strings e profundidade de objetos limitadas.
- Caminhos truncados informados ao modelo.
- Logs técnicos sem pergunta, resposta ou chave.
- Tratamento controlado de autenticação, rate limit, timeout, conexão e indisponibilidade.

## 12. Interface Web

A funcionalidade foi adicionada em:

```text
Tela inicial → IA
/inicio/ia
```

Não foi criada nova seção na sidebar.

A página inclui:

- lista de conversas;
- criação de conversa;
- reabertura de histórico;
- mensagens do gestor e da IA em cards industriais;
- resposta progressiva;
- status amigável durante consultas;
- cancelamento;
- tentativa novamente após falha recuperável;
- indicação do modelo;
- aviso permanente de somente leitura;
- estado desabilitado ou sem configuração.

A composição reutiliza tokens, cores, bordas, tipografia e componentes da família visual de Tela inicial. Não foi introduzida uma aparência paralela semelhante ao ChatGPT.

## 13. Correção responsiva

A inclusão da quinta sub-aba causava overflow horizontal em 1024×680 porque as abas mantinham largura mínima fixa.

Foi adicionada, somente no breakpoint necessário:

```css
.page-tab {
  min-width: 0;
  flex: 1 1 0;
}
```

Resultado medido em 1024×680:

```text
Antes: document.scrollWidth = 1158
Depois: document.scrollWidth = 1009
Viewport: 1024
Overflow horizontal: false
Largura de cada aba: aproximadamente 151 px
```

## 14. Otimizações realizadas

As otimizações foram limitadas a pontos comprováveis e não alteram lógica industrial:

1. O sanitizador de payload não copia mais dicionários e coleções inteiras antes de truncar.
2. Schemas das tools são reutilizados durante a solicitação.
3. A consulta preliminar do histórico busca somente a última mensagem.
4. O conhecimento enviado ao modelo possui limites globais e por item.
5. A criação de conversa bloqueia cliques simultâneos e duplicações acidentais.
6. O migrador repara migrations ausentes individualmente.
7. As cinco abas dividem a largura disponível no viewport mínimo.
8. A conexão com PostgreSQL local usa loopback, evitando dependência do IP do Wi-Fi.

## 15. Testes e verificações

### 15.1 Python

```text
Ran 224 tests
OK
```

Inclui testes de:

- serviço de IA;
- tool registry;
- provider Groq simulado;
- autenticação e CSRF;
- IDOR;
- streaming;
- persistência;
- retry e cancelamento;
- limites de rodadas;
- conhecimento validado;
- variáveis de ambiente;
- compatibilidade com o restante do backend.

### 15.2 PostgreSQL

Foram validados:

- criação das três tabelas;
- FKs;
- constraints;
- índices;
- UTF-8;
- isolamento de conversas por usuário;
- leitura exclusiva de conhecimento validado;
- upgrade aditivo 13 → 14;
- ausência de backfill produtivo;
- reparo de migration anterior ausente.

### 15.3 React/Vitest

```text
Test Files: 5 passed
Tests: 26 passed
```

Inclui:

- estado não configurado;
- criação de conversa;
- CSRF;
- streaming;
- erro controlado;
- retry;
- cancelamento;
- presença da sub-aba IA;
- compatibilidade das telas gerenciais existentes.

### 15.4 Build

```text
TypeScript + Vite
125 módulos transformados
Build concluído
```

O diretório `web/dist` foi regenerado.

### 15.5 Dependências e integridade

- `pip check`: nenhum requisito quebrado.
- 33 arquivos inspecionados por corrupção de Unicode.
- Nenhum caractere de substituição encontrado.
- Nenhum mojibake comum encontrado.
- Nenhuma chave com formato Groq encontrada fora do `.env`.
- `GROQ_API_KEY` permanece não configurada.

### 15.6 Validação visual

Foram verificadas no navegador:

- 1920×1061;
- 1600×900;
- 1366×768;
- 1024×680.

O fluxo visual isolado cobriu:

- login gerencial;
- abertura da sub-aba IA;
- criação de conversa;
- envio de pergunta;
- resposta em streaming simulada;
- persistência e reabertura visual;
- ausência de overflow horizontal no viewport mínimo.

## 16. Limitações e pendências

### `[NÃO VERIFICADO]` Chamada real à Groq

Nenhuma chamada real foi executada porque não há uma `GROQ_API_KEY` configurada. Consequentemente:

- nenhuma cota foi consumida;
- autenticação real da chave permanece pendente;
- latência e resposta real do modelo permanecem pendentes;
- o fluxo completo foi comprovado com provider determinístico simulado.

### `[A DEFINIR]` Ocorrências

Permanece pendente uma fonte canônica de ocorrências antes da criação de ferramenta específica.

### `[A DEFINIR]` Integração corporativa

A integração definitiva com Protheus/TOTVS continua dependente da definição da TI. A IA não altera essa fronteira e não cria dependência arquitetural nova de Qlik ou PostgreSQL como solução corporativa definitiva.

## 17. Procedimento para configurar a chave

1. Criar uma chave nova no console da Groq.
2. Não enviar a chave por chat, e-mail ou documentação.
3. Abrir o `.env` local do servidor.
4. Localizar ou criar a linha `GROQ_API_KEY=`.
5. Colar a chave imediatamente após o sinal `=`.
6. Ajustar `GESTOR_AI_ENABLED=true`.
7. Manter `GESTOR_AI_MODEL=openai/gpt-oss-120b`, salvo decisão explícita por outro modelo compatível.
8. Reiniciar o backend FastAPI.
9. Entrar com um usuário gerencial.
10. Abrir **Tela inicial → IA**.
11. Criar uma conversa e executar uma consulta controlada.
12. Confirmar streaming, tools utilizadas, persistência e ausência de erros no log.

## 18. Inventário de arquivos

### 18.1 Criados na implementação

```text
app/database/ai_repository.py
backend/ai/__init__.py
backend/ai/groq_provider.py
backend/api/dependencies/ai.py
backend/api/routers/ai.py
backend/api/schemas/ai.py
mes/ai/__init__.py
mes/ai/prompts/__init__.py
mes/ai/prompts/system_prompt.py
mes/contracts/ai.py
mes/services/ai_service.py
mes/services/ai_tools.py
docs/IA_GROQ_TESTE_MANUAL.md
tests/test_ai.py
tests/test_ai_postgres.py
web/src/api/ai.ts
web/src/pages/AIPage.tsx
web/src/test/ai.test.tsx
web/src/types/ai.ts
```

### 18.2 Modificados na implementação

```text
.env
.env.example
requirements.txt
app/database/schema.py
app/database/migrations.py
app/database/database.py
backend/api/config.py
backend/api/main.py
mes/contracts/__init__.py
tests/fakes.py
tests/web_preview_api.py
web/src/App.tsx
web/src/config/navigation.ts
web/src/styles/global.css
web/src/test/management.test.tsx
```

### 18.3 Artefatos gerados

```text
web/dist/index.html
web/dist/assets/*
```

## 19. Observações finais

- O checkout atual não possui metadados Git utilizáveis.
- Nenhum commit ou push foi executado.
- Nenhum banco operacional foi limpo ou alterado.
- A migration foi aplicada somente ao banco de teste autorizado.
- A IA permanece desabilitada até que uma chave seja adicionada localmente e `GESTOR_AI_ENABLED` seja ativado.
- A tela e as configurações de energia não foram alteradas ao final do trabalho.

## 20. Correção pós-implantação — carregamento do `.env`

Após a chave e `GESTOR_AI_ENABLED=true` serem adicionadas ao `.env`, a página ainda
apresentava a IA como desabilitada. A investigação confirmou que o arquivo estava
correto, mas o entrypoint `scripts/run_simulacao_residencia.py` usava
`dotenv_values` somente para montar o DSN do banco. As variáveis gerais da IA não
eram transferidas para o ambiente do processo. O carregamento da configuração Web
também dependia indiretamente da importação da camada de banco.

Foram aplicadas as seguintes correções:

1. `backend/api/config.py` passou a carregar explicitamente o `.env` do projeto com
   `override=False`, preservando variáveis definidas externamente.
2. `scripts/run_simulacao_residencia.py` passou a propagar todas as entradas válidas
   do `.env` para o processo sem sobrescrever variáveis já definidas.
3. O entrypoint residencial passou a usar `15432` como porta local padrão, coerente
   com o `compose.yaml` vigente.
4. Foi adicionado teste de regressão confirmando que `GROQ_API_KEY` e
   `GESTOR_AI_ENABLED` são carregadas pelo entrypoint.
5. O servidor antigo da porta 8000 foi encerrado após validação do PID e reiniciado
   pelo mesmo entrypoint.

Validação segura após a correção:

```text
FRESH_AI_ENABLED=True
FRESH_AI_CONFIGURED=True
PROVIDER_CONFIGURED=True
Servidor: http://127.0.0.1:8000
Health: ok
Fonte: postgresql_test_only
Simulação: ativa
```

Nenhuma chave foi impressa durante o diagnóstico ou gravada neste relatório.

## 21. Correção de usabilidade — envio pelo teclado

O campo de mensagem da IA passou a enviar a pergunta ao pressionar `Enter`.
Para preservar mensagens com múltiplas linhas, `Shift+Enter` continua inserindo uma
quebra de linha sem realizar o envio. O tratamento também respeita composição de
texto por IME, evitando disparos durante a composição de caracteres.

Validações executadas:

- 26 testes Web aprovados, incluindo a regressão específica do atalho;
- build TypeScript/Vite concluído com sucesso;
- teste no navegador confirmou `Shift+Enter` sem envio e `Enter` com envio e resposta;
- nenhum erro foi registrado no console do navegador;
- o servidor principal passou a servir o artefato `index-BAORkHB7.js`;
- health da API permaneceu `ok`, com PostgreSQL disponível e schema 14.

Essa alteração ficou restrita à interface do chat e não modificou regras industriais,
cálculos, persistência produtiva ou permissões.

## 22. Estabilização do tool calling e rate limit da Groq

### 22.1 Diagnóstico da falha

- **[CONFIRMADO]** O provider enviava `parallel_tool_calls=True` em toda chamada
  com tools. A API da Groq usa `true` também como default, portanto o comportamento
  paralelo estava explicitamente habilitado.
- **[CONFIRMADO]** Todas as 14 tools recebiam o mesmo conjunto de nove filtros,
  inclusive quando o handler não utilizava esses parâmetros. Os schemas completos
  ocupavam 9.151 caracteres e eram enviados em toda rodada.
- **[CONFIRMADO]** O SDK estava configurado com `max_retries=1`, permitindo retry
  automático de 429 fora da política da aplicação.
- **[CONFIRMADO]** Segundo o contrato da Groq, `tool_use_failed` significa que o
  modelo gerou uma estrutura de tool call inválida. Os três pontos anteriores
  aumentavam ambiguidade, tokens e risco de nova tentativa indevida.
- **[NÃO VERIFICADO]** O `failed_generation` da ocorrência original do Groq Console
  não foi fornecido e o teste real opt-in não foi autorizado nesta execução. Logo,
  não é possível afirmar se a geração original falhou especificamente por JSON,
  nome de tool ou argumento incompatível.

### 22.2 Captura segura de `failed_generation`

O provider passou a ler `exception.body.error.failed_generation` e formatos
equivalentes do SDK Groq 1.6.0. O log aceita somente:

- `request_id` interno;
- tipo/código técnico do erro;
- nome da tool, somente quando pertence às tools oferecidas;
- razão técnica curta e saneada;
- número da tentativa.

Argumentos tentados, mensagens, prompt, payload industrial e chave são ignorados.
No teste automático controlado, o conteúdo técnico seguro foi:

```text
error_type=tool_use_failed
tool=get_factory_status
reason=Tool call arguments are not valid JSON
attempt=1
```

Esse conteúdo foi simulado com o formato oficial de erro para validar a captura;
não é apresentado como o `failed_generation` real da ocorrência original.

### 22.3 Payload e política de tool calling

- toda chamada que fornece tools envia `parallel_tool_calls=False`;
- as rodadas com tools usam `tool_choice="auto"`;
- não existe uso genérico de `tool_choice="required"`;
- conversas simples, como `Olá` e `Quem é você?`, pulam a rodada de planejamento e
  fazem uma única chamada sem tools;
- a resposta final sem novas consultas também é solicitada com `tools=[]`;
- nenhum `response_format` ou Structured Output foi adicionado ao tool calling;
- a mensagem `assistant` que contém `tool_calls` é preservada antes de cada mensagem
  `role=tool`;
- `tool_call_id` e nome são copiados exatamente da resposta da Groq, sem reconstruir IDs.
- uma resposta anômala com mais de uma tool call é bloqueada sem executar handlers;
- uma tool registrada, mas ausente do subconjunto roteado para a pergunta, também é
  bloqueada de forma controlada.

### 22.4 Schemas simplificados

Os schemas continuam sendo objetos JSON simples com `additionalProperties=false`,
sem `oneOf`, `anyOf`, `allOf`, unions, nullable ou objetos aninhados. Cada tool agora
recebe somente os filtros usados pelo respectivo caso de uso. Exemplos:

- `get_factory_status`: nenhum argumento;
- `trace_work_order`: somente `op`, obrigatório;
- `get_resource_status`: `recurso` obrigatório e período opcional;
- `get_sector_status`: `setor` obrigatório e período opcional;
- análises: somente período e os filtros coerentes com o handler.

O conjunto completo caiu de aproximadamente 9.151 para 6.500 caracteres. A redução
principal vem do roteamento: uma pergunta de fábrica envia apenas 1.160 caracteres
de schema em vez dos 9.151 anteriores. A validação server-side no `AIToolRegistry`
permanece obrigatória: JSON inválido, tool inexistente, campo desconhecido, campo
excessivo, tipo incorreto, valor fora do enum e período inválido não executam handler.

### 22.5 Retry e rate limit

Para `HTTP 400 tool_use_failed`:

1. a primeira falha é registrada de forma segura;
2. ocorre somente uma segunda tentativa;
3. a pergunta e o subconjunto de tools são preservados;
4. a temperatura do retry fica limitada a `0.1`;
5. uma instrução curta exige JSON válido e nenhum campo adicional;
6. a segunda falha encerra com `Não foi possível consultar os dados necessários neste momento.`.

Para `HTTP 429`:

- o SDK usa `max_retries=0`;
- não há retry automático ou loop imediato;
- `retry-after`, `x-ratelimit-remaining-tokens` e
  `x-ratelimit-reset-tokens` são capturados e registrados sem conteúdo industrial;
- o provider mantém um cooldown em memória e bloqueia nova chamada externa durante
  o intervalo indicado por `Retry-After`;
- o frontend recebe `Limite temporário da IA atingido. Aguarde alguns segundos e tente novamente.`.

### 22.6 Redução de prompt e tokens

O System Prompt estável foi compactado sem remover os princípios normativos:

```text
Antes: 2.527 caracteres / 364 palavras
Depois: 2.139 caracteres / 308 palavras
Redução aproximada: 15,4% em caracteres
```

Estimativa estrutural da primeira chamada, usando aproximadamente quatro caracteres
por token e excluindo histórico, wrappers e resultados das tools:

| Intenção | Tools | Caracteres prompt + schemas | Tokens aproximados |
|---|---:|---:|---:|
| Antes, todas as tools | 14 | 11.678 | 2.920 |
| Fábrica | 3 | 3.299 | 825 |
| KPI/OEE | 5 | 4.633 | 1.160 |
| OP/rastreabilidade | 3 | 3.558 | 890 |
| Recurso/máquina | 2 | 3.048 | 760 |
| Fallback ambíguo | 2 | 2.857 | 715 |
| Conversa simples | 0 | 2.139 | 535 |

Os cerca de 3.100 tokens observados anteriormente são coerentes com a estimativa
antiga após acrescentar wrappers e a pergunta. O consumo real depois da correção
depende do histórico e do tamanho do resultado da facade; como o teste real não foi
autorizado, os números novos acima são estimativas, não métricas faturadas pela Groq.

O default configurável de `GESTOR_AI_MAX_COMPLETION_TOKENS` passou de 2.048 para 768.

### 22.7 Roteamento determinístico

Não existe chamada LLM para escolher tools. O backend normaliza o texto e seleciona
uma whitelist conservadora:

| Intenção | Tools disponíveis |
|---|---|
| fábrica/geral | `get_factory_status`, `get_management_overview`, `get_management_insights` |
| KPI/OEE | `get_management_insights`, `explain_kpi`, `get_downtimes`, `get_quality`, `get_setups` |
| OP/rastreabilidade | `trace_work_order`, `get_production_orders`, `get_production` |
| recurso/máquina | `get_resource_status`, `get_downtimes` |
| setor | `get_sector_status`, `get_management_insights` |
| nesting | `get_nestings` |
| auditoria | `get_audit_issues` |
| ambígua | `get_factory_status`, `get_management_insights` |
| conversacional simples | nenhuma |

Todas continuam read-only e delegam para a `FrontendBackendFacade`.

### 22.8 Testes e ativação

- testes focados da IA: **29 aprovados**;
- suíte Python completa: **236 aprovados**;
- testes PostgreSQL da migration 14: aprovados sem modificar migration ou schema;
- compilação Python dos arquivos alterados: aprovada;
- varredura UTF-8: aprovada;
- servidor reiniciado pelo mesmo entrypoint, PID 20300;
- health final: `status=ok`, `database=available`, `schema=14`;
- configuração ativa: IA habilitada, chave presente e máximo de 768 tokens.

Foi criado `scripts/test_groq_tool_call_real.py`. Ele não pertence à suíte automática,
exige `GESTOR_AI_REAL_TEST=true`, usa somente `TEST_DATABASE_URL` e disponibiliza
apenas `get_factory_status` na primeira chamada. Nesta execução a chave estava
presente, mas `GESTOR_AI_REAL_TEST` estava desabilitada; resultado: **SKIP**, sem
consumo real da Groq. Portanto, HTTP 200 e a sequência real de duas chamadas ainda
precisam ser confirmados numa execução explicitamente autorizada.

Nenhuma alteração foi feita em frontend, migration 14, tabelas, OEE, Disponibilidade,
Performance, FTT, rateio, saldos, estados, Andon, dashboards, autenticação,
autorização, CSRF, rastreabilidade ou regras da Engenharia de Manufatura.

## 23. Correção do HTTP 413 e compactação do resultado das tools

Esta seção registra a correção posterior ao teste real que recebeu `HTTP 413`,
`Limit: 8000 TPM` e `Requested: 9473 tokens`. Ela substitui, para o estado atual,
os números de ativação e teste real descritos no final da seção 22.

### 23.1 Confirmação do fluxo que falhou

**[CONFIRMADO PELO CÓDIGO E PELO TRACEBACK]** A primeira requisição do teste
anterior havia funcionado. O script somente alcança a atribuição
`final = await provider.complete(...)` depois de cumprir todos estes passos:

1. a primeira chamada retorna;
2. `finish_reason` é validado como `tool_calls`;
3. é validada exatamente uma tool chamada `get_factory_status`;
4. os argumentos passam por `json.loads()` e formam um objeto;
5. `get_factory_status` executa `FrontendBackendFacade.andon(...)`;
6. a mensagem `assistant` original e o resultado `role=tool` são acrescentados.

Portanto, os **9.473 tokens pertenciam à segunda requisição**, já contendo o
resultado integral da tool, e não à chamada inicial de planejamento.

### 23.2 Diagnóstico seguro do payload

Medição read-only no PostgreSQL de teste, sem registrar conteúdo industrial:

| Métrica | Antes da projeção | Depois da projeção |
|---|---:|---:|
| retorno bruto de `FrontendBackendFacade.andon` | 31.853 caracteres | não alterado na fonte |
| serialização/sanitização antiga em `role=tool` | 32.492 caracteres | — |
| mensagem `role=tool` efetivamente enviada | 32.492 caracteres | 7.126 caracteres |
| recursos existentes | 24 | 24 |
| exceções priorizadas | — | 12 |
| demais recursos | — | 12 |
| estimativa do resultado isolado | aproximadamente 8.123 tokens | aproximadamente 1.782 tokens |
| truncamento neste snapshot | não | não |

O resultado antigo da tool, sozinho, já consumia aproximadamente 8,1 mil tokens.
Somado ao System Prompt, schema, pergunta, mensagem assistant e reserva de conclusão,
ele explica o `Requested: 9473` retornado pela Groq. Nenhuma credencial, mensagem
completa ou conteúdo industrial foi escrito no log; as métricas técnicas disponíveis
são `raw_chars`, `sanitized_chars`, `items`, `estimated_tokens` e `truncated`.

### 23.3 Projeção compacta específica para IA

A `FrontendBackendFacade` e o `AndonService` não foram modificados. A nova sequência é:

```text
FrontendBackendFacade.andon (fonte canônica)
        → projeção read-only para IA
        → sanitização e limite por JSON válido
        → mensagem role=tool
        → Groq
```

A projeção não calcula, corrige, estima ou agrega nenhum valor. Ela seleciona os
campos já produzidos pelo backend. O payload compacto contém contexto/período,
resumo canônico, indicadores gerais disponíveis, recursos em atenção e demais
recursos. Para cada recurso mantém, quando existentes: setor, código do recurso,
estado, duração, OP, operação, OEE e motivo de parada.

Foram removidos da interface enviada ao modelo:

- estruturas de apresentação e layout destinadas ao React;
- `name` quando duplicava o código do recurso;
- labels e códigos de apresentação duplicados do estado;
- timestamps e propriedades internas não usadas na resposta gerencial;
- descrições extensas de produto/operação e dados repetidos da OP;
- `active_operations`, `order` e estruturas completas de renderização;
- métricas detalhadas por recurso que não pertencem à resposta compacta solicitada;
- objetos vazios, valores ausentes e unidades de apresentação redundantes.

As paradas são preservadas antes de qualquer redução. Os demais estados de atenção
(`desconhecido`, `retrabalho`, `setup` e `fila`) vêm antes dos recursos normais.
Quando o limite exige redução, o JSON permanece válido e informa `total`, `returned`
e `truncated=true`; não existe corte no meio de uma serialização.

### 23.4 Orçamento global de contexto

Foram adicionados defaults configuráveis:

```dotenv
GESTOR_AI_REQUEST_TOKEN_BUDGET=6000
GESTOR_AI_TOOL_RESULT_MAX_CHARS=10000
GESTOR_AI_MAX_COMPLETION_TOKENS=512
```

Antes de cada chamada, o orçamento considera conjuntamente mensagens, System Prompt,
schemas selecionados, resultado das tools e `max_completion_tokens`, com uma
estimativa conservadora baseada nos bytes UTF-8. O provider possui uma segunda
barreira e bloqueia localmente a requisição acima do budget antes de consumir a API.

O contexto inicial preserva, nesta ordem: System Prompt obrigatório, pergunta atual,
schemas necessários, histórico recente e conhecimento validado relevante. Histórico
e knowledge deixam de depender apenas dos limites isolados de 20 mensagens e 12.000
caracteres. Se houver redução, o modelo recebe uma nota explícita para não preencher
lacunas por inferência. Na segunda rodada, a pergunta atual, a mensagem assistant com
`tool_calls`, o resultado `role=tool` e o `tool_call_id` exato são obrigatórios; somente
o histórico antigo e knowledge adicional podem sair.

### 23.5 Tratamento separado do HTTP 413

`HTTP 413` agora é mapeado para:

```text
code=request_token_limit
retryable=false
mensagem=A consulta reuniu dados demais para o limite atual da IA.
```

Não há retry idêntico. O log seguro pode registrar apenas `request_id`, tipo técnico,
tentativa, limite e tokens solicitados extraídos da mensagem do SDK. O tratamento de
`HTTP 429` permanece separado, com cooldown e `Retry-After` quando disponível.

### 23.6 Novo teste real isolado

Execução autorizada em 25/08/2026, somente com `get_factory_status` e banco de teste:

| Etapa | HTTP | prompt_tokens | completion_tokens | total_tokens | finish_reason |
|---|---:|---:|---:|---:|---|
| primeira chamada | 200 | 625 | 36 | 661 | `tool_calls` |
| segunda chamada | 200 | 2.412 | 512 | 2.924 | `length` |

Resultado da tool no teste real:

```text
raw_chars=31853
sent_chars=7126
items=24
returned=24
truncated=false
tool=get_factory_status
arguments_json_valid=true
assistant_then_tool=true
tool_call_id_preserved=true
```

**Resultado final:** a primeira chamada solicitou a tool correta, o backend executou
a facade canônica, a segunda chamada retornou `HTTP 200` e produziu texto. A interação
inteira consumiu 3.585 tokens, menos da metade dos 8K TPM, sem depender de cache ou
upgrade. A segunda conclusão usou os 512 tokens disponíveis e terminou com
`finish_reason=length`; o texto estava presente, mas esse limite explícito deve ser
considerado ao avaliar respostas excepcionalmente longas.

### 23.7 Testes automatizados e limites preservados

- testes focados da IA: **33 aprovados**;
- suíte Python completa: **240 aprovados**;
- teste real: duas chamadas `HTTP 200`, sem entrar na suíte automática;
- regressões adicionadas para projeção compacta, exclusão do payload Web, JSON válido,
  preservação de paradas, truncamento declarado, budget de histórico/knowledge,
  preservação da sequência assistant/tool, `tool_call_id`, HTTP 413 sem retry e
  defaults 6.000/10.000/512;
- nenhuma regra industrial foi recalculada: os testes verificam que o valor canônico
  de OEE atravessa a projeção sem alteração.

Não foram modificados migration, banco, regras industriais, OEE, rateio, estados,
`FrontendBackendFacade`, Andon, autenticação, frontend ou modelo Groq.

## 24. Qualidade gerencial, Markdown seguro e UX de limite temporário

Esta seção registra a correção posterior de qualidade da resposta e da
apresentação do chat. A arquitetura de integração, o provider, o tool calling,
o roteamento, a projeção compacta, o budget e as fontes industriais não foram
alterados.

### 24.1 Arquivos alterados nesta etapa

- `mes/ai/prompts/system_prompt.py`;
- `mes/ai/prompts/__init__.py`;
- `mes/services/ai_service.py`;
- `mes/contracts/ai.py`;
- `backend/api/config.py`;
- `backend/ai/rate_limit_state.py` (novo);
- `backend/api/main.py`;
- `backend/api/routers/ai.py`;
- `web/src/components/AssistantMarkdown.tsx` (novo);
- `web/src/pages/AIPage.tsx`;
- `web/src/styles/global.css`;
- `web/src/types/ai.ts`;
- `web/package.json` e `web/package-lock.json`;
- `.env.example`;
- `docs/IA_GROQ_TESTE_MANUAL.md`;
- `scripts/test_groq_tool_call_real.py`;
- `tests/test_ai.py`;
- `web/src/test/ai.test.tsx`;
- `tests/web_preview_api.py`, somente para o preview visual isolado;
- este relatório.

### 24.2 System Prompt e qualidade da resposta

O prompt compacto passou a orientar explicitamente o modelo a:

- começar pela conclusão;
- responder como assistente gerencial industrial, e não como dump de campos;
- priorizar a principal exceção e sua evidência;
- responder perguntas simples em 3 a 8 frases e poucos parágrafos;
- não usar títulos, listas ou tabelas numa visão simples;
- omitir zeros, valores normais e enumerações sem relevância;
- não repetir a mesma evidência;
- tratar estado desconhecido como falta de informação, não falha;
- não apresentar `availability`, `reason` e `source` como estado operacional;
- não atribuir causa, impacto, meta, responsável, recomendação ou ação
  sem evidência canônica;
- não exibir segundos brutos quando a duração puder ser expressa naturalmente;
- consultar novamente dados mutáveis e usar o histórico apenas como contexto
  linguístico.

Todas as regras de segurança e Manufatura anteriormente presentes continuam no
prompt. A base estável passou de 2.139 caracteres / 308 palavras para
3.531 caracteres / 505 palavras nesta versão final, ainda significativamente
menor que o conjunto completo de schemas e dentro do budget global. O prefixo
permanece determinístico entre requisições.

Foi criada também uma instrução final curta e compartilhada entre o serviço e o
teste manual. Ela reforça a síntese depois do resultado da tool sem modificar a
sequência oficial `assistant(tool_calls) -> tool -> resposta final`.

### 24.3 Markdown seguro no chat

Mensagens da IA agora são renderizadas por `react-markdown` com `remark-gfm`.
São suportados negrito, itálico, listas, títulos discretos, tabelas, código inline
e blocos de código. Mensagens do gestor continuam sendo renderizadas como texto
comum, portanto `**texto**` digitado pelo usuário não vira formatação.

A proteção contra HTML/XSS é feita sem `dangerouslySetInnerHTML`, sem `rehypeRaw`
e com `skipHtml`. Tags `<script>`, imagens com handlers e demais HTML arbitrários
não entram no DOM nem são executados. Os testes confirmaram que os marcadores XSS
permanecem ausentes de `window`.

O CSS ficou restrito à família `.ai-markdown`: parágrafos compactos, listas
alinhadas, títulos pequenos, citação, código legível e tabela com bordas/tokens
oficiais e overflow horizontal apenas no contêiner da própria tabela. Não houve
redesign da tela. Em navegador real a página foi medida em `1024 x 680` com
`document.scrollWidth=1024` e `document.scrollHeight=680`, sem overflow global.

### 24.4 Limite temporário e consulta grande demais

O backend agora conserva um estado de cooldown da aplicação a partir do
`Retry-After` ou reset informado pelo provider. Quando esses valores não existem,
usa um fallback seguro de 30 segundos definido no backend, nunca um tempo fixo
inventado pelo React. `GET /api/v1/ai/status` publica somente:

```json
{
  "cooldown": {
    "active": true,
    "retry_after_seconds": 37,
    "blocked_until": "2026-08-25T10:56:37-03:00"
  }
}
```

Durante o cooldown:

- textarea, botão Enviar e envio por Enter ficam bloqueados;
- o texto pendente é preservado;
- nenhuma nova chamada de mensagem chega ao provider;
- histórico, troca de conversa e restante do Gestor continuam disponíveis;
- a contagem usa `blocked_until` e consulta novamente o status do backend ao zerar;
- remontagem da tela, troca de conversa ou atualização reconstroem o contador;
- um único timer é mantido;
- a explicação expansível usa linguagem comum e não cita Groq, HTTP, TPM,
  RPM, API, headers, credencial ou plano.

O erro temporário é exposto à UI como `code=rate_limit`. A consulta grande
demais continua separada como `code=request_token_limit`, `retryable=false`, não
inicia contador e orienta o gestor a perguntar por setor, recurso, OP ou indicador.
Nenhum segredo ou detalhe técnico do provider é incluído nesses contratos públicos.

### 24.5 Limite de conclusão

O default configurável passou de 512 para:

```dotenv
GESTOR_AI_MAX_COMPLETION_TOKENS=640
```

O valor foi atualizado no contrato, configuração de ambiente de exemplo e guia
manual. O provider não foi modificado. No teste real final, 640 permitiu encerrar
a resposta em 309 tokens de conclusão, com `finish_reason=stop`.

### 24.6 Testes automatizados, build e navegador

- testes focados da IA/Python: **40 aprovados**;
- suíte Python completa: **247 aprovados**;
- testes Web: **32 aprovados** em 5 arquivos;
- `npm run build`: aprovado, 379 módulos transformados;
- aviso não bloqueante existente: bundle principal acima de 500 kB;
- Markdown validado em streaming e apó a resposta final;
- Enter envia, Shift+Enter quebra linha, retry e cancelamento continuam funcionando;
- 429 bloqueia somente o compositor, preserva texto, impede nova chamada e libera
  após confirmação do backend;
- 413 não inicia timer;
- preview visual isolado validado em `1024 x 680`, sem consumir Groq;
- servidor principal reiniciado pelo entrypoint residencial e health confirmado com
  `status=ok`, banco disponível e schema 14.

### 24.7 Teste real final: "Como está a fábrica agora?"

Execução manual autorizada contra `TEST_DATABASE_URL`, com apenas
`get_factory_status` na primeira chamada e sem participação na suíte automática:

| Etapa | HTTP | prompt_tokens | completion_tokens | total_tokens | finish_reason |
|---|---:|---:|---:|---:|---|
| planejamento/tool call | 200 | 938 | 36 | 974 | `tool_calls` |
| resposta final | 200 | 2.843 | 309 | 3.152 | `stop` |
| **interação completa** | — | **3.781** | **345** | **4.126** | concluída |

Resultado da tool:

```text
raw_chars=31854
sent_chars=7127
items=24
truncated=false
arguments_json_valid=true
assistant_then_tool=true
tool_call_id_preserved=true
```

Resposta textual obtida:

> A fábrica está operando parcialmente: 12 recursos estão em produção, 1 está
> em setup, 1 está parado e 10 permanecem em estado desconhecido. O ponto de atenção
> mais evidente é a usinagem "Romi D 1000", que está parada há cerca de 27 horas
> devido à falta de material. Apesar de haver produção em vários setores, a ausência
> de indicadores de OEE – todos marcados como "dados_insuficientes" – impede avaliar a
> eficiência global. Essa limitação de dados impede confirmar se há outros gargalos
> ou perdas não visíveis no momento.

**[CONFIRMADO]** Foram quatro frases, sem tabela, sem dump de zeros, sem enumeração
de todas as máquinas, com conclusão primeiro, principal exceção e limitação de
dados. O OEE não foi recalculado: o backend retornou `dados_insuficientes`. Os 10
estados desconhecidos foram tratados como lacuna de visibilidade, não como dez
máquinas com problema.

Durante a instrumentação manual houve execuções anteriores que completaram as
chamadas reais, mas revelaram duas falhas exclusivas do script de relatório
(`tool_call_id` buscado após a instrução final e console Windows em CP-1252). O
script foi corrigido para manter referência explícita à mensagem `role=tool` e
saída UTF-8. Uma iteração intermediária também mostrou resposta longa e uma
recomendação indevida; esse achado endureceu o contrato textual antes do resultado
final acima. Nenhuma dessas correções tocou o provider ou as tools.

### 24.8 Escopo preservado

**[CONFIRMADO]** Não foram alterados `GroqProvider`, schemas/registro/seleção ou
execução de tools, `parallel_tool_calls`, `tool_choice`, projeção compacta, token
budget, `FrontendBackendFacade`, `AndonService`, migrations, tabelas, PostgreSQL,
autenticação, autorização, CSRF, OEE, Disponibilidade, Performance, FTT, rateio,
estados, saldos ou qualquer regra da Engenharia de Manufatura. A nova classe de
cooldown apenas traduz para o contrato HTTP/UI o tempo já informado pelo backend e
não modifica a política de rate limit do provider.
