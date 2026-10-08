# Topologia observada e limites

Coleta em 08/10/2026. Fontes: `evidence/local/network-passive-relevant.json`, `known-amada-host-dns-followup.json`, `known-neighbors-after-directed-read.json`, `amada-ad-computer-name-search.json` e leituras SMB.

## Rede deste computador — [CERTO]

| Item | Valor observado |
|---|---|
| Host/domínio | GTS04-LOG01 / gtsdobrasil.com.br; membro do domínio |
| Interface de empresa ativa | Wi-Fi Intel Wireless-AC 9462, índice 11 |
| IPv4 / máscara | 10.10.1.248/20 / 255.255.240.0 |
| Segmento IP direto | 10.10.0.0–10.10.15.255; isto não prova segmento OT nem autoriza sondar seus 4096 endereços |
| Rota padrão | 10.10.0.1 |
| DNS | 192.168.0.201 e 192.168.0.202 |
| Ethernet física | Realtek, desconectada |
| Redes virtuais | 192.168.56.0/24 VirtualBox; 172.28.144.0/20 Hyper-V; 172.26.0.0/20 WSL |
| VPN Fortinet | Interfaces não conectadas/presentes; nenhuma rota OT específica comprovada |
| VLAN | Não identificada. Ethernet desconectada tem VLAN ID 0; isso não determina a VLAN do Wi-Fi/switch |

`netsh wlan show interfaces` falhou por permissão/localização. Nenhuma configuração ou serviço de localização foi alterado.

## Ativos identificados

| IP | Nome/MAC | O que sabemos | Classe |
|---|---|---|---|
| 10.10.3.22 | GTS01-PRO06.gtsdobrasil.com.br; B0-7B-25-24-F7-9B | PC citado no backup AMADA; A DNS confirmado; Windows 11 Pro for Workstations no AD; 445 aceita conexão | [CERTO] |
| 192.168.0.218 | PTR gts-neri.gtsdobrasil.com.br | Servidor de `\\192.168.0.218\Arquivos`, mapeado em Z:, contém backup e DNK AMADA | [CERTO] |
| 192.168.0.210 | PTR SVR-FS.gtsdobrasil.com.br | `Departamentos`, mapeado em G: | [CERTO] |
| 192.168.0.201 | cache svr-dc01.gtsdobrasil.com.br | DNS e LDAP corporativos acessíveis | [CERTO] |
| 192.168.0.202 | servidor DNS configurado | Respondeu consultas A/PTR dirigidas | [CERTO] |
| 10.10.0.1 | 00-09-0F-09-00-12 | Gateway; prefixo IEEE Fortinet | [CERTO] IP/MAC/função de rota; [PROVÁVEL] equipamento Fortinet |
| 10.10.0.22 | 44-31-92-EC-A9-42 | Vizinho inicial, prefixo IEEE Hewlett Packard; função desconhecida | [CERTO] vizinho; [HIPÓTESE] qualquer relação AMADA |
| 10.10.4.1 | 00-15-5D-00-50-06 | Vizinho com prefixo IEEE Microsoft; pode ser virtual; função desconhecida | [CERTO] vizinho; [HIPÓTESE] função |
| 10.10.7.60 | MAC zero, Unreachable | Registro de tentativa anterior na tabela, não host vivo confirmado | [CERTO] registro; [HIPÓTESE] existência atual |

Fabricantes de prefixo verificados na [lista oficial IEEE](https://standards-oui.ieee.org/oui/oui.csv), acesso 08/10/2026, recorte em `ieee-known-oui.json`. Prefixo não identifica modelo/função e pode ser virtualizado. Os MACs dos CNC e do VCBox continuam desconhecidos.

## Desenho factual

```text
GTS04-LOG01 — Wi-Fi 10.10.1.248/20
   ├─ rota padrão 10.10.0.1 [gateway]
   ├─ DNS/LDAP 192.168.0.201/202
   ├─ SMB 192.168.0.218 [Arquivos: backups VPSS e DNK]
   ├─ SMB 192.168.0.210 [Departamentos]
   └─ acesso dirigido TCP/SMB 10.10.3.22 [GTS01-PRO06]

backup VPSS de GTS01-PRO06
   ├─ cadastro ENSIS3015AJ / AMNC 3i
   ├─ cadastro HG2204 / AMNC_3i
   └─ cadastro EGB1303E / AMNC_4ie
```

As linhas são relações observadas de rota, serviço ou cadastro. Não mostram ligação física CNC–PC, nem provam que o PC seja ponte de telemetria. Não foi identificado switch, número de porta ou VLAN OT.

## Desenho a comprovar — [HIPÓTESE]

```text
ENSIS [IP?] ─┐
HG2204 [IP?] ├── switch/rede [?] ── VCBox(s) [?] ── V-factory [?]
EGB [IP?] ───┘
       ↕ programação/vSDD [?]
GTS01-PRO06 [10.10.3.22]
```

Não se conhece o número de VCBoxes. Não foi comprovado que um único box atenda às três máquinas. O fluxo industrial deve ser conferido por cadastro/cabos/configuração; uma rota IP do PC não comprova acesso à rede interna do FANUC ou do AMNC.

### Topologia adicional comprovada

[CERTO] O pós-processador SigmaNEST configura NCPATH em `Z:\SIGMANEST\SNDATA_serv\Post\Amada_ensis\` e NCPATH2 em `Z:\NESTING LASER\`, com segunda saída ligada. [CERTO] SHA-256 do programa 9381 coincide nas duas pastas. Z corresponde a `\\192.168.0.218\Arquivos`. O caminho servidor de arquivos → CNC e o produtor físico dos CSVs não foram identificados. Não incluir esse servidor como VCBox. Ver documento 13.
