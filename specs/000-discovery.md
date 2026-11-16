# 000 — Discovery: reading the brief like a customer engagement

**Status:** Draft — awaiting author review
**Input:** "Assignment – AI FDE" brief + recruiter email (5 Nov).
**Why this document exists:** an FDE does not start by building. They start by understanding
who the customer is, what "done" means to them, and what they did *not* say. Everything in
`spec.md` must trace back to something here.

---

## 1. The engagement in one paragraph

The customer (NewPage hiring team) wants a working, containerised, conversational AI assistant
built on retrieval over documents, plus a written account of the engineering reasoning behind
it. The software is the vehicle; the real deliverable is **evidence of judgement**: how
trade-offs are made under constraints, and whether the builder can explain them in their own voice.

## 2. Stakeholders and what each one needs

| Stakeholder | Role | What they need from the deliverable | How they will consume it |
|---|---|---|---|
| Recruiter | Gatekeeper | On-time, complete submission (repo + README + screenshots) | Checks the link works and the list is complete |
| Engineering reviewer(s) | Primary evaluator | Clean code, sound RAG decisions, tests, Docker, observability | Clones the repo, runs `docker compose up`, tries their own questions, reads code |
| Hiring manager | Decision maker | Evidence this person can be put in front of a client and deliver | Reads the README top section, watches the video, looks at the UI |
| Future interview panel | Follow-up | Material to probe in a technical discussion | Uses the README's decisions as talking points |

**Implication:** the README is read by more people than the code. The first screen of the
README and the first 30 seconds of the app matter most.

## 3. Requirements extracted from the brief

### 3a. Explicit (stated in the brief)

| ID | Requirement | Source line in brief |
|---|---|---|
| B-01 | Fullstack web app, any stack | "Build a fullstack web application" |
| B-02 | Conversational assistant over a corpus using RAG or similar | "Core Functionality" |
| B-03 | Simple interface for upload/provide + ask | "Core Functionality" |
| B-04 | Well-designed UI, product creativity | "Creativity" |
| B-05 | Reasoned approach to chunking, embeddings, LLM, retrieval, prompts, context, guardrails, quality, observability | "Your approach and thought process" |
| B-06 | Clean, readable, well-structured code | "Engineering excellence" |
| B-07 | Containerised, tested, observable | "Engineering excellence" |
| B-08 | GitHub repo | "What to Submit" |
| B-09 | README: setup, architecture, productionisation on a hyperscaler, RAG/LLM decisions, key decisions, standards followed/skipped, AI-tool usage, what you'd do with more time | "What to Submit" |
| B-10 | Screenshots; video if time permits | "What to Submit" |
| B-11 | Explain AI-assisted dev approach: keeping output to your standards, repeatability, do's & don'ts | "AI-assisted development approach" |

### 3b. Implicit (not stated, but clearly expected)

| ID | Implicit requirement | Why we believe it |
|---|---|---|
| I-01 | **README in the author's own voice** | Said three times ("your thoughts, not an LLM's output") — the strongest signal in the brief |
| I-02 | Runs first time on a reviewer's machine | Reviewers will clone and run; a failed setup ends the evaluation |
| I-03 | Works on input *the reviewer* chooses, not just a curated demo | "Answer questions based on uploaded/provided documents" |
| I-04 | Honest about limits | "Acknowledge [edge cases] in your README" |
| I-05 | Scope discipline is itself graded | "Solid basic solution A LOT MORE than over-engineered" — said twice |
| I-06 | Cost to run is low | Reviewer pays nothing / uses their own key; must work with a free-tier key |

### 3c. Anti-requirements (things that would *hurt*)

- Over-engineering: microservices, k8s, agents for the sake of agents.
- Generic LLM-written README prose.
- A demo that only works on the author's sample data.
- Features that are half-finished. Cut them and list them in "next steps" instead.

## 4. Success criteria (how we'll know we've won)

1. A reviewer goes from `git clone` to a cited answer in **under 5 minutes**.
2. On a repo of the reviewer's choice, answers are **correct and cited** for typical onboarding questions.
3. Each topic in B-05 has a **visible implementation** *and* a short written rationale.
4. The README can be skimmed in 2 minutes and survives a 45-minute deep-dive interview.
5. Nothing in the repo is unexplained or unused.

## 5. Option assessment (customer lens)

Scored against what *this customer* values, not what is most fun to build.
1 = weak, 3 = strong.

| Criterion (weight) | 1. Docs | 2. Code | 3. Meetings | 4. Career |
|---|---|---|---|---|
| Relevance to the FDE role (×3) | 1 | **3** | 2 | 1 |
| Room to show B-05 depth (×3) | 2 | **3** | 2 | 2 |
| Reviewer can test with own input, I-03 (×2) | 2 | **3** — any public repo | 1 — needs transcripts | 2 |
| UI/product creativity potential (×2) | 1 | 2 | 2 | **3** |
| Guardrails story (×1) | 1 | **3** — secrets, injection | 2 | 3 — PII |
| Delivery risk, inverse (×2) | **3** | 2 | 2 | 3 |
| **Weighted total** | 22 | **35** | 24 | 28 |

**Decision:** Option 2 — Code Documentation Assistant.
**Main risk accepted:** code chunking is harder and reviewers will test on real repos.
**Mitigation:** first-class support for Python and JS/TS only, generic fallback for the rest,
and say so up front (I-04).

> Author: adjust weights/scores if you disagree. This table is your reasoning, not the AI's.

## 6. Constraints

- **Time:** one working session (~4 h stated as acceptable). Scope must fit; the rest goes to "next steps".
- **LLM provider:** Google Gemini key available. Must stay provider-agnostic (swap by config).
- **Budget:** free tier where possible; no paid managed services required to run it.
- **Author's existing expertise:** LangChain, Langfuse, NeMo Guardrails, LiteLLM — use where they
  fit genuinely, not to tick boxes.

## 7. Assumptions (to validate)

| # | Assumption | Risk if wrong | How to validate |
|---|---|---|---|
| A1 | Public GitHub repo URL is an acceptable way to "provide" code | Low | Brief explicitly says "GitHub repo or local files" |
| A2 | Reviewers will supply their own Gemini key, or we document how to get a free one | Medium — setup friction | Ask recruiter; document clearly; consider a mock/demo mode |
| A3 | Single-user, no auth is acceptable | Low | Brief doesn't mention users; document in productionisation |
| A4 | A video is a nice-to-have, not required | Low | Brief: "if time permits" |

## 8. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Reviewer's setup fails (Docker, keys) | Med | **High** | One-command start, `.env.example`, health check, tested on clean machine |
| Gemini free-tier rate limits during review | Med | Med | Retries with backoff via the LLM gateway; small context; document limits |
| Large repo makes ingestion slow | Med | Med | File/size limits, skip vendored dirs, progress UI |
| Poor answers on reviewer's repo | Med | **High** | Hybrid retrieval, eval set, honest "not found" behaviour |
| Over-scoping, nothing finished | Med | **High** | P1/P2 priorities in spec; cut P2 first |

## 9. Clarifying questions for the customer

A real FDE would send these before building. Optional to send — the brief allows assumptions
if they are documented.

1. Will reviewers run it locally with their own LLM key, or would you prefer a hosted demo link?
2. Is there a preferred way to share the repo (public, or private with specific reviewers)?

## 10. Traceability

Brief requirement → spec requirement → where it is delivered. Filled in as the spec and plan firm up.

| Brief | Spec | Delivered in |
|---|---|---|
| B-02, B-03, I-03 | FR-001…006, FR-010…015 | ingestion + chat |
| B-04 | FR-012, FR-020, FR-021, NFR-006 | UI |
| B-05 | FR-013, FR-015, FR-030…033, FR-040…042 | plan.md decisions + code |
| B-07, I-02 | NFR-003, Constitution VII | docker-compose, tests |
| B-09, I-01, I-04 | — | README (author-written sections) |
| B-11 | Constitution I, `CLAUDE.md` | README + repo process |
