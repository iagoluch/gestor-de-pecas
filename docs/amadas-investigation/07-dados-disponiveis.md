# Dados realmente disponíveis e dados ainda não comprovados

## Valores lidos nesta sessão — [CERTO]

| Campo/fonte | Significado e exemplo real | Frequência observada | Máquina | Utilidade MES |
|---|---|---|---|---|
| XML / NC_NAME | controlador configurado `AMNC_3i` | snapshot 21/08/2026 | HG2204 | identidade de cadastro |
| XML / NC_NAME | controlador configurado `AMNC_4ie` | snapshot 21/08/2026 | EGB1303E | identidade de cadastro |
| XML / ID_NC_DEVICE_NAME | `AMNC 3i` | snapshot 21/08/2026 | ENSIS3015AJ | identidade de cadastro |
| XML / ID_OSC_NAME | `ENSIS2000` | snapshot 21/08/2026 | perfil ENSIS | verificar discrepância com unidade 12 kW; não inferir potência física |
| XML / NAME_DISPLAY, MODEL | `HG-2204/2204`, `EGB-1303/1303` | snapshot 21/08/2026 | dobradeiras | associar ao catálogo de recursos, com conferência física |
| Nome de backup | V3.03.01 e GTS01-PRO06 | snapshot 21/08/2026 | software VPSS | localizar PC/configuração; não é firmware CNC |
| DNK / PR | `(PR8571)` | arquivo de 24/08/2026; leitura 08/10 | ENSIS | identificador de programa disponível no share |
| DNK / MC, TR | `Ensis3015AJ` | arquivo estático | ENSIS | perfil/alvo declarado pelo postprocessador |
| DNK / MA, M102 | `E-SPC1.25` | arquivo estático | ENSIS | código de material declarado; composição comercial precisa de catálogo |
| DNK / WK | `1.25T 3000.00X 1200.00` | arquivo estático | ENSIS | espessura/dimensões declaradas da chapa |
| DNK / TT | `00H01M37S` | arquivo estático | ENSIS | campo de tempo do programa; [PROVÁVEL] estimativa CAM, nunca tempo realizado medido |
| DNK / comentários de peça | `14333283` aparece em seções do programa | arquivo estático | ENSIS | candidato a vínculo de produto; [HIPÓTESE] semântica e quantidade física |
| DNK / CR | `Y2026M08D24` | arquivo estático | ENSIS | data declarada de geração; não timestamp de execução |
| DNK / MN | `239` | arquivo estático | ENSIS | [HIPÓTESE] significado desconhecido; não usar |
| DNK / PROGRAMADOR | campo presente (valor pessoal omitido) | arquivo estático | ENSIS | quem gerou o programa; não quem operou |
| DNK / G92 | `X3070.0 Y1550.0` = `ID_ORIGIN_X/Y` do XML ENSIS3015AJ | arquivo estático | ENSIS | prova que o DNK sai do perfil CAM `ENSIS2000` |
| DNK / E5, geometria | condição `E5`; 2 contornos de 2900,14 × 490,94 mm | arquivo estático | ENSIS | contexto de corte; 2 geometrias ≠ 2 peças produzidas |
| Share / LastWriteTime | 759 DNK, 24/08 a 08/10/2026; número não segue a data | listagem 08/10 | ENSIS | data de exportação/regravação; não data de corte |
| XML ENSIS / OSC, driver | `ENSIS2000`, `OUTPUT_MAX=2100`, `AMADA LC1212 AI`, origem 3070/1550 | snapshot 21/08/2026 | perfil ENSIS | perfil CAM; divergente da unidade 12 kW informada |

Detalhamento e fontes por campo: [12-analise-offline-artefatos.md](12-analise-offline-artefatos.md).

Programa original preservado em `evidence/local/sample-program-8571-original.DNK` (684 bytes). `sample-program-8571.DNK.txt` é cópia textual decodificada, não bytes originais. O original contém comandos CNC; foi somente lido, nunca executado/enviado.

Amostra não demonstra programa atual, peça produzida, OP, quantidade boa, ciclo iniciado/finalizado ou máquina ligada. Valores `COUNT` de ferramentas no XML não são contadores de produção.

## Matriz por máquina: requisitos operacionais

Legenda: **NC** = não comprovado ao vivo; **CAM** = cadastro/programa offline lido; **VF** = capacidade de produto documentada, acesso externo local desconhecido.

| Grupo/campos pedidos | ENSIS | HG2204 | EGB1303e | O que falta |
|---|---|---|---|---|
| Ligada/desligada | NC | NC | NC | sinal de power documentado; timeout não basta |
| Executando/parada/espera/setup/alarme | VF/NC | VF/NC | VF/NC | valores reais, transições e separação de causas |
| Programa atual, peça, job | CAM; atual NC | CAM de máquina; atual NC | CAM de máquina; atual NC | fonte operacional e vínculo programa/job/OP |
| Início/fim de ciclo | NC | NC | NC | sinal/timestamp e definição da unidade de ciclo |
| Quantidade/contador | VF/NC | VF/NC | VF/NC | unidade, resets, replay e classificação de qualidade |
| Golpes/ciclos de dobra | não aplicável à dobra | VF/NC | VF/NC | golpes por peça, golpes de setup e semântica de contador |
| Material/espessura | CAM lido; medição NC | parâmetros CAM disponíveis, amostra produtiva NC | parâmetros CAM disponíveis, amostra produtiva NC | programa efetivamente em uso; não confundir cadastro com sensor |
| Tempo de processo | TT estático; realizado NC | NC | NC | duração efetiva de execução/espera/apoio |
| Parâmetros | arquivos CAM presentes | XML de cadastro lido | XML de cadastro lido | lista de parâmetros efetivos legíveis; não ler/escrever controle por suposição |
| Energia/gases | VF/NC | VF/NC energia | VF/NC energia | medidores/opção, unidade, frequência e interface externa |
| Alarme: código/mensagem/início/fim/histórico | NC | NC | NC | eventos reais e retenção; UI de alarme não prova histórico exportável |
| Modelo/controlador | CAM | CAM | CAM | serial e identidade física por endpoint |
| Serial, versão/firmware CNC | NC | NC | NC | plaqueta/tela/identity node real |

Nenhuma frequência operacional foi medida. Template diário de CommandLog não comprova frequência do VCBox ou latência da máquina. Não há tabela de NodeIds/DataItems reais porque nenhum desses protocolos foi encontrado em execução.

## Consequência prática

**[CERTO]** Já é possível uma leitura offline de contexto de programa/material do Laser pelo share. **[PROVÁVEL]** VPSS/vSDD pode enriquecer contexto das dobradeiras. **[HIPÓTESE]** Conversão disso em estado/quantidade/tempo real depende de outra fonte operacional, devidamente comprovada.

### Dados atuais lidos em 08/10/2026 — complemento

[CERTO] Três CSVs SigmaNEST atuais e cinco linhas OP/peça foram lidos: tarefa T3687, programas 9379–9381, material/espessura, chapa, repetições, tempos estimados e quantidades planejadas. [CERTO] Há um leitor pontual validado sem escrita MES. Dados, schema e origem técnica em [13-leitura-atual-sigmanest.md](13-leitura-atual-sigmanest.md). Não são CommandLog/VCBox nem telemetria CNC. Estado/ciclo/contador de produção/alarme/energia continuam não comprovados.
