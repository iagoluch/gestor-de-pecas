# Progresso da lógica industrial — backend consolidado v11 — 19/08/2026

> Registro histórico. A arquitetura vigente está em `WEB_ARCHITECTURE.md`.
> A pendência aqui registrada para FTT/OEE foi superada pela validação de
> 25/08/2026 e não descreve mais a implementação vigente.

## Situação

As coletas do PCFactory e do Management View já são suficientes para a fundação atual. Não é necessário outro crawler amplo. Nova coleta deve ser cirúrgica e responder uma lacuna objetiva.

Tudo o que pode ser implementado sem inventar decisão da Manufatura/TI foi consolidado no backend desta versão.

## Principais avanços

1. `eventos_estado_recurso` passou a ser a fonte física canônica para períodos que já possuem esses registros.
2. Início, Parada, Retomada, Setup, Retrabalho, Corte/Nesting e fim de turno sincronizam a timeline física do recurso.
3. OPs simultâneas no mesmo estado não multiplicam o tempo físico.
4. Estados simultâneos incompatíveis são preservados como `desconhecido` e auditados.
5. Rateio mantém tempo físico separado do tempo atribuído à OP e exige conservação do total.
6. Quantidades usam eventos canônicos; produção realizada continua significando somente peças boas.
7. Calendário ganhou intervalos exatos e exceções sem inventar a posição de intervalos agregados.
8. Auditoria cruza estado físico, OPs, turno, calendário e rateio.
9. Management/Analytics preferem a fonte física canônica e só usam timeline de OP como fallback histórico/granular quando apropriado.
10. Ausência de Parada/Setup na fonte física canônica não faz o serviço voltar para uma timeline de OP potencialmente conflitante.
11. `FrontendBackendFacade` concentra os casos de uso que PySide6 e futura Web devem consumir.
12. `capabilities()` expõe regras, fontes e pendências para impedir regra duplicada no frontend.
13. Normalização de códigos/datas foi removida da dependência direta do driver PostgreSQL, reduzindo acoplamento de services.
14. `app.database` passou a carregar `Database` sob demanda; metadado de schema está em módulo sem dependência do driver.
15. `AGENTS.md` foi atualizado com a precedência da Manufatura, arquitetura Web futura, fontes canônicas e exigência de UTF-8.

## Schema

Versão atual: **11**.

A migration v11 inclui metadados do estado físico do recurso, intervalos exatos de turno e exceções de calendário.

## Validação desta etapa

- compilação dos módulos alterados: OK;
- **112 testes executáveis** de regras industriais, operador, Corte, produção, lookup, analytics, rateio, relatórios, permissões, runtime, catálogo e resiliência Qlik: OK;
- a suíte canônica v11 está incluída nesse total e possui 11 testes específicos;
- testes que exigem `psycopg`, PySide6, `requests_ntlm` ou DPAPI/Windows não são declarados aprovados neste container quando a dependência/plataforma não existe.

## Pendências que não devem ser inventadas

- regra final de FTT/OEE com refugo/retrabalho;
- mapeamento técnico do banco/serviço corporativo;
- estratégia oficial de rateio por cenário;
- carga oficial de calendários/feriados/exceções.

Esses itens não impedem iniciar a discussão/implementação do frontend porque o backend já sinaliza `nao_configurado`, `parcial` ou `dados_insuficientes` em vez de fabricar valores.
