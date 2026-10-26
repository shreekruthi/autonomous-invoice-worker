"""Real sandbox API. Write policy is enforced here, beyond the model/tool layer."""

import json
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import Field

from worker.config import Settings
from worker.domain import InvoiceError, StrictModel, digest, parse_invoice
from worker.store import Store, now


class WriteRequest(StrictModel):
    task_id: str
    invoice_id: str


class FaultRequest(StrictModel):
    name: str = Field(pattern="^(read_invoice|record_before|record_after|verify_corrupt)$")
    count: int = Field(ge=0, le=10)


def token_check(expected):
    def check(authorization: str = Header(default="")):
        if not secrets.compare_digest(authorization, f"Bearer {expected}"):
            raise HTTPException(401, "Invalid credential")

    return check


def latest_sources(store, vendor_id):
    rows = [r for r in store.rows("inbox") if r["vendor_id"] == vendor_id]
    return sorted(rows, key=lambda r: (r["issued_at"], r["id"]), reverse=True)


def require_latest(store, vendor_id, invoice_id):
    rows = latest_sources(store, vendor_id)
    if not rows or rows[0]["id"] != invoice_id:
        raise InvoiceError("Selected invoice is not the latest for this vendor")
    if len(rows) > 1 and rows[0]["issued_at"] == rows[1]["issued_at"]:
        raise InvoiceError("Two invoices share the latest issue date; source clarification is required")


def create_company(store: Store, settings: Settings) -> FastAPI:
    app = FastAPI(title="Sandbox Company API", dependencies=[Depends(token_check(settings.worker_token))])

    @app.get("/vendors")
    def vendors():
        return store.rows("vendors")

    @app.get("/invoices")
    def invoices(vendor_id: str):
        return [{k: v for k, v in row.items() if k != "body"} for row in latest_sources(store, vendor_id)]

    @app.get("/invoices/{invoice_id}")
    def invoice(invoice_id: str):
        if settings.enable_faults and store.consume_fault("read_invoice"):
            raise HTTPException(503, "Injected temporary inbox outage")
        try:
            return store.source(invoice_id)
        except KeyError:
            raise HTTPException(404, "Invoice not found") from None

    @app.get("/records")
    def records(vendor_id: str | None = None, invoice_number: str | None = None):
        rows = store.rows("records")
        return [
            dict(r) | {"payload": json.loads(r["payload"])}
            for r in rows
            if (vendor_id is None or r["vendor_id"] == vendor_id)
            and (invoice_number is None or r["invoice_number"] == invoice_number)
        ]

    @app.get("/records/{record_id}")
    def record(record_id: str):
        rows = [r for r in records() if r["id"] == record_id]
        if not rows:
            raise HTTPException(404, "Record not found")
        result = rows[0]
        if settings.enable_faults and store.consume_fault("verify_corrupt"):
            result["payload"]["amount_minor"] += 1
        return result

    @app.post("/records")
    def write(body: WriteRequest):
        if settings.enable_faults and store.consume_fault("record_before"):
            raise HTTPException(503, "Injected temporary ledger outage before commit")
        try:
            source = store.source(body.invoice_id)
            payload = parse_invoice(source)
            task = store.task(body.task_id)
            memory = task["memory"]
            require_latest(store, memory.get("vendor_id"), body.invoice_id)
        except (KeyError, InvoiceError) as exc:
            raise HTTPException(409, str(exc)) from exc
        fingerprint = digest(payload)
        if task["status"] != "running" or memory.get("prepared") != payload:
            raise HTTPException(409, "Task must be running with this exact validated invoice prepared")
        if not memory.get("lookup_done"):
            raise HTTPException(409, "Duplicate lookup is required before writing")
        # The business key and approval are checked in the same write transaction as insertion.
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM records WHERE vendor_id=? AND invoice_number=?",
                (payload["vendor_id"], payload["invoice_number"]),
            ).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise HTTPException(
                        409, "Business key exists with different content; manual review required"
                    )
                result = dict(existing) | {"payload": json.loads(existing["payload"]), "created": False}
            else:
                if payload["amount_minor"] > settings.approval_threshold_minor:
                    approved = db.execute(
                        "SELECT decision FROM approvals WHERE task_id=? AND fingerprint=?",
                        (body.task_id, fingerprint),
                    ).fetchone()
                    if not approved or approved["decision"] != "approve":
                        raise HTTPException(403, "Human approval is required for this exact fingerprint")
                record_id = "inv_" + fingerprint[:24]
                created_at = now()
                db.execute(
                    "INSERT INTO records VALUES(?,?,?,?,?,?)",
                    (
                        record_id,
                        payload["vendor_id"],
                        payload["invoice_number"],
                        fingerprint,
                        json.dumps(payload),
                        created_at,
                    ),
                )
                result = {
                    "id": record_id,
                    "fingerprint": fingerprint,
                    "payload": payload,
                    "created_at": created_at,
                    "created": True,
                }
        if settings.enable_faults and store.consume_fault("record_after"):
            raise HTTPException(
                503, "Injected lost response after successful commit; outcome unknown to caller"
            )
        return result

    return app
