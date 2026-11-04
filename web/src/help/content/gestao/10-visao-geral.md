---
titulo: Visão Geral
grupo: Início
ordem: 10
rotas: /inicio/visao-geral
---

A **Visão Geral** é a primeira tela da gestão. Ela junta, em cartões e gráficos, como a fábrica está indo no período escolhido. Qualquer conta da gestão abre esta tela.

O endereço antigo "Setores" da tela inicial leva para cá. Para mudar quais cartões aparecem e onde, veja [Personalizar a Visão Geral](topico:11-personalizar-visao-geral).

## Filtros

A tela usa a barra de filtros comum: período, setor e demais campos. Veja [Filtros](topico:04-filtros-globais). O padrão é o dia de hoje.

## Cartões e gráficos (blocos)

Cada bloco é independente. Se um falhar, os outros continuam.

| Bloco | O que mostra |
|---|---|
| Produção boa | Quantidade de peças boas no período. |
| OEE | Eficiência geral: Disponibilidade × Performance × FTT. |
| Disponibilidade | Quanto do tempo disponível foi trabalhado. |
| Performance | Ritmo de trabalho em relação ao tempo padrão. |
| FTT | Peças boas de primeira. |
| Simulação | Bloco de simulação (o que ele projeta exatamente: confirmar com a liderança). |
| Planejado × Realizado | Compara o que foi planejado com o que foi feito. |
| Exceções | Situações fora do normal que precisam de atenção. |
| Composição do tempo | Barra com para onde o tempo foi (veja abaixo). |
| Principais perdas | As maiores causas de perda de tempo. |
| Eventos ao vivo | Últimos acontecimentos no chão de fábrica. |
| Tabela de setores | Uma linha por setor com os indicadores. |
| Principais recursos | Máquinas e postos que mais pesam no resultado. |
| Inconsistências de auditoria | Problemas de registro que pedem conferência. |
| Chamadas | Chamadas recentes da gestão. |
| Metas | Atalho da tela de [Metas](topico:12-metas). |
| Andon | Resumo do painel Andon. |

Os blocos **Chamadas**, **Metas** e **Andon** vêm **ocultos** por padrão. Você os liga na personalização.

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

A barra divide o tempo em: **Produção, Setup, Parada não planejada, Parada planejada, A esclarecer, Retrabalho, Atividade sem OP, Recurso sem demanda e Fora do turno**. Ficam **fora do total**: Parada planejada, A esclarecer e Fora do turno.

## Estados dos números

Quando um cartão não tem número confiável, ele mostra uma frase no lugar. As frases estão no [Glossário](topico:05-glossario). Exemplo: "Ainda não há dados suficientes para este indicador."

## De onde vem este número

Cada indicador tem um painel de explicação. Ele mostra a fórmula e os valores usados. Use quando alguém questionar um número.

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
| Um bloco sumiu | Foi ocultado na personalização. | Use **Restaurar padrão**. |
| Zeros em tudo | Filtro restringindo demais, ou dia sem apontamento. | Clique em **Limpar**. |
