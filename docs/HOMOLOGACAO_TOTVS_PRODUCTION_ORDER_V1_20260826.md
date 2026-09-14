# Homologação técnica — TOTVS ProductionOrder V1

**Início da auditoria:** 26/08/2026  
**Homologação servidor-a-servidor concluída:** 27/08/2026  
**Escopo:** `TOTVS TESTE → Gestor TESTE` para `WhoIs` e
`ProductionOrder/upsert`  
**Escrita Gestor → TOTVS:** não implementada.

> Este documento foi atualizado para registrar a conclusão ao vivo de 27/08.
> As conclusões locais de 26/08 que tratavam rede/ACK como pendentes foram
> superadas pelas evidências reais abaixo.

## Resultado final

**APROVADO no ambiente TESTE.**

Comprovado:

- PCPA109 alcança o Gestor e valida `WhoIs`;
- PCPA111 envia `SC2/ProductionOrder` real;
- Cloudflare temporário encaminha ao backend TESTE;
- backend usa `gestor_pecas_test`, migration 16;
- OP é persistida e projetada;
- `receiveMessageResult` é um XML `TOTVSMessage/ResponseMessage` válido;
- `ProcessingInformation/Status=OK` é reconhecido pelo Protheus;
- `SOF010` registra status de sucesso.

## Contrato de retorno — correção da conclusão de 26/08

A evidência antiga em `SOF010` mostrava:

```text
OF_STATUS     1
OF_MSGRET     OK
```

Isso levou inicialmente à hipótese de que o SOAP bruto retornava texto `OK`.
A hipótese foi refutada pelo teste real e depois explicada nos fontes
Protheus 12.1.2510.

`pcpxfun.prx::PCPWebsPPI` faz parse de `receiveMessageResult` como XML e só
considera sucesso em:

```text
/TOTVSMessage/ResponseMessage/ProcessingInformation/Status = OK
```

O `OK` gravado em `SOF010` é uma constante/resultado normalizado pelo Protheus
após parse bem-sucedido.

A primeira tentativa real com texto puro `OK` produziu:

```text
OF_STATUS = 3
ERR_PRODUCTIONORDER_...
Não foi possível realizar o parse do XML de retorno do TOTVS MES.
```

Após implementar o `ResponseMessage`, o mesmo fluxo passou a produzir sucesso.

## Cadeia de fonte Protheus comprovada

Relatório de análise dos fontes 12.1.2510:

```text
PCPA111.prw  sincOP()
  → MATA650/PCPa650PPI
  → PCPWebsPPI()
  → receiveMessageResult parseado como XML

WSPCP.prw    getReturn()
  → construtor oficial TOTVSMessage/ResponseMessage
```

O mesmo `PCPWebsPPI` atende o fluxo do PCPA109/WhoIs e do
PCPA111/ProductionOrder.

## OP real utilizada

```text
OP           A9716901001
UniqueID     01|010004|A9716901001
Produto      PNT002002003
Descrição    BRACO ARTICULACAO
Quantidade   10 UN
```

Atividades no XML:

```text
01 IMPRESSAO OP / PCP
10 CORTE        / PLASMA
20 USINAGEM     / CNC-01
30 INSPECAO     / INSPEC
99 FINALIZADA   / ALMOX4
```

## Evidência no banco TESTE definitivo

Após a limpeza dos bancos históricos, o reenvio foi feito para o banco oficial
`gestor_pecas_test`.

Inbox:

```text
id                    2
transaction           ProductionOrder
external_id           01|010004|A9716901001
status                processed
result_action         inserted
activities_parsed     5
activities_projected  2
error_code            NULL
error_message         NULL
```

Cabeçalho:

```text
codigo_op          A9716901001
produto_codigo     PNT002002003
produto_descricao  BRACO ARTICULACAO
quantidade         10
ativo              true
totvs_unique_id    01|010004|A9716901001
```

Roteiro projetado:

```text
10 PLASMA / CORTE     / Corte     / ActivityID 108761
20 CNC-01 / USINAGEM  / Usinagem  / ActivityID 160893
```

As outras três atividades permanecem sem projeção automática por política
conservadora de mapeamento.

## Evidência no Protheus

Registro de sucesso observado:

```text
Transação    SC2
Registro     A9716901001
OF_STATUS    1
Programa     PCPA111
Arquivo      OK_PRODUCTIONORDER_20260827131817_A9716901001.xml
Mensagem     OK
```

## Banco e isolamento

Após consolidação do ambiente:

```text
gestor_pecas       → REAL preservado
gestor_pecas_test  → TESTE oficial / migration 16
postgres           → administrativo
```

A conexão do backend exposto no túnel foi comprovada em runtime com
`pg_stat_activity` e queries de health executadas em `gestor_pecas_test`.
Não houve sessão do Gestor no banco REAL durante a verificação.

Os antigos bancos de simulação/homologação foram removidos após dumps
restauráveis. Eles são apenas evidência histórica.

## WhoIs

O WhoIs foi homologado pelo PCPA109 antes do ProductionOrder e permaneceu
funcional após a unificação do construtor de resposta.

No banco TESTE oficial existe registro diagnóstico separado, sem efeito de
negócio.

## Segurança e invariantes preservados

- nenhuma escrita Gestor → TOTVS;
- nenhuma escrita direta em tabelas Protheus;
- parser seguro e payload limitado;
- inbox/auditoria preservadas;
- OPs existentes não são apagadas em lote;
- execução/apontamentos não são alterados pela ingestão de planejamento;
- recurso/setor desconhecido não é inventado.

## Limitações abertas

- apenas parte do roteiro real está semanticamente mapeada;
- retorno de erro estruturado `Status=ERROR` ainda não é requisito homologado da
  V1; falha interna usa SOAP Fault e não retorna falso sucesso;
- timestamps de inbox mostraram mistura de UTC e horário local e precisam de
  normalização antes de analytics/outbound definitivos;
- Quick Tunnel é temporário;
- contrato Gestor → TOTVS ainda precisa ser descoberto/homologado.

## Conclusão

`ProductionOrder V1` está **homologado no ambiente TESTE definitivo**. A próxima
etapa não é refazer conectividade: é fechar o mapeamento de roteiro/recurso/setor
e levar uma OP real recebida do TOTVS até o fluxo do operador, conforme
`ROADMAP.md`.
