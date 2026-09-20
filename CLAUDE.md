## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- Graph scope: `mes/`, `backend/`, `app/`, `web/`, `tests/` (code only — `docs/` and `assets/` are intentionally excluded: docs are 1.6M words of historical reports, low value for architecture queries; assets are images). Do not run `graphify update .` at the project root — it was not built from a root-level extraction and has no root manifest.
- After modifying code, rebuild with: `graphify extract ./mes/ --code-only && graphify extract ./backend/ --code-only && graphify extract ./app/ --code-only && graphify extract ./web/ --code-only && graphify extract ./tests/ --code-only && graphify merge-graphs ./mes/graphify-out/graph.json ./backend/graphify-out/graph.json ./app/graphify-out/graph.json ./web/graphify-out/graph.json ./tests/graphify-out/graph.json --out graphify-out/graph.json && graphify cluster-only .` (AST-only, no API cost). This also runs automatically in the background after every `git commit` via `.git/hooks/graphify-rebuild.sh` (only when a commit touches those 5 folders) — check `~/.cache/graphify-rebuild.log` if the graph seems stale.
