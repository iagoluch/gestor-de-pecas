# Cenários — Homologação Extrema

## Convenções

- OPs: `HOMEXT00001` até `HOMEXT00120`.
- Produtos: `PÇ-HOM-001` até `PÇ-HOM-024`.
- Tarefas: `T-HOM-001` até `T-HOM-024`.
- Planos: `hom:plano:<tarefa>:<nesting>`.
- Crachás: `H001` até `H012`.
- Todos os registros fictícios possuem origem ou observação ligada à homologação extrema.

## Fábrica simulada

Os 120 apontamentos são distribuídos entre Corte, Dobra, Usinagem, Serra, Solda e Pintura, em 10 dias e múltiplos turnos. Recursos são alternados entre perfis excelente, bom, médio, ruim, crítico, ocioso e com dados incompletos. A amostra inclui OP concluída, em processo, aguardando, parada, em setup e em retrabalho.

### Perfis usados

| Perfil | Características intencionais |
|---|---|
| Excelente | Bom volume, pouca perda e tempo real próximo do previsto |
| Bom | Pequenos desvios e perdas controladas |
| Médio | Variação moderada de tempo e qualidade |
| Ruim | Mais paradas, refugo e diferença Plano × Real |
| Crítico | Conflito físico, sobreposição ou inconsistência auditável |
| Ocioso | Sem demanda ou sem atividade no recorte |
| Dados incompletos | Causa raiz ou informação necessária ausente, sem preenchimento inventado |

## Produção, qualidade e estados

- `HOMEXT00001` contém descrição longa e acentuada: “Conjunto de proteção — aço inoxidável...”.
- Eventos de peças boas, refugo e retrabalho usam origens independentes, evitando duplicação.
- Há 24 OPs concluídas com refugo separado, comprovando que refugo não completa a quantidade planejada.
- Setup e Retrabalho aparecem como estados distintos, com seis OPs em cada estado.
- Parada manual sem OP e atividade produtiva sem OP são representadas em `TURNO-RES-01`.
- `SERRA-ZERO` possui evento de duração zero para validar tratamento de borda.

## Turnos

O calendário possui três turnos, intervalos e exceção. De 11/08 a 19/08 existem interrupções automáticas exatamente às 17:30 e 21:30, totalizando 18 eventos. A classificação esperada é programada, sem conversão em parada manual.

## OPs simultâneas e rateio

`HOMEXT00001` e `HOMEXT00002` compartilham a sessão física de `DOBRA-SIM-01`:

- tempo físico: 7.200 segundos;
- soma atribuída às duas OPs: 7.200 segundos;
- quantidade de OPs: 2;
- resultado obrigatório: conservação integral do tempo físico, sem duplicação.

## Estados conflitantes

Em `CNC-CONFLITO`, no dia 17/08/2026 entre 16:30 e 17:00, dois estados incompatíveis ocupam o mesmo recurso. Os 1.800 segundos devem permanecer visíveis como conflito/desconhecido. O sistema não pode escolher silenciosamente um vencedor.

## Corte e Nesting

- 24 tarefas e 48 planos, dois nestings por tarefa.
- 30 apontamentos realizados, sendo 20 concluídos e 10 ainda em processo.
- Máquinas alternadas entre Laser Ensis 3015 e Plasma TerraBlade 4.
- Materiais, espessuras, programas e tempos variam.
- Cada nesting preserva `previsto_segundos` próprio.
- A fila deve exibir tarefa, programa, nesting, material, espessura, tempo previsto, estado e progresso.

## Destaque

Os 44 eventos cobrem avanço, conclusão parcial e conclusão de tarefas de Corte, permitindo rastrear a liberação sequencial sem confundir Destaque com apontamento de máquina.

## Solda e demais setores

Solda possui recursos diferentes e estações selecionáveis, com OPs em múltiplos estados. Dobra, Usinagem e Serra usam recursos oficiais de seleção. Pintura usa posto operacional direto. O acesso do operador permanece limitado ao setor do usuário.

## Dados ruins deliberados

As 12 inconsistências são propositalmente preservadas. Incluem causa raiz ausente, evento de duração zero, estado conflitante e combinações incompletas. Elas devem aparecer em Auditoria/Confiabilidade e nunca ser “corrigidas” automaticamente.

## Web, API e segurança

- Usuário não autenticado: HTTP 401.
- Login inválido: HTTP 401.
- Operador tentando Management View: HTTP 403.
- Cookie da sessão gerencial: `HttpOnly`.
- Período invertido: HTTP 400.
- Paginação: segunda página com 17 itens por página.
- Exportação: CSV com BOM UTF-8, acentos preservados e 108 linhas.
- Concorrência: 24 requisições gerenciais em até oito threads.
- SSE: dois clientes recebem a mesma publicação e recebem `live_tick` sem depender de alteração no banco.

## Evidência visual

Foram capturadas telas gerenciais críticas em 1920×1080, 1600×900 e 1366×768. O fluxo do operador inclui Destaque, seleções de Dobra/Usinagem/Serra/Corte, fila de Corte, Pintura, Solda e postos críticos em resoluções menores. Os usuários temporários da captura são removidos ao final; os usuários normais copiados permanecem no banco exclusivo.

## Reexecução e limpeza

Carga idempotente:

```powershell
C:\Python314\python.exe tests\homologacao_extrema\seed_homologacao_extrema.py
```

Reconciliação:

```powershell
C:\Python314\python.exe tests\homologacao_extrema\reconcile.py
```

O script de limpeza é seguro por padrão e apenas descreve a ação. A remoção exige, simultaneamente, `--drop` e `--confirm-name` com o nome exato. Ele não foi executado com autorização de remoção, pois o banco deve permanecer disponível para auditoria.
