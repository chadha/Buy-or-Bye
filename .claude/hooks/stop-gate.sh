#!/bin/bash
# Stop: Claude can't finish a turn that changed Python while `make check` fails.
# Skips when nothing in app/ or tests/ changed, and never loops (stop_hook_active).
INPUT=$(cat)
if [ "$(echo "$INPUT" | jq -r '.stop_hook_active')" = "true" ]; then
  exit 0
fi
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
if git diff --quiet HEAD -- app tests 2>/dev/null && [ -z "$(git ls-files --others --exclude-standard app tests)" ]; then
  exit 0
fi
if ! OUTPUT=$(make check 2>&1); then
  echo "make check is failing. Fix it before finishing:" >&2
  echo "$OUTPUT" | tail -n 30 >&2
  exit 2
fi
exit 0
