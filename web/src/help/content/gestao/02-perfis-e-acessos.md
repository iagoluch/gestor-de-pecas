---
titulo: Perfis e o que cada um vê
grupo: Primeiros passos
ordem: 2
rotas:
---

Cada conta tem um **nível** (perfil). O nível decide quais seções aparecem no menu e quais telas abrem. Quem escolhe o nível de cada pessoa é a administração, na tela [Cadastro](topico:20-cadastro).

> O menu já esconde o que você não pode ver. Se uma tela não aparece, seu nível não tem acesso. A proteção de verdade fica no servidor, não só no menu.

## Quem entra na gestão

Entram no sistema da gestão estes níveis: **admin, líder, supervisor, manufatura, qualidade, gestor e diretoria**. O nível **Andon** entra só no painel Andon.

Outros níveis, como os operadores por estação e o almoxarifado, usam a tela do posto (veja o [Manual do Operador](/ajuda/operador)).

## O que cada seção do menu exige

| Seção | Quem vê |
|---|---|
| Tela inicial, Painéis Operacionais, Consulta Operacional, Produção, Análises, Auditoria, Relatórios, Rastreabilidade | Todos os níveis da gestão |
| Manufatura | admin e manufatura |
| Qualidade | admin e qualidade |
| Diretoria | admin e diretoria |
| Melhoria Contínua | admin e contas com o nível "melhoria contínua" |
| IagoDev (Crachás, Cadastro, Chamadas do IagoDev, Turnos, Alterações, Sistema) | só admin |
| Uma seção por área (Dobra e Corte, Usinagem, Serra, Solda, Pintura, Protótipo, Projetos/Ferramentaria) | contas com a área liberada |

Dentro de cada seção, algumas abas também são restritas. O menu mostra só as abas que o seu nível pode abrir.

## Áreas: líder e supervisor por setor

Alguns níveis de líder e supervisor são presos a áreas da fábrica. Esses perfis enxergam **só os dados do próprio setor** e têm uma seção própria no menu para cada área.

| Nível | Áreas liberadas |
|---|---|
| Supervisor de caldeiraria | Dobra e Corte, Usinagem, Serra |
| Supervisor de almoxarifado, solda e pintura | Solda, Pintura |
| Supervisor de protótipo | Protótipo |
| Líder de dobra e corte | Dobra e Corte |
| Líder de usinagem | Usinagem |
| Líder de serra | Serra |
| Líder de pintura (e de pintura e almoxarifado) | Pintura |
| Líder de projetos e ferramentaria | Projetos/Ferramentaria |
| Líder de solda | Solda |
| Líder de almoxarifado | nenhuma área própria |

**Admin** e **gerente industrial** veem todas as áreas. Por isso eles não têm seções por área no menu. Para ver um setor, eles usam o filtro **Setor** (veja [Filtros](topico:04-filtros-globais)) ou a aba Recursos de Consulta Operacional.

Quando a conta é presa a um setor, o filtro mostra "Setor: X" fixo, sem a opção "Todos os setores".

## Níveis personalizados

A administração pode criar níveis novos copiando as permissões de um nível existente. Dois exemplos citados no sistema:

- **PCP**: copia as permissões de líder. Pode ajustar o roteiro da OP junto com admin e manufatura.
- **Manutenção**: copia as permissões de líder, mas a conta só enxerga a tela de manutenção.

## Quem pode o quê (resumo de ações)

| Ação | Quem |
|---|---|
| Gerenciar usuários e níveis | só admin |
| Ajustar o tempo padrão | admin e manufatura (hoje a seção Manufatura não tem telas; o tempo padrão é ajustado direto no Protheus) |
| Cotas padrão da Qualidade | admin e qualidade |
| Roteiro da OP | admin, manufatura e PCP |
| Criar fila manual | líder e supervisor nas áreas deles; admin em todas |

## Problemas comuns

| O que aparece | O que significa | O que fazer |
|---|---|---|
| "Acesso restrito ao administrador" | A tela é só da conta de administração. | Peça a um administrador, se precisar de alguma alteração ali. |
| Uma seção que o colega vê não aparece no seu menu | Seu nível não tem acesso a ela. | Confirmar com a liderança se o seu nível deveria ter. |
| Os dados parecem menores que os do colega | Sua conta está presa a um setor. | É esperado. Só admin e gerente industrial veem todos os setores. |
