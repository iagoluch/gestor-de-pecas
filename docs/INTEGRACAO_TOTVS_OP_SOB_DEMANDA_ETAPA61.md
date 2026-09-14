# Integração TOTVS — busca de OP sob demanda (Etapa 6.1)

Data: 02/09/2026
Ambiente investigado: **TOTVS TESTE / `CSED4J_DEV`** — `gtsdo143182.protheus.cloudtotvs.com.br`
Banco do Gestor: **`gestor_pecas_test`** (migration 20)

O TOTVS REAL (`gtsdo142364…`) e o banco `gestor_pecas` REAL não foram tocados.

## Objetivo

Quando o operador digita uma OP que ainda não existe no Gestor, o Gestor deve
pedi-la ao TOTVS e carregá-la sozinho, pelo **mesmo** pipeline inbound já
homologado. O operador não deve abrir o PCPA109 nem saber se a OP já foi
sincronizada antes.

## 1. Descoberta — existe mecanismo oficial de *pull* de OP?

**Não existe.** A conclusão vem de resposta do próprio ambiente, não de
inferência. Todas as sondagens foram somente-leitura, sobre o TESTE, usando a
credencial REST já configurada.

### 1.1 WSPCP — o serviço que a integração homologada realmente usa

`https://…:1465/ws/WSPCP.apw?WSDL` publica **uma única operação**:
`RECEIVEMESSAGE`. Enviando `TOTVSMessage` com `Transaction=ProductionOrder`:

```text
<Status>ERROR</Status>
<Message type="ERROR" code="1">Transação "PRODUCTIONORDER" não implementada.</Message>
```

Varredura de transações no mesmo serviço (`SourceApplication=GESTOR_PECAS`):

| Transação enviada | Resposta do WSPCP |
| --- | --- |
| `productionappointment` | **implementada** (`ProductionOrderNumber é obrigatório.`) |
| `stopreport` | **implementada** (`A versão da mensagem informada não foi implementada!`) |
| `productionorder`, `whois`, `resource`, `resourcestatus`, `productionorderstatus`, `subproduct`, `operator`, `machine`, `item`, `productionorderrequest`, `requestproductionorder`, `syncproductionorder`, `productionorderquery`, `customexport`, `materialrequest`, `productionevent`, `resourceevent`, `wostatus`, `order` | `Transação "…" não implementada.` |

[CONFIRMADO] O WSPCP é **unidirecional para execução**: `ProductionAppointment`
e `StopReport`, Gestor → Protheus. Ele **não** possui operação de buscar OP.
A suspeita registrada no §3 do enunciado da etapa está comprovada.

### 1.2 EAI genérico

`EAISERVICE.apw` e `FWWSEAI.apw` estão ativos (`GETSTATUS` → `OK`), mas:

```text
Mensagem PRODUCTIONORDER nao configurada ou configurada incorretamente
para processamento pelo EAI
```

O registro de adapters do ambiente confirma a causa
(`GET /rest/totvseai/monitor/v1/apps/CSED4J_DEV01@PROTHEUS/transactions`):

```text
11 adapters registrados:
orderassignmentsinformation, paymentcondition (1.000/2.000/3.000),
project (2.000), request (1.001…1.005)
```

Nenhum adapter `ProductionOrder`. E `configurator/v1/apps` lista **um único
aplicativo**, o próprio Protheus (`isHost=true`) — não há aplicação externa
cadastrada no EAI. O caminho PPI/PCFactory não passa pelo EAI genérico.

### 1.3 Serviço oficial que roda o adapter e devolve o conteúdo

`GET /rest/totvseai/standardmessage/v1/contents/{transactionID}[/{InternalID}]`
("retorna um item solicitado de um adapter no padrão content") seria o
mecanismo ideal. No ambiente ele responde **HTTP 500 para toda transação**
testada (`ProductionOrder`, `Item`, `Product`, `CustomerVendor`, `PurchaseOrder`),
inclusive com `InternalID=01|010004|A9716901001`.

### 1.4 Web services SOAP de OP

`MTPRODUCTIONORDER` (`GETPRODUCTIONORDER`) e `MTINTEGRATIONAPS`
(`BRWPOOPERATIONS`) existem e são oficiais, mas com a credencial disponível:

```text
PRTCHKUSER : WebService invalido para este login
```

Além do bloqueio, o contrato não serve: `PRODUCTIONORDERVIEW` e `POOPERATION`
não trazem `ActivityID` nem `ActivityDescription`, e não há parâmetro de
empresa/filial — o serviço roda em `01/010001`, e a OP de referência é
`010004`.

### 1.5 REST de PCP

`GET /rest/api/pcp/v1/productionOrders` (porta 1467) **funciona** com a
credencial REST e devolve OPs reais, mas apenas **cabeçalho**:

```json
{"branchId":"010001","number":"000018","item":"OS","sequence":"001",
 "productionOrder":"000018OS001","itemCode":"MANUTENCAO","quantity":1,
 "reportQuantity":0,"unitOfMeasureCode":"UN","warehouseCode":"50",
 "startOrderDate":"2022-07-21","endOrderDate":"2022-07-21","scriptCode":""}
```

Sem roteiro, sem `ActivityCode`, sem `MachineCode`, e ignorando
`tenantId: 01,010004`. Não é possível produzir um `ProductionOrder` canônico a
partir dele.

### 1.6 Execução remota de rotina

`FWHOSTCOMMUNICATION` expõe `RUNMETHOD`/`RUNJOBMETHOD`, mas é comunicação
**entre hosts Protheus** e exige um objeto serializado `FwSerializable`.
`PCPA111.prw::sincOP()` é função de interface, acionada pelo browse do
PCPA109/PCPA111; não é método de classe serializável. Usar esse serviço para
disparar a rotina seria um hack frágil e não suportado — está registrado aqui e
**não** foi implementado.

### 1.7 Validação final dos serviços padrão (02/09/2026) — DECISÃO C

Antes de tratar a rotina customizada como definitiva, `MTPRODUCTIONORDER` e
`MTINTEGRATIONAPS` foram validados a fundo, pelo **WSDL real** (não pelo HTML de
publicação) e com OPs reais da filial `010004`. São **três bloqueios
independentes**, e o terceiro é decisivo mesmo que os outros dois sejam
resolvidos.

#### (a) Autorização — `PRTCHKUSER`

| Chamada | Resultado |
| --- | --- |
| `GETPRODUCTIONORDER` sem HTTP Basic | `AUTHENTICATION: USER NOT AUTHORIZED` (transporte) |
| `GETPRODUCTIONORDER` com a credencial REST | HTTP 500 · `PRTCHKUSER : WebService invalido para este login` |
| `BRWPOOPERATIONS` com a credencial REST | HTTP 500 · mesmo fault |
| `GETHEADER` **no mesmo serviço**, mesma credencial | **HTTP 200** |

`GETHEADER` responder 200 prova que o serviço está publicado e o login é aceito:
o bloqueio é a liberação **por método/usuário**. O fault é idêntico para
`USERCODE` `000739`, `000000`, `REST`, vazio e `999999` — ou seja, `PRTCHKUSER`
avalia o **login HTTP**, não o parâmetro `USERCODE`. É configuração de TI.

#### (b) Empresa/filial — o serviço não alcança `010004`

- O WSDL real **não possui nenhum parâmetro** de empresa/filial:
  `GETPRODUCTIONORDER(USERCODE, POID, POITEM, POSEQUENCE)` e
  `BRWPOOPERATIONS(USERCODE, POFROM, POTO, datas, QUERYADDWHERE)`.
  A varredura por `BRANCH|COMPANY|FILIAL|EMPRESA` só encontra `DELIVERYBRANCH`,
  campo de pedido de venda, sem relação.
- A publicação roda em `01 / 010001`; `TWSSERVICE.GETLOGININFO` devolve apenas
  `LoginSize`/`PswSize` — o login não carrega filial.
- Prova empírica no REST equivalente (`/rest/api/pcp/v1/productionOrders`):

```text
tenantId='01,010004' → 200  itens=100  filiais={'010001': 100}
tenantId='01,010001' → 200  itens=100  filiais={'010001': 100}
sem tenantId         → 200  itens=100  filiais={'010001': 100}
```

`tenantId` é ignorado. As OPs relevantes (`1079689C001`, `A9716901001`,
`PCMIXQ01001`) são de `01/010004` e estão fora do alcance da publicação.

#### (c) Contrato insuficiente — bloqueio decisivo

`PRODUCTIONORDERVIEW` (WSDL real) **não traz roteiro**: só
`LISTOFMATERIALORDERS` (empenhos). O roteiro só existiria via `POOPERATION`, do
MTINTEGRATIONAPS. E faltam campos que o modelo canônico exige:

| Campo exigido pelo pipeline canônico | Serviço padrão |
| --- | --- |
| `ItemDescription` (**obrigatório** no parser; `catalogo_pcp_ops.produto_descricao` é NOT NULL) | ausente em `PRODUCTIONORDERVIEW` |
| lista de operações no cabeçalho | ausente em `PRODUCTIONORDERVIEW` |
| `ActivityDescription` | ausente em `POOPERATION` |
| `ActivityCode` | `OPERATION` |
| `MachineCode` | `RESOURCECODE` |
| `WorkCenterCode` | `WORKCENTER` |
| `ActivityID` | só `IDAPS` — **não é bloqueio** |

`ActivityDescription` é **carregante**, não cosmético: a assinatura de
classificação do mapper canônico é a 4-tupla
`(ActivityCode, ActivityDescription, WorkCenterCode, MachineCode)`, e o marco
terminal é reconhecido por `("99", "finalizada", "almox4", "almox4")`.

Prova executada com o mapper real sobre o `ProductionOrder` real do PCPA111
(OP `1079689C001`), apagando apenas `ActivityDescription` — exatamente o que
`BRWPOOPERATIONS` consegue entregar:

```text
[A] com ActivityDescription : operações [('10','LASER1'), ('99','ALMOX4')]  marco terminal = 1
[B] sem ActivityDescription : operações []                                  marco terminal = 0
```

Sem a descrição o roteiro inteiro colapsa — não só o marco terminal — porque a
resolução de setor também depende dela. Recuperar isso exigiria afrouxar a
assinatura canônica, ou seja, **inventar semântica** e criar um segundo conjunto
de regras: proibido.

Nenhum serviço padrão do ambiente fornece a descrição da operação de uma OP. A
varredura dos 228 web services SOAP e dos 565 serviços REST publicados não
encontra equivalente: `MRPBOMROUTING` ("Operações por Componente") é o cadastro
de roteiro do MRP por componente, não as operações da OP, e `SFCA006API` é
cadastro de recursos.

#### Decisão

**C — SERVIÇOS PADRÃO INSUFICIENTES.** Mesmo com a liberação do `PRTCHKUSER` e
com uma publicação para `010004`, `MTPRODUCTIONORDER` + `MTINTEGRATIONAPS` não
entregam informação suficiente para produzir o modelo canônico sem inventar
semântica. A rotina customizada da seção 3, que reutiliza a montagem oficial do
PCPA111, passa a ser a **solução definitiva** — e não uma alternativa
provisória. O Gestor **não** foi alterado por esta validação.

### 1.8 Conclusão da descoberta

```text
PCPA109 / PCPA111 (sincOP)
  → MATA650 / PCPa650PPI
  → PCPWebsPPI()
  → HTTP POST PcfIntegService.receiveMessage  →  Gestor
```

Esse é o **único** produtor do `ProductionOrder` canônico, e ele é sempre
iniciado **do lado do Protheus, por interface**. A limitação exata que impede o
acionamento programático é: *não há rotina/serviço publicado que exponha
`sincOP()`/`PCPa650PPI` para um consumidor externo, e o WSPCP — o único serviço
da integração PPI publicado — implementa apenas as duas transações de execução.*

Aplica-se, portanto, o cenário previsto no §22 da etapa.

## 2. O que foi implementado no Gestor

Tudo do lado do Gestor está pronto e homologado. A única peça ausente é a
rotina do Protheus (§3).

```text
operador digita a OP
  → GET  /api/v1/operator/operations/{op}          consulta LOCAL, nunca toca o ERP
     ├─ hit  → carrega imediatamente
     └─ miss → sync.pending = true
  → POST /api/v1/operator/operations/{op}/sync     "Buscando OP no TOTVS..."
     → OrderProvisioningService        (fronteira neutra: a execução não sabe a origem)
     → ProductionOrderOnDemandSyncService
        1. normaliza (alfanumérico preservado)
        2. lookup local
        3. líder/seguidor por OP no PostgreSQL
        4. ProductionOrderRequestGateway → Protheus
        5. inline: entrega o XML ao pipeline canônico
           push:   aguarda a chegada por /PcfIntegService
        6. lookup local novamente, com prazo limitado
     → TotvsProductionOrderIngestionService   ← MESMO serviço do push normal
        parser → mapper → roteiro → recurso → marco terminal → catálogo
  → operador recebe a OP carregada
```

### Arquivos

| Arquivo | Papel |
| --- | --- |
| `mes/integrations/totvs/on_demand.py` | caso de uso `sync_production_order_on_demand`, portas, estados |
| `mes/integrations/totvs/on_demand_gateway.py` | transporte HTTP da solicitação + builders |
| `mes/services/order_provisioning.py` | fronteira neutra usada pela execução |
| `app/database/totvs_op_sync_repository.py` | lookup local e arbitragem líder/seguidor |
| `app/database/migrations.py` | migration **20** — `totvs_op_sync_requests` |
| `backend/api/routers/operator.py` | `GET …/operations/{op}` e `POST …/operations/{op}/sync` |
| `web/src/pages/operator/WorkbenchPage.tsx` | estados "Buscando OP no TOTVS...", achou / não achou / indisponível |
| `scripts/homologar_totvs_op_sob_demanda_etapa61.py` | homologação ponta a ponta no banco TESTE |
| `tests/test_totvs_on_demand.py` | 32 testes (domínio + PostgreSQL real) |

### Invariantes preservados

- **não há segunda implementação de importação de OP**: parser, mapper, regras
  de roteiro, classificação de recurso, marco terminal e persistência são os do
  push; a busca sob demanda só decide *quando* pedir;
- OP existente → lookup local, **zero** chamadas ao ERP;
- identidade da OP preservada: alfanumérica, sem remoção de zero, sem `int`;
  `UniqueId = CompanyId|BranchId|Number`;
- marco terminal continua `marco_terminal = TRUE`, `ativo = FALSE`, invisível ao
  operador e disponível ao outbound;
- ingestão não gera outbound, não inicia produção, não finaliza OP;
- SigmaNEST permanece somente leitura e não é condição para carregar uma OP;
- erro remoto não cria OP, operação nem dado parcial;
- cache negativo é curto e expira — "OP inexistente" nunca vira fato definitivo;
- a execução (`backend/api/routers/operator.py`) continua **sem conhecer a
  origem TOTVS**, conforme a fronteira canônica da Etapa 3.

### Configuração

Enquanto `GESTOR_TOTVS_OP_PULL_ENDPOINT` estiver vazio, não existe gateway: o
Gestor responde apenas o lookup local e informa indisponibilidade. Nada é
inventado para preencher a lacuna.

```ini
GESTOR_TOTVS_OP_PULL_ENDPOINT=https://gtsdo143182.protheus.cloudtotvs.com.br:1467/rest/GESTORPECASPO/gestorpecas/v1/production-order
GESTOR_TOTVS_OP_PULL_MODE=inline        # inline | push
GESTOR_TOTVS_OP_PULL_TIMEOUT_SECONDS=20 # prazo da chamada HTTP
GESTOR_TOTVS_OP_PULL_WAIT_SECONDS=25    # prazo total de espera pela OP
GESTOR_TOTVS_OP_PULL_POLL_INTERVAL_MS=500
GESTOR_TOTVS_OP_PULL_NEGATIVE_TTL_SECONDS=60
GESTOR_TOTVS_OP_PULL_COMPANY_ID=01
GESTOR_TOTVS_OP_PULL_BRANCH_ID=010004
GESTOR_TOTVS_OP_PULL_USERNAME=
GESTOR_TOTVS_OP_PULL_PASSWORD=
```

## 3. Solução no Protheus — PUBLICADA E HOMOLOGADA (Etapa 6.2)

**O fonte já existe:** `fontes/10-PCP/GPOPSYNC.prw`, com README, contrato,
instruções de compilação e critérios de homologação em `protheus/README.md`.

[CONFIRMADO EM 03/09/2026] A correção foi recompilada e publicada no
`CSED4J_DEV`. O serviço `GESTORPECASPO` abre corretamente SM0/SC2 no contexto da
requisição e executa o `MATI650` inline. `ZZ00000ZZ99` retorna 404/`notFound`;
OPs reais em `010001` e `010004` retornam HTTP 200, XML 2.004 e UniqueID da
filial solicitada. Não alterar novamente o GPOPSYNC nesta etapa.

A investigação dos fontes 12.1.2510 encontrou o ponto exato de reaproveitamento:

```text
PCPA111.prw::sincOP()        posiciona SC2 → mata650PPI(,,.T.,.T.,.F.,.F.)
mata650.prx::mata650PPI()    → PCPa650PPI()   (tem o parâmetro oficial lInCustom)
pcpxfun.prx::PCPa650PPI()    define lRunPPI / cPonteiro / INCLUI / ALTERA e chama
                                aRetXML := MATI650("", TRANS_SEND, EAI_MESSAGE_BUSINESS, "2.004")
                                aRetXML[2] := EncodeUTF8(aRetXML[2])
                             e só DEPOIS transporta com PCPWebsPPI()
MATI650.prw::MATI650()       monta e RETORNA o XML em memória (aRet[2])
```

`MATI650` devolve a mensagem **em memória**, então a montagem é separável do
transporte e o modo `inline` é possível — não é preciso cair no fallback `push`.
O endpoint chama `MATI650` diretamente, evitando os efeitos colaterais do
`PCPa650PPI` (filtro SOE, gravação de `C2_ROTEIRO` quando vazio, pendência e
POST no `PcfIntegService`). O trecho `TRANS_SEND` do `MATI650` é montagem pura,
sem `RecLock`/`MsUnLock`/`dbDelete`/transação: o serviço é funcionalmente
somente leitura.

`completXml()` produz exatamente o envelope já homologado
(`ProductionOrder_2_004.xsd`, `Type=BusinessMessage`, `SourceApplication=SIGAPCP`,
`CompanyId`/`BranchId` de `cEmpAnt`/`cFilAnt`), o que fecha o contrato abaixo.

O pipeline principal já falava esse contrato. A Etapa 7B precisou apenas
corrigir a representação do caso real em que o XML contém cabeçalho, mas zero
atividades: `sem_roteiro`, sem parser ou ingestão paralelos.

**Rotina/API necessária** — serviço TLPP/ADVPL mínimo, no mesmo appserver do
WSPCP, que reaproveita a montagem oficial já usada pelo PCPA111.

**Entrada** (`POST`, JSON):

```json
{"companyId": "01", "branchId": "010004", "number": "A9716901001"}
```

`number` é o `C2_NUM + C2_ITEM + C2_SEQUE` completo, **alfanumérico**. Não
converter para número, não remover zeros.

**Comportamento esperado**

1. abrir o ambiente na empresa/filial recebidas;
2. validar a existência da OP em SC2 pelas rotinas Protheus (sem SQL exposto);
3. chamar a **mesma** montagem oficial do `ProductionOrder` usada pelo
   PCPA111 (`sincOP()` → `MATA650`/`PCPa650PPI`), sem remontar a mensagem;
4. entregar o resultado por um dos dois modos.

**Saída — modo `inline` (preferido)**

```text
HTTP 200, Content-Type: text/xml
<TOTVSMessage> … ProductionOrder_2_004 … </TOTVSMessage>
```

**Saída — modo `push`**

```text
HTTP 200, Content-Type: application/json
{"status": "accepted"}
```
e o Protheus envia a mensagem pelo `PCPWebsPPI` ao `PcfIntegService` do Gestor,
exatamente como hoje. O Gestor aguarda a chegada por prazo limitado.

**OP inexistente**

```text
HTTP 404, {"status": "notFound"}
```

**Restrições**

- não escrever em SC2/SG2/SHY;
- não expor SQL nem consulta genérica;
- autenticação por ambiente (HTTP Basic serve; a credencial REST já existe);
- escopo mínimo: uma entrada, uma saída, nenhuma transação nova.

Os web services padrão de OP (`MTPRODUCTIONORDER`, `MTINTEGRATIONAPS`) foram
descartados como caminho — ver a seção 1.7. Liberar `PRTCHKUSER` ou publicar o
serviço para `010004` **não** resolve: o contrato não tem descrição de produto
nem de operação.

O EAI genérico permanece descartado no ambiente atual. Não reabrir esse caminho
sem fato novo que entregue o contrato completo e o contexto de filial correto.

## 4. Homologação executada

`scripts/homologar_totvs_op_sob_demanda_etapa61.py`, contra `gestor_pecas_test`.

A mensagem usada é o `ProductionOrder` **real gerado pelo Protheus**
(`Product name="MATA650" version="12.1.2510"`, `SourceApplication=SIGAPCP`),
capturada do PCPA111 para a OP `1079689C001` — que existia no Protheus e **não**
existia no Gestor. O responder local ocupa o lugar da rotina do §3, com o mesmo
contrato HTTP; ele **replica** a mensagem real, não a fabrica.

```text
Banco alvo: gestor_pecas_test
[1] 1079689C001 local = None                       ← MISS real
[2] status=sincronizada requested=True tempo=0.392s
[3] codigo_op=1079689C001 produto=IPCX04014054P qtd=2
    unique_id=01|010004|1079689C001
[4]  10 CORTE       recurso=LASER1  setor=Corte  terminal=False ativo=True  activity_id=166459
     99 FINALIZADA  recurso=ALMOX4  setor=-      terminal=True  ativo=False activity_id=166461
[5] itens de outbox = 0
[6] segunda busca: status=local  novas_chamadas=0
[7] OP inexistente: status=nao_encontrada, sem OP e sem operação criadas
[8] cache negativo: novas chamadas ao ERP = 0
[9] mecanismo indisponível: status=indisponivel, nenhum dado parcial
[10] concorrência: ['sincronizada','sincronizada'] chamadas_ao_erp=1
     OPs=1 marcos_terminais=1
HOMOLOGAÇÃO ETAPA 6.1: OK
```

Verificações complementares no mesmo banco:

```text
inbox    status=processed  result_action=inserted  external_id=01|010004|1079689C001
operador listar_operacoes_para_op('1079689C001') → 1 operação (10 CORTE / LASER1)
         o marco terminal 99/ALMOX4 não aparece para o operador
SigmaNEST correlação existente = 0; nenhuma escrita no SigmaNEST
```

As três atividades sem projeção (`01 IMPRESSAO OP/PCP`, `20`, `30 INSPECAO`)
seguem a política conservadora de mapeamento já vigente: recurso/etapa sem
semântica aprovada permanece não projetado e auditável.

## 5. Estado final da Etapa 7B

Em 03/09/2026, a OP `00615903001` percorreu o ponto de entrada normal do Gestor,
o GPOPSYNC/MATI650 real, a ingestão canônica, os catálogos PostgreSQL e a
consulta operacional. A segunda consulta foi local, sem novo HTTP. Ingestão não
criou outbox nem fatos operacionais.

A OP matriz `10795102002` retornou cabeçalho válido e zero atividades. Isso
revelou um problema concreto: o fluxo respondia `timeout` embora o ERP tivesse
confirmado a existência. O estado foi corrigido para `sem_roteiro`, com
`found=false`; o cabeçalho permanece auditável, nenhuma operação é inventada e
consultas seguintes não repetem o ERP.

Evidência completa em
`docs/evidencias/TOTVS_ETAPA7B_HOMOLOGACAO_REAL_2026-09-03.md`.
