# ROADMAP — Gestor de Peças

**Documento canônico de direção do projeto**  
**Atualizado em:** 11/09/2026 (Wave 6D — acompanhamento gerencial da Solda e ciclo da TV)  
**Workspace padrão:** `Gestor de Peças - Area de Testes`

> Este arquivo define a ordem oficial das próximas etapas. Quando um relatório
> histórico, prompt antigo ou documentação anterior divergir deste roadmap,
> prevalecem: (1) regras validadas com a Manufatura, (2) código/contratos atuais,
> (3) este `ROADMAP.md`, e só depois documentos históricos.

## 1. Objetivo final

Fechar o ciclo MES completo, mantendo responsabilidades claras:

```text
TOTVS / Protheus
  ↓ planejamento (OP, produto, quantidade, roteiro, recursos)
Gestor de Peças
  ↓ execução operacional
Operador
  ↓ eventos reais de fábrica
Gestor de Peças
  ↓ consolidação
Líder / Supervisor / Diretoria
  ↓
Andon / OEE / KPIs / rastreabilidade / relatórios / IA
  ↓ retorno operacional controlado
TOTVS / Protheus
```

Princípio de fonte de verdade:

- **TOTVS/Protheus:** planejamento corporativo e cadastros mestres que forem
  confirmados como pertencentes ao ERP;
- **SigmaNEST:** planejamento específico de Corte — tarefa, plano, nesting e a
  composição de produtos de cada agrupamento. **Qlik está removido da
  arquitetura alvo** e não pode voltar a ser fonte de verdade;
- **Gestor:** execução real, estados, tempos, quantidades, rastreabilidade,
  eventos operacionais, consolidações e inteligência;
- **PostgreSQL do Gestor:** persistência da aplicação; não é cache descartável
  do TOTVS e não deve ser substituído por escrita direta nas tabelas do ERP;
- **Frontend:** apresentação/interação; não cria regra industrial paralela.

## 2. Estado confirmado em 27/08/2026

### Ambiente e banco

```text
Workspace de desenvolvimento/homologação: Gestor de Peças - Area de Testes

PostgreSQL local:
  gestor_pecas       → REAL preservado
  gestor_pecas_test  → TESTE oficial
  postgres           → administrativo
```

Os bancos antigos de simulação/homologação foram removidos após dump e prova de
restauração. Seus nomes podem permanecer em relatórios históricos, mas **não são
alvos executáveis atuais**.

O backend atualmente exposto para a homologação TOTVS TESTE foi comprovado em
runtime usando `gestor_pecas_test`. Não inferir ambiente somente pela `.env`;
para homologações relevantes, confirmar a conexão efetiva.

**Versões de schema verificadas em 08/09/2026** (consulta direta a
`schema_migrations`): `gestor_pecas_test` = **24**; `gestor_pecas` REAL = **11**,
intocado. As migrations 23 e 24 da Wave 3 foram aplicadas somente no TESTE.

### Integração inbound TOTVS → Gestor

**HOMOLOGADA em TESTE para `WhoIs` e `ProductionOrder/upsert`.**

Comprovado:

```text
TOTVS TESTE
  ↓ PCPA109 / PCPA111
SOAP 1.1 PcfIntegService.receiveMessage
  ↓
Gestor TESTE
  ↓
PostgreSQL gestor_pecas_test
  ↓
TOTVSMessage/ResponseMessage
ProcessingInformation/Status = OK
  ↓
Protheus reconhece sucesso
```

Evidência operacional principal:

```text
OP              A9716901001
UniqueID        01|010004|A9716901001
Produto         PNT002002003
Descrição       BRACO ARTICULACAO
Quantidade      10 UN
Atividades XML  5
Projetadas      2
Status inbox    processed
Ação            inserted
```

Operações projetadas com mapeamento seguro atual:

```text
10 → CORTE     → PLASMA → Corte
20 → USINAGEM  → CNC-01 → Usinagem
```

Tratadas explicitamente sem gerar operação manual:

```text
01 → IMPRESSAO OP → PCP     → automática/não manual satisfeita
30 → INSPECAO     → INSPEC  → apontável Em manutenção
99 → FINALIZADA   → ALMOX4  → marco terminal
```

A resposta de sucesso **não é texto puro `OK`**. O `receiveMessageResult`
contém um `TOTVSMessage/ResponseMessage`; o Protheus parseia o XML e considera
sucesso quando `ProcessingInformation/Status = OK`. O `OK` visto no `SOF010`
é a mensagem normalizada pelo próprio Protheus após o parse.

### Fonte de dados do Corte — decisão de 27/08/2026

**Qlik: REMOVIDO da arquitetura alvo.** Nenhuma funcionalidade nova pode
depender de Qlik, QlikView, Qlik Sense ou exportação intermediária desses
produtos. A auditoria da Etapa 3 comprovou que o pacote `qlik/` já está órfão:
nenhum arquivo de `app/`, `backend/`, `mes/`, `scripts/` ou `tools/` o importa,
e `publicar_catalogo_sigmanest`/`publicar_catalogo_pcp` não possuem chamador em
produção. Uma guarda automatizada impede a reintrodução.

**Corte:**

```text
TOTVS        → OP do produto, quantidade e roteiro/operações
SigmaNEST DB → tarefas, planos, nestings e a composição de produtos do corte
Gestor       → correlaciona ambos e executa o apontamento pelo fluxo canônico
```

A OP é **do produto**. Não existe OP da tarefa, do plano ou do nesting: esses
são agrupamentos que contêm produtos, e uma mesma tarefa/plano/nesting pode
conter produtos de OPs diferentes. É proibido modelar `tarefa.codigo_op`,
`plano.codigo_op` ou `nesting.codigo_op` como relação 1:1. A correlação ocorre
no nível produto/peça, onde a OP existe.

A engenharia reversa do banco SigmaNEST foi executada na Etapa 3.1 e a
correlação está comprovada com dados reais. Detalhes em
`docs/INTEGRACAO_CORTE_SIGMANEST.md`.

### Itens ainda não homologados

- leitura direta do banco SigmaNEST para tarefas/planos/nestings do Corte;
- apontamento real completo usando uma OP originada do TOTVS;
- consolidação gerencial validada com esses mesmos eventos reais;
- retorno de execução Gestor → TOTVS;
- endpoint corporativo definitivo (o Quick Tunnel é somente homologação);
- produção.

## 3. Ordem oficial de execução

### ETAPA 0 — Higiene técnica e ambiente [EM ANDAMENTO]

Objetivo: manter um único caminho de TESTE e impedir confusão entre evidência
histórica, teste automatizado e ambiente operacional.

Concluído:

- `gestor_pecas_test` definido como banco TESTE oficial;
- bancos antigos removidos com dumps preservados e restauráveis;
- runtime TOTVS TESTE comprovado contra `gestor_pecas_test`;
- schema TESTE na migration 16;
- WSDL público e local respondendo;
- `WhoIs` validado pelo PCPA109.

Pendente antes de qualquer release:

- tornar `test_oee_evolution_equivalence` autossuficiente/determinístico, sem
  depender de banco histórico semeado manualmente;
- remover dependência de data fixa em `test_web_api` por relógio/data controlada;
- normalizar política de timezone. Hoje há evidência de `received_at` em UTC e
  `processed_at` em horário local em uma mesma mensagem; isso não bloqueia o
  inbound, mas bloqueia rastreabilidade/analytics/outbound definitivos.

**Gate:** suíte sem regressões novas e timestamps com semântica documentada.

---

### ETAPA 1 — ProductionOrder TOTVS → Gestor [CONCLUÍDA EM TESTE]

Objetivo: receber planejamento real do Protheus sem criar um ERP paralelo.

Concluído:

- SOAP `PcfIntegService.receiveMessage`;
- `WhoIs`;
- `ProductionOrder/upsert`;
- parser seguro;
- inbox e auditoria;
- identidade por `ProductionOrderUniqueID`;
- hash de mensagem e idempotência;
- controle temporal por `GeneratedOn`;
- upsert incremental da mesma OP;
- isolamento entre OPs;
- resposta `TOTVSMessage/ResponseMessage` aceita pelo PCPA111;
- prova no banco TESTE definitivo com `A9716901001`.

Ainda validar como extensão desta etapa, sem reabrir o que já está homologado:

- atualização real de quantidade/datas/roteiro/status da mesma OP;
- comportamento real de cancelamento/encerramento quando o contrato for
  observado no TOTVS;
- múltiplas OPs reais em sequência.

**Gate:** criação e atualização de OPs reais sem duplicação, stale overwrite ou
impacto em execução histórica.

---

### ETAPA 2 — Semântica oficial de roteiro, setor e recurso [CONCLUÍDA EM TESTE — 27/08/2026]

Objetivo: transformar as atividades recebidas do TOTVS em operações realmente
utilizáveis pelo Gestor, sem fuzzy matching ou regra inventada.

Trabalho:

1. levantar códigos reais de `ActivityCode`, `WorkCenterCode` e `MachineCode`;
2. cruzar evidência TOTVS/PCFactory com as regras da Manufatura;
3. classificar cada etapa como:
   - apontável pelo operador;
   - sistêmica/informativa;
   - qualidade;
   - logística/almoxarifado;
   - finalização;
   - ainda não definida;
4. formalizar aliases explícitos somente quando aprovados;
5. garantir que operações não mapeadas permaneçam auditáveis no XML/inbox e
   gerem warning, sem serem descartadas silenciosamente;
6. testar roteiros reais de Corte, Dobra, Usinagem, Serra, Solda, Pintura e os
   fluxos especiais pertinentes.

Caso inicial de referência: `A9716901001`, em especial `PCP`, `INSPEC` e
`ALMOX4`.

**Gate:** uma OP real entra com todas as etapas relevantes projetadas no setor e
recurso corretos, e as etapas não operacionais possuem tratamento explícito.

#### Auditoria funcional atualizada em 27/08/2026

Comprovado e preservado para a OP real `A9716901001`:

```text
10 → CORTE     → PLASMA → Corte     → APONTÁVEL CONFIRMADO
20 → USINAGEM  → CNC-01 → Usinagem  → APONTÁVEL CONFIRMADO
```

O mapper passou a registrar internamente um tratamento explícito por
`ActivityOrder`, incluindo `APONTÁVEL CONFIRMADO`, `APONTÁVEL EM MANUTENÇÃO`,
`AUTOMÁTICA/NÃO MANUAL SATISFEITA`, `ETAPA TERMINAL CONFIRMADA` e
`PENDENTE DE DECISÃO`. Somente `APONTÁVEL CONFIRMADO` gera operação. As demais
permanecem no XML/inbox com diagnóstico e não criam execução fictícia.

Regras funcionais incorporadas:

- `IMPRESSAO OP/PCP` é etapa automática/não manual já satisfeita, sem tarefa e
  sem apontamento fictício;
- `INSPECAO` e `INSPECAO QUALIDADE` com `CALDER/INSPEC` eram operações
  confirmadas e `APONTÁVEL EM MANUTENÇÃO` até existir a tela de Qualidade; a
  Etapa 7C entregou essa tela e as reclassificou como
  `INSPEÇÃO DE QUALIDADE CONFIRMADA`, projetadas inativas no roteiro;
- `FINALIZADA/ALMOX4` é marco terminal; sua mera presença no XML não finaliza a
  OP durante a ingestão;
- alias oficial exato `LASER → LASER1`;
- todos os recursos com pertencimento canônico a Pintura ou Solda são
  apontáveis pelo próprio setor;
- associação oficial exata `JATO → Pintura`, preservando o nome de roteiro
  `JATEAMENTO` e o código de recurso `JATO`;
- `PREPARACAO/PINT.L`, `PINTURA/PINT.L` e
  `INSPECAO PINTURA/INSPE2` são operações apontáveis de Pintura.

Auditoria do banco oficial `gestor_pecas_test`, migration 16:

- 6 recursos habilitados com `tipo_setor=Pintura`: `ESTUFA`, `INSPE2`,
  `PINT.L`, `PREP`, `RETOQ` e `TINTA`;
- `JATO` está com `tipo_setor` nulo no cadastro, mas a associação a Pintura foi
  validada diretamente pela Manufatura e formalizada no mapper canônico;
- 44 recursos habilitados com `tipo_setor=Solda`, todos cobertos por resolução
  exata baseada no cadastro;
- nenhum recurso com `tipo_setor=Montagem`; Montagem também não existe em
  `OPERATOR_SECTORS`, permissões ou rota operacional.

A regra funcional de Montagem está fechada: recursos que vierem a ser
canonicamente cadastrados como Montagem serão apontáveis pelo próprio setor,
com início, execução e fim, como Pintura e Solda. A ausência técnica atual não
bloqueia a semântica da Etapa 2. A criação progressiva do setor, permissões,
recursos, backend/frontend e fluxo do operador foi transferida para a Etapa 3.
Até essa implantação, nome semelhante a Montagem não autoriza projeção.

Validação automatizada direcionada nesta etapa:

- 29 testes unitários de parser/mapper/serviço/SOAP/WhoIs;
- 7 testes PostgreSQL em schema isolado de `TEST_DATABASE_URL`;
- cobertura explícita de PCP não manual, Qualidade Em manutenção, marco
  terminal sem finalização na ingestão, alias `LASER → LASER1`, ausência de
  fuzzy/prefixo, todos os recursos auditados de Pintura e Solda, nome
  `JATEAMENTO` preservado, Montagem não inventada, isolamento entre OPs,
  reenvio idempotente e ausência de escrita em execução.

Suíte Python completa: **328 testes executados, 326 aprovados e 2 falhas**. As
duas falhas são as pendências já registradas na Etapa 0 antes deste trabalho:
`test_oee_evolution_equivalence` depende de massa histórica manual e
`test_web_api` ainda espera a data fixa de 26/08/2026. Não houve falha nova nos
testes alterados ou na integração TOTVS.

**Gate fechado.** Todas as atividades observadas possuem tratamento funcional
explícito, operações comprovadas são projetadas sem fuzzy matching e etapas não
liberadas permanecem auditáveis. Montagem possui regra funcional definida e sua
implantação técnica pertence à Etapa 3. A Etapa 3 não foi iniciada.

---

### ETAPA 3 — Planejamento real na Tela do Operador [CONCLUÍDA EM TESTE — 27/08/2026]

Objetivo: o operador consumir diretamente a projeção derivada do TOTVS.

> **Fronteira normativa preservada:** a lógica de apontamento do Gestor é
> canônica. A integração TOTVS fornece planejamento ao domínio existente e não
> cria uma segunda lógica operacional. Início/fim, Setup, Produção,
> Parada/Retomada, Retrabalho, Finalização, crachá, máquina de estados, regras
> de bloqueio e eventos de execução continuam pertencendo exclusivamente aos
> serviços canônicos do Gestor.

Fluxo comprovado:

```text
ProductionOrder TOTVS
  ↓
catalogo_pcp_ops / catalogo_operacoes_op
  ↓
Database.listar_proximas_operacoes_roteiro
  ↓
OperatorFlowService.listar_cartoes
  ↓
/api/v1/operator/workbench
  ↓
WorkbenchPage (Tela do Operador existente)
  ↓
OperatorFlowService.executar → máquina de estados canônica
```

#### Auditoria do fluxo (Etapa 3A)

| Camada | Componente |
|---|---|
| PostgreSQL | `catalogo_pcp_ops`, `catalogo_operacoes_op`, `apontamentos_operacionais`, `eventos_apontamento_operador` |
| Repository | `Database.listar_operacoes_para_op`, `listar_proximas_operacoes_roteiro`, `listar_apontamentos_operacionais`, `enfileirar_apontamento_operacional`, `transicionar_apontamento_operador` |
| Service | `OperatorFlowService` (workbench), `CutService` (Corte), `ResourceStateService` |
| API | `backend/api/routers/operator.py` e `cutting.py` |
| Frontend | `OperatorPortalPage` → `WorkbenchPage` / `CuttingPage` / `HighlightPage` |
| Filtros da fila | `pcp.ativo`, `operacao.ativo`, ordem do roteiro, ausência de apontamento ativo/finalizado e `station_matches_route(setor, posto, codigo_recurso)` |

#### Gap encontrado (Etapa 3B)

Nenhuma incompatibilidade estrutural entre o que a ingestão TOTVS grava e o que
a fila canônica exige. A projeção do `ProductionOrder` já satisfaz o contrato
interno: `codigo_op`, `numero_operacao`, `descricao_operacao`, `tipo_setor`,
`codigo_recurso`, `ordem`, `ativo`, produto e quantidade. `op_por_tarefa` é
opcional (`tarefa_id` nulo), então uma OP sem tarefa de Destaque é aceita.

O único bloqueio real da OP `A9716901001` é **de dado, não de código**: sua
etapa `10 → CORTE → PLASMA` depende do planejamento de nesting, que hoje não
possui alimentador ativo (ver `docs/INTEGRACAO_CORTE_SIGMANEST.md`).
Enquanto o nesting não existir, a sequência mantém a Usinagem bloqueada — que é
o comportamento correto e **não foi contornado**.

#### Resultado comprovado

- OP TOTVS cuja etapa liberada é de um setor de bancada chega automaticamente à
  fila do recurso correto, com produto, descrição e quantidade do cabeçalho
  corporativo, e não aparece em recurso incompatível;
- `A9716901001` percorre a cadeia completa quando o Corte é concluído pelo
  caminho canônico existente: fila do `PLASMA` → apontamento de Corte → tarefa
  finalizada → `20 → CNC-01` liberada na fila da Usinagem;
- o ciclo Início → Setup → Retornar → Parada → Retomar → Retrabalho →
  finalização parcial → Finalizado roda sobre a OP TOTVS sem nenhuma alteração
  de regra, preservando bloqueio de `Retrabalho → Início`, exigência de crachá,
  limite de peças boas e separação de refugo;
- reenvio do `ProductionOrder` é idempotente e não duplica operação nem fila;
- nenhuma coluna, tabela ou evento específico de TOTVS existe na execução: os
  metadados corporativos ficam confinados ao planejamento.

#### Montagem

Criada a representação estrutural mínima e segura:

- `OPERATOR_SECTORS` passa a conter `operador_montagem / Montagem`, **sem posto
  configurado**;
- `USER_LEVELS`, `NAVIGATION_BY_LEVEL` e `CONSULTATION_TABS_BY_LEVEL` incluem
  `operador_montagem` (sem migration: `usuarios.nivel` não possui CHECK);
- `RESOURCE_OWNED_POINTABLE_SECTORS` passa a incluir `montagem`, aplicando a
  mesma regra funcional de Pintura e Solda;
- a Tela do Operador exibe empty state explícito para setor sem posto.

**Pendência cadastral registrada:** o `gestor_pecas_test` não possui nenhum
recurso com `tipo_setor='Montagem'`. Os ~100 códigos cujo *nome* lembra montagem
(`MPRT1`, `MONTAGEM PM05`, `MT.CHA`, …) permanecem com `tipo_setor` nulo e
**não são promovidos por semelhança**. Enquanto a Manufatura não classificar os
recursos, nenhuma operação de Montagem é projetada e o setor não possui estação.
Também permanece pendente confirmar se Montagem repete a restrição de Setup de
Pintura/Solda; até a decisão, o comportamento padrão de bancada foi mantido sem
inventar exceção.

#### Qualidade e marco terminal

`INSPECAO`/`INSPECAO QUALIDADE` com `CALDER/INSPEC` ficou **Em manutenção** até
a Etapa 7C (03/09/2026). Desde então é `INSPEÇÃO DE QUALIDADE CONFIRMADA`:
projetada em `catalogo_operacoes_op` como metadado inativo do roteiro, invisível
para o posto do operador e executada exclusivamente pela aba Qualidade.
`FINALIZADA/ALMOX4` continua marco terminal e não finaliza a OP na ingestão.

#### Correção complementar — elegibilidade posto ↔ setor/recurso (27/08/2026)

A primeira entrega da Etapa 3 deixou Pintura e Solda restritas ao recurso do
posto (`STATION_RESOURCE_CODES` mapeava "Pintura" → `PINT.L` e todas as estações
→ `SOLDA4`). Operações canônicas em `JATO`, `INSPE2`, `PREP`, `ESTUFA`, `RETOQ`,
`TINTA` e nos demais 44 recursos de Solda não chegavam à fila automática.

Regra corrigida, sem remapear recurso:

```text
operacao.tipo_setor      → determina qual fluxo/posto pode enxergar
operacao.codigo_recurso  → continua identificando o recurso real
```

- postos que representam uma **máquina** (Dobra, Usinagem, Serra, Corte)
  continuam exigindo igualdade exata com o recurso do roteiro;
- postos que representam o **próprio setor** (Pintura, Solda e Montagem) também
  aceitam qualquer recurso com pertencimento canônico ao setor;
- o pertencimento vem exclusivamente de `catalogo_recursos_pcfactory.tipo_setor`
  e da associação oficial `JATO → Pintura`. Nome, prefixo ou semelhança não
  criam elegibilidade;
- `codigo_recurso` **nunca** é convertido para o código do posto:
  `JATEAMENTO` permanece `JATO`, `INSPECAO PINTURA` permanece `INSPE2` e os
  recursos de Solda permanecem com seus próprios códigos, tanto na fila quanto
  em `apontamentos_operacionais` e nos eventos;
- apontar um recurso canônico do setor deixa de ser tratado como recurso
  divergente e não exige mais crachá de exceção;
- nenhum alias artificial foi criado. O único alias oficial continua sendo
  `LASER → LASER1`;
- exclusividade de estação de Solda, máquina de estados e regras de apontamento
  permanecem intactas.

A regra canônica (`SECTOR_OWNED_RESOURCE_SECTORS` e `OFFICIAL_RESOURCE_SECTORS`)
passou a viver em `app/core/resource_mapping.py`; o adaptador TOTVS apenas a
consome, eliminando a duplicação que existia entre ingestão e fluxo do operador.

Permanece como decisão cadastral da Manufatura, sem bloquear a etapa, modelar
estações internas de Pintura e Solda caso o roteiro corporativo passe a
detalhá-las.

**Gate fechado.** Uma OP originada no TOTVS chega ao posto correto e é
selecionável pelo operador sem seed fictício, usando exclusivamente os serviços
canônicos. A origem TOTVS deixa de ser relevante depois da projeção.

---

### ETAPA 3.1 — SigmaNEST → Gestor [CONCLUÍDA EM TESTE — 27/08/2026]

Objetivo: substituir definitivamente o Qlik como fonte do planejamento de Corte.

```text
TOTVS        → OP / produto / quantidade / roteiro
                        │
                        │ correlação no nível da peça
                        ▼
SigmaNEST DB → tarefa / programa / nesting / peças / máquina
                        │
                        ▼
Gestor       → fluxo canônico de apontamento (inalterado)
```

#### Fase A — engenharia reversa [CONCLUÍDA]

Banco auditado em **acesso somente leitura**: `SVR-DBLANTEK\SIGMANEST`,
`SNDBase2026`, SQL Server 2022 Express.

Estruturas e chaves confirmadas:

```text
Wo           PK WONumber                      19.247 linhas
Part         PK (WONumber, PartName)          19.995   FK Part.WONumber → Wo.WONumber
STPIPArc     PK AutoID                       189.171
ProgArchive  PK AutoID                        35.513
STOCK        PK SheetName                        388
```

Semântica comprovada:

- **Tarefa** = `ProgArchive.TaskName` (1.991 distintas), agrupa programas —
  observado até 121 programas em uma tarefa;
- **Programa/Plano** = `ProgArchive.ProgramName` (8.179 distintos), agrupa peças
  — observado até 45 WOs em um programa;
- **Nesting** = `ProgArchive` por `ProgramName` + `SheetName` + `RepeatID` +
  `ArchivePacketID`; a tabela é um arquivo de eventos;
- **Peça/produto** = `STPIPArc.PartName` + `WONumber` — **único lugar onde a OP
  existe**;
- **Máquina** = `ProgArchive.MachineName`, 2 valores (`Amada_ensis`,
  `Messer_XPR_300`), coerentes com o `CUT_MACHINE_MAP` já existente.

`WONumber == ProductionOrder.Number`: **COMPROVADO**. Das 4.542 OPs reais do
Protheus no banco REAL do Gestor, 905 (19,9%) existem em `Wo.WONumber` por
igualdade textual; as demais nunca passaram pelo Corte. O código de produto
**não** é chave — coincide em 84,7% dos casos, é prefixo do código Protheus em
13,3% e diverge em 2%. Normalização necessária: apenas caixa (65 linhas em
minúscula), já coberta por `limpa_codigo`.

`SN100`/`SN101`/`SN102`: semântica **NÃO COMPROVADA**. Existe correlação
estrutural (100% dos `SN102` de `ProgArchive` possuem `CompDate`, e nenhum
`SN100`/`SN101` possui), mas isso não vira regra. Usar `CompDate` explicitamente.

`DashboardProgramData` permanece **não confiável** como contrato: definição
inacessível ao login de consulta e erro de conversão de data já observado.

#### Fase B — contrato SigmaNEST → Gestor [CONCLUÍDA]

```text
backend/integrations/sigmanest_sqlserver.py  ← único lugar com SQL do SigmaNEST
mes/integrations/sigmanest/models.py         ← DTOs neutros
mes/integrations/sigmanest/gateway.py        ← porta + correlação com a OP TOTVS
scripts/auditar_sigmanest.py                 ← auditoria read-only
```

Os DTOs materializam a regra funcional: `SigmaNestTask` e `SigmaNestCutPlan`
**não possuem** atributo de OP; somente `SigmaNestPartLine` possui. A correlação
liga apenas OPs que já existem no catálogo canônico e devolve, separadamente, as
OPs vistas no SigmaNEST sem correspondência — que nunca são promovidas a OP nova.

Validado contra o banco real (recorte de 01/08/2026): 63 tarefas, 180 nestings,
2.251 linhas de peça, 637 OPs; **158 dos 180 nestings contêm mais de uma OP**,
confirmando que nesting ≠ OP. 491 OPs correlacionadas e 146 mantidas apenas como
diagnóstico.

Segurança verificada por teste: conexão `readonly`, `ApplicationIntent=ReadOnly`,
somente `SELECT ... WITH (NOLOCK)`, nenhum verbo de escrita ou DDL no módulo e
senha nunca registrada em log.

#### Fase C — sincronização incremental [CONCLUÍDA]

```text
SigmaNEST (read-only) → SigmaNestSyncService → catalogo_sigmanest_*
                      → Database.listar_fila_corte → CutService → Tela do Operador
```

- `app/database/sigmanest_repository.py` faz **somente upsert**, porque
  `publicar_catalogo_sigmanest` é um publicador de snapshot completo e inativaria
  tudo fora da janela incremental. O método antigo permanece intacto;
- identidades estáveis: `plano_hash = sha256(tarefa|programa|chapa|repeat_id)` e
  `linha_hash = sha256(tarefa|WONumber|PartName)`;
- marca d'água = `MAX(data_programa)` recuada por 7 dias de sobreposição;
- execução: `python scripts/sincronizar_sigmanest.py`.

**Migration 17 aplicada, aditiva:** `sigmanest_repeat_id`,
`sigmanest_archive_packet_id`, `sigmanest_comp_date`, `sigmanest_trans_type` e
`sigmanest_synced_at`. `TransType` é dado bruto auditável — nenhuma regra de
negócio o consulta e `status_programa` permanece nulo.

**Duas correções descobertas com dado real:**

1. `STPIPArc` também é arquivo de eventos (189.171 linhas para 47.174
   combinações reais). A leitura da Fase B duplicava a composição do nesting e
   passou a agregar por (programa, chapa, peça, WO);
2. o mapeamento de processos sugerido pelo modelo Qlik estava **deslocado**. A
   verificação contra 958 linhas reais fixou, com 100% de igualdade:
   `Data3→dobra`, `Data4→usinagem`, `Data5→solda`, `Data6→chanfro`.

**Prova com dado real** (schema isolado, 4.542 OPs reais do Protheus, janela de
01/08/2026):

```text
63 tarefas · 179 programas · 180 nestings · 699 peças · 637 OPs
491 OPs correlacionadas · 146 sem OP no Gestor → NÃO criadas
catalogo_pcp_ops 4.542 → 4.542  (nenhuma OP criada pelo SigmaNEST)
2a execução idempotente · 3a execução incremental por marca d'água
fila real do Corte: 51 tarefas no Laser e 12 no Plasma, com material,
programas e nestings reais; nenhum apontamento criado
```

#### Correção complementar — nesting concluído na origem (31/08/2026)

Decisão da Manufatura aplicada: `sigmanest_comp_date IS NOT NULL` significa que
o nesting já foi concluído no SigmaNEST e **não aparece mais como `Aguardando`**
na fila ativa do Corte. O predicado vive na consulta canônica
`Database.listar_fila_corte`.

A regra **apenas oculta da fila**. Ela não cria apontamento, não marca
`apontamentos_corte` como finalizado, não avança roteiro/OP e não toca a máquina
de estados. O registro continua persistido com `ativo = TRUE` e auditável, e a
regra é reversível pela própria origem.

Consequência intencional: uma OP com nesting concluído na origem e sem
apontamento no Gestor não tem a etapa de Corte considerada concluída pelo
roteiro. Avançar por dado da origem criaria execução sem apontamento; tratar
esse caso é decisão nova e separada.

#### Qlik

Confirmado **legado removível**: nenhuma chamada produtiva. A remoção física fica
para depois da Fase C, porque `qlik/catalog_sync.py`, `qlik/extract.py` e
`qlik/data_mapper.py` são a documentação executável da tradução de campos e
serviram de pista nesta auditoria. Três guardas automatizadas impedem
reintrodução.

**Gate fechado.** O planejamento real de Corte é lido do SigmaNEST, projetado
de forma incremental e idempotente nas tabelas canônicas, correlacionado à OP do
TOTVS sem criar OP paralela, e chega à fila real do Corte consumida pela Tela do
Operador existente. Nenhuma regra de apontamento foi alterada.

---

### ETAPA 4A — Auditoria execução → dados gerenciais [CONCLUÍDA EM TESTE — 31/08/2026]

Objetivo: provar que tudo que nasce na Tela do Operador alimenta uma única fonte
confiável para histórico, estado do recurso, tempos, quantidades e indicadores.

Cadeia auditada:

```text
Operador → API → OperatorFlowService → máquina de estados
        → apontamentos_operacionais + eventos_apontamento_operador
        → eventos_estado_recurso + eventos_quantidade_producao + historico
        → ManagementService.get_overview (physical_time / timeline / oee)
        → FrontendBackendFacade → Dashboard, Consulta Operacional e Andon
```

**Fonte única por informação, com fallback explícito:** estado físico em
`eventos_estado_recurso`; quantidades em `eventos_quantidade_producao` (a fonte
usada é declarada em `production.source`); execução em
`apontamentos_operacionais`; transições em `eventos_apontamento_operador`;
indicadores em `mes/analytics/oee.py`. Ausência nunca vira zero.

**Sem cálculo duplicado entre telas.** O Andon não recalcula: recebe
`consulta_operacional` e `inicio` prontos e apenas reagrupa. Dashboard e Andon
partem do mesmo `get_overview`. O frontend só formata. Travado por teste.

**Divergência encontrada e corrigida — relógio da sessão PostgreSQL.** A
aplicação grava `TIMESTAMP WITHOUT TIME ZONE` em hora local, mas a sessão do
banco rodava em UTC. Toda duração calculada em SQL contra `CURRENT_TIMESTAMP`
ficava 3 h adiantada enquanto a execução estava aberta — visível como
`03:00:22` num nesting recém-iniciado e, pior, inflando `cutting_real_seconds`
nos indicadores. Correção mínima: `PostgresPoolManager` fixa o fuso da sessão
(`GESTOR_DB_TIMEZONE`, padrão `America/Sao_Paulo`). Nenhuma regra de
apontamento, migration ou dado gravado foi alterado. Detalhes em
`docs/AUDITORIA_EXECUCAO_GERENCIAL_ETAPA_4A.md`.

**Divergência menor registrada, não corrigida:** a Management View mantém um
conversor local de segundos com formato diferente do `formatHours` compartilhado.
É apresentação, não cálculo; consolidar depende de decisão visual.

**Gate fechado.** Execução e leitura gerencial são consistentes, a fonte de cada
informação está declarada e a origem da OP (TOTVS, SigmaNEST ou manual) não
altera o cálculo. A Etapa 4B pode começar.

---

### ETAPA 4B — Simulação integral da fábrica [CONCLUÍDA EM TESTE — 31/08/2026]

Objetivo: validar o motor MES com a fábrica operando — vários setores ao mesmo
tempo, tempo passando, turno terminando, dia virando — e com uma OP originada
no TOTVS atravessando tudo isso.

Ambiente: `gestor_pecas_test`, schema 17, banco REAL intocado, SigmaNEST
somente leitura, porta 8000 reservada ao TOTVS e porta 8001 para a simulação.
Relógio virtual exclusivo da simulação; Windows e PostgreSQL não foram
alterados.

**Fluxo exercitado.** Fila → Setup → Produção → Parada → Retomada →
Retrabalho → parcial → quantidades boa/refugo → Finalização, com Corte, Dobra,
Usinagem e Solda simultâneos, mais quatro nestings reais do SigmaNEST
(`T3487`, `T3494`) finalizados pelo fluxo canônico do Corte.

**Continuidade temporal comprovada.** Intervalos automáticos (12:10–12:52 e
15:30–15:45), corte automático às 17:30 e às 21:30, operação aberta
atravessando H2 (17:30–21:30), a meia-noite e retomada em H1 (06:00–08:00) no
dia seguinte. A interrupção é gravada no horário oficial, não no instante da
detecção, e é idempotente. O evento físico não é fatiado na gravação: a
divisão diária acontece na leitura, recortando o segmento contra a janela do
filtro — sem duplicação nem perda de evento.

**OP TOTVS efetivamente apontada.** `A9717001001` e `A9717101001`
(`totvs_source_application = SIGAPCP`) percorreram `ProductionOrder` →
catálogo canônico → fila do posto de Solda → `OperatorFlowService` →
apontamento → eventos/estado físico/histórico → `ManagementService`. O
apontamento preserva `codigo_recurso = 'ROBO P'` do roteiro e registra
`maquina = 'Estação N'` como posto escolhido: nenhum alias foi criado.

**Andon.** Somente o verificador da 4B foi corrigido — ele procurava
`resources`/`items` na raiz, chaves que não existem; o contrato real agrupa em
`sectors[].resources[]`. O Andon não foi alterado. Confirmado que ele não
recalcula indicadores e que não converte ausência de estado físico em estado
inventado.

**OEE/KPI reconciliados de forma independente.** Disponibilidade, FTT e
`OEE = D × P × Q` foram recalculados por SQL bruto e aritmética própria,
batendo com `mes/analytics/oee.py`. Fora de turno é medido e exposto, mas não
entra no tempo disponível: acrescentar horas de `fora_turno` não altera
Disponibilidade nem OEE. Nenhuma fórmula foi alterada.

**Dois bugs comprovados e corrigidos.** (1) `listar_tempos_nesting_corte`
recortava a execução aberta no fim da janela, e a tela envia `fim` como
23:59:59 — um nesting iniciado há 1 s reportava 3.600 s, distorção que chegava
a `cutting_real_seconds`. Correção mínima: `as_of = min(fim, agora)`. (2) A
Consulta Operacional listava a mesma máquina duas vezes em modo de simulação
(`Gasparini` com estado real e `DOBRA1` como "livre"), porque comparava o
código técnico do catálogo com o nome do posto. Correção mínima: resolver a
identidade pelo mapa canônico existente. Ambos com teste de regressão. Nenhuma
regra de apontamento, fórmula, migration ou dado gravado foi alterado.

**Gate fechado.** O histórico permite reconstruir integralmente o que ocorreu
com cada OP sem depender do estado visual da tela. Reconciliação final:
**60 de 60 verificações consistentes**. Detalhes, evidências e reprodução em
`docs/SIMULACAO_INTEGRAL_FABRICA_ETAPA_4B.md`.

**Pendência registrada, fora do escopo desta etapa: saneamento de
recursos/postos.** Recursos de roteiro sem posto elegível (`SERRA4`, `SERRA6`,
`LASER`), 313 de 382 recursos sem `tipo_setor`, 4 códigos que diferem apenas
por capitalização e Montagem ainda sem recurso cadastrado. Nada disso foi
corrigido, mascarado ou contornado por alias — o bloqueio de Serra é o
comportamento correto para a configuração atual. **Tratado na Etapa 4C.**

---

### ETAPA 4C — Saneamento de recursos e postos [CONCLUÍDA EM TESTE — 31/08/2026]

Objetivo: deixar o cadastro de recursos e a relação recurso ↔ posto corretos e
com uma única fonte, corrigindo o que é comprovável e devolvendo à Manufatura
apenas o que exige decisão humana.

**Mapa centralizado.** Toda decisão de identidade de recurso vive em
`app/core/resource_mapping.py`. O alias oficial `LASER → LASER1` (Manufatura,
27/08/2026) morava só no adaptador TOTVS: a ingestão aceitava o código e a Tela
do Operador o recusava. Agora ingestão, fila, posto e relatórios consomem o
mesmo `canonical_resource_code`. Novos `ProductionOrder` reutilizam o cadastro
canônico porque `build_totvs_ingestion_service` já lê
`catalogo_recursos_pcfactory` filtrando `habilitado`.

**Serra resolvida.** `SERRA1` é a STARRET **S4220** e `SERRA2` a STRONG
**SFHA10** — o modelo está no próprio nome cadastral. `SFG-330` foi mapeada
para `SERRA3` (FRANHO RF-420) por marca e eliminação: o painel de produção
lista três serras, a tela tem três postos, dois já estavam fechados e a foto do
posto mostra uma Franho. `SERRA4` e `SERRA6` **não são gap de cadastro**: são
recursos de uma planilha de teste, usados só por OPs fictícias — o diagnóstico
da 4B foi corrigido. `SERRA5` é máquina real sem posto.

**Duplicidade por capitalização consolidada e a causa fechada.** Quatro pares
(`SCCGMM`/`SCCGmm`, `SCGM8`/`SCGm8`, `SCLCGM`/`SCLCGm`, `SSEDCGM`/`SSEDCGm`),
mesmo nome e zero uso, vieram de duas exportações do PC Factory. A variante
antiga foi **desativada, não apagada**. `publicar_recursos_pcfactory` passou a
reaproveitar a linha existente ignorando caixa, então a reimportação não recria
o problema. O Andon deixou de tratar esses códigos como alias ambíguo.

**Colisão entre código e nome corrigida.** `ALMOX4` é o código de um recurso e
o nome de outro (`ALMOXF4`); o mesmo ocorre com `RETRABALHO`/`RETR`. O Andon
indexava código e nome com o mesmo peso e anulava os dois aliases, exibindo a
mesma máquina em dois cartões. O código cadastral é a identidade e passou a
vencer o nome de outro registro; nome repetido entre códigos distintos continua
ambíguo. O Andon voltou a listar exatamente os recursos habilitados.

**313 recursos sem `tipo_setor` permanecem sem setor.** Nenhum tem roteiro,
apontamento ou estado físico, e o arquivo de origem do PC Factory não traz
coluna de setor. Classificar por nome seria inferência por semelhança e criaria
elegibilidade real em Solda. Fica como decisão em bloco da Manufatura.

**Matriz automática.** `RECURSO → SETOR → POSTO → ELEGÍVEL` para os sete
setores: 69 recursos setorizados, 64 elegíveis, 5 sem posto, **zero vazamento**
entre setores. Gerada por `scripts/sanear_recursos.py --matriz` e travada por
`tests/test_stage4c_resource_registry.py`. O código real da operação continua
preservado: `ROBO P` não vira `SOLDA4`, `PREP` não vira `PINT.L`.

**Gate fechado.** Nenhuma equivalência por semelhança de nome foi criada,
nenhum histórico de apontamento foi destruído e a máquina de estados não foi
tocada. Detalhes, provas e pendências humanas em
`docs/CADASTRO_RECURSOS_E_POSTOS.md`.

---

### ETAPA 5 — Retorno Gestor → TOTVS / ciclo de vida da OP [PARCIAL — 31/08/2026]

Esta numeração segue a decisão explícita da execução de 31/08/2026. A antiga
“consolidação gerencial” foi coberta pelos gates 4A/4B; a descoberta que estava
descrita como Etapa 6 e a implementação que estava descrita como Etapa 8 foram
absorvidas aqui, **sem antecipar a Etapa 7 de confiabilidade**.

Implementado:

```text
evento canônico persistido
  → read model somente leitura
  → TotvsOutboundService
  → mapper ProductionAppointment/StopReport
  → gateway SOAP WSPCP.ReceiveMessage
  → parser TOTVSMessage/ResponseMessage
```

- `ProductionAppointment 2.003` → WSPCP → MATA681 → SH6;
- `StopReport 1.001` → WSPCP → MATA682 → SH6;
- OP, operação, ActivityID e recurso são preservados do planejamento recebido;
- boas e refugo ficam separados;
- refugo exige código TOTVS explícito;
- retrabalho é bloqueado porque o contrato Protheus estudado não lhe dá destino;
- retomada fecha a parada anterior porque StopReport exige início e fim;
- chave `IDPCFactory` determinística por evento;
- dry-run padrão e envio com trava exata para `gestor_pecas_test`, host TESTE e
  confirmação literal;
- nenhuma alteração na máquina de estados, nenhuma origem paralela e nenhuma
  escrita direta em tabela TOTVS.

Comprovado no TOTVS TESTE (`Csed4j_dev`): PCPA112 executa os contratos como
“Apontamento de Produção”, mantém sucesso/erro e aceita reportes históricos de
quantidade zero com intervalo de tempo. Em 01/09/2026, o WSDL real foi obtido
na publicação externa TESTE `:1465/ws/WSPCP.apw?WSDL`: SOAP 1.1
document/literal, operação `RECEIVEMESSAGE`, namespace
`http://webservices.totvs.com.br/` e `SOAPAction`
`http://webservices.totvs.com.br/RECEIVEMESSAGE`. A saída publicada é
`RECEIVEMESSAGERESULT`, não `CRESPONSE`.

Um POST técnico sem mensagem de negócio alcançou o serviço e recebeu envelope
SOAP válido, mas foi recusado antes do processamento com HTTP 500/Fault
`AUTHENTICATION: USER NOT AUTHORIZED`. Como não houve 401/403,
`WWW-Authenticate` ou policy no WSDL, o mecanismo de autorização ainda não foi
inferido nessa primeira resposta. Depois da configuração local da credencial
REST TESTE, um POST com HTTP Basic retornou HTTP 200 e
`RECEIVEMESSAGERESULT/TOTVSMessage/ResponseMessage`; o `CXML` vazio foi
rejeitado objetivamente com `Status=ERROR`, código 1 e `Document is empty`.
Assim, HTTP Basic e o processamento SOAP estão comprovados sem envio de OP.

**Gate ainda aberto:** falta uma OP descartável autorizada e os códigos TESTE
de motivo de parada/refugo. Sem a OP ainda não há ACK de negócio emitido pelo
Gestor nem prova antes/depois no MATA650/PCPA112. Ver
`docs/INTEGRACAO_TOTVS_OUTBOUND_ETAPA5.md`.

---

### ETAPA 6 — Descoberta do contrato Gestor → TOTVS [ABSORVIDA PELA ETAPA 5]

O objetivo de descoberta foi executado dentro da Etapa 5 por decisão explícita
de 31/08/2026. Esta seção permanece apenas para registrar os critérios que não
podem regredir.

Evidências já encontradas nos fontes/histórico apontam para conceitos como:

```text
ProductionAppointment
StopReport
MATI681
MATI682
SOG010 / SOH010
```

Esses nomes foram confirmados por fonte oficial, código/documentação do
Protheus e tela PCPA112 do TESTE; não são mais apenas pistas.

Usar fontes originais Protheus 12.1.2510, XSD/WSDL e evidência de ambiente para
provar:

- endpoint/serviço real;
- autenticação;
- direção de chamada;
- payload exato;
- campos obrigatórios;
- identidade de OP/operação/recurso/operador;
- data/hora e timezone;
- boas/refugo/retrabalho;
- parada/motivo;
- ACK e erro;
- idempotência;
- retry;
- correção/cancelamento;
- efeito real no Protheus.

**Regra:** nunca escrever diretamente em SC2, SH6, SMO, SOG, SOH ou qualquer
outra tabela TOTVS para implementar integração.

**Gate de descoberta:** fechado. O gate de homologação prática permanece aberto
na Etapa 5 pelos bloqueios de ambiente ali registrados.

---

### ETAPA 7 — Outbox confiável do Gestor [CONCLUÍDA — 01/09/2026, executada como "Etapa 6"]

Esta frente foi executada em 01/09/2026 sob o rótulo **Etapa 6** na
comunicação de trabalho. A numeração do roadmap é mantida aqui para não
reescrever histórico; o conteúdo é o mesmo. Detalhamento em
`docs/INTEGRACAO_TOTVS_OUTBOX_ETAPA6.md` e evidência prática em
`docs/evidencias/TOTVS_OUTBOX_ETAPA6_2026-09-01.md`.

Entregue:

- migration 19 com `totvs_outbox` e `totvs_outbox_attempts`;
- enqueue na MESMA transação PostgreSQL do fato canônico do operador — o
  rollback do apontamento remove o item outbound junto;
- worker desacoplado, com `SELECT ... FOR UPDATE SKIP LOCKED`, lease e
  recuperação de `SENDING` abandonado;
- `idempotency_key` UNIQUE no banco, reutilizada por retry, timeout, reinício e
  reprocessamento;
- classificação de erro em transitório, autenticação/configuração, protocolo e
  ACK funcional, com backoff 1/2/5/10/30/60 minutos persistido;
- reprocessamento manual por serviço e CLI, sem editar payload;
- observabilidade por `metricas_outbound_totvs()`.

**Gate fechado.** Em 01/09/2026, no TOTVS TESTE real: o operador apontou com o
WSPCP inacessível, o commit local ocorreu, o item ficou em `RETRY` com a mesma
chave, o worker foi morto no meio de uma reserva e recuperado por lease, e com
o endpoint restaurado a mesma mensagem foi entregue com `Status=OK` e
`InternalId 783166`. Uma rejeição funcional real (`A680OPTOT`) virou `ERROR`
sem retry infinito. Nenhuma mensagem perdida, nenhuma duplicada.

**Correção final aplicada no mesmo dia.** O enqueue usava um `SAVEPOINT` para
não derrubar o apontamento se a gravação da outbox falhasse — o que permitia
justamente o cenário proibido: apontamento commitado sem a obrigação de
integração, perda que nenhum retry recupera. O `SAVEPOINT` foi removido. A
distinção passou a ser explícita: **ERP indisponível** commita e fica `PENDING`;
**obrigação que não pôde ser persistida** reverte a transação inteira
(`DatabaseIntegrityError`). Falta de `WasteCode`/`StopReasonCode` continua
commitando com item `ERROR` bloqueado, que agora guarda os **valores** do
refugo e o intervalo fechado da parada em `payload_context`, para lançamento
posterior no Protheus quando a Manufatura definir os cadastros.

**Banco REAL preparado, não promovido.** `gestor_pecas` está em schema 11 e a
aplicação exige 19. O gap foi auditado **somente em leitura** (sem achados
bloqueantes) e a cadeia 12→19 foi ensaiada fora do REAL em 0,293 s, preservando
todas as contagens, com constraints e índices válidos e a outbox funcional.
Procedimento, risco por migration e critérios de abortar em
`docs/PROMOCAO_SCHEMA_REAL_11_19.md`. Nenhuma migration foi executada no REAL e
a outbox permanece desligada por configuração.

Desenho original, mantido como referência:

Objetivo: desacoplar o clique do operador da disponibilidade instantânea do ERP.

Desenho alvo:

```text
operador executa ação
  ↓
Gestor grava evento produtivo
  ↓ COMMIT
outbox de integração
  ↓
worker/sender controlado
  ↓
TOTVS
  ↓
ACK / retry / erro auditável
```

Requisitos:

- `event_id` estável;
- idempotency/correlation key;
- estados `pending/sending/sent/acknowledged/retry/error` ou equivalentes;
- tentativas e backoff limitados;
- `last_error` sanitizado;
- nenhum payload/segredo sensível em log desnecessário;
- o apontamento local nunca é apagado porque o TOTVS ficou indisponível;
- reconciliação posterior possível.

Todos foram atendidos. Os estados implementados são
`PENDING/SENDING/RETRY/SENT/ERROR`; `acknowledged` não virou estado próprio
porque o ACK aceito **é** a condição de `SENT`, e um estado a mais sem
transição própria só criaria ambiguidade.

---

#### ETAPA 7A — Homologação E2E sem depender do GPOPSYNC real [CONCLUÍDA — HOMOLOGAÇÃO CONTROLADA, 02/09/2026]

O pipeline completo foi exercitado em schema efêmero de `gestor_pecas_test`,
substituindo somente `HTTP GPOPSYNC → XML ProductionOrder` por um responder
local que devolve byte a byte a fixture real da OP `1079689C001`, gerada pelo
`MATA650 12.1.2510`.

Comprovado:

- `MISS` local → `OrderProvisioningService` → sync sob demanda → uma única
  chamada HTTP para duas solicitações concorrentes → ingestão canônica;
- roteiro recebido com `ActivityCode`, `ActivityDescription`,
  `WorkCenterCode`, `MachineCode` e ordem preservados;
- `10/CORTE/LASER` projetado como recurso canônico `LASER1` e
  `99/FINALIZADA/ALMOX4` preservado uma vez, terminal/inativo/invisível;
- execução pelo `OperatorFlowService`, sem fatos produtivos inseridos por SQL,
  com boas e refugo separados;
- quatro obrigações atômicas: parada fechada, parcial, finalização e terminal;
- terminal com as duas boas reais, refugo zero e sem completar pelo planejado;
- `PENDING → SENDING → RETRY`, restart, payload/chave preservados e recuperação
  de `SENDING` abandonado pelo lease;
- sync, retry, tentativa terminal e processamento repetidos sem duplicação;
- teste automatizado leva os mesmos quatro itens a `SENT` usando o worker real
  e ACK controlado. Isso valida a máquina da outbox, não é ACK externo.

Não executado nesta rodada: envio dessas quatro mensagens ao WSPCP TESTE real,
porque a outbox/worker estão desligados e a OP usada como fonte do XML não foi
confirmada como descartável para novos movimentos no Protheus. O comando real
existe, mas exige confirmação literal do ambiente e da OP.

SigmaNEST: não aplicável à OP escolhida. A consulta somente leitura não
encontrou cadeia para `1079689C001`; nenhum nesting ou OP foi fabricado.

Evidência e reprodução:
`docs/evidencias/TOTVS_ETAPA7A_HOMOLOGACAO_CONTROLADA_2026-09-02.md` e
`scripts/homologar_totvs_e2e_etapa7a.py`.

O transporte controlado era o único limite desta etapa. A Etapa 7B fechou essa
lacuna com o GPOPSYNC/MATI650 real sem precisar repetir os movimentos outbound
já homologados. Assim, a 7A fica concluída no seu escopo de homologação
controlada.

#### ETAPA 7B — E2E real da OP sob demanda [CONCLUÍDA — HOMOLOGAÇÃO COM TRANSPORTE REAL, 03/09/2026]

No banco `gestor_pecas_test`, a OP `00615903001` começou em MISS real e percorreu
`OrderProvisioningService → ProductionOrderOnDemandSyncService → GPOPSYNC →
MATI650 → TotvsProductionOrderIngestionService → PostgreSQL → consulta
operacional`. Foi uma chamada HTTP real, em 1,317 s, ao endpoint TESTE `:1467`,
com HTTP 200 e `Content-Type: text/xml`.

Comprovado:

- `ProductionOrder` 2.004 real, `SIGAPCP`, `MATA650 12.1.2510`, UniqueID
  `01|010004|00615903001`, produto `IPCX04014041P`, quantidade 15 e reportada 0;
- quatro atividades recebidas: IMPRESSAO OP automática, CORTE/LASER, INSPECAO
  em manutenção e 99/FINALIZADA/ALMOX4 terminal;
- catálogo com uma operação apontável `10/CORTE/LASER1` e o marco 99 preservado
  inativo, sem setor e invisível ao operador;
- inbox processada uma vez, cabeçalho uma vez, uma solicitação `DONE`, zero
  apontamentos, zero quantidade, zero histórico e outbox 0 antes/depois;
- segunda consulta `local`, com zero chamada adicional ao ERP.

A OP matriz `10795102002` confirmou o caso real de cabeçalho sem roteiro:
HTTP 200, quantidade 14, `ListOfActivityOrders` vazio. O Gestor não inventa
operações. A execução revelou e corrigiu um bug de representação: o estado não
é mais `timeout`; agora responde `sem_roteiro`, `found=false`, com a mensagem
"OP existente no TOTVS, porém sem roteiro operacional utilizável", e consultas
seguintes não repetem o ERP.

Evidência e reprodução:
`docs/evidencias/TOTVS_ETAPA7B_HOMOLOGACAO_REAL_2026-09-03.md` e
`scripts/homologar_totvs_e2e_etapa7b.py`.

---

#### ETAPA 7C — Apontamento da Qualidade [CONCLUÍDA — IMPLEMENTADA, 03/09/2026]

A operação `INSPECAO`/`CALDER`/`INSPEC` **deixou de ser "APONTÁVEL EM
MANUTENÇÃO"**. A tela específica passou a existir, e com ela a classificação
`INSPEÇÃO DE QUALIDADE CONFIRMADA` no mapper.

Regra funcional implementada:

- a Qualidade é uma **capacidade de setor**, não um perfil, login ou aplicação.
  Habilitada para **Dobra, Usinagem e Serra** (bancadas da Caldeiraria);
  **Corte fica de fora**. A lista canônica vive em `app/core/quality.py` e é o
  único ponto a alterar para habilitar um setor novo;
- a operação de inspeção passou a ser **projetada** em `catalogo_operacoes_op`
  com `inspecao_qualidade = TRUE`, `ativo = FALSE` e `tipo_setor = NULL` — a
  mesma estratégia do marco terminal. O roteiro completo a exibe como contexto,
  sem torná-la apontável pelo posto produtivo; o read model do marco terminal
  continua somando apenas operações ativas;
- a fila da Qualidade é **exclusivamente local**: `catalogo_pcp_ops` +
  `catalogo_operacoes_op` + `apontamentos_operacionais`. A tela **não** aciona
  `ProductionOrderOnDemandSyncService` nem `GPOPSYNC`, e existe teste que falha
  se isso mudar. Quem libera a inspeção é a **conclusão da operação anterior**,
  não um botão manual;
- inspeção **unitária**, peça a peça, contra o **template de cotas do produto**:
  primeira definição pelo operador, alteração posterior somente por
  Supervisor/Líder, validada no backend. O padrão usado fica em **snapshot** na
  peça, então editar o template não altera inspeção histórica;
- RNC é domínio único (`qualidade_rnc`), habilitada apenas quando existe cota
  `Não conforme`, obrigatória antes de concluir a peça, e cota não conforme
  **nunca** resulta em `Aprovada` — recusado no serviço e no banco;
- PDF do produto embutido na própria tela (limitação de quiosque), com regra
  explícita de "mais recente" por versão; sem desenho, a inspeção continua
  liberada.

**Movimento TOTVS pelo mecanismo canônico, comprovado:** abrir a inspeção
executa `OperatorFlowService.executar("Início")` sobre a operação `INSPECAO`, e
a última peça executa `"Finalizado"`. Com a outbox habilitada em schema
descartável e a OP real `A9716901001`, preencher cotas e abrir RNC **não**
alteraram a `totvs_outbox` (3 → 3); o fechamento da inspeção criou exatamente um
`production_appointment` da operação `30`, com `<ActivityCode>30</ActivityCode>`
e `<MachineCode>INSPEC</MachineCode>`, e a chave de idempotência duplicada foi
recusada pelo banco. **Nenhum envio ao WSPCP foi executado**; o item fica
`PENDING` no worker/retry existentes.

Migration **21** criou template, cotas, sessão de
inspeção, peça, resultado de cota, RNC e desenho do produto. `GPOPSYNC`,
`MATI650`, contrato WSPCP, parser, outbox e SigmaNEST **não** foram alterados.

Testes: 611 backend (OK) e 59 frontend (OK), com build Web aprovado.

Pendências registradas, sem escolha por inferência:

1. o marco terminal continua sendo planejado quando as operações **apontáveis**
   terminam, sem esperar a `INSPECAO`. Se a Manufatura decidir que o terminal
   deve aguardar a Qualidade, é alteração de regra a autorizar;
2. a edição de template por Supervisor/Líder existe e está testada na API, mas
   ainda não possui ponto de entrada na área gerencial;
3. nenhum desenho real foi publicado no TESTE.

Evidência: `docs/evidencias/QUALIDADE_ETAPA7C_2026-09-03.md`.

---

#### WAVE 1 — Correções e estabilização [IMPLEMENTADA, 04/09/2026]

Sem alterar os contratos homologados de pull/outbound TOTVS ou a leitura do
SigmaNEST, a estabilização consolidou o roteiro completo (concluída, atual e
próximas), bloqueio por setor/recurso, histórico e tempos do Corte, fila e
conclusão da Qualidade, retorno rastreável de retrabalho à operação produtiva
anterior, filtros gerenciais/Andon e ciclo de contexto/streaming da IAgo.

A migration **22** (`SCHEMA_VERSION` 22) acrescentou apenas os vínculos de
rastreabilidade/idempotência do retrabalho originado pela inspeção. A unidade
dimensional da experiência da Qualidade é fixa em `mm`. Uma inspeção composta
inteiramente por retrabalho encerra sua sessão e retorna o saldo à operação
anterior pelo `OperatorFlowService`; não cria produção nova nem outbound
paralelo. O roteiro completo usa a conclusão canônica de tarefa/nestings para
reconhecer Corte, e a fila local da Qualidade usa a mesma evidência.

#### WAVE 2 — UX do operador, Corte automático e Dashboard gerencial [IMPLEMENTADA, 04/09/2026]

Nenhum contrato homologado foi tocado: TOTVS (pull `GPOPSYNC`/`MATI650`, outbound
WSPCP) e SigmaNEST continuam como estavam, e o SigmaNEST segue **somente
leitura**. Não houve migration nova; o schema permanece em **22**.

**Roteiro do operador.** O dropdown `Operação` foi removido: os cards do roteiro
passaram a ser o seletor. Eles ficaram compactos (~165 x 44 px, wrap responsivo),
preservam as cores semânticas de concluída/atual/próxima e marcam a seleção de
forma aditiva, sem apagar a cor do estado.

**Exceção de etapa (regra restaurada).** A Wave 1 tinha transformado
`actionable` (etapa atual + posto compatível) em bloqueio absoluto, o que matou a
regra de exceção que já existia no projeto. O `OperatorFlowService` voltou a
separar as três decisões:

- `station_eligible` — o posto executa a operação (setor + recurso). É o bloqueio
  duro; nenhuma confirmação o dispensa. `Dobra - Gasparini` continua sem apontar
  `CORTE`;
- `selectable` — o operador pode escolher a etapa. Etapa concluída permanece
  fechada;
- `requires_confirmation` — etapa fora da atual, do próprio posto: segue a regra
  canônica pré-existente `confirmacao_etapa_anterior_obrigatoria` /
  `confirmacao_recurso_obrigatoria`, com crachá autorizado e auditoria.

A tela pede uma confirmação em linguagem de operador (OP, etapa atual, etapa
selecionada) **antes** de trocar a seleção; cancelar preserva a etapa atual e
selecionar um card não registra nenhum evento produtivo.

**Ajuste de apontamento — 08/09/2026.** No Workbench normal, qualquer etapa do
roteiro que ainda não esteja concluída pode ser selecionada, mesmo quando
pertence a outro setor/recurso ou é o marco `INSPECAO`/`FINALIZADA`. A seleção
fora da etapa atual sempre mostra a confirmação; o apontamento mantém a
autorização canônica por crachá para etapa anterior pendente e/ou recurso
divergente. `Corte` e `Destaque` continuam nos seus fluxos especializados e não
recebem essa seleção genérica.

**Corte automático.** O `SigmaNestSyncService` — o mesmo do
`scripts/sincronizar_sigmanest.py`, sem segundo pipeline — passou a rodar em
ciclo dentro do processo Web (`_sigmanest_sync_loop`), fora do laço de eventos,
incremental pela marca d'água com sobreposição e idempotente. A tela é
invalidada pelo SSE já existente, e só quando a projeção realmente muda. A
pesquisa da fila de Corte virou **filtro** do que já está disponível; ela não é
mais o mecanismo que descobre ou importa a tarefa. Configuração:
`GESTOR_SIGMANEST_SYNC_ENABLED` (liga sozinho quando o SigmaNEST está
configurado), `GESTOR_SIGMANEST_SYNC_INTERVAL_SECONDS` (120 s) e
`GESTOR_SIGMANEST_SYNC_OVERLAP_DAYS` (7).

**Dashboard gerencial.** Os cards cuja informação principal era arquitetura,
fonte, fallback ou contrato técnico saíram das telas de gestão e deram lugar a
KPIs de decisão. Dois indicadores novos, ambos calculados no backend:

- **Confiabilidade (MTBF/MTTR)** — falha de equipamento é a parada classificada
  no grupo de **manutenção corretiva** do catálogo `catalogo_status_recursos`
  (`EQUIPMENT_FAILURE_STOP_GROUP`, hoje `0003`), e nunca por texto de motivo.
  Manutenção preventiva vive no grupo `0002` e corretamente não é falha; parada
  marcada como programada também não. `MTBF = tempo operacional ÷ falhas` e
  `MTTR = tempo de reparo ÷ reparos concluídos`, com o tempo operacional vindo da
  classificação produtiva canônica sobre o tempo físico consolidado. Sem catálogo
  de manutenção, sem falha no período ou sem tempo operacional, o indicador
  permanece explicitamente indisponível.
- **Capacidade/Utilização temporal** — base real é o **calendário produtivo**
  cadastrado (`CalendarService.period_summary`); a carga é o tempo físico ocupado
  (produção + setup + retrabalho), nunca o tempo rateado às OPs. É publicada como
  utilização temporal (a base do TEEP), não como capacidade em peças: essa
  exigiria tempo padrão/ciclo ideal confiável por operação, que o Gestor ainda
  não possui completo. Recurso sem calendário permanece `nao_configurado`.

O `OEE` e os demais KPIs canônicos não foram recalculados nem duplicados: o
frontend continua apenas recebendo, formatando e apresentando.


#### WAVE 3 — Consolidação do fluxo de apontamento [IMPLEMENTADA, 08/09/2026]

Aplicação do documento oficial `Fluxo de apontamento.docx` sobre o que já estava
homologado nas Waves 1 e 2. Nenhum contrato TOTVS foi tocado, o SigmaNEST
continua **somente leitura** e nenhuma movimentação produtiva real foi executada.
Migrations **23** e **24** (`SCHEMA_VERSION` 24), aplicadas **somente** em
`gestor_pecas_test`; o banco REAL `gestor_pecas` permanece em 11.

**Quem manda no avanço.** O avanço de etapa é decidido pelo estado local do
Gestor. O TOTVS fornece OP, roteiro, produto, quantidade e datas; o SigmaNEST
fornece o planejamento de Corte; o Gestor é a autoridade de execução. Não há —
nem passa a haver — consulta ao Protheus para anunciar a etapa corrente: a
ausência de pull de OP já estava provada na Etapa 6.1 e não foi reaberta. Marco
terminal e `IMPRESSAO OP` seguem `AUTOMATIC_SATISFIED`, sem apontamento fictício.

**Inspeção transitória.** O documento oficial diz que a inspeção "pode ser passada
direto" enquanto os operadores de máquina são treinados, mas ela não pode ser
desligada. Foi implementado `POST /quality/inspections/bypass`, que grava status
`DISPENSADA` com crachá autorizado e motivo, **sem** `apontamento_id`, **sem**
`template_id`, sem peça aprovada, sem cota medida e sem RNC — a restrição
`ck_qualidade_inspecao_dispensa` impede que a dispensa se disfarce de inspeção. A
OP dispensada sai da fila de elegíveis; a operação é idempotente. Solda e Pintura
não têm checklist dimensional: elas apontam a inspeção apenas para contabilizar o
tempo, usando o recurso efetivo do próprio posto (`recurso_efetivo` em
`OperatorFlowService`), e nunca ficam bloqueadas por ela.

**Pausas automáticas configuráveis.** Os horários saíram do domínio e viraram
`pausas_automaticas_setor` (migration 23), semeada exatamente com os valores já
em vigor — Almoço 12:10–12:52 (42 min) e Café 15:30–15:45 (15 min) para os nove
setores — de modo que o comportamento não mudou na aplicação da migration.
`shift_boundary.configured_breaks()` lê a configuração por setor e cai no
fallback de `ManufacturingRules.automatic_breaks` só quando não há registro. Tela
gerencial em `/inicio/pausas`.

**Destaque por tarefa e por plano.** O Destaque deixou de ter fila tradicional de
máquina. `listar_fila_destaque` agrupa por tarefa e devolve os planos, com
`situacao` `PARCIAL`/`COMPLETA` e progresso de corte. Um plano cortado pode ser
destacado imediatamente; a tarefa fecha sozinha quando o último plano disponível
é destacado (`_fechar_tarefa_se_completa`). O plano nunca aparece solto: a tarefa
pai encabeça cada bloco. A migration **24** acrescentou `plano_hash` a
`eventos_destaque_tarefa`, que passou a registrar o escopo do evento.

**Contagem de chapas — divergência real corrigida.** O repositório já usava
`repeat_id` no `plano_hash`, mas `montar_snapshot` deduplicava por
`(tarefa, programa, chapa)` e colapsava as repetições: várias chapas físicas
viravam uma linha só. A chave de deduplicação passou a incluir `RepeatID`
(`backend/integrations/sigmanest_sqlserver.py`), e `quantidade_chapas` é a
contagem das linhas projetadas. Não se assume "1 nesting = 1 chapa" em lugar
nenhum.

**Sincronização observável do Corte.** Ciclo automático e botão "Atualizar
tarefas" passam pelo mesmo `SigmaNestRefreshCoordinator`, serializado por
`asyncio.Lock`: um clique durante um ciclo em andamento adere a ele
(`aderiu_a_ciclo_em_andamento`) em vez de abrir um segundo pipeline. A tela
mostra a última sincronização vinda do backend; falha na origem preserva a fila
local com mensagem de operador, sem vazar traceback, ODBC ou SQL, e sem
interromper o ciclo seguinte. A marca d'água é
`MAX(catalogo_sigmanest_planos_corte.data_programa)` recuada por
`DEFAULT_OVERLAP_DAYS = 7`; a releitura sobreposta é segura porque a projeção é
idempotente. A pesquisa continua sendo filtro, nunca gatilho de importação.

**Qlik removido de fato.** A pasta `qlik/` saiu da raiz do repositório; a coluna
`maquina_qlik` virou `maquina_sigmanest` (migration 23); `.gitignore` e
`scripts/package_web_release.py` perderam as entradas de credencial. Um teste de
guarda reprova qualquer reaparição em `app/`, `backend/`, `mes/`, `scripts/` e
`tools/`. Sobrevivem apenas o SQL histórico das migrations 2 e 3, o próprio
`RENAME`, os seeds de schema 11 usados pelos ensaios de migração e os artefatos
de evidência já gravados da Etapa 4B — nenhum deles é dependência funcional.

#### Corrida no on-demand TOTVS — corrigida no fechamento da Wave 3 [08/09/2026]

Achado pela suíte completa (aparecia só sob carga; passava 5/5 isolado). A
ingestão do líder grava o **cabeçalho da OP antes das operações do roteiro**.
Quem consultava a mesma OP exatamente nessa janela lia "cabeçalho local sem
roteiro" e recebia `sem_roteiro` — resposta terminal errada sobre uma OP que
estava prestes a ficar pronta, e que ainda chamava `_reconcile_no_route_request`.
O ponto vulnerável era o lookup **anterior à reserva** (`step 1` de
`sync_production_order_on_demand`) e, em seguida, o `_poll_local` do seguidor.

Correção: "cabeçalho sem roteiro" só é resposta terminal quando **não há
sincronização em curso** para aquela OP (`totvs_op_sync_requests.status` diferente
de `PENDING`). Enquanto o líder trabalha, o chamador vira seguidor e espera —
dentro do próprio `timeout_seconds`, nunca além dele; esgotado o prazo, a resposta
parcial volta a valer exatamente como antes. O líder não foi afetado: a leitura
dele continua conclusiva, porque ele acabou de processar a resposta do TOTVS.
Nenhuma segunda chamada ao ERP é aberta pelo seguidor. Coberto por dois testes
determinísticos em `tests/test_totvs_on_demand.py`, que reproduzem a janela sem
depender de carga.

#### Ajustes pós-Wave 3 — Andon, Usinagem e Qualidade [IMPLEMENTADOS, 08/09/2026]

**Composição do Andon de parede.** O quadro deixou de ser um grid 2x2 simétrico e
passou a duas colunas independentes: cada painel parte de `flex-basis: auto`, com
a altura que a demanda ativa exige, e o painel de baixo absorve o restante.
Corrigido no caminho o grupo de recursos, que usava `grid-template-rows: auto
minmax(0,1fr)` e deixava metade do painel morta em painéis de grupo único (Solda,
Pintura). Todos os cartões têm a mesma altura, por token de faixa de resolução
(122 px em Full HD, 113 px em 801–960, 92 px até 800, 176 px em 2K/4K). Medido em
carga máxima normal (20 recursos ativos): 0 recortes de conteúdo e nenhuma
rolagem de página em 1920x1080, 1600x900 e 2560x1440.

**Solda por estação.** Confirmado no código antes de qualquer mudança: quando o
operador de Solda escolhe o posto, é a estação que vai como recurso no evento de
estado (`operator_flow.py` → `resource_state.registrar_estado`), e o Andon monta
um recurso não-catalogado com pertencimento canônico ao setor (`andon.py`). Em
produção o Andon já mostrava um cartão por estação; o defeito estava no fixture
da pré-visualização. A divisão por estação é condicional e só vale enquanto o
backend mandar a Solda como grupo único — quando a relação oficial de recursos
definir agrupamentos próprios, o painel segue o backend.

**Fila da Qualidade por setor de origem.** A operação de inspeção entra do TOTVS
sem `tipo_setor` próprio e a fila não filtrava nada: uma peça pronta na Dobra
aparecia também na Qualidade da Usinagem e da Serra. O dono da inspeção passou a
ser a última etapa apontável antes dela no roteiro — quem produziu a peça — com a
origem derivada em SQL a partir do catálogo de operações, **sem alteração de
schema e sem migration**. O recorte vale na fila, no resumo, no histórico, na
abertura (`qualidade_op_outro_setor`) e na dispensa. Origem não resolvível
permanece visível em todos os setores, para não sumir silenciosamente.

**Imagens das máquinas de Usinagem.** Fotos do `MP-CAL-001 — Manual de Processos
Fabris GTS` rev. 02, seções 8.1.1 a 8.1.5, ligadas ao posto pelo nome exato do
cadastro (`app/core/resource_mapping.py`); nenhum nome foi criado. Falta a foto do
Torno Mecânico (`TORNOC`), que usa o ícone do setor até a imagem chegar.

---

### ETAPA 8 — Implementar retorno de execução ao TOTVS [ABSORVIDA PELA ETAPA 5]

O mapper, o gateway e o envio manual controlado foram implementados na Etapa 5.
Outbox, retry e reconciliação não foram antecipados.

Ordem recomendada, sujeita ao contrato comprovado da Etapa 6:

1. `ProductionAppointment` — primeiro caso simples e controlado;
2. `StopReport` — paradas e motivos;
3. ampliar para refugo, retrabalho, setup, correções/cancelamentos somente se o
   contrato oficial exigir/permitir.

Cada implementação deve ter:

- DTO neutro;
- mapper explícito;
- sender/gateway separado do domínio;
- persistência/outbox;
- teste de contrato;
- teste idempotente;
- teste de erro/retry;
- trilha de auditoria.

**Gate:** permanece o gate prático da Etapa 5: um apontamento emitido pelo
Gestor deve aparecer no TOTVS TESTE com ACK e prova antes/depois.

---

### ETAPA 9 — Reconciliação bidirecional

Objetivo: detectar divergência entre o que o Gestor enviou e o que o TOTVS
aceitou/processou.

Precisamos responder para cada evento:

```text
foi criado no Gestor?
foi enfileirado?
foi enviado?
foi aceito pelo TOTVS?
qual retorno/código?
houve retry?
há divergência pendente?
```

Criar visão técnica/administrativa de integração sem permitir alteração
arbitrária de histórico produtivo.

**Gate:** nenhum evento fica indefinidamente “no limbo” sem estado explicável.

---

### ETAPA 10 — Homologação MES ponta a ponta

Escolher uma única OP de TESTE controlada e provar:

```text
1. criar/liberar OP no TOTVS TESTE
2. PCPA111 sincronizar ProductionOrder
3. Gestor receber e projetar roteiro
4. OP aparecer no posto correto
5. operador iniciar execução
6. executar Setup/Produção/Parada/Retomada conforme roteiro
7. registrar quantidades
8. finalizar operação
9. gestores acompanharem Andon/KPIs em tempo real
10. relatórios/rastreabilidade refletirem os mesmos eventos
11. Gestor gerar outbound
12. TOTVS receber apontamento/parada
13. ACK ficar reconciliado
14. nenhum dado ser duplicado
```

**Gate:** ciclo completo repetível sem intervenção manual no banco.

---

### ETAPA 11 — Infraestrutura corporativa definitiva

Objetivo: remover mecanismos temporários de homologação.

O Quick Tunnel/`trycloudflare.com` é descartável e **não entra em produção**.

Arquitetura de produção deve ser definida com TI, incluindo:

- URL corporativa estável;
- TLS;
- reverse proxy/API gateway quando aplicável;
- autenticação e restrição de origem;
- gestão de segredos;
- health checks;
- logs/correlation IDs;
- monitoramento e alertas;
- backup/restore;
- timeout/retry;
- separação rígida TESTE/REAL;
- plano de rollback.

Também é necessário preparar a migration do banco REAL de forma controlada. O
`gestor_pecas` atualmente preservado não deve ser atualizado ou usado em
homologações apenas para “igualar versão”.

**Gate:** ambiente REAL isolado e aprovado pela TI, sem apontar o TOTVS REAL para
infraestrutura de TESTE.

---

### ETAPA 12 — Piloto produtivo e expansão

Começar pequeno e mensurável. Prioridade recomendada: **Corte (Laser/Plasma)**,
por ser o fluxo com maior conhecimento e evidência acumulada.

Expansão sugerida após o piloto:

```text
Corte
→ Dobra
→ Usinagem
→ Serra
→ Solda
→ Pintura
→ demais fluxos/logística conforme regra validada
```

Cada setor só avança depois de:

- fluxo operacional aprovado;
- dados gerenciais coerentes;
- outbound/reconciliação estáveis quando aplicável;
- operadores/liderança treinados;
- rollback conhecido.

## 4. Regras que não podem ser quebradas pelo roadmap

- Manufatura prevalece sobre PCFactory/TOTVS quando se trata de regra funcional
  já validada.
- TOTVS é fonte de planejamento; Gestor não deve alterar planejamento por UI.
- Nenhuma escrita direta em tabela TOTVS.
- Nenhum fuzzy mapping de recurso/setor.
- Frontend não recalcula OEE nem regra industrial.
- Não apagar/regravar histórico produtivo para “corrigir” integração.
- TESTE e REAL nunca se cruzam.
- Bancos históricos removidos são evidência em dump/documento, não destinos.
- Toda alteração de contrato deve ter evidência e teste.
- Todo texto deve permanecer UTF-8 sem corrupção de acentos.
- **A lógica de apontamento do Gestor é canônica. A integração TOTVS fornece
  planejamento ao domínio existente e não cria uma segunda lógica operacional.**
- Qlik está removido da arquitetura alvo e não pode voltar como fonte de verdade.
- A OP é do produto. Tarefa, plano e nesting agrupam produtos e não possuem OP
  própria; a correlação com o SigmaNEST ocorre no nível produto/peça.

## 5. Próxima ação concreta

**Etapas concluídas: ETAPA 3 — Planejamento real na Tela do Operador (com a
correção de elegibilidade Pintura/Solda) e ETAPA 3.1 — SigmaNEST → Gestor.**

**Etapa concluída: ETAPA 4 — Auditoria execução → dados gerenciais (4A),
simulação integral da fábrica (4B) e saneamento de recursos e postos (4C).**

**Etapa concluída: ETAPA 5 — Retorno Gestor → TOTVS / ciclo de vida da OP.**
Em 01/09/2026 o Gestor enviou nove mensagens de negócio reais ao WSPCP do TOTVS
TESTE, todas com `Status=OK` e `InternalId` (783154 a 783162): sete
`ProductionAppointment` (quantidade zero, parcial, novo apontamento, dois
encerramentos de operação com `CloseOperation=true` e refugo com
`WasteCode=RP`) e dois `StopReport` (`StopReasonCode` `0010` e `0018`). O efeito
foi conferido no PCPA112, com todos os registros "Integrado com sucesso", e no
MATA650, onde a OP `A9716901001` mudou de **verde/Em aberto** para
**laranja/Iniciada** já com o apontamento de quantidade zero. Códigos reais de
refugo e de parada foram levantados no próprio TESTE; o `wasteCode=1` do arquivo
do integrador foi descartado por não existir na base. Evidência completa em
`docs/evidencias/WSPCP_TESTE_HOMOLOGACAO_NEGOCIO_2026-09-01.md`.

**Etapa concluída: ETAPA 5C — efetivação da produção no TOTVS.** A investigação
das fontes Protheus `12.1.2510` mostrou que o `ProductionAppointment` **é** o
mecanismo de efetivação: `MATA681` gera o SD3 (`A680GeraD3`) e chama `A250Atu`,
que faz `C2_QUJE += D3_QUANT` e grava `C2_DATRF` — mas **somente quando a
operação apontada é a última do roteiro** (`A680UltOper()`, avaliada sobre
SG2/SHY). Na Etapa 5B só existiam no catálogo do Gestor as operações `10` e `20`
do roteiro 35, que ainda tem `30 INSPEC` e `99 ALMOX4`; por isso nada era
efetivado. O mesmo explica a OP `PCMDPG01001` da PC-Factory, cujo roteiro 15
termina em `99` e que só recebe apontamento da operação `20`.

Comprovado por envio real em 01/09/2026: apontando a operação `99 / ALMOX4` da OP
`A9716901001`, o Protheus gerou o SD3 e a OP passou de `C2_QUJE` 0,00 / legenda
**Iniciada** para `C2_QUJE` 10,00 / legenda **Encerrada totalmente**, sem
nenhuma escrita direta em `SC2`. Nenhum contrato novo foi necessário; apenas o
`ActivityID` virou opcional no mapper, já que o adapter `MATI681` nunca lê esse
campo. Evidência em
`docs/evidencias/TOTVS_EFETIVACAO_PRODUCAO_ETAPA5C_2026-09-01.md`.

**Correção complementar concluída: marco terminal TOTVS.** O marco terminal
(`99 / FINALIZADA / ALMOX4`) passou a ser preservado no próprio
`catalogo_operacoes_op` — coluna `marco_terminal`, linha sempre `ativo = FALSE`,
`tipo_setor` nulo e constraint que impede reativá-la. Nenhum posto ALMOX4 nem
setor Logística foi criado e a Tela do Operador continua cega para ele, porque
já filtra `ativo IS TRUE`. O outbound ganhou um read model canônico
(`buscar_marco_terminal_outbound_totvs`) e um mapper próprio que só emite o
apontamento terminal quando **todas** as operações apontáveis estão concluídas
pela máquina de estados do operador — nunca na ingestão, em operação
intermediária ou em parcial aberta. A quantidade sai de uma função canônica
única (`terminal_approved_quantity`): apenas as peças boas da última operação
produtiva, sem somar etapas intermediárias, sem contar refugo e sem usar o
planejamento para completar o encerramento. A chave idempotente reutiliza o
gerador determinístico do outbound, ancorada em OP + operação terminal.

**Ciclo completo comprovado em 01/09/2026 na OP `PCMHBW01001`.** Ela entrou no
Gestor pelo caminho real de integração (PCPA109 → Sincronização, filtro
`C2_NUM = "PCMHBW"`), foi executada pelo fluxo canônico do operador nas
operações 10 e 20 (8 peças boas) e o marco terminal disparou sozinho:
`ActivityCode 99`, `MachineCode ALMOX4`, `ApprovedQuantity 8`,
`CloseOperation true`, ACK `Status=OK` com InternalId 783165. No MATA650 a OP
passou de **0,00 / laranja-Iniciada** para **8,00 / vermelha-Encerrada
totalmente**, com `C2_DATRF` preenchido — sem nenhuma escrita direta em `SC2`.

As tentativas anteriores reforçam a robustez: `A9716901001` foi recusada com
`A680OPTOT` por já ter sido encerrada com o mesmo marco (não duplicação no lado
do ERP) e `A9717001001` parou em `Itens Sem Saldo Bloqueados`, condição de
estoque do ambiente. Evidência completa em
`docs/evidencias/TOTVS_MARCO_TERMINAL_2026-09-01.md`.

Após o reinício do serviço do Gestor a projeção automática foi validada na
ingestão real de uma segunda OP (`PCMIXQ01001`): o roteiro chegou já com o marco
terminal `99/ALMOX4` inativo e sem setor, e o terminal corretamente **não** foi
emitido, por não haver nenhuma operação concluída.

**Etapa concluída: outbox, retry e confiabilidade do outbound TOTVS**
(comunicada como "Etapa 6"; corresponde à ETAPA 7 deste roadmap). Em
01/09/2026 o envio deixou de depender da disponibilidade instantânea do ERP: a
outbox é gravada na MESMA transação PostgreSQL do apontamento (migration 19,
`totvs_outbox` e `totvs_outbox_attempts`), o operador recebe sucesso no commit
local e um worker independente entrega ao WSPCP com reserva
`FOR UPDATE SKIP LOCKED`, lease, backoff persistido de 1/2/5/10/30/60 minutos e
`idempotency_key` UNIQUE reutilizada por todo retry. Comprovado no TOTVS TESTE
com WSPCP inacessível, worker morto no meio da reserva e entrega posterior da
mesma mensagem (`InternalId 783166`), além de rejeição funcional real
`A680OPTOT` encerrada como `ERROR` sem retry infinito. A garantia transacional
foi endurecida na revisão final: não há `SAVEPOINT` no enqueue, então falha ao
persistir a obrigação reverte a transação inteira, enquanto o ERP indisponível
segue commitando normalmente. O envio automático nasce desligado:
`GESTOR_TOTVS_OUTBOX_ENABLED` e `GESTOR_TOTVS_OUTBOX_WORKER_ENABLED` são
`false` por padrão. Detalhes em `docs/INTEGRACAO_TOTVS_OUTBOX_ETAPA6.md`.

**Etapa concluída (parcial por bloqueio do ERP): ETAPA 6.1 — sincronização de OP
sob demanda (02/09/2026).** O operador digita uma OP inexistente no Gestor e ela
é buscada e carregada sozinha, pelo MESMO pipeline inbound do push — parser,
mapper, roteiro, recurso, marco terminal e persistência canônica são os mesmos,
sem segunda implementação de importação de OP. Foram acrescentados o caso de uso
`sync_production_order_on_demand`, a fronteira neutra `OrderProvisioningService`
(a execução continua cega para a origem TOTVS), a migration **20**
(`totvs_op_sync_requests`, UNIQUE por OP) e os estados da Tela do Operador
("Buscando OP no TOTVS...", "OP não encontrada no TOTVS.", "Não foi possível
consultar o TOTVS no momento.").

A descoberta foi conclusiva e vem de resposta do próprio ambiente: **o Protheus
não possui mecanismo suportado para o Gestor solicitar uma OP.** O `WSPCP.apw`
implementa apenas `productionappointment` e `stopreport` — `ProductionOrder`
responde `Transação "PRODUCTIONORDER" não implementada`; o EAI genérico está
ativo mas sem adapter `ProductionOrder` registrado (o app host tem 11 adapters,
nenhum de OP) e sem aplicação externa cadastrada;
`totvseai/standardmessage/v1/contents` devolve HTTP 500 para toda transação;
`MTPRODUCTIONORDER`/`MTINTEGRATIONAPS` respondem `PRTCHKUSER: WebService
invalido para este login` e não trazem `ActivityID`/`ActivityDescription`; o
REST `/api/pcp/v1/productionOrders` funciona mas devolve só cabeçalho, sem
roteiro. `FWHOSTCOMMUNICATION.RUNMETHOD` existe, mas é comunicação entre hosts
Protheus com objeto `FwSerializable` — não é caminho suportado para acionar
`PCPA111::sincOP()`.

Homologação real em `gestor_pecas_test` com a OP `1079689C001`, que existia no
Protheus e não no Gestor, usando a mensagem `ProductionOrder` **real gerada pelo
MATA650 12.1.2510**: MISS local → solicitação HTTP → pipeline canônico → OP
`01|010004|1079689C001` com roteiro `10 CORTE/LASER1` e marco terminal
`99/ALMOX4` inativo e invisível → segunda busca local sem nova comunicação. OP
inexistente, indisponibilidade e duas solicitações simultâneas também foram
provadas (uma única sincronização lógica, uma OP, um marco terminal). Nenhum
outbound foi gerado pela ingestão e o SigmaNEST permaneceu somente leitura.

**Validação final dos serviços padrão (02/09/2026) — decisão C.** Antes de
tratar a rotina customizada como definitiva, `MTPRODUCTIONORDER` e
`MTINTEGRATIONAPS` foram validados pelo WSDL real e com OPs reais de `010004`.
Três bloqueios independentes: (a) `PRTCHKUSER` bloqueia `GETPRODUCTIONORDER` e
`BRWPOOPERATIONS` — mas `GETHEADER` no mesmo serviço responde 200, provando que
é liberação por método/usuário, e o fault não muda com nenhum `USERCODE`;
(b) não existe parâmetro de empresa/filial no WSDL e o `tenantId` é ignorado
(100/100 linhas em `010001` nos três testes), enquanto as OPs relevantes são de
`010004`; (c) **decisivo** — falta `ItemDescription` (obrigatório no parser),
falta a lista de operações no cabeçalho e falta `ActivityDescription`. Prova com
o mapper real sobre o `ProductionOrder` do PCPA111 da OP `1079689C001`: com
descrição → operações `[('10','LASER1'),('99','ALMOX4')]` e marco terminal 1;
apagando só a descrição → operações `[]` e marco terminal 0. Nenhum dos 228 web
services SOAP nem dos 565 serviços REST publicados fornece a descrição da
operação de uma OP. Portanto a rotina customizada da seção 3 do documento é a
solução **definitiva**, não uma alternativa. O Gestor não foi alterado por esta
validação.

**Etapa 6.2 concluída após correção e republicação (03/09/2026).**
A investigação cirúrgica dos fontes 12.1.2510 achou o ponto de reaproveitamento:
`PCPA111::sincOP()` → `mata650PPI()` → `PCPa650PPI()` → **`MATI650("", TRANS_SEND,
EAI_MESSAGE_BUSINESS, "2.004")`**, que **devolve o ProductionOrder em memória**
(`aRet[2]`). A montagem é portanto separável do transporte `PCPWebsPPI`, e o modo
**inline** é possível — o fallback push não foi necessário. Foi entregue
`fontes/10-PCP/GPOPSYNC.prw` (`WSRESTFUL gestorpecaspo`,
`POST /gestorpecas/v1/production-order`), um adaptador que valida a entrada,
posiciona a SC2 na filial pedida (troca `cFilAnt` por requisição e restaura
sempre — o mesmo idioma do padrão TOTVS em `mata650.prx`/`MATA010PPI.prw`), chama
o adapter oficial e devolve o XML com `EncodeUTF8`, como o `PCPa650PPI` faz. Não
reconstrói XML, não lê SC2/SG2/SHY para montar mensagem e não grava nada: o
trecho `TRANS_SEND` do `MATI650` não tem `RecLock`/`MsUnLock`/`dbDelete`. Estado
todo `Local`/`Private` da requisição, sem variável global mutável. Nenhum fonte
padrão TOTVS foi alterado.
Documentação e testes em `protheus/README.md`,
`scripts/homologar_totvs_op_sob_demanda_etapa62.py` e nos testes de contrato de
`tests/test_totvs_on_demand.py`. O transporte principal do Gestor não precisou
de alteração; a Etapa 7B acrescentou somente o estado explícito `sem_roteiro`
para o caso real de cabeçalho sem atividade operacional.

[CONFIRMADO] O fonte corrigido foi recompilado/publicado no Protheus TESTE. O
endpoint `POST /rest/GESTORPECASPO/gestorpecas/v1/production-order` na porta
1467 abre o contexto solicitado e
executa o `MATI650` real: OP ausente retorna 404/`notFound`; OPs reais das
filiais `010001` e `010004` retornam HTTP 200 com o UniqueID correspondente.

A Etapa 7B comprovou o consumo pelo Gestor com a OP `00615903001`, sem fixture
ou replay, e fechou o gate. Não alterar novamente o GPOPSYNC nem reabrir a
investigação dos serviços padrão sem fato novo.

**Preparação do banco REAL para o piloto (01/09/2026).** `gestor_pecas` está em
schema 11 e a aplicação exige 19. O gap foi auditado somente em leitura, sem
achados bloqueantes, e a promoção 11→19 foi ensaiada fora do REAL com dados
representativos, aprovada em 0,293 s sem perder registro. **Nenhuma migration
foi executada no banco REAL.** Runbook, risco por migration e critérios de
abortar em `docs/PROMOCAO_SCHEMA_REAL_11_19.md`. Não iniciar reconciliação
bidirecional.

**Wave 6A concluída (11/09/2026) — calendário operacional, hora extra planejada e
classificação central de parada.**

Turno normal **08:00–17:30**; fora de turno **17:30–08:00**. **Hora extra
planejada** passou a ser representada pelo cadastro que já existia: exceção
`disponivel_extra` em `excecoes_calendario_produtivo`. Não é um segundo turno
fixo, não ganhou tela nova e não tem tabela nova. Quando planejada, o período
integra a janela operacional (`CalendarService.operational_intervals`) e entra na
disponibilidade do período; quando não, o mesmo período permanece fora de turno.

**O relógio, sozinho, nunca bloqueia apontamento.** 18:00, 21:30, 01:00, 06:00 e
07:30 são horários operacionalmente válidos (`ManufacturingRules.appointment_allowed_at`).
Fora de turno muda a contabilidade de disponibilidade, não a permissão de apontar.
Fora de turno não compõe disponibilidade e não é parada da máquina.

**Fora de turno é grandeza global de calendário.** `consolidate_physical_time`
passou a usar a união temporal dos intervalos `fora_turno` no total global: o
mesmo intervalo noturno visto em Corte, Dobra e Solda deixou de ser somado três
vezes. As leituras por recurso e por setor continuam intactas, e
`out_of_shift_attributed_seconds` / `out_of_shift_duplicated_seconds` expõem a
diferença para auditoria.

**Classificação central de parada.** `ManufacturingRules.classify_stop` decide
PLANEJADA/NÃO_PLANEJADA a partir do catálogo PCFactory já existente — grupo
`0002 — PARADA PROGRAMADA` — sem inventar nomes de motivo. Precedência: motivos
sempre não planejados → fora de turno → `planejado` do catálogo → grupo →
interrupção programada do evento → NÃO_PLANEJADA por omissão. "Sem apontamento" e
"Recurso s/op" são sempre NÃO_PLANEJADA. A cor deriva da classificação (amarela /
vermelha) em um único mapa; `StopReasonFields` e o cartão do Andon deixaram de
decidir cor por `grupo_codigo === "0002"` e passaram a consumir
`classificacao`/`cor` e `stop_classification`/`color` do backend.

**Parada planejada deixou de afetar o OEE, pela entrada temporal.** A fórmula
canônica de `mes/analytics/oee.py` não foi alterada. O que mudou é o intervalo que
entra nela: `oee_seconds_by_category` remove a parada planejada do tempo
disponível, exatamente como o intervalo cadastrado do turno já sai da
disponibilidade do calendário. Parada não planejada continua penalizando
Disponibilidade e OEE. `time_bases` corrigiu `planned_downtime_seconds`, que antes
recebia o tempo de `fora_turno`; fora de turno agora vive em
`out_of_shift_seconds`.

**Alerta "Recurso possui tempo disponível de turno sem estado físico registrado":
removido da apresentação, cálculo preservado.** Investigado e concluído que não é
bug: um recurso ocioso dentro do turno — sem OP alocada, sem operador no posto —
legitimamente não tem estado físico, e essa é a condição operacional "Sem
apontamento", já classificada como parada não planejada e já visível no Andon e no
OEE. Emitir a mesma informação como erro de auditoria produzia um alerta por
recurso ocioso por dia, sem ação possível. `inspect_calendar_gaps` continua
existindo e passou a alimentar `auditoria.diagnostics.calendar_gaps` com
severidade `info`, fora da lista de alertas.

Cobertura: `tests/test_wave6a_calendario_operacional.py` (25 testes, os 18 casos
temporais obrigatórios). Regressão verde em calendar, OEE, manufacturing rules,
operator flow, management, alertas, categorias de evento e analytics temporal,
mais `vitest` de Andon e operador e `tsc -b` do frontend. Banco REAL intocado;
nenhuma migration nova.

**Wave 6B concluída (11/09/2026) — portão Setup/Qualidade da primeira peça.**

O fluxo do operador em Dobra, Usinagem e Serra passou a ser
`Selecionar OP → Iniciar (livre) → produz a primeira peça → Finalizar recusado,
orientando a apontar o Setup → botão Setup abre o checklist → medidas
conferidas → primeira peça aprovada → lote liberado e a OP retoma a produção
sozinha → o operador produz o resto do lote e finaliza normalmente`. A mudança
é de **experiência**:
o motor da primeira peça (`FirstPieceService`), a inspeção dimensional
(`QualityInspectionService`), a máquina de estados e a persistência canônica
continuam os mesmos, sem estado paralelo e sem migration.

Saíram da tela do operador, por serem apresentação redundante: o card "Primeira
peça" e a aba "Qualidade" do posto. **O botão Setup permanece**: ele é o
apontamento de estado do tempo de preparação da máquina — é durante o Setup que
a primeira peça é fabricada — e continua sendo a fonte única de
`setup_registrado_em`. O popup não repete essa confirmação; ele recusa a
liberação enquanto o Setup não tiver sido apontado, para não existirem duas
fontes de verdade sobre o mesmo fato.

**Refugo passou a exigir o crachá do responsável, como o retrabalho.** É o mesmo
cadastro (`autorizador_retrabalho`), a mesma validação e a mesma auditoria: nada
de segundo sistema de autorização, perfil ou login. A auditoria distingue
`RETRABALHO_PRIMEIRA_PECA` (bloqueia a OP, liberada pelo crachá),
`REFUGO_PRIMEIRA_PECA` (autorizado antes do descarte, sem bloquear) e
`REFUGO_APONTAMENTO` (refugo informado na finalização). Toda tentativa recusada
também é gravada. A regra de quantidade não mudou: refugo consome o planejado e
não vira peça boa.

**O histórico do portão passou a viver na gestão.** `Análises → Qualidade` lê o
endpoint que já existia (`GET /management/first-pieces`) e mostra a primeira
peça de cada operação — Setup apontado, resultado, cotas medidas, quem
inspecionou — além das autorizações por crachá. Nenhuma persistência nova.

**Scripts de simulação desatualizados excluídos.** `scripts/simulacao_fabrica/`,
`tests/etapa4b_factory_shift/`, `tests/test_simulacao_fabrica.py` e os quatro
executores que só existiam para dirigi-los (`simular_fabrica.py`,
`smoke_wave5_1.py`, `coletar_evidencias_wave5.py` e
`provisionar_simulacao_wave5.py`) foram removidos: eles apontavam Início antes
do portão e serão refeitos em wave futura. Nenhum teste fora desses diretórios
dependia deles. O provisionamento dos usuários sintéticos saiu junto — eles
continuam existindo no banco de teste, mas a recriação virá com a nova
simulação.

**Ninguém contorna a conferência.** `OperatorFlowService` recusa a
**finalização** nesses setores enquanto a primeira peça não estiver aprovada,
com o código `primeira_peca_gate_obrigatorio`, cuja mensagem orienta a apontar
o Setup. Produzir continua livre — o único bloqueio de produção é o do
retrabalho da primeira peça (Wave 5), liberado por crachá. Fechar ou cancelar o
popup não envia ação alguma e nunca aprova a peça.

**O checklist abre pelo botão Setup.** Ele continua sendo o apontamento do
tempo de preparação da máquina; quando a primeira peça ainda não foi aprovada,
o mesmo clique abre o popup. Aprovada a peça, o posto dispara o `Retornar`
canônico e a OP volta a produzir sem clique manual — mesma transição de sempre,
nenhum evento de sistema novo. Dali em diante o lote segue o apontamento normal
do setor (um Início, um Finalizar com as quantidades), sem repetir o portão e
sem apontamento peça a peça.

**A conformidade continua sendo a conta da Wave 5.1.** O operador informa só a
medida; `mes/domain/quality_measures.py` decide com `referencia ± margem` em
`Decimal`, com os limites pertencendo à faixa. Essa função de casamento de cotas
passou a ser compartilhada pela inspeção dimensional e pelo portão — uma única
autoridade, em vez de duas cópias. As cotas do popup são o template do produto
que já existia; produto sem cotas abre o editor existente dentro do popup.

Cobertura: `tests/test_wave6b_gate_setup_qualidade.py` (30 testes cobrindo os 24
casos pedidos mais o Setup apontado e as autorizações de refugo) e seis casos
novos de `vitest` no posto. Regressão verde em
operator flow, primeira peça, Wave 5.1, Wave 3, máquina de estados, qualidade,
fila TOTVS, banco/consistência gerencial e API Web, mais `npm test`, `tsc -b` e
`npm run build`. Validação visual no ambiente TEST com Dobra, Usinagem, Serra e
Pintura. Banco REAL intocado; nenhuma migration nova.

**Wave 6C concluída (11/09/2026) — a tela de Corte mostra a hierarquia real.**

A fila do Corte deixou de ser uma lista plana de tarefas e passou a exibir
`TAREFA → PLANO/NESTING → OP → PRODUTO`. A tarefa recolhe/expande (estado local
do React, sem coluna no banco) e, dentro dela, cada plano traz suas OPs com o
produto já projetado localmente, suas chapas físicas e seu estado. Nenhuma ação
nova foi criada: iniciar, parar, retomar e finalizar continuam os mesmos
comandos — a wave é de representação.

**O vínculo plano → OP passou a ser persistido, porque ele é dado, não
apresentação.** `STPIPArc.WONumber` (a OP) vive na linha de peça, que é aninhada
em um `ProgramName` específico. A projeção descartava o programa e tratava as
OPs como se pertencessem à tarefa inteira. A migration 28 acrescenta
`catalogo_sigmanest_ops.programa` (anulável) e a granularidade da linha passou a
ser `(tarefa, programa, OP, peça)`. Nada mudou no gateway SQL Server: a consulta
homologada já trazia `ProgramName` por peça. Linhas antigas, sem programa, só
são atribuídas quando a tarefa tem um único plano; com vários planos ficam
explicitamente em `ops_sem_plano`.

**"Aguardando corte" e "disponível para Destaque" são estados diferentes.** Os
estados do plano são `AGUARDANDO CORTE`, `EM CORTE`, `DISPONÍVEL PARA DESTAQUE`
e `FINALIZADO`. Um plano ainda não cortado jamais aparece como pendência do
Destaque. A regra de liberação não foi reescrita: o Corte lê
`ManufacturingRules.cut_releases_highlight` (só a Laser Ensis libera) e o read
model `listar_fila_destaque` para rotular o plano. O Destaque continua com o
fluxo homologado da Wave 3 — plano cortado libera na hora, tarefa incompleta
bloqueia o destaque da tarefa inteira, idempotência e histórico intactos.

**A quantidade de chapas e a repetição continuam vindo do SigmaNEST.** Cada
linha projetada é uma chapa física (`programa + chapa + RepeatID`); a tela
mostra `chapas_cortadas de chapas_total` e a lista de repetições do plano. Em
nenhum ponto se assume "1 nesting = 1 chapa".

Cobertura: `tests/test_wave6c_hierarquia_corte.py` (24 testes cobrindo os 20
casos pedidos, mais a seleção de plano e as linhas legadas sem programa) e
`web/src/test/cutting-hierarchy.test.tsx` (9 casos de renderização,
expand/collapse, seleção, estados, chapas/repetição, múltiplas tarefas,
loading/vazio/erro e atualização da fila). Regressão verde em Corte, Destaque,
SigmaNEST, operator flow, Waves 6A/6B, banco/consistência gerencial e API Web,
mais `npm test`, `tsc -b` e `npm run build`. Validação visual no ambiente TEST
com tarefa de dois planos, plano com duas OPs e nesting com repetição 1..4.
Banco REAL intocado.

**Decisão de negócio tomada (11/09/2026):** a execução da inspeção dimensional
peça a peça da operação `INSPECAO` (abrir inspeção, RNC e dispensa) fica **fora
do processo do operador por enquanto**, intencionalmente e sem prazo. O
backend, o serviço e os componentes continuam existindo e testados, apenas sem
ponto de entrada na tela do posto; o histórico continua visível na gestão. Não
é pendência esquecida — não recriar essa entrada sem uma decisão nova.

**Wave 6D concluída (11/09/2026) — a Solda ganhou visão gerencial e a TV virou
um ciclo.**

A tela `/welding-management` é **gerencial**, não operacional: PCP, Liderança,
Supervisão e Diretoria acompanham as OPs de conjunto soldado no modelo de
informação da planilha da PCP — ESTAÇÃO, OP, PRODUTO/CONJUNTO, MÁQUINA/MODELO,
DATA e STATUS. Nenhum comando foi criado, nenhum login por estação foi criado e
a estrutura fixa de estações do posto continua sendo a mesma. A entrada fica na
Tela inicial, ao lado do Andon (`/inicio/solda` → `/welding-management`), dentro
da mesma aplicação e da mesma autenticação.

**A linha é `(OP, operação de Solda do roteiro)` e a OP não é duplicada.** A
identidade continua sendo a canônica do catálogo (`codigo_op` = número + item +
sequência). Uma OP com duas soldas no roteiro aparece em duas linhas e continua
sendo uma OP no resumo. As fontes são as que já existiam: `catalogo_pcp_ops`,
`catalogo_operacoes_op` (`tipo_setor='Solda'`),
`catalogo_recursos_pcfactory` e `apontamentos_operacionais`.

**ESTAÇÃO é dado observado, não derivado.** Decisão do usuário: as estações
pegam a OP e executam — não existe mapeamento determinístico máquina → estação
e não deve existir. A estação exibida é a do apontamento real
(`apontamentos_operacionais.maquina`, onde a Solda já grava "Estação 1..10"); a
OP que ainda não passou por posto fica no agrupamento sem estação, com o texto
"Estação ainda não definida.". Nenhuma inferência a partir de produto, modelo,
máquina ou roteiro.

**MODELO vem do cadastro corporativo do produto e ainda não tem carga
automática.** A migration 29 criou `catalogo_pcp_ops.produto_modelo`, anulável,
como lugar definitivo do campo. Nesta wave **nada foi lido, puxado ou escrito no
ERP**: a coluna nasce vazia e a tela escreve "Modelo não identificado." enquanto
não houver valor real. A ingestão automática do campo é **pendência explícita de
etapa futura** e continua fora de escopo até decisão do usuário.

**Os três estados seguem regra, não estimativa.** FINALIZADA exige apontamento
concluído — data planejada e existência da OP não concluem OP. ATRASADA é a OP
criada em uma semana já encerrada que não recebeu apontamento naquela semana, ou
a OP cuja janela de prazo venceu sem conclusão; enquanto a semana de criação
está em curso, a OP não é declarada atrasada. A VENCER é a OP ainda dentro da
janela. **Atraso não bloqueia nada**: iniciar, parar, retomar e finalizar
continuam intactos, provado por teste que executa o fluxo do posto inteiro sobre
uma OP atrasada.

**Descoberta de planejamento registrada:** a ingestão corporativa de
`ProductionOrder` **não alimenta `data_emissao` nem `prazo_entrega`** — ela traz
`data_liberacao`, `inicio_planejado` e `fim_planejado`. Por isso a base temporal
é resolvida por precedência declarada: prazo = `prazo_entrega`, senão
`fim_planejado`; criação = `data_emissao`, senão o instante de geração da ordem
no planejamento. Quando a leitura usa a alternativa, o contrato marca `parcial` e
a tela mostra qual campo foi usado. Sem nenhuma das duas, o estado permanece
indisponível com motivo, em vez de virar "A VENCER" por eliminação.

**A TV virou ciclo, sem tocar no Andon.** `useTvRotation` alterna
`/andon` → `/welding-management` → `/andon`, **10 segundos em cada visão**, em
modo passivo e somente no perfil dedicado de TV; um gestor que abre a mesma rota
continua navegando por conta própria. O Andon homologado permanece integral —
recursos ativos, estados, OEE por recurso, paradas, Destaque, atualização e
layout. A atualização automática é a que já existia (canal em tempo real com
varredura periódica de reserva); nenhum mecanismo concorrente foi criado.

Cobertura: `tests/test_wave6d_solda_gerencial.py` (32 testes) e
`web/src/test/welding-management.test.tsx` (18 casos, incluindo o ciclo da TV
validado por tempo, sem clique), mais um caso novo em `tests/test_web_api.py`.
Regressão verde em Andon, waves 6A/6B/6C, fluxo do operador, máquina de estados,
API Web, migrations e consistência gerencial, além de `npm test` (149),
`tsc -b` e `vite build`. Validação visual na pré-visualização isolada (perfil de
TV e perfil gerencial) com estação de uma OP, estação de três OPs, OP a vencer,
OP atrasada pelos dois critérios, OP finalizada, modelo presente e ausente,
estação ausente e OP sem prazo. Banco REAL intocado; migration 29 aplicada
apenas em `gestor_pecas_test`.

**Wave 6E concluída (11/09/2026) — apresentação: filtros de cadastro e estado
técnico traduzido.**

Wave de apresentação. Nenhuma regra de negócio, contrato de API, cálculo,
calendário (6A), portão Setup/Qualidade (6B), hierarquia do Corte (6C),
autorização por crachá ou integração foi alterada; o backend não recebeu
mudança para trocar texto.

**Pausas e Crachás ganharam filtro e leitura organizada.** A mesma barra
(`web/src/components/RecordToolbar.tsx`) serve as duas telas: Pausas filtra por
setor, tipo (Almoço, Café e demais tipos derivados da descrição já cadastrada) e
busca; Crachás filtra por situação, perfil (responsável por retrabalho x
operador), origem do cadastro e busca. As duas mostram a contagem do recorte e
**Limpar filtros**. O recorte é aplicado sobre a lista já carregada — trocar
filtro não gera consulta nova — e sobrevive à navegação da sessão
(`hooks/usePersistentFilters`). Listar, criar, editar, ativar, desativar,
remover e designar responsável continuam nos mesmos endpoints e no mesmo corpo
de requisição; o formulário passou a abrir em diálogo, em vez de empurrar a
página.

**O estado interno continua no backend; quem traduz é o frontend.**
`web/src/utils/systemState.ts` é a única camada de humanização
(`sem_registros` → "Nenhum registro encontrado para o período.",
`dados_insuficientes` → "Ainda não há dados suficientes para este indicador.",
`nao_configurado` → "Este indicador ainda não foi configurado.", `parcial` →
"Dados parciais disponíveis para o período."), com as grafias equivalentes em
inglês/maiúsculas. `availabilityLabel`, `humanize`, `EmptyState`, `MetricCard`,
`StatusBadge`, Management View, Produção e Relatórios passaram a consumir essa
camada; a tabela duplicada da Visão Geral foi removida. O estado técnico
permanece em `data-availability`, que é gancho de estilo e não texto de tela.

**A IA passou a falar como sistema de gestão.** O mecanismo ficou intacto —
provider, streaming, modelos, tool calling, consultas, `ai_conversations` e
`ai_messages`. Só a apresentação mudou: `web/src/utils/assistantText.ts` traduz
estado citado na resposta, remove anotação interna de origem, nome de
campo/tabela, SQL e rastro de exceção, e dá nome humano à situação e ao tipo do
relatório gerado.

Cobertura: `web/src/test/pauses.test.tsx` (11), `web/src/test/badges.test.tsx`
(10) e `web/src/test/system-state.test.tsx` (14), com a suíte Web em 131 testes
verdes, `tsc -b` e `vite build` limpos, e `tests/test_web_api.py` (44) verde.
Validação visual no ambiente TEST (pré-visualização isolada, sem banco REAL):
Pausas, Crachás, Visão Geral, Análises, Relatórios, Produção, Auditoria e IA sem
identificador técnico no texto, sem rolagem horizontal e com estado vazio
explicado.

**Pendência de negócio (não decidida aqui):** o filtro por **setor** na tela de
Crachás não foi implementado porque `operadores_apontamento` não tem setor. O
crachá hoje é global: dar setor a ele seria criar regra nova (o setor
restringiria a autorização? viria do histórico de apontamento?). Precisa de
decisão da Engenharia de Manufatura antes de virar coluna ou filtro.

**Wave 3 concluída (08/09/2026) — próxima ação: homologação manual operacional.**
O fluxo de apontamento está consolidado conforme o documento oficial, com o
avanço de fila decidido localmente, inspeção pulável e auditável, Destaque por
tarefa/plano, sincronização do Corte observável e Qlik removido. O próximo passo
é a homologação manual pelo usuário sobre `gestor_pecas_test` — **não iniciada** e
fora do escopo automatizado. A promoção do banco REAL continua sem execução.

Frentes que dependem de decisão externa e não bloqueiam código:

0. **Cadastro de recursos** — cinco confirmações listadas em
   `docs/CADASTRO_RECURSOS_E_POSTOS.md`: o par `SFG-330`↔`SERRA3`, o posto de
   `SERRA5`, os postos de `PMCV`/`ROSQU`, a classificação em bloco dos 313
   recursos sem `tipo_setor` e a aposentadoria de `LASER` na origem.

1. **Roteiro x conclusão na origem** — decidir se OP com nesting concluído no
   SigmaNEST e sem apontamento no Gestor precisa de tratamento próprio na
   sequência do roteiro.
2. **Montagem** — a Manufatura precisa classificar os recursos reais com
   `tipo_setor='Montagem'` no cadastro. O setor, as permissões e a regra
   canônica já existem; nenhum recurso será promovido por semelhança de nome.
3. **Ingestão do MODELO da máquina (Wave 6D)** — a coluna
   `catalogo_pcp_ops.produto_modelo` existe desde a migration 29, mas **nenhum
   mecanismo a alimenta**. O campo é um atributo customizado do produto no
   cadastro corporativo e hoje não chega em nenhuma mensagem recebida pelo
   Gestor. Enquanto a carga não for decidida e implementada, a tela gerencial da
   Solda mostra "Modelo não identificado.". Não inferir o modelo a partir de
   máquina, recurso, roteiro ou descrição do produto.
4. **`prazo_entrega` sem origem (Wave 6D)** — a ingestão corporativa de
   `ProductionOrder` não envia `data_emissao` nem `prazo_entrega`. A leitura da
   Solda usa `fim_planejado` como janela de prazo e declara a leitura como
   parcial. Se a PCP precisar de prazo de entrega próprio, é decisão de negócio
   nova: origem do campo e quem o mantém.
