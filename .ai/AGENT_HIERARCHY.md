# Hierarquia de agentes

A topologia é **default-deny**:

```text
Iago
 ├─ claude-orchestrator (Opus 5.5 / high)
 └─ codex-orchestrator  (GPT-5.6 Sol / high)
        │
        └── workforce_employee
               │
               └── specialist_subagent (somente se explicitamente autorizado)
```

## Tipos

- `orchestrator`: runtime principal. Pode chamar funcionários, integrar resultados e decidir roteamento.
- `workforce_employee`: funcionário persistente de um setor. Não orquestra outros funcionários. Pode usar specialists explicitamente autorizados.
- `specialist_subagent`: subagente estreito de ferramenta/workflow. É leaf e não pode chamar outros agentes.

## Impeccable

Os quatro subagentes Impeccable existentes são `specialist_subagent` do `frontend-engineer`:

- `impeccable-asset-producer`
- `impeccable-documenter`
- `impeccable-finish-reviewer`
- `impeccable-manual-edit-applier`

O orquestrador não deve pular o Frontend Engineer para chamá-los diretamente.

## Por que workforce employees não chamam outros employees?

Dependência entre especialistas é coordenada pelo orquestrador. Isso evita cadeias recursivas, contexto perdido e dois agentes tentando assumir ownership da mesma tarefa.

Exemplo:

```text
Opus
 ├─ OEE Engineer
 ├─ MES Domain Guardian
 └─ QA Engineer
```

e não:

```text
Opus → OEE → MES Guardian → QA → ...
```
