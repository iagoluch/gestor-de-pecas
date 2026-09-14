# Simulação histórica de três meses — Gestor de Peças Web

> **HISTÓRICO — NÃO USAR COMO AMBIENTE ATUAL.** O banco citado neste relatório foi removido do servidor em 27/08/2026 após dump validado/restaurável. O banco TESTE oficial atual é `gestor_pecas_test`. A direção vigente está em `ROADMAP.md`.

> Registro histórico. A classificação original das fórmulas de OEE/FTT como
> exclusivas da simulação foi superada em 25/08/2026. A mesma regra agora é
> canônica para dados reais e simulados.

Data da execução: **24/08/2026**  
Período simulado: **01/06/2026 06:00 a 24/08/2026 08:32**  
Banco isolado: `gestor_pecas_test_homolog_simulacao_3_meses_20260824`  
Resultado final: **APROVADO — 204/204 reconciliações**

## Resumo executivo

O Gestor de Peças Web está em execução local em `http://127.0.0.1:8000/`, conectado exclusivamente ao PostgreSQL de teste. O banco isolado foi alimentado com três meses de dados fictícios e determinísticos de OPs, operações, tarefas, peças, nestings, apontamentos, quantidades, estados de recurso, setup, paradas, retrabalho, filas e rastreabilidade.

O acesso ativo ao Qlik foi retirado. Não existem sincronização, fallback, temporizador, worker ou dependência de rede Qlik no fluxo em execução. O arquivo local de credenciais Qlik foi removido. Campos ou nomes históricos que ainda existam no schema permanecem apenas como compatibilidade de migration/dados legados e não iniciam conexão externa.

A futura integração corporativa foi preparada por contrato neutro. O provedor está explicitamente marcado como `pending_totvs_definition`, sem leitura de planejamento e sem escrita de execução enquanto a TI não definir o mecanismo Protheus/TOTVS.

## Estado do ambiente

- Web local: `http://127.0.0.1:8000/`
- Saúde da API: `ok`
- Banco: `available`
- Schema: versão `12`
- Fonte ativa: `postgresql_test_only`
- Atualização em tempo real: SSE com `live_tick`, independente de novo apontamento
- Gestão Web: habilitada
- Operador Web: habilitado
- Cálculos: somente no backend
- Integração corporativa: pendente de definição pela TI, fechada para leitura e escrita
- Usuários: 11 contas do banco de teste comum preservadas no banco da simulação, com as mesmas senhas já cadastradas

## Volume carregado

| Entidade | Quantidade |
|---|---:|
| OPs / operações / apontamentos | 1.752 / 1.752 / 1.752 |
| Eventos de quantidade | 5.040 |
| Eventos de estado de recurso | 29.391 |
| Eventos de apontamento de operador | 27.588 |
| Participações de operador | 1.740 |
| Eventos de histórico | 1.752 |
| Interrupções automáticas de turno | 3.456 |
| Tarefas | 144 |
| Planos / nestings de Corte | 288 |
| Apontamentos de Corte | 288 |
| Cortes concluídos | 276 |
| Eventos de Destaque | 338 |
| Inconsistências deliberadas e auditáveis | 36 |

## Resultado mensal

| Período | Planejado | Peças boas | Refugo | Retrabalho | Disponibilidade | Performance | FTT | OEE | Utilização | Produtividade | AE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Junho | 288.480 | 286.792 | 5.379 | 1.533 | 88,59% | 92,97% | 97,65% | 80,43% | 92,29% | 87,59% | 82,37% |
| Julho | 299.700 | 301.542 | 2.959 | 903 | 91,47% | 95,85% | 98,74% | 86,57% | 94,38% | 90,97% | 87,68% |
| Agosto até 24/08 08:32 | 222.120 | 215.348 | 1.247 | 319 | 92,58% | 97,71% | 99,28% | 89,80% | 95,17% | 92,39% | 90,46% |

Na data desta execução, as fórmulas de OEE/FTT ainda estavam marcadas como
exclusivas do cenário histórico. Essa classificação é obsoleta; os resultados
numéricos permanecem evidência do cálculo que depois foi validado como canônico.

## Tempos relevantes

| Período | Setup produtivo | Paradas |
|---|---:|---:|
| Junho | 317h 37m 08s | 669h 35m 55s |
| Julho | 235h 34m 03s | 511h 22m 00s |
| Agosto até 24/08 08:32 | 133h 21m 50s | 311h 35m 46s |

O rateio conserva o tempo físico: **43.200 s físicos = 43.200 s atribuídos** nos 12 cenários simultâneos. Quantidade produzida contém somente peças boas; refugo e retrabalho permanecem separados. Setup é produtivo e não reduz Disponibilidade nem Performance.

## Validação funcional e técnica

- Reconciliação final: **204 aprovadas, 0 falhas**.
- Testes Python: **242/242 aprovados**.
- Testes Web: **11/11 aprovados**.
- Build Web de produção: **aprovado**.
- API, serviços e SQL conciliados contra o mesmo resultado esperado.
- Corte preserva tempo previsto e realizado individual por nesting.
- Interrupções automáticas respeitam 17:30 e 21:30, mantêm OP aberta e registram quantidade zero.
- Parada manual sem OP permanece permitida.
- OP aberta pode seguir para setup ou retrabalho sem apontamento prévio de início.
- Botão **Sair** disponível na gestão e na operação.
- Calendário em português e no padrão visual solicitado.

Durante a auditoria final foi detectado um evento produtivo extra de uma sessão visual anterior. O evento estava somente no banco isolado da simulação. O banco foi restaurado pelo seed determinístico e a reconciliação final confirmou novamente os **204/204** resultados esperados. O banco operacional não foi acessado nem alterado.

## Evidência visual

Foram geradas **46 capturas individuais** e **7 folhas de contato**. Todas as capturas principais foram refeitas em largura integral após a detecção de que o método anterior salvava apenas 816–822 px do painel. O gate visual agora exige a largura completa da viewport, descontando somente os 15 px da barra de rolagem do Chromium quando ela existe.

- [Manifesto de dimensões e hashes](screenshots/simulacao-3-meses/capture_manifest.txt)
- [Calendário com 24/08/2026 selecionado](screenshots/simulacao-3-meses/CALENDARIO_DATA.png)
- [Gestão — agosto](screenshots/simulacao-3-meses/MANAGEMENT_AGOSTO.png)
- [Folha completa da gestão](screenshots/simulacao-3-meses/contact_sheet_gestao.jpg)
- [Folha completa dos operadores](screenshots/simulacao-3-meses/contact_sheet_operacao.jpg)

Resoluções exercitadas: 1920×1080, 1600×900 e 1366×768. Páginas com conteúdo vertical foram registradas em captura integral para não ocultar cards, tabelas ou históricos.

## Limites e próximos passos corporativos

- Os dados são fictícios e não representam produção real.
- O PostgreSQL de teste é a persistência de transição, não uma decisão corporativa definitiva.
- Não foi assumida tabela, view, procedure, API, permissão ou chave de integração TOTVS.
- O planejamento continuará pertencendo ao Protheus/TOTVS; o Gestor registrará execução real e comparará Plano × Real.
- A ativação da integração corporativa dependerá de contrato e definição formal da TI.
