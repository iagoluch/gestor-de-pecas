# Auditoria de segurança — Gestor de Peças (ambiente TESTE)

**Data:** 2026-09-14
**Escopo:** OWASP Top 10 aplicado ao stack FastAPI/Python + React/TS + PostgreSQL.
**Método:** revisão de código nos pontos de entrada de dado externo e nos
mecanismos de segurança, mais provas dinâmicas pontuais executadas *in-process*
(FastAPI `TestClient`, banco falso). Nenhuma requisição saiu da máquina, nenhum
host externo foi tocado, o banco REAL (`gestor_pecas`) não foi acessado e nada
foi enviado ao TOTVS ou ao SigmaNEST. Sem força bruta, sem carga, sem
ferramenta ofensiva.

## Placar

| Severidade | Achados | Corrigidos | Documentados |
|---|---|---|---|
| Crítico | 1 | 1 | 0 |
| Alto | 2 | 1 | 1 |
| Médio | 4 | 2 | 2 |
| Baixo | 4 | 1 | 3 |
| Informativo | — | — | ver seção final |

---

## CRÍTICO

### C1 — Receptor SOAP do TOTVS, sem autenticação, exposto na internet pelo túnel

**OWASP:** A01 Broken Access Control / A05 Security Misconfiguration
**Local:** `backend/integrations/totvs_soap.py:178` (`POST /PcfIntegService`) e
`:159` (`GET /PcfIntegService`, WSDL)
**Status: CORRIGIDO**

`POST /PcfIntegService` não possui dependência de autenticação alguma: os
únicos gates eram `totvs_soap_enabled` e o cabeçalho `SOAPAction`. Uma mensagem
aceita chega a `TotvsIngestionService.handle_message` → `ingest`, que **grava a
OP no banco e commita** — o próprio código documenta que o 200 só existe depois
disso (`mes/integrations/totvs/service.py:139`).

Isoladamente isso é o contrato do EAI do Protheus, que fala com o Gestor pela
rede interna. O que transforma em crítico é a combinação com a publicação
externa:

- `iniciar_sistema_teste_cloudflare.py:751` sobe um *quick tunnel* do
  Cloudflare, grava o hostname em `GESTOR_WEB_PUBLIC_HOST` e o acrescenta a
  `GESTOR_WEB_ALLOWED_HOSTS` (`:760`);
- o `.env` atual já traz esse hostname em ambos, e
  `GESTOR_TOTVS_SOAP_ENABLED=true` com `GESTOR_TOTVS_ENABLED=true`.

Resultado: enquanto o túnel estiver de pé, qualquer pessoa que alcance a URL
pública injeta ou altera Ordem de Produção no banco, sem credencial. O WSDL
público (`GET /PcfIntegService`) ainda entrega o contrato pronto para montar a
mensagem.

**Prova (in-process, sem rede):** mesma requisição, dois `Host`:

```
[C1] LAN     (Host: testserver)                          -> 200
[C1] PUBLICO (Host: dod-road-matches-clusters...com)     -> 200
```

**Correção aplicada.** A porta do ERP passa a existir só no caminho interno.
`_arrived_through_public_host` (`backend/integrations/totvs_soap.py:30`) compara
o host da requisição com `GESTOR_WEB_PUBLIC_HOST` e recusa com `403`
(`totvs_soap_internal_only`) no `POST` e no WSDL. A recusa acontece **antes de
ler o corpo**.

Escolhida por ser a menor mudança que fecha o buraco sem tocar no contrato com o
Protheus: o TOTVS fala com o Gestor pelo IP da LAN (`10.10.1.248`), que continua
aceito. Quando `GESTOR_WEB_PUBLIC_HOST` é um nome interno
(`gestor-peca`, `localhost`, `127.0.0.1`, `testserver`, `::1` — lista em
`_INTERNAL_PUBLIC_HOSTS`), **nada é bloqueado**: sem túnel, o comportamento é
idêntico ao de antes.

**Depois da correção:**

```
POST pelo túnel público      -> 403
GET  WSDL pelo túnel público -> 403
POST pelo IP da LAN          -> 200
GET  WSDL pela LAN           -> 200
sem túnel, host da fábrica   -> 200
```

Regressão fixada em
`tests/test_totvs_integration.py::TotvsSoapContractTests::test_receptor_nao_responde_pelo_hostname_publicado`
e `::test_sem_hostname_publicado_a_rede_interna_nao_muda`.

> **Recomendação adicional (não aplicada):** defesa em profundidade seria não
> publicar `/PcfIntegService` no túnel (regra no proxy) e exigir mTLS ou segredo
> compartilhado no enlace TOTVS↔Gestor. O bloqueio por host resolve a exposição
> atual, mas continua sendo um controle de rede, não de identidade.

---

## ALTO

### A1 — Login do Dev Observatory sem freio de tentativa

**OWASP:** A07 Identification and Authentication Failures
**Local:** `backend/api/routers/dev_observatory.py:210`
**Status: CORRIGIDO**

Uma única credencial (`GESTOR_DEVOBS_LOGIN_USERNAME` / `_PASSWORD`) guarda uma
ferramenta que expõe stack trace completo, catálogo do PostgreSQL e **leitura do
ambiente REAL**. Não havia contagem de falhas, atraso ou bloqueio: tentativas
ilimitadas, e o endpoint é alcançável pelo mesmo túnel público do C1. A senha
configurada hoje é uma senha humana curta.

**Prova (5 tentativas, in-process — não é força bruta, é a demonstração de que
não existe contador):**

```
[A1] 5 tentativas erradas seguidas -> [401, 401, 401, 401, 401]
[A1] senha correta logo depois     -> 200 (sem bloqueio)
```

**Correção aplicada.** Freio por IP de origem, em processo, sem dependência
nova: `LOGIN_MAX_FAILURES = 5` falhas abrem `LOGIN_LOCKOUT_SECONDS = 300` s de
bloqueio com `429` (`dev_observatory_login_blocked`). Durante o bloqueio nem a
senha correta passa — o freio não pode virar oráculo de senha certa. Um login
bem-sucedido zera o contador.

A janela é deslizante: cada falha descarta antes as entradas já vencidas, o que
mantém a tabela limitada num processo de longa duração e impede que falhas
separadas por horas somem como se fossem seguidas.

**Limitação conhecida, deliberada:** atrás do túnel Cloudflare todas as
requisições chegam com o mesmo IP de origem, então o bloqueio é efetivamente
global. Para uma ferramenta de um único desenvolvedor isso é aceitável — e é o
comportamento seguro — mas significa que alguém na LAN pode trancar a
ferramenta por 5 minutos. Se incomodar, o caminho é aumentar
`LOGIN_MAX_FAILURES` ou reduzir a janela; não remover o freio.

Regressão fixada em
`tests/test_dev_observatory.py::DevObservatoryApiTests::test_login_trava_depois_de_tentativas_seguidas_e_aceita_senha_nao_ascii`.
O `setUp` da classe passou a limpar `_login_failures`, senão as recusas somadas
de um teste travariam o login do seguinte.

### A2 — Login principal do Gestor também não tem freio de tentativa

**OWASP:** A07 Identification and Authentication Failures
**Local:** `backend/api/routers/auth.py:30`, `app/database/database.py:220`
**Status: DOCUMENTADO — precisa de decisão sua**

`POST /api/v1/auth/login` chama `autenticar_usuario` direto, sem contador de
falhas, sem atraso e sem bloqueio de conta, e está publicado no mesmo túnel. O
hash é forte (PBKDF2-SHA256, 600 000 iterações — ver A-positivos), o que já
encarece muito a adivinhação, mas não substitui um freio.

**Por que não corrigi junto com a A1:** travar o login do Gestor é decisão
funcional com impacto de chão de fábrica. Um operador que erra a senha três
vezes num terminal compartilhado não pode ficar impedido de apontar produção.
Escolher entre bloqueio por conta, por IP, atraso progressivo ou nada é sua
chamada, não minha.

**Sugestão quando decidir:** atraso progressivo por IP+usuário (0 s, 1 s, 2 s,
4 s…, com teto de ~8 s) em vez de bloqueio. Encarece a adivinhação em ordens de
grandeza e nunca deixa um operador legítimo fora do terminal. O mesmo padrão de
`_login_failures` do Dev Observatory serve de base.

---

## MÉDIO

### M1 — IDOR entre setores na Qualidade: escrita não revalida o setor de origem

**OWASP:** A01 Broken Access Control
**Local:** `mes/services/quality.py:650` (`registrar_peca`), `:870`
(`finalizar_inspecao`), `:525` (`obter_inspecao`); rotas em
`backend/api/routers/quality.py:175`, `:199`, `:170`
**Status: CORRIGIDO** (migração 30 + `_exigir_setor`; ver "Correção aplicada"
ao final desta seção)

O domínio trata o recorte por setor como regra explícita: `abrir_inspecao`
recusa OP de outro setor com o comentário *"Digitar a OP não contorna o recorte
de setor: quem inspeciona é quem produziu a peça"* (`mes/services/quality.py:282`),
via `_pertence_ao_setor`. `listar_fila` e `listar_historico` também filtram.

**As rotas de escrita não repetem essa checagem.** `registrar_peca` e
`finalizar_inspecao` buscam a inspeção só pelo `id`
(`buscar_inspecao_qualidade` → `SELECT * FROM qualidade_inspecoes WHERE id = %s`)
e validam apenas status, sequência e template. No roteador, `_sector(user)` é um
gate de *papel* ("seu nível tem Qualidade habilitada?"), não de *recurso*.

Com três setores habilitados (`QUALITY_ENABLED_SECTORS = ("Dobra", "Usinagem",
"Serra")`, `app/core/quality.py:23`), um operador de Dobra pode, trocando o
`inspecao_id` na URL, registrar cotas, marcar não conformidade, abrir RNC e
finalizar uma inspeção de Usinagem ou Serra. A fronteira que o domínio garante
na abertura é contornável na escrita.

**Reprodução (não executada — exigiria escrever dado de inspeção real):**
autenticar como operador de Dobra, `POST
/api/v1/quality/inspections/{id}/pieces` com um `inspecao_id` aberto por
Usinagem.

**Por que não corrigi:** a linha `tipo_setor` de `qualidade_inspecoes` guarda
`QUALITY_APPOINTMENT_SECTOR` ("Qualidade"), **não** o setor de origem — o
`tipo_setor_origem` que `_pertence_ao_setor` lê vive na operação elegível, não na
inspeção. Reconstruí-lo a cada peça a partir de `listar_ops_elegiveis_inspecao()`
seria um scan por peça e, pior, daria falso negativo: depois da inspeção aberta
a OP pode já não constar dessa lista, e a guarda passaria a **bloquear o
operador certo**. A correção correta é uma migração, e migração sem git num
sistema que atende o chão de fábrica não é coisa para aplicar de surpresa.

**Correção recomendada (3 passos, nesta ordem):**

1. migração: `ALTER TABLE qualidade_inspecoes ADD COLUMN tipo_setor_origem TEXT`,
   preenchendo o histórico a partir de `catalogo_operacoes_op`;
2. `abrir_inspecao` grava `tipo_setor_origem=_texto(elegivel.get("tipo_setor_origem"))`
   junto com o resto (`mes/services/quality.py:299`);
3. um único helper privado no serviço — `_exigir_setor(sessao)` — comparando
   `sessao["tipo_setor_origem"]` com `quality_sector_for_user_level(self.nivel)`,
   chamado no topo de `registrar_peca`, `finalizar_inspecao` e `obter_inspecao`.
   Uma fonte de verdade, três chamadas; linhas antigas sem
   `tipo_setor_origem` permanecem visíveis a todos os setores, igual ao que
   `_pertence_ao_setor` já faz hoje.

**Correção aplicada (2026-09-14), exatamente nos três passos acima:**

* migração **30** (`QUALITY_SECTOR_OWNERSHIP_STATEMENTS`, `SCHEMA_VERSION = 30`):
  `qualidade_inspecoes.tipo_setor_origem TEXT` anulável, com backfill do
  histórico pela mesma regra da fila (última etapa apontável do roteiro antes
  da inspeção, via `catalogo_operacoes_op`);
* `abrir_inspecao` e `dispensar_inspecao` gravam a origem na sessão; o
  repositório passa a preferir a coluna e só cai na derivação pelo roteiro
  quando ela é nula (`_SETOR_ORIGEM_SQL`), para que fila, histórico, resumo e
  guarda não divirjam;
* `QualityInspectionService._exigir_setor` compara a origem gravada com
  `quality_sector_for_user_level(self.nivel)` e é chamado no topo de
  `registrar_peca`, `finalizar_inspecao` e `obter_inspecao` — esta última
  devolve `None`, mantendo o 404 do roteador em vez de confirmar o id sondado.

Sessão sem origem resolvida (linha legada) continua visível a todos os
setores, e nível sem setor de Qualidade não é recusado no serviço: o gate de
papel do roteador já barra o acesso, e chamadas internas do domínio não têm
usuário para comparar. Regressão coberta por
`tests/test_quality_inspection.py::QualityRuleTests::test_escrita_revalida_o_setor_dono_da_inspecao`
e `::test_inspecao_legada_sem_origem_continua_visivel_a_todos`.

### M2 — `500` não tratado no login do Dev Observatory com senha não-ASCII

**OWASP:** A04 Insecure Design (falha de disponibilidade em caminho de auth)
**Local:** `backend/api/routers/dev_observatory.py:197`
**Status: CORRIGIDO**

`secrets.compare_digest` levanta `TypeError: comparing strings with non-ASCII
characters is not supported` quando recebe `str` com acento. Uma senha como
`senhá` derrubava o endpoint de autenticação com **HTTP 500 e stack trace**, em
vez de recusar com 401. Pior: se a credencial *configurada* tivesse qualquer
acento, o login ficaria permanentemente quebrado.

Corrigido em `_credential_matches`, que compara os bytes UTF-8 — vale para
qualquer senha e continua em tempo constante.

No mesmo trecho, as comparações de usuário e senha passaram a ser **sempre as
duas** (`:216`): a versão anterior curto-circuitava no `and`, e não avaliar a
senha quando o usuário não confere transforma o tempo de resposta em oráculo de
usuário válido.

### M3 — `GESTOR_DEVOBS_SESSION_SECRET` aceitava segredo curto

**OWASP:** A02 Cryptographic Failures
**Local:** `backend/api/config.py:227`
**Status: CORRIGIDO**

`GESTOR_WEB_SESSION_SECRET` já exigia ao menos 32 bytes; o segredo do Dev
Observatory não exigia nada. Um `GESTOR_DEVOBS_SESSION_SECRET=123` era aceito, e
com ele a assinatura HMAC-SHA256 do cookie de sessão vira forjável offline — quem
forjar entra sem senha, freio da A1 incluído.

Corrigido com o mesmo piso de 32 bytes. Não afeta o ambiente atual: a variável
está vazia no `.env`, então o caminho executado continua sendo o do segredo
efêmero gerado (ver B4).

### M4 — `vitest` / `@vitest/mocker`: path traversal (2 moderadas)

**OWASP:** A06 Vulnerable and Outdated Components
**Local:** `web/package.json` (devDependency)
**Status: DOCUMENTADO — não apliquei**

`npm audit` aponta GHSA-82fw-gwwq-j7x9 (Path Traversal / Arbitrary File Read via
`@vitest/mocker` Redirect Mock), severidade moderada, em `vitest 2.1.0–4.1.10`.

Risco real baixo: é dependência de desenvolvimento, não vai para o bundle do
navegador e só é explorável por quem já roda os testes na máquina. A correção
(`npm audit fix --force`) instala `vitest@5.0.0`, mudança de major com quebra de
API. Trocar o runner de testes no meio de uma auditoria de segurança, sem git,
por uma moderada que não afeta produção, é troca ruim.

**Recomendação:** agendar o upgrade para `vitest@5` como tarefa própria, com a
suíte do frontend rodando antes e depois.

`pip-audit 2.10.1` contra os 36 pacotes Python instalados: **nenhuma
vulnerabilidade conhecida**. Rodado num venv descartável, fora do `.venv` do
projeto, que foi removido ao final.

---

## BAIXO

### B1 — Página de recusa do Dev Observatory montava HTML por `str.format`

**Local:** `backend/api/routers/dev_observatory.py:582`
**Status: CORRIGIDO (endurecimento)**

`_DENIED_PAGE.format(message=exc.message)` interpolava a mensagem de exceção
crua no HTML. **Não é explorável hoje:** todo `AppError` que
`require_dev_observatory_user` produz é 401 e cai na página de login, o ramo
genérico só recebe texto de infraestrutura, e o CSP das páginas fora de `/api/`
é `script-src 'self'` sem `unsafe-inline` — script injetado não executaria.

Mesmo assim a mensagem agora passa por `html.escape` em `_denied_page`, porque o
custo é uma linha e o risco é que alguém, depois, roteie por ali uma mensagem
que carregue nome, código de OP ou motivo vindo do banco.

### B2 — Sessão HMAC sem revogação do lado do servidor

**Local:** `backend/api/security/sessions.py`, `backend/api/routers/auth.py:80`
**Status: DOCUMENTADO**

As sessões são tokens HMAC autocontidos. `logout` apaga o cookie do navegador,
mas o token continua **válido até expirar** — 8 h na sessão principal, 12 h no
Dev Observatory. Cookie copiado antes do logout segue funcionando; desativar o
usuário no banco corta a sessão principal (`get_current_user` recarrega e checa
`ativo`), mas o Dev Observatory não tem esse recurso, porque não consulta
usuário nenhum.

Trade-off normal de sessão stateless, e o custo de trocar é alto. Se algum dia
importar: guardar `session_id` (já existe em `SessionClaims`) numa denylist em
memória no logout resolve o caso comum sem virar sessão com estado.

### B3 — Enumeração de usuário por tempo de resposta no login principal

**Local:** `app/database/database.py:227`
**Status: DOCUMENTADO**

`autenticar_usuario` retorna cedo quando o usuário não existe, pulando o PBKDF2
de 600 000 iterações. A diferença de tempo entre "usuário inexistente" e "senha
errada" é grande e mensurável, permitindo confirmar quais nomes existem.

Impacto baixo (nomes de operador não são segredo numa fábrica), mas combina mal
com a A2. Correção: calcular o hash contra um valor fictício quando a linha não
existe, para que os dois caminhos custem o mesmo.

### B4 — `GESTOR_WEB_SESSION_SECRET` ausente do `.env`

**Local:** `.env`, `backend/api/config.py:201`
**Status: DOCUMENTADO**

Nem `GESTOR_WEB_SESSION_SECRET` nem `GESTOR_DEVOBS_SESSION_SECRET` estão
definidos. Em `development` o código gera um segredo efêmero e apenas avisa no
log (em `production` ele recusa subir — o gate existe e está correto).

Consequência prática, não vulnerabilidade: **toda sessão cai a cada reinício do
processo**, nos dois logins. Definir os dois (≥ 32 bytes, distintos entre si)
elimina o incômodo e prepara o ambiente para produção.

### B5 — `sanitize()` não redige DSN nem token por nome composto

**Local:** `backend/observability/classification.py:58`
**Status: DOCUMENTADO**

`_REDACTED_KEYS` casa a chave por igualdade exata. Cobre bem o essencial
(`password`, `senha`, `senha_hash`, `token`, `cookie`, `csrf`, `authorization`,
`api_key`, `groq_api_key`, `secret`, `session`), inclusive a senha do Dev
Observatory, que chega em campo `password`.

Ficam de fora, e podem entrar num artefato do observatório se algum payload de
erro os carregar: `dsn`, `database_url`, `connection_string`, `bot_token`,
`telegram_bot_token`, `sigmanest_password`, `nova_senha`, `senha_atual`.

**Correção sugerida (1 linha de lógica):** trocar a igualdade por sufixo —
`any(chave.endswith(k) for k in _REDACTED_KEYS)` — e acrescentar `dsn`,
`database_url` e `connection_string` ao conjunto. O sufixo já resolveria
`telegram_bot_token` (termina em `token`) e `sigmanest_password`.

---

## Verificado e correto (nada a fazer)

Pontos que conferi explicitamente e que estão bem resolvidos:

- **Injeção SQL:** nenhuma. Todas as consultas usam parâmetros `%s`. Os dois
  únicos SQL montados por f-string são seguros: `app/database/database.py:4337`
  interpola um nome de coluna vindo de um `dict` fechado, e
  `backend/observability/metrics.py:129` itera a constante `TRACKED_TABLES`.
- **Command injection / desserialização:** `subprocess`, `os.system`, `eval`,
  `exec`, `pickle.loads` e `yaml.load` **não aparecem** em `app/`, `backend/`
  nem `mes/`.
- **XXE e DoS de parsing:** `defusedxml` em todo XML de entrada, mais bloqueio
  explícito de `<!DOCTYPE`/`<!ENTITY` (`totvs_soap.py:57`) e leitura do corpo
  com teto **antes** do parse (`_read_limited_body`, `:87`).
- **Path traversal em `/dev-observatory/reports/{name}`:** a defesa está
  correta. `(base / name / "report.md").resolve()` seguido de
  `base not in target.parents` recusa `../`, caminho absoluto e symlink.
  Nenhuma outra rota monta caminho a partir de nome vindo da URL: o PDF da
  Qualidade vem de `storage_path` do banco e o desenho do operador vem de uma
  varredura por correspondência de nome, nunca de concatenação
  (`mes/services/drawings.py:205`). O upload sanitiza com
  `re.compile(r"[^A-Za-z0-9._-]+")` sobre `Path(...).name`, valida o *magic
  number* do PDF e limita o tamanho.
- **CSRF:** `require_csrf` está em **todas** as rotas de escrita
  (`ai`, `auth/logout`, `cutting`, `highlight`, `management`, `operator`,
  `quality`, `reports`, `system`). As três sem ele são justificadas:
  `auth/login` (ainda não há sessão) e os dois do Dev Observatory, que usam
  sessão própria com `SameSite=Strict` e estão comentados no código. A
  verificação usa `hmac.compare_digest` e exige o token no header **e** no
  cookie **e** batendo com o claim da sessão.
- **XSS no frontend:** nenhum `dangerouslySetInnerHTML` em `web/src`. A página
  do observatório usa `.innerHTML`, mas passa tudo por `escapar()`
  (`backend/observability/page/app.js:26`), inclusive `query` do
  `pg_stat_activity`, traceback e nomes de recurso; todos os atributos montados
  são aspas duplas, cobertas pelo escape.
- **Cookies:** `httponly` na sessão, `samesite=strict` nos dois logins,
  `secure` seguindo `GESTOR_WEB_COOKIE_SECURE` (=1 no `.env`), `max_age`
  amarrado ao TTL. O cookie de CSRF é `httponly=False` de propósito — o JS
  precisa lê-lo.
- **Senhas:** PBKDF2-SHA256 com 600 000 iterações, salt de 32 bytes por usuário,
  comparação com `hmac.compare_digest` e reidratação automática de hash legado.
  Está no nível recomendado pela OWASP.
- **CORS:** `allow_origins` explícito (`localhost:5173`), nunca `*` com
  `allow_credentials=True`. Métodos e headers restritos.
- **Cabeçalhos:** `X-Content-Type-Options`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer` e CSP em **todas** as respostas, pelo
  middleware `request_context` (`backend/api/main.py:463`). `/api/` recebe
  `default-src 'none'` e `Cache-Control: no-store`; as páginas recebem
  `script-src 'self'` sem `unsafe-inline`. Os endpoints do Dev Observatory
  reforçam `no-store` por conta própria.
- **Somente leitura do REAL:** olhei com olhar de atacante e não achei desvio.
  A sessão nasce com `options=-c default_transaction_read_only=on`, que é
  parâmetro de servidor; a **prova de gravação** (`CREATE TEMP TABLE`) roda na
  abertura e, se o PostgreSQL não recusar, o pool é fechado e o REAL fica
  indisponível — falha fechada (`readonly_db.py:126`). Um `options` contrário no
  DSN é neutralizado pela concatenação (o último vence) e ainda assim a prova
  reprovaria. Nenhum endpoint do módulo escreve, e o pool do REAL é separado do
  pool da API. A recomendação do próprio docstring — papel dedicado com apenas
  `SELECT` — continua sendo o passo que falta para a garantia virar também de
  permissão.
- **Segredos:** `.env` está no `.gitignore` (junto com `.env.*`, preservando
  `.env.example`). Nenhuma senha, token ou chave literal no código-fonte: tudo
  vem de variável de ambiente, e os campos sensíveis de `WebSettings` usam
  `field(repr=False)`, o que impede vazamento em log de `repr`.

---

## Fora do escopo, observado de passagem

`tests/test_totvs_integration.py::TotvsParserContractTests::test_mapper_nao_inventa_setor_e_aplica_alias_laser_oficial_exato`
**já falhava antes desta auditoria** e continua falhando — confirmei rodando-o
isolado. O mapper devolve uma operação `('Pintura', 'PINT.L')` a mais do que o
teste espera. É problema de mapeamento industrial, sem relação com segurança e
sem relação com qualquer arquivo que toquei. Fica registrado, não corrigido.

---

## Arquivos alterados

| Arquivo | Mudança |
|---|---|
| `backend/integrations/totvs_soap.py` | C1: `_arrived_through_public_host` + recusa 403 no POST e no WSDL |
| `backend/api/routers/dev_observatory.py` | A1/M2: freio de tentativa, `_credential_matches` em bytes, comparação sem curto-circuito; B1: `_denied_page` com `html.escape` |
| `backend/api/config.py` | M3: piso de 32 bytes em `GESTOR_DEVOBS_SESSION_SECRET` |
| `tests/test_totvs_integration.py` | 2 testes de regressão do C1 |
| `tests/test_dev_observatory.py` | 1 teste de regressão da A1/M2 + limpeza de `_login_failures` no `setUp` |
| `app/database/migrations.py`, `app/database/schema.py` | M1: migração 30 (`tipo_setor_origem` + backfill), `SCHEMA_VERSION = 30` |
| `app/database/quality_repository.py` | M1: os dois INSERT de `qualidade_inspecoes` gravam a origem; `_SETOR_ORIGEM_SQL` prefere a coluna |
| `mes/services/quality.py` | M1: `_exigir_setor` em `registrar_peca`, `finalizar_inspecao` e `obter_inspecao`; origem persistida na abertura e na dispensa |
| `tests/fakes.py`, `tests/test_quality_inspection.py` | M1: dublê com a nova coluna + 2 testes de regressão |

## Validação executada

```
tests.test_dev_observatory tests.test_web_api tests.test_totvs_integration
tests.test_corporate_integration tests.test_permissions
  -> Ran 105 tests — 1 falha (a pré-existente do mapper, acima)

tests.test_totvs_outbound tests.test_totvs_outbox tests.test_totvs_etapa7a_e2e
tests.test_quality_inspection
  -> Ran 120 tests — OK

verificação dirigida das correções -> 13/13
pip-audit (36 pacotes Python)      -> nenhuma vulnerabilidade conhecida
npm audit (web/)                   -> 2 moderadas, ambas devDependency (M4)
```

## O que fazer a seguir, por ordem

1. **A2** — decidir a política de freio do login principal (é a única decisão
   que depende de você).
2. ~~**M1** — a migração de `tipo_setor_origem` e o `_exigir_setor`.~~ Feito em
   2026-09-14 (migração 30). Resta aplicá-la ao banco REAL na próxima janela.
3. **B4** — definir os dois segredos de sessão no `.env` (≥ 32 bytes, distintos).
4. **C1, defesa em profundidade** — deixar `/PcfIntegService` fora do túnel na
   camada de proxy, além do bloqueio por host que já está no código.
5. **M4** — agendar o upgrade para `vitest@5`.
6. **B5** — o `endswith` no `sanitize()`.
7. **B3** — igualar o custo dos dois caminhos de `autenticar_usuario`.
