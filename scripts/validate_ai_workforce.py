#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORG = ROOT / ".ai" / "organization.json"

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--quiet",action="store_true"); a=p.parse_args()
    errors=[]
    data=json.loads(ORG.read_text(encoding="utf-8"))
    sectors=data.get("sectors",[]); employees=data.get("employees",[])
    sids=[s["id"] for s in sectors]; eids=[e["id"] for e in employees]
    if len(sids)!=len(set(sids)): errors.append("sector IDs duplicados")
    if len(eids)!=len(set(eids)): errors.append("employee IDs duplicados")
    sset=set(sids); eset=set(eids)
    for e in employees:
        eid=e["id"]
        if e["sector"] not in sset: errors.append(f"{eid}: setor inexistente")
        for path in [ROOT/".ai"/"employees"/f"{eid}.md", ROOT/".claude"/"agents"/f"{eid}.md"]:
            if not path.exists(): errors.append(f"arquivo ausente: {path.relative_to(ROOT)}")
        for skill in e.get("skills",[]):
            for base in [ROOT/".claude"/"skills",ROOT/".agents"/"skills"]:
                path=base/skill/"SKILL.md"
                if not path.exists(): errors.append(f"skill ausente: {path.relative_to(ROOT)}")
    for s in sectors:
        for eid in s.get("employees",[]):
            if eid not in eset: errors.append(f"{s['id']}: funcionario inexistente {eid}")
    if errors:
        print("IA Workforce INVALIDA:")
        for err in errors: print("-",err)
        return 1
    if not a.quiet: print(f"IA Workforce OK: {len(sectors)} setores, {len(employees)} funcionarios.")
    return 0

if __name__=="__main__": raise SystemExit(main())
