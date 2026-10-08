# AMADA → Gestor de Peças: resultado da investigação

Data: 08/10/2026. Pesquisa pública PT/EN/JA, descoberta local passiva, leituras SMB/DNS/LDAP dirigidas e uma conexão TCP ao PC de programação. Nenhum pacote de teste foi enviado a CNC identificado; não houve alteração de máquina, parâmetro, infraestrutura, banco operacional ou programa.

**Resultado:** conseguimos ler arquivos reais de engenharia/programação AMADA, identificar seu PC e correlacionar as máquinas ao Gestor. **Ainda não obtivemos telemetria de execução das três máquinas.** OPC UA/MTConnect são declarados para o produto VCBox, mas nenhum endpoint instalado foi comprovado.

## Respostas às 13 perguntas

| Pergunta | Resposta e classificação |
|---|---|
| 1. Temos V-factory? | **[HIPÓTESE]** Instalação/contrato não confirmados. O backup inclui componentes relacionados a HDVCBox, mas isso pode ser configuração padrão do VPSS. |
| 2. Temos VCBox? | **[HIPÓTESE]** Não localizado. `IsSendVCBox=true` aparece com `CentOSIPadress` vazio; não prova equipamento conectado. |
| 3. Quais máquinas estão conectadas? | **[CERTO]** ENSIS3015AJ, HG2204 e EGB1303E estão cadastradas no backup de Parameter Explorer. **[HIPÓTESE]** Conexão operacional atual de qualquer uma ao V-factory/VCBox. |
| 4. Onde está o VCBox? | **[HIPÓTESE]** Localização, IP, MAC e hostname desconhecidos. Não confundir o PC Dell de programação com VCBox. |
| 5. Qual caminho máquina → VCBox/V-factory? | **[CERTO, produto]** AMADA documenta máquina → Ethernet cabeada → VCBox → plataforma. **[HIPÓTESE, planta]** Cabos, switch, segmentos, quantidade de boxes e caminho desta fábrica. |
| 6. Existe OPC UA? | **[CERTO, produto]** AMADA/Fujitsu declaram suporte no VCBox. **[HIPÓTESE, planta]** Servidor/cliente instalado, endpoint, licença, namespaces e nodes. |
| 7. Existe MTConnect? | **[CERTO, produto]** Declarado no VCBox. **[HIPÓTESE, planta]** Agent acessível e DataItems das três unidades. |
| 8. Existe outra interface? | **[CERTO, local]** SMB com programas DNK e backups VPSS/Parameter Explorer. XML local comprova ferramentas de CSV de CommandLog e envio FTP a HDVCBox; execução atual não comprovada. **[PROVÁVEL]** CSV pelo VCBox e FOCAS em certos AMNC3i; dependem de confirmação por unidade. |
| 9. Quais dados conseguimos ler? | **[CERTO]** Além dos cadastros/backups, CSVs atuais SigmaNEST: tarefa T3687, programas 9379–9381, OPs/peças, material, espessura, chapa, repetições, quantidades arranjadas e tempos estimados. DNK e SCH também legíveis. **[HIPÓTESE]** Estado/ciclo/contador/alarme/energia em tempo real. |
| 10. Conseguimos acesso local? | **[CERTO]** Leitura de `\\192.168.0.218\Arquivos`, arquivos AMADA e programas. PC `GTS01-PRO06 → 10.10.3.22`, MAC `B0-7B-25-24-F7-9B`, TCP/445 aceita conexão. `net view` mostrou apenas `Users`, cuja listagem foi vazia pela identidade atual. Caminho antigo `Components` não foi encontrado. Não equivale a acesso ao CNC, banco vSDD ativo ou VCBox. |
| 11. O que falta para conectar ao Gestor? | **[CERTO, lacuna]** Endpoint real, amostra bruta, identidade física/serial, semântica de estados/ciclos/contadores, relógio, vínculo programa/OP/chapa e arbitragem com operador/calendário. Não foi implementado conector. |
| 12. O que depende da AMADA? | **[PROVÁVEL]** Confirmar opção/versão/licença e fornecer contrato de interface externa do VCBox: direção, endpoint, autenticação read-only, tags e limites. Também esclarecer CommandLog/CSV, FOCAS por unidade e o cadastro CAM do Laser. |
| 13. Qual menor PoC? | **[CERTO, executado]** Leitor pontual de três CSVs atuais via SMB, com cinco linhas OP/peça e JSON sem escrita MES; fluxo de segunda saída DNK comprovado por configuração/hash. **[HIPÓTESE, PoC operacional]** Uma máquina, uma fonte habilitada, estado + programa + contador + timestamp durante operação normal, sem publicar fatos produtivos. |

## Achados locais que destravam a investigação

- **[CERTO]** PC de software AMADA: `GTS01-PRO06.gtsdobrasil.com.br`, DNS `10.10.3.22`; Active Directory o registra como Windows 11 Pro for Workstations. O vínculo com VPSS é comprovado nos nomes e XMLs do backup de 21/08/2026, não por inventário de processos ativos remoto.
- **[CERTO]** Arquivos em `Z:\AMADA\Backup_Software_AMADA\Amada_TotalBackup\Schedule\20260821Full`, versão `V3.03.01`.
- **[CERTO]** `CommandLogCsvUpload.exe` e `FTPSending.exe` estão referenciados em templates de tarefa. `IsTaskschRegisted=false`, endereço vSDD vazio e endereço HDVCBox vazio impedem concluir que a exportação rode.
- **[CERTO]** Cadastro HG: `NC_NAME=AMNC_3i`; EGB: `NC_NAME=AMNC_4ie`; Laser: `ID_NC_DEVICE_NAME=AMNC 3i`. O Laser também tem `ID_OSC_NAME=ENSIS2000`; isso não confirma a potência física informada de 12 kW.
- **[CERTO]** O Gestor distingue `LASER1`, `DOBRA2=HG2204`, `DOBRA3=EGB1303` e `DOBRA1=Gasparini`. A identificação física definitiva exige serial/IP.

## Adendo: análise offline de 08/10/2026

Somente leitura dos arquivos de `evidence/local/`. Resultado em [12-analise-offline-artefatos.md](12-analise-offline-artefatos.md):

- **[CERTO]** Todo artefato CommandLog/HDVCBox é modelo (datas-padrão 1753/0001, destinos vazios, sem usuário de registro). Não há CSV nem schema.
- **[CERTO]** O G92 do DNK coincide com a origem do perfil CAM no backup. Isso não prova uso atual do perfil de 2100 W; a leitura posterior identificou geração pelo SigmaNEST. Perfil ativo/potência: [HIPÓTESE].
- **[CERTO]** No share do Laser, número de programa não segue a data. `LastWriteTime` é modificação do arquivo; não comprova corte.

## Avanço comprovado: dados atuais de planejamento

**[CERTO]** Em 08/10/2026 foram lidos CSVs gerados às 11:20: tarefa T3687, programas 9379–9381, material ASTM A572, espessura 9.53 e cinco linhas de OP/peça. Quantidades arranjadas somam 105 para PCMOQ301001 e 120 para PCMOPD01001. O leitor pontual foi executado e salvou JSON, sem banco/API/CNC.

**[CERTO]** Configuração `.pst` e hash idêntico do programa 9381 comprovam SigmaNEST → `Post/Amada_ensis` → segunda saída `NESTING LASER`, no servidor 192.168.0.218. Não comprovam recepção ou execução no CNC. CSV e SCH são planejamento; estado, ciclo, produção, alarmes e energia continuam sem leitura comprovada.

**[CERTO]** Consultas atuais do PC AMADA: agendador remoto negou acesso; HTTP/80 e WinRM não forneceram conexão. Sem mudança de configuração nem credenciais alternativas. Consultas DNS/AD por nomes de máquinas/produtos não obtiveram novo alvo.

Fonte: [13-leitura-atual-sigmanest.md](13-leitura-atual-sigmanest.md), com amostras sanitizadas, campos, origens e comandos. Atualiza as respostas 8, 9, 10 e 13 acima: já existe PoC de leitura do planejamento atual; a prova operacional ainda depende de um endereço/configuração vigente ou amostra de evento da máquina.
- **[CERTO]** HG2204 e EGB1303E diferem em controlador, batentes e curso. [PROVÁVEL] `REFIX_DATE` idêntico indica manutenção de cadastro em lote, não uso.

## Limite atingido e próximo salto

Não há alvo CNC/VCBox comprovado que justifique sondagem OT. Não foi feita varredura do `/20`, teste em portas supostas de OPC UA/MTConnect/FOCAS, captura de tráfego ou tentativa de autenticação alternativa. O usuário informou não ter IPs/URL disponíveis no momento.

O próximo salto concreto é ler, no PC `GTS01-PRO06` ou nas telas AMNC, a configuração de máquinas/vSDD e de CommandLog/HDVCBox. Ver [10-proximo-teste.md](10-proximo-teste.md), com alvo, comando/procedimento, finalidade e impacto de cada opção.

## Entregas e evidência

Os onze documentos pedidos estão nesta pasta e no checkout do Gestor em `docs/amadas-investigation/`. `evidence/local/` contém respostas, XMLs sanitizados e programa original; `evidence/public/` contém quatro PDFs oficiais. [11-manifesto-sha256.csv](11-manifesto-sha256.csv) permite conferir integridade dos arquivos coletados.

Pesquisa pública: 30 fontes, com URL, data, trecho, máquina, confiança e consequência em [01-fontes-publicas.md](01-fontes-publicas.md). Inventário e topologia são fotografias desta sessão; nomes DNS, caminhos e versões podem mudar. A pesquisa não demonstra ausência de V-factory/VCBox na empresa e não esgota documentação privada da AMADA.

### Limite de autorização informado pelo usuário — 08/10/2026

FATO INFORMADO PELO USUÁRIO: não possui autorização para entrar no PC GTS01-PRO06. A autorização de descoberta somente leitura não autoriza login remoto. A janela local de configuração RDP foi aberta com `/edit`, sem conexão automática; não houve login remoto pelo agente. Não solicitar novamente que o usuário entre, não iniciar RDP, não usar credenciais alternativas e não alterar permissões/WinRM.

PENDENTE: a TI ou o responsável autorizado pelo PC deve fornecer somente os endereços atuais de CNC/VCBox/vSDD e a pasta de uma exportação operacional existente, sem senhas. Alternativamente, pode disponibilizar uma amostra operacional sanitizada em um compartilhamento já autorizado. Leituras de arquivos atualmente acessíveis continuam dentro do escopo original; dados CNC em tempo real ainda não foram obtidos.
