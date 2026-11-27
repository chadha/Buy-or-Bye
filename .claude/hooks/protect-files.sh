#!/bin/bash
# PreToolUse (Edit|Write): block edits to secrets, git internals and recorded idealo responses.
# Recorded fixtures are evidence: re-record them, never hand-edit them.
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
FILE_PATH="${FILE_PATH//\\//}"
for pattern in "/.env" ".git/" "tests/fixtures/idealo/"; do
  if [[ "$FILE_PATH" == *"$pattern"* ]]; then
    echo "Blocked: $FILE_PATH is protected ($pattern). Secrets and recorded idealo responses are not edited by hand." >&2
    exit 2
  fi
done
exit 0
