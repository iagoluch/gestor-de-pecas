# Pente-fino geral — 2026-09-14

Varredura ampla de bugs, otimização, compactação, organização e lixo em todas as
áreas do sistema (`mes/`, `app/`, `backend/`, `web/src/`, `simulacao/`,
`scripts/`, `tests/`, raiz). Sem git no projeto: nada foi apagado — o que é lixo
foi **movido** para `_quarentena_revisar/`, preservando o caminho relativo.

## Panorama

| Sinal | Antes | Depois |
| --- | --- | --- |
| Suíte Python (`unittest discover -s tests`) | 2 falhas + **1 erro** | **2 falhas, 0 erros** (899 testes, 363s) |
| Frontend `npx tsc -b` | limpo | limpo |
| Frontend `npx vitest run` | 156/156 | 156/156 |
| Arquivos soltos na raiz | 25 artefatos de 0 byte | 0 |

As duas falhas que restam são **as mesmas de antes** (item 1.2, à espera de
decisão de negócio). O erro foi resolvido. Nenhuma falha nova apareceu.

Duas observações de medição, registradas por honestidade:

- A execução de referência relatou 896 testes e a final, 899. A coleta hoje é
  determinística em 899 (`defaultTestLoader.discover`, zero falhas de import) e
  não há testes gerados dinamicamente (`load_tests`/`addTest`/`setattr`). Não
  consegui atribuir a diferença de 3 com certeza. O que importa para a
  comparação — mesmas 2 falhas, erro eliminado — não depende disso.
- Em uma das três execuções do `vitest` o resultado foi 155/156, enquanto a suíte
  Python completa disputava CPU e o Postgres de teste. As outras duas deram
  156/156, incluindo a execução final isolada. Trata-se de instabilidade sob
  carga, não de regressão: o frontend não foi tocado neste pente-fino. Não
  consegui capturar o nome do teste (as execuções seguintes passaram); se
  reaparecer, vale investigar como flake real.

Tamanho do código: `mes` 23.7k linhas · `tests` 32.3k · `app` 12.6k · `backend`
9.4k · `scripts` 8.9k · `simulacao` 7.2k · `web/src` 15.3k (81 arquivos).

---

## 1. Bugs e falhas reais

### 1.1 CORRIGIDO — Homologação Etapa 7A quebrada pela regra de refugo da Wave 5

**`scripts/homologar_totvs_e2e_etapa7a.py:237`** (seed do operador).

`tests/test_totvs_etapa7a_e2e.py` abortava com:

```
Ação canônica 'Finalizado' falhou: refugo_autorizacao_obrigatoria
O refugo precisa do crachá de um responsável autorizado para ser registrado.
```

Causa raiz: a Wave 5 passou a exigir crachá de responsável (`autorizador_retrabalho`)
para registrar refugo — `mes/services/operator_flow.py:1087` `_autorizar_refugo`.
O seed da homologação inseria o operador sem essa flag, e a coluna é
`BOOLEAN NOT NULL DEFAULT FALSE` (`app/database/migrations.py:1605`). O roteiro
da Etapa 7A aponta um refugo parcial de propósito, como evidência — então o
crachá único da homologação precisa acumular os dois papéis.

Correção: o `INSERT` passou a declarar `autorizador_retrabalho = TRUE`.
Verificado antes/depois: o teste ia a erro, agora passa (`Ran 1 test ... OK`).

### 1.2 ABERTO — decisão de negócio necessária: operações de Pintura repetidas

Duas falhas com **a mesma causa**:

- `tests/test_totvs_integration.py:251` `test_mapper_nao_inventa_setor_e_aplica_alias_laser_oficial_exato`
- `tests/test_totvs_postgres.py:440` `test_fixtures_idempotencia_upsert_stale_conflito_e_isolamento_por_op`

A fixture real `tests/fixtures/totvs/pend_productionorder_20260818165346_10796502001.xml`
(intocada desde 26/08) traz **três** atividades de Pintura distintas:

| ordem | nº operação | setor | recurso |
| --- | --- | --- | --- |
| 5 | 40 | Pintura | PINT.L |
| 6 | 50 | Pintura | JATO |
| 7 | 60 | Pintura | PINT.L |

O mapper hoje projeta as três (5 operações apontáveis no total). Os testes
esperam **4**, com a lista deduplicada e reordenada (`JATO`, `PINT.L`).

**Não alterei nada** — é uma regra de negócio com duas leituras razoáveis e
consequências opostas em produção:

- Se o comportamento atual estiver certo, os testes estão defasados desde a
  Wave 5.1, quando `PINT.L` virou posto oficial
  (`app/core/resource_mapping.py:94` `OFFICIAL_RESOURCE_SECTORS`). Antes disso
  as operações 40/60 caíam em "pendente de decisão" e só `JATO` sobrava.
- Se os testes estiverem certos, o mapper regrediu e passou a duplicar postos.

**A pergunta para você:** uma OP cujo roteiro passa **duas vezes** pelo mesmo
posto (operações 40 e 60 em `PINT.L`) deve gerar **duas** operações apontáveis
ou **uma**? Minha leitura técnica é que deve gerar duas — são etapas de
sequência diferentes, e deduplicar faria o operador perder um passo de pintura;
isso também combina com a filosofia conservadora do mapper ("não inventa setor",
"etapa preservada"). Mas isso muda o roteiro que chega ao chão de fábrica, então
não mexi sem sua confirmação. Confirmada a intenção, o ajuste é nas duas
asserções (o assunto real do primeiro teste é o alias `LASER`→`LASER1`, não a
contagem de Pintura).

### 1.3 Falha "conhecida" em `manufacturing_rules.py` — **não existe mais**

A memória de sessões anteriores registrava uma falha pré-existente ali.
`tests/test_manufacturing_rules.py` roda **7/7 OK**. O item pode ser encerrado.

### 1.4 Conexão ODBC do SigmaNEST devolvida só pelo GC — severidade baixa

**`backend/integrations/sigmanest_sqlserver.py:157`**

```python
with self._abrir() as conexao:
    cursor = conexao.cursor()
```

Em pyodbc, `with conexão:` faz commit/rollback mas **não fecha** a conexão, e o
cursor não está em `with`. Hoje o CPython recolhe os dois por contagem de
referência ao sair da função, então não há vazamento observável — mas é frágil
(depende do refcount) e destoa do resto do projeto. Correção sugerida:
`with closing(self._abrir()) as conexao, conexao.cursor() as cursor:`.
Não apliquei: é caminho de leitura do SigmaNEST e preferi não mexer em
integração no fim do dia.

---

## 2. Otimização de código, API e conexões

### 2.1 CORRIGIDO — conexão do pool aberta dentro de laço

**`app/database/database.py:2545` `iniciar_intervalo_automatico`**

A checagem de idempotência rodava **por recurso**, tomando uma conexão do pool a
cada volta:

```python
for row in self.listar_recursos_ativos_no_instante(instante):
    ...
    with self.connection() as connection, connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM eventos_estado_recurso WHERE UPPER(recurso) = UPPER(%s) ...")
```

Com N recursos ativos eram N conexões só para essa verificação, mais as de
`transicionar_estado_recurso`. O método vizinho `finalizar_intervalo_automatico`
(linha 2593) já fazia o certo: uma conexão, um `FOR UPDATE`, tudo dentro dela.

Correção: uma única leitura antes do laço monta o conjunto de recursos já
tratados; o laço passou a testar pertencimento em memória. Mesma predicação,
mesmo `instante`, N conexões → 1.

Validação: SQL novo executado **somente leitura** contra o banco de TESTE
(retorna a coluna `recurso`, como esperado); `tests/test_database_professionalization`,
`test_stage4b_factory_shift`, `test_wave6a_calendario_operacional`,
`test_operator_flow` e `test_intelligence_reports` → **106 testes OK** (64s, com
Postgres real).

Observação: a corrida leitura→escrita que existia antes **não corrompia dados** —
há índice único parcial `idx_estado_recurso_aberto` em
`eventos_estado_recurso (UPPER(recurso)) WHERE data_fim IS NULL`
(`app/database/migrations.py:536`) garantindo um único evento aberto por recurso.

### 2.2 Não é N+1 (falso positivo que vale registrar)

`mes/services/operator_flow.py:442` `_buscar_ativo` e `:455` `_buscar_conflito_ativo`
carregam todos os apontamentos ativos do setor e filtram em Python. Não é N+1
(é uma consulta só), mas é over-fetch em caminho quente do operador. Só vale
otimizar se o volume de apontamentos ativos por setor crescer muito — hoje não é
problema. Deixado como está.

### 2.3 Pool e cursores — saudáveis

`app/database/connection.py` está correto: `_ConnectionLease.close()` faz
rollback se a transação não estiver IDLE antes de devolver ao pool, e
`connection()` é context manager. Varredura por `.cursor()` fora de `with` em
`app/`, `backend/` e `mes/` encontrou **um único** caso (o 1.4 acima).

---

## 3. Compactação de `.py`

Nenhum problema objetivo: **0 erros de sintaxe, 0 definições duplicadas,
0 defaults mutáveis, 0 `except` nu** em `mes/`, `app/`, `backend/`, `simulacao/`.

### 3.1 Aplicado — imports mortos removidos (12)

`mes/services/resource_state.py` (`datetime`) · `simulacao/factory.py`
(`SEV_WARNING`) · `simulacao/monitors.py` (`timedelta`) · `simulacao/observatory.py`
(`Any`, `BackgroundTask`) · `simulacao/preflight.py` (`Path`) · `simulacao/runner.py`
(`timedelta`, `Any`) · `tests/test_intelligence_reports.py` (`BytesIO`) ·
`scripts/homologar_totvs_outbox_etapa6.py` (`datetime`) · `scripts/sanear_recursos.py`
(`resource_display_name`) · `scripts/seed_dados_ficticios.py` (`asdict`).

Todos os módulos reimportados com sucesso depois da edição. Dois candidatos eram
falso positivo (`replace` em `outbound_mapper.py`, `date` em
`seed_dados_ficticios.py`) e foram preservados. Dois foram deixados de fora de
propósito, por serem arquivos verificados nesta sessão:
`backend/api/routers/dev_observatory.py:28` (`get_database`) e
`tests/test_dev_observatory.py:15` (`datetime`) — remoção trivial quando quiser.

### 3.2 Documentado — duplicação real entre arquivos (3 casos, e só 3)

Comparação estrutural de **todas** as funções de `mes/`, `app/`, `backend/` e
`simulacao/` achou apenas três corpos idênticos em arquivos diferentes:

| função | locais |
| --- | --- |
| `_merge_intervals` | `mes/analytics/physical_time.py:160` · `mes/services/calendar.py:489` |
| `_json_value` | `mes/contracts/insights.py:15` · `mes/contracts/management.py:14` |
| `_transport_failure_kind` | `mes/integrations/totvs/on_demand_gateway.py:59` · `backend/integrations/totvs_wspcp.py:89` |

São helpers privados curtos (218–312 caracteres). Não consolidei: o ganho é
pequeno e cada unificação exige escolher um lar novo (módulo compartilhado) ou
criar acoplamento entre camadas — decisão que não vale tomar sem git no fim do
dia. `_json_value` é a mais fácil (mesmo pacote `mes/contracts/`) se quiser
atacar uma.

### 3.3 Documentado — funções grandes

55 funções acima de 100 linhas em produção. As maiores:

| função | linhas |
| --- | --- |
| `mes/services/management.py:36` `get_overview` | 515 |
| `mes/services/operator_flow.py:574` `executar` | 511 |
| `app/database/database.py:1919` `transicionar_apontamento_operador` | 391 |
| `app/database/database.py:507` `publicar_catalogo_sigmanest` | 355 |
| `app/database/database.py:4649` `transicionar_destaque_tarefa` | 273 |
| `mes/services/ai_service.py:95` `stream_message` | 284 |
| `mes/services/frontend_facade.py:262` `consulta_operacional` | 227 |

Não quebrei nenhuma. São o núcleo transacional do sistema, com testes densos em
volta; fatiar por estética, sem git e sem um bug que justifique, é risco puro.
Se for encarar, `get_overview` e `executar` são os melhores candidatos, e o
caminho seguro é extrair blocos para métodos privados um de cada vez, rodando
`test_operator_flow` + `test_execution_to_management_consistency` a cada passo.

---

## 4. Organização de pastas

### 4.1 Aplicado — raiz limpa

Os 25 arquivos soltos de 0 byte saíram da raiz (detalhe na seção 5). A raiz agora
tem só o que faz sentido: `README.md`, `AGENTS.md`, `ROADMAP.md`,
`requirements.txt`, `compose.yaml`, `.env*`, `iniciar_sistema_teste_cloudflare.py`
e os diretórios do projeto.

### 4.2 Documentado (NÃO aplicado) — `docs/` com 120 MB

| subpasta | tamanho |
| --- | --- |
| `docs/evidencias/` | 61 MB (sendo 60 MB em `simulacao_fabrica/`) |
| `docs/screenshots/` | 41 MB |
| `docs/references/` | 4,2 MB |
| 40 arquivos `.md` na raiz de `docs/` | — |

São dumps JSON de simulação e capturas de tela — evidência histórica, não
documentação de leitura. Recomendação: mover `evidencias/` e `screenshots/` para
um `artefatos/` (ou `evidencias/` na raiz) fora de `docs/`, deixando `docs/`
apenas com os `.md`. **Não executei**: são milhares de arquivos e vários
relatórios `.md` referenciam caminhos de evidência — sem git, um `mv` em massa
com links quebrados é exatamente o tipo de estrago difícil de desfazer. Vale
fazer em uma sessão dedicada, conferindo as referências.

### 4.3 Observação — `scripts/test_groq_*.py`

`scripts/test_groq_oee_real.py` e `scripts/test_groq_tool_call_real.py` têm
prefixo `test_` mas moram em `scripts/` e **chamam a API real da Groq**. A suíte
(`discover -s tests`) não os coleta, então não há risco hoje; mas o nome convida
ao acidente. Renomear para `verificar_groq_*.py` eliminaria a ambiguidade.

---

## 5. Arquivos inúteis — movidos para `_quarentena_revisar/`

**26 itens.** Nada foi apagado.

### 5.1 Artefatos de shell colado errado (25 arquivos, todos 0 byte)

`(init` · `,+` · `,session_title` · `0` · `ApiResponse` · `Este` · `None` ·
`OP.,+` · `PRODUTO.,+` · `bloqueio` · `call.method` · `dict` · `dict[str` ·
`div` · `div[data-tone` · `header` · `int` · `list[OrdemSintetica]` ·
`list[dict]` · `section` · `str` · `tuple[datetime` · `tuple[str` · `{,` · `{,+`

Evidência de que são lixo: (a) todos com **exatamente 0 byte**; (b) os nomes são
fragmentos de comando onde o `>` do shell virou redirecionamento
(`dict[str`, `tuple[datetime`, `div[data-tone`, `list[OrdemSintetica]` são
pedaços de anotação de tipo e de seletor CSS); (c) busca por `open("...")` /
`Path("...")` com esses nomes em todo `.py`/`.ts`/`.tsx` do projeto: **nenhuma
referência**.

### 5.2 `tests/homologacao_extrema.zip` (102 KB)

Snapshot do diretório `tests/homologacao_extrema/`, que continua no lugar e
íntegro. O zip contém os mesmos 15 arquivos **mais o `__pycache__/` com 5 `.pyc`** —
assinatura de um "zipar a pasta" casual. Redundante com o diretório vivo.

### 5.3 `__pycache__/_debug_andon.cpython-314.pyc`

O `_debug_andon.py` que você citou **já não existe** — só tinha ficado o bytecode
órfão na raiz. Movido junto.

### 5.4 O que NÃO foi mexido

- **Nenhum script de `scripts/`.** Nove têm zero referências
  (`homologar_totvs_op_sob_demanda_etapa62`, `homologar_totvs_soap_endpoint`,
  `import_totvs_production_order`, `limpar_cenario_gui`,
  `preencher_planejado_catalogo_status`, `preparar_desenhos_simulacao`,
  `run_simulacao_industrial`, `seed_cenario_gui`, `sync_test_users`), mas
  contagem de referência **não prova obsolescência** em ferramenta de CLI
  chamada à mão — `run_simulacao_industrial.py` é prova disso: zero referências e
  é a simulação industrial ativa. Nada de homologação foi tocado.
- `tests/andon_visual_preview.py` e `tests/web_preview_api.py`: referenciados em
  `.claude/launch.json`, são servidores de preview ativos.
- `tests/oee_preview_api.py`: só citado num relatório de 25/08, mas é um servidor
  de QA funcional de 993 bytes. Mantido.

---

## 6. Compactação dos testes — a hipótese não se confirmou

**Nenhum teste foi removido ou fundido, porque não há redundância real.**

Comparei os 896 testes por nome e por *impressão digital estrutural* do corpo
(AST normalizado, com literais e espaços neutralizados):

- **Corpos idênticos entre arquivos: 0 grupos.**
- **Nomes repetidos entre arquivos: 1** — `test_cota_fora_do_template_e_recusada`
  em `tests/test_quality_inspection.py:503` e
  `tests/test_wave6b_gate_setup_qualidade.py:353`. Inspecionados um a um: **não
  são duplicados**. O primeiro exercita `QualityService.registrar_peca` (aba
  Qualidade); o segundo, `FirstPieceService.registrar_checklist` (portão da
  primeira peça). É a mesma regra de negócio validada por **duas portas de
  entrada diferentes** — cobertura legítima, e justamente o tipo de par que
  parece redundante pelo nome e não é.

Ou seja: os nomes por "wave"/"stage" refletem a época em que a funcionalidade
entrou, não repetição de cobertura. `tests/` está grande (32,3k linhas) mas não
está inchado. Consolidar por semelhança de nome aqui **reduziria** cobertura.

---

## 7. Dependências

`requirements.txt` não declara `psutil`, mas `backend/observability/metrics.py:156`
e `simulacao/environment.py:169` o importam. **Não é bug**: os dois fazem import
tardio dentro de `try/except ImportError` com degradação graciosa — mesmo padrão
já documentado para o `pyodbc`. Sugestão cosmética: registrar `psutil` como
opcional comentado no `requirements.txt`, como já é feito com o `pyodbc`, para
quem instala do zero saber que a métrica de memória do Dev Observatory depende
dele.

---

## 8. Risco remanescente

1. **`_quarentena_revisar/` precisa da sua decisão.** Confirme e apague quando
   quiser. Confiança alta de que os 26 itens são descartáveis.
2. **Duas falhas de teste seguem abertas** (item 1.2), à espera da sua definição
   sobre posto repetido no roteiro. São as **mesmas duas** de antes do pente-fino:
   nada novo quebrou. Confirmado na execução final: `Ran 899 tests ...
   FAILED (failures=2, skipped=1)` — sem erros.
3. A mudança em `iniciar_intervalo_automatico` foi validada por 106 testes contra
   Postgres real e pelo SQL executado em leitura no banco de TESTE. A comparação
   de recurso passou de `UPPER()` no SQL dos dois lados para `UPPER()` no SQL
   contra `.upper()` no Python — equivalente para os códigos de recurso em uso
   (ASCII e acentuação latina comum).
4. Nada foi escrito no banco REAL, no TOTVS ou no SigmaNEST. A única consulta ao
   banco partiu de `load_postgres_config(testing=True)` e foi um `SELECT`.
