---
titulo: Análises - Qualidade
grupo: Análises
ordem: 73
rotas: /analises/qualidade
---

A tela **Análises — Qualidade** mostra quantas peças saíram boas, quantas foram refugo e quantas precisaram de retrabalho. Texto da tela: "Peças boas, refugo e retrabalho em fontes separadas, com FTT explícito."

Usa a barra de filtros do topo. Veja [Filtros globais](topico:04-filtros-globais). Para decidir o destino de uma RNC, veja [Decisão de RNC](topico:62-qualidade-rnc).

## Cartões

| Cartão | Significado |
|---|---|
| Produção boa | Peças boas lançadas. |
| Refugo | Peças descartadas. |
| Retrabalho | Peças que voltaram para ser refeitas. |
| FTT | Peças boas de primeira: boas ÷ (boas + refugo + retrabalho). Peça retrabalhada fica fora das boas de primeira. |

Exemplo: 90 boas, 6 refugo, 4 retrabalho. FTT = 90 ÷ 100 = 90%. Se o FTT não puder ser calculado, o cartão mostra o estado (por exemplo, sem registros) e o motivo embaixo.

Os valores maiores que zero são clicáveis e abrem a conta aberta.

## Listas e tabelas

| Bloco | Conteúdo |
|---|---|
| Refugo por motivo | Barras, em peças. |
| Retrabalho por motivo | Barras, em peças. |
| Qualidade por setor | Setor, Boas, Refugo, Retrabalho. Valores clicáveis (exceto setor "Não informado"). |
| Qualidade por produto | Produto, Boas, Refugo, Retrabalho. A tabela pode ser ordenada pelas colunas. Os números daqui não abrem a conta aberta. |

## Primeira peça — Setup e checklist do posto

Histórico lido do posto: a gestão só consulta. Esta parte e a das autorizações **não usam os filtros do topo**: mostram o histórico registrado, sem recorte de período.

| Coluna | Significado |
|---|---|
| Inspecionada em | Quando a primeira peça foi inspecionada. |
| OP / Operação / Setor / Produto | Identificação do serviço. |
| Setup | Data do registro; "Pendente" se obrigatório e não feito; "Não se aplica". |
| Resultado | Resultado da inspeção. "Bloqueada" quando há bloqueio ativo. |
| Inspecionou | Quem inspecionou. |
| Cotas medidas | Observação registrada na inspeção (as cotas medidas). "—" se não houver. |

Vazio: "Nenhuma primeira peça registrada".

## Autorizações por crachá — retrabalho e refugo

Registros de retrabalho e refugo que exigiram autorização: Data, OP, Ocorrência, Decisão, Crachá, Responsável e **Motivo da recusa** (quando recusada). Vazio: "Nenhuma autorização registrada".

## Problemas comuns

| Situação | O que fazer |
|---|---|
| Lista "vazia" em motivo | Sem refugo ou retrabalho no período. |
| Motivo "Não informado" | O operador lançou sem motivo. |
| FTT sem número | Sem peças no período; aumente o período. |

Veja também: [Análises — OEE](topico:70-analises-oee).
