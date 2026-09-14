# Descobertas SigmaNEST — 27/08/2026

## Objetivo

Registrar as descobertas confirmadas durante a engenharia reversa inicial do banco SigmaNEST para futura integração com o Gestor de Peças.

Este documento deve ser tratado como referência de investigação. Onde houver inferência, ela está explicitamente marcada.

---

## Decisão arquitetural

### Fontes de verdade

- **TOTVS**: OP, produto, quantidade e roteiro corporativo.
- **SigmaNEST**: planejamento específico do Corte — tarefas, programas/nestings, composição de peças, máquina e dados relacionados ao corte.
- **Gestor de Peças**: execução operacional, apontamentos, estados, eventos e rastreabilidade.
- **Qlik**: será removido da arquitetura alvo. Não criar novas dependências.

### Regra funcional importante

A **OP pertence ao produto/peça**.

Não modelar:

- tarefa → uma OP;
- programa/plano → uma OP;
- nesting → uma OP.

Uma tarefa/programa pode agrupar vários produtos e, consequentemente, várias ordens.

---

## Estruturas já identificadas no SigmaNEST

### `Part`

Campos investigados:

- `WONumber`
- `PartName`
- `QtyOrdered`
- `QtyCompleted`
- `Material`
- `Thickness`
- `Data1` ... `Data5`
- `CuttingTime`
- `NetArea`
- `RectArea`
- `PartLength`
- `PartWidth`
- `NetWeight`
- `RectWeight`

Foi observada uma relação declarada:

```text
Part.WONumber
    ↓
Wo.WONumber
```

### `Wo`

A tabela existe e possui `WONumber` como identificador obrigatório.

Campos observados incluem:

- `WONumber`
- `WODate`
- `OrderDate`
- `OrderNumber`
- `WoPriority`
- `StatusID`
- `DateCreated`
- outros campos auxiliares

No registro investigado `PCMDO701001`, campos como `OrderNumber`, `WOData1`, `WOData2` e `ExtReference` estavam vazios.

**Conclusão atual:** dentro do SigmaNEST, `WONumber` é a identidade que acompanha a ordem até as peças.

Ainda falta provar formalmente se:

```text
TOTVS ProductionOrder.Number == SigmaNEST Wo.WONumber
```

---

## `STPIPArc`

Campos investigados:

- `MasterPartQty`
- `ProgramName`
- `PartName`
- `SheetName`
- `WONumber`
- `QtyinProcess`
- `PartLength`
- `PartWidth`
- `TrueArea`
- `RectArea`
- `NestedArea`
- `TrueWeight`
- `RectWeight`
- `CuttingTime`
- `CuttingLength`
- `PierceQty`
- `Transtype`
- `TotalCuttingTime`

Essa estrutura permite seguir uma peça/ordem até um programa.

### Evidência real

Para:

```text
WONumber = PCMDO701001
PartName = PNT002002003
```

foram encontrados programas como:

```text
ProgramName = 7040
ProgramName = 7041
SheetName   = S197
```

---

## `ProgArchive`

Campos investigados:

- `ProgramName`
- `SheetName`
- `TaskName`
- `UsedArea`
- `ScrapFraction`
- `QtyinProcess`
- `MachineName`
- `CuttingTime`
- `PostDateTime`
- `Transtype`
- `CompDate`

### Evidência real

Para `ProgramName = 7040`:

```text
TaskName    = T2915
MachineName = Messer_XPR_300
SheetName   = S197
```

A tarefa `T2915` também possui pelo menos:

```text
ProgramName = 7040
ProgramName = 7041
```

**Conclusão confirmada:**

```text
1 Tarefa
→ pode possuir vários Programas
```

---

## Cardinalidade comprovada

O programa `7040` retornou:

- dezenas de registros;
- múltiplos `WONumber`;
- múltiplos `PartName`.

Exemplos observados:

```text
PCMCUV01002 → PNT002001012
PCLKU101003 → ...
PCMDO701001  → PNT002002003
...
```

Isso comprova:

```text
1 Programa
→ contém várias peças
→ pode conter várias WOs/OPs
```

Portanto:

```text
1 Programa != 1 OP
1 Tarefa   != 1 OP
```

---

## Modelo relacional provisório

Com base nas evidências atuais:

```text
Wo
│
│ WONumber
▼
Part
│
├─ WONumber
└─ PartName
        │
        ▼
STPIPArc
├─ WONumber
├─ PartName
├─ ProgramName
├─ SheetName
├─ QtyInProcess
└─ TransType
        │
        ▼
ProgArchive
├─ ProgramName
├─ TaskName
├─ MachineName
├─ SheetName
├─ PostDateTime
├─ TransType
└─ CompDate
```

Cardinalidades já demonstradas:

```text
1 WO
→ pode possuir peça(s)

1 Programa
→ contém várias peças
→ pode conter várias WOs

1 Tarefa
→ contém vários Programas
```

---

## `DashboardProgramData`

A view foi identificada como potencialmente valiosa por aparentar consolidar:

- `ProgramName`
- `TaskName`
- `MachineName`
- `PartName`
- `WONumber`
- quantidades
- chapa/material
- datas
- `TransType`

Entretanto, uma consulta provocou:

```text
Conversion failed when converting date and/or time from character string.
```

**Conclusão:** não usar `DashboardProgramData` como contrato da integração até auditar sua definição e os casts/conversões internos.

Consultar futuramente:

```sql
SELECT OBJECT_DEFINITION(
    OBJECT_ID('dbo.DashboardProgramData')
) AS ViewDefinition;
```

ou, se permitido:

```sql
EXEC sp_helptext 'dbo.DashboardProgramData';
```

---

## `TransType`

Foram observados valores:

```text
SN100
SN101
SN102
```

Nas amostras analisadas, `SN102` coincidiu com registros que possuíam `CompDate`.

**[Inferência — NÃO IMPLEMENTAR AINDA]**

Pode representar etapas/estados/eventos do ciclo do programa, possivelmente com `SN102` associado à conclusão.

Isso precisa ser comprovado antes de qualquer regra operacional.

---

## OP de homologação TOTVS

A OP:

```text
A9716901001
```

não foi encontrada nas consultas SigmaNEST realizadas.

Isso não invalida a arquitetura.

Explicação provável:

- a OP foi criada para homologação TOTVS;
- não necessariamente foi programada/processada no SigmaNEST.

Para comprovar a equivalência entre TOTVS e SigmaNEST, usar futuramente uma ordem real já processada no Corte, por exemplo uma `WONumber` existente como:

```text
PCMDO701001
```

e verificar se ela existe no Protheus como `ProductionOrder.Number`.

---

## Arquitetura alvo do Corte

```text
TOTVS
→ OP / produto / quantidade / roteiro
          │
          │ correlação no nível da peça/ordem
          ▼
SigmaNEST
→ tarefa
→ programa/nesting
→ peças/produtos
→ WONumber
→ máquina
→ chapa/material
          │
          ▼
Gestor de Peças
→ correlaciona planejamento
→ usa o fluxo canônico de apontamento existente
```

A integração SigmaNEST não deve criar:

- uma segunda tabela canônica de OP;
- apontamento específico SigmaNEST;
- apontamento específico TOTVS;
- lógica paralela de execução.

Depois da correlação, o fluxo operacional continua sendo o fluxo já existente no Gestor.

---

## Próximas perguntas técnicas

Antes de implementar a integração SigmaNEST:

1. Provar `TOTVS ProductionOrder.Number == SigmaNEST Wo.WONumber` usando uma ordem real já processada no Corte.
2. Confirmar o significado funcional de `TaskName`.
3. Confirmar o que a fábrica chama de **Plano** no modelo SigmaNEST.
4. Confirmar se `ProgramName` corresponde a programa/nesting/plano ou se existe outra entidade.
5. Descobrir o significado oficial de `SN100`, `SN101` e `SN102`.
6. Auditar a definição de `DashboardProgramData`.
7. Identificar a melhor consulta read-only para sincronização incremental.
8. Não implementar JOINs ou migrations antes dessas provas.

---

## Evidência adicional — modelo de dados do app Qlik (27/08/2026)

Fonte: dump `getTablesAndKeys` do app Qlik que lia o SigmaNEST
(`Documents/Desenvolvimento/Docs de texto/gettableandkeys.txt`). É evidência de
como o Qlik enxergava o SigmaNEST, **não** o schema do banco. Serve para
confirmar cardinalidades e revelar o alias de cada campo.

### Tabelas carregadas e volume real

| Tabela no modelo Qlik | Linhas | Campos |
|---|---:|---:|
| `PartWithQtyInProcess_sigmanest` | 18.403 | 70 |
| `DashboardProgram` | 175.893 | 136 |
| `ProgArchive` | 10.633 | 14 |
| `Part` | 18.403 | 18 |
| `STPIPrc` | 177.406 | 22 |
| `PESO_TOTAL_PROGRAMA` | 7.062 | 2 |
| `STOCK` | 365 | 8 |

### Tradução dos campos — de onde vinha `codigo_op`

O app Qlik renomeava os campos. O mapeamento explica exatamente o que a era
Qlik gravava em `catalogo_sigmanest_ops`:

| Alias no Qlik | Campo SigmaNEST | Destino no Gestor |
|---|---|---|
| `OrdemProducao` | `WONumber` | `catalogo_sigmanest_ops.codigo_op` |
| `NomePeca` / `PartName` | `PartName` | `catalogo_sigmanest_ops.id_peca` |
| `Programa` | `ProgramName` | `catalogo_sigmanest_programas.programa` |
| `NomeTarefa` | `TaskName` | `catalogo_sigmanest_tarefas.codigo_tarefa` |
| `NomeChapa` | `SheetName` | `catalogo_sigmanest_planos_corte.nome_chapa` |
| `NomeMaquina` | `MachineName` | `catalogo_sigmanest_planos_corte.maquina_qlik` |
| `MaterialPeca` / `EspessuraPeca` | `Material` / `Thickness` | `catalogo_sigmanest_tarefas.material` / `.espessura` |
| `CampoDobra`/`CampoUsinagem`/`CampoSolda`/`CampoChanfro` | `DOBRA`/`USINAGEM`/`SOLDA`/`CHANFRO` | processos seguintes da peça |

**Consequência forte:** a coluna que o Gestor sempre chamou de `codigo_op` no
catálogo de Corte é, na origem, o `WONumber` da **linha de peça**. Isso é
coerente com a regra funcional de que a OP pertence ao produto, e indica que a
correlação futura deve ocorrer em `Part`/`STPIPArc` (nível peça), nunca em
`ProgArchive` (nível programa).

### Cardinalidades confirmadas por contagem real

```text
ProgArchive : 10.633 linhas | 7.448 programas distintos | 1.766 tarefas distintas
              → média de 4,22 programas por tarefa
              → 1 TAREFA : N PROGRAMAS  (confirmado)

STPIPrc     : 177.406 linhas | 17.662 OrdemProducao distintas | 7.448 programas
              → ~23,8 linhas por programa
              → 1 PROGRAMA : N PEÇAS/WOs  (confirmado)

Part        : 18.403 linhas | 17.662 WONumber distintos | 5.857 PartName distintos
              → a WO praticamente não se repete; o produto sim
```

Isso reforça, com números, que **programa ≠ OP** e **tarefa ≠ OP**.

### Máquinas

`ProgArchive.NomeMaquina` possui apenas **2 valores distintos**, coerente com o
`CUT_MACHINE_MAP` já existente no Gestor (`AMADA_ENSIS` → Laser Ensis 3015 e
`MESSER_XPR_300` → Plasma TerraBlade 4). Isso indica que o domínio de valores da
coluna `maquina_qlik` sempre foi o do SigmaNEST, e não do Qlik.

### `TransType`

No recorte carregado pelo Qlik, `ProgArchive.Transtype` apresentou apenas **2**
valores distintos, enquanto a consulta direta ao banco observou `SN100`, `SN101`
e `SN102`. Ou seja, o Qlik filtrava. **A semântica continua NÃO COMPROVADA** e
não deve virar regra.

## Resolução — auditoria concluída na Etapa 3.1 (27/08/2026)

As perguntas abertas deste documento foram respondidas com acesso somente
leitura ao banco real `SVR-DBLANTEK\SIGMANEST` / `SNDBase2026`. O resultado
consolidado, o contrato implementado e as pendências restantes estão em
**`docs/INTEGRACAO_CORTE_SIGMANEST.md`**, que passa a ser a referência vigente.

Resumo do que ficou provado:

| Pergunta | Resultado |
|---|---|
| `WONumber == ProductionOrder.Number`? | **SIM**, igualdade textual (905 de 4.542 OPs reais do Protheus presentes em `Wo`) |
| `TaskName` é a tarefa? | **SIM**, 1.991 tarefas; agrupa programas (até 121) |
| `ProgramName` é plano/nesting? | é o **programa**; o nesting é `ProgramName` + `SheetName` + `RepeatID` + `ArchivePacketID` |
| Programa/tarefa têm OP própria? | **NÃO** — 158 de 180 nestings recentes contêm mais de uma OP |
| Produto serve de chave? | **NÃO** — coincide em 84,7%, é prefixo em 13,3%, diverge em 2% |
| `SN100`/`SN101`/`SN102` | **NÃO COMPROVADO**; há correlação estrutural com `CompDate`, mas não vira regra |
| `DashboardProgramData` | continua **não confiável**; definição inacessível ao login de consulta |

Este documento permanece como registro histórico da investigação inicial.

## Status

**Engenharia reversa SigmaNEST: PARCIAL / EM INVESTIGAÇÃO**

Já comprovado:

- `Wo`, `Part`, `STPIPArc` e `ProgArchive` são relevantes;
- `WONumber` acompanha a ordem até a peça;
- programa agrupa várias peças/WOs;
- tarefa agrupa vários programas;
- OP não pertence à tarefa nem ao programa;
- Qlik não fará parte da arquitetura alvo.

Ainda não comprovado:

- equivalência direta `WONumber ↔ ProductionOrder.Number`;
- semântica oficial de `TransType`;
- entidade exata correspondente a “Plano”;
- contrato final SigmaNEST → Gestor.
