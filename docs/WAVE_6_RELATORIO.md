# Wave 6 — Relatório Completo

**Projeto:** Gestor de Peças
**Ambiente:** TESTE (`gestor_pecas_test`) — banco REAL (`gestor_pecas`) nunca acessado em nenhuma sub-wave
**Período:** 2026-09-11
**Escopo:** Waves 6A, 6B, 6C, 6D e 6E

---

## Visão geral

A Wave 6 cobriu cinco frentes independentes do Gestor de Peças:

| Sub-wave | Tema | Status |
|---|---|---|
| 6A | Calendário, hora extra, paradas e OEE | ✅ Concluída |
| 6B | Gate de Setup/Qualidade no fluxo do operador | ✅ Concluída (com 2 rodadas de ajuste fino) |
| 6C | Reorganização da tela de Corte (hierarquia Tarefa→Plano→OP→Produto) | ✅ Concluída |
| 6D | Visão gerencial de Solda + integração com TV do Andon | ✅ Concluída (com 1 rodada de decisão de negócio) |
| 6E | Filtros de Pausas/Crachás + humanização de estados técnicos na UI/IA | ✅ Concluída |

Além das cinco waves, foi corrigida uma falha de teste pré-existente (não era regressão de nenhuma wave) que travava havia tempo: `test_execucao_nao_conhece_a_origem_totvs`.

---

## Wave 6A — Calendário, hora extra, paradas e OEE

**Objetivo:** turno normal 08:00–17:30, fora de turno como grandeza global (não duplicada por setor), hora extra como janela planejável, classificação central de parada (PLANEJADA/NÃO_PLANEJADA), correção da entrada do OEE sem tocar na fórmula.

**Principais mudanças:**
- Calendário: `mes/services/calendar.py` ganhou `shift_intervals`, `planned_overtime_intervals`, `operational_intervals`, `out_of_shift_intervals`. Hora extra reaproveita a exceção `disponivel_extra` já existente em `excecoes_calendario_produtivo` — sem tela nova, sem tabela nova.
- Classificação de parada centralizada em `ManufacturingRules.classify_stop` (`mes/domain/manufacturing_rules.py`), com precedência: motivos sempre não planejados → fora de turno → coluna `planejado` do catálogo → grupo `0002 — PARADA PROGRAMADA` → interrupção programada → não planejado por omissão. Cor derivada de um único mapa (amarelo/vermelho).
- Fora de turno passou a ser união temporal global em vez de somado por setor (eliminou ~11x de duplicação observada no período testado).
- OEE: fórmula intacta; a correção foi na entrada (`oee_seconds_by_category`), removendo parada planejada do tempo indisponível. Disponibilidade no período de teste subiu de ~76,2% para ~96,2%.
- Alerta "Recurso possui tempo disponível de turno sem estado físico registrado" removido da apresentação (cálculo interno preservado) — não era bug, era "Sem apontamento" duplicado sem ação possível.

**Ajuste posterior (dados):** as 84 linhas de `catalogo_status_recursos` foram classificadas em `planejado=true/false` usando o critério do grupo `0002` já documentado no código — 22 planejadas, 62 não planejadas, zero pendências.

**Testes:** 25+ testes novos cobrindo os 18 casos temporais especificados; regressão localizada verde.

---

## Wave 6B — Gate de Setup/Qualidade

**Objetivo inicial:** mover a entrada do fluxo de primeira peça do card separado "Primeira Peça" para o botão Iniciar, restrito a Dobra/Usinagem/Serra.

**Evolução (3 rodadas de correção do usuário, todas incorporadas):**

1. Aba "Qualidade" e botão "Setup" inicialmente removidos → **usuário corrigiu**: Setup precisa continuar existindo como apontamento de estado (a primeira peça ainda precisa ser fabricada fisicamente).
2. Retrabalho e refugo precisam de **aprovação de responsável via crachá** (reaproveitando o mesmo mecanismo, sem novo sistema de autorização).
3. Fluxo final de disparo do popup redesenhado: **Iniciar livre → Finalizar exige Setup apontado → clicar em Setup abre o popup do checklist → aprovação libera o lote e a OP retoma produção automaticamente**.

**Fluxo final implementado:**
```
Iniciar (livre, sem gate) → operador produz a 1ª peça
  → Finalizar sem Setup apontado: recusado, orienta apontar o Setup
  → clicar em Setup: aponta o estado E abre o popup do checklist
  → CONFORME → lote liberado → OP retoma produção sozinha (sem clique manual)
  → NÃO CONFORME → Retrabalho (bloqueio + crachá) ou Refugo (crachá)
  → resto do lote segue apontamento único normal (não peça a peça, como Corte)
```

**Preservado integralmente:** conformidade automática (Decimal, `referência ± margem`), regra de saldo/refugo (`Atendido = Boas + Refugo`), retrabalho com autorização por crachá, auditoria, escopo restrito a Dobra/Usinagem/Serra (Solda/Pintura/Corte inalterados).

**Decisão de negócio registrada, não decidida sozinho:** a retomada automática de produção após aprovação usa a transição "Retornar" canônica do posto — aparece na auditoria como um "Retornar" comum, não como evento distinto de retomada automática. Usuário confirmou que está bom assim.

**Fora do processo por decisão do usuário:** a inspeção dimensional peça a peça (`INSPECAO`, RNC, dispensa auditável) ficou sem ponto de entrada na tela do operador — backend/domínio intactos e testados, documentado como decisão intencional, não pendência esquecida.

**Também nesta wave:** histórico de setup/checklist e autorizações por crachá expostos em Análises → Qualidade (reaproveitando endpoint de gestão já existente); scripts de simulação antigos (`scripts/simulacao_fabrica/`, `tests/etapa4b_factory_shift/`) excluídos por incompatibilidade com o novo fluxo — nova versão fica para uma wave futura.

**Testes:** 35 testes dedicados + regressão ampla (129 rápidos + 105 Postgres) verdes; frontend 87/87; build limpo.

---

## Wave 6C — Reorganização da tela de Corte

**Objetivo:** tornar explícita a hierarquia Tarefa → Plano/Nesting → OP → Produto, com expand/collapse, distinguindo corretamente "aguardando corte" de "disponível para Destaque".

**Causa raiz identificada:** a OP existia na linha de peça do SigmaNEST (`STPIPArc.WONumber`), aninhada num `ProgramName`, mas a projeção descartava o programa — a granularidade `(tarefa, OP, peça)` tornava a hierarquia pedida impossível sem inventar dado.

**Correção:** migration 28 adiciona `programa` (anulável); granularidade passa a `(tarefa, programa, OP, peça)`. A consulta homologada do SigmaNEST já trazia esse campo — nenhuma mudança no gateway SQL Server.

**Resultado:** tarefa recolhível (▼/▶, estado local) → planos com estado próprio (`AGUARDANDO CORTE` / `EM CORTE` / `DISPONÍVEL PARA DESTAQUE` / `FINALIZADO`) → OPs com produto e quantidade → chapas reais com repetição (nunca assumindo "1 nesting = 1 chapa"). Destaque não foi reescrito — continua lendo a mesma regra canônica (`ManufacturingRules.cut_releases_highlight`).

**Testes:** 24 testes backend (20 casos pedidos + seleção de plano + linhas legadas) + 9 testes frontend; regressão verde em Corte, Destaque, SigmaNEST, sincronização automática.

**Pendências registradas, sem ação necessária:**
- Linhas antigas do catálogo sem "programa" aparecem em "OPs sem plano identificado" até a próxima sincronização do SigmaNEST — comportamento deliberado (não adivinhar atribuição). **Usuário: ok, aceito.**
- Avanço automático de nesting ao finalizar pode pular para outro plano em vez do corrente — comportamento pré-existente, fora do escopo da wave. **Usuário: ok, aceito.**

---

## Wave 6D — Visão gerencial de Solda + TV

**Objetivo:** nova tela gerencial (PCP/Liderança/Supervisão/Diretoria) mostrando OPs de conjuntos soldados por estação, com status A VENCER/ATRASADA/FINALIZADA, e ciclo automático da TV alternando Andon ↔ Solda a cada 10 segundos.

**Bloqueio inicial (investigação parou antes de inventar dado):**
1. Campo "MODELO MAQUI" do TOTVS sem lastro em nenhum valor real no ambiente de TESTE.
2. Sem caminho de ingestão automática (integração é só outbound).
3. Estações de Solda sem mapeamento determinístico no cadastro corporativo (todas caem no mesmo recurso `SOLDA4`).

**Decisões do usuário que destravaram a wave:**
1. Campo confirmado: `B1_ZMODELO` (coluna customizada da empresa).
2. Ingestão automática fica para análise futura — implementar a tela agora com "Modelo não identificado." até lá.
3. Estação não precisa de mapeamento — "as estações de solda vão pegar a OP e fazer" — passou a refletir o dado real observado em `apontamentos_operacionais.maquina`.

**Resultado:** tela `/welding-management`, colunas ESTAÇÃO/OP/PRODUTO/MÁQUINA/MODELO/DATA/STATUS, com textos humanos de ausência quando não houver dado (nunca `null`/técnico). TV alterna Andon↔Solda a cada 10s via `useTvRotation`, só para o perfil dedicado (`role === "andon"`); gestor não sofre a rotação. Andon homologado permaneceu intacto (testes + validação visual).

**Testes:** 32 testes backend + 18 frontend, incluindo o ciclo da TV medido por tempo real (sem clique); suíte web 149 verdes; build limpo. Validação cruzada com dados reais de TEST (33 OPs de Solda, 6 estações, 25 finalizadas / 8 a vencer).

**Nova pendência descoberta e registrada (decisão de negócio em aberto):** a ingestão de `ProductionOrder` do TOTVS não alimenta `data_emissao` nem `prazo_entrega` — só datas planejadas internas. Hoje o status usa `fim_planejado` como aproximação e sinaliza a limitação como dado parcial. Se a PCP quiser um prazo de entrega próprio na integração, é decisão de negócio nova, ainda **não resolvida**.

---

## Wave 6E — Pausas, Crachás e apresentação (UI/IA)

**Objetivo:** filtros úteis em Pausas e Crachás, e uma camada central de humanização para eliminar qualquer estado técnico cru (`sem_registros`, `dados_insuficientes`, `not_configured`, `partial` etc.) da interface e da IA, sem alterar backend nem o mecanismo da IA.

**Resultado:**
- Pausas: filtros `Setor / Tipo de pausa / Buscar`.
- Crachás: filtros `Situação / Perfil / Origem do cadastro / Buscar`. Filtro por Setor **não implementado** — crachá é global hoje (sem setor no cadastro). **Usuário confirmou: manter crachá global, sem esse filtro.**
- Camada central `web/src/utils/systemState.ts` (`humanizeSystemState` e variantes) aplicada em `EmptyState`, `DataTable`, `MetricCard`, `StatusBadge`, Visão Geral, Produção, Relatórios, Análises, Auditoria — sem espalhar `if status == "..."` pelo código.
- IA: mecanismo (provider, streaming, tool calling, persistência) intocado; apenas a apresentação da resposta passou a traduzir estado técnico citado e remover rastros de exceção/SQL/nome de tabela.
- Bug visual pré-existente corrigido de brinde: botão "Salvar" branco sobre branco no formulário de pausa/crachá.

**Testes:** 35 testes novos; suíte web 131/131; `tests/test_web_api.py` 44 OK; `tests/test_ai.py` 41 OK; build limpo. Validação visual em 14 rotas sem nenhum identificador técnico vazado.

---

## Correção adicional: falha de teste pré-existente

`test_execucao_nao_conhece_a_origem_totvs` falhava por um comentário mencionando "TOTVS" em `mes/domain/manufacturing_rules.py:32`, deixado pela própria Wave 6A. Reescrito para "sistema corporativo", preservando o significado. Teste e suíte relacionada (`Etapa3FronteiraCanonicaTests`, 10 testes) voltaram a passar. **Usuário: corrigir — feito.**

---

## Pendências que restam em aberto

Das 7 pendências levantadas ao final das waves, **6 foram resolvidas** por decisão do usuário nesta sessão. Fica em aberto apenas uma, descoberta durante a própria Wave 6D:

- **Origem do prazo de entrega da OP de Solda**: a integração TOTVS não traz `data_emissao`/`prazo_entrega` reais; o status "A VENCER" hoje usa `fim_planejado` como aproximação, sinalizado como dado parcial na tela. Requer decisão da PCP/Engenharia sobre se um prazo de entrega próprio deve ser adicionado à integração — fica para uma wave futura.

Também seguem registradas como trabalho futuro (sem bloquear nada hoje):
- Ingestão automática do campo MODELO (Wave 6D) — coluna já existe (`catalogo_pcp_ops.produto_modelo`), mecanismo de carga ainda não.
- Reconstrução dos scripts de simulação de fábrica (excluídos na Wave 6B) — nova versão planejada para o final do projeto.

---

## Resumo de testes por wave

| Wave | Testes backend novos | Testes frontend novos | Regressão |
|---|---|---|---|
| 6A | 25 | — | Verde |
| 6B | 35 | 4 (+87/87 total) | Verde (129 rápidos + 105 Postgres) |
| 6C | 24 | 9 (96/96 total) | Verde |
| 6D | 32 | 18 (149 verdes total) | Verde, Andon intacto |
| 6E | — | 35 (131/131 total) | Verde |

Nenhuma regressão remanescente conhecida ao final da Wave 6.
