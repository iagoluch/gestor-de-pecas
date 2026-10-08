# Leitura atual comprovada — ENSIS / SigmaNEST

Data: 08/10/2026, consultas entre 11:24 e 11:40, horário do computador −03:00. Somente leitura; nenhuma escrita em máquina, infraestrutura, banco ou API MES. Evidências desta etapa: `evidence/live-2026-10-08/`.

## Resultado concreto

**[CERTO]** Foram lidos três CSVs existentes no servidor de arquivos, criados pelo planejamento hoje às 11:20: tarefa `T3687`, programas `9379`, `9380`, `9381`. Foi executado um leitor pontual contra esses três arquivos, produzindo três amostras e cinco linhas de OP/peça em `poc-planejamento-resultado.json`. Nenhum dado foi gravado no Gestor.

**[CERTO]** O caminho configurado no pós-processador é:

```text
SigmaNEST — pós-processador Amada_ensis.pst / Amada_ensis.pas
  ├─ Post\Amada_ensis\9379–9381.DNK + T3687.SCH
  ├─ eReport\9379–9381.CSV
  └─ segunda saída NC: Z:\NESTING LASER\9379–9381.DNK
       └─ recepção/seleção no CNC: ainda desconhecida
```

`Z:` corresponde a `\\192.168.0.218\Arquivos`. É um servidor de arquivos, não um endereço CNC comprovado.

**[CERTO]** `Amada_ensis.pst`, linhas 347–350 da cópia sanitizada, contém `NCPATH=Z:\SIGMANEST\SNDATA_serv\Post\Amada_ensis\`, `NCEXT=.DNK`, `NCPATH2=Z:\NESTING LASER\`, `SAVE SECOND FILE=1`. A origem e a segunda saída do programa `9381.DNK` têm o mesmo SHA-256: `C700315A67DC07A7C393EA63DF8AC5A01FAD98BBCA9C855A11BA5EC63E99EFDE`. As duas cópias tinham 86.138 bytes. Evidência: `program-9381-export-hash-match.json`.

## Amostras reais

| Programa | Layout | Repetições declaradas | Tempo CSV | OP / peça / quantidade arranjada |
|---|---|---|---|---|
| 9379 | 1 | 2x | 00:39:00 | PCMOQ301001 / PPM008001017 / 74; PCMOPD01001 / PPM008001021 / 2 |
| 9380 | 2 | 1x | 00:41:54 | PCMOQ301001 / PPM008001017 / 31; PCMOPD01001 / PPM008001021 / 7 |
| 9381 | 3 | 3x | 00:55:42 | PCMOPD01001 / PPM008001021 / 111 |

**[CERTO]** Os três CSVs declaram `Maquina=Amada_ensis`, `Tarefa=T3687`, material `ASTM A572`, espessura `9.53`, chapa `S173`, dimensões 3000 × 1500. Os registros contêm `Data_Criacao` entre 11:20:17 e 11:20:20 de 08/10/2026, sem indicação de fuso na origem. Não adicionar fuso silenciosamente.

**[CERTO]** Soma declarada por OP: PCMOQ301001 = 74 + 31 = 105, igual à quantidade requerida 105; PCMOPD01001 = 2 + 7 + 111 = 120, igual à requerida 120. Total arranjado dos arquivos: 225. Não é quantidade produzida ou boa.

**[PROVÁVEL]** `Quant_Arranjada` já agrega as repetições do layout: 74/2=37, 2/2=1 e 111/3=37. Não multiplicar novamente sem confirmar o gerador do eReport e a unidade de cada linha no contrato SigmaNEST.

O programa 9381 declara `PR9381`, `MC/TR=Ensis3015AJ`, `MA=SS400-9.0E`, `WK=9.53T 3000X1500`, `TT01H07M50S`, `CRY2026M10D08` e referências `PPM008001021`. **[CERTO]** O código de condição/material no DNK difere do nome de material do CSV. Correspondência entre `SS400-9.0E` e `ASTM A572`: **[HIPÓTESE]**, exige tabela aprovada; não são sinônimos comprovados por estes arquivos.

**[CERTO]** CSV 9381 apresenta 00:55:42, enquanto DNK 9381 apresenta 01:07:50. Escopo, fatores e fórmula que explicam a diferença: **[HIPÓTESE]**. Preservar ambos; nenhum é duração medida na máquina.

## Origem técnica dos campos

| Campo | Origem lida | Conclusão |
|---|---|---|
| MC / TR / MN | `Amada_ensis.pas:665–667`, literais Ensis3015AJ / Ensis3015AJ / 239 | [CERTO] rótulos gerados pelo pós-processador; não consulta de identidade ao CNC |
| TT | `Amada_ensis.pas:701,709,2036–2047`, `PostObj.GetVariable('#60')` | [CERTO] tempo vem do contexto do SigmaNEST e é formatado para o programa; não telemetria |
| CR | `Amada_ensis.pas:697–702`, `Now` | [CERTO] data produzida durante geração do programa |
| `.SCH` MachineName=FOLAJ | `Amada_ensis.pas:55` e geração do cabeçalho | [CERTO] literal configurado; não hostname, serial ou detecção de outra máquina |
| product_quantity=2/1/3 | linhas do SCH e `PostObj.NumSheets` no gerador | [CERTO] repetições de chapa planejadas; não número de peças boas |
| reception_quantity=0 / rejection_quantity=0 / complete_code=2 | `Amada_ensis.pas:2265–2267`, valores constantes na geração | [CERTO] não evidência de recepção, refugo zero ou conclusão real |
| PRGNAME.DAT=9381 | arquivo e rotina de incremento no pós-processador | [PROVÁVEL] contador de nomes de programas gerados; nunca contador de produção |

Nenhum `.pas`, `.pst`, `.bat`, programa CNC ou exportador AMADA foi executado. O texto foi analisado como dado. Cópias são sanitizadas; nomes de programador foram omitidos nas novas amostras. Os hashes originais dos CSVs estão no resultado do leitor; o manifesto verifica as cópias entregues, que têm hashes diferentes após sanitização.

## Campos legíveis e uso no Gestor

| Campo existente no CSV | Exemplo | Uso candidato | Limite |
|---|---|---|---|
| Tarefa / Programa / Layout | T3687 / 9381 / 3 | correlação de planejamento com programa observado no futuro | não informa programa selecionado/agora no CNC |
| OS / Peca | PCMOPD01001 / PPM008001021 | OP e produto observados por linha | OS precisa corresponder a WONumber/TOTVS; código de peça não substitui OP |
| Quant_Requerida / Quant_Arranjada | 120 / 111 | reconciliação da composição planejada | não gravar em eventos_quantidade_producao |
| Repeticoes | 3x | quantidade de chapas planejada | não equivale automaticamente a RepeatID nem chapa física finalizada |
| Cod_Chapa / dimensões | S173 / 3000 × 1500 | contexto de material/chapa | não há identificador de chapa física executada |
| Material / Espessura | ASTM A572 / 9.53 | comparação com planejamento | declaração, não medição do material físico |
| Tempo / Tempo_Unitario | 00:55:42 / 00:01:30 | estimativas mantidas com origem | fórmula e homologação do padrão pendentes |
| Data_Criacao | 08/10/2026 11:20:20 | timestamp de geração do planejamento | sem fuso; não início/fim de ciclo |

**[CERTO]** O Gestor já possui `SigmaNestCutPlan`, `SigmaNestPartLine` e catálogo de planejamento (`mes/integrations/sigmanest/models.py`, `app/database/sigmanest_repository.py`). **[HIPÓTESE]** CSV como fonte alternativa/complementar. Ainda faltam identidade de repetição/chapa e validação de unidade para projetá-lo no catálogo sem colisões. Não foi implementado importador nem alterado o fluxo vigente.

## Testes novos e limites de acesso

Todos os testes direcionados abaixo foram apresentados com alvo, comando, finalidade e impacto antes da execução. Identidade Windows existente, sem credenciais alternativas.

| Alvo / procedimento | Resultado | O que permite concluir |
|---|---|---|
| GTS01-PRO06 / `schtasks /query /s GTS01-PRO06 /fo CSV` | acesso negado | [CERTO] a identidade atual não conseguiu consultar o agendador remoto; não prova ausência de tarefas |
| 10.10.3.22 / HTTP GET `/`, curl, timeout 3 s, limite 64 KiB | falha de conexão TCP/80 | [CERTO] não obtivemos resposta HTTP neste endereço/porta; não prova ausência de outras interfaces |
| GTS01-PRO06 / CIM Win32_Service via WSMan, filtro AMADA/SDD/VCBox/V-factory, timeout 8 s | conexão ao destino falhou | [CERTO] serviços não inventariados; não foi executada a sugestão `winrm quickconfig` da mensagem de erro |
| 192.168.0.218 / `net view` | share Arquivos | [CERTO] enumeração acessível; não identifica CNC |
| 192.168.0.201 / LDAP dnsNode por nomes AMADA/ENSIS/VCBox/VFACT/HG/EGB e laser/dobra/AMNC/VPSS/LIVLOTS/Fujitsu | zero correspondências visíveis nos filtros | [CERTO] nenhum endereço adicional obtido por essas consultas; não prova ausência de máquinas ou registros protegidos |
| Pastas específicas Produção/Apontamentos/FilesCfg/SNDATA_serv | listagens limitadas, sem recursão indiscriminada | [CERTO] encontrou fonte CSV atual; não foi uma busca completa em todos os servidores |

A primeira tentativa LDAP em `CN=MicrosoftDNS` falhou; a consulta corrigida na raiz das partições foi executada com sucesso. Evidências registram ambas para não tratar erro de consulta como ausência de registros.

## Correção da conclusão sobre potência

**[CERTO]** O backup AMADA declara ENSIS2000 / 2100 no perfil CAM. **[CERTO]** os arquivos atuais existem no fluxo SigmaNEST com geração independente dos comentários MC/TR e caminho NC configurado. Igualdade de G92/origem não prova que esse backup de perfil AMADA gera os programas atuais. A alegação anterior foi corrigida no documento 12.

**[HIPÓTESE]** O perfil AMADA está desatualizado, ativo ou é usado em outro fluxo. Não alterar potência, condições ou parâmetros em qualquer software/máquina com base nesta investigação.

## Próximo passo operacional

O bloqueio agora é obter configuração atual ou um endpoint identificado das máquinas/VCBox. Trocar modelo de IA não concede acesso Windows nem revela IPs não expostos nestas fontes.

No PC GTS01-PRO06, abrir DataExplorer e localizar a configuração vigente de vSDD/CommandLog/HDVCBox. Copiar somente endereço do servidor, endereço do box e pasta de saída, caso existam; sem credenciais e sem executar exportação/FTP. Um desses endereços permitiria um teste direcionado de leitura. Alternativa física: ler a tela de rede de uma AMNC, sem salvar alterações.

Ainda não lemos estado, ciclo, contador de produção, alarmes ou energia de nenhuma das três máquinas. V-factory/VCBox local, OPC UA e MTConnect continuam **[HIPÓTESE]**.

### Limite de autorização informado pelo usuário — 08/10/2026

FATO INFORMADO PELO USUÁRIO: não possui autorização para entrar no PC GTS01-PRO06. A autorização de descoberta somente leitura não autoriza login remoto. A janela local de configuração RDP foi aberta com `/edit`, sem conexão automática; não houve login remoto pelo agente. Não solicitar novamente que o usuário entre, não iniciar RDP, não usar credenciais alternativas e não alterar permissões/WinRM.

PENDENTE: a TI ou o responsável autorizado pelo PC deve fornecer somente os endereços atuais de CNC/VCBox/vSDD e a pasta de uma exportação operacional existente, sem senhas. Alternativamente, pode disponibilizar uma amostra operacional sanitizada em um compartilhamento já autorizado. Leituras de arquivos atualmente acessíveis continuam dentro do escopo original; dados CNC em tempo real ainda não foram obtidos.
