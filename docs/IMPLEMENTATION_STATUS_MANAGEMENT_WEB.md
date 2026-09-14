# Estado da fundação gerencial e preparação Web

> Registro histórico anterior à consolidação Web-only. Consulte
> `WEB_MIGRATION_STATUS.md` para o estado vigente. A pendência de fórmula de
> OEE/FTT registrada abaixo foi superada em 25/08/2026.

## Escopo desta evolução

Esta versão prepara o Gestor de Peças para alimentar as referências gerenciais sem converter a aplicação para Web agora. O apontamento PySide6 continua sendo a apresentação operacional vigente; as regras novas ficam fora da UI para poderem ser reutilizadas posteriormente por API e frontend Web.

## Entregue no backend

- schema v11 com fatos industriais, estado físico canônico, calendário detalhado, regras de fim de turno e migrations versionadas;
- eventos independentes de quantidade: boa, refugo e retrabalho;
- taxonomia semântica de status preparada para regras de disponibilidade, performance e qualidade;
- estado físico canônico de recurso independente de OP, já integrado às transições operacionais e a Corte/Nesting;
- calendário e turno por recurso, com intervalos exatos opcionais e exceções;
- capacidade configurável por recurso sem inventar valores atuais;
- participação temporal de operadores;
- sessão física do recurso e rateio explícito de tempo por OP;
- consolidação analítica por recurso para impedir que OPs simultâneas dupliquem horas físicas;
- detecção explícita de sobreposição com estados conflitantes, sem escolher uma classificação por suposição;
- inconsistências estruturadas para Auditoria e Confiabilidade dos Dados;
- motor temporal que separa lead time de produção, parada, setup, retrabalho e fora de turno;
- interrupção automática programada nos limites oficiais de 17:30 e 21:30, sem quantidade e sem finalizar a OP;
- Tempo MES apto a usar eventos em vez de assumir `fim - início` como tempo produtivo;
- contratos e serviços independentes de Qt, incluindo `FrontendBackendFacade.capabilities()` para a futura API;
- Corte com tempo individual por nesting, incluindo previsto, real e desvio;
- documentação da arquitetura Web futura e referências visuais dos gestores dentro do projeto.

## Regra de produção

Produção realizada é composta somente por peças boas. Refugo e retrabalho são armazenados como fatos separados. O histórico legado permanece por compatibilidade operacional, mas não deve ser a fonte canônica de quantidade gerencial.

## Corte: granularidade por nesting

Cada nesting é tratado como execução temporal própria. O backend e o painel MES de Corte expõem uma linha individual contendo, quando disponível:

- tarefa;
- plano/programa;
- número/sequência do nesting;
- máquina;
- material;
- espessura;
- tempo previsto;
- início real;
- fim real;
- tempo real;
- desvio absoluto/percentual;
- operador de início/fim;
- status.

Os totais do painel passam a ser derivados das execuções individuais no período, evitando perder a granularidade ao agrupar por tarefa.

## Métricas que não são inventadas

O backend não publica OEE, Disponibilidade, Performance, FTT ou capacidade restante como zero quando faltarem dados. Os contratos permitem sinalizar `sem_registros`, `dados_insuficientes`, `parcial` ou `nao_configurado`.

Para fechar esses indicadores em produção ainda será necessário cadastrar/confirmar os dados oficiais, principalmente:

- calendário e turnos reais por recurso;
- classificação semântica oficial dos status;
- dados de qualidade suficientes para FTT no filtro consultado;
- tempos padrão validados;
- estratégia oficial de rateio nas situações simultâneas;
- capacidade oficial dos recursos;
- causa raiz, lote, inspeções e quantidade de retrabalho quando esses dados passarem a ser coletados na operação.

## Arquitetura preparada para Web

A direção futura é:

```text
Raspberry Pi + Chromium (linha) ─┐
PC/Notebook (gestores) ──────────┼── Frontend Web
Celular/Tablet autorizado ───────┘       │
                                          ▼
                                    API HTTP/SSE/WS
                                          │
                                 domínio/services Python
                                          │
                                repositories/integrations
                                          │
                              ambiente corporativo/Protheus
```

A futura conversão não deve reimplementar as regras no frontend. A API deverá chamar os mesmos services usados nesta versão. `eventos_estado_recurso` é a fonte física preferencial; timeline por OP é fallback histórico/granular quando apropriado.

## Cenários de uso Web previstos

### Linha

Os Raspberry Pi atuais poderão abrir o apontamento pelo Chromium em modo kiosk. A estação não deverá precisar instalar Python/PySide6 quando a migração estiver concluída.

### Gestores e diretoria

Management View, Consulta, Produção, Análises, Auditoria, Rastreabilidade e Relatórios serão apropriados para navegador. O acesso remoto de usuários em viagem deverá passar exclusivamente pelo mecanismo de segurança aprovado pela TI.

## Segurança para a futura etapa Web

A migração Web deverá prever HTTPS, autenticação forte/SSO quando disponível, autorização no backend, acesso externo via infraestrutura aprovada pela TI, logs de acesso, proteção de sessão/token, nenhuma credencial no frontend e nenhuma conexão direta navegador→banco.

## Itens deliberadamente não executados nesta versão

- não foi criado servidor FastAPI;
- não foi criado frontend React/Next.js;
- não foi convertido o apontamento para navegador;
- não foram substituídas as telas PySide6;
- não foram preenchidas regras industriais ainda não confirmadas;
- não foram fabricados dados de capacidade, turno, FTT ou causa raiz.

Isso mantém a estabilização atual do apontamento e reduz o risco da futura migração Web.

## Cobertura dos 20 pontos após esta evolução

| # | Ponto | Backend nesta versão |
|---|---|---|
| 1 | Management View — Visão Geral | OEE e componentes consumidos da fonte canônica; ausência de fatos permanece explícita |
| 2 | Management View — Produção | Boas/refugo/retrabalho separados; Corte entra por nesting |
| 3 | Management View — Setores | Tempos e produção agregáveis por setor |
| 4 | Management View — Perdas | Paradas/setup/retrabalho disponíveis; causa raiz depende de coleta/classificação |
| 5 | Consulta Operacional | Fluxo atual preservado e fatos canônicos disponíveis |
| 6 | Tempo MES | Motor temporal separa lead time e estados; Corte expõe cada nesting |
| 7 | Ordens de Produção | Dados existentes preservados; planejamento corporativo pode ampliar datas/prioridade |
| 8 | Planejado × Realizado | Contrato implementado com campos disponíveis; datas planejadas podem ficar indisponíveis |
| 9 | OEE | Regra validada e centralizada; valor não é inventado quando faltam fatos necessários |
| 10 | Paradas | Timeline e agregações físicas implementadas; duplicidades de OP simultânea são removidas do total |
| 11 | Setup | Timeline e agregações implementadas; tipos preparados |
| 12 | Qualidade | Fatos independentes implementados; FTT consome o mesmo indicador canônico |
| 13 | Cronoanálise | Estatísticas básicas implementadas a partir de tempo produtivo por peça |
| 14 | Capacidade & Gargalos | Cadastro/contrato de capacidade preparado; gargalo oficial depende da regra empresarial |
| 15 | Auditoria — Inconsistências | Motor central inicial implementado |
| 16 | Auditoria — Confiabilidade dos Dados | Contagens implementadas; percentual não é arbitrado |
| 17 | Auditoria de origem | IDs das fontes preservados nos contratos de drill-down |
| 18 | Rastreabilidade | Serviço por OP implementado, incluindo nestings relacionados quando disponíveis |
| 19 | Rateio | Sessão física, leitura por período e distribuição explícita implementadas; tempo atribuído permanece separado do físico |
| 20 | Drill-down / fonte lógica única | Camadas domain/contracts/analytics/services/repositories preparadas para Desktop/Web |

## Observação sobre estabilização

A estrutura nova não força o operador atual a preencher campos que ainda não foram aprovados para a rotina da linha. Os campos e serviços existem para evolução controlada; a interface PySide6 continua usando o fluxo estabilizado, exceto pela visualização gerencial do tempo individual de cada nesting de Corte.
