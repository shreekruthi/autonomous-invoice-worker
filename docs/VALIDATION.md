# Validation actually performed

## Final source checks — 26 October 2026

The author ran `VERIFY.ps1` in normal Windows PowerShell after the restricted agent runtime could not create Windows asyncio's local socket pair. The resulting reports were read back from disk, and the recorded source digest was checked against the final Python/configuration/launcher source. No tests were skipped to obtain this result.

| Check | Observed result |
| --- | --- |
| Final complete pytest suite | **127 passed**, 0 failed, 0 errors, 0 skipped; latest verification test stage: 21.86 seconds |
| Coverage | **89.6%** overall, 825 of 921 statements covered |
| Ruff lint and formatting | Passed |
| Deterministic reliability evaluation | **10/10** scenarios passed |
| Runtime | Windows, Python **3.12.14**, dependencies in `requirements.lock` |
| Final source SHA-256 | `d385f03b729596c8f7e917cacd6d81d9d2b3f1136ee41e0853f731e7ce8b4038` |

Reports: [stage report](final-checks/report.json), [pytest JUnit results](final-checks/tests.xml), [coverage](final-checks/coverage.json), [reliability evaluation](final-checks/evaluation.json). The digest algorithm in `scripts/verify_submission.py` includes Python sources/tests, the lockfile, project configuration and root PowerShell launchers. Documentation, evidence and video edits do not change that code digest.

The tests exercise real task/company routes and temporary SQLite databases. External provider responses in contract tests are synthetic: they verify protocol handling and executor integration, not model intelligence. Completion tests use SQLite with eager read stubs; quota tests use HTTPX MockTransport and a fake clock. Final full-suite execution includes the asynchronous provider/workflow tests that previously could not finish inside the restricted agent runtime.

The deterministic evaluation covers standard recording, transient read failure, lost write response, duplicate protection, approval pause/approve/reject, missing/no source data and verification mismatch. Its 10/10 result is **not a live LLM success rate**.

The installed Starlette test adapter emits one deprecation warning about HTTPX. The suite passes; migrating that adapter is a maintenance task when upstream support changes.

## Actual live Groq observations

The user executed real tasks with Groq-hosted `openai/gpt-oss-20b`. The dashboard screenshots and persisted database/audit records support the observations below. Curated snapshots are in [the live evidence manifest](../examples/live-evidence/manifest.json).

| Live case | Observed result |
| --- | --- |
| Orbit approval and new write | Human approval recorded, invoice written, independent read-back succeeded, executor completed the task |
| Repeated Acme requests | Two successful tasks reference the same record; exactly one Acme row exists |
| Missing due field | Broken Labs pauses with `needs_input`; zero Broken Labs rows exist |
| Quota pacing | Four `provider_wait` audit events observed in the live run history; selected tasks completed |

Successful snapshot exports additionally compare the current saved payload/fingerprint and current source to the task's prepared data. Exports omit LLM history, source bodies and reviewer names; they contain synthetic company data. Local audit files are editable and are not signed attestations. These selected observations do not establish general paraphrase accuracy, prompt-injection resistance or a statistical planning-success rate.

Two real incidents informed fixes: a nine-step plan exceeded an overly tight cosmetic schema limit, and a quota failure on a redundant final model request left an already-verified task marked failed. The schema now allows 3–24 descriptive steps without enlarging the execution budget, and the executor completes immediately after verification. Fresh re-verification on resuming an older verified checkpoint is covered by tests; that particular legacy Acme checkpoint has not been confirmed recovered live.

Live provider quota remains external to the application. The header-based forecast and bounded retries reduce avoidable failures, but daily exhaustion and shared organisation traffic can still stop a run. A fresh real Groq Acme run recovered both an injected read outage and an injected lost post-commit response, then independently verified one ledger row. A repeated request reused that row. Orbit initially stopped on an incomplete model function call; explicit checkpoint resume, separate test-operator approval and read-back verification subsequently succeeded. Broken Labs paused for missing input without a write. See the [additional live recovery manifest](../examples/live-recovery/manifest.json). The automated recovery recording passed, but the applicant is making a preferred manual presentation; a reviewed public video URL remains pending.

## Remote CI

[GitHub Actions run #3](https://github.com/shreekruthi/autonomous-invoice-worker/actions/runs/40282386683) passed all three Ubuntu matrix jobs for Python 3.11, 3.12 and 3.13 on source commit `aba9bdba62698da9d1d03536179ebf36a8a06b4d`. Each job runs lint, formatting, the complete tests and deterministic reliability evaluation. This is separate from the live Groq demonstrations.

## Earlier browser/package baseline — 25 October 2026

The earlier baseline passed 61 tests with 88% coverage, the CLI/network demo, editable install and wheel build. The actual UI ran through headless Edge with Playwright, with zero page JavaScript errors. It demonstrated a read outage, a lost post-commit response, one Acme row, duplicate reuse, Orbit approval and Broken Labs blocking. Those records and the WebM are in `examples/evidence/` and `docs/assets/`, explicitly labelled **deterministic**. The historical [validation.json](validation.json) describes that earlier run rather than the final test count.

## Not claimed as completed

- An actual OpenAI provider run: its adapter passed contract tests; the included live execution evidence is Groq.
- A Docker image build: configuration is supplied; the local Docker engine was unavailable.
- Public hosting, arbitrary browser/desktop control, OCR/PDF/email ingestion or real ERP integration: outside this prototype.
- A hosted live recording or form submission: these remain pending. The source repository is [https://github.com/shreekruthi/autonomous-invoice-worker](https://github.com/shreekruthi/autonomous-invoice-worker); inspect its Actions page for the current remote CI result.
