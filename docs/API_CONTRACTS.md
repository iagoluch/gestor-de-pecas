# Contratos da API Web

Base local: `/api/v1`. Especificação navegável: `/api/docs`. OpenAPI: `/api/openapi.json`.

## Convenções

- Autenticação por cookie de sessão assinado e `HttpOnly`.
- `POST` autenticado requer cookie `gestor_csrf` e header `X-CSRF-Token` com o mesmo valor.
- Filtros comuns: `inicio`, `fim`, `setor`, `recurso`, `turno`, `op`, `operacao`, `produto`, `operador`.
- Paginação: `page` a partir de 1 e `page_size` entre 1 e 200.
- Erro padronizado: `{ "code", "message", "request_id", "details" }`.
- Respostas da API recebem `Cache-Control: no-store`, `X-Request-ID` e headers de proteção.
- Ausência industrial é expressa por `availability`, normalmente `disponivel`, `parcial`, `nao_configurado`, `dados_insuficientes`, `sem_registros` ou `inconsistente`.
- Esses valores são contrato e continuam no backend. A tradução para texto de tela é responsabilidade exclusiva da apresentação (`web/src/utils/systemState.ts`): nenhuma tela mostra o identificador cru (Wave 6E).

## Autenticação e sistema

| Método | Rota | Uso |
|---|---|---|
| `POST` | `/auth/login` | autentica no cadastro atual e cria sessão |
| `GET` | `/auth/session` | retorna usuário, perfil e acessos |
| `POST` | `/auth/logout` | encerra sessão; exige CSRF |
| `GET` | `/system/health` | saúde, schema e conectividade sem expor DSN |
| `GET` | `/system/capabilities` | capacidades e limites da migração atual |

## Management View

| Método | Rota | Uso |
|---|---|---|
| `GET` | `/management/overview` | produção, KPIs, tempo, setores e auditoria |
| `GET` | `/management/sectors` | consolidação por setor |
| `GET` | `/management/alerts` | alertas e confiabilidade |

## Gestão à vista

| Método | Rota | Uso |
|---|---|---|
| `GET` | `/andon` | snapshot fabril consolidado por setor/recurso |
| `GET` | `/welding` | acompanhamento gerencial da Solda por estação observada |

`/welding` é somente leitura, não recebe filtro de período e usa a mesma
autorização do Andon, porque a tela de gestão e o ciclo da TV consomem a mesma
projeção. A resposta traz `estacoes[]` (estação observada, `op_count` e `ops[]`),
`resumo` e `availability`. Cada linha é `(OP, operação de Solda do roteiro)` e
mantém a identidade canônica da OP (`codigo_op`).

- `modelo` e `estacao` são `{ value, availability }`: sem valor real, o estado é
  `nao_configurado` (modelo) ou `sem_registros` (estação) e quem escreve o texto
  humano é a apresentação. O backend nunca inventa o valor.
- `status.value` é `A VENCER`, `ATRASADA`, `FINALIZADA` ou ausente. Ausente
  significa que a OP não tem base temporal conhecida (`dados_insuficientes`), e
  `status.reason` explica a situação.
- `datas.referencia_prazo` e `datas.criacao` declaram qual campo foi usado
  (`label`) e se a leitura é `disponivel` ou `parcial`.

## Consulta Operacional

| Método | Rota | Uso |
|---|---|---|
| `GET` | `/operations/overview` | estado físico atual e resumo composto no servidor |
| `GET` | `/operations/resources` | recursos paginados |
| `GET` | `/operations/orders` | OPs em andamento |
| `GET` | `/operations/time` | composição canônica de tempo MES |
| `GET` | `/operations/stream` | stream SSE autenticado |

## Produção

| Método | Rota | Uso |
|---|---|---|
| `GET` | `/orders` | ordens paginadas; busca e status no servidor |
| `GET` | `/orders/production` | peças boas, refugo e retrabalho separados |
| `GET` | `/orders/planned-vs-actual` | plano somente leitura comparado ao realizado |

## Análises

`GET /analytics` retorna o conjunto. Rotas específicas: `/analytics/oee`, `/analytics/hours-utilization`, `/analytics/downtimes`, `/analytics/setups`, `/analytics/quality`, `/analytics/standard-vs-actual`, `/analytics/chronoanalysis` e `/analytics/capacity`.

O contrato de OEE mantém `value` no nível superior por compatibilidade e também expõe `components`. Os percentuais usam a escala `0..100`; valores sem fatos suficientes permanecem nulos com motivo. O cliente não completa a fórmula.

O estado de `evolution` é independente do indicador atual. Sem série histórica,
o card atual continua disponível e somente a evolução informa insuficiência.

## Auditoria, rastreabilidade e relatórios

| Método | Rota | Uso |
|---|---|---|
| `GET` | `/audit/appointments` | apontamentos e fonte |
| `GET` | `/audit` | inconsistências paginadas |
| `GET` | `/audit/reliability` | cobertura e confiabilidade sem percentual inventado |
| `GET` | `/traceability/orders/{op}` | OP, operações, eventos, estados, rateio, operadores e registros originais |
| `GET` | `/traceability/nestings` | nesting/lote/material, com tempo total e período separados |
| `GET` | `/reports/{tipo}` | `gerencial`, `producao`, `perdas`, `indicadores`, `dados_analiticos` |
| `GET` | `/reports/{tipo}/export.csv` | CSV separado por `;`, UTF-8 com BOM |

## Operador comum

| Método | Rota | Uso |
|---|---|---|
| `GET` | `/operator/context` | setor, recursos exatos, fila automática e fluxo derivados da sessão |
| `GET` | `/operator/stations` | estações de Solda com estado `Livre`, `Ocupada` ou `Selecionada` |
| `GET` | `/operator/operations/{op}` | roteiro completo da OP para o setor autenticado |
| `GET` | `/operator/workbench?resource=` | cartões de Produção e Fila do recurso validado |
| `GET` | `/operator/history?resource=&page=&page_size=` | histórico paginado; `page_size` entre 1 e 100 |
| `GET` | `/operator/stop-reasons?search=` | catálogo de parada pesquisável |
| `POST` | `/operator/actions` | Início, Parada/Retomada, Setup, Retrabalho e Finalizado |

O body de `/operator/actions` identifica OP, operação e recurso, mas o servidor não confia na descrição enviada pela UI: ele recarrega a operação no roteiro vigente. Quantidade boa, refugo e retrabalho permanecem campos separados. Finalização parcial conserva a operação aberta. Exceções de recurso/roteiro exigem confirmação e crachá. Operação concluída não é reaberta pelo fluxo normal.

Para Solda, o `POST` de Início verifica novamente a ocupação da estação, mesmo que a seleção visual estivesse desatualizada. Uma estação ocupada por outro operador retorna `409` com `code=operator_resource_occupied`.

## Corte e Destaque

| Método | Rota | Uso |
|---|---|---|
| `GET` | `/cutting/queue?resource=&search=` | fila automática filtrada no servidor: cada tarefa traz `planos[]` (programa, estado, chapas/repetição, `ops[]` com produto) e `nestings[]` com os tempos de cada chapa |
| `POST` | `/cutting/actions` | Início, Parada, Retomada e Finalizado por apontamento/nesting |
| `GET` | `/highlight/tasks/{codigo}` | tarefa, OPs, estado e tempos calculados no backend |
| `POST` | `/highlight/actions` | Início, Parada e Fim; Fim exige crachá válido |

O Corte preserva `tempo_previsto_segundos` e `tempo_real_segundos` em cada elemento de `nestings`; o total agregado não substitui esses valores. O Destaque devolve `execution_seconds`, `stopped_seconds`, `started_at`, `state_since` e `current_mode`, evitando cronômetros industriais calculados no navegador.

## Limites atuais

Não existem endpoints de Correção/Edição gerencial. O contrato corporativo Protheus/TOTVS permanece pendente de definição pela TI. A validação executada com `ApiFakeDatabase` não comprova conectividade, locks ou volume do PostgreSQL/Qlik de produção.
