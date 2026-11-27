# How we work with Claude Code

Distilled from Anthropic's published Claude Code best practices
(https://code.claude.com/docs/en/best-practices), applied to this repo.

## The loop
1. **Explore** in plan mode (`Shift+Tab` until "plan mode on"): "read app/verdict.py and
   docs/SPEC.md; how would we add X?"
2. **Plan:** ask for the plan, edit it (`Ctrl+G`), then approve. Skip this for one-line fixes.
3. **Implement with a check:** "write the failing test, implement, run `make check`, show the output".
   The Stop hook blocks finishing while `make check` fails.
4. **Ship:** `/ship`, which runs the checks, has the `reviewer` subagent review the diff in a fresh
   context, and opens the PR.

## Context hygiene
- `/clear` between unrelated tasks. After two failed corrections, `/clear` and re-prompt with what
  you learned: a clean session beats a long one.
- Research goes to subagents ("use the data-scout subagent to …") so the main context stays small.
- Name sessions with `/rename` (`idealo-adapter`, `ui-chart`) and resume with `claude --resume`.

## Parallel work on the day
- One feature per git worktree, each with its own Claude session, so edits don't collide:
  `git worktree add ../bob-ui -b feat/ui` then run `claude` inside it.
- Writer/reviewer: session A implements; session B (or the `reviewer` subagent) reviews.
- Suggested split: (1) idealo adapter via `/idealo-connect`, (2) UI and photo flow,
  (3) pitch, demo deals and `/demo` rehearsal.

## What lives where
| Need | Mechanism |
|---|---|
| Facts every session needs | `AGENTS.md` (shared) via `CLAUDE.md` |
| Rules for certain files only | `.claude/rules/` with `paths:` |
| Must happen every time | hooks in `.claude/settings.json` |
| Repeatable procedures | skills: `/ship`, `/demo`, `/deal-eval`, `/spec-interview`, `/idealo-connect` |
| Isolated research or review | subagents: `data-scout`, `reviewer`, `test-writer` |
| Review on GitHub | `@claude` in a PR or issue; automatic review on every PR |
