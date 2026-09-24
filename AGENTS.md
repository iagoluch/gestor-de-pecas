# AGENTS.md — Gestor de Peças

## Disciplina de execução do agente

Esta seção define **como trabalhar**, não o que este projeto faz — isso vem
nas seções seguintes. Vale para qualquer agente de codificação que abrir este
repositório (Codex, Claude Code ou outro), sem depender de ferramenta.

**Ordem de leitura no início de uma tarefa:** este arquivo → `ROADMAP.md`
(seção 5, "Próxima ação concreta") → `docs/STATUS_ATUAL.md` (estado real após
a última edição do ROADMAP — leia sempre, o ROADMAP fica defasado com
frequência) → `git log`/`git status` para o que mudou depois disso → só então
os `docs/*.md` específicos do assunto da tarefa. Não é preciso ler os dezenas
de relatórios datados em `docs/` inteiros; eles são evidência histórica,
consulte-os por nome quando a tarefa tocar o assunto deles.

**Fluxo padrão:** entender o objetivo real → localizar a implementação
responsável e seus consumidores → implementar na camada correta → validar de
forma proporcional ao risco → entregar. A implementação deve começar cedo;
não transforme uma tarefa localizada em auditoria do sistema inteiro antes de
tocar em código.

**Profundidade proporcional ao risco:**
- mudança pequena e localizada (texto, UI simples, correção óbvia): localizar
  → alterar → validar diretamente o que mudou;
- feature ou bug de porte médio: inspecionar os arquivos afetados e suas
  dependências diretas → implementar → validar o fluxo afetado;
- causa raiz incerta, múltiplos módulos, concorrência, migração de schema ou
  mudança de arquitetura: investigação mais profunda, mapear
  produtores/consumidores/contratos antes de alterar, validação ampla do
  fluxo.

**Validação:** rode apenas os testes diretamente relacionados à mudança, não
a suíte inteira por padrão (só quando o impacto for transversal, houver
evidência de regressão, ou o usuário pedir explicitamente). Depois de validar
adequadamente, pare — não entre em ciclo de procurar problema hipotético sem
evidência concreta.

**Escopo:** corrija problemas diretamente relacionados à tarefa ou
necessários para que a solução fique correta. Problemas independentes
encontrados no caminho devem ser **reportados**, não necessariamente
corrigidos na mesma tarefa — a menos que o usuário peça um pente-fino
explicitamente.

**Autonomia:** decida sozinho o que for tecnicamente determinável pelo
código, pelos testes, pela arquitetura existente ou pelas regras deste
arquivo e do `ROADMAP.md`. Só pergunte ao usuário quando houver uma decisão
de **negócio** genuína — múltiplas interpretações razoáveis, mudança de regra
industrial, ou algo que nenhum documento do repositório resolve. As
pendências já identificadas e aguardando decisão estão listadas em
`docs/STATUS_ATUAL.md` (seção "Pendências abertas") — não decidir essas por
conta própria, e não redescobri-las do zero.

**Comunicação:** ao terminar, reporte de forma direta — o que mudou, o que
foi validado, e limitações relevantes. Sem narrar cada arquivo investigado
nem justificar passos triviais.

**Manutenção destes documentos:** ao concluir uma tarefa que muda o estado do
projeto (homologação aprovada, contrato descoberto, decisão de negócio
fechada, bug corrigido de forma definitiva), atualize `docs/STATUS_ATUAL.md`
no mesmo trabalho. Quando esse arquivo acumular uma wave inteira fechada,
incorpore o conteúdo relevante ao `ROADMAP.md` (seção 5) e limpe
`STATUS_ATUAL.md` para a próxima janela — não deixe os dois divergirem por
muitos dias, como aconteceu entre 11/09 e 15/09/2026.

## Visão geral do projeto

O Gestor de Peças é um MES industrial **Web-only**. A apresentação oficial é React/TypeScript sobre FastAPI/Python. PostgreSQL permanece como banco da aplicação. O Protheus/TOTVS é a fonte de planejamento corporativo e o Gestor é a fonte de execução real.

O workspace padrão de desenvolvimento/homologação é:

```text
Gestor de Peças - Area de Testes
```

A direção oficial está em `ROADMAP.md`. Relatórios datados são evidência histórica; não devem reabrir decisões superadas nem substituir o roadmap atual.

## Hierarquia normativa — obrigatória

Quando houver conflito, seguir esta ordem:

1. **Regra explicitamente validada com a Engenharia de Manufatura.**
2. Regra funcional canônica já consolidada no Gestor de Peças.
3. Evidência observada no PCFactory/MES/Management View.
4. Inferência técnica.

PCFactory e Management View são fontes de evidência e dados, **não modelos a serem copiados**. Se o sistema atual divergir da Manufatura, manter a regra da Manufatura e registrar a divergência.

Não inventar regra ausente. Dado insuficiente deve permanecer `dados_insuficientes`, `parcial`, `nao_configurado` ou estado equivalente, em vez de virar zero ou uma estimativa silenciosa.

## Disciplina de roadmap e documentação

Antes de iniciar uma etapa nova, ler `ROADMAP.md` e confirmar o gate da etapa anterior. Não pular diretamente para outbound, dashboards ou produção se o roadmap ainda exigir semântica de roteiro, fluxo do operador ou homologação dos eventos reais.

Quando uma tarefa mudar o estado do projeto (homologação aprovada, contrato descoberto, banco/ambiente alterado, etapa concluída), atualizar no mesmo trabalho, quando aplicável:

- `ROADMAP.md`;
- documento técnico específico da área;
- `README.md` se afetar setup/arquitetura/estado geral;
- este `AGENTS.md` somente quando mudar regra permanente para agentes.

Não transformar logs, prompts ou relatórios históricos em fonte de verdade atual.

## Regras industriais canônicas

- `Quantidade Produzida` significa **somente peças boas**. Refugo e retrabalho são grandezas separadas.
- Refugo não completa a quantidade planejada da OP.
- Setup é classificado como produtivo e **não deve reduzir Disponibilidade nem Performance**.
- Atividade sem OP é classificada como produtiva.
- Parada lançada manualmente pelo operador é não programada.
- Interrupção automática do sistema é programada.
- Limites oficiais automáticos de turno: **17:30 e 21:30**.
- No fim de turno: gerar interrupção programada automática, quantidade zero, manter a OP aberta e exigir retomada manual depois. Não finalizar OP automaticamente.

### Calendário operacional (Wave 6A)

- Turno normal: **08:00–17:30**. Fora de turno: **17:30–08:00**.
- **Hora extra planejada** é uma janela pontual fora do turno normal (ex.: 17:30–21:30, 06:00–08:00), cadastrada como exceção `disponivel_extra` em `excecoes_calendario_produtivo`. Não é um segundo turno fixo e não tem tela própria. Quando planejada, o período integra a janela operacional planejada; quando não, o período continua fora de turno.
- **O relógio, sozinho, nunca bloqueia apontamento.** 18:00, 21:30, 01:00, 06:00 e 07:30 são horários operacionalmente válidos. Não implementar `if agora > 17:30: bloqueia`. Fora de turno muda a contabilidade de disponibilidade, não a permissão de apontar.
- Pausa automática cadastrada em `pausas_automaticas_setor` termina e retoma
  automaticamente no `hora_fim` configurado. Na abertura do turno oficial às
  **08:00**, o estado `fora_turno` termina em **Recurso sem demanda**, sem
  presumir OP, produção ou estado físico; uma OP interrompida continua exigindo
  retomada manual.
- Fora de turno **não** compõe disponibilidade e **não** é parada da máquina.
- Todo recurso habilitado no catálogo, atual ou futuro, possui linha do tempo
  contínua pelo scheduler. Dentro da janela operacional, sem programação de
  produção, o estado é **Recurso sem demanda**; recurso habilitado não pode
  ficar ausente/ocioso sem tempo. Esse estado entra no OEE como recurso
  disponível sem produção: 100% de Disponibilidade e 0% de Performance/OEE
  quando ocupar sozinho o período; sem peça, o FTT continua sem dado.
- Ao fim de almoço, café ou outra pausa automática, restaurar integralmente o
  estado imediatamente anterior: mesma OP em Produção, mesma Parada/motivo ou
  Recurso sem demanda. Não escolher categoria por inferência nem criar OP.
- Fora de turno é grandeza **global** de calendário: o mesmo intervalo noturno observado em vários setores/recursos não é somado na agregação global (a métrica por recurso/setor permanece).
- Classificação central de parada em `ManufacturingRules.classify_stop`: **PLANEJADA** (grupo `0002 — PARADA PROGRAMADA` do catálogo PCFactory: intervalo, café, reunião, limpeza, manutenção preventiva, fora de turno sem hora extra) ou **NÃO_PLANEJADA** (todo o resto). A cor deriva da classificação (`planejada` → amarela, `nao_planejada` → vermelha); nenhum componente visual decide cor por grupo de catálogo ou por texto do motivo.
- "Sem apontamento" e "Recurso s/op" são **sempre** NÃO_PLANEJADA, mesmo que o cadastro diga o contrário.
- **Parada planejada não afeta OEE**; parada não planejada afeta. A correção é feita na entrada temporal (`mes.analytics.oee.oee_seconds_by_category` remove a parada planejada do tempo disponível), nunca no resultado final nem com uma fórmula paralela.
- Recurso ocioso dentro do turno, sem estado físico, **não** é inconsistência de dado: é a condição "Sem apontamento". A lacuna de calendário permanece como diagnóstico interno (`auditoria.diagnostics.calendar_gaps`) e não aparece na lista de alertas.
- OP/operação concluída pela quantidade boa não deve ser reaberta pelo fluxo normal.
- Múltiplas OPs simultâneas podem ser legítimas. O tempo físico da máquina nunca pode ser multiplicado.
- Tempo físico do recurso e tempo atribuído às OPs por rateio são grandezas distintas.
- Se estados simultâneos do mesmo recurso forem incompatíveis, registrar/auditar `desconhecido`; não escolher um vencedor por inferência.
- Cada nesting de Corte deve preservar e expor seu próprio tempo previsto e realizado.

## Fontes canônicas do backend

A UI não deve montar uma verdade paralela. Para novas implementações, usar preferencialmente:

- estado físico do recurso: `eventos_estado_recurso`;
- quantidade boa/refugo/retrabalho: `eventos_quantidade_producao`;
- execução de OP: `apontamentos_operacionais` + `eventos_apontamento_operador`;
- tempo físico/rateado: `sessoes_recurso` + `rateios_tempo_op`;
- calendário: `calendarios_produtivos`, `turnos_produtivos`, `intervalos_turno_produtivo`, `excecoes_calendario_produtivo`;
- Corte/Nesting: `apontamentos_corte`;
- rastreabilidade: fontes anteriores + participações de operador + referências de origem.

Fallback histórico pode existir para dados anteriores à fonte canônica, mas deve ser marcado explicitamente e não pode sobrescrever evidência física melhor.

## Separação backend / frontend

Código novo em `mes/domain`, `mes/analytics`, `mes/services`, `mes/repositories` e `mes/contracts` não deve depender de FastAPI, React ou componentes visuais.

O frontend Web deve:

- consumir contratos/casos de uso do backend;
- não consultar tabelas diretamente;
- não recalcular OEE, tempos, produção, rateio ou confiabilidade;
- não inferir valor faltante;
- apresentar `availability/reason/source` quando o backend expuser incerteza;
- manter a mesma verdade em todas as telas e exportações.

### Acompanhamento gerencial da Solda (Wave 6D)

- A tela de Solda (`/welding-management`) é **gerencial**, para PCP, Liderança,
  Supervisão e Diretoria. Não é posto: não tem comando, não tem seletor de
  estação e não cria login por estação. A estrutura fixa de estações já
  existente (`app/core/operator_sectors.WELDING_STATIONS`) continua sendo a do
  posto.
- A linha é `(OP, operação de Solda do roteiro)` e a OP mantém a identidade
  canônica do catálogo (`codigo_op` = número + item + sequência). Não criar
  identificador novo nem duplicar OP quando o roteiro tiver mais de uma solda.
- **MODELO** é atributo do produto no cadastro corporativo e vive em
  `catalogo_pcp_ops.produto_modelo` (migration 29). **A ingestão automática
  desse campo ainda não existe** e é pendência explícita de etapa futura: até
  lá a coluna fica nula e a tela escreve "Modelo não identificado.". Não
  derivar modelo de máquina, recurso, roteiro ou descrição do produto.
- **ESTAÇÃO é dado operacional observado**, lido de
  `apontamentos_operacionais.maquina`. Decisão do usuário (11/09/2026): as
  estações pegam a OP e executam; **não existe mapeamento determinístico
  máquina → estação e não deve ser criado**. OP sem execução fica no
  agrupamento sem estação e a tela escreve "Estação ainda não definida.".
- Estados: **A VENCER** (dentro da janela de prazo), **ATRASADA** (OP criada em
  semana já encerrada sem apontamento naquela semana, ou janela de prazo
  vencida sem conclusão) e **FINALIZADA** (somente com apontamento concluído —
  data planejada e existência de OP não concluem OP). Sem base temporal, o
  estado permanece indisponível com motivo; não vira "A VENCER" por eliminação.
- **Atraso é acompanhamento e nunca bloqueia** iniciar, parar, retomar ou
  finalizar. A leitura gerencial não participa de nenhuma decisão de execução.
- A TV alterna sozinha `/andon` → `/welding-management` → `/andon`, **10
  segundos em cada visão**, em modo passivo e só no perfil dedicado de TV
  (`useTvRotation`). O Andon permanece intacto; a wave apenas o incluiu no
  ciclo.

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

## Arquitetura e integração corporativa

O planejamento pertence ao **Protheus/TOTVS**. O Gestor registra **execução real**, mantém PostgreSQL próprio e compara Plano × Real. Não existe decisão de substituir o PostgreSQL por escrita/leitura direta no banco do ERP.

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

**Wave 6B (11/09/2026) — o portão Setup/Qualidade da primeira peça.**
Em Dobra, Usinagem e Serra o fluxo do operador é
`Selecionar OP → Iniciar (livre) → produz a primeira peça → Finalizar é
recusado e manda apontar o Setup → botão Setup abre o popup com o checklist →
medidas conferidas → primeira peça aprovada → lote liberado e a OP volta
sozinha para a produção → o operador produz o resto do lote e finaliza`.
**Iniciar nunca é bloqueado pelo portão** e o popup **não** abre no Finalizar:
quem o abre é o botão Setup. O card separado de "Primeira
peça" e a aba "Qualidade" do posto **saíram da tela**. O botão **Setup
permanece**: ele é o apontamento de estado do tempo de preparação da máquina —
é durante o Setup que a primeira peça é fabricada — e continua sendo a **fonte
única** de `setup_registrado_em`. O popup não repete essa confirmação: ele
recusa a liberação enquanto o Setup não tiver sido apontado. Nada disso apagou
regra: o motor continua sendo `FirstPieceService`/`QualityInspectionService`, os
estados persistidos são os mesmos da Wave 5 e a conformidade continua sendo a
conta da Wave 5.1 (`referencia ± margem`, `Decimal`, limite dentro da faixa).

O que a Wave 6B acrescentou:

- `OperatorFlowService` recusa a **finalização** enquanto a primeira peça não
  estiver aprovada nesses três setores, com o código
  `primeira_peca_gate_obrigatorio`, cuja mensagem manda apontar o Setup. É essa
  recusa — e não a tela — que impede fechar a operação sem conferir a peça.
  Produzir não é bloqueado: o único bloqueio que ainda impede voltar a produzir
  é o do retrabalho da primeira peça (Wave 5), que espera o crachá.
- **O botão Setup é o ponto de entrada do checklist.** Quando a primeira peça
  ainda não foi aprovada, o clique no Setup aponta o estado (tempo de
  preparação da máquina, como sempre) e abre o popup em seguida. Aprovada a
  peça, o posto dispara o `Retornar` canônico e a OP volta a produzir sem o
  operador clicar em Iniciar de novo — é a mesma transição do posto, não um
  evento de sistema novo.
- **O portão é da primeira peça, não do lote.** Depois da aprovação, o restante
  da produção segue o apontamento normal do setor (um Início, um Finalizar com
  as quantidades); nada de apontamento peça a peça.
- `FirstPieceService.registrar_checklist` é a submissão única do popup: ela
  compõe os passos que já existiam (abrir a primeira peça, anotar o Setup
  confirmado, declarar a peça produzida e inspecioná-la). Reenvio do mesmo
  formulário devolve `primeira_peca_ja_aprovada` sem inspecionar de novo.
- O escopo é derivado, não é lista nova: `first_piece_gate_is_structured` usa
  `sector_has_quality` de `app/core/quality.py`. **Não acrescentar checklist a
  Solda, Pintura, Corte ou Montagem.**
- O checklist do popup é o **mesmo template de cotas do produto**
  (`qualidade_templates`), publicado em `GET /operator/first-piece`; o cadastro,
  quando o produto ainda não tem cotas, usa o editor que já existia
  (`POST /quality/templates`). Não criar um segundo cadastro de cotas.
- A tela nunca decide o portão: ela lê `primeira_peca.gate_estruturado` e
  `exige_gate_primeira_peca`, ambos calculados no backend.

**Refugo é decisão de responsável, igual ao retrabalho.** Desde o ajuste da Wave
6B, descartar peça exige o crachá de um responsável designado
(`autorizador_retrabalho`) — o mesmo cadastro, a mesma validação e a mesma
auditoria (`qualidade_primeira_peca_autorizacoes`) do retrabalho da primeira
peça. **Não criar um segundo sistema de autorização, perfil ou login.** São três
ocorrências distintas na auditoria: `RETRABALHO_PRIMEIRA_PECA` (bloqueia a OP e é
liberada pelo crachá), `REFUGO_PRIMEIRA_PECA` (autorizado **antes** do descarte;
não bloqueia a OP) e `REFUGO_APONTAMENTO` (refugo informado na finalização, em
`OperatorFlowService`). Na finalização, um crachá de responsável já informado
entre os operadores vale como autorização; toda tentativa — inclusive a recusada
— é gravada. Refugo continua consumindo o planejado sem virar peça boa.

**A inspeção dimensional peça a peça (`INSPECAO`) está fora do processo do
operador por decisão de negócio (11/09/2026)** — não é pendência esquecida. O
backend, o serviço e os componentes continuam existindo e testados, sem ponto
de entrada na tela do posto. Não recriar essa entrada sem decisão nova.

**O histórico do portão vive na gestão, não no posto.** A tela
`Análises → Qualidade` lê `GET /management/first-pieces` e mostra a primeira
peça de cada operação (Setup apontado, resultado, cotas medidas, quem
inspecionou) e as autorizações por crachá. Nenhuma persistência nova: é a
projeção dos mesmos registros que o posto grava.

A **Qualidade (Etapa 7C, 03/09/2026)** é uma capacidade de setor dentro da
experiência normal do operador, nunca um perfil, login ou aplicação. A lista de
setores habilitados vive só em `app/core/quality.py`; hoje são Dobra, Usinagem e
Serra, e Corte está explicitamente fora. A operação `INSPECAO/CALDER/INSPEC` é
projetada em `catalogo_operacoes_op` com `inspecao_qualidade = TRUE`,
`ativo = FALSE` e `tipo_setor = NULL` — como o marco terminal. O roteiro
completo pode exibi-la como contexto, mas nunca a torna apontável pelo posto;
o read model do marco terminal segue restrito às operações ativas. A tela da
Qualidade trabalha **somente com a fila local** e não pode acionar
`ProductionOrderOnDemandSyncService` nem `GPOPSYNC`: quando o fluxo chega na
inspeção a OP já existe aqui. O movimento empresarial vem do fluxo canônico
(`OperatorFlowService` → evento → outbox → `ProductionAppointment`); preencher
cota, marcar não conforme ou abrir RNC **não** gera outbound. Não criar segundo
domínio de RNC nem `QualityOutboundService`.

Desde a Wave 1 (04/09/2026), a unidade de cota apresentada ao operador é fixa
em `mm`. Resultado `RETRABALHO` retorna a peça para a operação produtiva
anterior aplicável no roteiro, preservando o vínculo com a inspeção e usando o
mesmo `OperatorFlowService`; não criar fila genérica ou produção nova. A
conclusão canônica de Corte é provada pelo fim do Destaque e por todos os
nestings ativos finalizados, não por um apontamento operacional fictício.

**Nunca escrever diretamente em tabelas TOTVS** para integrar execução. O retorno deve usar mecanismo suportado e uma camada de outbox/retry/reconciliação depois de o contrato ser comprovado.

O Quick Tunnel usado em homologação é temporário e não pode virar endpoint de produção.

**Qlik está removido (Wave 3, 08/09/2026).** Deixou de ser dívida congelada: a
pasta `qlik/` saiu da raiz do repositório e a coluna herdada virou
`maquina_sigmanest` pela migration 23. As únicas sobrevidas legítimas são o SQL
histórico das migrations 2 e 3 (que não pode ser reescrito sem quebrar a
reconstrução do schema do zero) e artefatos de evidência já gravados. Um teste
de guarda (`tests/test_totvs_operator_queue.py`) reprova qualquer reaparição em
`app/`, `backend/`, `mes/`, `scripts/` e `tools/`. Não recriar Qlik sob outro
nome nem introduzir exportação intermediária desses produtos.

Desde a Wave 2 (04/09/2026), o roteiro do operador é selecionado pelos **cards
das etapas**; não existe mais dropdown de operação. A elegibilidade do posto
(`station_eligible` = setor + recurso compatíveis) é bloqueio duro e nenhuma
confirmação a dispensa — `Dobra - Gasparini` não aponta `CORTE`. Etapa concluída
permanece fechada. Etapa fora da atual, porém do próprio posto, é `selectable` e
`requires_confirmation`: ela reutiliza a regra de exceção que já existia
(`confirmacao_etapa_anterior_obrigatoria` / `confirmacao_recurso_obrigatoria`,
com crachá autorizado). Não criar um bypass genérico do state machine nem uma
segunda semântica de confirmação.

A fonte oficial do planejamento específico de Corte é o **banco do SigmaNEST**. A OP é **do produto**: tarefa, plano e nesting são agrupamentos que contêm produtos e não possuem OP própria, e um mesmo agrupamento pode conter produtos de OPs diferentes. Nunca modelar `tarefa.codigo_op`, `plano.codigo_op` ou `nesting.codigo_op` como relação 1:1, nem criar OP a partir do SigmaNEST. A correlação foi comprovada em 27/08/2026 com dados reais: `TOTVS ProductionOrder.Number` é textualmente igual a `SigmaNEST Wo.WONumber`, e a OP aparece na linha de peça (`STPIPArc.WONumber` / `Part.WONumber`). O código de produto **não** é chave: em 15% dos casos ele diverge entre Protheus e SigmaNEST. Todo SQL do SigmaNEST vive exclusivamente em `backend/integrations/sigmanest_sqlserver.py`, com acesso somente leitura; o restante do Gestor consome apenas os DTOs de `mes/integrations/sigmanest`. Ver `docs/INTEGRACAO_CORTE_SIGMANEST.md`.

Desde a Wave 2, a materialização do planejamento de Corte é **automática**: o
processo Web executa em ciclo o mesmo `SigmaNestSyncService` do script manual
(`_sigmanest_sync_loop` em `backend/api/main.py`), somente leitura na origem,
incremental e idempotente, publicando invalidação SSE apenas quando a projeção
muda. **Não criar um segundo pipeline SigmaNEST.** A pesquisa da fila de Corte é
filtro do que já está disponível, nunca o mecanismo que descobre ou importa a
tarefa.

**Wave 3 (08/09/2026) — quem manda no avanço operacional.** O avanço de etapa é
decidido pelo **estado local do Gestor**, nunca por consulta ao TOTVS. O TOTVS é
fonte de OP, roteiro, produto, quantidade e datas; o SigmaNEST é fonte do
planejamento de Corte; o Gestor é a autoridade de execução. Não existe pull do
Protheus para descobrir a etapa corrente (provado na Etapa 6.1 e não reaberto).
Marco terminal e `IMPRESSAO OP` continuam satisfeitos automaticamente
(`AUTOMATIC_SATISFIED`), sem apontamento fictício.

**Inspeção — regra transitória em vigor.** Enquanto os operadores de máquina são
treinados, a inspeção **pode ser pulada**, mas não pode ser desligada. Pular é um
registro auditável e não falsifica qualidade: `POST /quality/inspections/bypass`
grava status `DISPENSADA` com crachá autorizado e motivo, sem `apontamento_id`,
sem `template_id`, sem peça aprovada, sem cota medida e sem RNC. A restrição
`ck_qualidade_inspecao_dispensa` (migration 23) impede que uma dispensa finja ter
sido uma inspeção. Solda e Pintura não têm checklist dimensional: elas apontam a
inspeção apenas para contabilizar o tempo, usando o recurso efetivo do próprio
posto, e nunca ficam bloqueadas por ela.

**No on-demand TOTVS, "cabeçalho sem roteiro" não é resposta terminal enquanto há
sincronização em curso** (08/09/2026). A ingestão grava o cabeçalho da OP antes
das operações do roteiro; durante essa janela o chamador precisa virar seguidor e
esperar dentro do próprio `timeout_seconds`, nunca devolver `sem_roteiro`. O
sinal é `totvs_op_sync_requests.status = PENDING`. Não transformar essa espera em
laço ilimitado nem em segunda chamada ao ERP.

**A fila da Qualidade é recortada pelo setor de origem da peça** (08/09/2026). A
operação de inspeção entra do TOTVS sem `tipo_setor` próprio; o dono dela é a
**última etapa apontável antes dela no roteiro** — quem produziu a peça. A origem
é derivada em SQL a partir do catálogo de operações, sem alteração de schema e
sem migration. O recorte vale na fila, no resumo, no histórico, na abertura
(`qualidade_op_outro_setor`) e na dispensa. Origem não resolvível permanece
visível em todos os setores: sumir da fila seria pior e silencioso.

**Pausas automáticas são configuração, não código.** Os horários vivem em
`pausas_automaticas_setor` (migration 23), são editáveis por setor na tela
gerencial `/inicio/pausas` e alimentam `mes/services/shift_boundary.py`. A lista
fixa em `ManufacturingRules.automatic_breaks` permanece só como fallback quando
não há configuração. Não voltar a fixar horário de pausa em código.

**A hierarquia do Corte é TAREFA → PLANO/NESTING → OP → PRODUTO.** São quatro
coisas diferentes e nenhuma representa a outra: a **tarefa** é o agrupador do
SigmaNEST (`ProgArchive.TaskName`); o **plano/nesting** é a unidade de corte
(`ProgramName`, materializada em chapas físicas por `SheetName + RepeatID`); a
**OP** pertence à peça (`STPIPArc.WONumber`) e por isso ao programa em que ela
foi aninhada — `catalogo_sigmanest_ops.programa` (migration 28) guarda esse
vínculo, e a granularidade da linha é `(tarefa, programa, OP, peça)`; o
**produto** é o item da OP, lido do catálogo canônico por LEFT JOIN. Não criar
OP artificial para representar plano nem nesting artificial para representar OP.
A fila de Corte publica essa hierarquia pronta em `CutService._group_rows`
(`planos[].ops[]`), resolvida no read model — sem estado persistido novo por
causa da apresentação e sem N+1. Linhas projetadas antes da migration 28 não têm
programa: elas só são atribuídas quando a tarefa tem um único plano; com vários
planos ficam em `ops_sem_plano`, nunca adivinhadas.

**"Aguardando corte" não é "disponível para Destaque".** Os estados do plano na
tela de Corte são `AGUARDANDO CORTE`, `EM CORTE`, `DISPONÍVEL PARA DESTAQUE` e
`FINALIZADO` (constantes em `mes/services/cut.py`). Um plano ainda não cortado é
trabalho pendente do **Corte** e nunca aparece como pendência do Destaque. A
disponibilidade para o Destaque continua sendo decidida exclusivamente pela
regra já homologada — `ManufacturingRules.cut_releases_highlight` (só a Laser
Ensis libera; Plasma não) somada ao read model `listar_fila_destaque`. O Corte
apenas lê esse estado para rotular o plano; não existe segunda regra.

**Destaque trabalha por tarefa e por plano.** Não existe fila tradicional no
Destaque: a tela lista as tarefas liberadas pelo Corte e, dentro delas, os planos.
Um plano cortado pode ser destacado imediatamente, sem esperar a tarefa inteira;
a tarefa fecha sozinha quando o último plano disponível é destacado. O plano
nunca aparece solto — a tarefa pai encabeça cada bloco — e a situação é
`PARCIAL` ou `COMPLETA`. A contagem de chapas vem do SigmaNEST: cada
`RepeatID` do mesmo programa é uma chapa física distinta, e **nunca** se assume
"1 nesting = 1 chapa" (`plano_hash = sha256(tarefa|programa|chapa|repeat_id)`).

**Sincronização do Corte é observável.** O ciclo automático e o botão
"Atualizar tarefas" passam pelo mesmo `SigmaNestRefreshCoordinator`
(`mes/services/sigmanest_refresh.py`), serializado por um `asyncio.Lock`: um
clique durante um ciclo em andamento adere a ele em vez de abrir um segundo. A
tela mostra a última sincronização e, quando a origem falha, preserva a fila
local com mensagem de operador — sem vazar traceback, ODBC ou SQL. A marca
d'água é `MAX(catalogo_sigmanest_planos_corte.data_programa)` recuada por
`DEFAULT_OVERLAP_DAYS = 7`; a releitura sobreposta é segura porque a projeção é
idempotente.

Falha de equipamento (MTBF/MTTR) é decidida pelo **grupo de manutenção corretiva
do catálogo de motivos** (`EQUIPMENT_FAILURE_STOP_GROUP` em
`mes/domain/manufacturing_rules.py`, hoje `0003`), nunca por texto de motivo.
Manutenção preventiva, espera, falta de material e setup não são falha, e parada
marcada como programada também não. Capacidade é publicada como **utilização
temporal** sobre o calendário produtivo cadastrado; capacidade em peças exige
tempo padrão/ciclo ideal confiável por operação e não deve ser estimada.

As telas gerenciais não devem exibir cards cuja informação principal seja
arquitetura, fonte, fallback, fórmula interna ou nome de tabela. Isso pertence à
documentação, a tooltip realmente necessário ou ao log.

**A lógica de apontamento do Gestor é canônica.** A integração TOTVS fornece planejamento ao domínio existente e não cria uma segunda lógica operacional. Depois da projeção para as estruturas canônicas, a origem da OP deve deixar de ser relevante: não criar branch por origem, tabela paralela de OP, evento especial nem coluna corporativa nas tabelas de execução.

## Segurança e consistência transacional

- operações produtivas relacionadas devem ser atômicas;
- proteger concorrência por recurso/OP quando necessário;
- não permitir duas sessões físicas sobrepostas do mesmo recurso;
- rateio deve conservar o tempo físico;
- migrations devem possuir espera limitada para locks;
- retries devem possuir limite;
- nunca limpar banco operacional em testes;
- testes PostgreSQL devem usar `TEST_DATABASE_URL` isolada; no workspace atual o banco TESTE oficial é `gestor_pecas_test`;
- eventos técnicos não devem poluir histórico produtivo;
- não reescrever evento histórico para esconder inconsistência.

## Estrutura principal

```text
web/                  frontend React/TypeScript
backend/api/          FastAPI, autenticação, HTTP/SSE e composição
backend/integrations/ adaptadores de transporte externo, incluindo SOAP TOTVS
app/database/         PostgreSQL, migrations e repositories concretos
mes/domain/           regras industriais
mes/analytics/        cálculos e consolidações
mes/contracts/        contratos neutros
mes/repositories/     abstrações de persistência
mes/services/         casos de uso
mes/integrations/     contratos/mapeadores de integração
qlik/                 integração legada
tests/                testes
docs/                 documentação
assets/               identidade visual e referências
```

Dependência esperada:

```text
UI/Web → contracts/services → domain/analytics → repository abstractions → infraestrutura
```

Nunca inverter essa direção fazendo domínio/analytics importar React, FastAPI ou detalhes de HTTP.

## Regras de codificação e arquivos

- Todos os arquivos de texto novos/alterados devem ser UTF-8.
- Preservar corretamente acentos: `Peças`, `Produção`, `Operação`, `Máquina`, `Interrupção`, etc.
- Não aceitar nomes ou conteúdos com mojibake, escapes Unicode indevidos ou caracteres de substituição.
- Antes de empacotar, varrer nomes e conteúdo por corrupção de Unicode.
- Não incluir `.env`, credenciais Qlik, tokens, perfis de navegador, caches, `.venv`, `__pycache__` ou `.pyc` em artefatos entregues.

## Mudanças e estabilização

- não alterar regra produtiva sem autorização;
- não transformar inferência do PCFactory em regra oficial;
- não esconder erro real alterando teste;
- não duplicar cálculo em serviço e UI;
- manter compatibilidade pública quando possível;
- mudanças de schema devem ser versionadas e seguras;
- quando uma definição oficial estiver pendente — como FTT final com refugo/retrabalho ou estratégia de rateio por cenário — preparar a arquitetura e marcar como pendente, sem escolher por conta própria.

## Contrato definitivo de design e fidelidade visual

Esta seção é normativa. Para qualquer tarefa que toque interface, layout, ícones, fontes, cores, gráficos, tabelas, responsividade ou composição visual, estas regras têm o mesmo peso das regras de negócio do sistema.

O objetivo não é criar uma interface "parecida". O objetivo é preservar e reproduzir o design aprovado do Gestor de Peças com fidelidade mensurável.

### Hierarquia de fonte de verdade visual

Quando houver dúvida ou conflito, usar esta ordem de precedência:

1. pedido visual explícito do usuário na tarefa atual;
2. `assets/screens/screens - atuais/*.png` — referência visual oficial vigente;
3. `web/src/styles/tokens.css` — tokens e métricas oficiais vigentes;
4. `web/src/styles/global.css` — composição, responsividade e estados visuais;
5. `web/src/components/` e `web/src/pages/` — comportamento dos componentes compartilhados;
6. `web/src/test/` — contratos automatizados de interface e comportamento;
7. `assets/screens/screens - legacy/*.png` — somente referência histórica, nunca autoridade quando divergir das telas atuais.

Não usar `legacy` para desfazer uma decisão presente nas telas atuais.

Se um pedido explícito aprovar uma mudança visual nova, atualizar de forma coerente os tokens, componentes, testes e referências visuais afetadas. Não deixar o sistema com duas definições contraditórias do mesmo padrão.

### Catálogo visual oficial

O catálogo atual contém 24 telas oficiais em:

```text
assets/screens/screens - atuais/
```

As 24 imagens têm viewport capturado de `1920 x 1061`.

A implementação Web usa como base lógica:

```text
MOCKUP_BASE_WIDTH  = 1920
MOCKUP_BASE_HEIGHT = 1080
```

Essa diferença é intencional: os PNGs representam a área útil capturada da aplicação, enquanto o layout responsivo é calculado sobre a referência lógica de 1920 x 1080.

Portanto:

- não alterar `MOCKUP_BASE_WIDTH` ou `MOCKUP_BASE_HEIGHT` para 1920 x 1061 apenas para coincidir com o PNG;
- ao medir screenshots, considerar o fator de escala do layout;
- no PNG atual de 1920 x 1061, por exemplo, a sidebar aparece com cerca de 321 px e o header com cerca de 107 px porque `1061 / 1080 ~= 0,9824`;
- na referência lógica de 1920 x 1080, as dimensões estruturais oficiais continuam sendo 327 px para a sidebar e 109 px para o header.

### Princípio visual

A identidade do Gestor de Peças é uma interface industrial limpa, funcional e de alta legibilidade, com:

- navegação lateral azul-marinho escura;
- header branco;
- área de conteúdo cinza muito clara;
- cards brancos com borda fria discreta;
- azul vivo como cor primária de ação e seleção;
- cores semânticas para sucesso, alerta e erro;
- tipografia Arial;
- ícones oficiais simples e nítidos;
- cantos levemente arredondados;
- ausência de efeitos decorativos desnecessários.

Não converter o projeto para outra linguagem visual, como Material, Fluent, glassmorphism, neumorphism, neon, gradientes decorativos, sombras fortes ou componentes excessivamente arredondados, salvo pedido explícito do usuário.

### Paleta oficial

As cores devem vir de `UI_COLORS` em `app/core/styles.py`. Não criar uma segunda paleta paralela.

| Token | Cor | Uso principal |
|---|---:|---|
| `bg` | `#F5F7FA` | fundo geral do conteúdo |
| `surface` | `#FFFFFF` | cards, header, campos e superfícies |
| `surface_alt` | `#F1F3F6` | zebra de tabelas e superfícies secundárias |
| `border` | `#C7D3E2` | bordas de cards, tabelas e controles |
| `divider` | `#DDE5EF` | divisórias leves |
| `text` | `#081630` | texto principal |
| `muted` | `#71809D` | texto secundário |
| `primary` | `#0866F5` | ação principal, seleção e foco |
| `primary_hover` | `#075BD8` | hover do primário |
| `primary_soft` | `#E8F2FF` | seleção e estado azul suave |
| `primary_dark` | `#052B55` | azul profundo auxiliar |
| `accent` | `#16A34A` | sucesso |
| `accent_soft` | `#EAF8EF` | sucesso suave |
| `warning` | `#F59E0B` | atenção |
| `warning_soft` | `#FFF6E6` | atenção suave |
| `danger` | `#EF3340` | erro/crítico |
| `danger_soft` | `#FFF0F1` | erro/crítico suave |
| `sidebar` | `#001E3F` | fundo principal da sidebar |
| `sidebar_active` | `#0866F5` | aba ativa |
| `sidebar_button` | `#082C55` | aba inativa |
| `sidebar_button_hover` | `#0C3765` | hover da aba |
| `sidebar_panel` | `#03264B` | cards internos da sidebar |
| `sidebar_border` | `#0A426F` | borda dos cards da sidebar |
| `sidebar_text` | `#FFFFFF` | texto da sidebar |
| `ok` | `#42D85A` | indicador positivo |
| `info` | `#0866F5` | informação |
| `alert` | `#F5B400` | alerta |
| `critical` | `#EF3340` | crítico |
| `orange` | `#FF7100` | categoria auxiliar |
| `purple` | `#7047E8` | categoria auxiliar/relatórios |
| `teal` | `#20A7A1` | categoria auxiliar |

Regras de cor:

- usar o token semântico, não copiar HEX arbitrariamente para novos componentes;
- não alterar a cor de um SVG oficial em disco;
- tint em memória só é permitido quando o componente existente já prevê tint semântico, como em `tinted_official_icon`;
- manter contraste equivalente ao design aprovado;
- não usar preto puro como texto padrão: o texto oficial é `#081630`;
- não trocar o fundo do conteúdo para branco: a separação `bg` versus `surface` faz parte do design.

### Tipografia oficial

Fonte padrão:

```text
Arial
```

A fonte deve vir de `DEFAULT_UI_FONT` / `UI_FONT`. Não misturar famílias tipográficas na interface principal.

Escala tipográfica oficial usada pelo stylesheet:

| Papel | Tamanho | Peso |
|---|---:|---:|
| título da página | 31 px | 700 |
| subtítulo da página | 12 px | normal |
| título de seção | 17 px | 700 |
| KPI normal — título | 13 px | normal |
| KPI normal — valor | 21 px | 700 |
| KPI normal — detalhe | 11 px | normal |
| KPI grande — título | 16 px | 700 |
| KPI grande — valor | 48 px | 700 |
| KPI grande — detalhe | 14 px | normal |
| KPI compacto — título | 14 px | 700 |
| KPI compacto — valor | 34 px | 700 |
| KPI compacto — detalhe | 12 px | normal |
| título de card de seleção | 32 px | 700 |
| texto de status | 14 px | normal |
| navegação | 16 px | normal; 700 quando ativa |
| tabela | 13 px | normal |
| cabeçalho de tabela | 13 px | 700 |

Tamanhos específicos definidos diretamente por componentes existentes devem ser preservados. Exemplos:

- formulário de apontamento: título e máquina em Arial 25 bold;
- label `Código da OP`: Arial 13 bold;
- input principal de OP: Arial 15;
- mensagem de sucesso: Arial 14 bold;
- saudação da sidebar: escala a partir de 16;
- operador da sidebar: escala a partir de 12.

Não "modernizar" a fonte, reduzir títulos ou alterar pesos só por preferência estética.

### Espaçamento e ritmo

Tokens oficiais de espaçamento em `SPACING`:

```text
xs   = 4
sm   = 8
md   = 12
lg   = 16
xl   = 24
page = 27
```

Regras:

- margem padrão da área de conteúdo: 27 px na escala 1.0;
- espaçamento estrutural padrão entre blocos da página: 16 px;
- espaçamento interno de card compartilhado: normalmente 14 x 12 px;
- toolbar compartilhada: 16 x 12 px com gap de 12 px;
- títulos de seção: ícone e texto com gap de 10 px;
- preferir os tokens e helpers existentes a valores novos;
- quando um valor específico já estiver comprovado no mockup ou teste, preservar esse valor;
- não aumentar padding para "dar mais respiro" sem comparar com o mockup.

### Raios, bordas e elevação

Tokens de raio:

```text
control = 5
card    = 10
panel   = 12
pill    = 9
```

Implementação atual relevante:

- cards: borda de 1 px `#C7D3E2`, raio 10 px;
- toolbar: borda de 1 px, raio 9 px;
- card de seleção: borda de 1 px, raio 12 px;
- botão comum: raio 6 px;
- campos: raio 5 px;
- badge de status: raio 8 px no delegate;
- tabelas: sem arredondamento visual no corpo (`border-radius: 0`).

Não adicionar sombra a todos os cards. O design atual depende majoritariamente de fundo + borda + espaçamento, não de elevação pesada.

### Estrutura principal da janela

A janela deve preservar a estrutura:

```text
+----------------------+-----------------------------------------+
|                      | Header branco                            |
| Sidebar escura       +-----------------------------------------+
| fixa à esquerda      |                                         |
|                      | Conteúdo #F5F7FA                        |
|                      | com margem responsiva                    |
|                      |                                         |
+----------------------+-----------------------------------------+
```

Dimensões de referência em escala 1.0:

```text
janela lógica:        1920 x 1080
sidebar:              327 px
header:               109 px
margem da página:      27 px
separação de página:   16 px
mínimo da janela:     1024 x 680
```

Não mover a navegação para o topo, não transformar a sidebar em drawer e não eliminar o header sem pedido explícito.

### Responsividade oficial

O fator de escala estrutural é:

```python
scale = max(0.64, min(1.0, width / 1920, height / 1080))
```

Regras derivadas:

- sidebar: `max(220, round(327 * scale))`;
- header: `max(76, round(109 * scale))`;
- margem de conteúdo: `max(14, round(27 * scale))`;
- usar `_s(valor)` para dimensões estruturais que devem acompanhar a escala;
- usar `_sf(valor)` para fontes escaláveis quando o componente já seguir essa estratégia;
- em sidebar extensa, usar o modo denso já implementado em vez de esconder itens;
- não permitir sobreposição de avatar, navegação, relógio, status e crédito;
- preservar funcionalidade em 1920x1080, 1600x900 e 1366x768;
- 1024x680 é o limite mínimo suportado da janela principal;
- scroll deve ser introduzido somente onde a arquitetura visual da tela realmente exige; não envolver indiscriminadamente toda página em containers roláveis.

Não substituir o sistema responsivo existente por scaling de screenshot, zoom global ou coordenadas absolutas.

### Sidebar

A sidebar é um elemento permanente de identidade e navegação.

Regras de referência em escala 1.0:

- largura: 327 px;
- fundo: `#001E3F`;
- margens do layout: aproximadamente 15 / 19 / 16 / 18 px;
- gap normal entre blocos: 9 px;
- logo oficial recortado: 254 x 52 px;
- avatar: 60 x 60 px;
- card de perfil oficial: 296 x 120 px em 1920x1080;
- botão de navegação: altura de referência 61 px;
- ícone de navegação: caixa de referência 62 x 47 px;
- botão inativo: `#082C55`;
- botão ativo: `#0866F5`, texto bold e faixa esquerda azul-clara;
- hover: `#0C3765`;
- texto da sidebar: branco;
- cards internos: `#03264B` com borda `#0A426F`;
- relógio, status de conexão e crédito do desenvolvedor permanecem visualmente agrupados no rodapé.

Na resolução lógica 1920x1080, os testes Web e a comparação com as capturas oficiais validam também posições-chave da sidebar. Alterações nessas posições só são aceitáveis quando o design for explicitamente revisado.

Não:

- trocar os ícones da navegação por emojis;
- reduzir a sidebar a ícones sem texto;
- mudar o estado ativo para outra cor;
- remover o bloco de identidade/operador por conveniência de layout;
- alterar a proporção do logo.

### Header

O header deve permanecer:

- branco;
- separado do conteúdo por divisor inferior `#DDE5EF` de 1 px;
- altura de referência 109 px;
- com margem interna aproximada de 28 px horizontal e 12 px vertical;
- título principal alinhado à esquerda;
- ações `Ajuda` e `Configurações` alinhadas à direita quando permitidas;
- ícones oficiais de 30 x 30 px nas ações;
- botão de voltar de 48 x 48 px quando aplicável;
- cartão de sincronização de catálogo somente quando a tela pedir esse estado.

A visibilidade de Configurações continua dependente de permissão; não alterar regra de autorização em nome de fidelidade visual.

### Área de conteúdo e cards

O conteúdo usa `#F5F7FA` como base e `#FFFFFF` como superfície.

Cards compartilhados devem reutilizar os componentes em `web/src/components/` ou composição equivalente já existente antes de criar uma implementação nova.

Padrão de card:

- fundo branco;
- borda de 1 px `#C7D3E2`;
- raio 10 px;
- tipografia escura;
- hierarquia clara entre título, valor e detalhe;
- alinhamento coerente dentro da família do componente.

Não criar cards com:

- gradientes;
- sombra intensa;
- contorno neon;
- ícones 3D;
- fundos coloridos arbitrários;
- raio muito maior que o padrão.

### KPIs

Os KPIs devem usar `KpiCard` e seus papéis tipográficos existentes.

Na Tela Inicial, a organização oficial dos KPIs em escala ampla é:

```text
Linha 1: OPs Ativas | Tarefas Abertas | Hoje | Banco de Dados
Linha 2: Dobra | Usinagem | Corte | Serra | Almoxarifado
```

Os ícones de KPI dessa tela usam recorte circular oficial de 48 x 48 px na referência 1920x1080.

Na Visão Geral da Consulta Operacional, o padrão atual é de 10 KPIs compactos organizados em duas linhas de 5 cards.

Ao adicionar KPI novo:

- reutilizar o mesmo componente;
- escolher ícone existente ou criar asset novo no mesmo padrão somente com aprovação;
- manter hierarquia título / valor / detalhe;
- manter altura uniforme dentro da mesma linha;
- não quebrar a grade para destacar um KPI sem referência visual aprovada.

### Cards de seleção

`SelectionCard` é o padrão para telas de escolha de máquina, Consulta Operacional e Relatórios.

Comportamento visual:

- superfície branca;
- borda fria de 1 px;
- raio 12 px;
- hover com borda primária de 2 px e fundo `#FBFDFF`;
- ícone/imagem centralizado;
- título em destaque;
- cursor de clique;
- proporção do asset preservada.

Para seleção de máquinas de Dobra, Usinagem e Serra, a grade oficial segue:

```text
[ máquina 1 ] [ máquina 2 ]
      [ máquina 3 ]
```

Ou seja: duas opções na primeira linha e a terceira centralizada abaixo.

Dimensões de referência usadas pela implementação:

- largura por card: aproximadamente 510–520 px escalados;
- altura por card: aproximadamente 405–415 px escalados;
- gap horizontal e vertical: 36 px escalados;
- container de seleção: até 1120 px de largura.

A tela de seleção de Relatórios usa dois cards grandes lado a lado. Não substituir por lista, combo ou tabs sem pedido explícito.

### Formulários de apontamento

As telas de registro de Dobra, Usinagem e setores que reutilizam esse padrão devem manter o formulário centralizado.

Padrão atual:

- card principal centralizado;
- largura de referência escalada em torno de 930 px, limitada a 1035 px;
- ícone do setor/máquina no topo;
- título do formulário centralizado;
- nome da máquina centralizado;
- label `Código da OP` acima do campo;
- input principal com altura mínima de 50 px;
- mensagem operacional/sucesso centralizada abaixo;
- fila da máquina em card separado, alinhado ao mesmo eixo e à mesma largura máxima.

Não transformar esse formulário em layout de duas colunas sem aprovação visual.

### Botões

Botão comum:

- altura mínima 38 px;
- padding 5 x 16 px;
- fundo branco;
- borda `#C7D3E2`;
- raio 6 px;
- texto bold;
- hover com borda/texto `#0866F5`.

Variantes:

- `primary`: fundo `#0866F5`, texto branco;
- `danger`: fundo `#EF3340`, texto branco;
- `success`: fundo `#16A34A`, texto branco.

Estados disabled devem continuar cinza claro e visualmente inativos.

Não usar cores semânticas de forma invertida: vermelho não é ação primária, verde não é cancelamento e azul não deve significar erro.

### Campos e controles

Padrão de inputs, selects, controles numéricos e áreas de texto:

- altura mínima 36 px;
- padding 5 x 10 px;
- fundo branco;
- texto `#081630`;
- borda `#C9D5E5`;
- raio 5 px;
- foco com borda `#0866F5`;
- seleção de texto com fundo primário.

Não remover o feedback de foco.

### Tabelas

Tabelas operacionais devem reutilizar `DataTable` sempre que possível.

Contrato visual atual:

```text
altura da linha:                 48 px
altura do cabeçalho:            48 px
largura mínima de coluna:       64 px
largura máx. de texto longo:   300 px
largura mínima de status:      190 px
padding de cálculo de célula:   32 px
padding de badge:               48 px
```

Regras:

- fundo branco;
- zebra com `#F1F3F6`;
- grid visível com `#C7D3E2`;
- cabeçalhos centralizados e bold;
- células centralizadas no padrão operacional atual;
- seleção com `#E8F2FF` sem inverter para texto branco;
- sem edição direta;
- seleção por linha;
- texto longo pode usar elide + tooltip;
- colunas de status não devem ser comprimidas abaixo do mínimo semântico;
- quando o conteúdo exceder a viewport, usar scroll horizontal em vez de destruir a legibilidade;
- não usar seletor CSS global de célula que sobrescreva as cores semânticas de linha.

### Estados e badges

Estados semânticos devem manter o padrão atual de fundo suave + texto/borda forte:

| Estado | Fundo | Texto/borda |
|---|---:|---:|
| Despachado / Concluído / Normal / OK / Ativa | `#EAF8EF` | `#11823B` |
| Finalizado | `#FFF6E6` | `#F07A00` |
| Destacando / Destaque / Em processo | `#E8F2FF` | `#0866F5` |
| Aguardando / Pendente | `#F2F4F7` | `#526078` |
| Atenção | `#FFF6E6` | `#D96800` |
| Atrasado / Crítico | `#FFF0F1` | `#E32636` |

O badge deve continuar compacto, arredondado e centralizado. Não representar status apenas por cor quando o texto já faz parte do componente.

O texto do badge e do estado vazio vem da camada de humanização
(`utils/systemState`), nunca do identificador cru do backend.

### Filtros de tela de cadastro (Wave 6E)

Pausas e Crachás usam a mesma barra (`components/RecordToolbar`): seletores +
busca + contagem do recorte + **Limpar filtros**. A regra é combinação simples,
não um filtro por campo. O recorte é aplicado sobre a lista já carregada — mudar
filtro não dispara consulta nova — e a seleção sobrevive à navegação da sessão
(`hooks/usePersistentFilters`). Filtro sem resultado mostra estado vazio
explicado, com a lista completa a um clique de distância.

### Ícones, logos e imagens

Os assets oficiais ficam em:

```text
assets/icons/
assets/branding/
```

Existe catálogo semântico em `assets` dentro de `web/src/config/assets.ts`.

Regras obrigatórias:

- reutilizar o SVG oficial correspondente antes de desenhar um ícone novo;
- preservar `viewBox`, proporção, sentido e identidade do asset;
- não editar o SVG em disco para mudar cor de um uso isolado;
- importar os assets pelo catálogo `web/src/config/assets.ts` ou helper equivalente;
- não substituir SVG oficial por emoji, ícone Unicode, Font Awesome, Material Icons ou asset externo sem autorização;
- não esticar imagem alterando sua proporção, salvo quando o componente existente fizer recorte intencional e validado;
- não deformar imagens de máquinas;
- não adicionar brilho, neon, sombra ou fundo decorativo aos ícones;
- manter ícones de uma mesma família com peso visual e escala equivalentes.

Branding oficial recortado:

```text
logo_gestor_pecas.png = 254 x 52
icone_perfil.png       = 60 x 60
```

Essas dimensões são validadas por teste.

### Telas e famílias de composição

Antes de alterar uma tela, identificar a família visual correspondente.

#### 1. Tela Inicial

Padrão:

- KPIs no topo em duas linhas;
- blocos de Últimas Movimentações e Tarefas Recentes;
- blocos de Alertas e Status;
- alinhamento de cabeçalhos de painéis;
- cards com altura equilibrada;
- sem scroll global da página em resoluções suportadas quando o layout atual já cabe.

#### 2. Tarefas e Cadastro

Padrão:

- toolbar/card de ações no topo;
- tabela como elemento principal;
- detalhes/ações secundárias abaixo quando aplicável;
- não deixar botões soltos fora do grid visual.

#### 3. Seleção de máquina

Padrão:

- cards grandes centralizados;
- duas opções na primeira linha e terceira centralizada;
- imagens de máquina em destaque;
- fundo geral limpo, sem painel decorativo adicional.

#### 4. Registro de máquina

Padrão:

- card de formulário central;
- forte hierarquia vertical;
- campo de OP como ação principal;
- status e fila abaixo;
- botão voltar no header.

#### 5. Consulta Operacional — seleção

Padrão:

- grade de `SelectionCard`;
- cada função representada por asset oficial;
- módulos novos devem seguir o mesmo sistema visual dos cards existentes.

#### 6. Consulta Operacional — visão geral

Padrão:

- KPIs compactos em duas linhas;
- alertas/status abaixo;
- controles secundários discretos;
- foco em leitura rápida de situação operacional.

#### 7. Consulta Operacional — tabelas

Padrão:

- filtros/ações no topo;
- tabela ocupando a maior parte da superfície útil;
- cores de linha e badge comunicam situação sem prejudicar leitura;
- histórico usa azul primário em ação de filtro/pesquisa quando aplicável.

#### 8. Relatórios — seleção

Padrão:

- dois cards grandes lado a lado;
- Movimentações associado ao roxo oficial;
- Tempo MES associado ao azul primário;
- muito espaço negativo controlado ao redor dos cards.

#### 9. Relatórios — conteúdo

Padrão:

- filtros/tabs discretos no topo;
- gráficos dentro de superfície branca;
- KPIs e tabelas usando os mesmos tokens do restante do sistema;
- não aplicar tema independente da biblioteca de gráficos que conflite com a UI.

### Gráficos

Gráficos Web devem parecer parte do sistema, não uma aplicação embutida com tema diferente.

Regras:

- fundo coerente com a superfície branca do card;
- títulos e labels legíveis;
- cores de série derivadas da paleta oficial quando houver correspondência semântica;
- evitar arco-íris de cores arbitrárias;
- quantidades de peças devem permanecer inteiras quando o dado for discreto;
- não remover eixos/labels necessários só para "limpar" o gráfico;
- respeitar o espaço do card e evitar corte de labels.

### Densidade e alinhamento

O design é compacto, porém não apertado.

Regras gerais:

- alinhar bordas de cards que pertencem à mesma coluna ou linha;
- manter alturas iguais em cards irmãos quando o padrão visual exigir;
- centralizar conteúdos de seleção e apontamento;
- em tabelas e dashboards, privilegiar uso da largura disponível;
- não criar grandes vazios por `stretch` mal posicionado;
- não encostar componentes nas bordas da página;
- não fazer correções locais que desalinharem a tela em outras resoluções.

### Regra para novos componentes e novas telas

Quando não existir mockup específico para uma nova funcionalidade:

1. identificar a família de tela existente mais próxima;
2. reutilizar layout, tokens e componentes compartilhados dessa família;
3. reutilizar `UI_COLORS`, `SPACING`, `RADII` e `DEFAULT_UI_FONT`;
4. reutilizar assets oficiais existentes sempre que semanticamente corretos;
5. criar o mínimo possível de novas constantes visuais;
6. se for necessário um novo padrão, centralizá-lo no design system em vez de espalhar stylesheet inline;
7. manter a nova tela visualmente indistinguível de uma tela que faria parte do conjunto original aprovado.

Não inventar design novo só porque não existe PNG da funcionalidade.

### Stylesheet e arquitetura visual

Preferência obrigatória:

- tokens em `web/src/styles/tokens.css`;
- stylesheet compartilhado em `web/src/styles/global.css`;
- componentes reutilizáveis em `web/src/components/`;
- composição das telas em `web/src/pages/` e `web/src/layouts/`.

Evitar:

- HEX repetido em dezenas de arquivos;
- `setStyleSheet` inline para componente reutilizável;
- regras globais que alterem widgets não relacionados;
- duplicar `SelectionCard`, `KpiCard` ou tabela com pequena diferença visual;
- valores mágicos sem relação com mockup, token ou necessidade responsiva.

Stylesheet inline é aceitável quando:

- o estado é realmente local/dinâmico;
- há justificativa semântica;
- não cria novo padrão visual paralelo.

### Mudanças visuais proibidas sem autorização explícita

Não fazer por iniciativa própria:

- redesenhar a interface;
- trocar paleta;
- trocar fonte;
- alterar logo;
- alterar espessura/estilo dos ícones oficiais;
- remover sidebar ou header;
- converter cards em layout sem borda;
- adicionar sombras/gradientes/neon;
- trocar tabelas por cards;
- trocar cards por tabelas;
- alterar ordem visual dos módulos principais;
- ocultar informação para "despoluir";
- reduzir controles operacionais importantes;
- mudar cor de status;
- alterar proporção das máquinas;
- usar assets `legacy` para substituir assets atuais;
- criar tema escuro;
- criar animações que atrasem operação ou modifiquem a leitura do estado;
- adicionar transparência que reduza contraste;
- substituir texto por ícone onde o mockup usa ambos.

### Fluxo obrigatório para qualquer tarefa visual

Antes de editar código de UI:

1. localizar a tela correspondente em `assets/screens/screens - atuais/`;
2. abrir e inspecionar visualmente o PNG;
3. identificar os SVGs/PNGs oficiais usados naquela tela;
4. ler os tokens em `web/src/styles/tokens.css`;
5. verificar o comportamento em `web/src/styles/`, `components/` e `pages/`;
6. localizar testes relevantes em `web/src/test/`;
7. medir geometria quando necessário, em vez de estimar "a olho";
8. modificar o menor número possível de componentes;
9. renderizar novamente e comparar com a referência;
10. validar também resoluções menores suportadas no navegador.

Uma IA não deve começar uma alteração visual relevante olhando apenas o componente React da tela.

### Regra de comparação visual

Ao comparar implementação com mockup, verificar no mínimo:

- largura da sidebar;
- altura do header;
- margem externa do conteúdo;
- posição do título;
- alinhamento dos cards;
- largura e altura de cards irmãos;
- distância entre cards;
- cor exata de fundos e bordas;
- raio de borda;
- tamanho e peso das fontes;
- tamanho, proporção e posição dos ícones;
- altura de inputs e botões;
- altura de linha e header de tabelas;
- alinhamento de tabela;
- cores de estados;
- comportamento de hover/foco/disabled quando relevante;
- overflow e clipping;
- presença indevida de scroll;
- comportamento em 1920x1080, 1600x900 e 1366x768.

Tolerância recomendada para elementos estruturais medidos na mesma escala: até aproximadamente 2 px quando houver arredondamento decorrente do fator responsivo. Cor de token e asset oficial não têm tolerância conceitual: devem ser os valores corretos.

### Validação visual automatizada

Quando uma alteração tocar o design, executar pelo menos:

```bash
cd web
npm test
npm run build
```

E, quando aplicável, também:

```bash
python -m unittest discover -s tests
```

Os testes de design já verificam, entre outros pontos:

- catálogo das telas atuais e legacy;
- dimensões dos PNGs oficiais;
- catálogo e validade dos SVGs;
- branding recortado;
- organização e dimensões de KPIs;
- geometria responsiva da sidebar e header;
- avatar, navegação, relógio e rodapé da sidebar;
- cards de seleção;
- tabelas, zebra, larguras, status e scroll;
- composição de relatórios e dashboards.

Não alterar testes para aceitar uma regressão visual. Se o design foi explicitamente alterado, atualizar teste e referência porque o contrato mudou, não porque o teste "atrapalha".

### Critério de pronto para tarefa visual

Uma tarefa visual só está pronta quando:

- a tela continua funcional;
- a regra de negócio não foi alterada;
- o mockup atual foi usado como referência;
- cores vêm dos tokens oficiais;
- fonte oficial foi preservada;
- assets oficiais foram reutilizados;
- proporções de imagens foram preservadas;
- componentes compartilhados foram reutilizados quando cabível;
- layout principal continua responsivo;
- não há clipping, sobreposição ou scroll indevido;
- os testes Web pertinentes passam;
- a tela foi comparada visualmente na resolução de referência;
- 1600x900 e 1366x768 foram verificadas quando a mudança for estrutural;
- qualquer divergência restante foi explicitamente informada no relatório final.

## Compatibilidade

Durante refatorações:

- atualizar imports internos para a arquitetura atual;
- evitar dependência circular;
- não recriar wrappers antigos na raiz sem necessidade real;
- não apagar arquivo sem confirmar que não existe import ativo;
- não duplicar lógica entre arquivos antigos e novos.

Wrappers temporários são permitidos apenas se ainda houver compatibilidade necessária.

Wrappers não devem conter regra duplicada.

## Testes e validação

Antes de considerar uma tarefa concluída, rodar quando aplicável:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Também validar imports principais do produto Web:

```bash
python -c "import backend.api.main"
python -c "import app.database.database"
python -c "import app.core.operator_sectors, app.core.permissions"
python -c "import mes.services.operator_flow"
python -c "import mes.services.cut"
python -c "import mes.services.task_lookup"
python -c "import mes.services.production"
python -c "import mes.services.operational_reports"
python -c "import mes.integrations.totvs.service"
```

Os entrypoints desktop (`gestordepeca.py`, `app/main_window.py`, `app/ui/*`) não
existem mais: o produto é Web-only. O pacote `qlik/` está fora da arquitetura
alvo e não deve ser incluído em validação de import.

Se houver reorganização de arquivos, criar ou atualizar teste de compatibilidade de imports.

## Critério de pronto

Uma tarefa só está pronta quando:

- o sistema continua importando;
- testes relevantes passam;
- migrations PostgreSQL e constraints relevantes continuam válidas quando o banco for tocado;
- fluxo produtivo principal não foi alterado indevidamente;
- não há loop infinito;
- integrações externas falham de forma controlada;
- erros importantes são registrados;
- mudanças foram explicadas;
- riscos restantes foram listados.

## Relatório final esperado

Ao final de cada tarefa relevante, informar:

- arquivos alterados;
- funções movidas ou modificadas;
- wrappers criados ou removidos;
- problemas encontrados;
- problemas corrigidos;
- testes executados;
- resultado dos testes;
- riscos restantes;
- pontos que exigem teste manual.

## Estilo de trabalho

Para tarefas complexas, primeiro analisar e planejar.

Fazer mudanças pequenas e verificáveis.

Preferir correções pequenas a reescritas grandes.

Durante estabilização, não criar novas funcionalidades.

Durante organização estrutural, estabilidade vale mais que estrutura perfeita.

Durante melhoria visual, não alterar regra de negócio.

Durante mudanças no banco, preservar dados, atomicidade e rastreabilidade acima de tudo.


## Direção futura Web

A apresentação oficial do Gestor de Peças é Web, incluindo apontamento e visão dos gestores. Terminais de linha devem ser compatíveis com Raspberry Pi + Chromium e gestores/diretoria usam navegador em dispositivos autorizados. Todo código novo de domínio, analytics, contratos, repositories e services deve permanecer independente de React e FastAPI. Ver `docs/WEB_TARGET_ARCHITECTURE.md`.

## Regras visuais operacionais — refatoração v12

Estas regras complementam a identidade visual existente e valem para as telas de apontamento do operador. Elas não autorizam mudar a paleta oficial.

- Produção e Fila de Ordem devem usar cards com hierarquia fixa: OP/estado → operação → produto/descrição → quantidades/tempo → contexto do estado.
- Descrição longa deve usar elide/tooltip ou quebra controlada; nunca pode invadir quantidade, badge, botão ou borda.
- OP em parada deve mostrar, quando disponível, o motivo e o tempo decorrido da parada; cor vermelha sozinha não é informação suficiente.
- O apontamento de Parada deve oferecer busca incremental dos motivos e lista rolável, preservando motivo selecionado, comentário e contexto da OP/recurso.
- Painel sem conteúdo deve exibir empty state curto em vez de grande área branca sem explicação.
- Histórico de Produção deve permitir leitura por OP/produto/descrição e distinguir Aberto/Finalizado por texto e badge, não apenas por cor.
- O modo operador do Destaque segue `Início → Fim`; `Parada` é ocorrência contextual durante a execução. Os botões Início/Fim/Parada permanecem visíveis e habilitados; transição inválida deve gerar explicação, não botão morto.
- Detalhes do Destaque devem estruturar Início, Fim, estado/tempo e, quando houver parada, motivo e contador de parada. Não usar uma linha única separada por `|`.
- Finalização do Destaque exige confirmação específica com tarefa, OPs vinculadas e crachá do operador antes do registro do fim.
- A tabela de OPs do Destaque deve priorizar Código OP, Nome da Peça, Setor Destino e Quantidade; colunas técnicas não necessárias ao operador não devem ocupar espaço visual.
- A tela de Corte deve oferecer busca por tarefa/plano e, quando os dados existirem, material/nesting; cards devem separar cabeçalho, material/espessura/quantidade, nesting/tempos e ação.
- Mensagens de UI devem usar linguagem operacional. Não expor detalhes internos como PostgreSQL, workers ou sincronização técnica salvo em tela administrativa apropriada.
- Foco de layout: 1920×1080; validar resistência em 1600×900 e 1366×768 sem comprometer o 1080p.
