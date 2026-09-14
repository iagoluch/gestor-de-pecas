# Homologação Extrema — Gestor de Peças Web

> **HISTÓRICO — NÃO USAR COMO AMBIENTE ATUAL.** O banco dedicado desta homologação foi removido em 27/08/2026 após backup validado. Não recriar/apontar o runtime atual para ele. Consulte `ROADMAP.md` para o estado vigente.

> Registro histórico da homologação de 20/08/2026. Menções à interface
> removida e à pendência de aprovação de OEE/FTT são obsoletas e servem
> apenas como evidência daquele baseline.

## Resultado executivo

**Gate técnico no ambiente isolado: APROVADO.**  
**Gate para entrada em produção corporativa: COM RESSALVAS.**

Em 20/08/2026 foi executada uma homologação real, reproduzível e isolada do Gestor de Peças Web. O banco operacional não recebeu escrita. Um banco exclusivo foi criado, carregado duas vezes para demonstrar idempotência, reconciliado por SQL direto, serviços e API e preservado ao final para auditoria.

Resultado consolidado:

- 53/53 verificações da reconciliação: `PASS`;
- 263/263 testes Python: `OK`;
- 9/9 testes Web: `PASS`;
- build Web de produção: `PASS`;
- 30/30 rotas de domínio avaliadas: HTTP 200;
- 24/24 consultas gerenciais concorrentes: sucesso;
- 39 screenshots de rotas/resoluções e duas folhas de contato;
- CSV analítico: 108 linhas, BOM UTF-8 e acentos preservados.

## Ambiente e isolamento

As informações abaixo estão sanitizadas e não contêm senha.

| Papel | Host | Porta | Banco | Usuário |
|---|---|---:|---|---|
| Operacional — somente leitura para copiar usuários | `10.10.1.248` | 54321 | `gestor_pecas` | `gestor_app` |
| Teste comum — não utilizado para a carga final | `10.10.1.248` | 54321 | `gestor_pecas_test` | `gestor_app` |
| Homologação extrema — leitura/escrita autorizada | `10.10.1.248` | 54321 | `gestor_pecas_test_homologacao_extrema_20260820` | `gestor_app` |

Barreiras implementadas:

- recusa automática se o alvo coincidir com o banco operacional ou teste comum;
- exigência dos termos `test` e `homolog` no nome do alvo;
- truncamento restrito ao nome exato do banco dedicado;
- DSNs exibidas somente em formato sanitizado;
- usuários copiados por leitura do operacional, sem exposição de hashes ou credenciais;
- limpeza destrutiva separada, desativada por padrão e protegida por confirmação nominal dupla.

[Confirmado] A segunda execução do seed retornou `created: false` e reproduziu exatamente os mesmos totais.  
[Confirmado] Uma verificação final em transação somente leitura encontrou zero OPs `HOMEXT%`, zero tarefas `T-HOM-%` e zero operadores com a fonte da homologação no banco operacional.  
[Confirmado] O banco exclusivo foi preservado. O script de limpeza não foi executado com `--drop`.

## Golden dataset

O período simulado vai de 11/08/2026 06:00 a 20/08/2026 21:30 e cobre Corte, Dobra, Usinagem, Serra, Solda e Pintura, múltiplos turnos e perfis de recurso heterogêneos.

| Métrica | Total confirmado |
|---|---:|
| OPs / operações / apontamentos | 120 / 120 / 120 |
| Eventos canônicos de quantidade | 149 |
| Planejado / bom / refugo / retrabalho | 7.200 / 4.968 / 72 / 26 |
| Tarefas / planos de Corte / apontamentos de Corte | 24 / 48 / 30 |
| Nestings concluídos | 20 |
| Eventos de Destaque | 44 |
| Crachás fictícios / usuários normais copiados | 12 / 11 |
| Inconsistências deliberadas | 12 |

Estados das OPs: 72 Finalizado, 12 Em processo, 12 Aguardando, 12 Parada, 6 Setup e 6 Retrabalho.

O dataset inclui recursos excelentes, bons, médios, ruins, críticos, ociosos e com dados incompletos. Valores ausentes permanecem visíveis, sem conversão silenciosa para zero.

## Validação das regras industriais

### Quantidade e qualidade

- Quantidade boa, refugo e retrabalho foram conciliados em SQL, serviço e API.
- Não há origem duplicada nos eventos de quantidade.
- Não há quantidade boa inválida.
- Existem 24 OPs concluídas com refugo separado, demonstrando que refugo não completa o planejado.
- O detalhamento por setor e recurso mantém a mesma fonte canônica.

### Setup, Retrabalho e Parada

- Setup e Retrabalho aparecem explicitamente no dataset e na classificação de estados.
- Setup permanece produtivo.
- Dez paradas manuais sem OP foram aceitas e classificadas separadamente.
- Causas ausentes permanecem como lacuna auditável.
- As regressões automatizadas cobrem o acesso a Setup/Retrabalho a partir de OP aberta, mesmo antes do início produtivo.

### Turnos

- Existem três turnos, intervalos e exceção de calendário.
- Foram conciliadas 18 interrupções automáticas exatamente nos limites oficiais de 17:30 e 21:30.
- Interrupção automática permanece programada e não é confundida com parada manual.

### Simultaneidade, rateio e conflito

- Uma sessão física de 7.200 segundos foi compartilhada por duas OPs.
- A soma dos rateios foi exatamente 7.200 segundos.
- O tempo físico não foi multiplicado.
- Um conflito físico intencional de 1.800 segundos permaneceu exposto como conflito/desconhecido.

### Atividade sem OP

Dez atividades produtivas sem OP foram registradas e mantidas como produtivas, conforme regra canônica.

## Corte, Nesting, Destaque e Solda

- Cada um dos 48 planos de Corte mantém seu próprio tempo previsto.
- Existem 30 apontamentos de Corte, 20 concluídos, com tempos previstos e realizados distintos.
- O conjunto contém Laser Ensis 3015 e Plasma TerraBlade 4, materiais, espessuras e programas variados.
- A fila Web apresenta os dados por nesting sem fundir seus tempos.
- Os 44 eventos de Destaque permanecem separados dos apontamentos de máquina.
- Solda possui tela de seleção de estação e foi verificada nas três resoluções de referência.

## Analytics, Management View e rastreabilidade

As visões gerenciais, operacionais, de qualidade, perdas, setups, paradas, capacidade, auditoria, confiabilidade, relatórios e rastreabilidade responderam com dados do banco exclusivo.

[Confirmado] A fonte do estado físico é `eventos_estado_recurso`.  
[Confirmado] A fonte das quantidades é `eventos_quantidade_producao`.  
[Confirmado] O Management View não possui módulo visual de Correção/Edição.  
[Confirmado] A OP `HOMEXT00001` possui timeline de rastreabilidade e texto longo em UTF-8.

### Indicadores ainda não oficiais

Disponibilidade, Performance, FTT e OEE não foram fabricados para fazer a tela parecer completa. O backend devolveu `parcial` ou `dados_insuficientes`, acompanhado de motivo e fonte, porque suas regras finais ainda não foram oficialmente confirmadas.

Isso é comportamento correto do contrato, não falha da homologação.

## API, segurança, filtros e exportação

Foram exercitadas 30 rotas de domínio. Todas responderam HTTP 200 com uma sessão gerencial válida.

Controles negativos:

- chamada sem autenticação: 401;
- login inválido: 401;
- operador tentando acessar Management View: 403;
- período final anterior ao inicial: 400;
- cookie de sessão: `HttpOnly`.

Paginação e exportação:

- página 2 com tamanho 17;
- 108 registros e sete páginas no recorte;
- CSV preservado em `tests/homologacao_extrema/exports/dados_analiticos.csv`;
- 108 linhas, BOM UTF-8 e acentos íntegros.

## Tempo real e multiusuário

O endpoint SSE foi validado com dois clientes conectados:

- ambos receberam a mesma publicação;
- ambos receberam o evento inicial de conexão;
- o `live_tick` continuou chegando sem depender de novo apontamento ou mutação no banco.

No frontend, o primeiro conjunto de dados permanece visível durante a atualização em segundo plano disparada pelo SSE. Isso elimina o estado de carregamento piscando continuamente em Auditoria e Relatórios.

Foram executadas 24 consultas gerenciais concorrentes com até oito threads: 24/24 responderam com sucesso, e o maior tempo observado na reconciliação final foi 452,794 ms.

## Performance

O limite de homologação foi 2.000 ms por consulta relevante.

| Medição | Resultado |
|---|---:|
| Management overview | 104,181 ms |
| Management alerts | 317,254 ms |
| Auditoria | 333,112 ms |
| Confiabilidade | 364,515 ms |
| Relatório analítico | 316,059 ms |
| Visão geral repetida — mediana | 61,838 ms |
| Visão geral repetida — p95 | 78,007 ms |
| Visão geral repetida — máximo | 103,628 ms |

Durante a homologação foi identificado um custo de aproximadamente 3,5 segundos causado por consultas repetidas ao mesmo catálogo de turnos, intervalos e exceções durante um único caso de uso. A correção introduziu cache local apenas durante a instância do serviço, sem estado global e sem alterar cálculo. Um teste de regressão comprova o reaproveitamento.

## Homologação visual

Foram preservadas e validadas as 24 telas oficiais atuais do PySide6 em 1920×1061, além do catálogo histórico necessário aos testes. A Web foi capturada nas resoluções:

- 1920×1080;
- 1600×900;
- 1366×768.

O conjunto possui 39 screenshots, cobrindo oito rotas gerenciais críticas nas três resoluções e os fluxos do operador de Destaque, Dobra, Usinagem, Serra, Corte, Pintura e Solda. Duas folhas de contato permitem inspeção rápida do conjunto.

Não foram alteradas a tipografia, a redação aprovada, a identidade cromática ou a ordem estrutural. A correção visual do Qt apenas restaurou propriedades de identificação e fundo transparente dos textos da fila de Corte no layout atual.

## Bugs encontrados e corrigidos

### 1. Consultas analíticas lentas

- Sintoma: Auditoria, Confiabilidade e relatório analítico levavam aproximadamente 3,5 s.
- Causa: catálogo de calendário consultado repetidamente dentro da mesma execução.
- Correção: cache local por instância para turnos, intervalos e exceções.
- Evidência: endpoints entre aproximadamente 317 e 345 ms; regressão automatizada aprovada.

### 2. Atualização SSE escondia dados

- Sintoma: refresh a cada segundo recolocava telas em estado de carregamento.
- Causa: o hook tratava refresh de fundo como carregamento inicial.
- Correção: manter os dados visíveis durante atualizações do mesmo caminho.
- Evidência: novo teste Web de tempo real e screenshots sem loading residual.

### 3. Contrato visual do catálogo Qt

- Sintoma: três testes oficiais falhavam por ausência local das referências e propriedades esperadas na fila atual.
- Correção: recuperação das 24 referências oficiais e 27 legadas a partir do backup local, restauração das propriedades `cutQueueText` e alinhamento do teste à redação atual já aprovada.
- Evidência: regressão completa 263/263.

## Reprodutibilidade

### Recriar/recarregar o banco exclusivo

```powershell
C:\Python314\python.exe tests\homologacao_extrema\seed_homologacao_extrema.py
```

### Reconciliar

```powershell
C:\Python314\python.exe tests\homologacao_extrema\reconcile.py
```

### Abrir a Web no banco exclusivo

```powershell
C:\Python314\python.exe tests\homologacao_extrema\run_web_homologacao.py
```

Acesse `http://127.0.0.1:8000/` e autentique-se com um dos usuários normais já existentes e copiados para o banco exclusivo. Nenhuma credencial é registrada neste relatório. O apelido `gestor-peca` não foi forçado porque depende da configuração de DNS/hosts do notebook e não é necessário para a homologação.

### Limpeza controlada

O arquivo `cleanup_homologacao_extrema.py` apenas mostra o alvo por padrão. A remoção exige `--drop` e `--confirm-name gestor_pecas_test_homologacao_extrema_20260820`. Essa ação não foi executada; o banco permanece disponível.

## Evidências entregues

- `tests/homologacao_extrema/seed_homologacao_extrema.py`
- `tests/homologacao_extrema/reconcile.py`
- `tests/homologacao_extrema/cleanup_homologacao_extrema.py`
- `tests/homologacao_extrema/run_web_homologacao.py`
- `tests/homologacao_extrema/capture_visual_homologacao.py`
- `tests/homologacao_extrema/expected_results.json`
- `tests/homologacao_extrema/expected_results.md`
- `tests/homologacao_extrema/scenarios.md`
- `tests/homologacao_extrema/seed_result.json`
- `tests/homologacao_extrema/actual_results.json`
- `tests/homologacao_extrema/api_matrix.json`
- `tests/homologacao_extrema/test_run_summary.json`
- `tests/homologacao_extrema/exports/dados_analiticos.csv`
- `docs/screenshots/homologacao-extrema/`
- `docs/HOMOLOGACAO_MATRIZ.md`

## Gate e condições para produção

### Gate técnico isolado: APROVADO

Não há falha bloqueante nos testes executados. Banco, backend, API e Web reconciliam os totais ouro e preservam as regras canônicas avaliadas.

### Gate corporativo: COM RESSALVAS

Antes de entrada irrestrita em produção, ainda são necessárias:

1. definição e homologação, pela TI, do mecanismo definitivo de integração com Protheus/TOTVS;
2. aprovação oficial das fórmulas de OEE, FTT, Performance e Capacidade;
3. troca do segredo efêmero por segredo persistente e implantação com HTTPS;
4. política validada de backup, restore, monitoramento e observabilidade;
5. broker compartilhado para SSE caso a implantação use mais de um processo/worker;
6. aceite presencial do fluxo completo por operadores e liderança, na rede e nos dispositivos reais;
7. validação específica da integração Qlik enquanto ela ainda for necessária.

[Não verificado] A integração corporativa e o ambiente físico de chão de fábrica não foram exercitados nesta homologação isolada.  
[Inferência] Cumpridas as condições acima, o risco técnico residual do núcleo testado é baixo; essa inferência não substitui o aceite da Manufatura e da TI.
