# Evidência local: origem, data e alcance

Coleta: 08/10/2026, America/Sao_Paulo. Originais remotos não foram modificados. XMLs entregues são representações sanitizadas; `sample-program-8571-original.DNK` é a cópia de bytes do programa. O manifesto SHA-256 valida as cópias entregues, não substitui hash do backup completo remoto.

| Evidência | Fonte legítima | Data da fonte | Trecho/resultado relevante | Máquina/confiança/consequência |
|---|---|---|---|---|
| network-passive-relevant.json | APIs locais Windows Get-Net*/cache/hosts/mapeamentos | snapshot 08/10/2026 | Wi-Fi 10.10.1.248/20; DNS .201/.202; G:/Z: existentes | [CERTO] posição do investigador; não inventariou CNC |
| known-amada-host-dns-followup.json | Resolve-DnsName em DNS corporativo .202 | 08/10/2026 | GTS01-PRO06.gtsdobrasil.com.br = 10.10.3.22 | [CERTO] resposta DNS naquele instante; alvo PC de programação candidato |
| amada-ad-computer-name-search.json | LDAP corporativo .201, identidade Windows atual, filtro delimitado | 08/10/2026 | GTS01-PRO06; Windows 11 Pro for Workstations | [CERTO] cadastro AD; não é inventário de processos ativos |
| known-neighbors-after-directed-read.json | tabela ARP/neighbor local | 08/10/2026 | 10.10.3.22 → B0-7B-25-24-F7-9B | [CERTO] relação IP/MAC observada; sem evidência de CNC |
| ieee-known-oui.json | https://standards-oui.ieee.org/oui/oui.csv | download 08/10/2026 | B07B25 Dell; 00090F Fortinet; 00155D Microsoft; 443192 HP | [CERTO] fabricante registrado do prefixo; não prova modelo do ativo |
| amada-pc-single-tcp445.json e amada-pc-net-view.txt | PC identificado, uma conexão TCP + SMB net view | 08/10/2026 | 445 conectado; compartilhamento Users | [CERTO] transporte/enumeração; nenhum acesso runtime |
| amada-pc-*-read/public-documents/users-share-root.json | listagens SMB direcionadas | 08/10/2026 | Components ausente; Users sem itens visíveis | [CERTO] respostas desta identidade; não prova disco vazio |
| amada-latest-backup.json | `\\192.168.0.218\Arquivos\AMADA\Backup_Software_AMADA\Amada_TotalBackup\Schedule\20260821Full` | 21/08/2026 | componentes V3.03.01, GTS01-PRO06 | [CERTO] backup/cadastro software; não firmware atual |
| sanitized__CommandLogOutput__*.xml | entradas do CommonSettings.vtb nesse backup | backup 21/08/2026 | IsTaskschRegisted=false; IsSendVCBox=true; CentOSIPadress vazio | [CERTO] configuração offline; ativação atual [HIPÓTESE] |
| sanitized__DataExplorer__DataExplorerSetting.xml | mesmo .vtb | backup 21/08/2026 | LastSelectedFolder = GTS01-PRO06/Components/Máquinas AMADA/HG2204 | [CERTO] caminho histórico, origem da investigação do PC |
| parameter-explorer-zip-entries.json e XMLs MachineRegistration | ParameterExplorer.px3 no mesmo backup | 21/08/2026 | EGB1303E/HG2204/ENSIS3015AJ; AMNC_4ie/AMNC_3i | [CERTO] modelos/controladores CAM; runtime [HIPÓTESE] |
| sanitized__ENSIS3015AJ_MACHINE_INFORMATION.xml | entrada de ParameterExplorer.px3 | 21/08/2026 | AMNC 3i; ID_OSC_NAME=ENSIS2000 | [CERTO] cadastro; potência física 12 kW não confirmada pelo XML |
| sample-program-8571-original.DNK | `\\192.168.0.218\Arquivos\NESTING LASER\8571.DNK` | LastWriteTime 24/08/2026; CR Y2026M08D24 | PR8571, MCEnsis3015AJ, E-SPC1.25, WK1.25T, TT00H01M37S | [CERTO] programa disponível; tempo previsto [PROVÁVEL], programa atual [HIPÓTESE] |

Listagens e índices foram preservados para reproduzir o caminho de investigação. Nomes de shares/pastas não são prova de licença/serviço conectado. Campos sensíveis foram omitidos dos XMLs antes de gravação/saída; nenhuma senha/token/chave foi testada ou extraída para uso.
