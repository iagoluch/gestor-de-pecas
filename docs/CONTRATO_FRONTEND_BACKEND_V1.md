# Contrato Frontend ↔ Backend v1

## Regra principal

O frontend não calcula indicadores industriais. Ele envia filtros/intenção e apresenta o resultado do backend.

## Descoberta de capacidades

```python
facade.capabilities()
```

Retorna:

- `contract_version`;
- `schema_version`;
- seções disponíveis;
- fontes canônicas;
- regras da Manufatura que a UI deve respeitar;
- políticas visuais/funcionais;
- definições ainda pendentes.

Isso permite que a futura API exponha um endpoint equivalente, por exemplo `/api/v1/capabilities`, sem duplicar regras.

## Início / Management View

```python
facade.inicio(filters)
```

Uso: cockpit gerencial, produção boa, composição física dos tempos, setores, Nesting, qualidade dos dados e rateio.

## Consulta Operacional

```python
facade.consulta_operacional(filters)
```

Uso: situação atual dos recursos e OPs ativas. O estado físico vem de `eventos_estado_recurso`.

## Produção

```python
facade.producao(filters)
```

Uso: Planejado × Realizado, Tempo Padrão × Real e tempos individuais de Nesting.

Planejamento é externo/Protheus; o Gestor registra execução real.

## Análises

```python
facade.analises(filters)
```

Uso:

- composição de tempos;
- paradas;
- setup;
- qualidade;
- Tempo Padrão × Real;
- Cronoanálise;
- capacidade quando configurada.

OEE, Disponibilidade, Performance e FTT são calculados pela fonte canônica
`mes.analytics.oee.calculate_oee`. O contrato transporta percentuais na escala
`0..100`, com precisão integral no backend e arredondamento apenas de apresentação.
Ausência real de insumo permanece explícita, sem ser convertida em zero.

## Auditoria

```python
facade.auditoria(filters)
```

Uso: inconsistências e confiabilidade dos dados. Não criar percentual de confiabilidade no frontend.

## Rastreabilidade

```python
facade.rastreabilidade(op)
```

Uso: drill-down da OP até eventos, recurso físico, operador, rateio, Nesting e fonte original.

## Políticas obrigatórias da interface

- não criar aba/card gerencial de Correção ou Edição;
- não somar refugo à Produção Realizada;
- não multiplicar tempo por OPs simultâneas;
- exibir dado indisponível/parcial como tal;
- não transformar `None` em zero;
- não recalcular OEE/Disponibilidade/Performance/FTT;
- manter filtros e exportações consumindo a mesma camada de serviço das telas.

## Serialização Web futura

Os contratos não dependem de FastAPI/Pydantic. A camada HTTP futura deve somente:

1. validar/autenticar a requisição;
2. converter filtros para `AnalyticsFilter`;
3. chamar o caso de uso/facade;
4. serializar datas/valores;
5. devolver a resposta.

Não mover regras de domínio para controllers/endpoints.
