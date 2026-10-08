# Análise offline dos artefatos já coletados

Data: 08/10/2026. Escopo: somente leitura de arquivos em `evidence/local/`. Nenhuma consulta de rede, execução AMADA, restauração, decriptação ou acesso a banco. Complementa os documentos 04, 07 e 09; não substitui conclusões anteriores.

Classificação: **[CERTO]** = lido no arquivo citado; **[PROVÁVEL]** = evidência forte, confirmação pendente; **[HIPÓTESE]** = possibilidade não demonstrada.

## 1. O que cada XML prova

| Arquivo (`evidence/local/`) | Campos lidos | O que prova | O que não prova |
|---|---|---|---|
| `sanitized__CommandLogOutput__CommandLogUploadTaskSetting.xml` e `...FtpSendHDVCBoxTaskSetting.xml` | Schema Task Scheduler 1.2; `Description` "This task automatically output CommandLog csv file…"; `StartBoundary=1753-01-01T15:15:00`; `DaysInterval=1`; `LogonType=Password`; `RunLevel=HighestAvailable`; `ExecutionTimeLimit=PT12H`; `Command` = `CommandLogCsvUpload.exe` / `FTPSending.exe` | [CERTO] existem modelos de tarefa diária que exportam CommandLog em CSV e enviam por FTP | [CERTO] nenhum nome de arquivo CSV, pasta de saída, colunas, encoding ou separador aparece. Nenhum `UserId`, `URI` ou `Date` de registro |
| `sanitized__CommandLogOutput__CommandLogCollectToolSetting.xml` | `IsTaskschRegisted=false`; `OutputTime`, `LastExecutionTime`, `vSDDserverName` vazios | [CERTO] no snapshot de 21/08/2026 a tarefa não constava como registrada e nunca registrou execução | estado atual no PC |
| `sanitized__CommandLogOutput__HDVCBoxSendSetting.xml` | `IsSendVCBox=true`; `CentOSIPadress` e `SendToFolderPath` vazios; `SendTime=0001/01/01 12:00:00` | [CERTO] flag ligada sem destino configurado | existência de VCBox ou envio |
| `sanitized__DataExplorer__DataExplorerSetting.xml` | `LastSelectedTabPage=PartsPage`; `LastSelectedFolder=\\GTS01-PRO06\Components\Máquinas AMADA\HG2204`; filtros `IsExcludeFilter` | [CERTO] o DataExplorer foi usado na aba de peças, apontando para o cadastro HG2204 | produção ou execução |
| `sanitized__localhost__Machines__Bend__HG2204__MachineRegistration.xml` | `NAME_BASE=HG-2204-N-N-A-1-0-A`; `NC_NAME=AMNC_3i`; `REFIX_DATE=2026/08/12/16/21` | [CERTO] cadastro CAM da HG2204 | serial, firmware, potência real |
| `sanitized__localhost__Machines__Bend__EGB1303E__MachineRegistration.xml` | `NAME_BASE=EGB-1303-N-N-A-N-A-3-A`; `NC_NAME=AMNC_4ie`; mesmo `REFIX_DATE` | [CERTO] cadastro CAM da EGB1303 | idem |
| `sanitized__ENSIS3015AJ_MACHINE_INFORMATION.xml` | `ID_ORIGIN_X/Y/Z=3070/1550/100`; faixa X −3…3073, Y −3…1553; `ID_MACHINE_DRIVER=AMADA LC1212 AI`; `ID_MAX_CUTTING_SPEED=120000`; `ID_NC_DEVICE_NAME=AMNC 3i`; `ID_OSC_NAME=ENSIS2000`; `ID_OSC_LASER_KIND=ID_FIBER`; `ID_OSC_OUTPUT_MAX=2100`; `ID_NC_CUT_CONDITION_DEEP_ENGRAVE=ID_E009` | [CERTO] perfil CAM presente no backup AMADA | potência física, serial e uso atual desse perfil |

### Sentinelas: modelo, não execução — [CERTO]

- `1753-01-01` é o menor `datetime` do SQL Server. `0001/01/01` é `DateTime.MinValue` do .NET. As duas datas são valores-padrão, não datas de evento.
- A combinação de datas-padrão, destinos vazios, ausência de `UserId` e `IsTaskschRegisted=false` classifica todos os artefatos CommandLog/HDVCBox como **modelo/configuração**.
- Não existe, nos arquivos locais, nenhuma evidência de execução desses exportadores.

### Diferenças HG2204 × EGB1303E — [CERTO] nos XMLs

| Item | HG2204 | EGB1303E | Leitura |
|---|---|---|---|
| Controlador | `AMNC_3i` | `AMNC_4ie` | gerações de NC diferentes |
| Posições de batente (PHL) | 21 | 15 | cadastro de ferramental/batente diferente |
| Faixa do encosto traseiro | ±1775,9 | ±1280,9 | [PROVÁVEL] comprimento útil maior na HG, coerente com ~4 m vs ~3 m |
| `REFIX_DATE` | 2026/08/12/16/21 | 2026/08/12/16/21 | data idêntica: [PROVÁVEL] carimbo de manutenção do cadastro em lote, não de uso da máquina |

## 2. Referências a CSV, caminhos, aplicações e servidores

| Referência | Fonte | Tipo |
|---|---|---|
| `C:\Program Files\AMADA3i\Tools\DataExplorer\CommandLogCollectionTool\CommandLogCsvUpload.exe` | XML de tarefa | executável (não executado) |
| `...\CommandLogCollectionTool\FTPSending.exe` | XML de tarefa | executável (não executado) |
| `\\GTS01-PRO06\Components\Máquinas AMADA\HG2204` | DataExplorerSetting | caminho histórico; não encontrado na leitura SMB anterior |
| `localhost/Settings/MxSettings/Csv*Import.xml` / `Csv*Export.xml` (11 arquivos) | `parameter-explorer-zip-entries.json` | [CERTO] nomes existem no índice; [PROVÁVEL] configs de importação/exportação CSV de **cadastro** (material, tipo de material, formato de chapa, cor, filme, propriedade de dobra). Conteúdo não extraído. Não são logs operacionais |
| `Z:\` raiz: `AMADA`, `NESTING LASER`, `LaserAmada.bat`, dois `*__out.log.1` de 02/04/2026 | `known-share-roots.json` | [HIPÓTESE] os `.log.1` são de outra aplicação; nome não liga a AMADA. Conteúdo não lido |
| `NESTING LASER` | `laser-share-root.json` | 759 arquivos, todos `.DNK`; nenhum CSV ou log |

**[CERTO]** Nenhum artefato local contém schema de CSV operacional. Qualquer coluna proposta hoje seria invenção.

## 3. Programa DNK 8571: campos interpretados

Fonte: `evidence/local/sample-program-8571-original.DNK`, 684 bytes, ASCII, CRLF, último registro no share 24/08/2026 13:04:54 −03:00.

| Linha | Valor | Interpretação |
|---|---|---|
| `(PR8571)` | 8571 | [CERTO] número do programa; igual ao nome do arquivo |
| `(MCEnsis3015AJ)` / `(TREnsis3015AJ)` | Ensis3015AJ | [CERTO] perfil declarado pelo pós-processador; [PROVÁVEL] máquina = LASER1 |
| `(MN 239)` | 239 | [HIPÓTESE] significado desconhecido (número de máquina, material ou ninho). Não usar até documentar |
| `(MAE-SPC1.25)` e `M102(E-SPC1.25)` | E-SPC1.25 | [CERTO] código de material repetido em comentário e em M-code; [PROVÁVEL] SPCC 1,25 mm |
| `(PROGRAMADOR: …)` | nome pessoal | [CERTO] campo presente. Valor omitido aqui por privacidade; identifica quem gerou, não quem operou |
| `(WK 1.25T 3000.00X 1200.00)` | 1,25 × 3000 × 1200 | [CERTO] espessura e chapa declaradas |
| `(TT00H01M37S)` | 97 s | [PROVÁVEL] tempo estimado pelo CAM. Nunca tempo realizado |
| `(CRY2026M08D24)` | 24/08/2026 | [CERTO] data de criação declarada; bate com a data do arquivo |
| `G90 G92 X3070.0 Y1550.0` | origem | [CERTO] igual a `ID_ORIGIN_X/Y` do XML ENSIS3015AJ |
| `(--n--N--14333283--)` | 3 seções | [CERTO] seção 1 só posiciona; seções 2 e 3 cortam um contorno cada |
| `E5` | condição | [PROVÁVEL] seleção de condição de corte (o XML usa a mesma família `ID_E009`) |
| `M103` … `M104` | blocos | [HIPÓTESE] delimitam trecho de corte; semântica exata depende do manual AMNC |
| Geometria | 2 retângulos de 2900,14 × 490,94 mm | [CERTO] por cálculo das coordenadas. Perímetro ~13,6 m no total |

**Regra mantida:** duas seções com `14333283` mostram duas geometrias no programa. Não provam duas peças produzidas, nem boas, nem de qual OP.

### Comportamento do share `NESTING LASER` — [CERTO] em `laser-share-root.json`

- 759 DNK, numerados de 8413 a 9372; 201 números ausentes na faixa.
- `LastWriteTime` de 24/08/2026 a 08/10/2026 08:21, em 30 dias distintos. Picos: 16/09 (74), 08/09 (63), 17/09 (61).
- Número ≠ ordem cronológica: 8571 é o arquivo mais antigo (24/08), mas 8413 é de 02/09. Há 16 inversões entre números vizinhos.
- Consequência: `LastWriteTime` é o horário de modificação registrado pelo sistema de arquivos. [PROVÁVEL] coincide com exportação/regravação nesse fluxo; não indica corte nem início de execução.
- [HIPÓTESE] números ausentes = programas apagados, nunca exportados ou exportados para outro destino. Não inferir.

## 4. Vínculo com LASER1, DOBRA2, DOBRA3

| Recurso Gestor | Evidência local | Classificação |
|---|---|---|
| LASER1 | DNK `MC/TR=Ensis3015AJ` + G92 = origem do perfil `ENSIS3015AJ` | [PROVÁVEL] falta serial na plaqueta/tela |
| DOBRA2 | `HG2204/MachineRegistration.xml`, `NC_NAME=AMNC_3i`, mapeamento em `08-mapeamento-gestor.md` | [PROVÁVEL] falta serial |
| DOBRA3 | `EGB1303E/MachineRegistration.xml`, `NC_NAME=AMNC_4ie` | [PROVÁVEL] falta serial |
| DOBRA1 (Gasparini) | pastas `Machines/Bend/GASPARINI` e `Tools/Bend/GASPARINI` no Parameter Explorer | [CERTO] cadastrada no CAM AMADA; fora do escopo AMADA de telemetria |

Os artefatos de dobra são só cadastro. Nenhum programa de dobra individual foi lido nesta etapa.

## 5. Divergência ENSIS2000 × ENSIS 12 kW

- **[CERTO]** O perfil CAM declara `ID_OSC_NAME=ENSIS2000`, `ID_OSC_OUTPUT_MAX=2100` e driver `AMADA LC1212 AI`.
- **[CERTO]** O DNK 8571 declara G92 X3070 Y1550, igual à origem do perfil no backup. Essa igualdade não prova o gerador, o perfil ativo ou a potência configurada no fluxo atual.
- **[HIPÓTESE]** O perfil pode ter sido herdado de outra máquina/template. Uso atual e motivo da divergência permanecem desconhecidos. A leitura posterior comprovou um fluxo independente de geração no SigmaNEST; ver documento 13.
- **[HIPÓTESE]** Consequências: `TT` dos DNK pode estar distorcido; tabelas de condição (`E5`) podem vir do pós-processador ou do NC, não do perfil. Não usar `TT` como padrão de tempo até resolver.
- **Prova necessária:** foto da plaqueta da fonte laser ou tela de informação do AMNC (potência, serial) + export do perfil ativo no GTS01-PRO06.

## 6. Formatos legíveis e limites

| Formato | Lido com | Limite |
|---|---|---|
| `.vtb`, `.abex`, `.px3` | assinatura ZIP; índice de entradas | só índices e XMLs pequenos sanitizados foram extraídos |
| XML de tarefa | UTF-16, schema Task Scheduler 1.2 | modelo; não reflete o agendador ativo |
| XML de cadastro AMADA | UTF-8, tags planas | campos sem dicionário oficial; significado inferido pelo nome |
| `.DNK` | ASCII, CRLF, comentários entre parênteses | M/E-codes e `MN` sem dicionário; comandos CNC nunca executados |
| `.vsddsqlzip` | só assinatura 7z | conteúdo e schema SQL desconhecidos |
| `.sd`, `.PD` | só cabeçalho `PDBACKUP` | formato proprietário |

## 7. Menor amostra adicional que destrava o próximo passo

1. **Um CSV real do CommandLog** gerado no GTS01-PRO06, com a pasta de saída e o XML da tarefa ativa (`schtasks /query /xml` feito por TI local).
2. **Ou** um CSV/log de HDVCBox/VCBox, se existir.
3. **Plaqueta/tela AMNC da ENSIS** com potência e serial, mais export do perfil ativo.

Para provar dado operacional, a amostra precisa conter:

- identificador de máquina ou serial;
- data/hora com fuso;
- tipo de evento que separe execução na máquina de ação de programação;
- número de programa (`PR`) para cruzar com o DNK;
- início/fim ou duração;
- contador com unidade e regra de reset.

Sem evidência de eventos da máquina e sua semântica, não classificar o arquivo como telemetria. Um protocolo pode fornecer snapshots válidos sem todos esses campos; a ausência de fuso, início/fim ou contador deve ser registrada como lacuna, não invalida automaticamente todo dado operacional.

## Atualização após leitura de novas fontes

[13-leitura-atual-sigmanest.md](13-leitura-atual-sigmanest.md) comprova CSVs reais de planejamento de hoje em `SIGMANEST/SNDATA_serv/eReport`, fora do conjunto offline analisado aqui. As afirmações de ausência de CSV deste documento dizem respeito às amostras offline iniciais e ao share `NESTING LASER`, não a todos os servidores da empresa. Ainda não foi encontrado CSV operacional do CommandLog/VCBox.
