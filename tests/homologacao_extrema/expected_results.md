# Resultados esperados — Homologação Extrema

## Identificação e segurança

- Dataset: `homologacao_extrema_v1`.
- Período: 11/08/2026 06:00 até 20/08/2026 21:30.
- Banco exclusivo: `gestor_pecas_test_homologacao_extrema_20260820`.
- O banco operacional e o banco comum de testes devem possuir nomes diferentes do banco exclusivo.
- A carga pode ler os usuários do banco operacional, mas nenhuma escrita pode ocorrer nele.
- A execução repetida deve produzir os mesmos totais no mesmo banco exclusivo.

## Totais ouro

| Grandeza | Esperado |
|---|---:|
| OPs | 120 |
| Operações | 120 |
| Apontamentos operacionais | 120 |
| Eventos canônicos de quantidade | 149 |
| Tarefas de Corte | 24 |
| Planos/Nestings de Corte | 48 |
| Apontamentos de Corte | 30 |
| Eventos de Destaque | 44 |
| Crachás fictícios | 12 |
| Inconsistências deliberadas | 12 |
| Usuários copiados | 11 |
| Quantidade planejada | 7.200 |
| Quantidade boa | 4.968 |
| Refugo | 72 |
| Retrabalho | 26 |

## Estados das OPs

| Estado | Esperado |
|---|---:|
| Finalizado | 72 |
| Em processo | 12 |
| Aguardando | 12 |
| Parada | 12 |
| Setup | 6 |
| Retrabalho | 6 |

## Casos de borda

| Caso | Esperado |
|---|---:|
| Sessão física compartilhada | 7.200 s |
| Tempo total rateado entre duas OPs | 7.200 s |
| Estados conflitantes | 1.800 s, expostos como conflito/desconhecido |
| Paradas manuais sem OP | 10 |
| Atividades produtivas sem OP | 10 |
| Interrupções automáticas de turno | 18 |
| Evento de duração zero | 1 |

## Corte, Nesting e Destaque

| Grandeza | Esperado |
|---|---:|
| Planos de Corte | 48 |
| Apontamentos realizados | 30 |
| Apontamentos concluídos | 20 |
| Tempo previsto total dos planos | 59.520 s |
| Tempo real total dos concluídos | 22.000 s |
| Eventos de Destaque | 44 |

Cada nesting deve preservar o próprio tempo previsto. A soma de nestings não pode substituir silenciosamente o valor de cada item.

## Invariantes obrigatórios

- `Quantidade Produzida` representa somente peças boas.
- Refugo e retrabalho permanecem separados e não completam a OP.
- Setup é produtivo e não reduz Disponibilidade ou Performance.
- Parada manual é não programada; interrupção automática é programada.
- Os limites automáticos oficiais são 17:30 e 21:30.
- OPs simultâneas podem compartilhar um recurso, mas o tempo físico não pode ser multiplicado.
- Estados físicos incompatíveis devem aparecer como conflito/desconhecido.
- Atividade sem OP continua produtiva.
- O Management View não possui módulo visual de Correção/Edição.
- Valor ausente ou regra não oficial permanece `dados_insuficientes`, `parcial` ou `nao_configurado`.

## Critério automatizado

O arquivo `reconcile.py` deve terminar com todas as verificações em `PASS`, confrontando:

1. resultado esperado;
2. SQL direto no banco exclusivo;
3. contratos e serviços do backend;
4. API HTTP e exportação CSV;
5. autenticação, autorização, concorrência, performance e SSE.

O JSON canônico e legível por máquina está em `expected_results.json`.
