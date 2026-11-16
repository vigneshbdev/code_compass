# Contract: Evaluation dataset and `make eval` (FR-042, SC-002, SC-003)

## Dataset file

Path: `eval/datasets/<name>-v<N>.yaml`. Versioned in git. Any change to questions or
expected answers creates a new version file, and old reports stay comparable to their version.

```yaml
name: fastapi-template
version: 1
repo: https://github.com/fastapi/full-stack-fastapi-template
commit: <full 40-char SHA>          # pinned; ingestion uses this exact commit
k: 8                                # hit-rate is measured over the packed context
questions:
  - id: q01
    category: locate                # locate | explain | dependency | identifier | followup | not_found | offtopic
    question: Where is the User database model defined?
    expected_files: [backend/app/models.py]     # author-verified; ANY match = hit
    notes: optional free text
  - id: q07
    category: followup
    history:                        # prior turns replayed before the question (FR-014)
      - "How are passwords hashed?"
    question: Where is that function called?
    expected_files: [backend/app/crud.py]
  - id: q15
    category: not_found
    question: How does the app integrate with Kafka?
    expected_files: []              # expect the "couldn't find" answer (FR-013)
  - id: q18
    category: offtopic
    question: Write me a poem about cats
    expected_files: []              # expect status "declined" (FR-032)
```

Rules: 10–15 questions (scope revision 2026-11-16); at least 2 `identifier`, and at least 1 each
of `followup`, `not_found` and `offtopic`. `expected_files` paths are validated against the pinned commit when the
dataset loads (a typo fails the run instead of skewing the score).

## Command

```bash
make eval                                   # default dataset
make eval DATASET=eval/datasets/fastapi-template-v1.yaml
# equivalent: docker compose --profile eval run --rm eval python -m codecompass.eval <dataset>
# (the `eval` image is the app image plus RAGAS; it is never started by `docker compose up`)
```

Needs a working LLM key and the compose stack (Postgres, Langfuse). It ingests the pinned
commit if that codebase isn't already ingested.

## Langfuse dataset

The YAML file is the source of truth. Each run upserts its items into a Langfuse Dataset
named `<name>-v<N>` (item ID `<name>-v<N>-<question id>`, expected output = `expected_files`,
metadata = category). Each question's chat trace receives the scores `eval_retrieval_hit`,
`eval_valid_citations` and `eval_faithfulness`, with the comment `eval run <UTC timestamp>`, so
runs can be compared by filtering scores in the Langfuse UI.

*As built (2026-11-16):* Langfuse SDK v5 replaced linked dataset runs with an experiment runner
that owns tracing. Eval therefore runs the app's own chat pipeline, then records scores on its
traces. Langfuse sync fails open; the local report is the source of truth.

The dataset refuses to load while any `# UNVERIFIED` marker remains (author task T148).
`--allow-unverified` permits a dry run, and the report name is then marked `-UNVERIFIED`.

## Report

Written to `eval/reports/<name>-v<N>-<UTC timestamp>.json` and `.md`, summarised on stdout,
and recorded in Langfuse as above.

| Metric | Definition | Target |
|---|---|---|
| `retrieval_hit_rate` | share of answerable questions where ≥ 1 expected file is in the packed context (custom) | ≥ 0.80 (SC-002) |
| `citation_validity` | share of claim-making answers (status `complete` or `unverified`) that contain ≥ 1 valid citation, so every `unverified` answer counts as a miss (custom) | 1.00 (SC-003) |
| `faithfulness` | RAGAS faithfulness (judge = `LLM_JUDGE_MODEL`) | reported; baseline tracked |
| `context_precision`, `context_recall` | file-level precision and recall of retrieved files against `expected_files`, computed in `eval/metrics.py` with no LLM (RAGAS's ID-based classes are private in RAGAS 0.4) | reported |
| `not_found_accuracy` | share of `not_found` questions answered with status `not_found` | reported |
| `offtopic_accuracy` | share of `offtopic` questions answered with status `declined` | reported |
| `latency_first_token_p50_ms` | over answerable questions only (declined and pre-check not-found answers skip the LLM) | ≤ 3000 (NFR-001) |
| `errors` | questions whose answer failed | 0 |

Per-question rows include the trace ID, so any miss can be opened in Langfuse. Exit code is `0`
regardless of score (it is a report, not a gate). `--fail-under 0.8` gates on retrieval hit-rate
for CI. Exit code `2` means the run could not start (dataset error or no working LLM key).
