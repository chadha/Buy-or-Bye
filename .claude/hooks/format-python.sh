#!/bin/bash
# PostToolUse (Edit|Write): format and auto-fix the Python file that was just edited.
FILE_PATH=$(jq -r '.tool_input.file_path // empty')
[[ "$FILE_PATH" == *.py ]] || exit 0
command -v ruff >/dev/null 2>&1 || exit 0
ruff format --quiet "$FILE_PATH" && ruff check --fix --quiet "$FILE_PATH" >/dev/null 2>&1
exit 0
