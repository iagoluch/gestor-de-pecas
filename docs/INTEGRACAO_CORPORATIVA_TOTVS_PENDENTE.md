# Integração corporativa Protheus/TOTVS — pendências restantes

**Atualizado em:** 27/08/2026

> O nome deste arquivo é mantido por compatibilidade documental. A entrada de
> `ProductionOrder` não está mais pendente: ela foi homologada no ambiente
> TESTE. As pendências atuais concentram-se na semântica operacional completa,
> no retorno Gestor → TOTVS e na infraestrutura definitiva.

## Estado já confirmado

Estão implementados e homologados no TESTE:

- `TOTVS → Gestor` por SOAP 1.1 `PcfIntegService.receiveMessage`;
- `WhoIs` do PCPA109;
- `ProductionOrder/upsert` do PCPA111;
- parser seguro, inbox, hash, controle temporal e upsert incremental;
- persistência no `gestor_pecas_test` / migration 16;
- projeção conservadora em `catalogo_pcp_ops` e `catalogo_operacoes_op`;
- `TOTVSMessage/ResponseMessage` com `ProcessingInformation/Status=OK` aceito
  pelo Protheus.

O retorno bruto de sucesso **não é texto puro `OK`**. O `OK` armazenado em
`SOF010` é normalizado pelo Protheus depois do parse do `ResponseMessage`.

## Responsabilidades

### TOTVS/Protheus

Fonte de planejamento corporativo:

- OP;
- produto;
- quantidade planejada;
- roteiro/operações;
- recursos/códigos corporativos quando confirmados;
- datas/status de planejamento conforme contrato.

### Gestor de Peças

Fonte de execução real:

- estados de recurso;
- Setup/Produção/Parada/Retrabalho;
- quantidades boas/refugo/retrabalho;
- operador e participações;
- tempos físicos e rateios;
- nesting/Corte;
- histórico, auditoria e rastreabilidade;
- Andon, OEE, KPIs, relatórios e IA a partir dos serviços canônicos.

O Gestor não altera planejamento por UI e não escreve diretamente em tabelas do
Protheus.

## Persistência

PostgreSQL permanece como banco da aplicação. A arquitetura atual não prevê
substituí-lo por acesso direto ao banco do ERP.

Ambientes atuais:

```text
gestor_pecas       → REAL preservado
gestor_pecas_test  → TESTE oficial
```

Bancos antigos de simulação/homologação foram removidos após backup verificado;
menções em relatórios datados são históricas.

## Pendências funcionais imediatas

1. fechar a matriz oficial de atividade/centro de trabalho/máquina →
   operação/setor/recurso;
2. levar `ProductionOrder` real à fila do operador;
3. executar um ciclo de apontamento completo com OP originada no TOTVS;
4. validar que gestão/Andon/OEE/rastreabilidade refletem os mesmos eventos;
5. normalizar timezone antes de consolidar duração e outbound.

## Retorno Gestor → TOTVS

Ainda não implementado.

Há evidência nos fontes/estruturas estudadas de conceitos como:

```text
ProductionAppointment
StopReport
MATI681
MATI682
SOG010
SOH010
```

Esses nomes são apenas pontos de investigação. Antes de codificar, deve ser
comprovado nos fontes Protheus 12.1.2510/XSD/WSDL:

- endpoint e direção da chamada;
- autenticação;
- payload exato;
- campos obrigatórios;
- identidade/correlação;
- semântica de quantidade e estados;
- timezone;
- ACK/erro;
- idempotência e retry;
- correção/cancelamento;
- efeito real no Protheus.

Não usar SQL direto em SC2, SH6, SMO, SOG, SOH ou outras tabelas como mecanismo
de integração.

## Arquitetura outbound esperada

O clique do operador não deve depender da disponibilidade instantânea do ERP.
A direção prevista é:

```text
evento produtivo
  ↓ commit local
outbox
  ↓
sender/worker
  ↓
TOTVS
  ↓
ACK / retry / erro / reconciliação
```

A outbox só deve ser implementada depois que o contrato outbound estiver
comprovado o suficiente para definir identidade e semântica.

## Infraestrutura

O Quick Tunnel utilizado na homologação é temporário. Produção requer endpoint
corporativo estável aprovado pela TI, com TLS, autenticação/restrição de origem,
segredos, observabilidade, health checks, backup e rollback.

## Documento de direção

A ordem oficial é `ROADMAP.md`. Este arquivo detalha somente a fronteira
corporativa e as pendências de integração.
