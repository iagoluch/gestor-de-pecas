---
titulo: Auditoria - Confiabilidade
grupo: Auditoria
ordem: 92
rotas: /auditoria/confiabilidade
---

Tela **Auditoria — Confiabilidade dos dados**. Mostra quanto dado foi analisado e quantos problemas abertos existem. **Não confunda** com confiabilidade de máquina (MTBF/MTTR), que fica em [Análises — Confiabilidade](topico:77-analises-confiabilidade).

## Cartões do topo

| Cartão | O que significa |
|---|---|
| Registros analisados | Quantos apontamentos foram examinados. |
| Estados físicos | Quantos estados de recurso (produzindo, parado, setup etc.) entraram na análise. |
| Sessões de rateio | Quantas sessões de divisão de tempo entre OPs foram checadas. |
| Confiabilidade | Hoje mostra **"Não configurada"**. |

Por que "Não configurada": o sistema não inventa percentual sem fórmula oficial. O texto da tela diz: "Percentual de confiabilidade não será inventado sem fórmula oficial." Definir a fórmula: confirmar com a liderança.

## Cobertura do período

- Apontamentos analisados.
- Estados físicos de recurso.
- Sessões de rateio.
- Inconsistências abertas: soma de todas as gravidades.

## Distribuição das inconsistências

Tabela Severidade × Ocorrências (informativo, aviso, erro, crítico). Os detalhes de cada uma estão em [Alertas e inconsistências](topico:91-auditoria-alertas-inconsistencias).

## De onde vem o estado físico

Normalmente dos eventos de estado do recurso. Se não houver, o sistema usa a linha do tempo dos apontamentos como substituto.

## Quem pode ver

Gestão. Veja [perfis e acessos](topico:02-perfis-e-acessos).

## Problemas comuns

- **Tudo zerado**: não há dados no período/filtro. Amplie o período.
- **Muitas críticas**: abra Alertas e inconsistências e filtre por setor.
