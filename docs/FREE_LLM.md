# Run the worker with a free hosted LLM

Use **Groq's Free tier** for the simplest setup without a large local model download. The adapter defaults to `openai/gpt-oss-20b`, an open-weight model served by Groq. The `openai/` prefix is the model's name on Groq; requests go to Groq, and this mode does not use your OpenAI account or OpenAI credits.

Groq currently documents a Free tier and tool calling. Free access has account and model quotas; it is not unlimited. Keep your account on the Free plan if you want no paid API usage. This application cannot inspect or enforce the billing plan on your provider account.

Official references, checked 26 October 2026:

- [Create a Groq API key](https://console.groq.com/docs/quickstart)
- [Free-tier limits](https://console.groq.com/docs/rate-limits)
- [Billing plan distinction](https://console.groq.com/docs/billing-faqs)
- [Tool calling contract](https://console.groq.com/docs/tool-use/local-tool-calling)

## 1. Create a free account and key

Open the [Groq console](https://console.groq.com/), sign in, and create an API key in the API Keys section. Keep the account on the Free tier. An OpenAI key will not work here. Put the new key only in your local `.env`; do not send it in chat, publish it, or show it in a recording.

## 2. Edit your existing configuration

Stop the app with Ctrl+C in the terminal running it. Open `.env` in your project directory. If it does not exist, copy `.env.groq.example` to `.env` first.

Set these values, preserving your other configuration:

```dotenv
WORKER_MODE=groq
GROQ_API_KEY=YOUR_GROQ_KEY
GROQ_MODEL=openai/gpt-oss-20b
GROQ_BASE_URL=https://api.groq.com/openai/v1
WORKER_DB=data/groq-live-01.sqlite3
ENABLE_FAULTS=true
```

No new Python package is needed. HTTPX already handles the provider API. The old `OPENAI_API_KEY` value is ignored in Groq mode; you can remove that line if you prefer. The new database filename preserves earlier runs and creates a fresh ledger. If you previously set `WORKER_MODE` in the terminal environment, change that value too: shell variables take precedence over `.env`.

## 3. Restart the server

Using your project's installed Python environment, run:

```powershell
python -m uvicorn worker.api:create_app --factory --host 127.0.0.1 --port 8001 --workers 1
```

On the original authoring computer, the already tested interpreter can be used from the project directory:

```powershell
& "..\..\work\.venv\Scripts\python.exe" -m uvicorn worker.api:create_app --factory --host 127.0.0.1 --port 8001 --workers 1
```

Open [http://127.0.0.1:8001](http://127.0.0.1:8001) and refresh the page. The badge should identify `groq` and the configured model. Create a **new task**; old OpenAI tasks cannot be resumed under a different provider mode because their stored histories use a different protocol.

## 4. Test one task first

Enter:

> Record the latest invoice from Acme Supplies and verify the saved record.

Inspect the tool trace, verified evidence and company ledger. Then test the duplicate request, Orbit Cloud's approval gate and Broken Labs' missing due date. Download the real traces. A hosted model is making the decisions, but you still need these observed results before claiming the model reliably completes the workflow.

## Rate limits and errors

Each planned action requests another model decision, so one task makes multiple provider calls. Free-tier token limits may be reached even with one user. Run one task at a time and allow pauses. Successful verification now completes the task directly in application code, without requesting a final model response.

- A 429 response may include `Retry-After`. The adapter waits at least that delay when it is at most 60 seconds and attempts remain. Longer delays or exhausted attempts stop with an explanatory error; resume later after the quota resets.
- Successful responses can also pace the next call: the adapter checks documented remaining-token/request and reset headers, reserving the previous input size, completion budget and 256 tokens for growth. It waits when that forecast exceeds remaining capacity. This is an estimate, not a guarantee; daily token exhaustion or other applications sharing the organization can still cause 429. Missing headers retain reactive retry behavior. Cooldowns are shared across tasks in this worker process, cleared by a restart, and recorded as `provider_wait` events. Automatic waits never exceed 60 seconds per wait; longer cooldowns stop for explicit resume.
- Daily quotas require waiting for the provider's reset or choosing another eligible model/account setup. The application never upgrades your plan or silently switches to deterministic mode.
- A 401 response means the Groq credential was rejected. Check `GROQ_API_KEY` locally without sharing it.
- A 400/404 can indicate an unavailable model or incompatible tool configuration. Check the model's availability in your Groq console.

### Already verified, but the task says failed with 429

An earlier version requested a final `finish` decision after successful read-back verification. A quota failure on that extra request could incorrectly leave the task marked failed. The executor now completes immediately after verification. After updating the code, restart the server, refresh the dashboard, select the existing failed task and choose **Resume from checkpoint**. If the checkpoint contains verification evidence and has action budget remaining, the executor re-reads the ledger and source before completing, with no model call or new invoice write. Changed data blocks completion. Earlier quota failures still require a provider cooldown before model-driven work can continue.

### Diagnose HTTP 400 without sharing a key

From the project directory, use your installed Python environment:

```powershell
python -m scripts.diagnose_groq
```

On the original authoring computer:

```powershell
& "..\..\work\.venv\Scripts\python.exe" -m scripts.diagnose_groq
```

This sends **one synthetic model request**, without executing a company action. It prints the HTTP status and redacted error fields, or the returned tool name if successful. It never prints authorization headers, API keys or failed-generation bodies. Run it in your normal terminal if the agent's restricted environment cannot access the provider. Review the redacted output before sharing it.

`tool_use_failed` means the provider rejected the model's generated tool call; it is different from a missing key or an unavailable model. The adapter now retries that specific failure within the existing attempt budget, with a corrective tool-call instruction and low sampling temperature. It never executes the provider's `failed_generation` text. Other 400 errors remain explicit failures rather than guessed repairs.

One observed live-provider failure was a valid nine-step invoice plan rejected by the original eight-item plan limit. The plan schema now allows 3–24 descriptive steps, with a regression test for the reported nine-step plan. Plans do not grant permission to execute; the separate action budget, approval policy, duplicate protection and verification gates are unchanged. Retry guidance for this validation error uses the current schema bounds without replaying raw provider instructions.

All task guards, invoice validation, approvals and verification remain enforced by application code. Tool schemas are sent to Groq and arguments are checked locally with Pydantic; provider-side strict-schema enforcement is not assumed. Raw provider error bodies and private reasoning fields are not saved to the audit trace.

## Final validation status

The complete final suite passed **127 tests**, with **89.6% coverage**, lint and formatting passed, and **10/10 deterministic reliability scenarios**. The author ran `VERIFY.ps1` in normal Windows PowerShell; the generated reports were read back here. This includes the asynchronous provider/workflow tests that previously stalled in the restricted agent runtime. See [VALIDATION.md](VALIDATION.md) and [the final report](final-checks/report.json).

Actual live Groq runs demonstrate an approved Orbit write with independent verification, repeated Acme requests reusing one ledger row, and missing-data blocking for Broken Labs. Four quota-wait audit events were observed in live history. Curated evidence is in [the live manifest](../examples/live-evidence/manifest.json). These cases are not a statistical model-quality benchmark; the 10/10 score and existing WebM describe deterministic planning. A fresh live injected-failure recording and recovery of the old verified Acme checkpoint are not claimed completed.

To reproduce the offline checks from an installed environment:

```powershell
python -m scripts.verify_submission
```

## Local alternative

[Ollama supports tool calling](https://docs.ollama.com/capabilities/tool-calling) and can run models locally without per-request API fees, using your own hardware. For example, the official [Qwen3 4B entry](https://ollama.com/library/qwen3:4b) lists an approximately 2.5 GB download; actual running memory requirements are higher. A native Ollama adapter is not included in this update. Do not point the OpenAI Responses adapter at Ollama's native `/api/chat` endpoint: the request and response protocols differ.
