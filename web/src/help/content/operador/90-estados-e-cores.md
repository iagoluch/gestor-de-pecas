---
titulo: Estados e etiquetas
grupo: Referência
ordem: 90
rotas:
---

Resumo dos estados que aparecem no sistema. Cores exatas variam com o tema claro ou escuro; confirmar com a liderança se precisar do tom.

## Estado do posto (barra de estado)

| Estado | Significado |
|---|---|
| Produzindo | OP em processo. |
| Parado | Posto parado, com motivo. |
| Setup | Preparação em andamento. |
| Retrabalho | Retrabalho em andamento. |
| Atividade sem OP | Atividade fora de OP. |
| Aguardando OP | Livre, esperando OP. |
| Fora do turno | Fora do horário. |
| Sem demanda | Sem OP para o posto. |
| Sem apontamento | Sem registro. |

## Cartões de recurso (escolha do posto)

| Estado | Significado |
|---|---|
| Livre | Nenhuma OP. |
| Em uso | "Em uso por N OP(s)". |
| Ocupada | Setup ou retrabalho aberto. |

## Etapas do roteiro

Concluída, Atual, Próxima. Veja [Carregar a OP e o roteiro](topico:04-carregar-op-e-roteiro).

## Cards da OP

Em processo, Parada, Setup, Retrabalho, Aguardando (padrão). Veja [Cards, fila e histórico](topico:10-cards-fila-e-historico).

## Corte

Tarefa: Aguardando, Em processo, Finalizado. Plano: AGUARDANDO CORTE, EM CORTE, entre outros. Veja [Corte](topico:20-corte).

## Destaque

Corte concluído, Corte parcial (tarefa). Aguardando destaque, Destaque em execução, Destaque parado, Destaque concluído (plano). Histórico: Em execução, Parada, Finalizada, Aguardando. Veja [Destaque](topico:30-destaque).

## Qualidade

| Item | Valores |
|---|---|
| Cota | Conforme, Não conforme, Informe a medida |
| Peça | Aprovada, Retrabalho, Refugo |
| Primeira peça | Conforme (libera o lote), Retrabalho (bloqueia), Refugo (nova primeira peça) |

Veja [Qualidade e inspeção](topico:40-qualidade-e-inspecao).

## Cores de aviso

- Vermelho: erro ou posto parado.
- Amarelo: atenção (ex.: motivo de parada classificado como de atenção).
- Verde: sucesso ou conforme.
- Azul: informação.
