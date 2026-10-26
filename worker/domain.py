"""Money, source parsing and fingerprints are code, never model-generated authority."""

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class TaskRequest(StrictModel):
    goal: str = Field(min_length=10, max_length=2000)


class Review(StrictModel):
    decision: str = Field(pattern="^(approve|reject)$")
    reviewer: str = Field(min_length=1, max_length=100)
    note: str = Field(default="", max_length=500)


class InvoiceError(ValueError):
    pass


def parse_invoice(source: dict) -> dict:
    """Accept a deliberately documented text format. Reject ambiguity instead of guessing."""
    text = source["body"]
    fields = {}
    for label in ("Invoice", "Vendor", "Amount", "Currency", "Issued", "Due"):
        matches = re.findall(rf"^{label}:\s*([^\r\n]+)$", text, re.MULTILINE)
        if len(matches) != 1:
            raise InvoiceError(f"Expected exactly one {label} field; ask for a corrected source")
        fields[label] = matches[0].strip()
    if fields["Vendor"] != source["vendor_id"]:
        raise InvoiceError("Vendor identity mismatch")
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9-]{1,49}", fields["Invoice"]):
        raise InvoiceError("Invalid invoice number")
    if fields["Currency"] != "INR":
        raise InvoiceError("Only INR invoices are supported; no currency conversion")
    try:
        if not re.fullmatch(r"[0-9]{1,9}(\.[0-9]{1,2})?", fields["Amount"]):
            raise InvoiceError("Amount must be a positive decimal with at most two decimal places")
        amount = Decimal(fields["Amount"])
        if amount <= 0:
            raise InvoiceError("Amount must be positive")
        issued, due = date.fromisoformat(fields["Issued"]), date.fromisoformat(fields["Due"])
        if due < issued:
            raise InvoiceError("Due date precedes issue date")
        if issued.isoformat() != source["issued_at"]:
            raise InvoiceError("Issue date disagrees with inbox metadata")
    except (InvalidOperation, ValueError) as exc:
        raise InvoiceError(str(exc)) from exc
    return {
        "source_id": source["id"],
        "vendor_id": source["vendor_id"],
        "invoice_number": fields["Invoice"],
        "amount_minor": int(amount * 100),
        "currency": fields["Currency"],
        "issued_at": issued.isoformat(),
        "due_date": due.isoformat(),
        "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def business_key(invoice: dict) -> tuple[str, str]:
    return invoice["vendor_id"], invoice["invoice_number"]
