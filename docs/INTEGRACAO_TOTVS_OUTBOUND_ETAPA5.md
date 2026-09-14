# ETAPA 5 — retorno Gestor → TOTVS / ciclo de vida da OP

Atualizado em: 01/09/2026  
Ambientes autorizados: `gestor_pecas_test` e TOTVS TESTE (`Csed4j_dev`)  
Status: **HOMOLOGADO NO TESTE, INCLUSIVE A EFETIVAÇÃO DA PRODUÇÃO.**
`ProductionAppointment` (zero, parcial, fechamento e refugo) e `StopReport` foram
aceitos com ACK real do WSPCP. Na Etapa 5C o ciclo foi fechado: apontando a
**última operação do roteiro**, o próprio Protheus gerou o SD3 e levou a OP
`A9716901001` de `C2_QUJE` 0,00/legenda Iniciada para `C2_QUJE` 10,00/legenda
**Encerrada totalmente**. Evidências em
`docs/evidencias/WSPCP_TESTE_HOMOLOGACAO_NEGOCIO_2026-09-01.md` e
`docs/evidencias/TOTVS_EFETIVACAO_PRODUCAO_ETAPA5C_2026-09-01.md`.

## 1. Resultado executivo

[CONFIRMADO] O caminho implementado é:

```text
evento canônico já confirmado
  → TotvsOutboundRepositoryMixin (somente SELECT)
  → TotvsOutboundService
  → mapper ProductionAppointment ou StopReport
  → TotvsWspcpClient (SOAP síncrono)
  → WSPCP.ReceiveMessage/CXML
  → MATA681 ou MATA682
  → SH6 + efeitos normais do Protheus
```

Nenhum código da tela, da máquina de estados ou do `OperatorFlowService` conhece
SOAP/XML. Não existe `if origem_op == "totvs"`. Não há outbox, worker, retry
permanente nem reconciliação automática nesta etapa.

[CONFIRMADO] O banco efetivo lido durante a implementação foi
`gestor_pecas_test` em `127.0.0.1:15432`; `gestor_pecas` não foi aberto nem
alterado. O TOTVS aberto no Chrome mostrou `TOTVS Manufatura MSSQL Csed4j_dev`,
empresa/filial `Gts do Brasil Ltda / Filial_iv - Verticalizacao`, identificando
o ambiente TESTE. Nenhum endpoint ou dado do TOTVS REAL foi chamado.

## 2. Contrato e fonte Protheus comprovados

### Serviço — WSDL real do TESTE

Fonte primária capturada em 01/09/2026:
`docs/evidencias/WSPCP_TESTE_2026-09-01.wsdl`.

- WSDL: `https://gtsdo143182.protheus.cloudtotvs.com.br:1465/ws/WSPCP.apw?WSDL`;
- `soap:address`: `https://gtsdo143182.protheus.cloudtotvs.com.br:1465/ws/WSPCP.apw`;
- `targetNamespace`: `http://webservices.totvs.com.br/`;
- serviço: `WSPCP`;
- port/binding: `WSPCPSOAP`;
- SOAP: **1.1**, transport `http://schemas.xmlsoap.org/soap/http`;
- style/use: `document/literal`;
- operação, com case exato: `RECEIVEMESSAGE`;
- `SOAPAction`: `http://webservices.totvs.com.br/RECEIVEMESSAGE`;
- entrada: `RECEIVEMESSAGE/CXML`, `xsd:string`, `minOccurs=1`, `maxOccurs=1`;
- saída: `RECEIVEMESSAGERESPONSE/RECEIVEMESSAGERESULT`, `xsd:string`,
  `minOccurs=1`, `maxOccurs=1`;
- processamento: síncrono;
- `ProductionAppointment`: despacho para `MATA681` no PCP;
- `StopReport`: despacho para `MATA682` no PCP;
- log de importação: `PCPA112`, sobre estruturas SOG/SOF/SOH;
- ACK: `TOTVSMessage/ResponseMessage`, com
  `ProcessingInformation/Status=OK|ERROR`, mensagens e, quando fornecido,
  `ReturnContent/ListOfInternalId`.

[CONFIRMADO] O WSDL real **não possui elemento `CRESPONSE`**. A saída publicada
é `RECEIVEMESSAGERESULT`. O client e o parser usam esse contrato, tolerando
apenas prefixos de namespace XML, não nomes alternativos inventados.

[CONFIRMADO] Um primeiro POST SOAP 1.1 anônimo chegou ao método e retornou
HTTP 500/Fault `AUTHENTICATION: USER NOT AUTHORIZED`. Após a credencial REST do
TESTE ser configurada localmente, uma tentativa com HTTP Basic retornou HTTP
200 e `RECEIVEMESSAGERESULT` estruturado. O `CXML` deliberadamente vazio foi
rejeitado com `ProcessingInformation/Status=ERROR`, código `1` e `Document is
empty`, comprovando que a autenticação passou e o WSPCP interpretou o conteúdo.
Nenhuma mensagem de negócio foi usada. A evidência está em
`docs/evidencias/WSPCP_TESTE_POST_TECNICO_2026-09-01.md`.

[EVIDÊNCIA SUPLEMENTAR DO MES] A configuração PC-Factory fornecida pelo usuário
também contém `ENABLEAUTH=TRUE` e o mesmo endpoint externo na porta 1465. O
extrato sanitizado está em
`docs/evidencias/PCFACTORY_CONFIG_TOTVS_SANITIZADA_2026-09-01.md`. O arquivo
original contém credenciais e connection strings e não foi copiado para o
repositório. Seu `wasteCode=1` permanece apenas como default observado, não como
código TOTVS autorizado.

### ProductionAppointment 2.003

Campos com destino comprovado no PCP:

| Contrato | Protheus |
|---|---|
| `MachineCode` | `SH6.H6_RECURSO` |
| `ProductionOrderNumber` | `SH6.H6_OP` |
| `ActivityCode` | `SH6.H6_OPERAC` |
| `Split` | `SH6.H6_DESDOBR` quando existir |
| `ItemCode` | `SH6.H6_PRODUTO` |
| `ApprovedQuantity` | `SH6.H6_QTDPROD` |
| `ScrapQuantity` | `SH6.H6_QTDPERD` |
| `StartReportDateTime` | `SH6.H6_DATAINI/H6_HORAINI` |
| `EndReportDateTime` | `SH6.H6_DATAFIN/H6_HORAFIN` |
| `ReportDateTime` | `SH6.H6_DTAPONT` |
| `CloseOperation` | `SH6.H6_PT` |

`ReportQuantity` é gerado como boas + refugo, sem incluir retrabalho. O
`ActivityID` recebido no `ProductionOrder` é preservado no contrato outbound e
o `ActivityCode` continua sendo a operação real. `MachineCode` vem de
`catalogo_operacoes_op.totvs_machine_code`; o mapper não troca o recurso por
nome de posto.

[CONFIRMADO] O XSD possui `ReworkQuantity`, mas a matriz Protheus examinada não
lhe dá destino no MATA681/SH6. Por isso o mapper envia zero e **bloqueia qualquer
evento canônico com retrabalho maior que zero**. Retrabalho não vira peça boa,
refugo ou outro campo por inferência.

[CONFIRMADO] Refugo exige `WasteCode` explícito e comprovado. O texto/motivo do
Gestor não é convertido automaticamente.

### StopReport 1.001

Campos obrigatórios comprovados:

| Contrato | Protheus |
|---|---|
| `MachineCode` | `SH6.H6_RECURSO` |
| `StopReasonCode` | `SH6.H6_MOTIVO` |
| `StartDateTime` | data/hora inicial em SH6 |
| `EndDateTime` | data/hora final em SH6 |
| `ReportDateTime` | timestamp do reporte |
| `OperatorCode` | `SH6.H6_OPERADO`, quando usado |

No PCP, o motivo deve existir na tabela SX5, grupo 44. O `StopType` tem uso
comprovado no SFC, mas não possui destino PCP nessa matriz e não é emitido pelo
mapper. Isso evita escolher silenciosamente entre convenções documentais
divergentes de programada/não programada.

O contrato exige início e término. Assim:

```text
evento Gestor parada   → mantém o fato canônico aberto; não envia StopReport incompleto
evento Gestor retomada → combina a parada imediatamente anterior com a retomada
                       → envia um StopReport fechado
```

O código SX5/44 é parâmetro explícito na homologação. `codigo_status_recurso`
do Gestor/PCFactory não é presumido igual ao motivo do Protheus.

## 3. Matriz evento Gestor → TOTVS → efeito esperado

| Evento canônico | Contrato | Rotina | Efeito comprovado por código | Homologação emitida pelo Gestor |
|---|---|---|---|---|
| início `producao`, quantidade zero | `ProductionAppointment` com zero, somente se chave explícita de homologação | MATA681 | movimento SH6 e legenda muda de "Em aberto" para "Iniciada" | **HOMOLOGADO** (783154) |
| `parcial` com boas | `ProductionAppointment`, `CloseOperation=false` | MATA681 | `H6_QTDPROD` e movimento em SH6 | **HOMOLOGADO** (783155/783156/783158) |
| `parcial`/`finalizado` com refugo | `ProductionAppointment` + `WasteCode` | MATA681 | `H6_QTDPERD` e detalhe de perda | **HOMOLOGADO** com `WasteCode=RP` (783160) |
| retrabalho > 0 | não enviado | — | sem destino Protheus comprovado | bloqueado corretamente |
| `finalizado` | `ProductionAppointment`, `CloseOperation=true` | MATA681 | `H6_PT`; envio posterior na mesma operação é recusado por `A680OPTOT` | **HOMOLOGADO** (783157/783159) |
| `parada` aberta | nenhum ainda | — | StopReport exige fim | não aplicável |
| retomada após `parada` | `StopReport` fechado | MATA682 | SH6 improdutivo com recurso/motivo/intervalo | **HOMOLOGADO** com `0010` e `0018` (783161/783162) |

## 4. Ciclo de vida/legendas do MATA650

As legendas não são estados enviados no XML. São calculadas pelo Protheus:

- **Prevista:** `C2_TPOP='P'`.
- **Em aberto:** `C2_TPOP='F'`, `C2_DATRF` vazio, sem movimentos SD3/SH6 e
  dentro do limite de ociosidade de `C2_DIASOCI`.
- **Iniciada:** `C2_TPOP='F'`, `C2_DATRF` vazio, existe movimento SD3/SH6 e o
  último movimento ainda está dentro de `C2_DIASOCI`.
- **Ociosa:** `C2_TPOP='F'`, `C2_DATRF` vazio e tempo desde o último movimento
  (ou `C2_DATPRI`) maior ou igual a `C2_DIASOCI`.
- **Encerrada parcialmente:** `C2_TPOP='F'`, `C2_DATRF` preenchido e
  `C2_QUJE < C2_QUANT`.
- **Encerrada totalmente:** `C2_TPOP='F'`, `C2_DATRF` preenchido e
  `C2_QUJE >= C2_QUANT`.

A paleta real desta base, lida em `Outras Ações → Legenda` do MATA650, é:
amarelo Prevista, verde Em aberto, laranja Iniciada, branco Ociosa, azul
Encerrada parcialmente, vermelho Encerrada totalmente.

[CONFIRMADO NO TESTE EM 01/09/2026] Um primeiro movimento SH6 é o que separa
“Em aberto” de “Iniciada”: a OP `A9716901001` passou de verde para laranja com
um `ProductionAppointment` de **quantidade zero**.

[RESOLVIDO NA ETAPA 5C] `C2_QUJE` e `C2_DATRF` são preenchidos pelo próprio
`ProductionAppointment`, mas **somente quando a operação apontada é a última do
roteiro**. Nesse caso `MATA681` chama `A680GeraD3("PR0", ...)`, que cria o SD3, e
`A250Atu`, que faz `C2_QUJE += D3_QUANT` e grava `C2_DATRF`. Na Etapa 5B foram
apontadas apenas as operações `10` e `20` do roteiro 35, que tem ainda `30` e
`99`; por isso nada era efetivado. O mesmo explica a OP `PCMDPG01001` da
PC-Factory, cujo roteiro 15 termina em `99` e que só recebe apontamento da
operação `20`. Detalhamento em
`docs/evidencias/TOTVS_EFETIVACAO_PRODUCAO_ETAPA5C_2026-09-01.md`.

## 5. Implementação

Arquivos principais:

- `mes/integrations/totvs/outbound_models.py`: fatos e DTOs neutros;
- `mes/integrations/totvs/outbound_mapper.py`: mapper e XML;
- `mes/integrations/totvs/outbound_ack.py`: ACK, erro, SOAP Fault e duplicidade;
- `mes/integrations/totvs/outbound_service.py`: caso de uso manual, fronteira
  pronta para futura outbox;
- `app/database/totvs_outbound_repository.py`: read model, somente `SELECT`;
- `backend/integrations/totvs_wspcp.py`: SOAP/HTTP;
- `scripts/homologar_totvs_outbound.py`: dry-run por padrão e envio com travas;
- `tests/test_totvs_outbound.py`: contrato e regressões.

Travas do comando de homologação:

1. banco efetivo exatamente `gestor_pecas_test`;
2. evento sem divergência de recurso;
3. timestamp não futuro;
4. `--send` explícito;
5. `--confirm-test-environment TOTVS_TESTE`;
6. hostname da URL igual ao `--expected-host`;
7. endpoint exatamente igual à publicação externa TESTE na porta 1465;
8. motivo de parada/refugo explicitamente informado;
9. retrabalho bloqueado.

Exemplo de dry-run, sem escrita externa:

```powershell
C:\Python314\python.exe scripts\homologar_totvs_outbound.py `
  --event-id 186 `
  --contract productionappointment `
  --allow-zero-quantity
```

## 6. Evidência do TOTVS TESTE disponível antes do envio Gestor

### PCPA109

- integração ativa;
- salva mensagens = sim;
- caminho de saída Protheus → Gestor apontava para Quick Tunnel temporário;
- essa URL não é o WSPCP de entrada.

### PCPA112

A consulta “Apontamento de Produção” mostrou registros históricos reais do
TESTE. No recorte renderizado havia 16 linhas “Integrado com sucesso” e 5
“Ocorreram erros”. Vários sucessos tinham quantidade zero e intervalo de
início/fim, provando na base que o MATA681 aceita reportes de tempo sem
quantidade quando OP/operação/recurso são válidos.

Também foram observados erros como “Ordem de produção sem empenho” e “H6_OP
inválido”. Portanto, uma OP simplesmente existente não é suficiente para
homologação; deve estar liberada e com pré-condições produtivas atendidas.

As OPs `A9716901001`, `A9717001001` e `A9717101001` existem no catálogo do
Gestor TESTE, mas **nenhuma foi declarada descartável pela Manufatura/TI**.
`A9717001001` e `A9717101001` já foram finalizadas apenas na simulação local e
possuem timestamps virtuais; o comando impede o envio desses eventos futuros.

## 7. Homologação prática — executada em 01/09/2026

OP escolhida no próprio TESTE: `A9716901001` (produto `PNT002002003`, filial
`010004`, firme, liberada, legenda verde, quantidade 10, produzida 0). Roteiro
real vindo do `ProductionOrder`: operação `10` recurso `PLASMA` e operação `20`
recurso `CNC-01`.

| Cenário | Antes | Evento/Payload | ACK | Depois | Resultado |
|---|---|---|---|---|---|
| Transporte SOAP anônimo | não aplicável | `CXML` vazio | HTTP 500/Fault `AUTHENTICATION: USER NOT AUTHORIZED` | nenhum efeito | CONECTIVIDADE CONFIRMADA |
| Transporte SOAP autenticado | não aplicável | `CXML` vazio | HTTP 200; `Status=ERROR`, código 1 | nenhum efeito | HTTP BASIC E PROCESSAMENTO CONFIRMADOS |
| A — início/zero | legenda verde, `C2_QUJE` 0,00 | `ProductionAppointment` 0, intervalo 08:00:00→09:47:11 | `Status=OK`, InternalId 783154 | legenda **laranja/Iniciada**, `C2_QUJE` 0,00 | **HOMOLOGADO** |
| B — produção parcial | legenda laranja | `ApprovedQuantity=2`, `CloseOperation=false` | `Status=OK`, 783155 | PCPA112 "Integrado com sucesso" com quantidade 2 | **HOMOLOGADO** |
| C — novo apontamento | idem | `ApprovedQuantity=3` | `Status=OK`, 783156 | PCPA112 com quantidade 3 | **HOMOLOGADO** |
| F — encerramento de operação | operação 10 aberta | `ApprovedQuantity=5`, `CloseOperation=true` | `Status=OK`, 783157 | operação 10 totalizada; novo envio nela é recusado por `A680OPTOT` | **HOMOLOGADO** |
| F — encerramento da última operação | operação 20 aberta | 4 e depois 6 com `CloseOperation=true` | `Status=OK`, 783158 e 783159 | operação 20 totalizada; `C2_QUJE`/`C2_DATRF` inalterados | **HOMOLOGADO COM RESSALVA** |
| E — refugo | `A9717001001` operação 10 | `ScrapQuantity=1` com `WasteCode=RP` | `Status=OK`, 783160 | PCPA112 "Integrado com sucesso" | **HOMOLOGADO** |
| C/D — parada e retomada | recurso `ROBO P` | `StopReport` fechado, `StopReasonCode=0010` e `0018` | `Status=OK`, 783161 e 783162 | PCPA112 "Apontamento de Parada — Integrado com sucesso" | **HOMOLOGADO** |
| E — retrabalho | sem destino Protheus comprovado | bloqueado pelo mapper | — | — | NÃO SUPORTADO |

### Ressalva medida, não presumida

`ProductionAppointment` alimenta o reporte de operação em SH6
(`ApprovedQuantity → H6_QTDPROD`, `ScrapQuantity → H6_QTDPERD`,
`CloseOperation → H6_PT`) e muda a legenda de "Em aberto" para "Iniciada" já no
primeiro movimento, mesmo com quantidade zero. Nesta parametrização ele **não**
preenche `C2_QUJE` nem `C2_DATRF`; a OP não passa a "Encerrada parcialmente" nem
"Encerrada totalmente" por esta rota. A OP `PCMDPG01001`, alimentada diariamente
pela PC-Factory desde 19/08/2026, apresenta exatamente o mesmo quadro, o que
mostra ser comportamento do ambiente e não do Gestor.

## 8. Códigos TOTVS TESTE confirmados

`WasteCode` (Cadastro de Motivo Refugo): `FH`, `FM`, `FP`, `NC`, `RB`, `RP`.
O `wasteCode=1` do arquivo do integrador **não existe** neste ambiente.

`StopReasonCode` (SX5 grupo 44, Cadastro de Motivo Parada): `0009` a `0028` e
`FE`, incluindo `0010 MANUTENCAO PREVENTIVA` e `0018 AJUSTANDO SETUP`, ambos
homologados em envio real.

## 9. Pendências reais que restam

- OP TESTE para repetir o encerramento ponta a ponta: é preciso uma OP com marco
  terminal em aberto **e** componentes com saldo. O último ensaio parou em
  `Itens Sem Saldo Bloqueados`, condição de estoque do ambiente.
- Retrabalho: continua sem campo efetivo comprovado no MATA681/SH6 e permanece
  bloqueado no mapper.
- OPs sem processo produtivo cadastrado na filial, como `02911901002` em
  `010007`, não são apontáveis. Depende da Engenharia, não da integração.

## 10. Próxima etapa

**Executada em 01/09/2026.** Outbox transacional, worker, retry com backoff e
recuperação após queda estão em `docs/INTEGRACAO_TOTVS_OUTBOX_ETAPA6.md`. Nada
desta Etapa 5 foi reescrito: contratos, mapper, parser de ACK, gateway SOAP,
regra do marco terminal e bloqueio de retrabalho continuam como homologados.
Reconciliação bidirecional automática continua fora do escopo.

## 11. Verificação automatizada

- testes específicos outbound: **21/21 aprovados**, incluindo duas regressões
  novas com o ACK real (`InternalId` com `Name`/`Destination` como elementos
  filhos e rejeição funcional `A680OPTOT`);
- suíte Python completa: **462 testes aprovados, 1 pulado** porque o banco TESTE
  ativo não contém fatos na janela histórica de julho/2026;
- Web/build: não executados, porque nenhum código Web foi alterado nesta etapa;
- WSDL: HTTP 200, XML válido, contrato SOAP extraído e preservado em evidência;
- POST WSPCP técnico: o anônimo provou a exigência de autenticação; o POST com
  credencial REST via HTTP Basic retornou HTTP 200 e ACK estruturado;
- **envio de negócio: 9 mensagens reais aceitas pelo WSPCP TESTE**, sendo 7
  `ProductionAppointment` (zero, parcial, novo apontamento, dois encerramentos de
  operação e refugo com `WasteCode=RP`) e 2 `StopReport` (`0010` e `0018`), com
  `InternalId` 783154 a 783162 e confirmação em PCPA112.

Um bug real foi encontrado e corrigido: o parser de ACK lia `InternalId` no
formato compacto e corrompia o identificador quando o WSPCP devolvia `Name`,
`Origin` e `Destination` como elementos filhos. Nenhum cálculo, estado, SQL
produtivo ou regra industrial foi alterado.

## 12. ETAPA 5C — efetivação da produção (`C2_QUJE` / `C2_DATRF`)

Investigação feita sobre as fontes Protheus `12.1.2510` do pacote `totvspcp`.
Detalhamento e provas em
`docs/evidencias/TOTVS_EFETIVACAO_PRODUCAO_ETAPA5C_2026-09-01.md`.

```text
WSPCP.receiveMessage → execInteg
   PRODUCTIONAPPOINTMENT → MATI681 → MSExecAuto(MATA681)
   STOPREPORT            → MATI682
   MOVEMENTSINTERNAL     → MATI250 (entrada com OP) ou MATI240

MATA681 (mata681.prx:835)
   If A680UltOper() .Or. lEncerraOP
       A680GeraD3("PR0", ...)   → cria SD3
       A250Atu(...)             → SC2

MATA250 (mata250.prx:3825/3862)
   Replace C2_QUJE  With C2_QUJE + SD3->D3_QUANT
   Replace C2_DATRF With Iif(MV_DATENC=="1", dDataBase, dEmissao)
```

[CONFIRMADO POR CÓDIGO E POR ENVIO REAL] O `ProductionAppointment` **é** o
mecanismo de efetivação. Ele só produz quando a operação apontada é a **última
do roteiro** (`A680UltOper()`), que o Protheus resolve percorrendo SG2/SHY do
produto + roteiro da OP. Não existe segunda mensagem obrigatória.

[CONFIRMADO NO TESTE] Apontando a operação `99 / ALMOX4` da OP `A9716901001`, o
Protheus gerou o SD3 e a OP passou de `C2_QUJE` 0,00 / legenda **Iniciada** para
`C2_QUJE` 10,00 / legenda **Encerrada totalmente**, sem nenhuma escrita direta
em `SC2`.

[DEDUZIDO DO COMPORTAMENTO] Como a produção ocorreu com `Product name` igual a
`GESTOR_PECAS` (logo `H6_OBSERVA != "TOTVSMES"`), o ambiente tem
`MV_VLDOPER = "S"`. O Gestor **não** precisa se identificar como `PPI`.

[AJUSTE DE CONTRATO] `ActivityID` passou a ser opcional no mapper: a matriz
oficial traz `--` para o Protheus e `MATI681.prw` nunca lê o campo. As operações
`30` e `99` foram aceitas sem ele em envio real.

## 13. Marco terminal preservado e disparado automaticamente

O marco terminal do roteiro (`99 / FINALIZADA / ALMOX4`) é preservado no próprio
`catalogo_operacoes_op` pela coluna `marco_terminal` (migration 18). A linha é
sempre gravada com `ativo = FALSE` e `tipo_setor` nulo, e uma constraint impede
torná-la apontável. Como as consultas do operador já filtram `ativo IS TRUE`,
ela é invisível na Tela do Operador sem nenhuma mudança de query. Nenhum posto
`ALMOX4` e nenhum setor fictício foram criados.

```text
execução canônica da OP concluída (todas as operações apontáveis finalizadas)
  → buscar_marco_terminal_outbound_totvs  (somente SELECT)
  → terminal_approved_quantity            (boas da última operação produtiva)
  → map_terminal_production_appointment   (ActivityCode/MachineCode reais)
  → ProductionAppointment CloseOperation=true
  → MATA681 → A680UltOper → A680GeraD3 → SD3 → A250Atu → C2_QUJE/C2_DATRF
```

O terminal não é emitido na ingestão, por operação intermediária nem por parcial
ainda aberta. A chave `IDPCFactory` é determinística por OP + operação terminal,
então reprocessar a mesma conclusão não gera um segundo apontamento.

Detalhamento e ACKs reais em
`docs/evidencias/TOTVS_MARCO_TERMINAL_2026-09-01.md`.
