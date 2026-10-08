# Investigação pública: integração AMADA → MES

Data da pesquisa: **2026-10-08**  
Escopo: fontes públicas em português, inglês e japonês; nenhuma interação com rede local ou máquina.  
Máquinas-alvo: ENSIS-3015AJ 12 kW / AMNC 3i; HG2204 / AMNC 3i; EGB1303e / AMNC 4ie.

## Resultado técnico

### O que foi comprovado publicamente

- **[CERTO]** A arquitetura V-factory usa um gateway chamado **V-factory Connecting Box (VCBox)**. A documentação atual exige ligação **cabeada** entre VCBox e máquina.
- **[CERTO]** AMADA e Fujitsu declararam oficialmente que o VCBox coleta dados de sensores e logs de operação e oferece interfaces abertas **OPC UA** e **MTConnect**.
- **[CERTO]** V-factory envia informação de operação em tempo real e My V-factory apresenta estado, produção, utilização, causas de parada, materiais, energia, manutenção e dados de dobra.
- **[CERTO]** O ENSIS-3015AJ existe em 12 kW e usa AMNC 3i; uma página oficial AMADA apresenta VCBox como opção para a família ENSIS.
- **[CERTO]** O HG-2204ATC usa AMNC 3i e foi documentado como máquina compatível com V-factory. O sufixo exato da máquina instalada precisa ser verificado: `HG2204` sozinho não prova que seja o modelo ATC.
- **[CERTO]** O EGB-1303e usa AMNC 4ie; o catálogo oficial da família EGB-e mostra V-factory/VCBox e monitoramento de operação, sensores e energia.
- **[CERTO]** A AMADA oferece ainda Vf-Signal 8 para máquinas sem AMNC e Vf-Gateway para equipamentos periféricos. São rotas diferentes do VCBox.
- **[CERTO]** Não foi localizado, em fonte pública, manual de integração contendo URL/porta, direção cliente-servidor, políticas de segurança, namespaces/NodeIds OPC UA, `Devices.xml`/DataItems MTConnect, esquema CSV, API Web ou SDK.

### O que a documentação não permite afirmar

- **[HIPÓTESE]** Que as três máquinas da empresa estejam conectadas hoje ao V-factory ou a um VCBox.
- **[HIPÓTESE]** Que o VCBox instalado, se existir, aceite conexão local de um cliente OPC UA ou requisições MTConnect. “Suporta OPC UA/MTConnect” não revela se ele consome, publica, traduz ou apenas exporta dados sob licença/configuração.
- **[HIPÓTESE]** Que AMNC 3i ou AMNC 4ie exponham diretamente OPC UA ou MTConnect. A evidência pública vincula os padrões ao **VCBox**, não ao controlador como servidor direto.
- **[HIPÓTESE]** Que exista API pública do My V-factory. Foram encontrados portal Web e aplicativo, mas nenhum contrato de API/SDK.
- **[HIPÓTESE]** Que todos os campos visíveis no My V-factory estejam disponíveis na interface aberta local, com a mesma granularidade e retenção.

## Arquitetura pública reconstruída

```text
máquina AMADA / AMNC ── Ethernet cabeada ── VCBox ── serviço seguro AMADA/Fujitsu ── V-factory / My V-factory
                                                   └─ interfaces abertas declaradas: OPC UA / MTConnect

máquina sem AMNC ── Vf-Signal 8 ── nuvem V-factory
periférico       ── Vf-Gateway  ── nuvem V-factory
fábrica sem internet própria ── Vf-Router ── V-factory
```

**[CERTO]** O fluxo máquina → VCBox → plataforma AMADA é documentado.  
**[PROVÁVEL]** O ponto de integração externa mais promissor é o VCBox, porque é nele que AMADA/Fujitsu colocam explicitamente OPC UA/MTConnect e geração CSV.  
**[HIPÓTESE]** A posição e a direção exatas da interface aberta continuam desconhecidas. O desenho acima não afirma que o MES consiga abrir uma sessão diretamente no VCBox sem habilitação da AMADA.

Uma página oficial japonesa recente relata que V-factory usa VCBox desde 2018, conecta cerca de 8.200 máquinas mundialmente e que máquinas principais atuais possuem VCBox de fábrica. Isso fortalece a maturidade da solução, mas não identifica os ativos desta planta.

## Compatibilidade por máquina

| Máquina | Evidência pública | Classificação | Consequência prática |
|---|---|---|---|
| ENSIS-3015AJ 12 kW / AMNC 3i | AMADA Brasil lista 3/6/9/12 kW; página/catálogo AMADA da família identifica AMNC 3i e VCBox opcional | **[CERTO]** para modelo e opção comercial; **[HIPÓTESE]** para unidade instalada | Procurar fisicamente/logicamente VCBox, contrato V-factory e cadastro da máquina; não presumir OPC UA direto no AMNC |
| HG2204 / AMNC 3i | HG-2204ATC é oficialmente AMNC 3i, V-factory/Vf-machine; caso japonês confirma telemetria de dobra | **[CERTO]** para HG-2204ATC; **[PROVÁVEL]** para “HG2204” sem sufixo | Confirmar plaqueta/sufixo, ano, opção ATC e cadastro V-factory antes de extrapolar |
| EGB1303e / AMNC 4ie | Catálogo oficial EGB-e inclui EGB-1303e, AMNC 4ie, V-factory e VCBox | **[CERTO]** como capacidade da família; **[HIPÓTESE]** quanto à ativação local | Melhor candidata a integração AMADA recente; verificar VCBox embutido/externo, contrato e configuração |

O relatório anual AMADA 2021 descreve o AMNC 3i como interface compatível com V-factory em lasers e dobradeiras. Isso confirma compatibilidade de produto, mas não define protocolo na porta Ethernet nem elimina a necessidade do VCBox.

## Dados que o produto documenta

Esta tabela separa o que o **produto V-factory/My V-factory mostra** do que está comprovado em uma interface aberta. A última coluna é deliberadamente conservadora.

| Grupo | Campo/capacidade documentada | Máquina aplicável | Prova de leitura pela interface aberta |
|---|---|---|---|
| Estado | Operating, Stopped, Stand-by/Preparing, Alarm | laser e dobra | **[HIPÓTESE]**; exibido no My V-factory, tags não publicadas |
| Estado | utilização, tempo operando, tempo parado, causas/ranking de paradas | laser e dobra | **[HIPÓTESE]**; granularidade/frequência desconhecidas |
| Produção | resultados de produção, número de produtos, tempo de trabalho | laser e dobra | **[HIPÓTESE]**; não há schema público |
| Programa | programa em execução/concluído, runtime e setup | máquinas conectadas | **[HIPÓTESE]**; catálogos mostram na UI, identificador bruto não publicado |
| Dobra | golpes/shots, média de golpes, peças por lote, setup, standby, alarme | HG/EGB | **[HIPÓTESE]**; My V-factory documenta análise de dobra |
| Processo | material, espessura, utilização de material, quantidade e matéria-prima consumida | laser e dobra, conforme configuração | **[HIPÓTESE]**; origem pode ser programa/banco, não sensor direto |
| Energia | eletricidade de máquina, oscilador, chiller e coletor de pó | especialmente laser | **[HIPÓTESE]**; pode depender de medidor/opção |
| Gases | oxigênio e nitrogênio | laser | **[HIPÓTESE]**; unidade e frequência não publicadas |
| Alarme | condição de alarme, avisos e análise/causa de falha | laser e dobra | **[HIPÓTESE]**; código, texto, início/fim e histórico bruto não publicados |
| Manutenção | saúde, inspeções diárias, substituições periódicas, versões de software | todas conectadas | **[HIPÓTESE]**; pode existir apenas no serviço AMADA |
| Identificação | lista de máquinas/software e versões | todas conectadas | **[HIPÓTESE]**; serial/modelo não explicitados como tags abertas |
| Vídeo | gravação/monitoramento de processamento pelo V-monitor | opcional | **[CERTO]** produto separado; não é telemetria do VCBox |
| Ordem/job | lista de trabalhos e captura automática de início/conclusão via LIVLOTS + AMNC 4ie | EGB/AMNC4ie quando equipado | **[CERTO]** capacidade AMADA; **[HIPÓTESE]** API MES externa |

### Estado pedido pelo MES

Mapeamento inicial possível, ainda dependente dos valores reais:

| Dado AMADA documentado | Evento MES sugerido | Observação |
|---|---|---|
| `Operating` | `machine_state=RUNNING` | direto apenas após verificar semântica e transições reais |
| `Stopped` | `machine_state=STOPPED` | precisa distinguir desligada, sem demanda e parada produtiva |
| `Stand-by/Preparing` | `machine_state=IDLE` ou `SETUP` | categoria AMADA combina estados que o MES pode separar |
| `Alarm` | `machine_state=ALARM` + evento de alarme | código/mensagem e fechamento precisam ser observados |
| contador/number of products | evento `part_count` | exigir contador monotônico, reset e unidade por ciclo/lote |
| hits/shots | evento `stroke_count` | útil na dobra; não equivale automaticamente a peça boa |
| start/completion do LIVLOTS | `job_started` / `job_completed` | só se a unidade tiver LIVLOTS e houver acesso legítimo ao dado |

Nenhum destes mapeamentos deve entrar em produção sem amostra bruta com timestamp e correlação com um ciclo observado.

## Interfaces e rotas possíveis

### 1. VCBox + V-factory

**[CERTO]** É a rota canônica e mais bem documentada. A conexão máquina–VCBox é cabeada. O VCBox coleta sensing data e operating logs, e o serviço AMADA/Fujitsu armazena/analisa os dados. A página atual declara upload em tempo real.

**Limitação:** um catálogo alemão de 2020 descreveu visualização no dia seguinte, enquanto a página atual fala em tempo real. Isso pode refletir versão, mercado ou diferença entre status instantâneo e relatório analítico. Frequência e latência precisam ser medidas localmente.

### 2. OPC UA no ecossistema VCBox

**[CERTO]** O anúncio oficial de 2017 declara interface OPC UA.  
**[HIPÓTESE]** endpoint, porta, discovery, certificados, SecurityPolicy, usuário, namespace e NodeIds; também não há prova de aderência ao OPC UA for Machine Tools.

A especificação **OPC UA for Machine Tools 1.02**, publicada em 2024, define modelos úteis para MES: identificação, estado/operação, jobs, contadores, tempos, alarmes e condições. V-factory é anterior a esse modelo. Portanto, só se deve usar os nós padronizados se o namespace real do servidor declarar essa companion specification.

Se um endpoint for encontrado, a investigação correta é exclusivamente `GetEndpoints`, `Browse` e `Read`, registrando certificado, políticas, namespaces, NodeIds, tipos, valores, timestamps e status codes. Não há fundamento público para tentar `Write` ou `Call`.

### 3. MTConnect no ecossistema VCBox

**[CERTO]** O anúncio oficial de 2017 declara suporte a MTConnect.  
**[HIPÓTESE]** existência de um Agent HTTP acessível localmente, URL/base path, versão, modelo de dispositivos ou DataItems AMADA.

Pelo padrão MTConnect, um Agent deve suportar recursos equivalentes a `probe`, `current`, `sample` e `assets`. Um `probe` real, não uma lista genérica do padrão, deve decidir o que existe. DataItems úteis definidos pelo padrão incluem `Availability`, `Execution`, `ControllerMode`, `Program`, `PartCount`, `CycleCount`, condições e energia; isso **não significa** que a AMADA publique todos eles.

### 4. CSV

**[PROVÁVEL]** Entrevista técnica da AMADA publicada pelo MONOist em 2018 informa que VCBox, além de OPC UA, pode gerar arquivos CSV para ligação com plataformas IoT do cliente. Falta documentação pública de diretório/transporte, schema, codificação, periodicidade e licença. É uma rota especialmente atraente para PoC se já existir exportação configurada, pois permite consumo somente leitura sem sessão no controle.

### 5. My V-factory Web/mobile

**[CERTO]** Interface humana sob contrato, com consulta remota dos dados descritos.  
**[HIPÓTESE]** API reutilizável. Não foi encontrada documentação oficial de REST, GraphQL, WebSocket, webhook ou export automatizado. Automatizar ou reproduzir chamadas internas sem contrato deve ser evitado; solicitar API/exportação oficial.

### 6. VPSS/SDD/VSSD/LIVLOTS

**[CERTO]** AMNC 3i pode se conectar por Ethernet ao servidor de dados AMADA SDD para desenhos, setup, sequência e programa de dobra. Materiais AMADA também descrevem bancos VPSS/VSSD e intercâmbio de arquivos CSV/XML em contextos de programação/FMS. LIVLOTS + AMNC 4ie captura início e conclusão de trabalhos.

Essas interfaces são relevantes para identificar programa, peça e job, mas parecem fazer parte do fluxo de engenharia/programação. Não há contrato público de leitura MES. Qualquer acesso deve começar pelos arquivos/configurações/logs legitimamente disponíveis no servidor, sem enviar programas à máquina.

### 7. Influent e vFactory legado

**[CERTO]** A AMADA America oferece `Influent Monitor`, que coleta dados de máquinas AMADA e fornece dashboard. A AMADA também documenta um `vFactory` legado baseado em navegador, com estados, resultados e alarmes. Eles podem existir em instalações antigas ou de outro mercado.

**Risco de confusão:** `vFactory` legado e `V-factory` com VCBox não devem ser tratados como o mesmo produto. Uma cópia não oficial de manual legado menciona TCP/8989, mas a origem não é confiável e a informação não deve orientar sonda de rede sem confirmação local/documental.

### 8. FANUC FOCAS no AMNC 3i

**[PROVÁVEL]** Existe uma rota direta adicional para alguns AMNC 3i. O guia técnico de conectividade da integradora MachineMetrics mostra especificamente um AMNC-3i com front-end Windows, a função `CNC Screen Display`, um FANUC NCU, Ethernet `EMBEDDED` e a tela `FOCAS2` configurável na porta 8193. O mesmo guia alerta que máquinas AMADA costumam ter rede interna e parâmetros próprios.

Essa evidência é visual e específica, porém não é documentação oficial AMADA e não demonstra que toda máquina AMNC 3i tenha a mesma NCU, licença ou porta livre. **[HIPÓTESE]** FOCAS pode ser candidato para o ENSIS se a NCU FANUC, a opção e o endpoint forem confirmados nessa unidade. O guia AMNC-3i não comprova a NCU do ENSIS local nem permite inferir compatibilidade da HG ou EGB.

FOCAS costuma ser uma interface de coleta de CNC para estado, programa, eixos, contadores e alarmes. Os campos realmente suportados dependem da série FANUC e das opções. Um teste futuro só faz sentido se a topologia/configuração já revelar a NCU e FOCAS habilitado; não há justificativa para procurar a porta 8193 em toda a rede OT.

### 9. VPSS 3i/4ie, vSDD e os backups encontrados

O investigador principal comunicou a existência de backup `Amada_TotalBackup` versão `V3.03.01` com componentes `ABEPlanner`, `BlankCAM`, `CommonSettings`, `DataExplorer`, `ParameterExplorer` e `ProductionDesigner`, incluindo um arquivo `DataExplorer.vsddsqlzip` grande. O cruzamento público permite as seguintes conclusões:

- **[CERTO]** A página oficial de atualizações AMADA manda executar o **Total Backup Tool** antes de atualizar VPSS 3i/4ie. Logo, o conjunto observado é backup nativo e coerente com o produto, não simples pasta casual.
- **[CERTO]** A página oficial de tutoriais inclui conexão de **Parameter Explorer e Data Explorer ao VSDD Server**, além de backup/restore e ABE Planner. Isso confirma uma arquitetura cliente-servidor vSDD.
- **[CERTO]** A página oficial VPSS 3i Blank lista Microsoft SQL Server como requisito. O tamanho e o sufixo `.vsddsqlzip` são coerentes com backup compactado do banco vSDD.
- **[CERTO]** Um guia VPSS 3i com copyright AMADA, hoje hospedado em repositório não oficial, mostra ABE Planner adicionando servidor vSDD por `Server Name`, seleção de máquinas definidas no Parameter Explorer e importação CSV com peça, quantidade, material, espessura e máquina.
- **[PROVÁVEL]** `.px3`, `.abex`, `.PD`, `.sd`, `.vtb` são pacotes de backup/configuração dos componentes indicados pelo nome. Não foi localizado schema público desses formatos.
- **[PROVÁVEL]** O machine master do Parameter Explorer/Data Explorer deve conter nome/modelo e associações usadas por CAM/SDD. Ele **pode** conter hostname/IP de servidores ou máquinas, mas nenhum manual público confirma tabela/campo de IP dentro do `.vsddsqlzip` ou `.px3`.
- **[CERTO]** Esses backups representam dados de engenharia, programas, parâmetros, materiais e planejamento. Eles não são evidência de telemetria em tempo real, alarmes ou estados de execução.

Consequência prática: a leitura legítima de configurações já extraídas pode revelar nomes de servidor, cadastros de máquinas e vínculo entre programa/peça/material, úteis para enriquecer eventos do MES. Abrir/restaurar o backup com a ferramenta AMADA em um ambiente isolado é diferente de consultar o servidor ativo; restauração não deve ser feita em produção. Para status e ciclos, ainda é necessária uma fonte operacional como VCBox, FOCAS, MTConnect ou OPC UA.

## Registro de evidências públicas

Todos os links foram acessados ou localizados em 2026-10-08. O trecho é curto e serve apenas para amarrar a conclusão à fonte.

| # | URL / fonte | Data da fonte | Trecho relevante (≤25 palavras) | Relacionado | Confiança e consequência |
|---:|---|---|---|---|---|
| 1 | [AMADA Japão — V-factory, mecanismo de conexão](https://www.sheetmetal.amada.co.jp/service/vfactory/vfactory_info.html) | página atual, acesso 2026-10-08 | “V-factory Connecting BOXとマシンは有線で接続する必要があります。” | VCBox; todas | **[CERTO]** ligação cabeada; procurar gateway e cabos/switch, sem presumir Wi-Fi |
| 2 | [Fujitsu — acordo AMADA/Fujitsu](https://info.archives.global.fujitsu/jp/news/2017/05/16-4.html) | 2017-05-16 | “OPC-UAとMT Connectのデータ交換標準規格にも対応” | VCBox | **[CERTO]** padrões fazem parte do produto; endpoint e direção seguem em aberto |
| 3 | [AMADA/Fujitsu — anúncio preservado](https://www.amada.co.jp/php/press/pdfs/000246_1.pdf) | 2017-05-16 | “センシングデータや稼働ログデータ” | VCBox; todas | **[CERTO]** tipo geral de dado coletado; cópia e hash em `evidence/public/` |
| 4 | [AMADA — conceito V-factory](https://www.amada.co.jp/php/press/pdfs/000247_1.pdf) | 2017-05-18 | “OPC-UA、MT Connect の汎用オープンインターフェイス” | VCBox | **[CERTO]** interface aberta declarada pela fabricante; falta manual técnico |
| 5 | [AMADA — My V-factory](https://www.amada.co.jp/php/press/pdfs/000269_1.pdf) | 2018-05-09 | “生産実績からマシンの実稼働状況、不稼働要因、材料・エネルギーの消費量” | todas | **[CERTO]** conjunto funcional mostrado; não prova tags abertas |
| 6 | [AMADA — solução V-factory atual](https://www.amada.co.jp/en/products/solution/) | página atual, acesso 2026-10-08 | “Operating information is uploaded in real time” | todas conectadas | **[CERTO]** produto atual suporta status remoto em tempo real; medir latência real |
| 7 | [AMADA Japão — caso com 8.200 máquinas](https://www.sheetmetal.amada.co.jp/column/case/case19/) | página atual, acesso 2026-10-08 | “国内外で8200台のアマダマシンとつながる” | ecossistema | **[CERTO]** solução implantada em escala; não prova instalação nesta planta |
| 8 | [MONOist — entrevista AMADA sobre VCBox](https://monoist.itmedia.co.jp/mn/articles/1806/18/news073_3.html) | 2018-06-18 | “OPC UAなどに対応している他CSVファイルを生成することも可能” | VCBox | **[PROVÁVEL]** export CSV; solicitar schema e habilitação atuais |
| 9 | [AMADA Taiwan — ENSIS AJ](https://www.amada.com.tw/tw/product/show.aspx?num=70) | página de produto, acesso 2026-10-08 | “V-factory Connecting Box [optional]” | ENSIS-3015AJ | **[CERTO]** opção comercial; verificar se foi comprada/instalada |
| 10 | [AMADA Brasil — ENSIS-3015AJ](https://amada.com.br/produtos/corte-a-laser-de-fibra/ensis-3015aj/) | página atual, acesso 2026-10-08 | “3kW, 6kW, 9kW e 12kW” | ENSIS-3015AJ | **[CERTO]** variante 12 kW confirmada no mercado local |
| 11 | [AMADA America — HG-2204ATC](https://www.amada.com/america/hg-2204-atc) | página atual, acesso 2026-10-08 | “AMNC 3i” | HG-2204ATC | **[CERTO]** controlador do modelo ATC; conferir identidade exata da máquina |
| 12 | [AMADA Japão — caso HG-2204ATC](https://www.sheetmetal.amada.co.jp/column/case/case10/) | caso publicado, acesso 2026-10-08 | “V-factory に標準で対応する Vfマシン” | HG-2204ATC | **[CERTO]** compatibilidade V-factory; telemetria de dobra é plausível no alvo |
| 13 | [AMADA Austrália — catálogo EGB-e](https://amada.com.au/wp-content/uploads/2024/01/EGBe-Series-Compressed.pdf) | 2023-12 | “Constant monitoring of operating conditions, sensors, power consumption” | EGB-1303e / AMNC4ie | **[CERTO]** família com V-factory; cópia e hash preservados |
| 14 | [AMADA America — EGB-e](https://www.amada.com/america/egb-e) | página atual, acesso 2026-10-08 | “AMNC 4ie” | EGB-1303e | **[CERTO]** controlador confirmado; não define protocolo direto |
| 15 | [AMADA Japão — HG ATC](https://www.sheetmetal.amada.co.jp/lineup/bend/hg-atc/hg-atc.html) | página atual, acesso 2026-10-08 | “HG-2204ATC” | HG | **[CERTO]** modelo oficial; sufixo da máquina local é lacuna crítica |
| 16 | [AMADA Japão — EGB-e](https://www.sheetmetal.amada.co.jp/lineup/bend/egb-e/egb-e.html) | página atual, acesso 2026-10-08 | “EGB-1303e” | EGB | **[CERTO]** modelo oficial da família AMNC4ie |
| 17 | [AMADA — software de rede legado](https://www.amada.co.jp/english/products/bankin/software/network.html) | página legada, acesso 2026-10-08 | “automatically consolidates and saves operating information” | vFactory legado | **[CERTO]** outra rota AMADA; identificar produto/versão antes de correlacionar |
| 18 | [AMADA Canada — vFactory](https://www.amada.ca/factorymngmt-vfactory) | página atual/legada, acesso 2026-10-08 | “real-time monitoring” | vFactory legado | **[CERTO]** dashboard de estados; não prova VCBox |
| 19 | [AMADA America — Influent](https://www.amada.com/america/influent) | página atual, acesso 2026-10-08 | “Influent Monitor collects AMADA machine data” | alternativa regional | **[CERTO]** produto de coleta existe; relevância ao Brasil é **[HIPÓTESE]** |
| 20 | [AMADA Alemanha — AMNC 3i/SDD](https://www.amada.de/index.php?L=3&id=3758) | página de produto, acesso 2026-10-08 | “connected to the AMADA SDD server via Ethernet” | AMNC 3i / HG | **[CERTO]** há fluxo proprietário de dados/programas; não é API MES comprovada |
| 21 | [AMADA Marker — CSV/XML em FMS](https://cdn.amada.eu/fileadmin/CentralData/AMADA-Marker/EN/Marker_2022_11.pdf) | 2022-11 | “CSV or XML file types” | VPSS/VSSD/FMS | **[PROVÁVEL]** integração por arquivos em produtos específicos; confirmar licenças e schema |
| 22 | [MTConnect — especificação Part 1](https://docs.mtconnect.org/MBSD_MTConnect_Part_1_2-0-0.pdf) | 2022-05-24 | “probe, current, sample, and assets” | qualquer Agent MTConnect | **[CERTO]** conjunto padrão de leitura; usar apenas se Agent real for identificado |
| 23 | [MTConnect Model — Execution](https://model.mtconnect.org/Version2.4/ObservationInformationModel/ObservationTypes/EventTypes/Execution/) | versão 2.4 | “operating state of a component” | potencial DataItem | **[CERTO]** semântica padrão; presença na AMADA é **[HIPÓTESE]** até `/probe` |
| 24 | [OPC Foundation — UA for Machine Tools 1.02](https://reference.opcfoundation.org/specs/OPC-40501-1) | 2024-11-01 | “MES, SCADA, ERP, or data analytics systems” | possível servidor OPC UA | **[CERTO]** companion spec relevante; aderência AMADA não comprovada |
| 25 | [OPC UA Machine Tools — use cases](https://reference.opcfoundation.org/specs/OPC-40501-1/5) | 2024-11-01 | “running, error, not producing, or the reason” | estados/jobs/alarmes | **[CERTO]** modelo esperado se namespace existir; não inventar NodeIds |
| 26 | [MachineMetrics — FOCAS Connectivity Guide](https://docs.machinemetrics.com/docs/machine-connectivity/focas-connectivity-guide/) | página atual, acesso 2026-10-08 | “Amada machines running the AMNC-3i interface use a Windows-based PC front-end.” | AMNC 3i/FANUC | **[PROVÁVEL]** FOCAS direto em certas máquinas; validar NCU/opção/topologia antes de teste dirigido |
| 27 | [AMADA America — atualizações VPSS](https://www.amada.com/america/current-software) | página atual, acesso 2026-10-08 | “run Total Backup Tool” | VPSS 3i/4ie | **[CERTO]** confirma ferramenta e natureza dos backups locais observados |
| 28 | [AMADA America — tutoriais de software](https://www.amada.com/america/software-tutorial-videos) | página atual, acesso 2026-10-08 | “Connect Parameter Explorer and Data Explorer to VSDD Server” | VSDD/VPSS4ie | **[CERTO]** confirma arquitetura de servidor e clientes oficiais |
| 29 | [AMADA America — VPSS3i Blank](https://www.amada.com/america/vpss3i-blank) | página atual, acesso 2026-10-08 | “SQL Server 2016 SP3 Standard Edition” | VSDD/VPSS | **[CERTO]** banco SQL faz parte das configurações suportadas; schema não publicado |
| 30 | [VPSS 3i Blank User Guide, espelho Scribd](https://www.scribd.com/document/1030204130/Vpss3i-Blank-Users-Guide) | manual ©2013; espelho não oficial | “select Network Connection or Local Connection, and set the Server Name” | ABE Planner/vSDD | **[PROVÁVEL]** configuração contém servidor lógico; fonte não oficial, não prova IP/tabela |

## Pesquisa que não encontrou contrato técnico

Foram feitas buscas combinando termos em português, inglês e japonês para `AMADA`, `VCBox`, `V-factory`, `Vf-Gateway`, `Vf-Signal`, `AMNC 3i`, `AMNC 4ie`, os três modelos, `OPC UA`, `MTConnect`, `API`, `SDK`, `NodeId`, `DataItem`, `integration manual`, `service manual`, `protocol`, `MES`, `GitHub`, Stack Overflow, Reddit e patentes.

Resultados negativos relevantes:

- nenhum repositório GitHub que implemente adaptador AMADA/VCBox foi encontrado; apareceram apenas agentes MTConnect genéricos;
- nenhum exemplo público de `Devices.xml`, `/probe`, namespace ou NodeId AMADA foi encontrado;
- nenhum manual oficial público de integração VCBox, API My V-factory ou SDK foi localizado;
- nenhum relato de fórum tinha evidência técnica suficiente para afirmar porta/protocolo/tag;
- nenhuma patente localizada revelou interface operacional mais útil que a documentação oficial;
- o site AMADA Brasil confirma o ENSIS 12 kW, mas não publica página técnica de V-factory/VCBox/API comparável à documentação japonesa.

Cobertura por tipo de fonte:

| Tipo pedido | Resultado |
|---|---|
| Sites oficiais AMADA, Japão/Europa/Américas/Ásia | evidência principal de máquinas, V-factory, VCBox, VPSS/VSDD e dados visíveis |
| Fujitsu | evidência primária da arquitetura segura e suporte OPC UA/MTConnect |
| PDFs, catálogos, press releases e material antigo | usados para EGB-e, My V-factory, AMNC3i, origem do VCBox e software de rede legado |
| Integradores/fabricantes conectando a MES | MachineMetrics forneceu evidência visual do FOCAS em AMNC-3i; MONOist registrou CSV/OPC UA do VCBox |
| GitHub | somente agentes MTConnect genéricos; nenhum adaptador AMADA/VCBox utilizável localizado |
| Stack Overflow | nenhum resultado técnico específico AMADA/VCBox com evidência reproduzível |
| Reddit e fóruns | relatos genéricos, sem documento, captura ou payload que justificasse elevar confiança |
| Patentes | nenhuma patente localizada publicou tags, NodeIds, DataItems ou protocolo aplicável ao alvo |
| Arquivos/versões antigas | usados os arquivos oficiais AMADA/Fujitsu e páginas legadas ainda acessíveis; Wayback não acrescentou contrato técnico confiável |

“Não localizado nesta pesquisa pública” não significa “não existe”. É evidência de que o próximo salto exige documentação de integrador/AMADA ou observação somente leitura de uma instalação real.

## Perguntas técnicas objetivas para a AMADA

Solicitar por escrito, referindo os números de série das três máquinas:

1. Cada máquina e seu controlador/versão suportam V-factory e qual opção/licença está instalada?
2. Existe VCBox na fábrica? É externo, embutido por máquina ou compartilhado? Qual modelo e versão?
3. O “OPC UA/MTConnect open interface” é entrada, saída ou ambos? Em qual equipamento termina a conexão do cliente?
4. Fornecer o **VCBox external integration manual** e matriz de versões.
5. OPC UA: endpoint, porta, SecurityPolicy/Mode, autenticação, certificado, namespaces, NodeSet e limites de subscription.
6. MTConnect: Agent URL, versão, `Devices.xml`, DataItems, sample interval e retenção do buffer.
7. CSV: transporte/diretório, schema, timezone, codificação, periodicidade, retenção e garantia de escrita atômica.
8. Quais campos estão habilitados por máquina: estado, programa/peça/job, início/fim, contadores, golpes, material/espessura, energia/gás, alarmes e identificação?
9. Há documentação oficial de export/API read-only do My V-factory ou Influent para MES externo?
10. Dados de ordem via LIVLOTS/AMNC4ie podem ser lidos sem permitir envio/alteração de programa?

## Menor PoC recomendado pela evidência pública

1. Comprovar inventário e topologia: modelo/série/versão de cada AMNC, VCBox/Vf-Gateway/Vf-Signal e contrato V-factory.
2. Se My V-factory já estiver contratado, confrontar uma janela curta de produção com a tela/exportação existente: estado, programa, contagem, golpes e alarmes. Isso prova quais dados chegam ao ecossistema sem tocar no CNC.
3. Obter da AMADA o caminho de exportação oficialmente suportado. Prioridade: CSV já configurado; depois MTConnect; depois OPC UA. A ordem reduz complexidade e risco, mas deve seguir o que estiver realmente licenciado.
4. Coletar uma amostra bruta somente leitura de uma máquina por interface e registrar timestamp/timezone, qualidade, frequência, reset de contador e transições de ciclo.
5. Só então escrever o adaptador AMADA → eventos normalizados do Gestor. Antes disso, qualquer conector seria baseado em hipótese.

### Critério de sucesso do PoC

Para uma máquina, obter durante um ciclo real, sem escrita no controle:

- identidade estável da máquina;
- estado com timestamp;
- programa/peça/job, se exposto;
- início e fim ou transição equivalente;
- contador de peça ou golpe;
- alarme com abertura e normalização;
- resposta após perda/reconexão;
- amostra original preservada.

O dado mais valioso para começar é `estado + programa + contador + timestamp`. Ele permite presença, ciclo e produção básica. Material, energia, manutenção e causas detalhadas podem ser incorporados depois de comprovados.

## Conclusão

**[CERTO]** Existe um caminho técnico plausível e oficialmente documentado: máquinas AMADA compatíveis → VCBox → V-factory, com OPC UA/MTConnect declarados e possível CSV. Há evidência comercial para ENSIS, EGB-e e HG-2204ATC; a HG2204 local sem sufixo exige confirmação específica.

**[HIPÓTESE]** A pesquisa pública não determina se esse caminho está instalado/ativado na empresa nem entrega o contrato necessário para programar o coletor. A investigação local deve buscar primeiro o VCBox e configurações V-factory; a investigação junto à AMADA deve pedir o manual da interface aberta, não apenas uma apresentação comercial.

**[HIPÓTESE]** Conectar diretamente aos AMNC nas portas usuais de OPC UA ou MTConnect sem evidência local seria especulação. O único ponto publicamente associado aos dois padrões é o VCBox.




