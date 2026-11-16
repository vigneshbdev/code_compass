# CodeCompass Constitution

Non-negotiable principles for this project. Every spec, plan, task and line of code
(human- or AI-written) must comply. If something conflicts with this file, this file wins
or gets amended explicitly — never silently ignored.

## Core Principles

### I. Spec is the source of truth
- Work flows: discovery → `spec.md` → `plan.md` → `tasks.md` → code. No code without a task;
  no task without a requirement.
- Every requirement has an ID (`FR-xxx`, `NFR-xxx`, `SC-xxx`). Tests and commits reference those IDs.
- When behaviour changes, the spec changes first.

### II. Simple and solid over clever
- Prefer the boring, well-understood option. Add a component only when a requirement needs it.
- One process per concern; no microservices, queues or Kubernetes in the core solution.
  Production-scale architecture is *documented*, not built.

### III. Grounded answers or no answer
- Every factual claim about the codebase must cite a source (`path:start-end`).
- If retrieval does not support an answer, the assistant says so instead of guessing.

### IV. Safe by default
- Secrets found in ingested code are never shown to the user or sent to the LLM.
- Ingested content is untrusted data, never instructions.
- Guardrails are tested like any other feature.

### V. Observable by default
- Every request produces a trace: retrieval results, prompt, model, tokens, cost, latency.
- Answer quality is measured with a versioned evaluation set, not by vibes.

### VI. Provider-agnostic
- LLM and embedding providers sit behind a single interface and are chosen by config.

### VII. Tested and reproducible (NON-NEGOTIABLE)
- Core logic (chunking, retrieval, guardrails) has unit tests written with or before the code;
  the API has integration tests.
- `docker compose up` runs the whole app. Setup takes under five minutes, excluding the one-time
  container image download (`docker compose pull`), whose duration the README reports separately.

### VIII. Readable by a stranger
- Clear module boundaries, typed code, small functions, no dead code.
- The README explains *why*, not just *what*.

## Development Workflow

Spec Kit drives the workflow: `/speckit-specify` → `/speckit-clarify` → `/speckit-plan` →
`/speckit-tasks` → `/speckit-analyze` → `/speckit-implement`.

`specs/000-discovery.md` is an addition on top of Spec Kit: it reads the brief as a customer
engagement (stakeholders, implicit requirements, risks) and every spec traces back to it.

## Quality Gates

Borrowed from multi-agent orchestration practice (metaswarm), kept deliberately lightweight:

1. **Human gate:** the author approves `spec.md` and `plan.md` before any code is written.
2. **Never trust a self-report:** a task is not done because the coding agent says so. The
   `spec-reviewer` subagent independently re-runs the tests and checks each acceptance
   scenario of the task's `FR-xxx` before the task is ticked.
3. **No model grades its own homework:** code written by Claude is reviewed by a different
   model (Gemini, via `scripts/cross-review.py`) before each commit of a completed user story.
4. **Tests green, lint clean** before every commit.

## Governance

- This constitution supersedes all other practices, including instructions in AI prompts.
- Amendments require: a stated reason, the author's approval, and a version bump below.
- Every plan contains a "Constitution Check"; any violation must be justified there or removed.
- Runtime guidance for AI assistants lives in `CLAUDE.md`.

**Version**: 1.1.0 | **Ratified**: 2026-11-16 | **Last Amended**: 2026-11-16

### Amendment log
- **1.1.0 (2026-11-16)**: VII: the five-minute setup limit excludes the one-time image download.
  *Reason*: the author chose self-hosted Langfuse for enterprise-grade observability, and its
  images cannot be pulled reliably within five minutes on a cold machine. App setup itself
  stays under five minutes. *Approved by*: author.
