---
name: architecture-review
description: Review architecture, layer boundaries, coupling and cross-cutting changes in Gestor de Peças.
---
# architecture-review

Comece por Graphify. Preserve React → FastAPI → services/contracts → domain/analytics → PostgreSQL. Procure verdade duplicada, dependência reversa, acoplamento oculto e abstração desnecessária. Se a semântica industrial mudar, consulte `mes-domain-guardian`.
