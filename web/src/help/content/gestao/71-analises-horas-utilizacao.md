---
titulo: Análises - Horas e Utilização
grupo: Análises
ordem: 71
rotas: /analises/horas-utilizacao
---

A tela **Análises — Horas & Utilização** mostra quanto tempo as máquinas ficaram registradas e como esse tempo se divide. Texto da tela: "Tempo registrado consolidado, sem multiplicar a máquina por OPs simultâneas, e o Tempo MES por categoria, setor e recurso."

Usa a barra de filtros do topo. Veja [Filtros globais](topico:04-filtros-globais).

## Parte de cima: cartões

| Cartão | Significado |
|---|---|
| Tempo registrado | Tempo físico real das máquinas, contado uma vez só. |
| Tempo atribuído bruto | Soma do tempo de todas as OPs. Se duas OPs rodam juntas na mesma máquina, o tempo conta duas vezes aqui. |
| Sobreposição removida | A diferença entre os dois acima: o tempo que seria contado em dobro. |
| Utilização | Quanto do tempo disponível virou trabalho. Se faltar capacidade ou calendário validado: "Requer capacidade e calendário validados". |

Exemplo: uma máquina trabalhou 1 h com 2 OPs ao mesmo tempo. Tempo registrado = 1 h. Atribuído bruto = 2 h. Sobreposição removida = 1 h.

## Produção por recurso e Resumo por setor

- **Produção por recurso**: barras com os 12 recursos que mais produziram.
- **Resumo por setor**: tabela com Setor, Produção, Setup e Paradas.

## Tempo MES por categoria, setor e recurso

Seção no fim da tela.

| Cartão | Significado |
|---|---|
| Tempo produtivo | Produção mais setup. |
| Parada não planejada | Paradas fora do plano. |
| Parada planejada | Paradas previstas. |
| Tempo total medido | Soma de todas as categorias. |
| Tempo a esclarecer | Tempo em que o mesmo recurso teve estados incompatíveis ao mesmo tempo. Sem conflito: "Sem conflito no período". |

Quando há mais de um recurso, os cartões mostram a **média por recurso** e o detalhe mostra o **total** (por exemplo, 35 recursos parados 1 h = 35 h no total; média 1 h). A categoria **Fora do turno** é do calendário, não da máquina: não é somada nem dividida.

A tabela **Categorias de tempo** traz "Média por recurso" e "Tempo total". Valores clicáveis abrem a conta. O gráfico **Produção por setor** mostra as horas de produção de cada setor.

## Problemas comuns

| Situação | O que fazer |
|---|---|
| Utilização pede "capacidade e calendário validados" | Falta calendário/turno cadastrado; confirmar com a liderança. |
| "Atualização temporariamente indisponível" | Os dados podem estar atrasados; aguarde e recarregue. |
| Tempo a esclarecer maior que zero | Há estados em conflito no mesmo recurso; conferir os apontamentos. |

Veja também: [Análises — OEE](topico:70-analises-oee) e [Capacidade e gargalos](topico:76-analises-capacidade-gargalos).
