# IA Workforce privada — Codex

Para tarefas não triviais, o agente principal atua como **orquestrador** de `.ai/ORCHESTRATOR.md`.
Runtime desejado: **GPT-5.6 Sol / high**. Use `.ai/employees/` e `.agents/skills/`; delegue só com independência real ou gate de risco. A workforce nunca faz parte do runtime MES.

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

## Contexto por tema — leitura obrigatória quando aplicável

Os arquivos abaixo foram extraídos deste `AGENTS.md` em 2026-09-29 e têm a **mesma força normativa** dele. Cada regra vive em exatamente um lugar; ler o arquivo do tema antes de agir quando a tarefa o tocar:

- `DESIGN.md` — ler ANTES de qualquer tarefa de UI/CSS/tela/componente visual.
- `SECURITY.md` — ler antes de tarefa de auth, sessão, segredos, credenciais, exposição de endpoint ou entrada externa.
- `DATABASE.md` — ler antes de tarefa de SQL, migration, schema, repositório, transação ou fonte canônica de dados.
- `API.md` — ler antes de tarefa de rota, contrato HTTP, fachada, integração TOTVS/SigmaNEST ou outbox.
- `CODE_STYLE.md` — ler ao escrever ou revisar código (codificação de arquivos, compatibilidade em refatorações).

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

## Arquitetura e integração corporativa

O planejamento pertence ao **Protheus/TOTVS**. O Gestor registra **execução real**, mantém PostgreSQL próprio e compara Plano × Real. Não existe decisão de substituir o PostgreSQL por escrita/leitura direta no banco do ERP.

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

Falha de equipamento (MTBF/MTTR) é decidida pelo **grupo de manutenção corretiva
do catálogo de motivos** (`EQUIPMENT_FAILURE_STOP_GROUP` em
`mes/domain/manufacturing_rules.py`, hoje `0003`), nunca por texto de motivo.
Manutenção preventiva, espera, falta de material e setup não são falha, e parada
marcada como programada também não. Capacidade é publicada como **utilização
temporal** sobre o calendário produtivo cadastrado; capacidade em peças exige
tempo padrão/ciclo ideal confiável por operação e não deve ser estimada.

**A lógica de apontamento do Gestor é canônica.** A integração TOTVS fornece planejamento ao domínio existente e não cria uma segunda lógica operacional. Depois da projeção para as estruturas canônicas, a origem da OP deve deixar de ser relevante: não criar branch por origem, tabela paralela de OP, evento especial nem coluna corporativa nas tabelas de execução.

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

## Mudanças e estabilização

- não alterar regra produtiva sem autorização;
- não transformar inferência do PCFactory em regra oficial;
- não esconder erro real alterando teste;
- não duplicar cálculo em serviço e UI;
- manter compatibilidade pública quando possível;
- mudanças de schema devem ser versionadas e seguras;
- quando uma definição oficial estiver pendente — como FTT final com refugo/retrabalho ou estratégia de rateio por cenário — preparar a arquitetura e marcar como pendente, sem escolher por conta própria.

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
