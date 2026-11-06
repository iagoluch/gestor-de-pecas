# Revisão do backend — achados (iniciada 05/11/2026)

Plano: `docs/PLANO_REVISAO_BACKEND_2026-11-05.md`. Inventário: `dev_reports/revisao/ETAPA0_INVENTARIO.md`.
Gravidade: crítico · alto · médio · baixo. Status: aberto · confirmado · corrigido · descartado.

## Etapa 0

**A1 — descartado na Etapa 1**
Engano do inventário: as rotas que gravam no observatório têm proteção CSRF (`Depends(_require_dev_observatory_csrf)`, `backend/api/routers/dev_observatory.py:648,694,714,766,806`). O script de rotas não reconheceu esse nome de função. Texto original abaixo.

**A1 (original)**
Observatório dev: 7 rotas que gravam não exigem CSRF, incluindo `POST /api/v1/dev-observatory/actions/terminate-backend`. A sessão do observatório é por cookie (`backend/api/routers/dev_observatory.py:331`), então um site de fora poderia disparar essas ações no navegador de quem está logado. Só existe com `dev_observatory_enabled`.

**A2 — baixo — aberto (Etapa 2)**
160 de 173 rotas não declaram `response_model`. O FastAPI não confere o que a API devolve; uma mudança no serviço pode quebrar a tela sem nenhum teste acusar.

**A3 — baixo — aberto**
`mes/services/operational_reports.py` (`OperationalReportService`) não é usado por nenhuma rota, serviço ou script; só por `tests/test_operational_report_service.py`. Candidato a remoção (decisão do usuário).

**A4 — baixo — aberto**
SigmaNEST: `pyodbc.connect(...)` em `backend/integrations/sigmanest_sqlserver.py:185` não passa tempo-limite de conexão; só a consulta tem. Se o servidor não responder ao login, a sincronização fica esperando o padrão do driver.

**A5 — baixo — aberto**
Configuração em dois lugares: `backend/api/config.py` e leitura direta do ambiente nas integrações (envio Protheus, SigmaNEST, PostgreSQL). 38 variáveis usadas no código não estão no `.env.example`, entre elas: `GESTOR_ANDON_DEMO_MODE`, `GESTOR_WEB_THREAD_POOL_SIZE`, `GESTOR_WEB_MANAGEMENT_READ_CONCURRENCY`, `GESTOR_WEB_OPERATIONS_STREAM_*`, `GESTOR_CHAMADA_LIMIT_*`, `PGSTATEMENT_TIMEOUT_MS`, `PGSSLMODE`, `SIGMANEST_LASER_MACHINE`, `SIGMANEST_PLASMA_MACHINE`, `TELEGRAM_LINK_*`.

**A6 — baixo — aberto**
Os 8 laços em segundo plano não têm trava contra rodar em dois processos. Hoje a instalação usa 1 processo de propósito; o risco é só se alguém mudar isso (envio duplicado ao Protheus seria o pior caso — conferir na Etapa 5 se a outbox se protege sozinha).

## Etapa 1 — Segurança e acesso

Relatório completo: `dev_reports/revisao/ETAPA1_SEGURANCA.md`. Nenhum achado crítico ou alto.
Prova principal: teste de nível × rota (14 níveis × 138 rotas = 1932 chamadas) não achou nenhum acesso indevido. Houve 4 recusas onde se esperava passar: fila e tarefa do Destaque para operador de corte e de dobra. São recusas pela regra do próprio setor, o que é esperado. A troca de id na URL também está protegida.
Ressalva: 19 rotas (Chamadas, Qualidade de cotas/desenho) exigem só login, e o nível é checado dentro da função. Para essas, o teste só confirmou que o login é exigido; quem bloqueia cada nível foi conferido lendo o código (ex.: `quality.py:266`, `quality.py:518`).

**A7 — médio — aberto**
O observatório dev vem **ligado por padrão**: `backend/api/config.py:770-771` (`default=True`) e `.env.example:161` (`true`). Um servidor novo montado copiando o exemplo publica a página e o login do observatório pelo túnel. Atrás desse login ficam erros internos, o catálogo do banco e o encerramento do backend. O instalador da VM já grava `false`, então o risco está só numa instalação manual. Correção: o padrão passa a ser desligado fora de test/development, e o `.env.example` traz `false`.

**A8 — baixo — aberto**
O "Sair" do observatório só apaga o cookie (`dev_observatory.py:327-343`). Um cookie copiado continua valendo até expirar, em até 12 h. Correção: um contador de sessão que o "Sair" incrementa, ou um prazo menor.

**A9 — baixo — aberto**
`/api/v1/system/health`, que é aberta, devolve `schema_version` (`backend/api/database.py:56-60`). Quem acha o endereço fica sabendo a versão do banco. Correção: sem login, devolver só ok/fora.

**A10 — baixo — aberto**
As preferências do usuário aceitam qualquer conteúdo em `dashboard_home: dict` (`backend/api/schemas/auth.py:54`). Qualquer conta, até um operador, grava até 1 MB de conteúdo sem formato no banco. Cada gravação substitui a anterior, não acumula. Correção: aceitar só os campos conhecidos e pôr limite de tamanho.

**Não verificado na Etapa 1 (fica pendente):**
- Login: medir o tempo de resposta (usuário inexistente × senha errada).
- Envio grande demais: provar a recusa (413) em teste. Até agora só foi conferido no código.
- gitleaks, pip-audit, bandit.
- Erro 500 sem detalhe interno.
- Se a lista de contatos das Chamadas mostra telefone/Telegram ao operador.
- Avisos em tempo real (SSE) por nível.
- Se a IA deixa gestor comum ver o custo da Diretoria.

## Etapa 3 — Regras de fábrica

Relatório completo: `dev_reports/revisao/ETAPA3_REGRAS_FABRICA.md`. Nenhuma regra quebrada no código; os problemas são testes que falham ou faltam.
Os testes que criam schema próprio foram pulados (`TEST_DATABASE_URL=` vazio), por causa da regra de 1 banco + 1 schema no notebook.
Tempo padrão: o sistema usa só o tempo do Protheus e ignora o manual. Isso **não é regressão**: é decisão do usuário de 04/11/2026 (commit db5c618, `mes/domain/standard_time.py:3-8`), que substituiu a de 06/10.

**A11 — médio — aberto (conferido: 7 falham)**
`tests/test_manutencao_sugestoes.py::ApiTests` tem 7 testes falhando. As datas do teste estão fixas em 26/10, mas a janela é de 7 dias, então hoje não acha nada. O sistema funciona; o que caiu foi a prova de "só Manutenção e admin decidem". Correção: usar relógio fixo no teste.

**A12 — médio — aberto**
`tests/test_backend_canonical_v11.py:505` falha. O Andon consulta o catálogo 3 vezes por atualização em vez de 1. Causa não investigada (ver Etapa 9, desempenho).

**A13 — médio — aberto**
Corte: nenhum teste separa "plano" de "OP" no total de peças boas (o teste usa 2 planos com 2 OPs). Se o total voltar a contar por OP, nenhum teste quebra. Correção: teste com 1 plano e 3 OPs, esperando 1.

**A14 — médio — aberto**
Fim de semana: nenhum teste garante que o apontamento de hora extra no sábado não é cortado às 17:30/21:30, nem que o recurso volta a "fora de turno" ao finalizar.

**A15 — médio — aberto**
Estados do operador: só 4 das 21 mudanças proibidas têm teste (`mes/domain/operator_state_machine.py:37`). Correção: um teste que compare as 36 combinações com a tabela.

**A16 — médio — aberto**
A regra de "Corte concluído" está em dois SQLs: `app/database/database.py:130` e a cópia em `app/database/totvs_outbound_repository.py:188-196`. A cópia existe por causa de import circular. Se só um mudar, a fila e a op 99 no Protheus passam a discordar. Correção: mover o trecho SQL para um módulo neutro usado pelos dois.

**A17 — baixo — aberto**
A decisão de RNC usa a mesma permissão das cotas padrão. Se outro nível ganhar acesso às cotas, ganha também o poder de decidir RNC.

**A18 — baixo — aberto**
`backend/api/routers/chamadas.py:77` repete a checagem "recurso é do setor" em vez de usar a função existente.

Observações, sem achado:
- O recurso que não é do operador é recusado com 403, não com 409. Faz sentido assim; vou ajustar o plano.
- Alerta não tem "fechar": some sozinho em 24 h. Ter "fechar" seria funcionalidade nova.

**Não verificado na Etapa 3** (testes que criam schema):
- Caso da OP 030.
- Duplo clique simultâneo direto no banco.
- Vigência de turno.
- Histórico de RNC.
- Decisão simultânea de manutenção.
- Chamadas gravando no banco.

## Etapa 4 — Cálculos e indicadores

Relatório completo: `dev_reports/revisao/ETAPA4_CALCULOS.md`. Itens OK:
- OEE bate com a conta à mão (ex.: 87,5% × 90,48% × 95% = 75,21%).
- Horas somadas + média e união do fora de turno seguem a regra.
- Tela e exportação usam a mesma função.
- Período vazio, recurso novo e tempo zero não quebram nada.

**A19 — alto — aberto (conferido no código)**
`mes/analytics/timeline.py:107-108`: quando há um evento depois do fim do recorte, o `break` pula o `else` do laço (`:126-128`). O último trecho não é fechado até o fim do recorte, e essas horas somem da conta.
Exemplo: a máquina produz das 08h às 14h e o gestor filtra 08h–12h. Aparece 0 h de produção, quando deveriam ser 4 h.
Em 2.000 casos sintéticos, 678 ficaram abaixo do período.
Onde afeta:
- análises industriais;
- relatórios operacionais;
- auditoria;
- Visão Geral, só quando falta o estado gravado da máquina.
Correção: antes do `break`, fechar o trecho em `end`, e criar um teste para esse caso.

**A20 — médio — aberto (conferido no código)**
O filtro de setor ainda compara o setor gravado na linha (`app/database/database.py:4896` e `:4934`), mas a tela mostra o setor do catálogo (commit 9c48c70).
Exemplo: uma máquina do Protótipo gravada como "Solda". Filtrando Protótipo, ela some. Filtrando Solda, ela aparece rotulada como Protótipo, e as horas entram na conta da Solda.
Correção: filtrar pelo setor depois de trocar pelo do catálogo. Falta um teste disso.

**A21 — baixo — aberto**
`mes/analytics/oee.py`:
- O cartão do OEE pode mostrar mais de 100% sem explicação; o aviso existe só no Desempenho (`:333-354`).
- O aviso de "dado parcial" se perde quando o Desempenho passa de 100% (`:316-325`).

**Não verificado na Etapa 4:**
- 40 testes que criam schema.
- Comparação da tela com o arquivo exportado usando dados reais.

## Etapa 5 — Integrações

Relatório completo: `dev_reports/revisao/ETAPA5_INTEGRACOES.md`. Por segurança, nada foi enviado ao Protheus e nenhuma sincronização foi rodada.

Conferido e OK:
- Leitura do TOTVS e tempo-limite em todas as chamadas HTTP.
- SigmaNEST é só leitura. Sync repetida não duplica: zero repetidos no banco de teste.
- O sistema funciona com Telegram e IA desligados.
- A outbox tem chave única no banco e se protege contra 2 processos. **Isso fecha a parte TOTVS do A6.**

**A22 — médio — aberto (conferido no código)**
O envio ao Protheus é "pelo menos uma vez" (`mes/integrations/totvs/outbox.py:11-15`). O próprio Protheus só recusa repetição quando a operação já está totalizada (`A680OPTOT`).
Cenário: um apontamento parcial é gravado no ERP, mas a resposta se perde depois de 30 s. O MES reenvia com a mesma chave e o parcial pode entrar duas vezes.
Falta confirmar no fonte do Protheus se a chave repetida é descartada. Correção possível: consultar no ERP antes de reenviar quando houve falta de resposta.

**A23 — médio — aberto (conferido no código)**
O envio desiste depois de 12 tentativas, cerca de 8 h (`outbox.py:56-64`, `:214-219`). Depois disso, a mensagem fica em ERRO e segura as seguintes da mesma OP.
Cenário: o ERP fica parado no fim de semana. Na segunda, os apontamentos não chegaram e só voltam se alguém reprocessar à mão.
Correção: falha de rede voltar sozinha para a fila depois de um tempo, ou avisar alguém.

**A24 — médio — aberto (consequência do A4)**
A busca no SigmaNEST pode travar em silêncio (`mes/services/sigmanest_refresh.py:96-117`). Se o servidor sumir da rede, a conexão fica presa sem registrar erro. Chapa nova não aparece no Corte até reiniciar a API.
Correção: a do A4, mais um alerta quando a última sincronização estiver velha.

**A25 — baixo — aberto**
Pontos menores, todos no relatório:
- XML que não está em UTF-8 é recusado sem registro.
- OP sob demanda pode demorar até ~40 s.
- `INSPEC` e `ALMOX4` estão fora do catálogo. Provavelmente de propósito.
- Os testes do Corte gravam por um caminho que a produção não usa.
- O limite de uso da IA dobra se houver 2 processos.

**Não verificado na Etapa 5:**
- 58 testes que criam schema: 35 da fila TOTVS (inclusive "Protheus fora" e "falta de resposta"), 17 do SigmaNEST e 6 do Telegram.
- Telas no navegador.

## Etapa 6 — Banco de dados

Relatório: `dev_reports/revisao/ETAPA6_BANCO.md`.

**OK:** banco de teste na versão 72, igual ao código. O apontamento e o aviso ao Protheus são gravados juntos (tudo ou nada). O banco barra OP duplicada no mesmo setor, dois estados abertos no mesmo recurso e plano de corte apontado duas vezes; na disputa a tela recebe 409. As conexões têm limite e são sempre devolvidas. A trava de banco errado funciona (8 de 8 testes).

- **A26 (médio)** — `app/database/database.py:6207-6210`: a consulta dos planos do Destaque filtra por `UPPER(COALESCE(maquina_sigmanest,''))`, sem índice e sem limite de data. Lê os ~12,4 mil planos inteiros a cada chamada, e cresce com o histórico. Correção: índice nessa expressão ou recorte por data, como a fila do Corte. (Conferido no código.)
- **A27 (baixo)** — `app/database/database.py:1998-2006`: o agendador busca `MIN(data_inicio)` por `UPPER(recurso)` em todo o histórico de `eventos_estado_recurso`. Correção: índice por recurso e data de início.
- **A28 (baixo)** — o banco não confere o texto do status do apontamento (um "Em Processo" com outra grafia escapa da trava de OP duplicada) e aceita fim antes do início (tempo negativo nos relatórios). Correção: duas regras CHECK; antes, conferir se o REAL já tem dados assim.
- **A29 (baixo)** — `backend/api/database.py:40`: com banco errado a tela mostra só "não foi possível conectar"; o motivo fica no log. No REAL a conferência do nome do banco é opcional.

**Ressalvas:** o `.env` deste notebook limita a 4 conexões (padrão do código é 10); conferir o valor no REAL antes de várias TVs e operadores ao mesmo tempo. O REAL está na versão 68 (pela memória, não conferido); 69 a 72 sobem juntas.

**Não verificado na Etapa 6:** migrations do zero e desempenho com volume (proibido neste notebook); 23 testes de transação e concorrência pulados (criam schema); número real de consultas por tela e a API recusando subir com banco errado (exigiriam outra API).

## Etapa 2 — Contrato da API (o que a tela recebe)

Relatório: `dev_reports/revisao/ETAPA2_CONTRATO.md`.

**OK:** nenhum campo que a tela lê falta na resposta (comparação por nome). Nenhum `raise HTTPException` em `mes/` ou `app/`. Erro de regra sai como 409/422 com texto em português. O SSE reconecta com espera de 5 a 30 s e libera a vaga quando a conexão fecha. Testes: 2 de erros e 31 de tempo real passaram (2 pulados).

- **A30 (médio)** — `GET /cutting/history` (`backend/api/routers/cutting.py:217` → `app/database/database.py:1628-1659`): o período é opcional e não há LIMIT. Sem filtro, devolve todo o histórico do corte. (Conferido no código.)
- **A31 (médio/baixo)** — `/system/events`: o teto é só o total de 500 vagas (`backend/api/main.py:884-886`, `backend/api/realtime.py:78`), sem limite por usuário. Uma conta com muitas abas pode tomar as vagas das outras. Os nomes dos eventos chegam a qualquer usuário logado, sem filtro por nível. (Conferido no código.)
- **A32 (médio)** — as rotas que gravam calendário (`productive-calendars`, `resource-calendars`) não têm tela nem teste.
- **A33 (médio na simulação, baixo em produção)** — `app/database/database.py:4958` (`agora_db()`) e `management.py:877` (`datetime.now()`) ignoram o relógio que pode ser trocado em teste ou simulação. Em produção o resultado é o mesmo. As outras 56 ocorrências de `now()` são inofensivas.
- **A34 (baixo/médio)** — `backend/api/errors/__init__.py:156-163`: quando o `detail` do HTTPException não é texto, a mensagem vira o texto genérico (caso do relógio virtual, `system.py:106`). O mesmo arquivo mostra "banco indisponível" para `DatabaseIntegrityError`, que é outra falha.
- **A35 (baixo)** — rotas sem chamador: `POST /quality/inspections/{id}/finish` (`quality.py:221`), sem tela nem teste, e `GET /quality/context`, usada só por teste. O `export.csv` não tem teto de linhas.
- **A36 (baixo)** — os tipos da tela `OperatorOperation`, `OperatorCard` e `StopReason` aceitam qualquer campo (`web/src/types/api.ts:76,190,323`). Se uma coluna for renomeada no banco, a tela não acusa erro (reforça o A2).

**Correção do 0.6:** `areas/{id}/queue/resources` e `maintenance/.../accept|discard` são usadas pela tela; a URL é montada em pedaços. `sync/diagnostico`, `reports/generate`, `reports/schedules` e `export.csv` são usadas só por teste ou integração.

**Não verificado na Etapa 2:** resposta real de rota com login na 8001; campos mandados sem uso (as rotas de operador e corte devolvem a linha inteira); se `listar_primeiras_pecas` tem teto; demais rotas de `rotas_sem_tela.txt` (insights, kpis, standard-times, diretoria); se a tela mostra o `details` do 422 em inglês; SSE sob carga ou queda real; suítes que criam schema.

## Etapa 7 — Confiabilidade e registros

Relatório: `dev_reports/revisao/ETAPA7_CONFIABILIDADE.md`.

**OK:** o log leva o id da requisição, e nenhum log grava senha, token, cookie ou corpo de login. Dos 61 `except` que só passam ou retornam, nenhum esconde falha relevante. Os 8 laços registram o erro e seguem na próxima volta. O observatório lê o banco por conexão só de leitura, garantida pelo PostgreSQL (`backend/observability/readonly_db.py:47,156`). Testes: 12 + 7 passaram. A 8001 respondeu 200 em live, ready e health, com o banco disponível.

- **A37 (médio)** — os laços não têm prazo máximo por volta (`backend/api/main.py:272, 308, 349, 473, 526, 621`). Uma chamada de rede ou de banco que trava para o laço sem aviso, inclusive a outbox e a virada de turno. Liga-se ao A4 e ao A24.
- **A38 (médio)** — `/ready` e `/health` olham só o banco (`backend/api/routers/system.py:178-188`). Protheus, SigmaNEST, fila da outbox e laço travado não aparecem, então a saúde fica verde mesmo com a integração parada. (Conferido no código.)
- **A39 (médio)** — `app/database/totvs_outbox_repository.py:180-182`: se a API cai durante a última tentativa de um item, a recuperação o põe em ERROR sem novo envio e sem aviso. Ele só volta pelo reprocesso manual (`:441`). Agrava o A23. (Conferido no código.)
- **A40 (baixo)** — o log do erro 500 traz só o id, sem rota, método e usuário (`backend/api/errors/__init__.py:168`); esses dados ficam só no observatório. O observatório grava a mensagem de erro e o traceback sem máscara (`backend/observability/recorder.py:226-229`); a pasta está no `.gitignore`.
- **A41 (baixo)** — os laços não têm recuo nem limite de log. Com o banco fora, o laço de turno (5 s), o do Telegram (3 s) e o da outbox (15 s) gravam erro com traceback sem parar (`main.py:637, 399, 278`).
- **A42 (baixo)** — depois de reiniciar, um item que estava em envio só é retomado quando o lease vence, em até 120 s (`backend/api/config.py:205`). Atrasa, mas não perde. Com o observatório ligado, cada apontamento grava uma linha em arquivo dentro do laço de eventos (`recorder.py:126-132`).

**Não verificado na Etapa 7:** `tests/test_totvs_outbox.py` (cria schema); comportamento com banco ou rede fora do ar; reinício real com item em envio; tempo com e sem observatório; se o observatório está ligado na 8001.

## Etapa 8 — Desempenho

Relatório: `dev_reports/revisao/ETAPA8_DESEMPENHO.md`. Os scripts de medição estão no scratchpad (`bench.py`, `bench2.py`).

**Como foi medido:** sem senha de teste, nenhuma rota com login foi medida pela API. As rotas abertas responderam em 5 a 13 ms. As funções de leitura foram medidas direto no `gestor_pecas_test`, com conexão só de leitura: é o tempo do banco, sem rede nem login. O banco de teste tem pouco dado (38 recursos).

**Tempos médios (máximo a frio):** Andon da TV 190 ms (476), 53 KB · snapshot do stream 156 ms · gestão "agora" 2 ms · painel de 1 mês 35 ms (345) · OEE de 1 dia 18 ms · OEE de 1 mês 158 ms (1.323) · perdas de 1 mês 333 ms · cartões do operador 25 ms · fila do Corte 97 ms (546). Nada passou de 1 s na média. O período máximo é limitado a 366 dias (`backend/api/dependencies/filters.py:91-95`).

- **A43 (médio)** — a fila do Corte devolve 1,44 MB de JSON para 90 tarefas, sem paginação (`backend/api/routers/cutting.py:80`). Uma só tarefa chega a 162 KB, 108 KB deles só de `planos`. Pesa na rede e no tablet do operador.
- **A44 (médio, tela)** — o site é um pacote único de 1,24 MB (368 KB comprimido), sem carregamento por tela: não há `lazy(` em `web/src`. A TV com Chrome 79 baixa todas as telas no primeiro acesso.
- **A45 (baixo/médio)** — só 2 leituras da gestão rodam ao mesmo tempo, e a fila de espera não tem prazo (`backend/api/config.py:143`, `backend/api/dependencies/bulkhead.py:16`). Duas exportações longas seguram o painel de todos os gestores. O CSV e o Excel são montados inteiros na memória (`backend/api/routers/reports.py:234-246, 263-264`), o que se liga ao A35.
- **A46 (baixo)** — cada conexão do stream refaz o snapshot completo a cada 15 s (`backend/api/routers/operations.py:155-165`). Com 156 ms por vez, 20 conexões dão cerca de 21% de um núcleo; com 3 a 5 telas o custo é desprezível.

**Não verificado na Etapa 8:** todas as rotas com login pela API (tempo com rede e gzip); exportação de 1 mês em paralelo com outras rotas; A26, porque a fila do Destaque veio vazia; A30, cuja função não foi localizada; memória da API sob o polling do Andon. Falta confirmar na TV física se ela usa o stream (`operations.py:131`) ou o polling de 30 s (`web/src/pages/AndonPage.tsx:322-326`). Para medir pela API é preciso uma senha de teste.

## Etapa 9 — Qualidade do código

Relatório: `dev_reports/revisao/ETAPA9_CODIGO.md`.

**OK:**
- Nenhum router escreve SQL; todos chamam a fachada do banco ou serviços.
- Não há nome indefinido (F821) nem redefinição (F811).
- A leitura estática não achou nenhum ciclo de import entre os 239 módulos. `python -c "import backend.api.main"` rodou sem erro: eu mesmo rodei; importar cria o app (`main.py:1059`), mas não roda o lifespan.
- Os 17 imports dentro de funções carregam sob demanda e não escondem ciclo.

- **A47 (médio)** — 11 funções passam de 150 linhas. As maiores:
  - `get_overview`, com 789 linhas (`mes/services/management.py:61`);
  - `executar`, com 679 (`mes/services/operator_flow.py:955`);
  - `transicionar_apontamento_operador`, com 451 (`app/database/database.py:2412`).

  São difíceis de testar por partes. Sugestão: dividir por bloco quando forem alteradas, não de uma vez.
- **A48 (baixo)** — o projeto não tem linter nem checagem de tipos no CI: ruff e mypy não estão instalados nem citados em requirements, pyproject ou workflows. Avisos menores achados por outro meio:
  - variável sem uso em `backend/api/report_workbook/executive.py:322`;
  - import sem uso em `mes/services/sigmanest_sync.py:30`.
- **A49 (baixo, possível)** — a regra que esconde o caminho de rede do desenho está implementada duas vezes: `backend/api/routers/operator.py:524` e `backend/api/routers/quality.py:478`. Não foi confirmado se as duas são idênticas.

**Não verificado na Etapa 9:**
- contagem de avisos do ruff e do mypy, porque as ferramentas não estão instaladas;
- duplicação além do grafo.

## Etapa 10 — Testes

Relatório: `dev_reports/revisao/ETAPA10_TESTES.md`.

**OK:** todo `test_*.py` roda no CI, e o smoke e2e só roda sob demanda (`e2e.yml:30`). A falha do Protheus tem boa cobertura: timeout, 5xx, autenticação e XML inválido, quase tudo sem criar schema.

- **A50 (ALTO)** — o CI está vermelho desde 04/11: as 6 últimas execuções falharam (conferi com `gh run list`). Na mais recente, 8 de 2.335 testes falham, e são exatamente o A11 e o A12. O `deploy.yml:16-25` chama o `ci.yml` como `validate`, e nenhum job de deploy começa sem ele. Resultado: **o deploy por tag está bloqueado**, e uma falha nova passaria despercebida no meio das antigas. A correção é consertar os testes do A11 e do A12.
- **A51 (médio)** — os testes de regra que rodam sem banco (184 passam) cobrem 78% de `mes/domain` e `mes/analytics`. Ficam de fora trechos críticos:
  - dia fora do turno (`manufacturing_rules.py:288`, ligado ao A14);
  - parada planejada × não planejada (`:431-455`);
  - hora extra planejada (`:562-573`);
  - janela que cruza a meia-noite (`:514-518`, `:536`, `:539`);
  - mensagens de transição inválida (`operator_state_machine.py:202-251`, ligado ao A15);
  - dois operadores no mesmo recurso (`:361-367`).
- **A52 (médio)** — há testes de permissão em 34 arquivos, mas nenhum percorre todas as rotas conferindo 401 sem login e 403 com o nível errado. Uma rota nova sem proteção não seria notada. A matriz da Etapa 1 (`matriz_acesso.py`, no scratchpad) pode virar esse teste.
- **A53 (médio)** — dois testes que não protegem nada:
  - `test_oee_evolution_equivalence.py:89` é pulado sempre que o banco não tem dados de julho/2026, então no CI nunca prova nada;
  - `test_kpi_explanation_adversarial.py:611` é um `expectedFailure` que esconde um bug aberto: a linha "Não informado" de `resource_kpis` faz a Performance e a A.E. não fecharem.
- **A54 (baixo)** — outros testes pulados ou sem efeito:
  - o pulo em `test_area_queue_adversarial.py:589` pode esconder uma regressão da Solda;
  - `test_web_api.py:1638` nunca roda no CI, porque o job não faz o build do React;
  - o SigmaNEST só tem teste do caminho feliz, sem teste de falha ao abrir o ODBC.
- **Lacuna local (não é bug):** 30 arquivos (649 testes) criam schema. Aqui ficam pulados e só rodam no CI, que tem PostgreSQL 17: concorrência, ordem de trava, migrations, estado de recurso e RNC.

**Não verificado na Etapa 10:**
- a cobertura dos testes com banco, porque o CI não mede cobertura;
- a cobertura de `quality_measures.py`;
- quais 3 testes o CI pula.

## Etapa 11 — Ponta a ponta (um dia de fábrica)

Rodado no TEST em 05/11/2026, com ids em `dev_reports/revisao/ponta-a-ponta.md`.

**OK:** o fluxo principal fecha: Corte (apontamento 5) → Dobra (apontamento 34) → Qualidade (inspeção 1) → Protheus TEST. A op 99 da OP 00601315031 saiu uma vez só (outbox 9). O OEE do setor Dobra bate com a conta manual (89,29%), e o relatório na tela, no Excel simples e no Excel técnico mostra os mesmos números.

- **A55 (ALTO)** — a op 99 nunca sai quando o plano do Corte foi concluído no SigmaNEST. A fila do Corte tira o plano que tem `sigmanest_comp_date`, mas `corte_origem` (`app/database/totvs_outbound_repository.py`) e `_corte_concluido_sql` (`app/database/database.py:130`) ignoram essa data. Assim a OP espera para sempre um Corte que ninguém vai apontar. Caso visto: OP 00601315032.
- **A56 (ALTO)** — o OEE por máquina não fecha. A quantidade (`eventos_quantidade_producao.recurso`) é gravada com o nome do posto ("1303", "Gasparini", "INSPEC"), mas o tempo e a linha do tempo usam o código ("DOBRA3", "DOBRA1"). Por isso:
  - `?recurso=DOBRA3` mostra 0 boas;
  - `?recurso=1303` mostra 5 boas, mas sem Performance;
  - `resource_kpis` lista as duas como máquinas separadas;
  - o relatório conta "Recursos utilizados 5".

  O total do setor está certo. A tela real manda o nome (`web/src/pages/operator/WorkbenchPage.tsx:692`), então o problema acontece na fábrica, não é efeito do teste. A correção é gravar o código canônico do recurso na quantidade. Vale conferir também se os dados antigos precisam de ajuste.
- **A57 (médio)** — a Qualidade grava a peça e devolve erro. Ao registrar a última peça, `registrar_peca` (`mes/services/quality.py:692`) grava a peça e a RNC e depois chama `_finalizar`. Se o tempo mínimo da operação ainda não passou, a chamada devolve 409 `duracao_minima_nao_atingida`. O inspetor vê erro, mas a peça e a RNC (RNC-1-0002) já ficaram salvas, e na nova tentativa ouve "todas já inspecionadas". A gravação e a finalização precisam ser uma coisa só, ou a resposta precisa dizer "peça salva, finalização pendente".
- **A58 (médio)** — um erro funcional na outbox trava a OP para sempre. O caso visto foi o "A680OPTOT" do Protheus, nas outbox 1 e 3, e não existe tela para reenviar ou descartar. Hoje só o script `scripts/totvs_outbox_admin.py` resolve.
- **A59 (médio)** — o sistema deixa iniciar uma OP que o Protheus já tem totalizada. O erro só aparece depois, na outbox (A58). Falta checar isso antes do início.
- **A60 (médio, confirmar regra)** — uma OP só com INSPEC (não apontável), com a op 99 inativa, nunca encerra no Protheus. Caso visto: OP 00601315034, que ficou sem marco de encerramento. É preciso confirmar com o negócio se é o esperado.
- **A61 (médio, confirmar regra)** — o recurso que termina o trabalho depois do fim do turno vai para "sem demanda" no Andon, e não para "fora do turno". Caso visto: LASER1 e DOBRA3, que terminaram às 17:37 com o turno acabando às 17:30. Já o DOBRA1, parado, mostrou "fora do turno".
- **A62 (baixo)** — a decisão de RNC "sucatear" responde 200, mas com `code` e `message` vazios. Quem chama não tem confirmação legível.
- **A63 (baixo)** — o acento chega quebrado no retorno (ACK) do Protheus ("OperaÃ§Ã£o"), um problema de codificação ao ler a resposta.
- **A64 (baixo)** — o SigmaNEST marca `dobra='SIM'` em OPs que não têm Dobra no roteiro do Protheus. Não deve virar regra sem conferir o roteiro.
- **A65 (baixo)** — a sincronização devolveu status vazio para PCLZRR01002 e PCLJVX01006. Desde as 12:12 do dia 05/11, a sincronização do SigmaNEST registra falhas. Isso é ligado ao A4 e precisa de investigação.
- **A66 (baixo, confirmar regra)** — o fim do Corte não manda nada ao Protheus. Só a Dobra e a Qualidade geram outbox. Se o Corte também deve apontar no ERP, falta o envio.
- **A67 (baixo)** — o texto da primeira peça confunde o operador: não deixa claro se ele está "produzindo a peça" ou "pedindo a inspeção".

**Ambiente (não é bug do código):** o `.env` deste notebook aponta para `production` e para o banco `gestor_pecas`, que não existe aqui. Para rodar a API, é preciso sobrescrever as duas coisas, como já foi feito nesta sessão.

**Não verificado na Etapa 11:**
- a tela (só API e banco);
- a TV física do Andon;
- o cálculo com volume real de um turno inteiro (os tempos do teste são de segundos).

## Etapa 12 — Configuração e entrega

Os testes chamaram `WebSettings.from_env` e `load_postgres_config` com ambientes montados à mão, num processo separado. A API 8001 não foi tocada.

**OK:**
- sem banco configurado, a API se recusa a subir com uma mensagem clara ("Defina DATABASE_URL ou PGHOST/PGDATABASE/PGUSER");
- em produção, sem `GESTOR_WEB_SESSION_SECRET` ou com um segredo de menos de 32 bytes, ela também se recusa a subir;
- quando nada é configurado, Protheus, SOAP, outbox, SigmaNEST, Telegram, IA e relatórios automáticos ficam desligados;
- em produção, o cookie só trafega por HTTPS;
- a documentação da API e as ferramentas de desenvolvimento só abrem quando o ambiente está numa lista permitida: test ou development;
- CI, e2e, instalador da VM e manual usam a mesma versão do Python, 3.14 (o notebook roda a 3.14.7);
- o instalador da VM gera os dois segredos e grava o observatório como desligado;
- o deploy faz backup antes, instala as dependências com hash conferido e depende do CI (A50).

- **A68 (médio)** — o nome do ambiente é tratado de dois jeitos. As ferramentas de desenvolvimento usam lista permitida, mas o segredo obrigatório e o cookie seguro só valem para os nomes "production", "producao" e "produção" (`backend/api/config.py:320`, `:456`). Num servidor com `GESTOR_WEB_ENV=homologacao` ou `prd`, a API sobe sem segredo fixo e com o cookie fora do HTTPS. Testei: `homologacao` subiu com `cookie_secure=False`. A correção é usar a mesma lista: tudo o que não for test ou development é tratado como produção.
- **A69 (baixo)** — uma integração ligada sem credencial sobe sem aviso. Testei `GESTOR_TOTVS_ENABLED`, `GESTOR_TOTVS_OUTBOX_WORKER_ENABLED`, `GESTOR_SIGMANEST_SYNC_ENABLED`, `TELEGRAM_ENABLED` e `GESTOR_AI_ENABLED` como `true`, sem URL, DSN, token ou chave: a API sobe. O erro só aparece depois, no laço de segundo plano. Só o SOAP confere a dependência. A correção é recusar a subida ou avisar com clareza na inicialização (e no `/system/ready`).
- **A70 (baixo)** — `GESTOR_TOTVS_MODEL_PULL_*` (endpoint, usuário e senha) continua em `deploy/totvs-real.env.example:17`, em `.env.example:119-120` e em `deploy/montar_pacote.py:42`. O código não lê mais essas variáveis: a busca do B1_ZMODELO foi removida em 07/10. Quem instala pode achar que precisa preencher. A correção é tirar dos exemplos.
- **A71 (baixo)** — `deploy/env-vm.example` não traz `GESTOR_DEVOBS_SESSION_SECRET`. Numa instalação manual a partir dele, cada início da API registra um log **ERROR** (`config.py:339-341`), mesmo com o observatório desligado. Isso é ruído que esconde erro de verdade. O instalador automático gera o segredo, então só a instalação manual é afetada.
- **12.4 Documentação:** `docs/STATUS_ATUAL.md` está atualizado até 05/11. Reflete o código nos pontos conferidos: aba Manutenção removida, tempo padrão só do Protheus, Corte só apontado e manual no sistema. Recebeu uma nota apontando para esta revisão. A A7 (observatório ligado por padrão) continua aberta.

**Não verificado na Etapa 12:**
- a subida real da API num servidor limpo (só testei a leitura da configuração);
- o `nginx.conf` contra as portas atuais;
- o deploy por tag de ponta a ponta, que está bloqueado pelo A50.

## Correções de 06/11/2026 (não commitadas)

Corrigidos e provados no TEST (API 8001, `gestor_pecas_test`, Protheus TEST ligado):

- **A50** — testes do A11/A12 consertados (`tests/test_manutencao_sugestoes.py`, `mes/services/management.py`, `mes/services/frontend_facade.py`); CI deve voltar a verde.
- **A55** — plano com `sigmanest_comp_date` conta como Corte concluído em `corte_origem` e `_corte_concluido_sql`; a op 99 da OP 00601315032 deixa de esperar Corte.
- **A56** — nome do posto e código são a mesma máquina: quantidade gravada pelo código (`resolve_resource_identity`), filtro de recurso aceita os dois (`resource_identity_names`, em `app/core/resource_mapping.py`) e a gestão agrupa pelo código. Prova (05/11): `?recurso=DOBRA3` e `?recurso=1303` dão o mesmo resultado (5 boas, A 83,2%, FTT 100%); setor Dobra lista só DOBRA1/DOBRA2/DOBRA3, sem linhas "1303"/"Gasparini". A Performance da DOBRA3 fica vazia de propósito: as OPs 031, 032 e PCLILX01003 não têm tempo padrão.
- **A57** — a última peça da Qualidade não devolve erro depois de gravar; a tela trata o encerramento pendente.
- **A58** — envio em ERRO pode ser descartado com motivo: status `DISCARDED` (migration 73, SCHEMA_VERSION 73), script `scripts/totvs_outbox_admin.py descartar` e rota só de admin `/api/v1/admin/totvs-outbox` (listar, `/{id}/reprocess`, `/{id}/discard`). Recusa devolve 409/404 com mensagem clara. Itens 2 e 3 (A680OPTOT) descartados no TEST. Falta a tela de admin.
- **A59** — OP com `status_pcp='7'` (encerrada no Protheus) não aceita novo apontamento.
- **A60** (decisão do usuário: deve encerrar) — OP só com INSPEC entra no marco terminal usando as operações apontadas não terminais. OP 00601315034 gerou o item 12 (op 99); o Protheus TEST recusou por **falta de saldo** do componente 5001000001 no armazém 08 (dado do TEST, não código).
- **A61** (decisão do usuário: fora de turno) — quem termina depois do fim do turno, inclusive na hora extra planejada, volta para Fora de turno. O teste `test_op_encerrada_na_hora_extra_planejada_entra_em_fora_de_turno` substituiu o antigo, que esperava "sem demanda".
- **A68** — todo ambiente fora de `test`/`development` exige segredo de sessão e liga o cookie seguro por padrão (`tests/test_config_environment.py`).
