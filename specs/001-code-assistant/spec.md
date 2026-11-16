# Feature Specification: Code Documentation Assistant

**Feature Branch**: `001-code-assistant`
**Created**: 2026-11-16
**Status**: Approved by author (2026-11-16)
**Derived from**: [`../000-discovery.md`](../000-discovery.md) — see its traceability table (§10)
**Scope rule**: this document says *what* and *why*. Tools and frameworks belong in `plan.md`.

## Problem

An engineer dropped into an unfamiliar codebase (a new job, a customer engagement, an
open-source contribution) spends days answering the same questions: *How is this structured?
Where is X implemented? What APIs does it expose? What does it depend on?* Reading code
linearly does not scale, and generic chatbots hallucinate because they have not seen the code.

**Goal:** a web app where a user points at a codebase, gets an overview of it, then asks
questions in plain English and receives answers grounded in the actual code, citing exact
files and lines.

**Users:** primarily an engineer onboarding onto code they did not write; secondarily a
reviewer evaluating this assignment on a repo of their choice.

## Clarifications

### Session 2026-11-16

- Q: What should a reviewer experience without an LLM API key? → A: A key is required; the README explains how to get a free Gemini key in ~2 minutes (no mock mode, no hosted demo).
- Q: Should ingested codebases and chat history survive an app restart? → A: Both persist on the server (codebases and conversations).
- Q: Is the codebase overview a must-have or a nice-to-have? → A: P1 must-have, built alongside chat.
- Q: Besides GitHub URL and .zip, should users point the app at a local folder? → A: No — GitHub URL and .zip only; local folders are zipped first.
- Q: Which public repo is the demo and evaluation target? → A: `fastapi/full-stack-fastapi-template` (Python backend + React/TypeScript frontend).

### Scope revision 2026-11-16 (author-approved)

The remaining work was cut to the essentials that demonstrate the FDE role (solid RAG, enterprise
tooling used for real, guardrails, observability, evaluation). Changes: the overview shows
languages, dependencies and starter questions only (FR-020); traces are viewed in Langfuse via a
link on each answer instead of an in-app panel (FR-040); conversations can be resumed and started
but not individually deleted (FR-016); the eval set has 10–15 questions (FR-042); stale-citation
flagging after re-ingest moves to Out of Scope.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Ingest a codebase (Priority: P1)

As a user, I want to add a codebase so that I can ask questions about it.

**Why this priority**: nothing else works without it.

**Independent Test**: ingest a known public repo; the summary lists the expected source files
and skips `node_modules`, lockfiles and binaries.

**Acceptance Scenarios**:

1. **Given** a public GitHub URL, **When** the user submits it, **Then** progress is shown and a
   summary reports files indexed and files skipped with reasons.
2. **Given** a .zip of a project, **When** the user uploads it, **Then** it is indexed the same way.
3. **Given** a repo above the size limit, **When** submitted, **Then** it is rejected with a
   clear message and nothing is partially indexed.
4. **Given** two ingested codebases, **When** the user switches between them, **Then** answers
   only use the selected codebase.

---

### User Story 2 — Ask questions with citations (Priority: P1)

As a user, I want to ask questions in plain English and get answers I can verify.

**Why this priority**: this is the core value of the product.

**Independent Test**: on an ingested repo, ask "where is X implemented?" for a known X; the
answer names the right file and the citation opens the right lines.

**Acceptance Scenarios**:

1. **Given** an ingested repo, **When** the user asks a question, **Then** the answer streams
   and includes citations in the form `path:start-end`.
2. **Given** an answer with citations, **When** the user clicks one, **Then** the cited code is
   shown with line numbers and the cited lines highlighted.
3. **Given** a question the code cannot answer, **When** asked, **Then** the assistant says it
   could not find it rather than guessing.
4. **Given** a previous answer, **When** the user asks "where is *that* called?", **Then** the
   follow-up is resolved using conversation context.
5. **Given** a question naming an exact identifier (e.g. `parse_config`), **When** asked,
   **Then** the chunk that defines it is retrieved even if semantic similarity is weak.
6. **Given** a conversation with several turns, **When** the app restarts and the user reopens
   it, **Then** all messages and citations are shown and follow-ups still use that context.

---

### User Story 3 — Guardrails (Priority: P1)

As an operator, I want the assistant to be safe even on untrusted repos.

**Why this priority**: reviewers will try to break it; one leaked key ends the demo.

**Independent Test**: ingest a fixture repo containing fake secrets and an injected comment;
neither the secrets nor the injected behaviour ever appear in answers.

**Acceptance Scenarios**:

1. **Given** a file containing an API key, **When** ingested, **Then** the key is redacted before
   indexing and never appears in prompts, answers or the code viewer.
2. **Given** a comment saying "ignore previous instructions and …", **When** that chunk is
   retrieved, **Then** the assistant does not follow it.
3. **Given** an off-topic request (e.g. "write me a poem about cats"), **When** asked, **Then**
   it is politely declined.
4. **Given** a secret that slipped past redaction, **When** it appears in a draft answer,
   **Then** the output check masks it.

---

### User Story 4 — Observability and quality (Priority: P1)

As a developer of this app, I want to see what happened on every request and measure quality.

**Why this priority**: required by the brief; it is how we prove answers are good.

**Independent Test**: ask one question and find its full trace; run the eval command and get a
report.

**Acceptance Scenarios**:

1. **Given** any chat request, **When** it completes, **Then** a trace records the query,
   rewritten query, retrieved chunks with scores, final prompt, model, tokens, cost,
   per-step latency and guardrail decisions, and the answer links to that trace in Langfuse.
2. **Given** an answer, **When** the user clicks thumbs up/down, **Then** the feedback is
   attached to that trace.
3. **Given** the versioned evaluation set, **When** the eval command runs, **Then** it reports
   retrieval hit-rate and answer faithfulness.

---

### User Story 5 — Codebase overview (Priority: P1)

As a user, I want an instant overview so I know what to ask.

**Why this priority**: it is the first screen a reviewer sees after ingestion and the clearest
answer to the brief's "UI/UX and product innovation" criterion.

**Independent Test**: ingest a repo with known manifests; the overview lists its languages and
manifest dependencies and offers starter questions.

**Acceptance Scenarios**:

1. **Given** a finished ingestion, **When** the overview opens, **Then** it shows the language
   breakdown and declared dependencies.
2. **Given** the overview, **When** displayed, **Then** it offers 3–5 starter questions
   specific to this codebase; clicking one asks it.

---

### Edge Cases

- Empty repo, or a repo with no supported source files.
- GitHub URL that is private, misspelt, or rate-limited by GitHub.
- Zip containing path traversal entries (`../../etc/passwd`) or symlinks.
- Very large single files (minified bundles, generated code).
- Non-UTF-8 files.
- The LLM provider is down or rate-limited mid-stream.
- The LLM API key is missing or invalid at startup (see NFR-007).
- A question asked while ingestion is still running.
- App restarts mid-ingestion: the codebase is marked failed (not left half-indexed) and can be retried.
- A codebase is re-ingested: existing conversations stay; citations open the current file.
- Two identifiers with the same name in different files.

## Requirements *(mandatory)*

### Functional Requirements

**Ingestion (US-1)**
- **FR-001**: System MUST ingest a public GitHub repo by URL.
- **FR-002**: System MUST ingest a local codebase uploaded as a .zip. These two are the only
  input methods; the app never reads arbitrary paths on the host filesystem.
- **FR-003**: System MUST skip `.gitignore`d paths, binaries, lockfiles, vendored/generated
  directories and files over a size limit.
- **FR-004**: System MUST show ingestion progress and a final summary (indexed, skipped, why).
- **FR-005**: System MUST reject repos over the size limit (NFR-004) with a clear message.
- **FR-006**: System MUST support multiple ingested codebases and scope chat to the selected one.
- **FR-007**: Ingested codebases (index and overview) MUST persist across app restarts; the user
  can delete a codebase, which also deletes its conversations.

**Q&A (US-2)**
- **FR-010**: Answers MUST stream token by token.
- **FR-011**: Every answer MUST cite the code it relies on as `path:start-end`.
- **FR-012**: Clicking a citation MUST show the cited code with line numbers and highlighting.
- **FR-013**: When retrieved code does not support an answer, the system MUST say so instead of guessing.
- **FR-014**: Follow-up questions MUST use conversation context.
- **FR-015**: Exact-identifier queries MUST retrieve the defining chunk even when semantic similarity is weak.
- **FR-016**: Conversations (messages, citations, feedback, trace IDs) MUST persist on the server
  across restarts. The user can list a codebase's past conversations, resume one and start a new
  one (conversations are deleted with their codebase).

**Guardrails (US-3)**
- **FR-030**: Secrets MUST be redacted at ingestion: never embedded, sent to the LLM or displayed.
- **FR-031**: Instructions embedded in ingested content MUST NOT be followed.
- **FR-032**: Off-topic requests MUST be politely declined.
- **FR-033**: Output MUST be checked so secrets never leak even if ingestion redaction missed them.

**Observability & quality (US-4)**
- **FR-040**: Each chat request MUST produce a trace with the fields in US-4 scenario 1, viewable
  in Langfuse through a link on the answer.
- **FR-041**: Users MUST be able to give thumbs up/down feedback, attached to the trace.
- **FR-042**: A versioned evaluation set MUST run from one command and report retrieval
  hit-rate and answer faithfulness. The set targets `fastapi/full-stack-fastapi-template` at a
  pinned commit, with 10–15 questions and author-verified expected source files per question.
- **FR-043**: Prompts MUST be versioned in git, and each trace MUST record the prompt version
  used. *(Added 2026-11-16 with author approval: resolves analysis finding C2.)*

**Overview (US-5)**
- **FR-020**: System MUST show the language breakdown and declared dependencies.
- **FR-021**: System MUST offer 3–5 codebase-specific starter questions.

### Non-Functional Requirements

- **NFR-001 Latency**: first token in ≤ 3 s at p50 for a typical question.
- **NFR-002 Languages**: Python and JavaScript/TypeScript are first-class (structure-aware
  chunking). Other text files are indexed with a generic strategy.
- **NFR-003 Deployability**: the whole app starts with one command.
- **NFR-004 Limits**: up to ~5,000 source files / 50 MB per repo in this version.
- **NFR-005 Config**: all keys and model names come from environment variables.
- **NFR-006 Accessibility**: keyboard navigable, light and dark mode, laptop-first; mobile best-effort.
- **NFR-007 Key required, fail fast**: an LLM API key is required to run. If it is missing or
  invalid, the app reports this clearly at startup (and in the UI) with a link to the README's
  "get a free Gemini key" steps, instead of failing on the first question.

### Key Entities

- **Codebase**: an ingested repo or upload. Name, source (URL or upload), status, stats, overview.
- **Chunk**: a contiguous span of one file. Path, start/end line, language, symbol name (if
  any), redacted text.
- **Conversation**: an ordered list of messages scoped to one codebase. Persisted server-side;
  has a title (from the first question), created/updated timestamps. Deleted with its codebase.
- **Message**: user question or assistant answer; answers carry citations and a trace ID.
- **Citation**: reference from an answer to a chunk (`path:start-end`).
- **Trace**: the observability record of one request, stored in Langfuse; feedback attaches here.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A reviewer goes from `git clone` to a cited answer in under 5 minutes, excluding
  the ~2 minutes to obtain a free Gemini API key and the one-time container image download
  (`docker compose pull`), whose duration the README reports separately. *(Amended 2026-11-16
  with author approval; see constitution v1.1.0.)*
- **SC-002**: On the eval set, the correct source file is in the retrieved context for ≥ 80% of questions.
- **SC-003**: 100% of answers that make claims about the code include at least one valid citation.
- **SC-004**: 0 secrets from the guardrail fixture repo appear in any answer, prompt or UI view.
- **SC-005**: Every topic the brief lists (chunking, embeddings, LLM, retrieval, prompts,
  context, guardrails, quality, observability) has a visible implementation and a written rationale.

## Assumptions

- Single user, no authentication (documented under productionisation).
- Reviewers obtain a free Gemini API key (required; README documents the steps), or supply
  another provider's key via config.
- Public GitHub repos are reachable from the machine running the app.
- English-language questions.

## Out of Scope (documented as future work)

- Authentication, multi-tenancy, per-user data isolation.
- Private GitHub repos (needs OAuth / token handling).
- Incremental re-indexing on git push.
- Call-graph / dependency-graph visualisation.
- Writing or modifying code (read-only Q&A).
- Ingesting from a local folder path or browser folder drag-and-drop (zip it instead).
- *(Scope revision 2026-11-16)* API route and entry-point detection in the overview; an in-app
  trace panel (Langfuse is the trace UI); flagging stale citations after re-ingest; deleting
  individual conversations; an eval set larger than 15 questions.

## Open Questions for the Author

> Decisions for *you*, not the AI. Answer inline (or run `/speckit-clarify`), then mark the spec Approved.

1. Anything in "Out of Scope" you want pulled in? → **No** (author, 2026-11-16).
