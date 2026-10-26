# Application answers — AI Engineering Intern

These answers match the project questions visible in the CentrAlign form on 26 October 2026. Review them, practise the explanations and edit anything you cannot personally defend. Personal details and declarations must be completed by you. The form has not been filled or submitted.

## Links and role

- Role: **AI Engineering Intern**.
- GitHub Repository link: https://github.com/shreekruthi/autonomous-invoice-worker
- Live demo link (if deployed): leave blank if there is no public deployment. A localhost URL is not accessible to reviewers.
- Demo Video Link: paste a shareable recording URL and verify access while signed out.

Do not submit a ZIP download link in place of a GitHub repository, or the deterministic recording as evidence of LLM autonomy without explaining its mode.

## In 3–5 sentences, what did you build?

I built an autonomous invoice worker that accepts a natural-language request and records a vendor's latest invoice in a sandbox company's internal ledger. In live mode, a Groq-hosted model creates a plan and selects tools after observing each execution result, while FastAPI and SQLite perform real validation and persistent writes. The worker checks for duplicates, pauses for human approval above a configurable amount, and verifies the saved record against the source before reporting success. It persists task context and audit evidence, uses bounded retries for transient failures, and stops for corrected input when required invoice data is missing. A separate deterministic mode supports repeatable reliability evaluation and is explicitly labelled as not being LLM autonomy.

## Briefly explain your architecture

A small browser dashboard talks to a FastAPI task API. A bounded executor alternates between a planner decision, an allowlisted typed tool call and an observation, saving structured context and events in SQLite. The live Groq planner uses native Chat Completions function calls; OpenAI Responses and a deterministic demo planner are separate adapters. Tools call a sandbox company API through HTTPX's ASGI transport, executing actual route validation, approval policy and database writes. The company API enforces a unique vendor/invoice business key and exact-fingerprint approvals, while the executor independently reads the ledger and source before generating a completion summary. The application, rather than the model, owns financial parsing, write permissions and success criteria.

## What parts of your system are genuinely autonomous?

In Groq mode, the model interprets the request within the supported invoice workflow, proposes a plan and selects the next tool and arguments from the observations it receives. It discovers the vendor directory, chooses a vendor and invoice, invokes validation and duplicate lookup, and can request approval or clarification instead of requiring the user to specify every action. The executor performs the selected tools and returns their actual results to the model; bounded transient retries and final completion are application-controlled reliability mechanisms. Human approval remains a human decision. The deterministic demo uses a fixture-aware state machine and is not presented as autonomous LLM reasoning.

## what is currently hard coded or manually configured?

The environment contains seeded synthetic vendors and English plain-text invoices, and the supported goal is recording one vendor's latest invoice in INR. Tool definitions, strict invoice field parsing, state guards, verification rules and the sandbox API are implemented in code. Provider/model settings, credentials, retry/action limits and the approval threshold are configured through environment variables; the default threshold is INR 5,000. A human reviews high-value writes, and corrected invoice data must come from a corrected source rather than an invented value. The local sandbox uses separate shared worker/reviewer development tokens, not a production identity system. Demo-mode action selection is deliberately hard coded.

## What models, frameworks, APIs, libraries, AI coding tools, or existing projects did you use?

The demonstrated live model is `openai/gpt-oss-20b` hosted on Groq and accessed through its Chat Completions API. The stack uses Python, FastAPI, SQLite, HTTPX, Pydantic and python-dotenv, with a vanilla HTML/CSS/JavaScript dashboard. Tests and checks use pytest, pytest-cov and Ruff; optional Playwright tooling records and exercises the browser UI. An OpenAI Responses adapter is also implemented and contract-tested, but the included live evidence comes from Groq. I used OpenAI Codex extensively for implementation, tests, documentation and debugging, including provider schema and rate-limit issues. The project was created for this assignment using these libraries, without adopting an existing agent application or claiming that AI-assisted work was entirely unaided.

## What is the biggest technical limitation of your current solution?

The biggest limitation is the narrow source and workflow interface: invoices must use the sandbox's structured plain-text format, rather than arbitrary PDFs, email inboxes or external ERP systems. Language understanding is model-driven, but financial extraction is deliberately handled by a strict parser. The live model can still select the wrong vendor or make an unhelpful decision; application guards constrain writes but do not prove semantic correctness for every request. Groq free-tier quotas can pause runs, and the prototype uses a single local worker with explicit resume rather than a distributed durable queue. The 10-scenario reliability score uses deterministic planning and is not a measured general live-model success rate.

## If you had another 2 weeks, what would you build/change next?

I would first build a labelled live-model evaluation covering paraphrases, ambiguous vendors, adversarial invoice text and interrupted executions, and measure verified success, unsafe writes, latency and token usage. Next I would add versioned document ingestion for one real test integration, preserving the existing approval and verification boundaries. I would introduce a durable background job queue with leases, cancellation and explicit time/token budgets so provider cooldowns do not tie up a request. Finally, I would add authenticated reviewer identities and improve evidence redaction and the interface for correcting source documents. I would prioritise measurable reliability within the invoice workflow before expanding to unrelated tasks.

## Final declaration

The form asks you to confirm that you built and understand the submission, disclosed components and AI tools, avoided confidential/unauthorised data, and can walk through, debug and modify it. Only check these after reviewing the code and practising the exercises in [INTERVIEW_PREP.md](INTERVIEW_PREP.md). These answers disclose Codex assistance; they do not replace your own understanding.
