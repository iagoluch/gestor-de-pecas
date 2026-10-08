# Inventário das três máquinas

Data: 08/10/2026. Inventário físico fornecido pelo usuário; cadastro de engenharia comprovado no backup de 21/08/2026; identidade MES comprovada no código e catálogo histórico, sem consulta ao banco ativo.

| Equipamento informado | Evidência local lida | Recurso Gestor | Identidade/telemetria pendente |
|---|---|---|---|
| ENSIS-3015AJ 12 kW — AMNC 3i | Parameter Explorer: `localhost/Machines/Blank/ENSIS3015AJ/`; `ID_NC_DEVICE_NAME=AMNC 3i`. DNK: `MCEnsis3015AJ`, `TREnsis3015AJ` | LASER1; SigmaNEST AMADA_ENSIS | Serial, IP/MAC CNC, versão real, potência/oscillator físico, VCBox e protocolo |
| HG2204 — AMNC 3i | `MachineRegistration.xml`: `NAME_DISPLAY=HG-2204`, `MODEL=2204`, `NC_NAME=AMNC_3i` | DOBRA2 | Serial, sufixo/ATC, IP/MAC, versão real, VCBox e protocolo |
| EGB1303e — AMNC 4ie | `MachineRegistration.xml`: `NAME_DISPLAY=EGB-1303`, `MODEL=1303`, `NC_NAME=AMNC_4ie`; pasta EGB1303E | DOBRA3 | Serial, IP/MAC, versão real, VCBox e protocolo |

**[CERTO]** Os valores acima existem nos arquivos; **[PROVÁVEL]** correspondem às unidades físicas informadas. Templates e cadastros CAM não substituem plaqueta nem leitura do controlador ao vivo.

## Ressalvas materiais

- Laser: o mesmo XML apresenta `ID_OSC_NAME=ENSIS2000`. Não foi interpretado como prova de laser de 2 kW e não confirma o de 12 kW. Pode ser cadastro/template, mas essa explicação é **[HIPÓTESE]**. A AMADA deve validar perfil/postprocessador usado.
- HG: fontes públicas de HG-2204ATC não comprovam que a HG2204 local tenha ATC. O XML local confirma controlador configurado AMNC_3i, sem inferir o sufixo físico.
- `V3.03.01` vem dos backups de componentes VPSS; não é firmware do CNC.
- O catálogo MES histórico vem de PC Factory e TESTE em 20/08/2026. Não foi lido catálogo REAL atual. `DOBRA1` é Gasparini, não a primeira AMADA da lista do usuário.

Amostras sanitizadas por máquina em `evidence/local/sanitized__*.xml`. O parâmetro `COUNT` de ferramentas e `SET_BI_COUNT` no cadastro não foi tratado como contador de produção/golpos.
