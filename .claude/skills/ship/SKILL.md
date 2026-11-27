---
name: ship
description: Finish a change - check, branch, commit, independent review, open a PR.
disable-model-invocation: true
---
Ship the current change: $ARGUMENTS

1. Run `make check`. If it fails, fix the root cause and re-run. Never skip or silence a check.
2. If on `main`, create a branch: `git switch -c <feat|fix>/<short-name>`.
3. Commit with a message that explains why.
4. Use the `reviewer` subagent on `git diff main...HEAD`. Fix findings that affect correctness
   or the rules in AGENTS.md; list the rest in the PR as optional.
5. Ask before pushing, then `git push -u origin HEAD` and `gh pr create` with: what changed,
   how to try it in the UI, and the `make check` output.
6. Reply with the PR link only.
