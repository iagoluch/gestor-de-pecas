# Regras Canônicas da Manufatura — Gestor de Peças

## Precedência

Estas regras foram definidas para o Gestor de Peças e têm precedência sobre qualquer
comportamento observado no PCFactory/MES/Management View. As coletas do sistema atual
servem como evidência de dados, cadastros e conceitos existentes; não são uma
especificação funcional do Gestor.

Em caso de divergência:

1. preservar a regra validada com a Manufatura;
2. registrar a divergência do MES atual;
3. não alterar silenciosamente a regra do Gestor para imitar o sistema legado.

## Quantidades

- `Quantidade Produzida` significa **somente peças boas**.
- Refugo é registrado separadamente e nunca vira peça boa.
- Retrabalho é registrado separadamente.
- Histórico e dashboards não podem somar refugo à produção realizada.

### Teto do planejado (decisão de 2026-09-08, Wave 4)

- A quantidade planejada da operação é **teto** de `peças boas + refugo`.
- `boas + refugo` **nunca** excede o planejado. A tentativa é recusada no
  serviço, na persistência e pela `CHECK ck_apontamentos_quantidade_atendida_planejada`.
- Saldo restante é `planejado - (boas + refugo)`.
- Uma OP/operação atinge a meta quantitativa quando `boas + refugo >= planejado`:
  a chapa refugada consumiu material planejado e não volta à fila.
- Retrabalho **não** participa dessa soma: ele continua pendente e é o que
  mantém a operação aberta para reapresentação.
- Enquanto houver saldo, a finalização é **parcial**: as quantidades ficam
  acumuladas e a operação **volta para a fila** do posto, exigindo um novo
  `Início` antes do fechamento. A operação segue sendo uma só.

Esta regra substitui a formulação anterior ("refugo não reduz o saldo de peças
boas planejadas"), que permitia `boas + refugo > planejado`. A fonte única da
regra é `mes/domain/manufacturing_rules.py`.

## Classificação temporal

São produtivos para a classificação aprovada do projeto:

- Produção;
- Setup;
- Atividade sem OP.

Não são produtivos:

- Parada;
- Retrabalho;
- Fila;
- Fora de turno;
- Estado desconhecido.

Setup deve ser exibido separadamente e não deve reduzir Disponibilidade ou Performance.
Parada manual é não programada. Interrupção automática é programada.

## Fim de turno

Limites oficiais atualmente definidos:

- **17:30**;
- **21:30**.

Quando um apontamento iniciado atravessa um desses limites:

1. registrar uma interrupção automática exatamente no horário do limite;
2. classificar a interrupção como programada;
3. não lançar quantidade boa, refugo ou produção;
4. não finalizar a OP;
5. manter a OP aberta;
6. exigir retomada manual no turno seguinte;
7. classificar o intervalo posterior como `fora_turno`, evitando que a noite seja
   contabilizada como parada;
8. garantir idempotência para que o mesmo limite não seja registrado duas vezes.

Se o sistema estiver fechado no instante do limite, a rotina pode recuperar o evento
posteriormente, persistindo o horário oficial do corte em vez do horário de abertura da
aplicação.

## Fonte dos indicadores

- Peças boas, refugo e retrabalho permanecem fatos distintos.
- Tempo físico de recurso e tempo atribuído a OPs em rateio permanecem distintos.
- OEE e componentes só podem ser publicados quando a regra e os dados necessários
  estiverem fechados; não inferir percentual para preencher dashboard.
- PCFactory/Management View podem ajudar a identificar campos e dados disponíveis, mas
  não podem mudar estas regras.

## Consolidação física e simultaneidade

- Timelines de OP são fatos atribuídos; não podem ser somadas diretamente para formar horas de máquina.
- No mesmo recurso e instante, duas ou mais OPs em Produção representam **um único intervalo físico** do recurso.
- O backend deve manter separadamente:
  - tempo físico consolidado do recurso;
  - tempo atribuído a cada OP/operação pelo rateio.
- Sobreposição de timelines do mesmo recurso com estados físicos diferentes é inconsistência de dados.
  O intervalo deve ser sinalizado como conflitante/desconhecido; o sistema não escolhe silenciosamente qual estado "vence".
- Pareto de paradas/setup também deve usar tempo físico consolidado para não multiplicar a mesma ocorrência por OPs simultâneas.
