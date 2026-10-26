# Live demonstration sequence and narration

Use synthetic data and keep the mode badge visible. Aim for a clear 4–6 minute explanation; a real free-tier run can take longer because of provider cooldowns. Keep those waits, or explicitly disclose cuts that omit waiting. Never imply that an earlier saved trace is executing live on screen.

## Prepare

- The final tests and reliability evaluation have passed; see [VALIDATION.md](VALIDATION.md).
- For a new run use `RUN.ps1 -Mode groq -Fresh -Faults -Port 8002` and open `http://127.0.0.1:8002`.
- Confirm the badge says **LLM · groq**, and the new company ledger is empty.
- Use a browser screen recording with microphone narration. Keep terminals containing credentials and the `.env` file out of the recording.
- Start the recording, then follow the steps below. The reviewer approval is a deliberate human action.

## Opening — about 20 seconds

Say in your own words:

> This is a focused autonomous invoice worker for a sandbox company. The Groq model chooses a plan and tools from observations. The application executes real API operations and database writes, enforces approval policy and independently checks completion. It records invoices; it does not make payments.

## Acme: execution and recovery

Before the first task, click **Inject retry + lost response**. The interface should confirm one read outage and one lost write response are armed.

Enter:

> Find the latest invoice from Acme Supplies, enter it into our internal system, and verify it.

Click **Run task** once. Wait for the outcome. A quota error is a provider stop: after its cooldown, use **Resume from checkpoint** on the same task. Do not repeatedly create tasks to retry.

When successful, expand the audit events. Show vendor discovery, invoice read, staged fields, a retried read, and the post-commit write retry. Open **Company ledger** and show one Acme row. Return to the verification card and show the record ID, source hash and checked fields.

Explain:

> I intentionally injected these two failures. The write failure happens after the database commit, so a retry must reconcile the same business key rather than create another invoice. The final success is based on reading the saved data back, not on the model saying it is done.

If this new live fault scenario fails, show the actual status and explain it. The included deterministic recording and the 10-scenario evaluation prove the tested tool-recovery mechanism separately; they do not turn an unsuccessful live run into a successful one.

## Acme again: duplicate protection

Enter:

> Record the latest invoice from Acme Supplies.

Run once. Show **Verified existing**, the same record ID and still one Acme row. Explain that the model can vary its tools, but the database uniqueness rule protects the business outcome.

## Orbit: human approval

Enter:

> Record the newest invoice from Orbit Cloud.

The default INR 12,500 invoice exceeds the INR 5,000 threshold. Show **AWAITING APPROVAL**, inspect the staged amount/date/hash, and confirm no Orbit record exists yet. As the human reviewer, click **Approve & resume**. Show the verified result and the second ledger row.

Explain:

> The planner has no approval tool. The review route uses a separate credential and the approval binds to the exact task and invoice fingerprint. The company API checks that approval again before inserting.

## Broken Labs: safe incomplete outcome

Enter:

> Record the latest invoice from Broken Labs.

Show **NEEDS INPUT**, the due-field validation message and no Broken Labs row in the ledger.

Explain:

> This invoice has a missing required field. The worker requests a corrected source instead of inventing a due date or reporting success. NEEDS INPUT is the intended safe result for this scenario.

## Closing: evidence and scope

Click **Download evidence** for the demonstrated tasks. Show the repository's validation report briefly.

> The final full suite passed 127 tests, and ten deterministic reliability scenarios passed. The live evidence demonstrates selected Groq workflows; I have not claimed a general live-model success rate. This prototype supports seeded English INR invoices and one local worker. Next I would evaluate more language variants, add versioned document ingestion and a durable queue. Codex helped substantially with implementation, testing and debugging, and I can explain the application boundaries shown here.

Use the final sentence only after practising the code walkthrough yourself.

## Alternative: narrate the already executed live tasks

If provider quota prevents another run, the existing real Groq traces remain useful. Clearly say, **"These tasks ran earlier; I am inspecting their saved results."** Show the original Orbit approval/write, repeated Acme record IDs, Broken Labs block and evidence export. Identify any deterministic recovery footage separately. Do not present saved-result inspection as a new execution.

After reviewing the recording, upload it, test its viewing permissions and place its shareable URL in the form and README.
