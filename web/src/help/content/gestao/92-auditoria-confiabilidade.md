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

Por que "Não configurada": o sistema não inventa percentual sem fórmula oficial. O texto da tela diz: "Percentual de confiabilidade não será inventado sem fórmula oficial." Não existe fórmula oficial no sistema, então o cartão nunca vai mostrar um percentual por conta própria. Ele só passaria a mostrar número se uma fórmula fosse criada no sistema (isso é decisão da diretoria e exige mudança no sistema).

## Cobertura do período

- Apontamentos analisados.
- Estados físicos de recurso.
- Sessões de rateio.
- Inconsistências abertas: soma de todas as gravidades.

## Distribuição das inconsistências

Tabela Severidade × Ocorrências (informativo, aviso, erro, crítico). Só aparecem as severidades que o sistema devolveu; sem nenhuma, a tabela mostra "Sem registros".

Ocioso dentro do turno, sem apontamento, **não** é inconsistência: é parada não planejada e já entra nas métricas de parada. Os detalhes de cada uma estão em [Alertas e inconsistências](topico:91-auditoria-alertas-inconsistencias).

## De onde vem o estado físico

Normalmente dos eventos de estado do recurso. Se não houver, o sistema usa a linha do tempo dos apontamentos como substituto.

## Quem pode ver

Gestão (contas com acesso à gestão). Veja [perfis e acessos](topico:02-perfis-e-acessos). Usa os [filtros globais](topico:04-filtros-globais).

## Problemas comuns

- **Tudo zerado**: não há dados no período/filtro. Amplie o período.
- **Muitas críticas**: abra Alertas e inconsistências e filtre por setor.
