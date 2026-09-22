# Pente-fino geral — 2026-09-21

Segunda rodada do pente-fino de qualidade, continuando (não refazendo) a rodada
de `docs/PENTE_FINO_2026-09-14.md`. Foco desta rodada, por escopo acordado:

- bugs reais com evidência (não hipótese);
- duplicação de lógica/regra entre módulos separados;
- arquivos-lixo (movidos para `_quarentena_revisar/`, nada apagado);
- testes quebrados ou ausentes para comportamento crítico já implementado;
- otimizações claras de baixo risco.

Fora de escopo por já terem sido auditados: segurança (auditoria de 2026-09-14)
e a regra "recursos apontáveis vs. sincronizados".

## Panorama

| Sinal | Antes | Depois |
| --- | --- | --- |
| Duplicações estruturais entre arquivos (varredura AST) | 2 | **0** |
| Teste quebrado em `tests/test_wave6a_calendario_operacional.py` | 1 falha (pré-existente no HEAD) | **0** |
| Imports/locais mortos apontados pelo pyflakes em `mes`/`backend`/`scripts` | 4 | **0** |
| Arquivos de 0 byte rastreados no repositório | 1 | **0** (movido para quarentena) |
| Testes executados nesta rodada | — | **141 passed, 1 skipped, 186 subtests** |

A limpeza da rodada anterior se manteve e agora está protegida pelo
`.gitignore`. Um único arquivo novo foi para `_quarentena_revisar/` (§5).

---

## 1. Bugs e falhas reais

### 1.1 Teste obsoleto escondendo uma contradição de regra de negócio — CORRIGIDO

`tests/test_wave6a_calendario_operacional.py` falhava **no HEAD limpo**, antes de
qualquer alteração desta rodada (verificado com baseline isolado).

O caso `test_dentro_do_turno_e_ociosidade_e_nunca_sem_demanda` afirmava que
`ManufacturingRules.resource_has_no_demand(category=fila, window_kind=<dentro do
turno>)` deveria ser `False`. Isso contradiz diretamente
`tests/test_no_demand_time_bucket.py::test_regra_de_ausencia_de_demanda_tem_fonte_unica`,
que trava a regra atual: fila **sem** OP é ausência de demanda; fila **com** OP
não é.

Causa raiz (forense de git): o commit `782f2cd` — *"fix: alinhar apontamentos e
estados operacionais"* — reescreveu deliberadamente a regra, de "só o marcador
`retorno_turno_sem_demanda` conta" para "qualquer fila sem OP conta", e atualizou
três arquivos de teste irmãos. O arquivo do wave6a ficou para trás.

Portanto **não** era uma decisão de negócio ambígua (a regra nova já está travada
por teste explícito), e sim um teste obsoleto. Foi corrigido preservando a
intenção original do caso — ociosidade é fila **com OP**, e a presença da ordem é
a evidência de demanda — e acrescentado o caso complementar que documenta a
generalização introduzida por `782f2cd`.

### 1.2 `resource_has_no_demand`: dois defeitos latentes — REPORTADO, NÃO CORRIGIDO

Ambos alteram comportamento de domínio, então seguem a regra "reporte, não
decida". Nenhum deles se manifesta em produção hoje.

**(a) Parâmetro inerte.** `ManufacturingRules.state_is_no_demand` ainda aceita
`interruption_type`, mas o corpo nunca o lê — resquício da regra antiga. Os
chamadores continuam passando o argumento. É uma assinatura que promete uma
influência que não existe.

**(b) `explicit_shift_return` inverte o resultado fora de turno.** Reproduzido:
com `category=fora_turno` e `window_kind=fora_turno`, o retorno é `True`; ao
acrescentar `explicit_shift_return=True`, passa a `False`. O ramo do
`explicit_shift_return` curto-circuita o *fallthrough* de fora-de-turno, ou seja,
o marcador de retorno de turno *reduz* a detecção de ausência de demanda em vez
de reforçá-la.

Hoje isso é inalcançável: `mes/services/shift_boundary.py:212` só anexa o
marcador `SHIFT_START_NO_DEMAND_TYPE` sobre um estado `fila`, nunca sobre
`fora_turno`. É uma armadilha para o próximo chamador, não um bug ativo.

**Decisão pendente do usuário:** remover o parâmetro inerte e o ramo
`explicit_shift_return` (simplificando a regra para o que os testes já travam),
ou preservá-los com intenção explícita.

---

## 2. Duplicação de lógica entre módulos

### 2.1 `transport_failure_kind()` — CORRIGIDO (primeira correção da rodada, já validada)

Classificação de falha de transporte HTTP estava copiada em três gateways TOTVS.
Consolidada em `mes/integrations/totvs/transport.py` e consumida por
`mes/integrations/totvs/on_demand_gateway.py`,
`mes/integrations/totvs/product_model_gateway.py` e
`backend/integrations/totvs_wspcp.py`. Validado previamente com 111/111 em
`tests/test_totvs_outbound.py`, `tests/test_totvs_on_demand.py` e
`tests/test_totvs_integration.py`. Confirmados os três imports nesta rodada; não
foi mexido de novo.

### 2.2 `_merge_intervals()` — CORRIGIDO

A mesma álgebra de união de intervalos (ordenar, descartar vazios, fundir
sobrepostos e adjacentes) existia duplicada em `mes/analytics/physical_time.py` e
`mes/services/calendar.py`. Era o último item aberto do §3.2 do relatório de
2026-09-14 — os outros dois já haviam sido resolvidos (`_transport_failure_kind`
acima, `_json_value` em refatoração de 17/09).

Consolidada em **`mes/analytics/intervals.py`** (`merge_intervals`). A camada foi
escolhida verificando a direção real de import: `mes.services` importa
`mes.analytics`, nunca o contrário — logo a casa comum é `analytics`. O
`calendar.py` tinha **7 chamadas** ao helper local, todas reescritas.

### 2.3 Varredura completa — nenhuma outra duplicação

Foi executado um detector estrutural por AST (normalizando constantes, para
pegar cópias com literais trocados) sobre `mes/`, `app/`, `backend/` e
`simulacao/`, em corpos de função com 3+ instruções e 150+ caracteres
normalizados. Depois da consolidação do 2.2 o resultado é **zero** duplicatas
entre arquivos. O código não tem, hoje, corpos copiados relevantes.

---

## 3. Código morto

Quatro itens removidos, todos confirmados por leitura do uso real (não apenas
pelo pyflakes):

| Arquivo | Item | Evidência |
| --- | --- | --- |
| `mes/services/management_insights.py` | `standard_total`, `actual_total` | Resquícios de antes de `performance_components` passar a usar o canônico `overview["kpi_time_bases"]`; calculados e descartados |
| `mes/integrations/totvs/outbound_mapper.py` | `from dataclasses import replace` | Os usos nas linhas 44/48 são `value.replace(microsecond=0)` — **método** de `datetime`, não a função importada |
| `scripts/seed_dados_ficticios.py` | `date` em `from datetime import ...` | Os usos nas linhas 414/809 são `now.date()` — **método**, não a classe importada |

**Correção de um erro do relatório anterior.** O §3.1 de
`docs/PENTE_FINO_2026-09-14.md` classificou os dois últimos como "falso
positivo" do linter e os preservou. A classificação estava errada: em ambos os
casos o nome importado é sombreado por um *método homônimo* do objeto usado no
call site, que é exatamente o padrão que engana a leitura rápida. Após a
remoção, o pyflakes fica limpo nesses arquivos e os testes seguem verdes.

---

## 4. Achados em `simulacao/` — REPORTADOS, NÃO CORRIGIDOS

Os dois mudam saída/semântica de relatório de simulação, o que é decisão de
produto.

### 4.1 `simulacao/preflight.py:157` — exceção engolida

```python
try:
    schema = observer.escalar("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
except Exception as exc:
    schema = None
```

`exc` é vinculado e descartado. A checagem seguinte reporta apenas
`schema is not None and int(schema) == int(SCHEMA_VERSION)`, então **falha de
conexão, falta de permissão e divergência real de versão produzem exatamente o
mesmo diagnóstico**. O `CLAUDE.md` do projeto proíbe tratamento silencioso de
erro; a correção natural é levar o motivo para os `dados` da checagem, mas isso
altera o contrato de saída do preflight.

### 4.2 `simulacao/report.py:97` — agregado calculado e nunca publicado

`codigos_erro = Counter(f"{classification}::{error_code or result}" ...)` é
computado sobre `erros` e nunca consumido. É o **único** `Counter` do arquivo sem
tabela correspondente: `codigos_bloqueio` (linha 96) é renderizado na 358,
`acoes` na 302, `validacoes_por_codigo` na 364. O relatório detalha erros
técnicos e do simulador em tabelas item a item, mas não tem a visão agregada por
código — o padrão sugere uma tabela omitida, não sobra de código. Publicá-la
muda o conteúdo do relatório de simulação, por isso fica para decisão.

---

## 5. Arquivos-lixo e organização

Varredura praticamente limpa nesta rodada:

- raiz com apenas 13 arquivos legítimos;
- nenhum artefato de 0 byte no código do projeto (os restantes são `py.typed`
  e `REQUESTED` dentro de `.venv/`, de terceiros);
- `reiniciar_build.py` (novo na raiz desde a rodada anterior) verificado:
  referência válida para `tools/reiniciar_servidor.py`.

**Um único item movido para `_quarentena_revisar/`:**
`.github/instructions/tds-vscode-1-0-2.instructions.md` — arquivo **de 0 byte**,
rastreado pelo git desde o commit baseline `67c89e0` e nunca alterado desde
então. Era o único ocupante de `.github/instructions/`. Um arquivo de
instruções vazio não tem conteúdo a entregar a nenhum consumidor. Movido com
`git mv` preservando o caminho relativo (`_quarentena_revisar/.github/instructions/`),
registrado como *rename* — nada foi apagado e a reversão é imediata.

**Observação (não é código do projeto):** existem 4 diretórios
`.claude/worktrees/agent-*` com cópias completas do repositório anteriores à
consolidação. São artefatos de ferramenta, estão no `.gitignore` e ocupam espaço;
podem ser removidos quando conveniente, mas ficam fora do escopo de um pente-fino
de código.

---

## 6. Itens herdados da rodada anterior, ainda abertos

Nenhum foi tratado nesta rodada (fora do escopo acordado ou sem mudança de
estado desde 14/09):

- **§1.4 — conexão ODBC do SigmaNEST.** `backend/integrations/sigmanest_sqlserver.py:~157`
  ainda usa `with self._abrir() as conexao:`; em `pyodbc` o `with` faz *commit*,
  não *close*. A conexão fica pendurada até o GC.
- **§4.3 —** `scripts/test_groq_*.py` com nome que o pytest coleta como teste.
- **§7 —** `psutil` usado sem estar declarado nas dependências.

---

## 7. Validação executada

Proporcional ao risco, restrita aos módulos tocados:

| Suíte | Motivo | Resultado |
| --- | --- | --- |
| `tests/test_industrial_analytics.py`, `tests/test_oee_consistency.py`, `tests/test_oee_evolution_equivalence.py` | consumidores de `physical_time`/`calendar` (merge de intervalos) | verde |
| `tests/test_wave6a_calendario_operacional.py`, `tests/test_no_demand_time_bucket.py` | regra de ausência de demanda (item 1.1) | verde |
| `tests/test_management_insights.py`, `tests/test_execution_to_management_consistency.py` | remoção de locais mortos | verde |
| `tests/test_totvs_outbound.py` | remoção do import `replace` | verde |

Totais: **89 passed, 1 skipped, 23 subtests** no primeiro bloco e **52 passed,
163 subtests** no segundo. A suíte completa não foi executada — a política do
projeto pede validação do módulo afetado, e nenhuma alteração desta rodada é
transversal.

## 8. Risco remanescente

Baixo. As correções são de três tipos: consolidação sem mudança de
comportamento (2.2), alinhamento de um teste a uma regra já travada por outro
teste (1.1) e remoção de código comprovadamente morto (3). Os achados que
alterariam comportamento — `resource_has_no_demand` (1.2), preflight (4.1) e
relatório de simulação (4.2) — foram deixados intactos, aguardando decisão.
