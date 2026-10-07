# Demonstração contínua do Andon

## Finalidade

A DEMO mantém uma fábrica sintética em movimento usando os fatos canônicos do
MES. O Andon e a Gestão leem os mesmos serviços e o mesmo motor de OEE usados
normalmente; não existe cálculo de KPI no simulador nem no frontend.

O isolamento é obrigatório. Toda escrita vai para o banco dedicado
`gestor_pecas_test_andon_demo`. O processo valida `current_database()` antes de
escrever, aceita como fonte de cadastro somente um banco TESTE, abre essa fonte
como somente leitura e nunca copia fatos operacionais. O perfil HTTP DEMO
também bloqueia TOTVS, SOAP, outbox, SigmaNEST, Telegram, IA, relatórios
automáticos e Dev Observatory. O scheduler de turno fica desligado somente
nesse perfil, pois a própria DEMO publica a timeline completa em calendário
24x7; no modo normal ele continua ativo.

## Preparar e executar

Use dois terminais PowerShell. O `.env` não é alterado e nenhuma credencial é
impressa.

No primeiro terminal, crie/migre o banco dedicado, copie somente os cadastros
necessários, aqueça o histórico e mantenha a fábrica em execução:

```powershell
.\.venv\Scripts\python.exe scripts\run_andon_demo.py --prepare --seed 1234
```

No segundo terminal, depois de liberar a porta 8001, carregue o ambiente
isolado e inicie o backend oficial. Desde 07/10/2026 a porta 8001 é da API
REAL (configuração `gestor-real-8001`), usada pela TV do Andon em produção; a
DEMO só deve subir sob demanda e **a API REAL precisa ser parada antes**, para
a TV não passar a mostrar dados sintéticos. Ao terminar a demonstração, pare a
DEMO e o simulador e reinicie a API REAL:

```powershell
. .\scripts\andon_demo_env.ps1
.\.venv\Scripts\python.exe -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8001
```

A TV fica disponível em `http://10.10.1.248:8001/andon`. Encerre cada processo
com `Ctrl+C`. Para um diagnóstico finito do preparo, acrescente `--once` ao
comando do simulador.

Uma segunda instância escritora no mesmo banco é recusada por advisory lock.
Executar novamente com `--prepare` limpa toda a timeline física e os eventos de
quantidade desse banco exclusivamente sintético, inclusive estados `SYSTEM`
que possam ter sobrado de uma execução anterior. Apontamentos e catálogo são
removidos somente no namespace `DEMO-ANDON-*`. O cenário é então reconstruído
a partir da seed informada.

## Comportamento industrial

- Descoberta dinâmica pelo inventário canônico de postos apontáveis, com todos
  os setores compatíveis presentes, pelo menos oito identidades físicas
  simultâneas e alvo padrão de 16.
- Ciclos independentes de 20 a 95 minutos, incrementos de quantidade durante a
  produção e warm start limitado ao dia contábil corrente.
- Perfis `NORMAL`, `PICO`, `BAIXA` e `PERTURBACAO`, alternados organicamente. O
  último inclui paradas longas de 20 a 45 minutos.
- Produção, setup, parada e retomada passam pelo motor canônico de estado do
  recurso. Quantidade boa/refugo atualiza atomicamente o acumulado do
  apontamento e o evento canônico lido pelo FTT.
- O rollover diário fecha o segmento anterior exatamente à meia-noite antes de
  iniciar o novo segmento, evitando carregar o numerador de Performance do dia
  anterior para a janela nova.
- Metas são definidas antes do ciclo. Um ciclo só recebe `Finalizado` quando a
  quantidade boa atende a meta; caso contrário, fecha como parcial
  `Aguardando`. Refugo permanece separado e não completa a OP.

## Limitação explícita do Corte

O cadastro TESTE possui recursos de Corte, mas não fornece nestings SigmaNEST
sintéticos confiáveis. A DEMO registra atividade produtiva sem OP, paradas e
retomadas no recurso de Corte. Ela não inventa uma OP operacional para obter
Performance ou FTT. Esses indicadores permanecem indisponíveis quando o motor
não possui numerador real para Corte.

Na descoberta de 06/10/2026, o catálogo corporativo TESTE não possuía recursos
habilitados para `Montagem` nem `Solda Alumínio`. O inventário físico canônico,
porém, contém as estações de `Solda Alumínio` já aprovadas no registro dos
postos; por isso elas participam da DEMO. `Montagem` permanece sem recurso e é
publicada como lacuna no resumo inicial. Nenhuma máquina ou estação é inferida.

## Invariantes de segurança

- Banco REAL e banco TESTE operacional não recebem escrita.
- O simulador não faz chamadas HTTP nem instancia gateways externos.
- `Database` é criado com enqueue da outbox TOTVS explicitamente desabilitado,
  independentemente das variáveis herdadas no terminal.
- A origem e o prefixo DEMO são verificados antes de limpar ou incrementar
  qualquer fato.
- O catálogo de origem é acessado com `default_transaction_read_only=on`.
