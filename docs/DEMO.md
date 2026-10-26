# A concise demo and submission guide

Aim for a 3–4 minute screen recording. Show the mode badge throughout. Start with a fresh `WORKER_DB` filename and `ENABLE_FAULTS=true`.

For the final Windows/Groq submission flow, use [DEMO_SCRIPT.md](DEMO_SCRIPT.md) and [SUBMISSION_GUIDE.md](SUBMISSION_GUIDE.md). The final full suite has passed 127 tests and the supplied live Groq evidence is separate from the deterministic recording below.

## Suggested narration

**0:00 — Scope and honesty.** “This worker records one vendor's latest invoice into a synthetic company's ledger. This run uses [deterministic demo / live LLM] mode. Demo mode proves execution and reliability; live mode asks a model for each next tool.”

**0:25 — Real execution.** Enter the Acme request. Open the plan and a couple of observations: vendor discovery, source read, validated fields, POST result. Open Company ledger and show the actual row. Return to the green verification card and show the ID/hash.

**1:10 — Idempotency.** Repeat the Acme request. Show “Verified existing” and the same record ID. The ledger count stays one. “A database uniqueness constraint protects this even when the first write's response is lost.”

**1:40 — Approval.** Submit Orbit Cloud. Show that no Orbit row exists while waiting. Review the exact amount/date/hash, then approve. Show the same task resume, independently verify, and add one row. Mention that the worker credential cannot call review.

**2:20 — Failure recovery.** Use a fresh database for the clearest fault run, or show the provided recorded fault trace. Inject a read failure and lost write response, run Acme, open the two `tool error` events and retries, then show one record and verification. A duplicate-only run would not exercise a new write failure.

**3:00 — Missing data and limits.** Run Broken Labs. It requests a corrected due date and does not invent one. Show the evaluation report and explain that model quality, OCR, real ERP integration and distributed queues are future work.

## Reproduce evidence

```bash
# Server running, demo mode, fresh database, faults enabled
python -m scripts.demo --faults --approve-demo --out artifacts/demo
python -m scripts.evaluate --out artifacts/evaluation.json

# Optional screen recording of the actual UI
python -m scripts.browser_demo --out artifacts/browser
```

`--approve-demo` is an explicit authorization for the scripted synthetic approval. The autonomous worker itself never receives reviewer credentials.

For a real-model video, configure `WORKER_MODE=groq` with your Groq key, or optionally `WORKER_MODE=openai` with an OpenAI key, create a fresh task and show its trace. Live decisions may differ and can fail; the demo script reports mismatched outcomes rather than quietly claiming success. Never display `.env` or API keys while recording.

## GitHub submission

- Source folder with README, environment example, tests, CI and Docker configuration.
- A short public video link or intentionally deployed sandbox demo, with the demonstrated mode labeled.
- A live LLM evidence export if claiming autonomous model behavior; synthetic data only.
- A concise explanation of key choices, limits and next steps (provided in the architecture and walkthrough docs).
- Your own contact details and authorship statement. No invented credentials, past experience or performance claims.

No repository, public deployment or video-host upload is created by the local project. The optional recorder creates a local WebM that you can review and upload yourself.
