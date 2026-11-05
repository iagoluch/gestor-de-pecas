---
titulo: Análises - OEE
grupo: Análises
ordem: 70
rotas: /analises/oee
---

A tela **Análises — OEE** mostra a eficiência da fábrica no período: quanto do tempo virou peça boa. Texto da tela: "Disponibilidade × Performance × FTT do período selecionado."

Usa a barra de filtros do topo (período, setor, recurso). Veja [Filtros globais](topico:04-filtros-globais). As contas são as mesmas da [Visão geral](topico:10-visao-geral).

## Cartões

| Cartão | O que significa | Conta em palavras |
|---|---|---|
| OEE | Eficiência geral. | Disponibilidade × Performance × FTT. |
| Disponibilidade | Quanto do tempo disponível a máquina trabalhou. | Tempo trabalhado ÷ tempo disponível. O tempo disponível é o trabalhado mais as paradas (e o tempo sem classificação). Fora de turno, fila e sem demanda não entram. |
| Performance | Se o ritmo bateu com o tempo padrão. | (Tempo padrão das peças boas + apoio) ÷ tempo trabalhado. "Apoio" é o tempo de setup, retrabalho e atividade sem OP. |
| FTT / Qualidade | Peças boas de primeira. | Boas ÷ (boas + refugo + retrabalho). |
| AE | "Produtivo líquido sobre tempo disponível." | (Tempo padrão das peças boas + apoio) ÷ tempo disponível. |
| Produtividade | "Produtivo bruto sobre tempo operacional." | Tempo em Produção (sem setup, retrabalho nem atividade sem OP) ÷ tempo operacional. |
| Utilização | "Tempo trabalhado sobre tempo operacional." | Trabalhado ÷ operacional. O tempo operacional é o mesmo tempo disponível; por isso, hoje a Utilização dá o mesmo número da Disponibilidade. |

Os números são clicáveis (quando há valor): abre um painel com a conta aberta.

### Exemplo simples

Máquina disponível 8 h, trabalhou 6 h: Disponibilidade = 6 ÷ 8 = 75%. As peças boas tinham 5 h de tempo padrão: Performance = 5 ÷ 6 = 83%. De 100 peças, 90 saíram boas: FTT = 90%. OEE = 0,75 × 0,83 × 0,90 = 56%.

## Evolução do OEE

Gráfico de linha com a evolução no tempo. Passe o mouse em um ponto para ver período, OEE, Disponibilidade, Performance e FTT. Precisa de pelo menos 2 pontos; senão aparece "Dados insuficientes".

## Onde o OEE está sendo perdido

Mostra a perda de cada componente: **100 menos o valor**, em "p.p. de perda no período" (pontos percentuais). Exemplo: Disponibilidade 75% = 25 p.p. de perda. O maior mostra onde atacar primeiro.

Mensagens: "Sem perda registrada no período." e "Sem dado suficiente no período."

## Perdas por motivo

Quebra em: Fora de turno, Parada planejada, Parada não planejada, Ritmo (performance), Refugo e Retrabalho. Os quatro primeiros aparecem em tempo (horas e minutos); Refugo e Retrabalho em peças. "Ritmo" é a diferença entre o tempo padrão das peças e o tempo trabalhado.

## Período sem demanda

Se o período inteiro foi "sem demanda" (recurso sem serviço, sem produção), a regra da empresa é: Disponibilidade 100%, Performance 0% e OEE 0%. O FTT fica "não se aplica".

## Quando não há número

"Dados insuficientes" ou outro estado no lugar do valor significa que falta dado para calcular. A tela não inventa número. O sistema não mostra meta de OEE nesta tela. Se a empresa tem uma meta, confirmar com a liderança.

## Problemas comuns

| Situação | O que fazer |
|---|---|
| Cartão com "Dados insuficientes" | Aumente o período ou confira se houve apontamento. |
| Gráfico sem linha | Escolha um período com ao menos 2 pontos. |
| Performance acima de 100% | As peças saíram mais rápido que o tempo padrão; vale revisar o padrão. |

Veja também: [Horas e utilização](topico:71-analises-horas-utilizacao) e [Paradas](topico:72-analises-paradas).
