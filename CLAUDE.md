# CLAUDE.md — instructions for AI coding assistants

This project uses **spec-driven development with GitHub Spec Kit**. Read before doing anything:

1. `.specify/memory/constitution.md` — non-negotiable principles and quality gates.
2. `specs/000-discovery.md` — who the customer is, what success means, risks.
3. The active feature folder (see `.specify/feature.json`), e.g. `specs/001-code-assistant/`
   with `spec.md`, `plan.md`, `tasks.md`.

## Workflow
`/speckit-specify` → `/speckit-clarify` → `/speckit-plan` → `/speckit-tasks` →
`/speckit-analyze` → `/speckit-implement`

## Rules
- Only implement tasks listed in `tasks.md`. If something is missing, propose a spec/plan change first.
- Reference requirement IDs (`FR-xxx`) in tests and commit messages.
- Never change `spec.md` or the constitution without the author's explicit approval.
- Write the test with (or before) the code. Run tests before claiming a task is done.
- A task is ticked `[x]` only after the `spec-reviewer` subagent returns `VERDICT: PASS`.
- Before committing a finished user story, run `python scripts/cross-review.py` (Gemini reviews
  Claude's code) and address or explicitly dismiss each finding.
- Keep changes small: one task per change.

## Don'ts
- No new dependencies without a line in `plan.md` saying why.
- No hard-coded keys, model names or URLs.
- Don't write the README's opinion sections ("why", "how I used AI", "what I'd change") — the author writes those.
