import asyncio
import time

import httpx
from pydantic import ValidationError

from worker.company import require_latest
from worker.domain import InvoiceError, digest, parse_invoice
from worker.planner import TOOLS, Action, PlannerError
from worker.store import now


class GuardError(ValueError):
    pass


class ToolHTTPError(RuntimeError):
    def __init__(self, status):
        self.status = status
        self.retryable = status in {429, 502, 503, 504}
        super().__init__(f"Sandbox HTTP {status}")


def has_verified_checkpoint(task):
    """A checkpoint selects re-verification, never success without a fresh read."""
    memory = task["memory"]
    return bool(
        memory.get("verified")
        and memory.get("prepared")
        and memory.get("record_id")
        and memory.get("plan")
        and memory.get("vendor_id")
        and memory.get("lookup_done")
    )


def finish_verified_task(task):
    """Completion is an application decision based on verified evidence, not another LLM turn."""
    memory = task["memory"]
    expected, evidence = memory.get("prepared"), memory.get("verified")
    if (
        not expected
        or not evidence
        or (
            evidence.get("record_id") != memory.get("record_id")
            or evidence.get("fingerprint") != digest(expected)
            or evidence.get("source_sha256") != expected.get("source_sha256")
        )
    ):
        raise GuardError("Cannot claim success without matching independent read-back evidence")
    task["status"] = "succeeded"
    verb = "Verified existing" if memory.get("duplicate") else "Recorded and verified"
    task["summary"] = (
        f"{verb} {expected['invoice_number']}: INR {expected['amount_minor'] / 100:,.2f}, "
        f"due {expected['due_date']}. Ledger ID {memory['record_id']}."
    )
    return {"summary": task["summary"], "evidence": evidence}


class Engine:
    def __init__(self, store, settings, company_app, planner):
        self.store, self.settings, self.company_app, self.planner = store, settings, company_app, planner
        self.lock = asyncio.Lock()

    async def request(self, method, path, **kwargs):
        # The transport executes actual FastAPI HTTP routes, validation, policy and SQLite writes.
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.company_app),
            base_url="http://sandbox",
            timeout=10,
            headers={"Authorization": f"Bearer {self.settings.worker_token}"},
        ) as client:
            result = await client.request(method, path, **kwargs)
        if result.status_code >= 400:
            raise ToolHTTPError(result.status_code)
        return result.json()

    async def run(self, task_id):
        # One local worker. Persisted checkpoints permit explicit resume after process failure.
        async with self.lock:
            task = self.store.task(task_id)
            if task["status"] not in {"pending", "interrupted"}:
                return task
            if task["mode"] != self.settings.mode:
                task["status"] = "failed"
                task["summary"] = (
                    "Task mode differs from server mode. Restore original mode or create a new task."
                )
                self.store.save(task)
                return task
            recheck_verified = task["status"] == "interrupted" and has_verified_checkpoint(task)
            if task["status"] == "interrupted":
                m = task["memory"]
                self.planner.observe(
                    task,
                    {
                        "ok": False,
                        "error": "Process interrupted; action outcome unknown. "
                        "Look up the ledger and verify before further writes.",
                    },
                )
                m.pop("verified", None)
                if "prepared" in m and not recheck_verified:
                    m["lookup_done"] = False
            task["status"] = "running"
            self.store.save(task)
            try:
                if recheck_verified and task["steps"] < self.settings.max_steps:
                    # Recover older tasks that already verified but failed on a final model request.
                    # Refresh ledger/source evidence without depending on provider availability.
                    task["steps"] += 1
                    result = await self.execute(task, Action("verify_record", {}))
                    task["memory"]["last_observation"] = result
                    if result.get("ok") and task["memory"].get("verified"):
                        self.complete(task, "checkpoint_reverification")
                    self.store.save(task)
                while task["status"] == "running" and task["steps"] < self.settings.max_steps:
                    action = await self.planner.choose(task, self.settings)
                    task["steps"] += 1
                    result = await self.execute(task, action)
                    task["memory"]["last_observation"] = result
                    self.planner.observe(task, result)
                    if action.name == "verify_record" and result.get("ok"):
                        self.complete(task, "independent_verification")
                    self.store.save(task)
                if task["status"] == "running":
                    task["status"] = "failed"
                    task["summary"] = "Step budget exhausted; inspect the trace before retrying."
            except PlannerError as exc:
                task["status"], task["summary"] = "failed", str(exc)
                self.store.event(task_id, "planner_error", {"error": str(exc)})
            except Exception as exc:
                task["status"] = "failed"
                task["summary"] = "Unexpected internal failure; inspect the audit event and server logs."
                self.store.event(task_id, "internal_error", {"type": type(exc).__name__})
            self.store.save(task)
            self.store.event(task_id, "stopped", {"status": task["status"], "summary": task["summary"]})
            return task

    def complete(self, task, reason):
        outcome = finish_verified_task(task)
        self.store.event(task["id"], "completed", {"by": "executor", "reason": reason, **outcome})
        return outcome

    async def execute(self, task, action: Action):
        start = time.monotonic()
        if action.name not in TOOLS:
            result = {"ok": False, "error": "Unknown tool; choose an allowlisted tool"}
            self.store.event(task["id"], "guard_rejected", {"tool": action.name, **result})
            return result
        try:
            args = TOOLS[action.name][0].model_validate(action.args).model_dump()
        except ValidationError:
            result = {"ok": False, "error": "Tool arguments violate the schema"}
            self.store.event(task["id"], "guard_rejected", {"tool": action.name, **result})
            return result
        self.store.event(task["id"], "action", {"step": task["steps"], "tool": action.name, "args": args})
        for attempt in range(1, self.settings.max_tool_attempts + 1):
            try:
                result = {"ok": True, **await self.dispatch(task, action.name, args)}
                self.store.event(
                    task["id"],
                    "observation",
                    {
                        "tool": action.name,
                        "attempt": attempt,
                        "elapsed_ms": round((time.monotonic() - start) * 1000),
                        "result": result,
                    },
                )
                return result
            except (ToolHTTPError, httpx.TimeoutException, httpx.NetworkError) as exc:
                retryable = not isinstance(exc, ToolHTTPError) or exc.retryable
                self.store.event(
                    task["id"],
                    "tool_error",
                    {
                        "tool": action.name,
                        "attempt": attempt,
                        "error": type(exc).__name__,
                        "status": getattr(exc, "status", None),
                        "retryable": retryable,
                    },
                )
                if retryable and attempt < self.settings.max_tool_attempts:
                    await asyncio.sleep(self.settings.retry_delay * (2 ** (attempt - 1)))
                    continue
                task["status"] = "failed"
                task["summary"] = "Tool execution failed after bounded recovery; outcome is not verified."
                return {"ok": False, "error": "Tool unavailable or rejected", "retryable": retryable}
            except InvoiceError as exc:
                task["status"], task["summary"] = "needs_input", str(exc)
                result = {"ok": False, "error": str(exc), "requires": "correct source or clarify task"}
                self.store.event(task["id"], "validation_blocked", {"tool": action.name, **result})
                return result
            except GuardError as exc:
                result = {"ok": False, "error": str(exc)}
                self.store.event(task["id"], "guard_rejected", {"tool": action.name, **result})
                return result
        raise RuntimeError("Unreachable retry state")

    async def dispatch(self, task, name, args):
        m = task["memory"]

        def need(condition, message):
            if not condition:
                raise GuardError(message)

        if name == "ask_user":
            task["status"], task["summary"] = "needs_input", args["question"]
            return {"question": args["question"]}
        if name == "set_plan":
            need("plan" not in m, "A plan already exists")
            m["plan"] = args["steps"]
            return {"plan": m["plan"]}
        need("plan" in m, "Create a plan first")
        if name == "discover_vendors":
            m["vendors"] = await self.request("GET", "/vendors")
            return {"vendors": m["vendors"]}
        if name == "select_vendor":
            need("vendor_id" not in m, "Vendor is immutable during a run; clarify to restart")
            need(
                any(v["id"] == args["vendor_id"] for v in m.get("vendors", [])),
                "Discover a valid vendor first",
            )
            m["vendor_id"] = args["vendor_id"]
            return {"vendor_id": m["vendor_id"]}
        need("vendor_id" in m, "Select a vendor first")
        if name == "search_invoices":
            m["invoices"] = await self.request("GET", "/invoices", params={"vendor_id": m["vendor_id"]})
            return {"invoices": m["invoices"]}
        if name == "read_invoice":
            need("prepared" not in m, "Cannot replace a staged source; clarify to restart")
            need(
                any(i["id"] == args["invoice_id"] for i in m.get("invoices", [])), "Read only listed invoices"
            )
            m["source"] = await self.request("GET", "/invoices/" + args["invoice_id"])
            return {"source": m["source"], "trust": "untrusted invoice data"}
        if name == "prepare_invoice":
            need("source" in m, "Read an invoice first")
            require_latest(self.store, m["vendor_id"], m["source"]["id"])
            canonical = parse_invoice(m["source"])
            # Detect source edits since the original observation.
            if parse_invoice(self.store.source(m["source"]["id"])) != canonical:
                raise InvoiceError("Source changed during execution; re-run after reviewing the correction")
            m["prepared"] = canonical
            return {
                "prepared": canonical,
                "fingerprint": digest(canonical),
                "approval_required": canonical["amount_minor"] > self.settings.approval_threshold_minor,
            }
        need("prepared" in m, "Prepare and validate an invoice first")
        expected = m["prepared"]
        fingerprint = digest(expected)
        if name == "lookup_record":
            records = await self.request(
                "GET",
                "/records",
                params={"vendor_id": expected["vendor_id"], "invoice_number": expected["invoice_number"]},
            )
            if records:
                if records[0]["fingerprint"] != fingerprint:
                    raise InvoiceError(
                        "Existing invoice number has different content; human reconciliation required"
                    )
                m["record_id"] = records[0]["id"]
                m["duplicate"] = True
            m["lookup_done"] = True
            return {"existing_record": records[0] if records else None}
        need(m.get("lookup_done"), "Check duplicates first")
        if name == "request_approval":
            need(not m.get("record_id"), "Existing record needs verification, not approval")
            need(
                expected["amount_minor"] > self.settings.approval_threshold_minor,
                "This amount needs no approval",
            )
            with self.store.connect() as db:
                row = db.execute(
                    "SELECT decision FROM approvals WHERE task_id=? AND fingerprint=?",
                    (task["id"], fingerprint),
                ).fetchone()
                if row and row["decision"] == "approve":
                    m["approved"] = True
                    return {"approved": True, "fingerprint": fingerprint}
                if row and row["decision"] == "reject":
                    task["status"], task["summary"] = "rejected", "Human reviewer rejected this invoice."
                    return {"approved": False}
                db.execute(
                    "INSERT INTO approvals(task_id,fingerprint,decision,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(task_id,fingerprint) DO UPDATE SET decision='pending',reviewer='',note='', "
                    "updated_at=excluded.updated_at WHERE approvals.decision='superseded'",
                    (task["id"], fingerprint, "pending", now()),
                )
            task["status"] = "awaiting_approval"
            task["summary"] = (
                "Invoice validated. A human must approve the exact staged amount before recording."
            )
            return {"approval_required": True, "fingerprint": fingerprint, "payload": expected}
        if name == "record_invoice":
            need(not m.get("verified"), "Record already verified")
            if expected["amount_minor"] > self.settings.approval_threshold_minor:
                need(m.get("approved"), "Call request_approval; the agent cannot approve itself")
            # Persist preparation before calling an independent API which rechecks the boundary.
            self.store.save(task)
            record = await self.request(
                "POST", "/records", json={"task_id": task["id"], "invoice_id": expected["source_id"]}
            )
            m["record_id"], m["duplicate"] = record["id"], not record["created"]
            return {"record": record}
        need("record_id" in m, "Record or find an existing invoice first")
        if name == "verify_record":
            require_latest(self.store, m["vendor_id"], expected["source_id"])
            record = await self.request("GET", "/records/" + m["record_id"])
            source = await self.request("GET", "/invoices/" + expected["source_id"])
            matches = record["payload"] == expected and record["fingerprint"] == fingerprint
            if not matches or parse_invoice(source) != expected:
                raise InvoiceError(
                    "Read-back verification failed: ledger or source does not match staged fields"
                )
            m["verified"] = {
                "record_id": record["id"],
                "fingerprint": fingerprint,
                "source_sha256": expected["source_sha256"],
                "verified_at": now(),
                "fields_checked": list(expected),
                "record_url": "/company/records/" + record["id"],
                "source_url": "/company/invoices/" + expected["source_id"],
            }
            return {"evidence": m["verified"]}
        if name == "finish":
            return finish_verified_task(task)
        raise GuardError("Unsupported tool")
