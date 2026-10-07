# Auditoria de segurança do backend — 2026-10-07

Responsável: `application-security-engineer` (IA Workforce). Tipo: auditoria **somente leitura**.
Nenhum código, `.env`, banco ou serviço foi alterado. Esta auditoria não repete o que já foi coberto antes:
bandit, pip-audit, freio de login, IDOR da Qualidade, session secrets, base_url da IA e X-Forwarded-For do freio.

Legenda:
- **[Certo]**: o caminho foi confirmado lendo o código.
- **[Provável]**: inferência sólida que não foi reproduzida em execução.
- Correção: **"mínima"** significa "mínima e segura de aplicar com teste". **"decisão"** significa "precisa de decisão do usuário".

---

## Achados

### A1. Médio — `POST /management/badges/{id}/telegram-link-code` sempre devolve 500 (controle de segurança inutilizável) [Certo]

- **Arquivo:** `backend/api/routers/management.py:380`
  ```python
  result = database.gerar_codigo_vinculo_telegram(operator_id, criado_por=user.username)
  ```
- **Causa:** `SessionUser` (`backend/api/schemas/auth.py`) não tem o campo `username`. Os campos são `id`, `name`, `role`, `management_access`, `andon_access`, `operator_access`, `operator_sector`, `operator_resources` e `operator_automatic_queue`. A dependência devolve um `SessionUser`, então a linha levanta `AttributeError` e o handler genérico responde 500.
- **Cenário:** o gestor tenta gerar o código de vínculo do Telegram de um crachá e recebe "erro interno" toda vez. O vínculo seguro por código, criado na auditoria de 01/10, não pode ser usado. Na prática, isso empurra o processo para um vínculo manual ou informal.
- **Evidência adicional:** nenhum teste em `tests/` referencia `telegram-link-code`. Por isso o CI não pegou.
- **Correção mínima:** trocar para `criado_por=user.name` e adicionar um teste de rota que gere o código e confira o 200.
- **Aplicação:** mínima.

### A2. Médio/Baixo — Erro bruto do SigmaNEST/pyodbc exibido na tela do operador do Corte [Certo no caminho, Provável no conteúdo]

- **Arquivos:**
  - `mes/services/sigmanest_refresh.py:119`
  - `backend/api/routers/cutting.py:151`
  ```python
  self.state.ultimo_erro = str(erro)[:300]          # sigmanest_refresh.py:119
  "erro": estado.get("ultimo_erro"),                 # cutting.py:151 (_sync_state)
  ```
- **Caminho:** `_sync_state` entra no payload de `/cutting/queue` e de `/cutting/sync`, que são rotas de operador.
- **Cenário:** quando a conexão ODBC ao SQL Server do SigmaNEST falha, os primeiros 300 caracteres da exceção do driver vão para o navegador do terminal do Corte. Esse texto normalmente contém servidor\instância, nome do banco, usuário de login e às vezes trecho de SQL. Qualquer pessoa com a conta do setor Corte, ou com o DevTools aberto num terminal compartilhado, vê a topologia do SQL Server de produção.
- **Correção mínima:**
  1. Em `_sync_state` da rota de operador, devolver só `MENSAGEM_ERRO` (constante já existente na mesma classe, linha 108) ou um código fixo.
  2. Manter o texto bruto apenas em `/cutting/sync/diagnostico` (gestão) e no log.
- **Aplicação:** mínima, com teste que simule a falha e confira que o payload de operador não contém o texto da exceção.

### A3. Baixo/Médio — Race TOCTOU em `definir_template` da Qualidade: primeira definição concorrente sobrescreve a outra sem permissão de edição [Certo]

- **Arquivos:**
  - `mes/services/quality.py:601-628`: o serviço faz `existente = buscar_template_qualidade(produto)` e só recusa se `existente is not None and not pode_editar`.
  - `app/database/quality_repository.py:397`: o repositório faz `INSERT ... ON CONFLICT ON CONSTRAINT uq_qualidade_template_produto DO UPDATE`.
  - `app/database/quality_repository.py:430`: mesmo padrão nas cotas, com `ON CONFLICT ... uq_qualidade_cota_sequencia DO UPDATE`.
- **Cenário:** dois operadores sem permissão de edição cadastram as cotas do mesmo produto "pela primeira vez" quase ao mesmo tempo. Os dois leem `existente = None` e os dois gravam. O segundo `DO UPDATE` sobrescreve as cotas do primeiro. A regra "só Supervisor/Líder/Qualidade altera o padrão" fica contornada. A janela é estreita, mas o efeito é um padrão de inspeção errado gravado em silêncio.
- **Correção mínima:** quando o chamador não tem `pode_editar`, usar `ON CONFLICT DO NOTHING RETURNING id` e devolver conflito (409) se nenhuma linha voltar. Alternativa: `SELECT ... FOR UPDATE` dentro da mesma transação.
- **Aplicação:** mínima, com teste de duas gravações sequenciais simulando a corrida (a segunda sem permissão deve receber 409).

### A4. Baixo — OpenAPI e Swagger UI expostos sem autenticação [Certo no código, Provável no impacto em produção]

- **Arquivo:** `backend/api/main.py:839-840`
  ```python
  docs_url="/api/docs",
  openapi_url="/api/openapi.json",
  ```
- **Cenário:** qualquer pessoa que alcance o host consegue listar o mapa completo da API, com todas as rotas, parâmetros, schemas e nomes de papéis. Isso não dá acesso direto, mas encurta o reconhecimento de um atacante na rede da fábrica ou via hostname publicado. Não confirmei se alguma configuração desliga essas rotas em `production`.
- **Correção mínima:** usar `docs_url=None` e `openapi_url=None` quando `GESTOR_WEB_ENV=production`, ou exigir sessão de gestão. Schemathesis e o CI usam o schema, então manter as rotas no `test`.
- **Aplicação:** decisão (o fluxo de Schemathesis/CI depende do schema).

### A5. Baixo/Médio — `POST /chamadas` sem limite por usuário: spam de Telegram para contatos [Certo]

- **Arquivo:** `backend/api/routers/chamadas.py:119` (`criar_chamada`). Exige apenas `get_current_user` + CSRF.
- **Cenário:** um usuário autenticado qualquer (inclusive conta de setor num terminal compartilhado) roda um loop e dispara centenas de mensagens Telegram para a gestão e os contatos. O resultado é ruído, possível bloqueio do bot pela API do Telegram e chamadas legítimas perdidas no meio.
- **Correção mínima:** um rate limit por usuário (ex.: N chamadas a cada X minutos), reaproveitando o padrão de `ai_user_rate_limit`.
- **Aplicação:** decisão (limite numérico e se vale para operador).

### A6. Baixo — Política de senha mínima de 6 caracteres [Certo]

- **Arquivo:** `backend/api/schemas/common.py:122`
  ```python
  senha: str | None = Field(default=None, min_length=6, max_length=256)
  ```
- **Cenário:** um admin cria contas de gestão com senha de 6 caracteres. O freio de login atrasa a adivinhação online, mas um vazamento do hash, mesmo com PBKDF2 600k, cai rápido em senhas curtas.
- **Correção:** subir para 8 ou 10 ao menos nos níveis de gestão/admin.
- **Aplicação:** decisão (afeta contas de setor do chão de fábrica, ver regra "simplicidade no chão de fábrica").

### A7. Baixo — Parâmetros de path/query sem `max_length` [Certo]

- **Onde:**
  - `op` em `/operator/operations/{op}` e `/operations/{op}/sync` (`backend/api/routers/operator.py`).
  - `task_code` em `backend/api/routers/highlight.py`.
  - `/traceability/orders/{op}`.
  - `q` e `setor` em `/chamadas/contatos`.
  - `recipient`, `alert_type`, `op`, `sector` e `status` em alertas internos e primeira peça (`management.py`).
  - Parâmetros de DELETE e histórico de tempo padrão.
  - `ChamadaContatoRequest.setores` (`common.py:139`), sem limite de itens nem de tamanho por item.
- **Cenário:** strings de vários KB vão parar em `ILIKE`/`=` no PostgreSQL. O impacto é só custo de consulta e de log, não injeção, porque as consultas são parametrizadas. O `BodySizeLimit` não cobre a query string.
- **Correção mínima:** `Path(max_length=60)` / `Query(max_length=120)` seguindo o padrão já usado em `analytics_filter`, e `Field(max_length=20)` + item `constr(max_length=80)` em `setores`.
- **Aplicação:** mínima.

### A8. Baixo — Corte: `appointment_id` do "Finalizado" não é amarrado ao `resource` enviado [Certo]

- **Arquivo:** `mes/services/cut.py:248-254`. `finalizar(apontamento_id)` procura em `self.listar_fila()` sem filtrar pela máquina de `payload.resource`.
- **Cenário:** um operador no terminal do Plasma finaliza, por ID, um apontamento em processo do Laser. Não há escalada de privilégio, porque a conta do setor Corte já é dona das duas máquinas. É um problema de integridade do apontamento, não de acesso.
- **Correção mínima:** filtrar a fila pelo recurso recebido antes de procurar o ID.
- **Aplicação:** mínima.

### A9. Baixo — Mensagens de exceção técnicas em superfícies restritas [Certo]

- `backend/api/routers/system.py:157`: `/system/rebuild-frontend` devolve os últimos 4000 caracteres do `npm run build`, com caminhos absolutos do servidor. Só admin + CSRF.
- `backend/api/routers/dev_observatory.py:143`: `AppError("dev_observatory_real_unavailable", str(exc), 503)` devolve a exceção bruta da conexão ao REAL (host/usuário). Só para a sessão do Dev Observatory, e a rota é bloqueada no host público.
- `dev_observatory.py:319` e `:522`: `"error": str(exc)` no status/relatório. Mesma restrição.
- `dev_observatory.py:673`: `f"Backend indisponível: {exc}"` na página. Sai antes da autenticação, mas a mensagem é escapada (`html.escape`) e só cai aqui em exceção não-AppError.
- **Correção:** opcional. O risco é baixo pelo público restrito. No item 673, trocar por mensagem fixa e logar `exc`.
- **Aplicação:** mínima.

---

## Top 5 priorizado

1. **A1:** `user.username` → `user.name` + teste. É um bug real que hoje desliga o vínculo seguro do Telegram. Cerca de 10 min.
2. **A2:** tirar o texto bruto do SigmaNEST do payload do operador. Cerca de 20 min com teste.
3. **A3:** `ON CONFLICT DO NOTHING` + 409 para quem não pode editar o template. Cerca de 30 min com teste.
4. **A5:** rate limit em `POST /chamadas`. Precisa decisão do limite. Cerca de 30 min depois de decidido.
5. **A7:** `max_length` nos path/query params listados. Mecânico, cerca de 30 min.

A4 (docs em produção) e A6 (senha mínima) dependem de decisão do usuário.

---

## Verificado e OK

- **Autenticação/autorização:**
  - Todas as rotas lidas usam a dependência de papel adequada. O nível admin cobre usuários, contatos, calendário e parâmetros de turno; a gestão cobre leitura e pausas; operador e Destaque são amarrados ao setor por `validate_resource`. Tempo padrão e Qualidade usam guardas próprias.
  - `get_current_user` recarrega o usuário do banco a cada request e confere `ativo` e `session_version`. Logout, troca de senha, nível e desativação revogam a sessão.
  - `save_user` impede o admin de se auto-rebaixar ou desativar.
- **CSRF / cookies:**
  - Double-submit com `hmac.compare_digest`, conferindo header e cookie contra a claim assinada.
  - CSRF presente em todas as rotas mutantes lidas (POST/PUT/DELETE de management, operator, cutting, highlight, quality, chamadas, ai, reports, system, logout). Nenhuma rota GET mutante foi encontrada.
  - Cookie de sessão `HttpOnly`, `SameSite=strict` e `Secure` conforme `cookie_secure`. O cookie CSRF não é HttpOnly, de propósito.
  - O Dev Observatory tem signer, cookie e CSRF próprios, confere a claim de papel (impede reuso do cookie principal se os segredos coincidirem), tem freio de login persistente com prefixo próprio, comparação de credencial em tempo constante sobre bytes UTF-8, e bloqueio no host público.
  - Login principal e login do observatório são POST sem CSRF. É aceitável com `SameSite=strict` + JSON.
- **Cabeçalhos:** nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, Permissions-Policy, HSTS com `cookie_secure`, e CSP com `script-src 'self'`. Também TrustedHost e BodySizeLimit.
- **Erros:**
  - O handler genérico de 500 devolve mensagem fixa e `DatabaseError` devolve 503 fixo. A IA devolve só `user_message`. O SOAP TOTVS loga e devolve uma falha fixa em exceção não prevista.
- **Path traversal:**
  - Desenhos: `DrawingLookupService` resolve o produto pelo banco e só varre as raízes configuradas.
  - Upload da Qualidade: nome sanitizado por `[^A-Za-z0-9._-]+`, magic bytes de PDF conferidos, teto de 20 MB.
  - `/dev-observatory/reports/{name}`: confere `base in target.parents`.
- **SSRF:**
  - O pull de OP sob demanda usa o endpoint fixo de env, com a OP no corpo JSON.
  - O `base_url` da IA está fora do escopo (já auditado).
- **XML / SOAP TOTVS:**
  - `defusedxml` no envelope (`totvs_soap.py:124`), no parser de negócio (`mes/integrations/totvs/parser.py:137`) e no ACK de saída (`outbound_ack.py:41`). DOCTYPE/ENTITY são recusados antes do parse, e o tamanho é limitado durante o streaming do corpo.
  - Allowlist de CIDR sobre `request.client.host`. Atrás do nginx (`deploy/nginx.conf`: `X-Forwarded-For $remote_addr`, que sobrescreve e não concatena) com uvicorn no padrão `forwarded_allow_ips=127.0.0.1`, o peer efetivo é o IP real. Fail-closed sem allowlist. Recusa no host público.
  - Respostas e falhas escapam o conteúdo com `escape`.
- **Injeção em saídas:**
  - Telegram: HTML escapado em `TelegramPresenter`.
  - CSV de relatórios: `safe_text` previne fórmula.
  - `Content-Disposition` de relatórios: o `report_type` é validado contra `REPORT_TYPES` no schema e na facade (`ReportError`). Download de desenho: nome sanitizado no upload.
- **SQL:** as f-strings vistas nos repositórios lidos (contatos, qualidade) interpolam só listas de colunas constantes; os valores vão parametrizados. Os `ILIKE` não escapam `%`/`_`, mas isso é coringa, não injeção.
- **Isolamento de dados:**
  - Conversas de IA e artefatos de relatório são filtrados por `user.id`, e `report_id` tem tamanho fixo.
  - `/chamadas/contatos` não devolve `telegram_chat_id` (lista de colunas fixa).
- **Validação Pydantic:** os modelos de request usam `extra="forbid"` com limites de tamanho. `analytics_filter` limita strings, datas, período (366 dias) e paginação (200).

- **SQL dinâmico (varredura completa de `app/`, `mes/`, `backend/`):**
  - Nenhum `execute(f"...")`, `.format(` ou `%` com dado externo.
  - Todos os blocos `f"""` de `app/database/` interpolam apenas:
    - constantes de módulo (`OUTBOX_COLUMNS`, `SYNC_REQUEST_COLUMNS`, `PROTHEUS_TIME_SQL`, `ESTADO_RECURSO_INTERVALO`, `SESSAO_RECURSO_INTERVALO`);
    - alias fixo (`_corte_concluido_sql("operacao"|"anterior")`, `database.py:1782/1830`);
    - fragmentos montados com `%s` (`join_clause`, `database.py:5266-5277`; `status_clause`, `database.py:6099-6101`);
    - allowlist (`timestamp_field`, `database.py:6073`).
  - `backend/observability/metrics.py:129` interpola o nome de tabela vindo de uma tupla constante.
- **Health:** `/system/health` e `/system/ready` (`backend/api/database.py:47-71`) devolvem só `status`, `database` e `schema_version`. A exceção vai apenas para o log.
- **Vínculo Telegram por código** (`app/database/database.py:5785`): consumo atômico (`FOR UPDATE OF codigo, operador` + `usado_em IS NULL` + expiração), freio de tentativas por chat persistido e hash do código. Recusa a troca silenciosa de vínculo.
- **Config de produção** (`backend/api/config.py:437-442`): `cookie_secure` vale `True` por padrão quando `GESTOR_WEB_ENV=production`. `allowed_hosts` tem allowlist explícita. O nginx (`deploy/nginx.conf:20-28`) redireciona 80→443, com TLS 1.2/1.3.

## Não coberto nesta rodada (pendente)

- Corridas em início/fim de apontamento (FOR UPDATE/advisory lock) e em `criar_usuario` (unique em `usuario`).
- `mes/integrations/totvs_wspcp.py` e o cliente SQL do SigmaNEST (`sigmanest_sqlserver.py`) não foram relidos linha a linha. A varredura de `execute(f"...")` acima não achou interpolação neles.
