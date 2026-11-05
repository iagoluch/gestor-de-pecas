---
titulo: Visão Geral
grupo: Início
ordem: 10
rotas: /inicio/visao-geral
---

A **Visão Geral** é a primeira tela da gestão. O título é "Tela inicial — Visão Geral" e a frase embaixo é "Como estamos, onde estamos perdendo e onde agir primeiro." Qualquer conta da gestão abre esta tela.

O endereço antigo "Setores" da tela inicial leva para cá. Para mudar quais blocos aparecem e onde, veja [Personalizar a Visão Geral](topico:11-personalizar-visao-geral).

## Filtros

A tela usa a barra de filtros comum: período, setor e demais campos. Veja [Filtros](topico:04-filtros-globais). O padrão é o dia de hoje.

## Blocos da tela

Cada bloco é independente. Se um falhar, os outros continuam. Os nomes abaixo são os que aparecem na tela.

| Bloco | O que mostra | Ao clicar |
|---|---|---|
| Produção boa | Peças boas no período. Refugo e retrabalho ficam separados. Mostra a variação contra o período anterior (some se o período ainda está em andamento). | O número abre a explicação. |
| OEE, Disponibilidade, Performance, FTT / Qualidade | Quatro cartões com o valor, a variação em pontos percentuais e um gráfico pequeno. Mostram "Sem meta definida" quando não há meta. | Botão **Entender** abre a explicação. |
| Simulação | Seis cartões: Planejado, Realizado, Atingimento, Utilização, Produtividade e AE. Só aparece quando o servidor devolve esses dados. | Explicação do número. |
| Planejado × realizado — acumulado | Gráfico de Realizado e Planejado, e o resumo Quantidade planejada, Quantidade boa realizada e Diferença. | Abre Produção, aba Planejado × Realizado. |
| O que precisa de atenção | Até 4 exceções, com contador "N exceções" e botão **Ver evidências**. Sem nada: "Nenhuma exceção identificada". | Leva a Tempo padrão, OEE ou Paradas & Setup, conforme o caso. |
| Composição do tempo | Média por recurso em destaque e o texto "total X somado de N máquinas". Itens fora do total aparecem como "não somado". | Abre Horas & Utilização. Clicar num item abre "de onde vem". |
| Maiores perdas | Até 4 maiores perdas de tempo. | Abre Paradas & Setup. |
| Agora na fábrica | Até 8 eventos recentes, com "há N min/h/d". Sem nada: "Sem eventos recentes". | Nada. |
| Setores — leitura rápida e execução real | Cartões de destaque e uma tabela (veja abaixo). | O nome do setor abre Consulta Operacional, aba Recursos, naquele setor. |
| Recursos com maior impacto | Até 4 máquinas ou postos que mais pesam. | Abre Paradas & Setup filtrado pelo recurso. |
| Inconsistências de dados | Até 4 problemas de registro. Sem nada: "Sem inconsistências abertas". | Abre Auditoria, aba Alertas e inconsistências. |
| Chamadas da gestão | Até 4 chamadas recentes e a contagem. Sem nada: "Nenhuma chamada registrada". | Abre [Chamadas](topico:15-chamadas). |
| Metas e atingimento | Planejado, realizado e atingimento. Sem meta: "Sem meta definida". | Abre Análises, aba OEE. |
| Alertas ao vivo | Contadores Produzindo, Em parada, Sem demanda e Fora de turno, e até 4 paradas atuais. | Abre o painel Andon. |

Os blocos **Chamadas da gestão**, **Metas e atingimento** e **Alertas ao vivo** vêm **ocultos** por padrão. Você os liga na personalização.

Se a conta não pode ver o Andon, o bloco Alertas ao vivo mostra: "O Andon não está disponível para esta conta ou o painel não respondeu."

### Tabela de setores

Colunas: Setor, OEE, Recursos produzindo (formato "N de M"), Produção boa, Refugo, Retrabalho, OPs, Tempo produtivo, Produção, Setup, Paradas e Tendência. OEE, Recursos produzindo e Tendência só aparecem quando há dados para isso. No Corte, a coluna OPs mostra "—", porque lá a contagem é por plano cortado (veja [Dobra e Corte](topico:36-area-dobra-e-corte)).

## De onde vêm os números

| Indicador | Fórmula |
|---|---|
| Disponibilidade | tempo trabalhado ÷ tempo disponível × 100 |
| Performance | (tempo padrão das peças boas + apoio) ÷ tempo trabalhado × 100 |
| FTT | boas ÷ (boas + refugo + retrabalho) × 100 |
| OEE | Disponibilidade × Performance × FTT, calculado com as somas do período (não com a média das médias) |
| Produtividade | tempo em Produção ÷ tempo operacional |
| Utilização | tempo trabalhado ÷ tempo operacional |

Palavras como "apoio" e "tempo padrão" estão no [Glossário](topico:05-glossario).

### Composição do tempo

A barra divide o tempo em: **Produção, Setup, Parada não planejada, Parada planejada, A esclarecer, Retrabalho, Atividade sem OP, Recurso sem demanda e Fora do turno**. Ficam **fora do total**: Parada planejada, A esclarecer e Fora do turno. Esse bloco só atualiza na virada do minuto.

## Estados dos números

Quando um cartão não tem número confiável, ele mostra uma frase no lugar. As frases estão no [Glossário](topico:05-glossario).

## De onde vem este número

Os números clicáveis (e o botão **Entender**) abrem um painel de explicação com a fórmula e os valores usados. Use quando alguém questionar um número.

## Quem vê

Todos os níveis da gestão. Contas presas a um setor veem só os dados dele.

## Relacionados

- O endereço antigo "Alertas" da tela inicial abre a aba "Alertas e inconsistências", em Auditoria.
- "Andon" e "Mapa da fábrica" abrem os painéis próprios (veja [O topo e o menu lateral](topico:03-menu-e-topo)).

## Problemas comuns

| O que aparece | O que significa | O que fazer |
|---|---|---|
| "Atualização temporariamente indisponível. Os dados exibidos podem estar desatualizados." | O servidor não respondeu na última tentativa. | Aguarde ou recarregue. |
| Cartão com frase em vez de número | Dados insuficientes, parciais ou inconsistentes. | Veja a frase no [Glossário](topico:05-glossario). |
| "Nenhum bloco visível na tela inicial" | Todos os blocos foram ocultados. | Clique em **Personalizar** e mostre algum, ou use **Restaurar padrão**. |
| Um bloco sumiu | Foi ocultado na personalização. | **Personalizar**, depois **Restaurar padrão**. |
| Zeros em tudo | Filtro restringindo demais, ou dia sem apontamento. | Clique em **Limpar**. |
