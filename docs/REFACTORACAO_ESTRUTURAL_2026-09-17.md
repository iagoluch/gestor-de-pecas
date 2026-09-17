# Refatoração estrutural — 17/09/2026

## Escopo e proteção

Auditoria estática de código, configurações, scripts, testes e assets. O banco
REAL não foi acessado nem alterado. As regras industriais, a fronteira
`FrontendBackendFacade`, migrations históricas, integrações TOTVS/SigmaNEST,
relatórios e referências visuais aprovadas foram preservados.

## Métricas de partida

| Métrica | Antes |
| --- | ---: |
| Arquivos-fonte Python/TS/TSX | 413 |
| Python | 319 |
| TypeScript | 23 |
| TSX | 71 |
| LOC aproximado | 112.629 |
| Arquivos-fonte menores que 20 linhas | 37 |
| Arquivos-fonte maiores que 500 linhas | 66 |
| Arquivos-fonte maiores que 800 linhas | 30 |

Após a primeira onda: **408** arquivos-fonte, **111.684** LOC, 35 arquivos
menores que 20 linhas e 65 maiores que 500 linhas. A queda de 945 linhas inclui
remoção de código morto; não houve compactação de regras de negócio.

O frontend tinha 98 fontes (19.848 LOC), 21 diretórios e profundidade máxima
três. O grafo Python de `app/`, `backend/` e `mes/` tinha 190 módulos, 509
dependências e nenhum ciclo.

## Auditoria e decisões

- **A/J:** `mes/analytics/canonical.py` não tinha importador, teste, script ou
  configuração consumidora. Removido.
- **A/D/F:** `mes/repositories/` continha dois protocolos sem consumidor.
  Removido junto com o diretório.
- **A/M/K:** nove arquivos vazios versionados em `web/`, dois caches
  `*.tsbuildinfo`, a tela não roteada `OperatorPendingPage` e o tipo órfão
  `QualityContext` foram removidos. `recharts` não possuía import no frontend
  e saiu das dependências.
- **C/O:** a serialização de valores de contrato era duplicada em
  `mes.contracts.management` e `mes.contracts.insights`; ficou uma única
  implementação compartilhada.
- **N/G/H:** páginas filhas do operador importavam helpers triviais da página
  raiz, formando um ciclo. Elas agora chamam o cliente HTTP diretamente e a
  mensagem de erro pertence ao cliente compartilhado.
- **C/K/N:** `EXPECTED_TABLES` era incompleto e o reset do TESTE mantinha uma
  segunda lista divergente. O manifesto de migrations agora é fonte única para
  diagnóstico e reset; o teste de schema exige igualdade, não subconjunto.

## Itens preservados deliberadamente

- migrations append-only, `FrontendBackendFacade`, routers FastAPI pequenos,
  módulos TOTVS/SigmaNEST e o pacote de relatórios;
- `QualityPage.tsx`, capacidade dormente intencional da Qualidade;
- assets de mockup e screenshots aprovados;
- `_quarentena_revisar/`, cuja exclusão exige decisão específica;
- refatoração de `Database` (5.466 linhas), a ser feita por blocos coesos e
  compatíveis, nunca em uma migração estrutural única.

## Validação da onda

- fluxos Web do operador, Qualidade, Corte e Chamada: **61 testes aprovados**;
- build Web (`tsc -b` + Vite): concluído;
- validação Python dirigida: 117/118; a falha restante é uma asserção
  pré-existente de contagem de consultas no Andon, fora dos arquivos alterados;
- banco REAL: nenhuma conexão ou operação executada.

## Pendências de próximas ondas

1. Remover CSS legado do Andon somente com validação visual em 1920×1080,
   1440 e perfil TV.
2. Extrair blocos coesos de `Database` mantendo a fachada e assinaturas.
3. Corrigir o README/configuração obsoleta da simulação somente depois de
   validar o fluxo industrial atual.
