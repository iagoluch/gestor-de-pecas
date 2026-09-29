# API.md — Gestor de Peças

Extraído do `AGENTS.md` em 2026-09-29; tem a mesma força normativa do `AGENTS.md`.

Contratos HTTP detalhados: `docs/API_CONTRACTS.md`; arquitetura Web: `docs/WEB_ARCHITECTURE.md`.

## Separação backend / frontend

Código novo em `mes/domain`, `mes/analytics`, `mes/services`, `mes/repositories` e `mes/contracts` não deve depender de FastAPI, React ou componentes visuais.

O frontend Web deve:

- consumir contratos/casos de uso do backend;
- não consultar tabelas diretamente;
- não recalcular OEE, tempos, produção, rateio ou confiabilidade;
- não inferir valor faltante;
- apresentar `availability/reason/source` quando o backend expuser incerteza;
- manter a mesma verdade em todas as telas e exportações.

### Estado interno x texto de tela (Wave 6E)

O estado interno continua no backend: `sem_registros`, `dados_insuficientes`,
`nao_configurado`, `parcial` e equivalentes permanecem no contrato e não devem
ser removidos, renomeados nem convertidos em zero. Quem traduz é a apresentação.

O caminho é sempre **backend (estado técnico) → camada de apresentação → texto
humano**. Essa camada é única: `web/src/utils/systemState.ts`
(`humanizeSystemState`, `systemStateSentence`, `availabilityLabel`,
`humanizeSystemStateIn`) e, para a resposta da IA,
`web/src/utils/assistantText.ts`. Não espalhar `if status === "..."` por
componente nem criar uma segunda tabela de tradução.

Nenhuma tela mostra identificador técnico, chave interna, nome de campo/tabela,
SQL ou exceção. Tela sem dado usa estado vazio explicado — nunca zero
artificial, `N/A`, `null`, `undefined`, array vazio ou nome de enum. O estado
técnico pode continuar em atributo de estilo (`data-availability`), que não é
texto lido pelo usuário.

A IA fala como sistema de gestão industrial. O mecanismo (provider, streaming,
modelos, tool calling, consultas, persistência) não muda por motivo de texto: a
apresentação da resposta é ajustada no frontend.

A camada `FrontendBackendFacade` continua sendo uma fronteira de casos de uso compartilhada. A API FastAPI existente deve adaptar/consumir essa camada e os serviços canônicos, nunca reimplementar regras no transporte HTTP.

O Management View não deve possuir aba/card de **Correção** ou **Edição**. Auditoria e versionamento podem existir no backend, mas não devem reaparecer como módulo visual gerencial sem nova decisão explícita.

## Arquitetura e integração corporativa — TOTVS e SigmaNEST

Estado confirmado em TESTE (27/08/2026):

- `WhoIs` do PCPA109 homologado;
- `ProductionOrder/upsert` do PCPA111 homologado;
- planejamento TOTVS chegando à fila e à Tela do Operador canônicas (Etapa 3);
- endpoint SOAP `PcfIntegService.receiveMessage`;
- banco TESTE oficial `gestor_pecas_test`, migration 16;
- OP real `A9716901001` recebida e persistida;
- resposta de sucesso é `TOTVSMessage/ResponseMessage` com `ProcessingInformation/Status=OK`; texto puro `OK` **não** é o contrato bruto;
- `OK` visto em `SOF010` é resultado normalizado pelo Protheus após parse;
- retorno Gestor → TOTVS possui mapper/gateway manual controlado para
  `ProductionAppointment` e `StopReport` (Etapa 5, 31/08/2026), mas ainda não
  foi homologado ponta a ponta no WSPCP TESTE. Em 01/09/2026, o WSDL externo
  `:1465/ws/WSPCP.apw?WSDL` e o transporte SOAP 1.1 foram comprovados; o POST
  técnico anônimo foi recusado com `AUTHENTICATION: USER NOT AUTHORIZED`, e a
  credencial REST via HTTP Basic depois retornou HTTP 200 com ACK estruturado
  para `CXML` vazio. Faltam OP descartável e códigos de motivo.
  Outbox/retry/reconciliação não foram implementados.

Para mapeamento de roteiro/recurso/setor, não usar fuzzy matching ou equivalência implícita. Recurso/etapa sem semântica aprovada permanece não projetado e auditável.

No outbound da Etapa 5, o serviço WSPCP/ReceiveMessage e os despachos
`ProductionAppointment → MATA681` e `StopReport → MATA682` foram comprovados.
Isso não autoriza novas transações nem produção REAL. Não assumir contrato por
nomes isolados em código/tabelas; qualquer ampliação continua exigindo
fonte/XSD/WSDL e comportamento real comprovados.

Busca de OP sob demanda (Etapa 6.1, 02/09/2026): o Protheus **não** oferece
mecanismo suportado para o Gestor solicitar uma OP. Provado no TESTE: o
`WSPCP.apw` implementa só `productionappointment` e `stopreport`
(`ProductionOrder` → "Transação não implementada"); o EAI genérico não tem
adapter `ProductionOrder` registrado; `totvseai/standardmessage/v1/contents`
responde HTTP 500; os serviços padrão de OP foram
validados a fundo e **descartados** (decisão C): `MTPRODUCTIONORDER` não traz
roteiro nem descrição de produto, `POOPERATION` não traz descrição de operação,
nenhum dos dois aceita empresa/filial (publicação presa em `01/010001`, e
`tenantId` é ignorado) e ambos respondem `PRTCHKUSER`. Liberar o `PRTCHKUSER` ou
publicar para `010004` **não** resolve, porque a assinatura de classificação do
mapper canônico é `(ActivityCode, ActivityDescription, WorkCenterCode,
MachineCode)` — sem `ActivityDescription` o roteiro inteiro e o marco terminal
deixam de ser reconhecidos. O REST `/api/pcp/v1/productionOrders` só devolve
cabeçalho. Não reabrir essa investigação sem fato novo. A busca sob demanda está
implementada no Gestor e reutiliza o pipeline inbound canônico; ela liga quando
`GESTOR_TOTVS_OP_PULL_ENDPOINT` aponta para o endpoint customizado de
`fontes/10-PCP/GPOPSYNC.prw`, compilado/publicado e homologado no TESTE em
03/09/2026 (contrato em `protheus/README.md`). Esse fonte reaproveita a montagem oficial
`MATI650("", TRANS_SEND, EAI_MESSAGE_BUSINESS, "2.004")` — a mesma que o
`PCPa650PPI` usa — e por isso devolve o ProductionOrder canônico inline.
**Não criar uma segunda implementação de importação de OP** e não montar
`ProductionOrder` à mão a partir de SC2/SG2/SHY ou das APIs REST de cabeçalho.

A camada de execução não conhece a origem do planejamento. `backend/api/routers/operator.py`
não pode mencionar TOTVS: a busca de OP passa pela fronteira neutra
`mes/services/order_provisioning.py`, e existe teste que falha se essa regra for
quebrada.

**Nunca escrever diretamente em tabelas TOTVS** para integrar execução. O retorno deve usar mecanismo suportado e uma camada de outbox/retry/reconciliação depois de o contrato ser comprovado.

A fonte oficial do planejamento específico de Corte é o **banco do SigmaNEST**. A OP é **do produto**: tarefa, plano e nesting são agrupamentos que contêm produtos e não possuem OP própria, e um mesmo agrupamento pode conter produtos de OPs diferentes. Nunca modelar `tarefa.codigo_op`, `plano.codigo_op` ou `nesting.codigo_op` como relação 1:1, nem criar OP a partir do SigmaNEST. A correlação foi comprovada em 27/08/2026 com dados reais: `TOTVS ProductionOrder.Number` é textualmente igual a `SigmaNEST Wo.WONumber`, e a OP aparece na linha de peça (`STPIPArc.WONumber` / `Part.WONumber`). O código de produto **não** é chave: em 15% dos casos ele diverge entre Protheus e SigmaNEST. Todo SQL do SigmaNEST vive exclusivamente em `backend/integrations/sigmanest_sqlserver.py`, com acesso somente leitura; o restante do Gestor consome apenas os DTOs de `mes/integrations/sigmanest`. Ver `docs/INTEGRACAO_CORTE_SIGMANEST.md`.

Desde a Wave 2, a materialização do planejamento de Corte é **automática**: o
processo Web executa em ciclo o mesmo `SigmaNestSyncService` do script manual
(`_sigmanest_sync_loop` em `backend/api/main.py`), somente leitura na origem,
incremental e idempotente, publicando invalidação SSE apenas quando a projeção
muda. **Não criar um segundo pipeline SigmaNEST.** A pesquisa da fila de Corte é
filtro do que já está disponível, nunca o mecanismo que descobre ou importa a
tarefa.

**No on-demand TOTVS, "cabeçalho sem roteiro" não é resposta terminal enquanto há
sincronização em curso** (08/09/2026). A ingestão grava o cabeçalho da OP antes
das operações do roteiro; durante essa janela o chamador precisa virar seguidor e
esperar dentro do próprio `timeout_seconds`, nunca devolver `sem_roteiro`. O
sinal é `totvs_op_sync_requests.status = PENDING`. Não transformar essa espera em
laço ilimitado nem em segunda chamada ao ERP.

**Sincronização do Corte é observável.** O ciclo automático e o botão
"Atualizar tarefas" passam pelo mesmo `SigmaNestRefreshCoordinator`
(`mes/services/sigmanest_refresh.py`), serializado por um `asyncio.Lock`: um
clique durante um ciclo em andamento adere a ele em vez de abrir um segundo. A
tela mostra a última sincronização e, quando a origem falha, preserva a fila
local com mensagem de operador — sem vazar traceback, ODBC ou SQL. A marca
d'água é `MAX(catalogo_sigmanest_planos_corte.data_programa)` recuada por
`DEFAULT_OVERLAP_DAYS = 7`; a releitura sobreposta é segura porque a projeção é
idempotente.
