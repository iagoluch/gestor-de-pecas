# MTConnect: suporte público e investigação local

**[CERTO, produto]** Interface MTConnect é declarada para o VCBox por AMADA/Fujitsu. Não foi identificado Agent instalado, base URL ou porta. Não houve requisição `/probe`, `/current`, `/sample` ou `/assets` a dispositivo industrial nesta sessão.

| Objeto pedido | Resultado real |
|---|---|
| Devices e Components | Não coletados |
| DataItems: ids, types, units | Não coletados |
| Execution / ControllerMode | Não coletados |
| Program / PartCount / golpes | Não coletados |
| Conditions / alarmes / Availability | Não coletados |
| Timestamps / instanceId / sequence / buffer | Não coletados |
| Resposta MTConnect original | Nenhuma; arquivos DNK/XML não são resposta MTConnect |

Não assumir MTConnect em 5000, 5001, 80 ou qualquer porta específica. HTTP acessível não prova MTConnect. Tampouco o Agent, se existir, necessariamente roda no AMNC.

## Requisições que seriam úteis após comprovar URL

**[HIPÓTESE, próximo teste]** Os exemplos abaixo são templates, não comandos executados nem URLs descobertas:

```text
GET <base-url-real>/probe
GET <base-url-real>/current
GET <base-url-real>/sample?count=10
```

Uma requisição por vez, timeout curto, limite de tamanho e sem retries automáticos. Registrar status HTTP, content-type e corpo original. A URL/base path real deve vir de config/manual; verificar semântica do Agent/versão antes de acrescentar parâmetros.

Primeiro `/probe`: ele determina os DataItems existentes e suas unidades. Depois `/current`, e somente então `/sample` limitado para observar sequência/transições. Não usar streaming/subscriptions contínuos na descoberta inicial. Não executar exemplos sobre endereço/porta adivinhados.

DataItems do padrão não são tags AMADA comprovadas. `Execution=ACTIVE`, `ControllerMode`, `Program`, `PartCount`, condições e energia só entram na tabela de integração depois de aparecerem na resposta real. Perda de conexão/`UNAVAILABLE` não comprova desligamento físico. Contador não prova peça boa ou conclusão de OP.

Fontes primárias: [especificação MTConnect](https://docs.mtconnect.org/MBSD_MTConnect_Part_1_2-0-0.pdf) e [modelo Execution](https://model.mtconnect.org/Version2.4/ObservationInformationModel/ObservationTypes/EventTypes/Execution/), registradas em 01. Versão efetiva do eventual Agent local permanece desconhecida.
