# AMADA → Gestor de Peças: evidência do checkout e mapeamento condicionado

Data: 08/10/2026. Escopo: leitura estática do checkout TESTE, sem banco, sem rede, sem imports da aplicação e sem alteração de código. Todas as linhas abaixo se referem ao checkout `C:/Users/iago.luchtenberg/Documents/Sistema - Iago/Gestor de Peças - Area de Testes`.

## 1. Resultado

[CERTO] Há identidades canônicas para Laser Ensis, HG2204 e EGB1303 no código e em artefato histórico do catálogo. Há separação entre estado físico, execução de OP, quantidades, tempo e rateio. Há planejamento SigmaNEST para a Laser.

[CERTO] Nenhum adapter AMADA/VCBox/MTConnect/OPC UA foi localizado na busca dos fontes Python de `app/`, `backend/`, `mes/`, testes e dependências consultadas. Isso é evidência de ausência de implementação localizada, não prova de ausência de serviços no chão de fábrica.

[CERTO] Esta leitura não comprovou endpoint de máquina, IP, serial, firmware, NodeId, DataItem nem valor de telemetria. Não autoriza afirmar que a empresa tem V-factory/VCBox ou que alguma máquina publica OPC UA/MTConnect.

## 2. Proveniência e limites da leitura

- Instruções lidas: `AGENTS.md`, `.ai/GOVERNANCE.md`, `.ai/employees/ot-connectivity-engineer.md`, `ROADMAP.md` seção 5, `docs/STATUS_ATUAL.md`, `API.md`, `DATABASE.md`, `docs/API_CONTRACTS.md`, `docs/WEB_ARCHITECTURE.md`, partes pertinentes de `docs/INTEGRACAO_CORTE_SIGMANEST.md`.
- HEAD observado: `9c5f712e86d8328113f15eb4422122a644b85170`.
- `git log --oneline -20` executado. O último commit altera rateio analítico por varredura de eventos.
- WIP encontrado e preservado: `app/database/database.py`, `docs/STATUS_ATUAL.md`, `mes/services/industrial_analytics.py`, `mes/services/standard_time.py`, `tests/fakes.py`, `tests/test_standard_time.py`, `tests/test_standard_time_postgres.py`, diretório não rastreado `CAPTURAS_UI/`.
- Evidência é do arquivo atual, incluindo WIP, não apenas do último commit. Números de linha podem mudar com trabalho paralelo.
- Na verificação final, outra sessão havia mudado o status para `M tests/test_concurrency_invariants.py` e `?? CAPTURAS_UI/`. Nenhuma escrita foi feita por este subtrabalho no checkout; o inventário de WIP acima é o snapshot inicial, não uma alegação de status final inalterado.
- Não foram lidos `.env`, credenciais ou certificados privados. Não foram executados testes/imports que poderiam inicializar banco/integrações. Validação foi leitura cruzada de contratos, código e artefatos existentes.
- O diretório de desenvolvimento tem nome TESTE, mas `docs/STATUS_ATUAL.md:32-41` registra promoção REAL e API operacional em `:8001`. O nome da pasta sozinho não é garantia de ambiente isolado.

## 3. Inventário e correspondência das identidades

| Máquina pedida | Nome no posto | Código canônico | Evidência | Classificação e limite |
|---|---|---|---|---|
| ENSIS-3015AJ 12 kW / AMNC 3i | Laser Ensis 3015 | `LASER1` | `app/core/resource_mapping.py:24,88`; `mes/services/cut.py:19-23` | [CERTO] identidade Laser Ensis no MES; [PROVÁVEL] corresponde à máquina física informada. Sufixo AJ, potência, serial e controlador não identificados no cadastro examinado. |
| HG2204 / AMNC 3i | 2204 | `DOBRA2` | `app/core/resource_mapping.py:13,71`; `tests/etapa4c_recursos/saneamento_recursos.json:80-90,3404-3421` | [CERTO] catálogo histórico nomeia HG2204 como DOBRA2; [PROVÁVEL] vínculo ao equipamento físico local até conferir serial/IP. |
| EGB1303e / AMNC 4ie | 1303 | `DOBRA3` | `app/core/resource_mapping.py:14,72`; `tests/etapa4c_recursos/saneamento_recursos.json:92-102,3423-3440` | [CERTO] catálogo histórico nomeia EGB1303 como DOBRA3; [PROVÁVEL] vínculo ao equipamento físico informado; sufixo “e” e controlador não constam na evidência examinada. |
| Gasparini | Gasparini | `DOBRA1` | `app/core/resource_mapping.py:12,70`; mesmo JSON `:68-78` | [CERTO] é outro recurso. Não associar a HG pelo rótulo informal “Dobra 1”. |

[CERTO] `LASER` é alias oficial de `LASER1`, registrado em `app/core/resource_mapping.py:56-64`. Identidade física e código gravado no roteiro são coisas diferentes: a função de alias permite comparação/leitura, não reescreve a operação recebida.

[CERTO] O código SigmaNEST é `AMADA_ENSIS`, que `mes/services/cut.py:19-23,62-69` mapeia para `Laser Ensis 3015`. Usar a função canônica de resolução, sem criar associação por prefixo/fuzzy matching.

[CERTO] A origem do catálogo histórico das dobradeiras é “PC Factory D0021 - Recurso”, sincronização `2026-08-20 16:35:46`, no JSON `:3409-3410,3428-3429`. O artefato declara banco `gestor_pecas_test` em `:2`; não é consulta atual ao catálogo REAL.

## 4. Fontes e estados existentes no MES

| Conceito | Fonte canônica | Código/contrato verificado |
|---|---|---|
| Estado físico da máquina | `eventos_estado_recurso` | `DATABASE.md:9`; `mes/services/resource_state.py:59-88`; `app/database/database.py:4353-4421,4758-4797` |
| Quantidade classificada | `eventos_quantidade_producao` | `DATABASE.md:10`; `mes/domain/industrial.py:63-66`; `app/database/database.py:4957-4994` |
| Execução da OP | `apontamentos_operacionais` + `eventos_apontamento_operador` | `DATABASE.md:11`; `mes/domain/operator_state_machine.py:15-84`; `mes/services/operator_flow.py:1382-1417` |
| Tempo físico e atribuição a OP | `sessoes_recurso` + `rateios_tempo_op` | `DATABASE.md:12`; `app/database/database.py:5186-5241` |
| Calendário/turno/pausa | calendários, turnos, exceções e parâmetros/setor | `DATABASE.md:13`; `docs/STATUS_ATUAL.md:65-95`; `mes/domain/manufacturing_rules.py:265-279` |
| Corte/chapa física | `apontamentos_corte` | `DATABASE.md:14`; `mes/services/cut.py:80-122,248-322` |
| Planejamento corporativo | OP/roteiro/recurso do TOTVS | `API.md`, `AGENTS.md` e roadmap. Não é fonte do estado físico observado. |

[CERTO] Categorias físicas no domínio: `fila`, `producao`, `parada`, `setup`, `retrabalho`, `atividade_sem_op`, `fora_turno`, `desconhecido` (`mes/domain/industrial.py:18-35`). `sem_demanda` é derivação analítica, não valor persistido: `mes/analytics/resource_state.py:44-63` deriva `fila` sem OP por regra canônica.

[CERTO] A máquina de estados de OP possui `fila`, `producao`, `parada`, `setup`, `retrabalho`, `finalizado` (`mes/domain/operator_state_machine.py:15-21`) e transições restritas (`:34-61`). O estado físico desconhecido ou CNC ativo não substitui automaticamente um comando do operador.

[CERTO] O banco impede dois estados físicos abertos para o mesmo recurso: `app/database/migrations.py:572`. O escritor toma trava por recurso (`database.py:4371`), encerra intervalo anterior e abre novo. Repetir exatamente o mesmo estado mantém o intervalo (`:4378-4392`); evento anterior ao início atual pode ser ignorado como retroativo (`:4373-4376`). Não há arbitragem explícita de prioridade OT × operador × scheduler na assinatura examinada.

[CERTO] Estado aceita `origem`, `referencia_origem`, `data_hora` e vínculos opcionais de OP/operação/produto (`database.py:4353-4359,4400-4418`). O serviço `ResourceStateService.registrar_estado` fixa origem `resource_state_service` (`mes/services/resource_state.py:82`); um futuro adapter precisará preservar a origem OT por contrato próprio na camada de serviço.

[CERTO] Quantidade exige OP e tipo `boa/refugo/retrabalho`, inteiro positivo (`database.py:4957-4968`; `migrations.py:574-590`). Índice único `(origem, referencia_origem, tipo)` com referência não nula existe (`migrations.py:595`). O método de inserção consultado não trata replay por `ON CONFLICT`; o futuro consumidor deve cuidar de repetição/retry e de reset de contador. Isso não equivale a exatamente uma vez ponta a ponta.

## 5. Mapeamento AMADA → observação normalizada → Gestor (PROPOSTA)

Todas as linhas seguintes são [HIPÓTESE] de contrato futuro. O valor/tag original precisa ser encontrado e sua semântica validada na máquina. `RUNNING`, `IDLE` etc. são nomes propostos de observação; não são enums existentes do Gestor.

| Sinal realmente obtido, se existir | Observação proposta | Destino possível no Gestor | Condição obrigatória |
|---|---|---|---|
| `Execution=ACTIVE` / execução CNC | `RUNNING` | Candidato a `producao` no recurso LASER1/DOBRA2/DOBRA3 | Confirmar se execução é lote, teste, retorno, demonstração ou primeira peça/setup; manter OP e aprovação separados. No primeiro PoC apenas comparar. |
| `Execution=STOPPED/READY/INTERRUPTED` | `IDLE/STOPPED`, valor original preservado | Candidato a `parada`, `fila` ou outro estado conforme contexto | CNC parado não decide causa industrial nem “sem demanda”. A OP pode estar ativa esperando carga, ferramenta ou operador. |
| Modo manual/edição | `MANUAL/EDIT` | Contexto da observação | Modo não prova `setup`. Não marcar setup apenas por ControllerMode. |
| Sinal dedicado, documentado, de preparação | `SETUP` | Candidato a `setup` | Validar diferença entre preparação, troca de ferramental e inspeção/primeira peça; não aprovar qualidade automaticamente. |
| Condition/Alarm código e texto | `ALARM_RAISED/CLEARED` | Registro observacional com período; causa candidata de parada | Alarme não é necessariamente parada. Associar ao estado/parada só se houver correlação e mapa aprovado para catálogo de motivos. |
| Availability indisponível / timeout | `TELEMETRY_UNAVAILABLE` com qualidade inválida | Sem dado confiável; candidato a `desconhecido` apenas após definir política | Comunicação ausente não prova máquina desligada, quebrada ou fora de turno. Não manter indefinidamente último valor como atual. |
| Power ligado/desligado explicitamente | `POWER_ON/OFF` | Contexto/estado observado | Não converter desligada em `fora_turno`; calendário é fonte de turno. |
| Programa atual / job | `PROGRAM_SELECTED/CHANGED` | Contexto do recurso e candidato à correlação com plano/operação | Igualdade de nome não prova OP. Laser exige programa/chapa/repetição e composição SigmaNEST. |
| Início/fim de ciclo | `CYCLE_STARTED/COMPLETED` | Tempo físico observado e candidato de reconciliação | Definir exatamente que ciclo está sendo medido; fim de ciclo não finaliza OP nem todo nesting/tarefa. |
| PartCount/counter | `COUNTER_OBSERVED`, eventualmente delta | Candidato de quantidade só após semântica e vínculo | Contador pode ser acumulado, peças tentadas, programa/chapa ou golpes; tratar reset, wrap, replay e troca de programa. Nunca marcar delta como boa por padrão. |
| StrokeCount/ciclo das dobradeiras | `STROKE_COMPLETED` | Telemetria de processo | Uma peça pode precisar de vários golpes e golpe de setup também conta. Não lançar peças boas/golpes na mesma unidade. |
| Material/espessura | `PROCESS_CONTEXT` com origem | Comparação com planejamento SigmaNEST/produto | Campo do programa é declarado/configurado, não medição de material físico. Divergência é reconciliação, não atualização automática do planejamento. |
| Energia acumulada/potência | `ENERGY_TOTAL/POWER` com unidade | Métrica observacional futura | Não foi encontrado contrato de consumo de energia no fluxo analisado; unidade, integração temporal e reset precisam de confirmação. |
| Modelo/serial/controlador/versão | `DEVICE_IDENTITY` | Associação física explícita ao recurso | Confirmar inventário com placa/controlador e endpoint; nome parecido não basta. |

Preservar no PoC: recurso candidato, identidade de device, protocolo, endpoint sem segredo, timestamp da origem e do recebimento, sequência/instanceId se houver, unidade, qualidade, valor original e referência da amostra. Isso é especificação proposta, não persistência implementada.

## 6. Particularidades do Laser e do SigmaNEST

[CERTO] O planejamento disponível tem tarefa, programa, chapa, máquina, repetição, material, espessura e composição por peça/WO. Fontes estáticas: `backend/integrations/sigmanest_sqlserver.py:131-167`; DTOs `mes/integrations/sigmanest/models.py:57-74,115-130,144-150`.

[CERTO] A identidade física de nesting inclui `TaskName/ProgramName/SheetName/RepeatID`; a deduplicação por repetição está comentada em `backend/integrations/sigmanest_sqlserver.py:265-268`. As regras atuais estão em `AGENTS.md` (hierarquia tarefa → plano → OP → produto). Um programa cortado várias vezes produz várias chapas físicas.

[CERTO] A documentação histórica registra 158/180 nestings com mais de uma OP e exemplo de 24 OPs em um programa (`docs/INTEGRACAO_CORTE_SIGMANEST.md:23-37`). São resultados históricos relatados, não medidos nesta sessão. Mesmo com programa CNC comprovado, não atribuir todo tempo/contador a uma única OP.

[CERTO] `WONumber` da linha de peça é a ponte documentada para a OP; código de produto não é chave suficiente (`API.md`, `docs/INTEGRACAO_CORTE_SIGMANEST.md:84-105`). O programa deve ser correlacionado sem adivinhar repetição/chapa ativa se existir ambiguidade.

[CERTO] `CutService.finalizar` pode concluir a chapa atual e começar a próxima da tarefa (`mes/services/cut.py:248-322`). Executar essa API com sinal de fim CNC teria efeitos maiores que um simples registro de telemetria.

[CERTO] Somente a Laser Ensis libera Destaque pela regra de identidade `ManufacturingRules.cut_releases_highlight` (`mes/domain/manufacturing_rules.py:226-229`). A conclusão canônica de Corte exige Destaque e todos os nestings ativos finalizados, como definido em `AGENTS.md`. Não substituir por “programa terminou”.

## 7. OEE, Andon e impacto de misturar fontes

[CERTO] OEE atual usa tempo físico e quantidades classificadas. Fórmulas do código: Disponibilidade = trabalhado/disponível; Performance = (tempo padrão de boas + apoio)/trabalhado; FTT = boas/(boas + refugo + retrabalho) (`mes/analytics/oee.py:114-128,134-190`). Setup, retrabalho e atividade sem OP entram como apoio conforme a fórmula vigente. Não implementar outro cálculo a partir de duty cycle do CNC.

[CERTO] Quantidade sem padrão confiável bloqueia ou marca Performance parcial; ausência permanece ausência (`oee.py:126-128`). Telemetria melhora tempo/ciclo, mas não resolve sozinha padrão/qualidade.

[CERTO] `docs/STATUS_ATUAL.md:28` registra pendências com Manufatura: validade do tempo previsto SigmaNEST como padrão e FTT/retrabalho/unidade de peça nestada. Consolidação por soma de bases foi homologada em 08/10. Não usar esta investigação para escolher regras ainda pendentes.

[CERTO] Andon aplica categorias recebidas da fonte canônica e usa `desconhecido` para categoria não reconhecida (`mes/services/andon.py:663-708`). Motivo/cor/classificação vêm resolvidos do backend, não de texto do alarme. A projeção publica categoria física, início, duração, motivo, código e fonte.

[CERTO] Falha para MTBF/MTTR depende do grupo corretivo `0003` (`mes/domain/manufacturing_rules.py:153-159,515`), não da simples presença de qualquer alarme.

[PROVÁVEL] Introduzir o polling OT diretamente no escritor de estado atual pode disputar a timeline com eventos do operador e scheduler, alterar OEE/Andon e perder a causa operacional. Esta consequência deriva do escritor único por recurso (`database.py:4371-4418`) e precisa de arbitragem aprovada antes de ativar ingestão operacional.

## 8. APIs reais disponíveis para comparação em PoC

Base de rotas [CERTO]: `/api/v1`, `backend/api/main.py:983-998`. Contratos públicos: `docs/API_CONTRACTS.md:3-14`.

| Método/rota | Utilidade | Evidência |
|---|---|---|
| `GET /api/v1/operator/stations` | postos e recursos elegíveis | `backend/api/routers/operator.py:126` |
| `GET /api/v1/operator/workbench` e `/history` | contexto/execução registrada | `operator.py:254,277` |
| `GET /api/v1/cutting/queue` e `/history` | programas/chapas/OPs e execução do Corte | `backend/api/routers/cutting.py:70,214` |
| `GET /api/v1/operations/overview` | estado físico e visão operacional | `backend/api/routers/operations.py:58` |
| `GET /api/v1/operations/resources`, `/orders`, `/time` | recursos, OPs ativas e tempo | `operations.py:79,100,115` |
| `GET /api/v1/operations/stream` | SSE de atualização MES | `operations.py:124` |
| `GET /api/v1/andon` | snapshot para TV | `backend/api/routers/andon.py:12-15` |
| `GET /api/v1/analytics/oee` | OEE calculado pelo serviço | `backend/api/routers/analytics.py:24`; `docs/API_CONTRACTS.md:74-78` |
| `GET /api/v1/orders/production` e `/planned-vs-actual` | realizado e comparação com plano | `backend/api/routers/orders.py:49,58` |

Estas rotas são existentes no código, não endpoints consultados nesta sessão. Requerem autorização/sessão apropriada conforme seu contrato; não improvisar bypass ou credencial de integração. Nenhuma rota dedicada de ingestão AMADA foi localizada.

[CERTO] `POST /operator/actions` (`operator.py:536`) e `POST /cutting/actions` (`cutting.py:232`) são comandos operacionais. Não são canais de teste de telemetria; podem gerar fatos, efeitos de workflow e outbound/avisos. A prova de leitura de máquina não autoriza chamá-los.

## 9. Menor PoC proposto e gates

[HIPÓTESE] Depois de comprovar um endpoint somente leitura de uma máquina, o menor PoC é capturar por curto período estado, programa, contador se existir e timestamp, salvar a resposta original e comparar os instantes com os apontamentos/chapas do Gestor. Uma máquina, uma sessão produtiva normal, sem comandar CNC e sem publicar fatos no REAL.

1. Conferir serial/modelo/controlador no device e relacionar explicitamente a `LASER1`, `DOBRA2` ou `DOBRA3`.
2. Demonstrar dois estados reais observados passivamente durante operação normal e registrar qual sinal muda. Não acionar a máquina para fabricar o teste.
3. Documentar latência/resolução, timestamp/timezone, qualidade e perda de conexão; não prometer “tempo real” sem medir.
4. Correlacionar programa CNC a contexto MES. Laser: tarefa/programa/chapa/repetição/composição; Dobra: OP/operação/produto e número de golpes por peça, sem estimar.
5. Só então propor ingestão por adapter de transporte externo + serviço neutro de normalização; conservar domínio e repositórios existentes.
6. Antes de ingressar na timeline operacional: decidir prioridades OT/operador/scheduler, períodos sem dado, tratamento de fora de turno e regras de associação. Validar em TEST realmente isolado e desativar efeitos externos no ensaio.

Não foi implementado adapter, schema, endpoint, worker ou framework. O resultado deste subtrabalho é o mapa factual do MES e os limites para encaixar sinais realmente descobertos pelo restante da investigação.

## 10. Lacunas específicas para a integração

- IP/serial/controller firmware e identidade do endpoint das três máquinas.
- Protocolo, modo/licença e fonte de dados realmente disponíveis por equipamento.
- Lista real de DataItems/NodeIds, valores/unidades e frequência.
- Semântica de ciclos/golpes, contador, reset e programas, inclusive primeira peça/setup.
- Vínculo entre programa/job e OP/operação; para Laser, também chapa/repetição e composição multi-OP.
- Política de arbitragem e reconciliação entre observação OT e fatos manuais/calendário.
- Qualidade de timestamp, sincronização de relógio e timezone: o schema atual armazena timestamps sem timezone (`app/database/migrations.py:563,588`), enquanto a origem pode enviar UTC/offset; converter explicitamente na fronteira futura e preservar original.
- Sinais de alarme não fazem parte de um contrato AMADA persistido localizado; definir associação de catálogo sem classificar warning como falha.
- Acesso operacional local ao MES não foi exercitado; catálogo atual REAL não foi consultado. Os pares de recursos acima são confirmados no código/artefato, com conferência física ainda pendente.

Observações task-observer: nenhuma observação nova registrada neste subtrabalho; Session Start compartilhado já executado pelo agente principal.

### Mapeamento com amostras reais do planejamento atual

[CERTO] CSV eReport: Tarefa→codigo_tarefa, Programa→programa, OS→OP observada por linha, Peca→produto observado, Quant_Arranjada→quantidade planejada declarada. [HIPÓTESE] equivalência final com o catálogo SigmaNEST exige confirmar WO/TOTVS, unidade, chapa física/RepeatID e abrangência das repetições. Não multiplicar Quant_Arranjada por Repeticoes sem validar o gerador; nas amostras, 74+31=105 e 2+7+111=120 já reconciliam os requeridos.

Evento observacional possível: PLANEJAMENTO_EXPORTADO → contexto de LASER1/AMADA_ENSIS e composição tarefa/programa/OP. Não emitir RUNNING, COUNTER_OBSERVED, peça boa ou finalização de Corte a partir desses arquivos. O JSON produzido é evidência externa ao MES, sem persistência operacional. Ver [13-leitura-atual-sigmanest.md](13-leitura-atual-sigmanest.md).
