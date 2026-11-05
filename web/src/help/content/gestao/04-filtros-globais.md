---
titulo: Filtros que valem para várias telas
grupo: Primeiros passos
ordem: 4
rotas:
---

Muitas telas têm no topo uma **barra de filtros**. O que você escolhe fica guardado e vale também para as outras telas que usam a mesma barra. Se você filtrar o setor "Pintura" na Visão Geral e abrir Análises, o filtro continua lá.

Telas administrativas (Pausas, Crachás, Turnos e outras) não usam essa barra. Elas têm filtros próprios, explicados em cada tópico.

## Período

O período começa em **hoje**, pelo relógio do sistema. A consulta vai das 00:00:00 do dia **Início** até as 23:59:59 do dia **Fim**.

| Botão | Período |
|---|---|
| **Hoje** | Só o dia de hoje. |
| **Ontem e hoje** | Ontem e hoje. |
| **7 dias** | Últimos 7 dias. |
| **30 dias** | Últimos 30 dias. |
| **Este mês** | Do dia 1 até hoje. |
| **Início** e **Fim** | Escolha as datas à mão. |

Os atalhos (Hoje até Este mês) aplicam na hora, junto com o que já estiver digitado nos outros campos, e o botão do período ativo fica destacado. Já as datas **Início** e **Fim** escolhidas à mão só valem depois de **Aplicar**. Telas que mostram a **situação de agora** exibem "Situação do dia corrente" no lugar do período.

## Setor

A lista **Setor** traz "Todos os setores" e: Corte, Dobra, Usinagem, Serra, Caldeiraria, Pintura, Solda Aço, Solda Alumínio, Solda Robô, Proj. Ferramentaria, Protótipo, Montagem, Destaque, Almoxarifado.

A escolha de setor só vale depois de **Aplicar**. Se a sua conta é presa a um setor, aparece "Setor: X" fixo, sem lista. Se for presa a vários, a lista traz só esses setores e não tem "Todos os setores". Veja [Perfis](topico:02-perfis-e-acessos).

## Mais filtros

O botão **Mais filtros** (vira **Menos filtros**) abre campos de texto. Um número ao lado mostra quantos estão preenchidos. Se algum já estiver preenchido (por exemplo, vindo de um clique na Visão Geral), a área abre sozinha junto com a tela. Os campos aparecem com "Todos" ou "Todas" como dica.

| Campo | O que filtrar |
|---|---|
| **Recurso** | A máquina ou posto. |
| **OP** | O número da ordem de produção. |
| **Operação** | A operação do roteiro. |
| **Produto** | O produto. |
| **Operador** | A pessoa que apontou. |

## Aplicar e Limpar

| Botão | O que faz |
|---|---|
| **Aplicar** | Passa a valer o que você mexeu: datas, setor e campos de texto. Enquanto você não clica, a tela continua com o filtro anterior. |
| **Limpar** | Volta tudo ao padrão: hoje, todos os setores (ou o seu setor, se a conta for presa a um) e sem filtros de texto. Também fecha a área de **Mais filtros**. |

Nem toda tela usa todos os campos. Cada tela mostra só os que fazem sentido para ela.

## Passos

1. Escolha o período (atalho ou datas).
2. Escolha o setor.
3. Se precisar, clique em **Mais filtros** e preencha recurso, OP, operação, produto ou operador.
4. Clique em **Aplicar**.

## Problemas comuns

| O que aparece | O que significa | O que fazer |
|---|---|---|
| "Carregando referência do sistema…" | O sistema ainda busca a data de hoje (a tela só abre depois disso). | Aguarde alguns segundos. |
| Números "zerados" ou diferentes do esperado | Algum filtro de outra tela ficou valendo. | Clique em **Limpar**. |
| O filtro de setor não deixa escolher "Todos" | Sua conta é presa a setores. | É esperado. |
