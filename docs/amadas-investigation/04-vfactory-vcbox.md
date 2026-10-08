# V-factory, VCBox, VPSS e evidência instalada

## O que a documentação oficial comprova

**[CERTO, produto]** AMADA/Fujitsu documentam coleta de sensores/logs e interfaces abertas OPC UA e MTConnect no VCBox. A conexão máquina–VCBox é cabeada. Fontes e datas em [01-fontes-publicas.md](01-fontes-publicas.md), itens 1–6.

**[PROVÁVEL]** Entrevista AMADA/MONOist descreve CSV do VCBox. Falta contrato de schema/transporte/licença. V-factory moderno, vFactory legado, Influent, Vf-Signal, Vf-Gateway e LIVLOTS são produtos/rotas distintos; sua existência comercial não comprova instalação local.

## Evidência local: backup CommonSettings de 21/08/2026 — [CERTO]

Fonte: `Z:\AMADA\Backup_Software_AMADA\Amada_TotalBackup\Schedule\20260821Full\TB_CommonSettings_V3.03.01_20260821_GTS01-PRO06.vtb`. Assinatura ZIP; leitura com ZipArchive sem restauração. XMLs sanitizados preservados em `evidence/local/`.

| Arquivo/campo | Valor real | Consequência |
|---|---|---|
| CommandLogCollectToolSetting.xml / IsTaskschRegisted | false | Coleta não aparece registrada nesse snapshot |
| mesmo / vSDDserverName, OutputTime, LastExecutionTime | vazios | Não identifica servidor nem execução efetiva |
| HDVCBoxSendSetting.xml / IsSendVCBox | true | Flag isolada; não prova box ou envio |
| mesmo / CentOSIPadress, SendToFolderPath | vazios | Não há alvo VCBox/FTP recuperável nesse arquivo |
| mesmo / SendTime | 0001/01/01 12:00:00 | Valor de configuração, não timestamp de envio real |
| CommandLogUploadTaskSetting.xml / Executável | `C:\Program Files\AMADA3i\Tools\DataExplorer\CommandLogCollectionTool\CommandLogCsvUpload.exe` | Ferramenta concreta de exportação CommandLog em CSV |
| FtpSendHDVCBoxTaskSetting.xml / Executável | mesmo diretório, `FTPSending.exe` | Ferramenta concreta de envio de arquivos ao HDVCBox |
| templates de tarefa / ScheduleByDay | DaysInterval=1 | Template diário; não comprova frequência real instalada |
| DataExplorerSetting.xml / LastSelectedFolder | `\\GTS01-PRO06\Components\Máquinas AMADA\HG2204` | Identifica origem/PC e cadastro HG; caminho ativo não encontrado |

Os templates apresentam `Enabled=true`, mas arquivo de backup não comprova registro no Task Scheduler ativo. Não foi executado exportador, FTP, tarefa agendada ou restorer. Usuário/senha e campos equivalentes foram omitidos, sem tentativas de leitura de credencial utilizável/decriptação.

**[CERTO] Análise offline de 08/10/2026:** os quatro XMLs CommandLog/HDVCBox são modelos. `StartBoundary=1753-01-01` (mínimo do SQL Server) e `SendTime=0001/01/01` (`DateTime.MinValue` do .NET) são valores-padrão. As tarefas não têm `UserId`, `URI` nem `Date` de registro. Nenhum arquivo traz nome, pasta, colunas ou separador do CSV. Detalhe em [12-analise-offline-artefatos.md](12-analise-offline-artefatos.md).

O arquivo chama o destino de `HDVCBox` e contém campo `CentOSIPadress`. **[HIPÓTESE]** Equivalência exata com versão física do VCBox e sistema operacional instalado; não inventar hostname a partir disso.

## VPSS/vSDD: dados disponíveis e limite

**[CERTO]** Existem backups nativos de ABEPlanner, BlankCAM, CommonSettings, DataExplorer, ParameterExplorer e ProductionDesigner, versão V3.03.01, hostname GTS01-PRO06. Parameter Explorer tem 2.994 entradas e cadastros das três AMADA mais Gasparini. ABEPlanner tem programação/cadastros de dobra. A documentação pública confirma servidor vSDD e uso de SQL Server em configurações VPSS.

**[CERTO]** `.vtb`, `.abex` e `.px3` lidos têm assinatura ZIP. `.vsddsqlzip` de 815.135.602 bytes tem assinatura 7z (`37-7A-BC-AF-27-1C`); não foi copiado integralmente, descompactado ou restaurado. `.sd` e `.PD` começam com `PDBACKUP` em UTF-16; isso não revela schema de banco ou protocolo.

**[HIPÓTESE]** Banco vSDD ativo pode oferecer vínculos programa/peça/material e cadastro de rede. Não foram comprovados servidor SQL atual, porta, banco/tabela/campo ou permissão read-only. Não abrir backup em software AMADA de produção nem criar usuário/permissão automaticamente.

## Caminho mais promissor

**[PROVÁVEL]** Configuração ativa do CommandLog/HDVCBox no PC GTS01-PRO06 pode apontar destino/exportação já existentes, reduzindo a necessidade de sondar CNC. Confirmar se CommandLog contém execução física ou ações de programação; o nome sozinho não responde.

Não localizar VCBox no nome de computador AD não prova ausência: um box Linux/appliance pode não pertencer ao domínio e pode estar em rede segregada.
