# Corte — SigmaNEST como fonte de planejamento (Qlik removido)

**Estado:** Fases A (engenharia reversa), B (contrato) e C (sincronização)
**CONCLUÍDAS** · migration 17 aplicada
**Atualização:** 27/08/2026
**Ambiente auditado:** `SVR-DBLANTEK\SIGMANEST` · `SNDBase2026` · SQL Server
2022 Express 16.0.1000.6 · login `ti_consulta` · **acesso somente leitura**

## 1. Decisão arquitetural

```text
TOTVS (Protheus)   → identidade da OP, produto, quantidade, roteiro
SigmaNEST (banco)  → tarefa, programa/nesting, composição de peças, máquina
Gestor de Peças    → correlaciona as duas fontes e executa o apontamento
Qlik               → REMOVIDO da arquitetura alvo
```

O apontamento continua sendo o fluxo canônico do Gestor. Não existe apontamento
SigmaNEST nem apontamento TOTVS.

## 2. Regra funcional obrigatória

**A OP pertence ao produto/peça.** Não existe OP da tarefa, do plano ou do
nesting. Tarefa, programa e nesting agrupam produtos, e cada produto pode estar
associado à sua OP.

Comprovado com dados reais (recorte de 01/08/2026 em diante):

```text
158 de 180 nestings (88%) contêm MAIS DE UMA OP
maior caso observado: programa 8560 / tarefa T3458 → 24 OPs distintas
tarefa T2414 → 121 programas
programa 7519 → 45 WOs e 40 peças distintas
```

É proibido modelar `tarefa.codigo_op`, `plano.codigo_op` ou `nesting.codigo_op`
como relação 1:1.

## 3. Estruturas confirmadas no banco real

| Objeto | Tipo | Linhas | Chave primária |
|---|---|---:|---|
| `Wo` | tabela | 19.247 | `WONumber` |
| `Part` | tabela | 19.995 | **(`WONumber`, `PartName`)** |
| `STPIPArc` | tabela | 189.171 | `AutoID` |
| `ProgArchive` | tabela | 35.513 | `AutoID` |
| `STOCK` | tabela | 388 | `SheetName` |
| `PartWithQtyInProcess` | view | 19.995 | — |
| `DashboardProgramData` | view | 189.171 | — |

Chaves estrangeiras declaradas que envolvem essas estruturas:

```text
Part.WONumber    → Wo.WONumber   (FK_part_Wo)
CTLPart.WONumber → Wo.WONumber   (FK_CTLPart_Wo)
```

Não existe FK declarada ligando `STPIPArc` ou `ProgArchive` às demais: a ligação
é por valor (`ProgramName`, `SheetName`, `WONumber`, `PartName`).

## 4. Cadeia comprovada com dado real

```text
Wo.WONumber = 00617399002
  → Part (WONumber, PartName) = (00617399002, PSM014003121)
      → STPIPArc  ProgramName=8501  SheetName=S420  QtyInProcess=1
          → ProgArchive  TaskName=T3432  MachineName=Amada_ensis
                         CompDate=2026-08-11 10:52:40
```

Semântica funcional:

| Conceito da fábrica | Estrutura SigmaNEST | Observação |
|---|---|---|
| **Tarefa** | `ProgArchive.TaskName` (`T####`) | agrupa programas; 1.991 tarefas distintas |
| **Programa / Plano** | `ProgArchive.ProgramName` | 8.179 distintos; **não** é uma OP |
| **Nesting** | `ProgArchive` (`ProgramName` + `SheetName` + `RepeatID` + `ArchivePacketID`) | a chapa física do programa |
| **Peça/produto** | `STPIPArc.PartName` + `WONumber` | **único lugar onde a OP existe** |
| **Máquina** | `ProgArchive.MachineName` | 2 valores: `Amada_ensis`, `Messer_XPR_300` |

`ProgArchive` é um **arquivo de eventos**: o mesmo programa/chapa aparece várias
vezes, um registro por `TransType` dentro de cada `ArchivePacketID`.

## 5. `WONumber == ProductionOrder.Number` — **COMPROVADO**

Método: as 4.542 OPs reais do Protheus presentes no `catalogo_pcp_ops` do banco
REAL do Gestor foram confrontadas com `Wo.WONumber` (ambos os lados em leitura).

```text
OPs do Protheus testadas          4.542
presentes em SigmaNEST.Wo           905  (19,9%)
ausentes                          3.637  (nunca programadas no Corte)
```

A ausência é esperada: nem toda OP passa por corte.

Conferência do produto nas 941 linhas `Part` correspondentes:

```text
produto idêntico ao Protheus      797  (84,7%)
produto é PREFIXO do Protheus     125  (13,3%)   ex.: IPCX04014279P → IPCX04014279
divergentes                        19  ( 2,0%)
```

**Conclusão normativa:** a chave de correlação é `WONumber` ↔ `codigo_op`, em
igualdade textual. O **produto não é chave** — em 15% dos casos ele difere
(sufixo corporativo ausente no SigmaNEST) e serve apenas para conferência.

Normalização necessária:

```text
espaços nas bordas em Wo.WONumber    0 linhas → nenhum trim obrigatório
espaços nas bordas em Part.WONumber  0 linhas
WONumber em caixa baixa             65 linhas → comparar em maiúsculas
```

`app.core.normalization.limpa_codigo` já aplica exatamente essa normalização.

A OP de homologação `A9716901001` **não existe** no SigmaNEST, como previsto:
ela nasceu para a homologação TOTVS e nunca foi programada no Corte. Por isso a
prova usou ordens reais já processadas.

## 6. `TransType` — semântica **NÃO COMPROVADA**

Distribuição real:

| TransType | `ProgArchive` | com `CompDate` | `STPIPArc` |
|---|---:|---:|---:|
| `SN100` | 17.844 | 0 | 95.122 |
| `SN101` | 9.820 | 0 | 54.042 |
| `SN102` | 7.849 | **7.849 (100%)** | 40.007 |

Correlação estrutural observada: em `ProgArchive`, **todo** registro `SN102`
possui `CompDate` e **nenhum** `SN100`/`SN101` possui.

Isso é evidência estatística, **não** semântica oficial. Não há documentação do
fornecedor que confirme o significado dos códigos. Portanto:

- **não** transformar `SN102` em "concluído" numa regra de negócio;
- usar `CompDate` (campo explícito) quando for necessário saber conclusão;
- manter `TransType` transportado e auditável no DTO, sem interpretação.

## 7. `DashboardProgramData`

A view existe (189.171 linhas, 136 colunas), mas:

- `OBJECT_DEFINITION` retornou vazio para `ti_consulta` (sem `VIEW DEFINITION`);
- a investigação inicial registrou `Conversion failed when converting date and/or
  time from character string` ao consultá-la.

**Não usar como contrato** enquanto sua definição não for auditada. O contrato
implementado usa as tabelas base, que têm tipos explícitos e conhecidos.

## 8. Contrato SigmaNEST → Gestor (Fase B, implementado)

```text
backend/integrations/sigmanest_sqlserver.py   ← ÚNICO lugar com SQL do SigmaNEST
        ↓ devolve DTOs neutros
mes/integrations/sigmanest/models.py          ← SigmaNestTask / CutPlan / PartLine
mes/integrations/sigmanest/gateway.py         ← porta + correlação com a OP TOTVS
```

DTOs, refletindo a regra funcional:

```text
SigmaNestTask       task_name, material, thickness, plans      → SEM OP
SigmaNestCutPlan    task, program, sheet, machine, packet,
                    posted_at, completed_at, trans_type, parts → SEM OP
SigmaNestPartLine   program, sheet, part_name, wo_number, qty  → AQUI está a OP
```

`SigmaNestPlanningService.correlacionar(snapshot, ordens_conhecidas)` devolve:

- as correlações apenas para OPs **que já existem** no catálogo canônico;
- a lista de OPs vistas no SigmaNEST e ausentes do Gestor, que permanecem
  auditáveis e **nunca são promovidas a OP nova**.

Validação contra o banco real (recorte de 01/08/2026):

```text
63 tarefas · 180 nestings · 2.251 linhas de peça · 637 OPs distintas
491 OPs correlacionadas com o catálogo do Gestor
146 OPs vistas no SigmaNEST sem correspondência → não criadas
```

Segurança do adaptador, verificada por teste:

- `readonly=True` + `ApplicationIntent=ReadOnly`;
- somente `SELECT ... WITH (NOLOCK)`;
- nenhum verbo de escrita ou DDL no módulo;
- senha nunca registrada em log (`mask_dsn`).

Configuração (`.env`, nunca versionada):

```text
SIGMANEST_SERVER=192.168.0.218,55035
SIGMANEST_DATABASE=SNDBase2026
SIGMANEST_USER=ti_consulta
SIGMANEST_PASSWORD=...
SIGMANEST_ODBC_DRIVER=ODBC Driver 18 for SQL Server
```

Ferramenta de auditoria: `scripts/auditar_sigmanest.py` (allowlist de leitura;
qualquer verbo de escrita aborta o script).

## 9. Fase C — sincronização incremental (IMPLEMENTADA)

```text
SigmaNestSqlServerGateway (read-only)
        ↓ snapshot de DTOs
mes/services/sigmanest_sync.py :: SigmaNestSyncService
        ↓ projeção incremental e idempotente
app/database/sigmanest_repository.py :: sincronizar_catalogo_sigmanest
        ↓
catalogo_sigmanest_tarefas / _programas / _planos_corte / _ops
        ↓ serviços canônicos já existentes
Database.listar_fila_corte → CutService → Tela do Operador
```

Execução: `python scripts/sincronizar_sigmanest.py` (aceita `--desde`,
`--overlap-dias`, `--tarefa` e `--dry-run`).

### Por que não se reutilizou `publicar_catalogo_sigmanest`

Aquele método publica um **snapshot completo** e inativa tudo que ficou de fora.
Uma janela incremental inativaria todo o histórico anterior. Por isso a Fase C
adiciona `sincronizar_catalogo_sigmanest`, que faz **somente**
`INSERT ... ON CONFLICT DO UPDATE`. O método antigo permanece intacto.

### Identidade e idempotência

```text
plano_hash  = sha256(tarefa | programa | chapa | repeat_id)
linha_hash  = sha256(tarefa | WONumber | PartName)
```

Ambas são identidades funcionais estáveis, independentes do `ArchivePacketID`
(que muda a cada evento de arquivo). Reprocessar a mesma janela não duplica nem
altera contagens.

### Leitura incremental

A marca d'água é `MAX(data_programa)` já projetada, recuada por uma janela de
sobreposição (padrão 7 dias). A releitura sobreposta é segura porque a projeção
é idempotente e protege contra programas lançados com data retroativa.

### Correção crítica descoberta na Fase C

`STPIPArc` **também** é arquivo de eventos: cada `(ProgramName, SheetName,
PartName, WONumber)` aparece ~4x (189.171 linhas para 47.174 combinações reais),
uma por `ArchivePacketID`/`TransType`, com `MasterPartQty` constante. A leitura
da Fase B duplicava a composição do nesting. A consulta passou a agregar por
essa chave, e a composição projetada agora é a real.

### Mapeamento dos campos de processo — **corrigido por prova**

O modelo do app Qlik sugeria `Data1→GERAL, Data2→DOBRA, …`. A verificação
direta contra 958 linhas reais já gravadas no Gestor **refutou** essa leitura e
fixou o mapeamento correto, com 100% de igualdade:

| Coluna SigmaNEST | Campo do Gestor |
|---|---|
| `Part.Data3` | `dobra` |
| `Part.Data4` | `usinagem` |
| `Part.Data5` | `solda` |
| `Part.Data6` | `chanfro` |

`Data1` é texto livre de categoria e `Data2` permanece **sem semântica
confirmada**; nenhum dos dois participa do roteamento. A regra de destino
(`DOBRA=SIM → Aguardando Dobra`, `USINAGEM=SIM → Aguardando Usinagem`, senão
`Almoxarifado`) é a regra canônica já validada e vive agora em
`mes/integrations/sigmanest/models.py`.

### Migration 17 (aplicada, aditiva)

```sql
ALTER TABLE catalogo_sigmanest_planos_corte
  ADD COLUMN sigmanest_repeat_id INTEGER,
  ADD COLUMN sigmanest_archive_packet_id INTEGER,
  ADD COLUMN sigmanest_comp_date TIMESTAMP,
  ADD COLUMN sigmanest_trans_type TEXT,
  ADD COLUMN sigmanest_synced_at TIMESTAMP;
ALTER TABLE catalogo_sigmanest_ops     ADD COLUMN sigmanest_synced_at TIMESTAMP;
ALTER TABLE catalogo_sigmanest_tarefas ADD COLUMN sigmanest_synced_at TIMESTAMP;
CREATE INDEX idx_catalogo_corte_sigmanest_sync ...;
```

Nenhuma coluna existente foi alterada ou removida. `sigmanest_trans_type` é
**dado bruto auditável**: nenhuma regra de negócio o consulta, e
`status_programa` permanece nulo — comprovado por teste.

### Wave 6C — o programa passou a viver na linha de peça (migration 28)

```sql
ALTER TABLE catalogo_sigmanest_ops ADD COLUMN programa TEXT;  -- anulável
CREATE INDEX idx_catalogo_sig_ops_programa ON catalogo_sigmanest_ops (codigo_tarefa, programa, ativo);
```

A OP pertence à peça (`STPIPArc.WONumber`) e a peça é aninhada em um
`ProgramName` específico. A projeção descartava esse campo e a granularidade da
linha era `(tarefa, OP, peça)`, o que fazia a fila de Corte tratar todas as OPs
como se pertencessem à tarefa inteira. A granularidade passou a ser
`(tarefa, programa, OP, peça)`, tornando explícita a hierarquia
`TAREFA → PLANO/NESTING → OP → PRODUTO`.

**A consulta homologada não mudou:** `_SQL_PECAS` já selecionava
`s.ProgramName`. A alteração é só de projeção (`SigmaNestSyncService` e
`sigmanest_repository`). A coluna é anulável de propósito: linhas projetadas
antes desta wave continuam válidas e ganham o programa no próximo ciclo; o read
model só as atribui a um plano quando a tarefa tem um único programa.

A quantidade de chapas e a repetição continuam vindo exclusivamente do
planejamento: cada linha de `catalogo_sigmanest_planos_corte` é uma chapa física
(`programa + chapa + RepeatID`). Em nenhum ponto se assume "1 nesting = 1 chapa".

### Prova com dado real (schema isolado de `gestor_pecas_test`)

Janela de 01/08/2026, com as 4.542 OPs reais do Protheus carregadas:

```text
1a sincronização   63 tarefas · 179 programas · 180 nestings · 699 peças
                   637 OPs no SigmaNEST · 491 correlacionadas
                   146 OPs sem correspondência → NÃO criadas
                   catalogo_pcp_ops 4.542 → 4.542 (nenhuma OP criada)
2a sincronização   idempotente: 180 nestings e 699 peças, sem duplicação
3a sincronização   incremental por marca d'água (2026-08-19): 19 tarefas, 70 nestings

fila real do Corte  Laser Ensis 3015 → 51 tarefas
                    Plasma TerraBlade 4 → 12 tarefas
                    com material real (ASTM A36 / A572), programas e nestings reais

exemplo correlacionado
  OP 00617399002 → tarefa T3432 → programa 8501 → chapa S420 → Amada_ensis
  OP 00648711003 → tarefa T3400 → programa 8440 → chapa S201 → Amada_ensis

tarefa T3453 → 12 programas      tarefa T3452 → 49 OPs distintas
```

Nenhum apontamento foi criado: `apontamentos_corte`,
`apontamentos_operacionais`, `eventos_apontamento_operador` e
`eventos_estado_recurso` permaneceram vazios.

### Nesting já concluído no SigmaNEST — regra decidida (31/08/2026)

Decisão da Manufatura: se `sigmanest_comp_date IS NOT NULL`, o nesting já foi
concluído na origem e **não é trabalho pendente do operador**.

A regra vive na consulta canônica `Database.listar_fila_corte`:

```sql
-- fila de espera
WHERE p.ativo IS TRUE
  AND p.data_programa >= %s
  AND a.id IS NULL
  AND p.sigmanest_comp_date IS NULL     -- ← concluído na origem sai da fila
```

O mesmo predicado foi aplicado ao `EXISTS` do ramo de finalizados, para que uma
tarefa cujos nestings restantes já estejam concluídos na origem não continue
exibindo apontamentos encerrados indefinidamente.

Limites deliberados da regra — ela **apenas oculta da fila ativa**:

- o registro continua persistido, com `ativo = TRUE`, e permanece auditável;
- **nenhum apontamento é criado**;
- `apontamentos_corte` **não** é marcado como `Finalizado`;
- **o roteiro/OP não avança automaticamente**. O gate de sequência em
  `listar_proximas_operacoes_roteiro` continua exigindo `apontamentos_corte`
  finalizado, ou seja, a conclusão operacional segue sendo exclusivamente do
  fluxo canônico do Gestor;
- a máquina de estados não foi tocada.

A regra é reversível pela própria origem: se o SigmaNEST deixar de informar a
conclusão, o nesting volta à fila na sincronização seguinte, sem intervenção
manual no Gestor.

**Consequência conhecida:** uma OP cujo nesting foi concluído no SigmaNEST mas
nunca apontado no Gestor não terá sua etapa de Corte considerada concluída pelo
roteiro, e as etapas seguintes permanecem bloqueadas. Isso é intencional —
avançar o roteiro por dado da origem seria criar execução sem apontamento. Se a
Manufatura quiser tratar esse caso, é decisão nova e separada.

Efeito medido no `gestor_pecas_test` após a sincronização real:

```text
224 planos persistidos · 34 concluídos na origem · 224 com ativo = TRUE
fila ativa: Laser 33 tarefas · Plasma 13 tarefas
apontamentos_corte: nenhum criado pela regra
```

## 10. Legado Qlik

O pacote `qlik/` está **órfão**: nenhum arquivo de `app/`, `backend/`, `mes/`,
`scripts/` ou `tools/` o importa, e `publicar_catalogo_sigmanest` /
`publicar_catalogo_pcp` não possuem chamador em produção — apenas testes e
seeds.

Ele é **legado removível** e já foi substituído: a Fase C alimenta as mesmas
tabelas canônicas lendo o SigmaNEST diretamente. A remoção física pode ocorrer
em tarefa própria; note que o mapeamento de campos do `qlik/data_mapper.py`
provou-se **incorreto por deslocamento** (seção 9) e não deve ser reutilizado
como referência.

Guardas automatizadas já existentes:

- `test_nenhuma_dependencia_funcional_de_qlik_no_produto_web` — nada importa `qlik`;
- `test_vocabulario_qlik_residual_esta_congelado_no_schema_e_no_rotulo` — só
  sobrevivem `maquina_qlik`, `machine_qlik` e o rótulo da migration 2;
- `test_fluxo_novo_nao_usa_qlik` — o código novo do SigmaNEST não menciona Qlik.

## 11. Pendências

1. agendar a execução periódica de `scripts/sincronizar_sigmanest.py`;
2. decidir se OP com nesting concluído na origem e sem apontamento no Gestor
   deve ter tratamento próprio no roteiro (seção 9, consequência conhecida);
3. confirmar com o fornecedor/Manufatura a semântica oficial de
   `SN100`/`SN101`/`SN102`;
4. auditar a definição de `DashboardProgramData` com permissão adequada;
5. avaliar a criação de um login SigmaNEST dedicado com apenas `db_datareader`;
6. decidir se o Gestor deve tratar as 15% de divergências de código de produto
   entre Protheus e SigmaNEST como diagnóstico visível.

## 12. Documentos relacionados

- `ROADMAP.md`
- `docs/DESCOBERTAS_SIGMANEST_20260827.md` — investigação inicial e modelo Qlik
- `docs/INTEGRACAO_TOTVS_PRODUCTION_ORDER_V1.md`
- `docs/OPERATOR_SCREEN_FLOW.md`
