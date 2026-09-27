#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORG = ROOT / ".ai" / "organization.json"
VALID_TYPES = {"orchestrator", "workforce_employee", "specialist_subagent"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    data = json.loads(ORG.read_text(encoding="utf-8"))
    sectors = data.get("sectors", [])
    employees = data.get("employees", [])
    orchestrators = data.get("orchestrator_nodes", [])
    specialists = data.get("specialist_subagents", [])

    sector_ids = [s["id"] for s in sectors]
    employee_ids = [e["id"] for e in employees]
    orchestrator_ids = [o["id"] for o in orchestrators]
    specialist_ids = [s["id"] for s in specialists]
    all_nodes = orchestrators + employees + specialists
    all_ids = [n["id"] for n in all_nodes]

    if len(sector_ids) != len(set(sector_ids)):
        errors.append("sector IDs duplicados")
    if len(all_ids) != len(set(all_ids)):
        errors.append("agent IDs duplicados entre tipos")

    sector_set = set(sector_ids)
    employee_set = set(employee_ids)
    specialist_set = set(specialist_ids)
    node_by_id = {n["id"]: n for n in all_nodes}

    for node in all_nodes:
        if node.get("type") not in VALID_TYPES:
            errors.append(f"{node['id']}: tipo invalido {node.get('type')!r}")

    for o in orchestrators:
        if o.get("type") != "orchestrator":
            errors.append(f"{o['id']}: deve ser orchestrator")
        if o.get("can_call_types") != ["workforce_employee"]:
            errors.append(f"{o['id']}: orchestrator so pode chamar workforce_employee")
        if o.get("can_call_ids"):
            errors.append(f"{o['id']}: use tipo para workforce; nao liste specialist direto")

    for e in employees:
        eid = e["id"]
        if e.get("type") != "workforce_employee":
            errors.append(f"{eid}: deve ser workforce_employee")
        if e["sector"] not in sector_set:
            errors.append(f"{eid}: setor inexistente")
        for path in [
            ROOT / ".ai" / "employees" / f"{eid}.md",
            ROOT / ".claude" / "agents" / f"{eid}.md",
        ]:
            if not path.exists():
                errors.append(f"arquivo ausente: {path.relative_to(ROOT)}")
        for skill in e.get("skills", []):
            for base in [ROOT / ".claude" / "skills", ROOT / ".agents" / "skills"]:
                path = base / skill / "SKILL.md"
                if not path.exists():
                    errors.append(f"skill ausente: {path.relative_to(ROOT)}")
        for callee in e.get("can_call_ids", []):
            if callee not in specialist_set:
                errors.append(f"{eid}: can_call_ids aponta para nao-specialist {callee}")
            elif eid not in node_by_id[callee].get("parent_ids", []):
                errors.append(f"{eid} -> {callee}: specialist nao autoriza este parent")
        for t in e.get("can_call_types", []):
            if t != "specialist_subagent":
                errors.append(f"{eid}: workforce nao pode chamar tipo {t}")

    for s in specialists:
        sid = s["id"]
        if s.get("type") != "specialist_subagent":
            errors.append(f"{sid}: deve ser specialist_subagent")
        parents = s.get("parent_ids", [])
        if not parents:
            errors.append(f"{sid}: specialist sem parent autorizado")
        for parent in parents:
            if parent not in employee_set:
                errors.append(f"{sid}: parent inexistente/nao-workforce {parent}")
            elif sid not in node_by_id[parent].get("can_call_ids", []):
                errors.append(f"{sid}: parent {parent} nao declara a chamada reciproca")
        if s.get("can_call_types") or s.get("can_call_ids"):
            errors.append(f"{sid}: specialist deve ser leaf e nao pode chamar agentes")
        path = ROOT / ".claude" / "agents" / f"{sid}.md"
        if not path.exists():
            errors.append(f"specialist sem arquivo Claude: {path.relative_to(ROOT)}")

    for sector in sectors:
        for eid in sector.get("employees", []):
            if eid not in employee_set:
                errors.append(f"{sector['id']}: funcionario inexistente {eid}")

    # Validate declared edges and reject cycles. Type policy is default-deny.
    edges: dict[str, set[str]] = {nid: set() for nid in all_ids}
    for o in orchestrators:
        # Type-based orchestrator edge expands to every workforce employee.
        edges[o["id"]].update(employee_ids)
    for e in employees:
        edges[e["id"]].update(e.get("can_call_ids", []))
    for s in specialists:
        edges[s["id"]].update(s.get("can_call_ids", []))

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            errors.append(f"ciclo de chamada detectado em {node_id}")
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        for callee in edges.get(node_id, set()):
            if callee not in node_by_id:
                errors.append(f"{node_id}: chama agente inexistente {callee}")
            else:
                visit(callee)
        visiting.remove(node_id)
        visited.add(node_id)

    for nid in all_ids:
        visit(nid)

    if errors:
        print("IA Workforce INVALIDA:")
        for error in sorted(set(errors)):
            print("-", error)
        return 1

    if not args.quiet:
        edge_count = sum(len(v) for v in edges.values())
        print(
            "IA Workforce OK: "
            f"{len(sectors)} setores, {len(employees)} funcionarios, "
            f"{len(orchestrators)} orquestradores, {len(specialists)} specialists, "
            f"{edge_count} arestas autorizadas."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
