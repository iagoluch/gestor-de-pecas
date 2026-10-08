# Lacunas, cobertura e limite de conclusão

## Lacunas que impedem coletor operacional

1. **[HIPÓTESE]** Existência/localização de VCBox, contrato My V-factory e máquinas efetivamente conectadas.
2. **[HIPÓTESE]** IP/MAC/serial dos CNC, rede interna NC–PC, switch/VLAN/ACL e percurso físico.
3. **[HIPÓTESE]** Endpoint/direção/licença/read-only de OPC UA, MTConnect, FOCAS, API ou exportação CSV.
4. **[HIPÓTESE]** NodeIds/DataItems/schema, unidades, frequência, qualidade, timestamps/UTC e retenção.
5. **[HIPÓTESE]** Semântica de contador de peça/golpe/chapa, reset, ciclo, alarme e programa/job.
6. **[HIPÓTESE]** Conteúdo operacional de CommandLog: pode registrar ações do software de programação; não foi encontrado CSV produzido.
7. **[HIPÓTESE]** Estado atual do vSDD, tarefas de exportação e licença VPSS no GTS01-PRO06. Backup tem parâmetros relevantes vazios.
8. **[HIPÓTESE]** Vínculo de serial/IP às identidades LASER1/DOBRA2/DOBRA3 e potência real correspondente ao perfil CAM ENSIS2000.

**Refinamento offline (08/10/2026), ver [12-analise-offline-artefatos.md](12-analise-offline-artefatos.md):**

- Lacuna 6: [CERTO] nenhum artefato local contém CSV, schema ou execução do CommandLog; os XMLs são modelos com datas-padrão. Fecha só com um CSV real + XML da tarefa ativa.
- Lacuna 8: [CERTO] o DNK 8571 usa a origem do perfil `ENSIS2000` (2100 W máx.). [PROVÁVEL] perfil CAM desatualizado frente à unidade de 12 kW. Até confirmar, `TT` não serve como padrão de tempo.
- Nova lacuna 9: [HIPÓTESE] significado de `MN`, `E5` e `M103/M104` no DNK. Precisa do manual de programação AMNC ou do pós-processador.

**Menor amostra para avançar:** um CSV real do CommandLog (com pasta e XML da tarefa ativa) ou um log HDVCBox, contendo máquina/serial, data/hora com fuso, tipo de evento, `PR`, início/fim e contador com unidade. Mais foto da plaqueta ou tela AMNC da ENSIS.

## Cobertura realizada

| Fase | Evidência e limite |
|---|---|
| Pública | 30 fontes, três idiomas, sites oficiais de vários países, PDF/manual/catálogo legado, Fujitsu, integrador, padrões. Cobertura negativa de GitHub/SO/Reddit/fóruns/patentes/arquivos em 01; não foi inspeção literal de todos os sites AMADA de todos os países. |
| Host passivo | interfaces/endereço/máscara/rotas/DNS/ARP/conexões/cache/hosts/mapeamentos, apps/processos/serviços e busca por nomes de arquivos nos locais descritos abaixo |
| Compartilhamentos | leitura de raízes G:/Z:, AMADA/backups e NESTING LASER; sem recursão indiscriminada em shares |
| Topologia | PC AMADA, servidores de arquivos/DNS e gateway identificados; CNC/VCBox/switch/VLAN não localizados |
| Dirigida de baixo impacto | DNS A/PTR de nomes/IP conhecidos, LDAP com limite 50/timeout 5s, uma conexão TCP/445, net view e listagens SMB em PC comprovado |
| MTConnect / OPC UA | não exercitados: não há endpoint comprovado; não são resultados negativos de porta |
| MES | leitura de código/catálogo histórico/contratos; nenhum banco/API ativo consultado |
| Engenharia reversa controlada | assinatura/índice ZIP, XMLs pequenos sanitizados, configuração CAM e programa DNK; nenhuma decriptação, credencial ou execução AMADA |
| Captura de tráfego | não realizada; exige autorização específica do usuário |

Busca local de nomes passou por Program Files, Program Files (x86), ProgramData, AppData Roaming/Local e Documents. Excluiu caches, browsers, node_modules, venv/site-packages, Packages, Codex e capturas volumosas. Permissões negadas e áreas excluídas impedem declarar inspeção integral do disco. Hits de `chamadas`/CMake Fujitsu foram falsos positivos, não softwares AMADA. Filtro exato não identificou serviço AMADA/OPC UA no PC do investigador. A busca textual no histórico PowerShell não produziu candidato relevante; só metadados de termos/IPs seriam preservados, sem comandos/segredos.

## Testes com resultado negativo ou inconclusivo

- Consulta DNS do nome curto GTS01-PRO06 no .201 falhou. FQDN no .202 respondeu 10.10.3.22; não insistiu em variações de endereço.
- `\\GTS01-PRO06...\Components\Máquinas AMADA` e `Users\Public\Documents` não foram encontrados. `Users` foi enumerável, mas vazio pela identidade atual. Não concluir ausência de arquivo no disco do PC.
- `netsh wlan show interfaces` requer permissão/localização. Não se elevou nem alterou privacidade.
- Não há inventário físico nem amostra de runtime. Firmware/serial/alarme/contador real permanecem desconhecidos.
- Backup vSDD de 815 MB não foi transferido integralmente/restaurado; apenas assinatura 7z lida. Schema e conteúdo do banco continuam desconhecidos.

## Dependências externas concretas

**[PROVÁVEL]** AMADA/suporte integrador deve fornecer contrato técnico da interface externa por serial/versão. TI local pode disponibilizar consulta aos cadastros e config ativa, sem ampliar permissão automaticamente. Operação/manutenção pode mostrar telas de informação/rede existentes, sem entrar em ajuste de NC.

O usuário respondeu que não possui IPs/URL no momento. O próximo teste foi preparado para trabalhar a partir do PC identificado e de telas de consulta; não depende de varrer o `/20`.

## Invariantes MES antes de implementação

Não classificar CNC ACTIVE como produção boa/OP iniciada; não igualar golpes a peças; não finalizar Corte/OP por programa encerrado; não converter timeout em máquina desligada; não sobrescrever timeline do operador/scheduler. Programas do Laser podem conter múltiplas OPs e chapas/repetições. Qualidade e regra de OEE permanecem canônicas.

### Lacunas após consultas atuais

[CERTO] Acesso ao agendador GTS01-PRO06 foi negado. HTTP/80 e consulta CIM de serviços via WinRM não forneceram conexão. Consultas LDAP/DNS por nomes AMADA/ENSIS/HG/EGB/VCBox e laser/dobra/AMNC/VPSS/LIVLOTS/Fujitsu não retornaram novos alvos visíveis. Nenhuma credencial alternativa ou mudança de serviço foi tentada.

[CERTO] A lacuna de amostra de planejamento atual foi fechada: existem CSVs e SCH de T3687 em 08/10/2026. Continua aberta a lacuna de evento operacional CommandLog/VCBox/CNC, IP das máquinas e interface externa. A igualdade de G92 não comprova uso do perfil AMADA de 2100 W; alegação corrigida no documento 12, com evidência adicional no 13.

### Limite de autorização informado pelo usuário — 08/10/2026

FATO INFORMADO PELO USUÁRIO: não possui autorização para entrar no PC GTS01-PRO06. A autorização de descoberta somente leitura não autoriza login remoto. A janela local de configuração RDP foi aberta com `/edit`, sem conexão automática; não houve login remoto pelo agente. Não solicitar novamente que o usuário entre, não iniciar RDP, não usar credenciais alternativas e não alterar permissões/WinRM.

PENDENTE: a TI ou o responsável autorizado pelo PC deve fornecer somente os endereços atuais de CNC/VCBox/vSDD e a pasta de uma exportação operacional existente, sem senhas. Alternativamente, pode disponibilizar uma amostra operacional sanitizada em um compartilhamento já autorizado. Leituras de arquivos atualmente acessíveis continuam dentro do escopo original; dados CNC em tempo real ainda não foram obtidos.
