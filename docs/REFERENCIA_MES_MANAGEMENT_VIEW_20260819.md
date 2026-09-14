# Referência técnica — PCFactory MES e Management View — 19/08/2026

## Finalidade

Este documento registra somente **evidências observadas** nas coletas técnicas do
PCFactory/MES e do Management View. Ele **não transforma comportamento legado em
regra do Gestor de Peças**.

A precedência funcional continua sendo:

1. regras validadas com a Manufatura;
2. regras canônicas do Gestor de Peças;
3. evidências do MES/Management View;
4. inferências técnicas.

Se o sistema atual divergir da Manufatura, a divergência deve ser documentada e a
regra da Manufatura permanece válida.

## Coletas analisadas

### PCFactory MES DEEP v4

Arquivo analisado: `PCFactory_MES_DEEP_v4_20260819_135431.zip`.

Resumo capturado pelo próprio coletor:

- 437 respostas;
- 109 corpos de resposta únicos;
- 65 endpoints;
- 123 caminhos JSON catalogados;
- 34 snapshots de página;
- 50 rotas descobertas;
- 88 códigos de tela observados;
- 14 candidatos de API encontrados em HTML/JavaScript;
- 121 GETs de leitura observados e repetidos pelo replay controlado;
- 30 rotas efetivamente visitadas;
- 0 falhas de navegação registradas.

Telas/rotas relevantes observadas incluem `D0023`, `D0024`, `D0028`, `D0714`,
`D0715`, `D1955`, `D2062` e as customizações `C1423`, `C1424`, `C1425`, `C1426`
e `C1779`.

### Management View AUTO v4

Arquivo analisado: `ManagementView_AUTO_v4_20260819_133055.zip`.

Resumo capturado pelo próprio coletor:

- 350 respostas de API;
- 45 corpos de resposta únicos;
- 33 endpoints;
- 9.239 caminhos JSON catalogados;
- 21 snapshots de página;
- 11 rotas visitadas;
- 20 interações de navegação seguras;
- 0 falhas de rota;
- nenhum WebSocket observado nessa coleta.

## Evidências úteis encontradas

### Recursos e estado atual

O Management View expõe recursos com campos como:

- código e nome;
- apelido;
- grupo gerencial;
- operador principal;
- código, nome e classe do status;
- cor visual;
- alarmes.

A coleta observou, entre outros, os pares legados:

- `0001` → `PRODUÇÃO`;
- `0078` → `SEM DEMANDA`;
- `0044` → `ATIVIDADE S/ OP`.

Esses códigos servem para mapeamento/integração. A semântica oficial do Gestor
continua definida por sua própria taxonomia e pelas regras da Manufatura.

### Turnos

O endpoint `ShiftTeam/V1` retornou cadastros com nomes como `Turno A`, `Turno B`
e `Turno C`. A coleta comprova a existência do conceito/cadastro de equipe de
turno no sistema atual, mas **não define os limites horários oficiais do Gestor**.

Para o Gestor permanecem válidos os limites já aprovados de interrupção automática
às **17:30** e **21:30**.

### Indicadores por recurso

`maps/v1/GetMapsTooltip` retornou, por recurso, campos como:

- `oee`;
- `performance`;
- `disponibility`;
- `quality`;
- OP/código de trabalho/produto quando disponíveis.

Foram observados inclusive valores acima de 100 em alguns recursos. Isso reforça
que os números legados devem ser tratados como **evidência**, não como regra a ser
copiada ou normalizada silenciosamente.

A relação de OEE já validada por amostra específica permanece:

```text
OEE = Disponibilidade × Performance × FTT
```

Mas a regra de FTT com refugo/retrabalho continua não fechada. O Gestor não deve
publicar um percentual inventado enquanto isso não estiver confirmado.

### Qualidade e inspeção

A coleta do Management View mostrou recursos com referências a inspeções e
checklists. A coleta do MES, em `D1955/PegarParamsTela`, mostrou preferências para
associação de especificação/inspeção a entidades como recurso, família de produto,
produto, OP, operação e lote.

[Inferência] A estrutura confirma que o modelo industrial precisa permitir
inspeções ligadas a diferentes níveis, mas não obriga o Gestor a reproduzir a
estrutura interna do PCFactory.

A regra funcional do Gestor continua sendo evoluir para checklist de conferência
de cotas e rastreabilidade da inspeção.

### Nesting/Corte

Foram observadas telas distintas para:

- início de nesting (`C1425`);
- report de nesting (`C1426`);
- interrupção de nesting (`C1779`).

Isso reforça a necessidade já definida no Gestor de manter cada nesting como
execução temporal própria, com tempo previsto, início, fim, tempo real, recurso,
material, espessura, operador, status e relacionamento com OPs quando disponível.

### Configuração das telas operacionais

O PCFactory expõe parâmetros como `GetParams`/`PegarParamsTela`, permissões e
preferências por tela. Eles são úteis para entender quais conceitos existem hoje,
mas flags internas como `GruCerto`, `MaqCerta`, `WOAskQty`, `VIniOpeAnt` e outras
não devem ser copiadas sem uma regra equivalente aprovada no Gestor.

## O que não precisa ser copiado

- códigos de tela `Dxxxx/Cxxxx/Jxxxx` como arquitetura do novo sistema;
- navegação e organização do PCFactory;
- códigos de status como domínio interno do Gestor;
- flags legadas sem significado funcional confirmado;
- cálculos que não possam ser explicados e reproduzidos por fatos canônicos;
- dashboards que apenas exibem percentuais sem explicar origem/perda;
- relatórios que recalculam a mesma fábrica com regras diferentes.

## Conclusão para a implementação

As duas coletas já fornecem evidência suficiente para avançar na fundação lógica.
Não há benefício proporcional em fazer outra varredura ampla do MES neste momento.

Se surgir uma lacuna concreta — por exemplo, um campo exato de calendário, uma
regra de qualidade ou um vínculo de nesting — deve ser criado um coletor **cirúrgico
para aquela pergunta**, em vez de repetir um crawler geral.

A próxima implementação deve priorizar:

- tempo físico sem duplicação em OPs simultâneas;
- rateio separado do tempo físico;
- árvore temporal explicável;
- qualidade/refugo/retrabalho separados;
- regras de turno da Manufatura;
- rastreabilidade até o fato de origem;
- contratos independentes do frontend, consumidos pela API Web.
