# Model replies of the language-model runs

`llm_cache.sqlite` is a copy of the response cache (`.auditiq/llm_cache.sqlite`) as it stood on 13 November 2026:
1,012 replies of the local models to the requests of the pilot and sample runs (C2 to C5), the policy reading and
Ask AI.

| Model | Replies | First | Last | Tokens |
|---|---|---|---|---|
| `qwen2.5:7b-ctx12k` | 942 | 2026-10-13 | 2026-11-13 | 3,326,808 |
| `qwen2.5-coder:7b` | 70 | 2026-10-11 | 2026-10-13 | 65,475 |

Each row holds the request as it was sent (model, messages, temperature, sample), the reply's text, the token counts
and the time the model took. Nothing else is stored: no key, no address beyond the local model server's.

**Replaying the model runs without a model.** Copy the file to `.auditiq/llm_cache.sqlite` (the cache the client
reads, `auditiq/llm.py`) and run the same commands: every request already answered is taken from the cache, so the
runs of `RESULTS.md`, Section 13 (steps 9 and 10) give the committed results without a GPU or a model server. A
request the cache does not hold still needs a configured model (`docs/OPERATIONS.md`).

The copy is a snapshot: later runs write to `.auditiq/llm_cache.sqlite`, which is not in the repository.
