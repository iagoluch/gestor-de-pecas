#!/usr/bin/env bash
# PostToolUse hook: type-checks the TypeScript project after an edit touches
# web/**/*.ts(x). Uses the project's own tsc -b (same command as `npm run build`),
# so it respects tsconfig project references instead of guessing flags per-file.
input=$(cat)
file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // .tool_response.filePath // empty')

case "$file" in
  *.ts|*.tsx) : ;;
  *) exit 0 ;;
esac
case "$file" in
  web/*|*/web/*) : ;;
  *) exit 0 ;;
esac

cd web || exit 0
out=$(node_modules/.bin/tsc -b tsconfig.json --pretty false 2>&1)
status=$?
if [ "$status" -ne 0 ]; then
  printf '%s' "$out" | jq -Rs '{decision:"block", reason: ("Erros de type-check TypeScript (tsc -b):\n" + .)}'
fi
exit 0
