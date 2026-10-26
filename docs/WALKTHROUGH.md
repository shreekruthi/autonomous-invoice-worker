# Understand and explain the project, step by step

## 1. Start with the user's outcome

The goal is not “generate a plan.” It is “a correct invoice record exists, and I can show it.” State that distinction in the interview and open the company ledger after a successful task.

The supported scope is intentionally small: one vendor, latest issue date, labeled English text, INR, internal recording. The assignment explicitly allows this. A model choosing tools is useful, but it must not be trusted to invent amounts, approve financial actions or declare success without evidence.

## 2. Read the business rules first

Open `worker/domain.py`. `parse_invoice` requires exactly one of each field. It validates the vendor against source metadata, rejects unsupported currencies, checks dates, and converts a decimal amount into integer minor units. The output is a canonical eight-field payload. `digest` hashes stable JSON for content binding.

Try changing an invoice's `Amount` to `NaN`, `0.001`, or a negative number in a fresh fixture database. The worker should pause rather than create an entry.

## 3. Follow one real tool

In `worker/engine.py`, find `record_invoice`. It saves its preparation checkpoint and POSTs to the company API. In `worker/company.py`, find `write`: it independently reloads the task/source, validates them and checks approval. Then it inserts a row inside a transaction.

Explain why checking only `memory.approved` would be unsafe. The company API uses a separate authoritative row that the model cannot create with its toolset.

## 4. Compare the two planners

`DemoPlanner` is a finite state machine. It is ideal for offline setup and repeatable reliability tests, but it is not language reasoning.

`OpenAIPlanner` sends function schemas to a real Responses endpoint. One returned call is schema-checked, executed, and followed by a `function_call_output` observation with the matching call ID. The next request replays that history so the model sees what happened. The loop code does not hardcode the live sequence.

Be explicit that live-model quality has to be tested separately. Scripted HTTP contract tests establish integration behavior, not model competence.

## 5. Break the happy path

On a fresh database with faults enabled, inject `read_invoice`. The API returns 503 once; the executor logs a failed attempt and retries. Inject `record_after`; the write commits but returns 503. The retry returns the already saved row because of business-key uniqueness. Show the single ledger row and verified task evidence.

Explain at-least-once calls versus idempotent effects. There is no claim of exactly-once network delivery.

## 6. Explain approval as durable state

Orbit Cloud's amount is above the configured threshold. `request_approval` stores a pending fingerprint and returns control to the human. The reviewer endpoint uses a different credential and checks that the source still matches. Approve resumes the same task; reject ends it. Stale content is not approved automatically.

The static reviewer token is intentionally a sandbox mechanism. A production reviewer would need an authenticated identity and role with auditable authorization.

## 7. Prove completion

`verify_record` makes independent GETs. It compares the saved payload to the staged payload, the stored fingerprint, the current source and latest issue date. The executor completes the task immediately after verification and builds the summary from those fields; no final model call is required. The compatibility `finish` tool requires matching evidence too. Show the source hash, record ID and checked fields in the UI or exported JSON.

Verification reads through another route but the same database. Say this clearly; production verification must match the actual external side effect.

## 8. Understand recovery and persistence

Read `worker/store.py`: tasks keep structured memory; events keep ordered observations. At startup, pending/running tasks become interrupted. Resume clears old verification and forces a ledger lookup if a payload was staged, so an uncertain write is reconciled before continuing. For an older checkpoint that already reached verification, resume instead repeats the ledger/source verification directly and completes without a model call. No automatic scheduling or distributed worker system is implied.

Clarification updates the persisted goal, clears operational memory and supersedes earlier grants while retaining the trace. This is intentionally a restart under a revised instruction, not free-form conversational document editing.

## 9. Read the tests as an engineering argument

Start with the happy path and post-commit test. Then read `test_company_boundary_rejects_forged_approved_memory` and the malicious planner tests. These demonstrate protections outside the planner. Read the mismatch test to see why “row exists” is weaker than verified success.

Run `python -m scripts.evaluate` and inspect the individual scenarios, not only the pass count. An evaluation should check outcomes and side effects. The provided score is a deterministic reliability score, not a general autonomy score.

## 10. Prepare for likely interview changes

| Interview request | Where to change it | What to verify |
| --- | --- | --- |
| Change approval threshold | `.env` / `Settings` | Below/equal/above boundary; reviewer enforcement stays in company API |
| Add another vendor/invoice | Fixture JSON, fresh DB | Selection, latest-date ordering and exact field parsing |
| Introduce permanent API failure | Fault/test transport | Bounded attempts, failed status and no false success |
| Add another provider | Implement `choose` / `observe` planner contract | Schema, history, errors, credentials and no silent fallback |
| Integrate an ERP | Company transport and domain mapping | Remote idempotency, permissions, document versioning and read-back |

Before submitting, run the live model with your own key, inspect several paraphrases and an adversarial source, and record the true results. Explain what did not work and how you would measure the next improvement. Do not promise general computer autonomy or a guaranteed shortlist.
