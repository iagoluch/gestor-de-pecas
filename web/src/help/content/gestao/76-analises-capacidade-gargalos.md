---
titulo: Análises - Capacidade e Gargalos
grupo: Análises
ordem: 76
rotas: /analises/capacidade-gargalos
---

A tela **Análises — Capacidade** mostra quanto do tempo disponível virou trabalho e onde está o gargalo (a máquina mais pressionada). Texto da tela: "Quanto do tempo disponível pelo calendário produtivo virou trabalho, e onde está o gargalo."

É medida em **tempo**, não em peças. Capacidade em peças não é publicada, porque exigiria tempo padrão confiável de todas as operações.

Usa a barra de filtros do topo. Veja [Filtros globais](topico:04-filtros-globais).

## Como a conta é feita

Para cada recurso:

1. **Tempo disponível** = horas do calendário/turno no período. Recurso sem calendário próprio usa o expediente da aba Turnos.
2. **Tempo ocupado** = produção + setup + retrabalho (tempo físico real).
3. **Livre** = disponível − ocupado (nunca negativo).
4. **Utilização** = ocupado ÷ disponível.

Exemplo: 160 h disponíveis, 120 h ocupadas. Livre = 40 h. Utilização = 75%.

Gargalo: o recurso de maior utilização (em empate, o de maior fila).

## Cartões

| Cartão | Significado |
|---|---|
| Utilização do período | Ocupado ÷ disponível, de todos os recursos com calendário. |
| Tempo disponível | Soma dos recursos com calendário. Detalhe: média por recurso e quantos estão sem calendário. Clicável. |
| Capacidade livre | Soma do tempo livre. Detalhe: horas já ocupadas. Clicável. |
| Gargalo | Nome do recurso mais pressionado e sua utilização. "Não determinado" sem calendário. |

Sem calendário/turno cadastrado, aparece "Não configurado" e o motivo.

## Tabela "Utilização por recurso"

| Coluna | Significado |
|---|---|
| Recurso / Setor | Máquina e setor. |
| Tempo disponível | Horas do calendário. |
| Tempo ocupado | Horas trabalhadas. |
| Livre | O que sobrou. |
| Utilização | Ocupado ÷ disponível. |
| Fila | Quantas operações aguardam nessa máquina. |
| Fila (h) | Horas de trabalho que a fila vai pedir: peças que faltam × tempo padrão. Pode ter o aviso "Fila maior que o tempo livre". Pode mostrar "inclui X h de tempo estimado" ou "parcial: N sem tempo padrão". |
| Disputa | "N OPs na mesma máquina" quando há mais de uma. |

Atenção: operações sem tempo padrão não entram na soma da fila; a nota no rodapé conta quantas ficaram de fora.

## Problemas comuns

| Mensagem | O que fazer |
|---|---|
| Nenhum recurso no filtro | Limpe os filtros. |
| N recurso(s) sem calendário | Cadastrar turno/calendário; confirmar com a liderança. |
| Nenhum recurso com calendário | Gargalo não pode ser determinado. |

Veja também: [Horas e utilização](topico:71-analises-horas-utilizacao).
