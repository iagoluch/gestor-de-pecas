# Próximo teste dirigido: obter dados reais sem tocar no controle

Data: 08/10/2026. Não há IP/endereço de CNC/VCBox comprovado. As ações abaixo são propostas; nenhuma foi executada nesta sessão além das identificadas como concluídas no registro ao final.

## Prioridade 1 — configuração ativa no PC AMADA identificado

| Item | Definição |
|---|---|
| Alvo | GTS01-PRO06, 10.10.3.22, Windows registrado no AD; não o CNC |
| Procedimento | Na sessão local legitimamente disponível, abrir somente telas de consulta do Data Explorer/Parameter Explorer e configurações existentes de CommandLog/HDVCBox; não clicar Save, Apply, Send, Restore ou registrar tarefa |
| Finalidade | Obter servidor vSDD atual, cadastros de conexão, destino HDVCBox e diretório CSV já existente |
| Impacto esperado | Consulta leve de configurações existentes. Acesso remoto/admin novo ou execução de AMADA/tool deve ser avaliado e autorizado antes, pois não foi comprovado seguro/disponível |
| Campos para registrar | hostname/IP/porta sem credencial; modo/licença; versão; máquina/serial; se export está ativo; caminho e nomes dos arquivos |

Paths identificados pelo backup: `C:\Program Files\AMADA3i\Tools\DataExplorer\CommandLogCollectionTool\`, com `CommandLogCsvUpload.exe` e `FTPSending.exe`. **Não executá-los** para fazer descoberta: poderiam produzir/enviar arquivos e alterar estado. Ler config/log já produzido é a opção inicial.

Uma listagem somente leitura seria:

```powershell
Get-ChildItem -LiteralPath 'C:\Program Files\AMADA3i\Tools\DataExplorer\CommandLogCollectionTool'
```

Esse comando é para a sessão LOCAL do PC AMADA, não para o notebook investigador, e não foi executado. Só ler arquivo identificado, pequeno e sem credenciais; não coletar senhas/tokens/chaves.

## Prioridade 2 — confirmar IP/identidade nas telas existentes

Alvo: ENSIS, HG2204 e EGB1303e. Procedimento: operador/manutenção mostrar telas de informação e configuração de rede em modo de consulta, registrando serial/controlador/versão/IP e, se exibido, gateway/servidor/VCBox. Finalidade: identificar alvo sem scanner. Impacto: leitura de telas existentes; não alterar parâmetros ou entrar em funções de controle.

FOCAS só se aplica após confirmar NCU/FANUC, Ethernet e opção/endpoint configurados. Não usar instruções de integrador que mandam alterar parâmetros do CNC. Não procurar 8193 em toda a rede.

## Prioridade 3 — ler fonte já habilitada

| Interface encontrada | Comando/procedimento inicial | Finalidade | Impacto/condição |
|---|---|---|---|
| CSV/log em diretório conhecido | `Get-Content -LiteralPath '<arquivo-real-pequeno>' -TotalCount 20` | schema/colunas/timestamps/unidades | uma leitura limitada, sem rodar exportador; conteúdo precisa ser operacional, não apenas CAM |
| MTConnect URL documentada | `GET <url-real>/probe`; depois `/current`; depois `/sample?count=10` se suportado | Devices/Components/DataItems e valores | uma requisição por vez com limite/timeout; mostrar URL/comando antes; sem streaming |
| OPC UA endpoint documentado | GetEndpoints, Browse limitado, Read dos nodes selecionados | política/namespace/NodeIds/valores | autenticação/certificado/limite aprovados; sem Write/Call e sem alterar trust/config |
| FOCAS confirmado por unidade | cliente oficial/integrador em funções de leitura documentadas | estado/programa/contador/alarme | somente após avaliação das funções/licença/limites; não executar conector genérico contra CNC por tentativa |
| My V-factory já contratado | consulta/exportação oficialmente existente | confirmar dados de runtime disponíveis | login legítimo pelo usuário; não contornar auth nem assumir API privada como suportada |

Os placeholders não são endereços descobertos nem autorização para sondagem genérica. Configurar/habilitar servidor, licença, firewall, trust, task scheduler, FTP ou exportação exige parar e pedir autorização com ação concreta. Captura do próprio host/interface também exige autorização específica; jamais MITM.

## Menor PoC operacional — [HIPÓTESE] até obter fonte

Uma máquina em produção NORMAL já programada, durante uma janela curta (por exemplo 10 minutos) aprovada para a taxa de leitura real. Salvar corpo original/CSV/XML + timestamp da origem e recebimento; começar por estado/programa/contador e observar transições sem acionar máquina para criar o teste. Correlacionar com operador/MES; não fazer POST operacional nem escrever banco.

Critério de conclusão: identidade física confirmada; ao menos duas transições observadas com qualidade/timestamp; unidade do contador e reset entendidos; programa ligado à unidade de trabalho correta; limites de acesso/latência medidos. Se o campo não existir, registrar indisponibilidade explicitamente. Alarme não deve ser provocado para teste.

## Registro de operações executadas e impacto

| Alvo | Comando/procedimento executado | Resultado | Impacto |
|---|---|---|---|
| notebook | Get-NetIPConfiguration/IPAddress/Adapter/Route/Neighbor/TCPConnection; cache DNS/hosts; apps/processos/serviços | rede e inventário passivos | leitura local; sem varredura |
| shares .210/.218 | Get-ChildItem de raízes e pastas AMADA específicas | backups, VPSS ISO, DNK | SMB com identidade atual; sem escrita remota |
| backup AMADA .218 | FileStream / ZipArchive / XmlReader de entradas selecionadas | registros CAM/VCBox/CSV; XML sanitizado | leituras pequenas/índice; sem restauração |
| DNS .201 | Resolve-DnsName GTS01-PRO06 | falha DNS | uma consulta |
| DNS .202 | Resolve-DnsName FQDN de GTS01-PRO06 e PTR de .218/.210 | IP PC e nomes servidores | três consultas direcionadas |
| 10.10.3.22 | TcpClient.ConnectAsync porta445, timeout2s, dispose | conectado | um handshake TCP, sem dados de aplicação |
| PC AMADA | net view GTS01-PRO06; listagens Components, Users/Public/Documents e Users | Users publicado; caminho antigo ausente; Users vazio | consultas SMB, sem senhas alternativas |
| AD .201 | DirectorySearcher, objectCategory=computer, nomes AMADA/VCBox/AMNC/VPSS/V-factory/LIVLOTS ou GTS01-PRO06; limite50/timeout5s | apenas GTS01-PRO06 | uma consulta LDAP corporativa |
| programa .218 | leitura/cópia LOCAL de 8571.DNK,684bytes | amostra original e texto | nenhuma escrita em máquina/share |

Não houve descoberta ativa geral de hosts, port scan, exploração, fuzzing, senha, comando CNC, captura, Write/Call OPC UA, alteração em serviços/infraestrutura, escrita operacional, commit ou push.

### Teste de leitura já executado e próximo desbloqueio

[CERTO] `evidence/live-2026-10-08/poc-leitura-planejamento.ps1` leu diretamente três CSVs existentes via SMB, sem iniciar coleta, exportação ou programa AMADA. Produziu três amostras / cinco linhas; resultado JSON na mesma pasta. Reexecução pontual: invocar o script no PowerShell. Impacto: três arquivos, aproximadamente 1,8 KB no total, mais metadados SMB; limite cinco arquivos / 200 KiB por arquivo. Não é polling contínuo nem leitura de CNC.

[PENDENTE] Próximo desbloqueio: no PC GTS01-PRO06, abrir a configuração vigente de DataExplorer/vSDD/CommandLog/HDVCBox e copiar somente endereço do servidor/box e pasta de saída existente. Sem senhas, alteração, registro de tarefa, exportação manual ou envio FTP. Alternativa: ler o IP na tela de rede de uma AMNC, sem salvar. Não ativar WinRM nem executar `winrm quickconfig` para esta investigação. Sem endereço novo comprovado, não fazer varredura OT.

### Limite de autorização informado pelo usuário — 08/10/2026

FATO INFORMADO PELO USUÁRIO: não possui autorização para entrar no PC GTS01-PRO06. A autorização de descoberta somente leitura não autoriza login remoto. A janela local de configuração RDP foi aberta com `/edit`, sem conexão automática; não houve login remoto pelo agente. Não solicitar novamente que o usuário entre, não iniciar RDP, não usar credenciais alternativas e não alterar permissões/WinRM.

PENDENTE: a TI ou o responsável autorizado pelo PC deve fornecer somente os endereços atuais de CNC/VCBox/vSDD e a pasta de uma exportação operacional existente, sem senhas. Alternativamente, pode disponibilizar uma amostra operacional sanitizada em um compartilhamento já autorizado. Leituras de arquivos atualmente acessíveis continuam dentro do escopo original; dados CNC em tempo real ainda não foram obtidos.
