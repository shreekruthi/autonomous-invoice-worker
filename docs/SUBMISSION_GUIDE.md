# Finish and submit the project

The source, final verification reports, existing live Groq evidence and a labelled deterministic browser recording are included. The repository has been created at [https://github.com/shreekruthi/autonomous-invoice-worker](https://github.com/shreekruthi/autonomous-invoice-worker). A shareable live demo video and your personal form declarations are the remaining external steps. The application has not been submitted.

## 1. Final checks — completed

`VERIFY.ps1` was run in the author's normal Windows PowerShell environment on 26 October 2026. Results: **127 tests passed**, no failures/errors/skips, **89.6% coverage**, **10/10 deterministic reliability scenarios**, lint and formatting passed. Reports are in [final-checks/report.json](final-checks/report.json) and [VALIDATION.md](VALIDATION.md).

To reproduce from the project folder after installing the README dependencies:

```powershell
& .\VERIFY.ps1
```

The result must say `RESULT: PASS`. This command makes no real provider calls. On macOS/Linux use `python -m scripts.verify_submission` in your installed environment.

## 2. Inspect the already collected live proof

Open [the live evidence manifest](../examples/live-evidence/manifest.json). It links four actual user-run Groq task snapshots:

- Orbit: a human approval, a new write and independent verification.
- Two Acme requests: both verify the same record; the ledger has one Acme row.
- Broken Labs: `needs_input`; no Broken Labs row exists.

These are projections of local task/audit records, with LLM history and reviewer names omitted. They are not scripted model outputs or a statistical autonomy benchmark. Current source and ledger payloads were compared when exporting successful cases.

## 3. Record your live video

Follow [DEMO_SCRIPT.md](DEMO_SCRIPT.md), which gives exact requests, expected outcomes and narration. You can inspect the existing successful runs immediately, or record a new run in a fresh database for a clearer end-to-end demonstration.

For a fresh Groq run, stop any server occupying port 8002, keep your existing Groq key in the local `.env`, and open PowerShell in the project folder:

```powershell
& .\RUN.ps1 -Mode groq -Fresh -Faults -Port 8002
```

This creates a separate database with a unique filename; existing runs are retained. Open `http://127.0.0.1:8002`. Keep that terminal open. `Ctrl+C` stops the server.

On Windows, bring the browser to the foreground and use your screen recorder. Xbox Game Bar uses **Windows+Alt+R** to start/stop and **Windows+Alt+M** to toggle the microphone. A browser recording normally goes to `Videos/Captures`. Review the file before uploading, especially the mode badge and any visible credentials. See [Microsoft's recording instructions](https://support.microsoft.com/en-us/accessibility/windows/use-a-screen-reader-to-record-your-screen-with-xbox-game-bar).

The supplied `docs/assets/demo.webm` is a **deterministic** execution/recovery recording. It can supplement a live Groq video; identify its mode if you use it. Do not relabel it as LLM autonomy.

Upload your reviewed live recording to a service you use, such as an unlisted video or a shared Drive file. Give reviewers view access and test the URL in a signed-out/private window. Do not paste a local file path into the form. There is no requirement to deploy the app: the form's live-deployment link is optional, while the demo-video link is required.

## 4. Publish the clean source on GitHub

This submission uses [https://github.com/shreekruthi/autonomous-invoice-worker](https://github.com/shreekruthi/autonomous-invoice-worker). Check the repository and its Actions page after upload completes. The following workflow documents how to upload a clean copy yourself, with no Git configuration:

1. Extract the supplied clean `autonomous-ai-worker.zip` into a **new folder**. Use the extracted copy for upload, since the working folder contains your private `.env` and local databases.
2. Sign into GitHub and open [New repository](https://github.com/new).
3. Suggested repository name: `autonomous-invoice-worker`.
4. Description: `An auditable LLM invoice worker with real sandbox execution, approvals, idempotency, recovery and read-back verification.`
5. Choose visibility that lets reviewers access it. A public repository is the easiest to review.
6. Leave the automatic README, licence and .gitignore options unchecked; the source includes them. Create the repository.
7. Choose **uploading an existing file**, or **Add file → Upload files**. Open the extracted `autonomous-ai-worker` folder and upload its **contents**, so `README.md`, `worker/`, `tests/`, `docs/` and `.github/` are at the repository root. Do not upload only the ZIP.
8. Include `.github/workflows/ci.yml`, `.gitignore`, `.dockerignore` and the environment examples. The clean ZIP excludes the real `.env`, databases, virtual environment and private generated artifacts. If GitHub reports more than 100 files, upload in batches while keeping the same directory structure.
9. Commit with a message such as `Build auditable autonomous invoice worker`.
10. Open the repository's **Actions** tab and let the checks run. The workflow tests Python 3.11, 3.12 and 3.13 on Linux; these remote checks are not claimed passed until GitHub actually reports that result.
11. Add your live recording URL near the top of the README, then test both the repository and video links from a signed-out/private window.

GitHub documents the [new repository flow](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository) and [browser file/folder uploads](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository). Browser uploads currently accept up to 100 files at once and 25 MiB per file; the included deterministic video is below that per-file limit.

## 5. Fill the application yourself

Open the original CentrAlign form. Choose **AI Engineering Intern**, enter your own personal details and use the reviewed answers in [FORM_ANSWERS.md](FORM_ANSWERS.md).

- Repository: the actual GitHub project URL.
- Live demo: leave blank if no public app was deployed.
- Video: the tested shareable recording URL.
- Project questions: copy and personalise the seven supplied answers.
- Declarations: confirm only statements you can truthfully make after working through [INTERVIEW_PREP.md](INTERVIEW_PREP.md).

Before clicking Submit, verify that both required links open, GitHub contains runnable source, the video labels its mode, and your answers disclose Codex assistance. Submit manually when you are satisfied. No hiring result is guaranteed by passing the technical checks.
