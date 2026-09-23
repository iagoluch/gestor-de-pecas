# IA Industrial com Groq — teste manual

## Limites desta V1

A IA é exclusivamente gerencial e read-only em relação ao MES. As únicas escritas são `ai_conversations` e `ai_messages`; `ai_knowledge` fica preparada para conhecimento administrado e validado, sem endpoint público de escrita. Não existem tools de SQL, apontamento, alteração de quantidade, finalização ou controle de máquina.

## Configuração local

1. Gere uma chave nova no console da Groq.
2. Abra o `.env` local do servidor. Não coloque a chave em código, React, `.env.example`, log ou mensagem de chat.
3. Localize ou crie a linha `GROQ_API_KEY=` e cole a chave imediatamente após o sinal `=` apenas no `.env` local.
4. Acrescente ou ajuste as demais opções:

   ```dotenv
   GESTOR_AI_ENABLED=true
   GESTOR_AI_MODEL=openai/gpt-oss-120b
   GESTOR_AI_REASONING_EFFORT=medium
   GESTOR_AI_TEMPERATURE=0.2
   GESTOR_AI_MAX_COMPLETION_TOKENS=640
   GESTOR_AI_REQUEST_TOKEN_BUDGET=6000
   GESTOR_AI_TOOL_RESULT_MAX_CHARS=10000
   GESTOR_AI_MAX_TOOL_ROUNDS=6
   GESTOR_AI_MAX_HISTORY_MESSAGES=20
   GESTOR_AI_TIMEOUT_SECONDS=60
   GESTOR_AI_REAL_TEST=false
   ```

5. Confirme que a URL de banco usada pelo backend aponta para o ambiente autorizado. Nesta máquina, o PostgreSQL do Docker publica a porta `15432`; em Wi-Fi diferente, prefira `127.0.0.1` quando backend e Docker rodam no mesmo computador.
6. Instale/atualize as dependências e inicie o backend pelo procedimento normal do projeto. A inicialização aplica a migration 14.
7. Entre com um usuário gerencial.
8. Abra **Tela inicial → IA** (`/inicio/ia`).
9. Crie uma conversa e pergunte: `Como está a fábrica agora?`

Ao alterar `GROQ_API_KEY` ou `GESTOR_AI_ENABLED`, reinicie o backend. O entrypoint
`scripts/run_simulacao_residencia.py` carrega essas variáveis diretamente do `.env`;
uma instância iniciada antes da alteração continua com a configuração antiga até ser
reiniciada.

Para conferir sem imprimir a chave:

```powershell
C:\Python314\python.exe -c "from backend.api.main import app; s=app.state.settings; print(s.ai_enabled, s.ai_configured)"
```

O resultado esperado após configurar e reiniciar é `True True`.

## Teste real isolado de tool calling

Esse teste é manual, usa somente o banco indicado por `TEST_DATABASE_URL` e não
faz parte da suíte automática. Ele só consome a Groq quando a autorização
explícita estiver ativa:

```powershell
$env:GESTOR_AI_REAL_TEST = "true"
C:\Python314\python.exe scripts\verificar_groq_tool_call_real.py
```

O primeiro passo disponibiliza exclusivamente `get_factory_status`; o script
valida a tool call, executa a facade canônica, preserva a sequência
`assistant(tool_calls) → tool` e solicita a resposta final. Remova a variável de
processo ao terminar se não quiser autorizar novos testes reais.

## Conferências

- Pressionar `Enter` no campo envia a mensagem; `Shift+Enter` insere uma quebra de linha sem enviar.
- A resposta aparece progressivamente.
- A interface mostra mensagens amigáveis como `Consultando produção…`, sem nomes internos de tools.
- A conversa permanece ao fechar e reabrir a página.
- Perguntas sobre KPI usam `FrontendBackendFacade.insights`/`explain_kpi`; os cálculos não são refeitos pelo modelo.
- Perguntas sobre OP usam a rastreabilidade canônica.
- Outra conta gerencial não consegue abrir a conversa alterando o ID da URL.
- Desativar `GESTOR_AI_ENABLED` ou remover a chave não impede login, operador, Andon ou telas gerenciais; a aba informa que a IA está desabilitada/não configurada.
- Nenhum evento, quantidade, OP, estado de recurso ou outra tabela produtiva é alterado pela consulta.

## Testes automáticos

Os testes usam provider simulado e não consomem quota da Groq. A migration 14 deve ser validada somente com `TEST_DATABASE_URL` apontando para banco cujo nome contenha `test`.
