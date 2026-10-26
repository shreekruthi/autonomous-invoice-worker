# Explain and modify the worker yourself

Start with this explanation in your own words:

> A user gives the worker an invoice-recording goal. The model chooses a tool, the executor checks whether it is permitted, the company API performs the actual operation, and the result becomes the next observation. SQLite stores the task's context and history. A write needs validated source data, a duplicate check and any required human approval. Success requires independently reading back the saved row and source; a model's assertion is insufficient.

## Follow one request through the code

1. `worker/api.py`: find `POST /api/tasks`. It creates a persisted task and invokes `engine.run`.
2. `worker/groq_planner.py`: find `build_request`, `choose`, `accept_response` and `observe`. Explain the assistant function call and matching tool observation.
3. `worker/planner.py`: inspect the shared typed tool registry and system instructions. Compare the real planner with `DemoPlanner`.
4. `worker/engine.py`: follow `run`, `execute` and `dispatch`. Identify schema checks, state guards, retries, step limits and automatic completion after verification.
5. `worker/domain.py`: inspect strict parsing, integer minor units and the canonical fingerprint. Explain why an unknown due date cannot be guessed.
6. `worker/company.py`: follow the write transaction. Find the unique business key, source reload, authoritative approval lookup and post-commit failure injection.
7. `worker/store.py`: inspect task checkpoints, ordered events, approval rows and startup interruption recovery.
8. Open the corresponding actual traces in `examples/live-evidence/` and match the actions to those functions.

## Questions you should answer without reading a script

**Where is the autonomy?** The live model proposes a plan and chooses the next registered tool and arguments from actual observations. The workflow and tools constrain its scope. The executor's retries, guards and completion logic are deterministic engineering, and demo mode is a state machine.

**Why a narrow sandbox?** It lets me demonstrate actual side effects, recovery and verification within a testable environment. The assignment permits a simulated company application. I have not built a general desktop agent or a real ERP connector.

**Why SQLite?** One local worker and small, structured tasks do not need a distributed database. SQLite provides durable checkpoints, transactions and a unique constraint. Multi-worker job ownership and distributed consistency would require more design.

**How do duplicates work?** The business key is `(vendor_id, invoice_number)`. Identical content returns the existing record. A changed fingerprint for that key requires reconciliation. A unique constraint and transactional insert protect the ledger even when two requests race.

**What if a write succeeded but its response disappeared?** The caller cannot assume failure means no write occurred. Retrying the same business key returns the original record, then verification confirms its content. If bounded retries end, the task remains unverified and an explicit resume reconciles the ledger.

**Can the agent approve itself?** No review tool is exposed to the planner. The review route requires a separate reviewer credential. The company API checks the database approval for the exact task and fingerprint, so forging an `approved` memory value is insufficient.

**Why independently read back?** A successful POST response does not establish the intended outcome. Verification GETs both the ledger and source, compares every canonical field and fingerprint, and checks latest-source selection. It is an independent API path over the same sandbox database, not an external reconciliation service.

**What is stored in memory?** The goal, plan, selected vendor, observed invoice, validated payload, duplicate lookup, record ID, approval status, observations and verification evidence. Provider tool-call/output history and usage are also persisted for live decisions. A vector database is unnecessary for this bounded task.

**Does missing input get repaired automatically?** No. A missing or conflicting required field stops the workflow. Clarification can update the goal, but financial facts need a corrected source. The prototype does not infer a due date from unrelated information.

**How are model errors handled?** Invalid local arguments and unsafe state transitions are rejected. A specific provider `tool_use_failed` response gets bounded repair guidance; raw failed generations are never executed. Provider/network retries are bounded, and quotas can require a later resume.

**What did you learn debugging the live model?** A valid nine-step plan exceeded an overly tight cosmetic schema limit; expanding that bound did not expand execution permissions. A final model call could fail after verification; completion now follows verified evidence directly. Provider quota headers now pace subsequent requests, while free-tier limits remain external constraints.

**What do your test results mean?** The final full suite passed 127 tests with about 89.6% coverage. Ten deterministic reliability scenarios passed. Separate persisted live Groq traces show approval/write/verification, duplicate reuse and missing-data blocking. Neither scripted provider responses nor the deterministic score measure general LLM planning quality.

**What did AI help with?** Codex substantially helped implement, test, document and debug the project. Explain the parts you reviewed and changed yourself truthfully. Do not claim unaided authorship or knowledge you have not developed.

## Practise three small changes in a separate copy

1. Change the approval threshold in the environment and predict whether Acme or Orbit pauses. Use a fresh database so an already-recorded duplicate does not hide the approval gate.
2. Before first startup of another fresh database, change a synthetic due date in `worker/fixtures/company.json`. Run the worker and show that the changed date appears in verified evidence. Seeding is insert-only, so editing the fixture does not rewrite an existing database.
3. In another fresh sandbox with faults enabled, inject a read error and lost write response. Find the retry events and prove that only one record exists. Explain why a duplicate-only task cannot demonstrate an after-commit write failure.

Then run `VERIFY.ps1` again. Keep practice edits separate from the verified submission unless you intend to submit and revalidate them.
