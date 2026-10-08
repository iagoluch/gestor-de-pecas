# Evidências de leitura atual — 08/10/2026

Fonte: share `\\192.168.0.218\Arquivos`, PC GTS01-PRO06 e DNS/AD 192.168.0.201. Somente leitura com identidade existente. Relatório e campos em `../../13-leitura-atual-sigmanest.md`.

- `sigmanest-9379/9380/9381.CSV`: cópias do eReport, com valor de Programador substituído por [OMITTED]. Preservam pares chave/valor e o campo vazio Descricao. SHA dos originais está no JSON do leitor; o manifesto calcula SHA das cópias sanitizadas.
- `poc-leitura-planejamento.ps1`: leitura pontual de três CSVs, sem CNC, banco ou API MES. Não executa software AMADA nem gera exportações. `poc-planejamento-resultado.json` é a execução diretamente no share, três amostras/cinco linhas.
- `sigmanest-9381.DNK.txt`: programa lido como texto, nunca executado; nome do programador omitido. `program-9381-export-hash-match.json` compara SHA originais das duas cópias remotas.
- `sigmanest-Amada_ensis.pst/pas.txt`: pós-processador lido como texto, nunca executado. Configuração de caminhos e geração de campos documentadas no relatório. Conversão de encoding pode substituir caracteres de comentários italianos; não usar as cópias para programar máquinas.
- `sigmanest-T3687.SCH.txt`: schedule gerado pelo planejamento, não resposta CNC. Complete_code=2 e contadores zero são constantes de geração, comprovadas no PAS.
- Demais arquivos: resultados e falhas de consultas de metadados. Falha de acesso/conexão não prova ausência de serviço, box ou CNC. O erro WSMan contém uma sugestão de configuração do Windows; ela não foi executada.

Nenhuma credencial foi extraída ou incluída. `LaserAmada-unc-paths.json` preserva somente caminhos conhecidos; o BAT não foi executado. A consulta DNS é filtrada, não transferência de zona ou levantamento completo da rede.
