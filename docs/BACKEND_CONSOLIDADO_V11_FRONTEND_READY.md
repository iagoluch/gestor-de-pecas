# Backend consolidado v11 — pronto para evolução do frontend

> Registro histórico anterior à promoção Web-only de 24/08/2026. A antiga
> pendência de aprovação de OEE/FTT foi superada em 25/08/2026.

## Estado

Esta versão fecha tudo o que pode ser implementado no backend sem inventar decisões que ainda dependem da Engenharia de Manufatura ou da TI.

O backend está preparado para que PySide6 e a futura Web consumam a mesma regra industrial. A interface não deve consultar tabelas diretamente nem recalcular indicadores.

## Precedência funcional

1. regra validada com a Engenharia de Manufatura;
2. regra canônica do Gestor de Peças;
3. evidência do PCFactory/MES/Management View;
4. inferência técnica.

O MES legado é fonte de evidência, não especificação do novo sistema.

## Fontes canônicas

| Assunto | Fonte canônica |
|---|---|
| Estado físico do recurso | `eventos_estado_recurso` |
| Quantidade boa/refugo/retrabalho | `eventos_quantidade_producao` |
| Execução da OP | `apontamentos_operacionais` + `eventos_apontamento_operador` |
| Tempo físico e rateio | `sessoes_recurso` + `rateios_tempo_op` |
| Calendário | `calendarios_produtivos` + `turnos_produtivos` + intervalos + exceções |
| Corte/Nesting | `apontamentos_corte` |
| Operadores | participação do apontamento/evento + `participacoes_operador` |

Fallback histórico continua permitido apenas quando a fonte canônica ainda não existe para o período e deve ser identificado como fallback.

## Entregas da v11

### Estado físico do recurso

- transição física única por recurso;
- lock transacional por recurso;
- estado aberto único;
- simultaneidade de OPs no mesmo estado não fragmenta a máquina;
- estados simultâneos incompatíveis viram `desconhecido`;
- estados físicos são sincronizados nas transições de apontamento;
- Corte/Nesting também atualiza o estado físico;
- fim de turno registra `fora_turno` programado/automático;
- eventos retroativos não reescrevem silenciosamente uma timeline posterior.

### Fim de turno

Mantidos os limites oficiais de 17:30 e 21:30:

- interrupção programada automática;
- quantidade zero;
- OP permanece aberta;
- retomada manual;
- idempotência;
- auditoria detecta OP que atravessou o limite sem a interrupção esperada.

### Quantidade

`Quantidade Produzida` permanece igual a peças boas. Refugo e retrabalho permanecem separados e não concluem a OP.

### Rateio

- tempo físico e tempo atribuído permanecem separados;
- sessão física do recurso não pode se sobrepor a outra sessão do mesmo recurso;
- soma dos tempos atribuídos deve conservar o tempo físico;
- Tempo Padrão × Real prefere o tempo rateado quando disponível.

### Calendário

A v11 adiciona:

- intervalos exatos de turno;
- exceções de calendário;
- suporte a turno que cruza meia-noite;
- recorte por período;
- nenhuma posição de intervalo é inventada.

Quando existe apenas `minutos_intervalo` agregado:

- turno completo pode conhecer o total disponível;
- a timeline continua parcial porque a posição do intervalo é desconhecida;
- em recorte parcial, o total do recorte também permanece desconhecido.

### Auditoria

O backend pode detectar, entre outros:

- OP ativa sem operador;
- OP ativa sem recurso;
- produção física sem OP sobreposta;
- estado físico desconhecido;
- estados físicos incompatíveis;
- fim de turno sem interrupção programada;
- rateio que não conserva tempo físico;
- tempo disponível de calendário sem estado físico registrado, somente quando o calendário permite essa conclusão com exatidão.

Não existe percentual de confiabilidade inventado.

### Analytics

- Management View prefere o estado físico canônico;
- Tempo MES prefere o estado físico canônico;
- Pareto de parada/setup não multiplica ocorrência por OPs simultâneas;
- ausência de uma categoria na fonte física canônica significa zero dessa categoria; não cai para timeline de OP e reintroduz dado conflitante;
- lead time sem eventos não vira Produção;
- Cronoanálise e Tempo Padrão × Real preservam a fonte do tempo.

### Rastreabilidade

A OP pode reunir:

- execução;
- eventos;
- estado físico do recurso;
- sessões/rateios;
- participação de operadores;
- Nesting/Corte relacionado;
- referências de origem.

### Preparação do frontend

`FrontendBackendFacade` é a fronteira atual de casos de uso para UI/Web:

- `capabilities()`;
- `inicio()`;
- `consulta_operacional()`;
- `producao()`;
- `analises()`;
- `auditoria()`;
- `rastreabilidade()`.

`capabilities()` expõe regras canônicas, fontes, versão de schema e decisões ainda pendentes para impedir que o frontend crie sua própria regra.

## O que permanece propositalmente pendente

### OEE / FTT

Não publicar fórmula final de FTT com refugo/retrabalho até a Manufatura confirmar a regra oficial. O frontend não deve calcular por conta própria.

### Integração corporativa

A TI ainda precisa definir como o Gestor acessará o ambiente corporativo/Protheus: banco, views, procedures, API ou outra interface. O domínio e os serviços já estão desacoplados para permitir a troca do repositório.

### Estratégia de rateio por cenário

O motor suporta estratégias, mas qual estratégia deve ser aplicada em cada cenário produtivo continua sendo decisão funcional oficial, não escolha automática do software.

### Dados reais de calendário

A estrutura está pronta. Turnos, intervalos, feriados e exceções precisam ser alimentados pela fonte oficial.

## Regra para o frontend

A partir desta versão, o frontend deve ser tratado como apresentação e interação. Regras industriais, agregações e indicadores pertencem ao backend.
