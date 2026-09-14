# Promoção do banco REAL do Gestor: schema 11 → 19

Atualizado em: 01/09/2026
Alvo: `gestor_pecas` (banco REAL do Gestor de Peças)
Estado hoje: **schema 11**; a aplicação exige **19**
Situação: **preparado e ensaiado. Nada foi executado no REAL.**

Este documento é o procedimento para quando a TI autorizar a promoção. Ele não
autoriza nada por si.

## 1. Situação verificada em leitura

`scripts/auditar_migracao_real_11_19.py --alvo real` abre a conexão com
`default_transaction_read_only=on` e declara `SET TRANSACTION READ ONLY`: um
`INSERT`/`UPDATE`/DDL acidental seria recusado pelo próprio PostgreSQL, não
apenas evitado por disciplina.

Resultado em 01/09/2026 (`docs/evidencias/AUDITORIA_MIGRACAO_REAL_11_19_2026-09-01.json`):

| Verificação | Resultado |
|---|---|
| `schema_migrations` | **11** (última: 19/08/2026) |
| Gap | 11 → 19 |
| `uq_catalogo_operacao_op_recurso` (migration 16 faz `DROP` sem `IF EXISTS`) | **presente** |
| Duplicatas em `(codigo_op, numero_operacao, codigo_recurso)` | **nenhuma** |
| `catalogo_operacoes_op.ativo` | `NOT NULL` |
| Linhas que violariam a `CHECK` da migration 18 | **0** |
| Categorias em `eventos_estado_recurso` | `producao` (5), `fora_turno` (1) — ambas aceitas pela `CHECK` da migration 12 |
| Tabelas/colunas que as migrations criam | **nenhuma existe de antemão** |
| Achados bloqueantes | **nenhum** |
| Veredito | `apto_para_promocao: true` |

Volumes: `catalogo_pcp_ops` 4.542, `catalogo_sigmanest_planos_corte` 425,
`historico` 131, `catalogo_operacoes_op` 66, `apontamentos_corte` 22,
`usuarios` 11, `eventos_estado_recurso` 6, `eventos_apontamento_operador` 4,
`apontamentos_operacionais` 2, `eventos_quantidade_producao` 0,
`catalogo_recursos_pcfactory` 0.

Nenhuma tabela chega perto de exigir janela longa.

## 2. Risco por migration

| # | Finalidade | O que faz | Risco sobre dados existentes | Rollback |
|---|---|---|---|---|
| 12 | estado de fila e ausência de demanda | `DROP CONSTRAINT IF EXISTS` + nova `CHECK` em `eventos_estado_recurso.categoria` | **Único ponto com validação sobre dados antigos nesta faixa.** Um valor histórico fora da lista abortaria. Verificado: só `producao` e `fora_turno`. | restaurar a `CHECK` anterior |
| 13 | contexto de retorno de parada/setup | 2 `ADD COLUMN` nulas + 2 `CHECK` sobre elas | nulo: as colunas nascem `NULL` e a `CHECK` aceita `NULL` | `DROP COLUMN` |
| 14 | IA Industrial | 3 `CREATE TABLE` + 3 índices | nulo: só cria. FK para `usuarios(id)`, que existe (11 linhas) | `DROP TABLE` |
| 15 | relatórios e distribuição | 4 `CREATE TABLE` + 4 índices | nulo: só cria. FKs para `usuarios(id)` | `DROP TABLE` |
| 16 | inbox TOTVS ProductionOrder | relaxa `data_emissao`, 9 `ADD COLUMN`, **`DROP CONSTRAINT uq_catalogo_operacao_op_recurso` sem `IF EXISTS`**, 3 índices `UNIQUE`/parciais, 1 `CREATE TABLE` | dois pontos: a constraint precisa existir (verificado) e `uq_catalogo_operacao_legacy` é `UNIQUE` sobre o trio já povoado (verificado: sem duplicatas). `DROP NOT NULL` é relaxamento, sempre seguro | recriar a constraint e `DROP` de colunas/índices |
| 17 | procedência SigmaNEST | 7 `ADD COLUMN` nulas + 1 índice parcial | nulo | `DROP COLUMN` |
| 18 | marco terminal do roteiro | `ADD COLUMN marco_terminal BOOLEAN NOT NULL DEFAULT FALSE`, `DROP NOT NULL` em `tipo_setor`, **nova `CHECK` validada contra todas as linhas**, índice parcial | a `CHECK` exige que toda linha antiga tenha `tipo_setor` e `ativo` preenchidos, porque nasce com `marco_terminal = FALSE`. Verificado: 0 violações. O `ADD COLUMN` com default constante não reescreve a tabela no PostgreSQL 11+ | `DROP CONSTRAINT` + `DROP COLUMN` |
| 19 | outbox outbound TOTVS | 2 `CREATE TABLE` + 6 índices | nulo: só cria. FK para `eventos_apontamento_operador(id)`, que existe | `DROP TABLE` |

Varredura pelos itens perigosos pedidos:

- **`DROP TABLE`** — nenhum;
- **`DROP COLUMN`** — nenhum;
- **`ALTER TYPE` / mudança de tipo** — nenhum;
- **`NOT NULL` novo** — nenhum. Só dois relaxamentos (`data_emissao` na 16,
  `tipo_setor` na 18) e uma coluna nova já com default;
- **`UNIQUE` nova sobre dados antigos** — uma, `uq_catalogo_operacao_legacy` na
  16; verificada sem duplicatas;
- **`CHECK` nova sobre dados antigos** — duas, migrations 12 e 18; ambas
  verificadas;
- **`UPDATE` em massa / backfill / transformação de dado** — **nenhum**. As
  migrations 12–19 não alteram uma única linha existente;
- **renome de tabela ou coluna** — nenhum;
- **mudança de chave primária** — nenhuma.

**Dependências de ordem:** 16 antes de 18 (a 18 mexe em colunas que a 16 tocou);
19 depois de 16/18 (FK para `eventos_apontamento_operador`, presente desde a 4).
`apply_migrations` já executa estritamente em ordem crescente, cada versão com
seus statements, tudo dentro de uma transação com `pg_advisory_xact_lock`,
`lock_timeout` e `statement_timeout` configuráveis.

## 3. Ensaio executado fora do REAL

O REAL só pôde ser lido, então **nenhum dado real foi copiado**. O ensaio
(`scripts/ensaiar_migracao_11_19.py`) monta um banco de schema 11 de verdade,
semeia os **mesmos volumes e as mesmas distribuições** medidas na auditoria e
roda a MESMA `apply_migrations`.

Resultado em 01/09/2026 (`docs/evidencias/ENSAIO_MIGRACAO_11_19_2026-09-01.json`):

- partida `11`, chegada `19`;
- **duração das migrations 12→19: 0,293 s** com 4.542 OPs e 425 planos de corte;
- contagens antes e depois **idênticas** nas dez tabelas conferidas;
- tabelas novas criadas e vazias;
- `constraints_nao_validadas: []`, `indices_invalidos: []`,
  `linhas_incoerentes_marco_terminal: 0`;
- aplicação sobe e reconhece a versão 19;
- consultas canônicas respondem sobre os dados anteriores;
- outbox exercitada: reserva, falha de transporte → `RETRY`, backoff agendado e
  tentativa registrada no histórico.

Regressão automatizada equivalente em `tests/test_migration_chain_11_19.py`
(8 testes), incluindo a prova negativa: com uma linha incompatível plantada, a
migration 18 **falha** e a cadeia para sem deixar o schema pela metade.

## 4. Procedimento de promoção

Executar somente com autorização da TI, em janela combinada.

### Pré-promoção

1. **Parar tudo que escreve** no `gestor_pecas`: backend Web, workers,
   sincronizações SigmaNEST/TOTVS, jobs agendados.
2. Confirmar que não restou sessão ativa:
   ```sql
   SELECT pid, usename, application_name, state, query_start
   FROM pg_stat_activity
   WHERE datname = 'gestor_pecas' AND pid <> pg_backend_pid();
   ```
3. Rodar o pré-voo e arquivar a saída:
   ```bash
   python scripts/auditar_migracao_real_11_19.py --alvo real
   ```
   Exige `apto_para_promocao: true` e `achados: []`.
4. **Backup completo** (`pg_dump -Fc`) e registro das contagens de referência
   das dez tabelas conferidas.
5. **Validar o backup restaurando-o** em um banco descartável. Um backup não
   restaurado não é backup.

### Promoção

6. Aplicar as migrations com a própria aplicação, nunca com SQL improvisado:
   ```bash
   python -c "from app.database import Database; Database().close()"
   ```
   `apply_migrations` roda 12→19 em ordem, sob advisory lock, e grava
   `schema_migrations`.
7. Validar o schema:
   ```bash
   python scripts/auditar_migracao_real_11_19.py --alvo real
   ```
   Esperado agora: `schema_version_registrada: 19` e `gap: sem gap`. Conferir
   também `pg_constraint.convalidated` e `pg_index.indisvalid` sem pendências, e
   as contagens iguais às do passo 4.

### Pós-promoção

8. Subir a aplicação e conferir o startup: versão 19 reconhecida, sem erro de
   migration no log.
9. **Smoke tests** de leitura: login, Tela do Operador em um posto, roteiro de
   uma OP, Andon, um relatório. Nada de escrita ainda.
10. Um apontamento de ida e volta em uma OP combinada com a Manufatura, com
    `GESTOR_TOTVS_OUTBOX_ENABLED=false`: prova que a operação normal funciona
    sem envolver integração.
11. **Só então**, no momento aprovado do piloto, habilitar a outbox — ver §5.
12. Observar a fila por pelo menos um turno:
    ```bash
    python scripts/totvs_outbox_admin.py metricas
    python scripts/totvs_outbox_admin.py listar --status ERROR
    ```

### Critérios objetivos de ABORTAR

Abortar e restaurar o backup, sem tentar corrigir o banco à mão, se:

- qualquer migration falhar (a transação já reverte sozinha; não repetir sem
  entender a causa);
- `apto_para_promocao` vier `false` no pré-voo;
- qualquer contagem das dez tabelas divergir do passo 4;
- existir constraint com `convalidated = false` ou índice com
  `indisvalid = false`;
- a aplicação não subir ou registrar erro de migration;
- qualquer consulta canônica do smoke test falhar;
- o `schema_migrations` ficar em versão intermediária.

**Não improvisar `ALTER`/`UPDATE` no banco durante o piloto.** Se algo divergir,
o caminho é restaurar o backup, corrigir a migration no código, reensaiar em
ambiente isolado e reagendar.

## 5. Ativar a outbox é uma decisão separada

Schema preparado **não é** integração ligada. Depois da promoção o REAL fica em
19 com `totvs_outbox` vazia e inerte, porque as chaves nascem `false`:

```dotenv
GESTOR_TOTVS_OUTBOX_ENABLED=false
GESTOR_TOTVS_OUTBOX_WORKER_ENABLED=false
```

Ligar exige, no momento aprovado do piloto e não antes:

1. `GESTOR_TOTVS_OUTBOUND_ENDPOINT` do ambiente correto;
2. credenciais corretas para esse ambiente;
3. `GESTOR_TOTVS_OUTBOUND_WASTE_CODE_MAP_JSON` preenchido pela Manufatura/PCP;
4. `GESTOR_TOTVS_OUTBOUND_STOP_REASON_MAP_JSON` preenchido pela Manufatura/PCP;
5. worker validado com `python scripts/totvs_outbox_admin.py worker --once`;
6. `GESTOR_TOTVS_OUTBOX_ENABLED=true` e depois
   `GESTOR_TOTVS_OUTBOX_WORKER_ENABLED=true`, nesta ordem, para que a fila
   comece a acumular antes de qualquer entrega.

Sem os mapas dos passos 3 e 4, refugos e paradas **não se perdem**: entram na
outbox como `ERROR` bloqueado, guardando quantidade, motivo do Gestor e
intervalo, prontos para serem lançados no Protheus depois via
`python scripts/totvs_outbox_admin.py reprocessar --id <id>`.
