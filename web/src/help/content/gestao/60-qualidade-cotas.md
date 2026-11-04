---
titulo: Qualidade - Cotas padrão
grupo: Qualidade
ordem: 60
rotas: /qualidade/cotas
---

A tela **Qualidade — Cotas padrão** guarda, para cada produto, as medidas que a peça deve ter. Cada medida é uma **cota**. Quando o inspetor mede uma peça, o sistema compara com estas cotas.

Texto da tela: "Consulte e ajuste as cotas padrão de cada produto. Cada alteração gera uma nova revisão e vale para as próximas inspeções."

## Quem pode ver

Só os níveis **Qualidade** e **Admin**. A seção "Qualidade" nem aparece no menu para os outros. Se alguém abrir o endereço, vê "Acesso restrito à Qualidade". Gestor comum deve pedir à Qualidade qualquer ajuste nas cotas.

## Filtro

| Campo | Como funciona |
|---|---|
| Produto | Digite o código (ou parte dele). A lista atualiza sozinha, sem apertar botão. |
| Limpar filtros | Apaga o código digitado. |

Ao lado do filtro aparece quantos produtos com cotas existem.

## Lista "Produtos com cotas padrão"

| Coluna | O que significa |
|---|---|
| Produto | Código do produto. Clique para abrir as cotas. Aparece **Inativo** embaixo quando o produto está desativado. |
| Descrição | Nome do produto. "—" se não houver. |
| Revisão | Número da versão das cotas ("Rev. 3"). Sobe 1 a cada salvamento. |
| Cotas | Quantas cotas o produto tem. |
| Atualizado por | Quem salvou por último. |
| Atualizado em | Data e hora do último salvamento. |
| Ações | Botão **Editar**. |

Com mais de 100 produtos, aparecem os botões **Anterior** e **Próxima** e o texto "Mostrando 1–100 de N".

## Botão "Cadastrar produto" (canto superior)

1. Clique em **Cadastrar produto**.
2. Digite o **Código do produto** e clique em **Continuar**.
3. Preencha as cotas (veja abaixo) e clique em **Salvar cotas do produto**.

Se o produto já tinha cotas, a tela avisa "O produto X já tinha cotas cadastradas; você está editando". Nada é sobrescrito sem aviso.

## Editar as cotas

Cada cota tem:

| Campo | Regra |
|---|---|
| Descrição (opcional) | Texto livre, só para identificar a cota. |
| Padrão (mm) | A medida correta da peça. Ex.: 125,0. |
| Tolerância (± mm) | Quanto a medida pode variar para mais ou para menos. Ex.: 0,5. |
| Unidade | Sempre **mm**. Não dá para trocar. |

- Botão **+ Adicionar cota** cria a próxima cota (Cota 2, 3...).
- Botão **Remover** aparece quando há mais de uma cota.
- O botão **Salvar cotas do produto** fica desligado enquanto algum Padrão ou Tolerância estiver vazio. O motivo aparece embaixo: "Preencha o padrão e a tolerância de todas as cotas para salvar."
- Exemplo: Padrão 125,0 e Tolerância 0,5 significa que de 124,5 a 125,5 mm a peça é aceita.
- Uma medida sem tolerância guardada (ex.: só "453") vale tolerância zero.

### O que acontece ao salvar

O sistema cria uma **nova revisão**. O aviso na tela diz: "Revisão atual: N. Ao salvar, é criada a revisão N+1, usada nas próximas inspeções." Inspeções já feitas ficam com o padrão antigo. Por isso, no [SPC](topico:61-qualidade-spc), revisões diferentes de uma cota nunca se misturam.

Mensagem de sucesso: "Cotas padrão de X atualizadas: revisão N." ou "Cotas padrão de X cadastradas."

## Problemas comuns

| Mensagem | O que fazer |
|---|---|
| Seu perfil não tem acesso às cotas padrão. Só a Qualidade e a administração usam esta tela. | Entre com uma conta da Qualidade ou peça ao admin. |
| Informe o código do produto. | O código estava vazio. |
| Informe ao menos a Cota 1 com o padrão da peça. | Salvou sem nenhuma cota. |
| Informe o padrão e a tolerância de todas as cotas. | Há cota com campo vazio. |
| A numeração das cotas é inválida / Há cotas repetidas. Feche e abra o produto de novo. | Feche a janela e abra o produto outra vez. |
| As cotas deste produto só podem ser alteradas pela Qualidade ou pela administração. | Produto protegido; só esses dois níveis alteram. |
| Alguma informação está inválida. Confira o código do produto e os valores das cotas. | Revise o que foi digitado. |
| Não foi possível acessar o servidor. Tente novamente. | Falha de rede; tente de novo. |
| Não foi possível carregar as cotas / Não foi possível abrir as cotas | Clique em **Tentar novamente**. |
| Nenhum produto com cotas cadastradas | Lista vazia; use **Cadastrar produto**. |
| Nenhum produto neste filtro | Confira o código digitado. |

Veja também: [SPC](topico:61-qualidade-spc) e [Decisão de RNC](topico:62-qualidade-rnc).
