# Capturas UI — Gestor de Peças

Capturado em 08/10/2026, entre 09:38 e 10:05 (America/Sao_Paulo). Screenshots reais do frontend servido, usando Chrome/Playwright em viewport de 1920 × 1080; páginas longas têm captura completa e modais usam a área visível. Nenhuma imagem foi gerada ou redesenhada.

## Cobertura realizada

| Acesso / representante | PNGs | Cobertura |
| --- | ---: | --- |
| Gestão normal — gestor | 86 | Telas comuns acessíveis e estados específicos listados abaixo. |
| Gestão da Manufatura — manufatura | 45 | Telas comuns acessíveis e estados específicos listados abaixo. |
| Gestão da Qualidade — qualidade | 41 | Telas comuns acessíveis e estados específicos listados abaixo. |
| Pintura — fluxo geral | 23 | Recurso, OP, roteiro, exceção de etapa, início, fila, parada, retomada, retrabalho, finalização com crachá, histórico e atividade sem OP. |
| Dobra — Caldeiraria | 17 | Setup, portão da primeira peça, cotas existentes/novas, medição fora da faixa, bloqueio, crachá responsável, alternativa de refugo e aprovação. |

Gestão comum: Tela inicial (Visão Geral, Setores, Alertas, Chamadas); Painéis (Andon, Mapa da fábrica, Pausas); Consulta Operacional (Visão Geral, Recursos, OPs em andamento, Tempo MES); Produção (Ordens, Realizada, Planejado × Realizado); Análises (OEE, Horas & Utilização, Paradas & Setup, Qualidade, Tempo padrão, Cronoanálise, Capacidade, Confiabilidade); Auditoria (Apontamentos, Inconsistências, Confiabilidade); cinco Relatórios; três visões de Rastreabilidade. Cada nível foi acessado separadamente. Formulários e filtros compartilhados têm detalhe principal em Gestão Normal para evitar repetição de estados idênticos.

Manufatura exclusiva: Tempo padrão, filtros, valor manual preenchido/salvo, histórico, menu e confirmação de remoção, recálculo em execução e resultado. Qualidade exclusiva: Cotas padrão, cadastro, editor com múltiplas cotas, revisão existente e filtro de produto.

## Origem dos dados e segurança da execução

- `TESTE` nas tabelas: API temporária em `127.0.0.1:8011`, com `current_database() = gestor_pecas_test` confirmado antes de escrever. Frontend atual de `web/dist`, sem mudanças no produto.
- `Simulação isolada` nas tabelas: infraestrutura existente `tests/web_preview_api.py`, nas portas 8010/8012, com `ApiFakeDatabase` em memória. A IA usou `VisualAIProvider`, sem consultar um provedor externo. São screenshots reais da interface, com dados simulados identificados.
- A porta 8001 pertence ao REAL e não foi usada para gravações nem para estas capturas. TOTVS/outbox/worker, sincronização SigmaNEST, Telegram, automações externas e IA externa estavam desativados na instância TESTE.
- Para os fluxos foram criadas somente no TESTE as OPs `UI-CAPTURA-PINTURA`, `UI-CAPTURA-DOBRA`, `UI-CAPTURA-DOBRA-NOVA`, o produto `UI-CAPTURA-PROD`, tarefa `UI-CAPTURAS` e crachá `UICAP`. Os três apontamentos terminaram com 2 boas e 0 refugo.
- O valor manual de 12 s usado no ensaio foi removido pelo próprio fluxo, preservando o histórico. O cadastro de cotas do produto simulado e os registros de execução/auditoria permanecem no TESTE. O recálculo de estimativas foi executado no TESTE.
- O estado Atividade sem OP na Pintura foi registrado no TESTE. Não foram enviadas chamadas da Gestão nem efetuadas exclusões de conversas/pausas existentes. As cinco contas temporárias e o crachá de ensaio foram desativados após a captura. Não há senhas, tokens, arquivos de ambiente ou perfis de navegador no pacote.

## Limites e pendências

- Admin é um quarto nível, fora dos três solicitados: cadastro de usuários/crachás, turnos, sistema e contatos Dev não fazem parte da cobertura. A antiga rota de Metas não aparece na navegação destes perfis e foi excluída.
- Refugo da primeira peça: alternativa e exigência de crachá capturadas; descarte não foi confirmado. O ramo de retrabalho foi executado e autorizado no TESTE.
- PDF de OP: o estado disponível foi “Sem PDF”; visualizador com documento real não foi capturado.
- Pausas automáticas por horário e fim de turno: formulários/configuração capturados; não foi aguardada uma transição de relógio. Parada manual e retomada foram executadas.
- Não foram provocados todos os erros possíveis de rede, disputas simultâneas ou estados de dados ausentes. Estados indisponíveis encontrados permanecem documentados nas capturas.
- A IA externa fica indisponível na instância TESTE por isolamento; o chat disponível e seus modais foram capturados no simulador existente.
- A gestão comum tem telas sem registros no filtro “Hoje” e exemplos preenchidos em 30 dias, rastreabilidade da OP e histórico de primeiras peças.

## Navegação das capturas

### Gestão normal — gestor

| Captura | Fluxo / rota | Estado / finalidade | Dados |
| --- | --- | --- | --- |
| [01_visao_geral.png](gestao/normal/01_visao_geral.png) | `/inicio/visao-geral` | visao geral | Simulação isolada |
| [02_filtros_expandidos.png](gestao/normal/02_filtros_expandidos.png) | `/inicio/visao-geral` | filtros expandidos | Simulação isolada |
| [03_explicacao_oee.png](gestao/normal/03_explicacao_oee.png) | `/inicio/visao-geral` | explicacao oee | Simulação isolada |
| [04_inicio_setores.png](gestao/normal/04_inicio_setores.png) | `/inicio/setores` | inicio setores | Simulação isolada |
| [05_inicio_alertas.png](gestao/normal/05_inicio_alertas.png) | `/inicio/alertas` | inicio alertas | Simulação isolada |
| [06_inicio_pausas.png](gestao/normal/06_inicio_pausas.png) | `/inicio/pausas` | inicio pausas | Simulação isolada |
| [07_inicio_chamadas.png](gestao/normal/07_inicio_chamadas.png) | `/inicio/chamadas` | inicio chamadas | Simulação isolada |
| [08_inicio_visao-geral.png](gestao/normal/08_inicio_visao-geral.png) | `/inicio/visao-geral` | inicio visao-geral | TESTE |
| [09_inicio_setores.png](gestao/normal/09_inicio_setores.png) | `/inicio/setores` | inicio setores | TESTE |
| [10_inicio_alertas.png](gestao/normal/10_inicio_alertas.png) | `/inicio/alertas` | inicio alertas | TESTE |
| [11_inicio_pausas.png](gestao/normal/11_inicio_pausas.png) | `/inicio/pausas` | inicio pausas | TESTE |
| [12_inicio_chamadas.png](gestao/normal/12_inicio_chamadas.png) | `/inicio/chamadas` | inicio chamadas | TESTE |
| [13_inicio_ia.png](gestao/normal/13_inicio_ia.png) | `/inicio/ia` | inicio ia | TESTE |
| [14_consulta-operacional_visao-geral.png](gestao/normal/14_consulta-operacional_visao-geral.png) | `/consulta-operacional/visao-geral` | consulta-operacional visao-geral | TESTE |
| [15_consulta-operacional_recursos.png](gestao/normal/15_consulta-operacional_recursos.png) | `/consulta-operacional/recursos` | consulta-operacional recursos | TESTE |
| [16_consulta-operacional_ops-em-andamento.png](gestao/normal/16_consulta-operacional_ops-em-andamento.png) | `/consulta-operacional/ops-em-andamento` | consulta-operacional ops-em-andamento | TESTE |
| [17_consulta-operacional_tempo-mes.png](gestao/normal/17_consulta-operacional_tempo-mes.png) | `/consulta-operacional/tempo-mes` | consulta-operacional tempo-mes | TESTE |
| [18_producao_ordens.png](gestao/normal/18_producao_ordens.png) | `/producao/ordens` | producao ordens | TESTE |
| [19_producao_realizada.png](gestao/normal/19_producao_realizada.png) | `/producao/realizada` | producao realizada | TESTE |
| [20_producao_planejado-realizado.png](gestao/normal/20_producao_planejado-realizado.png) | `/producao/planejado-realizado` | producao planejado-realizado | TESTE |
| [21_analises_oee.png](gestao/normal/21_analises_oee.png) | `/analises/oee` | analises oee | TESTE |
| [22_analises_horas-utilizacao.png](gestao/normal/22_analises_horas-utilizacao.png) | `/analises/horas-utilizacao` | analises horas-utilizacao | TESTE |
| [23_analises_paradas.png](gestao/normal/23_analises_paradas.png) | `/analises/paradas` | analises paradas | TESTE |
| [24_analises_qualidade.png](gestao/normal/24_analises_qualidade.png) | `/analises/qualidade` | analises qualidade | TESTE |
| [25_analises_tempo-padrao-real.png](gestao/normal/25_analises_tempo-padrao-real.png) | `/analises/tempo-padrao-real` | analises tempo-padrao-real | TESTE |
| [26_analises_cronoanalise.png](gestao/normal/26_analises_cronoanalise.png) | `/analises/cronoanalise` | analises cronoanalise | TESTE |
| [27_analises_capacidade-gargalos.png](gestao/normal/27_analises_capacidade-gargalos.png) | `/analises/capacidade-gargalos` | analises capacidade-gargalos | TESTE |
| [28_analises_confiabilidade.png](gestao/normal/28_analises_confiabilidade.png) | `/analises/confiabilidade` | analises confiabilidade | TESTE |
| [29_auditoria_apontamentos.png](gestao/normal/29_auditoria_apontamentos.png) | `/auditoria/apontamentos` | auditoria apontamentos | TESTE |
| [30_auditoria_inconsistencias.png](gestao/normal/30_auditoria_inconsistencias.png) | `/auditoria/inconsistencias` | auditoria inconsistencias | TESTE |
| [31_auditoria_confiabilidade.png](gestao/normal/31_auditoria_confiabilidade.png) | `/auditoria/confiabilidade` | auditoria confiabilidade | TESTE |
| [32_relatorios_gerencial.png](gestao/normal/32_relatorios_gerencial.png) | `/relatorios/gerencial` | relatorios gerencial | TESTE |
| [33_relatorios_producao.png](gestao/normal/33_relatorios_producao.png) | `/relatorios/producao` | relatorios producao | TESTE |
| [34_relatorios_perdas.png](gestao/normal/34_relatorios_perdas.png) | `/relatorios/perdas` | relatorios perdas | TESTE |
| [35_relatorios_indicadores.png](gestao/normal/35_relatorios_indicadores.png) | `/relatorios/indicadores` | relatorios indicadores | TESTE |
| [36_relatorios_dados-analiticos.png](gestao/normal/36_relatorios_dados-analiticos.png) | `/relatorios/dados-analiticos` | relatorios dados-analiticos | TESTE |
| [37_rastreabilidade_op-produto.png](gestao/normal/37_rastreabilidade_op-produto.png) | `/rastreabilidade/op-produto` | rastreabilidade op-produto | TESTE |
| [38_rastreabilidade_linha-do-tempo.png](gestao/normal/38_rastreabilidade_linha-do-tempo.png) | `/rastreabilidade/linha-do-tempo` | rastreabilidade linha-do-tempo | TESTE |
| [39_rastreabilidade_lote-material-nesting.png](gestao/normal/39_rastreabilidade_lote-material-nesting.png) | `/rastreabilidade/lote-material-nesting` | rastreabilidade lote-material-nesting | TESTE |
| [40_visao_geral_30_dias.png](gestao/normal/40_visao_geral_30_dias.png) | `/inicio/visao-geral` | visao geral 30 dias | TESTE |
| [41_filtros_avancados_teste.png](gestao/normal/41_filtros_avancados_teste.png) | `/inicio/visao-geral` | filtros avancados teste | TESTE |
| [42_modal_oee_teste.png](gestao/normal/42_modal_oee_teste.png) | `/inicio/visao-geral` | modal oee teste | TESTE |
| [43_formulario_nova_pausa.png](gestao/normal/43_formulario_nova_pausa.png) | `/inicio/pausas` | formulario nova pausa | TESTE |
| [44_edicao_pausa.png](gestao/normal/44_edicao_pausa.png) | `/inicio/pausas` | edicao pausa | TESTE |
| [45_menu_acoes_pausa.png](gestao/normal/45_menu_acoes_pausa.png) | `/inicio/pausas` | menu acoes pausa | TESTE |
| [46_geracao_exportacao_relatorio.png](gestao/normal/46_geracao_exportacao_relatorio.png) | `/relatorios/gerencial` | Exportação de relatório: estado Gerando | TESTE |
| [47_painel_notificacoes.png](gestao/normal/47_painel_notificacoes.png) | `/inicio/chamadas` | painel notificacoes | TESTE |
| [48_modal_chamar.png](gestao/normal/48_modal_chamar.png) | `/inicio/visao-geral` | modal chamar | TESTE |
| [49_analise_setup_subaba.png](gestao/normal/49_analise_setup_subaba.png) | `/analises/paradas` | analise setup subaba | TESTE |
| [50_mapa_fabrica.png](gestao/normal/50_mapa_fabrica.png) | `/mapa-fabrica` | mapa fabrica | TESTE |
| [51_andon.png](gestao/normal/51_andon.png) | `/andon` | andon | TESTE |
| [52_andon_detalhe_recurso.png](gestao/normal/52_andon_detalhe_recurso.png) | `/andon` | andon detalhe recurso | TESTE |
| [53_mapa_hover_recurso.png](gestao/normal/53_mapa_hover_recurso.png) | `/mapa-fabrica` | mapa hover recurso | TESTE |
| [54_consulta-operacional_recursos_filtros.png](gestao/normal/54_consulta-operacional_recursos_filtros.png) | `/consulta-operacional/recursos` | consulta-operacional recursos filtros | TESTE |
| [55_consulta-operacional_ops-em-andamento_filtros.png](gestao/normal/55_consulta-operacional_ops-em-andamento_filtros.png) | `/consulta-operacional/ops-em-andamento` | consulta-operacional ops-em-andamento filtros | TESTE |
| [56_consulta-operacional_tempo-mes_filtros.png](gestao/normal/56_consulta-operacional_tempo-mes_filtros.png) | `/consulta-operacional/tempo-mes` | consulta-operacional tempo-mes filtros | TESTE |
| [57_producao_ordens_filtros.png](gestao/normal/57_producao_ordens_filtros.png) | `/producao/ordens` | producao ordens filtros | TESTE |
| [58_producao_realizada_filtros.png](gestao/normal/58_producao_realizada_filtros.png) | `/producao/realizada` | producao realizada filtros | TESTE |
| [59_producao_planejado-realizado_filtros.png](gestao/normal/59_producao_planejado-realizado_filtros.png) | `/producao/planejado-realizado` | producao planejado-realizado filtros | TESTE |
| [60_analises_oee_filtros.png](gestao/normal/60_analises_oee_filtros.png) | `/analises/oee` | analises oee filtros | TESTE |
| [61_analises_horas-utilizacao_filtros.png](gestao/normal/61_analises_horas-utilizacao_filtros.png) | `/analises/horas-utilizacao` | analises horas-utilizacao filtros | TESTE |
| [62_analises_paradas_filtros.png](gestao/normal/62_analises_paradas_filtros.png) | `/analises/paradas` | analises paradas filtros | TESTE |
| [63_analises_qualidade_filtros.png](gestao/normal/63_analises_qualidade_filtros.png) | `/analises/qualidade` | analises qualidade filtros | TESTE |
| [64_analises_tempo-padrao-real_filtros.png](gestao/normal/64_analises_tempo-padrao-real_filtros.png) | `/analises/tempo-padrao-real` | analises tempo-padrao-real filtros | TESTE |
| [65_analises_cronoanalise_filtros.png](gestao/normal/65_analises_cronoanalise_filtros.png) | `/analises/cronoanalise` | analises cronoanalise filtros | TESTE |
| [66_analises_capacidade-gargalos_filtros.png](gestao/normal/66_analises_capacidade-gargalos_filtros.png) | `/analises/capacidade-gargalos` | analises capacidade-gargalos filtros | TESTE |
| [67_analises_confiabilidade_filtros.png](gestao/normal/67_analises_confiabilidade_filtros.png) | `/analises/confiabilidade` | analises confiabilidade filtros | TESTE |
| [68_auditoria_apontamentos_filtros.png](gestao/normal/68_auditoria_apontamentos_filtros.png) | `/auditoria/apontamentos` | auditoria apontamentos filtros | TESTE |
| [69_auditoria_inconsistencias_filtros.png](gestao/normal/69_auditoria_inconsistencias_filtros.png) | `/auditoria/inconsistencias` | auditoria inconsistencias filtros | TESTE |
| [70_auditoria_confiabilidade_filtros.png](gestao/normal/70_auditoria_confiabilidade_filtros.png) | `/auditoria/confiabilidade` | auditoria confiabilidade filtros | TESTE |
| [71_relatorios_gerencial_filtros.png](gestao/normal/71_relatorios_gerencial_filtros.png) | `/relatorios/gerencial` | relatorios gerencial filtros | TESTE |
| [72_relatorios_producao_filtros.png](gestao/normal/72_relatorios_producao_filtros.png) | `/relatorios/producao` | relatorios producao filtros | TESTE |
| [73_relatorios_perdas_filtros.png](gestao/normal/73_relatorios_perdas_filtros.png) | `/relatorios/perdas` | relatorios perdas filtros | TESTE |
| [74_relatorios_indicadores_filtros.png](gestao/normal/74_relatorios_indicadores_filtros.png) | `/relatorios/indicadores` | relatorios indicadores filtros | TESTE |
| [75_relatorios_dados-analiticos_filtros.png](gestao/normal/75_relatorios_dados-analiticos_filtros.png) | `/relatorios/dados-analiticos` | relatorios dados-analiticos filtros | TESTE |
| [76_rastreabilidade_lote-material-nesting_filtros.png](gestao/normal/76_rastreabilidade_lote-material-nesting_filtros.png) | `/rastreabilidade/lote-material-nesting` | rastreabilidade lote-material-nesting filtros | TESTE |
| [77_ordens_periodo_com_dados.png](gestao/normal/77_ordens_periodo_com_dados.png) | `/producao/ordens` | ordens periodo com dados | TESTE |
| [78_rastreabilidade_op_detalhada.png](gestao/normal/78_rastreabilidade_op_detalhada.png) | `/rastreabilidade/op-produto` | rastreabilidade op detalhada | TESTE |
| [79_linha_tempo_eventos_op.png](gestao/normal/79_linha_tempo_eventos_op.png) | `/rastreabilidade/linha-do-tempo` | linha tempo eventos op | TESTE |
| [80_qualidade_com_primeiras_pecas.png](gestao/normal/80_qualidade_com_primeiras_pecas.png) | `/analises/qualidade` | qualidade com primeiras pecas | TESTE |
| [81_tema_escuro.png](gestao/normal/81_tema_escuro.png) | `/inicio/visao-geral` | tema escuro | TESTE |
| [82_navegacao_recolhida.png](gestao/normal/82_navegacao_recolhida.png) | `/inicio/visao-geral` | navegacao recolhida | TESTE |
| [83_ia_simulada_disponivel.png](gestao/normal/83_ia_simulada_disponivel.png) | `/inicio/ia` | ia simulada disponivel | Simulação isolada |
| [84_ia_consulta_sugerida.png](gestao/normal/84_ia_consulta_sugerida.png) | `/inicio/ia` | ia consulta sugerida | Simulação isolada |
| [85_ia_resposta_simulada.png](gestao/normal/85_ia_resposta_simulada.png) | `/inicio/ia` | ia resposta simulada | Simulação isolada |
| [86_ia_confirmacao_exclusao.png](gestao/normal/86_ia_confirmacao_exclusao.png) | `/inicio/ia` | ia confirmacao exclusao | Simulação isolada |

### Gestão da Manufatura — manufatura

| Captura | Fluxo / rota | Estado / finalidade | Dados |
| --- | --- | --- | --- |
| [01_visao_geral_perfil.png](gestao/manufatura/01_visao_geral_perfil.png) | `/inicio/visao-geral` | visao geral perfil | TESTE |
| [02_tempo_padrao.png](gestao/manufatura/02_tempo_padrao.png) | `/manufatura/tempo-padrao` | tempo padrao | TESTE |
| [03_filtro_produto.png](gestao/manufatura/03_filtro_produto.png) | `/manufatura/tempo-padrao` | filtro produto | TESTE |
| [04_tempo_manual_preenchido.png](gestao/manufatura/04_tempo_manual_preenchido.png) | `/manufatura/tempo-padrao` | tempo manual preenchido | TESTE |
| [05_tempo_manual_salvo_teste.png](gestao/manufatura/05_tempo_manual_salvo_teste.png) | `/manufatura/tempo-padrao` | tempo manual salvo teste | TESTE |
| [06_historico_manual.png](gestao/manufatura/06_historico_manual.png) | `/manufatura/tempo-padrao` | historico manual | TESTE |
| [07_menu_manual.png](gestao/manufatura/07_menu_manual.png) | `/manufatura/tempo-padrao` | menu manual | TESTE |
| [08_confirmacao_remover_manual.png](gestao/manufatura/08_confirmacao_remover_manual.png) | `/manufatura/tempo-padrao` | confirmacao remover manual | TESTE |
| [09_manual_ensaio_removido.png](gestao/manufatura/09_manual_ensaio_removido.png) | `/manufatura/tempo-padrao` | manual ensaio removido | TESTE |
| [10_inicio_setores.png](gestao/manufatura/10_inicio_setores.png) | `/inicio/setores` | inicio setores | TESTE |
| [11_inicio_alertas.png](gestao/manufatura/11_inicio_alertas.png) | `/inicio/alertas` | inicio alertas | TESTE |
| [12_inicio_pausas.png](gestao/manufatura/12_inicio_pausas.png) | `/inicio/pausas` | inicio pausas | TESTE |
| [13_inicio_chamadas.png](gestao/manufatura/13_inicio_chamadas.png) | `/inicio/chamadas` | inicio chamadas | TESTE |
| [14_inicio_ia.png](gestao/manufatura/14_inicio_ia.png) | `/inicio/ia` | inicio ia | TESTE |
| [15_consulta-operacional_visao-geral.png](gestao/manufatura/15_consulta-operacional_visao-geral.png) | `/consulta-operacional/visao-geral` | consulta-operacional visao-geral | TESTE |
| [16_consulta-operacional_recursos.png](gestao/manufatura/16_consulta-operacional_recursos.png) | `/consulta-operacional/recursos` | consulta-operacional recursos | TESTE |
| [17_consulta-operacional_ops-em-andamento.png](gestao/manufatura/17_consulta-operacional_ops-em-andamento.png) | `/consulta-operacional/ops-em-andamento` | consulta-operacional ops-em-andamento | TESTE |
| [18_consulta-operacional_tempo-mes.png](gestao/manufatura/18_consulta-operacional_tempo-mes.png) | `/consulta-operacional/tempo-mes` | consulta-operacional tempo-mes | TESTE |
| [19_producao_ordens.png](gestao/manufatura/19_producao_ordens.png) | `/producao/ordens` | producao ordens | TESTE |
| [20_producao_realizada.png](gestao/manufatura/20_producao_realizada.png) | `/producao/realizada` | producao realizada | TESTE |
| [21_producao_planejado-realizado.png](gestao/manufatura/21_producao_planejado-realizado.png) | `/producao/planejado-realizado` | producao planejado-realizado | TESTE |
| [22_analises_oee.png](gestao/manufatura/22_analises_oee.png) | `/analises/oee` | analises oee | TESTE |
| [23_analises_horas-utilizacao.png](gestao/manufatura/23_analises_horas-utilizacao.png) | `/analises/horas-utilizacao` | analises horas-utilizacao | TESTE |
| [24_analises_paradas.png](gestao/manufatura/24_analises_paradas.png) | `/analises/paradas` | analises paradas | TESTE |
| [25_analises_qualidade.png](gestao/manufatura/25_analises_qualidade.png) | `/analises/qualidade` | analises qualidade | TESTE |
| [26_analises_tempo-padrao-real.png](gestao/manufatura/26_analises_tempo-padrao-real.png) | `/analises/tempo-padrao-real` | analises tempo-padrao-real | TESTE |
| [27_analises_cronoanalise.png](gestao/manufatura/27_analises_cronoanalise.png) | `/analises/cronoanalise` | analises cronoanalise | TESTE |
| [28_analises_capacidade-gargalos.png](gestao/manufatura/28_analises_capacidade-gargalos.png) | `/analises/capacidade-gargalos` | analises capacidade-gargalos | TESTE |
| [29_analises_confiabilidade.png](gestao/manufatura/29_analises_confiabilidade.png) | `/analises/confiabilidade` | analises confiabilidade | TESTE |
| [30_auditoria_apontamentos.png](gestao/manufatura/30_auditoria_apontamentos.png) | `/auditoria/apontamentos` | auditoria apontamentos | TESTE |
| [31_auditoria_inconsistencias.png](gestao/manufatura/31_auditoria_inconsistencias.png) | `/auditoria/inconsistencias` | auditoria inconsistencias | TESTE |
| [32_auditoria_confiabilidade.png](gestao/manufatura/32_auditoria_confiabilidade.png) | `/auditoria/confiabilidade` | auditoria confiabilidade | TESTE |
| [33_relatorios_gerencial.png](gestao/manufatura/33_relatorios_gerencial.png) | `/relatorios/gerencial` | relatorios gerencial | TESTE |
| [34_relatorios_producao.png](gestao/manufatura/34_relatorios_producao.png) | `/relatorios/producao` | relatorios producao | TESTE |
| [35_relatorios_perdas.png](gestao/manufatura/35_relatorios_perdas.png) | `/relatorios/perdas` | relatorios perdas | TESTE |
| [36_relatorios_indicadores.png](gestao/manufatura/36_relatorios_indicadores.png) | `/relatorios/indicadores` | relatorios indicadores | TESTE |
| [37_relatorios_dados-analiticos.png](gestao/manufatura/37_relatorios_dados-analiticos.png) | `/relatorios/dados-analiticos` | relatorios dados-analiticos | TESTE |
| [38_rastreabilidade_op-produto.png](gestao/manufatura/38_rastreabilidade_op-produto.png) | `/rastreabilidade/op-produto` | rastreabilidade op-produto | TESTE |
| [39_rastreabilidade_linha-do-tempo.png](gestao/manufatura/39_rastreabilidade_linha-do-tempo.png) | `/rastreabilidade/linha-do-tempo` | rastreabilidade linha-do-tempo | TESTE |
| [40_rastreabilidade_lote-material-nesting.png](gestao/manufatura/40_rastreabilidade_lote-material-nesting.png) | `/rastreabilidade/lote-material-nesting` | rastreabilidade lote-material-nesting | TESTE |
| [41_andon.png](gestao/manufatura/41_andon.png) | `/andon` | andon | TESTE |
| [42_mapa_fabrica.png](gestao/manufatura/42_mapa_fabrica.png) | `/mapa-fabrica` | mapa fabrica | TESTE |
| [43_produto_simulado_filtros.png](gestao/manufatura/43_produto_simulado_filtros.png) | `/manufatura/tempo-padrao` | produto simulado filtros | TESTE |
| [44_recalculo_estimativas_em_execucao.png](gestao/manufatura/44_recalculo_estimativas_em_execucao.png) | `/manufatura/tempo-padrao` | recalculo estimativas em execucao | TESTE |
| [45_recalculo_status.png](gestao/manufatura/45_recalculo_status.png) | `/manufatura/tempo-padrao` | recalculo status | TESTE |

### Gestão da Qualidade — qualidade

| Captura | Fluxo / rota | Estado / finalidade | Dados |
| --- | --- | --- | --- |
| [01_visao_geral_perfil.png](gestao/qualidade/01_visao_geral_perfil.png) | `/inicio/visao-geral` | visao geral perfil | TESTE |
| [02_cotas_produtos.png](gestao/qualidade/02_cotas_produtos.png) | `/qualidade/cotas` | cotas produtos | TESTE |
| [03_modal_cadastrar_produto.png](gestao/qualidade/03_modal_cadastrar_produto.png) | `/qualidade/cotas` | modal cadastrar produto | TESTE |
| [04_editor_cotas_novo_produto.png](gestao/qualidade/04_editor_cotas_novo_produto.png) | `/qualidade/cotas` | editor cotas novo produto | TESTE |
| [05_editor_cotas_multiplas.png](gestao/qualidade/05_editor_cotas_multiplas.png) | `/qualidade/cotas` | editor cotas multiplas | TESTE |
| [06_editar_cotas_existentes.png](gestao/qualidade/06_editar_cotas_existentes.png) | `/qualidade/cotas` | editar cotas existentes | TESTE |
| [07_inicio_setores.png](gestao/qualidade/07_inicio_setores.png) | `/inicio/setores` | inicio setores | TESTE |
| [08_inicio_alertas.png](gestao/qualidade/08_inicio_alertas.png) | `/inicio/alertas` | inicio alertas | TESTE |
| [09_inicio_pausas.png](gestao/qualidade/09_inicio_pausas.png) | `/inicio/pausas` | inicio pausas | TESTE |
| [10_inicio_chamadas.png](gestao/qualidade/10_inicio_chamadas.png) | `/inicio/chamadas` | inicio chamadas | TESTE |
| [11_inicio_ia.png](gestao/qualidade/11_inicio_ia.png) | `/inicio/ia` | inicio ia | TESTE |
| [12_consulta-operacional_visao-geral.png](gestao/qualidade/12_consulta-operacional_visao-geral.png) | `/consulta-operacional/visao-geral` | consulta-operacional visao-geral | TESTE |
| [13_consulta-operacional_recursos.png](gestao/qualidade/13_consulta-operacional_recursos.png) | `/consulta-operacional/recursos` | consulta-operacional recursos | TESTE |
| [14_consulta-operacional_ops-em-andamento.png](gestao/qualidade/14_consulta-operacional_ops-em-andamento.png) | `/consulta-operacional/ops-em-andamento` | consulta-operacional ops-em-andamento | TESTE |
| [15_consulta-operacional_tempo-mes.png](gestao/qualidade/15_consulta-operacional_tempo-mes.png) | `/consulta-operacional/tempo-mes` | consulta-operacional tempo-mes | TESTE |
| [16_producao_ordens.png](gestao/qualidade/16_producao_ordens.png) | `/producao/ordens` | producao ordens | TESTE |
| [17_producao_realizada.png](gestao/qualidade/17_producao_realizada.png) | `/producao/realizada` | producao realizada | TESTE |
| [18_producao_planejado-realizado.png](gestao/qualidade/18_producao_planejado-realizado.png) | `/producao/planejado-realizado` | producao planejado-realizado | TESTE |
| [19_analises_oee.png](gestao/qualidade/19_analises_oee.png) | `/analises/oee` | analises oee | TESTE |
| [20_analises_horas-utilizacao.png](gestao/qualidade/20_analises_horas-utilizacao.png) | `/analises/horas-utilizacao` | analises horas-utilizacao | TESTE |
| [21_analises_paradas.png](gestao/qualidade/21_analises_paradas.png) | `/analises/paradas` | analises paradas | TESTE |
| [22_analises_qualidade.png](gestao/qualidade/22_analises_qualidade.png) | `/analises/qualidade` | analises qualidade | TESTE |
| [23_analises_tempo-padrao-real.png](gestao/qualidade/23_analises_tempo-padrao-real.png) | `/analises/tempo-padrao-real` | analises tempo-padrao-real | TESTE |
| [24_analises_cronoanalise.png](gestao/qualidade/24_analises_cronoanalise.png) | `/analises/cronoanalise` | analises cronoanalise | TESTE |
| [25_analises_capacidade-gargalos.png](gestao/qualidade/25_analises_capacidade-gargalos.png) | `/analises/capacidade-gargalos` | analises capacidade-gargalos | TESTE |
| [26_analises_confiabilidade.png](gestao/qualidade/26_analises_confiabilidade.png) | `/analises/confiabilidade` | analises confiabilidade | TESTE |
| [27_auditoria_apontamentos.png](gestao/qualidade/27_auditoria_apontamentos.png) | `/auditoria/apontamentos` | auditoria apontamentos | TESTE |
| [28_auditoria_inconsistencias.png](gestao/qualidade/28_auditoria_inconsistencias.png) | `/auditoria/inconsistencias` | auditoria inconsistencias | TESTE |
| [29_auditoria_confiabilidade.png](gestao/qualidade/29_auditoria_confiabilidade.png) | `/auditoria/confiabilidade` | auditoria confiabilidade | TESTE |
| [30_relatorios_gerencial.png](gestao/qualidade/30_relatorios_gerencial.png) | `/relatorios/gerencial` | relatorios gerencial | TESTE |
| [31_relatorios_producao.png](gestao/qualidade/31_relatorios_producao.png) | `/relatorios/producao` | relatorios producao | TESTE |
| [32_relatorios_perdas.png](gestao/qualidade/32_relatorios_perdas.png) | `/relatorios/perdas` | relatorios perdas | TESTE |
| [33_relatorios_indicadores.png](gestao/qualidade/33_relatorios_indicadores.png) | `/relatorios/indicadores` | relatorios indicadores | TESTE |
| [34_relatorios_dados-analiticos.png](gestao/qualidade/34_relatorios_dados-analiticos.png) | `/relatorios/dados-analiticos` | relatorios dados-analiticos | TESTE |
| [35_rastreabilidade_op-produto.png](gestao/qualidade/35_rastreabilidade_op-produto.png) | `/rastreabilidade/op-produto` | rastreabilidade op-produto | TESTE |
| [36_rastreabilidade_linha-do-tempo.png](gestao/qualidade/36_rastreabilidade_linha-do-tempo.png) | `/rastreabilidade/linha-do-tempo` | rastreabilidade linha-do-tempo | TESTE |
| [37_rastreabilidade_lote-material-nesting.png](gestao/qualidade/37_rastreabilidade_lote-material-nesting.png) | `/rastreabilidade/lote-material-nesting` | rastreabilidade lote-material-nesting | TESTE |
| [38_andon.png](gestao/qualidade/38_andon.png) | `/andon` | andon | TESTE |
| [39_mapa_fabrica.png](gestao/qualidade/39_mapa_fabrica.png) | `/mapa-fabrica` | mapa fabrica | TESTE |
| [40_filtro_produto_cotas.png](gestao/qualidade/40_filtro_produto_cotas.png) | `/qualidade/cotas` | filtro produto cotas | TESTE |
| [41_editar_template_simulado.png](gestao/qualidade/41_editar_template_simulado.png) | `/qualidade/cotas` | editar template simulado | TESTE |

### Pintura — fluxo geral

| Captura | Fluxo / rota | Estado / finalidade | Dados |
| --- | --- | --- | --- |
| [01_selecao_recurso.png](operadores/pintura-fluxo-geral/01_selecao_recurso.png) | `/operador` | selecao recurso | TESTE |
| [02_posto_pintura.png](operadores/pintura-fluxo-geral/02_posto_pintura.png) | `/operador` | posto pintura | TESTE |
| [03_op_roteiro_carregado.png](operadores/pintura-fluxo-geral/03_op_roteiro_carregado.png) | `/operador` | op roteiro carregado | TESTE |
| [04_confirmacao_etapa.png](operadores/pintura-fluxo-geral/04_confirmacao_etapa.png) | `/operador` | confirmacao etapa | TESTE |
| [05_etapa_pintura_selecionada.png](operadores/pintura-fluxo-geral/05_etapa_pintura_selecionada.png) | `/operador` | etapa pintura selecionada | TESTE |
| [06_modal_iniciar.png](operadores/pintura-fluxo-geral/06_modal_iniciar.png) | `/operador` | Exceção operacional: etapa anterior pendente, requer crachá autorizado | TESTE |
| [07_roteiro_simulado.png](operadores/pintura-fluxo-geral/07_roteiro_simulado.png) | `/operador` | roteiro simulado | TESTE |
| [08_apontamento_iniciado.png](operadores/pintura-fluxo-geral/08_apontamento_iniciado.png) | `/operador` | apontamento iniciado | TESTE |
| [09_fila_expandida.png](operadores/pintura-fluxo-geral/09_fila_expandida.png) | `/operador` | fila expandida | TESTE |
| [10_modal_parada.png](operadores/pintura-fluxo-geral/10_modal_parada.png) | `/operador` | modal parada | TESTE |
| [11_busca_motivo_parada.png](operadores/pintura-fluxo-geral/11_busca_motivo_parada.png) | `/operador` | busca motivo parada | TESTE |
| [12_motivo_selecionado.png](operadores/pintura-fluxo-geral/12_motivo_selecionado.png) | `/operador` | motivo selecionado | TESTE |
| [13_estado_parado.png](operadores/pintura-fluxo-geral/13_estado_parado.png) | `/operador` | estado parado | TESTE |
| [14_retomada.png](operadores/pintura-fluxo-geral/14_retomada.png) | `/operador` | retomada | TESTE |
| [15_modal_retrabalho.png](operadores/pintura-fluxo-geral/15_modal_retrabalho.png) | `/operador` | modal retrabalho | TESTE |
| [16_estado_retrabalho.png](operadores/pintura-fluxo-geral/16_estado_retrabalho.png) | `/operador` | estado retrabalho | TESTE |
| [17_modal_finalizacao.png](operadores/pintura-fluxo-geral/17_modal_finalizacao.png) | `/operador` | modal finalizacao | TESTE |
| [18_finalizacao_quantidades_operador.png](operadores/pintura-fluxo-geral/18_finalizacao_quantidades_operador.png) | `/operador` | finalizacao quantidades operador | TESTE |
| [19_apontamento_finalizado.png](operadores/pintura-fluxo-geral/19_apontamento_finalizado.png) | `/operador` | apontamento finalizado | TESTE |
| [20_historico_expandido.png](operadores/pintura-fluxo-geral/20_historico_expandido.png) | `/operador` | historico expandido | TESTE |
| [21_atividade_sem_op.png](operadores/pintura-fluxo-geral/21_atividade_sem_op.png) | `/operador` | atividade sem op | TESTE |
| [22_estado_atividade_sem_op.png](operadores/pintura-fluxo-geral/22_estado_atividade_sem_op.png) | `/operador` | estado atividade sem op | TESTE |
| [23_parada_posto_sem_op.png](operadores/pintura-fluxo-geral/23_parada_posto_sem_op.png) | `/operador` | parada posto sem op | TESTE |

### Dobra — Caldeiraria

| Captura | Fluxo / rota | Estado / finalidade | Dados |
| --- | --- | --- | --- |
| [01_op_dobra_checklist_pendente.png](operadores/dobra-caldeiraria/01_op_dobra_checklist_pendente.png) | `/operador` | op dobra checklist pendente | TESTE |
| [02_finalizar_bloqueado_antes_setup.png](operadores/dobra-caldeiraria/02_finalizar_bloqueado_antes_setup.png) | `/operador` | finalizar bloqueado antes setup | TESTE |
| [03_confirmacao_setup.png](operadores/dobra-caldeiraria/03_confirmacao_setup.png) | `/operador` | confirmacao setup | TESTE |
| [04_checklist_primeira_peca.png](operadores/dobra-caldeiraria/04_checklist_primeira_peca.png) | `/operador` | checklist primeira peca | TESTE |
| [05_cota_fora_tolerancia.png](operadores/dobra-caldeiraria/05_cota_fora_tolerancia.png) | `/operador` | cota fora tolerancia | TESTE |
| [06_modal_autorizacao_responsavel.png](operadores/dobra-caldeiraria/06_modal_autorizacao_responsavel.png) | `/operador` | modal autorizacao responsavel | TESTE |
| [07_cracha_responsavel_preenchido.png](operadores/dobra-caldeiraria/07_cracha_responsavel_preenchido.png) | `/operador` | cracha responsavel preenchido | TESTE |
| [08_retrabalho_liberado.png](operadores/dobra-caldeiraria/08_retrabalho_liberado.png) | `/operador` | retrabalho liberado | TESTE |
| [09_refugo_primeira_peca_cracha.png](operadores/dobra-caldeiraria/09_refugo_primeira_peca_cracha.png) | `/operador` | refugo primeira peca cracha | TESTE |
| [10_medicoes_conformes.png](operadores/dobra-caldeiraria/10_medicoes_conformes.png) | `/operador` | medicoes conformes | TESTE |
| [11_primeira_peca_aprovada_estado.png](operadores/dobra-caldeiraria/11_primeira_peca_aprovada_estado.png) | `/operador` | Primeira peça aprovada após retrabalho; estado observado Retrabalho | TESTE |
| [12_conclusao_apos_aprovacao.png](operadores/dobra-caldeiraria/12_conclusao_apos_aprovacao.png) | `/operador` | conclusao apos aprovacao | TESTE |
| [13_produto_sem_cotas_editor.png](operadores/dobra-caldeiraria/13_produto_sem_cotas_editor.png) | `/operador` | produto sem cotas editor | TESTE |
| [14_cotas_padrao_preenchidas.png](operadores/dobra-caldeiraria/14_cotas_padrao_preenchidas.png) | `/operador` | cotas padrao preenchidas | TESTE |
| [15_template_cadastrado_medicao.png](operadores/dobra-caldeiraria/15_template_cadastrado_medicao.png) | `/operador` | template cadastrado medicao | TESTE |
| [16_primeira_peca_conforme_produto_novo.png](operadores/dobra-caldeiraria/16_primeira_peca_conforme_produto_novo.png) | `/operador` | primeira peca conforme produto novo | TESTE |
| [17_aprovacao_volta_producao.png](operadores/dobra-caldeiraria/17_aprovacao_volta_producao.png) | `/operador` | aprovacao volta producao | TESTE |

## Assets e referências visuais

[Catálogo de assets com origem, destino e finalidade](assets/ASSETS.md). São 51 binários reais usados pelas interfaces, 6 folhas CSS e 6 arquivos de referência de componentes/configuração; originais preservados e deduplicação por SHA-256.

- [Ícones](assets/icones/) — navegação, ações, setores e equipamentos.
- [Logos](assets/logos/) — gestão e operador.
- [Imagens](assets/imagens/) — avatares e recursos físicos.
- [Fontes](assets/fontes/README.md) — fontes nativas do sistema; sem binário fictício.
- [Estilos](assets/estilos/) — tokens, cores, tamanhos, layout e estilos de telas.
- [Componentes de referência](assets/estilos/componentes_referencia/) — shells, página, mapa e resolução dos assets.

## Validação do pacote

212 PNGs com assinatura válida, dimensões registradas e sem duplicatas de conteúdo. Índice e [manifesto](capturas.json) enumeram todas as capturas. Assets conferidos por SHA-256. Amostras de gestão, checklist da Dobra e finalização da Pintura conferidas visualmente. Nenhuma lógica de negócio foi alterada.