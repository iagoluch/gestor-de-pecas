# Matriz Final — Homologação Extrema do Gestor de Peças Web

> **HISTÓRICO — NÃO É MATRIZ DO AMBIENTE ATUAL.** O banco dedicado desta execução foi removido em 27/08/2026 após dump validado. O TESTE oficial atual é `gestor_pecas_test`; consulte `ROADMAP.md` para gates vigentes.

> Registro histórico de 20/08/2026. As ressalvas abaixo sobre aprovação de
> OEE/FTT foram superadas pela validação registrada em 25/08/2026 e não
> descrevem o comportamento vigente.

Data: 20/08/2026  
Banco exclusivo: `gestor_pecas_test_homologacao_extrema_20260820`  
Gate técnico isolado: **APROVADO**  
Gate de entrada em produção: **COM RESSALVAS**

## Legenda

- `PASS`: requisito exercitado e aprovado com evidência local/isolada.
- `PASS-COND`: comportamento aprovado, com dependência externa ou definição oficial pendente.
- `N/A`: requisito corretamente não calculado ou não aplicável, sem valor inventado.
- Severidade `B`: bloqueante para o gate técnico; `A`: alta; `M`: média; `I`: informativa.

## Matriz

| ID | Área | Evidência principal | Resultado | Status | Sev. |
|---:|---|---|---|---|:---:|
| 1 | Isolamento | Barreiras de nome/DSN; carga no banco exclusivo | Operacional intacto; alvo distinto | PASS | B |
| 2 | Integridade da regra | Reconciliação não altera expectativa | 53/53 comparações exatas | PASS | B |
| 3 | Precedência | Contratos canônicos e estados explícitos | Sem inferência silenciosa | PASS | B |
| 4 | Regras industriais | Quantidade, setup, paradas, turnos e rateio | Invariantes aprovadas | PASS | B |
| 5 | Golden dataset | Seed, JSON e Markdown de expectativa | Determinístico e auditável | PASS | B |
| 6 | Fábrica inteira | 10 dias, turnos, setores e perfis variados | Cobertura heterogênea | PASS | A |
| 7 | Perfis/setores | Corte, Dobra, Usinagem, Serra, Solda e Pintura | Perfis distribuídos | PASS | A |
| 8 | Volume | 120 OPs e eventos relacionados | Volume mínimo superado | PASS | A |
| 9 | OPs/roteiros | Estados, recursos e operações | 120/120/120 consistentes | PASS | B |
| 10 | Produção boa | SQL × serviço × API | 4.968 peças boas | PASS | B |
| 11 | Refugo | Fonte canônica separada | 72; não completa OP | PASS | B |
| 12 | Retrabalho | Fonte canônica e estados separados | 26 unidades; 6 OPs | PASS | B |
| 13 | Setup | Estado produtivo e telas operacionais | 6 OPs; regra preservada | PASS | B |
| 14 | Paradas | Manual sem OP e causas incompletas | 10 sem OP; auditáveis | PASS | B |
| 15 | Turnos | Calendário, intervalos e limites oficiais | 18 eventos em 17:30/21:30 | PASS | B |
| 16 | Rateio simultâneo | Sessão física e rateios | 7.200 s = 7.200 s | PASS | B |
| 17 | Estado conflitante | Sobreposição intencional | 1.800 s preservados | PASS | B |
| 18 | Atividade sem OP | Estado físico canônico | 10 atividades produtivas | PASS | B |
| 19 | Falta de apontamento | Inconsistências deliberadas | Expostas, não mascaradas | PASS | A |
| 20 | Operadores | 12 crachás fictícios e 11 usuários copiados | Rastreabilidade disponível | PASS | A |
| 21 | Solda | Seleção de estação e evidência responsiva | Fluxo renderizado | PASS | A |
| 22 | Corte | Fila, máquinas e apontamentos | Fluxo e dados aprovados | PASS | B |
| 23 | Nesting | Planos e tempos individuais | 48 tempos próprios | PASS | B |
| 24 | Destaque | 44 eventos e tela dedicada | Separação preservada | PASS | A |
| 25 | Plano × Real | Contratos analíticos | Desvios expostos | PASS | A |
| 26 | OEE e correlatos | Availability/reason/source | Sem fórmula oficial inventada | N/A | B |
| 27 | Agregação | Visão geral, setores e recursos | SQL × backend conciliados | PASS | B |
| 28 | Management View | Rotas, KPIs e ausência de Correção | Contrato aprovado | PASS | B |
| 29 | Drill-down | OP `HOMEXT00001` e nestings | Timeline disponível | PASS | A |
| 30 | Auditoria | 12 dados ruins deliberados | Alertas preservados | PASS | B |
| 31 | Confiabilidade | Endpoint dedicado | Incompletude sinalizada | PASS | B |
| 32 | Rastreabilidade | OP, operação, eventos e origem | Cadeia navegável | PASS | B |
| 33 | Histórico | Filtros temporais e timeline | Período completo disponível | PASS | A |
| 34 | Relatórios | Gerencial, produção, perdas, indicadores e analítico | 5 famílias HTTP 200 | PASS | A |
| 35 | Filtros | Período, setor, recurso, OP e produto | Contratos exercitados | PASS | A |
| 36 | Paginação | Página 2, tamanho 17 | Total 108, 7 páginas | PASS | A |
| 37 | SSE/tempo real | Dois clientes + `live_tick` | Atualiza sem novo apontamento | PASS | B |
| 38 | Multiusuário | 24 consultas, oito threads | 24/24; máx. 453 ms | PASS | B |
| 39 | Erros | 400, 401 e 403 esperados | Falhas controladas | PASS | B |
| 40 | UTF-8 | Texto longo, acentos e CSV BOM | Integridade preservada | PASS | B |
| 41 | Descrições grandes | OP longa e screenshots | Sem corrupção; layout legível | PASS | A |
| 42 | Resoluções | 1920×1080, 1600×900, 1366×768 | 39 capturas | PASS | A |
| 43 | Teste visual | PNGs e duas folhas de contato | Sem loading residual | PASS | A |
| 44 | Performance | 30 rotas e amostragem repetida | p95 geral repetido 78 ms | PASS | B |
| 45 | Consultas ao banco | SQL direto, repositório e API | Mesma verdade canônica | PASS | B |
| 46 | Reconciliação | `reconcile.py` e JSON real | 53 PASS, 0 FAIL | PASS | B |
| 47 | Dado ruim × bug | Dataset mantém inconsistências | Não houve correção automática | PASS | B |
| 48 | Correção de bugs | Cache de calendário e refresh SSE | Regressões adicionadas | PASS | B |
| 49 | Relatório final | `HOMOLOGACAO_EXTREMA.md` | Evidências e limites registrados | PASS | A |
| 50 | Matriz final | Este documento | Cobertura rastreável | PASS | A |
| 51 | Artefatos | Seed, reconcile, CSV, JSON, PNGs e docs | Entregues localmente | PASS | A |
| 52 | Gate final | Testes + pendências externas | Produção com ressalvas | PASS-COND | B |
| 53 | Dados imperfeitos | Perfis e 12 inconsistências | Realismo preservado | PASS | A |
| 54 | Resultado esperado | Backend/Web coerentes | Gate técnico aprovado | PASS | B |
| 55 | Execução obrigatória | Testes reais concluídos | Sem relatório meramente teórico | PASS | B |
| 56 | Preservação | Banco e cleanup seguro | Banco mantido; drop não executado | PASS | B |

## Ressalvas para produção

1. A integração corporativa definitiva com Protheus/TOTVS ainda depende de decisão e validação da TI.
2. Fórmulas oficiais de OEE, FTT, Performance e Capacidade ainda precisam ser aprovadas; o sistema corretamente devolve indisponibilidade/parcialidade.
3. O broker SSE atual é local ao processo. Implantação com múltiplos workers exige um barramento compartilhado, por exemplo PostgreSQL `LISTEN/NOTIFY` ou Redis.
4. A entrada em produção requer segredo de sessão persistente, HTTPS, política de backup/restore, monitoramento e aceite presencial de operadores/liderança na rede e nos dispositivos reais.
5. Qlik permaneceu desabilitado na homologação isolada; nenhuma conclusão foi extrapolada para a integração corporativa.

Nenhuma dessas ressalvas invalida o gate técnico local. Elas impedem classificar a implantação corporativa como aprovação irrestrita.
