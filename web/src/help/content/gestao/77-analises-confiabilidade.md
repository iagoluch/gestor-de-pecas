---
titulo: Análises - Confiabilidade
grupo: Análises
ordem: 77
rotas: /analises/confiabilidade
---

A tela **Análises — Confiabilidade** mostra com que frequência os equipamentos quebram e quanto tempo levam para voltar. Texto da tela: "Quebras de equipamento no período: com que frequência param e quanto tempo levam para voltar."

Usa a barra de filtros do topo. Veja [Filtros globais](topico:04-filtros-globais).

## O que conta como quebra

Só parada classificada como **manutenção corretiva** no catálogo de motivos, e que não seja programada. Falta de material, refeição, setup, espera e manutenção preventiva **não** são quebra.

## Fórmulas

| Sigla | Significa | Conta |
|---|---|---|
| MTBF | Tempo médio entre quebras | Tempo operacional ÷ número de quebras |
| MTTR | Tempo médio para reparar | Tempo total de reparo ÷ reparos concluídos |

Tempo operacional = produção, setup e atividade sem OP, em tempo físico.

Exemplo: 200 h operando, 4 quebras que somaram 8 h de reparo. MTBF = 200 ÷ 4 = 50 h (quebra a cada 50 h). MTTR = 8 ÷ 4 = 2 h. MTBF maior é melhor; MTTR menor é melhor.

Quebra ainda em andamento conta no número de quebras, mas só reparos concluídos entram no MTTR.

## Cartões

| Cartão | Significado |
|---|---|
| MTBF | "Tempo operacional entre quebras". |
| MTTR | "Tempo médio até voltar a produzir". |
| Quebras no período | Total, clicável (mostra a soma por equipamento). Detalhe: horas de máquina parada. |
| Equipamento mais crítico | Quem mais quebrou. "Nenhum" se não houve. |

## Tabelas

- **Quebras por equipamento**: Recurso, Quebras, Tempo parado, MTTR (ordenado por mais quebras).
- **Causas das quebras**: barras por motivo, em ocorrências.

## Quando não há número

| Mensagem | Motivo |
|---|---|
| Catálogo de motivos sem classe de manutenção corretiva | Não há base para separar quebra de perda comum; confirmar com a liderança. |
| Nenhuma falha de equipamento registrada no período. | Bom sinal, ou paradas lançadas com outro motivo. |
| Falhas registradas sem tempo operacional medido | MTBF não calculável. |
| Nenhuma quebra no período / Nenhuma causa registrada | Listas vazias. |

Veja também: [Paradas e Setup](topico:72-analises-paradas).
