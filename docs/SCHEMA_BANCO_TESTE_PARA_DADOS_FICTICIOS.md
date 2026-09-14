# Schema atual do PostgreSQL de teste para geração de dados fictícios

## Identificação do snapshot

- Data da leitura: `2026-08-18`.
- Banco consultado: `gestor_pecas_test`.
- PostgreSQL: `17.10`.
- Schema: `public`.
- Versão de migration: `7`.
- Fonte: leitura direta de `information_schema` e `pg_catalog` da base isolada.
- Este documento não contém endereço de conexão, usuário, senha ou hash de senha.

> [!IMPORTANT]
> Todo SQL gerado a partir deste documento deve ser executado exclusivamente
> contra `TEST_DATABASE_URL`. Não usar `DATABASE_URL`, não acessar o banco
> operacional e não habilitar o Qlik para produzir a carga.

## O que a outra IA deve preencher

Para criar OPs novas que possam ser digitadas e apontadas na tela do operador,
as tabelas mínimas são:

1. `catalogo_pcp_ops`: cabeçalho e quantidade prevista da OP;
2. `catalogo_operacoes_op`: roteiro ordenado da OP;
3. `tarefas`: somente quando a OP também precisar participar do fluxo de
   Corte/Destaque;
4. `op_por_tarefa`: liga a tarefa às suas OPs, somente quando houver tarefa.

As tabelas abaixo já possuem os catálogos necessários e normalmente devem ser
reutilizadas, não recriadas:

- `catalogo_recursos_pcfactory`;
- `catalogo_status_recursos`;
- `operadores_apontamento`.

As tabelas operacionais abaixo devem começar vazias para cada cenário novo. O
sistema as preenche ao clicar em Início, Parada, Setup, Retrabalho ou
Finalizado:

- `apontamentos_operacionais`;
- `eventos_apontamento_operador`;
- `operadores_evento_apontamento`;
- `historico`;
- `eventos_sistema`.

Não alterar por uma carga de OPs fictícias:

- `usuarios`;
- `schema_migrations`.

## Relações principais

```text
catalogo_pcp_ops (1)
    └── (N) catalogo_operacoes_op

tarefas (1)
    ├── (N) op_por_tarefa
    ├── (N) apontamentos_operacionais
    ├── (N) historico
    └── (N) eventos_destaque_tarefa

catalogo_operacoes_op (1)
    └── (N) apontamentos_operacionais

apontamentos_operacionais (1)
    └── (N) eventos_apontamento_operador
              └── (N:N) operadores_apontamento

catalogo_sigmanest_tarefas (1)
    ├── (N) catalogo_sigmanest_ops
    ├── (N) catalogo_sigmanest_programas
    └── (N) catalogo_sigmanest_planos_corte
              └── (0..1) apontamentos_corte
```

## Regras funcionais obrigatórias para a carga

1. Uma OP apontável precisa existir simultaneamente em `catalogo_pcp_ops` e
   possuir ao menos uma linha ativa em `catalogo_operacoes_op`.
2. `catalogo_operacoes_op.codigo_op` deve existir primeiro em
   `catalogo_pcp_ops.codigo_op`.
3. A quantidade exibida na tela vem de `catalogo_pcp_ops.quantidade`.
4. O roteiro é ordenado por `catalogo_operacoes_op.ordem` e depois por `id`.
5. `ordem` deve ser crescente dentro da OP. `numero_operacao` é o número
   industrial exibido e pode ser `10`, `20`, `30` etc.
6. A combinação `(codigo_op, numero_operacao, codigo_recurso)` deve ser única.
7. Não inserir uma operação chamada Destaque no roteiro. Destaque é uma fase
   da tarefa e começa com datas/eventos nulos.
8. Uma tarefa nova de Corte/Destaque deve entrar em `tarefas` com `status`
   `NULL`, além das três datas nulas. O texto `Aguardando` é derivado pela
   aplicação; gravá-lo em `tarefas.status` bloqueia o botão Início do Destaque.
9. `Aguardando` é apenas estado interno de fila em
   `apontamentos_operacionais.status`. Não usar nomes como `Aguardando Dobra`
   ou `Aguardando Usinagem` em `setor_destino_original` ou
   `setor_destino_atual`.
10. Para tarefa de Corte, o destino deve ser o nome público da primeira máquina
   ou setor posterior ao Corte. Se não houver operação posterior, usar
   `Almoxarifado`.
11. Não inserir manualmente eventos de produção para uma OP ainda não testada.
    O clique em Início cria o apontamento, o evento `fila` e o evento
    `producao` dentro da lógica transacional do sistema.
12. Não fornecer valores de `id` para colunas `IDENTITY`; deixar o PostgreSQL
    gerá-los.
13. Usar transação, colunas explícitas e `ON CONFLICT` somente nas chaves
    naturais documentadas. Não usar `TRUNCATE`, `DELETE`, `DROP` ou reset de
    sequences.

## Setores e recursos do roteiro

### Dobra

| Código do roteiro | Nome público da máquina |
|---|---|
| `DOBRA1` | `Gasparini` |
| `DOBRA2` | `2204` |
| `DOBRA3` | `1303` |

### Usinagem

| Código do roteiro | Nome público da máquina |
|---|---|
| `CNC-01` | `Romi D 1000` |
| `CNC-02` | `Eurostec` |
| `FRESA1` | `Fresadora FTV31` |
| `TCNC-1` | `Romi GL 350M` |
| `TORNOC` | `Torno Mecânico` |

### Corte

- Códigos atualmente usados na base fictícia: `LASER` e `PLASMA`.
- Máquinas públicas da tela: `Laser Ensis 3015` e `Plasma TerraBlade 4`.
- Em `catalogo_sigmanest_planos_corte.maquina_qlik`, usar obrigatoriamente os
  identificadores técnicos `AMADA_ENSIS` para o Laser e `MESSER_XPR_300` para
  o Plasma. Os nomes públicos pertencem à interface; gravá-los nessa coluna
  faz o filtro da fila retornar vazio.

### Serra

- Códigos observados nos roteiros atuais: `SERRA4` e `SERRA6`.
- A tela possui `SFG-330`, `S4220` e `SFHA-10`.
- Não inventar uma correspondência nova entre `SERRA4`/`SERRA6` e as máquinas.
  O posto selecionado pelo operador é usado na etapa atual.

### Pintura e Solda

- Pintura usa atualmente `PINT.L` no roteiro e é mostrada como `Pintura`.
- Solda usa atualmente `SOLDA4` no roteiro e é mostrada como `Solda`.
- Não subdividir Pintura ou Solda até que as etapas sejam esclarecidas.

## Inventário atual das tabelas

As quantidades são apenas o snapshot da leitura e mudam conforme os testes.

| Tabela | Linhas | Papel |
|---|---:|---|
| `apontamentos_corte` | 0 | Execuções do Corte |
| `apontamentos_operacionais` | 13 | Execução/fila atual por OP, operação e posto |
| `catalogo_operacoes_op` | 44 | Roteiros das OPs |
| `catalogo_pcp_ops` | 13 | Cabeçalho das OPs |
| `catalogo_recursos_pcfactory` | 372 | Recursos/máquinas importados |
| `catalogo_sigmanest_ops` | 3 | OPs vinculadas às tarefas SigmaNest |
| `catalogo_sigmanest_planos_corte` | 3 | Planos de Corte |
| `catalogo_sigmanest_programas` | 3 | Programas por tarefa de Corte |
| `catalogo_sigmanest_tarefas` | 1 | Catálogo de tarefas SigmaNest |
| `catalogo_status_recursos` | 84 | Motivos de parada e estados especiais |
| `eventos_apontamento_operador` | 28 | Histórico de estados do apontamento |
| `eventos_destaque_tarefa` | 0 | Eventos do Destaque |
| `eventos_sistema` | 28 | Diagnóstico técnico |
| `historico` | 15 | Histórico produtivo legado/projeção |
| `op_por_tarefa` | 13 | Relação tarefa × OP |
| `operadores_apontamento` | 1 | Crachás usados na finalização |
| `operadores_evento_apontamento` | 0 | Participantes N:N de eventos |
| `schema_migrations` | 7 | Controle das migrations |
| `tarefas` | 11 | Tarefas produtivas |
| `usuarios` | 8 | Login e permissões |

## Schema detalhado

Convenções:

- `IDENTITY` significa que o banco gera o ID;
- `timestamp` significa `timestamp without time zone`;
- campos sem `NULL` explícito são `NOT NULL`;
- os defaults abaixo são os defaults reais do banco.

### `catalogo_pcp_ops`

```text
codigo_op          text PRIMARY KEY
produto_codigo     text
produto_descricao  text
quantidade         integer CHECK (quantidade > 0)
unidade            text NULL
data_emissao       date
status_pcp         text NULL
filial             text NULL
local_estoque      text NULL
roteiro            text NULL
recurso            text NULL
ativo              boolean DEFAULT true
sincronizado_em    timestamp
```

### `catalogo_operacoes_op`

```text
id                    bigint IDENTITY PRIMARY KEY
codigo_op             text REFERENCES catalogo_pcp_ops(codigo_op) ON DELETE CASCADE
produto_codigo        text
produto_descricao     text
numero_operacao       text
codigo_recurso        text
descricao_operacao    text
tipo_setor            text
filial                text NULL
tipo                  text NULL
roteiro               text NULL
tempo_medio_segundos  numeric NULL
ordem                 integer
fonte                 text DEFAULT 'planilha_teste'
ativo                 boolean DEFAULT true
sincronizado_em       timestamp

UNIQUE (codigo_op, numero_operacao, codigo_recurso)
```

### `tarefas`

```text
id                       bigint IDENTITY PRIMARY KEY
codigo_tarefa            text UNIQUE
material                 text NULL
espessura                numeric NULL
status                   text NULL
data_inicio_destaque     timestamp NULL
data_finalizacao         timestamp NULL
data_despacho            timestamp NULL
observacoes              text NULL
```

Para uma tarefa ainda não apontada, manter as três datas nulas. O estado de
Destaque é derivado dos eventos e dessas datas, não de uma operação fictícia no
roteiro. Manter também `status = NULL`; não inserir `Aguardando` nessa coluna.

### `op_por_tarefa`

```text
id                       bigint IDENTITY PRIMARY KEY
tarefa_id                bigint REFERENCES tarefas(id) ON DELETE CASCADE
codigo_op                text
id_peca                  text NULL
setor_destino_original  text
setor_destino_atual     text NULL
quantidade_original     integer
quantidade_atual        integer NULL
editado                  boolean DEFAULT false

UNIQUE (tarefa_id, codigo_op)
```

Apesar de não haver FK física de `codigo_op` para `catalogo_pcp_ops`, a carga
fictícia deve manter essa referência lógica.

### `catalogo_recursos_pcfactory`

```text
codigo            text PRIMARY KEY
nome              text
tipo_setor        text NULL
habilitado        boolean DEFAULT true
fonte             text DEFAULT 'PC Factory D0021'
sincronizado_em   timestamp
```

### `catalogo_status_recursos`

```text
codigo               text PRIMARY KEY
nome                 text
grupo_id             integer NULL
grupo_codigo         text NULL
grupo_nome           text NULL
habilitado           boolean DEFAULT true
classificacao        integer NULL
setup                boolean DEFAULT false
retrabalho           boolean DEFAULT false
retorno_automatico   boolean DEFAULT false
parada_geral         boolean DEFAULT false
oculto               boolean DEFAULT false
requer_detalhe       boolean DEFAULT false
requer_comentario    boolean DEFAULT false
acao_padrao           integer NULL
fonte                 text DEFAULT 'TBLResourceStatus.xls'
sincronizado_em       timestamp
```

Para o popup de Parada, o serviço usa registros habilitados e não ocultos,
exclui grupo `0001` e exclui os registros marcados como Setup ou Retrabalho.

### `operadores_apontamento`

```text
id          bigint IDENTITY PRIMARY KEY
cracha      text UNIQUE
nome        text
ativo       boolean DEFAULT true
fonte       text DEFAULT 'cadastro'
criado_em   timestamp DEFAULT CURRENT_TIMESTAMP
```

O snapshot já contém o crachá fictício `1`, nome `Iago`. A finalização exige
ao menos um crachá ativo.

### `apontamentos_operacionais`

Tabela gerenciada pelo sistema durante o teste:

```text
id                       bigint IDENTITY PRIMARY KEY
op                       text
peca                     text NULL
tarefa_id                bigint NULL REFERENCES tarefas(id) ON DELETE SET NULL
tipo_setor               text
maquina                  text
status                   text DEFAULT 'Aguardando'
quantidade               integer DEFAULT 1 CHECK (quantidade > 0)
operador_fila            text
data_entrada             timestamp
operador_inicio          text NULL
data_inicio              timestamp NULL
operador_fim             text NULL
data_fim                 timestamp NULL
setor_destino            text NULL
catalogo_operacao_id     bigint NULL REFERENCES catalogo_operacoes_op(id) ON DELETE SET NULL
numero_operacao          text NULL
codigo_recurso           text NULL
descricao_operacao       text NULL
produto_codigo           text NULL
produto_descricao        text NULL
quantidade_boa           integer DEFAULT 0 CHECK (quantidade_boa >= 0)
quantidade_refugo        integer DEFAULT 0 CHECK (quantidade_refugo >= 0)
motivo_parada            text NULL
comentario               text NULL
codigo_status_recurso    text NULL REFERENCES catalogo_status_recursos(codigo) ON DELETE RESTRICT

CHECK (quantidade_boa <= quantidade)
```

Estados usados pela aplicação: `Aguardando`, `Em processo`, `Parada`, `Setup`,
`Retrabalho` e `Finalizado`.

> Regra da Manufatura (schema v10): a quantidade planejada é atingida exclusivamente
> por `quantidade_boa`. Refugo permanece separado e não conclui a OP.

Índice único parcial crítico:

```sql
UNIQUE (upper(op), upper(tipo_setor))
WHERE status IN ('Aguardando', 'Em processo', 'Parada', 'Setup', 'Retrabalho')
```

Assim, uma OP não pode ter duas execuções ativas simultâneas no mesmo setor.

### `eventos_apontamento_operador`

```text
id                       bigint IDENTITY PRIMARY KEY
apontamento_id           bigint REFERENCES apontamentos_operacionais(id) ON DELETE CASCADE
estado                   text
motivo                   text NULL
comentario               text NULL
quantidade_boa           integer DEFAULT 0 CHECK (quantidade_boa >= 0)
quantidade_refugo        integer DEFAULT 0 CHECK (quantidade_refugo >= 0)
operador                 text
data_hora                timestamp
codigo_status_recurso    text NULL REFERENCES catalogo_status_recursos(codigo) ON DELETE RESTRICT

CHECK estado IN ('fila', 'producao', 'parada', 'setup', 'retrabalho', 'parcial', 'finalizado')
```

### `operadores_evento_apontamento`

```text
evento_id     bigint REFERENCES eventos_apontamento_operador(id) ON DELETE CASCADE
operador_id   bigint REFERENCES operadores_apontamento(id) ON DELETE RESTRICT

PRIMARY KEY (evento_id, operador_id)
```

### `eventos_destaque_tarefa`

```text
id                       bigint IDENTITY PRIMARY KEY
tarefa_id                bigint REFERENCES tarefas(id) ON DELETE CASCADE
estado                   text CHECK estado IN ('inicio', 'parada', 'retomada', 'fim')
codigo_status_recurso    text NULL REFERENCES catalogo_status_recursos(codigo) ON DELETE RESTRICT
motivo                   text NULL
comentario               text NULL
operador                 text
data_hora                timestamp
```

### `historico`

```text
id          bigint IDENTITY PRIMARY KEY
op          text
tipo        text
setor       text NULL
motivo      text NULL
quantidade  integer
operador    text
data_hora   timestamp
peca        text NULL
tarefa_id   bigint NULL REFERENCES tarefas(id) ON DELETE SET NULL
```

### `eventos_sistema`

```text
id          bigint IDENTITY PRIMARY KEY
tipo        text
origem      text NULL
referencia  text NULL
mensagem    text
operador    text NULL
detalhes    text NULL
data_hora   timestamp
```

Eventos técnicos não devem ser criados para simular produção.

### Catálogo SigmaNest/Corte

#### `catalogo_sigmanest_tarefas`

```text
codigo_tarefa    text PRIMARY KEY
material         text NULL
espessura        numeric NULL
ativo            boolean DEFAULT true
sincronizado_em  timestamp
```

#### `catalogo_sigmanest_ops`

```text
linha_hash       text PRIMARY KEY
codigo_tarefa    text REFERENCES catalogo_sigmanest_tarefas(codigo_tarefa) ON DELETE CASCADE
codigo_op        text
id_peca          text NULL
setor_destino    text
quantidade       integer CHECK (quantidade >= 0)
dobra            text NULL
usinagem         text NULL
solda            text NULL
chanfro          text NULL
ativo            boolean DEFAULT true
sincronizado_em  timestamp
```

#### `catalogo_sigmanest_programas`

```text
codigo_tarefa    text REFERENCES catalogo_sigmanest_tarefas(codigo_tarefa) ON DELETE CASCADE
programa         text
ativo            boolean DEFAULT true
sincronizado_em  timestamp

PRIMARY KEY (codigo_tarefa, programa)
```

#### `catalogo_sigmanest_planos_corte`

```text
plano_hash                 text PRIMARY KEY
codigo_tarefa              text
programa                   text
nome_chapa                 text NULL
sequencia_nesting          integer CHECK (sequencia_nesting > 0)
area_usada                 numeric NULL
fracao_sucata              numeric NULL
quantidade_processo        integer DEFAULT 1 CHECK (quantidade_processo > 0)
maquina_qlik               text
tempo_previsto_segundos    numeric NULL
tempo_previsto_formatado   text NULL
data_programa              date NULL
status_programa            text NULL
ativo                      boolean DEFAULT true
sincronizado_em            timestamp
```

`codigo_tarefa` é uma referência lógica à tarefa SigmaNest; essa tabela não
possui FK física nessa coluna no schema atual. `maquina_qlik` armazena o código
técnico (`AMADA_ENSIS` ou `MESSER_XPR_300`), nunca o nome público exibido na
tela.

#### `apontamentos_corte`

```text
id                        bigint IDENTITY PRIMARY KEY
plano_hash                text UNIQUE REFERENCES catalogo_sigmanest_planos_corte(plano_hash)
codigo_tarefa             text
programa                  text
nome_chapa                text NULL
sequencia_nesting         integer
material                  text NULL
espessura                 numeric NULL
maquina                   text
maquina_qlik              text NULL
quantidade_processo       integer DEFAULT 1 CHECK (quantidade_processo > 0)
tempo_previsto_segundos   numeric NULL
data_programa             date NULL
area_usada                numeric NULL
fracao_sucata             numeric NULL
status                    text CHECK status IN ('Em processo', 'Finalizado')
operador_inicio           text
data_inicio               timestamp
operador_fim              text NULL
data_fim                  timestamp NULL
```

Regra adicional: `Em processo` exige fim/operador de fim nulos; `Finalizado`
exige ambos preenchidos.

### Tabelas administrativas

#### `usuarios`

```text
id            bigint IDENTITY PRIMARY KEY
nome          text UNIQUE
senha_hash    text
nivel         text DEFAULT 'operador_destaque'
ativo         boolean DEFAULT true
data_criacao  timestamp DEFAULT CURRENT_TIMESTAMP
```

Não criar senha em texto puro e não alterar usuários numa carga de OPs.

#### `schema_migrations`

```text
version      integer PRIMARY KEY
descricao    text
applied_at   timestamp DEFAULT CURRENT_TIMESTAMP
```

Não inserir, atualizar ou remover linhas manualmente.

## Ordem recomendada de inserção

### OPs comuns para Dobra, Usinagem, Serra, Solda ou Pintura

```text
1. catalogo_pcp_ops
2. catalogo_operacoes_op
3. tarefas                  (opcional)
4. op_por_tarefa            (opcional, depois de tarefas)
```

### Tarefa completa de Corte

```text
1. catalogo_pcp_ops
2. catalogo_operacoes_op
3. catalogo_sigmanest_tarefas
4. catalogo_sigmanest_programas
5. catalogo_sigmanest_planos_corte
6. catalogo_sigmanest_ops
7. tarefas
8. op_por_tarefa
```

Não inserir previamente em `apontamentos_corte` se o objetivo for testar o
botão de início do Corte.

## Prompt pronto para enviar à outra IA

Copie o texto abaixo e anexe este arquivo:

```text
Use o schema anexado como fonte de verdade. Gere um único script SQL
PostgreSQL, transacional e idempotente, apenas para o banco isolado de teste do
Gestor de Peças. Não execute o SQL.

Objetivo: criar dados totalmente fictícios para testar manualmente a tela de
apontamento dos operadores. Cada OP deve existir em catalogo_pcp_ops e possuir
roteiro em catalogo_operacoes_op. Gere OPs distribuídas entre Corte, Dobra,
Usinagem, Serra, Solda e Pintura, com quantidades positivas e roteiros de 2 a 6
operações. Inclua tarefas/op_por_tarefa somente para os cenários que devem
passar por Corte e Destaque.

Regras obrigatórias:
- não alterar usuarios, schema_migrations, recursos ou motivos de parada;
- não inserir eventos, histórico ou apontamentos já iniciados;
- não criar uma operação Destaque no roteiro;
- criar tarefas novas com tarefas.status NULL e as datas de Destaque nulas;
- usar AMADA_ENSIS ou MESSER_XPR_300 em
  catalogo_sigmanest_planos_corte.maquina_qlik, nunca o nome público da tela;
- não usar 'Aguardando Dobra', 'Aguardando Usinagem' ou nomes semelhantes como
  destino; use a máquina/setor real indicado no schema;
- manter produto e quantidade coerentes entre o cabeçalho e o roteiro;
- usar colunas explícitas, BEGIN/COMMIT e ON CONFLICT nas chaves naturais;
- não usar DELETE, TRUNCATE, DROP, ALTER ou reset de sequences;
- deixar colunas IDENTITY sem valor explícito;
- usar códigos e nomes claramente fictícios, sem copiar dados produtivos;
- ao final, incluir consultas SELECT de validação, mas não comandos de
  apontamento.

Antes do SQL, apresente uma tabela-resumo com OP, produto, quantidade e roteiro.
Depois do SQL, explique quais OPs podem ser testadas em cada setor e máquina.
```

## Consultas de validação após a carga

```sql
SELECT
    p.codigo_op,
    p.produto_codigo,
    p.quantidade,
    count(o.id) AS etapas
FROM catalogo_pcp_ops p
LEFT JOIN catalogo_operacoes_op o
       ON o.codigo_op = p.codigo_op
      AND o.ativo = true
WHERE p.ativo = true
GROUP BY p.codigo_op, p.produto_codigo, p.quantidade
ORDER BY p.codigo_op;

SELECT
    o.codigo_op,
    o.ordem,
    o.numero_operacao,
    o.tipo_setor,
    o.codigo_recurso,
    o.descricao_operacao
FROM catalogo_operacoes_op o
WHERE o.ativo = true
ORDER BY o.codigo_op, o.ordem, o.id;

SELECT
    t.codigo_tarefa,
    opt.codigo_op,
    opt.setor_destino_atual,
    opt.quantidade_atual
FROM tarefas t
JOIN op_por_tarefa opt ON opt.tarefa_id = t.id
ORDER BY t.codigo_tarefa, opt.codigo_op;
```
