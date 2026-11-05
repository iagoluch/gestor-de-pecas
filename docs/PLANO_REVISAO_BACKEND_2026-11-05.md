# Plano de revisão completa do backend — 05/11/2026

Objetivo: revisar o backend de ponta a ponta sem deixar parte de fora.
Escopo: `backend/` (API, segurança, integrações, mensagens, IA, observabilidade), `mes/` (regras, serviços, cálculos, integrações TOTVS/SigmaNEST), `app/database/` (migrations) e `tests/`.
Fora do escopo: telas (`web/`), exceto onde a tela consome o contrato da API.
Versão revisada: commit `9c48c70` (tudo que estava pendente foi salvo antes da revisão).

Regra de ouro: cada item só fecha com **prova** (saída de teste, resultado de consulta, log ou arquivo:linha). "Parece ok" não fecha item.

---

## Como usar

1. Uma etapa por vez, na ordem.
2. Cada item tem três partes: **O quê** (o que conferir), **Como** (comando, teste ou leitura exata) e **Prova** (o que precisa aparecer para dar OK).
3. Marque: OK / Problema (arquivo:linha + gravidade crítico/alto/médio/baixo) / Não se aplica.
4. Problema vai para `docs/REVISAO_BACKEND_ACHADOS_2026-11.md`. Só corrige no meio da revisão se for crítico de segurança.
5. Ambiente: só `gestor_pecas_test` (porta 15432), uma API na 8001, `GESTOR_WEB_ENV=development`, Protheus TEST e SigmaNEST ligados, Telegram e IA desligados.

Ferramentas já disponíveis no projeto: `pytest`, `unittest`, `bandit`, `pip-audit` (em `requirements-dev.txt`), `gitleaks` (CI), `graphify`. Não há `ruff`/`mypy` instalados — ver Etapa 9.

---

## Etapa 0 — Inventário (o mapa)

**0.1 Rotas**
- O quê: todas as rotas, método, caminho e dependência de acesso.
- Como: script que importa o app e percorre `app.routes`, listando `path`, `methods` e as funções `require_*` de cada `dependant`.
  `python -c "from backend.api.main import app; ..."` (salvar em `dev_reports/revisao/rotas.csv`).
- Prova: CSV com ~170 linhas; total bate com a contagem por router (management 34, quality 18, dev_observatory 15, operator 13...).

**0.2 Serviços**
- O quê: qual rota chama cada um dos 61 serviços de `mes/services/`.
- Como: `graphify query "quais routers chamam cada serviço de mes/services"` e conferir com `grep -rn "from mes.services" backend/api/routers`.
- Prova: lista serviço → routers; serviço sem nenhum chamador marcado como suspeito de código morto.

**0.3 Tarefas em segundo plano**
- O quê: laços que rodam sozinhos (sync, recálculo, outbox, observatório, SSE).
- Como: `grep -n "async def _.*_loop\|create_task\|lifespan" backend/api/main.py`.
- Prova: lista com nome, intervalo, o que faz e qual flag liga/desliga.

**0.4 Conexões externas**
- O quê: Protheus (`backend/integrations/totvs_soap.py`, `totvs_wspcp.py`), SigmaNEST (`sigmanest_sqlserver.py`), Telegram, IA.
- Como: leitura dos arquivos + `grep -n "timeout" ` em cada um.
- Prova: tabela conexão → arquivo → timeout → o que acontece se cair.

**0.5 Configuração**
- O quê: toda variável em `backend/api/config.py`.
- Como: listar os campos e cruzar com o `.env` de exemplo.
- Prova: cada variável tem uso conhecido; nenhuma lida em código e ausente do `config.py`.

**0.6 Código morto**
- O quê: rota que a tela não usa.
- Como: para cada caminho do 0.1, `grep -rn "<caminho>" web/src`.
- Prova: lista de rotas sem consumidor (pode ser legítimo: TV, scripts, integração — anotar o motivo).

## Etapa 1 — Segurança e acesso

**1.1 Toda rota exige login**
- Como: no CSV do 0.1, filtrar rotas sem `get_current_user`/`require_*`.
- Prova: só sobram rotas públicas de propósito (login, saúde, arquivos estáticos). Cada uma justificada.

**1.2 Nível certo por rota**
- O quê: operador não acessa gestão; Qualidade, Manutenção, Diretoria e admin isolados (`require_qualidade_user`, `require_manutencao_user`, `require_diretoria_user`, `require_admin_user` em `backend/api/dependencies/auth.py`).
- Como: teste parametrizado que loga com cada nível e chama cada rota protegida.
- Prova: tabela nível × rota com 200/403 esperados; zero 200 indevido.

**1.3 Login e freio de tentativas**
- Como: ler `backend/api/security/login_throttle.py`; teste com N senhas erradas seguidas.
- Prova: bloqueio após o limite; mensagem igual para usuário inexistente e senha errada.

**1.4 Sessão**
- Como: ler `backend/api/security/sessions.py`; chamar login e inspecionar o cabeçalho `Set-Cookie`.
- Prova: cookie com `HttpOnly`, `SameSite`, `Secure` (fora de development); logout faz a sessão antiga dar 401; sessão expira no prazo configurado.

**1.5 Trocar o id na URL (IDOR)**
- Como: com usuário de um nível, pedir OP/recurso/usuário/RNC de outro escopo trocando o id.
- Prova: 403 ou 404, nunca o dado.

**1.6 Entrada validada**
- Como: `grep -rn "request.json()\|Body(\|dict = " backend/api/routers` — todo corpo deve ser modelo Pydantic de `backend/api/schemas`.
- Prova: nenhum corpo cru; campos de texto com tamanho máximo; números com faixa.

**1.7 SQL sem concatenação**
- Como: `grep -rnE "execute\(f\"|execute\(.*\+|\.format\(" backend mes app`.
- Prova: zero ocorrência com dado vindo do usuário (nomes de tabela fixos são aceitáveis, anotar).

**1.8 Limites de carga**
- Como: conferir onde `body_limit.py`, `rate_limit.py` e `dependencies/bulkhead.py` são aplicados.
- Prova: relatórios, exportação Excel e IA protegidos; corpo acima do limite recebe 413.

**1.9 Segredos**
- Como: `docker run ... gitleaks detect` (mesmo comando do CI) + `grep -rniE "password|token|secret" backend mes --include=*.py | grep -v "settings\."`.
- Prova: zero segredo no código e no histórico; logs e erros não imprimem senha/token.

**1.10 Rotas de desenvolvimento**
- Como: ler `require_dev_observatory_user` (`auth.py:217`) e o registro do router em `main.py`.
- Prova: subir a API com ambiente diferente de development (sem conectar em produção, só checar o registro) → rotas `dev_observatory` não existem ou dão 404.

**1.11 Pacotes vulneráveis**
- Como: `pip-audit -r requirements.txt` e `bandit -r backend mes app -ll`.
- Prova: saída sem vulnerabilidade alta/crítica, ou cada uma justificada.

**1.12 CORS e cabeçalhos**
- Como: `grep -n "CORSMiddleware\|allow_origins" backend/api/main.py`; `curl -I http://localhost:8001/`.
- Prova: origens específicas (sem `*` com credenciais); cabeçalhos básicos presentes.

## Etapa 2 — Contrato da API (o que a tela recebe)

**2.1 Resposta declarada**
- Como: no CSV do 0.1, marcar rotas sem `response_model`.
- Prova: lista; para cada uma sem modelo, conferir manualmente contra `web/src/types/api.ts`.

**2.2 Tela e API falam a mesma língua**
- Como: para as 20 rotas mais usadas, comparar campos do schema Pydantic com o tipo em `web/src/types/api.ts`.
- Prova: zero campo que a tela lê e a API não manda (e vice-versa sem motivo).

**2.3 Erros padronizados**
- Como: ler `backend/api/errors/`; `grep -rn "raise HTTPException" mes` (domínio não deveria lançar erro HTTP).
- Prova: regra de negócio → 409 com motivo em português; validação → 422; sem acesso → 403; sem login → 401; teste mostrando que erro esperado não vira 500.

**2.4 Datas e fuso**
- Como: `grep -rn "datetime.now()\|datetime.utcnow()" backend mes` (deveria usar `clock.py`).
- Prova: zero `now()` sem fuso fora do relógio central.

**2.5 Listas grandes**
- Como: rotas que devolvem lista — conferir parâmetro de limite em `dependencies/filters.py`.
- Prova: nenhuma lista sem teto; teste com limite acima do máximo é recusado ou cortado.

**2.6 Tempo real (SSE)**
- Como: ler `backend/api/realtime.py`; abrir a conexão, derrubar a API, subir de novo.
- Prova: a tela reconecta; conexões fechadas somem da contagem; evento de gestão não chega para operador.

## Etapa 3 — Regras de fábrica

Cada item: ler a regra no código, achar o teste que a protege e rodar. Sem teste = Problema (médio ou alto).

**3.1 Estados do operador** — `mes/domain/operator_state_machine.py`
- Como: listar transições permitidas; `pytest tests -k "state_machine or operator_state" -q`.
- Prova: teste para cada transição proibida; duplo clique (mesma requisição duas vezes) não cria dois apontamentos.

**3.2 Apontamento**
- Como: `pytest tests -k "apontamento or pointing" -q`; tentar apontar em recurso só sincronizado.
- Prova: recurso não apontável é recusado com 409; boa/refugo/retrabalho somam a quantidade certa.

**3.3 Turno único e hora extra no fim de semana**
- Como: `mes/services/calendar.py`; `pytest tests -k "calendar or turno or shift" -q`.
- Prova: sábado/domingo = fora de turno, salvo hora extra; vigência de turno respeitada.

**3.4 Corte conta plano cortado** — `mes/services/cut.py`
- Como: `pytest tests -k "cut or corte" -q`.
- Prova: teste em que um plano com várias OPs conta 1 plano; OPs aparecem sem somar.

**3.5 Encerramento de OP com Corte na origem**
- Como: `pytest tests -k "encerramento or close_order" -q`.
- Prova: teste reproduzindo o caso da OP 030 passa.

**3.6 Primeira peça, cotas, RNC, NC** — `mes/domain/first_piece.py`, `quality_measures.py`
- Como: `pytest tests -k "first_piece or quality or rnc" -q`; conferir permissão de quem decide RNC.
- Prova: só Qualidade/admin decidem RNC; o que bloqueia e o que não bloqueia tem teste.

**3.7 Tempo padrão e rateio** — `mes/domain/standard_time.py`, `mes/analytics/rateio.py`
- Prova: teste com chave mista (aceitar manual); rateio fecha 100% do tempo.

**3.8 Manutenção e trava da Qualidade**
- Prova: mantenedor só vê `/manutencao`; trava da Qualidade testada.

**3.9 Alertas e chamadas** — `mes/domain/internal_alerts.py`, router `chamadas.py`
- Prova: quem recebe, quando expira e quem fecha, cada um com teste.

**3.10 Uma só fonte da verdade**
- Como: `graphify explain "manufacturing_rules"`; procurar a mesma condição repetida em routers.
- Prova: regra decidida em um lugar só; router só chama.

## Etapa 4 — Cálculos e indicadores

**4.1 OEE** — `mes/analytics/oee.py`
- Como: montar um dia sintético pequeno (ex.: 8 h de turno, 1 h parada, 100 peças, 5 refugo) e calcular à mão; rodar o serviço com o mesmo dado.
- Prova: disponibilidade, desempenho, qualidade e OEE iguais ao cálculo manual; cada número com "de onde veio".

**4.2 Linha do tempo** — `timeline.py`, `intervals.py`, `physical_time.py`
- Como: teste de propriedade: soma dos intervalos = tempo do período; nenhum intervalo negativo ou sobreposto; virada de meia-noite e de turno.
- Prova: testes passam, incluindo o caso de virada de dia.

**4.3 Estado do recurso** — `resource_state.py`
- Prova: estado "agora" igual ao último trecho da timeline (incluindo estado iniciado antes do período — mudança do commit `9c48c70`).

**4.4 Horas agregadas**
- Prova: teste em que dois recursos somam e mostram média; fora de turno usa união do calendário sem somar.

**4.5 Visão geral da gestão** — `mes/services/management.py` (34 rotas)
- Como: `pytest tests -k management -q`; conferir que o setor vem do catálogo (mudança recente).
- Prova: testes passam; setor de recurso sem catálogo cai no valor da linha.

**4.6 Relatório = tela**
- Como: para 3 filtros (dia, semana, mês), comparar número da rota da tela com o da exportação (`routers/reports.py`, `report_workbook/`).
- Prova: valores idênticos.

**4.7 Bordas**
- Como: chamar os cálculos com período vazio, recurso novo, tempo planejado zero.
- Prova: nada de divisão por zero, `NaN` ou valor acima de 100% sem explicação.

## Etapa 5 — Integrações

**TOTVS/Protheus** (`mes/integrations/totvs/`, `backend/integrations/totvs_*.py`)
- 5.1 Leitura robusta — Como: testes do `parser.py`/`mapper.py` com campo vazio, data inválida, acento e caractere especial. Prova: erro claro, sem quebrar a sincronização inteira.
- 5.2 Envio sem duplicar — Como: ler `outbox.py`, `outbound_enqueue.py`, `outbound_ack.py`; enviar a mesma mensagem duas vezes no Protheus TEST. Prova: chave de idempotência; segundo envio não cria apontamento duplicado no ERP.
- 5.3 Retentativa — Prova: limite de tentativas, intervalo crescente, mensagem que falha sempre fica marcada (não some, não trava a fila).
- 5.4 Protheus fora do ar — Como: apontar no MES com o transporte simulando falha. Prova: operador continua trabalhando; fila guarda e envia depois.
- 5.5 Timeout — Prova: toda chamada em `transport.py`/`totvs_soap.py` tem timeout explícito.
- 5.6 Mapeamento de recursos — Como: consulta cruzando `resource_mapping` com o catálogo. Prova: zero recurso órfão.

**SigmaNEST** (`mes/integrations/sigmanest/`, `backend/integrations/sigmanest_sqlserver.py`)
- 5.7 Só leitura — Como: `grep -niE "insert|update|delete|merge" backend/integrations/sigmanest_sqlserver.py`. Prova: zero escrita.
- 5.8 Sync repetida não duplica — Como: rodar a sincronização duas vezes seguidas. Prova: contagem de planos/tarefas igual.
- 5.9 Queda de conexão — Prova: erro registrado, API segue respondendo.

**Telegram e IA**
- 5.10 Desligados não quebram — Como: subir a API com os dois desligados e abrir telas que os usam. Prova: sem erro 500.
- 5.11 IA só lê — Como: ler `mes/services/ai_tools.py`. Prova: nenhuma ferramenta grava; respostas filtradas pelo nível do usuário; limite em `backend/ai/rate_limit_state.py`.

## Etapa 6 — Banco de dados

**6.1 Migrations do zero** — `app/database/migrations.py`
- Como: procedimento do banco descartável (memória "EXPLAIN com banco vazio"), mas **dentro** do `gestor_pecas_test` respeitando a regra de 1 banco + 1 schema: rodar todas as migrations em ordem e conferir que a última versão aplicada é a esperada.
- Prova: zero erro; versão final igual à do REAL (v68 ou superior documentada).

**6.2 Índices**
- Como: `EXPLAIN (ANALYZE, BUFFERS)` nas consultas de timeline, apontamentos, OEE e relatórios, com volume sintético rotulado.
- Prova: nenhum `Seq Scan` em tabela grande nas consultas principais.

**6.3 Tudo ou nada**
- Como: procurar operações de vários passos (apontar + outbox, fechar OP) e ver se estão numa transação só.
- Prova: teste que força erro no segundo passo e confere que o primeiro foi desfeito.

**6.4 Dois ao mesmo tempo**
- Como: teste com duas requisições simultâneas na mesma OP/recurso.
- Prova: uma passa, outra recebe 409; banco sem registro duplicado (restrição UNIQUE ou trava).

**6.5 Restrições no banco**
- Como: listar NOT NULL, FK, UNIQUE e CHECK das tabelas principais (`\d+ tabela` no psql).
- Prova: regras críticas também garantidas pelo banco, não só pelo código.

**6.6 N+1**
- Como: ligar log de SQL e abrir as 10 telas mais usadas.
- Prova: número de consultas por requisição não cresce com o número de itens.

**6.7 Conexões**
- Como: ler `backend/api/database.py`.
- Prova: pool com teto; conexão sempre devolvida (uso de `with`/`finally`).

**6.8 Trava do banco esperado**
- Como: subir a API com `GESTOR_EXPECTED_DATABASE` diferente do banco conectado.
- Prova: API recusa subir com mensagem clara.

## Etapa 7 — Confiabilidade e registros

**7.1 Logs com contexto** — `backend/api/request_context.py`
- Prova: erro no log traz rota, usuário e id da requisição; nenhum dado sensível.

**7.2 Erro engolido**
- Como: `grep -rnE "except( Exception)?:\s*$" -A2 backend mes | grep -B1 "pass"`.
- Prova: cada `except` registra ou repassa o erro; lista dos que não fazem.

**7.3 Tarefas em segundo plano**
- Como: forçar exceção dentro de cada laço do 0.3.
- Prova: laço registra o erro e continua na próxima volta; não roda duas cópias ao mesmo tempo.

**7.4 Rota de saúde** — `routers/system.py`
- Prova: mostra banco, Protheus e SigmaNEST separadamente; um fora do ar aparece como fora.

**7.5 Reinício no meio**
- Como: matar a API durante um apontamento e um envio à outbox.
- Prova: ao voltar, nada pela metade (transação desfeita ou concluída) e a outbox retoma.

**7.6 Observatório** — `backend/observability/`
- Prova: usa `readonly_db.py`; tempo da API com e sem observatório ligado praticamente igual.

## Etapa 8 — Desempenho

**8.1 Rotas mais usadas**
- Como: medir com `curl -w "%{time_total}"` (10 chamadas cada) as rotas do operador, Andon, gestão e OEE.
- Prova: tabela de tempos; anotar acima de 1 s.

**8.2 Rotas pesadas**
- Prova: relatório de 1 mês não trava outras rotas (medir 8.1 enquanto exporta); período máximo limitado.

**8.3 Andon na TV**
- Prova: resposta pequena (KB, não MB) e rápida com polling contínuo por 10 min sem crescer memória da API.

## Etapa 9 — Qualidade do código

**9.1 Camadas**
- Como: `grep -rn "execute(\|cursor" backend/api/routers`.
- Prova: router não acessa banco direto; regra fica em `mes/domain`/`mes/services`.

**9.2 Arquivos e funções grandes**
- Como: `find backend mes -name "*.py" | xargs wc -l | sort -n | tail -15`.
- Prova: lista dos maiores com sugestão de divisão (só sugestão, sem refatorar na revisão).

**9.3 Duplicação**
- Como: `graphify query "funções duplicadas ou parecidas entre serviços"`.
- Prova: lista de pares duplicados.

**9.4 Lint e tipos**
- Como: rodar uma vez `ruff check backend mes app` e `mypy backend mes` via `pipx run` (sem adicionar ao projeto).
- Prova: contagem de avisos por tipo; erros reais (variável indefinida, import errado) viram Problema.

**9.5 Import circular**
- Prova: `python -c "import backend.api.main"` sem erro e sem import tardio escondendo ciclo.

## Etapa 10 — Testes

**10.1 Cobertura das regras**
- Como: `pytest tests --cov=mes --cov=backend --cov-report=term-missing` (só módulos das Etapas 3 e 4 se quiser economizar).
- Prova: cada regra da Etapa 3 com teste; linhas críticas não cobertas listadas.

**10.2 Permissão**
- Prova: teste do 1.2 existe e roda no CI.

**10.3 Integrações simuladas**
- Prova: testes de falha, timeout e resposta estranha do Protheus e do SigmaNEST.

**10.4 Regra do notebook**
- Como: `grep -rn "CREATE SCHEMA\|CREATE DATABASE" tests`.
- Prova: zero teste criando banco/schema extra.

**10.5 Testes pulados**
- Como: `grep -rn "skip\|xfail" tests`.
- Prova: lista com motivo de cada um.

**10.6 CI**
- Como: `gh run list --workflow ci.yml --limit 5`.
- Prova: últimas execuções verdes. Atenção: o CI roda só 4 arquivos com pytest e o resto com unittest — conferir se nada fica de fora.

## Etapa 11 — Ponta a ponta (um dia de fábrica)

Rodar no TEST, anotando o id de cada registro e conferindo no banco a cada passo:

1. OP chega do Protheus TEST → aparece na fila certa.
2. Plano de corte chega do SigmaNEST → tarefa e plano corretos.
3. Operador loga, inicia, pausa, aponta e termina → estado e timeline corretos.
4. Primeira peça / Qualidade / RNC → bloqueios e decisões corretos.
5. Andon e estado do recurso mostram o que aconteceu.
6. OEE e visão da gestão batem com o cálculo manual do passo.
7. Encerramento vai para o Protheus pela outbox, uma vez só.
8. Relatório exportado bate com a tela.

Prova: roteiro preenchido com ids e prints em `dev_reports/revisao/ponta-a-ponta.md`.

## Etapa 12 — Configuração e entrega

- 12.1 Variável obrigatória ausente → API recusa subir com mensagem clara (testar tirando uma do ambiente).
- 12.2 Valores padrão seguros: sem configuração, nada sensível fica aberto.
- 12.3 `deploy/` e `.github/workflows/deploy.yml` coerentes com o que a API precisa (mesmas variáveis, mesma versão de Python).
- 12.4 Documentação de estado atual (`docs/`) reflete o código revisado.

---

## Ordem e responsáveis

1. Etapa 0 — base para tudo (pode ir para `haiku-worker`, é coleta mecânica).
2. Etapa 1 — `application-security-engineer`.
3. Etapa 3 — `mes-domain-guardian`; Etapa 4 — `oee-engineer`.
4. Etapa 5 — `totvs-integration-engineer` e `sigmanest-engineer`.
5. Etapa 6 — `database-engineer`.
6. Etapas 2, 7, 8, 9 — `backend-engineer`, `reliability-observability-engineer`, `performance-engineer`.
7. Etapas 10 e 11 — `qa-test-engineer`.
8. Parecer final — `technical-reviewer`.
