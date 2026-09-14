# Fluxo de telas do operador por setor

**Atualizado em:** 27/08/2026

## Fonte de planejamento

No fluxo integrado, OP, produto, quantidade planejada e roteiro chegam do
TOTVS/Protheus por `ProductionOrder` e são projetados pelo backend. Dados
fictícios continuam úteis para testes automatizados/visuais, mas não são fonte
de verdade do fluxo corporativo.

A primeira OP real homologada no banco TESTE oficial é `A9716901001`.
Duas de suas cinco atividades possuem projeção operacional segura:

```text
10 → CORTE     → PLASMA → Corte
20 → USINAGEM  → CNC-01 → Usinagem
```

`IMPRESSAO OP/PCP` é etapa automática já satisfeita, `INSPECAO/INSPEC` é
Qualidade **Em manutenção** e `FINALIZADA/ALMOX4` é marco terminal. As três
permanecem auditáveis no XML/inbox e não viram tarefa do operador.

Desde a Etapa 3 (27/08/2026), a projeção derivada do TOTVS entra diretamente na
fila canônica: `catalogo_operacoes_op` → `listar_proximas_operacoes_roteiro` →
`OperatorFlowService.listar_cartoes` → `/api/v1/operator/workbench`. A origem da
OP é invisível para o operador; a tela não exibe nenhuma marca corporativa.

Para o setor de Corte, a OP e a operação vêm do TOTVS, mas tarefa, plano e
nesting vêm do SigmaNEST. O Qlik foi removido da arquitetura alvo e a leitura
direta do banco SigmaNEST é pendência registrada em
`docs/INTEGRACAO_CORTE_SIGMANEST.md`. Uma OP TOTVS cuja rota começa no
Corte aguarda corretamente o planejamento de nesting; isso é sequência, não
defeito, e não deve ser contornado.

## Perfis e rotas

| Perfil | Rota operacional | Entrada do posto |
|---|---|---|
| `operador_destaque` | Destaque | Tela de apontamento |
| `operador_dobra` | Dobra | Seleção do recurso e apontamento |
| `operador_usinagem` | Usinagem | Seleção do recurso e apontamento |
| `operador_serra` | Serra | Seleção do recurso e apontamento |
| `operador_corte` | Corte | Seleção Laser/Plasma e fila |
| `operador_pintura` | Pintura | Tela de apontamento |
| `operador_solda` | Solda | Seleção da estação e apontamento |
| `operador_montagem` | Montagem | Seleção do recurso e apontamento |

Para esses perfis não devem aparecer módulos gerenciais fora de sua autorização.

`Montagem` existe estruturalmente desde a Etapa 3 e segue a mesma filosofia de
Pintura e Solda: recurso com pertencimento canônico é apontável pelo próprio
setor, com início, execução e fim. O cadastro oficial ainda não possui recurso
com `tipo_setor='Montagem'`, portanto o setor entra sem posto e a tela exibe um
empty state explícito. Nome semelhante não autoriza projeção.

## Sequência funcional alvo

```text
Login / identificação
  → recurso/estação, quando aplicável
  → fila de OPs compatíveis com o posto
  → OP originada do planejamento TOTVS
  → roteiro completo
  → operação correspondente ao setor/recurso
  → Iniciar (livre, inclusive na Caldeiraria)
  → produção da primeira peça
  → (Dobra, Usinagem e Serra) Finalizar é recusado até a primeira peça
      → botão Setup: aponta a preparação da máquina e abre o checklist
          → cotas medidas
          → primeira peça aprovada pelo sistema
          → lote liberado; a OP retoma a produção sozinha
  → Produção / Parada / Setup / Retrabalho
  → finalização com quantidade e identificação
  → histórico/rastreabilidade
```

O frontend não deve inferir roteiro ou compatibilidade. A API/backend entrega a
projeção canônica.

### Portão Setup/Qualidade da primeira peça (Wave 6B, 11/09/2026)

A primeira peça continua existindo como conceito de negócio, mas **deixou de ser
uma etapa visível da tela**: não há card de "Primeira peça" nem aba "Qualidade"
no posto. O botão **Setup permanece** onde o setor possui Setup: ele aponta o
tempo de preparação da máquina, que é quando a primeira peça é fabricada, e é
ele — e só ele — que registra o Setup do portão. O popup não pede essa
confirmação de novo.

- **Escopo**: somente Dobra, Usinagem e Serra (`app/core/quality.py`). Solda,
  Pintura, Corte e Destaque seguem o fluxo que já tinham.
- **Iniciar é livre.** Produzir nunca é bloqueado pelo portão.
- **Entrada do portão**: o `Finalizar` é recusado com
  `primeira_peca_gate_obrigatorio` enquanto a primeira peça não estiver
  aprovada, e a mensagem manda apontar o Setup. Quem abre o checklist é o botão
  `Setup`: ele aponta o estado de preparação da máquina e, no mesmo clique,
  apresenta as cotas.
- **Depois da aprovação**: a OP retorna à produção automaticamente (a transição
  `Retornar` do posto, disparada pela tela) e o restante do lote segue o
  apontamento normal do setor — um Início, um Finalizar com as quantidades.
- **Checklist**: as cotas são o template do produto já usado pela inspeção
  dimensional, com referência, margem e limites calculados pelo backend. Produto
  sem cotas abre o cadastro existente dentro do próprio popup.
- **Decisão**: o operador informa apenas a medida. O sistema calcula
  `limite_inferior = referencia - margem` e `limite_superior = referencia + margem`
  e aprova quando toda medida está dentro da faixa, limites inclusive.
- **Fechar ou cancelar o popup não envia nada e nunca libera a OP.**
- **Reprovada**: a peça vai para retrabalho (bloqueia a OP até o crachá do
  responsável designado) ou para refugo (consome saldo e exige outra primeira
  peça). **As duas decisões exigem o crachá do responsável**: o retrabalho é
  desbloqueado por ele e o refugo é autorizado por ele antes do descarte. O
  refugo informado na finalização da operação segue a mesma exigência. Não
  existe login para o responsável.
- **Aprovada**: o retorno é pontual — "Primeira peça aprovada. Lote liberado
  para produção." — e a produção recomeça sozinha.
- Retrabalho **depois** do lote liberado continua sendo o fluxo normal com
  alerta interno; ele não vira bloqueio de primeira peça.
- **Histórico**: o que o posto registrou (Setup, cotas medidas, resultado e
  autorizações por crachá) é consultado na gestão, em `Análises → Qualidade`.

## Máquina de estados canônica

```text
Fila -> Produção | Parada | Setup | Retrabalho
Produção -> Parada | Setup | Retrabalho | Finalizado
Parada -> Produção | Retrabalho | Finalizado
Setup -> Produção | Retrabalho | Finalizado
Retrabalho -> Parada | Setup | Finalizado
Finalizado -> estado terminal
```

Parada e Setup preservam `estado_retorno` quando interrompem Produção ou
Retrabalho. `Retomar`/`Retornar` recupera a atividade anterior. A transição
direta `Retrabalho → Produção/Início` continua bloqueada.

## Regras mínimas de apontamento

- entrada em Produção, Parada, Setup ou Retrabalho exige OP, operação e recurso;
- operação/recurso devem vir do contexto canônico do backend;
- parada exige motivo; comentário é opcional;
- finalização registra peças boas, refugo e identificação do operador;
- refugo e retrabalho não são somados silenciosamente às peças boas;
- fim de turno segue as regras canônicas de interrupção automática;
- Corte preserva tarefa/nesting e tempo próprio de cada nesting;
- Solda preserva exclusividade de estação;
- histórico produtivo não é reescrito para esconder inconsistência.

## Próxima homologação operacional

Depois de fechar a matriz de mapeamento TOTVS, usar uma OP real para provar:

```text
TOTVS
→ ProductionOrder
→ catalogo_pcp_ops / catalogo_operacoes_op
→ fila do recurso correto
→ operador
→ evento produtivo
→ histórico
```

Caso inicial recomendado: `A9716901001` no `PLASMA`, validando primeiro se o
roteiro recebido e o estado da OP realmente autorizam sua exibição/execução.
Não forçar a OP na UI apenas para o teste.

A cadeia acima já está coberta por teste determinístico em
`tests/test_totvs_operator_queue.py`, incluindo o encadeamento
Corte → Usinagem e o ciclo completo de apontamento sobre a OP TOTVS.

## Banco TESTE

O banco TESTE oficial é:

```text
gestor_pecas_test
```

`TEST_DATABASE_URL` deve apontar explicitamente para esse ambiente no checkout
`Gestor de Peças - Area de Testes`.

Os antigos bancos `*_simulacao_*`, `*_homolog_*`, `*_residencia_*` e
`seed_test` foram removidos do servidor após dump verificado. Não devem ser
recriados automaticamente por documentação ou teste comum.

Seeders de simulação histórica exigem alvo explícito e não devem ser executados
contra `gestor_pecas_test` por padrão.

## Dados fictícios

Fixtures e cargas fictícias permanecem válidas para teste de UI, regra,
regressão e cenários difíceis. Elas devem ser claramente identificadas como
fictícias e nunca usadas como prova de integração TOTVS real.

A prioridade corrente do projeto é substituir progressivamente a dependência de
massa fictícia na homologação funcional por OPs e eventos controlados que
nasceram no TOTVS TESTE.

## Critério de conclusão desta etapa

A etapa operacional estará pronta para avançar quando:

1. uma OP real TOTVS aparecer somente nos postos compatíveis;
2. o operador executar o ciclo permitido sem bypass de regra;
3. todos os eventos/timestamps/quantidades ficarem auditáveis;
4. o mesmo conjunto de eventos alimentar gestão/Andon/KPIs;
5. nenhum teste exigir banco histórico manualmente semeado para provar regra
   básica.

A sequência completa está em `ROADMAP.md`.
