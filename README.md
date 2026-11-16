# CodeCompass

Point CodeCompass at a public GitHub repository or a `.zip` of a project. It indexes the code,
then answers questions in plain English with citations to exact files and lines
(`path:start-end`). Click a citation to see the code with those lines highlighted.

<!-- DRAFT built from the project records (discovery, research, plan, this run). Rewrite in your own words before submitting. -->
I built CodeCompass for the NewPage AI FDE assignment. Of the four options, I chose the code
documentation assistant because it is closest to forward-deployed work (landing in a codebase you
did not write and needing answers quickly), and because reviewers can test it on any public
repository, not only on my sample data. It is for developers onboarding onto an unfamiliar codebase.

## Demo video

[![CodeCompass demo video (4:55): click to play](docs/screenshots/video-thumbnail.png)](https://drive.google.com/file/d/1n3T3b8rU6pva8Dl7vCGnu4GN_pIcLd2T/view?usp=sharing)

▶ **[Watch the demo on Google Drive (4 min 55 s)](https://drive.google.com/file/d/1n3T3b8rU6pva8Dl7vCGnu4GN_pIcLd2T/view?usp=sharing)**: the running stack, cited answers and
follow-ups on the indexed demo repository, guardrails declining off-topic questions, Langfuse
traces, and the pgvector data in pgAdmin. A copy is in the repository at
[`docs/videos/codecompass-demo.mp4`](docs/videos/codecompass-demo.mp4).

## Screenshots

All taken from the running app on the demo repository (`fastapi/full-stack-fastapi-template`).

| | |
|---|---|
| **Add a codebase**: public GitHub URL or `.zip` upload<br>![Add a codebase](docs/screenshots/06-add-codebase.png) | **Overview**: languages, dependencies, files indexed and skipped by reason, starter questions<br>![Overview](docs/screenshots/01-overview.png) |
| **Cited answer**: streamed answer with `path:start-end` citations<br>![Cited answer](docs/screenshots/02-answer.png) | **Code viewer**: clicking a citation highlights the cited lines<br>![Code viewer](docs/screenshots/03-viewer.png) |
| **Guardrails**: a prompt-injection attempt declined before any answer-model call<br>![Guardrails](docs/screenshots/04-guardrails.png) | **Langfuse trace**: one trace per question with retrieval steps, tokens, latency and citation scores<br>![Langfuse trace](docs/screenshots/05-langfuse-trace.png) |

## Submission contents

| Brief asks for | Where |
|---|---|
| Working, containerised app | `docker compose up` ([Quick start](#quick-start)) |
| Architecture and RAG/LLM decisions | [Architecture](#architecture), [`specs/001-code-assistant/research.md`](specs/001-code-assistant/research.md) |
| Productionisation on a hyperscaler | [Taking it to production](#taking-it-to-production-on-a-hyperscaler) |
| Tests and quality | [Tests and evaluation](#tests-and-evaluation) |
| Edge cases and limits | [Known limitations](#known-limitations) |
| AI-assisted development approach | [How this was built](#how-this-was-built) |
| Screenshots and video | [Screenshots](#screenshots), [Demo video](#demo-video) |

---

## Quick start

Prerequisites: Docker with Compose v2, and a Gemini API key (free, see below). The key is used for
chat only: embeddings run locally in the `ollama` service, which downloads the `nomic-embed-text`
model (about 275 MB) on first start.

```bash
git clone <this-repo> && cd codecompass
make init-env                 # creates .env with generated local secrets
# edit .env and set GEMINI_API_KEY=...
make pull                     # one-time image download (timed separately, see below)
docker compose up --build     # app, Postgres + pgvector, Ollama, self-hosted Langfuse
```

- App: <http://localhost:8000>
- Langfuse (traces, prompts, eval scores): <http://localhost:3000>. Log in with
  `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_PASSWORD` from `.env`.

Measured on the author's machine:

| Step | Time |
|---|---|
| Indexing the demo repo (236 files, 1,150 chunks; local CPU embeddings, 4-core laptop) | 17 min |
| First token of an answer (3 sample questions) | about 6 s |

Cold-start times (first image download and first build) were not measured on a clean machine.

### Get a free Gemini key

1. Open <https://aistudio.google.com/apikey> and sign in with a Google account.
2. Click **Create API key** and copy it.
3. Put it in `.env` as `GEMINI_API_KEY=...` and restart with `docker compose up -d app`.

Any provider LiteLLM supports works: set its key and change `LLM_MODEL`, `LLM_FAST_MODEL`,
`LLM_JUDGE_MODEL` and `EMBEDDING_MODEL` in `.env`. The default models are listed in
[Configuration](#configuration).

---

## What it does

| Capability | How |
|---|---|
| Ingest a public GitHub repo or a `.zip` | Tarball download with size caps; safe extraction (no `../` paths, symlinks or zip bombs); `.gitignore`, lockfiles, binaries and oversized files skipped, each with a reason |
| Never store or show secrets | `detect-secrets` redaction **before** anything is stored or embedded; the code viewer shows `[REDACTED:<type>]` |
| Structure-aware chunking | tree-sitter for Python, JavaScript and TypeScript (functions, classes, methods with class context); headings and line windows for other files |
| Hybrid retrieval | pgvector similarity + Postgres full-text search + exact function/class-name lookup, merged with Reciprocal Rank Fusion; exact symbol hits are pinned first |
| Grounded answers | Streaming answers that cite `path:start-end`; citations validated against what was retrieved; "I couldn't find this in the codebase." when retrieval has nothing; answers without a valid citation are labelled **Unverified** |
| Follow-ups | Follow-up questions are rewritten into standalone questions using the conversation; conversations are saved |
| Guardrails | NeMo Guardrails input rail (off-topic requests, jailbreak attempts), injection defence (instruction-like text in code is marked untrusted), output rail that masks secrets in streamed answers, secret masking on everything exported to Langfuse |
| Observability | One Langfuse trace per question: retrieval scores, prompt and prompt version, model, tokens, cost, per-step latency, guardrail decisions. Each answer links to its trace. 👍/👎 feedback becomes a Langfuse score |
| Evaluation | `make eval`: retrieval hit-rate, citation validity, RAGAS faithfulness, not-found and off-topic accuracy, first-token latency on a versioned question set |
| Overview | Language breakdown, declared dependencies, and 3–5 starter questions per codebase |

## Architecture

```text
Browser (React + TypeScript SPA)
   │ REST + Server-Sent Events
   ▼
app container: FastAPI, one process ──────────────────────────────────────────────────────┐
   ingestion: GitHub/zip → filter → redact (detect-secrets) → chunk (tree-sitter) → embed │
   chat:      NeMo input rail → rewrite follow-up → hybrid retrieval → answer stream     │
              (LangChain LCEL + LiteLLM) → NeMo output rail → citation validation        │
   overview:  languages, dependencies, starter questions                                 │
        │                     │                      │                     │               │
        ▼                     ▼                      ▼                     ▼               │
Postgres 16 + pgvector   Chat LLM via LiteLLM   Embeddings via LiteLLM   Langfuse v4       │
(chunks, vectors,        (Gemini by default)    (Ollama, local CPU:      (self-hosted:     │
 full-text, chats)                               nomic-embed-text)        web, worker,     │
                                                                          ClickHouse,      │
                                                                          Redis, MinIO)    │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

**How a question is answered**

1. The NeMo input rail checks the question, with recent questions as context.
2. A fast model rewrites a follow-up into a standalone question. Identifiers are also extracted
   with regular expressions, so exact-name lookup never depends on the LLM.
3. Three retrievers run in parallel on the selected codebase: vector, full-text and symbol.
   Their results are merged with Reciprocal Rank Fusion and packed into a token budget.
4. If nothing relevant is found, the fixed "couldn't find" answer is returned without an LLM call.
5. The answer streams from the main model. Each line passes the NeMo output rail before it
   reaches the browser.
6. Citations are checked against the retrieved chunks. Message, citations, usage and trace ID
   are saved.

**How a codebase is indexed**

| Stage | What happens |
|---|---|
| Download | GitHub tarball streamed with a byte cap, or a `.zip` upload; extraction rejects `../` paths, symlinks and zip bombs |
| Filter | `.gitignore` rules, lockfiles, binaries, vendored directories and oversized files are skipped, each with a recorded reason |
| Redact | `detect-secrets` replaces secrets with `[REDACTED:<type>]` before anything is stored, embedded or shown |
| Chunk | tree-sitter splits Python, JavaScript and TypeScript into functions, classes and methods with exact line ranges; other files split by headings or line windows |
| Embed | batches of chunks are embedded through LiteLLM (local Ollama by default) |
| Overview | languages, declared dependencies and starter questions are generated |
| Finalize | the new index becomes active in one transaction; the previous one is kept until then, so a failed re-index never breaks a working codebase |

Ingestion runs as an in-process background task and reports progress by stage, which the UI polls.

**Data model** (Postgres): `codebase` → `ingestion` (one per indexing run; records the embedding
model and dimension) → `file` and `chunk` (text, line range, symbol, `vector(768)` embedding,
generated `tsvector` for full-text search). Chat data is `conversation` → `message` → `citation`,
where each citation points at the chunk it came from.

**Design decisions** (recorded with alternatives in
[`research.md`](specs/001-code-assistant/research.md)):

| Topic | Decision | Ref |
|---|---|---|
| Shape | One app container (API, background ingestion, built SPA) plus platform services in Compose | R1 |
| Provider access | LiteLLM behind LangChain interfaces; every model comes from one `ModelFactory`, so changing provider is a config change | R3 |
| Chunking | Structure-aware with tree-sitter, so chunks are whole functions or classes with exact lines | R4 |
| Storage | One Postgres with pgvector and full-text search, instead of a separate vector database | R5 |
| Retrieval | Hybrid: vector + full-text + exact symbol lookup, fused with Reciprocal Rank Fusion; symbol hits pinned first | R6 |
| Grounding | Citations validated against the retrieved chunks; fixed "couldn't find" answer when retrieval is empty; otherwise **Unverified** | R7 |
| Guardrails | Secrets redacted at ingestion; NeMo input rail; code comments treated as untrusted data; streamed output filtered line by line | R9 |
| Observability | Self-hosted Langfuse: one trace per question, prompt versions, feedback scores | R10 |
| Evaluation | Versioned question set; custom retrieval and citation metrics plus RAGAS faithfulness | R11 |
| Ingestion execution | In-process async task with atomic switch-over, instead of a separate queue and worker | R14 |

### Why these choices

<!-- DRAFT built from the project records (discovery, research, plan, this run). Rewrite in your own words before submitting. -->

- **Chunking.** Citations are only useful if they point at exact lines, so chunks had to keep
  their line spans. LangChain's code splitters do not, so I parse with tree-sitter and still emit
  LangChain `Document`s. Python, JavaScript and TypeScript get structure-aware chunks; everything
  else falls back to headings or line windows. I accepted that trade-off and say so up front.
- **Embeddings.** I started with Gemini embeddings. During the end-to-end run the free-tier quota
  ran out mid-ingestion, so I moved embeddings to a local Ollama model (`nomic-embed-text`,
  768 dimensions, so no migration was needed). On a laptop CPU that was too slow at full length,
  so chunks are embedded from their first 512 tokens; full-text and symbol search still see the
  whole chunk. The model is one config value, so a hosted model can come back without code changes.
- **Retrieval.** Code questions mix meaning ("how does login work?") with exact names
  (`get_password_hash`). Vector search alone misses the names, so retrieval is hybrid: vector,
  full-text and symbol lookup, fused with Reciprocal Rank Fusion. The fusion is about 20 lines of
  our own code because LangChain moved `EnsembleRetriever` to its legacy package. A reranker is
  left as an option for when eval hit-rate falls below 80%, to protect latency.
- **Storage.** One Postgres with pgvector: vectors, the full-text index and metadata change in one
  transaction, which is what makes the atomic re-index switch-over simple. One less service for a
  reviewer to run.
- **Prompts and grounding.** The rule is "grounded answers or no answer". If retrieval finds
  nothing, the app returns a fixed "couldn't find" answer without calling the model. Every citation
  is checked against the retrieved chunks, and an answer without a valid one is marked Unverified.
- **Guardrails.** Secrets are the main risk in code, so they are redacted at ingestion, before
  storage or embedding. NeMo Guardrails handles off-topic and jailbreak attempts, and comments in
  code are treated as untrusted data. PII rails (Presidio) were left out because the spaCy model
  makes the image heavier and secrets are the stated risk.
- **Observability and quality.** Langfuse instead of a local trace table, because it brings
  datasets, prompt versioning and experiment comparison as well as traces. RAGAS is used for
  faithfulness but kept in a separate eval image, because it roughly doubles the app image.
- **LLM access.** LiteLLM behind one `ModelFactory`, for provider portability and retries with
  backoff on free-tier limits. This paid off during the run: switching chat models and moving
  embeddings to Ollama were configuration changes.

## Main technology

| Area | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async) + Alembic, Pydantic settings |
| LLM access | LiteLLM behind LangChain interfaces (one `ModelFactory`; provider set by config) |
| Embeddings | Ollama running `nomic-embed-text` (768 dimensions) locally, reached through LiteLLM like any other provider |
| Orchestration | LangChain (LCEL, retrievers, prompt templates) |
| Guardrails | NeMo Guardrails + `detect-secrets` |
| Storage | Postgres 16 + pgvector, generated `tsvector` full-text index |
| Observability | Langfuse v4 (self-hosted): traces, sessions, prompt versions, scores, datasets |
| Evaluation | Custom retrieval and citation metrics + RAGAS faithfulness |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, TanStack Query |
| Packaging | Docker Compose; one app image (RAGAS lives in a separate eval image) plus Postgres, Ollama and the Langfuse stack |

## Configuration

All settings come from `.env`. [`.env.example`](.env.example) lists every one with a comment.
The most important:

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | (empty) | Provider key read by LiteLLM |
| `LLM_MODEL` / `LLM_FAST_MODEL` / `LLM_JUDGE_MODEL` | `gemini/gemini-3.1-flash-lite` / `gemini/gemini-3.1-flash-lite` / `gemini/gemini-3.5-flash` | Answers / rewrite, guardrail check, starter questions / eval judge. Gemini 3.6+ and 3.5-flash-lite reject `temperature` and do not work yet |
| `EMBEDDING_MODEL`, `EMBEDDING_DIM` | `ollama/nomic-embed-512`, 768 | Embeddings, run locally (`nomic-embed-text` reading the first 512 tokens) by the compose `ollama` service so ingestion uses no API quota (CPU only, so slower). Changing the model marks codebases "re-ingest required" |
| `MAX_FILES`, `MAX_INDEX_BYTES` | 5000, 50 MB | Per-repository limits |
| `RETRIEVAL_TOP_K`, `CONTEXT_MAX_CHUNKS`, `CONTEXT_MAX_TOKENS` | 20, 8, 6000 | Retrieval breadth and context budget |
| `RETRIEVAL_MIN_SCORE` | 0.35 | Below this similarity (with no keyword or name match), answer "couldn't find" |
| `LANGFUSE_ENABLED` | true | Tracing; the app keeps working if Langfuse is down |

## Tests and evaluation

```bash
make test     # backend: unit + integration on a real Postgres (testcontainers), no API key needed
              # frontend: Vitest + Testing Library
make lint     # ruff, mypy --strict, eslint, tsc
make eval     # needs GEMINI_API_KEY and the running stack
```

Tests are named after the requirement they prove (for example `test_fr015_symbol_hit_is_pinned_first_despite_unrelated_vector_scores`). They use a
scripted fake model, so they run offline. One test, `test_sc004_no_planted_secret_reaches_any_output`,
ingests a repository full of fake secrets with a model that tries to echo them, and checks that no
secret reaches the browser, the database, the prompts, the code viewer or Langfuse.

**Eval results:** not run yet. The question set's expected files still need to be checked against
the pinned commit before the numbers mean anything. The targets are:

| Metric | Target |
|---|---|
| Retrieval hit-rate | ≥ 0.80 |
| Citation validity | 1.00 |
| RAGAS faithfulness | tracked |
| First-token latency p50 | ≤ 3 s (about 6 s observed, see [Known limitations](#known-limitations)) |

The question set is [`eval/datasets/fastapi-template-v1.yaml`](eval/datasets/fastapi-template-v1.yaml):
12 questions on `fastapi/full-stack-fastapi-template` at a pinned commit.

## Project layout

```text
backend/src/codecompass/
  api/            HTTP endpoints (codebases, conversations, streaming chat, feedback, health)
  ingestion/      sources (GitHub, zip), file filters, pipeline
  chunking/       tree-sitter and generic chunkers
  retrieval/      vector, full-text and symbol retrievers; fusion and packing
  chat/           rewrite, prompts context, citations, the chat service
  guardrails/     NeMo config, rails, secret redaction, injection detection
  observability/  Langfuse client, prompt versioning, logging
  overview/       languages, dependencies, starter questions
  eval/           dataset, metrics, RAGAS, reports, `python -m codecompass.eval`
  prompts/        versioned prompt files (synced to Langfuse)
frontend/src/     React app
specs/            spec-driven development artifacts (discovery, spec, plan, tasks)
eval/             evaluation datasets and reports
```

## Known limitations

Measured or observed during the end-to-end run:

- **First-token latency is about 6 s**, above the 3 s target. Before the answer starts, the input
  guardrail check (1–3 s), the follow-up rewrite (about 1.5 s) and retrieval (about 0.7 s) run in
  sequence. Each step's latency is recorded in the Langfuse trace.
- **Indexing is slow on CPU.** Local embeddings took 17 minutes for the demo repository on a
  4-core laptop. To keep that practical, each chunk is embedded from its first 512 tokens
  (`nomic-embed-512`); full-text and symbol search still cover the whole chunk. Switching
  `EMBEDDING_MODEL` to a hosted model is faster, but free tiers cap daily embedding requests.
- **Newer Gemini models are not usable yet.** Gemini 3.6+ and 3.5-flash-lite reject the
  `temperature` parameter the app sends, so the defaults are `gemini-3.1-flash-lite` and
  `gemini-3.5-flash`.
- **The startup health check tests the embedding model only.** With local embeddings, a missing
  or invalid Gemini key is not reported at startup; it appears as an error on the first question.
- **Langfuse traces are incomplete.** A trace shows the rewrite (for follow-ups), retrieval and
  answer spans, but the input guardrail check does not appear as its own span, and the trace's
  input field is empty.
- **Grouped citations are not clickable.** When the model writes two citations in one bracket
  (`[a.py:1-5, b.py:9-12]`), they render as plain text instead of links.
- **A re-index does not resume.** Restarting the app during indexing marks the run as interrupted;
  it must be retried from the start. The previous index stays active until the new one finishes.

## Taking it to production on a hyperscaler

Factual mapping of each component; the trade-off discussion is the author's.

| Here | Production (example: Google Cloud; AWS/Azure equivalents in brackets) |
|---|---|
| `app` container | Cloud Run or GKE (ECS/EKS, Container Apps/AKS), autoscaled, behind a load balancer with TLS |
| In-process ingestion task | A queue plus workers: Cloud Tasks / Pub/Sub (SQS, Service Bus) |
| Postgres + pgvector container | Cloud SQL or AlloyDB for PostgreSQL with pgvector (RDS/Aurora, Azure Database for PostgreSQL) |
| Uploads on a Docker volume | Cloud Storage (S3, Blob Storage) |
| Self-hosted Langfuse | Langfuse Cloud, or Langfuse on Kubernetes with managed Postgres, ClickHouse and Redis |
| `.env` secrets | Secret Manager (Secrets Manager, Key Vault) |
| LiteLLM library | LiteLLM proxy as a central gateway: virtual keys, budgets, fallbacks, spend tracking |
| Ollama on CPU for embeddings | A managed embedding API (Vertex AI, Bedrock, Azure OpenAI) or Ollama on GPU nodes; ingestion workers embed in parallel |
| Single user, no auth | SSO (OIDC) and per-tenant data isolation |

**What I would change first**

<!-- DRAFT built from the project records (discovery, research, plan, this run). Rewrite in your own words before submitting. -->

1. **Ingestion out of the web process.** Move it to a queue with workers and use GPU or managed
   embeddings. Indexing the demo repository took 17 minutes on CPU, and an app restart currently
   loses an in-progress run.
2. **Authentication and tenant isolation.** Today it is single-user with no auth, which is fine for
   a review but not for customer code.
3. **A LiteLLM proxy as the gateway,** for per-team keys, budgets, model fallbacks and spend
   tracking, instead of a key in an environment file.
4. **Latency.** Run the input guardrail in parallel with rewrite and retrieval instead of before
   them, to bring the first token from about 6 s towards the 3 s target.

## Scope and future work

Built: everything in the "What it does" table. Deliberately left out, to keep the solution
focused:

- API-route and entry-point detection in the overview
- An in-app trace panel (Langfuse is the trace UI, linked from every answer)
- Flagging citations whose code changed after a re-ingest (the content hash is already stored)
- Deleting individual conversations (they are deleted with their codebase)
- Private repositories, authentication, multi-tenancy, incremental re-indexing
- A reranker, and an agent for multi-step questions

## How this was built

The project uses **spec-driven development with [GitHub Spec Kit](https://github.com/github/spec-kit)**.
Every feature goes through the same pipeline before code is written:

```text
discovery → specify → clarify → plan → tasks → analyze → implement
```

| Step | Artifact | Content |
|---|---|---|
| Discovery | [`specs/000-discovery.md`](specs/000-discovery.md) | The brief read as a customer engagement: stakeholders, explicit and implicit requirements, risks |
| Constitution | [`.specify/memory/constitution.md`](.specify/memory/constitution.md) | Seven non-negotiable principles (spec is the source of truth; simple over clever; grounded answers or no answer; safe by default; observable by default; provider-agnostic; tested and reproducible) and quality gates |
| Specify / clarify | [`spec.md`](specs/001-code-assistant/spec.md) | Five user stories with acceptance scenarios, numbered requirements (`FR-xxx`, `NFR-xxx`) and success criteria (`SC-xxx`) |
| Plan | [`plan.md`](specs/001-code-assistant/plan.md), [`research.md`](specs/001-code-assistant/research.md), [`data-model.md`](specs/001-code-assistant/data-model.md), [`contracts/`](specs/001-code-assistant/contracts/) | Architecture, a requirement-to-module map, every dependency with its reason, decisions with rejected alternatives, HTTP and eval contracts |
| Tasks | [`tasks.md`](specs/001-code-assistant/tasks.md) | Dependency-ordered tasks, each tied to requirement IDs, grouped by user story |
| Analyze | `/speckit-analyze` | Cross-checks spec, plan and tasks for gaps and contradictions before implementation |

**Rules and checks defined for the AI coding assistant**

- [`CLAUDE.md`](CLAUDE.md) sets the working rules: implement only tasks listed in `tasks.md`;
  propose a spec or plan change first if something is missing; never edit `spec.md` or the
  constitution without the author's approval; no new dependency without a reason in `plan.md`;
  no hard-coded keys, model names or URLs; one task per change.
- **Tests are named after requirements** (`test_fr002_safe_extract.py`,
  `test_sc004_no_planted_secret_reaches_any_output`), so each requirement can be traced to the
  test that proves it.
- **Independent spec review:** the workflow defines a `spec-reviewer` subagent
  ([`.claude/agents/spec-reviewer.md`](.claude/agents/spec-reviewer.md)) that re-reads the spec,
  runs the tests itself and returns `VERDICT: PASS | FAIL` with a requirement-by-requirement
  coverage list, as the gate for ticking a task.
- **Cross-model review:** the workflow also provides
  [`scripts/cross-review.py`](scripts/cross-review.py), which has a different model (Gemini)
  review code written by Claude ("no model grades its own homework").

**Where the process stands:** the foundation tasks (T001–T029) are ticked in
[`tasks.md`](specs/001-code-assistant/tasks.md) and committed together. The user-story code (T030 onward) is
implemented and was verified end to end on the demo repository (see [Screenshots](#screenshots)),
but has not yet been through the `spec-reviewer` and cross-review gates, so those tasks are still
unticked.

### How I used AI

<!-- DRAFT built from the project records (discovery, research, plan, this run). Rewrite in your own words before submitting. -->

I used Claude Code as the coding assistant, inside the Spec Kit workflow above. The AI drafted
the discovery notes, spec, plan and tasks; I reviewed them and made the calls that are recorded as
author decisions (for example, hand-rolled fusion instead of a legacy LangChain class, and keeping
RAGAS out of the app image).

How I kept the output to my standard:

- **Rules in the repo, not in my head.** `CLAUDE.md` and the constitution are checked in, so every
  session starts from the same rules: only tasks from `tasks.md`, no unexplained dependencies, no
  hard-coded keys or model names, and no editing the spec without my approval.
- **Tests tied to requirements,** so "done" means a named test passes, not that the AI says so.
- **Reviewers that are not the author:** a spec-reviewer subagent and a Gemini cross-review script.
  As noted above, the user-story tasks have not been through these gates yet.
- **Running the real app,** not just tests. The end-to-end run surfaced issues the tests did not:
  the configured Gemini models rejected the `temperature` parameter (the health check only tested
  embeddings, so it looked fine), and the embedding quota ran out. Each fix went through the rules:
  the Ollama dependency got its line in `plan.md` before it was added.

What makes it repeatable: the spec artifacts, `CLAUDE.md`, the reviewer agent and the Spec Kit
commands are all in the repository, so another engineer or another AI session can pick up from
`tasks.md`.

Do's and don'ts:

- Do write the spec and the rules first; the AI follows written rules far better than chat.
- Do make the AI run things and show real output instead of claiming success.
- Do run the actual product end to end; tests with fake models will not catch provider changes.
- Don't let the AI pick dependencies or change the spec on its own.
- Don't let the AI write the reasoning you will be judged on.

### With more time

<!-- DRAFT built from the project records (discovery, research, plan, this run). Rewrite in your own words before submitting. -->

- Put the user-story tasks through the spec-reviewer and cross-review gates, and commit them
  per task.
- Check the eval set against the pinned commit, run `make eval`, and calibrate
  `RETRIEVAL_MIN_SCORE` from the results.
- Stop sending `temperature` to models that reject it, so newer Gemini models work, and make the
  health check test the chat model too.
- Add the input guardrail as its own Langfuse span, record the trace input, and make grouped
  citations clickable.
- Cut first-token latency, and add a reranker if hit-rate is below target.
- Resumable re-indexing, and the optional upgrades in the plan: LiteLLM proxy, PII rails, and an
  agent for multi-step questions.
