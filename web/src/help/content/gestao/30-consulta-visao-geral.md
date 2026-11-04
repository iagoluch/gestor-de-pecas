---
titulo: Consulta Operacional - Visão Geral
grupo: Consulta operacional
ordem: 30
rotas: /consulta-operacional/visao-geral
---

Tela **Consulta Operacional — Visão Geral**. Frase de apresentação: "Situação física atual dos recursos e OPs associadas no dia corrente, com atualização incremental."

Ela responde: **o que cada máquina e posto está fazendo agora?**

## Como a tela se comporta

- Mostra sempre o **dia corrente inteiro**. Não há período nem filtros globais.
- O único filtro é o seletor **Setor**, dentro do bloco "Recursos por estado".
- A tela se atualiza sozinha. No topo aparece um indicador:

| Indicador | Significado |
|---|---|
| Atualização ao vivo (ponto verde) | A tela está recebendo mudanças em tempo real. |
| Reconectando atualizações | A conexão caiu. A tela tenta voltar sozinha. Os números podem estar um pouco atrasados. |

## Cartões do topo

Clique no número de um cartão para abrir o painel "de onde vem este número" (veja [Filtros globais](topico:04-filtros-globais) e o [Glossário](topico:05-glossario)).

| Cartão | O que mostra | De onde vem | Cor |
|---|---|---|---|
| Em produção agora | "X de Y". X = recursos em produção. Y = total de recursos listados. Detalhe: "Recursos com estado produtivo". | Cada recurso vale 1. Conta os que estão no estado Produção. | Verde |
| OPs em execução | Quantidade de OPs ativas agora. | Soma das OPs ativas de cada recurso. | Azul |
| Recursos parados | Quantidade de recursos em parada (planejada ou não). | Conta os recursos no estado Parada. | Vermelho se houver parada, com o detalhe "Exigem ação imediata". Verde com "Nenhuma parada aberta". |
| Maior parada aberta | Tempo da parada mais longa no formato HH:MM:SS. Detalhe: "Recurso — motivo" (ou "motivo não informado"). | A maior duração entre os recursos parados. | Amarelo se há parada. Verde com "Nenhuma" se não há. |

Se o cartão e a lista de recursos não baterem, o painel avisa: "O cartão mostra N, mas as linhas carregadas somam M: o resumo do servidor e a lista foram lidos em momentos diferentes." Isso some quando a tela atualiza.

## Bloco "Recursos por estado"

1. Se houver mais de um setor, aparece o seletor **Setor**. Os setores vêm em ordem alfabética. O padrão é o primeiro da lista. Recurso sem setor cai em "Setor não informado".
2. Abaixo do seletor aparece um cartão por recurso do setor escolhido.
3. Sem recursos no setor, aparece uma mensagem de lista vazia.

### Cartão de recurso

| Campo | O que mostra |
|---|---|
| Nome e setor | O recurso físico e o setor dele. |
| Etiqueta de estado | O estado agora. Veja as cores abaixo. |
| OP | Número da OP. Clique para abrir a rastreabilidade da OP. |
| Operação | A operação em andamento. |
| Produto | O produto da OP. |
| Operador | Quem iniciou o apontamento. |
| Início | Quando o estado atual começou. |
| Duração | Há quanto tempo, em HH:MM:SS. |
| Estado atual | Aparece só quando a parada inteira é pelo menos 1 minuto maior que o trecho atual. Exemplo: parado desde 08:00 e agora no almoço. Mostra "HH:MM:SS desde data". |
| Motivo | O texto do motivo (parada, plano de corte, etc.). |

Campo sem informação mostra "Não disponível".

### Cores da etiqueta de estado

| Cor | Estados |
|---|---|
| Verde | Produção, normal, ok. |
| Vermelho | Parada, crítico, atrasado. |
| Amarelo | Setup, atenção, alerta. |
| Azul | Em processo, executando, informação. |
| Cinza | Os demais (fila, fora de turno, sem demanda, desconhecido). |

## Quais recursos aparecem

- Só **postos em que algum operador aponta**. Máquina que ninguém aponta não entra.
- Recurso sem demanda aparece como "fila" com o motivo "Recurso sem demanda".
- Recurso sem estado registrado aparece como "desconhecido" com o motivo "Estado físico canônico ainda não registrado para este recurso."
- Recurso do Corte que está cortando mostra o motivo "Plano" seguido do programa.
- A duração da parada é contínua: fila e parada juntas, em janela de até 36 horas, até o estado atual.

## Quem vê

Qualquer conta da gestão. Contas de líder ou supervisor presas a um setor veem só os dados do próprio setor (o filtro é feito no servidor).

## Problemas comuns

| O que aparece | O que significa | O que fazer |
|---|---|---|
| Reconectando atualizações | A conexão ao vivo caiu. | Aguarde. Se persistir, recarregue a página (F5). |
| Há telas demais acompanhando a operação ao vivo. Feche uma aba e tente de novo. | Há muitas abas abertas na mesma conta. | Feche abas da Visão Geral que não usa. |
| Atualização temporariamente indisponível. | O servidor não conseguiu montar a atualização. | Aguarde e recarregue a página. |
| Recurso "desconhecido" | Ainda não há estado registrado. | Confirmar com a liderança se o posto está ativo. |
| Tela de erro com botão de tentar de novo | A carga inicial falhou. | Clique em tentar de novo. |

## Veja também

- [Recursos](topico:31-consulta-recursos) (mesma informação em tabela, com filtros).
- [OPs em andamento](topico:32-consulta-ops-em-andamento).
- A aba antiga "Tempo MES" foi movida: o endereço `/consulta-operacional/tempo-mes` leva para Análises, Horas e Utilização.
