# Integração TOTVS ProductionOrder V1

**Estado:** HOMOLOGADA no ambiente TESTE  
**Atualização:** 27/08/2026  
**Escopo:** `TOTVS TESTE → Gestor TESTE` para `WhoIs` e
`ProductionOrder/upsert`

## 1. Resultado atual

A integração inbound está comprovada servidor-a-servidor no ambiente TESTE.

```text
TOTVS TESTE
  ↓
PCPA109 / PCPA111
  ↓ SOAP 1.1
PcfIntegService.receiveMessage
  ↓
Gestor TESTE
  ↓
parser → mapper → service → repository
  ↓
gestor_pecas_test (migration 16)
  ↓
TOTVSMessage/ResponseMessage
ProcessingInformation/Status = OK
  ↓
Protheus reconhece sucesso
```

O Gestor mantém `catalogo_pcp_ops` como catálogo canônico de planejamento
recebido e `catalogo_operacoes_op` como projeção operacional. Não foi criada uma
tabela concorrente de OPs.

## 2. Contrato SOAP confirmado

```text
Service     EAIServiceClass
PortType    EAIService
Operation   receiveMessage
SOAP        1.1 document/literal
SOAPAction  http://tempuri.org/EAIService/receiveMessage
Input       pXmlDocument : string
Output      receiveMessageResult : string
```

A mensagem de negócio é um `TOTVSMessage` textual transportado dentro de
`pXmlDocument`.

Endpoints do Gestor:

```text
GET  /PcfIntegService?wsdl
POST /PcfIntegService
```

O receptor é fail-closed por origem. Ao ativar
`GESTOR_TOTVS_SOAP_ENABLED=true`, também é obrigatório configurar
`GESTOR_TOTVS_SOAP_ALLOWED_SOURCE_CIDRS` com os IPs ou CIDRs reais dos
servidores TOTVS autorizados, separados por vírgula. Exemplo:

```dotenv
GESTOR_TOTVS_SOAP_ALLOWED_SOURCE_CIDRS=10.10.1.25/32,10.10.2.0/24
```

GET do WSDL e POST de mensagens são recusados antes da leitura do corpo quando
o IP observado diretamente no socket não pertence à allowlist. `Host` e
`X-Forwarded-For` não autenticam a origem; o bloqueio adicional pelo hostname
público permanece ativo. Se houver proxy entre TOTVS e Gestor, a rede deve
preservar a conexão direta ou aplicar a restrição no próprio proxy — cadastrar
somente o IP do proxy no Gestor autorizaria todos os clientes que o alcançam.

## 3. Correção definitiva sobre o ACK

A interpretação antiga de que o sucesso seria `receiveMessageResult = "OK"`
foi descartada pela homologação real e pela análise dos fontes Protheus
12.1.2510.

O consumidor `pcpxfun.prx::PCPWebsPPI`, usado tanto pelo PCPA109 quanto pelo
PCPA111/MATA650, faz parse XML de `receiveMessageResult` e só considera sucesso
quando:

```text
/TOTVSMessage/ResponseMessage/ProcessingInformation/Status = OK
```

Texto puro `OK` falha no parser e produz no Protheus a mensagem:

```text
Não foi possível realizar o parse do XML de retorno do TOTVS MES.
```

O construtor oficial observado em `WSPCP.prw::getReturn` usa
`TOTVSMessage/ResponseMessage`, com `Type=Response`, `Transaction` em maiúsculas,
correlação por UUID, `SentBy` derivado do produto recebido e
`ProcessingInformation/Status`.

O `OK` observado em `SOF010.OF_MSGRET` é o resultado **normalizado pelo
Protheus após o parse**, não o payload bruto de `receiveMessageResult`.

`GESTOR_TOTVS_SOAP_SUCCESS_RESULT=OK` permanece como configuração de
compatibilidade/fallback do transporte, mas o caminho de sucesso das mensagens
suportadas usa o XML produzido por `mes/integrations/totvs/response.py`.

## 4. WhoIs

O `WhoIs` do PCPA109 é tratado como diagnóstico sem efeito de negócio:

- recebido pelo mesmo endpoint SOAP;
- registrado/auditado na inbox;
- não cria nem altera OP;
- retorna `TOTVSMessage/ResponseMessage` com `Status=OK`;
- homologado ao vivo no PCPA109 com indicadores de comunicação/retorno verdes.

## 5. ProductionOrder real homologada

OP de referência enviada pelo PCPA111:

```text
Number                    A9716901001
ProductionOrderUniqueID   01|010004|A9716901001
ItemCode                  PNT002002003
ItemDescription           BRACO ARTICULACAO
Quantity                  10
UnitOfMeasureCode         UN
```

Atividades recebidas:

```text
01 → IMPRESSAO OP → PCP
10 → CORTE        → PLASMA
20 → USINAGEM     → CNC-01
30 → INSPECAO     → INSPEC
99 → FINALIZADA   → ALMOX4
```

No `gestor_pecas_test` oficial, após a limpeza dos bancos históricos:

```text
inbox id              2
transaction           ProductionOrder
external_id           01|010004|A9716901001
status                processed
result_action         inserted
activities_parsed     5
activities_projected  2
error_code            NULL
error_message         NULL
```

Cabeçalho persistido:

```text
codigo_op          A9716901001
produto_codigo     PNT002002003
produto_descricao  BRACO ARTICULACAO
quantidade         10
ativo              true
totvs_unique_id    01|010004|A9716901001
```

Operações projetadas com mapeamento seguro atual:

```text
10 → PLASMA → CORTE     → Corte     (ActivityID 108761)
20 → CNC-01 → USINAGEM  → Usinagem  (ActivityID 160893)
```

As demais atividades não receberam semântica inventada. Elas continuam
preservadas no payload e devem ser tratadas na etapa de mapeamento oficial.

## 6. Resultado do lado do Protheus

A primeira tentativa real, quando o Gestor ainda devolvia texto puro `OK`, foi
registrada pelo PCPA111 como erro de parse.

Após a correção do `ResponseMessage`, o Protheus registrou sucesso:

```text
Transação    SC2
Registro     A9716901001
OF_STATUS    1
Programa     PCPA111
Arquivo      OK_PRODUCTIONORDER_...
Mensagem     OK
```

Isso comprova o ciclo inbound e o ACK compatível com o consumidor real do
Protheus.

## 7. Identidade, idempotência e ordem temporal

Identidade preferencial: `ProductionOrderUniqueID`.

Controles:

1. SHA-256 do `TOTVSMessage` na inbox;
2. unicidade parcial de `catalogo_pcp_ops.totvs_unique_id`;
3. `GeneratedOn` para ordem temporal.

Comportamentos esperados/implementados:

- XML idêntico → idempotente;
- nova versão da mesma identidade → atualiza a mesma OP;
- mensagem mais antiga → `ignored_stale`;
- mesmo `GeneratedOn` com payload diferente → conflito controlado;
- `UUID` não é chave de negócio;
- uma OP não inativa outra OP;
- erro de persistência não recebe falso sucesso.

## 8. Projeção de roteiro

Política atual é conservadora:

- `ActivityDescription`/setor só é convertido quando existe regra canônica ou
  alias explícito;
- `MachineCode` é a identidade preferencial do recurso; `WorkCenterCode` só o
  substitui quando `MachineCode` está vazio;
- presença isolada no catálogo de recursos comprova existência, mas não
  semântica industrial. A exceção aprovada é o pertencimento cadastral exato
  dos recursos de Pintura e Solda, pois a Manufatura confirmou que todos são
  apontáveis pelo próprio setor;
- `LASER → LASER1` é alias funcional oficial e exato;
- `JATO → setor Pintura` é associação funcional oficial e exata. O nome da
  operação continua sendo o `ActivityDescription` recebido (`JATEAMENTO`) e o
  recurso continua sendo `JATO`;
- não há fuzzy matching, prefixo ou aproximação automática;
- etapa sem mapeamento seguro permanece auditável e gera warning com
  `ActivityID`, `ActivityCode`, `WorkCenterCode`, `MachineCode` e a classificação
  `PENDENTE DE DECISÃO`.

O mapper representa explicitamente os tratamentos possíveis de uma
`ActivityOrder`:

```text
APONTÁVEL CONFIRMADO
APONTÁVEL EM MANUTENÇÃO
AUTOMÁTICA/NÃO MANUAL SATISFEITA
ETAPA TERMINAL CONFIRMADA
NÃO APONTÁVEL CONFIRMADO
PENDENTE DE DECISÃO
```

Somente `APONTÁVEL CONFIRMADO` gera `MappedProductionOperation` e pode ser
persistida em `catalogo_operacoes_op`. As classificações automática, em
manutenção, terminal e pendente permanecem no XML/inbox e nos diagnósticos da
mensagem. Isso preserva o roteiro recebido sem criar tarefa operacional,
apontamento fictício ou finalização durante a ingestão.

### 8.1 Matriz auditada da OP real `A9716901001`

| ActivityCode | ActivityDescription | WorkCenterCode | MachineCode | Setor Gestor | Recurso Gestor | Classificação | Fonte da decisão |
|---|---|---|---|---|---|---|---|
| `01` | `IMPRESSAO OP` | `PCP` | `PCP` | — | — | `AUTOMÁTICA/NÃO MANUAL SATISFEITA` | regra funcional/Manufatura: etapa cumprida por padrão, sem início/fim e sem apontamento fictício |
| `10` | `CORTE` | `CORTE` | `PLASMA` | `Corte` | `PLASMA` | `APONTÁVEL CONFIRMADO` | regra funcional existente, código canônico exato e projeção homologada no TESTE |
| `20` | `USINAGEM` | `USINA` | `CNC-01` | `Usinagem` | `CNC-01` | `APONTÁVEL CONFIRMADO` | regra funcional existente, código canônico exato e projeção homologada no TESTE |
| `30` | `INSPECAO` | `CALDER` | `INSPEC` | — | — | `APONTÁVEL EM MANUTENÇÃO` | regra funcional/Manufatura: operação de Qualidade confirmada, indisponível até existir a tela específica |
| `99` | `FINALIZADA` | `ALMOX4` | `ALMOX4` | — | — | `ETAPA TERMINAL CONFIRMADA` | regra funcional/Manufatura: marco terminal; sua presença no XML não finaliza a OP durante a ingestão |

`IMPRESSAO OP` não é uma operação manual normal. Ela é uma etapa automática já
satisfeita, representada por classificação própria para não distorcer a regra
como `NÃO APONTÁVEL CONFIRMADO`.

### 8.2 Evidências adicionais e limites

- `DOBRA/DOBRA1` e `PINTURA/PINT.L` foram preservados;
- `CORTE/LASER` resolve somente pelo alias oficial exato para `LASER1`;
- `PREPARACAO/PINT.L`, `PINTURA/PINT.L` e
  `INSPECAO PINTURA/INSPE2` são apontáveis por Pintura;
- `JATEAMENTO/JATO` é apontável por Pintura. O nome `JATEAMENTO` permanece
  exatamente como recebido no roteiro;
- o cadastro oficial de TESTE possui 6 recursos habilitados com
  `tipo_setor=Pintura` (`ESTUFA`, `INSPE2`, `PINT.L`, `PREP`, `RETOQ`, `TINTA`)
  e 44 com `tipo_setor=Solda`; todos são aceitos por código exato para o setor
  cadastrado. `JATO` é a sétima associação de Pintura, aprovada diretamente
  pela Manufatura apesar de seu `tipo_setor` ainda estar nulo no cadastro;
- recurso conhecido de outro setor não é promovido por nome, prefixo ou
  semelhança;
- nenhuma linha de apontamento ou evento de execução foi criada nesta etapa.

### 8.3 Matriz adicional da fixture real `10796502001`

| ActivityCode | ActivityDescription | MachineCode | Setor Gestor | Recurso Gestor | Classificação |
|---|---|---|---|---|---|
| `01` | `IMPRESSAO OP` | `PCP` | — | — | `AUTOMÁTICA/NÃO MANUAL SATISFEITA` |
| `10` | `CORTE` | `LASER` | `Corte` | `LASER1` | `APONTÁVEL CONFIRMADO` |
| `20` | `DOBRA` | `DOBRA1` | `Dobra` | `DOBRA1` | `APONTÁVEL CONFIRMADO` |
| `30` | `INSPECAO QUALIDADE` | `INSPEC` | — | — | `APONTÁVEL EM MANUTENÇÃO` |
| `40` | `PREPARACAO` | `PINT.L` | `Pintura` | `PINT.L` | `APONTÁVEL CONFIRMADO` |
| `50` | `JATEAMENTO` | `JATO` | `Pintura` | `JATO` | `APONTÁVEL CONFIRMADO` |
| `60` | `PINTURA` | `PINT.L` | `Pintura` | `PINT.L` | `APONTÁVEL CONFIRMADO` |
| `70` | `INSPECAO PINTURA` | `INSPE2` | `Pintura` | `INSPE2` | `APONTÁVEL CONFIRMADO` |
| `99` | `FINALIZADA` | `ALMOX4` | — | — | `ETAPA TERMINAL CONFIRMADA` |

### 8.4 Montagem — implantada estruturalmente na Etapa 3

Regra funcional confirmada: todo recurso canonicamente pertencente à Montagem
será uma operação apontável pelo próprio setor, com início, execução e fim,
seguindo o mesmo princípio de Pintura e Solda.

Na Etapa 3 a representação estrutural foi criada: `Montagem` existe em
`OPERATOR_SECTORS` (nível `operador_montagem`), em `USER_LEVELS`, na matriz de
navegação e em `RESOURCE_OWNED_POINTABLE_SECTORS`. Nenhuma migration foi
necessária, pois `usuarios.nivel` não possui CHECK.

O gatilho de projeção é exclusivamente `tipo_setor` do cadastro oficial. O
`gestor_pecas_test` ainda não possui nenhum recurso habilitado com
`tipo_setor=Montagem`, portanto o setor entra **sem posto configurado** e
nenhuma operação de Montagem é projetada. Os códigos cujo nome lembra montagem
(`MPRT1`, `MONTAGEM PM05`, `MT.CHA`, `LINHAS`, …) permanecem com `tipo_setor`
nulo e continuam sem autorização: nome, prefixo ou semelhança não criam
pertencimento.

Pendência cadastral registrada: a Manufatura precisa classificar os recursos
reais de Montagem. Também permanece pendente confirmar se Montagem repete a
restrição de Setup de Pintura e Solda; até a decisão, o comportamento padrão de
bancada foi mantido sem inventar exceção.

## 9. Segurança

- `defusedxml`;
- recusa explícita de DTD/ENTITY;
- UTF-8 válido;
- limite padrão do XML;
- validação de SOAPAction/operação/parâmetro;
- payload não é despejado em log;
- receptor controlado por feature flags;
- nenhuma escrita direta em tabela TOTVS;
- nenhuma escrita Gestor → TOTVS implementada nesta V1.

## 10. Banco e ambiente

Ambiente de homologação atual:

```text
TOTVS TESTE → backend TESTE → gestor_pecas_test
```

Essa associação foi comprovada em runtime via `pg_stat_activity` e health query,
não apenas inferida da `.env`.

O `gestor_pecas` REAL permanece separado e não deve ser usado em homologação.

O Quick Tunnel usado durante a validação é temporário e não constitui endpoint
de produção.

## 11. Questão de timezone aberta

Foi observada uma mensagem com `received_at` representado em UTC e
`processed_at` em horário local. A integração inbound não foi afetada, porém a
política deve ser normalizada antes de usar esses timestamps como base definitiva
para:

- duração;
- turnos;
- OEE;
- rastreabilidade;
- outbound ao TOTVS.

Não corrigir por ajuste visual; definir armazenamento e conversão de timezone de
forma única no backend/banco.

## 12. Limite da V1 e próximo passo

Concluído:

```text
WhoIs
ProductionOrder/upsert
ACK ResponseMessage
persistência e projeção segura
```

Fora da V1:

```text
ProductionAppointment
StopReport
retorno Gestor → TOTVS
cancelamentos/correções outbound
endpoint corporativo definitivo
```

A Etapa 2 e a Etapa 3 estão concluídas em TESTE.

Fronteira da Etapa 3, comprovada por teste automatizado:

```text
ProductionOrder TOTVS
  ↓
catalogo_pcp_ops / catalogo_operacoes_op
  ↓
Database.listar_proximas_operacoes_roteiro
  ↓
OperatorFlowService.listar_cartoes  →  /api/v1/operator/workbench
  ↓
Tela do Operador existente
  ↓
OperatorFlowService.executar → máquina de estados canônica
```

A integração de planejamento não recria, substitui nem duplica início e fim,
Setup, Produção, Parada/Retomada, Retrabalho, Finalização, crachá, máquina de
estados, regras de bloqueio ou eventos de execução. Esses comportamentos
permanecem sob os serviços canônicos do Gestor, e a origem TOTVS deixa de ser
relevante depois da projeção: nenhuma tabela, coluna ou evento de execução
carrega marca corporativa.

Para o setor de Corte, a OP e a operação vêm do TOTVS, mas tarefa, plano e
nesting pertencem ao SigmaNEST. O Qlik foi removido da arquitetura alvo e a
leitura direta do banco SigmaNEST é uma pendência concreta descrita em
`docs/INTEGRACAO_CORTE_SIGMANEST.md`.

O retorno futuro ao TOTVS deverá traduzir os eventos resultantes desse fluxo
para contratos corporativos comprovados, sem alterar sua origem nem escrever
diretamente nas tabelas do ERP.
